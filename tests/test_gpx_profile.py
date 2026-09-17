"""Grille, lissage et invariants de la construction M2."""

import math
from dataclasses import replace
from itertools import pairwise

import pytest
from hypothesis import given

from fixtures.routes import COL, DEPART, LOLLIPOP_ROUTE, SOURCE, SOURCE_POINT
from fixtures.synthetic_routes import (
    flat_route_with_confused_points,
    irregular_route,
    meridian_route,
    out_and_back_route,
    subdivide_route,
    switchback_route,
)
from mountain_perf.gpx import (
    PROFILE_PARAMETER_SPECS,
    ProfileError,
    build_profile,
    build_profile_with_diagnostics,
)
from mountain_perf.gpx.geo import EARTH_RADIUS_M, deduplicated_polyline, haversine_m
from mountain_perf.gpx.profile import _build_grid, _smooth
from mountain_perf.schemas import NamedPoint, ParameterSet, Route
from strategies import plausible_routes, profile_parameter_sets


def test_parameter_specs() -> None:
    assert [
        (s.name, s.unit, s.default, s.minimum, s.maximum)
        for s in PROFILE_PARAMETER_SPECS
    ] == [
        ("grid_step_m", "m", 50, 1, 1000),
        ("smoothing_window_m", "m", 150, 0, 5000),
        ("point_match_max_offset_m", "m", 150, 1, 20000),
        ("point_match_min_separation_m", "m", 500, 0, 100000),
    ]


@pytest.mark.parametrize("total_m", [2000.0, 2000.0 + 1e-9])
def test_grid_exact_multiple_and_tiny_remainder(total_m: float) -> None:
    grid_m = _build_grid(total_m, 50)
    assert len(grid_m) == 41
    assert grid_m[0] == 0
    assert grid_m[-1] == total_m


@pytest.mark.parametrize("total_m", [50.0, 74.0, 75.0, 76.0, 99.0, 38412.0])
def test_grid_interval_bounds(total_m: float) -> None:
    grid_m = _build_grid(total_m, 50)
    assert grid_m[-1] == total_m
    assert all(25 <= b - a <= 75 for a, b in pairwise(grid_m))
    if total_m == 38412:
        assert len(grid_m) == 769


@pytest.mark.parametrize(("length_m", "step_m"), [(20.0, 50.0), (400.0, 1000.0)])
def test_route_shorter_than_step(length_m: float, step_m: float) -> None:
    assert _build_grid(length_m, step_m) == (0, length_m)
    profile = build_profile(
        meridian_route(length_m=length_m),
        ParameterSet(PROFILE_PARAMETER_SPECS, {"grid_step_m": step_m}),
    )
    assert profile.distance_m == pytest.approx((0, length_m), abs=1e-9)
    assert profile.step_m == step_m


@pytest.mark.parametrize("window_m", [0.0, 99.0])
def test_quantized_window_can_leave_elevations_unchanged(window_m: float) -> None:
    elevation_m = (1500.1, 1540.2, 1510.3)
    smoothed_m, count = _smooth(elevation_m, 50, window_m)
    assert smoothed_m is elevation_m
    assert count == 1
    result = build_profile_with_diagnostics(
        meridian_route(),
        ParameterSet(PROFILE_PARAMETER_SPECS, {"smoothing_window_m": window_m}),
    )
    assert result.smoothing_point_count == 1
    assert result.effective_smoothing_window_m == 50


def test_smoothing_shrinks_at_both_edges() -> None:
    assert _smooth((1500.0, 1510.0, 1520.0), 50, 150) == ((1505, 1510, 1515), 3)
    result = build_profile_with_diagnostics(
        meridian_route(), ParameterSet(PROFILE_PARAMETER_SPECS)
    )
    assert result.smoothing_point_count == 3
    assert result.effective_smoothing_window_m == 150


def test_confused_points_keep_first_elevation() -> None:
    profile = build_profile(
        flat_route_with_confused_points(),
        ParameterSet(PROFILE_PARAMETER_SPECS, {"smoothing_window_m": 0}),
    )
    assert all(e == 1500 for e in profile.elevation_m)
    assert profile.cumulative_ascent_m[-1] == 0
    assert len(profile.resolved_points) == 1
    assert profile.resolved_points[0].distance_m == pytest.approx(1000, abs=1e-3)


def test_zero_length_route_is_rejected() -> None:
    route = replace(meridian_route(length_m=20), latitude_deg=(45.0, 45.0))
    with pytest.raises(ProfileError, match="longueur nulle"):
        build_profile(route, ParameterSet(PROFILE_PARAMETER_SPECS))


def test_raw_ascent_matches_aligned_smooth_source_without_smoothing() -> None:
    """Pas sur une source bruitée : lisser change le D+ de centaines de mètres par
    construction ; ici la source lisse est alignée sur la grille et w = 0.
    """
    route = meridian_route()
    profile = build_profile(
        route, ParameterSet(PROFILE_PARAMETER_SPECS, {"smoothing_window_m": 0})
    )
    ascent_m = math.fsum(max(b - a, 0) for a, b in pairwise(route.elevation_m))
    assert profile.cumulative_ascent_m[-1] == pytest.approx(ascent_m, abs=1e-9)


