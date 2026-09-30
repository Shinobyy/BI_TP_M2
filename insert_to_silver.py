"""Bronze -> Silver : lit questions.csv, remplit silver_questions et
silver_ai_generations en parquet.

Le script est rejouable : on ne repose au modele que les questions qui n'ont
pas deja une generation pour le couple (model_name, prompt_version).
"""

import argparse
import csv
import hashlib
import json
import os
import sys
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any, cast

import pyarrow as pa
import pyarrow.parquet as pq

from ai_gen import (
    DEFAULT_MODEL,
    AiGeneration,
    SilverQuestion,
    generate_ai_answer,
    max_tokens_for,
    warm_up,
)

CSV_FILE_PATH = "questions.csv"
PARQUET_QUESTIONS_PATH = "questions.parquet"
PARQUET_AI_PATH = "ai.parquet"
# On reecrit le parquet toutes les FLUSH_EVERY generations : si le script
# plante au milieu d'un batch, on ne reperd pas tout le travail du modele.
FLUSH_EVERY = 20
# Requetes en vol par defaut. Le decodage d'un LLM est limite par la bande
# passante memoire, pas par le calcul : a chaque pas de token le serveur relit
# les poids du modele, et il les relit une seule fois pour tout le batch. Poser
# N questions en parallele coute donc bien moins que N fois une question seule.
DEFAULT_WORKERS = 8

QUESTIONS_SCHEMA = pa.schema(
    [
        ("question_id", pa.string()),
        ("type", pa.string()),
        ("difficulty", pa.string()),
        ("category", pa.string()),
        ("question", pa.string()),
        ("correct_answer", pa.string()),
        ("incorrect_answer_1", pa.string()),
        ("incorrect_answer_2", pa.string()),
        ("incorrect_answer_3", pa.string()),
    ]
)

AI_SCHEMA = pa.schema(
    [
        ("generation_id", pa.string()),
        ("question_id", pa.string()),
        ("model_name", pa.string()),
        ("prompt_version", pa.string()),
        ("ai_answer_raw", pa.string()),
        ("ai_answer_clean", pa.string()),
        ("ai_correct", pa.bool_()),
        ("response_time", pa.float64()),
        ("concurrency", pa.int32()),
        ("generated_at", pa.timestamp("us", tz="UTC")),
    ]
)


def make_question_id(question_text: str) -> str:
    """Id stable : la meme question garde le meme id d'un run a l'autre.

    C'est ce qui permet de rejouer le script sans reposer les questions, y
    compris quand main.py a rappele l'API et regenere un questions.csv.
    """
    return hashlib.sha1(question_text.encode("utf-8")).hexdigest()[:16]


def read_csv(file_path: str) -> list[SilverQuestion]:
    """Lit le CSV bronze et le met a la forme de silver_questions.

    Les doublons (une meme question revenue dans plusieurs appels API) sont
    ecrases par question_id, sinon on la poserait plusieurs fois au modele.
    """
    with open(file_path, newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))

    questions: dict[str, SilverQuestion] = {}
    for row in rows:
        # la colonne incorrect_answers est un array JSON, cf. main.py
        incorrect = json.loads(row["incorrect_answers"])
        question_id = make_question_id(row["question"])
        questions[question_id] = {
            "question_id": question_id,
            "type": row["type"],
            "difficulty": row["difficulty"],
            "category": row["category"],
            "question": row["question"],
            "correct_answer": row["correct_answer"],
            # les questions boolean n'ont qu'une mauvaise reponse
            "incorrect_answer_1": incorrect[0] if len(incorrect) > 0 else "",
            "incorrect_answer_2": incorrect[1] if len(incorrect) > 1 else None,
            "incorrect_answer_3": incorrect[2] if len(incorrect) > 2 else None,
        }
    return list(questions.values())


def write_questions_parquet(questions: list[SilverQuestion]) -> None:
    table = pa.Table.from_pylist(
        cast(list[dict[str, Any]], questions), schema=QUESTIONS_SCHEMA
    )
    pq.write_table(table, PARQUET_QUESTIONS_PATH)  # pyright: ignore[reportUnknownMemberType]


def load_done_keys() -> set[tuple[str, str, str]]:
    """Les (question_id, model_name, prompt_version) deja generes.

    La version de prompt fait partie de la cle : changer de prompt doit
    reposer les questions, c'est justement ce qu'on veut comparer.
    """
    if not os.path.exists(PARQUET_AI_PATH):
        return set()
    table = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        PARQUET_AI_PATH, columns=["question_id", "model_name", "prompt_version"]
    )
    # to_pylist() est type list[Any | None] par les stubs : on affirme le type
    # reel, sinon la cle de dedoublonnage remonte en tuple[Any | None, ...].
    return set(
        zip(
            cast(list[str], table["question_id"].to_pylist()),
            cast(list[str], table["model_name"].to_pylist()),
            cast(list[str], table["prompt_version"].to_pylist()),
        )
    )


