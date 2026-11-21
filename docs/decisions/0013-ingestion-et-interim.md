# 0013 — Ingestion des activités et format d'`interim/`

- **Date** : 2026-10-09
- **Statut** : acceptée (AN1-1), avec les précisions de fin de document (AN1-1,
  AN2-0 et AN2-1)

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
    *AN2-0 : la disposition des précisions 9 et 10 (un seul export, à la racine de
    `raw/`) est remplacée par les précisions 14 et 15 (plusieurs exports, chacun
    dans son dossier, venus avant l'acquisition) ; la forme d'`acquisition.json`
    (précision 9) et les règles de doublons de la précision 10 (entrées, archives)
    valent pour chaque export.*
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

## Précisions d'AN2-0

*Ajoutées par la PR AN2-0 (plusieurs exports pour les activités), avec l'accord du
moteur (conditions (a) et (c)). Elles remplacent la disposition à un seul export
des précisions 9 et 10, dont la forme d'`acquisition.json` et les règles de
doublons d'entrées et d'archives valent pour chaque export ; elles disent comment
se lisent les points 1 et 5 ; le reste du record ne change pas. Mesurées sur deux
exports réels, sans chiffre ici (règle 1).*

14. **Plusieurs exports.** L'ingestion lit tous les exports Garmin rangés sous
    `raw/garmin/`, chacun dans son dossier, `raw/garmin/<export>/` : son
    `acquisition.json` (sous la forme de la précision 9), son index et ses archives.
    Le nom du dossier ne sert qu'au rapport (lettres et chiffres ASCII, `_`, `.`,
    `-`) ; `activities` et `acquisition.json` sont réservés : dans `raw/garmin/`,
    ces deux noms désignent un export laissé à plat. Les autres dossiers de
    `raw/` appartiennent aux autres sources (charte,
    § 12) : l'ingestion des activités les ignore, comme un fichier posé dans
    `raw/garmin/`. Arrêtent l'ingestion, qui n'écrit rien et nomme l'export : un
    export laissé à plat, dans `raw/` ou dans `raw/garmin/` ; aucun export ; un nom
    de dossier hors de ces caractères ; un dossier sans `acquisition.json` ; deux
    exports au même instant d'acquisition ; une entrée gardée de l'index partie
    après l'instant d'acquisition de son export (partie à cet instant même, elle
    est admise ; une entrée refusée ne compte pas). **Aucun export ne se retire de `raw/`** : Garmin ne garde le détail des
    jours que sur une période récente, et un export ancien reste la seule source de
    ce qu'il a effacé. L'export unique d'AN1-1, rangé à la racine de `raw/`, se
    déplace une fois dans son dossier, par l'humain (copie vérifiée par empreinte,
    retrait de la racine ensuite) ; le déplacement ne change aucun fichier brut.
15. **Lequel fait foi.** Les exports se rangent par instant d'acquisition. La période
    d'un export va du premier départ de ses entrées gardées à son instant
    d'acquisition, bornes comprises. L'existence d'une activité se décide sur
    l'export le plus récent dont la période couvre son départ : absente de lui,
    elle n'est pas ingérée, et le rapport la compte « retirée de la source » (une
    activité supprimée dans Garmin Connect ne revient pas depuis un ancien export ;
    une entrée refusée dans cet export compte de même). Présente, son entrée vient
    de cet export. Son enregistrement vient de l'archive de cet export ; si elle
    manque, n'est pas un seul FIT lisible, ou si son FIT est refusé, des archives
    des autres exports, du plus récent au plus ancien : la première dont le FIT se
    lit. Garmin réécrit l'archive d'un FIT à chaque téléchargement, pas le FIT :
    deux exports se comparent par le membre `.fit`. Les mêmes exports, listés dans
    un autre ordre, donnent les mêmes octets.
16. **La provenance par export.** L'index porte la provenance de chaque export (son
    fichier d'index, son empreinte, son instant d'acquisition), et chaque entrée
    celle de l'export dont elle vient. La vue `Activity` reprend celle de l'entrée :
    `activity_view` ne prend plus l'index. Une activité dont l'entrée et l'archive
    viennent de deux exports garde son `activity_ref`, avec deux `source` dont
    les instants d'acquisition diffèrent (`Activity.source` et
    `TrackPointStream.source`). `Activity`,
    `TrackPointStream` et `SourceRef` ne changent pas. Le point 1 se lit ainsi :
    l'index porte les activités de tous les exports, sauf les entrées refusées et
    les activités retirées de la source. Le point 5 aussi : l'instant d'acquisition
    d'un export fait à la main peut se reconstituer après coup, par l'humain, sur
    les dates des fichiers de l'export (la fin de son dernier passage) ; jamais par
    l'ingestion.
17. **La charge selon Garmin.** `IndexedActivity` porte `training_load`
    (`activityTrainingLoad`), sans unité, `>= 0`, zéro gardé : clé absente ou
    `null`, champ absent ; valeur non numérique, non finie ou négative, champ absent
    et nommé dans `omitted_fields`. Seules les anciennes clés de l'index se lisent :
    une clé doublée en `is…` (`isElevationCorrected`…) ne change rien, et ne
    remplace pas l'ancienne qui manque.
