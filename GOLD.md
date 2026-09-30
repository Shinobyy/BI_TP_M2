# Couche Gold — conception et implémentation

Document de conception de la couche gold du pipeline, et script SQL DuckDB associé.

- **Bronze** — `questions.csv`, brut de l'API OpenTDB (`main.py`)
- **Silver** — `questions.parquet` + `ai.parquet`, nettoyé, dédoublonné, typé (`insert_to_silver.py`)
- **Gold** — tables métier pré-calculées, dans `dbt/gold/gold.duckdb`

`db.duckdb` est l'unique base : elle porte les vues silver (qui pointent sur les parquet) et les tables gold. Pas de second fichier — sinon il faudrait un `ATTACH` pour que gold puisse lire silver, et l'outil de BI aurait deux points de connexion au lieu d'un.

> **Chemins relatifs.** `read_parquet('ai.parquet')` est résolu au moment de la requête contre le répertoire courant du processus, **pas** contre l'emplacement du `.duckdb`. La même base ouverte depuis un autre dossier échoue sur `No files found that match the pattern "ai.parquet"`. Il faut donc toujours lancer depuis la racine du projet — ou, si un outil de BI doit ouvrir le fichier lui-même, matérialiser silver en tables (`CREATE TABLE ... AS SELECT * FROM read_parquet(...)`) pour rendre la base autonome.

---

## 1. Le critère qui sépare silver de gold

Une table gold se lit **sans jointure et sans agrégation**. Si la personne qui l'ouvre doit encore écrire un `GROUP BY` ou un `JOIN`, ce n'est pas du gold, c'est du silver élargi. Une ligne de gold = une ligne du tableau ou du graphique final.

Corollaire : on ne choisit pas les tables gold en regardant les données, on les choisit en écrivant d'abord les questions métier. Le piège classique est le gros cube générique « au cas où » — c'est exactement le rôle de silver.

## 2. Architecture retenue

DuckDB lit le parquet nativement : **on ne recopie pas silver dans la base**. Le fichier `db.duckdb` contient :

1. deux **vues** pointant sur les parquet silver ;
2. une vue **`fact_generations`** — l'unique jointure de la couche, enrichie de colonnes dérivées ;
3. les tables gold **matérialisées** (`CREATE OR REPLACE TABLE`).

Matérialisées et non en vue : une vue repousserait le calcul à la lecture, alors que l'intérêt d'une couche gold est justement d'être pré-calculée.

Le build est un **full refresh** à chaque exécution. Les volumes sont de l'ordre de quelques milliers de lignes ; l'incrémental n'apporterait que des bugs, et le full refresh préserve la propriété déjà acquise en bronze → silver : le pipeline est rejouable de bout en bout.

Avantage pratique : le fichier `.duckdb` s'ouvre directement depuis Metabase, Superset, Power BI ou un notebook, sans serveur à lancer.

---

## 3. Le socle

### Contrôle qualité préalable

`insert_to_silver.py` garantit qu'un triplet (`question_id`, `model_name`, `prompt_version`) n'apparaît qu'une fois. Si cette garantie sautait, gold double-compterait **silencieusement** — la classe de bug la plus pénible à diagnostiquer sur un chiffre agrégé. Trois lignes pour s'en prémunir :

```sql
SELECT
    count(*) AS n_rows,
    count(DISTINCT concat_ws('|', question_id, model_name, prompt_version)) AS n_keys,
    count(*) = count(DISTINCT concat_ws('|', question_id, model_name, prompt_version)) AS cle_unique
FROM read_parquet('ai.parquet');
```

### Vues silver

```sql
CREATE OR REPLACE VIEW silver_questions AS
SELECT * FROM read_parquet('questions.parquet');

CREATE OR REPLACE VIEW silver_ai_generations AS
SELECT * FROM read_parquet('ai.parquet');
```

### `fact_generations` — l'unique jointure

Grain le plus fin possible : **une ligne = une réponse d'un modèle à une question avec un prompt donné**. Toutes les tables gold en sont des agrégations. C'est ce qui garantit que deux tables gold ne se contredisent jamais.

