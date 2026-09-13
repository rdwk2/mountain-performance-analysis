"""Contrats du tracé : lieux nommés, géométrie lue, passages résolus, profil.

Deux objets pour un point remarquable (``docs/decisions/0004``) : le **lieu**
(``NamedPoint``), tel qu'il est dans le fichier, porté par ``Route`` ; le **passage**
(``ResolvedPoint``), résolu sur le tracé, porté par ``RouteProfile``. Un même lieu
peut donner plusieurs passages.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import accumulate
from types import MappingProxyType

from mountain_perf.schemas.common import (
    ELEVATION_RANGE_M,
    LATITUDE_RANGE_DEG,
    LONGITUDE_RANGE_DEG,
    QualityFlag,
    SourceRef,
)
from mountain_perf.schemas.parameters import ParameterSet
from mountain_perf.validation import (
    ContractError,
    require_all_finite,
    require_all_in_range,
    require_finite,
    require_immutable_sequence,
    require_in_range,
    require_increasing,
    require_min_length,
    require_non_empty,
    require_same_length,
)


class PointKind(StrEnum):
    """Nature d'un point nommé.

    Champs
    ------
    Valeurs décrites dans ``POINT_KIND_DESCRIPTIONS``.

    Invariants
    ----------
    Énumération fermée ; ``UNKNOWN`` est la valeur par défaut, et une valeur honnête.

    Producteur
    ----------
    Saisie manuelle ou semi-automatique (M5). Rien ne le remplit en M1.

    Consommateurs
    -------------
    L'affichage des passages (M5) ; plus tard, le temps d'arrêt par point (M6a).

    Non promis
    ----------
    **Jamais inféré en M1** : aucune reconnaissance de motif sur le nom ni sur
    ``raw_type``. Ce genre d'inférence se trompe en silence.
    """

    UNKNOWN = "unknown"
    START = "start"
    FINISH = "finish"
    AID_STATION = "aid_station"
    WATER = "water"
    COL = "col"
    SUMMIT = "summit"
    CHECKPOINT = "checkpoint"


POINT_KIND_DESCRIPTIONS: Mapping[PointKind, str] = MappingProxyType(
    {
        PointKind.UNKNOWN: "Nature non renseignée.",
        PointKind.START: "Départ.",
        PointKind.FINISH: "Arrivée.",
        PointKind.AID_STATION: "Ravitaillement : boire, manger, parfois assistance.",
        PointKind.WATER: "Point d'eau seul.",
        PointKind.COL: "Col : point haut de passage entre deux versants.",
        PointKind.SUMMIT: "Sommet.",
        PointKind.CHECKPOINT: "Point de contrôle ou de pointage, sans ravitaillement.",
    }
)


@dataclass(frozen=True)
class NamedPoint:
    """Lieu nommé, tel qu'il figure dans le fichier source.

    Champs
    ------
    - ``name`` — sans unité — nom du lieu.
    - ``latitude_deg`` — degrés — latitude WGS84, ``[-90, 90]``.
    - ``longitude_deg`` — degrés — longitude WGS84, ``[-180, 180]``.
    - ``elevation_m`` — mètres — altitude du fichier si présente, ``[-500, 9000]``.
    - ``kind`` — sans unité — nature du lieu, ``UNKNOWN`` par défaut.
    - ``raw_type`` — sans unité — le ``<type>``/``<sym>`` du GPX, tel quel.
    - ``cutoff_s`` — secondes depuis le départ — barrière horaire, ``> 0``.
      **Provisoire** : une barrière appartient à une course, pas à un tracé.
    - ``description`` — sans unité — texte libre du fichier.

    Invariants
    ----------
    - ``name`` non vide ;
    - coordonnées finies et dans leurs plages ;
    - ``elevation_m`` finie et dans ``[-500, 9000]`` si présente ;
    - ``cutoff_s`` fini et ``> 0`` si présent.

    Producteur
    ----------
    La lecture GPX (M2).

    Consommateurs
    -------------
    ``Route`` ; la résolution des passages (M2), qui produit des ``ResolvedPoint``.

    Non promis
    ----------
    - **aucune abscisse** : la position sur le tracé n'est pas résolue ici ;
    - ``kind`` n'est jamais inféré en M1 ;
    - ``raw_type`` vient de l'outil qui a produit le GPX et n'est pas fiable ;
    - ``elevation_m`` est celle du fichier et peut différer de celle du profil ;
    - ``cutoff_s`` pourra quitter ce type le jour où une notion de course existera.
    """

    name: str
    latitude_deg: float
    longitude_deg: float
    elevation_m: float | None
    kind: PointKind = PointKind.UNKNOWN
    raw_type: str | None = None
    cutoff_s: float | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.name, "name")
        require_finite(self.latitude_deg, "latitude_deg")
        require_in_range(self.latitude_deg, *LATITUDE_RANGE_DEG, "latitude_deg")
        require_finite(self.longitude_deg, "longitude_deg")
        require_in_range(self.longitude_deg, *LONGITUDE_RANGE_DEG, "longitude_deg")
        if self.elevation_m is not None:
            require_finite(self.elevation_m, "elevation_m")
            require_in_range(self.elevation_m, *ELEVATION_RANGE_M, "elevation_m")
        if self.cutoff_s is not None:
            require_finite(self.cutoff_s, "cutoff_s")
            if self.cutoff_s <= 0:
                raise ContractError(f"cutoff_s doit être > 0, reçu {self.cutoff_s}.")


@dataclass(frozen=True)
class Route:
    """Géométrie d'un tracé, telle que lue dans le fichier.

    Tableaux parallèles : le point ``i`` est
    ``(latitude_deg[i], longitude_deg[i], elevation_m[i])``.

    Champs
    ------
    - ``name`` — sans unité — nom du tracé.
    - ``latitude_deg`` — degrés — latitudes WGS84, ``[-90, 90]``.
    - ``longitude_deg`` — degrés — longitudes WGS84, ``[-180, 180]``.
    - ``elevation_m`` — mètres — altitudes du fichier, ``[-500, 9000]``.
    - ``named_points`` — sans unité — les lieux nommés du fichier.
    - ``source`` — sans unité — provenance du fichier.

    Invariants
    ----------
    - ``name`` non vide ;
    - les trois tableaux et ``named_points`` sont des tuples ;
    - les trois tableaux ont la même longueur, au moins 2 points ;
    - toutes les valeurs sont finies et dans leurs plages.

    Producteur
    ----------
    La lecture GPX (M2).

    Consommateurs
    -------------
    La construction du profil (M2), qui produit un ``RouteProfile``.

    Non promis
    ----------
    - **aucune distance** : elle se calcule, et c'est le M2 qui la calcule ;
    - **aucun temps** : un tracé est une géométrie, pas un enregistrement ;
    - **rien n'est lissé ni rééchantillonné** : les points ne sont pas
      régulièrement espacés ;
    - les points nommés sont ceux du fichier, tous, sans filtre ni tri ;
    - **aucun sport** : le même sentier se court, se marche et se skie ;
    - les tableaux ne sont pas copiés ; ils sont exigés immuables.
    """

    name: str
    latitude_deg: Sequence[float]
    longitude_deg: Sequence[float]
    elevation_m: Sequence[float]
    named_points: tuple[NamedPoint, ...]
    source: SourceRef

    def __post_init__(self) -> None:
        require_non_empty(self.name, "name")
        require_immutable_sequence(self.latitude_deg, "latitude_deg")
        require_immutable_sequence(self.longitude_deg, "longitude_deg")
        require_immutable_sequence(self.elevation_m, "elevation_m")
        require_immutable_sequence(self.named_points, "named_points")
        require_same_length(
            latitude_deg=self.latitude_deg,
            longitude_deg=self.longitude_deg,
            elevation_m=self.elevation_m,
        )
        require_min_length(self.latitude_deg, 2, "latitude_deg")
        require_all_finite(self.latitude_deg, "latitude_deg")
        require_all_finite(self.longitude_deg, "longitude_deg")
        require_all_finite(self.elevation_m, "elevation_m")
        require_all_in_range(self.latitude_deg, *LATITUDE_RANGE_DEG, "latitude_deg")
        require_all_in_range(self.longitude_deg, *LONGITUDE_RANGE_DEG, "longitude_deg")
        require_all_in_range(self.elevation_m, *ELEVATION_RANGE_M, "elevation_m")


@dataclass(frozen=True)
class ResolvedPoint:
    """Passage d'un lieu nommé, résolu sur le tracé.

    Champs
    ------
    - ``point`` — sans unité — le lieu d'origine.
    - ``distance_m`` — mètres — abscisse curviligne le long du tracé (distance
      horizontale cumulée depuis le départ), ``>= 0``.
    - ``elevation_m`` — mètres — altitude lue sur le profil, ``[-500, 9000]`` ;
      différente de ``point.elevation_m``.
    - ``offset_m`` — mètres — écart entre le lieu nommé et le tracé, ``>= 0``.
      Indicateur de qualité : 3 m est bon, 180 m mérite un regard.

    Invariants
    ----------
    - valeurs finies ;
    - ``distance_m >= 0`` ; ``offset_m >= 0`` ;
    - ``elevation_m`` dans ``[-500, 9000]``.

    Producteur
    ----------
    La résolution des passages (M2).

    Consommateurs
    -------------
    ``RouteProfile`` ; la projection (M3) et le backtest (M4), qui comparent des
    temps à ces passages.

    Non promis
    ----------
    - la règle qui a produit la résolution (minima locaux, seuils d'écart et de
      séparation) : elle est du M2 ;
    - l'unicité : un même lieu peut donner plusieurs ``ResolvedPoint``.
    """

    point: NamedPoint
    distance_m: float
    elevation_m: float
    offset_m: float

    def __post_init__(self) -> None:
        require_finite(self.distance_m, "distance_m")
        require_finite(self.elevation_m, "elevation_m")
        require_finite(self.offset_m, "offset_m")
        if self.distance_m < 0:
            raise ContractError(f"distance_m doit être >= 0, reçu {self.distance_m}.")
        if self.offset_m < 0:
            raise ContractError(f"offset_m doit être >= 0, reçu {self.offset_m}.")
        require_in_range(self.elevation_m, *ELEVATION_RANGE_M, "elevation_m")


@dataclass(frozen=True)
class RouteProfile:
    """Profil d'un tracé sur une grille de distance : le produit du M2.

    Tableaux parallèles : le point ``i`` de la grille est
    ``(distance_m[i], elevation_m[i])``.

    Champs
    ------
    - ``route_name`` — sans unité — nom du ``Route`` d'origine.
    - ``source`` — sans unité — provenance du ``Route`` d'origine.
    - ``distance_m`` — mètres — grille : distance cumulée **2D horizontale**
      depuis le départ.
    - ``elevation_m`` — mètres — altitude **lissée** sur la grille, ``[-500, 9000]``.
    - ``resolved_points`` — sans unité — passages aux lieux nommés, par abscisse
      croissante.
    - ``step_m`` — mètres — pas nominal de la grille, ``> 0``.
    - ``build_parameters`` — sans unité — paramètres de construction (lissage, pas
      de grille, seuils de résolution).
    - ``quality_flags`` — sans unité — suspicions portées par le profil ; vide par
      défaut.

    Propriétés calculées (jamais stockées) : ``grade``, ``cumulative_ascent_m``,
    ``cumulative_descent_m``.

    Invariants
    ----------
    - ``route_name`` non vide ;
    - ``distance_m``, ``elevation_m`` et ``resolved_points`` sont des tuples ;
    - ``len(elevation_m) == len(distance_m)``, au moins 2 points ;
    - valeurs finies ; altitudes dans ``[-500, 9000]`` ;
    - ``distance_m[0] == 0`` et ``distance_m`` strictement croissante ;
    - ``step_m`` fini et ``> 0`` ;
    - ``resolved_points`` triés par ``distance_m`` croissant au sens large, tous dans
      ``[0, distance_m[-1]]``.

    **Deux entrées de ``resolved_points`` peuvent porter le même ``NamedPoint``** à
    des abscisses différentes : aller-retour au sommet, boucle dont le départ est
    l'arrivée, lieu traversé à la montée et à la descente.

    Producteur
    ----------
    La construction du profil (M2), à partir d'un ``Route``.

    Consommateurs
    -------------
    Le moteur de projection (M3), le backtest (M4), l'interface (M5), le découpage
    en segments (M1b).

    Non promis
    ----------
    - le pas n'est **pas** exactement constant : le dernier intervalle est plus
      court, la longueur du tracé n'étant pas un multiple du pas ;
    - l'altitude est lissée : elle ne correspond pas point par point au fichier, et
      le D+ total d'ici diffère de celui du fichier, parfois de plusieurs centaines
      de mètres (``docs/PIEGES_DATA.md``) ;
    - la méthode de calcul de la distance (géodésique, projection) : seul son sens,
      horizontal, est fixé ici, parce que ``grade = Δaltitude / distance
      horizontale`` (``docs/decisions/0002``) ;
    - ``source`` n'est pas vérifiée contre le ``Route`` d'origine ;
    - les tableaux ne sont pas copiés ; ils sont exigés immuables.
    """

    route_name: str
    source: SourceRef
    distance_m: Sequence[float]
    elevation_m: Sequence[float]
    resolved_points: tuple[ResolvedPoint, ...]
    step_m: float
    build_parameters: ParameterSet
    quality_flags: frozenset[QualityFlag] = frozenset()

    def __post_init__(self) -> None:
        require_non_empty(self.route_name, "route_name")
        require_immutable_sequence(self.distance_m, "distance_m")
        require_immutable_sequence(self.elevation_m, "elevation_m")
        require_immutable_sequence(self.resolved_points, "resolved_points")
        require_same_length(distance_m=self.distance_m, elevation_m=self.elevation_m)
        require_min_length(self.distance_m, 2, "distance_m")
        require_all_finite(self.distance_m, "distance_m")
        require_all_finite(self.elevation_m, "elevation_m")
        require_all_in_range(self.elevation_m, *ELEVATION_RANGE_M, "elevation_m")
        if self.distance_m[0] != 0:
            raise ContractError(
                f"distance_m doit commencer à 0, reçu {self.distance_m[0]}."
            )
        require_increasing(self.distance_m, "distance_m", strict=True)
        require_finite(self.step_m, "step_m")
        if self.step_m <= 0:
            raise ContractError(f"step_m doit être > 0, reçu {self.step_m}.")
        for i, resolved in enumerate(self.resolved_points):
            require_in_range(
                resolved.distance_m,
                0.0,
                self.distance_m[-1],
                f"resolved_points[{i}].distance_m",
            )
        require_increasing(
            tuple(resolved.distance_m for resolved in self.resolved_points),
            "resolved_points.distance_m",
            strict=False,
        )

    @property
    def grade(self) -> tuple[float, ...]:
        """Pente (fraction, sans unité) de chaque intervalle de la grille.

        ``len(distance_m) - 1`` valeurs ; ``grade[i]`` est la pente entre les points
        ``i`` et ``i + 1`` : ``Δaltitude / Δdistance horizontale``. Positive en
        montée.
        """
        d, e = self.distance_m, self.elevation_m
        return tuple((e[i + 1] - e[i]) / (d[i + 1] - d[i]) for i in range(len(d) - 1))

    @property
    def cumulative_ascent_m(self) -> tuple[float, ...]:
        """D+ cumulé (mètres) à chaque point de la grille.

        Même longueur que ``distance_m``, commence à 0, croissant au sens large ;
        le dernier élément est le D+ total. Le D+ d'un segment s'obtient par
        soustraction.
        """
        e = self.elevation_m
        steps = (max(e[i + 1] - e[i], 0.0) for i in range(len(e) - 1))
        return tuple(accumulate(steps, initial=0.0))

    @property
    def cumulative_descent_m(self) -> tuple[float, ...]:
        """D− cumulé (mètres, positif) à chaque point de la grille.

        Même longueur que ``distance_m``, commence à 0, croissant au sens large ;
        le dernier élément est le D− total.
        """
        e = self.elevation_m
        steps = (max(e[i] - e[i + 1], 0.0) for i in range(len(e) - 1))
        return tuple(accumulate(steps, initial=0.0))
