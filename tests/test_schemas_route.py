"""Tests des contrats du tracé : NamedPoint, Route, ResolvedPoint, RouteProfile.

Un test par invariant dur (chacun attend ``ContractError``), les propriétés du
profil sous Hypothesis, et des exemples sur la fixture « sucette ».
"""

import math
from dataclasses import FrozenInstanceError, fields, replace
from itertools import pairwise
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fixtures.routes import (
    COL,
    DEPART,
    LOLLIPOP_PROFILE,
    LOLLIPOP_ROUTE,
    SOURCE_POINT,
)
from mountain_perf.schemas import (
    POINT_KIND_DESCRIPTIONS,
    ContractError,
    NamedPoint,
    PointKind,
    ResolvedPoint,
    Route,
    RouteProfile,
)
from strategies import (
    blank_texts,
    named_points,
    non_finite_floats,
    out_of_range_elevations_m,
    out_of_range_latitudes_deg,
    out_of_range_longitudes_deg,
    route_profiles,
    routes,
)

PASSAGE = LOLLIPOP_PROFILE.resolved_points[1]


# ---------------------------------------------------------------------------
# PointKind
# ---------------------------------------------------------------------------


def test_every_point_kind_is_described() -> None:
    assert set(POINT_KIND_DESCRIPTIONS) == set(PointKind)
    assert all(text.strip() for text in POINT_KIND_DESCRIPTIONS.values())


def test_point_kind_defaults_to_unknown() -> None:
    point = NamedPoint(name="X", latitude_deg=0.0, longitude_deg=0.0, elevation_m=None)
    assert point.kind is PointKind.UNKNOWN


# ---------------------------------------------------------------------------
# NamedPoint
# ---------------------------------------------------------------------------


@given(named_points())
def test_valid_named_points_build(point: NamedPoint) -> None:
    assert point.name.strip()


@given(blank_texts())
def test_named_point_blank_name_is_refused(name: str) -> None:
    with pytest.raises(ContractError, match="name"):
        replace(COL, name=name)


@given(st.one_of(out_of_range_latitudes_deg(), non_finite_floats()))
def test_named_point_bad_latitude_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match="latitude_deg"):
        replace(COL, latitude_deg=value)


@given(st.one_of(out_of_range_longitudes_deg(), non_finite_floats()))
def test_named_point_bad_longitude_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match="longitude_deg"):
        replace(COL, longitude_deg=value)


@given(st.one_of(out_of_range_elevations_m(), non_finite_floats()))
def test_named_point_bad_elevation_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match="elevation_m"):
        replace(COL, elevation_m=value)


def test_named_point_elevation_is_optional() -> None:
    assert replace(COL, elevation_m=None).elevation_m is None


@given(st.one_of(st.floats(max_value=0.0), non_finite_floats()))
def test_named_point_bad_cutoff_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match="cutoff_s"):
        replace(COL, cutoff_s=value)


def test_named_point_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        COL.name = "Autre"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@given(routes())
def test_valid_routes_build(route: Route) -> None:
    assert len(route.latitude_deg) == len(route.elevation_m) >= 2


def test_route_has_no_distance_time_or_sport() -> None:
    names = {f.name for f in fields(Route)}
    assert names == {
        "name",
        "latitude_deg",
        "longitude_deg",
        "elevation_m",
        "named_points",
        "source",
    }


@given(blank_texts())
def test_route_blank_name_is_refused(name: str) -> None:
    with pytest.raises(ContractError, match="name"):
        replace(LOLLIPOP_ROUTE, name=name)


def test_route_arrays_of_different_lengths_are_refused() -> None:
    with pytest.raises(ContractError, match="longueurs différentes"):
        replace(LOLLIPOP_ROUTE, elevation_m=LOLLIPOP_ROUTE.elevation_m[:-1])


def test_route_with_a_single_point_is_refused() -> None:
    with pytest.raises(ContractError, match="au moins 2"):
        replace(
            LOLLIPOP_ROUTE,
            latitude_deg=(45.0,),
            longitude_deg=(6.0,),
            elevation_m=(1000.0,),
        )