Quatre colonnes dérivées y sont calculées une fois pour toutes :

- `macro_domain` — préfixe avant `:` (`Entertainment: Film` → `Entertainment`), pour regrouper les catégories trop fines ;
- `n_choices` — nombre d'options réellement présentées, en miroir de `build_choices()` dans `ai_gen.py` ; c'est lui qui donne l'espérance au hasard (`1.0 / n_choices`) ;
- `question_length` ;
- `is_unparsed` — `ai_answer_clean IS NULL`.

```sql
CREATE OR REPLACE VIEW fact_generations AS
SELECT
    g.generation_id,
    g.question_id,
    g.model_name,
    g.prompt_version,
    g.ai_answer_raw,
    g.ai_answer_clean,
    g.ai_correct,
    g.response_time,
    g.generated_at,
    q.type,
    q.difficulty,
    q.category,
    q.question,
    q.correct_answer,
    CASE WHEN contains(q.category, ':')
         THEN trim(split_part(q.category, ':', 1))
         ELSE q.category
    END AS macro_domain,
    CASE WHEN q.type = 'boolean' THEN 2
         ELSE 1
            + (coalesce(q.incorrect_answer_1, '') <> '')::INT
            + (coalesce(q.incorrect_answer_2, '') <> '')::INT
            + (coalesce(q.incorrect_answer_3, '') <> '')::INT
    END AS n_choices,
    length(q.question) AS question_length,
    (g.ai_answer_clean IS NULL) AS is_unparsed
FROM silver_ai_generations g
JOIN silver_questions q USING (question_id);
```

---

## 4. Les six tables

### 4.1 `gold_model_performance`

**Question métier** — quel modèle répond le mieux, et de combien bat-il le hasard ?

**Grain** — une ligne par `model_name`, **à prompt fixé**. Comparer un modèle évalué en v1 à un autre évalué en v2 n'a aucun sens ; la version de prompt est une constante de la table, affichée en colonne pour que ce soit explicite.

**Ce que ça couvre** — le classement, et surtout la seule chose qui donne du sens au chiffre brut : l'écart au hasard. L'espérance aléatoire vaut ici ≈ 29 % (781 questions `boolean` à 50 %, 4 465 `multiple` à 25 %). Une accuracy de 63 % devient donc **+34 points de lift**, ce qui est une phrase de conclusion — « 63 % » tout seul n'en est pas une.

**Ce que ça ne couvre pas** — le pourquoi. Cette table dit qui gagne, jamais où ni comment.

**Piège n°1 — la pondération du corpus.** `Entertainment: Video Games` pèse 1 169 questions sur 5 246, soit **22 % du corpus**, quand `Musicals & Theatres` en pèse 36. L'accuracy globale est donc pour un cinquième un test de culture jeux vidéo. D'où deux colonnes : `accuracy_micro` (brute, pondérée par le corpus) et `accuracy_macro` (moyenne non pondérée des taux par catégorie). L'écart entre les deux est en soi un résultat sur la représentativité du jeu de données — mesuré à **+2,0 points** sur le run actuel.

**Piège n°2 — les périmètres inégaux.** L'option `--limit` de `insert_to_silver.py` prend les N premières questions restantes. Deux modèles lancés avec des limites différentes ne sont pas évalués sur le même sous-ensemble, et le classement est faussé. La table se restreint donc à **l'intersection** des questions posées à tous les modèles.

