-- ========== 0. Controle qualite ==========
SELECT
    count(*) AS n_rows,
    count(DISTINCT concat_ws('|', question_id, model_name, prompt_version)) AS n_keys,
    count(*) = count(DISTINCT concat_ws('|', question_id, model_name, prompt_version)) AS cle_unique
FROM read_parquet('ai.parquet');

-- ========== 1. Vues silver ==========
CREATE OR REPLACE VIEW silver_questions AS
SELECT * FROM read_parquet('questions.parquet');

CREATE OR REPLACE VIEW silver_ai_generations AS
SELECT * FROM read_parquet('ai.parquet');

-- ========== 2. Vue de jointure ==========
CREATE OR REPLACE VIEW fact_generations AS
SELECT
    g.generation_id,
    g.question_id,
    g.model_name,
    g.prompt_version,
    g.ai_answer_raw,
    g.ai_answer_clean,
    g.ai_correct,
    g.response_time,
    g.generated_at,
    q.type,
    q.difficulty,
    q.category,
    q.question,
    q.correct_answer,
    CASE WHEN contains(q.category, ':')
         THEN trim(split_part(q.category, ':', 1))
         ELSE q.category
    END AS macro_domain,
    CASE WHEN q.type = 'boolean' THEN 2
         ELSE 1
            + (coalesce(q.incorrect_answer_1, '') <> '')::INT
            + (coalesce(q.incorrect_answer_2, '') <> '')::INT
            + (coalesce(q.incorrect_answer_3, '') <> '')::INT
    END AS n_choices,
    length(q.question) AS question_length,
    (g.ai_answer_clean IS NULL) AS is_unparsed
FROM silver_ai_generations g
JOIN silver_questions q USING (question_id);

-- ========== 3. gold_model_performance ==========
CREATE OR REPLACE TABLE gold_model_performance AS
WITH ref AS (
    SELECT prompt_version FROM fact_generations
    GROUP BY 1 ORDER BY count(*) DESC LIMIT 1
),
scoped AS (
    SELECT * FROM fact_generations
    WHERE prompt_version = (SELECT prompt_version FROM ref)
),
common AS (
    SELECT question_id FROM scoped GROUP BY 1
    HAVING count(DISTINCT model_name) = (SELECT count(DISTINCT model_name) FROM scoped)
),
base AS (
    SELECT * FROM scoped WHERE question_id IN (SELECT question_id FROM common)
),
macro AS (
    SELECT model_name, avg(cat_accuracy) AS accuracy_macro
    FROM (SELECT model_name, category, avg(ai_correct::INT) AS cat_accuracy
          FROM base GROUP BY 1, 2)
    GROUP BY 1
)
SELECT
    b.model_name,
    (SELECT prompt_version FROM ref) AS prompt_version,
    count(*) AS n_questions,
    sum(b.ai_correct::INT) AS n_correct,
    round(avg(b.ai_correct::INT), 4) AS accuracy_micro,
    round(m.accuracy_macro, 4) AS accuracy_macro,
    round(avg(1.0 / b.n_choices), 4) AS chance_accuracy,
    round(avg(b.ai_correct::INT) - avg(1.0 / b.n_choices), 4) AS lift,
    round(avg((NOT b.is_unparsed)::INT), 4) AS format_compliance,
    round(median(b.response_time), 3) AS latency_p50,
    round(quantile_cont(b.response_time, 0.95), 3) AS latency_p95,
    min(b.generated_at) AS first_generated_at,
    max(b.generated_at) AS last_generated_at
FROM base b
JOIN macro m USING (model_name)
GROUP BY b.model_name, m.accuracy_macro
ORDER BY accuracy_micro DESC;

-- ========== 4. gold_prompt_performance ==========
CREATE OR REPLACE TABLE gold_prompt_performance AS
WITH per_pair AS (
    SELECT model_name, prompt_version,
           count(*) AS n_questions,
           sum(ai_correct::INT) AS n_correct,
           avg(ai_correct::INT) AS accuracy,
           avg(1.0 / n_choices) AS chance_accuracy,
           avg((NOT is_unparsed)::INT) AS format_compliance,
           avg(CASE WHEN NOT is_unparsed THEN ai_correct::INT END) AS accuracy_when_parsed,
           median(response_time) AS latency_p50
    FROM fact_generations GROUP BY 1, 2
),
paired AS (
    SELECT f.model_name, f.prompt_version,
           count(*) AS n_questions_communes,
           avg(f.ai_correct::INT) - avg(b.ai_correct::INT) AS delta_accuracy,
           avg((NOT f.is_unparsed)::INT) - avg((NOT b.is_unparsed)::INT) AS delta_format
    FROM fact_generations f
    JOIN fact_generations b
      ON b.question_id = f.question_id
     AND b.model_name = f.model_name
     AND b.prompt_version = 'v1'
    GROUP BY 1, 2
)
SELECT p.model_name, p.prompt_version, p.n_questions, p.n_correct,
       round(p.accuracy, 4) AS accuracy,
       round(p.chance_accuracy, 4) AS chance_accuracy,
       round(p.accuracy - p.chance_accuracy, 4) AS lift,
       round(p.format_compliance, 4) AS format_compliance,
       round(p.accuracy_when_parsed, 4) AS accuracy_when_parsed,
       round(p.latency_p50, 3) AS latency_p50,
       pr.n_questions_communes,
       round(pr.delta_accuracy, 4) AS delta_accuracy_vs_v1,
       round(pr.delta_format, 4) AS delta_format_compliance_vs_v1
