"""La page « sortie », par ``AppTest``, sans navigateur ni serveur (§ 6.5 et § 8.2 du
brief M5-2).

``AppTest.from_function`` sur une fonction de ce fichier qui appelle ``outing_page``
(piège 12) ; les figures se lisent par ``at.get("vega_lite_chart")``, leur
spécification par ``json.loads(element.proto.spec)``. Les données sont les fixtures,
copiées dans ``data_dir()`` (le dossier neuf de ``tests/conftest.py``). Sautés sans
l'extra ``tableau``.
"""

import json
import math
import shutil
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from fixtures.matching import MATCH_REFERENCE_GPX, MATCH_TRACE_GPX
from mountain_perf.config import DATA_DIR_ENV_VAR, data_dir
from mountain_perf.data_files import CURVES_FOLDER, FOLDERS, FileKind
from mountain_perf.gpx import GpxError, ProfileError
from mountain_perf.gpx.trace_reader import TraceError
from mountain_perf.model import CurveError
from mountain_perf.outing_views import (
    EffortRow,
    ScenarioEffort,
    clock_label,
    effort_rows,
    gaps,
)
from mountain_perf.runs import OutingMatch, check_outing, match_outing
from mountain_perf.schemas import Clock, ClockKind, OutingScores, Unavailability
from mountain_perf.units import format_duration, format_signed_duration
from mountain_perf.validation import ContractError

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = FIXTURES / MATCH_REFERENCE_GPX
TRACE = FIXTURES / MATCH_TRACE_GPX
UNFOLLOWED_ROUTE = FIXTURES / "mini_11.gpx"
"""Un préparé que la trace commitée ne suit pas (piège 5) ; sans heures, il sert aussi
de trace illisible."""
CURVE = FIXTURES / "courbe_synthetique.csv"
COMPANION = FIXTURES / "courbe_synthetique.meta.json"
TIMEOUT_S = 60

CHOOSE = "Choisis un préparé, une trace et une courbe, puis « Comparer »."
CAPTION = (
    "Contrôle de la sortie du 01/06/2026 (jour à Paris du premier instant de la "
    "trace) par v0 brut, à l'effort 1."
)
EFFORT_COLUMNS = [
    "horloge",
    "temps réel",
    "prévu sur ton préparé",
    "effort sur ton préparé",
    "prévu sur le chemin suivi",
    "effort sur le chemin suivi",
]


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


def _with_route(source: Path = REFERENCE) -> Path:
    return _copy(source, FOLDERS[FileKind.ROUTE])


def _with_trace(source: Path = TRACE, name: str | None = None) -> Path:
    return _copy(source, FOLDERS[FileKind.OUTING], name)


def _with_curve(window: tuple[date, date] | None = None) -> Path:
    """La courbe commitée ; avec ``window``, son compagnon réécrit avec cette fenêtre
    d'estimation."""
    curve = _copy(CURVE, CURVES_FOLDER)
    companion = _copy(COMPANION, CURVES_FOLDER)
    if window is not None:
        meta = json.loads(companion.read_text(encoding="utf-8"))
        meta["date_from"], meta["date_to"] = (day.isoformat() for day in window)
        companion.write_bytes(json.dumps(meta, ensure_ascii=False).encode("utf-8"))
    return curve


def _all_files() -> tuple[Path, Path, Path]:
    return _with_route(), _with_trace(), _with_curve()


def _compare(at: AppTest) -> AppTest:
    return at.button(key="sortie.comparer").click().run()


def _texts(at: AppTest) -> list[str]:
    return [str(element.value) for element in at.markdown]


def _charts(at: AppTest) -> list[dict[str, Any]]:
    return [json.loads(element.proto.spec) for element in at.get("vega_lite_chart")]


def _cells(at: AppTest, index: int) -> list[dict[str, str]]:
    records: list[dict[str, str]] = at.dataframe[index].value.to_dict("records")
    return records


def _reference_check(
    route: Path, trace: Path, curve: Path
) -> tuple[OutingMatch, OutingScores, tuple[Clock, ...]]:
    match = match_outing(route, trace, curve, {})
    check = check_outing(match)
    return match, check.scores, check.clocks


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


def test_a_route_without_trace_asks_for_a_trace() -> None:
    _with_route()
    _with_curve()
    at = _app()
    assert not at.exception
    assert [str(info.value) for info in at.info] == [
        "Aucune trace dans sorties/ : ajoute un GPX horodaté (barre latérale)."
    ]


def test_a_route_and_a_trace_without_curve_ask_for_a_curve() -> None:
    _with_route()
    _with_trace()
    at = _app()
    assert not at.exception
    assert [str(info.value) for info in at.info] == [
        "Aucune courbe (CSV et son .meta.json) dans reference/."
    ]


# ---------------------------------------------------------------------------
# Le calcul au clic
# ---------------------------------------------------------------------------


