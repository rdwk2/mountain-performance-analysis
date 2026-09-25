"""Segments de score, cas du § 7.2b du brief M4a-2b (``0010`` D4.2, D4.9, D4.10, D6).

Un test par ligne du tableau (33 lignes, paramétré par le nom de la ligne) : bornes
effectives, motif, classe, fractions (``0 / 1 / 0`` ou la pureté d'un régime quand la
ligne n'en donne pas), ``rho``, ``H_1``, ``H_2`` quand ils sont publiés, instants
quand la ligne les donne, à ``1e−6`` ; statuts des points pour les lignes neuves (ceux
des lignes de M4a-2a le sont déjà). Puis la correspondance des statuts (§ 8, test 5)
et les tests directs du chemin réalisé et du contrôle intérieur.
"""

from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise

import pytest

from fixtures import matching as m
from fixtures import segments as s
from fixtures.matching import MatchCase, local_trace, reference
from mountain_perf.backtest import (
    build_series,
    interior_deviations,
    realized_length_m,
    realized_path,
)
from mountain_perf.backtest.geometry import to_local
from mountain_perf.backtest.segments import _segment_distance_m
from mountain_perf.schemas import (
    PointStatus,
    RegimeClass,
    ScoreSegmentObservation,
    SegmentExclusion,
)

TOLERANCE = 1e-6
"""§ 7.0 : ``1e−6`` sur toutes les valeurs publiées."""

FOUND = PointStatus.FOUND
ANCHORED = PointStatus.ANCHORED
ABSENT = PointStatus.ABSENT
UNOBSERVED = SegmentExclusion.UNOBSERVED_BOUND
GAP = SegmentExclusion.GAP
RATIO = SegmentExclusion.LENGTH_RATIO
INTERIOR = SegmentExclusion.INTERIOR_DEVIATION
FLAT = RegimeClass.FLAT
DESCENT = RegimeClass.DESCENT
MIXED = RegimeClass.MIXED

PURE_FRACTIONS = {
    RegimeClass.ASCENT: (1.0, 0.0, 0.0),
    RegimeClass.FLAT: (0.0, 1.0, 0.0),
    RegimeClass.DESCENT: (0.0, 0.0, 1.0),
}


@dataclass(frozen=True)
class Seg:
    """Un segment attendu : ``[b_k ; b_{k+1}]``, motif (``None`` = admis), classe,
    fractions (``None`` : celles de la classe pure), ``(rho, H_1, H_2)`` quand ils
    sont publiés, instants ``t*_k → t*_{k+1}`` quand la ligne les donne."""

    start_m: float
    end_m: float
    exclusion: SegmentExclusion | None = None
    controls: tuple[float, float, float] | None = None
    times: tuple[float, float] | None = None
    regime_class: RegimeClass = FLAT
    fractions: tuple[float, float, float] | None = None


def ok(
    start_m: float,
    end_m: float,
    controls: tuple[float, float, float] = (1.0, 0.0, 0.0),
    times: tuple[float, float] | None = None,
    *,
    regime_class: RegimeClass = FLAT,
    fractions: tuple[float, float, float] | None = None,
) -> Seg:
    """Segment admis ; ``rho = 1``, ``H_1 = H_2 = 0`` par défaut."""
    return Seg(start_m, end_m, None, controls, times, regime_class, fractions)


def unobserved(start_m: float, end_m: float) -> Seg:
    return Seg(start_m, end_m, UNOBSERVED)


@dataclass(frozen=True)
class Row:
    """Une ligne du § 7.2b : son cas, ses segments, et les statuts de ses points quand
    la ligne est neuve."""

    case: Callable[[], MatchCase]
    segments: tuple[Seg, ...]
    statuses: tuple[PointStatus, ...] | None = None


FOUR_FOUND = (FOUND,) * 4
BOTH_ANCHORED = (ANCHORED, FOUND, FOUND, ANCHORED)
SIX_REGIMES = (ANCHORED, FOUND, FOUND, FOUND, FOUND, ANCHORED)
PASSAGE_STATUSES = (ANCHORED, FOUND, FOUND, ABSENT, ABSENT, ABSENT)
LIMIT = 1009.999999
"""Fin du tracé de Passages à ``1e−6`` (``L = 1009,999998942``)."""

