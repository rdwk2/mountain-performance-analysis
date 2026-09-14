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
  (on ne bouge pas plus longtemps que le temps écoulé sur le segment) ;
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