def _spy(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[Path, Path, Path | None, dict[str, float]]]:
    """Un espion à la place de ``match_outing`` dans le module de la page, qui appelle
    la vraie."""
    calls: list[tuple[Path, Path, Path | None, dict[str, float]]] = []

    def spy(
        route_path: Path,
        trace_path: Path,
        curve_path: Path | None,
        matching_values: Mapping[str, float],
    ) -> OutingMatch:
        calls.append((route_path, trace_path, curve_path, dict(matching_values)))
        return match_outing(route_path, trace_path, curve_path, matching_values)

    monkeypatch.setattr("mountain_perf.ui.sortie.match_outing", spy)
    return calls


def test_without_click_nothing_is_computed(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _spy(monkeypatch)
    _all_files()
    at = _app()
    assert not at.exception
    assert [str(info.value) for info in at.info] == [CHOOSE]
    assert not at.dataframe
    assert calls == []


def test_the_page_shows_the_comparison_on_click(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _spy(monkeypatch)
    route, trace, curve = _all_files()
    at = _compare(_app())
    assert not at.exception
    assert not at.error
    assert calls == [(route, trace, curve, {})]
    assert not at.warning
    assert CAPTION in [str(caption.value) for caption in at.caption]

    texts = _texts(at)
    expected = [
        "Partie comparée : 91 % du préparé (480 m sur 530 m).",
        "Points de score : trouvé 2, ancré 2, ambigu 0, absent 0, hors ε 0, tangente "
        "indéfinie 0.",
        "Préfixe comparable jusqu'à 505 m : les écarts aux points s'arrêtent là.",
        "Plus grand écart, en valeur absolue : écoulé 0:02:40, M θ1 0:01:42, (M+U) θ1 "
        "0:02:40.",
    ]
    assert [text for text in texts if text in expected] == expected

    match, scores, clocks = _reference_check(route, trace, curve)
    assert len(at.dataframe) == 2
    efforts = _cells(at, 0)
    assert list(efforts[0]) == EFFORT_COLUMNS
    rows = effort_rows(scores, clocks)
    assert len(efforts) == len(rows) == 3
    for cells, row in zip(efforts, rows, strict=True):
        assert row.usage is not None
        assert row.usage.projected_s is not None
        assert row.usage.effective_effort is not None
        assert row.control.projected_s is not None
        assert row.control.effective_effort is not None
        assert cells == {
            "horloge": clock_label(row.clock),
            "temps réel": format_duration(row.observed_s),
            "prévu sur ton préparé": format_duration(row.usage.projected_s),
            "effort sur ton préparé": f"{row.usage.effective_effort:.2f}",
            "prévu sur le chemin suivi": format_duration(row.control.projected_s),
            "effort sur le chemin suivi": f"{row.control.effective_effort:.2f}",
        }

    found = gaps(scores, match.passages, clocks)
    assert found is not None
    errors = _cells(at, 1)
    assert list(errors[0]) == [
        "point",
        "distance (m)",
        *(clock_label(clock) for clock in clocks),
    ]
    assert len(errors) == len(found.rows) == 3
    for cells, gap in zip(errors, found.rows, strict=True):
        assert cells["point"] == gap.name
        for clock, error_s in zip(clocks, gap.errors_s, strict=True):
            assert error_s is not None
            assert cells[clock_label(clock)] == format_signed_duration(error_s)
    assert [cells["distance (m)"] for cells in errors] == ["250", "500", "505"]

    followed, cumulated = _charts(at)
    spans, profile = followed["layer"]
    assert spans["mark"] == {"type": "rect", "opacity": 0.2}
    assert spans["encoding"]["x"]["title"] == "distance (m)"
    assert len(spans["data"]["values"]) == 3
    assert profile["encoding"]["y"]["field"] == "altitude (m)"
    (layer,) = cumulated["layer"]
    values = layer["data"]["values"]
    assert len(values) == 4
    assert values[0] == {"distance (m)": found.origin_m, "écart cumulé (min)": 0.0}
    second = values[1]
    assert second["distance (m)"] == 250.0
    assert math.isclose(second["écart cumulé (min)"], -1.25, rel_tol=1e-9)
    for value, gap in zip(values[1:], found.rows, strict=True):
        elapsed_s = gap.errors_s[0]
        assert elapsed_s is not None
        assert value == {
            "distance (m)": gap.distance_m,
            "écart cumulé (min)": elapsed_s / 60,
        }


def test_the_usage_and_control_columns_are_not_swapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sur la paire commitée, les deux colonnes sont identiques une fois mises en
    forme : un espion d'``effort_rows`` rend deux lignes écrites ici (révision 1,
    constat 5 a de B)."""
    elapsed, moving = Clock(ClockKind.ELAPSED), Clock(ClockKind.MOVING, 0)

    def effort(projected_s: float, observed_s: float) -> ScenarioEffort:
        e = projected_s / observed_s
        return ScenarioEffort(projected_s, math.log(e), None, e)

    def fake(scores: OutingScores, clocks: Sequence[Clock]) -> tuple[EffortRow, ...]:
        return (
            EffortRow(elapsed, 3600.0, effort(4000.0, 3600.0), effort(3000.0, 3600.0)),
            EffortRow(
                moving,
                3000.0,
                ScenarioEffort(None, None, Unavailability.MODEL_ERROR, None),
                effort(2700.0, 3000.0),
            ),
        )

    monkeypatch.setattr("mountain_perf.ui.sortie.effort_rows", fake)
    _all_files()
    at = _compare(_app())
    assert not at.exception
    assert _cells(at, 0) == [
        {
            "horloge": "écoulé",
            "temps réel": "1:00:00",
            "prévu sur ton préparé": "1:06:40",
            "effort sur ton préparé": "1.11",
            "prévu sur le chemin suivi": "0:50:00",
            "effort sur le chemin suivi": "0.83",
        },
        {
            "horloge": "M θ1",
            "temps réel": "0:50:00",
            "prévu sur ton préparé": "—",
            "effort sur ton préparé": "erreur du modèle",
            "prévu sur le chemin suivi": "0:45:00",
            "effort sur le chemin suivi": "0.90",
        },
    ]


@pytest.mark.parametrize(
    "error",
    [GpxError, ProfileError, TraceError, CurveError, ContractError, OSError],
)
def test_each_reading_error_is_shown_without_traceback(
    monkeypatch: pytest.MonkeyPatch, error: type[Exception]
) -> None:
    """Les six erreurs (révision 1, constat 5 c de B) : au clic, un seul ``st.error``,
    de leur message."""

    def failing(*args: object) -> OutingMatch:
        raise error("lecture impossible")

    monkeypatch.setattr("mountain_perf.ui.sortie.match_outing", failing)
    _all_files()
    at = _compare(_app())
    assert not at.exception
    assert [str(element.value) for element in at.error] == ["lecture impossible"]
    assert not at.dataframe


# ---------------------------------------------------------------------------
# Le résultat gardé
# ---------------------------------------------------------------------------


def test_the_result_stays_on_rerun_and_another_trio_hides_it() -> None:
    _all_files()
    at = _compare(_app())
    assert len(at.dataframe) == 2
    at.run()
    assert not at.exception
    assert len(at.dataframe) == 2
    second = _with_trace(name="z_seconde.gpx")
    at.run()
    at.selectbox(key="sortie.trace").set_value(second).run()
    assert not at.exception
    assert [str(info.value) for info in at.info] == [CHOOSE]
    assert not at.dataframe


def test_an_unreadable_trace_clears_the_kept_result() -> None:
    """Une trace sans heures (``mini_11.gpx``) posée à la main dans ``sorties/``,
    choisie après une comparaison réussie : l'erreur de lecture, puis, la trace d'avant
    choisie à nouveau sans clic, l'invitation à comparer (le résultat gardé a été
    effacé au clic)."""
    _, trace, _ = _all_files()
    at = _compare(_app())
    assert len(at.dataframe) == 2
    undated = _with_trace(UNFOLLOWED_ROUTE)
    at.run()
    at.selectbox(key="sortie.trace").set_value(undated).run()
    at = _compare(at)
    assert not at.exception
    assert len(at.error) == 1
    assert "instant manquant" in str(at.error[0].value)
    at.selectbox(key="sortie.trace").set_value(trace).run()
    assert not at.exception
    assert [str(info.value) for info in at.info] == [CHOOSE]
    assert not at.dataframe


# ---------------------------------------------------------------------------
# L'avertissement « dans la fenêtre » (0010 D2.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("window", "warning"),
    [
        (
            (date(2026, 5, 1), date(2026, 6, 1)),
            "Sortie dans la période d'estimation de la courbe (01/05/2026 – "
            "01/06/2026) : l'écart y est optimiste.",
        ),
        (
            (date(2026, 6, 1), date(2026, 6, 30)),
            "Sortie dans la période d'estimation de la courbe (01/06/2026 – "
            "30/06/2026) : l'écart y est optimiste.",
        ),
        ((date(2026, 6, 2), date(2026, 6, 30)), None),
        ((date(2026, 1, 1), date(2026, 1, 31)), None),
    ],
    ids=["finit ce jour-là", "commence ce jour-là", "commence le lendemain", "janvier"],
)
def test_the_window_warning(window: tuple[date, date], warning: str | None) -> None:
    _with_route()
    _with_trace()
    _with_curve(window)
    at = _compare(_app())
    assert not at.exception
    assert not at.error
    expected = [] if warning is None else [warning]
    assert [str(element.value) for element in at.warning] == expected
    assert CAPTION in [str(caption.value) for caption in at.caption]


# ---------------------------------------------------------------------------
# Sans partie comparable (piège 5)
# ---------------------------------------------------------------------------


def test_a_trace_that_follows_nothing_stops_after_the_profile() -> None:
    _with_route(UNFOLLOWED_ROUTE)
    _with_trace()
    _with_curve()
    at = _compare(_app())
    assert not at.exception
    assert not at.error
    assert [str(info.value) for info in at.info] == [
        "La trace ne suit aucune partie comparable du préparé."
    ]
    assert not at.dataframe
    assert len(at.get("vega_lite_chart")) == 1
    assert not [text for text in _texts(at) if text.startswith("Préfixe comparable")]
