"""Contrats de la sortie de l'outil : passages projetés, segments, projection.

Deux vues, une seule source : les **cumulés** (``Passage``), seule chose qu'un
chronométrage produit, et les **segments** (``Segment``), où l'erreur se diagnostique
— un cumul est une somme, une erreur au kilomètre 20 se propage dans tous les cumuls
suivants. Les segments sont toujours dérivés des passages, jamais stockés.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise

from mountain_perf.schemas.common import ELEVATION_RANGE_M, UTC_OFFSET_RANGE_S
from mountain_perf.schemas.parameters import ParameterSet
from mountain_perf.schemas.route import ResolvedPoint, RouteProfile
from mountain_perf.validation import (
    ContractError,
    require_aware,
    require_finite,
    require_immutable_sequence,
    require_in_range,
    require_increasing,
    require_min_length,
    require_non_empty,
)


@dataclass(frozen=True)
class Passage:
    """Passage projeté à un point du tracé : temps cumulés depuis le départ.

    Champs
    ------
    - ``point`` — sans unité — le passage résolu sur le profil (abscisse, altitude).
    - ``moving_time_s`` — secondes — temps de mouvement cumulé, ``>= 0``.
    - ``arrival_s`` — secondes — temps écoulé cumulé à l'arrivée au point, ``>= 0``.
    - ``departure_s`` — secondes — temps écoulé cumulé au départ du point, ``>= 0``.

    Propriété calculée (jamais stockée) : ``stop_duration_s``.

    Invariants
    ----------
    - valeurs finies et ``>= 0`` ;
    - ``departure_s >= arrival_s`` ;
    - ``moving_time_s <= arrival_s``.

    Une seule valeur de temps de mouvement : on n'avance pas pendant un arrêt, elle est
    la même à l'arrivée et au départ.

    Producteur
    ----------
    Le moteur de projection (M3, puis M6a).

    Consommateurs
    -------------
    ``Projection`` ; l'affichage des passages (M5) ; le backtest (M4).

    Non promis
    ----------
    - en M3 le modèle ne connaît pas les arrêts : ``arrival_s == departure_s``. Au M6a
      ils s'écartent, **sans que le contrat bouge** ;
    - l'origine des temps (``0``) est le départ de la projection, pas une heure.
    """

    point: ResolvedPoint
    moving_time_s: float
    arrival_s: float
    departure_s: float

    def __post_init__(self) -> None:
        for name in ("moving_time_s", "arrival_s", "departure_s"):
            value: float = getattr(self, name)
            require_finite(value, name)
            if value < 0:
                raise ContractError(f"{name} doit être >= 0, reçu {value}.")
        if self.departure_s < self.arrival_s:
            raise ContractError(
                f"departure_s ({self.departure_s}) doit être >= "
                f"arrival_s ({self.arrival_s})."
            )
        if self.moving_time_s > self.arrival_s:
            raise ContractError(
                f"moving_time_s ({self.moving_time_s}) doit être <= "
                f"arrival_s ({self.arrival_s})."
            )

    @property
    def stop_duration_s(self) -> float:
        """Temps d'arrêt au point (secondes) : ``departure_s - arrival_s``."""
        return self.departure_s - self.arrival_s


