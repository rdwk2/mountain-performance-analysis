# Dictionnaire de données

> **Fichier généré** depuis les docstrings de `mountain_perf.schemas` par
> `just dictionary`. Ne pas l'éditer à la main : un test échoue dès qu'il diverge
> du code. Pour le modifier, modifier la docstring, puis relancer la recette.

## Sommaire

- `Sport`
- `QualityFlag`
- `SourceRef`
- `ParameterSpec`
- `ParameterSet`
- `PointKind`
- `NamedPoint`
- `Route`
- `ResolvedPoint`
- `RouteProfile`
- `Activity`
- `TrackPointStream`
- `CurveProvenance`
- `PaceCurve`
- `Passage`
- `Segment`
- `Projection`
- `TimingConvention`
- `ObservedPassage`
- `ReferencePerformance`
- `OutingLabel`
- `DataSet`
- `ReferenceKind`
- `ArtifactRole`
- `Unavailability`
- `ArtifactRef`
- `RouteReference`
- `Outing`
- `RetentionDecision`
- `Performance`
- `RecordedTrace`
- `IntervalState`
- `ClockConvention`
- `ClockKind`
- `Clock`
- `ClockPartition`
- `ClockTotals`
- `StopEpisode`
- `PointStatus`
- `ScorePointObservation`
- `SegmentExclusion`
- `Regime`
- `RegimeClass`
- `ScoreSegmentObservation`
- `Coverage`
- `AdmittedTotals`
- `SensitivityConfiguration`
- `MatchResult`
- `PassageRole`
- `PassageStatus`
- `EpisodeOutcome`
- `PassageObservation`
- `EpisodeAttribution`
- `PassageMatchResult`
- `MetricValue`
- `ClassMetrics`
- `SupportMetrics`
- `PositiveTimeDiagnostic`
- `LogRatioEnvelope`
- `PassageErrors`
- `TargetMember`
- `UsageTarget`
- `Scenario`
- `AdmittedSegment`
- `ObservedPoint`
- `OutingObservation`
- `ModelForecast`
- `ClockScores`
- `ScenarioScores`
- `OutingScores`

---

## `Sport`

*`mountain_perf.schemas.common` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `FOOT` | `foot` | Déplacement à pied : marche, randonnée, course, trail. |
| `SKI_TOURING` | `ski_touring` | Ski de randonnée : montée en peaux, descente à ski. |
| `MTB` | `mtb` | Vélo tout-terrain. |

Famille de modèle de performance.

Le critère de découpage est : **la même famille de modèle s'applique-t-elle ?**,
c'est-à-dire `v = f(pente) × modificateurs` tient-il avec la même forme de
`f`. La marche et la course sont toutes deux `FOOT` : courbes différentes,
même famille. Le ski de randonnée non : la descente n'est pas sur la même
fonction et le rapport montée/descente est d'un ordre de grandeur.

Une nouvelle valeur se justifie quand la *forme* du modèle change, pas quand
l'activité change de nom. On ne déclare pas de valeur « au cas où ».

#### Champs

Valeurs décrites dans `SPORT_DESCRIPTIONS`.

#### Invariants

Énumération fermée ; une valeur inconnue n'existe pas.

#### Producteur

L'ingestion (M6b) et le choix d'une courbe.

#### Consommateurs

La sélection de courbe, à partir de l'intégration d'une deuxième courbe.

#### Non promis

Rien ne lit ce champ avant la deuxième courbe. Aucun `if sport == …` n'est
légitime de M2 à M5, sauf pour valider une cohérence (`docs/decisions/0003`).

---

## `QualityFlag`

*`mountain_perf.schemas.common` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `GPS_GAP` | `gps_gap` | Intervalle sans position enregistrée assez long pour rendre l'interpolation douteuse. |
| `ELEVATION_SPIKE` | `elevation_spike` | Variation d'altitude entre deux points incompatible avec un déplacement à pied. |
| `IMPLAUSIBLE_SPEED` | `implausible_speed` | Vitesse incompatible avec le sport et la pente. |

Suspicion portée par un objet, sans l'empêcher d'exister.

Politique de validation à deux niveaux — une décision de contrat, pas de style :

- **invariant dur** : `__post_init__` lève `ContractError`, l'objet n'existe
  pas (tableaux de longueurs différentes, altitude hors plage, `datetime`
  naïf…) ;
- **suspicion** : l'objet existe et porte un `QualityFlag`. Rien n'est bloqué.

Si tout levait, une seule activité avec un trou GPS ferait tomber toute
l'estimation de courbe ; si rien ne levait, on la construirait sur des données
pourries sans le savoir. **Le contrat est strict, l'ingestion est tolérante et
tracée.**

#### Champs

Valeurs décrites dans `QUALITY_FLAG_DESCRIPTIONS`.

#### Invariants

Énumération fermée. Seules les valeurs dont l'usage est déjà prévu sont
déclarées.

#### Producteur

Les détecteurs de qualité de l'ingestion (M6b). Aucun détecteur n'existe en M1.

#### Consommateurs

L'estimation de courbe (M6b), qui décide d'écarter ou de pondérer.

#### Non promis

Aucun seuil ni méthode de détection : ils sont du M6b. L'absence de drapeau ne
garantit pas l'absence de défaut, tant qu'aucun détecteur n'existe.

---

## `SourceRef`

*`mountain_perf.schemas.common` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `kind` | `str` | — |
| `identifier` | `str` | — |
| `content_hash` | `str` | — |
| `retrieved_at` | `datetime` | — |

Provenance d'un objet venu de l'extérieur du programme.

#### Champs

- `kind` — sans unité — nature de la source : `"gpx"`,
  `"garmin_activity"`, `"csv"`.
- `identifier` — sans unité — **nom du fichier, jamais un chemin complet**.
- `content_hash` — sans unité — `sha256` du contenu, 64 caractères
  hexadécimaux minuscules.
- `retrieved_at` — instant — moment de l'acquisition, *aware*, stocké en UTC.

#### Invariants

