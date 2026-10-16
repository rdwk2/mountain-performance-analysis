# 0013 — Ingestion des activités et format d'`interim/`

- **Date** : 2026-10-09
- **Statut** : acceptée (AN1-1), avec les précisions de fin de document

## Contexte

Le moteur a écrit dès M1b les contrats que l'ingestion Garmin devait produire pour
M6b : `Activity` et `TrackPointStream`. Aucun producteur ne les remplit encore. Depuis
le 2026-10-06, l'ingestion (`raw/` → contrats → `interim/`) est écrite par la piste
analyse, aux conventions du moteur, et le moteur lit `interim/` par ses contrats,
jamais `processed/` (`docs/ROADMAP.md`, M6b). Le moteur a posé cinq conditions :

- (a) un contrat existant de `schemas/` ou de `gpx/` ne change qu'avec son accord ; un
  contrat neuf, dans un module neuf de `schemas/`, est libre ;
- (b) distance et profil s'obtiennent par `gpx/geo.py` et `gpx/profile.py`, jamais
  réimplémentés ;
- (c) le format d'`interim/` est l'interface que M6b consommera : contrat et lecteur
  dans `src/`, décrits ici, et relus par le moteur avant toute fusion qui les change ;
- (d) l'ingestion est sans dépendance : pydantic est écarté ; seul le décodage des FIT
  passe par une bibliothèque, déclarée à part (`0011`) ;
- (e) aucun test n'écrit dans le vrai `MPA_DATA_DIR` (`tests/conftest.py`).

Depuis le 2026-10-08, les séries d'une activité viennent du FIT, à pleine résolution :
les points espacés de `activity_details` coupent les lacets en montagne
(`docs/PIEGES_DATA.md`).

Ce que montre le FIT d'un export réel, et que les contrats existants ne savent pas
porter :

- **chaque canal peut manquer indépendamment des autres** : des enregistrements sans
  position (le GPS qui capte au départ, une perte de signal), plus rarement sans
  altitude ou sans FC. `TrackPointStream` exige au contraire que chaque série soit
  présente sur tous les points ;
- **le chronomètre a des pauses**, que portent les messages `event` ; aucun contrat ne
  les porte ;
- **l'altitude vient de `enhanced_altitude` ou de `altitude`** : `TrackPointStream` ne
  dit pas laquelle ;
- **un export peut contenir des activités d'un type sans famille de modèle** (de
  l'escalade ou du renforcement, par exemple). `Activity` exige un `Sport`,
  énumération fermée (`0003`) : elles n'y ont pas de place, alors que la charge
  d'entraînement et les questions de la piste en ont besoin ;
- **le codec du moteur** (écriture canonique en JSON, `0010` D14) ne sait écrire ni le
  `frozenset` d'`Activity` ni les `Sequence` de `TrackPointStream`.

Trois questions : ce que contient `interim/` et sous quels contrats ; comment le
moteur obtient les siens ; sous quel format les fichiers s'écrivent.

## Options envisagées

**Contrats.**

**A. `Activity` et `TrackPointStream` tels quels dans `interim/`.** L'ingestion écarte
les enregistrements incomplets et les activités sans `Sport`. Simple, mais le tri est
figé dans `interim/` pour tous les consommateurs : la FC d'avant la prise du GPS
disparaît, et les activités sans famille de modèle aussi ; et le codec devrait
apprendre `frozenset` et `Sequence`.

**B. Modifier les contrats du moteur** : des valeurs absentes point par point dans
`TrackPointStream`, un `Sport` facultatif dans `Activity`. Fidèle à la source, mais
chaque consommateur doit gérer les trous partout, et c'est la condition (a).

**C. Des contrats neufs, fidèles à la source, et les contrats du moteur comme des
vues** calculées à la lecture. Rien d'existant ne change ; deux formes du même contenu
coexistent, l'une dérivée de l'autre.

**Format.**

**A. Du JSON canonique, par le codec du moteur**, dont la partie générique passe dans
un module commun : un fichier par activité, plus un index. La relecture reconstruit
chaque contrat par son constructeur, donc revalide ses invariants.

