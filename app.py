"""Benchmark LLM sur OpenTDB -- rapport interactif.

Point d'entree : configuration, thème, connexion, filtres globaux, navigation.
Les pages suivent l'ordre de lecture de GOLD.md section 5 : les tables gold ne
sont pas paralleles, elles forment une chaine, et l'ordre compte.

Lancement :  .venv/bin/streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from lib.db import base_disponible, nom_court, table
from lib.theme import appliquer_theme_altair

st.set_page_config(
    page_title="Benchmark LLM",
    page_icon=":material/monitoring:",
    layout="wide",
    initial_sidebar_state="expanded",
)

if not base_disponible():
    st.error("Base gold introuvable. Lancer `dbt build` dans `dbt/`.")
    st.stop()

appliquer_theme_altair()

# Feuille de style unique, injectee via st.html (sanitise par DOMPurify) et non
# via st.markdown(unsafe_allow_html=True). Elle ne cible que des classes
# `st-key-*`, le mecanisme officiellement documente : une cle de widget ou de
# conteneur devient une classe CSS. Les `data-testid` internes de Streamlit ne
# sont pas garantis stables entre versions.
st.html("""
<style>
@keyframes bi-apparition {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: none; }
}
.st-key-kpi, .st-key-viz, .st-key-filtres {
    animation: bi-apparition 0.4s cubic-bezier(0.22, 0.61, 0.36, 1) both;
}
.st-key-viz { animation-delay: 0.08s; }

/* Cartes KPI : st.metric(border=True) pose deja la bordure, on n'ajoute que
   la reaction au survol. */
.st-key-kpi [data-testid="stMetric"] {
    transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.st-key-kpi [data-testid="stMetric"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.08);
}

/* Les graphiques sont cliquables : le curseur doit le dire. */
.st-key-viz canvas, .st-key-viz svg { cursor: pointer; }

@media (prefers-reduced-motion: reduce) {
    .st-key-kpi, .st-key-viz, .st-key-filtres,
    .st-key-kpi [data-testid="stMetric"] {
        animation: none !important;
        transition: none !important;
    }
    .st-key-kpi [data-testid="stMetric"]:hover { transform: none; }
}
</style>
""")

# --------------------------------------------------------------------------
# Filtre global. Defini dans l'entrypoint et non dans une page : les widgets
# declares dans une page sont detruits a la navigation, ceux de l'entrypoint
# survivent et gardent leur valeur d'une page a l'autre.
# --------------------------------------------------------------------------
conformite = table("gold_format_compliance")
modeles = sorted(nom_court(conformite["model_name"]))

with st.sidebar:
    st.markdown("### Modèle analysé")
    st.session_state.setdefault("modele", modeles[0])
    st.radio(
        "Modèle analysé",
        modeles,
        key="modele",
        label_visibility="collapsed",
        help="Pilote les pages « Où ça casse », « Coût » et « Échecs ». "
             "Cliquer une barre du classement le change aussi.",
    )
    st.divider()
    st.caption(
        "Couche gold dbt · 4 modèles · 20 984 générations\n\n"
        "Les pages suivent l'ordre de lecture de GOLD.md §5."
    )

pages = st.navigation({
    "Valider": [
        st.Page("views/validite.py", title="Mes chiffres sont-ils exploitables ?",
                icon=":material/fact_check:", url_path="validite", default=True),
    ],
    "Comparer": [
        st.Page("views/classement.py", title="Qui gagne ?",
                icon=":material/trophy:", url_path="classement"),
        st.Page("views/ou_ca_casse.py", title="Où ça casse ?",
                icon=":material/grid_view:", url_path="ou-ca-casse"),
        st.Page("views/cout.py", title="Le temps machine",
                icon=":material/timer:", url_path="cout"),
    ],
    "Inspecter": [
        st.Page("views/echecs.py", title="À quoi ressemble un échec ?",
                icon=":material/search:", url_path="echecs"),
        st.Page("views/prompt.py", title="Effet du prompt",
                icon=":material/edit_note:", url_path="prompt"),
    ],
})

pages.run()
