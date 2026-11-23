"""La Fenêtre dans l'interface (AN4-1, § 6 et § 8 du brief), P1 à P14 : le contrôle de
la barre latérale, sa clé à part, la page « récupération » sur la Fenêtre, par
``AppTest.from_function``. Les tables du monde inventé (``fixtures.recovery_world``),
sans montée ni variante (§ 7.3), sauf P10 ; écrites sous ``data_dir()``, le dossier
neuf de ``tests/conftest.py``. Sautés sans les extras ``tableau`` et ``analyse``."""

from __future__ import annotations

import ast
import dataclasses
import json
import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("pyarrow")

import streamlit as st
from streamlit.testing.v1 import AppTest

import mountain_perf
from fixtures.recovery_world import base_tables, world_tables, write_world
from mountain_perf.analyse.tables import Tables
from mountain_perf.config import data_dir
from mountain_perf.schemas.processed import ClimbRow, DayRow
from mountain_perf.ui.piste import (
    CHOICE_WIDGET,
    EMPTY_RANGE,
    FIRST_WIDGET,
    LAST_WIDGET,
    RANGE_FIRST_KEY,
    RANGE_LAST_KEY,
    WINDOW_KEY,
    WINDOW_LABELS,
)

TIMEOUT_S = 30
UI = Path(mountain_perf.__file__).parent / "ui"
LABELS = ["28 jours", "56 jours", "90 jours", "tout l'historique", "plage"]
VALUE_SUFFIXES = (
    "-valeurs-pleines",
    "-valeurs-creuses",
    "-valeurs-hors-etendue",
    "-valeurs-en-pied",
)
PLUS_2 = timezone(timedelta(hours=2))
DATA_CAPTION = (
    "Données au 21/05/2000 à 21 h 15 (heure de Paris). Exploratoire : aucune alerte, "
    "aucun verdict."
)
EMPTY_DAYS = (
    "La table jours n'a aucune ligne : aucun export ne porte de données journalières "
    "(une archive Strava n'en a pas), ou interim/ n'est pas à jour : lancer just "
    "process."
)


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> Tables:
    return base_tables(tmp_path_factory.mktemp("base"))


@pytest.fixture(autouse=True)
def _empty_cache() -> Iterator[None]:
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


def _write(
    base: Tables,
    climbs: tuple[ClimbRow, ...] = (),
    *,
    rows: Sequence[DayRow] | None = None,
) -> Tables:
    """Les tables du monde (ou ``rows`` pour lignes de ``jours``), avec ``climbs`` pour
    seules montées et sans variante."""
    tables = dataclasses.replace(
        world_tables(base, rows=rows), climbs=climbs, variants=()
    )
    write_world(data_dir(), tables)
    return tables


def _recovery() -> None:
    from mountain_perf.ui.recuperation import recuperation_page

    recuperation_page()


def _q1() -> None:
    from mountain_perf.ui.q1 import q1_page

    q1_page()


def _q2() -> None:
    from mountain_perf.ui.q2 import q2_page

    q2_page()


def _app(
    page: Callable[[], None], state: Mapping[str, object] | None = None
) -> AppTest:
    """La page, la session posée par ``state`` avant la première exécution."""
    at = AppTest.from_function(page, default_timeout=TIMEOUT_S)
    for key, value in (state or {}).items():
        at.session_state[key] = value
    return at.run()


def _specs(at: AppTest) -> list[dict[str, Any]]:
    return [json.loads(element.proto.spec) for element in at.get("vega_lite_chart")]


def _points(at: AppTest) -> list[int]:
    """Le nombre de jours de chaque graphique de mesure : les données de ses quatre
    couches de valeurs (chaque jour est dans une seule)."""
    counts = []
    for spec in _specs(at):
        layers = [
            layer for layer in spec["layer"] if layer["name"].endswith(VALUE_SUFFIXES)
        ]
        if layers:
            counts.append(sum(len(layer["data"]["values"]) for layer in layers))
    return counts


def _captions(at: AppTest) -> list[str]:
    return [caption.value for caption in at.caption]


