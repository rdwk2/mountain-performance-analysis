"""``mperf project … --at D`` (OG-UI, § 6.3 (b) du brief) : la courbe à l'origine de la
course, calculée en mémoire, puis la projection.

La commande ne se lance jamais sur le vrai dossier des données : elle se teste par
``main([...])``, l'horloge ``cli._now`` fixée au 2024-04-01 12:00 UTC, sur le monde
``interim/`` des fixtures recalé (``tests/test_og1_cli_at.py``). La seconde voie
appelle à part les fonctions de ``runs.py`` et de ``reports.py``."""

from __future__ import annotations

import dataclasses
import io
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from fixtures.matching import MATCH_REFERENCE_GPX
from fixtures.processed import write_interim
from mountain_perf import cli
from mountain_perf.cli import main
from mountain_perf.config import DATA_DIR_ENV_VAR, data_dir
from mountain_perf.estimation.origin import OriginWindow
from mountain_perf.ingest.interim import read_index, read_recording, write_activities
from mountain_perf.model.export import write_passages_csv
from mountain_perf.reports import (
    curve_warnings,
    origin_curve_lines,
    passage_lines,
    projection_summary_lines,
)
from mountain_perf.runs import (
    FOLDER_ATHLETE,
    OriginCurve,
    RouteProjection,
    course_origin,
    curve_selection,
    load_curve_corpus,
    origin_curve,
    project_route,
)
from test_ingest_interim import REPORT
from test_og1_cli_at import realign

NOW = datetime(2024, 4, 1, 12, tzinfo=UTC)
TODAY = date(2024, 4, 1)
FIXTURES = Path(__file__).parent / "fixtures"
ROUTE = FIXTURES / "mini_11.gpx"
FOLLOWED = FIXTURES / MATCH_REFERENCE_GPX
CURVE = FIXTURES / "courbe_synthetique.csv"
MISSING = (
    "Erreur : --curve ou --at est obligatoire. Une courbe implicite rendrait la "
    "projection non reproductible.\n"
)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_now", lambda: NOW)


def write_aligned() -> Path:
    folder = data_dir()
    write_interim(folder)
    realign(folder)
    return folder


def project(
    capsys: pytest.CaptureFixture[str], *arguments: str
) -> tuple[int, str, str]:
    code = main(["project", *arguments])
    out, err = capsys.readouterr()
    return code, out, err


def second_way(
    route: Path, day: date, window: OriginWindow = 56, **values: float
) -> tuple[OriginCurve, RouteProjection]:
    """La courbe et la projection par les fonctions de ``runs.py`` appelées à part."""
    course = course_origin(day, TODAY)
    corpus = load_curve_corpus(
        data_dir(),
        FOLDER_ATHLETE,
        curve_selection().source_activity_types,
        course.origin,
        window,
    )
    curve = origin_curve(corpus, course, window, generated_at=NOW)
    assert curve.curve is not None
    return curve, project_route(route, curve.curve, {}, values)


def expected_lines(curve: OriginCurve, run: RouteProjection) -> list[str]:
    return [
        *origin_curve_lines(curve),
        *projection_summary_lines(run),
        *(
            f"avertissement : {warning}"
            for warning in curve_warnings(
                curve.result.history, run.diagnostics.out_of_support_time_share
            )
        ),
        *passage_lines(run.projection),
    ]


# --- La projection à l'origine --------------------------------------------------------


def test_project_at_prints_the_origin_lines_and_the_projection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_aligned()
    code, out, err = project(capsys, str(ROUTE), "--at", "2024-03-25")
    assert code == 0
    assert err == ""
    lines = out.splitlines()
    assert lines[0] == (
        "jour 2024-03-25 : origine 2024-03-18 00:00 à Paris ; fenêtre 56 jours, fins "
        "depuis le 2024-01-22 00:00 à Paris"
    )
    assert "activités retenues : 1 sur 2 candidates ; 1:04:52 en mouvement" in lines
    assert any(
        line.startswith("courbe       origine-2024-03-25-w56.csv   sha256 ")
        for line in lines
    )
    warnings = [line for line in lines if line.startswith("avertissement : ")]
    assert len(warnings) == 2
    assert warnings[0].startswith(
        "avertissement : moins de 20 sorties à pied passées (2) : "
    )
    assert warnings[1].startswith(
        "avertissement : 100 % du temps prévu hors du support "
    )
    curve, run = second_way(ROUTE, date(2024, 3, 25))
    assert lines == expected_lines(curve, run)