18. **Le rapport** compte en plus, par export, son nom, sa provenance, le début de
    sa période, ses entrées gardées et refusées, ses archives ; les activités
    retirées de la source ; par champ de l'index, les activités dont l'entrée d'un
    autre export diffère ; les activités aux FIT différents ; les enregistrements
    tirés d'un autre export que leur entrée. Les noms des fichiers lus et refusés
    partent de `raw/` : `garmin/<export>/…`. Une archive se juge sur l'index de son
    export.
19. **Format.** `INTERIM_FORMAT_VERSION` passe à 2 : le lecteur refuse un document
    du format 1, et `interim/` se régénère (`just ingest`, puis `just process` pour
    `processed/`). Aucun type de document neuf.
20. **La mise en place.** Si le nouveau dossier ne prend pas la place
    d'`interim/activities/` (un fichier tenu ailleurs, sous Windows), l'ancien
    reprend la sienne, comme les tables de `processed/` (`write_tables`).

## Précisions d'AN2-1

*Ajoutées par la PR AN2-1 (les données journalières), avec l'accord du moteur
(condition (c)). Le contrat des activités ne change pas : `interim/activities/`
s'écrit à l'octet comme en AN2-0 pour les mêmes exports.*

21. **Périmètre.** Les données journalières annoncées au point 6 sont dans
    `interim/days/`, décrites par `0018` ; ce record reste celui des activités. Le
    point « À revisiter : les données journalières, à AN2 » est fait.
22. **Le numéro de format.** « Un changement de contrat change le numéro de format »
    (point 3 et Conséquences) se lit ainsi : `INTERIM_FORMAT_VERSION` change au
    changement de **forme ou de sens** d'un contrat existant (un champ ajouté, retiré
    ou retypé, et aussi un champ dont l'unité ou la définition change sans changer de
    type : sans numéro neuf, un ancien document se relirait avec le sens neuf, en
    silence). Il ne change pas à l'ajout d'un type de document : un type neuf se
    déclare avec son premier format (`INTERIM_DOCUMENT_FIRST_FORMAT`,
    `ingest/interim.py`), et les documents existants restent lisibles sans
    réingestion. Les trois types des jours entrent au format 2.
23. **Deux mises en place.** `mperf ingest` calcule les activités et les jours avant
    la moindre écriture, puis met en place `interim/activities/` (précision 20), puis
    `interim/days/`, de la même façon. Une erreur avant l'écriture n'écrit rien. Si les
    jours ne prennent pas leur place après les activités, le message le dit, et
    relancer la commande remet tout en ordre (`0018`).

## Précisions d'AN1-3

*Ajoutées par la PR AN1-3 (l'ingestion d'une archive Strava), écrite par le moteur
avec l'accord de la piste (relais 51, 52 et 54). Sur des exports Garmin seuls,
`interim/` et `processed/` s'écrivent à l'octet comme avant. Mesurées sur une archive
réelle, sans chiffre ici (règle 1).*

24. **Le format.** `INTERIM_FORMAT_VERSION` reste 2. Un type de document neuf
    (`SourcesReport`), un membre ajouté à une énumération fermée
    (`RefusalReason.NOT_A_GZIP_FIT`), et des descriptions élargies à la source Strava,
    sans changer leur sens pour Garmin (les noms sous `raw/strava/` :
    `ExportReport.name`, `ReadFile.name`, `IngestionReport.read`,
    `DaysExportReport.name` ; `ExportReport.archives` ; `RetiredActivity` et son
    « Non promis » ; `IndexedActivity.activity_ref`, `start_time`,
    `source_activity_type`, son producteur et son « Non promis » ; sept
    descriptions d'`IndexField` ; au regard de la précision 22) ne changent pas le sens des
    documents écrits avant : ils se relisent tels quels. Un champ ajouté, retiré,
    retypé ou redéfini d'un contrat existant, ou la définition changée d'une valeur
    d'énumération, demandent toujours un numéro neuf.
25. **Les exports Strava.** `raw/strava/<export>/` : l'archive de Strava telle
    qu'envoyée (un seul `.zip`, jamais décompressé ni retouché) et `acquisition.json`
    (la forme de la précision 9, plus la clé facultative `timezone`, un nom IANA,
    propre à Strava). Arrêtent l'ingestion, qui n'écrit rien et nomme le fichier : une
    archive ou un `acquisition.json` posé à plat dans `raw/strava/` ; un nom de dossier
    hors des caractères de la précision 14 ; un `acquisition.json` absent, illisible,
    d'une autre forme, ou dont le fuseau est inconnu ; aucun zip, ou plusieurs ; une
    archive illisible ; `activities.csv` absent, illisible ou pas en UTF-8 ; un en-tête
    différent ; une ligne gardée partie après l'instant d'acquisition ; un même nom de
    dossier sous `raw/garmin/` et `raw/strava/` ; deux exports au même instant
    d'acquisition, toutes sources confondues ; ni export Garmin ni archive Strava.
    Aucun export ne se retire. Seuls `activities.csv` et les fichiers que sa colonne
    `Filename` nomme s'ouvrent : le reste de l'archive porte des données personnelles.
26. **L'index Strava.** L'en-tête d'`activities.csv` se vérifie en entier (104 noms,
    dans l'ordre, doublons compris). Se lisent, par rang, l'identifiant, la date, le
    type, le fichier, et la seconde colonne de chaque nom en double qu'un contrat lit
    (temps écoulé, distance en mètres, FC maximale), avec le temps en mouvement, le
    D+, le D− et la FC moyenne ; rien d'autre (ni nom, ni description, ni note, ni
    matériel, ni météo). La date est en UTC, lue sans la locale (mois anglais). Le
    fuseau d'une entrée : celui de son FIT (`activity.local_timestamp − timestamp`),
    sinon celui de `timezone`, sinon `Europe/Paris`, compté. `activity_ref` vaut
    `strava-<id>` ; `elevation_corrected` et `training_load` sont absents (des
    valeurs de Garmin). Les types de Strava sont dans la table des types, « Ride »
    hors table.
