-- Controle qualite de GOLD.md 3, porte en test dbt.
-- Si le grain (question_id, model_name, prompt_version) saute, toutes les tables
-- gold double-comptent sans lever la moindre erreur. Ce test echoue donc avant
-- que les marts ne produisent des chiffres faux.

SELECT question_id, model_name, prompt_version
FROM {{ ref('int_generations_enriched') }}
GROUP BY 1, 2, 3
HAVING count(*) > 1
