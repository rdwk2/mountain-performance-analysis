"""Les parcours des profils de démo et leurs GPX préparés (M5-3, § 6.1 (a), (e) et (g)
du brief)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mountain_perf.demo.gpx import write_route_gpx
from mountain_perf.demo.parcours import (
    METRES_PER_DEGREE,
    ROUTES,
    Route,
    Segment,
    altitude_at,
    climb_m,
    grade_at,
    length_m,
    route,
    to_lat_lon,
    xy_at,
)
from mountain_perf.demo.sorties import write_routes
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS, build_profile, read_gpx
from mountain_perf.schemas import ParameterSet
from mountain_perf.validation import ContractError

NAMES = (
    "deux_parties",
    "course_raide",
    "boucle_raide",
    "boucle_roulante",
    "boucle_moyenne",
    "boucle_douce",
)

TABLE = {
    "deux_parties": ("line", (0.0, 0.0), 1_000.0, 30_000.0, 2_320.0),
    "course_raide": ("line", (0.0, 0.0), 1_000.0, 10_000.0, 2_000.0),
    "boucle_raide": ("loop", (0.0, 2_000.0), 1_200.0, 8_000.0, 630.0),
    "boucle_roulante": ("loop", (0.0, -4_000.0), 1_100.0, 8_100.0, 175.5),
    "boucle_moyenne": ("loop", (-3_000.0, 2_000.0), 1_150.0, 5_400.0, 252.0),
    "boucle_douce": ("loop", (-3_000.0, -4_000.0), 1_050.0, 7_200.0, 117.0),
}
"""Forme, départ, altitude de départ, L et D+ du tableau du § 6.1 (e)."""

WAYPOINTS = {
    "deux_parties": (
        ("Départ", 0.0),
        ("Sommet 1", 2_000.0),
        ("Sommet 2", 5_000.0),
        ("Col", 10_000.0),
        ("Arrivée", 30_000.0),
    ),
    "course_raide": (
        ("Départ", 0.0),
        ("Sommet 1", 2_000.0),
        ("Sommet 2", 5_000.0),
        ("Arrivée", 10_000.0),
    ),
    "boucle_raide": (("Sommet", 3_400.0),),
    "boucle_roulante": (("Mi-parcours", 4_050.0),),
    "boucle_moyenne": (("Sommet", 2_400.0),),
    "boucle_douce": (("Mi-parcours", 3_600.0),),
}


def test_to_lat_lon() -> None:
    lat, lon = to_lat_lon(1000.0, 2000.0)
    assert lat == pytest.approx(0.017986420252709204, abs=1e-12)
    assert lon == pytest.approx(-139.99100678987364, abs=1e-12)
    assert METRES_PER_DEGREE == 111_195.0


def test_the_routes_in_order() -> None:
    assert tuple(r.name for r in ROUTES) == NAMES


@pytest.mark.parametrize("name", NAMES)
def test_length_and_climb(name: str) -> None:
    _, _, _, length, climb = TABLE[name]
    found = route(name)
    assert length_m(found) == pytest.approx(length, abs=1e-9)
    assert climb_m(found) == pytest.approx(climb, abs=1e-9)


def _line(*segments: Segment) -> Route:
    return Route(
        name="essai",
        segments=segments,
        start_xy=(0.0, 0.0),
        shape="line",
        start_altitude_m=0.0,
        waypoints=(),
    )


@pytest.mark.parametrize(
    ("segment", "climb"),
    [
        (Segment(100.0, 0.1, -0.1), 2.5),
        (Segment(100.0, -0.1, 0.1), 2.5),
        (Segment(100.0, 0.2, -0.05), 8.0),
    ],
)
def test_the_climb_of_a_segment_that_changes_sign(
    segment: Segment, climb: float
) -> None:
    """La part positive d'un tronçon qui change de signe (§ 6.1) ; le dernier croise
    zéro à 80 m."""
    assert climb_m(_line(segment)) == pytest.approx(climb, abs=1e-12)


def test_the_climb_of_a_route_whose_segments_change_sign() -> None:
    found = _line(
        Segment(100.0, 0.1, -0.1),
        Segment(100.0, -0.1, 0.1),
        Segment(100.0, 0.2, -0.05),
    )
    assert climb_m(found) == pytest.approx(13.0, abs=1e-12)


@pytest.mark.parametrize("name", NAMES)
def test_every_field_of_each_route(name: str) -> None:
    shape, start, altitude, _, _ = TABLE[name]
    found = route(name)
    assert isinstance(found, Route)
    assert (found.name, found.shape, found.start_xy, found.start_altitude_m) == (
        name,
        shape,
        start,
        altitude,
    )
    assert found.waypoints == WAYPOINTS[name]
    assert all(isinstance(segment, Segment) for segment in found.segments)


def test_every_field_of_a_segment() -> None:
    first = route("boucle_raide").segments[1]
    assert (first.length_m, first.grade_start, first.grade_end) == (2_000.0, 0.0, 0.36)
    assert route("deux_parties").segments[0] == Segment(2_000.0, 0.30, 0.30)


@pytest.mark.parametrize(
    ("name", "s", "altitude"),
    [
        ("deux_parties", 2_000.0, 1_600.0),
        ("deux_parties", 5_000.0, 2_100.0),
        ("deux_parties", 10_000.0, 2_300.0),
        ("deux_parties", 30_000.0, 2_060.0),
        ("boucle_raide", 3_400.0, 1_830.0),
        ("boucle_raide", 1_400.0, 1_290.0),
        ("boucle_raide", 8_000.0, 1_200.0),
    ],
)
def test_altitude_cases(name: str, s: float, altitude: float) -> None:
    assert altitude_at(route(name), s) == pytest.approx(altitude, abs=1e-9)


def test_grade_at_the_middle_of_the_ramp() -> None:
    assert grade_at(route("boucle_raide"), 1_400.0) == pytest.approx(0.18, abs=1e-9)


@pytest.mark.parametrize(
    ("name", "s", "xy"),
    [
        ("boucle_raide", 2_400.0, (2_400.0, 2_000.0)),
        ("boucle_raide", 3_400.0, (2_400.0, 3_000.0)),
        ("boucle_moyenne", 5_400.0, (-3_000.0, 2_000.0)),
        ("deux_parties", 12_345.0, (12_345.0, 0.0)),
    ],
)
def test_xy_cases(name: str, s: float, xy: tuple[float, float]) -> None:
    x, y = xy_at(route(name), s)
    assert x == pytest.approx(xy[0], abs=1e-9)
    assert y == pytest.approx(xy[1], abs=1e-9)


@pytest.mark.parametrize("name", NAMES)
def test_each_shape_starts_where_it_should(name: str) -> None:
    """Une ligne finit à L à l'est de son départ ; une boucle revient à son départ et
    à son altitude de départ."""
    found = route(name)
    total = length_m(found)
    x0, y0 = found.start_xy
    end = xy_at(found, total)
    assert xy_at(found, 0.0) == pytest.approx((x0, y0))
    if found.shape == "line":
        assert end == pytest.approx((x0 + total, y0))
    else:
        assert end == pytest.approx((x0, y0))
        assert altitude_at(found, total) == pytest.approx(found.start_altitude_m)


@pytest.mark.parametrize("s", [-1.0, 8_000.5])
def test_a_distance_outside_the_route_raises(s: float) -> None:
    with pytest.raises(ContractError):
        altitude_at(route("boucle_raide"), s)
    with pytest.raises(ContractError):
        xy_at(route("boucle_raide"), s)


def test_an_unknown_route_raises() -> None:
    with pytest.raises(ContractError):
        route("x")


@pytest.mark.parametrize("name", NAMES)
def test_the_prepared_gpx_reads_back(tmp_path: Path, name: str) -> None:
    found = route(name)
    path = tmp_path / f"{name}.gpx"
    write_route_gpx(found, path)
    assert path.read_bytes().startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
    read = read_gpx(path)
    length = length_m(found)
    assert read.point_count_read == round(length / 10) + 1
    assert [p.name for p in read.route.named_points] == [n for n, _ in found.waypoints]
    profile = build_profile(read.route, ParameterSet(PROFILE_PARAMETER_SPECS))
    assert profile.distance_m[-1] == pytest.approx(length, rel=0.005)
    tolerance = 0.03 if found.shape == "line" else 0.01
    assert profile.cumulative_ascent_m[-1] == pytest.approx(
        climb_m(found), rel=tolerance
    )


def test_the_prepared_gpx_have_lf_line_ends(tmp_path: Path) -> None:
    """Les six préparés de ``write_routes`` : UTF-8, fins de ligne ``\\n`` (§ 6.0,
    D8)."""
    write_routes(tmp_path)
    paths = sorted((tmp_path / "routes").glob("*.gpx"))
    assert len(paths) == len(NAMES)
    for path in paths:
        data = path.read_bytes()
        assert b"\r\n" not in data, path.name
        data.decode("utf-8")


def test_the_two_part_course_has_3001_points_and_5_places(tmp_path: Path) -> None:
    path = tmp_path / "deux_parties.gpx"
    write_route_gpx(route("deux_parties"), path)
    read = read_gpx(path)
    assert read.point_count_read == 3_001
    assert len(read.route.named_points) == 5