- `kind` et `identifier` non vides ;
- `identifier` ne contient ni `/`, ni `\`, ni `:`, et n'est pas `.`
  ou `..` : un chemin complet contient le nom de l'utilisateur, et ces objets
  finiront sérialisés puis cités. La règle 1 tient au niveau du type ;
- `content_hash` est un `sha256` hexadécimal minuscule ;
- `retrieved_at` porte un fuseau ; il est normalisé en UTC à la construction.

#### Producteur

Les lecteurs de fichiers : GPX (M2), ingestion Garmin (M6b), CSV de référence (M4).

#### Consommateurs

Tout objet dérivé qui recopie sa provenance (`RouteProfile`), et le backtest
(M4), qui doit pouvoir dire sur quel fichier il a calibré et sur quel fichier il
évalue.

#### Non promis

- `kind` n'est pas une énumération fermée : aucun code ne doit en dépendre
  pour se brancher ;
- `identifier` n'est pas unique : deux fichiers de même nom se distinguent par
  `content_hash` ;
- le fuseau d'origine de `retrieved_at` n'est pas conservé.

---

## `ParameterSpec`

*`mountain_perf.schemas.parameters` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `name` | `str` | — |
| `unit` | `str \| None` | — |
| `default` | `float` | — |
| `minimum` | `float` | — |
| `maximum` | `float` | — |
| `description` | `str` | — |

Déclaration d'un paramètre réel du modèle.

#### Champs

- `name` — sans unité — identifiant du paramètre, unique dans un jeu.
- `unit` — sans unité — unité de la valeur (`"m"`, `"s"`…) ; `None`
  pour une grandeur sans dimension (coefficient, fraction).
- `default` — en `unit` — valeur prise quand le jeu n'en fournit pas.
- `minimum` — en `unit` — borne basse incluse.
- `maximum` — en `unit` — borne haute incluse.
- `description` — sans unité — texte destiné à l'infobulle de l'interface.

#### Invariants

- `name` et `description` non vides ; `unit` non vide s'il est présent ;
- `default`, `minimum`, `maximum` finis ;
- `minimum <= default <= maximum`.

#### Producteur

Déclaration statique dans le code des briques qui ont des paramètres : le
moteur (M3, M6a), la construction du profil (M2).

#### Consommateurs

`ParameterSet` (validation), l'interface (M5, contrôles et bornes), le
backtest (M4, balayage).

#### Non promis

- aucun type autre que flottant : pas de booléen (le modèle est multiplicatif,
  désactiver un effet c'est mettre son coefficient à zéro), pas de choix
  d'objet (une courbe est une référence qui vit à côté du jeu) ;
- aucun pas, aucune échelle (linéaire, logarithmique) pour l'interface ;
- aucune spec réelle n'est déclarée en M1.

---

## `ParameterSet`

*`mountain_perf.schemas.parameters` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `specs` | `tuple[ParameterSpec, ...]` | — |
| `values` | `Mapping[str, float]` | `{}` |

Jeu de valeurs validé contre ses spécifications.

#### Champs

- `specs` — sans unité — tuple des `ParameterSpec` du jeu, dans l'ordre de
  déclaration.
- `values` — en unité de chaque spec — table `nom → valeur`. À la
  construction on peut n'en fournir qu'une partie ; **après construction, la
  table est complétée par les défauts** et contient exactement une entrée par
  spec, dans l'ordre des specs. Elle est en lecture seule.

#### Invariants

- `specs` est un tuple, sans doublon de nom ;
- toute clé de `values` correspond à une spec connue ;
- toute valeur est finie et dans `[minimum, maximum]` de sa spec.

#### Producteur

L'appelant d'une brique paramétrée : l'interface (M5), le backtest (M4), la
construction du profil (M2), qui l'enregistre dans `RouteProfile`.

#### Consommateurs

Le moteur (M3), la construction du profil (M2), et tout objet qui doit dire ce
qui l'a produit (`RouteProfile.build_parameters`, `Projection` en M1b).

#### Non promis

- la table fournie n'est pas conservée : elle est copiée, la modifier après
  construction n'a pas d'effet ;
- l'objet n'est pas hachable (la table est un `Mapping`) ;
- aucune validation croisée entre paramètres.

---

## `PointKind`

*`mountain_perf.schemas.route` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `UNKNOWN` | `unknown` | Nature non renseignée. |
| `START` | `start` | Départ. |
| `FINISH` | `finish` | Arrivée. |
| `AID_STATION` | `aid_station` | Ravitaillement : boire, manger, parfois assistance. |
| `WATER` | `water` | Point d'eau seul. |
| `COL` | `col` | Col : point haut de passage entre deux versants. |
| `SUMMIT` | `summit` | Sommet. |
| `CHECKPOINT` | `checkpoint` | Point de contrôle ou de pointage, sans ravitaillement. |

Nature d'un point nommé.

#### Champs

Valeurs décrites dans `POINT_KIND_DESCRIPTIONS`.

#### Invariants

Énumération fermée ; `UNKNOWN` est la valeur par défaut, et une valeur honnête.

#### Producteur

Saisie manuelle ou semi-automatique (M5). Rien ne le remplit en M1.

#### Consommateurs

L'affichage des passages (M5) ; plus tard, le temps d'arrêt par point (M6a).

#### Non promis

**Jamais inféré en M1** : aucune reconnaissance de motif sur le nom ni sur
`raw_type`. Ce genre d'inférence se trompe en silence.

---

## `NamedPoint`

*`mountain_perf.schemas.route` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `name` | `str` | — |
| `latitude_deg` | `float` | — |
| `longitude_deg` | `float` | — |
| `elevation_m` | `float \| None` | — |
| `kind` | `PointKind` | `PointKind.UNKNOWN` |
| `raw_type` | `str \| None` | `None` |
| `cutoff_s` | `float \| None` | `None` |
| `description` | `str \| None` | `None` |

Lieu nommé, tel qu'il figure dans le fichier source.

#### Champs

- `name` — sans unité — nom du lieu.
- `latitude_deg` — degrés — latitude WGS84, `[-90, 90]`.
- `longitude_deg` — degrés — longitude WGS84, `[-180, 180]`.
- `elevation_m` — mètres — altitude du fichier si présente, `[-500, 9000]`.
- `kind` — sans unité — nature du lieu, `UNKNOWN` par défaut.
- `raw_type` — sans unité — le `<type>`/`<sym>` du GPX, tel quel.
- `cutoff_s` — secondes depuis le départ — barrière horaire, `> 0`.
  **Provisoire** : une barrière appartient à une course, pas à un tracé.
- `description` — sans unité — texte libre du fichier.

#### Invariants

- `name` non vide ;
- coordonnées finies et dans leurs plages ;
- `elevation_m` finie et dans `[-500, 9000]` si présente ;
- `cutoff_s` fini et `> 0` si présent.

#### Producteur

La lecture GPX (M2).

#### Consommateurs

`Route` ; la résolution des passages (M2), qui produit des `ResolvedPoint`.

#### Non promis

- **aucune abscisse** : la position sur le tracé n'est pas résolue ici ;
- `kind` n'est jamais inféré en M1 ;
- `raw_type` vient de l'outil qui a produit le GPX et n'est pas fiable ;
- `elevation_m` est celle du fichier et peut différer de celle du profil ;
- `cutoff_s` pourra quitter ce type le jour où une notion de course existera.

---

## `Route`

*`mountain_perf.schemas.route` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `name` | `str` | — |
| `latitude_deg` | `Sequence[float]` | — |
| `longitude_deg` | `Sequence[float]` | — |
| `elevation_m` | `Sequence[float]` | — |
| `named_points` | `tuple[NamedPoint, ...]` | — |
| `source` | `SourceRef` | — |

Géométrie d'un tracé, telle que lue dans le fichier.

Tableaux parallèles : le point `i` est
`(latitude_deg[i], longitude_deg[i], elevation_m[i])`.

#### Champs

- `name` — sans unité — nom du tracé.
- `latitude_deg` — degrés — latitudes WGS84, `[-90, 90]`.
- `longitude_deg` — degrés — longitudes WGS84, `[-180, 180]`.
- `elevation_m` — mètres — altitudes du fichier, `[-500, 9000]`.
- `named_points` — sans unité — les lieux nommés du fichier.
- `source` — sans unité — provenance du fichier.

#### Invariants

- `name` non vide ;
- les trois tableaux et `named_points` sont des tuples ;
- les trois tableaux ont la même longueur, au moins 2 points ;
- toutes les valeurs sont finies et dans leurs plages.

#### Producteur

La lecture GPX (M2).

#### Consommateurs

La construction du profil (M2), qui produit un `RouteProfile`.

#### Non promis

- **aucune distance** : elle se calcule, et c'est le M2 qui la calcule ;
- **aucun temps** : un tracé est une géométrie, pas un enregistrement ;
- **rien n'est lissé ni rééchantillonné** : les points ne sont pas
  régulièrement espacés ;
- les points nommés sont ceux du fichier, tous, sans filtre ni tri ;
- **aucun sport** : le même sentier se court, se marche et se skie ;
- les tableaux ne sont pas copiés ; ils sont exigés immuables.

---

## `ResolvedPoint`

*`mountain_perf.schemas.route` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `point` | `NamedPoint` | — |
| `distance_m` | `float` | — |
| `elevation_m` | `float` | — |
| `offset_m` | `float` | — |

Passage d'un lieu nommé, résolu sur le tracé.

#### Champs

- `point` — sans unité — le lieu d'origine.
- `distance_m` — mètres — abscisse curviligne le long du tracé (distance
  horizontale cumulée depuis le départ), `>= 0`.
- `elevation_m` — mètres — altitude lue sur le profil, `[-500, 9000]` ;
  différente de `point.elevation_m`.
- `offset_m` — mètres — écart entre le lieu nommé et le tracé, `>= 0`.
  Indicateur de qualité : 3 m est bon, 180 m mérite un regard.

#### Invariants

- valeurs finies ;
- `distance_m >= 0` ; `offset_m >= 0` ;
- `elevation_m` dans `[-500, 9000]`.

#### Producteur

La résolution des passages (M2).

#### Consommateurs

`RouteProfile` ; la projection (M3) et le backtest (M4), qui comparent des
temps à ces passages.

#### Non promis

- la règle qui a produit la résolution (minima locaux, seuils d'écart et de
  séparation) : elle est du M2 ;
- l'unicité : un même lieu peut donner plusieurs `ResolvedPoint`.

---

## `RouteProfile`

*`mountain_perf.schemas.route` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `route_name` | `str` | — |
| `source` | `SourceRef` | — |
| `distance_m` | `Sequence[float]` | — |
| `elevation_m` | `Sequence[float]` | — |
| `resolved_points` | `tuple[ResolvedPoint, ...]` | — |
| `step_m` | `float` | — |
| `build_parameters` | `ParameterSet` | — |
| `quality_flags` | `frozenset[QualityFlag]` | `frozenset()` |

| Propriété calculée | Type | Sens |
|---|---|---|
| `grade` | `tuple[float, ...]` | Pente (fraction, sans unité) de chaque intervalle de la grille. |
| `cumulative_ascent_m` | `tuple[float, ...]` | D+ cumulé (mètres) à chaque point de la grille. |
| `cumulative_descent_m` | `tuple[float, ...]` | D− cumulé (mètres, positif) à chaque point de la grille. |

Profil d'un tracé sur une grille de distance : le produit du M2.

Tableaux parallèles : le point `i` de la grille est
`(distance_m[i], elevation_m[i])`.

#### Champs

- `route_name` — sans unité — nom du `Route` d'origine.
- `source` — sans unité — provenance du `Route` d'origine.
- `distance_m` — mètres — grille : distance cumulée **2D horizontale**
  depuis le départ.
- `elevation_m` — mètres — altitude **lissée** sur la grille, `[-500, 9000]`.
- `resolved_points` — sans unité — passages aux lieux nommés, par abscisse
  croissante.
- `step_m` — mètres — pas nominal de la grille, `> 0`.
- `build_parameters` — sans unité — paramètres de construction (lissage, pas
  de grille, seuils de résolution).
- `quality_flags` — sans unité — suspicions portées par le profil ; vide par
  défaut.

Propriétés calculées (jamais stockées) : `grade`, `cumulative_ascent_m`,
`cumulative_descent_m`.

#### Invariants

- `route_name` non vide ;
- `distance_m`, `elevation_m` et `resolved_points` sont des tuples ;
- `len(elevation_m) == len(distance_m)`, au moins 2 points ;
- valeurs finies ; altitudes dans `[-500, 9000]` ;
- `distance_m[0] == 0` et `distance_m` strictement croissante ;
- `step_m` fini et `> 0` ;
- `resolved_points` triés par `distance_m` croissant au sens large, tous dans
  `[0, distance_m[-1]]`.

**Deux entrées de `resolved_points` peuvent porter le même `NamedPoint`** à
des abscisses différentes : aller-retour au sommet, boucle dont le départ est
l'arrivée, lieu traversé à la montée et à la descente.

#### Producteur

La construction du profil (M2), à partir d'un `Route`.

#### Consommateurs

Le moteur de projection (M3), le backtest (M4), l'interface (M5), le découpage
en segments (M1b).

#### Non promis

- le pas n'est **pas** exactement constant sur le dernier intervalle — la
  longueur du tracé n'est pas un multiple du pas ;
- l'altitude est lissée : elle ne correspond pas point par point au fichier, et
  le D+ total d'ici diffère de celui du fichier, parfois de plusieurs centaines
  de mètres (`docs/PIEGES_DATA.md`) ;
- la méthode de calcul de la distance (géodésique, projection) : seul son sens,
  horizontal, est fixé ici, parce que `grade = Δaltitude / distance
  horizontale` (`docs/decisions/0002`) ;
- `source` n'est pas vérifiée contre le `Route` d'origine ;
- les tableaux ne sont pas copiés ; ils sont exigés immuables.

---

## `Activity`

*`mountain_perf.schemas.activity` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `activity_ref` | `str` | — |
| `sport` | `Sport` | — |
| `source_activity_type` | `str \| None` | — |
| `start_time` | `datetime` | — |
| `elapsed_duration_s` | `float` | — |
| `moving_duration_s` | `float` | — |
| `distance_m` | `float` | — |
| `ascent_m` | `float` | — |
| `descent_m` | `float` | — |
| `average_hr_bpm` | `float \| None` | — |
| `max_hr_bpm` | `float \| None` | — |
| `stream_ref` | `str \| None` | — |
| `source` | `SourceRef` | — |
| `quality_flags` | `frozenset[QualityFlag]` | `frozenset()` |

| Propriété calculée | Type | Sens |
|---|---|---|
| `utc_offset_s` | `int` | Décalage local au départ (secondes), lu sur le fuseau de `start_time`. |

Métadonnées d'une sortie enregistrée.

#### Champs

- `activity_ref` — sans unité — identifiant stable de l'activité dans la source.
- `sport` — sans unité — famille de modèle qui s'applique.
- `source_activity_type` — sans unité — type d'activité de la source, tel quel
  (`activityType.typeKey` de Garmin).
- `start_time` — instant — départ, *aware*, **dans son fuseau local à décalage
  fixe** (pas en UTC).
- `elapsed_duration_s` — secondes — temps écoulé, `> 0`.
- `moving_duration_s` — secondes — temps en mouvement, `> 0`.
- `distance_m` — mètres — distance de la source, `>= 0`.
- `ascent_m`, `descent_m` — mètres — D+ et D− de la source, `>= 0`.
- `average_hr_bpm`, `max_hr_bpm` — battements par minute — FC moyenne et
  maximale, `[20, 250]`, si présentes.
- `stream_ref` — sans unité — **référence** au flux (`TrackPointStream`),
  jamais le flux lui-même.
- `quality_flags` — sans unité — suspicions ; vide par défaut.
- `source` — sans unité — provenance.

Propriété calculée (jamais stockée) : `utc_offset_s`, le décalage porté par le
fuseau de `start_time`.

**`start_time` n'est pas normalisé en UTC**, contrairement à
`SourceRef.retrieved_at` : son fuseau porte le décalage local, qui a un sens
physique ici (chaleur, nuit). Règle générale : un instant dont l'heure locale a un
sens physique se stocke dans son fuseau à décalage fixe, les autres en UTC
(`docs/decisions/0006`). Le décalage n'est pas un champ parallèle : deux sources
de vérité finiraient par diverger, et l'erreur d'une heure qui en résulte est
silencieuse. Les comparaisons d'instants restent justes quel que soit le fuseau.

#### Invariants

- `activity_ref` non vide ;
- flottants finis ;
- durées `> 0` et `moving_duration_s <= elapsed_duration_s` ;
- `distance_m`, `ascent_m`, `descent_m` `>= 0` ;
- FC dans `[20, 250]` si présentes, et `average_hr_bpm <= max_hr_bpm` si les
  deux le sont ;
- `start_time` *aware*, et son décalage dans `[-43200, 50400]` secondes — ce
  qui attrape une confusion secondes / minutes / heures.

**Les deux durées restent deux champs.** La vérité terrain est en temps écoulé ; si
un seul chiffre portait à la fois « j'allais moins vite » et « je me suis arrêté
plus longtemps », le backtest ne pourrait jamais dire laquelle des deux hypothèses
était fausse. L'une se corrige par la physiologie, l'autre par la logistique : deux
champs rendent le résidu attribuable.

#### Producteur

L'ingestion (M6b). Le producteur **attache le fuseau local à l'instant**, et ne
passe pas un instant en UTC nu : l'objet le prendrait pour une heure locale à
UTC+0, sans rien lever.

#### Consommateurs

L'estimation de courbe (M6b), qui filtre et sélectionne les activités.

#### Non promis

- **le flux n'est pas contenu**, seulement référencé ; `stream_ref` peut être
  absent ;
- `distance_m` est celle de la source, et **on ne sait pas encore si elle est 2D
  ou 3D** (à vérifier au M6b) : l'écart biaiserait la pente d'autant plus que la
  pente est forte ;
- `source_activity_type` n'est pas normalisé. **`sport` ne remplace pas ce
  filtre** (exclure le tapis, séparer marche et course) : il dit seulement quelle
  famille de modèle s'applique ;
- `utc_offset_s` est le décalage administratif ; l'heure *solaire*, qui compte
  physiquement pour la chaleur et la nuit, en diffère de quelques dizaines de
  minutes sur les Alpes (`docs/decisions/0006`) ;
- le fuseau d'origine de `start_time` n'est pas conservé : il est ramené à un
  fuseau à décalage fixe de même instant et de même heure murale ;
- `quality_flags` vide ne garantit pas l'absence de défaut.

---

## `TrackPointStream`

*`mountain_perf.schemas.activity` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `activity_ref` | `str` | — |
| `time_s` | `Sequence[float]` | — |
| `latitude_deg` | `Sequence[float] \| None` | — |
| `longitude_deg` | `Sequence[float] \| None` | — |
| `elevation_m` | `Sequence[float] \| None` | — |
| `distance_m` | `Sequence[float] \| None` | — |
| `speed_ms` | `Sequence[float] \| None` | — |
| `heart_rate_bpm` | `Sequence[float] \| None` | — |
| `source` | `SourceRef` | — |
| `quality_flags` | `frozenset[QualityFlag]` | `frozenset()` |

Flux point par point d'une activité.

Tableaux parallèles : le point `i` est `time_s[i]` et, pour chaque tableau
présent, sa valeur d'indice `i`.

#### Champs

- `activity_ref` — sans unité — l'`Activity` à laquelle le flux appartient.
- `time_s` — secondes — temps depuis le départ, `>= 0`.
- `latitude_deg`, `longitude_deg` — degrés — WGS84, dans leurs plages.
- `elevation_m` — mètres — altitudes, `[-500, 9000]`.
- `distance_m` — mètres — distance cumulée de la source.
- `speed_ms` — m/s — vitesse mesurée par le capteur, `>= 0`.
- `heart_rate_bpm` — battements par minute — FC, `[20, 250]`.
- `quality_flags` — sans unité — suspicions ; vide par défaut.
- `source` — sans unité — provenance.

Tous les tableaux sauf `time_s` sont optionnels (`None` = absent du flux).

#### Invariants

- `activity_ref` non vide ;
- tableaux en tuples, de même longueur que `time_s`, valeurs finies ;
- `time_s` : au moins 1 point, `>= 0`, strictement croissant ;
- `distance_m` **croissante au sens large** ;
- `speed_ms >= 0` ; coordonnées, altitudes et FC dans leurs plages.

**Un point suffit** là où `Route` et `RouteProfile` en exigent 2 : ceux-ci
définissent une géométrie, qui n'existe pas en dessous de deux points ; un flux est
un enregistrement, et un enregistrement d'un seul échantillon reste une mesure —
c'est à l'estimation de décider s'il sert.

Le sens large sur `distance_m` n'est pas un relâchement : **un coureur à l'arrêt
ne progresse pas**, et le sens strict rejetterait toute activité comportant une
pause. C'est le contraire du profil, strictement croissant parce que c'est une
grille.

`speed_ms` est **stocké et non dérivé** de `distance_m` et `time_s` : c'est
une mesure indépendante du capteur, qui ne vaut pas exactement `Δd/Δt`.

#### Producteur

L'ingestion (M6b).

#### Consommateurs

L'estimation de courbe (M6b).

#### Non promis

- la régularité de l'échantillonnage ;
- la présence d'un champ donné ;
- `time_s[0]` n'est **pas** garanti nul ;
- la correspondance entre `distance_m` et un recalcul depuis les positions ;
- `activity_ref` n'est pas vérifié contre une `Activity` existante ;
- les tableaux ne sont pas copiés ; ils sont exigés immuables.

---

## `CurveProvenance`

*`mountain_perf.schemas.curve` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `activity_count` | `int` | — |
| `hr_center_bpm` | `float \| None` | — |
| `hr_width_bpm` | `float \| None` | — |
| `date_from` | `date` | — |
| `date_to` | `date` | — |
| `source_activity_types` | `frozenset[str]` | — |
| `min_duration_s` | `float \| None` | — |
| `estimator` | `str` | — |
| `generated_at` | `datetime` | — |

Comment une courbe a été estimée : sur quelles activités, avec quels filtres.

#### Champs

- `activity_count` — sans unité — nombre d'activités ayant servi, `>= 0`.
- `hr_center_bpm` — battements par minute — centre de la fenêtre de FC retenue,
  `[20, 250]`, si un filtre de FC a été appliqué.
- `hr_width_bpm` — battements par minute — largeur de cette fenêtre, `> 0`.
- `date_from`, `date_to` — dates civiles — fenêtre des activités retenues.
- `source_activity_types` — sans unité — types d'activité de la source retenus
  (`Activity.source_activity_type`).
- `min_duration_s` — secondes — durée minimale d'une activité retenue, `>= 0`.
- `estimator` — sans unité — nom libre de la méthode d'estimation.
- `generated_at` — instant — moment de l'estimation, *aware*, stocké en UTC.

#### Invariants

- `activity_count >= 0` ;
- `hr_center_bpm` et `hr_width_bpm` présents ensemble ou absents ensemble ;
  finis ; centre dans `[20, 250]`, largeur `> 0` ;
- `date_from <= date_to` ;
- `min_duration_s` fini et `>= 0` si présent ;
- `estimator` non vide ;
- `generated_at` *aware*, normalisé en UTC.

**Pourquoi la provenance est un champ et non un commentaire** : il y aura plusieurs
courbes pour un même sport — course, randonnée, fin de saison, FC 150. Marcher les
descentes au lieu de les courir ne change pas l'échelle de la courbe, ça change sa
**forme**, et appliquer la mauvaise courbe ne lève aucune erreur.

#### Producteur

L'estimation de courbe (M6b) ; une saisie manuelle pour la courbe figée du M3.

#### Consommateurs

Le choix explicite de la courbe dans un scénario ; le backtest (M4), qui doit dire
sur quoi la courbe a été calibrée.

#### Non promis

- un `source_activity_types` **vide signifie « aucun filtre »**, pas « aucune
  activité » ;
- `activity_count = 0` est légitime : courbe figée du M3, issue d'un CSV et non
  d'activités ;
- `date_from` et `date_to` sont des **dates civiles sans fuseau** ; la borne
  incluse ou exclue n'est pas fixée ici ;
- `estimator` est une chaîne libre en M1 : aucun code ne doit s'y brancher ;
- rien n'est vérifié contre les activités elles-mêmes.

---

## `PaceCurve`

*`mountain_perf.schemas.curve` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `sport` | `Sport` | — |
| `grade` | `Sequence[float]` | — |
| `speed_ms` | `Sequence[float]` | — |
| `sample_count` | `Sequence[int]` | — |
| `dispersion_ms` | `Sequence[float] \| None` | — |
| `estimation` | `CurveProvenance` | — |
| `source` | `SourceRef \| None` | — |

Courbe vitesse horizontale = f(pente), par tranches de pente.

Tableaux parallèles : la tranche `i` est centrée sur `grade[i]`, de vitesse
`speed_ms[i]`, estimée sur `sample_count[i]` points.

#### Champs

- `sport` — sans unité — famille de modèle ; sert à interdire les croisements
  absurdes, **pas** à choisir la courbe.
- `grade` — fraction — centres de tranches, `[-2, 2]`,
  `Δaltitude / distance horizontale` ; jamais un pourcentage.
- `speed_ms` — m/s — vitesse horizontale de chaque tranche, `> 0`.
- `sample_count` — sans unité — points ayant servi à chaque tranche, `>= 0`.
- `dispersion_ms` — m/s — dispersion de la vitesse dans la tranche, `>= 0`,
  si estimée.
- `estimation` — sans unité — provenance de l'estimation.
- `source` — sans unité — fichier d'origine, si la courbe en vient (CSV du M3).

#### Invariants

- tableaux en tuples, de même longueur, au moins 2 tranches ;
- flottants finis ;
- `grade` strictement croissant et dans `[-2, 2]` ;
- `speed_ms > 0` ; `sample_count >= 0` ; `dispersion_ms >= 0` si présente.

`sample_count` dit **où la courbe est soutenue par des données** et où elle n'est
qu'une interpolation : indispensable au M8 pour la dispersion, et pour savoir
jusqu'où on a le droit de croire les pentes extrêmes.

#### Producteur

L'estimation de courbe (M6b) ; la lecture d'un CSV figé (M3).

#### Consommateurs

Le moteur de projection (M3), choisie **explicitement** dans le scénario.

#### Non promis

- **l'interpolation entre deux tranches** : c'est du M3 ;
- **l'extrapolation hors de la plage observée** : que vaut la vitesse à −60 % si la
  courbe s'arrête à −40 % ? Non décidé ici, et une interpolation naïve y est
  généralement absurde (ligne de `BACKLOG.md`, M3) ;
- l'espacement régulier des tranches ;
- `Sport` ne choisit pas la courbe : plusieurs courbes coexistent pour un sport ;
- les tableaux ne sont pas copiés ; ils sont exigés immuables.

---

## `Passage`

*`mountain_perf.schemas.projection` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `point` | `ResolvedPoint` | — |
| `moving_time_s` | `float` | — |
| `arrival_s` | `float` | — |
| `departure_s` | `float` | — |

| Propriété calculée | Type | Sens |
|---|---|---|
| `stop_duration_s` | `float` | Temps d'arrêt au point (secondes) : `departure_s - arrival_s`. |

Passage projeté à un point du tracé : temps cumulés depuis le départ.

#### Champs

- `point` — sans unité — le passage résolu sur le profil (abscisse, altitude).
- `moving_time_s` — secondes — temps de mouvement cumulé, `>= 0`.
- `arrival_s` — secondes — temps écoulé cumulé à l'arrivée au point, `>= 0`.
- `departure_s` — secondes — temps écoulé cumulé au départ du point, `>= 0`.

Propriété calculée (jamais stockée) : `stop_duration_s`.

#### Invariants

- valeurs finies et `>= 0` ;
- `departure_s >= arrival_s` ;
- `moving_time_s <= arrival_s`.

Une seule valeur de temps de mouvement : on n'avance pas pendant un arrêt, elle est
la même à l'arrivée et au départ.

#### Producteur

Le moteur de projection (M3, puis M6a).

#### Consommateurs

`Projection` ; l'affichage des passages (M5) ; le backtest (M4).

#### Non promis

- en M3 le modèle ne connaît pas les arrêts : `arrival_s == departure_s`. Au M6a
  ils s'écartent, **sans que le contrat bouge** ;
- l'origine des temps (`0`) est le départ de la projection, pas une heure.

---

## `Segment`

*`mountain_perf.schemas.projection` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `start` | `Passage` | — |
| `end` | `Passage` | — |
| `ascent_m` | `float` | — |
| `descent_m` | `float` | — |
| `elevation_min_m` | `float` | — |
| `elevation_max_m` | `float` | — |

| Propriété calculée | Type | Sens |
|---|---|---|
| `duration_s` | `float` | Durée du tronçon (secondes) : `end.arrival_s - start.departure_s`. |
| `distance_m` | `float` | Longueur horizontale du tronçon (mètres) : différence des abscisses. |

Tronçon entre deux passages consécutifs d'une projection.

#### Champs

- `start`, `end` — sans unité — les deux passages qui bornent le tronçon.
- `ascent_m`, `descent_m` — mètres — D+ et D− du tronçon, `>= 0`.
- `elevation_min_m`, `elevation_max_m` — mètres — altitudes extrêmes du
  tronçon, `[-500, 9000]`.

Propriétés calculées (jamais stockées) : `duration_s`
(`end.arrival_s - start.departure_s`) et `distance_m` (différence des
abscisses).

Les altitudes et dénivelés sont stockés parce qu'ils ne se recalculent pas depuis
les deux passages seuls : il faut le profil.

#### Invariants

- valeurs finies ; `ascent_m`, `descent_m` `>= 0` ;
- altitudes dans `[-500, 9000]` et `elevation_min_m <= elevation_max_m` ;
- `end` n'est pas avant `start` : ni en abscisse, ni en temps
  (`end.arrival_s >= start.departure_s`).

#### Producteur

**Uniquement** `Projection.segments`.

#### Consommateurs

Le diagnostic d'erreur par tronçon (M4), l'affichage (M5).

#### Non promis

- **la cohérence des grandeurs avec un profil n'est pas garantie** par ce type :
  seule `Projection.segments` en produit de cohérentes. Un `Segment` construit
  à la main peut porter n'importe quel D+ ;
- les altitudes extrêmes se lisent sur le profil **lissé et rééchantillonné**, pas
  sur le GPX brut : elles diffèrent d'une application de cartographie, parfois de
  plusieurs dizaines de mètres, sans que ce soit un bug.

---

## `Projection`

*`mountain_perf.schemas.projection` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `profile` | `RouteProfile` | — |
| `curve_ref` | `str` | — |
| `parameters` | `ParameterSet` | — |
| `passages` | `tuple[Passage, ...]` | — |
| `start_time` | `datetime \| None` | — |
| `engine_version` | `str` | — |
| `generated_at` | `datetime` | — |

| Propriété calculée | Type | Sens |
|---|---|---|
| `utc_offset_s` | `int \| None` | Décalage local au départ (secondes), lu sur le fuseau de `start_time`. |
| `segments` | `tuple[Segment, ...]` | Tronçons entre passages consécutifs, dérivés des passages et du profil. |

Un scénario projeté sur un tracé : les passages, et les segments qui en dérivent.

#### Champs

- `profile` — sans unité — le profil projeté.
- `curve_ref` — sans unité — référence de la `PaceCurve` utilisée.
- `parameters` — sans unité — paramètres du modèle pour ce scénario.
- `passages` — sans unité — passages par abscisse croissante, départ et arrivée
  compris.
- `start_time` — instant — heure de départ, *aware*, **dans son fuseau local à
  décalage fixe** (pas en UTC) ; ancre les effets d'heure. Absent si non fixé.
- `engine_version` — sans unité — version du moteur qui a produit la projection.
- `generated_at` — instant — moment du calcul, *aware*, stocké en UTC.

Propriétés calculées (jamais stockées) : `segments`, `utc_offset_s`.

`start_time` n'est pas normalisé en UTC, contrairement à `generated_at` : son
fuseau porte le décalage local, qui a un sens physique (chaleur, nuit). Un instant
dont l'heure locale a un sens physique se stocke dans son fuseau à décalage fixe,
les autres en UTC (`docs/decisions/0006`).

#### Invariants

- `curve_ref` et `engine_version` non vides ;
- `passages` est un tuple d'au moins 2 passages ;
- abscisses croissantes au sens large ; **le premier passage est à l'abscisse 0 et
  le dernier à la fin du profil** ;
- pour deux passages consécutifs `i`, `i + 1` : `departure_s[i] <=
  arrival_s[i + 1]` (durée de segment `>= 0`, d'où `arrival_s` et
  `departure_s` croissants), `moving_time_s` croissant au sens large, et
  `moving_time_s[i + 1] - moving_time_s[i] <= arrival_s[i + 1] - departure_s[i]`
  à `TIME_TOLERANCE_S` près (on ne bouge pas plus longtemps que le temps écoulé
  sur le segment) ;
- `start_time` *aware* si présent, décalage dans `[-43200, 50400]` secondes ;
- `generated_at` *aware*, normalisé en UTC.

**La projection synthétise toujours un passage de départ et un d'arrivée**, même
si le GPX ne porte pas de waypoint à ces endroits : sans eux, les segments ne
couvrent pas la tête ni la queue du parcours et le total ne ferme pas.

**Invariant central** — les arrêts se somment sur les passages **intérieurs**
(`passages[1:-1]`)::

    Σ segment.duration_s + Σ passages[1:-1].stop_duration_s
        == passages[-1].arrival_s - passages[0].departure_s

Sommer les arrêts de *tous* les passages donne `passages[-1].departure_s -
passages[0].arrival_s`, une autre quantité : l'écart est l'arrêt au premier
passage plus l'arrêt au dernier.

#### Producteur

Le moteur de projection (M3, puis M6a, M7).

#### Consommateurs

L'interface (M5), le backtest (M4), la comparaison de scénarios (M9), la couche
d'incertitude (M8).

#### Non promis

- **une projection est un scénario, pas une fourchette.** Comparer deux scénarios,
  c'est comparer deux `Projection`. Pas de P50/P80 ici : **les quantiles ne
  s'additionnent pas** — le P80 du temps total n'est pas la somme des P80 par
  segment (c'est la variance qui s'additionne, pas l'écart-type), donc sommer des
  P80 surestime largement la fourchette. La couche d'incertitude du M8 sera une
  distribution *sur* les projections, pas une projection aux nombres plus larges ;
- `curve_ref` n'est pas résolu ni vérifié ; le `Sport` de la courbe n'est pas
  recoupé ici ;
- les passages ne sont pas vérifiés contre `profile.resolved_points` : départ et
  arrivée synthétisés n'y figurent pas forcément ;
- D+, D− et altitudes des segments supposent **l'altitude linéaire entre deux
  points de la grille** — l'hypothèse même de `RouteProfile.grade` ;
- `utc_offset_s` est le décalage **au départ** : une projection qui franchit un
  changement d'heure calculera les heures locales avec une heure d'écart après la
  bascule ;
- le fuseau d'origine de `start_time` n'est pas conservé : il est ramené à un
  fuseau à décalage fixe de même instant et de même heure murale ;
- l'origine des temps n'est pas garantie nulle (`passages[0].arrival_s`).

---

## `TimingConvention`

*`mountain_perf.schemas.reference` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `DEPARTURE` | `departure` | Temps au départ du point — défaut du projet : raisonnement de course et barrières horaires. |
| `ARRIVAL` | `arrival` | Temps à l'arrivée au point. |
| `UNKNOWN` | `unknown` | Convention non connue pour ce relevé. |

Ce que mesure un temps de passage relevé : l'arrivée au point ou le départ.

#### Champs

Valeurs décrites dans `TIMING_CONVENTION_DESCRIPTIONS`.

#### Invariants

Énumération fermée. `DEPARTURE` est le défaut du projet ; `UNKNOWN` est une
valeur honnête, pas une erreur.

#### Producteur

La lecture des relevés de référence (M4), passage par passage.

#### Consommateurs

L'appariement projection ↔ référence (M4), qui compare au `departure_s` ou à
l'`arrival_s` d'un `Passage` ; l'affichage et l'export (option `ARRIVAL`).

#### Non promis

Rien ne devine la convention d'un relevé : les relevés réels mélangent les deux
sans le dire (`docs/PIEGES_DATA.md`). Faute d'information, c'est `UNKNOWN`.

---

## `ObservedPassage`

*`mountain_perf.schemas.reference` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `point_name` | `str` | — |
| `elapsed_s` | `float` | — |
| `distance_m` | `float \| None` | — |
| `convention` | `TimingConvention` | — |

Temps de passage relevé à un point, lors d'une performance réelle.

#### Champs

- `point_name` — sans unité — nom du point tel que relevé.
- `elapsed_s` — secondes — temps écoulé depuis le départ, `>= 0`.
- `distance_m` — mètres — abscisse du point sur le tracé, `>= 0`, si le point
  a pu être situé.
- `convention` — sans unité — ce que mesure `elapsed_s` : arrivée, départ, ou
  inconnu.

#### Invariants

- `point_name` non vide ;
- `elapsed_s` fini et `>= 0` ;
- `distance_m` fini et `>= 0` si présent.

#### Producteur

La lecture des relevés de référence (M4).

#### Consommateurs

`ReferencePerformance` ; l'appariement et la métrique d'erreur (M4).

#### Non promis

- `point_name` n'est pas garanti identique au nom d'un `NamedPoint` ;
- `distance_m` n'est pas garanti sur la même grille ni le même tracé qu'un
  `RouteProfile` donné ;
- la convention est portée **par passage** : deux passages d'une même performance
  peuvent en avoir deux différentes.

---

## `ReferencePerformance`

*`mountain_perf.schemas.reference` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `athlete_ref` | `str` | — |
| `event_name` | `str` | — |
| `date` | `date` | — |
| `passages` | `tuple[ObservedPassage, ...]` | — |
| `source` | `SourceRef` | — |

Performance réelle chronométrée : la vérité terrain du backtest.

#### Champs

- `athlete_ref` — sans unité — **pseudonyme** de l'athlète, jamais un nom réel.
- `event_name` — sans unité — nom de l'épreuve ou de la sortie.
- `date` — date civile — jour de la performance.
- `passages` — sans unité — temps relevés, dans l'ordre du parcours.
- `source` — sans unité — provenance du relevé.

#### Invariants

- `athlete_ref` et `event_name` non vides ;
- `passages` est un tuple d'au moins 2 passages ;
- `elapsed_s` croissant au sens large le long de la liste.

#### Producteur

La lecture des relevés de référence (M4).

#### Consommateurs

Le backtest (M4).

#### Non promis

- **l'appariement avec une projection n'est pas défini ici** : rapprocher un
  `ObservedPassage` d'un `Passage` — par nom, par abscisse, avec quelle
  tolérance — est du M4 ;
- **seule une performance dont `athlete_ref` désigne l'athlète du projet peut
  être évaluée contre une projection.** Pour les autres coureurs il n'y a ni
  données d'entraînement, ni courbe, ni projection : comparer une projection issue
  de *sa* courbe au temps de *quelqu'un d'autre* ne produit pas un résultat faux,
  il en produit un dépourvu de sens — et qui ne se voit pas, noyé dans une erreur
  moyenne un peu plus grande. `athlete_ref` est un garde-fou, **pas** une gestion
  multi-athlètes, et rien ici ne vérifie qui il désigne ;
- les données de population (plusieurs centaines de coureurs) ne sont **pas**
  modélisées : leur usage n'est pas défini ;
- la monotonie de `elapsed_s` ne dit rien des conventions : un mélange
  `ARRIVAL` / `DEPARTURE` passe, et c'est voulu ;
- l'ordre des `distance_m` n'est pas vérifié.

---

## `OutingLabel`

*`mountain_perf.schemas.outing` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `RACE` | `race` | Course : effort de compétition, exclu du calage. |
| `TRAINING` | `training` | Entraînement. |

Étiquette course / entraînement d'une sortie (`0010` D2.4).

#### Champs

Valeurs décrites dans `OUTING_LABEL_DESCRIPTIONS`.

#### Invariants

Énumération fermée. L'absence d'étiquette s'écrit `None` sur la sortie, et
**ne vaut pas** entraînement.

#### Producteur

Le manifeste (M4a), sortie par sortie.

#### Consommateurs

`Performance.all_training` ; le calage (M4c), qui n'apprend que sur des
performances d'entraînement.

#### Non promis

Rien ne devine l'étiquette d'une sortie à partir de son nom, de sa date ou de son
parcours.

---

## `DataSet`

*`mountain_perf.schemas.outing` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `REPEATABILITY` | `repeatability` | Répétabilité : parcours répétés dans la fenêtre de la courbe ; scores « apprentissage ». |
| `DEVELOPMENT` | `development` | Développement : après la fenêtre, déjà regardées ; résultats indicatifs. |
| `CONFIRMATION` | `confirmation` | Confirmation : origine postérieure au figement de la déclaration du candidat. |

Jeu auquel une sortie est déclarée appartenir (`0010` D2.3).

#### Champs

Valeurs décrites dans `DATA_SET_DESCRIPTIONS`.

#### Invariants

Énumération fermée ; une sortie sans jeu déclaré porte `None`.

#### Producteur

Le manifeste (M4a).

#### Consommateurs

La référence de répétabilité (M4b) et le rapport (M4b), qui sépare les agrégats
par jeu.

#### Non promis

Le jeu n'est pas recoupé avec les dates de la sortie ni avec la fenêtre de la
courbe : il est déclaré, pas déduit.

---

## `ReferenceKind`

*`mountain_perf.schemas.outing` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `PREPARED` | `prepared` | Préparé : le tracé prévu avant la sortie. |
| `DESIGNATED_TRACE` | `designated_trace` | Trace de référence désignée à l'avance, faute de préparé. |

Nature du tracé de référence d'une sortie (`0010` D2.1, D2.6).

#### Champs

Valeurs décrites dans `REFERENCE_KIND_DESCRIPTIONS`.

#### Invariants

Énumération fermée.

#### Producteur

Le manifeste (M4a).

#### Consommateurs

Le choix du profil de domaine (M4a, orchestré en M4b) et l'appariement (M4a-2).

#### Non promis

Rien ne vérifie qu'une trace de référence désignée a bien été désignée **avant**
la sortie : c'est la date de disponibilité de l'artefact qui en répond.

---

## `ArtifactRole`

*`mountain_perf.schemas.outing` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `FORECAST_INPUT` | `forecast_input` | Entrée de prévision : courbe, préparé ou trace de référence, paramètres, historique de calage ; doit être disponible à l'origine. |
| `EVALUATION_OBSERVATION` | `evaluation_observation` | Observation d'évaluation : trace réalisée, fin réelle ; postérieure par nature, jamais testée à l'origine. |

Rôle d'un artefact dans une évaluation (`0010` D2.6).

#### Champs

Valeurs décrites dans `ARTIFACT_ROLE_DESCRIPTIONS`.

#### Invariants

Énumération fermée.

#### Producteur

Le manifeste (M4a).

#### Consommateurs

Le test de disponibilité à l'origine (M4c, confirmation), qui ne porte que sur
les entrées de prévision.

#### Non promis

Le rôle ne dit pas si l'artefact a effectivement servi à une prévision donnée.

---

## `Unavailability`

*`mountain_perf.schemas.outing` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `ABSENT` | `absent` | absent — observation introuvable. |
| `AMBIGUOUS` | `ambiguous` | ambigu — plusieurs observations candidates, jamais départagées par l'erreur d'un modèle. |
| `UNDEFINED_TANGENT` | `undefined_tangent` | tangente indéfinie — corde du profil trop courte pour orienter une normale. |
| `GAP` | `gap` | trou — un trou d'enregistrement de plus de 10 s. |
| `INTERIOR_DEVIATION` | `interior_deviation` | écart intérieur — la trace s'écarte du tracé à l'intérieur d'un segment. |
| `INSUFFICIENT_SUPPORT` | `insufficient_support` | support insuffisant — pas assez d'observations admises. |
| `ZERO_TIME` | `zero_time` | temps nul — un temps observé nul sous une horloge. |
| `UNIDENTIFIED_REFERENCE` | `unidentified_reference` | référence non identifiée — gabarit de répétabilité non identifiable. |
| `NON_CONVERGENCE` | `non_convergence` | non-convergence — limite d'itérations atteinte. |
| `MODEL_ERROR` | `model_error` | erreur du modèle — sortie de modèle nulle, négative, non finie ou manquante. |
| `NOT_CALIBRATED` | `not_calibrated` | non calé — population de calage vide. |
| `MULTI_OUTING_DAY` | `multi_outing_day` | jour multi-sorties — performance de plusieurs sorties, non évaluable. |

Statut d'une valeur non calculable (`0010` D0).

#### Champs

Valeurs décrites dans `UNAVAILABILITY_DESCRIPTIONS` ; chaque description
commence par le nom français du protocole.

#### Invariants

Énumération fermée : les douze statuts de `0010` D0, ni plus ni moins.

#### Producteur

Le backtest (M4a à M4d), là où une valeur ne peut pas être calculée.

#### Consommateurs

Le rapport (M4b) et la règle d'admission (M4c).

#### Non promis

Un statut ne vaut jamais zéro, ni « parfait », ni « échec sportif » ; un contrôle
obligatoire indisponible ne vaut pas satisfaction. Aucun producteur n'existe en
M4a-1 : le type est posé pour les lots suivants.

---

## `ArtifactRef`

*`mountain_perf.schemas.outing` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `source` | `SourceRef` | — |
| `available_at` | `datetime` | — |
| `role` | `ArtifactRole` | — |

Fichier utilisé par le backtest, avec son empreinte, sa disponibilité, son rôle.

#### Champs

- `source` — sans unité — nom du fichier et empreinte `sha256`.
- `available_at` — instant — moment à partir duquel l'artefact existait,
  *aware*, stocké en UTC.
- `role` — sans unité — entrée de prévision ou observation d'évaluation.

#### Invariants

`available_at` porte un fuseau ; il est normalisé en UTC à la construction.

#### Producteur

Le manifeste (M4a) : pour une trace ou un doublon, `available_at` est la fin de
la sortie ; pour une référence, l'instant déclaré.

#### Consommateurs

`Outing`, `RouteReference` ; le registre (M4b) ; le test de disponibilité à
l'origine (M4c).

#### Non promis

- `available_at` d'une observation d'évaluation n'est jamais testé à l'origine
  (`0010` D2.6) ;
- rien ne vérifie que le fichier existe encore, ni où il se trouve : `source`
  ne porte qu'un nom de fichier (règle 1).

---

## `RouteReference`

*`mountain_perf.schemas.outing` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `kind` | `ReferenceKind` | — |
| `artifact` | `ArtifactRef` | — |

Tracé de référence d'une sortie : préparé ou trace désignée à l'avance.

#### Champs

- `kind` — sans unité — préparé ou trace de référence désignée.
- `artifact` — sans unité — le fichier du tracé.

#### Invariants

`artifact.role` vaut `FORECAST_INPUT` : un tracé de référence est une entrée
de prévision.

#### Producteur

Le manifeste (M4a).

#### Consommateurs

Le profil de domaine (`0010` D2.1) et l'appariement (M4a-2).

#### Non promis

Le profil n'est pas construit ici ; le fichier n'est pas relu.

---

## `Outing`

*`mountain_perf.schemas.outing` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `outing_id` | `str` | — |
| `athlete_ref` | `str` | — |
| `sport` | `Sport` | — |
| `start_time` | `datetime` | — |
| `end_time` | `datetime` | — |
| `traces` | `tuple[ArtifactRef, ...]` | `()` |
| `duplicates` | `tuple[ArtifactRef, ...]` | `()` |
| `route_id` | `str \| None` | `None` |
| `variant` | `str \| None` | `None` |
| `declared_portion_m` | `tuple[float, float] \| None` | `None` |
| `reference` | `RouteReference \| None` | `None` |
| `dataset` | `DataSet \| None` | `None` |
| `label` | `OutingLabel \| None` | `None` |
| `external_records` | `tuple[ReferencePerformance, ...]` | `()` |

| Propriété calculée | Type | Sens |
|---|---|---|
| `elapsed_s` | `float` | Durée écoulée de la sortie (secondes) : `end_time − start_time`. |

Une sortie du manifeste, résolue : fichiers, instants, déclarations.

#### Champs

- `outing_id` — sans unité — identifiant stable de la sortie.
- `athlete_ref` — sans unité — pseudonyme de l'athlète.
- `sport` — sans unité — famille de modèle.
- `start_time`, `end_time` — instants — départ et fin, *aware*, stockés en
  UTC.
- `traces` — sans unité — fichiers de la trace réalisée, dans l'ordre de
  concaténation ; vide pour une sortie non tracée.
- `duplicates` — sans unité — autres enregistrements de la même sortie, hachés,
  jamais lus.
- `route_id`, `variant` — sans unité — parcours et variante déclarés.
- `declared_portion_m` — mètres — portion déclarée `(a, b)` du parcours.
- `reference` — sans unité — préparé ou trace de référence désignée.
- `dataset` — sans unité — jeu déclaré.
- `label` — sans unité — course ou entraînement ; `None` si absent.
- `external_records` — sans unité — relevés externes de la sortie.

Propriété calculée (jamais stockée) : `elapsed_s`.

#### Invariants

- `outing_id` et `athlete_ref` non vides ;
- `start_time` et `end_time` portent un fuseau, sont normalisés en UTC, et
  `start_time < end_time` ;
- `traces`, `duplicates` et `external_records` sont des tuples ;
- chaque trace et chaque doublon a le rôle `EVALUATION_OBSERVATION` ;
- `duplicates` non vide ⇒ `traces` non vide ;
- `route_id` et `variant` sont `None` ou non vides ;
- `declared_portion_m` est `None` ou un tuple `(a, b)` fini avec
  `0 <= a < b` ;
- chaque relevé externe porte l'`athlete_ref` de la sortie.

#### Producteur

Le manifeste (M4a).

#### Consommateurs

La rétention, le domaine et les performances (M4a) ; l'appariement (M4a-2) ; le
calage (M4c).

#### Non promis

- pour une sortie tracée, `start_time` et `end_time` sont les instants du
  premier et du dernier enregistrement, pas ceux d'une montre ;
- l'heure locale n'est pas conservée (un effet qui en aurait besoin, au M7, la
  lira sur l'`Activity` du M6b) ;
- le jour civil, le rang, la rétention et le domaine ne sont pas stockés : ils se
  dérivent ;
- `outing_id` n'est unique que dans un manifeste, et c'est le lecteur qui le
  vérifie, pas le type ;
- `dataset` n'est pas recoupé avec les dates ; `declared_portion_m` n'est pas
  recoupé avec la longueur d'un profil.

---

## `RetentionDecision`

*`mountain_perf.schemas.outing` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `outing` | `Outing` | — |
| `civil_date` | `date` | — |
| `rank` | `int` | — |
| `cumulative_elapsed_s` | `float` | — |
| `retained` | `bool` | — |

Décision de rétention d'une sortie dans son jour civil (`0010` D0).

#### Champs

- `outing` — sans unité — la sortie.
- `civil_date` — date civile — jour civil de son départ, à Paris.
- `rank` — sans unité — rang dans le jour, à partir de 1.
- `cumulative_elapsed_s` — secondes — somme des écoulés des sorties du jour
  jusqu'à celle-ci incluse, tous sports confondus.
- `retained` — sans unité — la sortie est-elle retenue.

#### Invariants

- `rank >= 1` ;
- `cumulative_elapsed_s` fini et `>= outing.elapsed_s` (à `1e−6` s près).

#### Producteur

`retain_outings` (`mountain_perf.backtest.outings`).

#### Consommateurs

Le regroupement en performances (M4a) ; le rapport (M4b), qui publie les sorties
non retenues en diagnostic.

#### Non promis

- la règle de rétention elle-même (la fonction la porte) : `retained` n'est pas
  recoupé avec `rank` et le cumul ;
- le jour civil n'est pas recoupé avec le départ ;
- le domaine n'est pas évalué ici.

---

## `Performance`

*`mountain_perf.schemas.outing` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `civil_date` | `date` | — |
| `outings` | `tuple[Outing, ...]` | — |

| Propriété calculée | Type | Sens |
|---|---|---|
| `athlete_ref` | `str` | Pseudonyme de l'athlète, commun à toutes les sorties. |
| `is_multi_outing` | `bool` | Vrai si la performance compte plus d'une sortie (« jour multi-sorties »). |
| `all_training` | `bool` | Vrai si toutes les sorties sont étiquetées entraînement (`0010` D2.4). |
| `end_time` | `datetime` | Instant de fin le plus tardif des sorties (la performance est terminée). |

Les sorties retenues et dans le domaine d'un même jour civil (`0010` D0).

Unité statistique de toutes les décisions du backtest : plis, moyennes, votes,
calage.

#### Champs

- `civil_date` — date civile — le jour, à Paris.
- `outings` — sans unité — les sorties, dans l'ordre de leur rang.

Propriétés calculées (jamais stockées) : `athlete_ref`, `is_multi_outing`,
`all_training`, `end_time`.

#### Invariants

- `outings` est un tuple d'au moins une sortie ;
- identifiants distincts ;
- même `athlete_ref` pour toutes les sorties ;
- ordre strictement croissant de `(start_time, outing_id)`.

#### Producteur

`group_performances` (`mountain_perf.backtest.outings`).

#### Consommateurs

La référence de répétabilité (M4b), le calage et l'admission (M4c).

#### Non promis

- le jour civil n'est pas recoupé avec les instants par le type (il faut un
  fuseau : c'est le regroupement qui le garantit) ;
- la rétention et le domaine ne sont pas revérifiés ;
- le jeu déclaré n'est pas agrégé ;
- une performance de plusieurs sorties est « jour multi-sorties » : le type la
  représente, il ne dit pas comment l'évaluer.

---

## `RecordedTrace`

*`mountain_perf.schemas.trace` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `start_time` | `datetime` | — |
| `time_s` | `tuple[float, ...]` | — |
| `latitude_deg` | `tuple[float, ...]` | — |
| `longitude_deg` | `tuple[float, ...]` | — |
| `elevation_m` | `tuple[float, ...]` | — |
| `sources` | `tuple[SourceRef, ...]` | — |
| `dropped_same_instant_count` | `int` | — |

| Propriété calculée | Type | Sens |
|---|---|---|
| `end_time` | `datetime` | Instant du dernier enregistrement, en UTC. |
| `elapsed_s` | `float` | Écoulé `E` (secondes) : `time_s[-1]`, trous compris (`0010` D5.1). |

Trace réalisée d'une sortie, telle que lue, enregistrements dans l'ordre.

Tableaux parallèles : l'enregistrement `i` est à l'instant
`start_time + time_s[i]`, en `(latitude_deg[i], longitude_deg[i],
elevation_m[i])`.

#### Champs

- `start_time` — instant — premier enregistrement, *aware*, stocké en UTC.
- `time_s` — secondes — temps depuis `start_time`.
- `latitude_deg`, `longitude_deg` — degrés — positions brutes WGS84.
- `elevation_m` — mètres — altitudes brutes.
- `sources` — sans unité — un fichier par tronçon, dans l'ordre de
  concaténation.
- `dropped_same_instant_count` — sans unité — enregistrements écartés parce
  qu'ils répétaient l'instant du dernier conservé.

Propriétés calculées (jamais stockées) : `end_time` et `elapsed_s` (l'écoulé
`E` de `0010` D5.1, trous compris).

#### Invariants

- `start_time` porte un fuseau ; il est normalisé en UTC ;
- les quatre tableaux et `sources` sont des tuples ;
- les quatre tableaux ont la même longueur, au moins 2 enregistrements ;
- valeurs finies ; coordonnées et altitudes dans leurs plages ;
- `time_s[0] == 0` et `time_s` strictement croissant ;
- au moins une source ;
- `dropped_same_instant_count >= 0`.

#### Producteur

`read_trace` (`mountain_perf.gpx.trace_reader`).

#### Consommateurs

Le manifeste (M4a) ; les séries dérivées et les horloges (M4a) ; l'appariement
(M4a-2).

#### Non promis

- l'échantillonnage est irrégulier ;
- **aucune position n'est dédoublonnée** : les enregistrements immobiles restent ;
- aucun lissage, aucun bloc, aucun trou détecté : ce sont des séries dérivées ;
- ce n'est pas un `TrackPointStream`, qui décrit un flux Garmin (M6b) ;
- les tableaux ne sont pas copiés ; ils sont exigés immuables.

---

## `IntervalState`

*`mountain_perf.schemas.clock` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `MOVING` | `moving` | M — mouvement : fenêtre mobile. |
| `STOPPED` | `stopped` | S — arrêt : suite d'intervalles immobiles d'une durée au moins égale au seuil de la convention. |
| `UNDETERMINED` | `undetermined` | U — indéterminé : trou, fenêtre invalide ou indéterminée, ou immobilité trop courte. |

État d'un intervalle élémentaire sous une convention (`0010` D5.2).

#### Champs

Valeurs décrites dans `INTERVAL_STATE_DESCRIPTIONS`.

#### Invariants

Énumération fermée : chaque intervalle reçoit un seul état par convention.

#### Producteur

La partition des horloges (`mountain_perf.backtest.clocks`).

#### Consommateurs

`ClockPartition` ; les horloges cumulées et les épisodes d'arrêt (M4a) ;
l'association arrêt → passage (M4a-3).

#### Non promis

`STOPPED` n'est pas un arrêt physique prouvé : le détecteur n'est pas validé
(`0010`, Conséquences).

---

## `ClockConvention`

*`mountain_perf.schemas.clock` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `max_horizontal_speed_ms` | `float` | — |
| `max_vertical_speed_ms` | `float` | — |
| `min_stop_s` | `float` | — |

Seuils d'une convention de détection du mouvement `θ = (h ; z ; c)`.

#### Champs

- `max_horizontal_speed_ms` — m/s — `h`, vitesse horizontale maximale d'une
  fenêtre immobile.
- `max_vertical_speed_ms` — m/s — `z`, vitesse verticale maximale, en valeur
  absolue.
- `min_stop_s` — secondes — `c`, durée minimale d'une suite immobile pour
  qu'elle devienne un arrêt.

#### Invariants

Les trois valeurs sont finies et `> 0`.

#### Producteur

`CLOCK_CONVENTIONS`, fixé par `0010` D5.2.

#### Consommateurs

La partition des horloges (M4a).

#### Non promis

Aucune convention n'est calée ni validée sur des arrêts connus.

---

## `ClockKind`

*`mountain_perf.schemas.clock` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `ELAPSED` | `elapsed` | Écoulé : temps de montre, trous et arrêts compris. |
| `MOVING` | `moving` | M_θ : temps en mouvement sous une convention. |
| `MOVING_OR_UNDETERMINED` | `moving_or_undetermined` | M_θ + U_θ : temps en mouvement ou indéterminé sous une convention. |

Nature d'une horloge (`0010` D5.4).

#### Champs

Valeurs décrites dans `CLOCK_KIND_DESCRIPTIONS`.

#### Invariants

Énumération fermée.

#### Producteur

`CLOCKS`.

#### Consommateurs

`clock_duration_s` (M4a) ; les totaux sur support admis (M4a-2) ; les métriques
(M4b).

#### Non promis

Aucune horloge n'est la « bonne » : l'écoulé est la référence principale, les dix
autres sont des scénarios.

---

## `Clock`

*`mountain_perf.schemas.clock` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `kind` | `ClockKind` | — |
| `convention_index` | `int \| None` | `None` |

Une des onze horloges : nature et, hors écoulé, convention.

#### Champs

- `kind` — sans unité — écoulé, `M_θ` ou `M_θ + U_θ`.
- `convention_index` — sans unité — indice dans `CLOCK_CONVENTIONS`.

#### Invariants

`convention_index` vaut `None` si et seulement si `kind` est `ELAPSED` ;
sinon il est dans `[0, 4]`.

#### Producteur

`CLOCKS`.

#### Consommateurs

`clock_duration_s` (M4a) ; le rapport (M4b).

#### Non promis

Rien sur la valeur d'une horloge : elle dépend d'une partition.

---

## `ClockPartition`

*`mountain_perf.schemas.clock` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `time_s` | `tuple[float, ...]` | — |
| `states` | `tuple[tuple[IntervalState, ...], ...]` | — |

État de chaque intervalle élémentaire d'une trace, sous les cinq conventions.

L'intervalle `i` est `[time_s[i] ; time_s[i+1])` ; `states[k][i]` est son
état sous `CLOCK_CONVENTIONS[k]`.

#### Champs

- `time_s` — secondes — instants des enregistrements, depuis le premier.
- `states` — sans unité — un tuple d'états par convention.

#### Invariants

- `time_s` et `states` (et chacun de ses éléments) sont des tuples ;
- `time_s` : au moins 2 valeurs, finies, strictement croissantes, avec
  `time_s[0] == 0` (l'origine de `0010` D5.3, celle de `RecordedTrace`) ;
- `len(states) == 5` ;
- chaque élément de `states` a `len(time_s) − 1` états.

#### Producteur

`clock_partition` (`mountain_perf.backtest.clocks`).

#### Consommateurs

Les horloges cumulées, les totaux et les épisodes d'arrêt (M4a) ; les totaux sur
support admis (M4a-2) ; l'association arrêt → passage (M4a-3).

#### Non promis

- les mesures de fenêtre (`v_h`, `D_h`…) ne sont pas conservées ;
- un état `STOPPED` n'est pas un arrêt physique prouvé (détecteur non validé,
  `0010` Conséquences) ;
- la partition n'est pas recoupée avec une trace.

---

## `ClockTotals`

*`mountain_perf.schemas.clock` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `elapsed_s` | `float` | — |
| `moving_s` | `float` | — |
| `stopped_s` | `float` | — |
| `undetermined_s` | `float` | — |

Totaux d'une trace sous une convention : écoulé, mouvement, arrêt, indéterminé.

#### Champs

- `elapsed_s` — secondes — écoulé `E`, trous compris.
- `moving_s` — secondes — `M_θ`.
- `stopped_s` — secondes — `S_θ`.
- `undetermined_s` — secondes — `U_θ`.

#### Invariants

- valeurs finies et `>= 0` ;
- `|M + S + U − E| <= 1e−9 · max(1, E)`.

#### Producteur

`trace_totals` (`mountain_perf.backtest.clocks`), pour les totaux de la trace.

#### Consommateurs

Le rapport (M4b), qui publie séparément les totaux de la trace et ceux du support
admis (M4a-2).

#### Non promis

Ce ne sont pas les totaux du support admis : les deux jeux ne se mélangent jamais
(`0010` D5.4).

---

## `StopEpisode`

*`mountain_perf.schemas.clock` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `start_s` | `float` | — |
| `end_s` | `float` | — |
| `first_record` | `int` | — |
| `last_record` | `int` | — |

Suite maximale d'intervalles `STOPPED` sous une convention.

#### Champs

- `start_s`, `end_s` — secondes depuis le premier enregistrement — bornes de
  l'épisode.
- `first_record`, `last_record` — sans unité — indices des enregistrements qui
  bornent l'épisode.

#### Invariants

- `start_s` et `end_s` finis, `0 <= start_s < end_s` ;
- `0 <= first_record < last_record`.

#### Producteur

`stop_episodes` (`mountain_perf.backtest.clocks`).

#### Consommateurs

L'association arrêt → passage (M4a-3) ; le rapport (M4b).

#### Non promis

- l'épisode n'est pas un arrêt physique prouvé ;
- les bornes ne sont pas recoupées avec une partition.

---

## `PointStatus`

*`mountain_perf.schemas.matching` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `FOUND` | `found` | Trouvé : un seul événement de candidats admissibles (D4.5 à D4.7). |
| `ANCHORED` | `anchored` | Ancré : extrémité sans candidat admissible, datée par le premier ou le dernier enregistrement (D4.8). |
| `AMBIGUOUS` | `ambiguous` | Ambigu : deux événements ou plus (D4.7), ou projection d'ancrage à égalité (D4.8) ; jamais départagé. |
| `ABSENT` | `absent` | Absent : aucun franchissement orienté dans la fenêtre, et pas d'ancrage — pour une extrémité, quel que soit l'échec de l'ancrage (D4.8). |
| `OUT_OF_TOLERANCE` | `out_of_tolerance` | Hors ε : au moins un franchissement orienté dans la fenêtre, aucun admissible, et pas d'ancrage — pour une extrémité aussi (D4.7, précision, appliquée à D4.8). |
| `UNDEFINED_TANGENT` | `undefined_tangent` | Tangente indéfinie : corde de moins de 1e−6 m (D4.3). |

Statut de l'observation d'un point de score (`0010` D4.3 à D4.8).

#### Champs

Valeurs décrites dans `POINT_STATUS_DESCRIPTIONS`.

#### Invariants

Énumération fermée : un point de score reçoit un seul statut par sortie.

#### Producteur

`match_points` (`mountain_perf.backtest.matching`).

#### Consommateurs

`ScorePointObservation` ; `mperf match` ; les segments, la couverture et le
préfixe (M4a-2b).

#### Non promis

Seuls `FOUND` et `ANCHORED` datent un point. Les autres statuts sont des
indisponibilités motivées (`0010` D0) : ni un échec sportif, ni une erreur du
modèle. `AMBIGUOUS` n'est jamais départagé.

---

## `ScorePointObservation`

*`mountain_perf.schemas.matching` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `index` | `int` | — |
| `nominal_m` | `float` | — |
| `effective_m` | `float` | — |
| `status` | `PointStatus` | — |
| `position` | `float \| None` | — |
| `time_s` | `float \| None` | — |
| `lateral_m` | `float \| None` | — |
| `realized_m` | `float \| None` | — |
| `candidate_count` | `int` | — |
| `event_count` | `int` | — |

| Propriété calculée | Type | Sens |
|---|---|---|
| `dated` | `bool` | Le point est daté : statut `FOUND` ou `ANCHORED`. |
| `anchoring_offset_m` | `float` | `effective_m − nominal_m` (mètres) : nul hors ancrage. |

Observation d'un point `k` de la grille de score par une trace réalisée.

#### Champs

- `index` — sans unité — `k`, rang dans la grille de score.
- `nominal_m` — mètres — `s_k`, abscisse du point sur la référence.
- `effective_m` — mètres — borne effective `b_k` (`0010` D4.2) : `s'_0`
  ou `s'_K` si l'extrémité est ancrée, sinon `s_k`.
