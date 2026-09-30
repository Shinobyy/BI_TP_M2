"""2. Qui gagne, et bat-on le hasard ?  (GOLD.md 4.1)"""

import altair as alt
import pandas as pd
import streamlit as st

from lib.db import nom_court, table
from lib.theme import palette

p = palette()

st.title("Qui gagne, et bat-on le hasard ?")
st.caption(
    "Les barres portent le taux de bonnes réponses. La ligne verticale marque "
    "l'espérance du tirage au sort : l'écart entre la barre et la ligne est le "
    "lift, et c'est lui qui conclut. « 63 % » tout seul n'est pas une phrase de "
    "conclusion, « +35 points au-dessus du hasard » en est une."
)

perf = table("gold_model_performance").copy()
perf["modele"] = nom_court(perf["model_name"])
perf["etiquette"] = [f"{a:.1%}  ({l:+.1%})"
                     for a, l in zip(perf["accuracy_micro"], perf["lift"])]
hasard = float(perf["chance_accuracy"].iloc[0])

clic = alt.selection_point(name="pick", fields=["modele"], on="click", clear="dblclick")
survol = alt.selection_point(name="hover", fields=["modele"], on="pointerover",
                             empty=True, clear="pointerout")

base = alt.Chart(perf).encode(
    y=alt.Y("modele:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
    x=alt.X("accuracy_micro:Q",
            title=f"Taux de bonnes réponses  (hasard : {hasard:.1%})",
            axis=alt.Axis(format=".0%", tickCount=6),
            scale=alt.Scale(domain=[0, 1])),
)
barres = base.add_params(clic, survol).mark_bar(cornerRadiusEnd=4, height=22).encode(
    color=alt.condition(alt.datum.lift >= 0, alt.value(p["bleu"]), alt.value(p["rouge"])),
    fillOpacity=alt.condition(survol, alt.value(1), alt.value(0.72)),
    tooltip=[
        alt.Tooltip("modele:N", title="Modèle"),
        alt.Tooltip("accuracy_micro:Q", title="Accuracy micro", format=".2%"),
        alt.Tooltip("accuracy_macro:Q", title="Accuracy macro", format=".2%"),
        alt.Tooltip("chance_accuracy:Q", title="Hasard", format=".2%"),
        alt.Tooltip("lift:Q", title="Lift", format="+.2%"),
        alt.Tooltip("n_questions:Q", title="Questions", format=","),
    ],
)
repere = alt.Chart(pd.DataFrame({"x": [hasard]})).mark_rule(
    color=p["ink_soft"], strokeWidth=1.5).encode(x="x:Q")
# Les parametres restent sur les barres seules : les porter aussi sur la couche
# texte les dupliquerait dans le layer, et Altair en deduplique un en silence.
etiquettes = base.mark_text(align="left", baseline="middle", dx=6, fontSize=12).encode(
    text=alt.Text("etiquette:N"), color=alt.value(p["ink_soft"]))

with st.container(key="viz"):
    evenement = st.altair_chart(
        (barres + repere + etiquettes).properties(height=40 + 34 * len(perf)),
        width="stretch",
        on_select="rerun",
        # Sans ce filtre, `hover` compte aussi comme une selection : chaque
        # mouvement de souris relancerait l'app et effacerait le clic en cours.
        selection_mode="pick",
        key="graphe_classement",
    )

choisi = [d["modele"] for d in (evenement.selection.get("pick") or [])] \
    if evenement and evenement.selection else []
if choisi and st.session_state.get("_dernier_clic") != choisi[0]:
    st.session_state["_dernier_clic"] = choisi[0]
    st.session_state["modele"] = choisi[0]
    st.rerun()

st.caption("Cliquez une barre pour analyser ce modèle dans les autres pages "
           "(double-clic pour désélectionner).")

classe = perf.sort_values("lift", ascending=False)
meilleur, dernier = classe.iloc[0], classe.iloc[-1]
ecart_mm = (perf["accuracy_macro"] - perf["accuracy_micro"]).mean()

g, d = st.columns(2)
g.markdown(
    f"**{meilleur['modele']}** mène avec {meilleur['accuracy_micro']:.1%} "
    f"d'accuracy, soit **{meilleur['lift']:+.1%}** au-dessus du hasard."
)
if dernier["lift"] <= 0:
    d.markdown(
        f"**{dernier['modele']}** est **sous le hasard** ({dernier['lift']:+.2%}) : "
        "il ne répond pas, il tire au sort. Son accuracy brute de "
        f"{dernier['accuracy_micro']:.1%} ressemble pourtant à un résultat."
    )
else:
    d.markdown(f"Le dernier, **{dernier['modele']}**, garde "
               f"{dernier['lift']:+.1%} de lift.")

st.caption(
    f"Accuracy macro supérieure à la micro de {ecart_mm:+.1%} en moyenne : le "
    "corpus est déséquilibré (Entertainment pèse 22 % des questions), donc "
    "l'accuracy brute est en partie un test de culture jeux vidéo."
)

st.divider()
st.subheader("Classement détaillé")
st.dataframe(
    perf[["modele", "n_questions", "accuracy_micro", "accuracy_macro",
          "chance_accuracy", "lift", "format_compliance", "latency_p50", "latency_p95"]],
    hide_index=True,
    width="stretch",
    column_config={
        "modele": st.column_config.TextColumn("Modèle"),
        "n_questions": st.column_config.NumberColumn("Questions", format="%d"),
        "accuracy_micro": st.column_config.ProgressColumn(
            "Accuracy micro", format="percent", min_value=0, max_value=1),
        "accuracy_macro": st.column_config.ProgressColumn(
            "Accuracy macro", format="percent", min_value=0, max_value=1),
        "chance_accuracy": st.column_config.NumberColumn("Hasard", format="percent"),
        "lift": st.column_config.NumberColumn("Lift", format="percent"),
        "format_compliance": st.column_config.NumberColumn("Conformité", format="percent"),
        "latency_p50": st.column_config.NumberColumn("Latence p50 (s)", format="%.2f"),
        "latency_p95": st.column_config.NumberColumn("Latence p95 (s)", format="%.2f"),
    },
)
