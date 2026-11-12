"""La page « récupération » (AN2-3, ``docs/decisions/0019``) : la table ``jours`` de
``processed/``, sans rien calculer (règle 7 de ``CLAUDE.md``) — les six mesures contre
leur normale, le journal, l'activité du jour, puis la HRV selon Garmin à part.

La vue vient de ``mountain_perf.analyse.recovery`` ; ce module n'écrit que les
descriptions Vega-Lite et la mise en page. ``mountain_perf.analyse`` ne s'importe que
dans les fonctions (``tests/test_ui_imports.py``, ``PISTE_PAGES``).

Ce que le rendu a appris (§ 7 du brief AN2-3) : un graphique par panneau, sans
``vconcat`` (Streamlit ne donne pas la largeur du conteneur aux vues concaténées qui ont
des couches) ; ``autosize`` en ``fit-x`` ; des noms de couche uniques sur la page (deux
couches du même nom mêlent leurs données) ; le schéma Vega-Lite v6 ; le domaine des
dates sur la première couche datée seulement, et aucune couche sans donnée.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import streamlit as st

from mountain_perf.ui.components import data_folder

COLORS: dict[str, str] = {
    "valeur": "#4a8bd6",
    "normale": "#f28e2b",
    "rupture": "#b07aa1",
    "incertain": "#bab0ac",
    "pied": "#9d9d9d",
    "texte": "#9d9d9d",
    "charge": "#9c755f",
    "garmin": "#ff9da7",
}
"""Les couleurs des marques."""

JOURNAL_COLORS: list[str] = [
    "#e15759",
    "#76b7b2",
    "#edc948",
    "#59a14f",
    "#ff9da7",
    "#9c755f",
    "#bab0ac",
    "#4e79a7",
]
"""Les couleurs des types du journal, dans l'ordre de ``JOURNAL_LABELS``."""

FAMILY_COLORS: list[str] = ["#59a14f", "#edc948", "#76b7b2", "#bab0ac"]
"""Les couleurs des familles d'activité, dans l'ordre de ``FAMILIES``."""

PANEL_HEIGHT = 110
"""La hauteur d'un panneau de mesure et de la HRV selon Garmin, en pixels."""

NARROW_HEIGHT = 70
"""La hauteur des durées et de la charge, en pixels."""

Y_AXIS_EXTENT = 48
"""La marge de l'axe des valeurs, la même sur chaque graphique : les zones de tracé
s'alignent."""

AUTOSIZE: dict[str, str] = {"type": "fit-x", "contains": "padding"}
"""En largeur étirée, ``fit`` ferait tenir la figure dans sa hauteur."""

LOCALE: dict[str, Any] = {
    "number": {
        "decimal": ",",
        "thousands": "\u202f",
        "grouping": [3],
        "currency": ["", "\u00a0\u20ac"],
    }
}
"""La virgule décimale, des espaces fines insécables entre les milliers."""

MEASURES_CAPTION = (
    "Mesures : point plein, admis dans la normale ; point creux, valeur écartée (la "
    "raison au survol) ; triangle, valeur écartée hors de l'échelle, posée au bord ; "
    "trait gris en pied, pas de valeur. Normale : trait plein, en pointillé quand sa "
    "fenêtre mêle l'avant et l'après d'une rupture (trait vertical) ou d'un jour "
    "incertain (fond gris) ; un repère et un trait vertical seuls : une normale isolée "
    "(un seul jour de son segment sur la période)."
)
LOAD_CAPTION = (
    "Charge : point plein, la somme des charges selon Garmin ; point creux, une charge "
    "minorée (des activités du jour sont sans charge) ; trait gris en pied, aucune "
    "activité du jour n'en a."
)
PERIOD_RECENT = "8 dernières semaines"
PERIOD_ALL = "Toute la table"
POINT_TOOLTIP: tuple[str, ...] = (
    "Jour",
    "Valeur",
    "Admission",
    "Nuit",
    "FC de repos",
    "Normale",
    "Plage",
    "Jours admis",
)
"""Le survol d'une valeur."""