@dataclass(frozen=True)
class Segment:
    """Tronçon entre deux passages consécutifs d'une projection.

    Champs
    ------
    - ``start``, ``end`` — sans unité — les deux passages qui bornent le tronçon.
    - ``ascent_m``, ``descent_m`` — mètres — D+ et D− du tronçon, ``>= 0``.
    - ``elevation_min_m``, ``elevation_max_m`` — mètres — altitudes extrêmes du
      tronçon, ``[-500, 9000]``.

    Propriétés calculées (jamais stockées) : ``duration_s``
    (``end.arrival_s - start.departure_s``) et ``distance_m`` (différence des
    abscisses).

    Les altitudes et dénivelés sont stockés parce qu'ils ne se recalculent pas depuis
    les deux passages seuls : il faut le profil.

    Invariants
    ----------
    - valeurs finies ; ``ascent_m``, ``descent_m`` ``>= 0`` ;
    - altitudes dans ``[-500, 9000]`` et ``elevation_min_m <= elevation_max_m`` ;
    - ``end`` n'est pas avant ``start`` : ni en abscisse, ni en temps
      (``end.arrival_s >= start.departure_s``).

    Producteur
    ----------
    **Uniquement** ``Projection.segments``.

    Consommateurs
    -------------
    Le diagnostic d'erreur par tronçon (M4), l'affichage (M5).

    Non promis
    ----------
    - **la cohérence des grandeurs avec un profil n'est pas garantie** par ce type :
      seule ``Projection.segments`` en produit de cohérentes. Un ``Segment`` construit
      à la main peut porter n'importe quel D+ ;
    - les altitudes extrêmes se lisent sur le profil **lissé et rééchantillonné**, pas
      sur le GPX brut : elles diffèrent d'une application de cartographie, parfois de
      plusieurs dizaines de mètres, sans que ce soit un bug.
    """

    start: Passage
    end: Passage
    ascent_m: float
    descent_m: float
    elevation_min_m: float
    elevation_max_m: float

    def __post_init__(self) -> None:
        for name in ("ascent_m", "descent_m", "elevation_min_m", "elevation_max_m"):
            require_finite(getattr(self, name), name)
        for name in ("ascent_m", "descent_m"):
            value: float = getattr(self, name)
            if value < 0:
                raise ContractError(f"{name} doit être >= 0, reçu {value}.")
        require_in_range(self.elevation_min_m, *ELEVATION_RANGE_M, "elevation_min_m")
        require_in_range(self.elevation_max_m, *ELEVATION_RANGE_M, "elevation_max_m")
        if self.elevation_min_m > self.elevation_max_m:
            raise ContractError(
                f"elevation_min_m ({self.elevation_min_m}) doit être <= "
                f"elevation_max_m ({self.elevation_max_m})."
            )
        if self.end.point.distance_m < self.start.point.distance_m:
            raise ContractError("end doit être à une abscisse >= celle de start.")
        if self.end.arrival_s < self.start.departure_s:
            raise ContractError(
                f"end.arrival_s ({self.end.arrival_s}) doit être >= "
                f"start.departure_s ({self.start.departure_s})."
            )

    @property
    def duration_s(self) -> float:
        """Durée du tronçon (secondes) : ``end.arrival_s - start.departure_s``."""
        return self.end.arrival_s - self.start.departure_s

    @property
    def distance_m(self) -> float:
        """Longueur horizontale du tronçon (mètres) : différence des abscisses."""
        return self.end.point.distance_m - self.start.point.distance_m


