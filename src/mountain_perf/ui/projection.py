"""La page « projection » (M5-1) : un préparé et une courbe choisis, les réglages
générés depuis les specs ; la synthèse de ``mperf project``, le profil, la vitesse
projetée, le tableau des passages et l'export CSV. Tout vient de la bibliothèque ; la
page met en forme."""

import io
from collections.abc import Callable, Sequence
from datetime import datetime, time
from pathlib import Path
from typing import Any

import streamlit as st

from mountain_perf.controls import changed_values, parameter_controls
from mountain_perf.data_files import FileKind, list_curves, list_files
from mountain_perf.gpx import (
    PROFILE_PARAMETER_DISPLAYS,
    PROFILE_PARAMETER_SPECS,
    GpxError,
    ProfileError,
)
from mountain_perf.model import (
    PROJECTION_PARAMETER_DISPLAYS,
    PROJECTION_PARAMETER_SPECS,
    CurveError,
)
from mountain_perf.model.export import write_passages_csv
from mountain_perf.model.views import (
    PassageRow,
    civil_start,
    interval_speeds,
    passage_rows,
)
from mountain_perf.reports import projection_summary_lines
from mountain_perf.runs import project_route
from mountain_perf.ui.components import (
    DISTANCE_AXIS,
    data_folder,
    file_adder,
    parameter_inputs,
)
from mountain_perf.units import (
    UNDEFINED,
    format_count,
    format_duration,
    format_pace,
    format_vam,
    ms_to_kmh,
)
from mountain_perf.validation import ContractError

PLACE_COLOR = "gray"
"""La couleur des lieux du profil, leur règle et leur nom : sans couleur donnée, Vega
les dessine en noir, illisibles sur le thème sombre ; le gris se lit sur les deux."""


def _name(path: Path) -> str:
    return path.name


def _or_dash(value: float | None, formatted: Callable[[float], str]) -> str:
    """Une valeur mise en forme, ou ``—`` quand elle est absente."""
    return UNDEFINED if value is None else formatted(value)


def _profile_chart(
    distance_m: Sequence[float],
    elevation_m: Sequence[float],
    rows: Sequence[PassageRow],
) -> dict[str, Any]:
    """Le profil, une règle verticale pointillée et le nom de chaque passage ; la
    règle et le nom en ``PLACE_COLOR``, lisibles sur le thème clair comme sur le
    sombre."""
    passages = [{"distance (m)": row.distance_m, "passage": row.name} for row in rows]
    return {
        "layer": [
            {
                "data": {
                    "values": [
                        {"distance (m)": d, "altitude (m)": z}
                        for d, z in zip(distance_m, elevation_m, strict=True)
                    ]
                },
                "mark": "line",
                "encoding": {
                    "x": DISTANCE_AXIS,
                    "y": {
                        "field": "altitude (m)",
                        "type": "quantitative",
                        "scale": {"zero": False},
                        "axis": {"format": "d"},
                    },
                },
            },
            {
                "data": {"values": passages},
                "mark": {"type": "rule", "strokeDash": [4, 4], "color": PLACE_COLOR},
                "encoding": {
                    "x": DISTANCE_AXIS,
                    "tooltip": [
                        {"field": "passage", "type": "nominal"},
                        {"field": "distance (m)", "type": "quantitative"},
                    ],
                },
            },
            {
                "data": {"values": passages},
                "mark": {
                    "type": "text",
                    "angle": 270,
                    "align": "left",
                    "baseline": "bottom",
                    "dx": 4,
                    "dy": -4,
                    "color": PLACE_COLOR,
                },
                "encoding": {
                    "x": DISTANCE_AXIS,
                    "y": {"value": 4},
                    "text": {"field": "passage", "type": "nominal"},
                },
            },
        ]
    }