def test_project_at_bounded(capsys: pytest.CaptureFixture[str]) -> None:
    write_aligned()
    code, out, _ = project(capsys, str(ROUTE), "--at", "2024-04-20")
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == (
        "course le 2024-04-20 : au-delà de 7 jours, origine bornée à aujourd'hui "
        "(celle d'une course le 2024-04-08) ; ce n'est pas la courbe que le backtest "
        "prendrait pour cette course"
    )
    assert lines[1] == (
        "jour 2024-04-08 : origine 2024-04-01 00:00 à Paris ; fenêtre 56 jours, fins "
        "depuis le 2024-02-05 00:00 à Paris"
    )
    curve, run = second_way(ROUTE, date(2024, 4, 20))
    assert curve.course.bounded
    assert lines == expected_lines(curve, run)


def test_project_at_not_bounded_has_no_bounded_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_aligned()
    _, out, _ = project(capsys, str(ROUTE), "--at", "2024-04-08")
    assert not out.startswith("course le ")
    assert out.splitlines()[0].startswith("jour 2024-04-08 : origine 2024-04-01 ")


def test_project_at_without_support_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_aligned()
    code, out, _ = project(capsys, str(FOLLOWED), "--at", "2024-03-25")
    assert code == 0
    warnings = [
        line for line in out.splitlines() if line.startswith("avertissement : ")
    ]
    assert len(warnings) == 1
    assert warnings[0].startswith("avertissement : moins de 20 sorties à pied ")
    curve, run = second_way(FOLLOWED, date(2024, 3, 25))
    assert run.diagnostics.out_of_support_time_share == 0
    assert out.splitlines() == expected_lines(curve, run)


def test_project_at_absence(capsys: pytest.CaptureFixture[str]) -> None:
    write_aligned()
    code, out, err = project(capsys, str(ROUTE), "--at", "2024-03-25", "--window", "7")
    assert code == 1
    lines = out.splitlines()
    assert lines[0] == (
        "jour 2024-03-25 : origine 2024-03-18 00:00 à Paris ; fenêtre 7 jours, fins "
        "depuis le 2024-03-11 00:00 à Paris"
    )
    course = course_origin(date(2024, 3, 25), TODAY)
    corpus = load_curve_corpus(data_dir(), FOLDER_ATHLETE, TRAIL, course.origin, 7)
    curve = origin_curve(corpus, course, 7, generated_at=NOW)
    assert curve.curve is None
    assert lines == list(origin_curve_lines(curve))
    reason = curve.result.absence_reason
    assert err == f"Erreur : aucune courbe à l'origine : {reason}\n"


TRAIL = frozenset({"trail_running"})


def test_project_at_all_the_past(capsys: pytest.CaptureFixture[str]) -> None:
    write_aligned()
    code, out, _ = project(capsys, str(ROUTE), "--at", "2024-03-25", "--window", "all")
    assert code == 0
    assert out.splitlines()[0] == (
        "jour 2024-03-25 : origine 2024-03-18 00:00 à Paris ; fenêtre tout le passé"
    )
    curve, run = second_way(ROUTE, date(2024, 3, 25), "all")
    assert out.splitlines() == expected_lines(curve, run)


# --- Le CSV ---------------------------------------------------------------------------