- `status` — sans unité — statut de l'observation.
- `position` — sans unité — `π = i + f`, position fractionnaire dans la trace.
- `time_s` — secondes — `t*`, depuis le premier enregistrement de la trace.
- `lateral_m` — mètres — écart latéral signé `(P − Q)·n` du candidat qui
  date l'événement, ou de l'enregistrement ancré ; positif à gauche du sens de
  parcours de la référence.
- `realized_m` — mètres — `d_r(π)`, abscisse réalisée.
- `candidate_count` — sans unité — candidats admissibles de la fenêtre, après
  confusion des candidats de même `π`.
- `event_count` — sans unité — événements formés par ces candidats.

Propriétés calculées (jamais stockées) : `dated` et `anchoring_offset_m`.

#### Invariants

- `index >= 0` ; `nominal_m` et `effective_m` finis et `>= 0` ;
- `effective_m != nominal_m` ⇒ `status == ANCHORED` ;
- `position`, `time_s`, `lateral_m`, `realized_m` présents **si et
  seulement si** le point est daté ; présents, ils sont finis, et `position`,
  `time_s`, `realized_m` sont `>= 0` ;
- `ANCHORED` ⇒ `position` entière : l'ancrage date par un enregistrement ;
- `candidate_count >= 0`, `event_count >= 0`,
  `event_count <= candidate_count` ;
