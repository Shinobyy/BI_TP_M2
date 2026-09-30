{{ config(materialized='table') }}

-- GOLD.md 4.3 -- visuel principal : ou ca casse, theme croise avec difficulte.
-- Grain : une case de la heatmap.
--
-- Regrouper les 24 categories en 13 macro-domaines ameliore la fiabilite des
-- cellules sans la resoudre : seuls Entertainment et Science se regroupent
-- reellement, les autres categories n'ont pas de prefixe.
--
-- A l'affichage : colorer par lift et non par accuracy -- le mix vrai/faux
-- contre QCM varie d'une case a l'autre -- et imprimer le n dans la case.

SELECT
    model_name,
    prompt_version,
    macro_domain,
    difficulty,
    {{ metriques_accuracy() }}
FROM {{ ref('int_generations_enriched') }}
GROUP BY 1, 2, 3, 4
ORDER BY model_name, prompt_version, macro_domain, difficulty
