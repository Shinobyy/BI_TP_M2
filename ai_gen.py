"""

Table silver_questions {
  question_id string [pk]
  type string
  difficulty string
  category string
  question string
  correct_answer string
  incorrect_answer_1 string
  incorrect_answer_2 string
  incorrect_answer_3 string
}

Table silver_ai_generations {
  generation_id string [pk]
  question_id string [ref: > silver_questions.question_id, not null]
  model_name string
  prompt_version string
  ai_answer_raw string
  ai_answer_clean string
  ai_correct boolean
  response_time float
  concurrency int
  generated_at timestamp
}
"""

import os
import json
import random
import re
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, NotRequired, TypedDict

import requests


# ---------- MODELS ----------
# DEFAULT_MODEL = "lmstudio-community/llama-3.2-3b-instruct"
# DEFAULT_MODEL = "mistralai/ministral-3-3b"
# DEFAULT_MODEL = "liquid/lfm2.5-1.2b"
DEFAULT_MODEL = "google/gemma-3-270m"



# Serveur LM Studio : son API est compatible OpenAI, donc de simples appels
# HTTP suffisent, sans le SDK lmstudio.
#
# L'adresse vient de l'environnement. Elle etait codee en dur sur une machine
# du reseau local, ce qui n'a rien a faire dans un depot : ca ne marche que
# depuis ce reseau, et ca publie une adresse d'infrastructure interne. Le
# defaut vise l'installation standard de LM Studio, sur la machine locale.
#
#     export LMSTUDIO_URL="http://192.168.1.42:1234"
BASE_URL = os.environ.get("LMSTUDIO_URL", "http://localhost:1234")
# rstrip : avec ou sans slash final sur BASE_URL, on ne veut pas de "//" dans
# le chemin. LM Studio y repond 200 avec {"error":"Unexpected endpoint..."},
# donc un corps sans "choices" au lieu d'un vrai code d'erreur HTTP.
CHAT_COMPLETIONS_URL = f"{BASE_URL.rstrip('/')}/v1/chat/completions"
# La premiere question du batch peut declencher le chargement du modele en
# memoire cote serveur : on laisse de la marge.
REQUEST_TIMEOUT_SECONDS = 120
# Lettres proposees au modele. 4 suffisent : l'API renvoie au plus 3 mauvaises
# reponses, et les questions boolean n'en ont qu'une.
LETTERS = "ABCD"

# Budget de sortie. 32 tokens suffisent largement a un modele qui repond
# directement : la sortie utile tient dans {"answer":"B"}.
DEFAULT_MAX_TOKENS = 32
# Les modeles de raisonnement depensent d'abord des centaines de tokens dans
# reasoning_content, qui sont comptes dans max_tokens. Si le budget s'epuise
# avant la reponse, l'API renvoie finish_reason "length" et un content VIDE :
# la generation compte alors comme fausse sans que le modele ait eu tort.
# C'est ce qui mettait gemma-4-e4b a 0% sur 88 questions.
# Mesure sur gemma-4-e4b : 104 tokens de raisonnement pour une question de
# film, soit 110 au total. Mais a 512, 3 generations sur 28 rendaient encore un
# content vide : les questions difficiles font beaucoup plus reflechir le
# modele, d.ou 1024.
# Pour deepseek-r1, la valeur n'est pas mesuree (le modele est trop lent a
# faire tourner en boucle ici) : 2048 est un majorant confortable pour un
# distill R1. Un finish_reason "length" avec un content vide veut dire qu'il
# faut monter le budget.
MAX_TOKENS_BY_MODEL = {
    "google/gemma-4-e4b": 1024,
    "google/gemma-4-12b": 1024,
    "deepseek/deepseek-r1-0528-qwen3-8b": 2048,
}

# LM Studio renvoie des 5xx transitoires, notamment quand plusieurs requetes
# arrivent pendant le chargement JIT du modele. Sur un batch de plusieurs
# milliers de questions, une erreur ponctuelle ne doit pas tout arreter.
MAX_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 2.0
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def max_tokens_for(model_name: str) -> int:
    """Budget de sortie du modele, raisonnement compris."""
    return MAX_TOKENS_BY_MODEL.get(model_name, DEFAULT_MAX_TOKENS)


class SilverQuestion(TypedDict):
    """Une ligne de silver_questions."""

    question_id: str
    type: str
    difficulty: str
    category: str
    question: str
    correct_answer: str
    incorrect_answer_1: str
    incorrect_answer_2: NotRequired[str | None]
    incorrect_answer_3: NotRequired[str | None]