- `FOUND` ⇒ `event_count == 1` ;
- `ANCHORED`, `ABSENT`, `OUT_OF_TOLERANCE`, `UNDEFINED_TANGENT` ⇒
  `candidate_count == 0` ;
- `AMBIGUOUS` ⇒ `event_count >= 2` ou `candidate_count == 0` (au moins
  deux événements, ou aucun candidat et une projection d'ancrage à égalité).

#### Producteur

`match_points` (`mountain_perf.backtest.matching`).

#### Consommateurs

`mperf match` ; les segments, la couverture et le préfixe (M4a-2b) ; les
passages nommés (M4a-3).

#### Non promis

- la cohérence **entre** points (indices consécutifs, positions et instants
  croissants, bornes effectives croissantes) n'est pas vérifiée ici : c'est une
  propriété de `match_points` et un invariant du futur `MatchResult`
  (M4a-2b) ;
- un point ne connaît ni `K` ni `L` ;
- `lateral_m` n'est pas comparé à `ε`, que le contrat ignore.

---

## `SegmentExclusion`

*`mountain_perf.schemas.matching` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `UNOBSERVED_BOUND` | `unobserved_bound` | Borne non observée : une borne ni trouvée ni ancrée (D4.10, point 1) ; durée inconnue. |
| `GAP` | `gap` | Trou : un intervalle de plus de 10 s à l'intérieur (D4.9) ; temps écoulé connu, jamais scoré. |
| `LENGTH_RATIO` | `length_ratio` | Rapport de longueur : longueur réalisée sur longueur du segment hors de [0,6 ; 1,6] (D4.10, point 3, précision). |
| `INTERIOR_DEVIATION` | `interior_deviation` | Écart intérieur : H = max(H_1, H_2) > ε (D4.10, point 4). |

Motif d'exclusion d'un segment de score (`0010` D4.9, D4.10).

#### Champs

Valeurs décrites dans `SEGMENT_EXCLUSION_DESCRIPTIONS`.

Correspondance entre le statut des bornes (`PointStatus`), le motif du segment
et les indisponibilités de `0010` D0 (`Unavailability`) :

- deux bornes `found` ou `anchored` : admis, `gap`, `length_ratio` ou
  `interior_deviation` ; pas d'indisponibilité de borne ;
- une borne `ambiguous`, `absent` ou `undefined_tangent` :
  `unobserved_bound` ; indisponibilité `ambiguous`, `absent` ou
  `undefined_tangent` ;
- une borne `out_of_tolerance` : `unobserved_bound` ; pas d'équivalent
  (précision de D4.7) ;
- motif `gap` : indisponibilité `gap` ;
- motif `length_ratio` : pas d'équivalent (précision de D4.10) ;
- motif `interior_deviation` : indisponibilité `interior_deviation`.

#### Invariants

Énumération fermée ; un segment non admis porte un seul motif, le premier dans
l'ordre des conditions de D4.10 : borne non observée, trou, rapport de longueur,
écart intérieur.

#### Producteur

`observe_segment` et `match_trace` (`mountain_perf.backtest.segments`).

#### Consommateurs

`ScoreSegmentObservation` ; `Coverage` ; `mperf match` ; les métriques
(M4b), qui lisent le motif et les statuts des bornes.

#### Non promis

`UNOBSERVED_BOUND` ne dit pas quel statut a la borne : ce sont les points du
`MatchResult` qui le portent. Aucune conversion vers `Unavailability` n'est
codée ici.

---

## `Regime`

*`mountain_perf.schemas.matching` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `ASCENT` | `ascent` | Montée : pente fine g > 0,05. |
| `FLAT` | `flat` | Plat : −0,05 ≤ g ≤ 0,05, bornes incluses. |
| `DESCENT` | `descent` | Descente : pente fine g < −0,05. |

Régime d'un intervalle de la grille fine, selon sa pente (`0010` D6).

#### Champs

Valeurs décrites dans `REGIME_DESCRIPTIONS`.

#### Invariants

Énumération fermée : chaque pente fine reçoit un seul régime.

#### Producteur

`grade_regime` (`mountain_perf.backtest.segments`).

#### Consommateurs

Les fractions de régime des segments ; `Coverage.regime_fraction` ;
`mperf match` ; les métriques par régime (M4b).

#### Non promis

Le diagnostic « descente roulante / raide » de D6 n'est pas un régime : il n'est
pas calculé en M4a (M4b).

---

## `RegimeClass`

*`mountain_perf.schemas.matching` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `ASCENT` | `ascent` | Montée pure : au moins 80 % de la longueur en montée. |
| `FLAT` | `flat` | Plat pur : au moins 80 % de la longueur en plat. |
| `DESCENT` | `descent` | Descente pure : au moins 80 % de la longueur en descente. |
| `MIXED` | `mixed` | Mixte : aucun régime n'atteint 80 % de la longueur. |

Classe d'un segment de score (`0010` D6).

#### Champs

Valeurs décrites dans `REGIME_CLASS_DESCRIPTIONS`.

#### Invariants

Énumération fermée : un segment est pur d'un régime ou mixte.

#### Producteur

`regime_class` (`mountain_perf.backtest.segments`).

#### Consommateurs

`ScoreSegmentObservation` ; les métriques par régime (M4b).

#### Non promis

Mixte n'est jamais une cible, un garde-fou ni une dimension d'apprentissage
(D6). Le temps observé n'est jamais réparti selon les fractions.

---

## `ScoreSegmentObservation`

*`mountain_perf.schemas.matching` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `index` | `int` | — |
| `nominal_start_m` | `float` | — |
| `nominal_end_m` | `float` | — |
| `start_m` | `float` | — |
| `end_m` | `float` | — |
| `ascent_fraction` | `float` | — |
| `flat_fraction` | `float` | — |
| `descent_fraction` | `float` | — |
| `regime_class` | `RegimeClass` | — |
| `exclusion` | `SegmentExclusion \| None` | — |
| `length_ratio` | `float \| None` | — |
| `h1_m` | `float \| None` | — |
| `h2_m` | `float \| None` | — |
| `start_s` | `float \| None` | — |
| `end_s` | `float \| None` | — |
| `realized_start_m` | `float \| None` | — |
| `realized_end_m` | `float \| None` | — |

| Propriété calculée | Type | Sens |
|---|---|---|
| `admitted` | `bool` | Segment admis au score : aucun motif d'exclusion (`0010` D4.10). |
| `length_m` | `float` | `end_m − start_m` (mètres) : longueur exacte entre les bornes effectives (`0010` D4.2). |
| `interior_deviation_m` | `float \| None` | `H = max(H_1, H_2)` (mètres, `0010` D4.10) ; `None` si l'un manque. |

Observation d'un segment `[b_k ; b_{k+1}]` de la grille de score.

#### Champs

- `index` — sans unité — `k`, rang du segment.
- `nominal_start_m`, `nominal_end_m` — mètres — `s_k`, `s_{k+1}`.
- `start_m`, `end_m` — mètres — bornes effectives `b_k`, `b_{k+1}`
  (`0010` D4.2).
- `ascent_fraction`, `flat_fraction`, `descent_fraction` — sans unité —
  fractions de régime sur `[b_k ; b_{k+1}]` (D6).
- `regime_class` — sans unité — classe du segment, pure ou mixte (D6).
- `exclusion` — sans unité — motif d'exclusion ; `None` = admis (D4.10).
- `length_ratio` — sans unité — rapport de longueur `rho` (D4.10, point 3).
- `h1_m`, `h2_m` — mètres — `H_1`, `H_2` (D4.10, point 4).
- `start_s`, `end_s` — secondes — `t*_k`, `t*_{k+1}`, instants des bornes
  quand elles sont datées.
- `realized_start_m`, `realized_end_m` — mètres — `d_r(π_k)`,
  `d_r(π_{k+1})`, abscisses réalisées des bornes quand elles sont datées (D3).

Propriétés calculées (jamais stockées) : `admitted`, `length_m` et
`interior_deviation_m`.

#### Invariants

- `index >= 0` ; les quatre abscisses finies et `>= 0` ;
  `nominal_start_m < nominal_end_m` ; `start_m < end_m` ;
- fractions finies, chacune dans `[0 ; 1]` à `1e−9` près, de somme 1 à
  `1e−9` près ;
- `regime_class` est `MIXED` ou le régime d'une plus grande fraction ; une
  fraction égale à 1 à `1e−9` près impose sa classe ;
- `start_s` présent si et seulement si `realized_start_m` l'est ; de même
  pour `end_s` et `realized_end_m` ; présents, ils sont finis et `>= 0` ;
  `start_s < end_s` et `realized_start_m <= realized_end_m` quand les quatre
  sont présents ;
- `length_ratio`, `h1_m`, `h2_m` : tous présents ou tous absents ;
  présents, finis et `>= 0` ;
- admis ⇒ `length_ratio`, `start_s`, `end_s` présents ;
- `UNOBSERVED_BOUND` ⇒ `length_ratio` absent, et `start_s` ou `end_s`
  absent ;
- `GAP` ⇒ `length_ratio` absent, `start_s` et `end_s` présents ;
- `LENGTH_RATIO` ou `INTERIOR_DEVIATION` ⇒ `length_ratio`, `start_s`,
  `end_s` présents.

#### Producteur

`observe_segment` et `match_trace` (`mountain_perf.backtest.segments`).

#### Consommateurs

`Coverage`, `MatchResult`, `mperf match` ; les métriques (M4b).

#### Non promis

- un segment de bord ancré n'est pas la même cellule que le segment nominal
  (D4.2) : ses bornes le distinguent, son `index` non ;
- les temps d'un segment non admis ne sont jamais un score ;
- le contrat ignore les seuils (`0,6`, `1,6`, `ε`, `0,80`) et ne vérifie
  donc pas qu'un motif correspond aux valeurs publiées : c'est le rôle des tests
  du producteur.

---

## `Coverage`

*`mountain_perf.schemas.matching` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `reference_length_m` | `float` | — |
| `admitted_m` | `float` | — |
| `excluded_unobserved_bound_m` | `float` | — |
| `excluded_gap_m` | `float` | — |
| `excluded_length_ratio_m` | `float` | — |
| `excluded_interior_deviation_m` | `float` | — |
| `anchoring_excluded_m` | `float` | — |
| `ascent_length_m` | `float` | — |
| `flat_length_m` | `float` | — |
| `descent_length_m` | `float` | — |
| `admitted_ascent_m` | `float` | — |
| `admitted_flat_m` | `float` | — |
| `admitted_descent_m` | `float` | — |
| `admitted_elapsed_s` | `float` | — |
| `excluded_gap_s` | `float` | — |
| `excluded_length_ratio_s` | `float` | — |
| `excluded_interior_deviation_s` | `float` | — |
| `prefix_segment_count` | `int` | — |
| `prefix_end_m` | `float` | — |
| `prefix_end_s` | `float \| None` | — |
| `prefix_last_passage` | `str \| None` | — |

| Propriété calculée | Type | Sens |
|---|---|---|
| `fraction` | `float` | `admitted_m / L` (sans unité) : couverture globale (`0010` D4.11). |

Couverture publiée d'une sortie contre un tracé de référence (`0010` D4.11).

#### Champs

- `reference_length_m` — mètres — `L`, longueur du profil de référence.
- `admitted_m` — mètres — longueur des segments admis.
- `excluded_unobserved_bound_m`, `excluded_gap_m`,
  `excluded_length_ratio_m`, `excluded_interior_deviation_m` — mètres —
  longueur des segments exclus, par motif.
- `anchoring_excluded_m` — mètres — `b_0 + (L − b_K)`, motif `ancrage`.
- `ascent_length_m`, `flat_length_m`, `descent_length_m` — mètres —
  longueurs fines de chaque régime sur `[0 ; L]`.
- `admitted_ascent_m`, `admitted_flat_m`, `admitted_descent_m` — mètres —
  longueurs fines de chaque régime dans les segments admis.
- `admitted_elapsed_s` — secondes — `E_A`, écoulé des segments admis.
- `excluded_gap_s`, `excluded_length_ratio_s`,
  `excluded_interior_deviation_s` — secondes — temps écoulés exclus connus,
  par motif.
- `prefix_segment_count` — sans unité — `m`, longueur du préfixe comparable.
- `prefix_end_m` — mètres — `b_m`, fin du préfixe.
- `prefix_end_s` — secondes — `t*_m`, `None` si le point `m` n'est pas
  daté.
- `prefix_last_passage` — sans unité — nom du dernier lieu nommé du préfixe,
  `None` s'il n'en contient pas.

Propriété calculée (jamais stockée) : `fraction` ; méthode
`regime_fraction(regime)` : longueur admise du régime rapportée à sa longueur
sur `[0 ; L]`, `None` si celle-ci est nulle (« non évalué »).

#### Invariants

- valeurs finies et `>= 0` ; `L > 0` ;
- `admitted_m + Σ excluded_*_m + anchoring_excluded_m = L` à
  `1e−6·max(1, L)` près ;
- `ascent_length_m + flat_length_m + descent_length_m = L` à
  `1e−6·max(1, L)` près ;
- chaque longueur admise d'un régime `<=` sa longueur sur `[0 ; L]` à
  `1e−6·max(1, L)` près ;
- `prefix_segment_count >= 0` ; `prefix_last_passage` non vide s'il est
  présent.

#### Producteur

`match_trace` (`mountain_perf.backtest.segments`).

#### Consommateurs

`MatchResult`, `mperf match` ; le rapport (M4b).

#### Non promis

- les « durées inconnues » de D4.11 sont les segments `unobserved_bound` du
  `MatchResult`, que `mperf match` compte ;
- le temps passé sur les marges d'ancrage n'est pas observé et n'est pas publié ;
- les comptes de points par statut sont dans les points.

---

## `AdmittedTotals`

*`mountain_perf.schemas.matching` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `elapsed_s` | `float` | — |
| `moving_s` | `float` | — |
| `stopped_s` | `float` | — |
| `undetermined_s` | `float` | — |

Totaux du support admis sous une convention : écoulé, mouvement, arrêt,
indéterminé (`0010` D5.4).

#### Champs

- `elapsed_s` — secondes — `E_A`, somme des `t*_{k+1} − t*_k` des segments
  admis.
- `moving_s` — secondes — `M_{θ,A}`.
- `stopped_s` — secondes — `S_{θ,A}`.
- `undetermined_s` — secondes — `U_{θ,A}`.

#### Invariants

- valeurs finies et `>= 0` ;
- `|M + S + U − E_A| <= 1e−9 · max(1, E_A)` (la tolérance de `ClockTotals`).

#### Producteur

`admitted_totals` (`mountain_perf.backtest.segments`).

#### Consommateurs

`MatchResult`, `mperf match` ; les enveloppes et le rapport (M4b).

#### Non promis

Ce ne sont pas les totaux de la trace (`ClockTotals`) : aucun des deux types ne
se convertit en l'autre, les deux jeux ne se mélangent jamais (D5.4).

---

## `SensitivityConfiguration`

*`mountain_perf.schemas.matching` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `score_step_m` | `float` | — |
| `lateral_tolerance_m` | `float` | — |
| `cluster_radius_m` | `float` | — |
| `clock` | `Clock` | — |

Une configuration de sensibilité (`0010` D13).

#### Champs

- `score_step_m` — mètres — `Δ`, pas de la grille de score.
- `lateral_tolerance_m` — mètres — `ε`, tolérance latérale.
- `cluster_radius_m` — mètres — `r_c`, rayon de regroupement.
- `clock` — sans unité — l'horloge de la configuration.

#### Invariants

Valeurs finies ; `Δ > 0`, `ε > 0`, `r_c >= 0`.

#### Producteur

`SENSITIVITY_CONFIGURATIONS` (`mountain_perf.backtest.sensitivity`).

#### Consommateurs

L'exécution de la sensibilité (M4d).

#### Non promis

Rien n'est exécuté en M4a ; une configuration ne dit pas comment elle sera
exécutée.

---

## `MatchResult`

*`mountain_perf.schemas.matching` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `parameters` | `ParameterSet` | — |
| `points` | `tuple[ScorePointObservation, ...]` | — |
| `segments` | `tuple[ScoreSegmentObservation, ...]` | — |
| `coverage` | `Coverage` | — |
| `departure_delay_s` | `float \| None` | — |
| `trace_totals` | `tuple[ClockTotals, ...]` | — |
| `admitted_totals` | `tuple[AdmittedTotals, ...]` | — |
| `low_convention_index` | `int \| None` | — |
| `high_convention_index` | `int \| None` | — |
| `admitted_sensitivity_range_s` | `tuple[float, float] \| None` | — |

Tout ce que l'appariement observe d'une sortie contre un tracé de référence.

#### Champs

- `parameters` — sans unité — `Δ`, `ε`, `r_c`, déclarés par
  `MATCHING_PARAMETER_SPECS`.
- `points` — sans unité — l'observation de chaque point de score, dans l'ordre.
- `segments` — sans unité — l'observation de chaque segment, dans l'ordre.
- `coverage` — sans unité — couverture, exclusions et préfixe (D4.11).
- `departure_delay_s` — secondes — `t*_0`, depuis le premier enregistrement ;
  `None` si le départ n'est pas daté.
- `trace_totals` — sans unité — les cinq totaux de la trace (D5.4).
- `admitted_totals` — sans unité — les cinq totaux du support admis (D5.4).
- `low_convention_index`, `high_convention_index` — sans unité — `θ_bas`,
  `θ_haut`, indices dans `CLOCK_CONVENTIONS`.
- `admitted_sensitivity_range_s` — secondes — `I_sens,A`,
  `(min_θ M_{θ,A} ; E_A − min_θ S_{θ,A})`.

#### Invariants

- `points`, `segments`, `trace_totals`, `admitted_totals` sont des
  tuples ;
- `len(points) >= 2`, `len(segments) == len(points) − 1` ;
- `points[k].index == k` et `segments[k].index == k` ;
- `points[0].nominal_m == 0`, `points[−1].nominal_m ==
  coverage.reference_length_m`, `nominal_m` strictement croissants ;
- `effective_m` strictement croissants ; `effective_m != nominal_m` seulement
  pour le premier et le dernier point ;
- `position` et `time_s` strictement croissants le long des points datés ;
- pour chaque `k` : `nominal_start_m`, `start_m`, `start_s`,
  `realized_start_m` du segment `k` égaux à `nominal_m`, `effective_m`,
  `time_s`, `realized_m` du point `k` ; de même pour la fin avec le point
  `k + 1` ;
- un segment est `unobserved_bound` si et seulement si l'une de ses bornes
  n'est pas datée ;
- `m = coverage.prefix_segment_count` : les `m` premiers segments sont
  admis, et `m == len(segments)` ou le segment `m` ne l'est pas ;
  `prefix_end_m` et `prefix_end_s` sont `effective_m` et `time_s` du
  point `m` ;
- `departure_delay_s == points[0].time_s` ;
- `len(trace_totals) == len(admitted_totals) == len(CLOCK_CONVENTIONS)` ; les
  `elapsed_s` des `admitted_totals` égaux entre eux et à
  `coverage.admitted_elapsed_s` à `1e−9·max(1, E_A)` près ;
- `low_convention_index`, `high_convention_index` et
  `admitted_sensitivity_range_s` sont `None` si et seulement si aucun segment
  n'est admis ; présents, les deux indices sont le premier indice du minimum de
  `moving_s` et du maximum de `moving_s + undetermined_s` des
  `admitted_totals`, et l'intervalle vaut `(min moving_s ; E_A − min
  stopped_s)` à `1e−9·max(1, E_A)` près (sa borne basse peut dépasser la haute
  d'un ulp sur un support entièrement mobile).

#### Producteur

`match_trace` (`mountain_perf.backtest.segments`).

#### Consommateurs

`mperf match` ; les passages (M4a-3) ; les métriques et le rapport (M4b).

#### Non promis

- un `MatchResult` ne connaît ni la trace ni le tracé, seulement ce qui en a été
  observé ;
- la grille `nominal_m` n'est pas recalculée par le contrat, qui ignore `Δ` ;
- aucun extrême segment par segment n'est jamais publié (D5.4).

---

## `PassageRole`

*`mountain_perf.schemas.matching` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `DEPARTURE` | `departure` | Départ : l'occurrence reprend le départ (à moins de 1 m de 0) ; jamais une cible (D7.4). |
| `ARRIVAL` | `arrival` | Arrivée : l'occurrence reprend l'arrivée (à moins de 1 m de L), ancrage compris — arrivée unique (D4.12). |
| `INTERMEDIATE` | `intermediate` | Intermédiaire : toute autre occurrence. |

Rôle d'une occurrence de lieu nommé du préparé (`0010` D4.12, D7.4).

#### Champs

Valeurs décrites dans `PASSAGE_ROLE_DESCRIPTIONS`.

#### Invariants

Énumération fermée : une occurrence reçoit un seul rôle, déduit du point de score
qu'elle reprend.

#### Producteur

`attach_occurrence` et `observe_passages` (`mountain_perf.backtest.passages`).

#### Consommateurs

`PassageObservation` ; `mperf match` ; la construction de `K` (M4b).

#### Non promis

Le rôle ne dit pas qu'une occurrence est dans `K` : M4b le fixe. Le seuil qui
le détermine vit dans `mountain_perf.backtest.passages`.

---

## `PassageStatus`

*`mountain_perf.schemas.matching` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `FOUND` | `found` | Trouvé : un seul événement de franchissement de la normale en s_w entre les deux points de score qui l'encadrent, ou point de score repris trouvé (D4.12). |
| `ANCHORED` | `anchored` | Ancré : départ ou arrivée repris d'un point ancré, observé avec son statut (D4.8, D7.4). |
| `AMBIGUOUS` | `ambiguous` | Ambigu : deux événements ou plus, point repris ambigu, ou violation de chronologie (D4.12) ; jamais départagé. |
| `ABSENT` | `absent` | Absent : aucun franchissement orienté entre les deux points qui l'encadrent, ou point repris absent. |
| `OUT_OF_TOLERANCE` | `out_of_tolerance` | Hors ε : au moins un franchissement orienté, aucun admissible, ou point repris hors ε ; se comporte comme absent (D4.7, précision). |
| `UNDEFINED_TANGENT` | `undefined_tangent` | Tangente indéfinie : corde de moins de 1e−6 m en s_w (D4.3), ou point repris de tangente indéfinie. |
| `OUTSIDE_PREFIX` | `outside_prefix` | Hors préfixe : occurrence hors du préfixe comparable, non cherchée (D4.12, « sur le préfixe comparable seulement »). |

Statut de l'observation d'une occurrence de lieu nommé (`0010` D4.12).

#### Champs

Valeurs décrites dans `PASSAGE_STATUS_DESCRIPTIONS` : les six valeurs de
`PointStatus`, mêmes valeurs et mêmes sens pour une occurrence, et
`OUTSIDE_PREFIX`.

#### Invariants

Énumération fermée : une occurrence reçoit un seul statut par sortie ;
`ANCHORED` seulement pour un départ ou une arrivée repris d'un point ancré ;
`AMBIGUOUS` aussi après une violation de chronologie.

#### Producteur

`observe_passages` (`mountain_perf.backtest.passages`).

#### Consommateurs

`PassageObservation` ; `mperf match` ; les métriques (M4b).

#### Non promis

Seuls `FOUND` et `ANCHORED` datent une occurrence avant la chronologie ; les
autres statuts sont des indisponibilités motivées (`0010` D0), jamais un échec
sportif. Le statut d'une reprise est celui du point de score repris, pas un
franchissement de la normale du lieu.

---

## `EpisodeOutcome`

*`mountain_perf.schemas.matching` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `ATTRIBUTED` | `attributed` | Attribué : l'épisode est attribué à une seule occurrence (D4.12). |
| `NO_CANDIDATE` | `no_candidate` | Sans candidate : aucune occurrence candidate. |
| `TIE` | `tie` | Non attribué : égalité persistante en temps puis en espace ; épisode publié (D4.12). |

Sort d'un épisode d'arrêt sous `θ_c` dans l'association arrêt → passage
(`0010` D4.12).

#### Champs

Valeurs décrites dans `EPISODE_OUTCOME_DESCRIPTIONS`.

#### Invariants

Énumération fermée : un épisode reçoit une seule issue.

#### Producteur

`attribute_episode` et `observe_passages`
(`mountain_perf.backtest.passages`).

#### Consommateurs

`EpisodeAttribution` ; `mperf match` ; le rapport (M4b).

#### Non promis

`TIE` n'est jamais départagé ; `NO_CANDIDATE` ne dit pas pourquoi aucune
occurrence n'était candidate.

---

## `PassageObservation`

*`mountain_perf.schemas.matching` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `point` | `ResolvedPoint` | — |
| `role` | `PassageRole` | — |
| `status` | `PassageStatus` | — |
| `crossing_s` | `float \| None` | — |
| `association_window_s` | `tuple[float, float] \| None` | — |
| `arrival_s` | `float \| None` | — |
| `departure_s` | `float \| None` | — |
| `stop_total_s` | `float \| None` | — |
| `episode_count` | `int` | — |
| `chronology_violation` | `bool` | — |
| `comparable` | `bool` | — |
| `unavailability` | `Unavailability \| None` | — |

| Propriété calculée | Type | Sens |
|---|---|---|
| `dated` | `bool` | Les instants sont présents : `FOUND`, `ANCHORED`, ou `AMBIGUOUS` après une violation de chronologie, événements conservés (`0010` D4.12). |

Observation d'une occurrence de lieu nommé par une trace réalisée (`0010`
D4.12).

#### Champs

- `point` — sans unité — l'occurrence : `point.name`, `distance_m`
  (`s_w`), `offset_m`.
- `role` — sans unité — départ, arrivée ou intermédiaire.
- `status` — sans unité — statut de l'observation, après la chronologie.
- `crossing_s` — secondes depuis le premier enregistrement — `t*_w`.
- `association_window_s` — secondes — `(début, fin)` de la fenêtre
  d'association.
- `arrival_s`, `departure_s` — secondes — `arrivée_w`, `départ_w`.
- `stop_total_s` — secondes — `S`, somme des durées des épisodes attribués.
- `episode_count` — sans unité — nombre d'épisodes attribués.
- `chronology_violation` — sans unité — la chronologie a rendu l'occurrence
  ambiguë.
- `comparable` — sans unité — utilisable comme observation comparable,
  maintenue dans le préfixe.
- `unavailability` — sans unité — motif quand l'occurrence n'est pas
  comparable (`0010` D0).

Propriété calculée (jamais stockée) : `dated`.

#### Invariants

- `crossing_s`, `association_window_s`, `arrival_s`, `departure_s`,
  `stop_total_s` : tous présents ou tous absents ; présents si et seulement si
  `status` est `FOUND` ou `ANCHORED`, ou `AMBIGUOUS` avec
  `chronology_violation` ;
- présents : valeurs finies et `>= 0` ; `début <= crossing_s <= fin` de la
  fenêtre ; `arrival_s <= crossing_s <= departure_s` ;
  `0 <= stop_total_s <= departure_s − arrival_s` ;
- `episode_count >= 0` ; `episode_count == 0` ⇒ `stop_total_s == 0` et
  `arrival_s == crossing_s == departure_s`, les instants présents ;
  `episode_count > 0` ⇒ `role` est `INTERMEDIATE` et les instants sont
  présents ;
- `chronology_violation` ⇒ `status == AMBIGUOUS` et `role == INTERMEDIATE` ;
- `status == ANCHORED` ⇒ `role` est `DEPARTURE` ou `ARRIVAL` ;
- `role == DEPARTURE` ⇒ `comparable` faux, `unavailability` absent,
  `status` autre que `OUTSIDE_PREFIX` ;
- `role != DEPARTURE` : `comparable` ⇒ `status` `FOUND` ou `ANCHORED`
  et `unavailability` absent ; non `comparable` ⇒ `unavailability` vaut
  `INSUFFICIENT_SUPPORT` pour `FOUND` ou `ANCHORED` (non maintenue), sinon
  `PASSAGE_STATUS_UNAVAILABILITY[status]`.

#### Producteur

`observe_passages` (`mountain_perf.backtest.passages`).

#### Consommateurs

`PassageMatchResult`, `mperf match` ; les métriques et le rapport (M4b).

#### Non promis

- `comparable` ne dit pas que le passage est dans `K` (M4b le fixe) ;
- le `crossing_s` d'une reprise est l'instant du point de score repris, pas un
  franchissement de la normale du lieu ;
- `stop_total_s` n'est pas une durée d'arrêt physique prouvée ;
- la fenêtre d'un départ ou d'une arrivée ne sert à aucune association ;
- le contrat ignore `ε`, `r_c`, `θ_c` et les seuils de 1 s et 1 m.

---

## `EpisodeAttribution`

*`mountain_perf.schemas.matching` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `episode` | `StopEpisode` | — |
| `outcome` | `EpisodeOutcome` | — |
| `passage_index` | `int \| None` | — |
| `median_latitude_deg` | `float` | — |
| `median_longitude_deg` | `float` | — |

Sort d'un épisode d'arrêt sous `θ_c` (`0010` D4.12, D5.2).

#### Champs

- `episode` — sans unité — l'épisode d'arrêt, bornes `[a ; b]`.
- `outcome` — sans unité — attribué, sans candidate ou non attribué.
- `passage_index` — sans unité — rang de l'occurrence attributaire dans
  `PassageMatchResult.passages`.
- `median_latitude_deg`, `median_longitude_deg` — degrés — position lissée
  médiane de l'épisode, coordonnée par coordonnée.

#### Invariants

- `passage_index` présent si et seulement si `outcome == ATTRIBUTED`, et
  alors `>= 0` ;
- médianes finies, latitude dans `[−90 ; 90]`, longitude dans `[−180 ; 180]`.

#### Producteur

`observe_passages` (`mountain_perf.backtest.passages`).

#### Consommateurs

`PassageMatchResult`, `mperf match` ; le rapport (M4b).

#### Non promis

L'épisode n'est pas un arrêt physique prouvé ; la médiane n'est pas recoupée avec
la trace ; le contrat ignore `ε` et les seuils de 1 s et 1 m.

---

## `PassageMatchResult`

*`mountain_perf.schemas.matching` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `passages` | `tuple[PassageObservation, ...]` | — |
| `episodes` | `tuple[EpisodeAttribution, ...]` | — |

Les passages d'une sortie contre un tracé de référence (`0010` D4.12).

#### Champs

- `passages` — sans unité — l'observation de chaque occurrence, dans l'ordre de
  `profile.resolved_points`.
- `episodes` — sans unité — le sort de chaque épisode d'arrêt sous `θ_c`,
  dans l'ordre du temps.

#### Invariants

- `passages` et `episodes` sont des tuples ;
- `point.distance_m` non décroissants le long de `passages` ;
- `episodes[i].episode.end_s < episodes[i + 1].episode.start_s` ;
- tout `passage_index` est `< len(passages)` et désigne une occurrence
  `INTERMEDIATE` dont le statut est `FOUND`, ou `AMBIGUOUS` avec
  `chronology_violation` ;
- pour chaque passage, `episode_count` est le nombre d'épisodes qui le
  désignent ; ses instants présents, `arrival_s == min(crossing_s, début des
  épisodes attribués)`, `departure_s == max(crossing_s, fin des épisodes
  attribués)` et `stop_total_s == math.fsum(fin − début)` — égalités
  exactes : le producteur les calcule ainsi.

#### Producteur

`observe_passages` (`mountain_perf.backtest.passages`).

#### Consommateurs

`mperf match` ; les métriques et le rapport (M4b).

#### Non promis

Le résultat ne porte ni `K`, ni les points, ni la couverture : ils sont dans le
`MatchResult`. Aucun passage n'y est une cible.

---

## `MetricValue`

*`mountain_perf.schemas.metrics` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `value` | `float \| None` | — |
| `unavailability` | `Unavailability \| None` | — |
| `count` | `int` | — |

| Propriété calculée | Type | Sens |
|---|---|---|
| `available` | `bool` | La valeur est présente (`value is not None`). |

Une valeur de métrique, ou son indisponibilité, avec son effectif (`0010` D0,
D7.5).

#### Champs

- `value` — unité de la métrique : sans unité pour les métriques logarithmiques
  et `q_usage`, secondes pour `C_k` — la valeur.
- `unavailability` — sans unité — le motif (`0010` D0).
- `count` — sans unité — l'effectif du support de la valeur, en segments ou en
  passages.

Propriété calculée (jamais stockée) : `available`.

#### Invariants

- exactement un de `value` et `unavailability` est présent ;
- `value` finie ;
- `count >= 0` ;
- `value` présente ⇒ `count >= 1`.

#### Producteur

Les fonctions de `mountain_perf.backtest.metrics`.

#### Consommateurs

Les contrats qui la portent (`ClassMetrics`, `SupportMetrics`,
`PassageErrors`, `UsageTarget`) et leurs consommateurs : l'assemblage (M4b-2),
la référence D8 (M4b-3), le rapport (M4b-5), l'admission (M4c).

#### Non promis

- le contrat ne dit pas de quel support il s'agit : c'est le contrat qui le porte ;
- une valeur n'est jamais « zéro par défaut ».

---

## `ClassMetrics`

*`mountain_perf.schemas.metrics` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `regime_class` | `RegimeClass` | — |
| `segment_count` | `int` | — |
| `underrepresented` | `bool` | — |
| `log_ratio` | `MetricValue` | — |
| `dispersion` | `MetricValue` | — |
| `shape` | `MetricValue` | — |

Les métriques d'une classe de régime sur le support (`0010` D6, D7.2, D7.5).

#### Champs

- `regime_class` — sans unité — la classe.
- `segment_count` — sans unité — `n_R`, segments du support dans la classe.
- `underrepresented` — sans unité — « trop peu représenté » (D7.5).
- `log_ratio` — sans unité — `E_R`.
- `dispersion` — sans unité — `D_R`.
- `shape` — sans unité — `E_R − L`, diagnostic de forme.

#### Invariants

- `segment_count >= 0` ;
- les trois valeurs ont `count == segment_count`, le même motif, ou sont toutes
  trois présentes ;
- motif parmi les motifs du support (`insufficient_support`, `zero_time`,
  `model_error`) ;
- `segment_count == 0` ⇒ motif `insufficient_support` ;
- `underrepresented` ⇒ `segment_count >= 1` ;
- `dispersion` présente ⇒ `dispersion.value >= 0` ;
- `dispersion` présente et `segment_count == 1` ⇒ `dispersion.value == 0.0`
  **exactement** (D7.2).

#### Producteur

`support_metrics` et `positive_time_diagnostic`
(`mountain_perf.backtest.metrics`).

#### Consommateurs

`SupportMetrics`, qui la porte, et ses consommateurs : l'assemblage (M4b-2), la
référence D8 (M4b-3), le rapport (M4b-5), l'admission (M4c).

#### Non promis

- le seuil de 3 n'est pas dans le contrat : le contrat ne vérifie pas que
  `underrepresented` correspond à l'effectif (tests du producteur) ;
- `E_R` d'une classe « trop peu représentée » n'est ni une cible ni un garde-fou
  (D7.5) ;
- mixte n'est jamais une cible (D6).

---

## `SupportMetrics`

*`mountain_perf.schemas.metrics` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `segment_count` | `int` | — |
| `model_error` | `bool` | — |
| `log_ratio` | `MetricValue` | — |
| `dispersion` | `MetricValue` | — |
| `within` | `MetricValue` | — |
| `between` | `MetricValue` | — |
| `compensation` | `MetricValue` | — |
| `classes` | `tuple[ClassMetrics, ...]` | — |

Les métriques d'un support (`0010` D7.1, D7.2, D5.5).

#### Champs

- `segment_count` — sans unité — `n`, segments du support.
- `model_error` — sans unité — sortie de modèle invalide sur le support (D7.1).
- `log_ratio` — sans unité — `L`.
- `dispersion` — sans unité — `A`.
- `within` — sans unité — `W`.
- `between` — sans unité — `B`.
- `compensation` — sans unité — `C_comp`.
- `classes` — sans unité — les métriques de chaque classe de régime.

#### Invariants

- `classes` est un tuple de quatre éléments, de `regime_class` montée, plat,
  descente, mixte, dans cet ordre ;
- `sum(segment_count des classes) == segment_count` ;
- `log_ratio`, `dispersion`, `within`, `between`, `compensation` ont
  `count == segment_count` ;
- `dispersion`, `within`, `between`, `compensation` ont le même motif, ou
  sont toutes présentes (« motif vectoriel ») ;
- tous les motifs sont parmi les motifs du support (`insufficient_support`,
  `zero_time`, `model_error`) ;
- `segment_count == 0` ⇐⇒ `log_ratio` et le motif vectoriel sont
  `insufficient_support` ; et alors `model_error` est faux ;
- `model_error` ⇒ aucune valeur présente, ni du support ni des classes ;
- non `model_error` ⇒ aucun motif `model_error`, nulle part ;
- `log_ratio` en `zero_time` ⇒ motif vectoriel `zero_time` ;
- `dispersion` présente ⇒ `log_ratio` présente ;
- pour chaque classe, son motif est `insufficient_support` si son effectif est
  nul, sinon le motif vectoriel ;
- `shape` présente ⇒ `shape.value == log_ratio.value (de la classe) −
  log_ratio.value (du support)` exactement ;
- valeurs vectorielles présentes : `A`, `W`, `B` `>= 0` ; avec
  `S = A + W + B + |C_comp|` : `C_comp >= −τ·S` et
  `|A − (W + B − C_comp)| <= τ·S` (`τ = METRIC_RELATIVE_TOLERANCE`).

#### Producteur

`support_metrics` et `positive_time_diagnostic`
(`mountain_perf.backtest.metrics`).

#### Consommateurs

L'assemblage (M4b-2), la référence D8 (M4b-3, scores du jour retiré), le rapport
(M4b-5), l'admission (M4c).

#### Non promis

- ni les `r_i`, ni `alpha_R`, ni les totaux ne sont publiés ;
- l'identité ne sépare pas deux causes additives (D7.2) ;
- le contrat ne connaît ni l'horloge, ni le scénario, ni le modèle : ils sont dans
  l'assemblage (M4b-2) ;
- un `SupportMetrics` ne dit pas s'il porte le support principal ou le
  diagnostic : c'est `PositiveTimeDiagnostic` qui le dit ;
- le résultat n'est pas promis hors du domaine du brief M4b-1 (§ 3, choix 12) :
  projections et temps observés positifs dans `[1e−6 ; 1e12]` ; au-delà, une
  valeur finie `> 0` peut faire sous-dépasser ou déborder un quotient ou une
  somme.

---

## `PositiveTimeDiagnostic`

*`mountain_perf.schemas.metrics` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `mask` | `tuple[bool, ...]` | — |
| `metrics` | `SupportMetrics` | — |

Le diagnostic du sous-support à temps positifs (`0010` D5.5).

#### Champs

- `mask` — sans unité — un booléen par segment du support principal, vrai si
  `t_i > 0`.
- `metrics` — sans unité — les métriques des segments de masque vrai.

#### Invariants

- `mask` est un tuple de booléens ;
- `metrics.segment_count` égale le nombre de vrais de `mask` ;
- aucun motif `zero_time` dans `metrics`.

#### Producteur

`positive_time_diagnostic` (`mountain_perf.backtest.metrics`).

#### Consommateurs

L'assemblage (M4b-2), le rapport (M4b-5).

#### Non promis

- **ne remplace jamais le support principal**, ni pour une cible ni pour un
  garde-fou (D5.5) ;
- le contrat ne vérifie pas le masque contre les temps (il ne les connaît pas).

---

## `LogRatioEnvelope`

*`mountain_perf.schemas.metrics` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `lower` | `float \| None` | — |
| `upper` | `float \| None` | — |
| `min_abs` | `float \| None` | — |
| `unavailability` | `Unavailability \| None` | — |

L'intervalle de `L` pour un temps admissible dans `[a ; b]` (`0010` D5.4).

#### Champs

- `lower`, `upper` — sans unité — bornes de `L`, `ln(P/b)` et `ln(P/a)`.
- `min_abs` — sans unité — `min |L|` sur l'intervalle.
- `unavailability` — sans unité — le motif (`0010` D0).

#### Invariants

- motif absent ⇒ les trois valeurs présentes et finies ;
- motif `model_error` ⇒ les trois absentes ;
- motif `zero_time` ⇒ soit les trois absentes (`b = 0`), soit `lower` finie,
  `upper == math.inf` et `min_abs` finie (`a = 0 < b`) ;
- aucun autre motif ;
- valeurs présentes : `lower <= upper`, `min_abs >= 0`, et `min_abs == 0` si
  et seulement si `lower <= 0 <= upper`.

#### Producteur

`log_ratio_envelope` (`mountain_perf.backtest.metrics`).

#### Consommateurs

M4b-2 (enveloppes de la performance et de chaque régime), le rapport (M4b-5).

#### Non promis

- une enveloppe vaut **à `P` fixé** : elle ne borne pas les scores de modèles
  recalés différemment selon l'horloge (D5.4) ;
- `E_R` et `D_R` aux horloges scénarios ne sont pas des bornes.

---

## `PassageErrors`

*`mountain_perf.schemas.metrics` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `errors_s` | `tuple[MetricValue, ...]` | — |
| `model_error` | `bool` | — |
| `max_abs_error_s` | `MetricValue` | — |
| `max_error_s` | `MetricValue` | — |
| `min_error_s` | `MetricValue` | — |

Les erreurs aux passages (`0010` D7.3).

#### Champs

- `errors_s` — secondes — `C_k = P_k − T_k`, un par point donné, dans l'ordre
  donné.
- `model_error` — sans unité — sortie de modèle invalide en l'un des points
  donnés.
- `max_abs_error_s`, `max_error_s`, `min_error_s` — secondes —
  `max |C_k|`, `max C_k`, `min C_k`.

#### Invariants

- `errors_s` est un tuple ; chacun de ses éléments a `count == 1` ;
- les trois agrégats ont le même motif et le même effectif, ou sont tous trois
  présents ;
- leur effectif est le nombre d'erreurs présentes ou en `model_error` (points
  observés) ;
- effectif nul ⇒ motif `insufficient_support` ;
- effectif non nul : agrégats en `model_error` si et seulement si
  `model_error` ;
- non `model_error` ⇒ aucune erreur en `model_error` ;
- agrégats présents ⇒ égaux, exactement, à `max(|c|)`, `max(c)`, `min(c)`
  sur les erreurs présentes ;
- un `C_k` présent reste permis quand `model_error` est vrai (brief M4b-1,
  § 3, choix 7).

#### Producteur

`passage_errors` (`mountain_perf.backtest.metrics`).

#### Consommateurs

L'assemblage (M4b-2), le rapport (M4b-5).

#### Non promis

- ni les abscisses, ni les noms des points : l'appelant tient l'ordre ;
- l'ensemble des points (préfixe, origine exclue) est construit par l'appelant
  (M4b-2).

---

## `TargetMember`

*`mountain_perf.schemas.metrics` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `occurrence_index` | `int \| None` | — |
| `arrival` | `bool` | — |

Un élément de l'ensemble `K` de la cible d'usage (`0010` D7.4, D4.12).

#### Champs

- `occurrence_index` — sans unité — rang de l'occurrence dans la suite des rôles
  donnée à `default_targets` (celle de `PassageMatchResult.passages`).
- `arrival` — sans unité — l'élément est l'arrivée.

#### Invariants

- `occurrence_index` absent ⇒ `arrival` ;
- présent ⇒ `>= 0`.

#### Producteur

`default_targets` (`mountain_perf.backtest.metrics`).

#### Consommateurs

M4b-2 (cumulés et statut de chaque élément), le rapport (M4b-5).

#### Non promis

Un élément d'arrivée sans occurrence désigne l'arrivée de la grille de score
(`b_K`).

---

## `UsageTarget`

*`mountain_perf.schemas.metrics` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `weights` | `tuple[float, ...] \| None` | — |
| `q_usage` | `MetricValue` | — |
| `q_usage_prefix` | `MetricValue` | — |
| `comparable` | `tuple[bool, ...]` | — |
| `model_error` | `bool` | — |
| `arrival_anchor_gap_m` | `float \| None` | — |

| Propriété calculée | Type | Sens |
|---|---|---|
| `target_count` | `int` | `N`, nombre d'éléments de `K` (`len(comparable)`). |
| `available_count` | `int` | `n` de « n passages sur N » : éléments disponibles (`q_usage.count`). |

La cible d'usage d'une performance (`0010` D7.4).

#### Champs

- `weights` — sans unité — les `w_k` ; absents si les poids par défaut ne sont
  pas calculables.
- `q_usage` — sans unité — la cible d'usage.
- `q_usage_prefix` — sans unité — le diagnostic `q_usage | préfixe`.
- `comparable` — sans unité — un booléen par élément de `K` : passage
  comparable (garde-fou de D10.4).
- `model_error` — sans unité — sortie de modèle invalide en l'un des éléments de
  `K` (`P_k` ou `P^(0)_k`).
- `arrival_anchor_gap_m` — mètres — `L − s'_K` d'une arrivée ancrée.

