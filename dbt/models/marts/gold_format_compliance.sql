{{ config(materialized='table') }}

-- GOLD.md 4.4 -- Mes chiffres d'accuracy sont-ils seulement valides ?
-- Table de controle, a lire en premier (GOLD.md 5) : elle conditionne la
-- validite de tout le reste. Separe strictement l'echec de format de l'echec de
-- connaissance, ce qui justifie d'avoir rendu ai_answer_clean nullable en silver.

SELECT
    model_name,
    prompt_version,
    count(*) AS n_generations,
    sum(is_unparsed::INT) AS n_unparsed,
    round(avg(is_unparsed::INT), 4) AS pct_unparsed,
    round(avg(ai_correct::INT), 4) AS accuracy_all,
    round(avg(CASE WHEN NOT is_unparsed THEN ai_correct::INT END), 4) AS accuracy_when_parsed,
    round(avg(CASE WHEN NOT is_unparsed THEN ai_correct::INT END)
          - avg(ai_correct::INT), 4) AS gap
FROM {{ ref('int_generations_enriched') }}
GROUP BY 1, 2
ORDER BY 1, 2
