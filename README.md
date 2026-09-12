# mountain-performance-analysis

Analyse de données de sport de montagne et modélisation de la performance.

**Outil actuel** : projection des temps de passage sur un tracé GPX, à partir d'une
courbe allure↔pente construite sur les données d'entraînement de l'athlète, et
validée contre des performances réelles.

> 🚧 En construction. Voir [`docs/ROADMAP.md`](docs/ROADMAP.md) pour l'état d'avancement.

---

## Pourquoi

Les estimateurs de temps de course classiques appliquent une règle universelle
(Naismith, Tobler) qui ignore à la fois le coureur et la forme de la course. Deux
parcours de même distance et même dénivelé ne se courent pas pareil, et deux
coureurs ne s'y dégradent pas pareil.

L'approche ici : partir de la courbe vitesse = f(pente) **mesurée** sur les sorties
du coureur, puis modéliser la dégradation au fil de la course — en particulier
l'idée que le coût d'une descente dépend de sa profondeur et du moment où elle
arrive, pas seulement de son dénivelé.

Chaque effet ajouté au modèle est validé contre des temps de passage réels.

---

## Installation

Prérequis : [`uv`](https://docs.astral.sh/uv/) et `git`. Python 3.12 est installé
par uv si besoin.

```bash
git clone git@github.com:rdwk2/mountain-performance-analysis.git
cd mountain-performance-analysis
uv tool install rust-just   # installe la commande `just`
uv sync                     # crée .venv et installe les dépendances de dev
cp .env.example .env        # puis renseigne MPA_DATA_DIR dans .env
just check                  # lint + types + tests : doit être vert
```

`MPA_DATA_DIR` pointe vers le dossier de données, **hors du dépôt** (voir la
section Données). `just` charge `.env` automatiquement ; sous Windows, écris le
chemin avec des barres obliques (`C:/Users/...`). Les tests n'en ont pas besoin :
ils ne touchent jamais aux données réelles.

## Utilisation

*(à compléter au jalon M3)*

## Comment marche le modèle

Voir [`docs/MODELE_V1.md`](docs/MODELE_V1.md).

## Validation

*(à compléter au jalon M4 : métrique, baselines, résultats)*

---

## Données

Ce dépôt **ne contient aucune donnée personnelle**. Les données réelles vivent
dans un dossier externe pointé par la variable d'environnement `MPA_DATA_DIR`
(voir [`docs/decisions/0001-separation-data-code.md`](docs/decisions/0001-separation-data-code.md)).
Les tests utilisent uniquement les fixtures synthétiques de `tests/fixtures/`.

## Développement

```bash
just check   # lint + types + tests — LA commande
just lint    # ruff check + ruff format --check
just types   # mypy strict
just test    # pytest
just fmt     # formatage et corrections automatiques
```

Voir [`CLAUDE.md`](CLAUDE.md) pour les conventions.