def _speed_chart(
    distance_m: Sequence[float], speeds_ms: Sequence[float]
) -> dict[str, Any]:
    """La vitesse projetée de chaque intervalle, placée à son début."""
    return {
        "data": {
            "values": [
                {"distance (m)": d, "vitesse (km/h)": ms_to_kmh(v)}
                for d, v in zip(distance_m[:-1], speeds_ms, strict=True)
            ]
        },
        "mark": "line",
        "encoding": {
            "x": DISTANCE_AXIS,
            "y": {"field": "vitesse (km/h)", "type": "quantitative"},
        },
    }


def _table(rows: Sequence[PassageRow]) -> list[dict[str, str]]:
    """Le tableau des passages, une ligne par passage ; ``—`` pour une valeur
    absente."""
    table = []
    for row in rows:
        segment = row.segment
        leg = (UNDEFINED,) * 4
        if segment is not None:
            leg = (
                format_count(segment.distance_m),
                format_count(segment.ascent_m),
                format_count(segment.descent_m),
                format_duration(segment.duration_s),
            )
        table.append(
            {
                "passage": row.name,
                "distance (m)": format_count(row.distance_m),
                "altitude (m)": format_count(row.elevation_m),
                "temps": format_duration(row.arrival_s),
                "heure": UNDEFINED
                if row.clock_time is None
                else row.clock_time.strftime("%d/%m %H:%M"),
                "tronçon (m)": leg[0],
                "D+ (m)": leg[1],
                "D− (m)": leg[2],
                "durée": leg[3],
                "allure": _or_dash(row.speed_ms, format_pace),
                "montée horaire": _or_dash(row.ascent_rate_ms, format_vam),
            }
        )
    return table


def projection_page() -> None:
    """La page « projection »."""
    st.title("Projection")
    data = data_folder()
    if data is None:
        return
    file_adder(data)
    routes = list_files(data, FileKind.ROUTE)
    if not routes:
        st.info("Aucun préparé dans routes/ : ajoute un GPX (barre latérale).")
        return
    curves = list_curves(data)
    if not curves:
        st.info("Aucune courbe (CSV et son .meta.json) dans reference/.")
        return

    profile_controls = parameter_controls(
        PROFILE_PARAMETER_SPECS, PROFILE_PARAMETER_DISPLAYS
    )
    projection_controls = parameter_controls(
        PROJECTION_PARAMETER_SPECS, PROJECTION_PARAMETER_DISPLAYS
    )
    start: datetime | None = None
    with st.sidebar:
        route = st.selectbox("Préparé", routes, format_func=_name, key="prepare")
        curve = st.selectbox("Courbe", curves, format_func=_name, key="courbe")
        st.subheader("Réglages")
        profile_values = parameter_inputs(profile_controls, "profil")
        projection_values = parameter_inputs(projection_controls, "projection")
        if st.checkbox("Heure de départ", key="depart"):
            day = st.date_input("Jour", key="depart_jour")
            at = st.time_input("Heure", value=time(8, 0), key="depart_heure")
            start = civil_start(day, at)

    try:
        run = project_route(
            route,
            curve,
            changed_values(profile_controls, profile_values),
            changed_values(projection_controls, projection_values),
        )
    except (GpxError, ProfileError, CurveError, ContractError) as error:
        st.error(str(error))
        return

    st.code("\n".join(projection_summary_lines(run)), language=None)
    rows = passage_rows(run.projection, start)
    profile = run.projection.profile

    st.subheader("Profil")
    st.vega_lite_chart(
        spec=_profile_chart(profile.distance_m, profile.elevation_m, rows),
        width="stretch",
    )

    st.subheader("Vitesse projetée")
    speeds_ms = interval_speeds(run.projection, run.curve.curve)
    st.vega_lite_chart(
        spec=_speed_chart(profile.distance_m, speeds_ms), width="stretch"
    )

    st.subheader("Passages")
    st.dataframe(_table(rows), hide_index=True)

    stream = io.StringIO()
    write_passages_csv(run.projection, stream)
    st.download_button(
        "Exporter les passages (CSV)",
        stream.getvalue(),
        file_name=f"{route.stem}_passages.csv",
        mime="text/csv",
        key="export",
    )
