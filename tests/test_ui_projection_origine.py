"""La page « projection » avec la courbe à l'origine ou d'une plage (OG-UI, § 6.4 du
brief), par ``AppTest.from_function`` sur la page seule.

Le monde ``interim/`` des fixtures recalé (``tests/test_og1_cli_at.py``) sous
``data_dir()`` ; l'horloge des pages, ``mountain_perf.runs.now``, au 2024-04-01
12:00 UTC ; les caches de Streamlit vidés avant chaque test. La seconde voie appelle à
part les fonctions de ``runs.py`` et de ``reports.py``."""

from __future__ import annotations

import dataclasses
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("streamlit")

import streamlit as st
from streamlit.testing.v1 import AppTest

from fixtures.matching import MATCH_REFERENCE_GPX
from fixtures.processed import write_interim
from mountain_perf.config import data_dir
from mountain_perf.estimation.intervals import activity_intervals
from mountain_perf.estimation.origin import OriginWindow
from mountain_perf.ingest.interim import read_index, read_recording, write_activities
from mountain_perf.model.views import passage_rows
from mountain_perf.reports import origin_curve_lines, projection_summary_lines
from mountain_perf.runs import (
    OriginCurve,
    RouteProjection,
    course_origin,
    load_athlete_corpus,
    origin_curve,
    project_route,
)
from mountain_perf.ui.components import (
    FILE_SOURCE,
    RANGE_SOURCE,
    WINDOW_LINK,
    FileSource,
    OriginSource,
    RangeSource,
)
from test_ingest_interim import INDEX_SOURCE, REPORT
from test_og1_cli_at import realign
from test_ogui_cli import write_not_projectable
from test_schemas_interim import entry

NOW = datetime(2024, 4, 1, 12, tzinfo=UTC)
TODAY = date(2024, 4, 1)
FIXTURES = Path(__file__).parent / "fixtures"
ROUTE = FIXTURES / "mini_11.gpx"
FOLLOWED = FIXTURES / MATCH_REFERENCE_GPX
CURVE = FIXTURES / "courbe_synthetique.csv"
COMPANION = FIXTURES / "courbe_synthetique.meta.json"
TRAIL = frozenset({"trail_running"})
TIMEOUT_S = 60
FIRST_LINE = (
    "jour 2024-04-01 : origine 2024-03-25 00:00 à Paris ; fenêtre 56 jours, fins "
    "depuis le 2024-01-29 00:00 à Paris"
)


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mountain_perf.runs.now", lambda: NOW)
    st.cache_resource.clear()


def _page() -> None:
    """La page seule, sans la navigation de ``app.py``."""
    from mountain_perf.ui.projection import projection_page

    projection_page()


def _app() -> AppTest:
    return AppTest.from_function(_page, default_timeout=TIMEOUT_S).run()


def _with(route: Path = ROUTE) -> Path:
    folder = data_dir()
    write_interim(folder)
    realign(folder)
    routes = folder / "routes"
    routes.mkdir(exist_ok=True)
    shutil.copy(route, routes / route.name)
    return routes / route.name


def _block(at: AppTest) -> list[str]:
    (block,) = at.code
    return str(block.value).split("\n")


def _warnings(at: AppTest) -> list[str]:
    return [str(element.value) for element in at.warning]


def _markdown(at: AppTest) -> list[str]:
    return [str(element.value) for element in at.markdown]


def _infos(at: AppTest) -> list[str]:
    return [str(element.value) for element in at.info]


def _second_way(
    route: Path, day: date = TODAY, window: OriginWindow = 56
) -> tuple[OriginCurve, RouteProjection]:
    corpus = load_athlete_corpus(data_dir(), TRAIL)
    curve = origin_curve(corpus, course_origin(day, TODAY), window, generated_at=NOW)
    assert curve.curve is not None
    return curve, project_route(route, curve.curve, {}, {})


def _set_day(at: AppTest, day: date) -> AppTest:
    return at.date_input(key="jour").set_value(day).run()


# --- Par défaut : à l'origine, aujourd'hui, 56 jours ----------------------------------


