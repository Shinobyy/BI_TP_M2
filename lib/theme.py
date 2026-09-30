"""Palette et thème Altair, declines pour les deux modes.

Les deux jeux de couleurs sont valides par script contre leur propre surface
(validate_palette.js) : bande de clarte, plancher de chroma, separation en
vision deficiente et contraste. Un mode sombre n'est pas un mode clair inverse,
il a ses propres pas.
"""

from __future__ import annotations

import altair as alt
import streamlit as st

FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"
DIFFICULTY_ORDER = ["easy", "medium", "hard"]

CLAIR = {
    "surface": "#fcfcfb",
    "ink": "#0b0b0b",
    "ink_soft": "#52514e",
    "muted": "#898781",
    "grid": "#e1e0d9",
    "axis": "#c3c2b7",
    "bleu": "#2a78d6",
    "rouge": "#e34948",
    "neutre": "#f0efec",
    "encre_case": "#ffffff",
}

SOMBRE = {
    "surface": "#1a1a19",
    "ink": "#ffffff",
    "ink_soft": "#c3c2b7",
    "muted": "#898781",
    "grid": "#2c2c2a",
    "axis": "#383835",
    "bleu": "#3987e5",
    "rouge": "#e66767",
    "neutre": "#383835",
    "encre_case": "#ffffff",
}


def palette() -> dict[str, str]:
    """Couleurs du mode actif. st.context.theme deduit le mode du fond reel."""
    mode = getattr(getattr(st.context, "theme", None), "type", "light")
    return SOMBRE if mode == "dark" else CLAIR


def appliquer_theme_altair() -> None:
    """Chrome recessif, SANS couleur d'encre ni de fond.

    Streamlit injecte deja les couleurs de texte de son theme actif dans les
    graphiques (st.altair_chart(theme="streamlit"), le defaut). Fixer ici un
    fond ou une encre cree une seconde source de verite : si les deux ne
    basculent pas ensemble, on obtient du texte clair sur fond clair. On ne
    declare donc que la geometrie -- tailles, graisses, epaisseurs -- et on
    laisse Streamlit peindre. Le fond reste transparent : il herite de la page,
    il ne peut plus la contredire.
    """

    @alt.theme.register("bi_tp", enable=True)
    def _theme() -> dict:
        return {
            "config": {
                "background": "transparent",
                "font": FONT,
                "view": {"stroke": "transparent"},
                "axis": {
                    "gridWidth": 1,
                    "labelFontSize": 12,
                    "titleFontSize": 12,
                    "titleFontWeight": "normal",
                    "titlePadding": 10,
                },
                "legend": {
                    "labelFontSize": 12,
                    "titleFontSize": 12,
                    "titleFontWeight": "normal",
                },
            }
        }
