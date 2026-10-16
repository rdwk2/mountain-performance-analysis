"""Contrats d'``interim/`` (``schemas/interim.py``) : invariants, un cas par règle."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from mountain_perf.schemas import (
    TEMPERATURE_RANGE_C,
    ActivityIndex,
    ActivityRecording,
    DeviceProvenance,
    DiscardCount,
    DiscardReason,
    DistanceChannel,
    ElevationChannel,
    ElevationField,
    HeartRateChannel,
    IndexedActivity,
    IndexField,
    IngestionReport,
    PositionChannel,
    ReadFile,
    RecordingMismatch,
    RecordingPart,
    RecordingSession,
    RefusalReason,
    RefusedEntry,
    RefusedFile,
    SourceRef,
    SpeedChannel,
    SpeedField,
    TemperatureChannel,
    TimerEvent,
    TimerEventType,
    TimerTrigger,
    ViewRefusal,
    ViewRefusalCount,
)
from mountain_perf.validation import ContractError

H = "d" * 64
PLUS2 = timezone(timedelta(hours=2))
SOURCE = SourceRef("garmin_fit", "11.zip", H, datetime(2024, 4, 1, 12, tzinfo=PLUS2))


def entry(**changes: Any) -> IndexedActivity:
    base: dict[str, Any] = {
        "activity_ref": "11",
        "source_activity_type": "trail_running",
        "start_time": datetime(2024, 3, 9, 9, 30, tzinfo=PLUS2),
        "elapsed_duration_s": 3723.5,
        "moving_duration_s": 3301.25,
        "distance_m": 10450.75,
        "ascent_m": 812.5,
        "descent_m": 798.25,
        "elevation_corrected": False,
        "average_hr_bpm": 141.0,
        "max_hr_bpm": 173.0,
        "has_recording": True,
        "omitted_fields": (),
    }
    return IndexedActivity(**{**base, **changes})


def recording(**changes: Any) -> ActivityRecording:
    base: dict[str, Any] = {
        "activity_ref": "11",
        "start_time": datetime(2024, 3, 9, 7, 30, tzinfo=UTC),
        "sessions": (RecordingSession("running", "trail", 0.0, 61.0, 59.0, 120.0),),
        "timer_events": (TimerEvent(0.0, TimerEventType.START, None),),
        "position": PositionChannel((0.0, 1.0), (45.0, 45.0001), (6.0, 6.0002)),
        "elevation": None,
        "distance": None,
        "heart_rate": None,
        "speed": None,
        "temperature": None,
        "device": DeviceProvenance("activity", "garmin", 999, None, 12.34, None, None),
        "discarded": (),
        "source": SOURCE,
    }
    return ActivityRecording(**{**base, **changes})


# --- IndexedActivity ----------------------------------------------------------------


def test_entry_keeps_its_local_offset_fixed() -> None:
    e = entry()
    assert e.start_time.utcoffset() == timedelta(hours=2)
    assert isinstance(e.start_time.tzinfo, timezone)


@pytest.mark.parametrize("ref", ["", "a/b", "a\\b", ".", "..", "é1", "a b"])
def test_entry_ref_must_name_a_file(ref: str) -> None:
    with pytest.raises(ContractError, match="activity_ref"):
        entry(activity_ref=ref)


def test_entry_ref_allows_dots_dashes_underscores() -> None:
    assert entry(activity_ref="a.b-c_9").activity_ref == "a.b-c_9"


def test_entry_type_not_empty() -> None:
    with pytest.raises(ContractError, match="source_activity_type"):
        entry(source_activity_type="  ")


def test_entry_start_aware_and_offset_in_range() -> None:
    with pytest.raises(ContractError, match="start_time"):
        entry(start_time=datetime(2024, 3, 9, 9, 30))
    with pytest.raises(ContractError, match="décalage"):
        entry(start_time=datetime(2024, 3, 9, tzinfo=timezone(timedelta(hours=15))))


def test_elapsed_must_be_positive_moving_may_be_zero() -> None:
    with pytest.raises(ContractError, match="elapsed_duration_s"):
        entry(elapsed_duration_s=0.0)
    assert entry(moving_duration_s=0.0).moving_duration_s == 0.0
    with pytest.raises(ContractError, match="moving_duration_s"):
        entry(moving_duration_s=-0.5)


@pytest.mark.parametrize("name", ["distance_m", "ascent_m", "descent_m"])
def test_lengths_non_negative_and_finite(name: str) -> None:
    assert getattr(entry(**{name: 0.0}), name) == 0.0
    with pytest.raises(ContractError, match=name):
        entry(**{name: -1.0})
    with pytest.raises(ContractError, match=name):
        entry(**{name: float("inf")})


@pytest.mark.parametrize("name", ["average_hr_bpm", "max_hr_bpm"])
def test_heart_rates_in_range(name: str) -> None:
    for ok in (20.0, 250.0):
        assert getattr(entry(**{name: ok}), name) == ok
    for bad in (19.9, 250.1, float("nan")):
        with pytest.raises(ContractError, match=name):
            entry(**{name: bad})


def test_no_cross_field_invariant_in_the_index() -> None:
    e = entry(average_hr_bpm=180.0, max_hr_bpm=150.0, moving_duration_s=5000.0)
    assert e.average_hr_bpm == 180.0


def test_omitted_fields_sorted_unique_and_absent() -> None:
    e = entry(
        distance_m=None,
        ascent_m=None,
        omitted_fields=(IndexField.ASCENT, IndexField.DISTANCE),
    )
    assert e.omitted_fields == (IndexField.ASCENT, IndexField.DISTANCE)
    with pytest.raises(ContractError, match="omitted_fields"):
        entry(
            distance_m=None,
            ascent_m=None,
            omitted_fields=(IndexField.DISTANCE, IndexField.ASCENT),
        )
    with pytest.raises(ContractError, match="omitted_fields"):
        entry(
            distance_m=None, omitted_fields=(IndexField.DISTANCE, IndexField.DISTANCE)
        )
    with pytest.raises(ContractError, match="distance_m est omis"):
        entry(omitted_fields=(IndexField.DISTANCE,))
    with pytest.raises(ContractError, match="omitted_fields"):
        entry(omitted_fields=[])


# --- ActivityIndex ------------------------------------------------------------------


def test_index_sorted_by_instant_then_ref() -> None:
    early = entry(activity_ref="9", start_time=datetime(2024, 3, 9, 6, tzinfo=UTC))
    same_a = entry(activity_ref="10")
    same_b = entry(activity_ref="12")
    index = ActivityIndex((early, same_a, same_b), SOURCE)
    assert [e.activity_ref for e in index.entries] == ["9", "10", "12"]
    with pytest.raises(ContractError, match="trié"):
        ActivityIndex((same_b, same_a), SOURCE)
    with pytest.raises(ContractError, match="trié"):
        ActivityIndex((same_a, early), SOURCE)


def test_index_sort_uses_the_instant_not_the_wall_clock() -> None:
    """09:00 à +02:00 (07:00 UTC) précède 08:00 à +00:00."""
    a = entry(activity_ref="a", start_time=datetime(2024, 3, 9, 9, tzinfo=PLUS2))
    b = entry(activity_ref="b", start_time=datetime(2024, 3, 9, 8, tzinfo=UTC))
    assert ActivityIndex((a, b), SOURCE).entries == (a, b)


def test_index_refs_unique() -> None:
    a = entry(activity_ref="5", start_time=datetime(2024, 3, 9, 6, tzinfo=UTC))
    b = entry(activity_ref="5", start_time=datetime(2024, 3, 9, 7, tzinfo=UTC))
    with pytest.raises(ContractError, match="répété"):
        ActivityIndex((a, b), SOURCE)


# --- canaux --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "make",
    [
        lambda t: PositionChannel(t, (45.0,) * len(t), (6.0,) * len(t)),
        lambda t: ElevationChannel(t, (1.0,) * len(t), ElevationField.ALTITUDE),
        lambda t: DistanceChannel(t, (1.0,) * len(t)),
        lambda t: HeartRateChannel(t, (100.0,) * len(t)),
        lambda t: SpeedChannel(t, (1.0,) * len(t), SpeedField.SPEED),
    ],
)
def test_channel_times(make: Any) -> None:
    assert make((0.0, 2.5)).time_s == (0.0, 2.5)
    for bad in ((), (-0.5,), (1.0, 1.0), (2.0, 1.0), (float("nan"),)):
        with pytest.raises(ContractError, match="time_s"):
            make(bad)
    with pytest.raises(ContractError, match="time_s"):
        make([0.0])


def test_channel_lengths_and_ranges() -> None:
    with pytest.raises(ContractError, match="longueurs"):
        PositionChannel((0.0, 1.0), (45.0,), (6.0, 6.0))
    with pytest.raises(ContractError, match="latitude_deg"):
        PositionChannel((0.0,), (90.5,), (6.0,))
    with pytest.raises(ContractError, match="longitude_deg"):
        PositionChannel((0.0,), (45.0,), (-180.5,))
    with pytest.raises(ContractError, match="elevation_m"):
        ElevationChannel((0.0,), (9000.5,), ElevationField.ALTITUDE)
    with pytest.raises(ContractError, match="heart_rate_bpm"):
        HeartRateChannel((0.0,), (19.0,))
    with pytest.raises(ContractError, match="speed_ms"):
        SpeedChannel((0.0,), (-0.1,), SpeedField.SPEED)
    with pytest.raises(ContractError, match="distance_m"):
        DistanceChannel((0.0,), (-0.1,))


def test_distance_non_decreasing() -> None:
    assert DistanceChannel((0.0, 1.0), (5.0, 5.0)).distance_m == (5.0, 5.0)
    with pytest.raises(ContractError, match="distance_m"):
        DistanceChannel((0.0, 1.0), (5.0, 4.5))


# --- sessions, événements, appareil, écarts -----------------------------------------


def test_session_values() -> None:
    assert RecordingSession(None, None, 0.0, None, None, None).sport is None
    with pytest.raises(ContractError, match="sport"):
        RecordingSession("", None, 0.0, None, None, None)
    with pytest.raises(ContractError, match="sub_sport"):
        RecordingSession("running", " ", 0.0, None, None, None)
    with pytest.raises(ContractError, match="start_s"):
        RecordingSession("running", None, -1.0, None, None, None)
    for name in ("elapsed_duration_s", "timer_duration_s", "distance_m"):
        values: list[float | None] = [None, None, None]
        values[
            ["elapsed_duration_s", "timer_duration_s", "distance_m"].index(name)
        ] = -1.0
        with pytest.raises(ContractError, match=name):
            RecordingSession("running", None, 0.0, *values)


def test_timer_event_time() -> None:
    with pytest.raises(ContractError, match="time_s"):
        TimerEvent(-0.5, TimerEventType.STOP, None)


def test_device_values() -> None:
    d = DeviceProvenance(
        None, None, None, datetime(2024, 1, 1, 1, tzinfo=PLUS2), None, None, None
    )
    assert d.time_created == datetime(2023, 12, 31, 23, tzinfo=UTC)
    assert d.time_created is not None
    assert d.time_created.tzinfo is UTC
    with pytest.raises(ContractError, match="product"):
        DeviceProvenance("activity", None, -1, None, None, None, None)
    with pytest.raises(ContractError, match="manufacturer"):
        DeviceProvenance("activity", "", None, None, None, None, None)
    with pytest.raises(ContractError, match="time_created"):
        DeviceProvenance("activity", None, None, datetime(2024, 1, 1), None, None, None)
    with pytest.raises(ContractError, match="software_version"):
        DeviceProvenance("activity", None, None, None, -0.01, None, None)


def test_discard_count_positive() -> None:
    with pytest.raises(ContractError, match="count"):
        DiscardCount(RecordingPart.POSITION, DiscardReason.OUT_OF_RANGE, 0)


# --- ActivityRecording --------------------------------------------------------------


def test_recording_start_in_utc() -> None:
    r = recording(start_time=datetime(2024, 3, 9, 9, 30, tzinfo=PLUS2))
    assert r.start_time == datetime(2024, 3, 9, 7, 30, tzinfo=UTC)
    assert r.start_time.tzinfo is UTC


def test_recording_sessions() -> None:
    s0 = RecordingSession("running", None, 0.0, None, None, None)
    s1 = RecordingSession("cycling", None, 30.0, None, None, None)
    assert recording(sessions=(s0, s1, s1)).sessions[2] is s1
    with pytest.raises(ContractError, match="sessions"):
        recording(sessions=())
    with pytest.raises(ContractError, match=r"sessions\[0\]\.start_s"):
        recording(sessions=(s1,))
    with pytest.raises(ContractError, match=r"sessions\.start_s"):
        recording(sessions=(s0, s1, dataclasses.replace(s1, start_s=10.0)))


def test_recording_timer_events_non_decreasing() -> None:
    a, b = (
        TimerEvent(5.0, TimerEventType.STOP_ALL, None),
        TimerEvent(5.0, TimerEventType.START, None),
    )
    assert recording(timer_events=(a, b)).timer_events == (a, b)
    with pytest.raises(ContractError, match="timer_events"):
        recording(timer_events=(a, TimerEvent(4.0, TimerEventType.START, None)))


def test_recording_needs_a_channel() -> None:
    assert recording(position=None, heart_rate=HeartRateChannel((0.0,), (90.0,)))
    with pytest.raises(ContractError, match="canal"):
        recording(position=None)


def test_recording_discarded_sorted_unique() -> None:
    a = DiscardCount(RecordingPart.HEART_RATE, DiscardReason.OUT_OF_RANGE, 2)
    b = DiscardCount(RecordingPart.POSITION, DiscardReason.BEFORE_START, 1)
    c = DiscardCount(RecordingPart.POSITION, DiscardReason.HALF_POSITION, 3)
    assert recording(discarded=(a, b, c)).discarded == (a, b, c)
    with pytest.raises(ContractError, match="discarded"):
        recording(discarded=(b, a))
    with pytest.raises(ContractError, match="discarded"):
        recording(discarded=(c, b))
    with pytest.raises(ContractError, match="discarded"):
        recording(discarded=(a, dataclasses.replace(a, count=5)))


# --- rapport -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["", "/a", "a/", "a//b", "./a", "a/../b", "c:\\x", "a\\b"]
)
def test_report_names_are_relative(name: str) -> None:
    with pytest.raises(ContractError, match="name"):
        ReadFile(name, H)


def test_report() -> None:
    read = (
        ReadFile("activities/activities.json", H),
        ReadFile("activity_fit/1.zip", H),
    )
    refused = (RefusedFile("activity_fit/1.zip", RefusalReason.UNREADABLE_FIT),)
    entries = (
        RefusedEntry(2, RefusalReason.DUPLICATE_ENTRY),
        RefusedEntry(10, RefusalReason.UNUSABLE_ENTRY),
    )
    views = (
        ViewRefusalCount(ViewRefusal.INVARIANT, "running", 1),
        ViewRefusalCount(ViewRefusal.NO_SPORT, "golf", 3),
        ViewRefusalCount(ViewRefusal.NO_SPORT, "sailing", 2),
    )
    mismatches = (
        RecordingMismatch("10", 3600.0, 60.0, 60.0),
        RecordingMismatch("9", 0.0, 61.5, 60.0),
    )
    report = IngestionReport(
        datetime(2024, 4, 1, 12, tzinfo=PLUS2),
        read,
        refused,
        entries,
        views,
        mismatches,
    )
    assert report.retrieved_at.tzinfo is UTC
    with pytest.raises(ContractError, match="read"):
        IngestionReport(report.retrieved_at, read[::-1], (), (), (), ())
    with pytest.raises(ContractError, match="refused_entries"):
        IngestionReport(report.retrieved_at, read, (), entries[::-1], (), ())
    with pytest.raises(ContractError, match="figurer dans read"):
        IngestionReport(
            report.retrieved_at,
            read[:1],
            (RefusedFile("activity_fit/1.zip", RefusalReason.NOT_ONE_FIT),),
            (),
            (),
            (),
        )
    with pytest.raises(ContractError, match="view_refusals"):
        IngestionReport(report.retrieved_at, read, (), (), views[::-1], ())
    with pytest.raises(ContractError, match="view_refusals"):
        IngestionReport(report.retrieved_at, read, (), (), (views[1], views[1]), ())
    with pytest.raises(ContractError, match="mismatches"):
        IngestionReport(report.retrieved_at, read, (), (), (), mismatches[::-1])
    with pytest.raises(ContractError, match="mismatches"):
        IngestionReport(report.retrieved_at, read, (), (), (), [mismatches[0]])  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="view_refusals"):
        IngestionReport(report.retrieved_at, read, (), (), [views[0]], ())  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="content_hash"):
        ReadFile("a", "D" * 64)
    with pytest.raises(ContractError, match="position"):
        RefusedEntry(-1, RefusalReason.UNUSABLE_ENTRY)


# --- compléments du balayage par mutation ----------------------------------------


def test_entry_elapsed_finite_and_small_positive() -> None:
    assert entry(elapsed_duration_s=0.5).elapsed_duration_s == 0.5
    with pytest.raises(ContractError, match="elapsed_duration_s"):
        entry(elapsed_duration_s=float("inf"))


def test_index_entries_must_be_a_tuple() -> None:
    with pytest.raises(ContractError, match="entries"):
        ActivityIndex([entry()], SOURCE)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("make", "name"),
    [
        (lambda v: PositionChannel((0.0,), v, (6.0,)), "latitude_deg"),
        (lambda v: PositionChannel((0.0,), (45.0,), v), "longitude_deg"),
        (lambda v: ElevationChannel((0.0,), v, ElevationField.ALTITUDE), "elevation_m"),
        (lambda v: DistanceChannel((0.0,), v), "distance_m"),
        (lambda v: HeartRateChannel((0.0,), v), "heart_rate_bpm"),
        (lambda v: SpeedChannel((0.0,), v, SpeedField.SPEED), "speed_ms"),
    ],
)
def test_channel_values_are_finite_tuples(make: Any, name: str) -> None:
    good = 100.0 if name == "heart_rate_bpm" else 1.0
    with pytest.raises(ContractError, match=name):
        make([good])
    with pytest.raises(ContractError, match=name):
        make((float("nan"),))


@pytest.mark.parametrize(
    "make",
    [
        lambda t: PositionChannel(t, (45.0,), (6.0,)),
        lambda t: ElevationChannel(t, (1.0,), ElevationField.ALTITUDE),
        lambda t: DistanceChannel(t, (1.0,)),
        lambda t: HeartRateChannel(t, (100.0,)),
        lambda t: SpeedChannel(t, (1.0,), SpeedField.SPEED),
    ],
)
def test_channel_times_and_values_same_length(make: Any) -> None:
    with pytest.raises(ContractError, match="longueurs"):
        make((0.0, 1.0))


def test_position_longitudes_same_length() -> None:
    with pytest.raises(ContractError, match="longueurs"):
        PositionChannel((0.0,), (45.0,), (6.0, 6.0))


def test_zero_is_allowed_where_the_bound_is_zero() -> None:
    assert SpeedChannel((0.0,), (0.0,), SpeedField.SPEED).speed_ms == (0.0,)
    session = RecordingSession("running", None, 0.0, 0.0, 0.0, 0.0)
    assert session.distance_m == 0.0
    device = DeviceProvenance("activity", None, 0, None, 0.0, None, None)
    assert (device.product, device.software_version) == (0, 0.0)
    assert RecordingSession("running", None, 0.0, 0.5, 0.5, 0.5).timer_duration_s == 0.5
    assert (
        DeviceProvenance(None, None, None, None, 0.5, None, None).software_version
        == 0.5
    )


def test_non_finite_times_name_their_field() -> None:
    with pytest.raises(ContractError, match="start_s"):
        RecordingSession("running", None, float("nan"), None, None, None)
    with pytest.raises(ContractError, match="time_s"):
        TimerEvent(float("nan"), TimerEventType.START, None)


@pytest.mark.parametrize(
    ("changes", "name"),
    [
        ({"activity_ref": "a/b"}, "activity_ref"),
        ({"start_time": datetime(2024, 3, 9, 7, 30)}, "start_time"),
        (
            {"sessions": [RecordingSession("running", None, 0.0, None, None, None)]},
            "sessions",
        ),
        (
            {"timer_events": [TimerEvent(0.0, TimerEventType.START, None)]},
            "timer_events",
        ),
        ({"discarded": []}, "discarded"),
    ],
)
def test_recording_errors_name_their_field(changes: dict[str, Any], name: str) -> None:
    with pytest.raises(ContractError, match=name):
        recording(**changes)


def test_report_errors_name_their_field() -> None:
    at = datetime(2024, 4, 1, tzinfo=UTC)
    read = (ReadFile("a", H), ReadFile("b", H))
    with pytest.raises(ContractError, match="retrieved_at"):
        IngestionReport(datetime(2024, 4, 1), (), (), (), (), ())
    with pytest.raises(ContractError, match="read"):
        IngestionReport(at, list(read), (), (), (), ())  # type: ignore[arg-type]
    refused = (
        RefusedFile("b", RefusalReason.NOT_ONE_FIT),
        RefusedFile("a", RefusalReason.NOT_ONE_FIT),
    )
    with pytest.raises(ContractError, match="refused_files"):
        IngestionReport(at, read, refused, (), (), ())
    with pytest.raises(ContractError, match="name"):
        RefusedFile("../a", RefusalReason.NOT_ONE_FIT)


# --- compléments de la passe experte (révision 2) -----------------------------------


def test_elevation_corrected_is_optional_and_omittable() -> None:
    assert entry(elevation_corrected=None).elevation_corrected is None
    assert entry(elevation_corrected=True).elevation_corrected is True
    omitted = entry(
        elevation_corrected=None, omitted_fields=(IndexField.ELEVATION_CORRECTED,)
    )
    assert omitted.omitted_fields == (IndexField.ELEVATION_CORRECTED,)
    with pytest.raises(ContractError, match="elevation_corrected est omis"):
        entry(
            elevation_corrected=False, omitted_fields=(IndexField.ELEVATION_CORRECTED,)
        )


def test_view_refusal_count() -> None:
    count = ViewRefusalCount(ViewRefusal.NO_SPORT, "golf", 1)
    assert (count.reason, count.source_activity_type, count.count) == (
        ViewRefusal.NO_SPORT,
        "golf",
        1,
    )
    with pytest.raises(ContractError, match="count doit être > 0, reçu 0"):
        ViewRefusalCount(ViewRefusal.NO_SPORT, "golf", 0)
    with pytest.raises(ContractError, match="source_activity_type"):
        ViewRefusalCount(ViewRefusal.NO_SPORT, " ", 1)


def test_recording_mismatch() -> None:
    mismatch = RecordingMismatch("11", -3600.0, None, None)
    assert mismatch.start_offset_s == -3600.0
    assert RecordingMismatch("11", 0.0, 0.0, 0.0).index_elapsed_s == 0.0
    with pytest.raises(ContractError, match="activity_ref"):
        RecordingMismatch("a/b", 0.0, None, None)
    with pytest.raises(ContractError, match="start_offset_s"):
        RecordingMismatch("11", float("nan"), None, None)
    for bad in (-1.0, float("inf")):
        with pytest.raises(ContractError, match="recording_elapsed_s"):
            RecordingMismatch("11", 0.0, bad, None)
        with pytest.raises(ContractError, match="index_elapsed_s"):
            RecordingMismatch("11", 0.0, None, bad)


def test_temperature_channel_contract() -> None:
    assert TEMPERATURE_RANGE_C == (-60.0, 80.0)
    channel = TemperatureChannel((0.0, 1.0), (-60.0, 80.0))
    assert channel.temperature_c == (-60.0, 80.0)
    for bad in (-60.5, 80.5, float("nan")):
        with pytest.raises(ContractError, match="temperature_c"):
            TemperatureChannel((0.0,), (bad,))
    with pytest.raises(ContractError, match="temperature_c"):
        TemperatureChannel((0.0,), [20.0])  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="longueurs"):
        TemperatureChannel((0.0, 1.0), (20.0,))
    with pytest.raises(ContractError, match="time_s"):
        TemperatureChannel((1.0, 1.0), (20.0, 21.0))


def test_a_temperature_channel_is_a_channel() -> None:
    only = recording(position=None, temperature=TemperatureChannel((0.0,), (20.0,)))
    assert only.temperature is not None


def test_timer_event_trigger_and_device_sensors_are_kept() -> None:
    assert TimerEvent(0.0, TimerEventType.STOP, TimerTrigger.AUTO).trigger is (
        TimerTrigger.AUTO
    )
    device = DeviceProvenance(None, None, None, None, None, True, False)
    assert (device.barometer, device.external_heart_rate_sensor) == (True, False)
