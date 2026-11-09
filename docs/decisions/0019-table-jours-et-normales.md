# 0019 — La table `jours` et les normales

- **Date** : 2026-11-05
- **Statut** : acceptée (AN2-2)

## Contexte

`0018` a mis les données journalières dans `interim/days/` : un document par jour,
Training Status à part, le rapport des jours, et des vues qui calculent à la lecture
tout ce qui demande un seuil (`ingest/day_views.py`). Il annonçait le consommateur de
la piste : la table `jours`, ses normales, puis la page de récupération (AN2-3), qui
lira `jours` sans rien calculer (règle 7). La charte fixait le cadre : une série journalière
vit sur tous les jours du calendrier, jours manquants compris (§ 4 bis, point 7) ; la
nuit appartient au jour du réveil (§ 4) ; une normale manque sans assez de jours sur sa
fenêtre (§ 3) ; les jours `maladie` et `blessure` du journal sortent des normales par
défaut (§ 3) ; un changement de montre est une rupture d'office, l'intervalle incertain
exclu des fenêtres (§ 11).

La passe experte des définitions d'AN2 a fixé les validités des
grandeurs d'un jour, la règle des normales (la fenêtre des jours qui précèdent, le jour
lui-même exclu, un minimum de jours admis, la médiane, une dispersion robuste, la HRV en
log) et ce qui les rompt. Restaient à fixer : ce que porte une ligne, et comment la tirer
d'`interim/` ; quels jours entrent dans une normale ; ce que fait une rupture ; le
journal de l'athlète (`journal.csv`, charte, § 3), que rien ne lisait encore ; la durée
du calcul : les vues des jours parcourent tous les documents qu'on leur passe (`0018`,
« Contraignant ») ; appelées pour chaque jour sur toute la suite, leur coût croît comme
le carré du nombre de jours.

## Options envisagées

**Une rupture** (un changement de montre, ou de version d'algorithme de la famille de la
mesure).

**A. La rupture d'office** (charte, § 11) : la normale repart après la
dernière rupture, l'intervalle incertain exclu des fenêtres. C'est la règle d'une
question qui compare des périodes ; sur la page, la normale manquerait après chaque
changement, le temps que la fenêtre se remplisse, et de nouveau au retour à une montre
déjà vue.

