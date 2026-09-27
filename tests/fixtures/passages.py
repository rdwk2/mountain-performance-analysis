"""Fixtures synthétiques des passages (M4a-3) — plan à 45° N, valeurs inventées.

Convention du § 7.0 du brief M4a-3 : références et traces décrites en mètres
``(x, y)``, converties par :func:`fixtures.traces.local_deg` ; références par
:func:`fixtures.segments.named_route` (plates, lieux nommés en ``local_deg``) ; chemins
par :class:`fixtures.matching.TracePath` et :func:`fixtures.segments.stay`, traces
par formule par :func:`fixtures.matching.local_trace`, positions calculées rang par
rang, dans l'ordre d'opérations du brief. Ces constructions ne se simplifient pas :
une autre construction des mêmes chemins peut déplacer un enregistrement de quelques
``1e−13`` m et changer un résultat près d'une ligne.

- le repère direct du § 7.3.2 et ses traces à 1 Hz, pour ``crossing_candidates``
  borné et ``occurrence_crossing`` ;
- un constructeur par ligne du tableau du § 7.3.1, et :func:`observed_passages`, qui
  les passe par ``match_trace`` puis ``observe_passages``.

Utilisées par ``tests/test_backtest_crossing_bound.py``,
``tests/test_backtest_passage_rules.py``, ``tests/test_backtest_passages.py``,
``tests/test_backtest_passages_properties.py`` et
``tests/test_cli_match_passages.py``.
"""

from collections.abc import Sequence
from dataclasses import replace

from fixtures import segments
from fixtures.matching import MatchCase, Point, TracePath, local_trace
from fixtures.segments import named_route, reference_profile, stay
from fixtures.traces import local_deg
from mountain_perf.backtest import (
    build_series,
    clock_partition,
    match_trace,
    observe_passages,
)
from mountain_perf.backtest.geometry import LocalFrame
from mountain_perf.schemas import MatchResult, PassageMatchResult, RecordedTrace

_ANCHOR = local_deg(0.0, 0.0)

DIRECT_FRAME = LocalFrame(
    anchor_lat_deg=_ANCHOR[0],
    anchor_lon_deg=_ANCHOR[1],
    tangent=(1.0, 0.0),
    normal=(-0.0, 1.0),
)
"""Repère direct du § 7.3.2 : ancre ``local_deg(0, 0)``, tangente ``(1, 0)``,
normale ``(−0,0 ; 1)`` ; ``h = x`` et l'écart latéral ``= y`` dans le plan de
l'ancre. Un enregistrement en ``x = 0`` a exactement les flottants de l'ancre
(``h = 0``) ; ``x = −1`` et ``x = 1`` ont des ``h`` opposés au bit près."""


def direct_trace(
    x_m: Sequence[float],
    y_m: float = 0.0,
    time_s: Sequence[float] | None = None,
) -> RecordedTrace:
    """Trace ``local_trace`` sur l'axe du repère direct : positions ``(x, y)``,
    instants ``0, 1, 2, …`` sauf mention."""
    times = list(time_s) if time_s is not None else [float(t) for t in range(len(x_m))]
    return local_trace(times, [(x, y_m) for x in x_m])


def observed_passages(case: MatchCase) -> tuple[MatchResult, PassageMatchResult]:
    """``match_trace`` puis ``observe_passages`` sur un cas : profil aux défauts de
    ``0008``, séries et partition construites sur sa trace."""
    series = build_series(case.trace)
    partition = clock_partition(case.trace, series)
    geometry, profile = case.geometry, reference_profile(case)
    match = match_trace(
        geometry, profile, case.trace, series, partition, case.parameters
    )
    return match, observe_passages(
        match, geometry, profile, case.trace, series, partition
    )


# ---------------------------------------------------------------------------
# § 7.3.1 — une fonction par ligne du tableau
# ---------------------------------------------------------------------------