Propriétés calculées (jamais stockées) : `target_count` (`N`) et
`available_count` (`n` de « n passages sur N »).

#### Invariants

- `comparable` est un tuple non vide ;
- `weights` présents : tuple de longueur `len(comparable)`, valeurs finies,
  `>= 0`, de somme 1 à `WEIGHT_SUM_TOLERANCE` près ;
- `weights` absents ⇒ `model_error` ;
- `q_usage.count == q_usage_prefix.count <= len(comparable)` ;
- `q_usage` présent ⇒ `count == len(comparable)` et `value >= 0` ;
- `q_usage_prefix` présent ⇒ `value >= 0` ;
- `model_error` ⇒ `q_usage_prefix` indisponible et `q_usage` indisponible ;
- non `model_error` ⇒ aucun des deux n'a le motif `model_error` ;
- le nombre de vrais de `comparable` est `<= q_usage.count` ;
- `arrival_anchor_gap_m` présent ⇒ fini et `>= 0`.

#### Producteur

`usage_target` (`mountain_perf.backtest.metrics`).

#### Consommateurs

L'assemblage (M4b-2), le rapport (M4b-5), l'admission (M4c).

#### Non promis

- `q_usage_prefix` n'est **ni une cible ni un garde-fou** (D7.4) ;
- le contrat ne connaît pas les éléments de `K` (l'appelant les tient) ;
- il ne vérifie ni « départ exclu » ni « arrivée unique » (tests de
  `default_targets`).

---

## `Scenario`

*`mountain_perf.schemas.scoring` · énumération*

| Membre | Valeur | Description |
|---|---|---|
| `USAGE` | `usage` | Usage : projection sur le profil de référence (préparé ou trace de référence désignée), comparée à la trace réalisée (D3). |
| `CONTROL` | `control` | Contrôle : projection sur le profil de la trace réalisée elle-même, rétrospective, non disponible à J−7 (D3). |

Scénario d'une prévision (`0010` D3).

#### Champs

Valeurs décrites dans `SCENARIO_DESCRIPTIONS`.

#### Invariants

Énumération fermée : usage ou contrôle.

#### Producteur

`usage_forecast` et `control_forecast` (`mountain_perf.backtest.scoring`).

#### Consommateurs

`ModelForecast`, `ScenarioScores`, `OutingScores` ; `mperf match` ; le
rapport (M4b-5).

#### Non promis

L'écart de scores entre les deux scénarios n'isole pas causalement une cause
(D3) ; le diagnostic de géométrie (usage − contrôle) n'est pas calculé ici.

---

## `AdmittedSegment`

*`mountain_perf.schemas.scoring` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `index` | `int` | — |
| `nominal_start_m` | `float` | — |
| `nominal_end_m` | `float` | — |
| `start_m` | `float` | — |
| `end_m` | `float` | — |
| `realized_start_m` | `float` | — |
| `realized_end_m` | `float` | — |
| `regime_class` | `RegimeClass` | — |
| `times_s` | `tuple[float, ...]` | — |

Un segment admis de la sortie et ses temps sous les onze horloges (`0010`
D4.2, D5.3, D5.4, D7.1).

#### Champs

- `index` — sans unité — `k`, rang du segment dans la grille de score.
- `nominal_start_m`, `nominal_end_m` — mètres — `s_k`, `s_{k+1}`, bornes
  nominales.
- `start_m`, `end_m` — mètres — `b_k`, `b_{k+1}`, bornes effectives
  (D4.2).
- `realized_start_m`, `realized_end_m` — mètres — `d_r(π_k)`,
  `d_r(π_{k+1})`, abscisses réalisées des bornes (D3).
- `regime_class` — sans unité — la classe du segment, celle de la référence
  (partition commune, D3).
- `times_s` — secondes — le temps du segment sous chacune des onze horloges,
  dans l'ordre de `CLOCKS`.

#### Invariants

- `index >= 0` ; les six abscisses finies et `>= 0` ;
  `nominal_start_m < nominal_end_m` ; `start_m < end_m` ;
  `realized_start_m <= realized_end_m` ;
- `regime_class` est une `RegimeClass` ;
- `times_s` est un tuple de `len(CLOCKS)` valeurs finies et `>= 0` ;
- `times_s[0] > 0` (l'écoulé d'un segment admis : `t*_k < t*_{k+1}`).

#### Producteur

`observe_outing` (`mountain_perf.backtest.scoring`).

#### Consommateurs

`score_scenario` ; la référence D8 (M4b-3 : un segment est identifié par ses
bornes, et un segment de bord ancré n'est pas la cellule nominale, D4.2) ; le
rapport (M4b-5) ; les baselines (M4c).

#### Non promis

- `M_θ <= (M + U)_θ <= E` n'est vrai qu'en réels et n'est pas vérifié ;
- les temps ne sont pas recoupés avec une partition ;
- le contrat ne dit pas quelles bornes effectives diffèrent des nominales (celles
  d'un bord ancré, par le producteur).

---

## `ObservedPoint`

*`mountain_perf.schemas.scoring` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `distance_m` | `float` | — |
| `score_index` | `int \| None` | — |
| `passage_index` | `int \| None` | — |
| `unavailability` | `Unavailability \| None` | — |
| `times_s` | `tuple[float, ...] \| None` | — |

| Propriété calculée | Type | Sens |
|---|---|---|
| `available` | `bool` | Le point est observé : `unavailability is None`. |

Un point de `C_k`, ou un élément de `K`, observé sur la sortie (`0010`
D4.12, D7.3, D7.4).

#### Champs

- `distance_m` — mètres — l'abscisse où le cumul projeté est lu : `b_k` d'un
  point de score, `s_w` d'un lieu, `b_K` de l'arrivée.
- `score_index` — sans unité — `k` d'un point de score (et de l'arrivée).
- `passage_index` — sans unité — rang du lieu dans
  `PassageMatchResult.passages`.
- `unavailability` — sans unité — le motif d'observation (`0010` D0).
- `times_s` — secondes — `T_k`, cumulé depuis `t*_0` sous chacune des onze
  horloges, dans l'ordre de `CLOCKS`.

Propriété calculée (jamais stockée) : `available`.

#### Invariants

- `distance_m` finie et `>= 0` ;
- au moins un des deux indices est présent ; présents, ils sont `>= 0` ;
- `times_s` présent **si et seulement si** `unavailability` est absent ;
- `unavailability` absent ou dans `OBSERVATION_UNAVAILABILITY` (jamais
  `model_error`, `zero_time`…) ;
- `times_s` présent : tuple de `len(CLOCKS)` valeurs finies et `>= 0`.

#### Producteur

`observe_outing` (`mountain_perf.backtest.scoring`).

#### Consommateurs

`score_scenario` ; le rapport (`mperf match`, M4b-5).

#### Non promis

- le nom du lieu n'est pas porté : l'appelant a les passages ;
- un `T_k` peut être nul sous une horloge (`comparable` le dira, M4b-1).

---

## `OutingObservation`

*`mountain_perf.schemas.scoring` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `reference_length_m` | `float` | — |
| `origin_m` | `float` | — |
| `origin_s` | `float \| None` | — |
| `segments` | `tuple[AdmittedSegment, ...]` | — |
| `error_points` | `tuple[ObservedPoint, ...]` | — |
| `members` | `tuple[TargetMember, ...]` | — |
| `targets` | `tuple[ObservedPoint, ...]` | — |
| `arrival_anchor_gap_m` | `float \| None` | — |

Ce qu'une sortie observe, indépendamment de tout modèle (`0010` D4.8, D4.11,
D4.12, D5.3, D5.4, D7.1, D7.3, D7.4).

#### Champs

- `reference_length_m` — mètres — `L`, longueur du tracé de référence.
- `origin_m` — mètres — `b_0`, origine des cumulés.
- `origin_s` — secondes depuis le premier enregistrement — `t*_0` ; absent si
  le départ n'est pas daté.
- `segments` — sans unité — les segments admis, dans l'ordre.
- `error_points` — sans unité — les points de `C_k` (D7.3) : points de score
  du préfixe et lieux intermédiaires, origine exclue, par abscisse croissante.
- `members` — sans unité — `K` par défaut (`default_targets`, D7.4).
- `targets` — sans unité — un élément observé par membre, dans le même ordre.
- `arrival_anchor_gap_m` — mètres — `L − b_K` d'une arrivée ancrée (D4.8).

#### Invariants

- `L` finie et `> 0` ; `0 <= b_0 < L` ; `origin_s` absent, ou fini et
  `>= 0` ;
- `segments`, `error_points`, `members`, `targets` sont des tuples ;
- `segments` : `index` strictement croissants ; `b_0 <= start_m` et
  `end_m <= L` ;
- `error_points` : exactement un des deux indices ; `score_index >= 1`
  (origine exclue) ; `distance_m` non décroissantes, dans `[b_0 ; L]` ;
- `members` et `targets` : même longueur, `>= 1` ; le dernier membre est
  `arrival`, et lui seul ; pour un membre intermédiaire,
  `targets[i].passage_index == members[i].occurrence_index` et `score_index`
  absent ; pour l'arrivée, `score_index` présent et
  `passage_index == occurrence_index` ;
- `origin_s` absent ⇒ `error_points` vide et aucun élément de `targets`
  disponible ;
- `arrival_anchor_gap_m` absent, ou fini et `>= 0`.

#### Producteur

`observe_outing` (`mountain_perf.backtest.scoring`).

#### Consommateurs

Les prévisions et `score_scenario` ; la référence D8 (M4b-3) ; le rapport
(M4b-5) ; les baselines (M4c).

#### Non promis

Le contrat ne vérifie pas que `score_index` de l'arrivée vaut `K`, ni les
temps contre une partition, ni que les points sont ceux du préfixe : ce sont les
tests du producteur.

---

## `ModelForecast`

*`mountain_perf.schemas.scoring` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `scenario` | `Scenario` | — |
| `source` | `SourceRef` | — |
| `curve_ref` | `str` | — |
| `parameters` | `ParameterSet` | — |
| `engine_version` | `str` | — |
| `generated_at` | `datetime` | — |
| `segment_s` | `tuple[float \| None, ...]` | — |
| `point_s` | `tuple[float \| None, ...]` | — |
| `target_s` | `tuple[float \| None, ...]` | — |

La prévision d'un modèle dans un scénario (`0010` D3, D7.1 ; décision 1 de
rdw).