ROWS: dict[str, Row] = {
    "T01": Row(m.t01, (ok(0, 250), ok(250, 500), ok(500, 520))),
    "T01-bis": Row(m.t01_bis, (ok(0, 250), ok(250, 500), ok(500, 520))),
    "X01": Row(
        m.x01,
        (
            ok(25, 250, (1.000425, 7.86875, 7.996599)),
            ok(250, 500, (1.000426, 5.825, 5.851678)),
            ok(500, 505, (1.000426, 5.86875, 5.99745)),
        ),
    ),
    "X01 à 10 s": Row(
        lambda: m.x01(step_s=10.0),
        (
            ok(25, 250, (1.000425, 7.34375, 7.996599)),
            ok(250, 500, (1.000426, 5.34375, 5.851678)),
            ok(500, 505, (1.000426, 0.0, 5.99745)),
        ),
    ),
    "X08 coude": Row(
        m.x08_elbow,
        (
            ok(25, 250, (1.0, 1.999998, 1.999998)),
            ok(250, 311, (1.0, 1.999928, 1.999928)),
        ),
    ),
    "X09 départ rejeté": Row(m.x09, (unobserved(0, 250), ok(250, 325))),
    "X12 K = 1 à rebours": Row(m.x12, (unobserved(25, 40),)),
    "Demi-tour": Row(m.half_turn, (unobserved(0, 275), unobserved(275, 550))),
    "T05": Row(m.t05, (Seg(0, 250, GAP), ok(250, 500), ok(500, 510))),
    "T05-ter": Row(m.t05_ter, (ok(0, 250), ok(250, 500), ok(500, 510))),
    "T07": Row(m.t07, (unobserved(0, 250), ok(250, 270))),
    "Fenêtre": Row(
        m.window,
        (
            ok(0, 250),
            unobserved(250, 500),
            unobserved(500, 750),
            ok(750, 1000),
            ok(1000, 1250),
            ok(1250, 1499.999997),
        ),
    ),
    "Hors ε": Row(
        m.out_of_tolerance,
        (unobserved(0, 250), unobserved(250, 500), unobserved(500, 510)),
    ),
    "À 29 m à l'est": Row(
        m.east_29,
        (
            ok(0, 250, (1.0, 29.0, 29.0)),
            ok(250, 500, (1.0, 28.998862, 28.998862)),
            ok(500, 510, (1.0, 28.997724, 28.997724)),
        ),
    ),
    "Sans préparé": Row(
        m.without_prepared,
        (ok(0, 250), ok(250, 500, (0.996366, 0.6, 0.848528)), ok(500, 600)),
    ),
    "Coin": Row(
        m.corner,
        (
            Seg(0, 250, INTERIOR, (0.902287, 19.53125, 31.234752)),
            ok(250, 500, (0.991867, 22.017393, 24.987778)),
            ok(500, 540),
        ),
    ),
    "Régimes": Row(
        s.regimes,
        (
            ok(
                20,
                250,
                (1.000025, 2.967988, 2.999924),
                (0.0, 153.177665),
                regime_class=MIXED,
                fractions=(0.782609, 0.217391, 0.0),
            ),
            ok(
                250,
                500,
                (1.000025, 1.356707, 1.365448),
                (153.177665, 319.675127),
                fractions=(0.0, 0.8, 0.2),
            ),
            ok(
                500,
                750,
                (1.000025, 2.185976, 2.187762),
                (319.675127, 486.172589),
                regime_class=DESCENT,
            ),
            ok(
                750,
                1000,
                (1.000026, 3.957317, 3.964367),
                (486.172589, 652.670051),
                regime_class=DESCENT,
            ),
            ok(
                1000,
                1005,
                (1.000026, 3.967988, 3.999899),
                (652.670051, 656.0),
                regime_class=DESCENT,
            ),
        ),
        SIX_REGIMES,
    ),
    "Régimes-écart": Row(
        s.regimes_deviation,
        (
            ok(
                20,
                250,
                (1.0, 3.0, 3.0),
                (0.0, 152.785714),
                regime_class=MIXED,
                fractions=(0.782609, 0.217391, 0.0),
            ),
            Seg(
                250,
                500,
                INTERIOR,
                (1.056856, 36.5, 32.320532),
                (152.785714, 331.333333),
                fractions=(0.0, 0.8, 0.2),
            ),
            ok(
                500,
                750,
                (1.000079, 2.356757, 2.369181),
                (331.333333, 498.0),
                regime_class=DESCENT,
            ),
            ok(
                750,
                1000,
                (1.00008, 3.924324, 3.936624),
                (498.0, 664.666667),
                regime_class=DESCENT,
            ),
            ok(
                1000,
                1005,
                (1.00008, 3.943243, 3.999682),
                (664.666667, 668.0),
                regime_class=DESCENT,
            ),
        ),
        SIX_REGIMES,
    ),
    "Départ ancré puis trou": Row(
        s.anchored_departure_then_gap,
        (
            Seg(12, 250, GAP, times=(0.0, 161.666667)),
            ok(250, 500, (1.0, 3.0, 3.0), (161.666667, 328.333333)),
            ok(500, 507, (1.0, 3.0, 3.0), (328.333333, 333.0)),
        ),
        BOTH_ANCHORED,
    ),
    "Arrivée avant un trou": Row(
        s.arrival_before_a_gap,
        (
            ok(0, 250, times=(0.0, 166.666667)),
            ok(250, 500, times=(166.666667, 333.333333)),
            ok(500, 510, times=(333.333333, 340.0)),
        ),
        FOUR_FOUND,
    ),
    "rho haut": Row(
        s.high_ratio,
        (
            Seg(0, 250, RATIO, (2.555927, 9.620566, 3.850217), (0.0, 500.0)),
            Seg(250, 500, RATIO, (2.540516, 9.620566, 5.086272), (500.0, 1000.0)),
            Seg(500, 510, RATIO, (2.715201, 9.620566, 1.443831), (1000.0, 1020.0)),
        ),
        FOUR_FOUND,
    ),
    "rho et écart": Row(
        s.ratio_and_deviation,
        (
            Seg(0, 250, RATIO, (2.060944, 35.948857, 18.750881), (0.0, 500.0)),
            Seg(250, 500, RATIO, (2.060944, 35.948857, 18.750881), (500.0, 1000.0)),
            Seg(500, 510, RATIO, (2.660804, 23.603507, 9.380115), (1000.0, 1020.0)),
        ),
        FOUR_FOUND,
    ),
    "rho bas": Row(
        s.low_ratio,
        (
            ok(0, 250, times=(0.0, 125.0)),
            Seg(250, 500, RATIO, (0.52, 0.0, 60.0), (125.0, 190.0)),
            ok(500, 730, times=(190.0, 305.0)),
        ),
        FOUR_FOUND,
    ),
    "Zigzag est-ouest": Row(
        s.east_west_zigzag,
        (
            ok(0, 250, (1.478739, 4.324436, 3.350174), (0.4, 200.4)),
            ok(250, 500, (1.471925, 4.324266, 4.148081), (200.4, 400.4)),
            ok(500, 510, (1.553828, 4.324097, 1.264866), (400.4, 408.4)),
        ),
        FOUR_FOUND,
    ),
    "Bosse à l'est": Row(
        s.east_bump,
        (
            ok(25, 250, (1.030962, 22.771339, 21.375905), (0.0, 156.0)),
            ok(250, 500, (1.000126, 2.904648, 2.920152), (156.0, 322.666667)),
            ok(500, 505, (1.000126, 2.928342, 2.999387), (322.666667, 326.0)),
        ),
        BOTH_ANCHORED,
    ),
    "Pointe du tracé": Row(
        s.reference_spike,
        (
            ok(0, 250, times=(0.0, 125.0)),
            Seg(250, 500, INTERIOR, (0.780894, 3.952048, 32.0), (125.0, 222.611732)),
            ok(500, 614.776535, times=(222.611732, 280.0)),
        ),
        FOUR_FOUND,
    ),
    "Écart de la trace": Row(
        s.trace_spur,
        (
            Seg(0, 250, INTERIOR, (1.242656, 31.476923, 1.06885), (0.0, 252.0)),
            ok(250, 500, times=(252.0, 452.0)),
            ok(500, 510, times=(452.0, 460.0)),
        ),
        FOUR_FOUND,
    ),
    "Dépassement": Row(
        s.overshoot,
        (
            ok(0, 250, (1.100376, 12.0, 4.788521), (0.0, 192.0)),
            ok(250, 500, (1.012959, 11.6, 11.884859), (192.0, 361.959184)),
            ok(500, 510, times=(361.959184, 368.653061)),
        ),
        FOUR_FOUND,
    ),
    "Arrêt hors support": Row(
        s.stop_off_support,
        (
            Seg(0, 250, INTERIOR, (1.155965, 40.0, 24.0), (0.0, 342.706897)),
            ok(250, 500, times=(342.706897, 509.517242)),
            ok(500, 750, times=(509.517242, 676.327587)),
            ok(750, 760, times=(676.327587, 683.0)),
        ),
        (FOUND,) * 5,
    ),
    "Arrêt": Row(
        s.stop,
        (
            ok(0, 250, times=(0.0, 276.721312)),
            ok(250, 500, times=(276.721312, 443.52459)),
            ok(500, 750, times=(443.52459, 610.327869)),
            ok(750, 760, times=(610.327869, 617.0)),
        ),
        (FOUND,) * 5,
    ),
    "Deux arrêts": Row(
        s.two_stops,
        (
            ok(0, 100, times=(0.0, 66.666667)),
            ok(100, 200, times=(66.666667, 243.333333)),
            ok(200, 300, times=(243.333333, 310.0)),
            ok(300, 400, times=(310.0, 376.666667)),
            ok(400, 500, times=(376.666667, 586.377296)),
            ok(500, 600, times=(586.377296, 653.155259)),
            ok(600, 700, times=(653.155259, 719.933222)),
            ok(700, 760, times=(719.933222, 760.0)),
        ),
        (FOUND,) * 9,
    ),
    "Passages": Row(
        s.passages,
        (
            ok(12, 250, (1.0, 2.0, 2.0), (0.0, 158.666667)),
            ok(250, 500, (1.0, 2.0, 2.0), (158.666667, 325.333334)),
            unobserved(500, 750),
            unobserved(750, 1000),
            unobserved(1000, LIMIT),
        ),
        PASSAGE_STATUSES,
    ),
    "Passages, départ exclu": Row(
        s.passages_departure_excluded,
        (
            Seg(12, 250, INTERIOR, (1.131879, 37.15, 23.216006), (0.0, 182.136364)),
            ok(250, 500, (1.0, 2.0, 2.0), (182.136364, 349.181819)),
            unobserved(500, 750),
            unobserved(750, 1000),
            unobserved(1000, LIMIT),
        ),
        PASSAGE_STATUSES,
    ),
}


