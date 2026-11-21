# 0023 — Le code de Q2

- **Date** : 2026-11-15
- **Statut** : acceptée

## Contexte

Q2 demande si l'efficience en montée progresse : la VAM à FC comparable, ou par battement
au-dessus de la FC de repos ([`docs/analyse/QUESTIONS.md`](../analyse/QUESTIONS.md)). Son
plan d'analyse, tenu hors du dépôt comme le veut la charte (§ 10), fige la mesure, les
exclusions, le modèle à deux étages, la lecture bornée, la simulation de puissance et
vingt-quatre essais. Les outils génériques existent (`0021`) ; les colonnes que Q2 lit
aussi (`0014`, `0019`, précisions d'AN3-1a et d'AN3-3a). Il manquait le code qui sait ce
qu'est une montée, une journée et une période, et la commande qui l'exécute.

## Options envisagées

**A. Un paquet `analyse/q2/` et deux modes d'une commande** : `mperf q2 puissance`, puis
`mperf q2`, l'estimation refusée tant qu'aucun résultat de puissance n'existe pour les mêmes
tables.

**B. Deux PR** : la puissance d'abord, l'estimation après le plan v2. La commande qui
estime l'effet n'existerait pas avant le plan v2 ; un cycle de relecture de plus.

**C. Une seule commande sans mode**, qui calcule la puissance puis estime : l'ordre du
plan de Q2, la puissance avant toute estimation (la charte, § 6, la fait calculer par
simulation sur le plan réel), ne serait plus qu'une habitude.

## Décision

**A.** Le code de Q2 est un paquet de la piste, `analyse/q2/`, en Python pur : il
n'importe ni numpy ni scipy (`0021` les ferme à `analyse/inference/`), seulement les
outils du paquet d'inférence. Il lit `processed/` et `athlete.toml` ; l'estimation lit
aussi le dernier résultat de puissance (`resultats/Q2/puissance/`) et le journal des
essais (`resultats/essais.jsonl`).

## Conventions

- **Un dossier par exécution**, sous `MPA_DATA_DIR`, jamais réécrit, comme Q1 (`0015`) :
  `resultats/Q2/puissance/<date>_<empreinte>/` pour la puissance (`puissance.csv`,
  `flux.csv`, `provenance.json`), `resultats/Q2/<date>_<empreinte>/` pour l'estimation
  (`essais.csv`, `flux.csv`, `figure.csv`, `figure.html`, `autocorrelation.csv`,
  `provenance.json`). L'empreinte est celle de la provenance sans la date : les mêmes
  tables, le même code et les mêmes paramètres donnent la même empreinte, et une
  exécution relancée le même jour sur les mêmes entrées est refusée, sans rien écrire.
- **La garde** : `mperf q2` cherche le dernier résultat de puissance calculé sur les mêmes
  tables (la provenance des tables, comme la page « Q1 ») ; sans lui, il refuse. C'est une
  garde, pas une preuve : l'ordre « puissance, plan v2, estimation » reste une consigne.
  La valeur critique calibrée par la puissance, quand elle se déclenche, sert à
  l'estimation.
- **Le journal des essais**, `resultats/essais.jsonl` (charte § 8) : chaque exécution de
  `mperf q2` y ajoute ses vingt-quatre lignes, en ajout seul ; chaque ligne porte
  l'empreinte de la précédente (`codec.canonical_bytes`, `codec.content_hash`) ; une
  chaîne rompue est refusée avant toute écriture.
- **La graine** est une constante du code, écrite dans la provenance, sans option pour la
  changer : une graine changée après un résultat compterait pour un essai (charte § 6).
  Chaque tirage vient d'un générateur enfant (`child_rng`) dont la clé dit l'essai et
  l'usage ; la sortie ne dépend pas du nombre de processus (`--processus`) : chaque
  processus, le principal compris, calcule sur un seul fil de calcul matriciel
  (`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS` posés à 1, une valeur déjà
  posée écrasée), car les calculs de numpy changent à l'octet avec le nombre de fils.
- **La puissance** simule la VAM au niveau des montées, à travers les deux étages, autour
  du modèle **sans le terme de date** ; sa sortie n'affiche aucune estimation de la date
  sur les données. Dans la simulation, le bootstrap de l'effet inverse garde la covariance
  fixée à celle de l'ajustement du tirage (un calcul linéaire) ; sur les données, elle est
  réestimée à chaque tirage, comme le plan le demande. Mesuré par la conception sur six
  jeux de données inventés : la largeur de l'intervalle à covariance réestimée vaut de
  0,74 à 1,66 fois celle à covariance fixée (médiane 0,96), sans sens constant ; la
  puissance de la lecture bornée est donc une approximation, dite comme telle (le
  résumé de `mperf q2 puissance` : « puissance approchée ») ; c'est la mesure que la
  note du 2026-11-15 de `0021` reprend. Réestimer la covariance dans la simulation
  demanderait des mois de calcul.
- **Les périodes** se déclarent dans une table `[periodes]` d'`athlete.toml`
  (`decouverte = { debut = "AAAA-MM-JJ", fin = "AAAA-MM-JJ" }`), lue par
  `analyse/athlete.py` pour Q2 seule ; absente, les sensibilités qui en dépendent sont
  « non faites » et le flux est sans période.
- **Les seuils** du plan sont des paramètres déclarés (`Q2_PARAMETER_SPECS`), écrits dans
  la provenance ; l'appareil principal (fabricant et numéro de produit, jamais un numéro
  de série) aussi.
- **La figure** : le dernier tronçon de la courbe (les jours au-delà du nœud à 75 % des
  dates) est marqué provisoire : pour une spline, c'est la lecture de la « demi-fenêtre la
  plus récente » de la charte (§ 8).
- Tout résultat de Q2 est **exploratoire** sur ces données : la ligne de `deja_vu.csv`
  n'est pas lue, la règle s'applique d'office.

## Pourquoi

Une seule commande à deux modes garde l'ordre de la charte dans le code (la garde) sans
attendre un second cycle de relecture ; le paquet de la piste garde la clôture de numpy, et
les tests de Q2 restent en Python pur. Le journal chaîné rend visible toute relance : la
charte compte chaque estimation comme un essai.

## Conséquences

- **Facile** : Q1 et les questions suivantes reprennent la forme (paquet, deux dossiers,
  journal des essais, graine fixe) ; une sensibilité s'ajoute comme une ligne d'essai.
- **Contraignant** : `mperf q2 puissance` dure de l'ordre de trois heures par régime sur
  un processus ; `--processus` le divise (un fil de calcul matriciel par processus,
  sinon les processus se gênent). Un résultat de puissance d'autres
  tables ne compte pas : après `just process`, la puissance se relance.
- **À revisiter** : le plan v2 (après le contrôle réel) peut fixer le cinquième retrait, la
  valeur critique, une vingt-cinquième sensibilité ; une note datée le dira ici.

## Précisions d'AN3-5 (2026-11-20)

- **La relecture** : `stored_estimations` et `latest_estimation` relisent
  `resultats/Q2/` comme `analyse/results.py` relit `resultats/Q1/` (les tables
  actuelles d'abord, puis la date, l'écriture, le nom) ; seuls comptent les dossiers
  au nom de `RESULT_NAME` : `puissance/` n'est ni lu ni compté illisible ; un
  dossier sans `essais.csv` est illisible (Q1 n'exige que `provenance.json`).
  `read_estimation` relit les essais, la figure, le flux (sommé sur les mois),
  l'autocorrélation et la puissance que nomme `provenance.json` (`puissance.dossier`),
  à son empreinte : une puissance absente ou changée ne se remplace pas par une autre.