27. **Garmin d'abord.** L'existence se décide par source (la précision 15 entre
    exports Garmin, la même entre exports Strava) ; puis une activité Strava appariée
    à une activité Garmin gardée — par l'empreinte du FIT, sinon par l'identité
    (fabricant, produit, création) et le départ, sinon par le départ seul pour le
    fabricant `garmin`, toujours un pour un — n'a pas d'entrée : l'entrée et
    l'enregistrement de Garmin font foi ; un FIT d'un appareil Garmin non apparié,
    parti dans la période d'un export Garmin, est retiré de la source (l'export de
    `RetiredActivity` est l'export Garmin le plus récent qui couvre son départ) ; le
    reste devient une entrée Strava. **Une entrée Strava qu'un export Garmin plus
    récent porte devient l'entrée Garmin : son `activity_ref` change, et tout ce qui
    la cite (manifestes, registre, positions des parcours, `deja_vu.csv`) se relit à
    l'identifiant Garmin.** **Deux limites dites** : une ligne Strava sans FIT lisible
    (sans fichier, `Filename` d'une autre forme qu'`activities/<nom>`, GPX, membre
    absent, pas gzip, FIT refusé) ne s'apparie à rien et devient une entrée Strava,
    même si un export Garmin porte la même sortie (deux entrées) ; un FIT Garmin
    refusé dont la copie Strava se lit par tolérance s'apparie, et l'activité reste
    sans enregistrement (« Garmin d'abord »). **Le cas « manque »** : une activité
    Garmin sans enregistrement — sans archive, ou dont le FIT est refusé et n'a pas
    les mêmes octets que sa copie Strava — n'a que les empreintes de ses membres
    pour l'appariement ; sa copie Strava ne s'y relie pas et, d'un appareil Garmin
    et partie dans la période d'un export Garmin, elle est retirée comme « absente
    de Garmin » alors que Garmin porte l'activité, qui reste sans enregistrement.
28. **Le rapport.** `sources.json` (`SourcesReport`), écrit seulement s'il y a un
    export Strava ; les noms des fichiers lus partent de `raw/`
    (`strava/<export>/<zip>/…`) ; un `.fit.gz` absent du zip : une entrée sans
    archive ; présent mais pas gzip : `NOT_A_GZIP_FIT`. Un `Filename` d'une autre
    forme que `activities/<nom>` : la ligne est gardée, sans fichier ; un membre nommé
    par plusieurs lignes se lit une fois ; si plusieurs de ces lignes deviennent des
    entrées, seule la première, par identifiant croissant, reçoit l'enregistrement,
    les autres restent sans enregistrement (`shared_file_entries`). `sources.json`
    compte aussi les entrées Strava sans enregistrement parties dans la période d'un
    export Garmin (`possible_duplicates`) : des doublons possibles, la première
    limite de la précision 27 rendue visible ; une même entrée peut compter dans les
    deux. Entre exports Strava, ni les champs ni les FIT ne se comparent.
29. **Sans export Garmin.** Le rapport des jours nomme les exports Strava, sans jour ;
    `jours` n'a pas de ligne, et l'instant d'acquisition des tables est celui du
    dernier export Strava.
30. **La lecture tolérante bornée**, pour les seuls FIT d'une archive Strava (un FIT
    d'un export Garmin reste lu strictement) : la seule exception à la lecture stricte
    (`0011`). Une seconde lecture, le CRC toujours strict et les erreurs en alerte,
    garde un FIT dont la lecture stricte échoue si chaque alerte est celle d'une
    définition de champ dont la taille n'est pas un multiple de son type, rattachée à
    sa définition, et si chaque champ ainsi malformé est d'un message que le contrat
    ne lit pas (ni `record`, `session`, `file_id`, `device_info`, `activity` ou
    `event`) ou est le champ `data` du message `event`. Chaque champ sauté est compté
    dans `sources.json`. Un `event.data` sauté donne `TimerEvent.trigger = None`, que
    les tables comptent comme « pas une pause automatique » (`auto_pause_count`) : 0,
    et non « inconnu ».
