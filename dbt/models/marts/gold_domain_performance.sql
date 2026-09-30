{{ config(materialized='table') }}

-- Precision par theme (GOLD.md 4.3, vue marginale).
-- Grain : une ligne par (model_name, prompt_version, macro_domain).
--
-- Reagregee depuis le grain fin, et non en moyennant les cellules de
-- gold_domain_difficulty_matrix : ce serait moyenner des moyennes calculees sur
-- des effectifs inegaux.

SELECT
    model_name,
    prompt_version,
    macro_domain,
    {{ metriques_accuracy() }},
    round(median(response_time), 3) AS median_seconds
FROM {{ ref('int_generations_enriched') }}
GROUP BY 1, 2, 3
ORDER BY model_name, prompt_version, lift DESC
