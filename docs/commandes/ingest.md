# `just ingest` — l'ingestion des exports Garmin

`just ingest` lance `mperf ingest` avec l'extra `ingest` : il lit les exports Garmin
rangés sous `MPA_DATA_DIR/raw/garmin/` et écrit `MPA_DATA_DIR/interim/activities/`
([`0013`](../decisions/0013-ingestion-et-interim.md)) et
`MPA_DATA_DIR/interim/days/` ([`0018`](../decisions/0018-donnees-journalieres.md)).
Chaque export a son
dossier, `raw/garmin/<export>/` (lettres et chiffres ASCII, `_`, `.` et `-`, sauf
`activities` et `acquisition.json`, réservés : dans `raw/garmin/`, ils désignent un
export laissé à plat ; le nom ne sert qu'au rapport), qui comprend :

- `acquisition.json`, l'instant où l'export a été obtenu, écrit à la main
  (`{"retrieved_at": "<instant ISO 8601 avec fuseau>"}`) ;
- `activities/activities.json`, l'index des activités ;
- `activity_fit/<identifiant>.zip`, une archive par activité, qui contient son FIT ;
- `<famille>/<AAAA-MM-JJ>.json`, un fichier par jour pour chacune des onze familles
  journalières (`sleep`, `hrv`, `resting_hr`, `heart_rate`, `body_battery`, `stress`,
  `respiration`, `spo2`, `daily_summary`, `training_readiness`, `training_status`) ;
  une famille peut manquer, et un export sans aucune est admis.

Les autres dossiers de `raw/` sont laissés aux autres sources. Aucun export ne se
retire : Garmin efface avec le temps le détail des jours, et un export ancien en reste
la seule source. Pour chaque activité, l'export qui fait foi est le plus récent dont
la période (du premier départ de ses entrées gardées à son instant d'acquisition)
couvre son départ : une activité qu'il ne porte pas n'est pas ingérée, elle est
« retirée de la source ». Pour chaque jour, l'export de référence est le plus récent
où le jour est complet et a encore son détail, sinon le plus récent où il est
complet, puis tronqué, puis sans mesure, puis le plus récent qui le porte ; une
famille ou une série qu'il n'a pas, ou les segments de la nuit, peuvent venir du plus
récent des autres exports qui les porte, si leurs fenêtres s'accordent (même début de la
fenêtre du jour, même nuit à la seconde ; pour les segments, leurs durées aussi).

Dans `interim/activities/`, l'ingestion écrit trois choses :

- l'index des activités, avec la provenance de chaque export ;
- un enregistrement par activité dont un FIT se lit : un canal par grandeur, chacun
  avec ses instants, sans interpolation ;
- le rapport de l'ingestion : par export, sa période et ses entrées ; les fichiers lus
  et refusés, les entrées de l'index refusées, les activités retirées de la source,
  les activités sans vue `Activity`, les désaccords entre un FIT et son entrée, et ce
  qui diffère d'un export à l'autre (champs de l'index, FIT).

Dans `interim/days/`, trois choses aussi :

- un document par jour : sa fenêtre et son état (complet, tronqué, sans mesure,
  vide), sa nuit principale (rattachée au jour du réveil) et ses siestes, une valeur
  par grandeur, les séries de la journée et de la nuit, sans interpolation, les
  entrées de Training Readiness, et la provenance de chaque nuit, sieste, résumé,
  série et entrée ;
- Training Status, chaque bloc à sa date propre ;
- le rapport des jours : par export, ses jours et ses familles ; les fichiers lus et
  refusés, les jours par export de référence, les emprunts et leurs refus, les écarts
  entre exports (emprunts, dégradations, révisions, à part) ; les points écartés et les
  codes inconnus, avec leur motif : ceux de la lecture sur les seules lectures retenues
  (la référence et les familles empruntées entières, pas le prêteur d'une série ou de
  segments seuls), et les points que l'assemblage jette (nuit absente, jour sans
  fenêtre).

Rien n'est corrigé : une valeur écartée est comptée, avec son motif. `raw/` n'est jamais
écrit. Une ingestion qui s'arrête sur une erreur avant d'écrire laisse en place les
`interim/activities/` et `interim/days/` précédents ; si les jours ne prennent pas leur
place après les activités, le message le dit, et relancer `just ingest` remet tout en
ordre. Deux ingestions des mêmes fichiers écrivent les mêmes octets. Le moteur lit
`interim/` par ses vues : la trace d'un enregistrement (`trace_view`) pour
`just curve` (M6b) ; il lira les jours par les vues de `ingest/day_views.py` (M7) :
une vue prise à un instant ne rend que ce dont l'instant propre (la fin d'une nuit,
l'instant d'un point) est au plus tard cet instant, ou strictement avant, et ses
seuils sont des arguments.

```bash
just ingest
```

La sortie donne d'abord le nombre d'exports, puis une ligne par export (son instant
d'acquisition, ses entrées gardées et refusées, ses archives). Elle compte ensuite les
activités de l'index, les enregistrements, les fichiers refusés, les entrées refusées,
les entrées sans archive, les désaccords et les activités sans vue `Activity`, avec une
ligne par couple (motif, type de la source) de ces dernières ; enfin les activités
retirées de la source, les champs de l'index qui diffèrent d'un export à l'autre (une
ligne par champ), les activités aux FIT différents et les enregistrements tirés d'un
autre export que leur entrée. Viennent ensuite les jours : leur nombre, une ligne par
export de référence et une par état du jour, puis les morceaux empruntés, les emprunts
refusés, les révisions, les dégradations et les écarts à part entre exports (en champs
× jours), les fichiers journaliers refusés, les points écartés, les codes inconnus, les
blocs de Training Status et ceux sans instant propre. Pas d'exemple ici : sur les
exports réels, ces nombres
restent hors du dépôt ([`docs/analyse/CHARTE.md`](../analyse/CHARTE.md), § 10).
