"""Contrats d'``interim/`` (``schemas/interim.py``) : invariants, un cas par règle."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from mountain_perf.schemas import (
    INTERIM_FORMAT_VERSION,
    TEMPERATURE_RANGE_C,
    ActivityIndex,
    ActivityRecording,
    DeviceProvenance,
    DiscardCount,
    DiscardReason,
    DistanceChannel,
    ElevationChannel,
    ElevationField,
    ExportReport,
    FieldDifferenceCount,
    HeartRateChannel,
    IndexDifference,
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
    RetiredActivity,
    SourceRef,
    SpeedChannel,
    SpeedField,
    TemperatureChannel,
    TimerEvent,
    TimerEventType,
    TimerTrigger,
    ViewRefusal,
    ViewRefusalCount,
    require_export_name,
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
        "training_load": 87.5,
        "has_recording": True,
        "omitted_fields": (),
        "source": SOURCE,
    }
    return IndexedActivity(**{**base, **changes})


LATER = dataclasses.replace(
    SOURCE, content_hash="e" * 64, retrieved_at=SOURCE.retrieved_at + timedelta(days=30)
)


def export_report(**changes: Any) -> ExportReport:
    base: dict[str, Any] = {
        "name": "garmin_a",
        "index": SOURCE,
        "period_start": datetime(2024, 3, 9, 9, 30, tzinfo=PLUS2),
        "entries": 3,
        "refused_entries": (),
        "archives": 2,
    }
    return ExportReport(**{**base, **changes})


def report(**changes: Any) -> IngestionReport:
    base: dict[str, Any] = {
        "exports": (export_report(),),
        "read": (),
        "refused_files": (),
        "retired": (),
        "view_refusals": (),
        "mismatches": (),
        "index_differences": (),
        "fit_differences": 0,
        "recordings_from_other_export": 0,
    }
    return IngestionReport(**{**base, **changes})


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
    index = ActivityIndex((early, same_a, same_b), (SOURCE,))
    assert [e.activity_ref for e in index.entries] == ["9", "10", "12"]
    with pytest.raises(ContractError, match="trié"):
        ActivityIndex((same_b, same_a), (SOURCE,))
    with pytest.raises(ContractError, match="trié"):
        ActivityIndex((same_a, early), (SOURCE,))


def test_index_sort_uses_the_instant_not_the_wall_clock() -> None:
    """09:00 à +02:00 (07:00 UTC) précède 08:00 à +00:00."""
    a = entry(activity_ref="a", start_time=datetime(2024, 3, 9, 9, tzinfo=PLUS2))
    b = entry(activity_ref="b", start_time=datetime(2024, 3, 9, 8, tzinfo=UTC))
    assert ActivityIndex((a, b), (SOURCE,)).entries == (a, b)


def test_index_refs_unique() -> None:
    a = entry(activity_ref="5", start_time=datetime(2024, 3, 9, 6, tzinfo=UTC))
    b = entry(activity_ref="5", start_time=datetime(2024, 3, 9, 7, tzinfo=UTC))
    with pytest.raises(ContractError, match="répété"):
        ActivityIndex((a, b), (SOURCE,))


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
        ReadFile("a/activities/activities.json", H),
        ReadFile("a/activity_fit/1.zip", H),
    )
    refused = (RefusedFile("a/activity_fit/1.zip", RefusalReason.UNREADABLE_FIT),)
    views = (
        ViewRefusalCount(ViewRefusal.INVARIANT, "running", 1),
        ViewRefusalCount(ViewRefusal.NO_SPORT, "golf", 3),
        ViewRefusalCount(ViewRefusal.NO_SPORT, "sailing", 2),
    )
    mismatches = (
        RecordingMismatch("10", 3600.0, 60.0, 60.0),
        RecordingMismatch("9", 0.0, 61.5, 60.0),
    )
    retired = (RetiredActivity("10", "b"), RetiredActivity("9", "b"))
    differences = (
        FieldDifferenceCount(IndexDifference.DISTANCE, 2),
        FieldDifferenceCount(IndexDifference.START_TIME, 1),
    )
    exports = (export_report(), export_report(name="b", index=LATER))
    full = report(
        exports=exports,
        read=read,
        refused_files=refused,
        retired=retired,
        view_refusals=views,
        mismatches=mismatches,
        index_differences=differences,
        fit_differences=1,
        recordings_from_other_export=2,
    )
    assert [item.name for item in full.exports] == ["garmin_a", "b"]
    assert (full.fit_differences, full.recordings_from_other_export) == (1, 2)
    assert report(fit_differences=0, recordings_from_other_export=0).exports
    for changes, name in (
        ({"read": read[::-1]}, "read"),
        (
            {
                "read": read[:1],
                "refused_files": (
                    RefusedFile("a/activity_fit/1.zip", RefusalReason.NOT_ONE_FIT),
                ),
            },
            "figurer dans read",
        ),
        ({"view_refusals": views[::-1]}, "view_refusals"),
        ({"view_refusals": (views[1], views[1])}, "view_refusals"),
        ({"view_refusals": [views[0]]}, "view_refusals"),
        ({"mismatches": mismatches[::-1]}, "mismatches"),
        ({"mismatches": [mismatches[0]]}, "mismatches"),
        ({"retired": retired[::-1]}, "retired"),
        ({"retired": list(retired)}, "retired"),
        ({"retired": (RetiredActivity("9", "c"),)}, "retired"),
        ({"index_differences": differences[::-1]}, "index_differences"),
        ({"index_differences": [differences[0]]}, "index_differences"),
        ({"exports": exports[::-1]}, "exports"),
        ({"exports": ()}, "exports"),
        ({"exports": list(exports)}, "exports"),
        ({"exports": (export_report(), export_report(index=LATER))}, "répété"),
        ({"fit_differences": -1}, "fit_differences"),
        ({"recordings_from_other_export": -1}, "recordings_from_other_export"),
    ):
        with pytest.raises(ContractError, match=name):
            report(**changes)
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
        ActivityIndex([entry()], (SOURCE,))  # type: ignore[arg-type]


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
    read = (ReadFile("a", H), ReadFile("b", H))
    with pytest.raises(ContractError, match="read"):
        report(read=list(read))
    refused = (
        RefusedFile("b", RefusalReason.NOT_ONE_FIT),
        RefusedFile("a", RefusalReason.NOT_ONE_FIT),
    )
    with pytest.raises(ContractError, match="refused_files"):
        report(read=read, refused_files=refused)
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


# --- format 2 (AN2-0) : plusieurs exports, la charge selon Garmin ---------------------


def test_the_interim_format_is_two() -> None:
    assert INTERIM_FORMAT_VERSION == 2


def test_training_load_is_optional_finite_and_not_negative() -> None:
    assert entry(training_load=None).training_load is None
    assert entry(training_load=0.0).training_load == 0.0
    for bad in (-0.25, float("inf"), float("nan")):
        with pytest.raises(ContractError, match="training_load"):
            entry(training_load=bad)
    omitted = entry(training_load=None, omitted_fields=(IndexField.TRAINING_LOAD,))
    assert omitted.omitted_fields == (IndexField.TRAINING_LOAD,)
    with pytest.raises(ContractError, match="training_load est omis"):
        entry(omitted_fields=(IndexField.TRAINING_LOAD,))


def test_index_exports_are_sorted_by_instant_and_known_to_each_entry() -> None:
    a = entry(activity_ref="9", source=LATER)
    b = entry(activity_ref="10", start_time=datetime(2024, 3, 10, tzinfo=UTC))
    index = ActivityIndex((a, b), (SOURCE, LATER))
    assert index.exports == (SOURCE, LATER)
    assert [e.source for e in index.entries] == [LATER, SOURCE]
    assert ActivityIndex((), (SOURCE,)).entries == ()
    other_hash = dataclasses.replace(SOURCE, content_hash="f" * 64)
    for entries, exports, name in (
        ((a,), (LATER, SOURCE), "exports"),
        ((), (), "exports"),
        ((), [SOURCE], "exports"),
        ((), (SOURCE, other_hash), "exports"),
        ((a,), (SOURCE,), "l'un des exports"),
        ((entry(source=other_hash),), (SOURCE,), "l'un des exports"),
    ):
        with pytest.raises(ContractError, match=name):
            ActivityIndex(entries, exports)  # type: ignore[arg-type]


def test_export_report() -> None:
    made = export_report()
    assert made.period_start is not None
    assert made.period_start.tzinfo is UTC
    assert made.period_start == datetime(2024, 3, 9, 7, 30, tzinfo=UTC)
    assert export_report(entries=0, period_start=None).period_start is None
    at_acquisition = export_report(period_start=SOURCE.retrieved_at)
    assert at_acquisition.period_start == SOURCE.retrieved_at
    assert export_report(archives=0, entries=1).archives == 0
    refused = (
        RefusedEntry(1, RefusalReason.UNUSABLE_ENTRY),
        RefusedEntry(3, RefusalReason.DUPLICATE_ENTRY),
    )
    assert export_report(refused_entries=refused).refused_entries == refused
    for changes, name in (
        ({"name": "a/b"}, "nom d'un export"),
        ({"name": ".."}, "nom d'un export"),
        ({"name": "é"}, "nom d'un export"),
        ({"entries": -1, "period_start": None}, "entries doit être"),
        ({"archives": -1}, "archives doit être"),
        ({"entries": 0}, "period_start"),
        ({"period_start": None}, "period_start"),
        ({"period_start": datetime(2024, 3, 9, 9, 30)}, "period_start"),
        (
            {"period_start": SOURCE.retrieved_at + timedelta(microseconds=1)},
            "ne peut pas suivre",
        ),
        ({"refused_entries": refused[::-1]}, "refused_entries"),
        ({"refused_entries": list(refused)}, "refused_entries"),
    ):
        with pytest.raises(ContractError, match=name):
            export_report(**changes)


def test_retired_activity_and_difference_count() -> None:
    assert RetiredActivity("12", "garmin_b") == RetiredActivity("12", "garmin_b")
    with pytest.raises(ContractError, match="activity_ref"):
        RetiredActivity("1 2", "garmin_b")
    with pytest.raises(ContractError, match="nom d'un export"):
        RetiredActivity("12", "b/c")
    assert FieldDifferenceCount(IndexDifference.TRAINING_LOAD, 1).count == 1
    with pytest.raises(ContractError, match="count"):
        FieldDifferenceCount(IndexDifference.TRAINING_LOAD, 0)


def test_index_difference_names_the_value_fields_of_an_entry() -> None:
    fields = {field.name for field in dataclasses.fields(IndexedActivity)}
    compared = {difference.value for difference in IndexDifference}
    assert compared == fields - {
        "activity_ref",
        "has_recording",
        "omitted_fields",
        "source",
    }


def test_export_names() -> None:
    for good in ("garmin_2024-04-01", "a", "A.b-c_1"):
        require_export_name(good)
    for bad in ("", ".", "..", "a/b", "a b", "é", "a:b"):
        with pytest.raises(ContractError, match="nom d'un export"):
            require_export_name(bad)
