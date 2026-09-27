"""Horloges (§ 4.7 du brief M4a-1, ``0010`` D5) : fenêtres, qualification,
confirmation, partition, cumulés, totaux, épisodes.

Scénarios du § 7.1 sur le plan équatorial (``fixtures.traces``), 1 Hz et 1 000 m
d'altitude sauf mention. Les égalités de seuil se testent sur ``qualify`` seul, par
un tableau de valeurs exactement représentables à ``τ/2`` et ``2τ`` des seuils ; et,
pour les horloges seulement, à travers une trace : trois fixtures (brief M4a-2c,
§ 5.2) atteignent les seuils exactement en réels à travers le lissage et
l'interpolation, et la règle de ``0010`` D5.2 les retrouve.
"""

import math
from collections.abc import Sequence
from dataclasses import FrozenInstanceError
from itertools import pairwise
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fixtures.traces import parallel_trace, planar_trace
from mountain_perf.backtest.clocks import (
    CLOCK_HALF_WINDOW_S,
    CLOCK_THRESHOLD_RELATIVE_TOLERANCE,
    Qualification,
    _diameter_m,
    _smoothed_at,
    clock_duration_s,
    clock_partition,
    confirm,
    cumulative_s,
    qualify,
    stop_episodes,
    trace_totals,
    window_measures,
)
from mountain_perf.backtest.series import build_series
from mountain_perf.gpx.geo import EARTH_RADIUS_M
from mountain_perf.schemas import (
    CENTRAL_CONVENTION_INDEX,
    CLOCK_CONVENTIONS,
    CLOCKS,
    Clock,
    ClockConvention,
    ClockKind,
    ClockPartition,
    IntervalState,
    RecordedTrace,
    StopEpisode,
)
from mountain_perf.schemas.clock import CLOCK_TOTALS_RELATIVE_TOLERANCE
from strategies import eventful_traces

M, S, U = IntervalState.MOVING, IntervalState.STOPPED, IntervalState.UNDETERMINED
MOBILE, IMMOBILE, INDETERMINATE = (
    Qualification.MOBILE,
    Qualification.IMMOBILE,
    Qualification.INDETERMINATE,
)
C = CENTRAL_CONVENTION_INDEX
SECONDS_0_300 = [float(t) for t in range(301)]


def _tent(t: float) -> float:
    """``5 − |t − 105|`` sur ``[100 ; 110]``, 0 ailleurs (X06-bis, X06-ter)."""
    return 5 - abs(t - 105) if 100 <= t <= 110 else 0.0


def _totals(trace: RecordedTrace) -> list[tuple[float, float, float]]:
    partition = clock_partition(trace, build_series(trace))
    return [
        (t.moving_s, t.stopped_s, t.undetermined_s) for t in trace_totals(partition)
    ]


def _episodes(trace: RecordedTrace, k: int = C) -> list[tuple[float, float]]:
    partition = clock_partition(trace, build_series(trace))
    return [(e.start_s, e.end_s) for e in stop_episodes(partition, k)]


def _intervals_in(partition: ClockPartition, k: int, state: IntervalState) -> list[int]:
    return [i for i, mark in enumerate(partition.states[k]) if mark is state]


def _assert_totals(
    actual: Sequence[tuple[float, float, float]],
    expected: Sequence[tuple[float, float, float]],
) -> None:
    """Totaux ``(M, S, U)`` à ``1e−6`` s près (§ 7.0)."""
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected, strict=True):
        assert got == pytest.approx(want, abs=1e-6)


def test_window_constant_of_0010_d5_2() -> None:
    assert CLOCK_HALF_WINDOW_S == 15.0


def test_threshold_tolerance_of_0010_d5_2() -> None:
    """``0010`` D5.2, précision M4a-2c : ``τ = 1e−6``. Le tableau de ``qualify`` est
    construit avec la constante et la suit ; ce test seul en fixe la valeur."""
    assert CLOCK_THRESHOLD_RELATIVE_TOLERANCE == 1e-6


