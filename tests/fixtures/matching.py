"""Fixtures synthétiques de l'appariement (M4a-2a) — plan à 45° N, valeurs inventées.

Convention du § 7.0 du brief M4a-2a : références et traces sont décrites en mètres
``(x, y)``, ``x`` vers l'est et ``y`` vers le nord, et converties par
:func:`fixtures.traces.local_deg`, l'aide unique ; une autre latitude de base ne sert
qu'aux reconstructions à 0° et 60° (test 4 du § 8). Référence plate (0 m), trace à
1 000 m.

- :func:`reference_route` et :func:`reference` : une référence par ses sommets ;
- :func:`local_trace` : une trace par ses instants et ses points ;
- :class:`TracePath` : les chemins « ``A→B→…`` à ``v`` m/s, un enregistrement toutes
  les ``δ`` s » du § 7.0, chaque branche coupée en ``round(longueur / (v·δ))`` pas
  égaux ;
- un constructeur par ligne du tableau du § 7.2a, et les trois fixtures de session
  S01 à S03 (règles qu'aucune ligne du § 7.2a ne distingue).

Utilisées par ``tests/test_backtest_matching.py``,
``tests/test_backtest_matching_properties.py`` et ``tests/test_cli_match.py``.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Self

from fixtures.traces import TRACE_SOURCE, TRACE_START, gpx_document, local_deg
from mountain_perf.backtest import (
    MATCHING_PARAMETER_SPECS,
    ReferenceGeometry,
    build_series,
    match_points,
    reference_geometry,
    trace_route,
)
from mountain_perf.schemas import (
    ParameterSet,
    RecordedTrace,
    Route,
    ScorePointObservation,
    SourceRef,
)

REFERENCE_SOURCE = SourceRef(
    kind="gpx",
    identifier="reference_synthetique.gpx",
    content_hash="1" * 64,
    retrieved_at=datetime(2026, 9, 24, tzinfo=UTC),
)

Point = tuple[float, float]
"""Un point ``(x, y)`` du plan de base, en mètres."""


def reference_route(*vertices_m: Point, base_latitude_deg: float = 45.0) -> Route:
    """Référence plate de sommets ``vertices_m``, sans lieu nommé."""
    positions = [
        local_deg(x_m, y_m, base_latitude_deg=base_latitude_deg)
        for x_m, y_m in vertices_m
    ]
    return Route(
        name="Référence synthétique",
        latitude_deg=tuple(lat for lat, _ in positions),
        longitude_deg=tuple(lon for _, lon in positions),
        elevation_m=(0.0,) * len(positions),
        named_points=(),
        source=REFERENCE_SOURCE,
    )


def reference(*vertices_m: Point, base_latitude_deg: float = 45.0) -> ReferenceGeometry:
    """Géométrie de référence de :func:`reference_route`."""
    return reference_geometry(
        reference_route(*vertices_m, base_latitude_deg=base_latitude_deg)
    )


def local_trace(
    time_s: Sequence[float],
    points_m: Sequence[Point],
    *,
    base_latitude_deg: float = 45.0,
) -> RecordedTrace:
    """Trace à 1 000 m d'altitude, positions par :func:`local_deg`."""
    positions = [
        local_deg(x_m, y_m, base_latitude_deg=base_latitude_deg)
        for x_m, y_m in points_m
    ]
    return RecordedTrace(
        start_time=TRACE_START,
        time_s=tuple(float(t) for t in time_s),
        latitude_deg=tuple(lat for lat, _ in positions),
        longitude_deg=tuple(lon for _, lon in positions),
        elevation_m=(1000.0,) * len(positions),
        sources=(TRACE_SOURCE,),
        dropped_same_instant_count=0,
    )