```sql
CREATE OR REPLACE TABLE gold_model_performance AS
WITH ref AS (
    -- prompt de reference : le plus utilise. Remplacer par une valeur en dur
    -- (ex. 'v1') pour figer la comparaison sur un prompt precis.
    SELECT prompt_version FROM fact_generations
    GROUP BY 1 ORDER BY count(*) DESC LIMIT 1
),
scoped AS (
    SELECT * FROM fact_generations
    WHERE prompt_version = (SELECT prompt_version FROM ref)
),
common AS (
    -- perimetre commun : questions posees a TOUS les modeles
    SELECT question_id FROM scoped GROUP BY 1
    HAVING count(DISTINCT model_name) = (SELECT count(DISTINCT model_name) FROM scoped)
),
base AS (
    SELECT * FROM scoped WHERE question_id IN (SELECT question_id FROM common)
),
macro AS (
    -- moyenne NON ponderee des taux par categorie
    SELECT model_name, avg(cat_accuracy) AS accuracy_macro
    FROM (SELECT model_name, category, avg(ai_correct::INT) AS cat_accuracy
          FROM base GROUP BY 1, 2)
    GROUP BY 1
)
SELECT
    b.model_name,
    (SELECT prompt_version FROM ref) AS prompt_version,
    count(*) AS n_questions,
    sum(b.ai_correct::INT) AS n_correct,
    round(avg(b.ai_correct::INT), 4) AS accuracy_micro,
    round(m.accuracy_macro, 4) AS accuracy_macro,
    round(avg(1.0 / b.n_choices), 4) AS chance_accuracy,
    round(avg(b.ai_correct::INT) - avg(1.0 / b.n_choices), 4) AS lift,
    round(avg((NOT b.is_unparsed)::INT), 4) AS format_compliance,
    round(median(b.response_time), 3) AS latency_p50,
    round(quantile_cont(b.response_time, 0.95), 3) AS latency_p95,
    min(b.generated_at) AS first_generated_at,
    max(b.generated_at) AS last_generated_at
FROM base b
JOIN macro m USING (model_name)
GROUP BY b.model_name, m.accuracy_macro
ORDER BY accuracy_micro DESC;
```

---

### 4.2 `gold_prompt_performance`

**Question métier** — à modèle constant, qu'apporte le passage de v1 à v2 ?

**Grain** — une ligne par couple (`model_name`, `prompt_version`).

**Ce que ça couvre** — l'effet du prompt engineering isolé de l'effet du modèle, et surtout la décomposition du gain en **deux causes distinctes** : le modèle sait mieux (`accuracy_when_parsed` monte) ou le modèle obéit mieux (`format_compliance` monte). Un prompt v2 peut gagner cinq points sans que le modèle ait rien appris, juste en cessant de broder. Confondre les deux, c'est tirer la mauvaise conclusion sur ce qui a marché.

**Ce que ça ne couvre pas** — quelles questions ont basculé. Deux prompts à 63 % peuvent réussir des questions totalement différentes ; il faut la matrice appariée v1 × v2 pour le voir (hors périmètre de ces six tables).

**État actuel** — seul `v1` existe : la table sort une ligne unique et ne dit rien. Elle n'a de valeur qu'après un second run avec un nouveau prompt. C'est d'ailleurs la raison pour laquelle `prompt_version` fait partie de la clé de dédoublonnage dans `load_done_keys()` : le pipeline est déjà prêt, il ne lui manque que la donnée.

**Détail d'implémentation** — le delta est calculé sur les questions **communes** au prompt et à la baseline, via un auto-jointure sur `question_id`, et non en soustrayant deux moyennes calculées sur des périmètres différents. Pour la baseline elle-même, le delta vaut mécaniquement 0.

