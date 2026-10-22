"""Garanties de la page « sortie » sans test à la tête de la PR #35 (relecture de la
PR : la C et la conception) : les lieux nommés, les écarts indisponibles, l'origine des
écarts et les horloges distinctes, sur des cas construits par objets
(``tests/fixtures/scoring.py``) ; une partie comparée sans point d'écart ; le jour à
Paris et la fenêtre dans la page ; un autre préparé ou une autre courbe choisis ; les
légendes au texte du brief ; les deux figures en entier ; la ligne de ``PAGES``.

``AppTest.from_function`` sur une fonction de ce fichier qui appelle ``outing_page``
(piège 12 du brief M5-2). Sautés sans l'extra ``tableau``.
"""

import ast
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

import mountain_perf
from fixtures.matching import MATCH_REFERENCE_GPX, MATCH_TRACE_GPX
from fixtures.scoring import Chain, chain, curve_read, run_chain, run_scores, scores
from fixtures.segments import stop_off_support
from mountain_perf.backtest.calendar import civil_date
from mountain_perf.backtest.scoring import report_clocks
from mountain_perf.config import data_dir
from mountain_perf.data_files import CURVES_FOLDER, FOLDERS, FileKind
from mountain_perf.gpx import read_gpx
from mountain_perf.outing_views import GapRow, Gaps, admitted_spans
from mountain_perf.runs import OutingCheck, OutingMatch, match_outing
from mountain_perf.schemas import OutingScores
from mountain_perf.series import build_series

APP = Path(mountain_perf.__file__).parent / "ui" / "app.py"
FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = FIXTURES / MATCH_REFERENCE_GPX
TRACE = FIXTURES / MATCH_TRACE_GPX
CURVE = FIXTURES / "courbe_synthetique.csv"
COMPANION = FIXTURES / "courbe_synthetique.meta.json"
TIMEOUT_S = 60
CHOOSE = "Choisis un préparé, une trace et une courbe, puis « Comparer »."
CLOCK_LEGEND_OF_THE_BRIEF = (
    "Horloges : écoulé, tout le temps ; M θn, le temps en mouvement ; (M+U) θn, en "
    "mouvement ou incertain ; θn, la convention d'arrêt retenue (0010 D5)."
)
EFFORT_LIMITS_OF_THE_BRIEF = (
    "L'effort effectif est l'effort auquel v0 aurait prévu ton temps sur la partie "
    "comparée. Il est rétrospectif, limité à cette partie, faussé par les arrêts sous "
    "l'écoulé, et il mêle ton effort du jour et l'erreur de la courbe ; sur ton "
    "préparé, s'y ajoute l'écart entre le préparé et le chemin suivi (raccourcis, "
    "détours, GPS), que mesure l'écart entre les deux colonnes (0010 D3). Ce n'est pas "
    "une erreur du modèle, dont le chiffre qui fait foi reste celui du backtest."
)
DETAIL = "Le détail (régimes, enveloppes, épisodes) : mperf match --curve."
DISTANCE_AXIS_OF_THE_BRIEF = {
    "field": "distance (m)",
    "type": "quantitative",
    "axis": {"format": "d"},
}


def _page() -> None:
    from mountain_perf.ui.sortie import outing_page

    outing_page()


def _copy(source: Path, folder: str, name: str | None = None) -> Path:
    target = data_dir() / folder
    target.mkdir(exist_ok=True)
    path = target / (name or source.name)
    shutil.copy(source, path)
    return path


def _route(name: str | None = None) -> Path:
    return _copy(REFERENCE, FOLDERS[FileKind.ROUTE], name)


def _trace() -> Path:
    return _copy(TRACE, FOLDERS[FileKind.OUTING])


def _curve(stem: str = "courbe_synthetique") -> Path:
    _copy(COMPANION, CURVES_FOLDER, f"{stem}.meta.json")
    return _copy(CURVE, CURVES_FOLDER, f"{stem}.csv")


def _compare() -> AppTest:
    at = AppTest.from_function(_page, default_timeout=TIMEOUT_S).run()
    return at.button(key="sortie.comparer").click().run()


def _cells(at: AppTest, index: int) -> list[dict[str, str]]:
    records: list[dict[str, str]] = at.dataframe[index].value.to_dict("records")
    return records


def _charts(at: AppTest) -> list[dict[str, Any]]:
    return [json.loads(element.proto.spec) for element in at.get("vega_lite_chart")]


def _texts(at: AppTest) -> list[str]:
    return [str(element.value) for element in at.markdown]


def _captions(at: AppTest) -> list[str]:
    return [str(element.value) for element in at.caption]