@given(plausible_routes(), profile_parameter_sets())
def test_generated_profiles_satisfy_contract(
    route: Route, parameters: ParameterSet
) -> None:
    profile = build_profile(route, parameters)
    total_m = deduplicated_polyline(route.latitude_deg, route.longitude_deg).distance_m[
        -1
    ]
    assert profile.distance_m[-1] == total_m
    assert profile.source == route.source
    assert profile.route_name == route.name
    assert profile.build_parameters is parameters
    assert profile.quality_flags == frozenset()
    assert all(math.isfinite(g) for g in profile.grade)
    assert profile.resolved_points
    distances_m = [p.distance_m for p in profile.resolved_points]
    assert distances_m == sorted(distances_m)
    assert all(0 <= d <= total_m for d in distances_m)
    assert all(
        p.offset_m <= parameters["point_match_max_offset_m"]
        for p in profile.resolved_points
    )
    for point in route.named_points:
        passages_m = [p.distance_m for p in profile.resolved_points if p.point == point]
        assert all(
            b - a >= parameters["point_match_min_separation_m"]
            for a, b in pairwise(passages_m)
        )
    if total_m >= profile.step_m:
        assert all(
            profile.step_m / 2 - 1e-9 <= b - a <= 1.5 * profile.step_m + 1e-9
            for a, b in pairwise(profile.distance_m)
        )


def test_irregular_spacing_resolves_exact_abscissa() -> None:
    profile = build_profile(irregular_route(), ParameterSet(PROFILE_PARAMETER_SPECS))
    assert len(profile.resolved_points) == 1
    assert profile.resolved_points[0].distance_m == pytest.approx(1500, abs=1e-3)
    assert profile.resolved_points[0].offset_m == pytest.approx(0, abs=1e-9)


def test_point_at_max_offset_is_resolved() -> None:
    point = NamedPoint(
        name="Lieu au seuil",
        latitude_deg=math.degrees(150 / EARTH_RADIUS_M),
        longitude_deg=math.degrees(3 / EARTH_RADIUS_M),
        elevation_m=None,
    )
    route = Route(
        name="Méridien équatorial",
        latitude_deg=(0.0, math.degrees(300 / EARTH_RADIUS_M)),
        longitude_deg=(0.0, 0.0),
        elevation_m=(1500.0, 1500.0),
        named_points=(point,),
        source=SOURCE,
    )
    parameters = ParameterSet(
        PROFILE_PARAMETER_SPECS, {"point_match_max_offset_m": 3.0}
    )
    profile = build_profile(route, parameters)
    assert len(profile.resolved_points) == 1
    passage = profile.resolved_points[0]
    assert passage.point == point
    assert passage.offset_m == 3.0
    assert passage.distance_m == pytest.approx(150.0, rel=0, abs=1e-3)


@pytest.mark.parametrize("offset_m", [0.0, 3.0, 500.0])
def test_projection_inside_300m_meridian_segment(offset_m: float) -> None:
    route = meridian_route(length_m=300, spacing_m=300, amplitude_m=0)
    point = NamedPoint(
        name="Lieu",
        latitude_deg=45 + math.degrees(150 / EARTH_RADIUS_M),
        longitude_deg=6
        + math.degrees(offset_m / (EARTH_RADIUS_M * math.cos(math.pi / 4))),
        elevation_m=None,
    )
    route = replace(route, named_points=(point,))
    result = build_profile_with_diagnostics(
        route, ParameterSet(PROFILE_PARAMETER_SPECS)
    )
    if offset_m == 500:
        assert result.profile.resolved_points == ()
        assert result.matched_point_count == 0
        assert len(result.unresolved_points) == 1
        assert result.unresolved_points[0].point == point
        assert result.unresolved_points[0].min_offset_m == pytest.approx(500, abs=1e-3)
    else:
        assert result.matched_point_count == 1
        assert result.unresolved_points == ()
        (passage,) = result.profile.resolved_points
        assert passage.distance_m == pytest.approx(150, abs=1e-3)
        # Épingler l'écart, pas seulement la présence d'un passage (cos φ).
        assert passage.offset_m == pytest.approx(offset_m, abs=1e-3)


def test_out_and_back_keeps_both_passages_after_subdivision() -> None:
    route = out_and_back_route()
    parameters = ParameterSet(PROFILE_PARAMETER_SPECS)
    before = build_profile(route, parameters).resolved_points
    after = build_profile(
        subdivide_route(subdivide_route(route)), parameters
    ).resolved_points
    assert len(before) == len(after) == 2
    assert [p.distance_m for p in after] == pytest.approx(
        [p.distance_m for p in before], abs=1e-9
    )
    assert [p.offset_m for p in before] == pytest.approx([8, 2], abs=1e-3)


def _distance_to_vertex(route: Route, end: int) -> float:
    return math.fsum(
        haversine_m(
            route.latitude_deg[i],
            route.longitude_deg[i],
            route.latitude_deg[i + 1],
            route.longitude_deg[i + 1],
        )
        for i in range(end)
    )


