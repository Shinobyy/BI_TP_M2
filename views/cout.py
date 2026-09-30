"""4. Est-ce que ca vaut le temps machine ?  (GOLD.md 4.5)"""

import altair as alt
import streamlit as st

from lib.db import nom_court, table
from lib.theme import palette

p = palette()
focus = st.session_state["modele"]

st.title("Est-ce que ça vaut le temps machine ?")
st.caption(
    "Le coût unitaire fusionne les deux axes : un modèle deux fois plus précis "
    "mais cinq fois plus lent y perd immédiatement. Échelle horizontale "
    "logarithmique, l'écart entre modèles dépasse le facteur 13."
)

cout = table("gold_model_cost").copy()
cout["modele"] = nom_court(cout["model_name"])
cout["accuracy"] = cout["n_correct"] / cout["n_questions"]
ligne = cout[cout["modele"] == focus].iloc[0]

with st.container(key="kpi"):
    k1, k2, k3 = st.columns(3, gap="medium")
    k1.metric("Secondes par bonne réponse", f"{ligne['seconds_per_correct_answer']:.2f} s",
              icon=":material/bolt:", border=True, delta_description=focus)
    k2.metric("Latence médiane", f"{ligne['median_seconds']:.2f} s",
              icon=":material/timer:", border=True,
              help="Médiane et non moyenne : un régime de démarrage et des "
                   "ralentissements ponctuels tirent la moyenne à un facteur "
                   "trois de la médiane.")
    k3.metric("Questions par minute", f"{ligne['questions_per_minute']:.1f}",
              icon=":material/speed:", border=True)

# Emphase : le modele analyse en couleur, les autres en gris de retrait. Une
# seule serie a l'ecran, donc pas de legende -- l'etiquette nomme le point.
est_focus = f"datum.modele === '{focus}'"
points = (
    alt.Chart(cout)
    .mark_point(filled=True, stroke=p["surface"], strokeWidth=2)
    .encode(
        x=alt.X("seconds_per_correct_answer:Q",
                title="Secondes par bonne réponse (échelle log)",
                scale=alt.Scale(type="log", nice=False,
                                domain=[cout["seconds_per_correct_answer"].min() * 0.75,
                                        cout["seconds_per_correct_answer"].max() * 2.6]),
                axis=alt.Axis(format=".3~s")),
        y=alt.Y("accuracy:Q", title="Accuracy", axis=alt.Axis(format=".0%"),
                scale=alt.Scale(zero=False, padding=24)),
        color=alt.condition(est_focus, alt.value(p["bleu"]), alt.value(p["muted"])),
        size=alt.condition(est_focus, alt.value(220), alt.value(120)),
        tooltip=[
            alt.Tooltip("modele:N", title="Modèle"),
            alt.Tooltip("accuracy:Q", title="Accuracy", format=".1%"),
            alt.Tooltip("seconds_per_correct_answer:Q", title="s / bonne réponse", format=".2f"),
            alt.Tooltip("median_seconds:Q", title="Latence médiane", format=".3f"),
            alt.Tooltip("total_seconds:Q", title="Coût total (s)", format=",.0f"),
            alt.Tooltip("steady_state_seconds:Q", title="Régime établi (s)", format=",.0f"),
        ],
    )
)
# Le texte porte une encre, jamais la teinte de la serie. `size` herite piloterait
# la taille de police : on le surcharge.
etiquettes = points.mark_text(align="left", dx=12, dy=-8).encode(
    text="modele:N",
    size=alt.value(12),
    color=alt.condition(est_focus, alt.value(p["ink"]), alt.value(p["muted"])),
)

with st.container(key="viz"):
    st.altair_chart((points + etiquettes).properties(height=380), width="stretch")

moins_cher = cout.loc[cout["seconds_per_correct_answer"].idxmin()]
st.caption(
    f"Meilleur rapport : **{moins_cher['modele']}**, "
    f"{moins_cher['seconds_per_correct_answer']:.2f} s par bonne réponse. "
    "`total_seconds` répond à « qu'est-ce que ce run m'a coûté », "
    "`steady_state_seconds` à « à quelle vitesse ce modèle traite en régime "
    "établi » : seule la seconde est comparable entre un run de 50 questions et "
    "un run de 5 000."
)

st.divider()
st.subheader("Coût détaillé")
st.dataframe(
    cout[["modele", "accuracy", "total_seconds", "median_seconds",
          "steady_state_seconds", "seconds_per_correct_answer", "questions_per_minute"]],
    hide_index=True,
    width="stretch",
    column_config={
        "modele": st.column_config.TextColumn("Modèle"),
        "accuracy": st.column_config.ProgressColumn(
            "Accuracy", format="percent", min_value=0, max_value=1),
        "total_seconds": st.column_config.NumberColumn("Coût total (s)", format="%.0f"),
        "median_seconds": st.column_config.NumberColumn("Médiane (s)", format="%.2f"),
        "steady_state_seconds": st.column_config.NumberColumn("Régime établi (s)", format="%.0f"),
        "seconds_per_correct_answer": st.column_config.NumberColumn("s / bonne rép.", format="%.2f"),
        "questions_per_minute": st.column_config.NumberColumn("Questions / min", format="%.1f"),
    },
)