class TracePath:
    """Chemin du § 7.0 : chaque branche ``A→B`` parcourue à ``v`` m/s, un
    enregistrement toutes les ``δ`` s, coupée en ``round(longueur / (v·δ))`` pas
    **égaux** ; le premier point d'une branche est le dernier de la précédente.
    Une position de branche est ``(1 − u)·A + u·B`` : exacte en ``B``."""

    def __init__(self, start: Point) -> None:
        self.time_s: list[float] = [0.0]
        self.points_m: list[Point] = [start]

    def to(self, *waypoints: Point, speed_ms: float, step_s: float = 1.0) -> Self:
        """Branches successives jusqu'à chaque point de ``waypoints``."""
        for bx_m, by_m in waypoints:
            ax_m, ay_m = self.points_m[-1]
            steps = round(math.hypot(bx_m - ax_m, by_m - ay_m) / (speed_ms * step_s))
            for s in range(1, steps + 1):
                u = s / steps
                self.time_s.append(self.time_s[-1] + step_s)
                self.points_m.append(
                    ((1 - u) * ax_m + u * bx_m, (1 - u) * ay_m + u * by_m)
                )
        return self

    def jump(self, target: Point, duration_s: float) -> Self:
        """Un seul enregistrement en ``target``, ``duration_s`` après le dernier."""
        self.time_s.append(self.time_s[-1] + duration_s)
        self.points_m.append(target)
        return self

    def trace(self, *, base_latitude_deg: float = 45.0) -> RecordedTrace:
        return local_trace(
            self.time_s, self.points_m, base_latitude_deg=base_latitude_deg
        )


def matching_parameters(**values: float) -> ParameterSet:
    """Paramètres de l'appariement ; les défauts de ``0010`` sauf mention."""
    return ParameterSet(MATCHING_PARAMETER_SPECS, values)


@dataclass(frozen=True)
class MatchCase:
    """Une référence, une trace et des paramètres.

    ``features`` : étiquettes de construction posées par une stratégie (``"gap"``,
    ``"backtrack"``…), pour vérifier ce qu'elle sait produire ; vide ailleurs.
    """

    route: Route
    trace: RecordedTrace
    parameters: ParameterSet = field(default_factory=matching_parameters)
    features: frozenset[str] = frozenset()

    @property
    def geometry(self) -> ReferenceGeometry:
        return reference_geometry(self.route)

    def match(self) -> tuple[ScorePointObservation, ...]:
        """Les observations de ``match_points`` sur ce cas."""
        return match_points(
            self.geometry, self.trace, build_series(self.trace), self.parameters
        )


def _along_x(
    x_m: Sequence[float], y_m: float = 0.0, time_s: Sequence[float] | None = None
) -> RecordedTrace:
    times = time_s if time_s is not None else range(len(x_m))
    return local_trace(list(times), [(x, y_m) for x in x_m])


EAST_510 = ((0.0, 0.0), (510.0, 0.0))
EAST_520 = ((0.0, 0.0), (520.0, 0.0))
CENTERED_510 = ((-250.0, 0.0), (260.0, 0.0))
HALF_TURN = ((0.0, 0.0), (275.0, 0.0), (0.0, 0.0))

# ---------------------------------------------------------------------------
# § 7.2a — une fonction par ligne du tableau
# ---------------------------------------------------------------------------


def t01() -> MatchCase:
    """``x = 2t``, un enregistrement toutes les 2 s, ``t = 0 … 260``."""
    times = [2.0 * i for i in range(131)]
    return MatchCase(
        reference_route(*EAST_520), _along_x([2 * t for t in times], time_s=times)
    )


def t01_bis() -> MatchCase:
    """À l'arrêt en ``x = 0`` de 0 à 10 s, puis ``x = 2(t − 10)``, toutes les 2 s."""
    times = [2.0 * i for i in range(136)]
    return MatchCase(
        reference_route(*EAST_520),
        _along_x([max(0.0, 2 * (t - 10)) for t in times], time_s=times),
    )


def x01(step_s: float = 2.0) -> MatchCase:
    """``x = 25 + 1,5·t``, ``y = 8 − 14·(x − 25)/480``, ``t = 0 … 320``."""
    times = [step_s * i for i in range(round(320 / step_s) + 1)]
    points = []
    for t in times:
        x_m = 25 + 1.5 * t
        points.append((x_m, 8 - 14 * (x_m - 25) / 480))
    return MatchCase(
        reference_route((0.0, 0.0), (530.0, 0.0)), local_trace(times, points)
    )


X03_ROUTE = (
    (0.0, 0.0),
    (20.0, 0.0),
    (20.0, 10.0),
    (0.0, 10.0),
    (0.0, 20.0),
    (0.0, 300.0),
)


def x03() -> MatchCase:
    path = TracePath((10.0, 5.0)).to(
        (20.0, 5.0), (20.0, 10.0), (0.0, 10.0), (0.0, 20.0), (0.0, 300.0), speed_ms=1.0
    )
    return MatchCase(reference_route(*X03_ROUTE), path.trace())


