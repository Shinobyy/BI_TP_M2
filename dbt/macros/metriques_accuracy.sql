{#
    Le bloc de metriques commun aux agregations de gold.

    Centralise parce que ces six colonnes doivent rester identiques d'une table
    a l'autre : modifier `lift` ici et pas la ferait donner a deux tables gold
    deux reponses differentes a la meme question -- exactement ce que
    l'architecture a jointure unique cherche a empecher.
#}
{% macro metriques_accuracy(seuil_fiabilite=30) %}
    count(*) AS n_questions,
    sum(ai_correct::INT) AS n_correct,
    round(avg(ai_correct::INT), 4) AS accuracy,
    round(avg(1.0 / n_choices), 4) AS chance_accuracy,
    round(avg(ai_correct::INT) - avg(1.0 / n_choices), 4) AS lift,
    -- en dessous du seuil, une cellule est trop maigre pour etre coloree
    -- comme les autres (GOLD.md 4.3)
    count(*) >= {{ seuil_fiabilite }} AS is_reliable
{% endmacro %}
