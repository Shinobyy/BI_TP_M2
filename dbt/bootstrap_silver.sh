#!/usr/bin/env sh
# Enregistre la couche silver (parquet) comme vues dans la base cible dbt.
# A lancer apres insert_to_silver.py, et a chaque fois que gold/gold.duckdb est recree.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(dirname "$HERE")

# git ne versionne pas les dossiers vides, et gold.duckdb est un artefact
# ignore : dans un clone neuf, ce repertoire n'existe pas encore.
mkdir -p "$HERE/gold"

duckdb "$HERE/gold/gold.duckdb" <<SQL
CREATE SCHEMA IF NOT EXISTS silver;
CREATE OR REPLACE VIEW silver.ai_gen    AS SELECT * FROM read_parquet('$ROOT/ai.parquet');
CREATE OR REPLACE VIEW silver.questions AS SELECT * FROM read_parquet('$ROOT/questions.parquet');
SQL