#### Champs

- `scenario` — sans unité — usage ou contrôle.
- `source` — sans unité — le tracé du profil projeté : la référence en usage, la
  trace en contrôle.
- `curve_ref` — sans unité — la référence de la courbe.
- `parameters` — sans unité — les paramètres du modèle.
- `engine_version` — sans unité — la version du moteur.
- `generated_at` — date — l'instant de la prévision, avec fuseau.
- `segment_s` — secondes — `p_i`, une projection par segment admis.
- `point_s` — secondes — `P_k`, un cumulé par point de `C_k` (usage).
- `target_s` — secondes — `P_k`, un cumulé par élément de `K` (usage).

#### Invariants

- `curve_ref` et `engine_version` non vides ; `generated_at` avec fuseau ;
- `segment_s`, `point_s`, `target_s` sont des tuples ;
- `scenario == CONTROL` ⇒ `point_s` et `target_s` vides.

#### Producteur

`usage_forecast` et `control_forecast` (`mountain_perf.backtest.scoring`).

#### Consommateurs

`score_scenario` ; la prévision conservée (M4b-4) ; les baselines (M4c).

#### Non promis

- **les valeurs ne sont pas validées** : ce sont des sorties de modèle, jugées
  par D7.1 dans les scores (`None`, non finies ou `<= 0` y deviennent
  « erreur du modèle ») ;