def test_the_default_shows_two_warnings() -> None:
    from mountain_perf.ui.projection import _table

    route = _with()
    at = _app()
    assert not at.exception
    block = _block(at)
    assert block[0] == FIRST_LINE
    curve, run = _second_way(route)
    assert block == [*origin_curve_lines(curve), *projection_summary_lines(run)]
    warnings = _warnings(at)
    assert len(warnings) == 2
    assert warnings[0].startswith(
        "Avertissement : moins de 20 sorties à pied passées (2) : "
    )
    assert warnings[1].startswith(
        "Avertissement : 100 % du temps prévu hors du support "
    )
    assert WINDOW_LINK in _markdown(at)
    (table,) = at.dataframe
    assert table.value.to_dict("records") == _table(passage_rows(run.projection, None))


def test_a_followed_route_has_only_the_cold_start_warning() -> None:
    _with(FOLLOWED)
    at = _app()
    assert not at.exception
    warnings = _warnings(at)
    assert len(warnings) == 1
    assert warnings[0].startswith("Avertissement : moins de 20 sorties à pied ")


def test_seven_days_is_an_absence() -> None:
    _with()
    at = _set_day(_app(), date(2024, 3, 25))
    at = at.radio(key="fenetre").set_value("autre").run()
    at = at.number_input(key="fenetre_jours").set_value(7).run()
    assert not at.exception
    infos = _infos(at)
    assert len(infos) == 1
    assert infos[0].startswith("Aucune courbe à l'origine : ")
    assert not at.dataframe
    assert _block(at)[0] == (
        "jour 2024-03-25 : origine 2024-03-18 00:00 à Paris ; fenêtre 7 jours, fins "
        "depuis le 2024-03-11 00:00 à Paris"
    )
    assert WINDOW_LINK in _markdown(at)


def test_a_far_day_is_bounded() -> None:
    _with()
    at = _set_day(_app(), date(2024, 4, 20))
    assert not at.exception
    block = _block(at)
    assert block[0] == (
        "course le 2024-04-20 : au-delà de 7 jours, origine bornée à aujourd'hui "
        "(celle d'une course le 2024-04-08) ; ce n'est pas la courbe que le backtest "
        "prendrait pour cette course"
    )
    assert block[1].startswith("jour 2024-04-08 : origine 2024-04-01 00:00 à Paris")


def test_a_near_day_is_not_bounded() -> None:
    _with()
    at = _set_day(_app(), date(2024, 4, 8))
    assert not at.exception
    assert _block(at)[0].startswith("jour 2024-04-08 : origine 2024-04-01 00:00")


@pytest.mark.parametrize(
    ("choice", "text"),
    [
        ("tout le passé", "fenêtre tout le passé"),
        ("28 jours", "fenêtre 28 jours, fins depuis le 2024-02-26 00:00 à Paris"),
        ("56 jours", "fenêtre 56 jours, fins depuis le 2024-01-29 00:00 à Paris"),
    ],
)
def test_the_windows(choice: str, text: str) -> None:
    _with()
    at = _app().radio(key="fenetre").set_value(choice).run()
    assert not at.exception
    assert _block(at)[0] == (
        f"jour 2024-04-01 : origine 2024-03-25 00:00 à Paris ; {text}"
    )


# --- Sur une plage --------------------------------------------------------------------


def _range(at: AppTest, date_from: date, date_to: date) -> AppTest:
    at = at.radio(key="source").set_value(RANGE_SOURCE).run()
    at.date_input(key="plage_debut").set_value(date_from)
    return at.date_input(key="plage_fin").set_value(date_to).run()


def test_a_range() -> None:
    _with()
    at = _range(_app(), date(2024, 3, 1), date(2024, 3, 31))
    assert not at.exception
    assert _block(at)[0] == (
        "plage du 2024-03-01 au 2024-03-31 : les départs de ces jours (jour local), "
        "sans contrainte de disponibilité ; une description, pas une prévision"
    )
    warnings = _warnings(at)
    assert len(warnings) == 1
    assert warnings[0].startswith(
        "Avertissement : 100 % du temps prévu hors du support "
    )
    assert WINDOW_LINK not in _markdown(at)


def test_a_range_without_candidate() -> None:
    _with()
    at = _range(_app(), date(2024, 1, 1), date(2024, 1, 31))
    assert not at.exception
    assert _infos(at) == [
        "Aucune courbe sur la plage : aucune activité candidate : aucun "
        "enregistrement des types demandés dans la fenêtre."
    ]
    assert not at.dataframe


def test_a_reversed_range() -> None:
    _with()
    at = _range(_app(), date(2024, 3, 31), date(2024, 3, 1))
    assert not at.exception
    assert len(at.error) == 1
    assert "date_from" in str(at.error[0].value)