@pytest.mark.parametrize(
    "field_name", ["latitude_deg", "longitude_deg", "elevation_m", "named_points"]
)
def test_route_mutable_arrays_are_refused(field_name: str) -> None:
    # Any : on passe volontairement une list là où le type exige un tuple.
    changes: dict[str, Any] = {field_name: list(getattr(LOLLIPOP_ROUTE, field_name))}
    with pytest.raises(ContractError, match=f"{field_name}.*tuple"):
        replace(LOLLIPOP_ROUTE, **changes)


def _with_value(
    values: tuple[float, ...], index: int, value: float
) -> tuple[float, ...]:
    return (*values[:index], value, *values[index + 1 :])


@given(st.one_of(out_of_range_latitudes_deg(), non_finite_floats()))
def test_route_bad_latitude_is_refused(value: float) -> None:
    latitudes = _with_value(tuple(LOLLIPOP_ROUTE.latitude_deg), 3, value)
    with pytest.raises(ContractError, match=r"latitude_deg\[3\]"):
        replace(LOLLIPOP_ROUTE, latitude_deg=latitudes)


@given(st.one_of(out_of_range_longitudes_deg(), non_finite_floats()))
def test_route_bad_longitude_is_refused(value: float) -> None:
    longitudes = _with_value(tuple(LOLLIPOP_ROUTE.longitude_deg), 3, value)
    with pytest.raises(ContractError, match=r"longitude_deg\[3\]"):
        replace(LOLLIPOP_ROUTE, longitude_deg=longitudes)


@given(st.one_of(out_of_range_elevations_m(), non_finite_floats()))
def test_route_bad_elevation_is_refused(value: float) -> None:
    elevations = _with_value(tuple(LOLLIPOP_ROUTE.elevation_m), 3, value)
    with pytest.raises(ContractError, match=r"elevation_m\[3\]"):
        replace(LOLLIPOP_ROUTE, elevation_m=elevations)


# ---------------------------------------------------------------------------
# ResolvedPoint
# ---------------------------------------------------------------------------


@given(st.one_of(st.floats(max_value=-1e-9), non_finite_floats()))
def test_resolved_point_bad_distance_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match="distance_m"):
        replace(PASSAGE, distance_m=value)


@given(st.one_of(st.floats(max_value=-1e-9), non_finite_floats()))
def test_resolved_point_bad_offset_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match="offset_m"):
        replace(PASSAGE, offset_m=value)


@given(st.one_of(out_of_range_elevations_m(), non_finite_floats()))
def test_resolved_point_bad_elevation_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match="elevation_m"):
        replace(PASSAGE, elevation_m=value)


def test_resolved_point_zero_distance_and_offset_are_valid() -> None:
    passage = ResolvedPoint(point=DEPART, distance_m=0.0, elevation_m=0.0, offset_m=0.0)
    assert passage.distance_m == passage.offset_m == 0.0


# ---------------------------------------------------------------------------
# RouteProfile — invariants durs
# ---------------------------------------------------------------------------


@given(blank_texts())
def test_profile_blank_route_name_is_refused(name: str) -> None:
    with pytest.raises(ContractError, match="route_name"):
        replace(LOLLIPOP_PROFILE, route_name=name)


def test_profile_arrays_of_different_lengths_are_refused() -> None:
    with pytest.raises(ContractError, match="longueurs différentes"):
        replace(LOLLIPOP_PROFILE, elevation_m=LOLLIPOP_PROFILE.elevation_m[:-1])


def test_profile_with_a_single_point_is_refused() -> None:
    with pytest.raises(ContractError, match="au moins 2"):
        replace(
            LOLLIPOP_PROFILE,
            distance_m=(0.0,),
            elevation_m=(1000.0,),
            resolved_points=(),
        )