_SCHEMA = "https://vega.github.io/schema/vega-lite/v6.json"
_GARMIN_TITLE = "HRV selon Garmin (ms) : moyenne de la semaine et bornes de Garmin"
_DASH = {"domain": ["plein", "pointillé"], "range": [[1, 0], [5, 4]]}
_EDGE_SHAPES = {
    "domain": ["dessous", "dessus"],
    "range": ["triangle-down", "triangle-up"],
}
_RIBBON_HEIGHT = 22


def _tooltip(fields: Sequence[str]) -> list[dict[str, str]]:
    return [{"field": field, "type": "nominal"} for field in fields]


def _values(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(record) for record in records]


def _x(field: str) -> dict[str, Any]:
    """Un axe des dates, sans domaine ni réglage des étiquettes (posés par
    :func:`_chart`)."""
    return {
        "field": field,
        "type": "temporal",
        "scale": {"type": "utc"},
        "axis": {"title": None, "format": "%d/%m", "grid": True},
    }


def _y_axis(title: str | None = None) -> dict[str, Any]:
    return {"title": title, "minExtent": Y_AXIS_EXTENT, "maxExtent": Y_AXIS_EXTENT}


def _y(
    field: str, domain: tuple[float, float] | None, title: str | None = None
) -> dict[str, Any]:
    """Un axe des valeurs, sans zéro, au domaine du panneau s'il en a un."""
    scale: dict[str, Any] = {"zero": False}
    if domain is not None:
        scale["domain"] = list(domain)
    return {
        "field": field,
        "type": "quantitative",
        "scale": scale,
        "axis": _y_axis(title),
    }


def _layer(
    name: str,
    records: Sequence[Mapping[str, Any]],
    mark: dict[str, Any],
    encoding: dict[str, Any],
) -> dict[str, Any] | None:
    """Une couche ; ``None`` sans donnée (aucune couche vide n'est émise)."""
    if not records:
        return None
    return {
        "name": name,
        "data": {"values": _values(records)},
        "mark": mark,
        "encoding": encoding,
    }


def _empty(prefix: str, sentence: str, height: int) -> list[dict[str, Any] | None]:
    """Les deux couches d'un graphique vide : l'axe, invisible, qui garde la marge,
    puis la phrase."""
    datum = [{"vide": 0}]
    return [
        _layer(
            f"{prefix}-axe-vide",
            datum,
            {"type": "point", "color": COLORS["texte"], "opacity": 0},
            {
                "y": {
                    "field": "vide",
                    "type": "quantitative",
                    "axis": {
                        **_y_axis(),
                        "labels": False,
                        "ticks": False,
                        "domain": False,
                        "grid": False,
                    },
                }
            },
        ),
        _layer(
            f"{prefix}-{'panneau-vide' if prefix not in _CHARTS else 'vide'}",
            datum,
            {
                "type": "text",
                "align": "left",
                "baseline": "middle",
                "color": COLORS["texte"],
            },
            {
                "x": {"value": 4},
                "y": {"value": height / 2},
                "text": {"value": sentence},
            },
        ),
    ]


_CHARTS = ("durees", "charge", "garmin")
"""Les graphiques dont la phrase vide s'appelle ``<préfixe>-vide`` ; celle d'une
mesure s'appelle ``<p>-panneau-vide``."""


def _chart(
    view: Any,
    title: str,
    height: int,
    layers: Sequence[dict[str, Any] | None],
    *,
    labels: bool,
) -> dict[str, Any]:
    """Un graphique autonome : ses couches non vides, le domaine des dates sur la
    première couche datée seulement, le même réglage des étiquettes sur toutes."""
    kept = [layer for layer in layers if layer is not None]
    dated = False
    for layer in kept:
        x = layer["encoding"].get("x")
        if x is None or x.get("type") != "temporal":
            continue
        x["axis"] = {**x["axis"], "labels": labels, "ticks": labels}
        if not dated and view.x_domain is not None:
            x["scale"] = {**x["scale"], "domain": list(view.x_domain)}
            dated = True
    return {
        "$schema": _SCHEMA,
        "autosize": dict(AUTOSIZE),
        "config": {"locale": LOCALE},
        "width": "container",
        "height": height,
        "title": {
            "text": title,
            "anchor": "start",
            "fontSize": 12,
            "fontWeight": "normal",
            "color": COLORS["texte"],
        },
        "layer": kept,
    }