def test_the_default_range() -> None:
    _with()
    at = _app().radio(key="source").set_value(RANGE_SOURCE).run()
    assert not at.exception
    assert at.date_input(key="plage_debut").value == date(2024, 2, 5)
    assert at.date_input(key="plage_fin").value == date(2024, 3, 31)


# --- La courbe non projetable ---------------------------------------------------------


def _not_projectable() -> None:
    write_not_projectable()
    routes = data_dir() / "routes"
    routes.mkdir(exist_ok=True)
    shutil.copy(ROUTE, routes / ROUTE.name)


def test_a_not_projectable_curve_is_an_error() -> None:
    _not_projectable()
    at = _app()
    assert not at.exception
    assert len(at.error) == 1
    assert str(at.error[0].value).startswith("La tranche centrale de pente ")


def test_a_not_projectable_curve_read_at_four_minutes() -> None:
    _not_projectable()
    at = _app().slider(key="projection.curve_min_support_min").set_value(4.0).run()
    assert not at.exception
    marks = [line for line in _block(at) if line.startswith("Courbe non projetable")]
    assert len(marks) == 1
    assert marks[0].startswith(
        "Courbe non projetable par read_curve : La tranche centrale de pente "
    )
    assert at.dataframe


# --- Les erreurs ----------------------------------------------------------------------


def test_without_interim_at_the_origin() -> None:
    routes = data_dir() / "routes"
    routes.mkdir()
    shutil.copy(ROUTE, routes / ROUTE.name)
    at = _app()
    assert not at.exception
    assert len(at.error) == 1
    assert not at.code


def test_an_os_error_is_shown_without_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refused(*_: Any) -> RouteProjection:
        raise PermissionError("refusé")

    monkeypatch.setattr("mountain_perf.ui.projection.project_route", refused)
    _with()
    reference = data_dir() / "reference"
    reference.mkdir()
    shutil.copy(CURVE, reference / CURVE.name)
    shutil.copy(COMPANION, reference / COMPANION.name)
    at = AppTest.from_function(_page, default_timeout=TIMEOUT_S)
    at.session_state["source"] = FILE_SOURCE
    at.run()
    assert not at.exception
    assert [str(element.value) for element in at.error] == ["refusé"]


# --- Les caches -----------------------------------------------------------------------


def _add_an_entry() -> None:
    """L'index réécrit avec une entrée de plus, sans enregistrement : une autre
    empreinte."""
    folder = data_dir()
    index = read_index(folder)
    recordings = [
        read_recording(folder, item.activity_ref)
        for item in index.entries
        if item.has_recording
    ]
    extra = entry(
        source=INDEX_SOURCE,
        activity_ref="a5",
        source_activity_type="golf",
        has_recording=False,
        start_time=datetime(2024, 3, 13, 9, tzinfo=UTC),
    )
    write_activities(
        folder,
        dataclasses.replace(index, entries=(*index.entries, extra)),
        recordings,
        REPORT,
    )


def test_the_corpus_is_kept_until_the_index_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Path] = []

    def spy(folder: Path, types: frozenset[str]) -> Any:
        calls.append(folder)
        return load_athlete_corpus(folder, types)

    monkeypatch.setattr("mountain_perf.ui.components.load_athlete_corpus", spy)
    _with()
    at = _app()
    at = _set_day(at, date(2024, 3, 25))
    assert not at.exception
    assert len(calls) == 1
    _add_an_entry()
    at = _set_day(at, date(2024, 4, 1))
    assert not at.exception
    assert len(calls) == 2


def test_the_intervals_cache_serves_two_days(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def spy(recording: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(recording.activity_ref)
        return activity_intervals(recording, *args, **kwargs)

    monkeypatch.setattr("mountain_perf.estimation.origin.activity_intervals", spy)
    _with()
    at = _app()
    at = _set_day(at, date(2024, 3, 25))
    assert not at.exception
    assert sorted(calls) == ["a1", "a3"]


# --- Chaque champ des trois sources ---------------------------------------------------


def test_the_sources_read_every_field() -> None:
    origin = OriginSource(date(2024, 4, 1), 56)
    assert (origin.day, origin.window) == (date(2024, 4, 1), 56)
    ranged = RangeSource(date(2024, 3, 1), date(2024, 3, 31))
    assert (ranged.date_from, ranged.date_to) == (date(2024, 3, 1), date(2024, 3, 31))
    assert FileSource(None).path is None
    assert FileSource(CURVE).path == CURVE
