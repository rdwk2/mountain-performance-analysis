# Charge .env s'il existe (MPA_DATA_DIR), sans échouer s'il est absent (CI).
set dotenv-load := true
set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

# Une commande par ligne : just s'arrête à la première qui échoue et renvoie
# son code de sortie. Ne jamais enchaîner avec `;`, ça masquerait un échec.

# Lint + types + tests. Vert = le projet va bien.
check: lint types test

# Lint et vérification du formatage (sans rien modifier)
lint:
    uv run ruff check .
    uv run ruff format --check .

# Typage strict (cibles définies dans pyproject.toml : src/ et tests/)
types:
    uv run mypy

# Tests
test:
    uv run pytest

# Formatage et corrections automatiques
fmt:
    uv run ruff check --fix .
    uv run ruff format .

# Régénère docs/DICTIONNAIRE_DONNEES.md depuis les docstrings des schémas
dictionary:
    uv run python scripts/data_dictionary.py

# Régénère docs/img/chaine.svg, la figure du README (données synthétiques)
figure:
    uv run python scripts/readme_figure.py

# Backtest enregistré des cinq modèles et rapport D15 (0010 D9, D14, D15) : le manifeste
# MPA_DATA_DIR/reference/manifeste.json et la courbe <curve> du même dossier ;
# registre et rapport sous MPA_DATA_DIR. Exemple : just backtest courbe.csv ; les options
# suivent la courbe, dont --sensitivity, la sensibilité de 0010 D13 (M4d-3).
backtest curve *options:
    uv run mperf backtest "{{env_var('MPA_DATA_DIR')}}/reference/manifeste.json" --curve "{{env_var('MPA_DATA_DIR')}}/reference/{{curve}}" {{options}}

# Ingestion des exports Garmin (AN1-1, AN2-0, docs/decisions/0013) : MPA_DATA_DIR/raw/garmin → MPA_DATA_DIR/interim/activities,
# avec l'extra ingest (fitdecode).
ingest:
    uv run --extra ingest mperf ingest

# Régénère interim/ puis processed/ depuis raw/ (AN1-2b, docs/decisions/0014) :
# l'ingestion (extra ingest), puis les tables de processed/ (mperf tables, extra analyse).
process:
    uv run --extra ingest mperf ingest
    uv run --extra analyse mperf tables

# La figure de Q1 (AN1-2c, docs/decisions/0015) : MPA_DATA_DIR/processed →
# MPA_DATA_DIR/resultats/Q1/<date>_<empreinte>/, avec l'extra analyse (pyarrow, plotly).
q1:
    uv run --extra analyse mperf q1

# Une courbe allure↔pente personnelle (M6b) : MPA_DATA_DIR/interim →
# MPA_DATA_DIR/reference/<name>.csv et son compagnon, jamais réécrits. Exemple :
# just curve saison --from 2000-01-01 --to 2000-12-31 --athlete x ; les options suivent
# le nom (mperf curve --help).
curve name *options:
    uv run mperf curve "{{name}}" {{options}}

# L'interface (M5, docs/decisions/0016) : une appli Streamlit locale, sur MPA_DATA_DIR
# (routes/, sorties/, reference/), avec l'extra tableau ; à ouvrir sur
# http://localhost:8501. Serveur local seulement, sans télémétrie :
# .streamlit/config.toml, lu depuis la racine, où just lance ses recettes.
ui:
    uv run --extra tableau streamlit run src/mountain_perf/ui/app.py