EAST = ((0.0, 0.0), (1010.0, 0.0))
"""``EST`` : ``(0,0)→(1010,0)``, de longueur ``L = 1009,999999``."""

Place = tuple[str, Point]


def _east(places: Sequence[Place], path: TracePath) -> MatchCase:
    return MatchCase(named_route(EAST, places), path.trace())


def passages() -> MatchCase:
    """Passages : A (375 ; 5), B (250,4 ; 0), C (900 ; 0) ; ``t = 0 … 1135`` :
    ``x = t`` (``t <= 380``), ``380`` (``380 < t <= 500``), ``t − 120`` ensuite ;
    ``y = 40 − |x − 875|·40/75`` si ``t > 500`` et ``800 < x < 950``, 0 sinon."""
    points: list[Point] = []
    for t in range(1136):
        x_m = float(t) if t <= 380 else 380.0 if t <= 500 else float(t - 120)
        y_m = 40 - abs(x_m - 875) * 40 / 75 if t > 500 and 800 < x_m < 950 else 0.0
        points.append((x_m, y_m))
    return MatchCase(
        named_route(
            EAST, (("A", (375.0, 5.0)), ("B", (250.4, 0.0)), ("C", (900.0, 0.0)))
        ),
        local_trace(range(1136), points),
    )


def y01() -> MatchCase:
    """Y01 : w (240 ; 0) ; ``t = 0 … 1799`` : ``x = t`` (``t <= 220``),
    ``220 + 0,05·(t − 220)`` (``t <= 1020``), ``260 + (t − 1020)`` ensuite ;
    ``y = 60 − |x − 375|·60/75`` pour ``300 < x < 450``, 0 sinon ; altitude
    ``1000 + 0,06·x``, posée sur les positions de ``local_trace``."""
    points: list[Point] = []
    for t in range(1800):
        if t <= 220:
            x_m = float(t)
        elif t <= 1020:
            x_m = 220 + 0.05 * (t - 220)
        else:
            x_m = 260 + (t - 1020)
        y_m = 60 - abs(x_m - 375) * 60 / 75 if 300 < x_m < 450 else 0.0
        points.append((x_m, y_m))
    trace = local_trace(range(1800), points)
    trace = replace(trace, elevation_m=tuple(1000 + 0.06 * x_m for x_m, _ in points))
    return MatchCase(named_route(EAST, (("w", (240.0, 0.0)),)), trace)


def m05() -> MatchCase:
    """M05 : Fin (1010 ; 3), Départ (0 ; 2), Borne (250,3 ; 0), Borne bis
    (249,8 ; 0), À 1,5 m (251,5 ; 0) ; ``(0,0)→(1015,0)`` à 1 m/s."""
    places = (
        ("Fin", (1010.0, 3.0)),
        ("Départ", (0.0, 2.0)),
        ("Borne", (250.3, 0.0)),
        ("Borne bis", (249.8, 0.0)),
        ("À 1,5 m", (251.5, 0.0)),
    )
    return _east(places, TracePath((0.0, 0.0)).to((1015.0, 0.0), speed_ms=1.0))


def m05_anchored() -> MatchCase:
    """M05 ancré : Départ (0 ; 2), Avant (8 ; 3), Juste après (12,7 ; 3), Presque
    (1005 ; 0), Fin (1010 ; 3) ; ``(12,0)→(1004,0)`` à 1 m/s."""
    places = (
        ("Départ", (0.0, 2.0)),
        ("Avant", (8.0, 3.0)),
        ("Juste après", (12.7, 3.0)),
        ("Presque", (1005.0, 0.0)),
        ("Fin", (1010.0, 3.0)),
    )
    return _east(places, TracePath((12.0, 0.0)).to((1004.0, 0.0), speed_ms=1.0))