# ---------------------------------------------------------------------------
# Tableau des horloges du § 7.1 — une ligne par test
# ---------------------------------------------------------------------------

T09 = planar_trace([float(t) for t in range(181)], [0.0] * 181)
X06 = planar_trace(SECONDS_0_300, [0.098 * t for t in SECONDS_0_300])
X06_BIS = planar_trace(SECONDS_0_300, [_tent(t) for t in SECONDS_0_300])
X06_TER = planar_trace(
    SECONDS_0_300, [0.0] * 301, elevation_m=[1000 + _tent(t) for t in SECONDS_0_300]
)
T08 = planar_trace(
    SECONDS_0_300,
    [0.04 * t for t in SECONDS_0_300],
    elevation_m=[1000 - 0.1 * t for t in SECONDS_0_300],
)


def test_t09_fixed_position() -> None:
    _assert_totals(_totals(T09), [(0, 146, 34)] * 5)
    partition = clock_partition(T09, build_series(T09))
    assert _intervals_in(partition, C, S) == list(range(17, 163))
    assert stop_episodes(partition, C) == (StopEpisode(17, 163, 17, 163),)


def test_x06_slow_drift_is_mobile_only_under_the_strictest_convention() -> None:
    _assert_totals(_totals(X06), [(266, 0, 34)] + [(0, 266, 34)] * 4)
    assert _episodes(X06) == [(17, 283)]


def test_x06_window_is_read_at_the_exact_bounds() -> None:
    """Interpolation aux bornes exactes : ``D_h = 2,94`` ; les enregistrements
    encadrants donneraient ``3,038`` et ``U``."""
    measures = window_measures(X06, build_series(X06), 100, complete=True)
    assert measures is not None
    assert measures.v_h == pytest.approx(0.098, abs=1e-6)
    assert measures.d_h == pytest.approx(2.94, abs=1e-6)


def test_x06_bis_totals_and_episodes() -> None:
    _assert_totals(_totals(X06_BIS)[C : C + 1], [(8, 232, 60)])
    partition = clock_partition(X06_BIS, build_series(X06_BIS))
    assert _intervals_in(partition, C, M) == [*range(88, 92), *range(118, 122)]
    assert _episodes(X06_BIS) == [(17, 88), (122, 283)]


def test_x06_bis_diameter_includes_interior_records() -> None:
    """Sommet lissé ``(3 + 4 + 5 + 4 + 3)/5 = 3,8`` : un diamètre sur les seules
    bornes donnerait 0 et ``IMMOBILE`` partout."""
    measures = window_measures(X06_BIS, build_series(X06_BIS), 104, complete=True)
    assert measures is not None
    assert (measures.v_h, measures.v_z) == pytest.approx((0, 0), abs=1e-6)
    assert (measures.d_h, measures.d_z) == pytest.approx((3.8, 0), abs=1e-6)
    assert measures.d_h is not None
    assert measures.d_z is not None
    assert [
        qualify(measures.v_h, measures.v_z, measures.d_h, measures.d_z, c)
        for c in CLOCK_CONVENTIONS
    ] == [INDETERMINATE, INDETERMINATE, IMMOBILE, INDETERMINATE, INDETERMINATE]


def test_x06_ter_altitude_range_includes_interior_records() -> None:
    measures = window_measures(X06_TER, build_series(X06_TER), 104, complete=True)
    assert measures is not None
    assert (measures.v_h, measures.v_z, measures.d_h) == pytest.approx(
        (0, 0, 0), abs=1e-6
    )
    assert measures.d_z == pytest.approx(3.8, abs=1e-6)
    assert measures.d_h is not None
    assert measures.d_z is not None
    assert {
        qualify(measures.v_h, measures.v_z, measures.d_h, measures.d_z, c)
        for c in CLOCK_CONVENTIONS
    } == {INDETERMINATE}


