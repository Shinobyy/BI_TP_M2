{{ config(materialized='table') }}

-- GOLD.md 4.1 -- Quel modele repond le mieux, et de combien bat-il le hasard ?
-- Grain : une ligne par model_name, a prompt fixe.
--
-- accuracy_micro est ponderee par le corpus, lui-meme desequilibre
-- (Entertainment: Video Games pese 22 % des questions) ; accuracy_macro est la
-- moyenne non ponderee des taux par categorie. L'ecart entre les deux est en
-- soi un resultat sur la representativite du jeu de donnees.

WITH ref_prompt AS (
    -- le prompt le plus utilise ; mettre une valeur en dur pour figer la
    -- comparaison sur un prompt precis
    SELECT prompt_version
    FROM {{ ref('int_generations_enriched') }}
    GROUP BY 1
    ORDER BY count(*) DESC
    LIMIT 1
),

scoped AS (
    SELECT *
    FROM {{ ref('int_generations_enriched') }}
    WHERE prompt_version = (SELECT prompt_version FROM ref_prompt)
),

-- GOLD.md 4.1 restreint le classement aux questions posees a TOUS les modeles,
-- pour neutraliser les perimetres inegaux que produit l'option --limit. Garde
-- necessaire : sans elle, un modele a peine lance ramene le perimetre commun de
-- 5 246 questions a sa poignee, pour tous les autres. Inerte aujourd'hui, les
-- 4 modeles couvrant le corpus entier.
full_models AS (
    SELECT model_name
    FROM scoped
    GROUP BY 1
    HAVING count(DISTINCT question_id)
           >= 0.5 * (SELECT count(DISTINCT question_id) FROM scoped)
),

common AS (
    SELECT question_id
    FROM scoped
    WHERE model_name IN (SELECT model_name FROM full_models)
    GROUP BY 1
    HAVING count(DISTINCT model_name) = (SELECT count(*) FROM full_models)
),

base AS (
    SELECT *
    FROM scoped
    WHERE model_name IN (SELECT model_name FROM full_models)
      AND question_id IN (SELECT question_id FROM common)
),

macro_accuracy AS (
    -- moyenne NON ponderee des taux par categorie
    SELECT model_name, avg(cat_accuracy) AS accuracy_macro
    FROM (
        SELECT model_name, category, avg(ai_correct::INT) AS cat_accuracy
        FROM base
        GROUP BY 1, 2
    )
    GROUP BY 1
)

SELECT
    b.model_name,
    (SELECT prompt_version FROM ref_prompt) AS prompt_version,
    count(*) AS n_questions,
    sum(b.ai_correct::INT) AS n_correct,
    round(avg(b.ai_correct::INT), 4) AS accuracy_micro,
    -- any_value plutot qu'un GROUP BY sur une valeur deja agregee : il y a une
    -- seule accuracy_macro par modele, la jointure ne peut pas en ramener deux
    round(any_value(m.accuracy_macro), 4) AS accuracy_macro,
    round(avg(1.0 / b.n_choices), 4) AS chance_accuracy,
    round(avg(b.ai_correct::INT) - avg(1.0 / b.n_choices), 4) AS lift,
    round(avg((NOT b.is_unparsed)::INT), 4) AS format_compliance,
    round(median(b.response_time), 3) AS latency_p50,
    round(quantile_cont(b.response_time, 0.95), 3) AS latency_p95,
    min(b.generated_at) AS first_generated_at,
    max(b.generated_at) AS last_generated_at
FROM base b
JOIN macro_accuracy m USING (model_name)
GROUP BY b.model_name
ORDER BY accuracy_micro DESC
