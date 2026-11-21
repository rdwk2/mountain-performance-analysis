"""Les pages d'OG-UI sur les profils de démo (M5-3, § 6.4 (c) du brief), par
``AppTest.from_function`` sur chaque page : la version réduite de chaque personnage
(``tests/demo_world.py``), ``MPA_DATA_DIR`` posé sur son dossier, l'horloge des pages à
T0 12:00 UTC, les caches de Streamlit vidés avant chaque test."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("fitdecode")
pytest.importorskip("streamlit")
pytest.importorskip("pyarrow")

import streamlit as st
from streamlit.testing.v1 import AppTest

from demo_world import built
from mountain_perf.config import DATA_DIR_ENV_VAR
from mountain_perf.demo.constantes import CHARACTER_NAMES

NOW = datetime(2026, 11, 13, 12, tzinfo=UTC)
RACE = date(2026, 12, 4)
TIMEOUT_S = 30
WARNINGS = {"debutant": 2, "polyvalente": 0, "grimpeur": 0, "rouleur": 1, "moyen": 1}
BOUNDED = (
    "course le 2026-12-04 : au-delà de 7 jours, origine bornée à aujourd'hui (celle "
    "d'une course le 2026-11-20) ; "
)


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mountain_perf.runs.now", lambda: NOW)
    st.cache_resource.clear()


def _on(name: str, factory: pytest.TempPathFactory, patch: pytest.MonkeyPatch) -> Path:
    folder = built(name, factory).folder
    patch.setenv(DATA_DIR_ENV_VAR, str(folder))
    return folder


def _projection() -> None:
    from mountain_perf.ui.projection import projection_page

    projection_page()


def _outing() -> None:
    from mountain_perf.ui.sortie import outing_page

    outing_page()


def _window() -> None:
    from mountain_perf.ui.fenetre import window_page

    window_page()


def _app(page: Callable[[], None]) -> AppTest:
    return AppTest.from_function(page, default_timeout=TIMEOUT_S).run(timeout=TIMEOUT_S)


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_the_projection_page(
    name: str,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = _on(name, tmp_path_factory, monkeypatch)
    at = _app(_projection)
    at.selectbox(key="prepare").set_value(folder / "routes" / "deux_parties.gpx")
    at = at.date_input(key="jour").set_value(RACE).run(timeout=TIMEOUT_S)
    assert not at.exception
    (block,) = at.code
    assert str(block.value).split("\n")[0].startswith(BOUNDED)
    assert len(at.warning) == WARNINGS[name]


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_the_outing_page(
    name: str,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = _on(name, tmp_path_factory, monkeypatch)
    (trace,) = (folder / "sorties").iterdir()
    loop = trace.stem.split("_", 2)[2]
    day = date.fromisoformat(trace.stem.split("_")[1])
    origin = day - timedelta(days=7)
    at = _app(_outing)
    at.selectbox(key="sortie.prepare").set_value(folder / "routes" / f"{loop}.gpx")
    at.selectbox(key="sortie.trace").set_value(trace)
    at = at.button(key="sortie.comparer").click().run(timeout=TIMEOUT_S)
    assert not at.exception
    caption = (
        f"Courbe à l'origine du {origin:%d/%m/%Y} (00:00 à Paris, 7 jours avant la "
        "sortie) : "
    )
    assert any(str(c.value).startswith(caption) for c in at.caption), [
        c.value for c in at.caption
    ]


def test_the_window_page(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _on("polyvalente", tmp_path_factory, monkeypatch)
    at = _app(_window)
    assert not at.exception


def _recovery() -> None:
    from mountain_perf.ui.recuperation import recuperation_page

    recuperation_page()


def _q1() -> None:
    from mountain_perf.ui.q1 import q1_page

    q1_page()


def _q2() -> None:
    from mountain_perf.ui.q2 import q2_page

    q2_page()


Q2_NO_RESULT = (
    "Aucun résultat de Q2 dans resultats/Q2/ : lancer just q2 puissance, puis just q2."
)
"""L'information de la page « Q2 » sans résultat (§ 6.2 du brief AN3-5)."""


@pytest.mark.parametrize("name", CHARACTER_NAMES)
@pytest.mark.parametrize(
    ("page", "infos"),
    [(_recovery, []), (_q1, []), (_q2, [Q2_NO_RESULT])],
    ids=["recuperation", "q1", "q2"],
)
def test_the_piste_pages(
    name: str,
    page: Callable[[], None],
    infos: list[str],
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Les pages récupération, Q1 et Q2 : la table et le journal existent, la figure
    de Q1 aussi ; aucune exception, aucune erreur. Aucune information, sauf sur la
    page Q2 : les profils de démo n'ont pas de résultat de Q2 (AN3-5), elle dit
    comment en faire un."""
    _on(name, tmp_path_factory, monkeypatch)
    at = _app(page)
    assert not at.exception
    assert not at.error
    assert [info.value for info in at.info] == infos
