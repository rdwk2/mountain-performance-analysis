"""Q2 (AN3-3b, ``docs/decisions/0023``) : l'efficience en montée progresse-t-elle ?
La mesure principale est le log de la VAM à FC comparable (M-P), la secondaire la VAM
par battement au-dessus de la FC de repos (M-S), par régime (montées longues, côtes,
ski de randonnée).

**Ce que le paquet fait** : il forme les journées depuis les tables de ``processed/``,
applique les exclusions dans leur ordre et compte le flux (``data.py``), forme les
groupes de parcours (``routes.py``), décide du budget et des retraits, estime les deux
étages du modèle, la régression inverse et la lecture bornée (``model.py``), simule la
puissance avant toute estimation (``power.py``), joue les 24 essais (``trials.py``),
calcule la figure (``figure.py``) et écrit les résultats et le journal chaîné des
essais (``results.py``).

**Ce qu'il lit** : les tables de ``processed/`` (relues par
``mountain_perf.analyse.parquet``), la table ``[periodes]`` d'``athlete.toml``, et,
pour l'estimation, ses propres résultats de puissance et ``resultats/essais.jsonl``.
Jamais ``raw/``, ``interim/`` ni ``journal.csv``.

**Ce qu'il écrit** : ``resultats/Q2/puissance/<date>_<empreinte>/``,
``resultats/Q2/<date>_<empreinte>/`` et ``resultats/essais.jsonl``, sous
``MPA_DATA_DIR``.

**La clôture** : aucun module du paquet n'importe numpy, scipy, pyarrow ni plotly
(``docs/decisions/0021``) ; les calculs matriciels passent par
``mountain_perf.analyse.inference``, qui reçoit des listes Python et rend des
tableaux numpy, que ``q2`` lit par indice, ``float(...)`` ou ``.tolist()``.
"""
