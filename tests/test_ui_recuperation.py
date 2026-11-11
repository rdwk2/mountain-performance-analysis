"""Les pages « récupération » et « Q1 » (AN2-3, annexe C.4 du brief) : les descriptions
Vega-Lite lues comme des données, puis les pages par ``AppTest.from_function``, sans
navigateur ni serveur. Les tables du monde inventé (``fixtures.recovery_world``) sont
écrites sous ``data_dir()``, le dossier neuf de ``tests/conftest.py`` ; le cache des
tables est vidé avant et après chaque test. Sautés sans les extras ``tableau`` et
``analyse``."""

from __future__ import annotations

import dataclasses
import json
import shutil
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("pyarrow")

import streamlit as st
from streamlit.testing.v1 import AppTest

from fixtures.recovery_world import (
    FIRST_DAY,
    base_tables,
    world_rows,
    world_tables,
    write_world,
)
from mountain_perf.analyse import parquet
from mountain_perf.analyse.recovery import RecoveryView, recovery_view
from mountain_perf.analyse.tables import Tables
from mountain_perf.config import data_dir
from mountain_perf.schemas.processed import DayRow
from mountain_perf.ui.recuperation import (
    COLORS,
    PERIOD_ALL,
    garmin_spec,
    page_specs,
)

TIMEOUT_S = 30
SCHEMA_V6 = "https://vega.github.io/schema/vega-lite/v6.json"
GARMIN_TITLE = "HRV selon Garmin (ms) : moyenne de la semaine et bornes de Garmin"
MEASURE_TITLES = [
    "HRV de la nuit (ms)",
    "FC de repos (bpm)",
    "Sommeil mesuré (h)",
    "Stress de la nuit",
    "Respiration de la nuit (resp./min)",
    "SpO2 de la nuit (%)",
]
VALUE_SUFFIXES = (
    "-valeurs-pleines",
    "-valeurs-creuses",
    "-valeurs-hors-etendue",
    "-valeurs-en-pied",
)
OTHER_COMMIT = "d" * 40


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> Tables:
    return base_tables(tmp_path_factory.mktemp("base"))


@pytest.fixture(autouse=True)
def _empty_cache() -> Iterator[None]:
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


def _other(tables: Tables) -> Tables:
    """Les mêmes tables, d'une autre provenance (un autre commit)."""
    provenance = dataclasses.replace(tables.provenance, commit=OTHER_COMMIT)
    return dataclasses.replace(tables, provenance=provenance)


def _written(base: Tables, folder: Path | None = None, **changes: Any) -> Tables:
    tables = world_tables(base, **changes)
    write_world(data_dir() if folder is None else folder, tables)
    return tables


def _view(
    base: Tables,
    *,
    everything: bool = False,
    rows: Sequence[DayRow] | None = None,
    journal: bool = True,
) -> RecoveryView:
    tables = world_tables(base, rows=rows, journal=journal)
    return recovery_view(tables.days, tables.provenance, everything=everything)


def _charts(view: RecoveryView) -> list[dict[str, Any]]:
    """Les graphiques de la page, dans l'ordre, Garmin à la fin."""
    return [*page_specs(view), garmin_spec(view)]


