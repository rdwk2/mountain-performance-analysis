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