def test_t08_vertical_speed_is_unsigned() -> None:
    """Une vitesse verticale signée rendrait ``M = 0``."""
    _assert_totals(_totals(T08)[C : C + 1], [(266, 0, 34)])
    measures = window_measures(T08, build_series(T08), 100)
    assert measures is not None
    assert (measures.v_h, measures.v_z) == pytest.approx((0.04, 0.1), abs=1e-6)


def test_gap_of_11_s_splits_the_blocks() -> None:
    times = [float(t) for t in (*range(101), *range(111, 261))]
    trace = planar_trace(times, [0.0] * len(times))
    assert len(build_series(trace).blocks) == 2
    _assert_totals(_totals(trace)[C : C + 1], [(0, 181, 79)])
    assert _episodes(trace) == [(17, 83), (128, 243)]


def test_step_of_10_s_is_not_a_gap() -> None:
    times = [float(t) for t in (*range(101), *range(110, 260))]
    trace = planar_trace(times, [0.0] * len(times))
    assert len(build_series(trace).blocks) == 1
    _assert_totals(_totals(trace)[C : C + 1], [(0, 225, 34)])
    assert _episodes(trace) == [(17, 242)]


def test_step_of_10_001_s_is_a_gap() -> None:
    times = [*map(float, range(101)), *(110.001 + j for j in range(150))]
    trace = planar_trace(times, [0.0] * len(times))
    assert len(build_series(trace).blocks) == 2
    _assert_totals(_totals(trace)[C : C + 1], [(0, 181, 78.001)])


# ---------------------------------------------------------------------------
# Correctifs de relecture de la PR #8
# ---------------------------------------------------------------------------

EAST_DRIFT_45N = parallel_trace(SECONDS_0_300, [0.08 * t for t in SECONDS_0_300])
"""Dérive vers l'est à 0,08 m/s sur le parallèle 45° N, 1 Hz, ``t = 0 … 300``."""


def test_local_plane_scales_longitude_by_cos_latitude() -> None:
    """P1 — § 4.7 point 1 : ``x = R·Δλ·cos φ_lo``. Sans le facteur ``cos φ``, une
    vitesse est-ouest serait surestimée de 41 % à 45° N."""
    trace = EAST_DRIFT_45N
    measures = window_measures(trace, build_series(trace), 150, complete=True)
    assert measures is not None
    assert (measures.v_h, measures.d_h) == pytest.approx((0.08, 2.4), abs=1e-6)
    assert (measures.v_z, measures.d_z) == pytest.approx((0, 0), abs=1e-6)
    _assert_totals(_totals(trace), [(266, 0, 34)] + [(0, 266, 34)] * 4)


SLOW_ZIGZAG = planar_trace(
    SECONDS_0_300,
    [0.08 * t + 6 * math.sin(2 * math.pi * t / 10) for t in SECONDS_0_300],
)
"""Zigzag lent : ``x = 0,08·t + 6·sin(2π·t/10)`` m. Sur toute fenêtre de 30 s les
sinus s'annulent aux bornes (``v_h = 0,08``) mais le zigzag lissé donne ``D_h``
entre 8,67 et 9,47 m, au-dessus de ``30·h`` sous toutes les conventions."""


def test_slow_zigzag_is_undetermined_not_stopped() -> None:
    """P2 — les diamètres décident : lente mais étendue, la fenêtre est indéterminée
    sous θ2 à θ5, jamais immobile."""
    _assert_totals(_totals(SLOW_ZIGZAG), [(266, 0, 34)] + [(0, 0, 300)] * 4)


FIXED_HALF_HERTZ = planar_trace([2.0 * k for k in range(101)], [0.0] * 101)
"""Position fixe à 0,5 Hz, ``t = 0, 2, …, 200`` : toutes les bornes ``m ± 15`` des
fenêtres tombent sur un enregistrement."""


