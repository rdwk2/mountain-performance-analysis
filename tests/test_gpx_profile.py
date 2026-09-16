"""Grille, lissage et invariants de la construction M2."""

import math
from dataclasses import replace
from itertools import pairwise

import pytest
from hypothesis import given

from fixtures.synthetic_routes import flat_route_with_confused_points, meridian_route
from mountain_perf.gpx import (
    PROFILE_PARAMETER_SPECS,
    ProfileError,
    build_profile,
    build_profile_with_diagnostics,
)
from mountain_perf.gpx.geo import deduplicated_polyline
from mountain_perf.gpx.profile import _build_grid, _smooth
from mountain_perf.schemas import ParameterSet, Route
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
    if total_m >= profile.step_m:
        assert all(
            profile.step_m / 2 - 1e-9 <= b - a <= 1.5 * profile.step_m + 1e-9
            for a, b in pairwise(profile.distance_m)
        )