FROM per_pair p
LEFT JOIN paired pr USING (model_name, prompt_version)
ORDER BY p.model_name, p.accuracy DESC;

-- ========== 5. gold_category_difficulty_matrix ==========
CREATE OR REPLACE TABLE gold_category_difficulty_matrix AS
SELECT
    model_name, prompt_version, macro_domain, category, difficulty,
    count(*) AS n_questions,
    sum(ai_correct::INT) AS n_correct,
    round(avg(ai_correct::INT), 4) AS accuracy,
    round(avg(1.0 / n_choices), 4) AS chance_accuracy,
    round(avg(ai_correct::INT) - avg(1.0 / n_choices), 4) AS lift,
    count(*) >= 30 AS is_reliable
FROM fact_generations
GROUP BY 1, 2, 3, 4, 5
ORDER BY model_name, prompt_version, category, difficulty;

CREATE OR REPLACE TABLE gold_domain_difficulty_matrix AS
SELECT
    model_name, prompt_version, macro_domain, difficulty,
    count(*) AS n_questions,
    sum(ai_correct::INT) AS n_correct,
    round(avg(ai_correct::INT), 4) AS accuracy,
    round(avg(1.0 / n_choices), 4) AS chance_accuracy,
    round(avg(ai_correct::INT) - avg(1.0 / n_choices), 4) AS lift,
    count(*) >= 30 AS is_reliable
FROM fact_generations
GROUP BY 1, 2, 3, 4
ORDER BY model_name, prompt_version, macro_domain, difficulty;

-- ========== 6. gold_format_compliance ==========
CREATE OR REPLACE TABLE gold_format_compliance AS
SELECT
    model_name, prompt_version,
    count(*) AS n_generations,
    sum(is_unparsed::INT) AS n_unparsed,
    round(avg(is_unparsed::INT), 4) AS pct_unparsed,
    round(avg(ai_correct::INT), 4) AS accuracy_all,
    round(avg(CASE WHEN NOT is_unparsed THEN ai_correct::INT END), 4) AS accuracy_when_parsed,
    round(avg(CASE WHEN NOT is_unparsed THEN ai_correct::INT END)
          - avg(ai_correct::INT), 4) AS gap
FROM fact_generations
GROUP BY 1, 2
ORDER BY 1, 2;

-- ========== 7. gold_model_cost ==========
CREATE OR REPLACE TABLE gold_model_cost AS
SELECT
    model_name, prompt_version,
    count(*) AS n_questions,
    sum(ai_correct::INT) AS n_correct,
    round(sum(response_time), 1) AS total_seconds,
    round(median(response_time), 3) AS median_seconds,
    round(median(response_time) * count(*), 1) AS steady_state_seconds,
    round(sum(response_time) / nullif(sum(ai_correct::INT), 0), 3) AS seconds_per_correct_answer,
    round(median(response_time) * count(*) / nullif(sum(ai_correct::INT), 0), 3) AS steady_seconds_per_correct,
    round(60.0 * count(*) / nullif(sum(response_time), 0), 1) AS questions_per_minute
FROM fact_generations
GROUP BY 1, 2
ORDER BY seconds_per_correct_answer;

-- ========== 8. gold_failure_review ==========
CREATE OR REPLACE TABLE gold_failure_review AS
SELECT
    question_id, model_name, prompt_version,
    macro_domain, category, difficulty, type,
    question, correct_answer, ai_answer_clean, ai_answer_raw,
    is_unparsed,
    round(response_time, 3) AS response_time,
    generated_at
FROM fact_generations
WHERE NOT ai_correct
ORDER BY macro_domain, category, difficulty;

CREATE OR REPLACE TABLE gold_failure_sample AS
SELECT * EXCLUDE (rn) FROM (
    SELECT *, row_number() OVER (
        PARTITION BY model_name, prompt_version, macro_domain
        ORDER BY hash(question_id)
    ) AS rn
    FROM gold_failure_review
) WHERE rn <= 10;
