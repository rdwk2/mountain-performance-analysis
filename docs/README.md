# La documentation

Le [README](../README.md) présente le projet ; ces pages le détaillent.

## Utiliser

- [Les commandes](commandes/README.md) : une page par commande, avec ses options, les
  fichiers qu'elle lit et écrit, et sa sortie d'exemple.
- [Contribuer](../CONTRIBUTING.md) : vérifier, la version de Python, les tests qui
  lisent la documentation, le garde-fou des données.

## Décisions et documents

Une décision structurante = un fichier dans [`docs/decisions/`](decisions/),
sur le gabarit [`0000-template.md`](decisions/0000-template.md). Toutes
sont au statut « acceptée » :

- [0001 — Séparation stricte données / code](decisions/0001-separation-data-code.md)
- [0002 — Unités internes et unités d'affichage](decisions/0002-unites.md)
- [0003 — Portée multi-sport des contrats](decisions/0003-portee-multi-sport.md)
- [0004 — Le point remarquable comme pivot](decisions/0004-point-remarquable-pivot.md)
- [0005 — Convention des temps de passage](decisions/0005-convention-temps-de-passage.md)
- [0006 — Le temps](decisions/0006-temps.md)
- [0007 — Forme des données](decisions/0007-forme-des-donnees.md)
- [0008 — Géométrie, lissage et résolution des passages](decisions/0008-geometrie-et-lissage.md)
- [0009 — Moteur de projection v0](decisions/0009-moteur-projection-v0.md)
- [0010 — Protocole de backtest et métrique d'erreur](decisions/0010-protocole-de-backtest.md)
- [0011 — Bibliothèques de la piste analyse](decisions/0011-bibliotheques-analyse.md)
- [0012 — Notebooks et règle 7](decisions/0012-notebooks-et-regle-7.md)
- [0013 — Ingestion des activités et format d'`interim/`](decisions/0013-ingestion-et-interim.md)
- [0014 — Les montées et les tables de `processed/`](decisions/0014-montees-et-tables.md)
- [0015 — La figure de Q1](decisions/0015-figure-de-q1.md)
- [0016 — Interface v0](decisions/0016-interface-v0.md)
- [0017 — Estimation de la courbe personnelle](decisions/0017-estimation-de-la-courbe.md)
- [0018 — Les données journalières dans `interim/days/` et leurs vues](decisions/0018-donnees-journalieres.md)
- [0019 — La table `jours` et les normales](decisions/0019-table-jours-et-normales.md)
- [0020 — L'origine glissante : la règle d'estimation à l'origine](decisions/0020-origine-glissante.md)

Autres documents :

- [`docs/MODELE_V1.md`](MODELE_V1.md) — la spécification de départ du
  modèle, reprise de la version précédente du projet ; le M3 n'en implémente que
  la partie 1 ;
- [`docs/DICTIONNAIRE_DONNEES.md`](DICTIONNAIRE_DONNEES.md) — les contrats de
  données, généré depuis les docstrings ;
- [`docs/PIEGES_DATA.md`](PIEGES_DATA.md) — les pièges déjà rencontrés dans
  les données Garmin ;
- [`docs/analyse/`](analyse/) — la charte et les questions de la piste analyse ;
- [`CLAUDE.md`](../CLAUDE.md) — les règles et les conventions du dépôt.

## Suivre

- [`ROADMAP.md`](ROADMAP.md) : où en est le projet, et le plan, jalon par jalon ;
- [`JOURNAL.md`](JOURNAL.md) : ce qui a été fait, session par session ;
- [`BACKLOG.md`](../BACKLOG.md) : les idées en attente.
