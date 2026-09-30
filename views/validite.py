"""1. Mes chiffres sont-ils exploitables ?  (GOLD.md 4.4)"""

import streamlit as st

from lib.db import nom_court, table

st.title("Mes chiffres sont-ils exploitables ?")
st.caption(
    "Table de contrôle, à lire en premier : elle conditionne la validité de tout "
    "le reste. Une accuracy calculée sur des sorties illisibles ne mesure plus le "
    "modèle, elle mesure un bug de parsing."
)

conformite = table("gold_format_compliance").copy()
conformite["modele"] = nom_court(conformite["model_name"])
cout = table("gold_model_cost")

n_gen = int(conformite["n_generations"].sum())
n_illisible = int(conformite["n_unparsed"].sum())
pct_ok = 1 - n_illisible / n_gen
ecart_max = float(conformite["gap"].abs().max())
accuracy_globale = cout["n_correct"].sum() / cout["n_questions"].sum()

# Pas de sparkline ici : un sparkline represente une sequence ordonnee, et ces
# donnees n'en ont pas. L'axe serait 4 modeles sans ordre naturel, donc la forme
# de la courbe ne dirait rien -- au mieux elle refleterait le tri choisi, au pire
# elle suggererait une tendance inexistante. GOLD.md 8 le confirme : pas d'axe
# temps exploitable (pas de run_id, et les modeles n'ont pas tourne ensemble).
#
# Le chiffre secondaire porte un ecart, pas une evolution : delta_arrow="off"
# pour ne pas dessiner une fleche de tendance, delta_color="off" pour ne pas le
# teinter en bien/mal.
hasard = float(table("gold_model_performance")["chance_accuracy"].iloc[0])

with st.container(key="kpi"):
    k1, k2, k3, k4 = st.columns(4, gap="medium")
    k1.metric("Taux de bonnes réponses", f"{accuracy_globale:.1%}",
              delta=f"{(accuracy_globale - hasard) * 100:+.1f} pts",
              delta_arrow="off", delta_color="off",
              delta_description="au-dessus du hasard",
              icon=":material/target:", border=True)
    k2.metric("Générations", f"{n_gen:,}".replace(",", " "),
              delta=f"{len(conformite)} modèles comparés",
              delta_arrow="off", delta_color="off",
              icon=":material/database:", border=True)
    k3.metric("Conformité de format", f"{pct_ok:.2%}",
              delta=f"{n_illisible} sorties illisibles",
              delta_arrow="off", delta_color="off",
              icon=":material/rule:", border=True)
    k4.metric("Écart d'accuracy maximal", f"{ecart_max:+.2%}",
              icon=":material/compare_arrows:", border=True,
              help="accuracy_when_parsed − accuracy_all, par modèle. Mesure de "
                   "combien les sorties illisibles faussent le chiffre publié.")

# Le verdict porte une icône et un libellé : la couleur ne dit jamais le sens
# toute seule.
if pct_ok >= 0.99 and ecart_max < 0.01:
    st.success(
        f"**Chiffres exploitables.** {n_illisible} sorties illisibles sur "
        f"{n_gen:,}".replace(",", " ")
        + f", et l'accuracy n'en bouge que de {ecart_max:.2%} au pire. "
        "Les pages suivantes peuvent être lues telles quelles.",
        icon=":material/check_circle:",
    )
else:
    st.warning(
        f"**Prudence.** {n_illisible} sorties illisibles sur {n_gen} "
        f"({1 - pct_ok:.2%}), écart d'accuracy jusqu'à {ecart_max:.2%}. "
        "Vérifier le parsing avant de conclure.",
        icon=":material/warning:",
    )

st.divider()
st.subheader("Conformité par modèle")
st.caption(
    "`ai_answer_clean` est *nullable* en silver plutôt que forcé à `false` : une "
    "réponse illisible n'est pas une mauvaise réponse, c'est un problème de "
    "format, qui appelle une correction différente."
)

st.dataframe(
    conformite[["modele", "n_generations", "n_unparsed", "pct_unparsed",
                "accuracy_all", "accuracy_when_parsed", "gap"]],
    hide_index=True,
    width="stretch",
    column_config={
        "modele": st.column_config.TextColumn("Modèle"),
        "n_generations": st.column_config.NumberColumn("Générations", format="%d"),
        "n_unparsed": st.column_config.NumberColumn("Illisibles", format="%d"),
        "pct_unparsed": st.column_config.NumberColumn("% illisible", format="percent"),
        "accuracy_all": st.column_config.ProgressColumn(
            "Accuracy (tout)", format="percent", min_value=0, max_value=1),
        "accuracy_when_parsed": st.column_config.ProgressColumn(
            "Accuracy (lisibles)", format="percent", min_value=0, max_value=1),
        "gap": st.column_config.NumberColumn("Écart", format="%.4f"),
    },
)