@pytest.mark.parametrize("field_name", ["distance_m", "elevation_m", "resolved_points"])
def test_profile_mutable_arrays_are_refused(field_name: str) -> None:
    # Any : on passe volontairement une list là où le type exige un tuple.
    changes: dict[str, Any] = {field_name: list(getattr(LOLLIPOP_PROFILE, field_name))}
    with pytest.raises(ContractError, match=f"{field_name}.*tuple"):
        replace(LOLLIPOP_PROFILE, **changes)


@given(non_finite_floats())
def test_profile_non_finite_distance_is_refused(value: float) -> None:
    distances = _with_value(tuple(LOLLIPOP_PROFILE.distance_m), 3, value)
    with pytest.raises(ContractError, match=r"distance_m\[3\]"):
        replace(LOLLIPOP_PROFILE, distance_m=distances)


@given(st.one_of(out_of_range_elevations_m(), non_finite_floats()))
def test_profile_bad_elevation_is_refused(value: float) -> None:
    elevations = _with_value(tuple(LOLLIPOP_PROFILE.elevation_m), 3, value)
    with pytest.raises(ContractError, match=r"elevation_m\[3\]"):
        replace(LOLLIPOP_PROFILE, elevation_m=elevations)


def test_profile_distance_must_start_at_zero() -> None:
    shifted = tuple(d + 10.0 for d in LOLLIPOP_PROFILE.distance_m)
    with pytest.raises(ContractError, match="commencer à 0"):
        replace(LOLLIPOP_PROFILE, distance_m=shifted)


@pytest.mark.parametrize("repeated", [2000.0, 1500.0])
def test_profile_distance_must_be_strictly_increasing(repeated: float) -> None:
    distances = _with_value(tuple(LOLLIPOP_PROFILE.distance_m), 3, repeated)
    with pytest.raises(ContractError, match="strictement croissante"):
        replace(LOLLIPOP_PROFILE, distance_m=distances)


@given(st.one_of(st.floats(max_value=0.0), non_finite_floats()))
def test_profile_bad_step_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match="step_m"):
        replace(LOLLIPOP_PROFILE, step_m=value)


def test_profile_resolved_points_must_be_sorted() -> None:
    passages = LOLLIPOP_PROFILE.resolved_points
    unsorted = (passages[0], passages[2], passages[1], passages[3])
    with pytest.raises(ContractError, match=r"resolved_points\.distance_m"):
        replace(LOLLIPOP_PROFILE, resolved_points=unsorted)


def test_profile_resolved_point_beyond_the_end_is_refused() -> None:
    beyond = replace(PASSAGE, distance_m=6000.5)
    passages = (*LOLLIPOP_PROFILE.resolved_points, beyond)
    with pytest.raises(ContractError, match=r"resolved_points\[4\]"):
        replace(LOLLIPOP_PROFILE, resolved_points=passages)


def test_profile_resolved_point_at_the_end_is_valid() -> None:
    at_end = replace(PASSAGE, distance_m=6000.0)
    passages = (*LOLLIPOP_PROFILE.resolved_points, at_end)
    assert (
        replace(LOLLIPOP_PROFILE, resolved_points=passages).resolved_points[-1]
        == at_end
    )


def test_profile_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        LOLLIPOP_PROFILE.step_m = 10.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RouteProfile — stocké vs dérivé
# ---------------------------------------------------------------------------


def test_profile_stored_fields_are_exactly_the_contract() -> None:
    assert [f.name for f in fields(RouteProfile)] == [
        "route_name",
        "source",
        "distance_m",
        "elevation_m",
        "resolved_points",
        "step_m",
        "build_parameters",
        "quality_flags",
    ]


@pytest.mark.parametrize(
    "derived", ["grade", "cumulative_ascent_m", "cumulative_descent_m"]
)
def test_derived_quantities_are_properties_not_fields(derived: str) -> None:
    assert derived not in {f.name for f in fields(RouteProfile)}
    assert isinstance(getattr(RouteProfile, derived), property)


