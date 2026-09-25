"""Géométrie de référence de l'appariement (§ 5a.2 du brief M4a-2a).

``0010`` D4.1 (polyligne dédoublonnée, position à l'abscisse ``s``), D4.3 (plan
local, tangente, normale, tangente indéfinie) et D4.8 (projection d'ancrage). Les
cas sans trace de la liste « Géométrie, sans trace » du § 7.2a, et la dernière ligne
du tableau des prédicats (``anchor_projection``).
"""

import math

import pytest
from hypothesis import given

from fixtures.matching import (
    GREENWICH_EAST_DEG,
    greenwich_route,
    reference,
    reference_route,
)
from fixtures.synthetic_routes import flat_route_with_confused_points
from fixtures.traces import local_deg, parallel_deg, parallel_trace
from mountain_perf.backtest import reference_geometry, trace_route
from mountain_perf.backtest.geometry import (
    ANCHOR_TIE_M,
    HALF_CHORD_M,
    MIN_CHORD_M,
    anchor_projection,
    frame_at,
    position_at,
    project_restricted,
    to_local,
)
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS, ProfileError, build_profile
from mountain_perf.gpx.geo import EARTH_RADIUS_M
from mountain_perf.schemas import ParameterSet, Route
from strategies import plausible_routes

X03 = ((0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0), (0.0, 20.0), (0.0, 300.0))
"""Référence de X03 (§ 7.2a) : un lacet serré, puis une longue branche vers le nord."""


def _profile_length_m(route: Route) -> float:
    return build_profile(route, ParameterSet(PROFILE_PARAMETER_SPECS)).distance_m[-1]


def test_constants_of_0010() -> None:
    """D4.3 : demi-corde de 25 m, corde minimale de ``1e−6`` m ; D4.8 : 1 cm."""
    assert HALF_CHORD_M == 25.0
    assert MIN_CHORD_M == 1e-6
    assert ANCHOR_TIE_M == 0.01


@pytest.mark.parametrize("x_m", [0.0, -20.0, 1.5, 250.0, 520.0, 1500.0])
def test_local_deg_is_parallel_deg_on_the_base_parallel(x_m: float) -> None:
    """§ 7.0 : sur ``y = 0``, la convention rend exactement l'aide de M4a-1."""
    assert local_deg(x_m, 0.0) == parallel_deg(x_m)


# ---------------------------------------------------------------------------
# Plan local (D4.3)
# ---------------------------------------------------------------------------


def test_to_local_at_45_north() -> None:
    anchor = local_deg(0.0, 0.0)
    assert to_local(*anchor, *local_deg(100.0, 0.0)) == pytest.approx(
        (100.0, 0.0), abs=1e-8
    )
    assert to_local(*anchor, *local_deg(0.0, 50.0)) == pytest.approx(
        (0.0, 50.0), abs=1e-8
    )


def test_to_local_uses_the_cosine_of_the_anchor() -> None:
    """100 m de longitude équatoriale ne font que 50 m à 60° N (``cos 60° = 0,5``)."""
    point = (60.0, 6.0 + math.degrees(100.0 / EARTH_RADIUS_M))
    assert to_local(60.0, 6.0, *point) == pytest.approx((50.0, 0.0), abs=1e-8)


# ---------------------------------------------------------------------------
# Polyligne de référence et position à l'abscisse s (D4.1)
# ---------------------------------------------------------------------------


def test_position_at_returns_each_vertex_bit_for_bit() -> None:
    """X03 : chaque sommet, ``L`` compris, est rendu tel quel."""
    geometry = reference(*X03)
    for i, s_m in enumerate(geometry.distance_m):
        assert position_at(geometry, s_m) == (
            geometry.latitude_deg[i],
            geometry.longitude_deg[i],
        )
    assert position_at(geometry, geometry.length_m) == (
        geometry.latitude_deg[-1],
        geometry.longitude_deg[-1],
    )


def test_position_at_is_bounded_to_the_route() -> None:
    geometry = reference(*X03)
    first = (geometry.latitude_deg[0], geometry.longitude_deg[0])
    last = (geometry.latitude_deg[-1], geometry.longitude_deg[-1])
    assert position_at(geometry, -5.0) == first
    assert position_at(geometry, geometry.length_m + 5.0) == last


