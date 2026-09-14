"""Tests des contrats de l'activité : Activity, TrackPointStream.

Un test de refus par invariant dur (chacun attend ``ContractError``), sur des objets
de base construits à la main et modifiés champ par champ par ``replace``.
"""

from collections.abc import Sequence
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mountain_perf.schemas import (
    Activity,
    ContractError,
    SourceRef,
    Sport,
    TrackPointStream,
)
from strategies import (
    activities,
    blank_texts,
    finite_floats,
    naive_datetimes,
    non_finite_floats,
    out_of_range_elevations_m,
    out_of_range_latitudes_deg,
    out_of_range_longitudes_deg,
    track_point_streams,
)

SOURCE = SourceRef(
    kind="garmin_activity",
    identifier="activite.json",
    content_hash="0" * 64,
    retrieved_at=datetime(2026, 9, 14, 8, 0, tzinfo=UTC),
)

PARIS_SUMMER = timezone(timedelta(hours=2))

ACTIVITY = Activity(
    activity_ref="a-1",
    sport=Sport.FOOT,
    source_activity_type="trail_running",
    start_time=datetime(2026, 7, 1, 6, 0, tzinfo=PARIS_SUMMER),
    elapsed_duration_s=3600.0,
    moving_duration_s=3000.0,
    distance_m=10000.0,
    ascent_m=500.0,
    descent_m=500.0,
    average_hr_bpm=140.0,
    max_hr_bpm=170.0,
    stream_ref="a-1-stream",
    source=SOURCE,
)

STREAM = TrackPointStream(
    activity_ref="a-1",
    time_s=(0.0, 10.0, 20.0, 30.0),
    latitude_deg=(45.0, 45.001, 45.002, 45.002),
    longitude_deg=(6.0, 6.0, 6.0, 6.0),
    elevation_m=(1000.0, 1005.0, 1010.0, 1010.0),
    distance_m=(0.0, 30.0, 60.0, 60.0),
    speed_ms=(3.0, 3.0, 3.0, 0.0),
    heart_rate_bpm=(120.0, 130.0, 135.0, 128.0),
    source=SOURCE,
)


def _with_value(values: Sequence[float], index: int, value: float) -> tuple[float, ...]:
    return (*values[:index], value, *values[index + 1 :])


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------


@given(activities())
def test_valid_activities_build(activity: Activity) -> None:
    assert activity.moving_duration_s <= activity.elapsed_duration_s
    assert activity.start_time.utcoffset() == timedelta(seconds=activity.utc_offset_s)


def test_activity_references_its_stream_and_does_not_contain_it() -> None:
    types = {f.name: f.type for f in fields(Activity)}
    assert types["stream_ref"] == "str | None"
    assert not any("TrackPointStream" in str(t) for t in types.values())


def test_activity_start_time_keeps_its_local_fixed_offset() -> None:
    assert ACTIVITY.start_time.utcoffset() == timedelta(hours=2)
    assert ACTIVITY.utc_offset_s == 7200


def test_activity_utc_offset_is_a_property_not_a_field() -> None:
    assert "utc_offset_s" not in {f.name for f in fields(Activity)}
    assert isinstance(Activity.utc_offset_s, property)


@given(blank_texts())
def test_activity_blank_ref_is_refused(ref: str) -> None:
    with pytest.raises(ContractError, match="activity_ref"):
        replace(ACTIVITY, activity_ref=ref)


@given(naive_datetimes())
def test_activity_naive_start_time_is_refused(start_time: datetime) -> None:
    with pytest.raises(ContractError, match="start_time"):
        replace(ACTIVITY, start_time=start_time)


@pytest.mark.parametrize("hours", [20, -13])
def test_activity_start_time_offset_out_of_range_is_refused(hours: int) -> None:
    # Légal en Python (|décalage| < 24 h), hors des fuseaux réels.
    start_time = datetime(2026, 7, 1, 6, 0, tzinfo=timezone(timedelta(hours=hours)))
    with pytest.raises(ContractError, match="décalage de start_time"):
        replace(ACTIVITY, start_time=start_time)


@pytest.mark.parametrize("name", ["elapsed_duration_s", "moving_duration_s"])
@given(value=st.one_of(st.floats(max_value=0.0), non_finite_floats()))
def test_activity_bad_duration_is_refused(name: str, value: float) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=name):
        replace(ACTIVITY, **changes)


@given(st.floats(min_value=3600.001, max_value=1e6))
def test_activity_moving_longer_than_elapsed_is_refused(moving: float) -> None:
    with pytest.raises(ContractError, match="moving_duration_s"):
        replace(ACTIVITY, moving_duration_s=moving)


def test_activity_moving_equal_to_elapsed_is_valid() -> None:
    assert replace(ACTIVITY, moving_duration_s=3600.0).moving_duration_s == 3600.0


@pytest.mark.parametrize("name", ["distance_m", "ascent_m", "descent_m"])
@given(value=st.one_of(st.floats(max_value=-1e-9), non_finite_floats()))
def test_activity_bad_distance_or_elevation_gain_is_refused(
    name: str, value: float
) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=name):
        replace(ACTIVITY, **changes)