- les longueurs ne sont pas recoupées avec une observation : ce sont les
  préconditions de `score_scenario`.

---

## `ClockScores`

*`mountain_perf.schemas.scoring` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `clock` | `Clock` | — |
| `support` | `SupportMetrics` | — |
| `diagnostic` | `PositiveTimeDiagnostic \| None` | — |
| `passage_errors` | `PassageErrors \| None` | — |
| `usage_target` | `UsageTarget \| None` | — |

Les scores d'un scénario sous une horloge (`0010` D5.5, D7).

#### Champs

- `clock` — sans unité — l'horloge des temps observés.
- `support` — sans unité — les métriques du support (D7.1, D7.2).
- `diagnostic` — sans unité — le sous-support à temps positifs (D5.5), quand le
  support a un temps nul.
- `passage_errors` — sans unité — les erreurs aux passages `C_k` (D7.3), en
  usage.
- `usage_target` — sans unité — la cible d'usage `q_usage` (D7.4), en usage.

#### Invariants

- `diagnostic` présent **si et seulement si**
  `support.dispersion.unavailability is ZERO_TIME` ; présent,
  `len(diagnostic.mask) == support.segment_count` ;
- `passage_errors` et `usage_target` tous deux présents ou tous deux absents.

#### Producteur

`score_scenario` (`mountain_perf.backtest.scoring`).

