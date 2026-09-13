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
