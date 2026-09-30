{{ config(materialized='table') }}

-- GOLD.md 4.2 -- A modele constant, qu'apporte le passage de v1 a v2 ?
-- Grain : une ligne par couple (model_name, prompt_version).
--
-- L'interet est la decomposition du gain en deux causes distinctes : le modele
-- sait mieux (accuracy_when_parsed monte) ou il obeit mieux (format_compliance
-- monte). Les confondre, c'est tirer la mauvaise conclusion sur ce qui a marche.
--
-- Etat actuel : seul v1 existe, donc une ligne par modele et un delta
-- mecaniquement nul. La table ne dira quelque chose qu'apres un second prompt.

WITH per_pair AS (
    SELECT
        model_name,
        prompt_version,
        count(*) AS n_questions,
        sum(ai_correct::INT) AS n_correct,
        round(avg(ai_correct::INT), 4) AS accuracy,
        round(avg(1.0 / n_choices), 4) AS chance_accuracy,
        round(avg(ai_correct::INT) - avg(1.0 / n_choices), 4) AS lift,
        round(avg((NOT is_unparsed)::INT), 4) AS format_compliance,
        round(avg(CASE WHEN NOT is_unparsed THEN ai_correct::INT END), 4) AS accuracy_when_parsed,
        round(median(response_time), 3) AS latency_p50
    FROM {{ ref('int_generations_enriched') }}
    GROUP BY 1, 2
),

paired AS (
    -- Delta mesure sur les questions COMMUNES au prompt et a la baseline, via
    -- une auto-jointure sur question_id. Soustraire deux moyennes calculees sur
    -- des perimetres differents donnerait un chiffre qui ne veut rien dire.
    SELECT
        f.model_name,
        f.prompt_version,
        count(*) AS n_questions_communes,
        round(avg(f.ai_correct::INT) - avg(b.ai_correct::INT), 4) AS delta_accuracy_vs_v1,
        round(avg((NOT f.is_unparsed)::INT) - avg((NOT b.is_unparsed)::INT), 4)
            AS delta_format_compliance_vs_v1
    FROM {{ ref('int_generations_enriched') }} f
    JOIN {{ ref('int_generations_enriched') }} b
      ON b.question_id = f.question_id
     AND b.model_name = f.model_name
     AND b.prompt_version = 'v1'
    GROUP BY 1, 2
)

-- Les colonnes sont deja nommees et arrondies dans les CTE : inutile de les
-- reenumerer ici.
SELECT
    p.*,
    pr.n_questions_communes,
    pr.delta_accuracy_vs_v1,
    pr.delta_format_compliance_vs_v1
FROM per_pair p
LEFT JOIN paired pr USING (model_name, prompt_version)
ORDER BY p.model_name, p.accuracy DESC