@pytest.mark.parametrize("name", ["average_hr_bpm", "max_hr_bpm"])
@given(
    value=st.one_of(
        finite_floats(250.001, 1e4), finite_floats(-1e4, 19.999), non_finite_floats()
    )
)
def test_activity_bad_heart_rate_is_refused(name: str, value: float) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=name):
        replace(ACTIVITY, **changes)


def test_activity_average_hr_above_max_is_refused() -> None:
    with pytest.raises(ContractError, match="average_hr_bpm"):
        replace(ACTIVITY, average_hr_bpm=171.0)


# ---------------------------------------------------------------------------
# TrackPointStream
# ---------------------------------------------------------------------------


@given(track_point_streams())
def test_valid_streams_build(stream: TrackPointStream) -> None:
    assert len(stream.time_s) >= 1


def test_stream_with_a_single_point_is_valid() -> None:
    stream = TrackPointStream(
        activity_ref="a-1",
        time_s=(5.0,),
        latitude_deg=None,
        longitude_deg=None,
        elevation_m=None,
        distance_m=None,
        speed_ms=None,
        heart_rate_bpm=None,
        source=SOURCE,
    )
    assert stream.time_s == (5.0,)


def test_stream_speed_is_stored_not_derived() -> None:
    assert "speed_ms" in {f.name for f in fields(TrackPointStream)}


@given(blank_texts())
def test_stream_blank_ref_is_refused(ref: str) -> None:
    with pytest.raises(ContractError, match="activity_ref"):
        replace(STREAM, activity_ref=ref)


def test_stream_without_points_is_refused() -> None:
    with pytest.raises(ContractError, match="au moins 1"):
        replace(
            STREAM,
            time_s=(),
            latitude_deg=None,
            longitude_deg=None,
            elevation_m=None,
            distance_m=None,
            speed_ms=None,
            heart_rate_bpm=None,
        )


@pytest.mark.parametrize(
    "name",
    [
        "latitude_deg",
        "longitude_deg",
        "elevation_m",
        "distance_m",
        "speed_ms",
        "heart_rate_bpm",
    ],
)
def test_stream_array_of_a_different_length_is_refused(name: str) -> None:
    changes: dict[str, Any] = {name: getattr(STREAM, name)[:-1]}
    with pytest.raises(ContractError, match="longueurs différentes"):
        replace(STREAM, **changes)


@pytest.mark.parametrize("name", ["time_s", "distance_m", "heart_rate_bpm"])
def test_stream_mutable_arrays_are_refused(name: str) -> None:
    changes: dict[str, Any] = {name: list(getattr(STREAM, name))}
    with pytest.raises(ContractError, match=f"{name}.*tuple"):
        replace(STREAM, **changes)


@pytest.mark.parametrize(
    "name",
    [
        "time_s",
        "latitude_deg",
        "longitude_deg",
        "elevation_m",
        "distance_m",
        "speed_ms",
        "heart_rate_bpm",
    ],
)
@given(value=non_finite_floats())
def test_stream_non_finite_value_is_refused(name: str, value: float) -> None:
    changes: dict[str, Any] = {name: _with_value(getattr(STREAM, name), 3, value)}
    with pytest.raises(ContractError, match=rf"{name}\[3\]"):
        replace(STREAM, **changes)


def test_stream_negative_time_is_refused() -> None:
    with pytest.raises(ContractError, match=r"time_s\[0\]"):
        replace(STREAM, time_s=(-1.0, 10.0, 20.0, 30.0))


@pytest.mark.parametrize("repeated", [10.0, 5.0])
def test_stream_time_must_be_strictly_increasing(repeated: float) -> None:
    with pytest.raises(ContractError, match=r"time_s.*strictement croissante"):
        replace(STREAM, time_s=_with_value(STREAM.time_s, 2, repeated))


def test_stream_distance_accepts_a_plateau() -> None:
    # Un arrêt : la distance ne progresse pas entre les deux derniers points.
    assert STREAM.distance_m == (0.0, 30.0, 60.0, 60.0)


def test_stream_distance_refuses_a_decrease() -> None:
    with pytest.raises(ContractError, match=r"distance_m.*croissante"):
        replace(STREAM, distance_m=(0.0, 30.0, 60.0, 59.0))


@given(finite_floats(-1e3, -1e-9))
def test_stream_negative_speed_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match=r"speed_ms\[3\]"):
        replace(STREAM, speed_ms=_with_value(STREAM.speed_ms or (), 3, value))


@pytest.mark.parametrize(
    ("name", "values"),
    [
        ("latitude_deg", out_of_range_latitudes_deg()),
        ("longitude_deg", out_of_range_longitudes_deg()),
        ("elevation_m", out_of_range_elevations_m()),
        (
            "heart_rate_bpm",
            st.one_of(finite_floats(250.001, 1e4), finite_floats(-1e4, 19.999)),
        ),
    ],
)
@given(data=st.data())
def test_stream_value_out_of_range_is_refused(
    name: str, values: st.SearchStrategy[float], data: st.DataObject
) -> None:
    value = data.draw(values)
    changes: dict[str, Any] = {name: _with_value(getattr(STREAM, name), 1, value)}
    with pytest.raises(ContractError, match=rf"{name}\[1\]"):
        replace(STREAM, **changes)
