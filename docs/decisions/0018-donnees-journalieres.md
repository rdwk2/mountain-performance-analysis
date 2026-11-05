# 0018 — Les données journalières dans `interim/days/` et leurs vues

- **Date** : 2026-10-28
- **Statut** : acceptée (AN2-1)

## Contexte

`0013` couvre les activités ; son point 6 annonçait que les données journalières le
compléteraient avec AN2. Chaque export Garmin porte onze familles journalières, un
fichier par jour chacune : `sleep`, `hrv`, `resting_hr`, `heart_rate`, `body_battery`,
`stress`, `respiration`, `spo2`, `daily_summary`, `training_readiness`,
`training_status`. Deux exports réels (comptés hors du dépôt, sans chiffre ici,
règle 1) montrent ce qu'une ingestion doit savoir porter :

- **le jour de Garmin** commence à minuit, heure locale ; sa fenêtre, écrite en GMT,
  n'a qu'un décalage : au changement d'heure, deux fenêtres voisines se recouvrent
  d'une heure (printemps) ou laissent un trou d'une heure (automne). Une fenêtre peut
  être **tronquée** (Garmin n'avait rien reçu au-delà), un jour peut être complet sans
  rien de mesuré, un document peut être vide ;
- **Garmin efface le détail des jours anciens** (séries de la journée, phases et séries
  du sommeil, HRV de la nuit) et appauvrit le jour ; entre deux exports, un jour ne
  change guère que s'il a perdu son détail ;
- **une même grandeur** se lit dans plusieurs familles (FC de repos, HRV, respiration et
  SpO2 de la nuit, stress) ; les familles portent des **codes** (phases du sommeil,
  sentinelles du stress et de la respiration, statuts du Body Battery), qu'elles
  écrivent parfois en flottants de valeur entière ;
- **une nuit** appartient au jour du réveil, les siestes sont à part ; Training
  Readiness porte plusieurs entrées par jour ; Training Status range des **blocs à leur
  date propre**, qui peut précéder le jour du fichier ; `respiration` et `spo2` du jour
  J portent aussi la nuit de J + 1.

Deux consommateurs : la piste (la table `jours`, ses normales et la page de
récupération, AN2-2 et AN2-3) et le moteur, dont M7 lira le sommeil, le Body Battery,
Training Status et la FC de repos, par des vues de `ingest/`, jamais en ouvrant les
fichiers (`0013`, condition (c)). Trois questions : ce que contient `interim/days/` et
sous quels contrats ; quel export fait foi pour un jour ; comment une vue prise à un
instant ne rend rien de postérieur.

## Options envisagées

**La forme.**

**A. Un document par famille et par jour**, copie normalisée de chaque fichier. Fidèle,
mais chaque lecteur refait le choix de l'export, les emprunts et la source de chaque
grandeur, et M7 relirait onze familles.

**B. Un document par jour, rangé par sujet** (le jour, la nuit, les siestes, les valeurs
du jour, les séries, les entrées de Training Readiness), une source par grandeur, et
Training Status dans un document à part.

**C. Une table par grandeur**, toutes dates confondues. Proche de la table `jours`
d'AN2-2, dont ce serait une copie avant l'heure.

**Les seuils** (nuit courte, décalée, partielle, statut de la FC de repos, couverture).

**A. Calculés à l'ingestion et écrits.** Simple à lire, mais un seuil changé demande une
réingestion, et le backtest du moteur ne peut pas les faire varier.

**B. Rien qui demande un seuil dans `interim/days/`** : des vues les calculent à la
lecture, les seuils en arguments, sans valeur par défaut.

**Le numéro de format.**

**A. `INTERIM_FORMAT_VERSION` à 3** : `interim/activities/` devient illisible avant une
réingestion, pour M6b comme pour la piste.

**B. Les types des jours au premier format 2**, la version inchangée.

## Décision

Forme B, seuils B, format B.

### Les fichiers

Sous `MPA_DATA_DIR/interim/days/` : un document par jour, `<AAAA-MM-JJ>.json`
(`DayRecord`) ; `training_status.json` (`TrainingStatusHistory`) ; `report.json`
(`DaysReport`). Les contrats sont dans `schemas/days.py` ; l'écriture
(`write_days`) et la relecture (`read_days`, `read_training_status`,
`read_days_report`) dans `ingest/interim.py`, par l'enveloppe commune du codec
(`0013`, point 3) ; `read_days` refuse un élément étranger dans le dossier. Le dossier
s'écrit à côté (`days.nouveau/`), puis prend la place de l'ancien, qui reprend la
sienne si le nouveau ne la prend pas (`0013`, précision 20).

### Le document d'un jour

Un document par jour de Garmin qu'au moins un export porte (au moins un fichier d'une
famille à cette date, même vide). Il porte :