def test_the_table_has_thirty_three_rows() -> None:
    """§ 7.2b : trente-trois lignes."""
    assert len(ROWS) == 33


def _expect(segment: ScoreSegmentObservation, expected: Seg) -> None:
    assert segment.start_m == pytest.approx(expected.start_m, abs=TOLERANCE)
    assert segment.end_m == pytest.approx(expected.end_m, abs=TOLERANCE)
    assert segment.exclusion is expected.exclusion
    assert segment.regime_class is expected.regime_class
    fractions = expected.fractions or PURE_FRACTIONS[expected.regime_class]
    observed = (
        segment.ascent_fraction,
        segment.flat_fraction,
        segment.descent_fraction,
    )
    assert observed == pytest.approx(fractions, abs=TOLERANCE)
    controls = (segment.length_ratio, segment.h1_m, segment.h2_m)
    if expected.controls is None:
        assert controls == (None, None, None)
    else:
        assert controls == pytest.approx(expected.controls, abs=TOLERANCE)
    if expected.times is not None:
        times = (segment.start_s, segment.end_s)
        assert times == pytest.approx(expected.times, abs=TOLERANCE)


@pytest.mark.parametrize("name", list(ROWS))
def test_segments_of_the_row(name: str) -> None:
    """§ 7.2b, une ligne : ``0010`` D4.2 (bornes effectives), D6 (fractions et classe),
    D4.9 et D4.10 (motif, ``rho``, ``H_1``, ``H_2``)."""
    row = ROWS[name]
    points, segments = s.observed(row.case())
    if row.statuses is not None:
        assert tuple(p.status for p in points) == row.statuses
    assert len(segments) == len(row.segments)
    for segment, expected in zip(segments, row.segments, strict=True):
        _expect(segment, expected)


