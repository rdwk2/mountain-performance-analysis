"""Les colonnes des tables (``mountain_perf.analyse.tables``, ``docs/decisions/0014``) :
chacune vient de ce qu'elle nomme. Les valeurs attendues se recalculent ici depuis les
mesures publiques (``analyse.climbs``), l'index et l'enregistrement ; deux
``interim/`` synthétiques (``tests/fixtures/processed.py``)."""

from __future__ import annotations

import dataclasses
import math
from bisect import bisect_right
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import pytest

from fixtures.processed import (
    COMMIT,
    GAP,
    HEART_RATE_FROM_S,
    HEART_RATE_STEP_S,
    gap_recording,
    write_gap_interim,
    write_interim,
    write_one,
    write_positions_interim,
)
from mountain_perf.analyse.athlete import DEFAULT_SETTINGS
from mountain_perf.analyse.climbs import (
    CLIMB_PARAMETER_SPECS,
    MotionTrack,
    climbs,
    interpolate,
    motion_track,
    state_time_s,
    track_route,
)
from mountain_perf.analyse.quality import (
    QUALITY_PARAMETER_SPECS,
    REGIME_PARAMETER_SPECS,
    altitude_stratum,
    climb_flags,
    grade_stratum,
    regime,
)
from mountain_perf.analyse.stability import (
    STABILITY_PARAMETER_SPECS,
    stability,
    variant_climbs,
)
from mountain_perf.analyse.tables import Tables, build_tables
from mountain_perf.estimation.intervals import HeartRateSeries, heart_rate_series
from mountain_perf.gpx.geo import haversine_m
from mountain_perf.gpx.profile import (
    PROFILE_PARAMETER_SPECS,
    build_profile_with_diagnostics,
)
from mountain_perf.ingest.interim import read_index, read_recording
from mountain_perf.schemas import (
    CENTRAL_CONVENTION_INDEX,
    CLOCK_CONVENTIONS,
    ActivityRecording,
    HeartRateChannel,
    IntervalState,
    ParameterSet,
)

K = CENTRAL_CONVENTION_INDEX
MOVING = IntervalState.MOVING


@pytest.fixture(scope="module")
def walk(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Tables]:
    folder = tmp_path_factory.mktemp("interim")
    write_interim(folder)
    return folder, build_tables(folder, DEFAULT_SETTINGS, commit=COMMIT)


@pytest.fixture(scope="module")
def gap(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Tables]:
    folder = tmp_path_factory.mktemp("trou")
    write_gap_interim(folder)
    return folder, build_tables(folder, DEFAULT_SETTINGS, commit=COMMIT)


@pytest.fixture(scope="module")
def positions(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Tables]:
    folder = tmp_path_factory.mktemp("positions")
    write_positions_interim(folder)
    return folder, build_tables(folder, DEFAULT_SETTINGS, commit=COMMIT)


def _track(folder: Path, ref: str) -> tuple[ActivityRecording, MotionTrack]:
    recording = read_recording(folder, ref)
    track = motion_track(recording)
    assert track is not None
    return recording, track