- **la fenêtre du jour** : son début, *aware* dans le décalage de la fenêtre (`0006`),
  et la fin des données (`data_end`, la fin GMT de la fenêtre de la source) ; la famille
  d'où elle vient : `daily_summary`, à défaut `heart_rate`, `stress`, `respiration`,
  `spo2`, dans cet ordre ;
- **l'état du jour**, décidé dans cet ordre : `empty` (aucune famille ne porte de
  fenêtre du jour) ; `no_measurement` (l'indicateur de présence de `daily_summary` est
  faux ou, sans lui, ni échantillon mesuré dans les séries du jour ni nuit) ;
  `truncated` (les données finissent avant début + 24 h) ; `complete`. L'état, la
  fenêtre et la fin des données viennent toujours de la référence ; un jour `empty`
  peut porter une nuit ou des familles empruntées ;
- **l'export de référence** (plus bas) et la provenance (`SourceRef`) du fichier qui
  porte chaque nuit, sieste, résumé, série, entrée de Training Readiness : un objet
  emprunté garde celle de son export ; des segments de la nuit empruntés n'ont pas la
  leur (la nuit garde celle de son fichier), ni l'indicateur de présence ;
- **la nuit principale**, rattachée au jour du réveil : sa fenêtre (chaque borne dans
  son décalage), les durées des phases (profond, léger, paradoxal), de l'éveil et du
  non mesurable, ses segments de phase, le type de confirmation de sa fenêtre et si
  elle est confirmée, si elle vient de la montre, si l'appareil détecte le paradoxal
  (sinon le paradoxal est absent, pas nul), les résumés de Garmin, l'écart de
  température cutanée, et **ses séries, prises dans `sleep`** ; quand toutes ses
  durées sont connues (le paradoxal, ou un appareil qui ne le détecte pas), l'égalité
  fin − début = phases + éveil + non mesurable se vérifie à `NIGHT_TOLERANCE_S` près, et
  ses écarts se comptent : ce n'est pas un invariant ;
- **les siestes**, triées, chacune avec sa fenêtre et sa durée de sommeil selon Garmin ;
- **les valeurs du jour, une source par grandeur** : la FC de repos (`resting_hr`), la
  HRV de la nuit et de la semaine, son statut et ses bornes (`hrv`), la respiration et
  la SpO2 (`respiration`, `spo2`), le stress du jour, le Body Battery du jour et les
  totaux d'activité (`daily_summary`) ; les copies des autres familles se contrôlent
  (désaccords comptés), les copies de Training Readiness restent des entrées de
  l'indicateur ; chaque grandeur déclare son **support** (`QUANTITY_SUPPORTS`) : la
  nuit, le réveil (une grandeur que Garmin fixe à la fin de la nuit : HRV de la
  semaine, statut et bornes, Body Battery au réveil), la journée, ou l'instant ; les
  vues en tirent son instant propre ;
- **les séries du jour** (FC, stress, Body Battery et son statut, respiration, SpO2) ;
- **les entrées de Training Readiness** de l'appareil que la source dit principal,
  triées par instant ;
- **les versions d'algorithme** portées, et **les rangs des appareils** que nomment les
  familles du jour (l'ordre de première apparition, jamais un identifiant : `0013`,
  points 1 et 5).

