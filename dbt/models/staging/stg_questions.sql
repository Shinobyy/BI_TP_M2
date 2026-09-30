SELECT
    question_id,
    type,
    difficulty,
    category,
    question,
    correct_answer,
    incorrect_answer_1,
    incorrect_answer_2,
    incorrect_answer_3,
FROM {{ source('silver', 'questions') }}