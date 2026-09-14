"""Tests des contrats de sortie : Passage, Segment, Projection.

Un test de refus par invariant dur, l'invariant central sous Hypothesis sur toutes les
variantes de projection, et les oracles chiffrés des fixtures à 30 km.
"""

import math
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fixtures.performance import (
    AID_A,
    FINISH,
    MARKER,
    OFF_GRID_PROJECTION,
    START,
    THIRTY_KM_PROFILE,
    THREE_POINT_PROJECTION,
)
from mountain_perf.schemas import ContractError, Projection, Segment
from mountain_perf.schemas.projection import _interpolate
from strategies import (
    blank_texts,
    elevations_m,
    naive_datetimes,
    non_finite_floats,
    out_of_range_elevations_m,
    projections,
)

SEGMENT = THREE_POINT_PROJECTION.segments[0]


def _central_gap(projection: Projection) -> float:
    """Σ segments + Σ arrêts intérieurs − (dernière arrivée − premier départ)."""
    passages = projection.passages
    lhs = math.fsum(seg.duration_s for seg in projection.segments) + math.fsum(
        p.stop_duration_s for p in passages[1:-1]
    )
    return lhs - (passages[-1].arrival_s - passages[0].departure_s)


# ---------------------------------------------------------------------------
# Passage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["moving_time_s", "arrival_s", "departure_s"])
@given(value=st.one_of(st.floats(max_value=-1e-9), non_finite_floats()))
def test_passage_bad_time_is_refused(name: str, value: float) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=name):
        replace(AID_A, **changes)


def test_passage_departure_before_arrival_is_refused() -> None:
    with pytest.raises(ContractError, match="departure_s"):
        replace(AID_A, departure_s=4499.0)


def test_passage_moving_time_beyond_arrival_is_refused() -> None:
    with pytest.raises(ContractError, match="moving_time_s"):
        replace(AID_A, moving_time_s=4501.0)


def test_passage_stop_duration_is_derived() -> None:
    assert AID_A.stop_duration_s == 300.0
    assert START.stop_duration_s == 0.0


# ---------------------------------------------------------------------------
# Segment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["ascent_m", "descent_m", "elevation_min_m", "elevation_max_m"]
)
@given(value=non_finite_floats())
def test_segment_non_finite_value_is_refused(name: str, value: float) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=name):
        replace(SEGMENT, **changes)


@pytest.mark.parametrize("name", ["ascent_m", "descent_m"])
def test_segment_negative_elevation_change_is_refused(name: str) -> None:
    changes: dict[str, Any] = {name: -1.0}
    with pytest.raises(ContractError, match=name):
        replace(SEGMENT, **changes)


@pytest.mark.parametrize("name", ["elevation_min_m", "elevation_max_m"])
@given(value=out_of_range_elevations_m())
def test_segment_elevation_out_of_range_is_refused(name: str, value: float) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=name):
        replace(SEGMENT, **changes)


def test_segment_min_above_max_is_refused() -> None:
    with pytest.raises(ContractError, match="elevation_min_m"):
        replace(SEGMENT, elevation_min_m=1900.0)


def test_segment_end_before_start_in_distance_is_refused() -> None:
    with pytest.raises(ContractError, match="abscisse"):
        replace(
            SEGMENT,
            start=AID_A,
            end=replace(MARKER, arrival_s=5000.0, departure_s=5000.0),
        )


def test_segment_end_before_start_in_time_is_refused() -> None:
    with pytest.raises(ContractError, match=r"end\.arrival_s"):
        replace(
            SEGMENT,
            start=AID_A,
            end=replace(FINISH, moving_time_s=0.0, arrival_s=4700.0),
        )


def test_segment_duration_and_distance_are_properties() -> None:
    names = {f.name for f in fields(Segment)}
    for derived in ("duration_s", "distance_m"):
        assert derived not in names
        assert isinstance(getattr(Segment, derived), property)


# ---------------------------------------------------------------------------
# Projection — invariants durs
# ---------------------------------------------------------------------------


def test_segments_are_a_property_not_a_field() -> None:
    assert "segments" not in {f.name for f in fields(Projection)}
    assert isinstance(Projection.segments, property)