Une série a un canal par grandeur, ses instants strictement croissants, en secondes
depuis le début de sa fenêtre (du jour, ou de la nuit pour les séries de `sleep`),
sans interpolation ; un code sentinelle est gardé comme un code ; un point hors de la
fenêtre de son fichier est gardé au jour du fichier, et compté. Les séries et les
segments d'une nuit absente, et les séries du jour d'un jour sans fenêtre, sont écartés
et comptés. **Ne s'ingèrent pas** : les textes et codes de conseil, le besoin de
sommeil et l'alignement, la série de mouvement, les champs de la nuit de J + 1
(`tomorrow…`), les événements de Body Battery (ils portent des noms et des identifiants
d'activité), les identifiants, les calories, `range/` et le profil.

**Pas de rapprochement avec l'appareil d'un FIT** : les familles journalières ne nomment
leur appareil que par un identifiant (et Training Status par un nom de modèle), que
l'ingestion ne garde pas ; aucune clé ne relie les deux. La rupture d'une mesure se lit
sur le rang et les versions d'algorithme ; un changement de firmware se contrôle sur les
FIT des activités (`docs/analyse/CHARTE.md`, § 11).

### Training Status

Son propre document : cinq suites de blocs (le statut, avec son horodatage et les
charges aiguë et chronique et leur rapport ; l'équilibre de la charge ; la VO2max ;
l'acclimatation à la chaleur ; l'acclimatation à l'altitude), chacune triée par **date
propre**, un seul bloc par date. Un bloc sans date propre est refusé, et compté dans le
fichier retenu pour son jour (Training Status ne s'emprunte pas). Chaque bloc porte son
**instant propre**, calculé à l'ingestion : l'horodatage du statut (en UTC : la source
n'en donne pas l'heure locale) ; sinon
la fin de la fenêtre du jour de sa date, celle des grandeurs de la journée (ci-dessous,
« Les vues ») ; sans fenêtre de ce jour, le début de la fenêtre du lendemain, si ce
lendemain a une fenêtre (un jour `empty` n'en a pas ; le seul instant propre qui lit un
autre jour : « Les vues ») ; sinon le minuit local qui suit sa date, au décalage de la
fenêtre du jour du fichier choisi (une heure trop tôt ou trop tard quand ce fichier est
de l'autre côté d'un changement d'heure, de l'écart des décalages après un voyage) ;
sinon aucun (le bloc reste, compté, et aucune vue ne le rend). Un fichier dont une table
rangée par appareil a plusieurs clés sans exactement un bloc principal est refusé.

### La lecture d'un fichier

`ingest/families.py` lit un fichier d'une famille, depuis ses octets, sans E/S. Refus du
fichier, le premier rencontré : JSON illisible ; racine d'un autre type ; date du
document autre que celle de son nom ; Training Status dont une table rangée par appareil
a plusieurs clés sans exactement un bloc principal ; un champ lu d'un autre type, un
point en colonnes trop court, ou une liste de descripteurs de colonnes, présente et non
vide, qui contredit la disposition lue (une colonne lue placée ailleurs ou absente, un
élément qui n'est pas un objet : `COLUMN_LAYOUTS`). Un document vide (`{}`, `[]`), ou
dont rien ne se lit, n'est pas un refus : la famille est absente ce jour-là. **Un code
se lit par sa valeur** : `1.0` est le code `1`. Une valeur hors de la plage de sa
famille (tirée de bornes physiques, jamais des valeurs observées ; zéro n'est écarté que
hors de la plage), un code inconnu (avec sa valeur), un instant qui ne croît pas, un
segment qui en recouvre un autre : écartés et comptés, jamais corrigés.

### Plusieurs exports

`ingest/days.py` calcule tout, jour par jour, avant la moindre écriture.

- **Refus d'un export** (rien n'est écrit, le message nomme l'export) : un fichier
  journalier daté après la date locale de son instant d'acquisition ; la fin des données
  du dernier jour qui porte une fenêtre du jour strictement plus de
  `ACQUISITION_TOLERANCE_S` (une heure) après cet instant. Un export sans familles
  journalières est admis.
- **L'export de référence d'un jour** : le plus récent où le jour est `complete` **et a
  son détail** (une série fine que Garmin efface y est non vide, la SpO2 exclue, qui
  s'arrête aussi par un réglage de la montre) ; à défaut, le plus récent où il est
  `complete` ; puis `truncated` ; puis `no_measurement` ; puis le plus récent qui le
  porte. Un jour n'est donc `empty` que si aucun export ne lui donne de fenêtre. Les
  familles du jour viennent de lui, sauf les emprunts.
- **Les emprunts** : une famille absente de la référence, ou une série, ou les segments
  de la nuit, viennent du plus récent des autres exports qui les porte, et de lui seul,
  si leurs fenêtres s'accordent (même début de la fenêtre du jour ; même
  fenêtre de la nuit à la seconde ; des segments qui redonnent les durées du résumé de
  la nuit retenue à `NIGHT_TOLERANCE_S` près) ; sinon ils restent absents, et le refus
  se compte. `body_battery` et `training_status` ne s'empruntent pas.
- **Les écarts entre exports** : la référence se compare à chacun des autres exports
  qui portent le jour, champ par champ, et chaque écart se range dans une classe, dans
  cet ordre : l'**emprunt** (le champ est d'une famille reçue entière, ses copies et sa
  série du jour refusée comprises, ou d'une série ou des segments reçus seuls) ; la
  **dégradation** (le plus récent des deux n'a plus le détail du jour que l'ancien
  avait : tout écart de ce jour entre eux s'y range, une révision comprise) ; la
  **révision** (le jour complet dans les deux, aussi riches, la valeur présente des
  deux côtés) ; le reste, **à part**. Un jour compte une fois par famille, champ et
  classe. Les révisions sont le contrôle de la charte sur les métriques de Garmin
  (§ 7) : comptées sur les seuls jours aussi riches dans les deux exports. Des champs
  de métadonnées qui changent à chaque export ne se comparent pas
  (`COMPARISON_IGNORED_FIELDS`).
- **Un bloc de Training Status** de date D vient de l'export de référence du jour D s'il
  le porte, sinon du plus récent qui le porte ; dans cet export, du fichier du jour D
  s'il le porte, sinon du plus ancien qui le porte. Ses écarts, dans un export et d'un
  export à l'autre, se comptent par sorte et par champ.

### Le rapport

`report.json` dit, par export, son nom, son instant, son premier et son dernier jour, ses
fichiers et ses familles ; les fichiers lus et refusés, avec leur motif ; les jours par
export de référence ; les jours dont la fenêtre ne vient pas de `daily_summary` et les
familles dont la fenêtre diffère ; les emprunts et leurs refus ; les écarts entre exports
par classe ; par série, les points hors de la fenêtre de leur fichier et les instants
présents dans deux jours voisins ; pour les séries de la journée, le plus grand écart
entre le dernier instant d'un jour et le premier du suivant ; l'égalité de la nuit hors
tolérance ; les points écartés par motif : ceux que l'assemblage jette (`no_night`,
`no_window`), et ceux de la lecture, comptés comme ci-dessous ; les siestes qui
recoupent la nuit ; les écarts des blocs, les blocs sans instant propre. Sur les seules
lectures retenues, c'est-à-dire la référence et les familles empruntées entières (pas le
prêteur d'une série ou de segments seuls) : les points écartés par la lecture, les blocs
refusés, les désaccords entre copies, les copies de Training Readiness qui diffèrent du
document final, les codes, contextes et types de confirmation inconnus, les entrées de
Training Readiness d'un appareil non principal.

### Les vues

`ingest/day_views.py`, sans dépendance, sur `interim/days/`, jamais écrites. **Règle
commune**, pour les vues prises à un instant `t` (`sleep_within` et `series_between` à
leur borne `end`, `body_battery_at`, `night_before`, `training_status_at`,
`readiness_at`, `resting_hr_at`) : la vue ne rend que ce dont l'instant propre est au
plus tard `t` ; avec `strict=True`, strictement avant. L'instant propre d'une nuit ou
d'une sieste est sa fin ; celui d'un point, son instant ; celui d'une entrée de Training
Readiness, son horodatage ; celui d'une grandeur, selon son support : la fin de la nuit
(nuit, réveil), la fin de la fenêtre de son jour (journée) : le plus tard de son
début + 24 h et de sa fin des données, lue dans le seul document du jour, jamais dans
celui du lendemain, dont l'existence est une donnée d'après `t` (un jour de 25 h complet
finit au minuit local qui suit ; un jour de 23 h, à début + 24 h, une heure après sa
vraie fin ; le jour du passage à l'heure d'hiver dont les données finissent au plus tard
à début + 24 h, tronqué ou écrit sur 24 h à un seul décalage, à début + 24 h, au plus
une heure avant son minuit local, ses données finissant avant ; s'il finit entre
début + 24 h et ce minuit, à sa fin des données) ; celui d'un bloc, le sien. La vue à
`t` ne dépend ainsi d'aucune donnée d'après `t`, sauf par l'instant propre d'un bloc
sans horodatage ni fenêtre de son jour, qui lit le début de la fenêtre du lendemain
(« Training Status ») : selon que ce lendemain a une fenêtre, il bouge de l'écart entre
les deux décalages (une heure au changement d'heure). Une nuit n'existe qu'une fois
finie, et une nuit rendue l'est telle que connue à `t` : ses séries et ses segments
coupés à `t`.
`night_assessment`, `resting_hr_on` et `readiness_on_waking` se prennent sur un jour, pas
à un instant : elles lisent le document du jour entier, et `resting_hr_on` rend
l'instant propre de son jour, pour que l'appelant applique la règle ; `nights_after` est
hors de la règle commune. À égalité d'instant propre, une vue rend le dernier dans
l'ordre des documents ; le dédoublonnage des points garde le fichier du jour le plus
ancien. Les seuils sont des arguments sans valeur par défaut, contrôlés (finis, dans
leur domaine, sinon une erreur qui nomme l'argument), leur unité dans leur nom, et
chaque docstring dit si la borne est comprise.

| Vue | Ce qu'elle rend |
|---|---|
| `sleep_within(days, start, end)` | les épisodes entiers (nuits, siestes) finis au plus tard à `end` et au plus tôt à `start`, leur sommeil et sa couverture : par groupe d'épisodes qui se recouvrent, la somme, ou l'union sur les segments et les fenêtres des siestes, bornée par la somme ; une nuit sans segments dans un groupe qui en recouvre un autre rend le sommeil absent |
| `body_battery_at(days, instant)` | la dernière valeur, son statut et son âge, sur une série fusionnée (les points de `sleep` dans les fenêtres des nuits, ceux du jour ailleurs) |
| `night_before(days, instant)` | la dernière nuit principale finie au plus tard à l'instant, et l'écart |
| `training_status_at(history, kind, instant)` | le dernier bloc d'une sorte, et son âge |
| `readiness_at(days, instant)` | la dernière entrée de Training Readiness, et son âge |
| `night_assessment(days, day, …)` | l'état de la nuit (`missing`, `declared`, `in_progress`, `partial`, `complete`, dans cet ordre) et ses drapeaux `short` et `shifted` |
| `resting_hr_on(days, day, min_sleep_s=…)` | la FC de repos d'un jour et son statut (`absent`, `provisional`, `no_night`, `valid`, dans cet ordre), avec l'instant propre du jour |
| `resting_hr_at(days, instant, min_sleep_s=…)` | la dernière FC de repos de statut autre qu'`absent`, son jour, son statut et son âge |
| `nights_after(days, after, count)` | les premières nuits finies après `after` : vue d'analyse rétrospective, hors de la règle commune |
| `readiness_on_waking(days, day, tolerance_s=…)` | la première entrée « réveil » après la nuit du jour, moins la tolérance, avant la sieste suivante |
| `series_between(days, kind, start, end, …)` | les points d'une série, dédoublonnés par instant (le fichier du jour le plus ancien gardé), et leur couverture ; sous `min_coverage_fraction`, aucun point : la couverture et le motif |

### La commande

`mperf ingest` lit et vérifie tous les exports (activités, puis jours), calcule tout,
écrit les activités, puis les jours. Une erreur avant l'écriture n'écrit rien. Pour les
mêmes exports, `interim/activities/` s'écrit **à l'octet** comme avant les jours. Si
l'écriture ou la mise en place des jours échoue (une `OSError`) après celle des
activités, le message le dit (`DAYS_NOT_IN_PLACE`), et relancer remet tout en ordre. La sortie ajoute les comptes des
jours après ceux des activités, inchangés.

### Le format

Les trois types des jours se déclarent dans `INTERIM_DOCUMENT_FIRST_FORMAT` au premier
format **2** ; `INTERIM_FORMAT_VERSION` reste à 2. Il change au changement de **forme ou
de sens** d'un contrat existant (un champ dont l'unité ou la définition change), pas à
l'ajout d'un type (`0013`, précision 22).

## Pourquoi

- **Un document par jour, une source par grandeur** : le choix de l'export, les emprunts
  et la source de chaque grandeur se font une fois, à l'ingestion, et chaque morceau
  garde sa provenance. M7 et la table `jours` lisent un document par jour ; aucun lecteur
  ne choisit une copie au hasard. A laissait ce travail à chacun ; C anticipait la table
  d'AN2-2 en y mêlant des choix de lecture.
- **Training Status à part** : un bloc vaut pour sa date propre, qui peut précéder le
  fichier ; rangé au jour du fichier, une vue le lirait à la mauvaise date.
- **Les seuils dans les vues** : M7 les déclare en `ParameterSpec` et le backtest les fait
  varier ; la piste déclare les siens dans `analyse/` (AN2-2) ; `interim/days/` reste ce
  que la source dit. Les constantes d'`ingest/` sont des seuils de l'ingestion elle-même
  (tolérances, plages, codes), comme `MISMATCH_TOLERANCE_S`.
- **L'export de référence** : Garmin appauvrit les jours anciens au lieu de les corriger ;
  un export plus ancien et plus riche fait donc foi. À richesse égale, le plus récent ; et
  un jour sans mesure mais avec sa fenêtre passe devant un jour vide plus récent, qui lui
  ferait perdre sa fenêtre et ses séries.
- **L'instant propre et `strict`** : c'est la garde contre la fuite de données ; le
  backtest du moteur ne tient pour disponible que ce qui finit strictement avant l'origine
  `o_j` (`0010`, D2.5), minuit à Paris, qui est aussi, un jour ordinaire et la montre à
  l'heure de Paris, l'instant propre des grandeurs de la journée de la veille : les deux
  lectures doivent être possibles.
- **Un rang plutôt qu'un identifiant** : `0013` n'en garde aucun ; un rang suffit à voir
  une rupture.
- **Le format B** : aucune réingestion imposée ; M6b relit `interim/activities/` tel quel.
- **Deux mises en place, pas une** : l'écriture des activités ne change pas, ni ses
  octets ; si les jours ne prennent pas leur place après elle, les activités neuves
  restent justes, le message le dit, et relancer suffit.
- **Le contrôle des descripteurs de colonnes** : dans `activity_details`, les index des
  colonnes changent d'un fichier à l'autre ; dans les familles journalières, ils ont
  toujours dit la disposition lue ; un fichier qui en dirait une autre se refuse plutôt
  que de se lire de travers.

## Conséquences

- **Facile** : ajouter une vue sans toucher aux fichiers ; faire varier un seuil ; ajouter
  une famille, un champ ou une série (le contrat change de forme : le numéro de format
  aussi, et `interim/` se régénère depuis `raw/`, sans rien perdre).
- **Contraignant** : un gros module de contrats ; des vues qui parcourent les jours à
  chaque appel ; tous les documents des jours en mémoire jusqu'à leur écriture.
- **À revisiter** : une lecture « telle que connue à `t` » à travers les exports (la
  provenance de chaque objet et les exports gardés la laissent possible) ; un index par jour,
  si la table `jours` le demande ; la mémoire de l'ingestion, si des années de séries la
  rendent lourde ; l'appareil des jours face à celui des FIT, si une clé non identifiante
  apparaît.
