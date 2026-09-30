{{ config(materialized='table') }}

-- GOLD.md 4.5 -- Combien de secondes machine pour obtenir une bonne reponse ?
-- Grain : une ligne par couple (model_name, prompt_version).
--
-- La moyenne est inexploitable : un regime de demarrage (chargement du modele
-- cote serveur) et des ralentissements ponctuels la tirent a un facteur trois de
-- la mediane. D'ou deux colonnes complementaires :
--   total_seconds        -- ce que le run a reellement coute, demarrage inclus
--   steady_state_seconds -- mediane x n, la vitesse en regime etabli, seule
--                           grandeur comparable entre un run de 50 questions et
--                           un run de 3 000, ou le demarrage est amorti autrement
--
-- Depuis le passage aux appels HTTP la latence reseau est incluse : ce qui est
-- mesure est le cout observe du service, pas le cout GPU pur.

SELECT
    model_name,
    prompt_version,
    count(*) AS n_questions,
    sum(ai_correct::INT) AS n_correct,
    round(sum(response_time), 1) AS total_seconds,
    round(median(response_time), 3) AS median_seconds,
    round(median(response_time) * count(*), 1) AS steady_state_seconds,
    round(sum(response_time) / nullif(sum(ai_correct::INT), 0), 3) AS seconds_per_correct_answer,
    round(median(response_time) * count(*) / nullif(sum(ai_correct::INT), 0), 3) AS steady_seconds_per_correct,
    round(60.0 * count(*) / nullif(sum(response_time), 0), 1) AS questions_per_minute
FROM {{ ref('int_generations_enriched') }}
GROUP BY 1, 2
ORDER BY seconds_per_correct_answer
