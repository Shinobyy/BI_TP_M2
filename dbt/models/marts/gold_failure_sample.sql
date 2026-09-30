{{ config(materialized='table') }}

-- GOLD.md 4.6 -- echantillon lisible a la main : 10 erreurs par macro-domaine.
-- Le volume brut de gold_failure_review est stockable mais illisible, et le
-- parcourir dans l'ordre ne montrerait que du jeu video (22 % du corpus).
--
-- Ordonne par hash(question_id) et non aleatoirement : deux builds successifs
-- tirent le meme echantillon, comme le melange de build_choices() est seede sur
-- question_id. Les exemples cites dans le rapport restent valides apres rebuild.

SELECT * EXCLUDE (rn)
FROM (
    SELECT
        *,
        row_number() OVER (
            PARTITION BY model_name, prompt_version, macro_domain
            ORDER BY hash(question_id)
        ) AS rn
    FROM {{ ref('gold_failure_review') }}
)
WHERE rn <= 10
