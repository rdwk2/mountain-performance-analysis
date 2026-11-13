# Contribuer

Les règles du dépôt sont dans [`CLAUDE.md`](CLAUDE.md), que ce fichier ne recopie pas :
une tâche = une branche = une pull request, relue avec la CI verte (règle 8) ; aucune
donnée personnelle dans le dépôt (règle 1) ; une idée vue en passant va dans
[`BACKLOG.md`](BACKLOG.md) (règle 3). Ici : comment vérifier, la version de Python, les
tests qui lisent la documentation, et le garde-fou des données.

## Vérifier

`just check` enchaîne trois recettes :

| Recette | Ce qu'elle lance |
|---|---|
| `just lint` | `ruff check`, puis `ruff format --check` |
| `just types` | `mypy` strict sur `src/`, `tests/` et `scripts/` |
| `just test` | `pytest` |

`just fmt` formate et corrige ; `just dictionary` régénère
[`docs/DICTIONNAIRE_DONNEES.md`](docs/DICTIONNAIRE_DONNEES.md) ; `just figure`
régénère la figure du README. La CI
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) lance `just check` sur
une machine vierge, sous Python 3.12, sans extra, puis toute la suite, et les types, avec
tous les extras, à chaque push et à chaque pull request.

## La version de Python

Prérequis : [`uv`](https://docs.astral.sh/uv/) et `git`. Python 3.12, la version de
la CI, que uv installe au besoin : la suite n'est verte que sous 3.12 (sous 3.13 et
3.14, un test de l'écriture canonique échoue ; ligne « La suite n'est verte que sous
Python 3.12 » de [`BACKLOG.md`](BACKLOG.md)), d'où le `.python-version` du dépôt, que
uv suit en créant le `.venv`, et le `--python 3.12` de l'installation du [README](README.md).

## Les tests qui lisent la documentation

Des sorties de `mperf` sont recopiées au caractère près dans la documentation, et des
tests les rejouent :

| Test | Lit | Vérifie |
|---|---|---|
| [`test_readme_examples.py`](tests/test_readme_examples.py) | `README.md`, `docs/commandes/profile.md`, `project.md`, `match.md` | chaque bloc `bash` d'une ligne `uv run mperf …` est suivi de la sortie réelle de la commande, ou d'un extrait contigu, sur les fixtures |
| [`test_readme_backtest.py`](tests/test_readme_backtest.py), [`test_readme_sensitivity.py`](tests/test_readme_sensitivity.py) | `docs/commandes/backtest.md` | les extraits de la synthèse et de la sensibilité, sur le monde synthétique des tests |
| [`test_readme_figure.py`](tests/test_readme_figure.py) | `README.md`, `docs/img/chaine.svg` | la figure est à jour (`just figure`), et le README l'affiche avant « Pourquoi » |
| [`test_docs_links.py`](tests/test_docs_links.py) | `README.md`, `CONTRIBUTING.md`, `docs/**/*.md` hors `DICTIONNAIRE_DONNEES.md` | chaque lien relatif mène à un fichier ou à un dossier qui existe |

Une PR qui change une sortie, une option ou une phrase de ces pages les met à jour avec
elle ([`CLAUDE.md`](CLAUDE.md), « Méthode de travail »).

## Les données personnelles et le hook

Ce dépôt ne contient aucune donnée personnelle (règle 1 de [`CLAUDE.md`](CLAUDE.md),
décision [`0001`](docs/decisions/0001-separation-data-code.md)). Les données
réelles vivent hors du dépôt, dans le dossier désigné par `MPA_DATA_DIR`. Claude
Code, ouvert dans un clone du dépôt, n'y touche pas : le hook de
[`.claude/settings.json`](.claude/settings.json)
([`scripts/hooks/proteger_donnees.py`](scripts/hooks/proteger_donnees.py)) refuse ses
outils de fichiers sous ce dossier, qu'il connaît par `MPA_DATA_DIR` (l'environnement,
sinon le `.env` du clone), et ses commandes qui le nomment ou qui écrivent dans les
données ; les commandes sur les données réelles (`just ingest`, `just process`,
`just q1`, `just backtest`, `just curve`, `just ui`) sont lancées par l'humain. C'est
un garde-fou, pas une enceinte : une commande qui atteint le dossier sans le nommer n'est pas vue. Les
tests et les exemples de la documentation n'utilisent que les fixtures synthétiques de
[`tests/fixtures/`](tests/fixtures/README.md).
