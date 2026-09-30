{{ config(materialized='table') }}

-- GOLD.md 4.6 -- A quoi ressemblent concretement les erreurs ?
-- Grain : une ligne par generation fausse. Seule table du lot qui n'agrege rien.
--
-- Elle repond a "montre-moi", pas a "combien" : c'est la qu'on va chercher les
-- exemples cites dans le rapport. Elle reste du gold parce qu'elle est
-- entierement denormalisee -- on la filtre par categorie ou par modele sans
-- jamais rejoindre les questions.

SELECT
    question_id,
    model_name,
    prompt_version,
    macro_domain,
    category,
    difficulty,
    type,
    question,
    correct_answer,
    ai_answer_clean,
    ai_answer_raw,
    is_unparsed,
    round(response_time, 3) AS response_time,
    generated_at
FROM {{ ref('int_generations_enriched') }}
WHERE NOT ai_correct
ORDER BY macro_domain, category, difficulty