def x03_arrival() -> MatchCase:
    path = TracePath((0.0, 300.0)).to(
        (0.0, 20.0), (0.0, 10.0), (20.0, 10.0), (20.0, 5.0), (10.0, 5.0), speed_ms=1.0
    )
    return MatchCase(reference_route(*reversed(X03_ROUTE)), path.trace())


def x03_bis() -> MatchCase:
    path = TracePath((0.0, 0.0)).to((505.0, 0.0), (495.0, 0.0), speed_ms=1.0)
    return MatchCase(reference_route(*EAST_520), path.trace())


def x08_elbow() -> MatchCase:
    path = TracePath((22.0, 5.0)).to((22.0, 291.0), speed_ms=2.0)
    return MatchCase(
        reference_route((0.0, 0.0), (20.0, 0.0), (20.0, 300.0)), path.trace()
    )


def x08_mirror() -> MatchCase:
    path = TracePath((22.0, 291.0)).to((22.0, 5.0), speed_ms=2.0)
    return MatchCase(
        reference_route((20.0, 300.0), (20.0, 0.0), (0.0, 0.0)), path.trace()
    )


def x09() -> MatchCase:
    path = TracePath((20.0, 20.0)).to(
        (-5.0, 40.0), (5.0, 40.0), (25.0, 40.0), (25.0, 300.0), speed_ms=1.0
    )
    return MatchCase(
        reference_route((0.0, 0.0), (25.0, 0.0), (25.0, 300.0)), path.trace()
    )


def x10() -> MatchCase:
    path = TracePath((25.0, 300.0)).to((25.0, 20.0), (20.0, 20.0), speed_ms=1.0)
    return MatchCase(
        reference_route((25.0, 300.0), (25.0, 0.0), (0.0, 0.0)), path.trace()
    )


def x11() -> MatchCase:
    path = TracePath((0.0, 0.0)).to(
        (504.0, 0.0), (504.0, 600.0), (504.0, 6.0), speed_ms=2.0
    )
    return MatchCase(reference_route(*EAST_510), path.trace())


def x12() -> MatchCase:
    return MatchCase(
        reference_route((0.0, 0.0), (40.0, 0.0)),
        _along_x([25.0, 22.0], time_s=[0.0, 4.0]),
    )


def x13() -> MatchCase:
    path = (
        TracePath((0.0, 0.0))
        .to((260.0, 0.0), (260.0, 340.0), (490.0, 340.0), (490.0, 0.0), speed_ms=2.0)
        .jump((590.0, 0.0), 10.0)
        .to((1010.0, 0.0), speed_ms=2.0)
    )
    return MatchCase(reference_route((0.0, 0.0), (1010.0, 0.0)), path.trace())


def x14() -> MatchCase:
    path = TracePath((0.0, 0.0)).to(
        (274.0, 0.0),
        (138.0, 0.0),
        (138.0, -250.0),
        (138.0, 0.0),
        (0.0, 0.0),
        speed_ms=2.0,
    )
    return MatchCase(
        reference_route(*HALF_TURN),
        path.trace(),
        matching_parameters(score_step_m=275.0),
    )


def x04() -> MatchCase:
    return MatchCase(
        reference_route(*CENTERED_510),
        _along_x([-1.0, 1.0, -1.0, 1.0], time_s=[0.0, 2.0, 102.0, 104.0]),
    )


def x05() -> MatchCase:
    return MatchCase(
        reference_route((0.0, 0.0), (20.0, 0.0)),
        _along_x([0.0, 20.0], time_s=[0.0, 10.0]),
    )


def t02() -> MatchCase:
    return MatchCase(
        reference_route(*CENTERED_510),
        local_trace([0.0, 10.0], [(-1.0, -40.0), (1.0, 40.0)]),
    )


def t03_cluster() -> MatchCase:
    return MatchCase(
        reference_route(*CENTERED_510),
        _along_x([-1.0, 1.0, -1.0, 1.0], time_s=[0.0, 2.0, 4.0, 6.0]),
    )


def t03_branches() -> MatchCase:
    points = [
        (-1.0, 0.0),
        (1.0, 0.0),
        (1.0, 20.0),
        (-1.0, 20.0),
        (-1.0, 0.0),
        (1.0, 0.0),
    ]
    return MatchCase(
        reference_route(*CENTERED_510),
        local_trace([2.0 * i for i in range(6)], points),
    )