def _by_objects(monkeypatch: pytest.MonkeyPatch, c: Chain, s: OutingScores) -> None:
    """``match_outing`` et ``check_outing`` de la page remplacés par la chaîne d'un cas
    construit par objets ; les fichiers de la barre latérale ne servent qu'au choix, et
    ``read`` (que la page ne lit pas) est celui du préparé commité."""
    trace = c.case.trace
    match = OutingMatch(
        c.case.parameters,
        curve_read(),
        read_gpx(REFERENCE),
        c.profile,
        c.case.geometry,
        trace,
        build_series(trace),
        c.partition,
        c.match,
        c.passages,
    )
    check = OutingCheck(s, report_clocks(c.match), civil_date(trace.start_time), False)
    monkeypatch.setattr("mountain_perf.ui.sortie.match_outing", lambda *_: match)
    monkeypatch.setattr("mountain_perf.ui.sortie.check_outing", lambda *_: check)
    _route(), _trace(), _curve()


def test_the_page_names_the_places_under_each_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """« Passages » : les lieux B et A ; écoulé, ``M θ3`` et ``(M+U) θ1`` distincts."""
    _by_objects(monkeypatch, chain("Passages"), scores("Passages"))
    at = _compare()
    assert not at.exception
    table = _cells(at, 1)
    assert [row["point"] for row in table] == [
        "point 1",
        "B",
        "A",
        "point 2",
        "point 3",
    ]
    assert {key: table[2][key] for key in ("écoulé", "M θ3", "(M+U) θ1")} == {
        "écoulé": "−6:03",
        "M θ3": "−4:08",
        "(M+U) θ1": "−4:31",
    }
    assert (
        "Plus grand écart, en valeur absolue : écoulé 0:10:20, M θ3 0:08:23, "
        "(M+U) θ1 0:08:48."
    ) in _texts(at)


def test_the_page_shows_unavailable_gaps_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """« Chronologie » : W1 et W2 ambigus, « — » dans le tableau, sautés par la
    figure."""
    _by_objects(monkeypatch, chain("Chronologie"), scores("Chronologie"))
    at = _compare()
    assert not at.exception
    table = _cells(at, 1)
    assert [row["point"] for row in table][1:3] == ["W1", "W2"]
    for row in table[1:3]:
        assert [row[key] for key in ("écoulé", "M θ3", "(M+U) θ1")] == ["—"] * 3
    _, cumulated = _charts(at)
    (layer,) = cumulated["layer"]
    assert len(layer["data"]["values"]) == 1 + 7 - 2


def test_the_page_draws_the_gaps_from_the_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """« Régimes » : ``b_0`` vaut 20 m ; la distance d'un point au-delà de 1 000 m est
    écrite par ``format_count``."""
    s = scores("Régimes")
    _by_objects(monkeypatch, chain("Régimes"), s)
    at = _compare()
    assert not at.exception
    _, cumulated = _charts(at)
    first = cumulated["layer"][0]["data"]["values"][0]
    assert first == {"distance (m)": s.observation.origin_m, "écart cumulé (min)": 0.0}
    assert first["distance (m)"] == pytest.approx(20.0, abs=1e-6)
    last_m = s.observation.error_points[-1].distance_m
    assert last_m >= 1000
    distances = [row["distance (m)"] for row in _cells(at, 1)]
    assert distances[-1] == f"{last_m:,.0f}".replace(",", " ")


def test_the_page_writes_a_dash_for_unavailable_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un écart et un plus grand écart indisponibles sous chaque horloge."""

    def unavailable(
        scores: object, passages: object, clocks: tuple[object, ...]
    ) -> Gaps:
        none = (None,) * len(clocks)
        return Gaps(0.0, (GapRow("point 1", 250.0, none),), none)

    monkeypatch.setattr("mountain_perf.ui.sortie.gaps", unavailable)
    _route(), _trace(), _curve()
    at = _compare()
    assert not at.exception
    assert _cells(at, 1) == [
        {
            "point": "point 1",
            "distance (m)": "250",
            "écoulé": "—",
            "M θ1": "—",
            "(M+U) θ1": "—",
        }
    ]
    assert (
        "Plus grand écart, en valeur absolue : écoulé —, M θ1 —, (M+U) θ1 —."
    ) in _texts(at)
    _, cumulated = _charts(at)
    assert cumulated["layer"][0]["data"]["values"] == [
        {"distance (m)": 0.0, "écart cumulé (min)": 0.0}
    ]


def test_a_compared_part_without_gap_points_has_no_gap_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``stop_off_support`` : 510 m admis, un préfixe comparable de 0 m, aucun
    ``C_k``."""
    c = run_chain(stop_off_support())
    _by_objects(monkeypatch, c, run_scores(c))
    at = _compare()
    assert not at.exception
    assert len(at.dataframe) == 1
    assert len(at.get("vega_lite_chart")) == 1
    assert (
        "Préfixe comparable jusqu'à 0 m : les écarts aux points s'arrêtent là."
    ) in _texts(at)
    assert not [text for text in _texts(at) if text.startswith("Plus grand écart")]


def _shifted_trace(first: datetime) -> Path:
    """La trace commitée dans ``sorties/``, ses 33 instants décalés pour que le premier
    soit ``first``."""
    text = TRACE.read_text(encoding="utf-8")
    assert text.count("2026-06-01T08:") == 33
    delta = first - datetime(2026, 6, 1, 8, 0, tzinfo=UTC)

    def shift(found: re.Match[str]) -> str:
        instant = datetime.fromisoformat(found.group(1)) + delta
        return f"<time>{instant.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}</time>"

    folder = data_dir() / FOLDERS[FileKind.OUTING]
    folder.mkdir(exist_ok=True)
    path = folder / "trace_decalee.gpx"
    path.write_text(re.sub(r"<time>([^<]+)</time>", shift, text), encoding="utf-8")
    return path


