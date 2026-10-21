"""La page « projection », par ``AppTest``, sans navigateur ni serveur (§ 6.9 et § 8.2
du brief M5-1).

Les données sont les fixtures, copiées dans ``data_dir()`` (le dossier neuf de
``tests/conftest.py``). Sautés sans l'extra ``tableau``.
"""

import shutil
from collections.abc import Mapping
from datetime import date, time
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

import mountain_perf
from mountain_perf.config import DATA_DIR_ENV_VAR, data_dir
from mountain_perf.data_files import FileKind
from mountain_perf.reports import projection_summary_lines
from mountain_perf.runs import RouteProjection, project_route

APP = Path(mountain_perf.__file__).parent / "ui" / "app.py"
FIXTURES = Path(__file__).parent / "fixtures"
ROUTE = FIXTURES / "mini_11.gpx"
TRACE = FIXTURES / "appariement_trace_x01.gpx"
CURVE = FIXTURES / "courbe_synthetique.csv"
COMPANION = FIXTURES / "courbe_synthetique.meta.json"
TIMEOUT_S = 30

COLUMNS = [
    "passage",
    "distance (m)",
    "altitude (m)",
    "temps",
    "heure",
    "tronçon (m)",
    "D+ (m)",
    "D− (m)",
    "durée",
    "allure",
    "montée horaire",
]


def _app() -> AppTest:
    return AppTest.from_file(APP, default_timeout=TIMEOUT_S).run()


def _with_route() -> Path:
    routes = data_dir() / "routes"
    routes.mkdir(exist_ok=True)
    shutil.copy(ROUTE, routes / ROUTE.name)
    return routes / ROUTE.name


def _with_curve() -> Path:
    reference = data_dir() / "reference"
    reference.mkdir(exist_ok=True)
    shutil.copy(CURVE, reference / CURVE.name)
    shutil.copy(COMPANION, reference / COMPANION.name)
    return reference / CURVE.name


def _tree() -> list[str]:
    root = data_dir()
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


def _summary(at: AppTest) -> list[str]:
    (block,) = at.code
    return str(block.value).split("\n")


# ---------------------------------------------------------------------------
# Le dossier des données, les listes vides
# ---------------------------------------------------------------------------


def test_without_data_dir_the_error_is_shown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATA_DIR_ENV_VAR)
    at = _app()
    assert not at.exception
    assert len(at.error) == 1
    assert "La variable d'environnement MPA_DATA_DIR n'est pas définie" in str(
        at.error[0].value
    )


def test_an_empty_data_dir_asks_for_a_route() -> None:
    at = _app()
    assert not at.exception
    assert [str(info.value) for info in at.info] == [
        "Aucun préparé dans routes/ : ajoute un GPX (barre latérale)."
    ]


def test_a_route_without_curve_asks_for_a_curve() -> None:
    _with_route()
    at = _app()
    assert not at.exception
    assert [str(info.value) for info in at.info] == [
        "Aucune courbe (CSV et son .meta.json) dans reference/."
    ]


# ---------------------------------------------------------------------------
# La projection
# ---------------------------------------------------------------------------


def test_the_page_shows_the_summary_the_table_and_the_export() -> None:
    route, curve = _with_route(), _with_curve()
    at = _app()
    assert not at.exception
    assert not at.error
    expected = projection_summary_lines(project_route(route, curve, {}, {}))
    assert _summary(at) == list(expected)
    (table,) = at.dataframe
    assert list(table.value.columns) == COLUMNS
    assert len(table.value) == 4
    assert list(table.value["passage"]) == ["Départ", "Départ", "Col", "Arrivée"]
    assert list(table.value["heure"]) == ["—"] * 4
    assert len(at.download_button(key="export").proto.label) > 0


def test_the_effort_slider_changes_the_summary() -> None:
    _with_route()
    _with_curve()
    at = _app()
    assert "effort       1.00" in _summary(at)
    at.slider(key="projection.effort").set_value(0.9).run()
    assert not at.exception
    assert "effort       0.90" in _summary(at)


def test_the_page_passes_only_the_changed_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un espion à la place de ``project_route`` dans le module de la page, qui appelle
    la vraie : au défaut, les deux jeux valent ``{}``."""
    calls: list[tuple[dict[str, float], dict[str, float]]] = []

    def spy(
        route_path: Path,
        curve_path: Path,
        profile_values: Mapping[str, float],
        projection_values: Mapping[str, float],
    ) -> RouteProjection:
        calls.append((dict(profile_values), dict(projection_values)))
        return project_route(route_path, curve_path, profile_values, projection_values)

    monkeypatch.setattr("mountain_perf.ui.projection.project_route", spy)
    _with_route()
    _with_curve()
    at = _app()
    at.slider(key="projection.effort").set_value(0.9).run()
    assert not at.exception
    assert calls == [({}, {}), ({}, {"effort": 0.9})]


def test_a_start_time_fills_the_clock_column() -> None:
    _with_route()
    _with_curve()
    at = _app()
    at.checkbox(key="depart").check().run()
    at.date_input(key="depart_jour").set_value(date(2026, 7, 1))
    at.time_input(key="depart_heure").set_value(time(8, 0)).run()
    assert not at.exception
    (table,) = at.dataframe
    clock = list(table.value["heure"])
    assert clock[0] == "01/07 08:00"
    assert all(value != "—" for value in clock)


def test_an_unreadable_curve_is_an_error_without_traceback() -> None:
    _with_route()
    reference = data_dir() / "reference"
    reference.mkdir()
    (reference / "fausse.csv").write_bytes(b"pas,une,courbe\n")
    shutil.copy(COMPANION, reference / "fausse.meta.json")
    at = _app()
    assert not at.exception
    assert len(at.error) == 1
    assert not at.code


# ---------------------------------------------------------------------------
# L'ajout d'un fichier
# ---------------------------------------------------------------------------


def _upload(at: AppTest, path: Path, content: bytes | None = None) -> None:
    data = path.read_bytes() if content is None else content
    upload = at.file_uploader(key="ajout_fichier")
    upload.set_value((path.name, data, "application/gpx+xml")).run()


def test_a_route_is_added_on_click() -> None:
    at = _app()
    _upload(at, ROUTE)
    at.button(key="ajout_bouton").click().run()
    assert not at.exception
    assert (data_dir() / "routes" / ROUTE.name).read_bytes() == ROUTE.read_bytes()
    assert [str(s.value) for s in at.success] == ["mini_11.gpx ajouté à routes/."]


def test_an_outing_is_added_to_its_folder() -> None:
    at = _app()
    at.radio(key="ajout_sorte").set_value(FileKind.OUTING).run()
    _upload(at, TRACE)
    at.button(key="ajout_bouton").click().run()
    assert not at.exception
    assert (data_dir() / "sorties" / TRACE.name).read_bytes() == TRACE.read_bytes()
    assert not (data_dir() / "routes").exists()


def test_an_upload_without_click_writes_nothing() -> None:
    at = _app()
    _upload(at, ROUTE)
    at.run()
    assert not at.exception
    assert _tree() == []


def test_a_refused_file_is_an_error_and_writes_nothing() -> None:
    at = _app()
    _upload(at, ROUTE, b"pas du XML")
    at.button(key="ajout_bouton").click().run()
    assert not at.exception
    assert len(at.error) == 1
    assert str(at.error[0].value).startswith(
        "mini_11.gpx ne se lit pas comme un tracé préparé : "
    )
    assert _tree() == []