def test_project_at_with_csv_prints_only_the_csv(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_aligned()
    code, out, err = project(capsys, str(ROUTE), "--at", "2024-03-25", "--csv")
    assert code == 0
    curve, run = second_way(ROUTE, date(2024, 3, 25))
    stream = io.StringIO()
    write_passages_csv(run.projection, stream)
    assert out == stream.getvalue()
    expected = [
        *origin_curve_lines(curve),
        *(
            f"avertissement : {warning}"
            for warning in curve_warnings(
                curve.result.history, run.diagnostics.out_of_support_time_share
            )
        ),
    ]
    assert err.splitlines() == expected
    assert len([line for line in expected if line.startswith("avertissement")]) == 2


# --- Les options ----------------------------------------------------------------------


def test_neither_curve_nor_at(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = project(capsys, str(ROUTE))
    assert code == 1
    assert out == ""
    assert err.startswith("usage: mperf project")
    assert err.endswith(MISSING)


def test_curve_and_at_exclude_each_other(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["project", str(ROUTE), "--curve", str(CURVE), "--at", "2024-03-25"])
    assert raised.value.code == 2


def test_the_curve_alone_is_today_s_projection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _ = project(capsys, str(ROUTE), "--curve", str(CURVE))
    assert code == 0
    assert out.startswith("fichier      mini_11.gpx")


def test_window_without_at(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = project(
        capsys, str(ROUTE), "--curve", str(CURVE), "--window", "28"
    )
    assert code == 1
    assert out == ""
    assert err == "Erreur : --window demande --at.\n"


def test_window_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["project", str(ROUTE), "--at", "2024-03-25", "--window", "0"])
    assert raised.value.code == 2


# --- La courbe non projetable ---------------------------------------------------------


def write_not_projectable() -> None:
    """Le monde du § 6.2, l'index réécrit : ``a1`` en ``running_x``, ``a2`` en
    ``trail_running`` ; ``a2`` seule retenue, la tranche centrale sous 10 min."""
    folder = write_aligned()
    index = read_index(folder)
    types = {"a1": "running_x", "a2": "trail_running"}
    entries = tuple(
        dataclasses.replace(
            item,
            source_activity_type=types.get(
                item.activity_ref, item.source_activity_type
            ),
        )
        for item in index.entries
    )
    recordings = [
        read_recording(folder, item.activity_ref)
        for item in index.entries
        if item.has_recording
    ]
    rewritten = dataclasses.replace(index, entries=entries)
    write_activities(folder, rewritten, recordings, REPORT)


def test_a_not_projectable_curve_stops_the_reading(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_not_projectable()
    code, out, err = project(capsys, str(ROUTE), "--at", "2024-03-25")
    assert code == 1
    assert out == ""
    assert err.startswith("Erreur : La tranche centrale de pente ")


def test_a_not_projectable_curve_read_at_four_minutes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_not_projectable()
    code, out, _ = project(
        capsys, str(ROUTE), "--at", "2024-03-25", "--min-support-min", "4"
    )
    assert code == 0
    lines = out.splitlines()
    marks = [line for line in lines if line.startswith("Courbe non projetable")]
    assert len(marks) == 1
    assert marks[0].startswith(
        "Courbe non projetable par read_curve : La tranche centrale de pente "
    )
    curve, run = second_way(ROUTE, date(2024, 3, 25), curve_min_support_min=4.0)
    assert curve.result.support_error is not None
    assert lines == expected_lines(curve, run)


# --- Les erreurs ----------------------------------------------------------------------


@pytest.mark.parametrize("case", ["sans-dossier", "sans-interim", "gpx-illisible"])
def test_project_at_errors_leave_stdout_empty(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case: str,
) -> None:
    route = ROUTE
    if case == "sans-dossier":
        monkeypatch.delenv(DATA_DIR_ENV_VAR)
    elif case == "gpx-illisible":
        write_aligned()
        route = tmp_path / "illisible.gpx"
        route.write_text("<gpx>", encoding="utf-8")
    code, out, err = project(capsys, str(route), "--at", "2024-03-25")
    assert code == 1
    assert out == ""
    assert err.startswith("Erreur : ")
    assert "Traceback" not in err
