"""Commande ``mperf project`` : le tableau du brief, le bout en bout, les erreurs.

Le tableau du § 5.6 du brief teste **l'association tronçon ↔ ligne**, pas la
géométrie d'un GPX : il est vérifié sur la sortie de ``write_passages_csv`` appliquée
au profil synthétique, dont les distances et les dénivelés sont exacts. Un
aller-retour par un GPX ne le permettrait pas — les distances haversine d'un méridien
de sept points espacés de 100 m tombent à 599,999 999 999 7 m, et les pentes à
0,100 000 000 000 3. Le bout en bout est vérifié séparément, sur ``mini_11.gpx``.
"""

import csv
import io
from pathlib import Path

import pytest

from fixtures.curves import SUPPORT_CURVE
from fixtures.projection import CURVE_REF, ENDPOINTS, SIX_INTERVAL_PROFILE
from mountain_perf.cli import PASSAGE_CSV_HEADER, main, write_passages_csv
from mountain_perf.model.engine import PROJECTION_PARAMETER_SPECS, project
from mountain_perf.schemas import ParameterSet

FIXTURES = Path(__file__).parent / "fixtures"
GPX = FIXTURES / "mini_11.gpx"
CURVE = FIXTURES / "courbe_synthetique.csv"

TIME_TOLERANCE_S = 1e-6


def written_rows() -> list[dict[str, str]]:
    """Les cellules réellement écrites par la commande, pas un recalcul."""
    projection = project(
        SIX_INTERVAL_PROFILE,
        SUPPORT_CURVE,
        ParameterSet(PROJECTION_PARAMETER_SPECS),
        curve_ref=CURVE_REF,
        endpoints=ENDPOINTS,
    )
    stream = io.StringIO()
    write_passages_csv(projection, stream)
    rows = list(csv.reader(io.StringIO(stream.getvalue())))
    assert tuple(rows[0]) == PASSAGE_CSV_HEADER
    return [dict(zip(PASSAGE_CSV_HEADER, row, strict=True)) for row in rows[1:]]


# ---------------------------------------------------------------------------
# Le tableau du brief, cellule par cellule
# ---------------------------------------------------------------------------


def test_csv_first_row_has_no_preceding_segment() -> None:
    row = written_rows()[0]
    assert row["name"] == "Départ"
    assert float(row["distance_m"]) == 0.0
    assert float(row["arrival_s"]) == 0.0
    assert row["segment_duration_s"] == ""
    assert row["segment_distance_m"] == ""
    assert row["segment_ascent_m"] == ""
    assert row["segment_descent_m"] == ""


def test_csv_named_passage_row() -> None:
    row = written_rows()[1]
    assert row["name"] == "Refuge"
    assert float(row["distance_m"]) == 250.0
    assert float(row["arrival_s"]) == pytest.approx(370 / 3, abs=TIME_TOLERANCE_S)
    assert float(row["segment_duration_s"]) == pytest.approx(
        370 / 3, abs=TIME_TOLERANCE_S
    )
    assert float(row["segment_distance_m"]) == 250.0
    assert float(row["segment_ascent_m"]) == 10.0
    assert float(row["segment_descent_m"]) == 10.0


def test_csv_last_row_describes_only_the_last_leg() -> None:
    """Le mode d'échec que ce tableau vise : ``segment_duration_s = arrival_s``.

    Un moteur parfaitement juste peut être exporté avec le cumulé dans la colonne
    du tronçon. Sur la ligne de 250 m la faute serait invisible — ``370/3`` dans les
    deux conventions — et seule cette ligne-ci la trahit, en affirmant que le
    dernier tronçon dure toute la projection.
    """
    row = written_rows()[2]
    assert row["name"] == "Arrivée"
    assert float(row["distance_m"]) == 600.0
    assert float(row["arrival_s"]) == pytest.approx(540.0, abs=TIME_TOLERANCE_S)
    assert float(row["segment_duration_s"]) == pytest.approx(
        1250 / 3, abs=TIME_TOLERANCE_S
    )
    assert float(row["segment_distance_m"]) == 350.0
    assert float(row["segment_ascent_m"]) == 60.0
    assert float(row["segment_descent_m"]) == 40.0