class AiGeneration(TypedDict):
    """Une ligne de silver_ai_generations."""

    generation_id: str
    question_id: str
    model_name: str
    prompt_version: str
    ai_answer_raw: str
    ai_answer_clean: str | None
    ai_correct: bool
    response_time: float
    concurrency: int
    generated_at: datetime


def build_choices(question: SilverQuestion) -> list[str]:
    """Construit la liste des choix a proposer au modele.

    L'ordre est melange, sinon la bonne reponse serait toujours en A et le
    modele aurait juste en repondant toujours la meme lettre. Le melange est
    seede sur le question_id : deux runs donnent le meme ordre, donc les
    resultats restent comparables d'une execution a l'autre.
    """
    if question["type"] == "boolean":
        return ["True", "False"]

    incorrect = [
        answer
        for answer in (
            question["incorrect_answer_1"],
            question.get("incorrect_answer_2"),
            question.get("incorrect_answer_3"),
        )
        if answer
    ]
    choices = [question["correct_answer"], *incorrect]
    random.Random(question["question_id"]).shuffle(choices)
    return choices


def build_prompt_v1(question: SilverQuestion, choices: list[str]) -> str:
    """Prompt v1 : QCM, on donne la categorie, la difficulte et les choix."""
    listed = "\n".join(
        f"{letter}. {choice}" for letter, choice in zip(LETTERS, choices)
    )
    allowed = ", ".join(LETTERS[: len(choices)])
    return (
        "You are answering a trivia question. Pick the single correct choice.\n\n"
        f"Category: {question['category']}\n"
        f"Difficulty: {question['difficulty']}\n"
        f"Type: {question['type']}\n\n"
        f"Question: {question['question']}\n\n"
        f"Choices:\n{listed}\n\n"
        f"Answer with only one letter among {allowed}."
    )


# Chaque version de prompt est enregistree ici : c'est ce que trace la colonne
# prompt_version, pour pouvoir comparer les taux de reussite entre versions.
PROMPT_BUILDERS: dict[str, Callable[[SilverQuestion, list[str]], str]] = {
    "v1": build_prompt_v1,
}


def build_answer_schema(choice_count: int) -> dict[str, Any]:
    """Schema JSON impose au modele : {"answer": "B"} et rien d'autre.

    Un 3B a tendance a broder ("The correct answer is B, because..."). L'enum
    des lettres valides evite d'avoir a rattraper ca au parsing.
    """
    return {
        "type": "object",
        "properties": {
            "answer": {"type": "string", "enum": list(LETTERS[:choice_count])},
        },
        "required": ["answer"],
        "additionalProperties": False,
    }


def parse_answer(raw: str, choices: list[str]) -> str | None:
    """Retrouve le texte de la reponse choisie. None si la sortie est illisible."""
    text = raw.strip()

    # Cas nominal : sortie structuree {"answer": "B"}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        pass
    else:
        if isinstance(parsed, dict):
            text = str(parsed.get("answer", "")).strip() # type: ignore

    letters = LETTERS[: len(choices)]
    match = re.search(rf"\b([{letters}])\b", text.upper())
    if match:
        return choices[letters.index(match.group(1))]

    # Repli : le modele a repondu le texte au lieu de la lettre
    normalized = text.strip(" .\"\'").lower()
    for choice in choices:
        if choice.lower() == normalized:
            return choice
    return None


# Une Session par thread, gardee d'une question a l'autre : sinon chaque appel
# repaie l'etablissement de la connexion TCP. On ne partage pas une Session
# unique entre threads car requests ne la garantit pas thread-safe, et son pool
# est plafonne a 10 connexions (au-dela, urllib3 les jette et les recree).
_thread_local = threading.local()


def get_session() -> requests.Session:
    """La Session HTTP du thread courant, creee au premier appel."""
    session: requests.Session | None = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        _thread_local.session = session
    return session


class LmStudioError(RuntimeError):
    """Le serveur n'a pas rendu de completion exploitable."""


