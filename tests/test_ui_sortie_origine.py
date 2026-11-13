"""La page « sortie » avec la courbe à l'origine ou d'une plage (OG-UI, § 6.5 du
brief), par ``AppTest.from_function`` sur la page seule.

Le monde ``interim/`` des fixtures recalé (``tests/test_og1_cli_at.py``) sous
``data_dir()`` ; ``appariement_reference.gpx`` et ``appariement_trace_x01.gpx`` (une
sortie du 2026-06-01) ; l'horloge des pages, ``mountain_perf.runs.now``, au
2026-06-10 12:00 UTC ; les caches de Streamlit vidés avant chaque test. Sautés sans
l'extra ``tableau``."""

from __future__ import annotations

import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("streamlit")

import streamlit as st
from streamlit.testing.v1 import AppTest

from fixtures.matching import MATCH_REFERENCE_GPX, MATCH_TRACE_GPX
from fixtures.processed import write_interim
from mountain_perf.config import data_dir
from mountain_perf.data_files import FOLDERS, FileKind
from mountain_perf.outing_views import effort_rows
from mountain_perf.reports import (
    origin_curve_lines,
    outing_support_lines,
)
from mountain_perf.runs import (
    OutingMatch,
    check_outing,
    course_origin,
    load_athlete_corpus,
    match_outing,
    origin_curve,
    outing_support_share,
)
from mountain_perf.ui.components import RANGE_SOURCE, WINDOW_LINK
from test_og1_cli_at import realign

NOW = datetime(2026, 6, 10, 12, tzinfo=UTC)
TODAY = date(2026, 6, 10)
FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = FIXTURES / MATCH_REFERENCE_GPX
TRACE = FIXTURES / MATCH_TRACE_GPX
TRAIL = frozenset({"trail_running"})
TIMEOUT_S = 60
CHOOSE = "Choisis un préparé, une trace et une courbe, puis « Comparer »."
OPTIMISTIC = "Sortie dans la période d'estimation de la courbe"
CAPTION_TAIL = (
    " : la sortie n'est pas dans sa fenêtre, l'écart est une prévision hors "
    "échantillon."
)


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mountain_perf.runs.now", lambda: NOW)
    st.cache_resource.clear()


def _page() -> None:
    """La page seule, sans la navigation de ``app.py``."""
    from mountain_perf.ui.sortie import outing_page

    outing_page()


def _app() -> AppTest:
    return AppTest.from_function(_page, default_timeout=TIMEOUT_S).run()


def _copy(source: Path, folder: str, name: str | None = None) -> Path:
    target = data_dir() / folder
    target.mkdir(exist_ok=True)
    path = target / (name or source.name)
    shutil.copy(source, path)
    return path


def _with(trace: Path = TRACE) -> tuple[Path, Path]:
    folder = data_dir()
    write_interim(folder)
    realign(folder)
    return _copy(REFERENCE, FOLDERS[FileKind.ROUTE]), _copy(
        trace, FOLDERS[FileKind.OUTING]
    )


def _late_trace() -> Path:
    """La trace commitée, ses instants ``2026-06-01T08:0…`` changés en
    ``2026-06-20T08:0…`` : datée au-delà d'aujourd'hui + 7 jours."""
    text = TRACE.read_text(encoding="utf-8")
    assert "2026-06-01T08:0" in text
    folder = data_dir() / FOLDERS[FileKind.OUTING]
    folder.mkdir(exist_ok=True)
    path = folder / "trace_tardive.gpx"
    path.write_text(
        text.replace("2026-06-01T08:0", "2026-06-20T08:0"), encoding="utf-8"
    )
    return path


def _compare(at: AppTest) -> AppTest:
    return at.button(key="sortie.comparer").click().run()


def _all_the_past(at: AppTest) -> AppTest:
    return at.radio(key="sortie.fenetre").set_value("tout le passé").run()


def _block(at: AppTest) -> list[str]:
    (block,) = at.code
    return str(block.value).split("\n")


def _texts(elements: Any) -> list[str]:
    return [str(element.value) for element in elements]


def _second_way(route: Path, trace: Path, day: date) -> tuple[Any, OutingMatch]:
    corpus = load_athlete_corpus(data_dir(), TRAIL)
    curve = origin_curve(corpus, course_origin(day, TODAY), "all", generated_at=NOW)
    assert curve.curve is not None
    return curve, match_outing(route, trace, curve.curve, {})


# --- À l'origine ----------------------------------------------------------------------


def test_the_default_is_an_absence() -> None:
    _with()
    at = _compare(_app())
    assert not at.exception
    assert _texts(at.info) == [
        "Aucune courbe à l'origine : aucune activité candidate : aucun "
        "enregistrement des types demandés ne finit dans la fenêtre."
    ]
    assert not at.dataframe


