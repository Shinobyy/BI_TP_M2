"""3. Ou ca casse ?  (GOLD.md 4.3)

Deux vues marginales -- par theme, par niveau -- puis leur croisement en detail.
"""

import pandas as pd
import streamlit as st

from lib.charts import barres_accuracy, heatmap
from lib.db import nom_court, table
from lib.theme import DIFFICULTY_ORDER

focus = st.session_state["modele"]

st.title("Où ça casse ?")
st.caption(f"Modèle analysé : **{focus}** — modifiable dans la barre latérale.")

with st.container(key="filtres"):
    grain = st.segmented_control(
        "Maille des thèmes",
        ["Macro-domaine", "Catégorie"],
        default="Macro-domaine",
        help="13 macro-domaines contre 24 catégories : plus la maille est fine, "
             "plus les cellules passent sous le seuil de fiabilité.",
    ) or "Macro-domaine"

champ = "macro_domain" if grain == "Macro-domaine" else "category"
themes = table("gold_domain_performance" if grain == "Macro-domaine"
               else "gold_category_performance").copy()
themes["modele"] = nom_court(themes["model_name"])
lignes_theme = themes[themes["modele"] == focus]

niveaux = table("gold_difficulty_performance").copy()
niveaux["modele"] = nom_court(niveaux["model_name"])
lignes_niveau = niveaux[niveaux["modele"] == focus].copy()
lignes_niveau["difficulty"] = pd.Categorical(
    lignes_niveau["difficulty"], categories=DIFFICULTY_ORDER, ordered=True)
lignes_niveau = lignes_niveau.sort_values("difficulty")

with st.container(key="viz"):
    gauche, droite = st.columns([3, 2], gap="large")

    with gauche:
        st.subheader("Par thème")
        st.altair_chart(
            barres_accuracy(lignes_theme, champ, "Taux de bonnes réponses",
                            trier=True, hauteur=30 + 26 * len(lignes_theme)),
            width="stretch",
        )

    with droite:
        st.subheader("Par niveau de difficulté")
        st.altair_chart(
            barres_accuracy(lignes_niveau, "difficulty", "Taux de bonnes réponses",
                            trier=False, hauteur=150),
            width="stretch",
        )
        if len(lignes_niveau) == 3:
            lift = lignes_niveau.set_index("difficulty")["lift"]
            # lift est une fraction ; l'ecart se lit en points de pourcentage
            ecart = float(lift.get("easy", 0) - lift.get("hard", 0)) * 100
            if ecart > 5:
                st.success(
                    f"Écart facile → difficile : **{ecart:+.1f} points** de lift. "
                    "Le label `difficulty` d'OpenTDB prédit donc bien la "
                    "difficulté réelle pour ce modèle.",
                    icon=":material/trending_down:",
                )
            else:
                st.info(
                    f"Écart facile → difficile : **{ecart:+.1f} point** de lift. "
                    "Les niveaux sont quasi plats : le label de la source ne "
                    "prédit pas grand-chose pour ce modèle.",
                    icon=":material/horizontal_rule:",
                )

st.caption(
    "La part de questions vrai/faux varie selon le niveau (hasard à 50 % contre "
    "25 % pour un QCM), donc l'écart d'accuracy brute entre niveaux exagère un "
    "peu l'écart réel. Le lift, en infobulle, corrige ce biais."
)

st.divider()
st.subheader("Thème croisé avec la difficulté")
st.caption(
    "Coloré par lift, pas par accuracy : le mix vrai/faux contre QCM varie d'une "
    "case à l'autre, donc deux cases à 60 % ne valent pas la même chose selon que "
    "le hasard y vaut 50 % ou 25 %."
)

masquer = st.toggle(
    "Masquer les cellules sous 30 questions",
    value=False,
    help="Une case à n=6 affichée dans la même palette qu'une case à n=300 "
         "produit une conclusion inventée. Par défaut elles sont estompées.",
)

matrice = table("gold_domain_difficulty_matrix" if grain == "Macro-domaine"
                else "gold_category_difficulty_matrix").copy()
matrice["modele"] = nom_court(matrice["model_name"])
cellules = matrice[matrice["modele"] == focus]
total, maigres = len(cellules), int((~cellules["is_reliable"]).sum())
if masquer:
    cellules = cellules[cellules["is_reliable"]]

if cellules.empty:
    st.warning("Aucune cellule ne passe le seuil pour ce modèle.")
else:
    st.altair_chart(heatmap(cellules, champ, grain), width="stretch")
    st.caption(
        f"{maigres} cellules sur {total} comptent moins de 30 questions"
        + (" et sont masquées." if masquer else " et sont estompées. "
           "Le n est imprimé dans chaque case : ne conclure sur aucune case "
           "sans le lire.")
    )
    with st.expander("Voir les cellules affichées"):
        st.dataframe(cellules.drop(columns=["model_name"]),
                     hide_index=True, width="stretch")