@dataclass(frozen=True)
class Projection:
    """Un scénario projeté sur un tracé : les passages, et les segments qui en dérivent.

    Champs
    ------
    - ``profile`` — sans unité — le profil projeté.
    - ``curve_ref`` — sans unité — référence de la ``PaceCurve`` utilisée.
    - ``parameters`` — sans unité — paramètres du modèle pour ce scénario.
    - ``passages`` — sans unité — passages par abscisse croissante, départ et arrivée
      compris.
    - ``start_time`` — instant — heure de départ, *aware*, **dans son fuseau local à
      décalage fixe** (pas en UTC) ; ancre les effets d'heure. Absent si non fixé.
    - ``engine_version`` — sans unité — version du moteur qui a produit la projection.
    - ``generated_at`` — instant — moment du calcul, *aware*, stocké en UTC.

    Propriétés calculées (jamais stockées) : ``segments``, ``utc_offset_s``.

    ``start_time`` n'est pas normalisé en UTC, contrairement à ``generated_at`` : son
    fuseau porte le décalage local, qui a un sens physique (chaleur, nuit). Un instant
    dont l'heure locale a un sens physique se stocke dans son fuseau à décalage fixe,
    les autres en UTC (``docs/decisions/0006``).

    Invariants
    ----------
    - ``curve_ref`` et ``engine_version`` non vides ;
    - ``passages`` est un tuple d'au moins 2 passages ;
    - abscisses croissantes au sens large ; **le premier passage est à l'abscisse 0 et
      le dernier à la fin du profil** ;
    - pour deux passages consécutifs ``i``, ``i + 1`` : ``departure_s[i] <=
      arrival_s[i + 1]`` (durée de segment ``>= 0``, d'où ``arrival_s`` et
      ``departure_s`` croissants), ``moving_time_s`` croissant au sens large, et
      ``moving_time_s[i + 1] - moving_time_s[i] <= arrival_s[i + 1] - departure_s[i]``
      (on ne bouge pas plus longtemps que le temps écoulé sur le segment) ;
    - ``start_time`` *aware* si présent, décalage dans ``[-43200, 50400]`` secondes ;
    - ``generated_at`` *aware*, normalisé en UTC.

    **La projection synthétise toujours un passage de départ et un d'arrivée**, même
    si le GPX ne porte pas de waypoint à ces endroits : sans eux, les segments ne
    couvrent pas la tête ni la queue du parcours et le total ne ferme pas.

    **Invariant central** — les arrêts se somment sur les passages **intérieurs**
    (``passages[1:-1]``)::

        Σ segment.duration_s + Σ passages[1:-1].stop_duration_s
            == passages[-1].arrival_s - passages[0].departure_s

    Sommer les arrêts de *tous* les passages donne ``passages[-1].departure_s -
    passages[0].arrival_s``, une autre quantité : l'écart est l'arrêt au premier
    passage plus l'arrêt au dernier.

    Producteur
    ----------
    Le moteur de projection (M3, puis M6a, M7).

    Consommateurs
    -------------
    L'interface (M5), le backtest (M4), la comparaison de scénarios (M9), la couche
    d'incertitude (M8).

    Non promis
    ----------
    - **une projection est un scénario, pas une fourchette.** Comparer deux scénarios,
      c'est comparer deux ``Projection``. Pas de P50/P80 ici : **les quantiles ne
      s'additionnent pas** — le P80 du temps total n'est pas la somme des P80 par
      segment (c'est la variance qui s'additionne, pas l'écart-type), donc sommer des
      P80 surestime largement la fourchette. La couche d'incertitude du M8 sera une
      distribution *sur* les projections, pas une projection aux nombres plus larges ;
    - ``curve_ref`` n'est pas résolu ni vérifié ; le ``Sport`` de la courbe n'est pas
      recoupé ici ;
    - les passages ne sont pas vérifiés contre ``profile.resolved_points`` : départ et
      arrivée synthétisés n'y figurent pas forcément ;
    - D+, D− et altitudes des segments supposent **l'altitude linéaire entre deux
      points de la grille** — l'hypothèse même de ``RouteProfile.grade`` ;
    - ``utc_offset_s`` est le décalage **au départ** : une projection qui franchit un
      changement d'heure calculera les heures locales avec une heure d'écart après la
      bascule ;
    - l'origine des temps n'est pas garantie nulle (``passages[0].arrival_s``).
    """

    profile: RouteProfile
    curve_ref: str
    parameters: ParameterSet
    passages: tuple[Passage, ...]
    start_time: datetime | None
    engine_version: str
    generated_at: datetime

    def __post_init__(self) -> None:
        require_non_empty(self.curve_ref, "curve_ref")
        require_non_empty(self.engine_version, "engine_version")
        require_immutable_sequence(self.passages, "passages")
        require_min_length(self.passages, 2, "passages")
        require_increasing(
            tuple(passage.point.distance_m for passage in self.passages),
            "passages.distance_m",
            strict=False,
        )
        first, last = self.passages[0], self.passages[-1]
        if first.point.distance_m != 0:
            raise ContractError(
                "Le premier passage doit être à l'abscisse 0, "
                f"reçu {first.point.distance_m}."
            )
        end_m = self.profile.distance_m[-1]
        if last.point.distance_m != end_m:
            raise ContractError(
                f"Le dernier passage doit être à la fin du profil ({end_m} m), "
                f"reçu {last.point.distance_m}."
            )
        for i, (a, b) in enumerate(pairwise(self.passages)):
            if b.arrival_s < a.departure_s:
                raise ContractError(
                    f"passages[{i + 1}].arrival_s ({b.arrival_s}) doit être >= "
                    f"passages[{i}].departure_s ({a.departure_s})."
                )
            if b.moving_time_s < a.moving_time_s:
                raise ContractError(
                    f"passages[{i + 1}].moving_time_s doit être >= "
                    f"passages[{i}].moving_time_s."
                )
            if b.moving_time_s - a.moving_time_s > b.arrival_s - a.departure_s:
                raise ContractError(
                    f"Segment {i} : moving_time_s progresse plus que le temps écoulé."
                )
        if self.start_time is not None:
            offset = require_aware(self.start_time, "start_time")
            require_in_range(
                offset.total_seconds(),
                *UTC_OFFSET_RANGE_S,
                "décalage de start_time (s)",
            )
        require_aware(self.generated_at, "generated_at")
        object.__setattr__(self, "generated_at", self.generated_at.astimezone(UTC))

    @property
    def utc_offset_s(self) -> int | None:
        """Décalage local au départ (secondes), lu sur le fuseau de ``start_time``."""
        if self.start_time is None:
            return None
        return int(require_aware(self.start_time, "start_time").total_seconds())

    @property
    def segments(self) -> tuple[Segment, ...]:
        """Tronçons entre passages consécutifs, dérivés des passages et du profil.

        ``len(passages) - 1`` segments. Altitude supposée linéaire entre deux points de
        la grille.
        """
        grid = self.profile.distance_m
        elevation = self.profile.elevation_m
        ascent = self.profile.cumulative_ascent_m
        descent = self.profile.cumulative_descent_m
        segments: list[Segment] = []
        for start, end in pairwise(self.passages):
            a, b = start.point.distance_m, end.point.distance_m
            inner = elevation[bisect_right(grid, a) : bisect_left(grid, b)]
            extremes = (
                _interpolate(grid, elevation, a),
                _interpolate(grid, elevation, b),
                *inner,
            )
            segments.append(
                Segment(
                    start=start,
                    end=end,
                    # max(0, …) : un arrondi flottant ne doit pas rendre un D+ négatif.
                    ascent_m=max(
                        0.0,
                        _interpolate(grid, ascent, b) - _interpolate(grid, ascent, a),
                    ),
                    descent_m=max(
                        0.0,
                        _interpolate(grid, descent, b) - _interpolate(grid, descent, a),
                    ),
                    elevation_min_m=min(extremes),
                    elevation_max_m=max(extremes),
                )
            )
        return tuple(segments)


def _interpolate(grid: Sequence[float], values: Sequence[float], x: float) -> float:
    """Valeur en ``x`` d'une grandeur linéaire par morceaux sur ``grid``.

    ``grid`` strictement croissante, ``x`` dans ``[grid[0], grid[-1]]``. Exacte aux
    points de la grille. Sert à l'altitude et aux D+/D− cumulés, linéaires entre deux
    points de grille puisque l'altitude y est monotone.
    """
    i = min(max(bisect_right(grid, x) - 1, 0), len(grid) - 2)
    x0, x1 = grid[i], grid[i + 1]
    if x == x0:
        return values[i]
    if x == x1:
        return values[i + 1]
    t = (x - x0) / (x1 - x0)
    return values[i] + t * (values[i + 1] - values[i])
