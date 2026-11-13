# `just process` — les tables des activités, des montées, des variantes et des jours

`just process` régénère tout depuis `raw/` : l'ingestion (`mperf ingest`, extra
`ingest`), puis `mperf tables` (extra `analyse`), qui lit
`MPA_DATA_DIR/interim/activities/`, `MPA_DATA_DIR/interim/days/`, `athlete.toml` et
`journal.csv`, et écrit quatre tables Parquet dans `MPA_DATA_DIR/processed/`
([`0014`](../decisions/0014-montees-et-tables.md),
[`0019`](../decisions/0019-table-jours-et-normales.md)) :

- `activites.parquet`, une ligne par activité de l'index : les valeurs de l'index (hors
  de la charge selon Garmin, que `jours.parquet` somme par jour), le temps de mouvement
  du moteur sous ses cinq conventions, le pas, les trous et les pauses, l'appareil, et
  les montées comptées par régime ;
- `montees.parquet`, une ligne par montée : ses bornes en temps, son gain, sa vitesse
  ascensionnelle (le gain pris en mouvement divisé par le temps en mouvement, avec sa
  variante et son enveloppe), sa pente, son régime (côte, intermédiaire, montée longue,
  ski de randonnée, ski de randonnée court, autre sport), ses strates de pente et
  d'altitude, ses drapeaux et sa stabilité, sa FC moyenne décalée de 60 s (celle de
  l'outil de FC du moteur), sur son temps en mouvement et ses variantes, avec la part
  que la FC en couvre, et sa position (latitude, longitude) à son départ et à son
  arrivée ;
- `variantes.parquet`, une ligne par montée de chaque variante déclarée de la
  définition (celles que la stabilité recalcule) : ses bornes, son gain, son gain pris
  en mouvement et son temps en mouvement, son régime, ses strates et ses drapeaux sous
  les paramètres de la variante ; la stabilité des points de la figure de Q1 la lit
  ([`0015`](../decisions/0015-figure-de-q1.md)) ;
