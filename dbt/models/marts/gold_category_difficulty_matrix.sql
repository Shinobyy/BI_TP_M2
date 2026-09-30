{{ config(materialized='table') }}

-- GOLD.md 4.3 -- le detail de gold_domain_difficulty_matrix, a la maille des 24
-- categories. Grain : une case de la heatmap fine.
--
-- Plus la maille est fine, plus les cellules passent sous le seuil de 30
-- questions : is_reliable devient ici une garde de premiere necessite. Une case
-- a n=6 affichee dans la meme palette qu'une case a n=300 produit une
-- conclusion inventee.

SELECT
    model_name,
    prompt_version,
    macro_domain,
    category,
    difficulty,
    {{ metriques_accuracy() }}
FROM {{ ref('int_generations_enriched') }}
GROUP BY 1, 2, 3, 4, 5
ORDER BY model_name, prompt_version, category, difficulty