def test_lollipop_has_two_junction_passages_and_one_col() -> None:
    profile = build_profile(LOLLIPOP_ROUTE, ParameterSet(PROFILE_PARAMETER_SPECS))
    junctions = [
        p.distance_m for p in profile.resolved_points if p.point == SOURCE_POINT
    ]
    assert junctions == pytest.approx(
        [_distance_to_vertex(LOLLIPOP_ROUTE, i) for i in (1, 5)], abs=1e-9
    )
    cols = [p.distance_m for p in profile.resolved_points if p.point == COL]
    assert cols == pytest.approx([_distance_to_vertex(LOLLIPOP_ROUTE, 2)], abs=1e-9)
    starts = [p.distance_m for p in profile.resolved_points if p.point == DEPART]
    assert starts == [0.0]


def test_final_waypoint_is_resolved() -> None:
    route = LOLLIPOP_ROUTE
    finish = NamedPoint(
        "Arrivée", route.latitude_deg[-1], route.longitude_deg[-1], None
    )
    route = replace(route, named_points=(finish,))
    profile = build_profile(route, ParameterSet(PROFILE_PARAMETER_SPECS))
    (passage,) = profile.resolved_points
    assert passage.distance_m == profile.distance_m[-1]
    assert passage.offset_m == 0


def test_switchbacks_use_greedy_suppression() -> None:
    route = switchback_route()
    all_passages = build_profile(
        route,
        ParameterSet(PROFILE_PARAMETER_SPECS, {"point_match_min_separation_m": 0}),
    ).resolved_points
    assert len(all_passages) == 5
    offsets_m = [p.offset_m for p in all_passages]
    assert offsets_m == pytest.approx([70, 30, 10, 50, 90], abs=1e-3)
    gaps_m = [b.distance_m - a.distance_m for a, b in pairwise(all_passages)]
    assert all(d < 500 for d in gaps_m)
    assert all(a + b > 500 for a, b in pairwise(gaps_m))
    selected = build_profile(
        route, ParameterSet(PROFILE_PARAMETER_SPECS)
    ).resolved_points
    assert len(selected) == 3
    assert [p.distance_m for p in selected] == pytest.approx(
        [_distance_to_vertex(route, i) for i in (1, 7, 13)],
        abs=1e-9,
    )


def test_two_nearby_minima_keep_smaller_offset() -> None:
    route = replace(
        out_and_back_route(),
        latitude_deg=tuple(math.degrees(y / EARTH_RADIUS_M) for y in (0, 0, 10, 10)),
        longitude_deg=tuple(math.degrees(x / EARTH_RADIUS_M) for x in (0, 100, 100, 0)),
        elevation_m=(1500.0,) * 4,
        named_points=(
            NamedPoint(
                "Lieu",
                math.degrees(8 / EARTH_RADIUS_M),
                math.degrees(55 / EARTH_RADIUS_M),
                None,
            ),
        ),
    )
    all_passages = build_profile(
        route,
        ParameterSet(
            PROFILE_PARAMETER_SPECS,
            {
                "point_match_max_offset_m": 10,
                "point_match_min_separation_m": 0,
            },
        ),
    ).resolved_points
    assert len(all_passages) == 2
    separation_m = all_passages[1].distance_m - all_passages[0].distance_m
    assert separation_m == pytest.approx(100, abs=1e-9)
    kept = build_profile(route, ParameterSet(PROFILE_PARAMETER_SPECS)).resolved_points
    assert kept == (all_passages[1],)
    # À la séparation exacte, les deux restent admissibles (suppression stricte).
    at_boundary = build_profile(
        route,
        ParameterSet(
            PROFILE_PARAMETER_SPECS,
            {
                "point_match_max_offset_m": 10,
                "point_match_min_separation_m": separation_m,
            },
        ),
    ).resolved_points
    assert at_boundary == all_passages


def test_equal_offsets_are_ordered_by_abscissa() -> None:
    route = replace(
        out_and_back_route(),
        latitude_deg=(0.0, 0.0, 0.0),
        named_points=(NamedPoint("Lieu", 0, math.degrees(500 / EARTH_RADIUS_M), None),),
    )
    profile = build_profile(
        route,
        ParameterSet(PROFILE_PARAMETER_SPECS, {"point_match_min_separation_m": 1500}),
    )
    (passage,) = profile.resolved_points
    assert passage.distance_m == pytest.approx(500, abs=1e-9)


def test_resolved_elevation_interpolates_smoothed_profile() -> None:
    route = meridian_route()
    point = NamedPoint("Lieu", 45 + math.degrees(125 / EARTH_RADIUS_M), 6, 1234)
    profile = build_profile(
        replace(route, named_points=(point,)), ParameterSet(PROFILE_PARAMETER_SPECS)
    )
    (passage,) = profile.resolved_points
    gain = (1 + math.sqrt(2)) / 3
    expected_m = 1500 + 20 * gain * (1 + math.sqrt(0.5)) / 2
    assert passage.elevation_m == pytest.approx(expected_m, abs=1e-9)
    assert passage.elevation_m != point.elevation_m
