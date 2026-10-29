"""Les intervalles d'une activité (``mountain_perf.estimation.intervals``, M6b,
``docs/decisions/0017``) : la grille du profil, les bornes, les temps M/S/U sous θc, le
plafond, la FC décalée.

Enregistrements synthétiques : ``tests/fixtures/montees.py`` (qui enregistre à partir
de ``t = 1 s`` : la FC lue dans le temps de la trace est celle de l'enregistrement
1 s plus tard), et :func:`line`, une trace le long du méridien de 6° E. La haversine
n'est pas ronde (50 m le long du méridien en donnent 50,00000000024) : un arrêt ou un
plafond « exactement sur une borne » se prend sur une borne calculée."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Sequence
from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fixtures.montees import FLAT, climb_at, recording
from mountain_perf.clocks import clock_partition
from mountain_perf.estimation.intervals import (
    ActivityIntervals,
    CurveInterval,
    TraceRefusal,
    activity_intervals,
    heart_rate_series,
    time_at_distance,
)
from mountain_perf.gpx.geo import EARTH_RADIUS_M
from mountain_perf.gpx.profile import PROFILE_PARAMETER_SPECS
from mountain_perf.ingest.views import trace_view
from mountain_perf.schemas import (
    CENTRAL_CONVENTION_INDEX,
    ActivityRecording,
    ElevationChannel,
    ElevationField,
    HeartRateChannel,
    IntervalState,
    ParameterSet,
    PositionChannel,
)
from mountain_perf.series import build_series
from test_schemas_interim import recording as interim_recording

CLIMB = [FLAT, climb_at(600, 0.15, 60), FLAT]
"""Un replat de 500 m à 1 m/s, 60 m de montée à 15 % et 600 m/h, un replat."""

PROFILE = ParameterSet(PROFILE_PARAMETER_SPECS)
_M_PER_DEG = EARTH_RADIUS_M * math.pi / 180


def intervals_of(
    rec: ActivityRecording,
    *,
    hr_lag_s: float = 60.0,
    hr_min_coverage: float = 0.8,
    max_elapsed_s: float | None = None,
) -> ActivityIntervals:
    result = activity_intervals(
        rec,
        PROFILE,
        hr_lag_s=hr_lag_s,
        hr_min_coverage=hr_min_coverage,
        max_elapsed_s=max_elapsed_s,
    )
    assert isinstance(result, ActivityIntervals)
    return result


def line(
    times: Sequence[float],
    metres: Sequence[float],
    elevations: Sequence[float] | None = None,
    heart_rate: tuple[Sequence[float], Sequence[float]] | None = None,
) -> ActivityRecording:
    """Un enregistrement le long du méridien de 6° E depuis 45° N : aux instants
    ``times``, les distances ``metres`` ; altitudes de 1 000 m par défaut ; la FC
    ``(instants, valeurs)`` si donnée."""
    base = recording([FLAT], noise=False)
    t = tuple(float(x) for x in times)
    z = tuple(1000.0 for _ in t) if elevations is None else tuple(elevations)
    return dataclasses.replace(
        base,
        position=PositionChannel(
            t, tuple(45.0 + d / _M_PER_DEG for d in metres), tuple(6.0 for _ in t)
        ),
        elevation=ElevationChannel(t, z, ElevationField.ENHANCED_ALTITUDE),
        heart_rate=(
            None
            if heart_rate is None
            else HeartRateChannel(tuple(heart_rate[0]), tuple(heart_rate[1]))
        ),
    )


def with_heart_rate(
    rec: ActivityRecording,
    bpm: Callable[[float], float],
    keep: Callable[[float], bool] = lambda t: True,
) -> ActivityRecording:
    """``rec`` avec une FC ``bpm(t)`` aux instants des positions (temps de
    l'enregistrement) que ``keep`` garde."""
    assert rec.position is not None
    times = tuple(t for t in rec.position.time_s if keep(t))
    return dataclasses.replace(
        rec, heart_rate=HeartRateChannel(times, tuple(bpm(t) for t in times))
    )


def hr_only(times: Sequence[float], values: Sequence[float]) -> ActivityRecording:
    """Un enregistrement dont seule la FC compte, pour ``HeartRateSeries.mean``."""
    return interim_recording(
        heart_rate=HeartRateChannel(
            tuple(float(t) for t in times), tuple(float(v) for v in values)
        )
    )


def mean_of(
    rec: ActivityRecording, low: float, high: float, coverage: float = 1.0
) -> float | None:
    series = heart_rate_series(rec, 0.0)
    assert series is not None
    return series.mean(low, high, coverage)


# --- La grille, les bornes, les temps -----------------------------------------------


def test_the_intervals_pave_the_trace() -> None:
    """Le premier intervalle commence à 0, le dernier finit à l'écoulé, chacun où le
    précédent finit ; ``M + S + U = E``, aucun temps négatif."""
    result = intervals_of(recording(CLIMB, noise=False))
    intervals = result.intervals
    assert intervals[0].start_s == 0.0
    assert intervals[-1].end_s == result.elapsed_s
    for previous, current in pairwise(intervals):
        assert current.start_s == previous.end_s
    for interval in intervals:
        assert 0 < interval.length_m <= 50
        total = interval.moving_s + interval.stopped_s + interval.undetermined_s
        assert total == pytest.approx(interval.elapsed_s, abs=1e-9)
        assert min(interval.moving_s, interval.stopped_s, interval.undetermined_s) >= 0
    view = trace_view(recording(CLIMB, noise=False))
    assert view is not None
    assert result.elapsed_s == view.trace.time_s[-1] - view.trace.time_s[0]


def test_the_grade_follows_the_smoothed_profile() -> None:
    """La pente est celle du profil lissé : nulle sur le replat, 15 % dans la montée,
    où la vitesse en mouvement est celle de 600 m/h."""
    intervals = intervals_of(recording(CLIMB, noise=False)).intervals
    assert intervals[0].grade == 0.0
    assert max(i.grade for i in intervals) == pytest.approx(0.15, abs=0.002)
    steep = [i for i in intervals if abs(i.grade - 0.15) <= 0.002]
    assert steep
    for interval in steep:
        speed = interval.length_m / interval.moving_s
        assert speed == pytest.approx(600 / 3600 / 0.15, rel=0.01)


def test_a_stop_falls_in_the_interval_where_the_distance_stops() -> None:
    """Sans arrêt, aucun temps S ; un arrêt de 120 s tombe tout entier dans un seul
    intervalle, celui où la distance s'arrête."""
    plain = intervals_of(recording([FLAT, FLAT], noise=False)).intervals
    assert sum(i.stopped_s for i in plain) == 0
    stopped = intervals_of(
        recording([FLAT, FLAT], noise=False, stops=[(200.0, 320.0)])
    ).intervals
    assert sum(i.stopped_s for i in stopped) > 60
    carriers = [i for i in stopped if i.stopped_s > 0]
    assert len(carriers) == 1
    assert carriers[0].start_s <= 200.0
    assert carriers[0].end_s >= 320.0


def test_s05_a_wait_at_the_start_is_kept() -> None:
    """S05 : la première borne est le premier instant de la trace (``0017``, P1.3) ;
    une attente au départ n'est pas perdue."""
    result = intervals_of(line((0, 120, 140, 160), (0, 0, 50, 100)))
    intervals = result.intervals
    assert len(intervals) == 2
    assert intervals[0].start_s == 0.0
    assert intervals[0].end_s == pytest.approx(140, abs=1e-6)
    assert intervals[1].end_s == 160.0
    assert sum(i.elapsed_s for i in intervals) == pytest.approx(160, abs=1e-9)
    assert result.elapsed_s == pytest.approx(160, abs=1e-9)
    waited = intervals_of(recording([FLAT, FLAT], noise=False, stops=[(0.0, 120.0)]))
    first = waited.intervals[0]
    assert first.start_s == 0.0
    assert first.elapsed_s > 120
    assert first.stopped_s + first.undetermined_s >= 100
    assert sum(i.elapsed_s for i in waited.intervals) == pytest.approx(
        waited.elapsed_s, abs=1e-9
    )


def test_p1_2_the_grid_of_the_profile() -> None:
    """P1.2 : les intervalles sont ceux de la grille du profil, le dernier plus court ;
    une position répétée ne change rien."""
    metres = list(range(131))
    lengths = [i.length_m for i in intervals_of(line(metres, metres)).intervals]
    assert lengths == pytest.approx([50, 50, 30], abs=1e-6)
    assert sum(lengths) == pytest.approx(130, abs=1e-6)
    assert all(i.grade == 0.0 for i in intervals_of(line(metres, metres)).intervals)
    short = intervals_of(line(metres[:31], metres[:31])).intervals
    assert len(short) == 1
    assert short[0].length_m == pytest.approx(30, abs=1e-6)
    assert short[0].start_s == 0.0
    assert short[0].end_s == 30.0
    plain = list(range(101))
    repeated = [*range(50), 49, *range(50, 101)]
    times = list(range(len(repeated)))
    expected = [i.length_m for i in intervals_of(line(plain, plain)).intervals]
    got = [i.length_m for i in intervals_of(line(times, repeated)).intervals]
    assert got == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize(
    ("s", "expected"),
    [(0, 0), (25, 5), (50, 30), (75, 35), (100, 40), (120, 40)],
)
def test_time_at_distance(s: float, expected: float) -> None:
    """P1.3 : à abscisse égale (un arrêt), le dernier instant ; au-delà de la dernière
    abscisse, le dernier instant."""
    distance = (0.0, 50.0, 50.0, 50.0, 100.0)
    time = (0.0, 10.0, 20.0, 30.0, 40.0)
    assert time_at_distance(distance, time, s) == expected


def test_a_stop_belongs_to_a_single_interval() -> None:
    """Un arrêt sur la trace revient à un seul intervalle ; un arrêt à l'arrivée au
    dernier."""
    times = list(range(201))
    metres = [t if t <= 50 else (50 if t <= 150 else t - 100) for t in times]
    intervals = intervals_of(line(times, metres)).intervals
    carriers = [i for i in intervals if i.stopped_s > 0]
    assert len(carriers) == 1
    assert carriers[0].stopped_s > 60
    assert carriers[0].start_s <= 50
    assert carriers[0].end_s >= 150
    arrival = intervals_of(line(times, [min(t, 100) for t in times])).intervals
    assert arrival[-1].end_s == 200.0
    assert arrival[-1].stopped_s >= 60
    assert sum(i.elapsed_s for i in arrival) == pytest.approx(200, abs=1e-9)


def test_p1_4_a_gap_stays_in_u() -> None:
    """P1.4 : un trou de 15 s reste dans U, sans traitement ; la somme des M des
    intervalles est le temps M de la trace."""
    times = [*range(51), *range(65, 116)]
    rec = line(times, times)
    intervals = intervals_of(rec).intervals
    for interval in intervals:
        total = interval.moving_s + interval.stopped_s + interval.undetermined_s
        assert total == pytest.approx(interval.elapsed_s, abs=1e-9)
    holder = [i for i in intervals if i.start_s <= 50 and i.end_s >= 65]
    assert len(holder) == 1
    assert holder[0].undetermined_s >= 15
    view = trace_view(rec)
    assert view is not None
    trace = view.trace
    states = clock_partition(trace, build_series(trace)).states[
        CENTRAL_CONVENTION_INDEX
    ]
    moving = sum(
        trace.time_s[i + 1] - trace.time_s[i]
        for i, state in enumerate(states)
        if state is IntervalState.MOVING
    )
    assert sum(i.moving_s for i in intervals) == pytest.approx(moving, abs=1e-9)


def test_refusals() -> None:
    """Sans altitude, ou une seule : « sans trace » ; S21, deux positions identiques :
    « profil impossible », pas une exception (``0017``, P1.1)."""
    no_elevation = dataclasses.replace(recording(CLIMB, noise=False), elevation=None)
    single = interim_recording(
        elevation=ElevationChannel((1.0,), (1000.0,), ElevationField.ENHANCED_ALTITUDE)
    )
    same = interim_recording(
        position=PositionChannel((1.0, 2.0), (45.0, 45.0), (6.0, 6.0)),
        elevation=ElevationChannel(
            (1.0, 2.0), (1000.0, 1000.0), ElevationField.ENHANCED_ALTITUDE
        ),
    )
    for rec, refusal in (
        (no_elevation, TraceRefusal.NO_TRACE),
        (single, TraceRefusal.NO_TRACE),
        (same, TraceRefusal.NO_PROFILE),
    ):
        assert (
            activity_intervals(rec, PROFILE, hr_lag_s=60.0, hr_min_coverage=0.8)
            is refusal
        )


# --- Le plafond ---------------------------------------------------------------------


@pytest.mark.parametrize("ceiling", [60.0, 333.3, 900.5])
def test_the_ceiling_cuts(ceiling: float) -> None:
    """P2.4 (S07, S23) : le plafond coupe l'intervalle qui le traverse, retire ceux
    qui le suivent, et laisse ceux d'avant tels quels."""
    rec = recording([FLAT, FLAT], noise=False, stops=[(300.0, 400.0)])
    plain = intervals_of(rec)
    capped = intervals_of(rec, max_elapsed_s=ceiling)
    assert capped.ceiling_s == ceiling
    assert capped.elapsed_s == plain.elapsed_s
    assert all(i.end_s <= ceiling for i in capped.intervals)
    assert sum(i.elapsed_s for i in capped.intervals) == pytest.approx(
        ceiling, abs=1e-9
    )
    assert [i.truncated for i in capped.intervals] == [
        *(False for _ in capped.intervals[:-1]),
        True,
    ]
    k = len(capped.intervals) - 1
    cut, origin = capped.intervals[-1], plain.intervals[k]
    assert cut.grade == origin.grade
    assert cut.start_s == origin.start_s
    assert 0 < cut.length_m < origin.length_m
    assert capped.after_ceiling == len(plain.intervals) - len(capped.intervals)
    assert capped.after_ceiling_s == pytest.approx(plain.elapsed_s - ceiling, abs=1e-9)
    assert capped.intervals[:-1] == plain.intervals[:k]


def test_s23_a_ceiling_of_one_second() -> None:
    metres = list(range(101))
    capped = intervals_of(line(metres, metres), max_elapsed_s=1.0)
    assert len(capped.intervals) == 1
    only = capped.intervals[0]
    assert only.truncated
    assert (only.start_s, only.end_s) == (0.0, 1.0)
    assert only.length_m == pytest.approx(1.0, abs=1e-6)
    assert capped.after_ceiling == 1
    assert capped.after_ceiling_s == 99.0


def test_a_ceiling_exactly_on_a_bound() -> None:
    """Un plafond pris sur une borne calculée : l'intervalle qui finit au plafond est
    gardé entier, celui qui y commence est retiré (``a >= X``)."""
    metres = list(range(101))
    rec = line(metres, metres)
    plain = intervals_of(rec)
    capped = intervals_of(rec, max_elapsed_s=plain.intervals[0].end_s)
    assert capped.intervals == (plain.intervals[0],)
    assert capped.after_ceiling == 1


def test_the_sweep_of_ceilings_on_bounds() -> None:
    """Le balayage : pour chaque vitesse de 0,5 à 3,9 m/s et chaque fin d'intervalle
    calculée sans plafond, hors la dernière, prise pour plafond, les intervalles sont
    ceux d'origine jusqu'à elle, non coupés — 427 cas."""
    cases = 0
    times = list(range(301))
    for tenth in range(5, 40):
        speed = tenth / 10
        rec = line(times, [speed * t for t in times])
        plain = intervals_of(rec)
        for k, interval in enumerate(plain.intervals[:-1]):
            capped = intervals_of(rec, max_elapsed_s=interval.end_s)
            assert capped.intervals == plain.intervals[: k + 1], (speed, k)
            assert capped.after_ceiling == len(plain.intervals) - (k + 1)
            cases += 1
    assert cases == 427


def test_a_ceiling_during_a_stop() -> None:
    times = list(range(121))
    metres = [t if t <= 30 else (30 if t <= 70 else t - 40) for t in times]
    capped = intervals_of(line(times, metres), max_elapsed_s=50.0)
    assert len(capped.intervals) == 1
    only = capped.intervals[0]
    assert only.truncated
    assert only.end_s == 50.0
    assert only.length_m == pytest.approx(30.0, abs=1e-6)


def test_a_ceiling_beyond_the_trace_cuts_nothing() -> None:
    rec = recording(CLIMB, noise=False)
    capped = intervals_of(rec, max_elapsed_s=1e5)
    assert capped.after_ceiling == 0
    assert capped.after_ceiling_s == 0.0
    assert capped.intervals == intervals_of(rec).intervals


def test_the_cut_keeps_the_grade_and_reads_the_heart_rate_on_its_part() -> None:
    """La coupe garde la pente de l'intervalle du profil ; sa FC se lit sur sa partie
    gardée."""
    rec = with_heart_rate(
        recording(CLIMB, noise=False), lambda t: 150 + min(50, max(0, t - 701))
    )
    plain = intervals_of(rec, hr_lag_s=0.0)
    capped = intervals_of(rec, hr_lag_s=0.0, max_elapsed_s=700.0)
    cut = capped.intervals[-1]
    origin = plain.intervals[len(capped.intervals) - 1]
    assert cut.truncated
    assert cut.grade == origin.grade
    assert cut.grade == pytest.approx(0.15, abs=0.002)
    assert cut.heart_rate_bpm == pytest.approx(150.0, abs=1e-9)
    assert origin.heart_rate_bpm is not None
    assert origin.heart_rate_bpm > 150


# --- La FC --------------------------------------------------------------------------


def test_without_a_heart_rate_channel_every_heart_rate_is_undefined() -> None:
    intervals = intervals_of(recording(CLIMB, noise=False)).intervals
    assert all(i.heart_rate_bpm is None for i in intervals)


def test_a_constant_heart_rate_under_the_lag() -> None:
    """Une FC constante : définie là où la fenêtre décalée tient dans la série,
    indéfinie ailleurs ; sans décalage, partout."""
    rec = with_heart_rate(recording(CLIMB, noise=False), lambda t: 150.0)
    lagged = intervals_of(rec)
    assert any(i.heart_rate_bpm is None for i in lagged.intervals)
    for interval in lagged.intervals:
        if interval.end_s + 60 <= lagged.elapsed_s:
            assert interval.heart_rate_bpm == pytest.approx(150.0, abs=1e-9)
        else:
            assert interval.heart_rate_bpm is None
    for interval in intervals_of(rec, hr_lag_s=0.0).intervals:
        assert interval.heart_rate_bpm == pytest.approx(150.0, abs=1e-9)


@pytest.mark.parametrize("lag", [0.0, 60.0])
def test_the_lag_shifts_the_window(lag: float) -> None:
    """FC de 100 avant 700 s, 180 à partir de 700 s (temps de l'enregistrement, le
    temps de la trace plus 1 s) : la fenêtre décalée lit la FC d'après."""
    rec = with_heart_rate(
        recording(CLIMB, noise=False), lambda t: 100.0 if t < 700 else 180.0
    )
    seen = set()
    for interval in intervals_of(rec, hr_lag_s=lag).intervals:
        if interval.heart_rate_bpm is None:
            continue
        low, high = interval.start_s + lag + 1, interval.end_s + lag + 1
        if high <= 699:
            assert interval.heart_rate_bpm == pytest.approx(100.0, abs=1e-9)
            seen.add("avant")
        elif low >= 700:
            assert interval.heart_rate_bpm == pytest.approx(180.0, abs=1e-9)
            seen.add("après")
        else:
            assert 100 < interval.heart_rate_bpm < 180
            seen.add("entre")
    assert seen == {"avant", "après", "entre"}


def test_the_heart_rate_is_read_in_the_time_of_the_trace() -> None:
    """Positions à partir de 100 s, FC dès 1 s : la FC se lit dans le temps de la
    trace, comme les positions."""
    times = list(range(100, 701))
    hr_times = list(range(1, 701))
    rec = line(
        times,
        [t - 100 for t in times],
        heart_rate=(hr_times, [100.0 if t < 400 else 180.0 for t in hr_times]),
    )
    intervals = intervals_of(rec, hr_lag_s=0.0).intervals
    before = [i for i in intervals if i.end_s <= 299]
    after = [i for i in intervals if i.start_s >= 300]
    assert before
    assert after
    for interval in before:
        assert interval.heart_rate_bpm == pytest.approx(100.0, abs=1e-9)
    for interval in after:
        assert interval.heart_rate_bpm == pytest.approx(180.0, abs=1e-9)


def test_a_heart_rate_gap() -> None:
    """Aucun échantillon strictement entre 600 et 640 s : indéfinie sur les intervalles
    dont la fenêtre perd trop dans le trou, définie sans couverture exigée."""
    rec = with_heart_rate(
        recording(CLIMB, noise=False), lambda t: 150.0, lambda t: not 600 < t < 640
    )
    covered = intervals_of(rec, hr_lag_s=0.0).intervals
    free = intervals_of(rec, hr_lag_s=0.0, hr_min_coverage=0.0).intervals
    losing = [
        k
        for k, i in enumerate(covered)
        if min(i.end_s + 1, 640) - max(i.start_s + 1, 600) > 0.2 * i.elapsed_s + 10
    ]
    assert losing
    for k in losing:
        assert covered[k].heart_rate_bpm is None
        assert free[k].heart_rate_bpm == pytest.approx(150.0, abs=1e-9)


def test_without_heart_rate_the_geometry_is_the_same() -> None:
    rec = recording(CLIMB, noise=False)
    plain = intervals_of(rec).intervals
    with_hr = intervals_of(with_heart_rate(rec, lambda t: 150.0)).intervals
    assert tuple(dataclasses.replace(i, heart_rate_bpm=None) for i in with_hr) == plain


# --- HeartRateSeries.mean -----------------------------------------------------------


def test_s09_the_integral_is_exact() -> None:
    """S09 : un pas coupé par la fenêtre compte pour sa partie dedans, interpolée
    (``0017``, P5.1)."""
    rec = hr_only((0, 10), (140, 180))
    assert mean_of(rec, 0.0, 5.0) == pytest.approx(150.0, abs=1e-9)
    assert mean_of(rec, 2.5, 7.5) == pytest.approx(160.0, abs=1e-9)
    assert mean_of(rec, 0.0, 10.0) == pytest.approx(160.0, abs=1e-9)


@settings(deadline=None)
@given(
    st.floats(min_value=0.0, max_value=90.0),
    st.floats(min_value=0.1, max_value=30.0),
)
def test_a_linear_heart_rate_is_averaged_exactly(a: float, length: float) -> None:
    """Une FC linéaire : la moyenne sur ``[a ; b]``, à 100 % de couverture, est celle
    du milieu."""
    times = list(range(0, 121, 3))
    rec = hr_only(times, [100 + 0.5 * t for t in times])
    b = min(a + length, 120.0)
    assert mean_of(rec, a, b, 1.0) == pytest.approx(100 + 0.25 * (a + b), abs=1e-9)


def test_s10_the_coverage_of_a_gap() -> None:
    """S10 : un trou de 20 s ; la couverture exigée se compare à la tolérance près."""
    times = [*range(41), *range(60, 121)]
    rec = hr_only(times, [150.0 for _ in times])
    assert mean_of(rec, 0.0, 100.0, 0.8) == pytest.approx(150.0, abs=1e-9)
    assert mean_of(rec, 1.0, 100.0, 0.8) is None
    assert mean_of(rec, 1.0, 100.0, 0.79) == pytest.approx(150.0, abs=1e-9)


def test_a_gap_partly_in_the_window() -> None:
    """Le trou n'est pas une FC nulle : la moyenne se divise par la durée couverte."""
    times = [*range(41), *range(70, 151)]
    rec = hr_only(times, [100 + t / 10 for t in times])
    assert mean_of(rec, 50.0, 140.0, 0.8) is None
    assert mean_of(rec, 50.0, 140.0, 0.75) == pytest.approx(110.5, abs=1e-9)


def test_the_window_must_lie_in_the_series() -> None:
    rec = hr_only((10, 20, 30), (150, 150, 150))
    assert mean_of(rec, 9.9, 20.0) is None
    assert mean_of(rec, 10.0, 30.0) == pytest.approx(150.0, abs=1e-9)
    assert mean_of(rec, 20.0, 30.1) is None
    assert mean_of(rec, 20.0, 20.0, 0.0) is None


def test_curve_interval_elapsed() -> None:
    interval = CurveInterval(50.0, 0.0, 10.0, 60.0, 40.0, 10.0, 0.0, None)
    assert interval.elapsed_s == 50.0