def test_csv_carries_the_m3_timing_convention() -> None:
    for row in written_rows():
        assert row["arrival_s"] == row["departure_s"] == row["moving_time_s"]


# ---------------------------------------------------------------------------
# Bout en bout
# ---------------------------------------------------------------------------


def test_report_on_mini_gpx(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["project", str(GPX), "--curve", str(CURVE)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "fichier      mini_11.gpx   sha256 " in captured.out
    assert "courbe       courbe_synthetique.csv   sha256 " in captured.out
    assert "3 activités, 2026-01-01 → 2026-01-31" in captured.out
    assert "grille       1 000 m, 21 points, pas 50 m" in captured.out
    assert (
        "9 tranches lues, 5 retenues (>= 10 min), plage −20 % … +20 %" in captured.out
    )
    assert "hors support : 0 % de la distance, 0 % du temps" in captured.out
    assert "effort       1.00" in captured.out
    assert "départ et arrivée synthétisés" in captured.out


def test_end_to_end_csv_header_and_first_row(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["project", str(GPX), "--curve", str(CURVE), "--csv"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    rows = list(csv.reader(io.StringIO(captured.out)))
    assert tuple(rows[0]) == PASSAGE_CSV_HEADER
    first = dict(zip(PASSAGE_CSV_HEADER, rows[1], strict=True))
    assert first["name"] == "Départ"
    assert float(first["distance_m"]) == 0.0
    assert first["segment_duration_s"] == ""


def test_effort_changes_the_projected_time(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def total_s(*extra: str) -> float:
        assert main(["project", str(GPX), "--curve", str(CURVE), "--csv", *extra]) == 0
        rows = list(csv.reader(io.StringIO(capsys.readouterr().out)))
        return float(rows[-1][PASSAGE_CSV_HEADER.index("arrival_s")])

    assert total_s("--effort", "0.8") == pytest.approx(total_s() / 0.8, rel=1e-9)


# ---------------------------------------------------------------------------
# Erreurs d'entrée
# ---------------------------------------------------------------------------


def test_missing_curve_option_fails_with_usage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Une courbe implicite rendrait la projection non reproductible."""
    assert main(["project", str(GPX)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage: mperf project" in captured.err
    assert "--curve" in captured.err
    assert "Traceback" not in captured.err


def test_missing_companion_names_the_expected_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    orphan = tmp_path / "sans_compagnon.csv"
    orphan.write_text(CURVE.read_text(encoding="utf-8"), encoding="utf-8")
    assert main(["project", str(GPX), "--curve", str(orphan)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "sans_compagnon.meta.json" in captured.err
    assert "Traceback" not in captured.err


def test_unreadable_curve_has_no_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "entete.csv"
    broken.write_text(
        CURVE.read_text(encoding="utf-8").replace("vam_mh", "vam"), encoding="utf-8"
    )
    (tmp_path / "entete.meta.json").write_text(
        (FIXTURES / "courbe_synthetique.meta.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assert main(["project", str(GPX), "--curve", str(broken)]) == 1
    captured = capsys.readouterr()
    assert "En-tête inattendu" in captured.err
    assert "Traceback" not in captured.err


def test_missing_curve_file_is_readable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["project", str(GPX), "--curve", str(tmp_path / "absente.csv")]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Erreur" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("option", "value", "parameter"),
    [
        ("--effort", "0.4", "effort"),
        ("--effort", "1.6", "effort"),
        ("--min-support-min", "-1", "curve_min_support_min"),
        ("--min-support-min", "1441", "curve_min_support_min"),
        ("--step-m", "0", "grid_step_m"),
    ],
)
def test_parameter_outside_bounds_is_readable(
    capsys: pytest.CaptureFixture[str], option: str, value: str, parameter: str
) -> None:
    assert main(["project", str(GPX), "--curve", str(CURVE), option, value]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert parameter in captured.err
    assert "doit être dans" in captured.err
    assert "Traceback" not in captured.err
