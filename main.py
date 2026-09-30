import csv
import html
import json
import os
import time
from typing import Any, TypedDict

import requests

BASE_URL = "https://opentdb.com"
# L'API OpenTDB n'accepte qu'une requete toutes les 5 secondes par IP
RATE_LIMIT_SECONDS = 5
# Codes de reponse renvoyes par l'API dans le champ response_code
RESPONSE_CODE_SUCCESS = 0
RESPONSE_CODE_TOKEN_EMPTY = 4
RESPONSE_CODE_ERROR = -1  # notre code a nous, quand la requete HTTP echoue
CSV_HEADER = [
    "type",
    "difficulty",
    "category",
    "question",
    "correct_answer",
    "incorrect_answers",
]
_last_request_at: float | None = None


def rate_limited_get(url: str) -> requests.Response:
    global _last_request_at
    if _last_request_at is not None:
        wait = RATE_LIMIT_SECONDS - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
    response = requests.get(url)
    _last_request_at = time.monotonic()
    return response


class Question(TypedDict):
    type: str
    difficulty: str
    category: str
    question: str
    correct_answer: str
    incorrect_answers: list[str]


def get_session_token() -> str | None:
    response = rate_limited_get(f"{BASE_URL}/api_token.php?command=request")
    if response.status_code == 200:
        data: dict[str, Any] = response.json()
        return data.get("token")
    return None


def get_questions(token: str) -> tuple[int, list[Question]]:
    # Renvoie (response_code, questions) : le code 4 signale un token epuise,
    # ce qui n'est pas une erreur mais la fin normale de la session.
    response = rate_limited_get(f"{BASE_URL}/api.php?amount=50&token={token}")
    if response.status_code != 200:
        return RESPONSE_CODE_ERROR, []
    data: dict[str, Any] = response.json()
    return data.get("response_code", RESPONSE_CODE_ERROR), data.get("results", [])


def write_questions_to_file(questions: list[Question], filename: str) -> None:
    # CSV format:   type string
    #   difficulty string
    #   category string
    #   question string
    #   correct_answer string
    #   incorrect_answers string[] -> on stocke l'array en raw, en JSON
    #  Le header n'est ecrit qu'a la creation, les lots suivants sont ajoutes.
    #  Les textes de l'API sont encodes en entites HTML (&quot;, &#039;, &amp;),
    #  on les decode avant d'ecrire. csv.writer se charge de l'echappement.
    is_new_file = not os.path.exists(filename)
    with open(filename, "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        if is_new_file:
            writer.writerow(CSV_HEADER)
        for question in questions:
            writer.writerow(
                [
                    question["type"],
                    question["difficulty"],
                    html.unescape(question["category"]),
                    html.unescape(question["question"]),
                    html.unescape(question["correct_answer"]),
                    json.dumps(
                        [
                            html.unescape(answer)
                            for answer in question["incorrect_answers"]
                        ],
                        ensure_ascii=False,
                    ),
                ]
            )


def main() -> None:
    filename = "questions.csv"
    # On repart d'un fichier vide a chaque execution, sinon on ajoute les
    # questions a la suite de celles du run precedent.
    if os.path.exists(filename):
        os.remove(filename)

    token = get_session_token()
    if not token:
        print("Failed to get session token.")
        return

    total = 0
    while True:
        response_code, questions = get_questions(token)
        if response_code == RESPONSE_CODE_TOKEN_EMPTY:
            print(f"Session finished. {total} questions written to {filename}.")
            return
        if response_code != RESPONSE_CODE_SUCCESS or not questions:
            print(f"Failed to get questions (response_code={response_code}).")
            return

        write_questions_to_file(questions, filename)
        total += len(questions)
        print(f"{len(questions)} questions written to {filename} ({total} total)")

if __name__ == "__main__":
    main()