def t03_east(base_latitude_deg: float = 45.0) -> MatchCase:
    """Le sous-chemin s'écarte de 12 m vers l'est d'une référence qui monte au nord."""
    points = [
        (0.0, 249.0),
        (0.0, 251.0),
        (12.0, 251.0),
        (12.0, 249.0),
        (0.0, 249.0),
        (0.0, 251.0),
    ]
    return MatchCase(
        reference_route((0.0, 0.0), (0.0, 510.0), base_latitude_deg=base_latitude_deg),
        local_trace(
            [2.0 * i for i in range(6)], points, base_latitude_deg=base_latitude_deg
        ),
    )


def half_turn() -> MatchCase:
    path = TracePath((0.0, 0.0)).to((275.0, 0.0), (0.0, 0.0), speed_ms=1.0)
    return MatchCase(
        reference_route(*HALF_TURN),
        path.trace(),
        matching_parameters(score_step_m=275.0),
    )


def _t05(first_end: int, second_start: int) -> MatchCase:
    times = [*range(first_end + 1), *range(second_start, 511)]
    return MatchCase(
        reference_route(*EAST_510), _along_x([float(t) for t in times], time_s=times)
    )


def t05() -> MatchCase:
    return _t05(100, 111)


def t05_bis() -> MatchCase:
    return _t05(245, 256)


def t05_ter() -> MatchCase:
    return _t05(245, 255)


def t07() -> MatchCase:
    return MatchCase(
        reference_route((0.0, 0.0), (270.0, 0.0)),
        _along_x([245.0 + t for t in range(28)]),
    )


def window() -> MatchCase:
    """Fenêtre : boucle de 390 m au nord à 2 m/s, un enregistrement par seconde."""
    path = TracePath((0.0, 0.0)).to(
        (260.0, 0.0),
        (260.0, 390.0),
        (490.0, 390.0),
        (490.0, 0.0),
        (1500.0, 0.0),
        speed_ms=2.0,
    )
    return MatchCase(reference_route((0.0, 0.0), (1500.0, 0.0)), path.trace())


def out_of_tolerance() -> MatchCase:
    return MatchCase(
        reference_route(*EAST_510), _along_x([float(t) for t in range(521)], y_m=40.0)
    )


def east_29(base_latitude_deg: float = 45.0) -> MatchCase:
    """À 29 m à l'est d'une référence qui monte au nord."""
    return MatchCase(
        reference_route((0.0, 0.0), (0.0, 510.0), base_latitude_deg=base_latitude_deg),
        local_trace(
            range(521),
            [(29.0, float(t)) for t in range(521)],
            base_latitude_deg=base_latitude_deg,
        ),
    )


def zigzag() -> MatchCase:
    points = [(float(t), 5 * math.sin(2 * math.pi * t / 20)) for t in range(511)]
    return MatchCase(reference_route(*EAST_510), local_trace(range(511), points))


def without_prepared() -> MatchCase:
    """La trace elle-même, en ``Route`` par ``trace_route``."""
    trace = TracePath((0.0, 0.0)).to((300.0, 0.0), (300.0, 300.0), speed_ms=1.0).trace()
    return MatchCase(trace_route(trace, "Sans préparé"), trace)


def corner() -> MatchCase:
    path = TracePath((0.0, 0.0)).to(
        (200.0, 0.0), (240.0, 50.0), (240.0, 300.0), speed_ms=1.0
    )
    return MatchCase(
        reference_route((0.0, 0.0), (240.0, 0.0), (240.0, 300.0)), path.trace()
    )


def arrival_cluster() -> MatchCase:
    """``x = t`` jusqu'à 512, puis 511, 510, 509, 508, 509, … 515, 1 m/s."""
    x_m = [*range(513), 511, 510, 509, 508, *range(509, 516)]
    return MatchCase(reference_route(*EAST_510), _along_x([float(x) for x in x_m]))


def arrival_from_ahead() -> MatchCase:
    points = [(530.0, 50.0), (510.0, 20.0), (510.0, 10.0), (510.0, 0.0)]
    return MatchCase(
        reference_route(*EAST_510), local_trace([0.0, 10.0, 20.0, 30.0], points)
    )


