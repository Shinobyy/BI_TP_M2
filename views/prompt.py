"""Annexe : effet du prompt.  (GOLD.md 4.2)"""

import streamlit as st

from lib.db import nom_court, table

st.title("Effet du prompt")

prompts = table("gold_prompt_performance").copy()
prompts["modele"] = nom_court(prompts["model_name"])
n_versions = prompts["prompt_version"].nunique()

st.caption(
    "Cette table décompose un gain en deux causes distinctes : le modèle sait "
    "mieux (`accuracy_when_parsed` monte) ou il obéit mieux "
    "(`format_compliance` monte). Les confondre, c'est tirer la mauvaise "
    "conclusion sur ce qui a marché."
)

if n_versions < 2:
    st.info(
        f"**Une seule version de prompt en base** (`"
        f"{prompts['prompt_version'].iloc[0]}`), donc `delta_accuracy_vs_v1` vaut "
        "0 partout et cette table ne dit rien encore.\n\n"
        "Le pipeline est prêt : `prompt_version` fait partie de la clé de "
        "dédoublonnage, il ne manque que la donnée. Relancer "
        "`insert_to_silver.py --prompt-version v2` la remplit.",
        icon=":material/info:",
    )
else:
    st.success(f"{n_versions} versions de prompt comparables.",
               icon=":material/check_circle:")

st.dataframe(
    prompts[["modele", "prompt_version", "n_questions", "accuracy", "lift",
             "format_compliance", "accuracy_when_parsed", "latency_p50",
             "n_questions_communes", "delta_accuracy_vs_v1",
             "delta_format_compliance_vs_v1"]],
    hide_index=True,
    width="stretch",
    column_config={
        "modele": st.column_config.TextColumn("Modèle"),
        "prompt_version": st.column_config.TextColumn("Prompt", width="small"),
        "n_questions": st.column_config.NumberColumn("Questions", format="%d"),
        "accuracy": st.column_config.ProgressColumn(
            "Accuracy", format="percent", min_value=0, max_value=1),
        "lift": st.column_config.NumberColumn("Lift", format="percent"),
        "format_compliance": st.column_config.NumberColumn("Conformité", format="percent"),
        "accuracy_when_parsed": st.column_config.NumberColumn("Acc. lisibles", format="percent"),
        "latency_p50": st.column_config.NumberColumn("Latence p50", format="%.2f"),
        "n_questions_communes": st.column_config.NumberColumn("Q. communes", format="%d"),
        "delta_accuracy_vs_v1": st.column_config.NumberColumn("Δ accuracy", format="percent"),
        "delta_format_compliance_vs_v1": st.column_config.NumberColumn("Δ conformité", format="percent"),
    },
)
