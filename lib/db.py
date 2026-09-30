"""Acces a la couche gold dbt.

La connexion est mise en cache avec `cache_resource` et non rouverte a chaque
requete : c'est une ressource non serialisable, partagee par tout le process.
Les resultats passent par `cache_data`, qui ne prend que des arguments
hashables -- d'ou une fonction `table()` qui prend un nom, pas un objet
connexion.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).resolve().parent.parent / "dbt" / "gold" / "gold.duckdb"

TABLES_GOLD = [
    "gold_format_compliance",
    "gold_model_performance",
    "gold_prompt_performance",
    "gold_domain_performance",
    "gold_category_performance",
    "gold_difficulty_performance",
    "gold_domain_difficulty_matrix",
    "gold_category_difficulty_matrix",
    "gold_model_cost",
    "gold_failure_review",
    "gold_failure_sample",
]


@st.cache_resource(show_spinner=False)
def connexion() -> duckdb.DuckDBPyConnection:
    """Ouverte une fois pour toute la duree du process.

    En lecture seule : plusieurs lecteurs peuvent coexister, et l'app ne peut
    pas corrompre la base pendant qu'un `dbt build` tourne. Apres un rebuild,
    `connexion.clear()` force une reconnexion sur le nouveau fichier.
    """
    return duckdb.connect(str(DB_PATH), read_only=True)


@st.cache_data(show_spinner=False)
def table(nom: str) -> pd.DataFrame:
    """Lit une table gold. Le nom est valide contre une liste blanche : il est
    interpole dans le SQL, et une table gold n'a aucune raison d'etre nommee
    dynamiquement."""
    if nom not in TABLES_GOLD:
        raise ValueError(f"table gold inconnue : {nom}")
    return connexion().execute(f"SELECT * FROM main.{nom}").df()


def nom_court(serie: pd.Series) -> pd.Series:
    """'lmstudio-community/llama-3.2-3b-instruct' -> 'llama-3.2-3b-instruct'."""
    return serie.str.split("/").str[-1]


def base_disponible() -> bool:
    return DB_PATH.exists()