# ---------------------------------------------------------------------------
# Fixtures de session — règles qu'aucune ligne du § 7.2a ne distingue
# ---------------------------------------------------------------------------


def s01() -> MatchCase:
    """``π > π_cur`` strict pour ``k > 0`` : la trace part sur la ligne d'arrivée
    (``h = 0`` en ``π = 0``), à plus de ``ε`` du départ ; 5 m en 3 s."""
    return MatchCase(
        reference_route((0.0, 0.0), (40.0, 0.0)),
        _along_x([40.0, 45.0], time_s=[0.0, 3.0]),
    )


def s02() -> MatchCase:
    """Un point 1 ambigu (deux passages de ``x = 250`` séparés par un détour à 20 m),
    puis une boucle de 1 028 m avant ``x = 500``, franchi à ``d_r ≈ 1 348`` : dans la
    fenêtre de l'état inchangé (``D = 1 550``), hors de celle d'un état mis à jour
    après l'ambiguïté (``925`` avec ``k_der = 1``, ``1 223`` avec ``π_cur`` en
    plus). 2 m/s, un enregistrement toutes les 2 s."""
    path = TracePath((0.0, 0.0)).to(
        (252.0, 0.0),
        (252.0, 20.0),
        (248.0, 20.0),
        (248.0, 0.0),
        (252.0, 0.0),
        (252.0, 400.0),
        (480.0, 400.0),
        (480.0, 0.0),
        (764.0, 0.0),
        speed_ms=2.0,
        step_s=2.0,
    )
    return MatchCase(reference_route((0.0, 0.0), (760.0, 0.0)), path.trace())


def s03() -> MatchCase:
    """Départ ancrable (``h_0 = 7,5``, écart latéral 3 m) et deux événements au
    départ, séparés par un détour à 27 m : l'ancrage n'efface pas l'ambiguïté.
    1,5 m/s, un enregistrement toutes les 2 s."""
    path = TracePath((7.5, 3.0)).to(
        (-1.5, 3.0),
        (1.5, 3.0),
        (1.5, 27.0),
        (-1.5, 27.0),
        (-1.5, 3.0),
        (1.5, 3.0),
        (517.5, 3.0),
        speed_ms=1.5,
        step_s=2.0,
    )
    return MatchCase(reference_route(*EAST_510), path.trace())


# ---------------------------------------------------------------------------
# § 8, test 5 — trace qui suit une référence droite
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StraightCase:
    """Référence droite sur le parallèle de base, et trace qui la suit en ``x``
    strictement croissant ; ``time_s`` et ``x_m`` sont la description plane de la
    trace, dont l'attendu se lit sans la géographie du code."""

    case: MatchCase
    time_s: tuple[float, ...]
    x_m: tuple[float, ...]


MAX_STRAIGHT_RECORDS = 20_000
"""Plafond d'enregistrements d'une :class:`StraightCase` : 0,3 m/s à 1/64 s ferait
600 000 enregistrements sur 3 000 m."""