def cut_corner() -> MatchCase:
    """Coin coupé : ``(0,0)→(766,0)→(506,150)``, épingle d'environ 150° ; W
    (766 ; 0) ; ``(0,0)→(753,0)→(753,8)→(747 ; 11,5)→(750 ; 9,8)→(506,150)`` à
    1 m/s."""
    path = TracePath((0.0, 0.0)).to(
        (753.0, 0.0),
        (753.0, 8.0),
        (747.0, 11.5),
        (750.0, 9.8),
        (506.0, 150.0),
        speed_ms=1.0,
    )
    route = named_route(
        ((0.0, 0.0), (766.0, 0.0), (506.0, 150.0)), (("W", (766.0, 0.0)),)
    )
    return MatchCase(route, path.trace())


def out_of_tolerance() -> MatchCase:
    """Hors ε : H (375,5 ; 0) ; ``t = 0 … 1015`` : ``x = t``, ``y = 45`` pour
    ``t = 375`` et ``376``, 0 sinon."""
    points = [(float(t), 45.0 if t in (375, 376) else 0.0) for t in range(1016)]
    return MatchCase(
        named_route(EAST, (("H", (375.5, 0.0)),)), local_trace(range(1016), points)
    )


def switchback() -> MatchCase:
    """Lacet : L (375,5 ; 0) ; ``(0,0)→(380,0)→(363,0)→(1015,0)`` à 1 m/s."""
    path = TracePath((0.0, 0.0)).to(
        (380.0, 0.0), (363.0, 0.0), (1015.0, 0.0), speed_ms=1.0
    )
    return _east((("L", (375.5, 0.0)),), path)


def wide_switchback() -> MatchCase:
    """Lacet large : L (375,5 ; 0) ; ``(0,0)→(380,0)→(350,0)→(1015,0)`` à 1 m/s."""
    path = TracePath((0.0, 0.0)).to(
        (380.0, 0.0), (350.0, 0.0), (1015.0, 0.0), speed_ms=1.0
    )
    return _east((("L", (375.5, 0.0)),), path)


def _stop_at(x_m: float, count: int, then_ms: float = 1.0) -> TracePath:
    """``(0,0)→(x,0)`` à 1 m/s, ``stay`` ``count``, ``→(1015,0)`` à ``then_ms``."""
    path = stay(TracePath((0.0, 0.0)).to((x_m, 0.0), speed_ms=1.0), count)
    return path.to((1015.0, 0.0), speed_ms=then_ms)


def tie() -> MatchCase:
    """Égalité : E1 (370,3 ; 0), E2 (389,7 ; 12) ; ``(0,0)→(380,0)`` à 1 m/s,
    ``stay`` 120, ``→(1015,0)`` à 1 m/s."""
    places = (("E1", (370.3, 0.0)), ("E2", (389.7, 12.0)))
    return _east(places, _stop_at(380.0, 120))


def tie_by_space() -> MatchCase:
    """Égalité, espace : E1 (372,5 ; 0), E2 (391,5 ; 0) ; ``(0,0)→(380,0)`` à 1 m/s,
    ``stay`` 120, ``→(1015,0)`` à **2** m/s."""
    places = (("E1", (372.5, 0.0)), ("E2", (391.5, 0.0)))
    return _east(places, _stop_at(380.0, 120, then_ms=2.0))


def window() -> MatchCase:
    """Fenêtre : Y (495 ; 0), X (525 ; 0) ; ``(0,0)→(503,0)`` à 1 m/s, ``stay`` 120,
    ``→(1015,0)`` à 1 m/s."""
    places = (("Y", (495.0, 0.0)), ("X", (525.0, 0.0)))
    return _east(places, _stop_at(503.0, 120))


def chronology() -> MatchCase:
    """Chronologie : W1 (375,5 ; 0), W2 (378,5 ; 0) ; ``(0,0)→(375,0)`` à 1 m/s ;
    ``→(376,5 ; 0)`` à 0,01 m/s ; ``→(380,1 ; 0)`` à 0,04 m/s ; ``→(1015,0)`` à
    1 m/s."""
    path = (
        TracePath((0.0, 0.0))
        .to((375.0, 0.0), speed_ms=1.0)
        .to((376.5, 0.0), speed_ms=0.01)
        .to((380.1, 0.0), speed_ms=0.04)
        .to((1015.0, 0.0), speed_ms=1.0)
    )
    return _east((("W1", (375.5, 0.0)), ("W2", (378.5, 0.0))), path)


