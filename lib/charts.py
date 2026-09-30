"""Fabriques de graphiques partagees entre les pages.

Une seule convention de couleur dans toute l'app : bleu si la barre depasse le
hasard, rouge sinon. La teinte porte la polarite, jamais autre chose -- ni le
survol, ni le rang, ni la magnitude.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

from lib.theme import DIFFICULTY_ORDER, palette


def barres_accuracy(df: pd.DataFrame, champ: str, titre: str,
                    trier: bool = True, hauteur: int | None = None) -> alt.LayerChart:
    """Barres d'accuracy avec le repere du hasard dans le titre d'axe.

    Le repere est dans le titre et non en etiquette flottante : pose dans le
    plot, il finit par chevaucher une barre.
    """
    p = palette()
    hasard = float(df["chance_accuracy"].mean())

    barres = (
        alt.Chart(df)
        .mark_bar(cornerRadiusEnd=4)
        .encode(
            y=alt.Y(f"{champ}:N", title=None, sort="-x" if trier else None,
                    axis=alt.Axis(labelLimit=220)),
            x=alt.X("accuracy:Q", title=f"{titre}  (hasard : {hasard:.1%})",
                    axis=alt.Axis(format=".0%", tickCount=5),
                    scale=alt.Scale(domain=[0, 1])),
            color=alt.condition(alt.datum.lift >= 0,
                                alt.value(p["bleu"]), alt.value(p["rouge"])),
            opacity=alt.condition("datum.is_reliable", alt.value(1), alt.value(0.35)),
            tooltip=[
                alt.Tooltip(f"{champ}:N", title=titre),
                alt.Tooltip("accuracy:Q", title="Accuracy", format=".1%"),
                alt.Tooltip("chance_accuracy:Q", title="Hasard", format=".1%"),
                alt.Tooltip("lift:Q", title="Lift", format="+.1%"),
                alt.Tooltip("n_questions:Q", title="Questions", format=","),
            ],
        )
    )
    repere = alt.Chart(pd.DataFrame({"x": [hasard]})).mark_rule(
        color=p["ink_soft"], strokeWidth=1.5
    ).encode(x="x:Q")
    etiquettes = barres.mark_text(align="left", dx=6, fontSize=11).encode(
        text=alt.Text("accuracy:Q", format=".0%"),
        color=alt.value(p["ink_soft"]),
        opacity=alt.value(1),
    )
    chart = barres + repere + etiquettes
    return chart.properties(height=hauteur) if hauteur else chart


def heatmap(cellules: pd.DataFrame, champ: str, grain: str) -> alt.LayerChart:
    """Matrice theme x difficulte, coloree par lift.

    Divergent ancre sur zero -- la ligne du hasard -- mais borne aux donnees
    reelles : un domaine symetrique gaspille tout un bras quand aucune cellule
    n'est sous le hasard. interpolate='lab' parce qu'en sRGB le chemin
    bleu -> gris passe par le magenta, qui se lit comme une troisieme teinte.
    """
    p = palette()
    haut = max(float(cellules["lift"].max()), 0.01)
    bas = min(float(cellules["lift"].min()), -0.01)

    cellules = cellules.copy()
    cellules["pct"] = [f"{v:.0%}" for v in cellules["accuracy"]]
    cellules["n_lbl"] = [f"n={int(v)}" for v in cellules["n_questions"]]
    ordre = (cellules.groupby(champ)["lift"].mean()
             .sort_values(ascending=False).index.tolist())

    base = alt.Chart(cellules).encode(
        x=alt.X("difficulty:N", title=None, sort=DIFFICULTY_ORDER,
                axis=alt.Axis(labelAngle=0, orient="top")),
        y=alt.Y(f"{champ}:N", title=None, sort=ordre),
    )
    # Le stroke a la couleur de la surface cree l'espace de 2px entre les cases.
    cases = base.mark_rect(stroke=p["surface"], strokeWidth=2).encode(
        color=alt.Color("lift:Q", title="Lift",
                        scale=alt.Scale(domain=[bas, 0, haut],
                                        range=[p["rouge"], p["neutre"], p["bleu"]],
                                        interpolate="lab", clamp=True),
                        legend=alt.Legend(format="+.0%", gradientLength=170)),
        opacity=alt.condition("datum.is_reliable", alt.value(1), alt.value(0.3)),
        tooltip=[
            alt.Tooltip(f"{champ}:N", title=grain),
            alt.Tooltip("difficulty:N", title="Difficulte"),
            alt.Tooltip("accuracy:Q", title="Accuracy", format=".1%"),
            alt.Tooltip("lift:Q", title="Lift", format="+.1%"),
            alt.Tooltip("n_questions:Q", title="Questions", format=","),
            alt.Tooltip("is_reliable:N", title="n >= 30"),
        ],
    )
    # Encre claire seulement sur les cases assez saturees, et jamais sur une
    # cellule estompee qui tire vers le fond de la page. Le seuil porte sur la
    # position le long du bras concerne : les deux bras ont des longueurs
    # differentes, un meme |lift| n'y donne pas la meme saturation.
    vers_pole = f"(datum.lift >= 0 ? datum.lift / {haut} : datum.lift / {bas})"
    encre = alt.condition(f"datum.is_reliable && {vers_pole} > 0.6",
                          alt.value(p["encre_case"]), alt.value(p["ink"]))
    pct = base.mark_text(dy=-6, fontSize=12).encode(
        text="pct:N", color=encre, opacity=alt.value(1))
    n = base.mark_text(dy=8, fontSize=10).encode(
        text="n_lbl:N", color=encre, opacity=alt.value(0.75))

    return (cases + pct + n).properties(
        height=60 + 34 * cellules[champ].nunique()
    )