**B. La normale continue, avec des avertissements** (décision de rdw, à l'ouverture
d'AN2-2) :
une rupture n'exclut rien ; la ligne la marque, ainsi que les jours incertains et la
normale dont la fenêtre mêle l'avant et l'après. Un écart à la rupture d'office de la
charte, pour la seule normale de `jours`.

**Une nuit courte** (sous le sommeil mesuré déclaré, `days.short_sleep_s`).

**A. Exclue de toutes les normales de nuit** : un filtre de qualité pour la
HRV, le stress, la respiration et la SpO2 de la nuit ; pour le sommeil mesuré, le
drapeau se lit sur la mesure elle-même.

**B. Admise dans la normale du sommeil mesuré, exclue des autres** (décision de rdw, à
l'ouverture d'AN2-2). Un écart à A, que proposait la passe experte, pour cette seule
normale.

**La durée.**

**A. Un index par jour dans `ingest/day_views.py`** : une interface neuve des vues, un
point de contact avec le moteur, dont M7 lira ces vues.

**B. Une tranche bornée** : `analyse/` passe à chaque vue les seuls documents qu'elle
lit, sauf une série de nuit étirée sur plus d'un jour (au-delà de `[d − 1, d + 1]`), et
les vues ne changent pas.

## Décision

Rupture B, nuit courte B, durée B. `mperf tables` écrit une quatrième table,
`processed/jours.parquet`, avec les trois autres, dont les lignes ne changent pas ; ses
normales, leurs paramètres et le lecteur du journal sont dans `analyse/`.

### La table et ses lignes

Le contrat de la ligne est `DayRow` (`schemas/processed.py`), publié par le
dictionnaire de données ; `analyse/days.py` la calcule (`day_rows`), `analyse/tables.py`
la met dans les tables (`Tables.days`, et le résumé `Tables.day_summary`, un
`DaySummary`).

- **Une ligne par jour du calendrier**, du premier au dernier document d'`interim/days/`,
  bornes comprises ; la clé est le jour (`day`), les lignes sont triées par jour. Un jour
  de l'étendue sans document a sa ligne, d'état `absent` (`DayRowState` : `absent`, puis
  les quatre états de `DayState`) : ni fenêtre, ni export de référence, ni rang, ni nuit,
  ni valeur du jour ; elle porte Training Status, le journal, l'activité du jour,
  `uncertain_device` et sa normale ; ses comptes de siestes et d'entrées de Training
  Readiness valent 0, sans rien dire du jour. Un `interim/days/` sans document donne une
  table vide.
- **Les groupes de colonnes**, dans l'ordre du contrat :
  - **le jour** : son état, le début de sa fenêtre et la fin des données, l'export de
    référence, les rangs des appareils du jour et le jour incertain
    (`uncertain_device`), les versions d'algorithme ;
  - **la nuit rattachée au jour** : ses bornes, son état et ses drapeaux `short` et
    `shifted` (avec le motif d'un drapeau inconnu), le sommeil mesuré, les phases,
    l'éveil, le non mesurable et sa part, la confirmation de la fenêtre, les résumés de
    Garmin (score, stress, FC moyenne, variation du Body Battery, moments agités), l'écart
    de température cutanée, et ce que la ligne tire de la série du Body Battery ;
  - **les siestes** : leur nombre, la somme des durées de leurs fenêtres, la somme de
    leurs sommeils selon Garmin, celles qui recoupent la nuit ;
  - **les valeurs du jour** : la FC de repos et son statut, la HRV selon Garmin (la nuit,
    la semaine, le statut, les bornes), la respiration, la SpO2, le stress du jour, sa
    durée mesurée et sa validité, le Body Battery du jour, les totaux d'activité ;
  - **Training Readiness du réveil** : score, niveau, instant de l'entrée retenue, son
    motif d'absence, et le nombre d'entrées du jour ;
  - **Training Status**, les cinq sortes ;
  - **le journal** : les types des événements qui couvrent le jour ;
  - **l'activité du jour** ;
  - **les normales** de six mesures, chacune avec son admission, sa normale, sa plage,
    sa dispersion, ses jours admis, son motif d'absence, son segment, sa rupture et sa
    normale à cheval.
- Une grandeur absente est un manque, jamais un zéro, sauf les durées de l'activité du
  jour, sommes des seules activités qui en ont (0 si aucune n'en a), que complète
  `activities_without_elapsed` ; une valeur « selon Garmin » est celle du document du
  jour, sans rien de recalculé. Un instant s'écrit en deux
  colonnes, l'heure murale et le décalage (`0014`), toutes deux nulles quand il manque.

### Les vues et leurs seuils

Les états, les drapeaux et les statuts viennent des vues d'AN2-1 (`night_assessment`,
`resting_hr_on`, `readiness_on_waking`, `series_between`), appelées avec des seuils
déclarés dans `analyse/days.py` (`DAY_VIEW_PARAMETER_SPECS`), communs à tous les
athlètes, que la provenance porte sous `days.<nom>` :

| Paramètre | Défaut | Rôle |
|---|---|---|
| `days.max_unmeasured_fraction` | 0,20 | au-delà de cette part non mesurable du temps au lit, la nuit est `partial` |
| `days.short_sleep_s` | 14 400 s | sous ce sommeil mesuré, la nuit est `short` |
| `days.shift_s` | 14 400 s | au-delà de cet écart au milieu habituel, la nuit est `shifted` |
| `days.usual_window_days` | 28 jours | la fenêtre du milieu habituel de la nuit |
| `days.usual_min_nights` | 14 nuits | le minimum de nuits du milieu habituel |
| `days.resting_hr_min_sleep_s` | 10 800 s | sous ce sommeil mesuré, la FC de repos est `no_night` |
| `days.readiness_tolerance_s` | 900 s | la tolérance de Training Readiness du réveil |
| `days.stress_min_fraction` | 0,5 | la part de la fenêtre du jour qui valide le stress du jour |
| `days.min_coverage_fraction` | 0,8 | la couverture minimale d'une grandeur tirée d'une série |
| `days.night_body_battery_step_s` | 180 s | le pas de la série du Body Battery, une résolution déclarée de la source |

`DayDefinition(views, normals)` réunit ces seuils et les paramètres des normales
(`NORMAL_PARAMETER_SPECS`, plus bas) ; `items()` les écrit `days.<nom>` et
`normal.<nom>`, triés, comme `Definition.items()` pour les montées, et la provenance les
porte avec ceux de la définition ; `DEFAULT_DAY_DEFINITION` est le jeu par défaut. Un
paramètre qui est un compte ou un interrupteur se convertit en entier, et une valeur non
entière lève une `ValueError` qui le nomme (`integer_parameter`).

### Les validités

- Une grandeur de support `day` (`QUANTITY_SUPPORTS`) d'un jour qui n'est pas
  `complete` est absente de la ligne, ni nulle ni partielle, sauf la FC de repos, dont
  `resting_hr_on` dit le statut (`provisional` sur un jour tronqué) ; les grandeurs de
  la nuit et du réveil restent.
- L'état de la nuit (`missing`, `declared`, `in_progress`, `partial`, `complete`, dans
  cet ordre) et ses drapeaux viennent de `night_assessment`, la FC de repos et son
  statut (`absent`, `provisional`, `no_night`, `valid`) de `resting_hr_on`, Training
  Readiness du réveil de `readiness_on_waking`.
- Le stress du jour : `stress_measured_s` est la somme des durées au repos, en stress
  bas, moyen et haut (absente si l'une manque, donc sur tout jour qui n'est pas
  `complete`) ; `stress_valid` est vrai si elle atteint `days.stress_min_fraction` de
  la fenêtre du jour, de son début au plus tard de début + 24 h et de la fin des données
  (la fin que les vues donnent à un jour, calculée de la même façon : leur fonction est
  privée) ; absent sans stress ou sans fenêtre.
- La SpO2 reste hors de l'état de la nuit.

### Ce que la ligne tire d'une série

La seule série lue est celle du Body Battery de la nuit :
`series_between(…, SeriesKind.NIGHT_BODY_BATTERY, …)` entre le début et la fin de la
nuit, au pas `days.night_body_battery_step_s` et au minimum `days.min_coverage_fraction`.
`night_body_battery_coverage` est sa couverture ; `night_body_battery_ceiling` dit si un
point atteint le haut de l'échelle de Garmin (la borne haute de
`BODY_BATTERY_LEVEL_RANGE`, la plage de la lecture des familles) ; sous le minimum, ou
sans point, les deux manquent et `night_body_battery_absence` porte le motif de la vue ;
sans nuit, `no_night`. Les autres mesures de la nuit sont les résumés de Garmin, hors de
la règle de couverture. Le résumé de `mperf tables` compte les nuits sous le minimum :
une série dont le pas dépasse le pas déclaré divisé par le minimum de couverture (par
exemple, aux défauts, 180 s / 0,8 = 225 s) les y mettrait toutes. Il compte à part les
nuits sans point (`no_point` : la série n'a aucun point dans la fenêtre de la nuit, par
exemple un jour ancien dont la source a vidé la série), sans quoi il laisserait croire
que chaque nuit a sa série ; une ligne sans nuit (`no_night`, une ligne `absent`
comprise) n'est comptée ni dans l'un ni dans l'autre.