@pytest.mark.parametrize("name", list(ROWS))
def test_unobserved_bound_is_an_undated_bound(name: str) -> None:
    """§ 8, test 5 : chaque segment ``unobserved_bound`` a une borne non datée, et
    chaque segment dont une borne n'est pas datée est ``unobserved_bound``."""
    points, segments = s.observed(ROWS[name].case())
    for segment, (start, end) in zip(segments, pairwise(points), strict=True):
        undated = not (start.dated and end.dated)
        assert (segment.exclusion is UNOBSERVED) == undated


# ---------------------------------------------------------------------------
# Chemin réalisé (§ 5b.5 ; 0010 D4.10, point 3)
# ---------------------------------------------------------------------------


MOVING_X_M = (0.0, 3.0, 6.0, 9.0, 12.0, 22.0)
"""Six enregistrements vers l'est sur le parallèle de base, toutes les 2 s. Positions
lissées (moyenne centrée tronquée au bord du bloc) : 3 ; 4,5 ; 6 ; 10,4 ; 12,25 ;
14,333… m — différentes des brutes aux indices 1, 3, 4 et 5."""


def _moving_path(first: float, second: float) -> list[float]:
    """Abscisses ``x`` (m, plan de base) du chemin réalisé entre deux positions."""
    trace = local_trace([2.0 * i for i in range(6)], [(x, 0.0) for x in MOVING_X_M])
    path = realized_path(trace, build_series(trace), first, second)
    return [to_local(45.0, 6.0, lat, lon)[0] for lat, lon in path]


