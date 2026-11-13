# Les commandes

Une page par commande : ce qu'elle fait, ses options et leurs défauts, les fichiers
qu'elle lit et écrit, et sa sortie d'exemple quand elle en a une.

- [`mperf profile`](profile.md) — le profil d'un GPX
- [`mperf project`](project.md) — les temps de passage
- [`mperf match`](match.md) — une trace réalisée face à un tracé
- [`just backtest`](backtest.md) — le backtest enregistré des cinq modèles, et le backtest
  glissant (`just backtest-rolling`)
- [`just curve`](curve.md) — la courbe personnelle
- [`just ingest`](ingest.md) — l'ingestion des exports Garmin
- [`just process`](process.md) — les tables des activités, des montées, des variantes et
  des jours
- [`just q1`](q1.md) — la figure de Q1
- [`just ui`](ui.md) — l'interface

Avant de commencer : les sous-commandes de `mperf`, les extras et le dossier des
données, ci-dessous ; l'installation est dans le [README](../../README.md).

## Utilisation : `mperf`

Huit sous-commandes, installées par `uv sync` ; `ingest`, `tables` et `q1` demandent en
plus leur extra (`ingest`, `analyse`). Les exemples de ces pages ont été exécutés depuis la
racine du dépôt, sur des fixtures synthétiques commitées
([`tests/fixtures/`](../../tests/fixtures/README.md)) ; celui du backtest, sur le monde
synthétique que les tests écrivent dans un dossier temporaire.

## Les extras

Aucune dépendance de calcul : la seule dépendance d'exécution est `tzdata`, sous
Windows. L'ingestion (`mperf ingest`, qui lit les FIT) demande en plus l'extra `ingest`
(fitdecode, [`0011`](../decisions/0011-bibliotheques-analyse.md)) :
`uv sync --locked --extra ingest`, ou `just ingest`, qui l'installe de lui-même ; sans
lui, les tests qui lisent des FIT se sautent. L'écriture des tables de `processed/` en
Parquet et la figure de Q1 demandent l'extra `analyse` (pyarrow et plotly,
[`0014`](../decisions/0014-montees-et-tables.md),
[`0015`](../decisions/0015-figure-de-q1.md)) : `uv sync --locked --extra analyse`,
ou `just process` et `just q1` ; sans lui, les tests qui écrivent du Parquet ou rendent
la figure se sautent.
L'interface demande l'extra `tableau` (Streamlit,
[`0016`](../decisions/0016-interface-v0.md)) : `uv sync --locked --extra tableau`, ou
`just ui` ; sans lui, les tests de l'interface se sautent. Ses pages de la piste analyse
lisent aussi `processed/` et demandent l'extra `analyse` ; `just ui` installe les deux.
Le serveur n'écoute que la machine, sans télémétrie (`.streamlit/config.toml`).

## Le dossier des données

`MPA_DATA_DIR`, le dossier des données personnelles hors du dépôt, sert au backtest
enregistré (`just backtest` : manifeste, courbe, registre, rapports), à l'ingestion
(`just ingest` : `raw/garmin/` lu, `interim/activities/` et `interim/days/`
écrits), aux tables (`just process` :
l'ingestion, puis `interim/activities/`, `interim/days/`, `athlete.toml` et `journal.csv`
lus, `processed/` écrit), à la figure
de Q1 (`just q1` : `processed/` lu, `resultats/Q1/` écrit), à la courbe personnelle
(`just curve` : `interim/activities/` lu, `reference/` écrit) et à l'interface
(`just ui` : `routes/`, `sorties/`, `reference/`, `processed/` et `resultats/Q1/` lus ;
`routes/` et `sorties/` écrits par l'ajout d'un fichier) ; les autres commandes ne le lisent pas, les tests non plus
([`tests/conftest.py`](../../tests/conftest.py) le pose sur un dossier temporaire neuf
pour chaque test). Pour le renseigner, copier [`.env.example`](../../.env.example) en
`.env` ; `just` charge `.env` s'il existe. Sous Windows, écrire le chemin avec des
barres obliques.