def test_the_page_writes_the_day_in_paris() -> None:
    """Premier instant le 31 janvier à 23 h UTC : le 1er février à Paris, hors de la
    fenêtre de janvier."""
    _route(), _curve()
    _shifted_trace(datetime(2026, 1, 31, 23, 0, tzinfo=UTC))
    at = _compare()
    assert not at.exception
    assert (
        "Contrôle de la sortie du 01/02/2026 (jour à Paris du premier instant de la "
        "trace) par v0 brut, à l'effort 1."
    ) in _captions(at)
    assert not at.warning


def test_the_page_over_midnight_in_paris() -> None:
    """Premier instant le 31 janvier à 23 h 58 à Paris, dernier le 1er février : le jour
    et l'avertissement sont ceux du premier instant."""
    _route(), _curve()
    _shifted_trace(datetime(2026, 1, 31, 22, 58, tzinfo=UTC))
    at = _compare()
    assert not at.exception
    assert (
        "Contrôle de la sortie du 31/01/2026 (jour à Paris du premier instant de la "
        "trace) par v0 brut, à l'effort 1."
    ) in _captions(at)
    assert [str(warning.value) for warning in at.warning] == [
        "Sortie dans la période d'estimation de la courbe (01/01/2026 – 31/01/2026) : "
        "l'écart y est optimiste."
    ]


def test_another_route_or_another_curve_hides_the_result() -> None:
    first_route = _route()
    _trace()
    first_curve = _curve()
    second_route = _route("z_second.gpx")
    second_curve = _curve("z_courbe")
    at = _compare()
    assert len(at.dataframe) == 2
    at.selectbox(key="sortie.prepare").set_value(second_route).run()
    assert not at.exception
    assert [str(info.value) for info in at.info] == [CHOOSE]
    assert not at.dataframe
    at.selectbox(key="sortie.prepare").set_value(first_route).run()
    assert len(at.dataframe) == 2
    at.selectbox(key="sortie.courbe").set_value(second_curve).run()
    assert [str(info.value) for info in at.info] == [CHOOSE]
    assert not at.dataframe
    at.selectbox(key="sortie.courbe").set_value(first_curve).run()
    assert len(at.dataframe) == 2


def test_the_page_writes_the_legends_of_the_brief() -> None:
    """Les légendes comparées au texte du brief, pas aux constantes qu'elles
    vérifient."""
    _route(), _trace(), _curve()
    at = _compare()
    captions = _captions(at)
    assert CLOCK_LEGEND_OF_THE_BRIEF in captions
    assert EFFORT_LIMITS_OF_THE_BRIEF in captions
    assert DETAIL in captions


def test_the_two_charts_in_full() -> None:
    """Les bandes de la partie comparée (``x`` et ``x2``), le profil du préparé, et
    l'abscisse des deux figures, au format du brief."""
    route, trace, curve = _route(), _trace(), _curve()
    at = _compare()
    assert not at.exception
    followed, cumulated = _charts(at)
    spans, profile = followed["layer"]
    match = match_outing(route, trace, curve, {})
    assert spans["data"]["values"] == [
        {"début (m)": a, "fin (m)": b} for a, b in admitted_spans(match.result)
    ]
    assert spans["encoding"] == {
        "x": {
            **DISTANCE_AXIS_OF_THE_BRIEF,
            "field": "début (m)",
            "title": "distance (m)",
        },
        "x2": {"field": "fin (m)"},
    }
    assert profile["mark"] == "line"
    assert profile["data"]["values"] == [
        {"distance (m)": d, "altitude (m)": z}
        for d, z in zip(
            match.profile.distance_m, match.profile.elevation_m, strict=True
        )
    ]
    assert profile["encoding"] == {
        "x": DISTANCE_AXIS_OF_THE_BRIEF,
        "y": {
            "field": "altitude (m)",
            "type": "quantitative",
            "scale": {"zero": False},
            "axis": {"format": "d"},
        },
    }
    (layer,) = cumulated["layer"]
    assert layer["encoding"]["x"] == DISTANCE_AXIS_OF_THE_BRIEF


def test_the_page_line_of_pages() -> None:
    """La ligne de ``PAGES`` du § 6.5 : ``st.Page(outing_page, title="Sortie",
    url_path="sortie")``, après la projection."""
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    pages = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Page"
    ]
    described = [
        (
            ast.unparse(page.args[0]),
            {keyword.arg: ast.literal_eval(keyword.value) for keyword in page.keywords},
        )
        for page in pages
    ]
    assert described == [
        ("projection_page", {"title": "Projection", "url_path": "projection"}),
        ("outing_page", {"title": "Sortie", "url_path": "sortie"}),
    ]