**B. Du CSV par canal**, plus un JSON de métadonnées : il s'ouvre dans un tableur,
mais les fuseaux et les types se perdent, et il faut un second écrivain et un second
lecteur.

**C. Une base SQLite** (bibliothèque standard) : interrogeable, un seul fichier, mais
binaire, avec des migrations de schéma, et rien de tel dans le projet.

## Décision

Contrats : option C. Format : option A, en JSON brut.

**1. `interim/` est fidèle à la source.** Des contrats neufs, dans un module neuf de
`schemas/` (nom fixé par le brief d'AN1), écrits avec des `tuple`, des `StrEnum`, des
instants et des dataclasses, que le codec écrit déjà :

- **l'activité de l'index**, pour toutes les activités de l'export, quel que soit leur
  type : identifiant de la source, type de la source tel quel, départ (*aware*, dans
  son fuseau local à décalage fixe, `0006`), durées écoulée et en mouvement, distance,
  D+ et D−, FC moyenne et maximale (les champs que la source peut omettre sont
  facultatifs), référence à l'enregistrement s'il existe, provenance avec l'instant
  d'acquisition de l'export (point 5). L'index garde les valeurs de la source sans
  leur imposer les invariants qu'`Activity` pose entre champs (point 2) ;
- **l'enregistrement d'une activité**, tiré de son FIT :
  - un **canal par grandeur**, chacun avec son propre temps (secondes depuis le
    départ, strictement croissant, valeurs finies et dans leurs plages) : positions
    (`position_lat`, `position_long`, converties des semicercles en degrés à la
    lecture), altitude (`enhanced_altitude`, ou `altitude` à défaut, et le champ
    d'origine dit), distance cumulée de la source (croissante au sens large), FC,
    vitesse du capteur (`enhanced_speed`, pour diagnostic seulement : le moteur
    calcule la vitesse sur les positions) ;
  - la **session** : sport et sous-sport de la source, départ, temps écoulé, temps du
    chronomètre, distance totale ;
  - les **arrêts et reprises du chronomètre** (messages `event`) ;
  - la **provenance de l'appareil** (`file_id`) : type de fichier, fabricant, produit,
    date de création, et la version du firmware de la montre (`device_info`), dont la
    charte a besoin (§ 11). **Ni numéro de série ni identifiant de l'appareil** ;
  - les suspicions (`QualityFlag`), et le compte des échantillons écartés par canal,
    avec leur motif.

Un canal absent du fichier est absent de l'enregistrement. Rien n'est interpolé.

**2. Les contrats du moteur sont des vues**, calculées par des fonctions de `ingest/`,
sans dépendance et testées :

- `Activity`, pour les seules activités dont le type a une famille de modèle
  (`Sport`), dont l'index porte tous les champs qu'`Activity` exige, et dont les
  valeurs satisfont ses invariants (FC moyenne au plus égale à la maximale, temps en
  mouvement au plus égal au temps écoulé…) ; les autres n'ont pas de vue, et le
  rapport d'ingestion les compte avec leur motif. La correspondance entre types de la
  source et `Sport` est une table de `ingest/`, fixée par le brief d'AN1 et relue par
  le moteur ; un type absent de la table n'a pas de vue ;
- `TrackPointStream`, aux seuls instants où tous les canaux demandés sont présents
  (les positions toujours ; l'altitude, la FC, la distance, la vitesse à la demande).
  Les instants écartés se comptent ; un trou de positions plus long qu'un seuil porte
  `GPS_GAP` (seuil fixé par le brief d'AN1, relu par le moteur), et un instant écarté
  faute d'un autre canal demandé se compte, sans drapeau ; un enregistrement sans
  aucun instant complet n'a pas de vue.

Le moteur lit `interim/` par ces vues et par le lecteur d'`interim/`, jamais en
ouvrant les fichiers lui-même. Les distances et les profils se recalculent sur les
positions par `gpx/geo.py` et `gpx/profile.py` ; la distance de la source ne sert
qu'au diagnostic.

**3. Les fichiers.** Sous `MPA_DATA_DIR/interim/activities/` : un fichier d'index, un
fichier par enregistrement, et le rapport de la dernière ingestion (fichiers lus et
leurs empreintes, fichiers refusés et leur motif). Chaque fichier est un document JSON
canonique (`{"type", "format", "data"}`), écrit et relu par l'enveloppe commune du
codec (point 4) ; la relecture revalide le contrat et vérifie que la réécriture
redonne les mêmes octets. Un numéro de format propre à `interim/` change à chaque
changement de contrat. Pas de compression au départ.

**4. Le codec devient commun.** Sa partie générique (`encode_value`, `decode_value`,
`encode_contract`, `decode_contract`, `canonical_bytes`, `content_hash`, `CodecError`,
`NON_FINITE_TEXTS` et leurs aides) passe de `backtest/codec.py` à
`src/mountain_perf/codec.py`, avec l'enveloppe des documents, paramétrée par les types
admis et le numéro de format : le registre l'appelle avec les siens, `interim/` avec
les siens. Ce changement précède le code d'AN1 ; il se fait avec l'accord du moteur,
sans changement de comportement du registre, amende les tests d'imports du codec
(`tests/test_backtest_registry_imports.py`) et ajoute ceux du module commun. `ingest/`
importe le module commun, jamais `backtest/`.

**5. Règles d'ingestion.**

- Seule la commande d'ingestion écrit dans `interim/` ; elle ne lit que `raw/`,
  qu'elle n'écrit jamais. Supprimer `interim/` ne perd rien.
- Deux ingestions des mêmes fichiers bruts écrivent les mêmes octets : aucun instant
  d'exécution dans `interim/`. L'instant d'acquisition (`retrieved_at` de `SourceRef`)
  est celui de l'export : rangé dans `raw/` avec lui au moment de l'acquisition (par
  la commande d'acquisition, ou à la main pour un export manuel ; forme fixée par le
  brief d'AN1), lu par l'ingestion et recopié dans l'index, d'où les vues le
  reprennent ; jamais l'instant de l'ingestion ou d'une lecture, ni la date de
  modification d'un fichier. Les lecteurs de fichiers du moteur y mettent, eux,
  l'instant de lecture : un consommateur ne compare pas les `retrieved_at` de
  producteurs différents (le contrat le dira si le moteur le demande, condition (a)).
  Un export sans instant d'acquisition est refusé, et le rapport le dit.
- Lecture stricte des FIT (`0011`) : un fichier refusé n'a pas d'enregistrement,
  son activité reste dans l'index, et le rapport dit pourquoi.
- Le contrat est strict, l'ingestion tolérante et tracée : un échantillon hors plage,
  ou dont l'instant ne suit pas strictement celui du dernier échantillon gardé, est
  écarté et compté, jamais corrigé en silence ; de même, un champ de l'index hors de
  sa plage est omis et compté.
- Rien d'autre que ce dont les contrats ont besoin : ni nom de l'athlète, ni titre ou
  lieu d'activité, ni identifiant d'utilisateur ou d'appareil.
- Une activité sans FIT, ou dont le FIT n'a pas d'enregistrement, a une entrée d'index
  sans enregistrement.

**6. Périmètre.** Ce record couvre les activités : l'index et les FIT. Les données
journalières (sommeil, HRV, FC de repos, indicateurs de Garmin) le compléteront avec
AN2. `activity_details`, `activity_splits` et `activity_weather` ne sont pas ingérés
en AN1.

## Pourquoi

- **C plutôt que A** : `interim/` est la base de tout ce qui suit. Un tri fait à
  l'ingestion se répercute sur toutes les questions, et une donnée écartée là ne
  revient qu'en refaisant le contrat. Les activités sans famille de modèle comptent
  pour la charge et pour les questions de récupération.
- **C plutôt que B** : rien ne change dans les contrats du moteur, et M6b reçoit
  exactement ce qu'il a prévu. Les deux formes ne sont pas deux vérités : la vue se
  calcule toujours depuis `interim/`, et rien ne l'écrit.
- **Format A** : le codec existe, il est testé, il écrit les flottants à l'identique
  (aller-retour exact), et sa relecture revalide les contrats. B et C ajouteraient un
  format et deux programmes de plus.
- **Un module commun plutôt qu'un import depuis `backtest/`** : importer
  `backtest/codec.py` depuis `ingest/` chargerait tout le paquet `backtest`, et un
  test du moteur l'interdit, à raison. Réutiliser du code qui n'est pas déclaré commun
  finit par lier des modules qui n'ont rien à voir.
- **JSON brut** : en JSON canonique, un enregistrement à la seconde de six canaux pèse
  de l'ordre de 65 octets (mesuré sur des séries synthétiques), soit quelques
  mégaoctets pour une sortie de dix heures ; la compression le divise par trois
  environ (mêmes séries), mais rend les fichiers illisibles sans outil et ajoute une
  couche. Elle ne touche que l'écrivain et le lecteur, pas les contrats : elle peut
  venir plus tard.

## Conséquences

- **Facile** : ajouter une activité, un canal ou un champ, en régénérant `interim/`
  (un changement de contrat change le numéro de format, et le codec refuse un document
  à l'ancien format) ; donner au moteur une autre vue sans toucher aux fichiers.
- **Contraignant** : deux formes du flux, et des fonctions de vue à tester ; le codec
  rendu commun avant le code d'AN1 ; une table des types de la source à tenir.
- **À revisiter** : la compression, si `interim/` dépasse le gigaoctet ; d'autres
  modules du moteur à rendre communs, au moment où un second utilisateur en a besoin,
  jamais avant ; les données journalières, à AN2 ; la nature 2D ou 3D de la distance
  de la source (`BACKLOG`, M6b), que les canaux de positions et de distance permettent
  de mesurer.

## Précisions d'AN1-1

*Ajoutées par la PR AN1-1, qui fait passer ce record de « proposée » à « acceptée ».
Mesurées sur un export réel, sans chiffre ici (règle 1).*

1. **Modules.** Les contrats sont dans `schemas/interim.py` : l'index
   (`IndexedActivity`, `ActivityIndex`), l'enregistrement (`ActivityRecording`, ses
   canaux `PositionChannel`, `ElevationChannel`, `DistanceChannel`, `HeartRateChannel`,
   `SpeedChannel`, `TemperatureChannel`, ses sessions `RecordingSession`, ses événements `TimerEvent`, son
   appareil `DeviceProvenance`, ses écarts `DiscardCount`) et le rapport
   (`IngestionReport`, avec `ViewRefusalCount` et `RecordingMismatch`). Le code est
   dans `ingest/` : `types.py` (la table des types),
   `views.py` (les vues), `interim.py` (les documents), `index.py`, `fit.py` (seul
   importeur de fitdecode) et `export.py` (l'ingestion d'un export).
2. **Plusieurs sessions.** Un FIT multisport porte plusieurs sessions : l'enregistrement
   en porte la suite, et son départ est celui de la plus ancienne ; tous ses temps en
   partent.
3. **Instants.** Ceux de l'enregistrement sont en UTC ; l'heure locale d'une activité
   est celle de l'index, seule source de vérité pour elle.
4. **Le champ écrit.** fitdecode déduit `enhanced_altitude` d'`altitude`, et
   `enhanced_speed` de `speed`, par expansion de composants : seul un champ écrit dans
   le fichier compte. L'altitude vient d'`enhanced_altitude` si un `record` du fichier
   y écrit une valeur, sinon d'`altitude` ; la vitesse, d'`enhanced_speed`, sinon de `speed` ; le
   champ retenu est dit, et l'autre ne s'y mêle pas ; une valeur écrite dans l'autre
   champ, sans le champ retenu, est comptée. Une valeur invalide du FIT n'est pas une
   valeur.
5. **Écarts, dans cet ordre, par canal** : échantillon sans horodatage ; instant avant
   le départ ; instant qui ne suit pas strictement celui du dernier échantillon gardé,
   compté comme doublon s'il en répète la valeur à cet instant ; latitude sans
   longitude ou l'inverse ; zéro brut du codage FIT (altitude de −500 m exactement,
   position (0°, 0°)) ; valeur non finie ou hors plage ; distance inférieure à la
   dernière gardée. Un échantillon écarté ne devient pas le dernier gardé. Les
   événements du chronomètre : sans horodatage ; avant le départ ; antérieur au dernier
   gardé (deux événements au même instant sont gardés) ; type inconnu. Un champ de
   l'index inutilisable est omis et nommé dans son entrée (`omitted_fields`) ; le
   rapport ne le compte pas (ce qui précise « omis et compté », plus haut).
6. **Drapeaux.** L'enregistrement n'en porte pas. Seul `GPS_GAP` existe en AN1-1 : la
   vue `TrackPointStream` le pose quand deux de ses instants consécutifs sont séparés de
   plus de 10 s, le trou du moteur (`0010` D4.4) ; les trous du canal des positions y
   sont tous, plus ceux que l'intersection avec les canaux demandés crée (ce qui précise
   le point 2 : un instant écarté faute d'un autre canal n'a pas de drapeau propre, mais
   le trou qu'il laisse dans la vue pose `GPS_GAP`). Une pause du chronomètre le pose
   aussi quand elle laisse plus de 10 s sans instant dans la vue : la vue ne lit pas le
   chronomètre. Le drapeau ne sert pas à écarter un flux : les trous se lisent sur les
   instants, leur cause sur les événements du chronomètre. Les autres détecteurs
   viendront avec leur usage.
7. **Table des types** : `ingest/types.py` (`SOURCE_TYPE_SPORTS`), relue par le moteur ;
   les exclusions voulues sont écrites dans sa docstring. Le rapport compte les
   entrées sans vue `Activity`, par motif et par type de la source (point 2), et
   `mperf ingest` les affiche : un type absent de la table se voit au premier export
   qui le porte.
8. **Fichiers** : `interim/activities/index.json`, `report.json` et
   `recordings/<identifiant>.json`, écrits dans un dossier voisin puis mis en place
   ensemble.
9. **Instant d'acquisition** : `raw/acquisition.json`, un objet à la seule clé
   `retrieved_at` (instant ISO 8601 avec fuseau). Absent ou illisible, `mperf ingest`
   s'arrête et n'écrit rien (plutôt qu'un rapport, point 5).
10. **Un seul export**, à la racine de `raw/` ; plusieurs exports, et lequel fait foi,
    viendront avec l'acquisition. Un identifiant répété dans l'index fait refuser
    toutes ses entrées ; plusieurs archives au même nom sans extension sont toutes
    refusées.
11. **`SourceRef`** : sa docstring dit que chaque producteur met dans `retrieved_at` son
    propre instant d'acquisition (condition (a), accord du moteur).
12. **L'index et le FIT.** Le rapport compte les enregistrements dont le départ, ou la
    somme des temps écoulés des sessions, diffère de plus de 1 s de ceux de l'entrée ;
    rien n'est refusé. L'index dit si Garmin Connect a recalé l'altitude
    (`elevation_corrected`) : son D+ vient alors d'un modèle de terrain, et ne se
    compare pas à l'altitude du FIT, que la correction ne change pas.
13. **Capteurs, pauses, température.** L'appareil dit si le fichier décrit un baromètre
    parmi ses capteurs internes, et un capteur de FC externe (ANT+ ou Bluetooth Low
    Energy) ; chaque événement du chronomètre, son déclencheur (l'athlète, la pause
    automatique, un appareil de fitness) quand le fichier l'écrit. La température du
    capteur de la montre est un canal : chauffée par le corps, ce n'est pas celle de
    l'air (charte, § 12) ; la vue `TrackPointStream` ne la porte pas.
