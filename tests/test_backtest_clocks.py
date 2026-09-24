"""Horloges (§ 4.7 du brief M4a-1, ``0010`` D5) : fenêtres, qualification,
confirmation, partition, cumulés, totaux, épisodes.

Scénarios du § 7.1 sur le plan équatorial (``fixtures.traces``), 1 Hz et 1 000 m
d'altitude sauf mention. Les égalités de seuil se testent sur ``qualify`` seul, avec
des valeurs exactement représentables, jamais à travers une trace (§ 7.0).
"""

import math
from collections.abc import Sequence
from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fixtures.traces import parallel_trace, planar_trace
from mountain_perf.backtest.clocks import (
    CLOCK_HALF_WINDOW_S,
    Qualification,
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


def test_economy_matches_the_complete_partition_when_diameters_decide() -> None:
    """P2 — test 3 du § 8.1 sur une trace où l'économie ne peut pas se taire."""
    economic = clock_partition(SLOW_ZIGZAG, build_series(SLOW_ZIGZAG))
    assert economic.states == _complete_partition(SLOW_ZIGZAG)


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


DYADIC = ClockConvention(0.125, 0.03125, 60.0)
"""``30·h = 3,75`` et ``30·z = 0,9375`` sont exacts en flottant."""


def _up(value: float) -> float:
    return math.nextafter(value, math.inf)


@pytest.mark.parametrize(
    ("measures", "expected"),
    [
        ((0.125, 0.03125, 3.75, 0.9375), IMMOBILE),
        ((0.125, 0.03125, _up(3.75), 0.9375), INDETERMINATE),
        ((0.125, 0.03125, 3.75, _up(0.9375)), INDETERMINATE),
        ((_up(0.125), 0.03125, 3.75, 0.9375), MOBILE),
        ((0.125, _up(0.03125), 3.75, 0.9375), MOBILE),
    ],
    ids=["seuils-atteints", "D_h+", "D_z+", "v_h+", "v_z+"],
)
def test_qualification_at_the_thresholds(
    measures: tuple[float, float, float, float], expected: Qualification
) -> None:
    assert qualify(*measures, DYADIC) is expected


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
