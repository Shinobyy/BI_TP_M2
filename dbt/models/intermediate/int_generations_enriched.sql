-- `fact_generations` de GOLD.md 3 : l'unique jointure de la couche.
-- Grain : une ligne = une reponse d'un modele a une question avec un prompt
-- donne. Toutes les tables gold en sont des agregations, et c'est ce qui
-- garantit qu'elles ne se contredisent jamais.

SELECT
    g.*,
    q.* EXCLUDE (question_id, incorrect_answer_1, incorrect_answer_2, incorrect_answer_3),

    -- 'Entertainment: Film' -> 'Entertainment' : 24 categories, 13 macro-domaines.
    -- split_part rend la chaine entiere quand le separateur est absent.
    trim(split_part(q.category, ':', 1)) AS macro_domain,

    -- Options reellement presentees, en miroir de build_choices() dans
    -- ai_gen.py : donne l'esperance au hasard (1 / n_choices). Les questions
    -- boolean tombent d'elles-memes a 2, elles n'ont qu'un seul mauvais choix.
    -- Le test accepted_values sur n_choices casse le build si ce n'est plus vrai.
    1 + (coalesce(q.incorrect_answer_1, '') <> '')::INT
      + (coalesce(q.incorrect_answer_2, '') <> '')::INT
      + (coalesce(q.incorrect_answer_3, '') <> '')::INT AS n_choices,

    length(q.question) AS question_length,
    (g.ai_answer_clean IS NULL) AS is_unparsed

FROM {{ ref('stg_ai_gen') }} g
JOIN {{ ref('stg_questions') }} q USING (question_id)

-- Run avorte : gemma-4-e4b n'a vu que 25 des 5 246 questions. Exclu ici, donc
-- exclu partout en aval. A retirer si le run est refait.
WHERE g.model_name <> 'google/gemma-4-e4b'

-- Tient le grain : le benchmark de concurrence a repose 4 questions a
-- gemma-3-270m (a concurrency 1 puis 4). On garde la concurrence la plus basse,
-- response_time etant une metrique de tete (GOLD.md 4.5).
QUALIFY row_number() OVER (
    PARTITION BY g.question_id, g.model_name, g.prompt_version
    ORDER BY g.concurrency, g.generated_at, g.generation_id
) = 1