def post_with_retry(payload: dict[str, Any]) -> dict[str, Any]:
    """POST vers LM Studio, en reessayant les erreurs transitoires.

    Renvoie le corps JSON deja parse, garanti porteur d'un "choices" non vide.

    LM Studio ne signale pas toujours ses rates par un code HTTP : pendant un
    changement de modele il repond 200 avec un corps sans "choices". Ce cas est
    traite comme transitoire, au meme titre qu'un 503. Le corps de la reponse
    est remonte dans l'exception finale, la ou raise_for_status() le masquait.
    """
    session = get_session()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = session.post(
                CHAT_COMPLETIONS_URL, json=payload, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt == MAX_ATTEMPTS:
                raise
            detail = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code not in RETRYABLE_STATUS:
                response.raise_for_status()
                try:
                    body: dict[str, Any] = response.json()
                except ValueError:
                    detail = f"reponse non-JSON : {response.text[:300]}"
                else:
                    if body.get("choices"):
                        return body
                    # 200 sans "choices" : corps d'erreur, ou modele en cours de
                    # chargement. C'est ce qui produisait un KeyError opaque.
                    detail = f"200 sans 'choices' : {response.text[:300]}"
            else:
                detail = f"HTTP {response.status_code} : {response.text[:300]}"

            if attempt == MAX_ATTEMPTS:
                raise LmStudioError(
                    f"{MAX_ATTEMPTS} tentatives echouees sur "
                    f"{CHAT_COMPLETIONS_URL} (modele {payload.get('model')!r}) "
                    f"-- {detail}"
                )
        # backoff exponentiel : laisse au serveur le temps de finir de charger
        # le modele avant la tentative suivante.
        time.sleep(RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1))
    raise AssertionError("boucle de reprise sortie sans retour ni exception")


def warm_up(model_name: str = DEFAULT_MODEL) -> None:
    """Force le chargement du modele avant d'ouvrir les vannes.

    LM Studio charge le modele a la premiere requete. Si N requetes arrivent
    pendant ce chargement, une partie repart en 500 : on en envoie donc une
    seule, et on attend qu'elle aboutisse.
    """
    post_with_retry(
        {
            "model": model_name,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "temperature": 0,
        }
    )


def generate_ai_answer(
    question: SilverQuestion,
    model_name: str = DEFAULT_MODEL,
    prompt_version: str = "v1",
    concurrency: int = 1,
) -> AiGeneration:
    """Pose une question a l'IA locale et renvoie une ligne silver_ai_generations.

    Thread-safe : chaque thread a sa propre Session HTTP, et le melange des
    choix est seede sur le question_id, donc sans etat partage.

    :param question: la ligne silver_questions a poser (type, choix, bonne reponse).
    :param model_name: modele servi par LM Studio.
    :param prompt_version: cle dans PROMPT_BUILDERS.
    :param concurrency: nombre de requetes en vol pendant ce run. Purement
        descriptif, mais indispensable a l'analyse : des que plusieurs requetes
        partent en parallele, response_time inclut l'attente en file et l'effet
        du batch cote serveur. Comparer des latences generees a des concurrences
        differentes n'a pas de sens, d'ou la colonne pour pouvoir filtrer.
    :return: la ligne prete a inserer, avec correction et temps de reponse.
    """
    choices = build_choices(question)
    prompt = PROMPT_BUILDERS[prompt_version](question, choices)

    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        # temperature 0 : on veut la meme reponse si on rejoue le batch
        "temperature": 0,
        "max_tokens": max_tokens_for(model_name),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "trivia_answer",
                "strict": True,
                "schema": build_answer_schema(len(choices)),
            },
        },
    }

    started_at = time.perf_counter()
    body = post_with_retry(payload)
    response_time = time.perf_counter() - started_at

    # content peut etre vide si le modele n'a rien produit : parse_answer
    # renverra None et la ligne comptera comme fausse. Sur un modele de
    # raisonnement, c'est le signe que max_tokens_for() est trop bas.
    raw = body["choices"][0]["message"]["content"] or ""
    clean = parse_answer(raw, choices)
    return {
        "generation_id": str(uuid.uuid4()),
        "question_id": question["question_id"],
        "model_name": model_name,
        "prompt_version": prompt_version,
        "ai_answer_raw": raw,
        "ai_answer_clean": clean,
        # clean vaut None quand la sortie est illisible : compte comme faux,
        # mais la colonne ai_answer_clean permet de les distinguer a l'analyse.
        "ai_correct": clean == question["correct_answer"],
        "response_time": response_time,
        "concurrency": concurrency,
        "generated_at": datetime.now(timezone.utc),
    }


if __name__ == "__main__":
    demo: SilverQuestion = {
        "question_id": "demo-1",
        "type": "multiple",
        "difficulty": "medium",
        "category": "Science: Computers",
        "question": "What does CPU stand for?",
        "correct_answer": "Central Processing Unit",
        "incorrect_answer_1": "Central Process Unit",
        "incorrect_answer_2": "Computer Personal Unit",
        "incorrect_answer_3": "Central Processor Unit",
    }
    print(build_prompt_v1(demo, build_choices(demo)))
    print("---")
    print(generate_ai_answer(demo))