def _interpolate(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    i = max(0, min(bisect_right(xs, x) - 1, len(xs) - 2))
    return ys[i] + (x - xs[i]) / (xs[i + 1] - xs[i]) * (ys[i + 1] - ys[i])


def test_the_climb_rows_carry_their_measures(walk: tuple[Path, Tables]) -> None:
    """Chaque colonne d'une montée vient de ses mesures, décalées du premier instant
    de la vue, de l'enregistrement et du profil du moteur."""
    folder, tables = walk
    recording, track = _track(folder, "a1")
    measures = climbs(track)
    rows = [c for c in tables.climbs if c.activity_ref == "a1"]
    assert len(rows) == len(measures) == 2
    profile = build_profile_with_diagnostics(
        track_route(track), ParameterSet(PROFILE_PARAMETER_SPECS)
    ).profile
    offset = track.offset_s
    variants = variant_climbs(track)
    climb = ParameterSet(CLIMB_PARAMETER_SPECS)
    quality = ParameterSet(QUALITY_PARAMETER_SPECS)
    regimes = ParameterSet(REGIME_PARAMETER_SPECS)
    (activity,) = [a for a in tables.activities if a.activity_ref == "a1"]
    for row, m in zip(rows, measures, strict=True):
        s = m.span
        assert (row.start_offset_s, row.end_offset_s) == (
            offset + s.start_s,
            offset + s.end_s,
        )
        assert row.elapsed_s == pytest.approx(s.end_s - s.start_s, abs=1e-9)
        assert (
            row.profile_start_m,
            row.profile_end_m,
            row.profile_gain_m,
            row.raw_profile_gain_m,
            row.profile_ascent_m,
            row.gain_m,
        ) == (
            s.profile_start_m,
            s.profile_end_m,
            s.profile_gain_m,
            s.raw_profile_gain_m,
            s.profile_ascent_m,
            s.gain_m,
        )
        assert (
            row.moving_gain_m_by_convention,
            row.stopped_gain_m_by_convention,
            row.undetermined_gain_m_by_convention,
            row.moving_s_by_convention,
            row.stopped_s_by_convention,
            row.undetermined_s_by_convention,
        ) == (
            m.moving_gain_m,
            m.stopped_gain_m,
            m.undetermined_gain_m,
            m.moving_s,
            m.stopped_s,
            m.undetermined_s,
        )
        envelope = m.vertical_speed_envelope_ms
        assert envelope is not None
        assert (
            row.gap_gain_m,
            row.slow_moving_s,
            row.vertical_speed_ms,
            row.moving_or_undetermined_vertical_speed_ms,
            row.vertical_speed_low_ms,
            row.vertical_speed_high_ms,
        ) == (
            m.gap_gain_m,
            m.slow_moving_s,
            m.vertical_speed_ms,
            m.moving_or_undetermined_vertical_speed_ms,
            envelope[0],
            envelope[1],
        )
        assert (
            row.moving_distance_m,
            row.grade,
            row.net_displacement_m,
            row.sinuosity,
            row.low_elevation_m,
            row.high_elevation_m,
            row.moving_mean_elevation_m,
        ) == (
            m.moving_distance_m,
            m.grade,
            m.net_displacement_m,
            m.sinuosity,
            m.low_elevation_m,
            m.high_elevation_m,
            m.moving_mean_elevation_m,
        )
        assert (
            row.step_s,
            row.longest_step_s,
            row.max_vertical_rate_ms,
            row.outside_moving_gain_fraction,
            row.slow_moving_fraction,
        ) == (
            m.step_s,
            m.longest_step_s,
            m.max_vertical_rate_ms,
            m.outside_moving_gain_fraction,
            m.slow_moving_fraction,
        )
        device = recording.device
        assert (
            row.device_manufacturer,
            row.device_product,
            row.software_version,
            row.external_heart_rate_sensor,
        ) == (
            device.manufacturer,
            device.product,
            device.software_version,
            device.external_heart_rate_sensor,
        )
        assert row.local_start_time == recording.start_time + timedelta(
            seconds=offset + s.start_s
        )
        stab = stability(m, variants, ParameterSet(STABILITY_PARAMETER_SPECS))
        assert (row.found_fraction, row.max_relative_deviation, row.stable) == (
            stab.found_fraction,
            stab.max_relative_deviation,
            stab.stable,
        )
        assert row.regime == regime(
            s.gain_m,
            row.sport,
            DEFAULT_SETTINGS.reference_vertical_speed_ms,
            regimes,
        )
        assert row.grade_stratum == grade_stratum(m, climb, regimes, quality)
        assert row.altitude_stratum == altitude_stratum(m, regimes)
        assert row.flags == tuple(
            sorted(
                climb_flags(
                    m,
                    row.sport,
                    barometric=row.barometric,
                    altimetric_drift=activity.altimetric_drift is True,
                    climb=climb,
                    quality=quality,
                )
            )
        )
        assert row.preceding_moving_s == pytest.approx(
            state_time_s(track, K, MOVING, 0.0, s.start_s), abs=1e-9
        )
        assert row.preceding_ascent_m == pytest.approx(
            _interpolate(
                profile.distance_m, profile.cumulative_ascent_m, s.profile_start_m
            ),
            abs=1e-9,
        )
        assert row.preceding_descent_m == pytest.approx(
            _interpolate(
                profile.distance_m, profile.cumulative_descent_m, s.profile_start_m
            ),
            abs=1e-9,
        )


def test_the_activity_rows_carry_the_index_and_the_recording(
    walk: tuple[Path, Tables],
) -> None:
    folder, tables = walk
    index = {e.activity_ref: e for e in read_index(folder).entries}
    row = tables.activities[0]
    entry = index[row.activity_ref]
    assert (
        row.start_time,
        row.index_elapsed_s,
        row.index_moving_s,
        row.index_distance_m,
        row.index_ascent_m,
        row.index_descent_m,
        row.index_elevation_corrected,
        row.index_average_heart_rate_bpm,
        row.index_max_heart_rate_bpm,
        row.has_recording,
    ) == (
        entry.start_time,
        entry.elapsed_duration_s,
        entry.moving_duration_s,
        entry.distance_m,
        entry.ascent_m,
        entry.descent_m,
        entry.elevation_corrected,
        entry.average_hr_bpm,
        entry.max_hr_bpm,
        entry.has_recording,
    )
    recording, track = _track(folder, row.activity_ref)
    device = recording.device
    assert (
        row.session_count,
        row.device_manufacturer,
        row.device_product,
        row.software_version,
        row.barometer,
        row.external_heart_rate_sensor,
    ) == (
        len(recording.sessions),
        device.manufacturer,
        device.product,
        device.software_version,
        device.barometer,
        device.external_heart_rate_sensor,
    )
    assert (row.track_offset_s, row.track_elapsed_s) == (
        track.offset_s,
        track.time_s[-1],
    )
    for field, state in (
        (row.moving_s_by_convention, IntervalState.MOVING),
        (row.stopped_s_by_convention, IntervalState.STOPPED),
        (row.undetermined_s_by_convention, IntervalState.UNDETERMINED),
    ):
        assert field == tuple(
            track.time_in_state_s[(k, state)][-1] for k in range(len(CLOCK_CONVENTIONS))
        )
    profile = build_profile_with_diagnostics(
        track_route(track), ParameterSet(PROFILE_PARAMETER_SPECS)
    ).profile
    assert (
        row.profile_distance_m,
        row.profile_ascent_m,
        row.profile_descent_m,
    ) == (
        profile.distance_m[-1],
        profile.cumulative_ascent_m[-1],
        profile.cumulative_descent_m[-1],
    )
    zs = track.smoothed_elevation_m
    assert row.closure_elevation_m == zs[-1] - zs[0]
    assert row.closure_rate_ms == pytest.approx(abs(zs[-1] - zs[0]) / track.time_s[-1])
    assert (row.step_s, row.longest_step_s, row.gap_count, row.gap_s) == (
        1.0,
        1.0,
        0,
        0.0,
    )
    assert (row.timer_stop_count, row.auto_pause_count) == (1, 1)
    assert row.loop is False
    assert row.mean_heart_rate_bpm == pytest.approx(140.0)
    assert row.heart_rate_coverage == pytest.approx(1.0)
    assert row.mean_temperature_c == pytest.approx(12.0)
    assert (row.flagged_climb_count, row.unstable_climb_count) == (0, 0)
    ski = tables.activities[1]
    assert (ski.flagged_climb_count, ski.climb_count) == (1, 1)


def test_a_position_gap_with_elevation(gap: tuple[Path, Tables]) -> None:
    """Le trou de la vue : compté dans l'activité et dans la montée, et le D+ que le
    canal d'altitude garde pendant lui (10 m : 60 s à 600 m/h)."""
    _, tables = gap
    (activity,) = tables.activities
    (climb,) = tables.climbs
    duration = GAP[1] - GAP[0]
    assert (activity.gap_count, activity.gap_s) == (1, duration)
    assert (climb.gap_count, climb.gap_s) == (1, duration)
    assert activity.position_gap_ascent_m == pytest.approx(
        duration * 600 / 3600, abs=1e-6
    )
    assert climb.gap_gain_m == pytest.approx(duration * 600 / 3600, abs=0.5)


def _moving_pieces(
    track: MotionTrack, start_s: float, end_s: float
) -> list[tuple[float, float, float]]:
    """Les intervalles M (θc) de la vue dans ``[start_s ; end_s]`` : (début, fin,
    durée), instants de l'enregistrement."""
    t, marks, offset = track.time_s, track.states[K], track.offset_s
    out = []
    for i in range(len(t) - 1):
        lo, hi = max(t[i], start_s), min(t[i + 1], end_s)
        if marks[i] is MOVING and hi > lo:
            out.append((t[i] + offset, t[i + 1] + offset, hi - lo))
    return out


def _heart_rate(at_s: float) -> float | None:
    if at_s < HEART_RATE_FROM_S:
        return None
    return 100.0 if at_s < HEART_RATE_STEP_S else 180.0


def test_heart_rate_in_moving_time_its_coverage_and_its_second_half(
    gap: tuple[Path, Tables],
) -> None:
    """La FC d'une montée : moyenne des intervalles M qui ont une FC à leur instant de
    départ, pondérée par leur durée ; la part du temps M couverte ; la moyenne de la
    seconde moitié du temps M."""
    folder, tables = gap
    (climb,) = tables.climbs
    _, track = _track(folder, "g1")
    offset = track.offset_s
    pieces = _moving_pieces(
        track, climb.start_offset_s - offset, climb.end_offset_s - offset
    )
    total = math.fsum(d for _, _, d in pieces)
    with_hr = [(d, _heart_rate(a)) for a, _, d in pieces if _heart_rate(a) is not None]
    covered = math.fsum(d for d, _ in with_hr)
    expected = math.fsum(d * v for d, v in with_hr if v is not None) / covered
    assert climb.moving_heart_rate_coverage == pytest.approx(covered / total)
    assert 0.3 < climb.moving_heart_rate_coverage < 0.7
    assert climb.moving_mean_heart_rate_bpm == pytest.approx(expected)
    run, second = 0.0, []
    for a, _, d in pieces:
        if run >= total / 2:
            second.append((d, _heart_rate(a)))
        run += d
    kept = [(d, v) for d, v in second if v is not None]
    second_mean = math.fsum(d * v for d, v in kept if v is not None) / math.fsum(
        d for d, _ in kept
    )
    assert climb.second_half_mean_heart_rate_bpm == pytest.approx(second_mean)
    assert second_mean > expected + 1
    assert climb.moving_mean_temperature_c == pytest.approx(10.0)
    (activity,) = tables.activities
    assert activity.mean_temperature_c == pytest.approx(10.0)
    assert 0.3 < (activity.heart_rate_coverage or 0.0) < 0.7
    values = [_heart_rate(t + offset) for t in track.time_s]
    present = [v for v in values if v is not None]
    assert activity.heart_rate_coverage == pytest.approx(len(present) / len(values))
    assert activity.mean_heart_rate_bpm == pytest.approx(
        math.fsum(present) / len(present)
    )


def _support_mean(
    series: HeartRateSeries, pieces: Sequence[tuple[float, float]], lag_s: float
) -> tuple[float | None, float]:
    """La FC d'un support, refaite depuis l'outil public : chaque morceau décalé, les
    sommes, la division par la durée couverte, la couverture bornée à 1."""
    total = math.fsum(b - a for a, b in pieces)
    parts = [series.integral(a + lag_s, b + lag_s) for a, b in pieces]
    integral = math.fsum(i for i, _ in parts)
    covered = math.fsum(c for _, c in parts)
    coverage = min(1.0, covered / total)
    return (integral / covered if coverage > 0 else None), coverage


def test_the_heart_rate_columns_come_from_the_common_window(
    gap: tuple[Path, Tables],
) -> None:
    """Les huit colonnes de la FC décalée (AN3-1a) : refaites depuis
    ``heart_rate_series`` et ``HeartRateSeries.integral``, sur les pas M de la montée
    rognés à ses bornes, sans ``analyse.heart_rate``."""
    folder, tables = gap
    (climb,) = tables.climbs
    recording, track = _track(folder, "g1")
    offset = track.offset_s
    series = heart_rate_series(recording, offset)
    assert series is not None
    start_s, end_s = climb.start_offset_s - offset, climb.end_offset_s - offset
    moving = [
        (max(a - offset, start_s), min(b - offset, end_s))
        for a, b, _ in _moving_pieces(track, start_s, end_s)
    ]
    total = math.fsum(b - a for a, b in moving)
    half, run = total / 2, 0.0
    second: list[tuple[float, float]] = []
    for a, b in moving:
        if second:
            second.append((a, b))
        elif run + (b - a) > half:
            second.append((a + (half - run), b))
        run += b - a
    expected = {
        "lagged_moving": _support_mean(series, moving, 60.0),
        "unlagged_moving": _support_mean(series, moving, 0.0),
        "lagged_second_half": _support_mean(series, second, 60.0),
        "lagged_elapsed": _support_mean(series, [(start_s, end_s)], 60.0),
    }
    for name, (bpm, coverage) in expected.items():
        assert bpm is not None, name
        assert getattr(climb, f"{name}_heart_rate_bpm") == pytest.approx(
            bpm, rel=1e-9
        ), name
        assert getattr(climb, f"{name}_heart_rate_coverage") == pytest.approx(
            coverage, rel=1e-9
        ), name
    lagged, unlagged = expected["lagged_moving"], expected["unlagged_moving"]
    lagged_half = expected["lagged_second_half"]
    assert lagged[0] != pytest.approx(unlagged[0])
    assert lagged_half[0] != pytest.approx(lagged[0])
    assert lagged_half[0] != pytest.approx(unlagged[0])
    assert lagged[1] != pytest.approx(unlagged[1])


GAP_HEART_RATE = (GAP[0] + 60.0, GAP[1] + 60.0)
"""Le trou de ``g1`` décalé de 60 s : la FC y vaut 180, et 100 partout ailleurs."""


@pytest.fixture(scope="module")
def gap_heart_rate(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Tables]:
    """``g1`` avec une FC sur toute l'activité, qui change pendant le temps non M de la
    montée (le trou de la vue, décalé)."""
    folder = tmp_path_factory.mktemp("trou_fc")
    rec = gap_recording()
    assert rec.elevation is not None
    times = rec.elevation.time_s
    values = tuple(
        180.0 if GAP_HEART_RATE[0] <= t <= GAP_HEART_RATE[1] else 100.0 for t in times
    )
    write_one(
        folder,
        dataclasses.replace(rec, heart_rate=HeartRateChannel(times, values)),
    )
    return folder, build_tables(folder, DEFAULT_SETTINGS, commit=COMMIT)


def test_the_lagged_moving_and_elapsed_heart_rates_differ(
    gap_heart_rate: tuple[Path, Tables],
) -> None:
    """La FC décalée du temps M et celle de la fenêtre écoulée, refaites depuis l'outil
    public, sans ``analyse.heart_rate`` : la fenêtre écoulée garde le trou décalé, où
    la FC est haute ; le temps M, non."""
    folder, tables = gap_heart_rate
    (climb,) = tables.climbs
    recording, track = _track(folder, "g1")
    offset = track.offset_s
    series = heart_rate_series(recording, offset)
    assert series is not None
    start_s, end_s = climb.start_offset_s - offset, climb.end_offset_s - offset
    moving = [
        (max(a - offset, start_s), min(b - offset, end_s))
        for a, b, _ in _moving_pieces(track, start_s, end_s)
    ]
    on_moving = _support_mean(series, moving, 60.0)
    on_elapsed = _support_mean(series, [(start_s, end_s)], 60.0)
    assert on_moving[0] is not None
    assert on_elapsed[0] is not None
    assert climb.lagged_moving_heart_rate_bpm == pytest.approx(on_moving[0], rel=1e-9)
    assert climb.lagged_elapsed_heart_rate_bpm == pytest.approx(on_elapsed[0], rel=1e-9)
    assert on_elapsed[0] - on_moving[0] >= 1.0


def _nearest(times: Sequence[float], at_s: float) -> int:
    """L'indice de l'instant de ``times`` le plus proche de ``at_s``, à moins de
    ``1e-6`` s."""
    i = min(range(len(times)), key=lambda k: abs(times[k] - at_s))
    assert abs(times[i] - at_s) < 1e-6
    return i


def test_the_climb_positions_are_the_view_at_the_bounds(
    positions: tuple[Path, Tables], walk: tuple[Path, Tables]
) -> None:
    """Les quatre positions d'une montée sont celles de la vue à ses bornes, lues dans
    le temps de la trace (AN3-3a, ``0014``) ; leur distance est exactement le
    déplacement net."""
    folder, tables = positions
    recording, track = _track(folder, "p1")
    rows = [c for c in tables.climbs if c.activity_ref == "p1"]
    # Le monde distingue ce qu'il doit distinguer.
    assert rows
    assert track.offset_s >= 10.0
    for row in rows:
        assert row.start_latitude_deg != row.end_latitude_deg
        assert row.start_longitude_deg != row.end_longitude_deg
        wrong = interpolate(track.time_s, track.latitude_deg, row.start_offset_s)
        assert abs(wrong - row.start_latitude_deg) > 1e-9
    position = recording.position
    assert position is not None
    for row in rows:
        for at_s, lat, lon in (
            (row.start_offset_s, row.start_latitude_deg, row.start_longitude_deg),
            (row.end_offset_s, row.end_latitude_deg, row.end_longitude_deg),
        ):
            i = _nearest(position.time_s, at_s)
            assert lat == pytest.approx(position.latitude_deg[i], rel=0, abs=1e-12)
            assert lon == pytest.approx(position.longitude_deg[i], rel=0, abs=1e-12)
        assert (
            haversine_m(
                row.start_latitude_deg,
                row.start_longitude_deg,
                row.end_latitude_deg,
                row.end_longitude_deg,
            )
            == row.net_displacement_m
        )
    _, walk_tables = walk
    walk_rows = [c for c in walk_tables.climbs if c.activity_ref == "a1"]
    assert walk_rows
    for row in walk_rows:
        assert (
            haversine_m(
                row.start_latitude_deg,
                row.start_longitude_deg,
                row.end_latitude_deg,
                row.end_longitude_deg,
            )
            == row.net_displacement_m
        )