def final_chronology() -> MatchCase:
    """Chronologie finale : F (1004,5 ; 0) ; ``(0,0)→(1003,0)`` à 1 m/s ;
    ``→(1012,0)`` à 0,05 m/s."""
    path = (
        TracePath((0.0, 0.0))
        .to((1003.0, 0.0), speed_ms=1.0)
        .to((1012.0, 0.0), speed_ms=0.05)
    )
    return _east((("F", (1004.5, 0.0)),), path)


def out_and_back() -> MatchCase:
    """Aller-retour : ``(0,0)→(620,0)→(0,0)`` ; T (620 ; 0), M (300 ; 3), résolu
    deux fois ; ``(0,0)→(620,0)→(305,0)`` à 1 m/s, ``stay`` 120, ``→(0,0)`` à
    1 m/s."""
    path = stay(
        TracePath((0.0, 0.0)).to((620.0, 0.0), (305.0, 0.0), speed_ms=1.0), 120
    ).to((0.0, 0.0), speed_ms=1.0)
    route = named_route(
        ((0.0, 0.0), (620.0, 0.0), (0.0, 0.0)),
        (("T", (620.0, 0.0)), ("M", (300.0, 3.0))),
    )
    return MatchCase(route, path.trace())


def resume_at_m() -> MatchCase:
    """Reprise en m : R (499,5 ; 0), R+ (500,8 ; 0) ; ``(0,0)→(505,0)`` à 1 m/s,
    ``stay`` 120, ``→(550,0)→(625,40)→(700,0)→(1015,0)`` à 1 m/s."""
    path = stay(TracePath((0.0, 0.0)).to((505.0, 0.0), speed_ms=1.0), 120).to(
        (550.0, 0.0), (625.0, 40.0), (700.0, 0.0), (1015.0, 0.0), speed_ms=1.0
    )
    return _east((("R", (499.5, 0.0)), ("R+", (500.8, 0.0))), path)


def resume_at_m_off_route() -> MatchCase:
    """Reprise en m, hors tracé : R (499,5 ; 0) ; ``(0,0)→(505,0)`` à 1 m/s,
    ``stay`` 120, ``→(505,200)`` à 1 m/s."""
    path = stay(TracePath((0.0, 0.0)).to((505.0, 0.0), speed_ms=1.0), 120).to(
        (505.0, 200.0), speed_ms=1.0
    )
    return _east((("R", (499.5, 0.0)),), path)


def passages_m4a2b() -> MatchCase:
    """Passages (M4a-2b) : la fixture ``passages()`` de M4a-2b, telle quelle."""
    return segments.passages()


def return_crossing() -> MatchCase:
    """Retour : W (375,5 ; 0) ; ``(0,0)→(520,0)→(520,40)→(390,40)→(390,5)→(370,5)
    →(385,5)→(385,40)→(600,40)→(600,0)→(1015,0)`` à 1 m/s."""
    path = TracePath((0.0, 0.0)).to(
        (520.0, 0.0),
        (520.0, 40.0),
        (390.0, 40.0),
        (390.0, 5.0),
        (370.0, 5.0),
        (385.0, 5.0),
        (385.0, 40.0),
        (600.0, 40.0),
        (600.0, 0.0),
        (1015.0, 0.0),
        speed_ms=1.0,
    )
    return _east((("W", (375.5, 0.0)),), path)


def stop_at_arrival() -> MatchCase:
    """Arrêt à l'arrivée : Fin (1010 ; 3) ; ``(0,0)→(1012,0)`` à 1 m/s,
    ``stay`` 120."""
    path = stay(TracePath((0.0, 0.0)).to((1012.0, 0.0), speed_ms=1.0), 120)
    return _east((("Fin", (1010.0, 3.0)),), path)


