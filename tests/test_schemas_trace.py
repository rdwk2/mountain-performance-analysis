"""Tests du contrat ``RecordedTrace`` (§ 4.1 du brief M4a-1, ``0010`` D4.4, D5.1)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from hypothesis import given

from mountain_perf.schemas import ContractError, RecordedTrace, SourceRef
from strategies import (
    naive_datetimes,
    non_finite_floats,
    out_of_range_elevations_m,
    out_of_range_latitudes_deg,
    out_of_range_longitudes_deg,
    recorded_traces,
)

SOURCE = SourceRef(
    kind="gpx",
    identifier="trace.gpx",
    content_hash="0" * 64,
    retrieved_at=datetime(2026, 9, 24, tzinfo=UTC),
)

TRACE = RecordedTrace(
    start_time=datetime(2026, 6, 1, 10, 0, tzinfo=timezone(timedelta(hours=2))),
    time_s=(0.0, 1.0, 2.5),
    latitude_deg=(45.0, 45.0001, 45.0002),
    longitude_deg=(6.0, 6.0, 6.0),
    elevation_m=(1000.0, 1001.0, 1002.0),
    sources=(SOURCE,),
    dropped_same_instant_count=1,
)

ARRAYS = ("time_s", "latitude_deg", "longitude_deg", "elevation_m")


def _with(name: str, index: int, value: float) -> RecordedTrace:
    values = list(getattr(TRACE, name))
    values[index] = value
    changes: dict[str, Any] = {name: tuple(values)}
    return replace(TRACE, **changes)


@given(recorded_traces())
def test_valid_traces_build(trace: RecordedTrace) -> None:
    assert trace.time_s[0] == 0
    assert trace.start_time.tzinfo is UTC


def test_properties_are_derived_from_time_s() -> None:
    """``elapsed_s`` est l'écoulé ``E`` de ``0010`` D5.1."""
    assert TRACE.elapsed_s == 2.5
    assert TRACE.start_time == datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    assert TRACE.end_time == datetime(2026, 6, 1, 8, 0, 2, 500000, tzinfo=UTC)


@given(naive_datetimes())
def test_naive_start_time_is_refused(instant: datetime) -> None:
    with pytest.raises(ContractError, match="start_time"):
        replace(TRACE, start_time=instant)


def test_start_time_is_normalized_to_utc() -> None:
    assert TRACE.start_time.tzinfo is UTC


@pytest.mark.parametrize("name", [*ARRAYS, "sources"])
def test_mutable_sequences_are_refused(name: str) -> None:
    changes: dict[str, Any] = {name: list(getattr(TRACE, name))}
    with pytest.raises(ContractError, match=rf"{name}.*tuple"):
        replace(TRACE, **changes)


@pytest.mark.parametrize("name", ARRAYS)
def test_parallel_arrays_have_the_same_length(name: str) -> None:
    changes: dict[str, Any] = {name: getattr(TRACE, name)[:2]}
    with pytest.raises(ContractError, match="longueurs différentes"):
        replace(TRACE, **changes)


def test_at_least_two_records() -> None:
    single: dict[str, Any] = {name: getattr(TRACE, name)[:1] for name in ARRAYS}
    with pytest.raises(ContractError, match="au moins 2"):
        replace(TRACE, **single)


@pytest.mark.parametrize("name", ARRAYS)
@given(value=non_finite_floats())
def test_non_finite_values_are_refused(name: str, value: float) -> None:
    """Un non-fini est aussi hors plage ou hors ordre : le message nomme la finitude."""
    with pytest.raises(ContractError, match=rf"{name}\[1\] doit être fini"):
        _with(name, 1, value)


def test_time_origin_is_the_first_record() -> None:
    with pytest.raises(ContractError, match=r"time_s\[0\] doit valoir 0"):
        replace(TRACE, time_s=(0.5, 1.0, 2.5))


@pytest.mark.parametrize("time_s", [(0.0, 1.0, 1.0), (0.0, 2.0, 1.0)], ids=str)
def test_time_is_strictly_increasing(time_s: tuple[float, ...]) -> None:
    with pytest.raises(ContractError, match="strictement croissante"):
        replace(TRACE, time_s=time_s)


@given(out_of_range_latitudes_deg())
def test_latitude_out_of_range_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match=r"latitude_deg\[1\] doit être dans"):
        _with("latitude_deg", 1, value)


@given(out_of_range_longitudes_deg())
def test_longitude_out_of_range_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match=r"longitude_deg\[1\] doit être dans"):
        _with("longitude_deg", 1, value)


@given(out_of_range_elevations_m())
def test_elevation_out_of_range_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match=r"elevation_m\[1\] doit être dans"):
        _with("elevation_m", 1, value)


def test_at_least_one_source() -> None:
    with pytest.raises(ContractError, match="sources doit contenir au moins 1"):
        replace(TRACE, sources=())


def test_dropped_count_is_not_negative() -> None:
    with pytest.raises(ContractError, match="dropped_same_instant_count"):
        replace(TRACE, dropped_same_instant_count=-1)


def test_immobile_records_are_kept() -> None:
    """Aucune position n'est dédoublonnée : deux enregistrements au même endroit."""
    still = replace(TRACE, latitude_deg=(45.0, 45.0, 45.0))
    assert len(still.time_s) == 3