def straight_case(
    length_m: float,
    x0_m: float,
    y0_m: float,
    steps: Sequence[tuple[float, int]],
    slopes: Sequence[float],
) -> StraightCase:
    """Référence ``(0, 0)→(length_m, 0)``, sommets tous les 10 m ; trace partant de
    ``(x0_m, y0_m)``, jusqu'au-delà de la fin.

    ``steps`` : motif cyclé de ``(vitesse en m/s, pas en 1/64 s)`` ; ``slopes`` : motif
    cyclé de ``Δy / Δx`` dans ``[−1 ; 1]``, ``y`` borné à ``[−10 ; 10]`` m.
    """
    vertices = [(10.0 * i, 0.0) for i in range(int(length_m // 10) + 1)]
    if vertices[-1][0] < length_m:
        vertices.append((length_m, 0.0))
    t_s, x_m, y_m = 0.0, x0_m, y0_m
    times, points = [t_s], [(x_m, y_m)]
    i = 0
    while x_m <= length_m:
        speed_ms, sixty_fourths = steps[i % len(steps)]
        dt_s = sixty_fourths / 64
        dx_m = speed_ms * dt_s
        t_s += dt_s
        x_m += dx_m
        y_m = min(10.0, max(-10.0, y_m + slopes[i % len(slopes)] * dx_m))
        times.append(t_s)
        points.append((x_m, y_m))
        i += 1
    return StraightCase(
        MatchCase(reference_route(*vertices), local_trace(times, points)),
        tuple(times),
        tuple(x for x, _ in points),
    )


# ---------------------------------------------------------------------------
# § 8, test 5 — traces quelconques sur une référence en ligne brisée
# ---------------------------------------------------------------------------

Phase = tuple[str, float, float, float, float]
"""Une phase de :func:`wandering_case` :

- ``("move", Δs, écart, v, δ)`` : avance de ``Δs`` le long du tracé (``Δs < 0`` : retour
  en arrière) jusqu'à l'écart latéral donné, à ``v`` m/s, toutes les ``δ`` s ;
- ``("to", s, écart, v, δ)`` : de même jusqu'à l'abscisse plane ``s`` ;
- ``("stop", n, 0, 0, 0)`` : ``n`` enregistrements immobiles, un par seconde ;
- ``("gap", Δs, durée, 0, 0)`` : un seul enregistrement, ``Δs`` plus loin, ``durée``
  secondes après le précédent.
"""


def _along(vertices: Sequence[Point], s_m: float, offset_m: float) -> Point:
    """Point d'abscisse plane ``s`` et d'écart ``offset`` (à gauche) le long de la
    ligne brisée, prolongée au-delà de ses extrémités."""
    lengths = [math.dist(a, b) for a, b in pairwise(vertices)]
    i, start_m = 0, 0.0
    while i < len(lengths) - 1 and s_m > start_m + lengths[i]:
        start_m += lengths[i]
        i += 1
    (ax, ay), (bx, by) = vertices[i], vertices[i + 1]
    ux, uy = (bx - ax) / lengths[i], (by - ay) / lengths[i]
    along_m = s_m - start_m
    return ax + along_m * ux - offset_m * uy, ay + along_m * uy + offset_m * ux


def wandering_case(
    vertices: Sequence[Point],
    start: tuple[float, float],
    phases: Sequence[Phase],
    parameters: ParameterSet,
) -> MatchCase:
    """Trace qui erre autour d'une référence en ligne brisée : suivi avec écart,
    retours, détours, arrêts, trous. ``start`` : abscisse plane et écart latéral du
    premier enregistrement."""
    s_m, offset_m = start
    t_s = 0.0
    times, points = [t_s], [_along(vertices, s_m, offset_m)]
    features: set[str] = set()
    for kind, a, b, speed_ms, step_s in phases:
        if kind in ("move", "to"):
            delta_m = a if kind == "move" else a - s_m
            if delta_m < 0:
                features.add("backtrack")
            distance_m = abs(delta_m) + abs(b - offset_m)
            steps = max(1, round(distance_m / (speed_ms * step_s)))
            for j in range(1, steps + 1):
                u = j / steps
                t_s += step_s
                times.append(t_s)
                points.append(
                    _along(vertices, s_m + u * delta_m, offset_m + u * (b - offset_m))
                )
            s_m, offset_m = s_m + delta_m, b
        elif kind == "stop":
            features.add("stop")
            for _ in range(int(a)):
                t_s += 1.0
                times.append(t_s)
                points.append(points[-1])
        else:
            features.add("gap")
            s_m += a
            t_s += b
            times.append(t_s)
            points.append(_along(vertices, s_m, offset_m))
    return MatchCase(
        reference_route(*vertices),
        local_trace(times, points),
        parameters,
        frozenset(features),
    )


# ---------------------------------------------------------------------------
# § 8, test 6 — la paire de GPX commitée de ``mperf match``
# ---------------------------------------------------------------------------

MATCH_REFERENCE_GPX = "appariement_reference.gpx"
MATCH_TRACE_GPX = "appariement_trace_x01.gpx"


def utc_text(time_s: float) -> str:
    """Instant ``TRACE_START + time_s`` en texte ISO 8601, en UTC."""
    return (TRACE_START + timedelta(seconds=time_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


def gpx_texts(case: MatchCase, trace_times: bool = True) -> tuple[str, str]:
    """Référence et trace d'un cas en GPX, coordonnées en ``repr`` exact : la
    référence sans ``<time>``, la trace horodatée en UTC depuis ``TRACE_START``."""
    route, trace = case.route, case.trace
    reference = gpx_document(
        [
            (repr(lat), repr(lon), repr(ele), None)
            for lat, lon, ele in zip(
                route.latitude_deg, route.longitude_deg, route.elevation_m, strict=True
            )
        ]
    )
    records = gpx_document(
        [
            (repr(lat), repr(lon), repr(ele), utc_text(t) if trace_times else None)
            for t, lat, lon, ele in zip(
                trace.time_s,
                trace.latitude_deg,
                trace.longitude_deg,
                trace.elevation_m,
                strict=True,
            )
        ]
    )
    return reference, records


def x01_gpx_pair() -> tuple[str, str]:
    """La paire commitée : référence ``(0,0)→(530,0)`` sans lieu nommé, et X01
    échantillonnée toutes les 10 s (``t = 0 … 320``, 33 enregistrements)."""
    return gpx_texts(x01(step_s=10.0))


# ---------------------------------------------------------------------------
# Correctifs de la PR #9 — R1 : coordonnées en degrés, à cheval sur un méridien
# ---------------------------------------------------------------------------

GREENWICH_WEST_DEG = -0.0027181091080278373
GREENWICH_EAST_DEG = 0.007578580617976076
"""Longitudes de part et d'autre du méridien de Greenwich, à 45° N.

``b − a`` n'y est pas exact : ``a + t·(b − a)`` rend en ``t = 1`` la longitude
``0.007578580617976077``, un ulp au-delà de ``b``. Aux coordonnées de
:func:`local_deg` (6° E), la même écriture serait exacte (lemme de Sterbenz) et ne
se distinguerait pas de ``(1 − t)·a + t·b``. **Exception au § 7.0** : ces fixtures
sont écrites directement en degrés, ``local_deg`` ne franchissant pas de méridien.
"""


def degree_route(
    latitude_deg: Sequence[float], longitude_deg: Sequence[float]
) -> Route:
    """Référence plate écrite directement en degrés, sans lieu nommé."""
    return Route(
        name="Référence en degrés",
        latitude_deg=tuple(latitude_deg),
        longitude_deg=tuple(longitude_deg),
        elevation_m=(0.0,) * len(latitude_deg),
        named_points=(),
        source=REFERENCE_SOURCE,
    )


def degree_trace(
    time_s: Sequence[float],
    latitude_deg: Sequence[float],
    longitude_deg: Sequence[float],
) -> RecordedTrace:
    """Trace écrite directement en degrés, à 1 000 m d'altitude."""
    return RecordedTrace(
        start_time=TRACE_START,
        time_s=tuple(time_s),
        latitude_deg=tuple(latitude_deg),
        longitude_deg=tuple(longitude_deg),
        elevation_m=(1000.0,) * len(time_s),
        sources=(TRACE_SOURCE,),
        dropped_same_instant_count=0,
    )


def greenwich_route() -> Route:
    """R1a : deux sommets, ``(45, W)`` puis ``(45, E)``, de part et d'autre de
    Greenwich."""
    return degree_route((45.0, 45.0), (GREENWICH_WEST_DEG, GREENWICH_EAST_DEG))


def greenwich_arrival() -> MatchCase:
    """R1d : 401 enregistrements toutes les 2 s sur la référence de R1a, longitudes
    ``(1 − j/400)·W + (j/400)·E`` pour ``j < 400``, puis ``E`` exactement : la trace
    finit sur le dernier sommet, bit pour bit."""
    west, east = GREENWICH_WEST_DEG, GREENWICH_EAST_DEG
    longitudes = [(1 - j / 400) * west + (j / 400) * east for j in range(400)]
    return MatchCase(
        greenwich_route(),
        degree_trace([2.0 * j for j in range(401)], [45.0] * 401, [*longitudes, east]),
    )


# ---------------------------------------------------------------------------
# Correctifs de la PR #9 — R2 à R5 et R7
# ---------------------------------------------------------------------------


def outer_elbow() -> MatchCase:
    """R2, Coude extérieur : référence de X08 ; le premier enregistrement, en
    ``(24, −3)``, est à l'extérieur du coude et se projette sur le sommet ``(20, 0)``,
    à 5 m (candidat « sommet » de ``project_restricted``). 148 enregistrements."""
    path = TracePath((24.0, -3.0)).to((22.0, 5.0), (22.0, 291.0), speed_ms=2.0)
    return MatchCase(
        reference_route((0.0, 0.0), (20.0, 0.0), (20.0, 300.0)), path.trace()
    )