@pytest.mark.parametrize("name", ["curve_ref", "engine_version"])
@given(value=blank_texts())
def test_projection_blank_reference_is_refused(name: str, value: str) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=name):
        replace(THREE_POINT_PROJECTION, **changes)


def test_projection_mutable_passages_are_refused() -> None:
    passages: Any = list(THREE_POINT_PROJECTION.passages)
    with pytest.raises(ContractError, match=r"passages.*tuple"):
        replace(THREE_POINT_PROJECTION, passages=passages)


def test_projection_with_a_single_passage_is_refused() -> None:
    with pytest.raises(ContractError, match="au moins 2"):
        replace(THREE_POINT_PROJECTION, passages=(START,))


def test_projection_passages_out_of_order_are_refused() -> None:
    with pytest.raises(ContractError, match=r"passages\.distance_m"):
        replace(OFF_GRID_PROJECTION, passages=(START, AID_A, MARKER, FINISH))


def test_projection_must_start_at_abscissa_zero() -> None:
    with pytest.raises(ContractError, match="abscisse 0"):
        replace(THREE_POINT_PROJECTION, passages=(MARKER, AID_A, FINISH))


def test_projection_must_end_at_the_end_of_the_profile() -> None:
    with pytest.raises(ContractError, match="fin du profil"):
        replace(THREE_POINT_PROJECTION, passages=(START, MARKER, AID_A))


def test_projection_departure_after_next_arrival_is_refused() -> None:
    late = replace(MARKER, arrival_s=562.5, departure_s=5000.0)
    with pytest.raises(ContractError, match=r"passages\[2\]\.arrival_s"):
        replace(OFF_GRID_PROJECTION, passages=(START, late, AID_A, FINISH))


def test_projection_decreasing_moving_time_is_refused() -> None:
    backwards = replace(FINISH, moving_time_s=4000.0)
    with pytest.raises(ContractError, match="moving_time_s doit être >="):
        replace(THREE_POINT_PROJECTION, passages=(START, AID_A, backwards))


def test_projection_moving_faster_than_elapsed_is_refused() -> None:
    # 8 401 s de mouvement pour un segment de 8 400 s, arrivée pourtant cohérente.
    too_much = replace(FINISH, moving_time_s=12901.0)
    with pytest.raises(ContractError, match="plus que le temps écoulé"):
        replace(THREE_POINT_PROJECTION, passages=(START, AID_A, too_much))


@given(naive_datetimes())
def test_projection_naive_start_time_is_refused(start_time: datetime) -> None:
    with pytest.raises(ContractError, match="start_time"):
        replace(THREE_POINT_PROJECTION, start_time=start_time)


@pytest.mark.parametrize("hours", [20, -13])
def test_projection_start_time_offset_out_of_range_is_refused(hours: int) -> None:
    start_time = datetime(2026, 7, 1, 6, 0, tzinfo=timezone(timedelta(hours=hours)))
    with pytest.raises(ContractError, match="décalage de start_time"):
        replace(THREE_POINT_PROJECTION, start_time=start_time)


@given(naive_datetimes())
def test_projection_naive_generated_at_is_refused(generated_at: datetime) -> None:
    with pytest.raises(ContractError, match="generated_at"):
        replace(THREE_POINT_PROJECTION, generated_at=generated_at)


def test_projection_utc_offset_is_read_from_start_time() -> None:
    assert THREE_POINT_PROJECTION.utc_offset_s is None
    local = datetime(2026, 7, 1, 6, 0, tzinfo=timezone(timedelta(hours=2)))
    projection = replace(THREE_POINT_PROJECTION, start_time=local)
    assert projection.utc_offset_s == 7200
    assert projection.start_time == local
    assert "utc_offset_s" not in {f.name for f in fields(Projection)}


# ---------------------------------------------------------------------------
# Projection — invariant central et sommes (Hypothesis)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "variant",
    [
        {"stops": "none"},
        {"stops": "long"},
        {"edge_stops": True},
        {"min_passages": 2, "max_passages": 2},
        {"min_passages": 50, "max_passages": 50},
        {"same_abscissa": True},
        {"repeated_place": True},
    ],
    ids=[
        "arrets-nuls",
        "arrets-longs",
        "arrets-aux-extremites",
        "deux-passages",
        "cinquante-passages",
        "meme-abscisse",
        "lieu-traverse-deux-fois",
    ],
)
@given(data=st.data())
def test_central_invariant(variant: dict[str, Any], data: st.DataObject) -> None:
    projection = data.draw(projections(**variant))
    assert _central_gap(projection) == 0.0