def _radio(at: AppTest) -> Any:
    return at.sidebar.radio(key=CHOICE_WIDGET)


def test_p1_without_key_the_default_is_56_days(base: Tables) -> None:
    _write(base)
    at = _app(_recovery)
    assert not at.exception
    radio = _radio(at)
    assert radio.label == "Fenêtre"
    assert radio.options == LABELS
    assert list(WINDOW_LABELS.values()) == LABELS
    assert radio.value == "56"
    assert radio.proto.horizontal is True
    assert "Du 27/03/2000 au 21/05/2000." in _captions(at)
    assert _points(at) == [56] * 6
    assert not at.sidebar.date_input


def test_p2_the_kept_choice_is_read_on_the_first_run(base: Tables) -> None:
    _write(base)
    at = _app(_recovery, {WINDOW_KEY: "90"})
    assert not at.exception
    assert _radio(at).value == "90"
    assert "Du 22/02/2000 au 21/05/2000." in _captions(at)
    assert _points(at) == [90] * 6


def test_p3_the_choice_is_copied_to_its_own_key(base: Tables) -> None:
    _write(base)
    at = _app(_recovery)
    _radio(at).set_value("tout").run()
    assert not at.exception
    assert at.session_state[WINDOW_KEY] == "tout"
    assert "Du 03/01/2000 au 21/05/2000." in _captions(at)
    assert _points(at) == [140] * 6


def test_p4_28_days(base: Tables) -> None:
    _write(base)
    at = _app(_recovery)
    _radio(at).set_value("28").run()
    assert not at.exception
    assert "Du 24/04/2000 au 21/05/2000." in _captions(at)
    assert _points(at) == [28] * 6


def test_p5_a_range_shows_two_dates(base: Tables) -> None:
    _write(base)
    at = _app(_recovery)
    _radio(at).set_value("plage").run()
    assert not at.exception
    first = at.sidebar.date_input(key=FIRST_WIDGET)
    last = at.sidebar.date_input(key=LAST_WIDGET)
    assert (first.label, first.value) == ("Du", date(2000, 3, 27))
    assert (last.label, last.value) == ("Au", date(2000, 5, 21))
    assert (first.proto.format, last.proto.format) == ("DD/MM/YYYY", "DD/MM/YYYY")
    assert len(at.sidebar.date_input) == 2
    _radio(at).set_value("56").run()
    assert not at.exception
    assert not at.date_input


def _range(base: Tables, first: date, last: date) -> AppTest:
    _write(base)
    at = _app(_recovery)
    _radio(at).set_value("plage").run()
    at.sidebar.date_input(key=FIRST_WIDGET).set_value(first).run()
    at.sidebar.date_input(key=LAST_WIDGET).set_value(last).run()
    return at


def test_p6_a_range_of_three_days(base: Tables) -> None:
    at = _range(base, date(2000, 5, 10), date(2000, 5, 12))
    assert not at.exception
    assert at.session_state[RANGE_FIRST_KEY] == date(2000, 5, 10)
    assert at.session_state[RANGE_LAST_KEY] == date(2000, 5, 12)
    assert "Du 10/05/2000 au 12/05/2000." in _captions(at)
    assert _points(at) == [3] * 6


def test_p7_an_upside_down_range_is_said_empty(base: Tables) -> None:
    at = _range(base, date(2000, 5, 12), date(2000, 5, 10))
    assert not at.exception
    assert [info.value for info in at.info] == [EMPTY_RANGE]
    assert EMPTY_RANGE == (
        "La plage est vide : son premier jour vient après le second, ou elle est hors "
        "des données."
    )
    assert _captions(at) == [DATA_CAPTION]
    assert not at.get("vega_lite_chart")


def test_p8_kept_dates_outside_the_data_stay_as_they_are(base: Tables) -> None:
    _write(base)
    state = {
        WINDOW_KEY: "plage",
        RANGE_FIRST_KEY: date(1999, 1, 1),
        RANGE_LAST_KEY: date(2001, 1, 1),
    }
    at = _app(_recovery, state)
    assert not at.exception
    assert at.sidebar.date_input(key=FIRST_WIDGET).value == date(1999, 1, 1)
    assert at.sidebar.date_input(key=LAST_WIDGET).value == date(2001, 1, 1)
    assert "Du 03/01/2000 au 21/05/2000." in _captions(at)