def test_position_at_interpolates_along_a_segment() -> None:
    geometry = reference((0.0, 0.0), (520.0, 0.0))
    anchor = local_deg(0.0, 0.0)
    assert to_local(*anchor, *position_at(geometry, 250.0)) == pytest.approx(
        (250.0, 0.0), abs=1e-6
    )
    # Sur la branche nord de X03 : 25 m après le sommet (0, 20), donc en (0, 45).
    geometry = reference(*X03)
    s_m = geometry.distance_m[4] + 25.0
    assert to_local(*anchor, *position_at(geometry, s_m)) == pytest.approx(
        (0.0, 45.0), abs=1e-6
    )


def test_position_at_is_exact_at_the_end_across_a_meridian() -> None:
    """R1a (correctifs de la PR #9) : ``(1 − t)·a + t·b`` rend le dernier sommet bit
    pour bit, là où ``b − a`` n'est pas exact ; ``a + t·(b − a)`` rendrait
    ``0.007578580617976077``."""
    geometry = reference_geometry(greenwich_route())
    assert position_at(geometry, geometry.length_m) == (45.0, GREENWICH_EAST_DEG)
    assert position_at(geometry, geometry.length_m) == (45.0, 0.007578580617976076)


def test_geometry_keeps_the_deduplicated_vertices() -> None:
    route = flat_route_with_confused_points()
    geometry = reference_geometry(route)
    assert len(route.latitude_deg) == 5
    assert geometry.latitude_deg == tuple(route.latitude_deg[i] for i in (0, 1, 4))
    assert geometry.distance_m[0] == 0.0


def test_length_is_the_profile_length_bit_for_bit_with_confused_points() -> None:
    route = flat_route_with_confused_points()
    assert reference_geometry(route).length_m == _profile_length_m(route)


@given(plausible_routes())
def test_length_is_the_profile_length_bit_for_bit(route: Route) -> None:
    assert reference_geometry(route).length_m == _profile_length_m(route)


def test_zero_length_route_is_refused_like_build_profile() -> None:
    route = reference_route((10.0, 0.0), (10.0, 0.0))
    with pytest.raises(ProfileError):
        build_profile(route, ParameterSet(PROFILE_PARAMETER_SPECS))
    with pytest.raises(ProfileError, match="longueur nulle"):
        reference_geometry(route)


# ---------------------------------------------------------------------------
# Repère : tangente, normale, tangente indéfinie (D4.3)
# ---------------------------------------------------------------------------


def test_one_sided_chord_at_the_start() -> None:
    frame = frame_at(reference((0.0, 0.0), (520.0, 0.0)), 0.0)
    assert frame is not None
    assert frame.tangent == pytest.approx((1.0, 0.0), abs=1e-12)
    assert frame.normal == pytest.approx((0.0, 1.0), abs=1e-12)
    assert (frame.anchor_lat_deg, frame.anchor_lon_deg) == local_deg(0.0, 0.0)


def test_normal_points_to_the_left_of_the_route() -> None:
    """Vers le nord, la gauche est l'ouest : ``n = (−1, 0)``."""
    frame = frame_at(reference((0.0, 0.0), (0.0, 510.0)), 250.0)
    assert frame is not None
    assert frame.tangent == pytest.approx((0.0, 1.0), abs=1e-9)
    assert frame.normal == pytest.approx((-1.0, 0.0), abs=1e-9)


def test_half_turn_has_an_undefined_tangent() -> None:
    """Demi-tour (§ 7.2a) : la corde de 250 m à 300 m est de longueur nulle."""
    geometry = reference((0.0, 0.0), (275.0, 0.0), (0.0, 0.0))
    assert frame_at(geometry, 275.0) is None
    assert frame_at(geometry, 250.0) is not None


def test_chord_leans_the_normal_at_a_corner() -> None:
    """Coin (§ 7.2a), en ``s = 250`` : corde de ``(225, 0)`` à ``(240, 35)``."""
    frame = frame_at(reference((0.0, 0.0), (240.0, 0.0), (240.0, 300.0)), 250.0)
    assert frame is not None
    norm = math.hypot(15.0, 35.0)
    # Ancre hors du parallèle de base : son cos φ décale x de 2,4e−5 m sur 15 m.
    assert frame.tangent == pytest.approx((15.0 / norm, 35.0 / norm), abs=1e-5)