def _layers(charts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [layer for chart in charts for layer in chart["layer"]]


def _named(chart: Mapping[str, Any], suffix: str) -> list[dict[str, Any]]:
    return [layer for layer in chart["layer"] if layer["name"].endswith(suffix)]


def _walk(value: object) -> Iterator[dict[str, Any]]:
    """Chaque objet d'une description, en profondeur."""
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _temporal(chart: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Les encodages ``x`` temporels, couche après couche."""
    return [
        layer["encoding"]["x"]
        for layer in chart["layer"]
        if layer["encoding"].get("x", {}).get("type") == "temporal"
    ]


def _y_axes(chart: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        layer["encoding"]["y"]["axis"]
        for layer in chart["layer"]
        if "axis" in layer["encoding"].get("y", {})
    ]


def _index(text: str) -> int:
    return (date.fromisoformat(text[:10]) - FIRST_DAY).days


def _replaced(changes: Callable[[DayRow], dict[str, Any]]) -> list[DayRow]:
    """Le monde, les 56 dernières lignes changées par ``changes``."""
    rows = list(world_rows())
    for i in range(len(rows) - 56, len(rows)):
        rows[i] = dataclasses.replace(rows[i], **changes(rows[i]))
    return rows


def _recovery() -> None:
    from mountain_perf.ui.recuperation import recuperation_page

    recuperation_page()


def _app(page: Callable[[], None]) -> AppTest:
    return AppTest.from_function(page, default_timeout=TIMEOUT_S).run()


def _specs(at: AppTest) -> list[dict[str, Any]]:
    return [json.loads(element.proto.spec) for element in at.get("vega_lite_chart")]


@pytest.mark.parametrize("everything", [False, True])
def test_every_mark_rule_and_text_has_a_color(base: Tables, everything: bool) -> None:
    charts = _charts(_view(base, everything=everything))
    assert len(charts) == 10
    for layer in _layers(charts):
        mark = layer["mark"]
        encoded = layer["encoding"].get("color", {})
        assert "color" in mark or "scale" in encoded, layer["name"]


def test_no_line_in_the_value_layers(base: Tables) -> None:
    count = 0
    for everything in (False, True):
        for layer in _layers(_charts(_view(base, everything=everything))):
            if layer["name"].endswith(VALUE_SUFFIXES):
                count += 1
                assert layer["mark"]["type"] != "line", layer["name"]
                assert "line" not in layer["mark"], layer["name"]
    assert count >= 12


def test_no_invalid_setting_and_no_zero_in_the_scales(base: Tables) -> None:
    for everything in (False, True):
        view = _view(base, everything=everything)
        charts = _charts(view)
        for item in _walk(charts):
            assert "invalid" not in item
            if item.get("type") == "quantitative" and "scale" in item:
                assert item["scale"]["zero"] is False
        for panel, chart in zip(view.panels, page_specs(view)[1:7], strict=True):
            for layer in chart["layer"]:
                y = layer["encoding"].get("y", {})
                if "scale" in y and panel.domain is not None:
                    assert y["scale"]["domain"] == list(panel.domain)


def test_the_normal_is_drawn_per_run_and_dashed_by_the_view(base: Tables) -> None:
    charts = _charts(_view(base, everything=True))
    normals = [layer for c in charts for layer in _named(c, "-normale")]
    ranges = [
        layer
        for c in charts
        for layer in _named(c, "-plage")
        if not layer["name"].endswith("-isolee-plage")
    ]
    assert normals
    assert ranges
    for layer in normals:
        assert layer["encoding"]["detail"]["field"] == "suite"
        assert layer["encoding"]["strokeDash"]["field"] == "trait"
    for layer in ranges:
        assert layer["encoding"]["detail"]["field"] == "suite"


def test_the_charts_share_the_dates_and_the_axis_margin(base: Tables) -> None:
    for everything in (False, True):
        view = _view(base, everything=everything)
        assert view.x_domain is not None
        for chart in _charts(view):
            assert chart["autosize"] == {"type": "fit-x", "contains": "padding"}
            dated = _temporal(chart)
            assert dated, chart["title"]["text"]
            assert dated[0]["scale"] == {"type": "utc", "domain": list(view.x_domain)}
            assert all(x["scale"] == {"type": "utc"} for x in dated[1:])
            axes = _y_axes(chart)
            assert axes
            assert all(a["minExtent"] == a["maxExtent"] == 48 for a in axes)


def test_the_layer_names_are_unique_on_the_page(base: Tables) -> None:
    for everything in (False, True):
        names = [
            layer["name"]
            for layer in _layers(_charts(_view(base, everything=everything)))
        ]
        assert len(names) == len(set(names))


def test_the_page_charts_in_order(base: Tables) -> None:
    tail = ["Activité du jour, par famille (h)", "Charge selon Garmin", GARMIN_TITLE]
    titles = [chart["title"]["text"] for chart in _charts(_view(base))]
    assert titles == ["Journal", *MEASURE_TITLES, *tail]
    titles = [chart["title"]["text"] for chart in _charts(_view(base, journal=False))]
    assert titles == [*MEASURE_TITLES, *tail]


def test_the_garmin_hrv_has_its_own_color(base: Tables) -> None:
    chart = garmin_spec(_view(base))
    colors = {
        item["color"]
        for item in _walk(chart["layer"])
        if isinstance(item.get("color"), str)
    }
    assert colors == {COLORS["garmin"]}
    assert COLORS["garmin"] != COLORS["normale"]


def test_an_empty_panel_says_so_and_keeps_the_margin(base: Tables) -> None:
    chart = page_specs(_view(base))[6]
    assert chart["title"]["text"] == "SpO2 de la nuit (%)"
    names = [layer["name"] for layer in chart["layer"]]
    assert "night_spo2-axe-vide" in names
    assert "night_spo2-panneau-vide" in names
    assert names.index("night_spo2-axe-vide") < names.index("night_spo2-panneau-vide")
    for suffix in ("-valeurs-pleines", "-valeurs-creuses", "-normale", "-plage"):
        assert not _named(chart, suffix)


def test_without_tables_the_error_of_read_tables_is_shown() -> None:
    at = _app(_recovery)
    assert not at.exception
    assert [error.value for error in at.error] == [
        "aucune table dans processed/ : lancer just process"
    ]
    assert not at.get("vega_lite_chart")


def test_the_page_shows_the_ten_charts(base: Tables) -> None:
    _written(base)
    at = _app(_recovery)
    assert not at.exception
    assert len(_specs(at)) == 10
    assert not at.error
    assert not at.info
    assert at.caption[0].value.startswith(
        "Données au 21/05/2000 à 21 h 15 (heure de Paris)."
    )
    at.radio(key="recuperation.periode").set_value("Toute la table").run()
    assert not at.exception
    assert len(_specs(at)) == 10
    assert "Du 03/01/2000 au 21/05/2000." in [caption.value for caption in at.caption]


def test_without_journal_the_page_says_so(base: Tables) -> None:
    _written(base, journal=False)
    at = _app(_recovery)
    assert [info.value for info in at.info] == [
        "Pas de journal.csv : aucun événement n'est marqué. Un jour sans événement "
        "n'est pas un jour sans maladie."
    ]
    assert len(_specs(at)) == 9


def test_an_empty_table_is_said(base: Tables) -> None:
    _written(base, rows=())
    at = _app(_recovery)
    assert not at.exception
    assert [info.value for info in at.info] == [
        "La table jours n'a aucune ligne : lancer just process."
    ]
    assert not at.get("vega_lite_chart")


def test_the_tables_are_read_once_while_their_provenance_holds(
    base: Tables, monkeypatch: pytest.MonkeyPatch
) -> None:
    tables = _written(base)
    reads: list[Path] = []
    read = parquet.read_tables

    def counted(folder: Path) -> Tables:
        reads.append(folder)
        return read(folder)

    monkeypatch.setattr(parquet, "read_tables", counted)
    at = _app(_recovery)
    at.run()
    at.radio(key="recuperation.periode").set_value(PERIOD_ALL).run()
    assert not at.exception
    assert len(reads) == 1
    write_world(data_dir(), _other(tables))
    at.run()
    assert not at.exception
    assert len(reads) == 2


def test_the_key_of_the_cache_is_the_provenance(base: Tables) -> None:
    assert parquet.tables_key(data_dir()) is None
    tables = _written(base)
    key = parquet.tables_key(data_dir())
    assert key is not None
    assert key.count(b"\n") == 3
    write_world(data_dir(), _other(tables))
    other = parquet.tables_key(data_dir())
    assert other is not None
    assert other != key


def test_the_key_changes_when_any_table_is_rewritten(base: Tables) -> None:
    first, second = data_dir() / "premieres", data_dir() / "autres"
    tables = _written(base, first)
    write_world(second, _other(tables))
    key = parquet.tables_key(first)
    assert key is not None
    for name in (
        parquet.ACTIVITIES_FILE,
        parquet.CLIMBS_FILE,
        parquet.VARIANTS_FILE,
        parquet.DAYS_FILE,
    ):
        mixed = data_dir() / f"melange-{name}"
        shutil.copytree(first / parquet.PROCESSED_DIR, mixed / parquet.PROCESSED_DIR)
        shutil.copy(
            second / parquet.PROCESSED_DIR / name, mixed / parquet.PROCESSED_DIR / name
        )
        changed = parquet.tables_key(mixed)
        assert changed is not None
        assert changed != key, name


def test_every_layer_of_a_chart_has_the_same_date_labels(base: Tables) -> None:
    for everything in (False, True):
        for chart in _charts(_view(base, everything=everything)):
            settings = {
                (x["axis"]["labels"], x["axis"]["ticks"]) for x in _temporal(chart)
            }
            assert len(settings) <= 1, chart["title"]["text"]


def test_the_normal_layer_data_never_crosses_a_gap(base: Tables) -> None:
    view = _view(base, everything=True)
    rows = world_rows()
    for panel, chart in zip(view.panels, page_specs(view)[1:7], strict=True):
        p = panel.measure.value
        for layer in _named(chart, "-normale"):
            runs: dict[str, list[dict[str, Any]]] = {}
            for record in layer["data"]["values"]:
                assert record["normale"] is not None
                runs.setdefault(record["suite"], []).append(record)
            for run in runs.values():
                assert len({record["trait"] for record in run}) == 1
                days = [_index(record["midi"]) for record in run]
                assert days == list(range(days[0], days[0] + len(days)))
                if run[0]["trait"] == "pointillé":
                    straddles = [
                        getattr(rows[d], f"{p}_normal_straddles") for d in days
                    ]
                    assert all(straddles[1:-1])


def test_each_day_is_in_one_value_layer_and_the_foot_at_the_bottom(
    base: Tables,
) -> None:
    for everything in (False, True):
        view = _view(base, everything=everything)
        for panel, chart in zip(view.panels, page_specs(view)[1:7], strict=True):
            days = sorted(
                record["midi"]
                for suffix in VALUE_SUFFIXES
                for layer in _named(chart, panel.measure.value + suffix)
                for record in layer["data"]["values"]
            )
            assert days == [point["midi"] for point in panel.points]
            for layer in _named(chart, "-valeurs-en-pied"):
                assert layer["encoding"]["y"] == {"value": 106}


def test_the_garmin_layers_are_drawn_per_run(base: Tables) -> None:
    chart = garmin_spec(_view(base, everything=True))
    for name, field in (
        ("garmin-bornes", "suite_bornes"),
        ("garmin-moyenne", "suite_moyenne"),
    ):
        (layer,) = [layer for layer in chart["layer"] if layer["name"] == name]
        assert layer["encoding"]["detail"]["field"] == field
        assert all(record[field] is not None for record in layer["data"]["values"])


def test_empty_activity_and_garmin_charts_say_so(base: Tables) -> None:
    rows = _replaced(
        lambda row: {
            "activity_count": 0,
            "garmin_training_load": 0.0,
            "activities_without_load": 0,
            "foot_elapsed_s": 0.0,
            "mtb_elapsed_s": 0.0,
            "ski_touring_elapsed_s": 0.0,
            "other_elapsed_s": 0.0,
            "other_activity_count": 0,
            "activities_without_elapsed": 0,
            "hrv_weekly_avg_ms": None,
            "hrv_baseline_balanced_low_ms": None,
            "hrv_baseline_balanced_upper_ms": None,
        }
    )
    charts = _charts(_view(base, rows=rows))
    for chart, prefix in zip(charts[-3:], ("durees", "charge", "garmin"), strict=True):
        assert [layer["name"] for layer in chart["layer"]] == [
            f"{prefix}-axe-vide",
            f"{prefix}-vide",
        ]


def _sentence(chart: Mapping[str, Any]) -> str | None:
    texts = [
        layer["encoding"]["text"]["value"]
        for layer in chart["layer"]
        if layer["mark"]["type"] == "text"
    ]
    return texts[0] if texts else None


def test_a_chart_with_nothing_to_draw_is_empty(base: Tables) -> None:
    rows = _replaced(
        lambda row: {
            "hrv_weekly_avg_ms": None,
            "hrv_baseline_balanced_upper_ms": None,
            "activities_without_elapsed": row.activity_count,
            "foot_elapsed_s": 0.0,
            "mtb_elapsed_s": 0.0,
            "ski_touring_elapsed_s": 0.0,
            "other_elapsed_s": 0.0,
        }
    )
    durations, loads, garmin = _charts(_view(base, rows=rows))[-3:]
    assert _sentence(durations) == "Aucune durée d'activité sur la période"
    assert _sentence(loads) is None
    assert _sentence(garmin) == "Pas de HRV selon Garmin sur la période"


def test_no_layer_without_data(base: Tables) -> None:
    for everything in (False, True):
        for journal in (False, True):
            view = _view(base, everything=everything, journal=journal)
            for layer in _layers(_charts(view)):
                assert layer["data"]["values"], layer["name"]


def test_the_chart_settings_are_written_values(base: Tables) -> None:
    for chart in _charts(_view(base)):
        assert chart["$schema"] == SCHEMA_V6
        assert chart["autosize"] == {"type": "fit-x", "contains": "padding"}
        assert chart["config"]["locale"]["number"]["decimal"] == ","
        assert chart["width"] == "container"
        axes = _y_axes(chart)
        assert axes
        assert all(a["minExtent"] == 48 and a["maxExtent"] == 48 for a in axes)


def test_the_dates_are_written_on_the_first_chart_the_load_and_garmin(
    base: Tables,
) -> None:
    for journal, labelled in (
        (True, {"Journal", "Charge selon Garmin", GARMIN_TITLE}),
        (False, {"HRV de la nuit (ms)", "Charge selon Garmin", GARMIN_TITLE}),
    ):
        shown = set()
        for chart in _charts(_view(base, journal=journal)):
            dated = _temporal(chart)
            if dated and dated[0]["axis"]["labels"]:
                assert dated[0]["axis"]["ticks"]
                shown.add(chart["title"]["text"])
        assert shown == labelled


def test_the_dash_of_the_normal_is_written(base: Tables) -> None:
    dashes = [
        layer["encoding"]["strokeDash"]
        for layer in _layers(_charts(_view(base, everything=True)))
        if "strokeDash" in layer["encoding"]
    ]
    assert dashes
    for dash in dashes:
        assert dash["scale"] == {
            "domain": ["plein", "pointillé"],
            "range": [[1, 0], [5, 4]],
        }


def test_the_durations_are_stacked_by_their_order(base: Tables) -> None:
    (layer,) = [
        layer for layer in _layers(_charts(_view(base))) if layer["name"] == "durees"
    ]
    assert layer["transform"] == [
        {
            "stack": "heures",
            "groupby": ["debut"],
            "sort": [{"field": "ordre"}],
            "as": ["h0", "h1"],
        }
    ]
    assert layer["mark"]["type"] == "rect"


def test_the_value_tooltip_and_the_edge_shapes_are_written(base: Tables) -> None:
    fields = [
        "Jour",
        "Valeur",
        "Admission",
        "Nuit",
        "FC de repos",
        "Normale",
        "Plage",
        "Jours admis",
    ]
    layers = _layers(_charts(_view(base)))
    values = [layer for layer in layers if layer["name"].endswith(VALUE_SUFFIXES)]
    assert values
    for layer in values:
        assert [t["field"] for t in layer["encoding"]["tooltip"]] == fields
    edges = [
        layer for layer in layers if layer["name"].endswith("-valeurs-hors-etendue")
    ]
    assert edges
    for layer in edges:
        assert layer["encoding"]["shape"]["scale"] == {
            "domain": ["dessous", "dessus"],
            "range": ["triangle-down", "triangle-up"],
        }


def test_the_journal_legend_lists_the_present_types_only(base: Tables) -> None:
    (layer,) = [
        layer for layer in _layers(_charts(_view(base))) if layer["name"] == "rubans"
    ]
    assert layer["encoding"]["color"]["legend"]["values"] == [
        "Maladie",
        "Blessure",
        "Course",
        "Séjour en altitude",
    ]


def test_the_empty_panel_sentence_is_written(base: Tables) -> None:
    sentences = [
        layer["encoding"]["text"]["value"]
        for layer in _layers(_charts(_view(base)))
        if layer["name"].endswith("-panneau-vide")
    ]
    assert sentences == [
        "SpO2 de la nuit (%) : aucune valeur ni normale sur la période"
    ]
