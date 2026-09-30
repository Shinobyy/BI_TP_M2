"""5. A quoi ressemble un echec ?  (GOLD.md 4.6)"""

import streamlit as st

from lib.db import nom_court, table

focus = st.session_state["modele"]

st.title("À quoi ressemble un échec ?")
st.caption(
    "Échantillon stratifié : 10 erreurs par macro-domaine, tirage déterministe "
    "sur `hash(question_id)`. Deux builds successifs tirent le même échantillon, "
    "donc les exemples cités dans un rapport restent valides après rebuild."
)

echantillon = table("gold_failure_sample").copy()
echantillon["modele"] = nom_court(echantillon["model_name"])
du_modele = echantillon[echantillon["modele"] == focus]

toutes = table("gold_failure_review").copy()
toutes["modele"] = nom_court(toutes["model_name"])
n_total = int((toutes["modele"] == focus).sum())

with st.container(key="kpi"):
    k1, k2, k3 = st.columns(3, gap="medium")
    k1.metric("Erreurs au total", f"{n_total:,}".replace(",", " "),
              icon=":material/error:", border=True, delta_description=focus)
    k2.metric("Dans l'échantillon", f"{len(du_modele)}",
              icon=":material/filter_alt:", border=True,
              delta_description="10 par macro-domaine")
    k3.metric("Illisibles", f"{int(du_modele['is_unparsed'].sum())}",
              icon=":material/help:", border=True,
              help="Une erreur illisible est un problème de format, pas de "
                   "connaissance. Tant que ce compteur reste à zéro, ce sont "
                   "de vraies erreurs de connaissance.")

domaines = sorted(du_modele["macro_domain"].unique())
choisis = st.multiselect("Macro-domaines", domaines, default=domaines)
affiche = du_modele[du_modele["macro_domain"].isin(choisis)]

st.dataframe(
    affiche[["macro_domain", "category", "difficulty", "type", "question",
             "correct_answer", "ai_answer_clean", "response_time"]],
    hide_index=True,
    width="stretch",
    height=520,
    column_config={
        "macro_domain": st.column_config.TextColumn("Domaine"),
        "category": st.column_config.TextColumn("Catégorie"),
        "difficulty": st.column_config.TextColumn("Niveau", width="small"),
        "type": st.column_config.TextColumn("Type", width="small"),
        "question": st.column_config.TextColumn("Question", width="large"),
        "correct_answer": st.column_config.TextColumn("Bonne réponse"),
        "ai_answer_clean": st.column_config.TextColumn("Réponse du modèle"),
        "response_time": st.column_config.NumberColumn("Latence (s)", format="%.2f"),
    },
)
st.caption(f"{len(affiche)} erreurs affichées sur {len(du_modele)} dans l'échantillon "
           f"de **{focus}**.")
