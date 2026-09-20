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
import math
from pathlib import Path

import pytest

from fixtures.curves import SUPPORT_CURVE
from fixtures.projection import CURVE_REF, ENDPOINTS, SIX_INTERVAL_PROFILE
from mountain_perf.cli import PASSAGE_CSV_HEADER, main, write_passages_csv
from mountain_perf.gpx.geo import EARTH_RADIUS_M
from mountain_perf.model.engine import PROJECTION_PARAMETER_SPECS, project
from mountain_perf.schemas import ParameterSet

FIXTURES = Path(__file__).parent / "fixtures"
GPX = FIXTURES / "mini_11.gpx"
CURVE = FIXTURES / "courbe_synthetique.csv"

TIME_TOLERANCE_S = 1e-6

EXPECTED_HEADER = (
    "name",
    "distance_m",
    "elevation_m",
    "arrival_s",
    "departure_s",
    "moving_time_s",
    "segment_duration_s",
    "segment_distance_m",
    "segment_ascent_m",
    "segment_descent_m",
)
"""L'en-tête du § 4.5 du brief, écrit en toutes lettres.

Importer ``PASSAGE_CSV_HEADER`` ferait un oracle qui vérifie ce qu'il produit :
renommer une colonne des deux côtés passerait inaperçu.
"""


def test_production_header_matches_the_brief() -> None:
    assert PASSAGE_CSV_HEADER == EXPECTED_HEADER


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
    assert tuple(rows[0]) == EXPECTED_HEADER
    return [dict(zip(EXPECTED_HEADER, row, strict=True)) for row in rows[1:]]


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


def test_csv_elevations_come_from_the_smoothed_profile() -> None:
    """Les altitudes écrites sont celles du profil, pas des zéros (L03).

    Rien ne les vérifiait : les mettre toutes à zéro passait.
    """
    altitudes = [float(row["elevation_m"]) for row in written_rows()]
    assert altitudes == list(SIX_INTERVAL_PROFILE.elevation_m[i] for i in (0, 2, -1))
    assert altitudes == [1000.0, 1000.0, 1020.0]


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
    assert tuple(rows[0]) == EXPECTED_HEADER
    first = dict(zip(EXPECTED_HEADER, rows[1], strict=True))
    assert first["name"] == "Départ"
    assert float(first["distance_m"]) == 0.0
    assert first["segment_duration_s"] == ""


def steep_gpx(tmp_path: Path) -> Path:
    """Méridien de 300 m : plat, puis +40 %, puis plat. Pas 100 m, sans lissage.

    Un tiers de la distance sort du support ±20 % de la courbe synthétique, et
    comme le prolongement y est lent (2 s/m contre 1/3), il pèse les trois quarts
    du temps. C'est le cas qui rend les parts affichées observables.
    """
    latitudes = [45 + math.degrees(d / EARTH_RADIUS_M) for d in (0, 100, 200, 300)]
    points = "".join(
        f'<trkpt lat="{lat:.14f}" lon="6"><ele>{ele}</ele></trkpt>'
        for lat, ele in zip(latitudes, (1000, 1000, 1040, 1040), strict=True)
    )
    path = tmp_path / "raide.gpx"
    path.write_text(f"<gpx><trk><trkseg>{points}</trkseg></trk></gpx>", "utf-8")
    return path


def test_report_shows_non_zero_out_of_support_shares(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Les parts hors support sont calculées, pas écrites en dur (L06).

    Le seul cas testé jusqu'ici valait 0 % des deux côtés : remplacer le calcul
    par la chaîne « 0 % » passait.
    """
    argv = [
        "project",
        str(steep_gpx(tmp_path)),
        "--curve",
        str(CURVE),
        "--step-m",
        "100",
        "--smoothing-m",
        "0",
    ]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "hors support : 33 % de la distance, 75 % du temps" in out
    assert "pentes rencontrées : +0 % … +40 %" in out
    # 100/3 + 200 + 100/3 s, soit 4 min 27 s arrondies.
    assert "durée        0:04:27" in out


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