def test_window_bound_exactly_on_a_record() -> None:
    """P8 — § 4.7 point 1 : ``j⁻(β) = max{j : t_j <= β}``, confondu avec ``j⁺`` quand
    ``β`` tombe sur un enregistrement. Fenêtre de l'intervalle 9 : ``[4 ; 34]``, et
    l'enregistrement en 4 s (indice 2) a un lissage complet."""
    trace = FIXED_HALF_HERTZ
    series = build_series(trace)
    measures = window_measures(trace, series, 9, complete=True)
    assert measures is not None
    assert (measures.v_h, measures.v_z, measures.d_h, measures.d_z) == pytest.approx(
        (0, 0, 0, 0), abs=1e-6
    )
    assert window_measures(trace, series, 8, complete=True) is None
    _assert_totals(_totals(trace), [(0, 164, 36)] * 5)


def test_window_measures_are_frozen() -> None:
    """P9 — ``WindowMeasures`` est gelé (§ 4.7)."""
    target: Any = window_measures(T09, build_series(T09), 90)
    assert target is not None
    with pytest.raises(FrozenInstanceError):
        target.v_h = 1.0


def test_economy_matches_the_complete_partition_when_diameters_decide() -> None:
    """P2 — test 3 du § 8.1 sur une trace où l'économie ne peut pas se taire."""
    economic = clock_partition(SLOW_ZIGZAG, build_series(SLOW_ZIGZAG))
    assert economic.states == _complete_partition(SLOW_ZIGZAG)


# ---------------------------------------------------------------------------
# Égalités de seuil exactes à travers une trace (``0010`` D5.2, précision M4a-2c)
# ---------------------------------------------------------------------------

SECONDS_0_299 = [float(t) for t in range(300)]

STEP_1_0_M = planar_trace(
    SECONDS_0_299,
    [0.0] * 300,
    elevation_m=[1234.4 if t < 150 else 1235.4 for t in range(300)],
)
"""Marche de 1,0 m entre les enregistrements 149 et 150. Lissée, elle monte en cinq
pas de 0,2 m ; aux intervalles 136 et 162, ``Δz = 0,9`` m exactement en réels, donc
``v_z = z`` et ``D_z = 30·z`` sous ``θ2``, ``θ4``, ``θ5``. Sur une base de 1 000 m,
l'arrondi tomberait du bon côté et la règle stricte passerait."""

STEP_1_5_M = planar_trace(
    SECONDS_0_299,
    [0.0] * 300,
    elevation_m=[1000.0 if t < 150 else 1001.5 for t in range(300)],
)
"""Marche de 1,5 m : ``v_z = 0,015`` et ``D_z = 0,45`` sous ``θ1`` (intervalles 133
et 165) ; ``v_z = 0,045`` et ``D_z = 1,35`` sous ``θ3`` (136 et 162), ``0,045`` étant
aussi le plus haut seuil vertical de l'économie."""

PACE_0_15_MS = planar_trace(SECONDS_0_299, [0.15 * t for t in SECONDS_0_299])
"""Pas de 0,15 m/s : ``v_h = h`` et ``D_h = 30·h`` sous ``θ3`` sur toute fenêtre
valide, ``0,15`` étant aussi le plus haut seuil horizontal de l'économie."""


@pytest.mark.parametrize(
    ("trace", "expected"),
    [
        (
            STEP_1_0_M,
            [(31, 234, 34), (25, 240, 34), (0, 265, 34), (25, 240, 34), (25, 240, 34)],
        ),
        (
            STEP_1_5_M,
            [(31, 234, 34), (29, 236, 34), (25, 240, 34), (29, 236, 34), (29, 236, 34)],
        ),
        (PACE_0_15_MS, [(265, 0, 34), (265, 0, 34), (0, 265, 34)] + [(265, 0, 34)] * 2),
    ],
    ids=["marche-1,0-m", "marche-1,5-m", "pas-0,15-m-s"],
)
def test_threshold_equalities_through_a_trace(
    trace: RecordedTrace, expected: list[tuple[float, float, float]]
) -> None:
    """``0010`` D5.2, précision M4a-2c : les égalités exactes en réels sont retrouvées
    à travers le lissage et l'interpolation. Totaux ``(M, S, U)`` exacts : les durées
    sont des secondes entières."""
    assert _totals(trace) == expected


