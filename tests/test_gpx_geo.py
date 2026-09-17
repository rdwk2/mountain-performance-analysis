"""Géométrie synthétique : oracles analytiques, en distance horizontale."""

import math

import pytest

from mountain_perf.gpx.geo import (
    EARTH_RADIUS_M,
    deduplicated_polyline,
    haversine_m,
    project_point_on_segment,
)


def test_meridian_distance() -> None:
    latitude_deg = (45.0, 45.001, 45.007, 45.01)
    polyline = deduplicated_polyline(latitude_deg, (6.0,) * 4)
    expected_m = EARTH_RADIUS_M * math.radians(latitude_deg[-1] - latitude_deg[0])
    assert polyline.distance_m[-1] == pytest.approx(expected_m, abs=1e-9)


def test_longitude_distance_includes_latitude_cosine() -> None:
    # Pythagore sur les degrés surestimerait un est-ouest à 45° de 41 %.
    north_m = haversine_m(45, 6, 46, 6)
    east_m = haversine_m(45, 6, 45, 7)
    assert east_m / north_m == pytest.approx(math.cos(math.radians(45)), rel=1e-4)


def test_identical_points_have_zero_distance() -> None:
    assert haversine_m(45, 6, 45, 6) == 0


def test_antipodal_distance_is_finite() -> None:
    assert haversine_m(45, 6, -45, -174) == pytest.approx(math.pi * EARTH_RADIUS_M)


def test_deduplication_keeps_first_and_preserves_return_passage() -> None:
    polyline = deduplicated_polyline((45, 45, 46, 46, 45), (6,) * 5)
    assert polyline.indices == (0, 2, 4)
    step_m = EARTH_RADIUS_M * math.radians(1)
    assert polyline.distance_m == pytest.approx((0, step_m, 2 * step_m), abs=1e-9)


def test_empty_polyline() -> None:
    assert deduplicated_polyline((), ()).indices == ()


@pytest.mark.parametrize(
    ("latitude_deg", "expected_t"), [(44, 0), (45.5, 0.5), (47, 1)]
)
def test_projection_is_clamped(latitude_deg: float, expected_t: float) -> None:
    t, offset_m = project_point_on_segment(45, 6, 46, 6, latitude_deg, 6)
    assert t == expected_t
    expected_offset_m = EARTH_RADIUS_M * math.radians(abs(latitude_deg - (45 + t)))
    assert offset_m == pytest.approx(expected_offset_m, abs=1e-9)


def test_projection_on_confused_segment() -> None:
    assert project_point_on_segment(45, 6, 45, 6, 45, 6) == (0, 0)