def test_quality_flags_default_to_empty() -> None:
    assert LOLLIPOP_PROFILE.quality_flags == frozenset()


# ---------------------------------------------------------------------------
# RouteProfile — propriétés (Hypothesis)
# ---------------------------------------------------------------------------


@given(route_profiles())
def test_grade_has_one_value_per_interval(profile: RouteProfile) -> None:
    assert len(profile.grade) == len(profile.distance_m) - 1


@given(route_profiles())
def test_cumulative_ascent_is_non_decreasing_and_sums_positive_steps(
    profile: RouteProfile,
) -> None:
    ascent = profile.cumulative_ascent_m
    e = profile.elevation_m
    assert len(ascent) == len(profile.distance_m)
    assert ascent[0] == 0.0
    assert all(b >= a for a, b in pairwise(ascent))
    expected = math.fsum(max(e[i + 1] - e[i], 0.0) for i in range(len(e) - 1))
    assert ascent[-1] == pytest.approx(expected, rel=1e-9, abs=1e-6)


@given(route_profiles())
def test_cumulative_descent_is_non_decreasing_and_sums_negative_steps(
    profile: RouteProfile,
) -> None:
    descent = profile.cumulative_descent_m
    e = profile.elevation_m
    assert len(descent) == len(profile.distance_m)
    assert descent[0] == 0.0
    assert all(b >= a for a, b in pairwise(descent))
    expected = math.fsum(max(e[i] - e[i + 1], 0.0) for i in range(len(e) - 1))
    assert descent[-1] == pytest.approx(expected, rel=1e-9, abs=1e-6)


@given(route_profiles())
def test_ascent_minus_descent_is_the_net_elevation_change(
    profile: RouteProfile,
) -> None:
    net = profile.cumulative_ascent_m[-1] - profile.cumulative_descent_m[-1]
    e = profile.elevation_m
    assert net == pytest.approx(e[-1] - e[0], rel=1e-9, abs=1e-6)


@given(route_profiles())
def test_grade_sign_matches_elevation_change(profile: RouteProfile) -> None:
    e = profile.elevation_m
    for i, grade in enumerate(profile.grade):
        assert math.copysign(1, grade) == math.copysign(1, e[i + 1] - e[i]) or (
            grade == 0
        )


@given(route_profiles(duplicate_named_point=True))
def test_profile_with_a_place_passed_twice_builds_in_order(
    profile: RouteProfile,
) -> None:
    abscissae = [passage.distance_m for passage in profile.resolved_points]
    assert abscissae == sorted(abscissae)
    points = [passage.point for passage in profile.resolved_points]
    assert any(points.count(point) >= 2 for point in points)


# ---------------------------------------------------------------------------
# Fixture « sucette » — valeurs calculables de tête
# ---------------------------------------------------------------------------


def test_lollipop_grade() -> None:
    assert LOLLIPOP_PROFILE.grade == (0.25, 0.25, 0.0, 0.0, -0.25, -0.25)


def test_lollipop_cumulative_ascent_and_descent() -> None:
    assert LOLLIPOP_PROFILE.cumulative_ascent_m == (
        0.0,
        250.0,
        500.0,
        500.0,
        500.0,
        500.0,
        500.0,
    )
    assert LOLLIPOP_PROFILE.cumulative_descent_m == (
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        250.0,
        500.0,
    )


def test_lollipop_segment_ascent_by_subtraction() -> None:
    ascent = LOLLIPOP_PROFILE.cumulative_ascent_m
    assert ascent[2] - ascent[1] == 250.0


def test_lollipop_source_is_passed_twice() -> None:
    source_passages = [
        passage.distance_m
        for passage in LOLLIPOP_PROFILE.resolved_points
        if passage.point == SOURCE_POINT
    ]
    assert source_passages == [1000.0, 5000.0]


def test_lollipop_route_keeps_file_points_unfiltered() -> None:
    assert LOLLIPOP_ROUTE.named_points == (DEPART, SOURCE_POINT, COL)