```sql
CREATE OR REPLACE TABLE gold_prompt_performance AS
WITH per_pair AS (
    SELECT model_name, prompt_version,
           count(*) AS n_questions,
           sum(ai_correct::INT) AS n_correct,
           avg(ai_correct::INT) AS accuracy,
           avg(1.0 / n_choices) AS chance_accuracy,
           avg((NOT is_unparsed)::INT) AS format_compliance,
           avg(CASE WHEN NOT is_unparsed THEN ai_correct::INT END) AS accuracy_when_parsed,
           median(response_time) AS latency_p50
    FROM fact_generations GROUP BY 1, 2
),
paired AS (
    -- delta calcule sur le perimetre COMMUN avec la baseline v1
    SELECT f.model_name, f.prompt_version,
           count(*) AS n_questions_communes,
           avg(f.ai_correct::INT) - avg(b.ai_correct::INT) AS delta_accuracy,
           avg((NOT f.is_unparsed)::INT) - avg((NOT b.is_unparsed)::INT) AS delta_format
    FROM fact_generations f
    JOIN fact_generations b
      ON b.question_id = f.question_id
     AND b.model_name = f.model_name
     AND b.prompt_version = 'v1'
    GROUP BY 1, 2
)
SELECT p.model_name, p.prompt_version, p.n_questions, p.n_correct,
       round(p.accuracy, 4) AS accuracy,
       round(p.chance_accuracy, 4) AS chance_accuracy,
       round(p.accuracy - p.chance_accuracy, 4) AS lift,
       round(p.format_compliance, 4) AS format_compliance,
       round(p.accuracy_when_parsed, 4) AS accuracy_when_parsed,
       round(p.latency_p50, 3) AS latency_p50,
       pr.n_questions_communes,
       round(pr.delta_accuracy, 4) AS delta_accuracy_vs_v1,
       round(pr.delta_format, 4) AS delta_format_compliance_vs_v1
FROM per_pair p
LEFT JOIN paired pr USING (model_name, prompt_version)
ORDER BY p.model_name, p.accuracy DESC;
```

---

### 4.3 `gold_category_difficulty_matrix`

**Question métier** — sur quels domaines et à quelle difficulté le modèle décroche-t-il ?

**Grain** — une ligne par cellule (`model`, `prompt`, `category`, `difficulty`), c'est-à-dire une case de la heatmap.

**Ce que ça couvre** — la carte des forces et faiblesses, et accessoirement le test du label `difficulty` d'OpenTDB : si les colonnes `easy` / `medium` / `hard` sont plates, c'est que le label de la source ne prédit rien de la difficulté réelle pour un modèle. Résultat intéressant en soi, et gratuit.

**Piège n°1 — les cellules trop fines, chiffré.** 24 catégories × 3 difficultés = **72 cellules, dont 38 sous le seuil de 30 questions** (la plus petite en contient 6). Une case à n=6 affichée dans la même palette qu'une case à n=300 produit une conclusion inventée. D'où la colonne `is_reliable` et l'affichage systématique du `n` dans la cellule.

La version par macro-domaine (`gold_domain_difficulty_matrix`, 39 cellules dont 20 fiables) améliore les choses sans les résoudre : seuls `Entertainment` et `Science` se regroupent réellement, les autres catégories n'ont pas de préfixe. Si l'on veut un visuel dont **toutes** les cases sont défendables, il faut abandonner l'axe difficulté et se contenter des 13 macro-domaines.

**Piège n°2 — comparer des taux bruts entre cellules.** Le mix `boolean` / `multiple` varie d'une cellule à l'autre : deux cases à 60 % ne valent pas la même chose selon qu'elles sont pleines de vrai/faux (hasard à 50 %) ou de QCM à quatre options (hasard à 25 %). **Colorer la heatmap par `lift`, pas par `accuracy`**, et imprimer `accuracy` + `n` dans la case.

Illustration directe des deux pièges : trié par `lift` décroissant, le tableau fait remonter `Art / easy` en tête à 90,9 % — sur **11 questions**.

```sql
CREATE OR REPLACE TABLE gold_category_difficulty_matrix AS
SELECT
    model_name, prompt_version, macro_domain, category, difficulty,
    count(*) AS n_questions,
    sum(ai_correct::INT) AS n_correct,
    round(avg(ai_correct::INT), 4) AS accuracy,
    round(avg(1.0 / n_choices), 4) AS chance_accuracy,
    round(avg(ai_correct::INT) - avg(1.0 / n_choices), 4) AS lift,
    count(*) >= 30 AS is_reliable
FROM fact_generations
GROUP BY 1, 2, 3, 4, 5
ORDER BY model_name, prompt_version, category, difficulty;

-- Variante agregee : visuel principal, la table ci-dessus servant de detail.
CREATE OR REPLACE TABLE gold_domain_difficulty_matrix AS
SELECT
    model_name, prompt_version, macro_domain, difficulty,
    count(*) AS n_questions,
    sum(ai_correct::INT) AS n_correct,
    round(avg(ai_correct::INT), 4) AS accuracy,
    round(avg(1.0 / n_choices), 4) AS chance_accuracy,
    round(avg(ai_correct::INT) - avg(1.0 / n_choices), 4) AS lift,
    count(*) >= 30 AS is_reliable
FROM fact_generations
GROUP BY 1, 2, 3, 4
ORDER BY model_name, prompt_version, macro_domain, difficulty;
```