### Training Status

Chaque bloc va à la ligne de sa date propre (`day`), pour chacune des cinq sortes (le
statut et les charges ; l'équilibre de la charge ; la VO2max ; l'acclimatation à la
chaleur ; à l'altitude), avec son instant propre en colonne (`ts_status_instant`,
`ts_load_balance_instant`, `ts_vo2_max_instant`, `ts_heat_instant`,
`ts_altitude_instant`), absent si le bloc n'en a pas : la ligne porte alors des valeurs
que `training_status_at` ne rend jamais. Un bloc d'un jour hors de l'étendue de la
table n'a pas de ligne et se compte (`blocks_outside_days`). `TrainingStatusHistory`
n'a qu'un bloc par sorte et par date (son contrat le tient) : la table ne compte pas de
doublon.

### L'admission dans les normales, par mesure

La valeur d'une mesure entre dans les normales si aucun refus ne s'applique ; sinon la
ligne porte le premier, dans l'ordre d'`AdmissionRefusal` :

1. `absent_row` : la ligne est `absent` ;
2. `no_value` : la valeur manque ;
3. `invalid_value` : une FC de repos d'un statut autre que `valid`, ou une HRV `<= 0`
   (elle n'a pas de logarithme) ;
4. pour une mesure de nuit (toutes sauf la FC de repos) : `night_not_complete` (un état
   autre que `complete`), `short_night` (le drapeau `short` posé, **sauf pour le sommeil
   mesuré**), `shifted_night` (le drapeau `shifted` posé) ; un drapeau inconnu n'exclut
   pas ;
5. le journal du jour : `illness` (`maladie`), `injury` (`blessure`), `altitude_stay`
   (`sejour_altitude`, si `normal.exclude_altitude_stay` vaut 1, le défaut).

La ligne porte `<p>_admitted` et `<p>_refusal` ; une valeur refusée reste dans sa
colonne, et la normale ne lit que les valeurs admises. Le journal s'applique au jour de
la ligne, et la nuit suit son jour de réveil : une `maladie` du 12 au 14 (exemple
inventé) refuse les jours 12 à 14, donc la nuit du 11 au 12, pas celle du 14 au 15.

### Les normales

`analyse/normals.py`, en Python pur, sur des suites alignées sur les lignes de la table
(des jours consécutifs, `absent` comprises), sans lecture d'`interim/`. Six mesures
(`NormalMeasure`, `MEASURE_SPECS`), dans cet ordre :

| Mesure (préfixe) | Valeur lue | Échelle | Résolution déclarée | Version qui la rompt |
|---|---|---|---|---|
| HRV de la nuit (`hrv`) | `hrv_last_night_avg_ms` | log | 1 ms | aucune |
| FC de repos (`resting_hr`) | `resting_hr_bpm` (`resting_hr_on`) | linéaire | 1 bpm | aucune |
| sommeil mesuré (`measured_sleep`) | `measured_sleep_s` (`night_assessment`) | linéaire | 60 s | `sleep_version` |
| stress de la nuit (`night_stress`) | `night_avg_stress` | linéaire | 1 | `sleep_version` |
| respiration de la nuit (`night_respiration`) | `respiration_avg_sleep_breaths_per_min` | linéaire | 1 /min | `respiration_version` |
| SpO2 de la nuit (`night_spo2`) | `spo2_avg_sleep_percent` | linéaire | 1 % | aucune |

La version qui rompt une mesure est celle de sa famille (le stress de la nuit est un
champ de `sleep`) ; `sleep_respiration_version` ne rompt aucune normale.

- **La fenêtre du jour t** : les lignes des jours `[t − normal.window_days, t − 1]`,
  bornes comprises (plus courte au début de la table) ; le jour t n'en est jamais.
- **Le minimum** : les jours admis de la fenêtre se comptent (`<p>_admitted_days`) ;
  aucun, la normale manque, motif `no_admitted_day` ; au moins un et strictement moins
  que `normal.min_admitted_days`, motif `too_few_admitted_days`.
- **La normale** : sur les valeurs admises de la fenêtre (en log pour la HRV), la
  médiane ; la MAD, médiane des écarts absolus à la médiane ; s = max(`normal.mad_factor`
  × MAD ; plancher), le plancher étant la résolution déclarée, et pour la HRV
  ln(1 + r / m), r sa résolution en ms et m = exp(médiane du log). La normale est dans
  l'unité de la mesure, pour la HRV m ; la dispersion est s, et pour la HRV, à sa place,
  `hrv_log_median` et `hrv_log_dispersion`, la médiane et le s du log.
- **La plage** : médiane ∓ `normal.range_k` × s ; pour la HRV, exp(médiane du log ∓
  `normal.range_k` × s), en ms, donc dissymétrique. Exemple inventé : une médiane du log
  de 4,0 et un s de 0,1 donnent une plage de 49,4 à 60,3 ms, et 54,6 ms au centre.
- **Le segment** du jour t est le nombre de lignes avant t dont la normale manque : deux
  lignes à normale présente ont le même segment si et seulement si aucune normale absente
  ne les sépare. La page de récupération y coupera la normale et sa plage.
- Chaque ligne porte sa normale, une ligne `absent` ou sans valeur comprise ; la normale
  du jour t ne dépend que des valeurs et des admissions des jours avant t (l'admission
  d'un jour, elle, peut lire plus loin : le drapeau `shifted` d'un jour d dépend des
  nuits des jours qui le précèdent).

Les paramètres des normales sont déclarés dans `analyse/normals.py`
(`NORMAL_PARAMETER_SPECS`), communs à tous les athlètes, et la provenance les porte sous
`normal.<nom>` : `normal.window_days` (28 jours), `normal.min_admitted_days` (14 jours),
`normal.mad_factor` (1,4826), `normal.range_k` (1), `normal.exclude_altitude_stay` (1 ;
0 admet les jours `sejour_altitude`), et une résolution par mesure,
`normal.hrv_resolution_ms`, `normal.resting_hr_resolution_bpm`,
`normal.measured_sleep_resolution_s`, `normal.night_stress_resolution`,
`normal.night_respiration_resolution_breaths_per_min`,
`normal.night_spo2_resolution_percent` (les valeurs du tableau). Les composites de
Garmin (Training Readiness, score de sommeil, statut HRV, Body Battery) n'ont pas de
normale.

### Les ruptures, les jours incertains, la normale à cheval

- **Une rupture de rang au jour R** : R porte des rangs d'appareil, et l'un d'eux manque
  aux rangs du dernier jour avant R qui en porte ; aucune au premier jour qui en porte.
  Elle vaut pour les six mesures. Un rang de la veille qui disparaît n'en est pas une ;
  le retour à une montre déjà vue en est une (rangs 1, puis 2, puis 1 : ruptures au
  premier 2 et au retour du 1).
- **Une rupture de version de la mesure au jour R** : R porte une version de la famille
  de la mesure, différente de celle du dernier jour avant R qui en porte une ; aucune à
  la première.
- **`<p>_rupture`** est vrai au jour d'une rupture de rang ou de version de la mesure.
  **Une rupture n'exclut rien** et ne coupe pas les segments : la normale continue à
  travers elle.
- **Un jour incertain** (`uncertain_device`, commun aux mesures) : un jour à au moins
  deux rangs (on ne sait pas quelle montre a mesuré) ; ou un jour sans rang situé entre
  le dernier jour à rangs avant lui et un jour suivant de rupture de rang, sans jour à
  rangs entre eux (l'intervalle incertain d'un changement de montre). Sa valeur
  reste, admise comme les autres.
- **Une normale à cheval au jour t** (`<p>_normal_straddles`) : une rupture de la mesure
  à un jour de `[t − normal.window_days + 1, t − 1]` (une rupture au premier jour de la
  fenêtre n'y mêle rien), ou un jour incertain dans `[t − normal.window_days, t − 1]`.
- **Exemple inventé** : l'ancienne montre seule jusqu'au jour 3, les deux aux jours 4 et
  5, la nouvelle seule dès le jour 6 : rupture au jour 4, jours incertains 4 et 5,
  normale à cheval du jour 5 au jour 33, plus rien dès le jour 34. Une version qui
  change au jour 10, sans jour incertain : normale à cheval du jour 11 au jour 37.

### Le journal

`analyse/journal.py` lit `MPA_DATA_DIR/journal.csv` (`read_journal`), tenu à la main par
l'athlète, jamais écrit par la bibliothèque ; son format, pour qui le tient, est dans la
docstring du module et au § 3 de la charte. En bref : un CSV en UTF-8, avec ou sans BOM
(« CSV UTF-8 » dans Excel) ; une ligne d'en-tête qui nomme `debut`, `fin`, `type` et,
facultative, `note`, dans n'importe quel ordre ; le séparateur `;` si l'en-tête en
contient un, sinon `,` ; les dates en `AAAA-MM-JJ`, dates locales, `debut` et `fin`
compris, `fin` obligatoire et jamais avant `debut` ; l'un des huit types de la charte,
sans accent ; les blancs autour d'un champ sans guillemets, les lignes vides et une
marge de colonnes sans nom et vides à la fin de l'en-tête sans effet (un champ entre
guillemets s'écrit collé à ses séparateurs). Sans fichier, ou avec un fichier
vide, aucun événement.

- `read_journal` rend un `Journal` : les événements (`JournalEvent` : début, fin, type,
  ligne ; la `note` n'est pas gardée) et le SHA-256 des octets lus, `None` sans fichier.
- Un fichier malformé lève `JournalError`, qui arrête `mperf tables` sans rien écrire :
  `journal.csv, ligne <n> : <cause>`, ou `journal.csv : <cause>` pour l'encodage et un
  fichier illisible ; les causes sont des constantes du module (`*_CAUSE`) ; **aucun
  message ne recopie une valeur du fichier** (ni note, ni type, ni date, ni nom
  d'en-tête), et l'erreur n'enchaîne aucune autre exception.
- `journal_types_by_day(journal, first, last)` rend, pour chaque jour de
  `[first, last]` (les bornes de la table) couvert par un événement, ses types, triés
  par valeur et sans doublon ; un événement qui déborde y est coupé. La ligne n'en garde
  que les types (`journal_types`), jamais la `note`.

### L'activité du jour

Les entrées de l'index d'`interim/activities/`, de tout type, avec ou sans
enregistrement ; le jour d'une activité est la date locale de son départ (`start_time`,
comme `ActivityRow`) : une activité à cheval sur minuit compte tout entière au jour de
son départ ; une activité d'avant le premier jour de la table ou d'après le dernier n'a
pas de ligne et se compte au résumé. Par jour :

- `activity_count` ; `garmin_training_load`, la somme des charges selon Garmin
  présentes (`training_load`, jamais recalculée), `0` sans activité, absente si toutes
  les activités du jour en sont sans (un manque ; une charge nulle est une valeur) ;
  `activities_without_load` ;
- par famille de la table des types (`SOURCE_TYPE_SPORTS` : `foot`, `mtb`,
  `ski_touring`), la somme des temps écoulés de l'index (`elapsed_duration_s`), et pour
  les types sans famille `other_elapsed_s` et `other_activity_count` ; la famille vient
  de la table, pas de la vue `Activity` : une entrée que la vue refuse garde la sienne ;
- une activité sans temps écoulé ne s'ajoute à aucune durée et se compte
  (`activities_without_elapsed`).

Exemple inventé : 1 h de vélo de route et 1 h 30 de bloc le même jour donnent 2 h 30
d'« autres » et deux activités.

### La provenance

`ProcessedProvenance` gagne quatre champs, à la fin : `interim_days_sha256`,
l'empreinte d'`interim/days/`, calculée comme `interim_sha256`, qui garde son sens
(`interim/activities/` seul) ; `journal_sha256`, le SHA-256 des octets de `journal.csv`,
ou `JOURNAL_ABSENT` (« absent ») sans fichier ; `day_count`, les lignes de `jours` ;
`acquired_at`, l'instant d'acquisition le plus récent des exports du rapport des jours
(`DaysReport`), en texte ISO 8601, en UTC, tel qu'`interim/` le garde, toujours
présent (le contrat l'exige : le rapport nomme toujours au moins un export).
`parameters` porte aussi les `days.<nom>` et les `normal.<nom>`. Les tables dépendent
donc aussi de `journal.csv` : deux régénérations ne donnent les mêmes tables qu'avec le
même journal ; toute retouche du fichier, une note ou un blanc compris, change son
empreinte, donc les quatre tables et l'empreinte des résultats de Q1.
La relecture des tables est dans `0014` (précisions d'AN2-2).

### La tranche bornée

Chaque vue reçoit une tranche des documents, jamais toute la suite : `night_assessment`
du jour d, les documents des jours `[d − days.usual_window_days, d]` ; `resting_hr_on`
et `readiness_on_waking`, le document du jour d ; `series_between` sur la nuit du jour
d, les documents des jours `[d − 1, d + 1]`. Les tranches se prennent par bissection sur
la suite triée des documents, et le coût de la table devient linéaire en le nombre de
jours. Un test vérifie, sur des fixtures qui en exercent les bords (une nuit à cheval sur
deux documents, des jours manquants, un changement d'heure), que chaque vue rend le même
objet sur la tranche et sur la suite entière.

### `mperf tables`

`build_tables` lit d'abord tout ce qui peut refuser vite, avant le calcul des montées :
il vérifie qu'`interim/days/` existe (sans lui, un `interim/` écrit avant AN2-1,
`TablesError`, dont le message dit de relancer `just process`), relit les jours
(`read_days`, `read_training_status`, `read_days_report` : une `CodecError` ou une
`ContractError` devient une `TablesError` qui nomme les jours d'`interim/`) et le journal
(`read_journal` : `JournalError`). Il calcule ensuite les trois tables d'AN1-2 comme
avant, puis `jours` (`day_rows`) et la provenance. L'aide de la commande dit ce qu'elle
lit : « Écrire MPA_DATA_DIR/processed depuis interim/activities, interim/days et
journal.csv (AN1-2b, AN2-2) ».
Le résumé, dans cet ordre, garde les lignes d'avant, sauf le libellé d'empreinte :

```text
Activités : <n>
Montées : <n>
  <régime> : <n>
Montées marquées : <n>
Montées instables : <n>
Montées des variantes : <n>
Jours : <n>
  sans document : <n>
  activités hors des jours : <n>
  blocs de Training Status hors des jours : <n>
  nuits sous la couverture du Body Battery : <n>
  nuits sans point de Body Battery : <n>
Journal : <SHA-256 de journal.csv, ou « absent »>
Empreinte d'interim/activities/ : <empreinte>
Empreinte d'interim/days/ : <empreinte>
Commit : <commit>
-> activites.parquet, montees.parquet, variantes.parquet, jours.parquet
```

Une erreur, celles d'avant et `JournalError`, s'affiche « Erreur : <message> », code 1,
et rien n'est écrit.

## Pourquoi

- **Rupture B** : la normale de `jours` est descriptive. La page la montrera jour après
  jour ; sous A, elle disparaîtrait juste après un changement de montre, quand on veut
  justement voir si quelque chose a changé. Les avertissements disent où la fenêtre mêle
  l'avant et l'après, et la page le dira sans changer la plage. La conséquence, dite à
  rdw : si deux montres ne mesurent pas pareil, la normale traîne derrière la nouvelle,
  et des jours sortent de la plage sans que rien n'ait changé chez l'athlète ;
  l'avertissement empêche de le lire comme un changement. Les questions gardent A : un
  plan refait sa normale sous la règle de la charte, § 11.
- **Nuit courte B** : le drapeau `short` se lit sur le sommeil mesuré ; l'exclure de sa
  normale filtrerait la mesure par elle-même (la normale ne verrait jamais une période de
  nuits courtes, et une nuit courte sortirait le plus souvent de la plage ; la charte
  écarte ce genre de filtre pour les montées, § 2). Exemple inventé : 15 nuits courtes
  sur 28 ; sous A, il reste 13 nuits admises, et la normale du sommeil disparaît
  justement quand les nuits courtes dominent ; admises, elles y entrent, et la normale
  les suit. Pour les autres mesures de nuit, la nuit courte reste un filtre de qualité.
- **Durée B** : chaque vue ne lit que peu de jours (la fenêtre du milieu habituel, le
  jour, ou les voisins d'une nuit) ; la tranche donne les mêmes objets, sauf une série
  de nuit étirée sur plus d'un jour (Non promis), et `day_views.py` ne change pas. Un
  index ne se proposait que si la tranche ne suffisait pas.
- **Les seuils déclarés** : les vues n'ont aucun défaut (`0018`) ; la piste déclare les
  siens, et la provenance dit avec lesquels la table a été calculée. Le pas de la série du
  Body Battery et les résolutions sont des résolutions de la source, déclarées comme les
  autres paramètres : une montre qui écrirait plus finement demanderait une autre
  déclaration, et une série dont le pas dépasse le pas déclaré divisé par le minimum de
  couverture (par exemple, aux défauts, 225 s) tombe sous ce minimum, ce que le résumé
  compte.
- **La HRV en log** : une mesure multiplicative (charte, § 6) ; son centre est
  exp(médiane du log), et sa plage, revenue en ms, est dissymétrique. **Les autres
  mesures dans leur unité**, le sommeil mesuré compris, bien que la charte, § 6, range
  les durées parmi les mesures multiplicatives (décision de rdw, au cadrage d'AN2) :
  la plage de la page se lit dans l'unité de la mesure ; un plan de question sur le
  sommeil suit la charte. **Le plancher** :
  sans lui, une fenêtre de valeurs égales donnerait une plage nulle.
- **Les segments** : la page coupera la normale et sa plage là où elle manque, sans
  rien recalculer ; une rupture est un avertissement, pas une coupure.
- **L'activité du jour en temps écoulés** : l'index les porte pour toute activité, avec
  ou sans enregistrement ; les horloges du moteur n'existent que pour une activité qui a
  une trace. **La charge de Garmin**, sommée sans être recalculée : une charge
  recalculée depuis les activités appartient au plan d'une question (charte, § 5).
- **Le journal tel qu'Excel l'écrit** (`;`, « CSV UTF-8 ») et des dates `AAAA-MM-JJ` sans
  ambiguïté ; des messages sans valeur du fichier : la `note` est un texte libre,
  personnel, et une valeur recopiée dans un message en sortirait (le terminal, une
  trace).
- **`acquired_at` en texte, en UTC** : `interim/` garde l'instant en UTC, le décalage
  d'origine n'est que dans `acquisition.json`, que `mperf tables` ne lit pas ; et la
  provenance des tables entre telle quelle dans le `provenance.json` de Q1, qui ne
  sérialise pas un `datetime`.

## Conséquences

- **Facile** : la page de récupération (AN2-3) lira `jours` sans rien calculer (règle
  7) : ses marques pleines, creuses et grises dans les admissions et leurs motifs, ses
  segments dans `<p>_segment`, ses règles verticales dans `<p>_rupture` ; faire varier un
  seuil ou un paramètre des normales ; savoir, par la provenance, de quel `interim/`, de
  quel journal et de quels paramètres vient la table.
- **Contraignant** : après la fusion, `just process` une fois : `mperf tables` refuse un
  `interim/` sans `days/`, `read_tables` des tables d'avant AN2-2 ; l'empreinte des
  résultats de Q1 change, puisque leur provenance porte celle des tables. Un
  `journal.csv` malformé arrête `mperf tables`, avant le calcul des montées. La table
  se recalcule en entier à chaque `mperf tables`, et tous les documents des jours sont
  en mémoire.
- **Non promis** :
  - la normale à cheval d'un jour peut changer quand un jour à rangs postérieur paraît :
    un jour sans rang n'est incertain qu'au vu du jour à rangs qui le suit ; la valeur
    de la normale, elle, ne dépend que des jours d'avant ;
  - une sortie enregistrée deux fois (par deux appareils, deux entrées de l'index)
    compte deux fois dans l'activité du jour ;
  - une valeur incertaine reste admise : `uncertain_device` la marque, rien ne l'exclut ;
  - la charge du jour est celle de Garmin, jamais recalculée ; les composites de Garmin
    n'ont pas de normale ;
  - aucun firmware : les rangs ne se comparent pas à l'appareil d'un FIT (`0018`) ; un
    changement de firmware se contrôle dans le plan de chaque question (charte, § 11) ;
  - la tranche de `series_between` rend le même objet que la suite entière tant
    qu'aucune nuit d'un document hors de `[d − 1, d + 1]` ne porte de point dans la
    fenêtre de la nuit de d (une série de nuit étirée sur plus d'un jour) ; aucun
    contrat d'`interim/days/` ne l'interdit ; vérifié par la conception sur le réel, à
    revérifier au contrôle réel de la PR ;
  - un jeu où `normal.window_days` est sous `normal.min_admitted_days` n'est pas
    refusé : la normale y manque toujours (`too_few_admitted_days`, ou
    `no_admitted_day` quand la fenêtre n'a aucun jour admis) ;
  - le journal ne dit que ce que l'athlète y écrit : un jour sans événement n'est pas un
    jour sans maladie.
- **À revisiter** :
  - un temps en mouvement dans l'activité du jour : il viendrait des horloges du moteur
    (`moving_s_by_convention` d'`ActivityRow`, `0010` D5), pas de celui de Garmin ; elles
    n'existent que pour une activité qui a une trace, et la convention se choisira
    (`BACKLOG`) ;
  - un index par jour dans `ingest/day_views.py`, si la tranche ne suffisait plus
    (`0018`) ;
  - les seuils `days.*` et les résolutions, quand une autre montre ou un autre athlète
    passera par la table.
