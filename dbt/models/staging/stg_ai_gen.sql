SELECT
    generation_id,
    question_id,
    model_name,
    prompt_version,
    ai_answer_raw,
    ai_answer_clean,
    ai_correct,
    response_time,
    concurrency,
    generated_at
FROM {{ source('silver', 'ai_gen') }}