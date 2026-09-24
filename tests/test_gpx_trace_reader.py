"""Lecture de trace (§ 4.2 du brief M4a-1, ``0010`` D4.4) sur fichiers inventés.

La fixture ``trace_troncons.gpx`` porte les valeurs du § 7.1 ; chaque cas d'erreur est
une variante écrite dans ``tmp_path``.
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fixtures.traces import equatorial_deg, equatorial_point, gpx_document
from mountain_perf.gpx.reader import GpxError
from mountain_perf.gpx.trace_reader import TraceError, read_trace
from mountain_perf.schemas import ContractError

FIXTURES = Path(__file__).parent / "fixtures"
TRONCONS = FIXTURES / "trace_troncons.gpx"


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _points(start_s: int, xs: range) -> list[tuple[str, str, str | None, str | None]]:
    return [
        equatorial_point(
            float(x),
            f"2026-06-01T08:{(start_s + k) // 60:02d}:{(start_s + k) % 60:02d}Z",
        )
        for k, x in enumerate(xs)
    ]


# ---------------------------------------------------------------------------
# Fixture à tronçons (§ 7.1)
# ---------------------------------------------------------------------------


def test_fixture_records_and_times() -> None:
    """Doublon d'instant écarté et compté ; tronçons concaténés (``0010`` D4.4)."""
    trace = read_trace([TRONCONS])
    assert len(trace.time_s) == 12
    assert trace.dropped_same_instant_count == 1
    assert trace.time_s == (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, *map(float, range(20, 26)))
    assert trace.start_time == datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    assert trace.elapsed_s == 25


def test_fixture_keeps_the_first_of_same_instant_records() -> None:
    trace = read_trace([TRONCONS])
    expected = [
        equatorial_deg(float(x), 0.0) for x in (0, 1, 2, 3, 5, 6, *range(7, 13))
    ]
    assert list(zip(trace.latitude_deg, trace.longitude_deg, strict=True)) == expected
    assert trace.elevation_m == (1000.0,) * 12


def test_fixture_source_is_one_ref_per_file() -> None:
    before = datetime.now(UTC)
    (source,) = read_trace([TRONCONS]).sources
    assert source.kind == "gpx"
    assert source.identifier == "trace_troncons.gpx"
    assert source.content_hash == hashlib.sha256(TRONCONS.read_bytes()).hexdigest()
    assert before <= source.retrieved_at <= datetime.now(UTC)


# ---------------------------------------------------------------------------
# Formats admis
# ---------------------------------------------------------------------------


def test_offsets_and_fractional_seconds_are_admitted(tmp_path: Path) -> None:
    lat, lon = equatorial_deg(0.0, 0.0)
    points = [
        (repr(lat), repr(lon), "1000", "2026-06-01T10:00:00+02:00"),
        (repr(lat), repr(lon), "1000", "2026-06-01T08:00:00.25Z"),
        (repr(lat), repr(lon), "1000", "2026-06-01T08:00:01.5+00:00"),
    ]
    trace = read_trace([_write(tmp_path, "t.gpx", gpx_document(points))])
    assert trace.start_time == datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    assert trace.time_s == (0.0, 0.25, 1.5)


def test_files_are_concatenated_in_the_given_order(tmp_path: Path) -> None:
    first = _write(tmp_path, "a.gpx", gpx_document(_points(0, range(3))))
    second = _write(tmp_path, "b.gpx", gpx_document(_points(2, range(3, 6))))
    trace = read_trace([first, second])
    assert trace.time_s == (0.0, 1.0, 2.0, 3.0, 4.0)
    assert trace.dropped_same_instant_count == 1
    assert [source.identifier for source in trace.sources] == ["a.gpx", "b.gpx"]


def test_waypoints_are_ignored(tmp_path: Path) -> None:
    text = gpx_document(_points(0, range(2))).replace(
        "<trk>", '<wpt lat="1" lon="1"><time>2020-01-01T00:00:00Z</time></wpt><trk>'
    )
    assert len(read_trace([_write(tmp_path, "w.gpx", text)]).time_s) == 2