@pytest.mark.parametrize("i", [136, 162])
def test_step_1_0_m_equalities_are_immobile_under_theta_c(i: int) -> None:
    """``0010`` D5.2, précision M4a-2c : ``v_z = z`` et ``D_z = 30·z`` à l'arrondi
    près, la fenêtre est immobile."""
    measures = window_measures(STEP_1_0_M, build_series(STEP_1_0_M), i)
    assert measures is not None
    qualification = qualify(
        measures.v_h, measures.v_z, measures.d_h, measures.d_z, CLOCK_CONVENTIONS[C]
    )
    assert qualification is IMMOBILE


# ---------------------------------------------------------------------------
# Cumulés et durées (``0010`` D5.3) sur X06-bis, θ_c
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def x06_bis_partition() -> ClockPartition:
    """Partition de X06-bis, calculée à l'exécution et non au chargement du module :
    une exception de ``clock_partition`` fait rougir des tests nommés, pas la collecte
    (P3)."""
    return clock_partition(X06_BIS, build_series(X06_BIS))


@pytest.mark.parametrize(
    ("at_s", "expected"), [(90, 2), (89.5, 1.5), (120, 6), (300, 8), (0, 0)]
)
def test_cumulative_moving_time(
    x06_bis_partition: ClockPartition, at_s: float, expected: float
) -> None:
    moving = cumulative_s(x06_bis_partition, C, frozenset({M}), at_s)
    assert moving == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize(
    ("clock", "expected"),
    [
        (CLOCKS[0], 50),
        (CLOCKS[1 + C], 8),
        (CLOCKS[6 + C], 34),
    ],
    ids=["ecoule", "M_theta_c", "M+U_theta_c"],
)
def test_clock_duration_between_80_and_130(
    x06_bis_partition: ClockPartition, clock: Clock, expected: float
) -> None:
    duration = clock_duration_s(x06_bis_partition, clock, 80, 130)
    assert duration == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("at_s", [-0.001, 300.001, math.nan])
def test_cumulative_outside_the_trace_is_refused(
    x06_bis_partition: ClockPartition, at_s: float
) -> None:
    with pytest.raises(ValueError, match="hors de la trace"):
        cumulative_s(x06_bis_partition, C, frozenset({M}), at_s)


@pytest.mark.parametrize("clock", CLOCKS, ids=str)
def test_clock_duration_never_negative(
    x06_bis_partition: ClockPartition, clock: Clock
) -> None:
    """Précision de relecture : ``start_s > end_s`` est refusé (``0010`` D4.12) ;
    ``start_s == end_s`` rend 0."""
    with pytest.raises(ValueError, match="jamais de durée négative"):
        clock_duration_s(x06_bis_partition, clock, 130, 80)
    assert clock_duration_s(x06_bis_partition, clock, 100.5, 100.5) == 0


@pytest.mark.parametrize("bounds", [(-1.0, 10.0), (10.0, 301.0)], ids=str)
def test_clock_duration_outside_the_trace_is_refused(
    x06_bis_partition: ClockPartition, bounds: tuple[float, float]
) -> None:
    with pytest.raises(ValueError, match="hors de la trace"):
        clock_duration_s(x06_bis_partition, CLOCKS[0], *bounds)


# ---------------------------------------------------------------------------
# Confirmation et qualification (fonctions pures)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("durations_s", "qualifications", "expected"),
    [
        ((30, 29.9), (IMMOBILE, IMMOBILE), (U, U)),
        ((30, 30), (IMMOBILE, IMMOBILE), (S, S)),
        ((30, 30.1), (IMMOBILE, IMMOBILE), (S, S)),
        ((40, 1, 40), (IMMOBILE, INDETERMINATE, IMMOBILE), (U, U, U)),
        ((70, 1), (IMMOBILE, MOBILE), (S, M)),
    ],
    ids=["59,9", "60-pile", "60,1", "coupee", "arret-puis-mobile"],
)
def test_confirmation_with_c_60(
    durations_s: tuple[float, ...],
    qualifications: tuple[Qualification, ...],
    expected: tuple[IntervalState, ...],
) -> None:
    """``0010`` D5.2 : une suite maximale immobile de durée ``>= c`` est un arrêt."""
    assert confirm(durations_s, qualifications, 60.0) == expected