#### Consommateurs

`ScenarioScores` ; le rapport (`mperf match`, M4b-5).

#### Non promis

Le contrat ne recalcule pas les objets de M4b-1 et ne les recoupe pas avec
l'observation.

---

## `ScenarioScores`

*`mountain_perf.schemas.scoring` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `scenario` | `Scenario` | — |
| `forecast` | `ModelForecast` | — |
| `envelope` | `LogRatioEnvelope \| None` | — |
| `class_envelopes` | `tuple[LogRatioEnvelope \| None, ...]` | — |
| `clocks` | `tuple[ClockScores, ...]` | — |

Les scores d'un scénario sous les onze horloges, et ses enveloppes (`0010`
D5.4, D7).

#### Champs

- `scenario` — sans unité — usage ou contrôle.
- `forecast` — sans unité — la prévision scorée.
- `envelope` — sans unité — l'enveloppe de `L` du support (D5.4).
- `class_envelopes` — sans unité — l'enveloppe de `E_R` de chaque classe, dans
  l'ordre de `RegimeClass` (montée, plat, descente, mixte).
- `clocks` — sans unité — les scores sous chaque horloge, dans l'ordre de
  `CLOCKS`.

#### Invariants

- `forecast.scenario == scenario` ; `class_envelopes` et `clocks` sont des
  tuples ;
- `tuple(c.clock for c in clocks) == CLOCKS` ;
- sous toutes les horloges, le même `support.segment_count`, égal à
  `len(forecast.segment_s)`, les mêmes effectifs de classe et le même
  `support.model_error` ;
- `passage_errors` présent sous chaque horloge **si et seulement si**
  `scenario == USAGE` ; en usage, `len(errors_s) == len(forecast.point_s)` et
  `len(usage_target.comparable) == len(forecast.target_s)` ;
- `envelope` absente **si et seulement si** `segment_count == 0` ;
  `class_envelopes` a quatre éléments, chacun absent si et seulement si
  l'effectif de sa classe est nul ;
- une enveloppe présente de motif `model_error` ⇒ `support.model_error` ;
  `support.model_error` ⇒ toute enveloppe présente a un motif.

#### Producteur

`score_scenario` (`mountain_perf.backtest.scoring`).

#### Consommateurs

`OutingScores` ; le rapport (`mperf match`, M4b-5) ; les baselines (M4c).

#### Non promis

Les enveloppes ne sont pas recalculées par le contrat ; elles valent à `P`
fixé (D5.4).

---

## `OutingScores`

*`mountain_perf.schemas.scoring` · dataclass gelée*

| Champ | Type | Défaut |
|---|---|---|
| `observation` | `OutingObservation` | — |
| `control` | `ScenarioScores` | — |
| `usage` | `ScenarioScores \| None` | — |

Les scores d'un modèle sur une sortie, dans ses scénarios (`0010` D3, D7).

#### Champs

- `observation` — sans unité — ce que la sortie observe, indépendamment du
  modèle.
- `control` — sans unité — les scores du scénario contrôle.
- `usage` — sans unité — les scores du scénario usage ; absent pour une sortie
  sans référence (D3).

#### Invariants

- `control.scenario == CONTROL` ; `usage` absent ou
  `usage.scenario == USAGE` ;
- pour chaque scénario présent,
  `len(forecast.segment_s) == len(observation.segments)` ;
- en usage, `len(point_s) == len(observation.error_points)` et
  `len(target_s) == len(observation.targets)`.

#### Producteur

`score_outing` et `v0_scores` (`mountain_perf.backtest.scoring`).

#### Consommateurs

`mperf match` ; le rapport (M4b-5).

#### Non promis

- `usage` absent ne dit pas pourquoi (sortie sans référence : l'appelant le
  sait) ;
- aucune métrique n'y est agrégée sur plusieurs sorties.