def test_p8_bis_a_kept_range_outside_the_data_is_said_empty(base: Tables) -> None:
    _write(base)
    state = {
        WINDOW_KEY: "plage",
        RANGE_FIRST_KEY: date(2000, 6, 10),
        RANGE_LAST_KEY: date(2000, 6, 20),
    }
    at = _app(_recovery, state)
    assert not at.exception
    assert [info.value for info in at.info] == [EMPTY_RANGE]
    assert _captions(at) == [DATA_CAPTION]
    assert not at.get("vega_lite_chart")


def test_p9_an_unknown_kept_choice_falls_back_to_56(base: Tables) -> None:
    _write(base)
    at = _app(_recovery, {WINDOW_KEY: "abc"})
    assert not at.exception
    assert _radio(at).value == "56"


def _late_climb(base: Tables) -> ClimbRow:
    """Une montée de base, partie le 2000-06-02 à 1 h 30 ``+02`` (le 1er juin en UTC),
    après le dernier jour de ``jours``."""
    assert base.climbs
    return dataclasses.replace(
        base.climbs[0], local_start_time=datetime(2000, 6, 2, 1, 30, tzinfo=PLUS_2)
    )


def test_p10_the_anchor_is_common_to_days_and_climbs(base: Tables) -> None:
    _write(base, (_late_climb(base),))
    at = _app(_recovery)
    assert not at.exception
    assert "Du 08/04/2000 au 02/06/2000." in _captions(at)
    assert _points(at) == [44] * 6
    first = _specs(at)[0]
    dated = [
        layer["encoding"]["x"]
        for layer in first["layer"]
        if layer["encoding"].get("x", {}).get("type") == "temporal"
    ]
    assert dated[0]["scale"]["domain"] == [
        "2000-04-08T00:00:00Z",
        "2000-06-03T00:00:00Z",
    ]


PAGE_FILE = "page_recuperation.py"
OTHER_FILE = "page_autre.py"
APP_FILES = {
    PAGE_FILE: (
        "from mountain_perf.ui.recuperation import recuperation_page\n"
        "\n"
        "recuperation_page()\n"
    ),
    OTHER_FILE: 'import streamlit as st\n\nst.title("Autre page")\n',
    "appli.py": (
        "import streamlit as st\n"
        "\n"
        "page = st.navigation(\n"
        f'    [st.Page("{PAGE_FILE}", title="Récupération"),'
        f' st.Page("{OTHER_FILE}", title="Autre")]\n'
        ")\n"
        "page.run()\n"
    ),
}
"""Une appli jetable : la page « récupération », une page sans le contrôle, et
``st.navigation`` qui les déclare (``AppTest.switch_page`` n'ouvre que des pages
fichiers)."""


def _navigation_app(folder: Path) -> AppTest:
    folder.mkdir()
    for name, text in APP_FILES.items():
        (folder / name).write_text(text, encoding="utf-8")
    return AppTest.from_file(str(folder / "appli.py"), default_timeout=TIMEOUT_S).run()


@pytest.fixture
def default_value_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> Iterator[pytest.LogCaptureFixture]:
    """Le journal de ``streamlit.elements.lib.policies``, capté : son avertissement
    « default value », émis une fois par processus, réarmé ; le journal de Streamlit
    ne se propage pas, d'où le gestionnaire posé sur lui."""
    from streamlit.elements.lib import policies

    monkeypatch.setattr(policies, "_shown_default_value_warning", False)
    logger = logging.getLogger(policies.__name__)
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger=policies.__name__)
    yield caplog
    logger.removeHandler(caplog.handler)