def test_confirmation_needs_one_duration_per_interval() -> None:
    with pytest.raises(ValueError, match="qualifications"):
        confirm((1.0,), (IMMOBILE, IMMOBILE), 60.0)


def test_confirmation_has_no_tolerance_below_c() -> None:
    """Correctif R4 de la PR #11 (brief M4a-2c, § 2 : ``confirm`` inchangé) : une
    suite immobile d'un flottant sous 60 s reste indéterminée ; la tolérance des
    seuils de mesure (``0010`` D5.2, précision M4a-2c) ne s'applique pas aux
    durées."""
    assert confirm((math.nextafter(60.0, 0.0),), (IMMOBILE,), 60.0) == (U,)


DYADIC = ClockConvention(0.125, 0.03125, 60.0)
"""``30·h = 3,75`` et ``30·z = 0,9375`` sont exacts en flottant."""


TAU = CLOCK_THRESHOLD_RELATIVE_TOLERANCE
EQUAL = 1 + TAU / 2
"""Facteur d'une mesure égale à son seuil à ``τ/2`` près."""
BEYOND = 1 + 2 * TAU
"""Facteur d'une mesure qui dépasse son seuil."""


@pytest.mark.parametrize(
    ("measures", "expected"),
    [
        ((0.125, 0.03125, 3.75, 0.9375), IMMOBILE),
        ((0.125 * EQUAL, 0.03125, 3.75, 0.9375), IMMOBILE),
        ((0.125, 0.03125 * EQUAL, 3.75, 0.9375), IMMOBILE),
        ((0.125, 0.03125, 3.75 * EQUAL, 0.9375), IMMOBILE),
        ((0.125, 0.03125, 3.75, 0.9375 * EQUAL), IMMOBILE),
        ((0.125 * BEYOND, 0.03125, 3.75, 0.9375), MOBILE),
        ((0.125, 0.03125 * BEYOND, 3.75, 0.9375), MOBILE),
        ((0.125, 0.03125, 3.75 * BEYOND, 0.9375), INDETERMINATE),
        ((0.125, 0.03125, 3.75, 0.9375 * BEYOND), INDETERMINATE),
    ],
    ids=[
        "seuils-atteints",
        "v_h-egal",
        "v_z-egal",
        "D_h-egal",
        "D_z-egal",
        "v_h-au-dela",
        "v_z-au-dela",
        "D_h-au-dela",
        "D_z-au-dela",
    ],
)
def test_qualification_at_the_thresholds(
    measures: tuple[float, float, float, float], expected: Qualification
) -> None:
    """``0010`` D5.2, précision M4a-2c : une mesure égale à son seuil à ``τ/2`` près
    ne le dépasse pas ; à ``2τ`` au-delà, elle le dépasse."""
    assert qualify(*measures, DYADIC) is expected


def test_tolerance_boundary_is_included() -> None:
    """Correctif R5 de la PR #11 (brief M4a-2c, § 3.1) : une mesure qui dépasse son
    seuil d'exactement ``τ·s`` lui est égale. Aucune mesure des cinq conventions de
    ``0010`` ne tombe sur cette frontière : la convention est construite pour."""
    h = 1_000_000.0 / 2**23
    x = 1_000_001.0 / 2**23
    assert x - h == CLOCK_THRESHOLD_RELATIVE_TOLERANCE * h  # frontière exacte
    assert qualify(x, 0.0, 0.0, 0.0, ClockConvention(h, 0.03, 60.0)) is IMMOBILE


def test_qualification_needs_diameters_only_when_not_mobile() -> None:
    assert qualify(1.0, 0.0, None, None, DYADIC) is MOBILE
    with pytest.raises(ValueError, match="D_h et D_z"):
        qualify(0.0, 0.0, None, 0.0, DYADIC)