def _uncertain(name: str, view: Any) -> dict[str, Any] | None:
    return _layer(
        name,
        view.uncertain,
        {"type": "rect", "color": COLORS["incertain"], "opacity": 0.25},
        {"x": _x("debut"), "x2": {"field": "fin"}},
    )


def measure_spec(view: Any, panel: Any, *, labels: bool = False) -> dict[str, Any]:
    """Le graphique d'une mesure (U7)."""
    p = panel.measure.value
    domain = panel.domain
    dash = {"field": "trait", "type": "nominal", "scale": _DASH, "legend": None}
    normal_color = COLORS["normale"]
    layers: list[dict[str, Any] | None] = [_uncertain(f"{p}-incertains", view)]
    layers += [
        _layer(
            f"{p}-plage",
            panel.normal_lines,
            {"type": "area", "color": normal_color, "opacity": 0.18},
            {
                "x": _x("midi"),
                "y": _y("bas", domain),
                "y2": {"field": "haut"},
                "detail": {"field": "suite", "type": "nominal"},
            },
        ),
        _layer(
            f"{p}-normale",
            panel.normal_lines,
            {"type": "line", "color": normal_color},
            {
                "x": _x("midi"),
                "y": _y("normale", domain),
                "detail": {"field": "suite", "type": "nominal"},
                "strokeDash": dash,
            },
        ),
        _layer(
            f"{p}-normale-isolee-plage",
            panel.isolated,
            {"type": "rule", "color": normal_color},
            {
                "x": _x("midi"),
                "y": _y("bas", domain),
                "y2": {"field": "haut"},
                "strokeDash": dash,
            },
        ),
        _layer(
            f"{p}-normale-isolee",
            panel.isolated,
            {"type": "tick", "orient": "horizontal", "color": normal_color},
            {"x": _x("midi"), "y": _y("normale", domain)},
        ),
        _layer(
            f"{p}-ruptures",
            panel.ruptures,
            {"type": "rule", "color": COLORS["rupture"]},
            {"x": _x("debut"), "tooltip": _tooltip(("Rupture",))},
        ),
    ]
    tooltip = _tooltip(POINT_TOOLTIP)
    if domain is not None:
        full = [pt for pt in panel.points if pt["marque"] == "plein"]
        hollow = [
            pt for pt in panel.points if pt["marque"] == "creux" and pt["hors"] is None
        ]
        outside = [pt for pt in panel.points if pt["hors"] is not None]
        color = COLORS["valeur"]
        layers += [
            _layer(
                f"{p}-valeurs-pleines",
                full,
                {"type": "point", "filled": True, "color": color},
                {
                    "x": _x("midi"),
                    "y": _y("y", domain, panel.title),
                    "tooltip": tooltip,
                },
            ),
            _layer(
                f"{p}-valeurs-creuses",
                hollow,
                {"type": "point", "filled": False, "color": color},
                {"x": _x("midi"), "y": _y("y", domain), "tooltip": tooltip},
            ),
            _layer(
                f"{p}-valeurs-hors-etendue",
                outside,
                {"type": "point", "filled": False, "color": color},
                {
                    "x": _x("midi"),
                    "y": _y("y", domain),
                    "shape": {
                        "field": "hors",
                        "type": "nominal",
                        "scale": _EDGE_SHAPES,
                        "legend": None,
                    },
                    "tooltip": tooltip,
                },
            ),
        ]
    else:
        layers += _empty(
            p, f"{panel.title} : aucune valeur ni normale sur la période", PANEL_HEIGHT
        )
    layers.append(
        _layer(
            f"{p}-valeurs-en-pied",
            [pt for pt in panel.points if pt["marque"] == "pied"],
            {"type": "tick", "orient": "vertical", "color": COLORS["pied"]},
            {
                "x": _x("midi"),
                "y": {"value": PANEL_HEIGHT - 4},
                "tooltip": tooltip,
            },
        )
    )
    return _chart(view, panel.title, PANEL_HEIGHT, layers, labels=labels)