def test_realized_path_raw_ends_and_strictly_interior_smoothed_records() -> None:
    """``P(1,5)`` brut à 4,5 m (lissé : 5,25), lissés de 2 et 3 (6 et 10,4, brut 9),
    ``P(4)`` brut à 12 m (lissé : 12,25)."""
    assert _moving_path(1.5, 4.0) == pytest.approx([4.5, 6.0, 10.4, 12.0], abs=1e-9)


def test_realized_path_between_integer_positions() -> None:
    """``π`` entiers : les enregistrements eux-mêmes aux extrémités, et seulement les
    enregistrements strictement intérieurs, lissés."""
    assert _moving_path(0.0, 1.0) == pytest.approx([0.0, 3.0], abs=1e-9)
    assert _moving_path(0.0, 5.0) == pytest.approx(
        [0.0, 4.5, 6.0, 10.4, 12.25, 22.0], abs=1e-9
    )


def test_realized_path_refuses_decreasing_positions() -> None:
    with pytest.raises(ValueError, match="positions décroissantes"):
        _moving_path(2.0, 1.5)


def test_realized_length_is_the_haversine_length() -> None:
    """Un aller-retour sur le parallèle de base : 3 + 2 + 5 m, la longueur du chemin
    et non la corde de 6 m (le long du parallèle, haversine et ``x`` diffèrent de
    moins de ``1,5e−7`` m, § 7.0 de M4a-2a)."""
    trace = local_trace([0.0, 1.0, 2.0, 3.0], [(0, 0), (3, 0), (1, 0), (6, 0)])
    path = tuple(zip(trace.latitude_deg, trace.longitude_deg, strict=True))
    assert realized_length_m(path) == pytest.approx(10.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Contrôle intérieur (§ 5b.5 ; 0010 D4.10, point 4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("point", "expected_m"),
    [
        ((5.0, 3.0), 3.0),
        ((-4.0, 3.0), 5.0),
        ((13.0, -4.0), 5.0),
    ],
)
def test_distance_to_a_segment_is_clamped_to_its_ends(
    point: tuple[float, float], expected_m: float
) -> None:
    assert _segment_distance_m(point, (0.0, 0.0), (10.0, 0.0)) == expected_m


def test_distance_to_a_zero_length_segment_is_the_distance_to_its_point() -> None:
    assert _segment_distance_m((3.0, 4.0), (0.0, 0.0), (0.0, 0.0)) == 5.0


def test_interior_deviation_without_interior_point() -> None:
    """``H_1 = 0`` sans point intérieur ; ``H_2`` lu aux segments du chemin."""
    geometry = reference((0.0, 0.0), (100.0, 0.0))
    trace = local_trace([0.0, 10.0], [(0.0, 3.0), (100.0, 3.0)])
    path = tuple(zip(trace.latitude_deg, trace.longitude_deg, strict=True))
    h1_m, h2_m = interior_deviations(geometry, path, 0.0, geometry.length_m, 30.0)
    assert h1_m == 0.0
    assert h2_m == pytest.approx(3.0, abs=1e-6)