# ---------------------------------------------------------------------------
# Cas d'erreur (§ 7.1) — le message nomme le fichier, jamais son chemin
# ---------------------------------------------------------------------------


def test_decreasing_instant_is_a_trace_error(tmp_path: Path) -> None:
    points = _points(0, range(3))
    points[2] = equatorial_point(2.0, "2026-06-01T08:00:00.5Z")
    path = _write(tmp_path, "decroissant.gpx", gpx_document(points))
    with pytest.raises(TraceError, match=r"decroissant\.gpx, trkpt\[2\]") as error:
        read_trace([path])
    assert str(tmp_path) not in str(error.value)


def test_decreasing_instant_across_segments_is_a_trace_error(tmp_path: Path) -> None:
    text = gpx_document(_points(10, range(3)), _points(5, range(3, 5)))
    with pytest.raises(TraceError, match=r"trkpt\[3\]"):
        read_trace([_write(tmp_path, "t.gpx", text)])


def test_second_file_starting_before_the_end_of_the_first(tmp_path: Path) -> None:
    first = _write(tmp_path, "a.gpx", gpx_document(_points(0, range(5))))
    second = _write(tmp_path, "b.gpx", gpx_document(_points(2, range(5, 8))))
    with pytest.raises(TraceError, match=r"b\.gpx, trkpt\[0\]"):
        read_trace([first, second])


def test_naive_instant_is_a_gpx_error(tmp_path: Path) -> None:
    """``0006`` : un instant sans fuseau est refusé."""
    points = _points(0, range(3))
    points[1] = equatorial_point(1.0, "2026-06-01T08:00:01")
    with pytest.raises(GpxError, match=r"t\.gpx, trkpt\[1\]\.time.*sans fuseau"):
        read_trace([_write(tmp_path, "t.gpx", gpx_document(points))])


@pytest.mark.parametrize("tag", ["time", "ele"])
def test_missing_time_or_elevation_is_a_gpx_error(tmp_path: Path, tag: str) -> None:
    points = _points(0, range(3))
    lat, lon, ele, time = points[1]
    points[1] = (lat, lon, ele, None) if tag == "time" else (lat, lon, None, time)
    with pytest.raises(GpxError, match=rf"trkpt\[1\]\.{tag}"):
        read_trace([_write(tmp_path, "t.gpx", gpx_document(points))])


def test_unreadable_instant_is_a_gpx_error(tmp_path: Path) -> None:
    points = _points(0, range(3))
    points[1] = equatorial_point(1.0, "hier matin")
    with pytest.raises(GpxError, match="illisible"):
        read_trace([_write(tmp_path, "t.gpx", gpx_document(points))])


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_non_finite_value_is_a_trace_error(tmp_path: Path, value: str) -> None:
    points = _points(0, range(3))
    _, lon, ele, time = points[1]
    points[1] = (value, lon, ele, time)
    with pytest.raises(TraceError, match=r"trkpt\[1\] : valeur non finie"):
        read_trace([_write(tmp_path, "t.gpx", gpx_document(points))])


def test_single_record_is_a_trace_error(tmp_path: Path) -> None:
    with pytest.raises(TraceError, match="au moins 2"):
        read_trace([_write(tmp_path, "t.gpx", gpx_document(_points(0, range(1))))])


def test_records_collapsing_to_one_instant_are_a_trace_error(tmp_path: Path) -> None:
    points = [equatorial_point(float(x), "2026-06-01T08:00:00Z") for x in range(3)]
    with pytest.raises(TraceError, match="reçu 1"):
        read_trace([_write(tmp_path, "t.gpx", gpx_document(points))])


def test_malformed_xml_is_a_gpx_error(tmp_path: Path) -> None:
    with pytest.raises(GpxError, match=r"t\.gpx : XML mal formé"):
        read_trace([_write(tmp_path, "t.gpx", "<gpx><trk>")])


def test_out_of_range_value_stays_a_contract_error(tmp_path: Path) -> None:
    points = _points(0, range(3))
    _, lon, ele, time = points[1]
    points[1] = ("91", lon, ele, time)
    with pytest.raises(ContractError, match="latitude_deg"):
        read_trace([_write(tmp_path, "t.gpx", gpx_document(points))])
