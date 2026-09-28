"""Compte-rendu M2 et erreurs lisibles, sur GPX synthétiques uniquement."""

import csv
import io
import math
import sys
from pathlib import Path

import pytest

from mountain_perf.cli import main
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS, build_profile, read_gpx
from mountain_perf.gpx.geo import EARTH_RADIUS_M
from mountain_perf.schemas import ParameterSet

FIXTURES = Path(__file__).parent / "fixtures"


def test_report_on_mini_gpx(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["profile", str(FIXTURES / "mini_11.gpx")]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "fichier      mini_11.gpx   sha256 " in captured.out
    assert "lecture      11 points, 0 écartés (doublons), 1 tronçon" in captured.out
    assert "grille       1 000 m, 21 points, pas 50 m" in captured.out
    assert "lissage      150 m demandé → 150 m effectif (3 points)" in captured.out
    # Triangle de 50 m : bouts lissés à 1502,5 m, crête à 1546 + 2/3 m.
    assert (
        "dénivelé     D+ 44 m / D− 44 m        (brut : D+ 50 m / D− 50 m)"
        in captured.out
    )
    assert "points       2 résolus sur 2, 0 <wpt> sans nom ignoré(s)" in captured.out


def test_csv_has_grid_rows_and_empty_final_grade(
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = FIXTURES / "mini_11.gpx"
    assert main(["profile", str(path), "--csv"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    rows = list(csv.reader(io.StringIO(captured.out)))
    profile = build_profile(read_gpx(path).route, ParameterSet(PROFILE_PARAMETER_SPECS))
    assert rows[0] == ["distance_m", "elevation_m", "grade"]
    assert len(rows) == len(profile.distance_m) + 1
    assert [float(row[0]) for row in rows[1:]] == list(profile.distance_m)
    assert [float(row[1]) for row in rows[1:]] == list(profile.elevation_m)
    assert [float(row[2]) for row in rows[1:-1]] == list(profile.grade)
    assert rows[-1][2] == ""


def test_unnamed_waypoint_is_visible(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["profile", str(FIXTURES / "mini_wpt_sans_nom.gpx")]) == 0
    assert (
        "points       2 résolus sur 2, 1 <wpt> sans nom ignoré(s)"
        in capsys.readouterr().out
    )


def test_99m_window_reports_no_smoothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["profile", str(FIXTURES / "mini_11.gpx"), "--smoothing-m", "99"]) == 0
    out = capsys.readouterr().out
    assert "99 m demandé → aucun lissage (50 m effectif, 1 point)" in out
    assert "150 m effectif" not in out
    assert "D+ 50 m / D− 50 m" in out


def test_unresolved_place_is_visible(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = (FIXTURES / "mini_11.gpx").read_text(encoding="utf-8")
    lon_deg = 6 + math.degrees(500 / (EARTH_RADIUS_M * math.cos(math.pi / 4)))
    waypoint = f'<wpt lat="45" lon="{lon_deg}"><name>Lointain</name></wpt>'
    path = tmp_path / "lointain.gpx"
    path.write_text(content.replace("</gpx>", waypoint + "</gpx>"), encoding="utf-8")
    assert main(["profile", str(path)]) == 0
    out = capsys.readouterr().out
    assert "2 résolus sur 3" in out
    assert "non résolus : « Lointain » (500 m)" in out


def test_segment_gap_is_visible(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = (FIXTURES / "mini_11.gpx").read_text(encoding="utf-8")
    path = tmp_path / "troncons.gpx"
    path.write_text(
        content.replace("</trkpt>", "</trkpt></trkseg><trkseg>", 1), encoding="utf-8"
    )
    assert main(["profile", str(path)]) == 0
    assert "2 tronçons, saut maximal 100 m" in capsys.readouterr().out


def test_step_larger_than_route(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "court.gpx"
    lat_deg = 45 + math.degrees(400 / EARTH_RADIUS_M)
    path.write_text(
        '<gpx><trk><trkseg><trkpt lat="45" lon="6"><ele>1500</ele></trkpt>'
        f'<trkpt lat="{lat_deg}" lon="6"><ele>1500</ele></trkpt></trkseg></trk></gpx>',
        encoding="utf-8",
    )
    assert main(["profile", str(path), "--step-m", "1000"]) == 0
    assert "grille       400 m, 2 points, pas 1 000 m" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("original", "replacement", "message"),
    [
        ("</gpx>", "", "XML mal formé"),
        ("<ele>1500</ele>", "<ele>12a</ele>", "numérique illisible"),
        ('lat="45.00000000000000"', "", "numérique manquante"),
        ("<ele>1500</ele>", "<ele>9500</ele>", "elevation_m"),
    ],
)
def test_invalid_file_has_no_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    original: str,
    replacement: str,
    message: str,
) -> None:
    content = (FIXTURES / "mini_11.gpx").read_text(encoding="utf-8")
    path = tmp_path / "invalide.gpx"
    path.write_text(content.replace(original, replacement), encoding="utf-8")
    assert main(["profile", str(path)]) != 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("option", "value", "parameter"),
    [
        ("--step-m", "0", "grid_step_m"),
        ("--smoothing-m", "-1", "smoothing_window_m"),
        ("--max-offset-m", "20001", "point_match_max_offset_m"),
        ("--min-separation-m", "100001", "point_match_min_separation_m"),
    ],
)
def test_parameter_outside_bounds_is_readable(
    capsys: pytest.CaptureFixture[str],
    option: str,
    value: str,
    parameter: str,
) -> None:
    assert main(["profile", str(FIXTURES / "mini_11.gpx"), option, value]) != 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert parameter in captured.err
    assert "doit être dans" in captured.err
    assert "Traceback" not in captured.err


def test_missing_file_is_readable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["profile", str(tmp_path / "absent.gpx")]) != 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Erreur" in captured.err
    assert "Traceback" not in captured.err


# ---------------------------------------------------------------------------
# Sorties sous une console cp1252
# ---------------------------------------------------------------------------


def _cp1252(errors: str) -> tuple[io.BytesIO, io.TextIOWrapper]:
    """Ce que Python ouvre sur une sortie redirigée sous Windows."""
    raw = io.BytesIO()
    return raw, io.TextIOWrapper(raw, encoding="cp1252", errors=errors)


def test_report_is_utf8_under_a_cp1252_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw, stream = _cp1252("strict")
    monkeypatch.setattr(sys, "stdout", stream)
    assert main(["profile", str(FIXTURES / "mini_11.gpx")]) == 0
    stream.flush()
    # Décodé en UTF-8 : en cp1252, un flux non reconfiguré passerait sur « é ».
    text = raw.getvalue().decode("utf-8")
    assert "lissage      150 m demandé → 150 m effectif (3 points)" in text
    assert "D+ 44 m / D− 44 m" in text
    assert stream.errors == "strict"


def test_help_is_utf8_under_a_cp1252_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw, stream = _cp1252("strict")
    monkeypatch.setattr(sys, "stdout", stream)
    # Sous 25 colonnes, argparse couperait la ligne de l'aide.
    monkeypatch.setenv("COLUMNS", "80")
    with pytest.raises(SystemExit) as exit_info:
        main(["project", "--help"])
    assert exit_info.value.code == 0
    stream.flush()
    assert "Courbe allure↔pente" in raw.getvalue().decode("utf-8")


def test_error_is_utf8_under_a_cp1252_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw, stream = _cp1252("backslashreplace")
    monkeypatch.setattr(sys, "stderr", stream)
    assert main(["profile", str(FIXTURES / "absent_é.gpx")]) == 1
    stream.flush()
    # En cp1252, « é » s'écrit 0xE9, qui n'est pas de l'UTF-8 : le décodage échouerait.
    text = raw.getvalue().decode("utf-8")
    assert text.startswith("Erreur : ")
    assert "absent_é.gpx" in text
    assert stream.errors == "backslashreplace"


def test_other_streams_are_left_as_they_are(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    assert main(["profile", str(FIXTURES / "mini_11.gpx")]) == 0
    assert "lissage      150 m demandé → 150 m effectif (3 points)" in stream.getvalue()