---

### 4.4 `gold_format_compliance`

**Question métier** — mes chiffres d'accuracy sont-ils seulement valides ?

**Grain** — une ligne par couple (`model`, `prompt`).

**Ce que ça couvre** — la robustesse de la sortie structurée, strictement séparée de la connaissance. C'est la table qui justifie d'avoir rendu `ai_answer_clean` nullable en silver plutôt que de forcer un `false` : une accuracy calculée sur 15 % de sorties illisibles ne mesure plus le modèle, elle mesure un bug de parsing.

**Sa vraie nature ici** — **0 illisible sur 3 735 générations**, soit 100 % de conformité. Ce n'est donc pas une table d'analyse mais une **table de contrôle**, et elle prend toute sa valeur maintenant, précisément parce que le mécanisme vient de changer. Le SDK `lmstudio` passait le schéma via `response_format` ; les appels HTTP le passent enveloppé dans un `json_schema` avec `strict: true`. Si cette enveloppe est mal formée, LM Studio peut l'ignorer **silencieusement** et repasser en texte libre : pas d'erreur, pas d'exception, juste une accuracy qui s'effondre sans raison apparente.

**Utilisation recommandée** — lancer un petit run après la migration vers l'API HTTP et vérifier que `pct_unparsed` reste à 0. C'est le test de non-régression de la migration.

**Limite connue** — `parse_answer()` a trois chemins (JSON valide, repli sur la lettre, repli sur le texte) mais ne dit pas lequel il a emprunté. Savoir combien de réponses ont dû être rattrapées au parsing demanderait une colonne `parse_path` en silver. Sans elle, on est limité au binaire lisible / illisible.

```sql
CREATE OR REPLACE TABLE gold_format_compliance AS
SELECT
    model_name, prompt_version,
    count(*) AS n_generations,
    sum(is_unparsed::INT) AS n_unparsed,
    round(avg(is_unparsed::INT), 4) AS pct_unparsed,
    round(avg(ai_correct::INT), 4) AS accuracy_all,
    round(avg(CASE WHEN NOT is_unparsed THEN ai_correct::INT END), 4) AS accuracy_when_parsed,
    round(avg(CASE WHEN NOT is_unparsed THEN ai_correct::INT END)
          - avg(ai_correct::INT), 4) AS gap
FROM fact_generations
GROUP BY 1, 2
ORDER BY 1, 2;
```

---

### 4.5 `gold_model_cost`

**Question métier** — combien de secondes machine pour obtenir une bonne réponse ?

**Grain** — une ligne par couple (`model`, `prompt`).

**Ce que ça couvre** — l'arbitrage qualité / vitesse ramené à un chiffre unique. Un modèle deux fois plus précis mais cinq fois plus lent y perd immédiatement. C'est la table la plus « métier » du lot : elle fusionne les deux axes en un coût unitaire.

**Piège — la moyenne est inexploitable, mesuré.** Médiane à 0,425 s, moyenne à 1,27 s : un facteur trois. **10,6 % des appels (>5 s) portent 67 % du temps total.** Deux phénomènes distincts se superposent :

1. **Un régime de démarrage franc.** En découpant l'historique en sessions (coupure à 60 s d'inactivité), on obtient 5 sessions ; les **10 premiers appels de chaque session ont une médiane de 6,06 s contre 0,42 s ensuite** — un facteur 14. C'est le chargement du modèle côté serveur.
2. **Des ralentissements ponctuels non expliqués.** Le démarrage ne concerne que ~50 appels, alors que 410 dépassent 5 s. Les 360 autres sont dispersés dans le régime établi et ne sont **pas** corrélés à la longueur de l'énoncé (70 caractères en moyenne pour les lents, 68 pour les rapides). Vraisemblablement une éviction/rechargement ou de la contention côté serveur — gold expose l'anomalie, il ne l'explique pas.