def test_invalid_window_and_gap_have_no_measures() -> None:
    times = [float(t) for t in (*range(101), *range(111, 261))]
    trace = planar_trace(times, [0.0] * len(times))
    series = build_series(trace)
    assert window_measures(trace, series, 100) is None  # le trou lui-même
    assert window_measures(trace, series, 16) is None  # lissage tronqué
    assert window_measures(trace, series, 17) is not None
    # j⁺(98,5) = 99, dont le lissage est tronqué ; la borne haute ne sort du bloc
    # qu'à partir de l'intervalle 85.
    assert window_measures(trace, series, 83) is None


# ---------------------------------------------------------------------------
# Fonctions internes : diamètre, valeurs lissées aux bornes, épisodes
# (correctif R6 de la PR #11, lacunes K1 à K6 du balayage mécanique)
# ---------------------------------------------------------------------------

TWO_SECOND_STEPS = [2.0 * k for k in range(11)]
"""``t = 0, 2, …, 20`` s."""


def test_diameter_north_south() -> None:
    """K1 : diamètre d'une paire qui s'écarte sur les deux axes, nord-sud compris."""
    assert _diameter_m([(0.0, 0.0), (3.0, 4.0)]) == 5.0


def test_diameter_farthest_pair_is_not_first_and_last() -> None:
    """K2 : la paire la plus éloignée est le premier point et un point intérieur,
    pas le premier et le dernier."""
    assert _diameter_m([(0.0, 0.0), (1.0, 0.0), (10.0, 0.0), (2.0, 0.0)]) == 10.0


def test_smoothed_at_a_bound_on_a_record() -> None:
    """K3 : borne de fenêtre sur un enregistrement (``0010`` D5.2, ``j⁻`` et ``j⁺``
    confondus) : ses latitude et longitude lissées, chacune à sa place."""
    trace = planar_trace(
        TWO_SECOND_STEPS, list(TWO_SECOND_STEPS), [2 * t for t in TWO_SECOND_STEPS]
    )
    lat, lon, _ = _smoothed_at(trace, build_series(trace), 10.0)
    assert lat == pytest.approx(math.degrees(20 / EARTH_RADIUS_M), abs=1e-12)
    assert lon == pytest.approx(math.degrees(10 / EARTH_RADIUS_M), abs=1e-12)


def test_smoothed_at_interpolates_on_a_two_second_step() -> None:
    """K4 : interpolation en temps à un pas différent de 1 s."""
    trace = planar_trace(TWO_SECOND_STEPS, [0.0] * 11, list(TWO_SECOND_STEPS))
    lat, _, _ = _smoothed_at(trace, build_series(trace), 9.0)
    assert lat == pytest.approx(math.degrees(9 / EARTH_RADIUS_M), abs=1e-12)


def test_smoothed_at_interpolates_a_non_linear_smoothed_series() -> None:
    """K5 : interpolation sur une série lissée non linéaire. Altitudes ``t²`` à
    1 Hz, lissées en ``j² + 2`` : 27 en 5 s, 38 en 6 s, 32,5 à mi-chemin."""
    seconds = [float(t) for t in range(12)]
    trace = planar_trace(seconds, [0.0] * 12, elevation_m=[t * t for t in seconds])
    assert _smoothed_at(trace, build_series(trace), 5.5)[2] == 32.5


def test_stop_episode_from_the_first_to_the_last_interval() -> None:
    """K6 : épisode du premier au dernier intervalle. Inatteignable par
    ``clock_partition``, dont les bords sont indéterminés, mais ``stop_episodes``
    est public."""
    partition = ClockPartition(time_s=(0.0, 1.0, 2.0, 3.0), states=((S, S, S),) * 5)
    assert stop_episodes(partition, 0) == (
        StopEpisode(start_s=0.0, end_s=3.0, first_record=0, last_record=3),
    )


# ---------------------------------------------------------------------------
# Propriétés, sur des traces à trous, pas irréguliers et immobilités garantis
# ---------------------------------------------------------------------------


