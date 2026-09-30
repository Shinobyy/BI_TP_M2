{{ config(materialized='table') }}

-- Le detail de gold_domain_performance, sur les 24 categories brutes d'OpenTDB.
-- Grain : une ligne par (model_name, prompt_version, category).

SELECT
    model_name,
    prompt_version,
    macro_domain,
    category,
    {{ metriques_accuracy() }},
    round(median(response_time), 3) AS median_seconds
FROM {{ ref('int_generations_enriched') }}
GROUP BY 1, 2, 3, 4
ORDER BY model_name, prompt_version, lift DESC