- `jours.parquet`, une ligne par jour du calendrier, du premier au dernier jour
  d'`interim/days/`, un jour sans document compris (« absent ») : la nuit rattachée au
  jour du réveil (son état, ses drapeaux « courte » et « décalée », le sommeil mesuré et
  ses phases, les résumés de Garmin), les siestes, les valeurs du jour selon Garmin (FC
  de repos et son statut, HRV, respiration, SpO2, stress, Body Battery, pas), Training
  Readiness du réveil, Training Status à sa date propre, les types du journal qui
  couvrent le jour, l'activité du jour (la charge selon Garmin et les temps écoulés par
  famille de sport), l'instant du milieu de la demi-heure où la FC de la journée est la
  plus basse ; et, pour six mesures (HRV de la nuit, FC de repos, sommeil
  mesuré, stress, respiration et SpO2 de la nuit), si la valeur du jour entre dans les
  normales, sinon pourquoi, et la normale des 28 jours précédents (un paramètre
  déclaré), sa plage, ses segments et ses avertissements de rupture (un changement de
  montre ou de version d'algorithme ne coupe pas la normale : il se marque).

Les montées se détectent sur le profil du moteur ; leurs bornes et leur gain se lisent
en temps, sur l'altitude lissée du moteur, et un replat qui monte doucement reste hors
de la montée, à un pas de grille près (un bout plus court qu'un pas peut y rester et
diluer la VAM d'une côte courte) ; près de la pente d'un replat, le bruit de l'altitude
peut y laisser bien plus (`docs/decisions/0014`). Un drapeau marque une montée sans la
retirer. Les quatre fichiers portent la même provenance : les empreintes
d'`interim/activities/`, d'`interim/days/` et de `journal.csv` (ou « absent »), le
commit et la version du paquet, tous les paramètres de la définition, des vues des jours
et des normales, les nombres de lignes, et l'instant d'acquisition le plus récent des
exports ; régénérés depuis le même `interim/` par le même code, avec les mêmes
`athlete.toml` et `journal.csv` et la même version de pyarrow (celle de `uv.lock`), ils
sont identiques à l'octet sur la même plateforme (d'un système à l'autre, les derniers
chiffres d'un nombre peuvent différer) ; toute retouche de `journal.csv`, une note ou un
blanc compris, change son empreinte, donc les quatre tables et l'empreinte des résultats
de Q1. Comme pour [`just backtest`](backtest.md), le code exécuté doit
être celui d'un clone git, installé par `uv sync`, et `mperf tables` refuse un clone dont
un fichier suivi est modifié : le commit doit dire le code qui a écrit les tables. Les
quatre fichiers s'écrivent dans un dossier à part, puis prennent ensemble la place de
`processed/` : une écriture qui échoue laisse les tables d'avant.

`MPA_DATA_DIR/athlete.toml` peut déclarer, dans sa table `[analyse]`, la vitesse
ascensionnelle de référence qui fixe la frontière des régimes, et les produits de
montre qui portent un baromètre :

```toml
[analyse]
reference_vertical_speed_m_per_h = 900
barometer_products = [{ manufacturer = "garmin", product = 1 }]
```

Absente, la vitesse prend le défaut du projet (900 m/h) ; elle ne se calcule pas sur
les données, pour que les régimes ne dépendent pas de la mesure.

`MPA_DATA_DIR/journal.csv`, facultatif, tenu à la main et jamais écrit par `mperf`,
porte les événements que Garmin ne contient pas
([`docs/analyse/CHARTE.md`](../analyse/CHARTE.md), § 3) : une ligne par événement,
`debut`, `fin`, `type` et, facultative, `note`. Exemple inventé, tel qu'Excel en français
l'enregistre :

```text
debut;fin;type;note
2000-01-12;2000-01-14;maladie;
2000-02-05;2000-02-05;course;"une note ; avec le séparateur"
```

- **le fichier** : un CSV en UTF-8, avec ou sans BOM (dans Excel, « Enregistrer sous »,
  type « CSV UTF-8 ») ; le séparateur est `;` si la ligne d'en-tête en contient un,
  sinon `,` ; un champ qui contient le séparateur s'écrit entre guillemets ;
- **l'en-tête**, la première ligne non vide, nomme les colonnes dans n'importe quel
  ordre, sans accent (`debut`, pas `début`) ; la casse et les blancs autour d'un nom ne
  comptent pas ; des colonnes sans nom et vides à la fin de l'en-tête (une marge
  qu'Excel laisse) et les lignes vides sont ignorées ;
- **les dates** s'écrivent `AAAA-MM-JJ` et rien d'autre, en dates locales (dans Excel,
  mettre les colonnes `debut` et `fin` au format personnalisé `aaaa-mm-jj`, ou en texte,
  avant d'enregistrer) ; `debut` et `fin` sont compris, un événement d'un jour a `fin`
  égale à `debut` ; `fin` est obligatoire et jamais avant `debut` : un événement en cours
  s'écrit avec sa fin prévue, qui se corrige ensuite ; une nuit suit son jour de réveil
  (une `maladie` du 12 au 14 couvre la nuit du 11 au 12, pas celle du 14 au 15) ;
- **`type`**, sans accent : `maladie`, `blessure`, `course`, `deplacement`,
  `demenagement`, `sejour_altitude`, `etalon` ou `autre` ; les jours `maladie` et
  `blessure`, et par défaut `sejour_altitude`, n'entrent dans aucune normale de `jours` ;
- **`note`** est un texte libre pour l'athlète seul : `mperf` ne la garde pas, mais
  toute retouche du fichier, une note ou un blanc compris, change son empreinte, donc
  les quatre tables et l'empreinte des résultats de Q1.

Sans fichier, ou avec un fichier vide, il n'y a aucun événement. Un fichier malformé
arrête `mperf tables`, qui n'écrit rien : le message dit la ligne
(`journal.csv, ligne <n> : <cause>`) et la cause (sans ligne pour l'encodage ou un
fichier illisible : `journal.csv : <cause>`), sans recopier aucune valeur du fichier.

```bash
just process
```

Après l'ingestion, `mperf tables` dit le nombre d'activités et de montées, les
montées par régime, les montées marquées et instables, les montées des variantes ; le
nombre de jours de `jours`, et parmi eux ceux sans document ; les activités et les blocs
de Training Status hors des jours, les nuits dont la série de Body Battery est sous le
minimum de couverture, et celles dont la série n'a aucun point ; l'empreinte de
`journal.csv` (ou « absent »), celles d'`interim/activities/` et d'`interim/days/`, le
commit et les fichiers écrits. Pas d'exemple ici : sur les exports réels, ces nombres restent hors du dépôt ([`docs/analyse/CHARTE.md`](../analyse/CHARTE.md), § 10). Sans
`interim/days/` (un `interim/` écrit avant AN2-1), la commande s'arrête sans rien
écrire : relancer `just process`.