def _complete_partition(trace: RecordedTrace) -> tuple[tuple[IntervalState, ...], ...]:
    """Définition complète de ``0010`` D5.2, sans l'économie de ``clock_partition``."""
    series = build_series(trace)
    durations_s = [b - a for a, b in pairwise(trace.time_s)]
    states: list[tuple[IntervalState, ...]] = []
    for convention in CLOCK_CONVENTIONS:
        qualifications: list[Qualification] = []
        for i in range(len(durations_s)):
            measures = window_measures(trace, series, i, complete=True)
            qualifications.append(
                INDETERMINATE
                if measures is None
                else qualify(
                    measures.v_h, measures.v_z, measures.d_h, measures.d_z, convention
                )
            )
        states.append(confirm(durations_s, qualifications, convention.min_stop_s))
    return tuple(states)


def _stopped_runs(marks: Sequence[IntervalState]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    i = 0
    while i < len(marks):
        if marks[i] is S:
            j = i
            while j + 1 < len(marks) and marks[j + 1] is S:
                j += 1
            runs.append((i, j))
            i = j + 1
        else:
            i += 1
    return runs


@settings(deadline=None, max_examples=50)
@given(eventful_traces())
def test_partition_properties(trace: RecordedTrace) -> None:
    series = build_series(trace)
    partition = clock_partition(trace, series)
    n = len(trace.time_s) - 1
    assert partition.time_s == trace.time_s
    assert any(series.gap_after)
    for k, convention in enumerate(CLOCK_CONVENTIONS):
        marks = partition.states[k]
        assert len(marks) == n
        assert all(mark in (M, S, U) for mark in marks)
        assert all(marks[i] is U for i in range(n) if series.gap_after[i])
        for first, last in _stopped_runs(marks):
            duration_s = trace.time_s[last + 1] - trace.time_s[first]
            assert duration_s >= convention.min_stop_s - 1e-9
            assert not any(series.gap_after[first : last + 1])
    assert _stopped_runs(partition.states[C])  # l'immobilité garantie est un arrêt


@settings(deadline=None, max_examples=50)
@given(eventful_traces())
def test_economy_gives_the_complete_partition(trace: RecordedTrace) -> None:
    """§ 4.7 point 4 : omettre les diamètres des fenêtres mobiles ne change rien."""
    economic = clock_partition(trace, build_series(trace))
    assert economic.states == _complete_partition(trace)


@settings(deadline=None, max_examples=50)
@given(eventful_traces())
def test_trace_totals_identity(trace: RecordedTrace) -> None:
    """``0010`` D5.2 : ``M + S + U = E`` pour chaque convention."""
    for totals in trace_totals(clock_partition(trace, build_series(trace))):
        assert totals.elapsed_s == trace.elapsed_s
        gap = math.fsum(
            (
                totals.moving_s,
                totals.stopped_s,
                totals.undetermined_s,
                -totals.elapsed_s,
            )
        )
        assert abs(gap) <= CLOCK_TOTALS_RELATIVE_TOLERANCE * max(1.0, totals.elapsed_s)


@settings(deadline=None, max_examples=50)
@given(eventful_traces(), st.data())
def test_clock_durations_are_additive_and_bounded(
    trace: RecordedTrace, data: st.DataObject
) -> None:
    """``0010`` D5.3 : additivité sur tout découpage ``[a ; b]`` puis ``[b ; c]``."""
    partition = clock_partition(trace, build_series(trace))
    end_s = trace.time_s[-1]
    a, b, c = sorted(
        data.draw(st.floats(min_value=0.0, max_value=end_s)) for _ in range(3)
    )
    for clock in CLOCKS:
        whole = clock_duration_s(partition, clock, a, c)
        parts = clock_duration_s(partition, clock, a, b) + clock_duration_s(
            partition, clock, b, c
        )
        assert parts == pytest.approx(whole, abs=1e-9)
        assert -1e-9 <= whole <= c - a + 1e-9
        if clock.kind is ClockKind.ELAPSED:
            assert whole == c - a