def test_all_the_past_compares_at_the_origin_of_the_outing() -> None:
    from mountain_perf.ui.sortie import _effort_table

    route, trace = _with()
    at = _compare(_all_the_past(_app()))
    assert not at.exception
    captions = _texts(at.caption)
    assert (
        "Courbe à l'origine du 25/05/2026 (00:00 à Paris, 7 jours avant la sortie)"
        + CAPTION_TAIL
    ) in captions
    assert not any(OPTIMISTIC in text for text in _texts(at.warning))
    block = _block(at)
    assert block[0] == (
        "jour 2026-06-01 : origine 2026-05-25 00:00 à Paris ; fenêtre tout le passé"
    )
    curve, match = _second_way(route, trace, date(2026, 6, 1))
    check = check_outing(match)
    share = outing_support_share(match)
    assert block == [
        *origin_curve_lines(curve),
        *outing_support_lines(match, share),
    ]
    warnings = _texts(at.warning)
    assert len(warnings) == 1
    assert warnings[0].startswith("Avertissement : moins de 20 sorties à pied ")
    assert WINDOW_LINK in _texts(at.markdown)
    records = at.dataframe[0].value.to_dict("records")
    assert records == _effort_table(effort_rows(check.scores, check.clocks))


# --- Sur une plage --------------------------------------------------------------------


def _range(at: AppTest, date_from: date, date_to: date) -> AppTest:
    at = at.radio(key="sortie.source").set_value(RANGE_SOURCE).run()
    at.date_input(key="sortie.plage_debut").set_value(date_from)
    return at.date_input(key="sortie.plage_fin").set_value(date_to).run()


def test_a_range_before_the_outing() -> None:
    _with()
    at = _compare(_range(_app(), date(2024, 3, 1), date(2024, 3, 31)))
    assert not at.exception
    assert not any(OPTIMISTIC in text for text in _texts(at.warning))
    block = _block(at)
    assert block[0].startswith("plage du 2024-03-01 au 2024-03-31 : ")
    assert block[-2].startswith("support      ")
    assert block[-1].startswith("             hors support : ")
    assert WINDOW_LINK not in _texts(at.markdown)
    assert at.dataframe


def test_a_range_holding_the_outing_is_optimistic() -> None:
    _with()
    at = _compare(_range(_app(), date(2024, 3, 1), date(2026, 6, 30)))
    assert not at.exception
    assert any(
        text == f"{OPTIMISTIC} (01/03/2024 – 30/06/2026) : l'écart y est optimiste."
        for text in _texts(at.warning)
    )


def test_a_range_without_candidate() -> None:
    _with()
    at = _compare(_range(_app(), date(2026, 5, 1), date(2026, 6, 30)))
    assert not at.exception
    infos = _texts(at.info)
    assert len(infos) == 1
    assert infos[0].startswith("Aucune courbe sur la plage : ")
    assert not at.dataframe


# --- Les erreurs ----------------------------------------------------------------------


def test_an_unreadable_trace_at_the_origin() -> None:
    from mountain_perf.ui.sortie import RESULT_KEY

    _with(FIXTURES / "mini_11.gpx")
    at = _compare(_app())
    assert not at.exception
    assert len(at.error) == 1
    assert "instant manquant" in str(at.error[0].value)
    assert RESULT_KEY not in at.session_state


# --- La trace datée au-delà d'aujourd'hui + 7 jours -----------------------------------


def test_a_trace_beyond_seven_days_has_a_bounded_caption() -> None:
    folder = data_dir()
    write_interim(folder)
    realign(folder)
    _copy(REFERENCE, FOLDERS[FileKind.ROUTE])
    _late_trace()
    at = _compare(_all_the_past(_app()))
    assert not at.exception
    assert (
        "Courbe à l'origine du 10/06/2026 (00:00 à Paris, aujourd'hui : la sortie est "
        "datée au-delà d'aujourd'hui + 7 jours)" + CAPTION_TAIL
    ) in _texts(at.caption)
    assert _block(at)[0].startswith(
        "course le 2026-06-20 : au-delà de 7 jours, origine bornée à aujourd'hui "
        "(celle d'une course le 2026-06-17) ; "
    )


# --- Le résultat gardé ----------------------------------------------------------------


def test_the_result_stays_and_another_source_hides_it() -> None:
    _with()
    at = _compare(_all_the_past(_app()))
    assert at.dataframe
    at.run()
    assert not at.exception
    assert at.dataframe
    at = at.radio(key="sortie.source").set_value(RANGE_SOURCE).run()
    assert _texts(at.info) == [CHOOSE]
    assert not at.dataframe


def test_another_window_hides_the_result() -> None:
    _with()
    at = _compare(_all_the_past(_app()))
    assert at.dataframe
    at = at.radio(key="sortie.fenetre").set_value("56 jours").run()
    assert not at.exception
    assert _texts(at.info) == [CHOOSE]
    assert not at.dataframe
    at = at.radio(key="sortie.fenetre").set_value("tout le passé").run()
    assert at.dataframe


def test_without_click_nothing_is_computed_at_the_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []

    def spy(*args: Any) -> Any:
        calls.append(args)
        return match_outing(*args)

    def corpus_spy(*args: Any) -> Any:
        calls.append(args)
        return load_athlete_corpus(*args)

    monkeypatch.setattr("mountain_perf.ui.sortie.match_outing", spy)
    monkeypatch.setattr("mountain_perf.ui.components.load_athlete_corpus", corpus_spy)
    _with()
    at = _all_the_past(_app())
    assert not at.exception
    assert _texts(at.info) == [CHOOSE]
    assert not at.dataframe
    assert calls == []