def journal_spec(view: Any) -> dict[str, Any]:
    """Le graphique du journal (U9) : un ruban par suite de jours qui portent un
    type."""
    from mountain_perf.analyse.recovery import JOURNAL_LABELS

    names = list(JOURNAL_LABELS.values())
    present = [name for name in names if any(r["Type"] == name for r in view.ribbons)]
    layers = [
        _uncertain("journal-incertains", view),
        _layer(
            "rubans",
            view.ribbons,
            {"type": "rect"},
            {
                "x": _x("debut"),
                "x2": {"field": "fin"},
                "y": {
                    "field": "Type",
                    "type": "nominal",
                    "sort": names,
                    "axis": {**_y_axis(), "labels": False, "ticks": False},
                },
                "color": {
                    "field": "Type",
                    "type": "nominal",
                    "scale": {"domain": names, "range": JOURNAL_COLORS},
                    "legend": {"orient": "top", "title": None, "values": present},
                },
                "tooltip": _tooltip(("Type", "Période")),
            },
        ),
    ]
    height = max(_RIBBON_HEIGHT * len(present), _RIBBON_HEIGHT)
    return _chart(view, "Journal", height, layers, labels=True)


def durations_spec(view: Any) -> dict[str, Any]:
    """Les durées de l'activité du jour, empilées par famille (U10)."""
    from mountain_perf.analyse.recovery import FAMILIES

    title = "Activité du jour, par famille (h)"
    if not view.durations:
        layers = _empty(
            "durees", "Aucune durée d'activité sur la période", NARROW_HEIGHT
        )
        return _chart(view, title, NARROW_HEIGHT, layers, labels=False)
    layer = _layer(
        "durees",
        view.durations,
        {"type": "rect"},
        {
            "x": _x("debut"),
            "x2": {"field": "fin"},
            "y": {"field": "h0", "type": "quantitative", "axis": _y_axis()},
            "y2": {"field": "h1"},
            "color": {
                "field": "famille",
                "type": "nominal",
                "scale": {
                    "domain": [name for _, name in FAMILIES],
                    "range": FAMILY_COLORS,
                },
                "legend": {"orient": "top", "title": None},
            },
            "tooltip": _tooltip(("Jour", "famille", "Durée")),
        },
    )
    assert layer is not None
    layer["transform"] = [
        {
            "stack": "heures",
            "groupby": ["debut"],
            "sort": [{"field": "ordre"}],
            "as": ["h0", "h1"],
        }
    ]
    return _chart(view, title, NARROW_HEIGHT, [layer], labels=False)


def loads_spec(view: Any) -> dict[str, Any]:
    """La charge selon Garmin (U12)."""
    title = "Charge selon Garmin"
    if not view.loads:
        layers = _empty("charge", "Aucune activité sur la période", NARROW_HEIGHT)
        return _chart(view, title, NARROW_HEIGHT, layers, labels=True)
    tooltip = _tooltip(
        ("Jour", "Charge", "Activités", "Sans charge", "Autres activités", "Sans durée")
    )
    color = COLORS["charge"]

    def marked(mark: str) -> list[Mapping[str, Any]]:
        return [load for load in view.loads if load["marque"] == mark]

    layers = [
        _layer(
            "charge-pleine",
            marked("plein"),
            {"type": "point", "filled": True, "color": color},
            {"x": _x("midi"), "y": _y("charge", None), "tooltip": tooltip},
        ),
        _layer(
            "charge-minoree",
            marked("creux"),
            {"type": "point", "filled": False, "color": color},
            {"x": _x("midi"), "y": _y("charge", None), "tooltip": tooltip},
        ),
        _layer(
            "charge-absente",
            marked("pied"),
            {"type": "tick", "orient": "vertical", "color": COLORS["pied"]},
            {
                "x": _x("midi"),
                "y": {"value": NARROW_HEIGHT - 4},
                "tooltip": tooltip,
            },
        ),
    ]
    return _chart(view, title, NARROW_HEIGHT, layers, labels=True)


