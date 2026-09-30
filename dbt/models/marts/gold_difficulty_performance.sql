{{ config(materialized='table') }}

-- Precision par niveau : facile / moyen / difficile.
-- Grain : une ligne par (model_name, prompt_version, difficulty).
--
-- Teste aussi le label `difficulty` d'OpenTDB : des accuracy plates signifient
-- que le label de la source ne predit rien de la difficulte reelle.
--
-- pct_boolean est indispensable a la lecture : les questions vrai/faux ont un
-- hasard a 50 % contre 25 % pour un QCM, et elles ne sont pas reparties
-- uniformement sur les trois niveaux. Comparer les accuracy brutes entre
-- niveaux compare donc aussi deux esperances differentes -- d'ou le lift.

SELECT
    model_name,
    prompt_version,
    difficulty,
    {{ metriques_accuracy() }},
    round(avg((type = 'boolean')::INT), 4) AS pct_boolean,
    round(median(response_time), 3) AS median_seconds
FROM {{ ref('int_generations_enriched') }}
GROUP BY 1, 2, 3
ORDER BY model_name, prompt_version,
         CASE difficulty WHEN 'easy' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END