def two_stops() -> MatchCase:
    """Deux arrêts : A (375,5 ; 0) ; ``(0,0)→(380,0)`` à 1 m/s, ``stay`` 100,
    ``→(395,0)→(380,0)`` à 1 m/s, ``stay`` 100, ``→(1015,0)`` à 1 m/s."""
    path = stay(TracePath((0.0, 0.0)).to((380.0, 0.0), speed_ms=1.0), 100)
    path = stay(path.to((395.0, 0.0), (380.0, 0.0), speed_ms=1.0), 100)
    return _east((("A", (375.5, 0.0)),), path.to((1015.0, 0.0), speed_ms=1.0))


def departure_in_stop() -> MatchCase:
    """Départ dans l'arrêt : Départ (0 ; 2), P (3,5 ; 0) ; ``(−1,0)→(4,0)`` à
    0,04 m/s ; ``→(1015,0)`` à 1 m/s."""
    path = (
        TracePath((-1.0, 0.0))
        .to((4.0, 0.0), speed_ms=0.04)
        .to((1015.0, 0.0), speed_ms=1.0)
    )
    return _east((("Départ", (0.0, 2.0)), ("P", (3.5, 0.0))), path)


def stop_at_35_m() -> MatchCase:
    """Arrêt à 35 m : Z (345 ; 0) ; ``(0,0)→(380,0)`` à 1 m/s, ``stay`` 120,
    ``→(1015,0)`` à 1 m/s."""
    return _east((("Z", (345.0, 0.0)),), _stop_at(380.0, 120))


def final_outside_prefix() -> MatchCase:
    """Final hors préfixe : F (999,5 ; 0), Fin (1010 ; 3) ; ``(0,0)→(997,5 ; 0)`` à
    1 m/s ; puis zigzag à 0,05 m/s par les sommets
    ``(997,5 + j ; 3 si j impair, 0 sinon)``, ``j = 1 … 15``."""
    zigzag = [(997.5 + j, 3.0 if j % 2 else 0.0) for j in range(1, 16)]
    path = (
        TracePath((0.0, 0.0)).to((997.5, 0.0), speed_ms=1.0).to(*zigzag, speed_ms=0.05)
    )
    return _east((("F", (999.5, 0.0)), ("Fin", (1010.0, 3.0))), path)


def undated_departure() -> MatchCase:
    """Départ non daté : Départ (0 ; 2), Q (100 ; 0) ;
    ``(40,0)→(200,0)→(200,200)`` à 1 m/s."""
    path = TracePath((40.0, 0.0)).to((200.0, 0.0), (200.0, 200.0), speed_ms=1.0)
    return _east((("Départ", (0.0, 2.0)), ("Q", (100.0, 0.0))), path)


def resume_next_out_of_tolerance() -> MatchCase:
    """Reprise en m, point m + 1 hors ε : R (499,5 ; 0) ;
    ``(0,0)→(520,0)→(520,100)→(800,100)→(800,0)→(1015,0)→(505,0)`` à 1 m/s,
    ``stay`` 120."""
    path = TracePath((0.0, 0.0)).to(
        (520.0, 0.0),
        (520.0, 100.0),
        (800.0, 100.0),
        (800.0, 0.0),
        (1015.0, 0.0),
        (505.0, 0.0),
        speed_ms=1.0,
    )
    return _east((("R", (499.5, 0.0)),), stay(path, 120))


def two_resumes() -> MatchCase:
    """Deux reprises : Borne bis (249,1 ; 0), Borne (250,9 ; 0) ;
    ``(0,0)→(252,0)`` à 1 m/s, ``stay`` 120, ``→(1015,0)`` à 1 m/s."""
    places = (("Borne bis", (249.1, 0.0)), ("Borne", (250.9, 0.0)))
    return _east(places, _stop_at(252.0, 120))
