"""Les vues du moteur sur ``interim/`` (``ingest/views.py``, ``0013`` point 2)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Any

import pytest

from mountain_perf.ingest.types import SOURCE_TYPE_SPORTS
from mountain_perf.ingest.views import (
    GPS_GAP_THRESHOLD_S,
    ActivityView,
    activity_view,
    stream_view,
)
from mountain_perf.schemas import (
    ActivityIndex,
    ActivityRecording,
    DistanceChannel,
    ElevationChannel,
    ElevationField,
    HeartRateChannel,
    PositionChannel,
    QualityFlag,
    SpeedChannel,
    SpeedField,
    Sport,
    TimerEvent,
    TimerEventType,
    ViewRefusal,
)
from test_schemas_interim import SOURCE, entry, recording

INDEX_SOURCE = dataclasses.replace(
    SOURCE, kind="garmin_activities", identifier="activities.json"
)


def _view(**changes: Any) -> ActivityView:
    e = entry(**changes)
    return activity_view(ActivityIndex((e,), INDEX_SOURCE), e)


# --- Activity ------------------------------------------------------------------------


def test_activity_view_copies_every_field() -> None:
    view = _view()
    a = view.activity
    assert view.refusal is None
    assert a is not None
    assert (a.activity_ref, a.sport, a.source_activity_type) == (
        "11",
        Sport.FOOT,
        "trail_running",
    )
    assert a.start_time == entry().start_time
    assert (a.elapsed_duration_s, a.moving_duration_s) == (3723.5, 3301.25)
    assert (a.distance_m, a.ascent_m, a.descent_m) == (10450.75, 812.5, 798.25)
    assert (a.average_hr_bpm, a.max_hr_bpm) == (141.0, 173.0)
    assert a.stream_ref == "11"
    assert a.source == INDEX_SOURCE
    assert a.quality_flags == frozenset()


def test_activity_view_without_recording_has_no_stream_ref() -> None:
    a = _view(has_recording=False).activity
    assert a is not None
    assert a.stream_ref is None


def test_activity_view_optional_heart_rates_stay_optional() -> None:
    a = _view(average_hr_bpm=None, max_hr_bpm=None).activity
    assert a is not None
    assert a.average_hr_bpm is None


@pytest.mark.parametrize(
    ("kind", "sport"),
    [
        ("mountain_biking", Sport.MTB),
        ("backcountry_skiing", Sport.SKI_TOURING),
        ("hiking", Sport.FOOT),
    ],
)
def test_activity_view_maps_the_type(kind: str, sport: Sport) -> None:
    a = _view(source_activity_type=kind).activity
    assert a is not None
    assert a.sport is sport


def test_type_table_is_exactly_the_reviewed_one() -> None:
    assert dict(SOURCE_TYPE_SPORTS) == {
        "running": Sport.FOOT,
        "street_running": Sport.FOOT,
        "trail_running": Sport.FOOT,
        "track_running": Sport.FOOT,
        "treadmill_running": Sport.FOOT,
        "walking": Sport.FOOT,
        "casual_walking": Sport.FOOT,
        "speed_walking": Sport.FOOT,
        "hiking": Sport.FOOT,
        "mountaineering": Sport.FOOT,
        "backcountry_skiing": Sport.SKI_TOURING,
        "mountain_biking": Sport.MTB,
    }


@pytest.mark.parametrize(
    "name",
    ["elapsed_duration_s", "moving_duration_s", "distance_m", "ascent_m", "descent_m"],
)
def test_activity_view_missing_field(name: str) -> None:
    assert _view(**{name: None}).refusal is ViewRefusal.MISSING_FIELD


@pytest.mark.parametrize(
    "changes",
    [
        {"moving_duration_s": 0.0},
        {"moving_duration_s": 4000.0},
        {"average_hr_bpm": 180.0},
    ],
)
def test_activity_view_invariant(changes: dict[str, float]) -> None:
    assert _view(**changes).refusal is ViewRefusal.INVARIANT


def test_refusal_order_type_then_missing_then_invariant() -> None:
    """Un type sans famille et un champ manquant : NO_SPORT ; un champ manquant et un
    invariant violé : MISSING_FIELD."""
    assert (
        _view(source_activity_type="golf", distance_m=None).refusal
        is ViewRefusal.NO_SPORT
    )
    assert (
        _view(distance_m=None, moving_duration_s=0.0).refusal
        is ViewRefusal.MISSING_FIELD
    )


# --- TrackPointStream ----------------------------------------------------------------


def _rec(**changes: Any) -> ActivityRecording:
    base = {
        "position": PositionChannel(
            (0.0, 1.0, 2.0, 13.5),
            (45.0, 45.0001, 45.0002, 45.0003),
            (6.0, 6.0, 6.0001, 6.0002),
        ),
        "elevation": ElevationChannel(
            (1.0, 2.0, 3.0, 13.5),
            (1001.0, 1002.0, 1003.0, 1013.5),
            ElevationField.ENHANCED_ALTITUDE,
        ),
        "heart_rate": HeartRateChannel((0.0, 2.0, 13.5), (100.0, 102.0, 113.0)),
        "distance": DistanceChannel((0.0, 1.0, 2.0, 13.5), (0.0, 11.0, 22.0, 150.0)),
        "speed": SpeedChannel(
            (0.0, 1.0, 2.0), (2.0, 2.1, 2.2), SpeedField.ENHANCED_SPEED
        ),
    }
    return recording(**{**base, **changes})


def test_positions_alone() -> None:
    view = stream_view(_rec())
    s = view.stream
    assert s is not None
    assert view.positions_without_requested == 0
    assert s.time_s == (0.0, 1.0, 2.0, 13.5)
    assert s.latitude_deg == (45.0, 45.0001, 45.0002, 45.0003)
    assert s.longitude_deg == (6.0, 6.0, 6.0001, 6.0002)
    assert (s.elevation_m, s.distance_m, s.speed_ms, s.heart_rate_bpm) == (None,) * 4
    assert s.activity_ref == "11"
    assert s.source == SOURCE


def test_requested_channels_intersect_the_instants() -> None:
    view = stream_view(_rec(), elevation=True, heart_rate=True)
    s = view.stream
    assert s is not None
    assert s.time_s == (2.0, 13.5)
    assert s.elevation_m == (1002.0, 1013.5)
    assert s.heart_rate_bpm == (102.0, 113.0)
    assert view.positions_without_requested == 2


def test_each_channel_lands_in_its_column() -> None:
    s = stream_view(_rec(), distance=True, speed=True).stream
    assert s is not None
    assert s.time_s == (0.0, 1.0, 2.0)
    assert s.distance_m == (0.0, 11.0, 22.0)
    assert s.speed_ms == (2.0, 2.1, 2.2)


@pytest.mark.parametrize("channel", ["elevation", "distance", "heart_rate", "speed"])
def test_missing_requested_channel_gives_no_view(channel: str) -> None:
    view = stream_view(_rec(**{channel: None}), **{channel: True})
    assert view.stream is None
    assert view.positions_without_requested == 4


def test_late_positions_without_gap_have_no_flag() -> None:
    rec = _rec(position=PositionChannel((100.0, 101.0), (45.0, 45.0), (6.0, 6.0)))
    s = stream_view(rec).stream
    assert s is not None
    assert s.quality_flags == frozenset()


def test_no_positions_no_view() -> None:
    view = stream_view(_rec(position=None))
    assert view.stream is None
    assert view.positions_without_requested == 0


def test_gps_gap_threshold_on_the_position_channel() -> None:
    assert GPS_GAP_THRESHOLD_S == 10.0
    gap = stream_view(_rec()).stream
    assert gap is not None
    assert gap.quality_flags == frozenset({QualityFlag.GPS_GAP})
    edge = _rec(position=PositionChannel((0.0, 10.0), (45.0, 45.0), (6.0, 6.0)))
    s = stream_view(edge).stream
    assert s is not None
    assert s.quality_flags == frozenset()


def test_gap_is_read_on_the_view() -> None:
    """Positions chaque seconde de 0 à 30 s, FC absente de 5 à 20 s : la vue avec la FC
    saute de 4 à 21 s (un trou que le canal des positions n'a pas) ; sans la FC, aucun
    trou."""
    times = tuple(float(t) for t in range(31))
    hr_times = tuple(t for t in times if not 5 <= t <= 20)
    rec = _rec(
        position=PositionChannel(times, (45.0,) * 31, (6.0,) * 31),
        heart_rate=HeartRateChannel(hr_times, (120.0,) * len(hr_times)),
    )
    with_hr = stream_view(rec, heart_rate=True)
    assert with_hr.stream is not None
    assert with_hr.positions_without_requested == 16
    assert with_hr.stream.quality_flags == frozenset({QualityFlag.GPS_GAP})
    without = stream_view(rec).stream
    assert without is not None
    assert without.quality_flags == frozenset()


def test_an_intersection_gap_of_ten_seconds_is_not_a_gap() -> None:
    """Le seuil vaut aussi pour un trou de l'intersection : 10 s exactement n'en est
    pas un."""
    times = tuple(float(t) for t in range(21))
    hr_times = tuple(t for t in times if not 1 <= t <= 9)
    rec = _rec(
        position=PositionChannel(times, (45.0,) * 21, (6.0,) * 21),
        heart_rate=HeartRateChannel(hr_times, (120.0,) * len(hr_times)),
    )
    s = stream_view(rec, heart_rate=True).stream
    assert s is not None
    assert s.time_s[:2] == (0.0, 10.0)
    assert s.quality_flags == frozenset()


def test_start_time_is_not_needed_by_the_view() -> None:
    rec = _rec(start_time=datetime(2030, 1, 1, tzinfo=UTC))
    assert stream_view(rec).stream is not None


def test_timer_events_do_not_set_the_flag() -> None:
    """La vue ne lit pas les événements du chronomètre : un arrêt qui ne sépare pas deux
    instants de plus de 10 s ne pose pas de drapeau."""
    times = tuple(float(t) for t in range(31))
    rec = _rec(
        position=PositionChannel(times, (45.0,) * 31, (6.0,) * 31),
        timer_events=(
            TimerEvent(0.0, TimerEventType.START, None),
            TimerEvent(5.0, TimerEventType.STOP, None),
            TimerEvent(6.0, TimerEventType.START, None),
            TimerEvent(30.0, TimerEventType.STOP_ALL, None),
        ),
    )
    s = stream_view(rec).stream
    assert s is not None
    assert s.quality_flags == frozenset()


def test_a_gap_covered_by_a_timer_pause_still_sets_the_flag() -> None:
    """Un trou de plus de 10 s pendant une pause du chronomètre pose le drapeau : la
    vue ne lit pas les pauses, elle n'en exempte aucun trou (``0013``, précision 6)."""
    times = (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 30.0, 31.0, 32.0)
    rec = _rec(
        position=PositionChannel(times, (45.0,) * 9, (6.0,) * 9),
        timer_events=(
            TimerEvent(0.0, TimerEventType.START, None),
            TimerEvent(5.0, TimerEventType.STOP, None),
            TimerEvent(30.0, TimerEventType.START, None),
            TimerEvent(32.0, TimerEventType.STOP_ALL, None),
        ),
    )
    s = stream_view(rec).stream
    assert s is not None
    assert s.quality_flags == frozenset({QualityFlag.GPS_GAP})