def test_p13_the_window_survives_a_real_change_of_page(
    base: Tables, tmp_path: Path, default_value_log: pytest.LogCaptureFixture
) -> None:
    """La persistance réelle d'une page à l'autre, par ``st.navigation`` : la clé du
    contrôle disparaît sur une page qui ne le pose pas, la clé à part reste, et le
    retour sur la page « récupération » rend le choix (« 90 ») puis la plage ;
    jamais l'avertissement « default value » de Streamlit (le code n'écrit pas la
    clé d'un contrôle)."""
    _write(base)
    at = _navigation_app(tmp_path / "choix")
    assert not at.exception
    _radio(at).set_value("90").run()
    at.switch_page(OTHER_FILE).run()
    assert not at.exception
    assert at.session_state.get(WINDOW_KEY) == "90"
    assert CHOICE_WIDGET not in at.session_state
    at.switch_page(PAGE_FILE).run()
    assert not at.exception
    assert _radio(at).value == "90"
    assert "Du 22/02/2000 au 21/05/2000." in _captions(at)

    at = _navigation_app(tmp_path / "plage")
    _radio(at).set_value("plage").run()
    at.sidebar.date_input(key=FIRST_WIDGET).set_value(date(2000, 5, 10)).run()
    at.sidebar.date_input(key=LAST_WIDGET).set_value(date(2000, 5, 12)).run()
    at.switch_page(OTHER_FILE).run()
    assert not at.exception
    assert FIRST_WIDGET not in at.session_state
    at.switch_page(PAGE_FILE).run()
    assert not at.exception
    assert at.sidebar.date_input(key=FIRST_WIDGET).value == date(2000, 5, 10)
    assert at.sidebar.date_input(key=LAST_WIDGET).value == date(2000, 5, 12)
    assert "Du 10/05/2000 au 12/05/2000." in _captions(at)

    warned = [
        record.getMessage()
        for record in default_value_log.records
        if "default value" in record.getMessage()
    ]
    assert not warned


def test_p13_bis_the_six_keys_are_distinct() -> None:
    """Les deux clés à part de la plage, celle du choix et les trois clés des
    contrôles sont six chaînes deux à deux différentes."""
    keys = (
        WINDOW_KEY,
        RANGE_FIRST_KEY,
        RANGE_LAST_KEY,
        CHOICE_WIDGET,
        FIRST_WIDGET,
        LAST_WIDGET,
    )
    assert all(isinstance(key, str) for key in keys)
    assert len(set(keys)) == 6


def test_p14_tables_without_days_still_show_the_window(base: Tables) -> None:
    """Des tables sans aucune ligne de ``jours`` et une montée : l'étendue vient de la
    montée, le contrôle paraît (56 jours) ; la page dit la table vide, sa seule
    légende est celle des données, et aucun graphique."""
    _write(base, (_late_climb(base),), rows=())
    at = _app(_recovery)
    assert not at.exception
    assert _radio(at).value == "56"
    assert [info.value for info in at.info] == [EMPTY_DAYS]
    assert _captions(at) == [DATA_CAPTION]
    assert not at.get("vega_lite_chart")


@pytest.mark.parametrize("page", [_q1, _q2], ids=["q1", "q2"])
def test_p11_the_q_pages_have_no_window(base: Tables, page: Callable[[], None]) -> None:
    _write(base)
    at = _app(page)
    assert not at.exception
    assert not [radio for radio in at.sidebar.radio if radio.label == "Fenêtre"]


def _defined(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _imported_from(tree: ast.Module, module: str) -> set[str]:
    return {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == module
        for alias in node.names
    }


def test_p12_the_tables_are_read_by_piste_only() -> None:
    import mountain_perf.ui.piste as piste
    import mountain_perf.ui.recuperation as recuperation

    tree = ast.parse((UI / "recuperation.py").read_text(encoding="utf-8"))
    removed = {"cached_tables", "_read", "_cached_read", "PERIOD_RECENT", "PERIOD_ALL"}
    assert not _defined(tree) & removed
    for name in ("recuperation.py", "q1.py", "q2.py"):
        page = ast.parse((UI / name).read_text(encoding="utf-8"))
        assert "cached_tables" in _imported_from(page, "mountain_perf.ui.piste"), name
    assert vars(recuperation)["cached_tables"] is piste.cached_tables
