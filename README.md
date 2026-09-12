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

*(à compléter au jalon M0)*

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
just check   # lint + types + tests
```

Voir [`CLAUDE.md`](CLAUDE.md) pour les conventions.