def garmin_spec(view: Any) -> dict[str, Any]:
    """La HRV selon Garmin (U13), à part, par suites de jours consécutifs."""
    if not view.garmin_hrv:
        layers = _empty(
            "garmin", "Pas de HRV selon Garmin sur la période", PANEL_HEIGHT
        )
        return _chart(view, _GARMIN_TITLE, PANEL_HEIGHT, layers, labels=True)
    color = COLORS["garmin"]
    layers = [
        _layer(
            "garmin-bornes",
            [day for day in view.garmin_hrv if day["suite_bornes"] is not None],
            {"type": "area", "color": color, "opacity": 0.25},
            {
                "x": _x("midi"),
                "y": _y("bas", None),
                "y2": {"field": "haut"},
                "detail": {"field": "suite_bornes", "type": "nominal"},
            },
        ),
        _layer(
            "garmin-moyenne",
            [day for day in view.garmin_hrv if day["suite_moyenne"] is not None],
            {"type": "line", "point": {"color": color}, "color": color},
            {
                "x": _x("midi"),
                "y": _y("moyenne", None),
                "detail": {"field": "suite_moyenne", "type": "nominal"},
                "tooltip": _tooltip(("Jour", "Moyenne de la semaine", "Bornes")),
            },
        ),
    ]
    return _chart(view, _GARMIN_TITLE, PANEL_HEIGHT, layers, labels=True)


def page_specs(view: Any) -> list[dict[str, Any]]:
    """Les graphiques empilés de la page, dans l'ordre (U1) : le journal s'il y a des
    rubans, les six mesures, les durées, la charge."""
    specs: list[dict[str, Any]] = []
    if view.ribbons:
        specs.append(journal_spec(view))
    for panel in view.panels:
        specs.append(measure_spec(view, panel, labels=not specs))
    specs.append(durations_spec(view))
    specs.append(loads_spec(view))
    return specs


def _read(data: Path, key: bytes) -> Any:
    """La lecture des tables, sous la clé de leur provenance ; ``read_tables`` résolu
    à l'appel."""
    from mountain_perf.analyse import parquet

    del key  # la clé ne sert qu'au cache
    return parquet.read_tables(data)


_cached_read = st.cache_resource(max_entries=1, show_spinner="Lecture des tables…")(
    _read
)
"""La lecture gardée en mémoire tant que le dossier et la clé ne changent pas ;
``st.cache_resource`` appliqué par un appel, sans décorateur (``mypy`` sans l'extra
``tableau``)."""


def cached_tables(data: Path) -> Any:
    """Les tables de ``data/processed/``, gardées en mémoire tant que leur provenance
    ne change pas ; sans clé (``tables_key`` rend ``None``), la lecture directe, qui
    lève comme ``read_tables``."""
    from mountain_perf.analyse import parquet

    key = parquet.tables_key(data)
    if key is None:
        return parquet.read_tables(data)
    return _cached_read(data, key)


def recuperation_page() -> None:
    """La page « récupération » (U15)."""
    from mountain_perf.analyse.parquet import ProcessedError
    from mountain_perf.analyse.recovery import recovery_view

    st.title("Récupération")
    data = data_folder()
    if data is None:
        return
    try:
        tables = cached_tables(data)
    except (ProcessedError, FileNotFoundError) as error:
        st.error(str(error))
        return
    choice = st.radio(
        "Période",
        (PERIOD_RECENT, PERIOD_ALL),
        horizontal=True,
        key="recuperation.periode",
    )
    view = recovery_view(
        tables.days, tables.provenance, everything=choice == PERIOD_ALL
    )
    st.caption(f"{view.data_at}. Exploratoire : aucune alerte, aucun verdict.")
    if view.first_day is None or view.last_day is None:
        st.info("La table jours n'a aucune ligne : lancer just process.")
        return
    st.caption(f"Du {view.first_day:%d/%m/%Y} au {view.last_day:%d/%m/%Y}.")
    if view.journal_absent:
        st.info(
            "Pas de journal.csv : aucun événement n'est marqué. Un jour sans événement "
            "n'est pas un jour sans maladie."
        )
    for spec in page_specs(view):
        st.vega_lite_chart(spec=spec, width="stretch")
    st.caption(MEASURES_CAPTION)
    st.caption(LOAD_CAPTION)
    for sentence in view.legend:
        st.caption(sentence)
    st.vega_lite_chart(spec=garmin_spec(view), width="stretch")