@given(projections(edge_stops=True))
def test_summing_all_stops_is_another_quantity(projection: Projection) -> None:
    passages = projection.passages
    all_stops = math.fsum(seg.duration_s for seg in projection.segments) + math.fsum(
        p.stop_duration_s for p in passages
    )
    assert all_stops == passages[-1].departure_s - passages[0].arrival_s
    assert all_stops != passages[-1].arrival_s - passages[0].departure_s


@given(projections())
def test_segment_distances_sum_to_the_profile_length(projection: Projection) -> None:
    total = math.fsum(seg.distance_m for seg in projection.segments)
    assert total == pytest.approx(projection.profile.distance_m[-1], rel=1e-9)


@given(projections())
def test_segment_ascent_and_descent_sum_to_the_profile_totals(
    projection: Projection,
) -> None:
    profile = projection.profile
    ascent = math.fsum(seg.ascent_m for seg in projection.segments)
    descent = math.fsum(seg.descent_m for seg in projection.segments)
    assert ascent == pytest.approx(profile.cumulative_ascent_m[-1], rel=1e-9, abs=1e-6)
    assert descent == pytest.approx(
        profile.cumulative_descent_m[-1], rel=1e-9, abs=1e-6
    )


@given(projections(stops="any"))
def test_moving_time_never_exceeds_arrival(projection: Projection) -> None:
    assert all(p.moving_time_s <= p.arrival_s for p in projection.passages)


@given(projections(same_abscissa=True))
def test_passages_at_the_same_abscissa_give_an_empty_segment(
    projection: Projection,
) -> None:
    assert any(seg.distance_m == 0.0 for seg in projection.segments)


# ---------------------------------------------------------------------------
# Fixtures — oracles chiffrés
# ---------------------------------------------------------------------------


def test_three_point_projection_segments() -> None:
    first, second = THREE_POINT_PROJECTION.segments
    assert (first.duration_s, second.duration_s) == (4500.0, 8400.0)
    assert (first.distance_m, second.distance_m) == (12000.0, 18000.0)
    assert (first.ascent_m, first.descent_m) == (800.0, 400.0)
    assert (second.ascent_m, second.descent_m) == (600.0, 800.0)
    assert (first.elevation_min_m, first.elevation_max_m) == (1000.0, 1800.0)
    assert (second.elevation_min_m, second.elevation_max_m) == (1200.0, 2000.0)


def test_three_point_projection_closes() -> None:
    passages = THREE_POINT_PROJECTION.passages
    stops = sum(p.stop_duration_s for p in passages[1:-1])
    assert stops == 300.0
    assert 4500.0 + 8400.0 + stops == 13200.0
    assert _central_gap(THREE_POINT_PROJECTION) == 0.0


def test_off_grid_interpolation_oracle() -> None:
    grid = THIRTY_KM_PROFILE.distance_m
    assert _interpolate(grid, THIRTY_KM_PROFILE.elevation_m, 1500.0) == 1200.0
    assert _interpolate(grid, THIRTY_KM_PROFILE.cumulative_ascent_m, 1500.0) == 200.0
    assert _interpolate(grid, THIRTY_KM_PROFILE.cumulative_descent_m, 1500.0) == 0.0


def test_off_grid_first_segment() -> None:
    segment = OFF_GRID_PROJECTION.segments[0]
    assert (segment.ascent_m, segment.descent_m) == (200.0, 0.0)
    assert (segment.elevation_min_m, segment.elevation_max_m) == (1000.0, 1200.0)


@given(elevations_m())
def test_interpolation_is_exact_on_grid_points(elevation: float) -> None:
    grid = (0.0, 10.0, 20.0)
    values = (elevation, 0.0, elevation)
    assert [_interpolate(grid, values, x) for x in grid] == list(values)