D'où deux colonnes complémentaires : `total_seconds` répond à « qu'est-ce que ce run m'a réellement coûté » (budget honnête, à conserver), `steady_state_seconds` (= médiane × n) à « à quelle vitesse ce modèle traite-t-il en régime établi » (capacité, comparable entre modèles). L'écart est de **79 minutes contre 26 minutes** : ne garder que la première rendrait toute comparaison entre un run de 50 questions et un run de 3 000 trompeuse, puisque le coût de démarrage y est amorti très différemment.

**Garde-fous** — `seconds_per_correct_answer` divise par `n_correct`, d'où le `nullif(..., 0)`. Et depuis le passage aux appels HTTP, la latence réseau est incluse : ce qui est mesuré est le **coût observé du service**, pas le coût GPU pur. Autant le nommer ainsi dans le rapport.

**Résultat négatif utile** — l'accuracy des générations lentes (62,4 %) et rapides (63,7 %) est identique. La latence ne porte donc aucune information sur la difficulté de la question : inutile de construire les tables croisant temps et justesse, la réponse est déjà là.

```sql
CREATE OR REPLACE TABLE gold_model_cost AS
SELECT
    model_name, prompt_version,
    count(*) AS n_questions,
    sum(ai_correct::INT) AS n_correct,
    -- cout reellement paye, demarrage inclus
    round(sum(response_time), 1) AS total_seconds,
    round(median(response_time), 3) AS median_seconds,
    -- cout en regime etabli, comparable entre modeles
    round(median(response_time) * count(*), 1) AS steady_state_seconds,
    round(sum(response_time) / nullif(sum(ai_correct::INT), 0), 3) AS seconds_per_correct_answer,
    round(median(response_time) * count(*) / nullif(sum(ai_correct::INT), 0), 3) AS steady_seconds_per_correct,
    round(60.0 * count(*) / nullif(sum(response_time), 0), 1) AS questions_per_minute
FROM fact_generations
GROUP BY 1, 2
ORDER BY seconds_per_correct_answer;
```

---

### 4.6 `gold_failure_review`

**Question métier** — à quoi ressemblent concrètement les erreurs ?

**Grain** — une ligne par génération fausse. C'est la seule table du lot qui n'agrège rien.

**Ce que ça couvre** — l'analyse qualitative : c'est là qu'on va chercher les exemples cités dans le rapport. Elle répond à « montre-moi », pas à « combien ». Elle reste légitimement du gold parce qu'elle est entièrement dénormalisée : on la filtre par catégorie ou par modèle sans jamais rejoindre `silver_questions`.

**Piège — le volume et sa composition.** **1 375 erreurs**, dont **0 illisible** : ce sont donc 1 375 vraies erreurs de connaissance, et la colonne `is_unparsed` restera constante à `false` tant que le format tient. Le volume est stockable mais illisible à la main, et le parcourir dans l'ordre ne montrerait que du jeu vidéo (22 % du corpus). D'où `gold_failure_sample`, échantillon **stratifié** par macro-domaine — dix erreurs par domaine, soit 128 lignes réellement lisibles.

L'échantillon est ordonné par `hash(question_id)` et non aléatoirement : deux builds successifs tirent le même échantillon, comme le mélange des choix de `build_choices()` est seedé sur `question_id`. Les exemples cités dans le rapport restent valides après un rebuild.

```sql
CREATE OR REPLACE TABLE gold_failure_review AS
SELECT
    question_id, model_name, prompt_version,
    macro_domain, category, difficulty, type,
    question, correct_answer, ai_answer_clean, ai_answer_raw,
    is_unparsed,
    round(response_time, 3) AS response_time,
    generated_at
FROM fact_generations
WHERE NOT ai_correct
ORDER BY macro_domain, category, difficulty;

-- Echantillon stratifie : 10 erreurs par macro-domaine, tirage deterministe.
CREATE OR REPLACE TABLE gold_failure_sample AS
SELECT * EXCLUDE (rn) FROM (
    SELECT *, row_number() OVER (
        PARTITION BY model_name, prompt_version, macro_domain
        ORDER BY hash(question_id)
    ) AS rn
    FROM gold_failure_review
) WHERE rn <= 10;
```