def test_frame_coordinates_and_distance() -> None:
    frame = frame_at(reference((0.0, 0.0), (520.0, 0.0)), 250.0)
    assert frame is not None
    point = local_deg(253.0, 4.0)
    assert frame.coordinates(*point) == pytest.approx((3.0, 4.0), abs=1e-6)
    assert frame.distance_m(*point) == pytest.approx(5.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Projection d'ancrage (D4.8, précision)
# ---------------------------------------------------------------------------


def test_restricted_projection_at_equal_distance_is_ambiguous() -> None:
    """X03 : minima de distance 5 en ``s = 10`` et ``s ≈ 40``."""
    projection = project_restricted(
        reference(*X03), *local_deg(10.0, 5.0), 0.0, 60.0, local_deg(0.0, 0.0)
    )
    assert projection.ambiguous
    assert projection.offset_m == pytest.approx(5.0, abs=1e-6)
    assert projection.distance_along_m == pytest.approx(10.0, abs=1e-6)


def test_restricted_projection_into_an_elbow() -> None:
    """X08 coude : ``(22, 5)`` se projette sur la seconde branche, à 2 m, en 25 m."""
    projection = project_restricted(
        reference((0.0, 0.0), (20.0, 0.0), (20.0, 300.0)),
        *local_deg(22.0, 5.0),
        0.0,
        60.0,
        local_deg(0.0, 0.0),
    )
    assert not projection.ambiguous
    assert projection.distance_along_m == pytest.approx(25.0, abs=1e-6)
    assert projection.offset_m == pytest.approx(2.0, abs=1e-6)


def test_restricted_projection_is_bounded_to_the_interval() -> None:
    """Un point au-delà de la borne se projette sur la borne exacte, pas au-delà."""
    geometry = reference((0.0, 0.0), (520.0, 0.0))
    projection = project_restricted(
        geometry, *local_deg(100.0, 3.0), 0.0, 60.0, local_deg(0.0, 0.0)
    )
    assert projection.distance_along_m == 60.0
    projection = project_restricted(
        geometry,
        *local_deg(400.0, 3.0),
        geometry.length_m - 60.0,
        geometry.length_m + 10.0,
        local_deg(520.0, 0.0),
    )
    assert projection.distance_along_m == geometry.length_m - 60.0


def test_restricted_projection_refuses_an_empty_interval() -> None:
    geometry = reference((0.0, 0.0), (520.0, 0.0))
    with pytest.raises(ValueError, match="intervalle vide"):
        project_restricted(
            geometry, *local_deg(10.0, 0.0), 30.0, 30.0, local_deg(0.0, 0.0)
        )


@pytest.mark.parametrize(
    "candidates",
    [
        [(5.0, 10.0), (5.0078125, 40.0)],
        [(5.0, 10.0), (5.0, 10.015625)],
    ],
)
def test_anchor_projection_ambiguous(candidates: list[tuple[float, float]]) -> None:
    """§ 7.2a, prédicats : écart de distance ``< 0,01`` et abscisses ``> 0,01``."""
    assert anchor_projection(candidates)[2]


@pytest.mark.parametrize(
    ("candidates", "along_m"),
    [
        ([(5.0, 10.0), (5.015625, 40.0)], 10.0),
        ([(0.0, 10.0), (0.01, 40.0)], 10.0),
        ([(5.0, 10.0), (5.0, 10.0078125)], 10.0),
        ([(1.0, 3.0078125), (1.0, 3.0)], 3.0),
    ],
)
def test_anchor_projection_not_ambiguous(
    candidates: list[tuple[float, float]], along_m: float
) -> None:
    """§ 7.2a, prédicats : écart de distance d'exactement ``0,01`` (pas à égalité),
    abscisses à ``0,0078125`` (confondues), plus petite abscisse à distance égale."""
    chosen_m, distance_m, ambiguous = anchor_projection(candidates)
    assert not ambiguous
    assert chosen_m == along_m
    assert distance_m == min(d for d, _ in candidates)


def test_anchor_projection_needs_a_candidate() -> None:
    with pytest.raises(ValueError, match="aucun candidat"):
        anchor_projection([])


# ---------------------------------------------------------------------------
# Trace en Route (D3)
# ---------------------------------------------------------------------------


def test_trace_route_keeps_raw_positions_without_named_point() -> None:
    trace = parallel_trace((0.0, 1.0, 2.0), (0.0, 1.5, 1.5))
    route = trace_route(trace, "Sortie sans préparé")
    assert route.name == "Sortie sans préparé"
    assert route.latitude_deg == trace.latitude_deg
    assert route.longitude_deg == trace.longitude_deg
    assert route.elevation_m == trace.elevation_m
    assert route.named_points == ()
    assert route.source == trace.sources[0]
