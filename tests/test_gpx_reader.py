"""Lecture sur fichiers inventés ; les entrées invalides restent dans tmp_path."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mountain_perf.gpx import GpxError, read_gpx
from mountain_perf.gpx.geo import haversine_m
from mountain_perf.schemas import PointKind
from mountain_perf.validation import ContractError

FIXTURES = Path(__file__).parent / "fixtures"


def test_namespace_variants_preserve_every_route_field() -> None:
    routes = [
        read_gpx(FIXTURES / filename).route
        for filename in ("mini_11.gpx", "mini_10.gpx", "mini_sans_ns.gpx")
    ]
    # Tout sauf source : nom, trois tableaux et chaque champ des lieux nommés.
    assert routes[0] == replace(routes[1], source=routes[0].source)
    assert routes[0] == replace(routes[2], source=routes[0].source)
    assert routes[0].name == "Mini méridien"
    start, summit = routes[0].named_points
    assert (start.elevation_m, summit.elevation_m) == (999, 1600)
    assert (start.description, summit.description) == ("Départ inventé", "Col inventé")
    assert (start.raw_type, summit.raw_type) == ("start", "Summit")
    assert all(point.kind is PointKind.UNKNOWN for point in routes[0].named_points)
    assert all(point.cutoff_s is None for point in routes[0].named_points)


def test_counts_and_source() -> None:
    path = FIXTURES / "mini_11.gpx"
    before = datetime.now(UTC)
    result = read_gpx(path)
    assert (result.point_count_read, result.point_count_dropped) == (11, 0)
    assert (result.segment_count, result.max_segment_gap_m) == (1, 0)
    assert result.unnamed_waypoint_count == 0
    assert result.route.source.kind == "gpx"
    assert result.route.source.identifier == path.name
    assert (
        result.route.source.content_hash
        == hashlib.sha256(path.read_bytes()).hexdigest()
    )
    assert before <= result.route.source.retrieved_at <= datetime.now(UTC)


def test_unnamed_waypoint_is_counted() -> None:
    result = read_gpx(FIXTURES / "mini_wpt_sans_nom.gpx")
    assert result.unnamed_waypoint_count == 1
    assert len(result.route.named_points) == 2


def test_all_tracks_and_segments_are_concatenated(tmp_path: Path) -> None:
    path = tmp_path / "troncons.gpx"
    path.write_text(
        '<gpx><trk><trkseg><trkpt lat="45" lon="6"><ele>1500</ele></trkpt>'
        '<trkpt lat="45" lon="6"><ele>1515</ele></trkpt></trkseg>'
        '<trkseg><trkpt lat="45.001" lon="6"><ele>1501</ele></trkpt></trkseg>'
        "</trk><trk><name>Ignoré</name><trkseg>"
        '<trkpt lat="45.011" lon="6"><ele>1502</ele></trkpt></trkseg>'
        '<wpt lat="45" lon="6"><name>Pas au premier niveau</name></wpt>'
        "</trk></gpx>",
        encoding="utf-8",
    )
    result = read_gpx(path)
    assert result.route.name == "troncons"
    assert result.route.latitude_deg == (45, 45.001, 45.011)
    assert result.route.elevation_m == (1500.0, 1501.0, 1502.0)
    assert result.route.named_points == ()
    assert (result.point_count_read, result.point_count_dropped) == (4, 1)
    assert result.segment_count == 3
    assert result.max_segment_gap_m == pytest.approx(
        haversine_m(45.001, 6, 45.011, 6), abs=1e-9
    )


def _read_invalid(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / "invalide.gpx"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(GpxError, match=message):
        read_gpx(path)


def test_malformed_xml_is_rejected(tmp_path: Path) -> None:
    _read_invalid(tmp_path, "<gpx>", "XML mal formé")


def test_missing_trackpoints_are_rejected(tmp_path: Path) -> None:
    _read_invalid(tmp_path, "<gpx><trk><trkseg/></trk></gpx>", "Aucun <trkpt>")


def test_single_point_is_rejected(tmp_path: Path) -> None:
    _read_invalid(
        tmp_path,
        '<gpx><trk><trkseg><trkpt lat="45" lon="6"><ele>1500</ele></trkpt>'
        "</trkseg></trk></gpx>",
        "au moins 2 points",
    )


def test_all_confused_points_are_rejected(tmp_path: Path) -> None:
    point = '<trkpt lat="45" lon="6"><ele>1500</ele></trkpt>'
    _read_invalid(
        tmp_path,
        f"<gpx><trk><trkseg>{point * 3}</trkseg></trk></gpx>",
        "longueur nulle",
    )


def test_missing_elevation_is_rejected(tmp_path: Path) -> None:
    _read_invalid(
        tmp_path,
        '<gpx><trk><trkseg><trkpt lat="45" lon="6"/></trkseg></trk></gpx>',
        r"trkpt\[0\].ele.*manquante",
    )


@pytest.mark.parametrize(
    ("original", "invalid", "message"),
    [
        ("<ele>1500</ele>", "<ele>12a</ele>", "ele.*illisible"),
        ('lat="45.00000000000000"', "", "lat.*manquante"),
        ('lon="6"', 'lon="abc"', "lon.*illisible"),
        ("<ele>999</ele>", "<ele>12a</ele>", r"wpt\[0\].ele.*illisible"),
    ],
)
def test_invalid_numbers_are_gpx_errors(
    tmp_path: Path, original: str, invalid: str, message: str
) -> None:
    content = (FIXTURES / "mini_11.gpx").read_text(encoding="utf-8")
    assert original in content
    _read_invalid(tmp_path, content.replace(original, invalid), message)


def test_physical_violation_remains_contract_error(tmp_path: Path) -> None:
    content = (FIXTURES / "mini_11.gpx").read_text(encoding="utf-8")
    path = tmp_path / "altitude.gpx"
    path.write_text(
        content.replace("<ele>1500</ele>", "<ele>9500</ele>"), encoding="utf-8"
    )
    with pytest.raises(ContractError, match="elevation_m"):
        read_gpx(path)