def append_generations(generations: list[AiGeneration]) -> None:
    """Ajoute les nouvelles lignes a ai.parquet.

    Un parquet ne s'ouvre pas en append : on relit, on concatene, et on
    remplace le fichier d'un coup avec os.replace pour ne jamais laisser un
    ai.parquet a moitie ecrit si ca coupe pendant l'ecriture.
    """
    if not generations:
        return

    table = pa.Table.from_pylist(
        cast(list[dict[str, Any]], generations), schema=AI_SCHEMA
    )
    if os.path.exists(PARQUET_AI_PATH):
        existing = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
            PARQUET_AI_PATH, schema=AI_SCHEMA
        )
        table = pa.concat_tables([existing, table])

    tmp_path = f"{PARQUET_AI_PATH}.tmp"
    pq.write_table(table, tmp_path)  # pyright: ignore[reportUnknownMemberType]
    os.replace(tmp_path, PARQUET_AI_PATH)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt-version", default="v1")
    parser.add_argument(
        "--limit", type=int, help="ne poser que les N premieres questions restantes"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=(
            "questions posees en parallele "
            f"(defaut {DEFAULT_WORKERS}, 1 pour mesurer des latences propres)"
        ),
    )
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers doit valoir au moins 1")

    questions = read_csv(CSV_FILE_PATH)
    write_questions_parquet(questions)
    print(f"{len(questions)} questions uniques -> {PARQUET_QUESTIONS_PATH}")

    done = load_done_keys()
    todo = [
        question
        for question in questions
        if (question["question_id"], args.model, args.prompt_version) not in done
    ]
    print(
        f"{len(questions) - len(todo)} deja generees pour "
        f"({args.model}, {args.prompt_version}), {len(todo)} a poser"
    )
    if args.limit is not None:
        todo = todo[: args.limit]

    if not todo:
        return

    pending: list[AiGeneration] = []
    correct = 0
    done_count = 0
    stopped: BaseException | None = None
    print(
        f"{args.workers} question(s) en parallele, "
        f"max_tokens={max_tokens_for(args.model)}"
    )

    # Une requete seule avant le batch : LM Studio charge le modele a la
    # premiere demande, et les requetes qui arrivent pendant ce chargement
    # repartent en 500. On attend donc que le modele soit chaud.
    print("chargement du modele...", flush=True)
    warm_up(args.model)

    # Tout est soumis d'un coup : le pool n'en garde que args.workers en vol,
    # le reste attend dans sa file et reste annulable si on coupe.
    executor = ThreadPoolExecutor(max_workers=args.workers)
    futures: dict[Future[AiGeneration], SilverQuestion] = {
        executor.submit(
            generate_ai_answer,
            question,
            args.model,
            args.prompt_version,
            args.workers,
        ): question
        for question in todo
    }
    try:
        # as_completed rend les reponses dans l'ordre d'arrivee, pas dans celui
        # de todo : le compteur affiche compte les generations terminees.
        for future in as_completed(futures):
            question = futures[future]
            generation = future.result()
            pending.append(generation)
            done_count += 1
            if generation["ai_correct"]:
                correct += 1

            status = "OK" if generation["ai_correct"] else "KO"
            # affichage seulement : le parquet garde l'enonce complet
            label = question["question"]
            print(
                f"[{done_count}/{len(todo)}] {status} "
                f"{generation['response_time']:5.2f}s {label}"
            )
            if len(pending) >= FLUSH_EVERY:
                append_generations(pending)
                pending = []
    except (KeyboardInterrupt, Exception) as exc:
        # On capture au lieu de laisser remonter : le finally doit pouvoir
        # sauvegarder avant que le processus ne parte.
        stopped = exc
    finally:
        # Meme sur Ctrl+C ou erreur du modele, on garde ce qui est deja genere.
        # Les questions encore en file sont annulees ; celles deja parties
        # finissent dans le vide et seront reposees au prochain run, puisque
        # seules les generations ecrites dans le parquet comptent comme faites.
        for future in futures:
            future.cancel()
        append_generations(pending)
        executor.shutdown(wait=False)

    print(f"{correct}/{done_count} bonnes reponses -> {PARQUET_AI_PATH}")

    if stopped is not None:
        if isinstance(stopped, KeyboardInterrupt):
            print("Interrompu. Relance la meme commande pour reprendre.")
            code = 130
        else:
            print(f"Arret sur {type(stopped).__name__}: {stopped}")
            print("Relance la meme commande pour reprendre.")
            code = 1
        # Les requetes deja parties tiennent leur thread jusqu'au timeout HTTP
        # (REQUEST_TIMEOUT_SECONDS), et l'atexit de concurrent.futures rejoint
        # ces threads avant de rendre la main : sans ca, le script paraissait
        # fige apres un Ctrl+C. Tout est deja ecrit, on sort sans les attendre.
        sys.stdout.flush()
        os._exit(code)


if __name__ == "__main__":
    main()