---

## 5. Ordre de lecture

Les six tables ne sont pas parallèles : elles forment une chaîne, et l'ordre compte.

| # | Table | La question à laquelle elle répond |
|---|---|---|
| 1 | `gold_format_compliance` | Mes chiffres sont-ils exploitables ? |
| 2 | `gold_model_performance` | Qui gagne, et bat-on le hasard ? |
| 3 | `gold_prompt_performance` | Le mérite revient-il au modèle ou au prompt ? |
| 4 | `gold_category_difficulty_matrix` | Où ça casse ? |
| 5 | `gold_model_cost` | Est-ce que ça vaut le temps machine ? |
| 6 | `gold_failure_review` | Concrètement, à quoi ressemble un échec ? |

`gold_format_compliance` vient en premier parce qu'elle conditionne la validité de tout le reste. Les cinq autres répondent chacune à une question qu'aucune des autres ne couvre — c'est le test qu'aucune n'est redondante.

---

## 6. Exécution

Le script `gold.sql` contient l'ensemble des requêtes ci-dessus dans l'ordre. Les chemins parquet sont **relatifs** : lancer depuis la racine du projet.

```bash
duckdb db.duckdb < gold.sql
```

Le build est idempotent : relancer écrase les tables. Comme `insert_to_silver.py` réécrit `ai.parquet` toutes les 20 générations, **rebuilder gold après la fin d'un run**, sinon les tables matérialisent un instantané partiel.

Inspection rapide :

```bash
duckdb db.duckdb -box -c "SELECT * FROM gold_model_performance"
duckdb db.duckdb -box -c "SELECT * FROM gold_model_cost"
```

---

## 7. Résultats observés

Instantané pris pendant un run en cours (`ai.parquet` était encore en cours d'écriture) — 3 735 générations, 1 modèle, 1 prompt.

| Indicateur | Valeur |
|---|---|
| Corpus | 5 246 questions uniques, 24 catégories, 13 macro-domaines |
| Couverture | 3 735 générations, soit 71 % du corpus posé |
| Accuracy micro / macro | 63,2 % / 65,2 % |
| Espérance au hasard | 28,8 % → **lift +34,4 points** |
| Conformité de format | 100 % (0 illisible) |
| Latence p50 / p95 | 0,425 s / 7,92 s |
| Coût total / régime établi | 79 min / 26 min |
| Secondes par bonne réponse | 2,00 (0,67 en régime établi) |
| Erreurs à analyser | 1 375, dont 128 dans l'échantillon stratifié |

---

## 8. Limites connues

- **Pas d'axe temps exploitable.** Silver n'a pas de `run_id`, seulement `generated_at`. On peut comparer des modèles et des prompts entre eux, pas suivre l'évolution d'un même couple dans le temps. Le découpage en sessions utilisé pour l'analyse de latence est une heuristique (coupure à 60 s d'inactivité), pas une donnée.
- **Pas de calibration.** Aucun logprob ni score de confiance n'est stocké : impossible de savoir si le modèle « hésitait ».
- **Biais de position hors d'atteinte.** Le mélange des choix est seedé sur `question_id` dans `build_choices()`, donc reproductible — mais avec le `random` de Python, impossible à rejouer en SQL. Toute analyse de biais de lettre exigerait de matérialiser `correct_letter` et `answer_letter` en silver.
- **Métriques de coût approximatives.** `response_time` est un temps mur incluant désormais la latence réseau. La réponse de l'API LM Studio contient un bloc `usage` (`prompt_tokens`, `completion_tokens`) que le pipeline ne stocke pas ; le persister en silver donnerait des métriques de coût bien plus solides que le temps mur.
