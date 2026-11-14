"""La page « sortie » (M5-2) : une sortie comparée à son préparé par v0 brut à l'effort
1, le contrôle d'une sortie — ``mperf match --curve`` en interface. Le tracé suivi,
prévu contre réalisé et l'effort effectif, l'écart cumulé aux points. La courbe à
l'origine de la sortie (par défaut), sur une plage de dates, ou un fichier de
``reference/`` (OG-UI). Tout vient de la bibliothèque ; la page met en forme."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit as st

from mountain_perf.data_files import FileKind, list_curves, list_files
from mountain_perf.estimation.origin import OriginHistory
from mountain_perf.gpx import GpxError, ProfileError
from mountain_perf.gpx.trace_reader import TraceError
from mountain_perf.ingest.interim import InterimError
from mountain_perf.model import CurveError
from mountain_perf.outing_views import (
    METRIC_UNAVAILABILITY_LABELS,
    POINT_STATUS_LABELS,
    EffortRow,
    Gaps,
    ScenarioEffort,
    admitted_spans,
    clock_label,
    effort_rows,
    followed_route,
    gaps,
)
from mountain_perf.reports import (
    curve_warnings,
    origin_curve_lines,
    outing_support_lines,
    range_curve_lines,
)
from mountain_perf.runs import (
    CourseOrigin,
    CurveBytes,
    OutingCheck,
    OutingMatch,
    check_outing,
    match_outing,
    outing_day,
    outing_support_share,
    paris_today,
)
from mountain_perf.schemas import Clock, RouteProfile
from mountain_perf.ui.components import (
    DISTANCE_AXIS,
    WINDOW_LINK,
    FileSource,
    OriginSource,
    cached_origin_curve,
    cached_range_curve,
    curve_source_inputs,
    data_folder,
    file_adder,
)
from mountain_perf.units import (
    UNDEFINED,
    format_count,
    format_duration,
    format_share,
    format_signed_duration,
)
from mountain_perf.validation import ContractError

RESULT_KEY = "sortie.resultat"
"""Le dernier résultat, gardé d'une relance à l'autre avec le trio comparé (le préparé,
la trace, la source de la courbe)."""

CLOCK_LEGEND = (
    "Horloges : écoulé, tout le temps ; M θn, le temps en mouvement ; (M+U) θn, en "
    "mouvement ou incertain ; θn, la convention d'arrêt retenue (0010 D5)."
)
"""La légende des horloges, sous le tableau prévu contre réalisé."""

EFFORT_LIMITS = (
    "L'effort effectif est l'effort auquel v0 aurait prévu ton temps sur la partie "
    "comparée. Il est rétrospectif, limité à cette partie, faussé par les arrêts sous "
    "l'écoulé, et il mêle ton effort du jour et l'erreur de la courbe ; sur ton "
    "préparé, s'y ajoute l'écart entre le préparé et le chemin suivi (raccourcis, "
    "détours, GPS), que mesure l'écart entre les deux colonnes (0010 D3). Ce n'est pas "
    "une erreur du modèle, dont le chiffre qui fait foi reste celui du backtest."
)
"""Ce qu'est l'effort effectif, et ses limites."""


def _name(path: Path) -> str:
    return path.name


@dataclass(frozen=True)
class _Shown:
    """Ce que la page montre en plus avec une courbe à l'origine ou d'une plage
    (OG-UI) : les lignes de la source suivies de la plage de support et de la part hors
    support, les avertissements, et, à l'origine, l'origine de la course (``None`` sur
    une plage). Mise en forme seule : tout vient de la bibliothèque."""

    lines: tuple[str, ...]
    warnings: tuple[str, ...]
    course: CourseOrigin | None


def _origin_caption(course: CourseOrigin) -> str:
    """La légende d'une courbe à l'origine, bornée ou non (OG-UI, F1)."""
    when = (
        "aujourd'hui : la sortie est datée au-delà d'aujourd'hui + 7 jours"
        if course.bounded
        else "7 jours avant la sortie"
    )
    return (
        f"Courbe à l'origine du {course.origin_day:%d/%m/%Y} (00:00 à Paris, {when}) : "
        "la sortie n'est pas dans sa fenêtre, l'écart est une prévision hors "
        "échantillon."
    )


def _followed_chart(
    spans: Sequence[tuple[float, float]], profile: RouteProfile
) -> dict[str, Any]:
    """Les segments admis, en bandes, sous le profil du préparé."""
    return {
        "layer": [
            {
                "data": {"values": [{"début (m)": a, "fin (m)": b} for a, b in spans]},
                "mark": {"type": "rect", "opacity": 0.2},
                "encoding": {
                    "x": {
                        **DISTANCE_AXIS,
                        "field": "début (m)",
                        "title": "distance (m)",
                    },
                    "x2": {"field": "fin (m)"},
                },
            },
            {
                "data": {
                    "values": [
                        {"distance (m)": d, "altitude (m)": z}
                        for d, z in zip(
                            profile.distance_m, profile.elevation_m, strict=True
                        )
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
        ]
    }


def _effort_cells(effort: ScenarioEffort | None) -> tuple[str, str]:
    """Le temps prévu et l'effort d'un scénario ; ``—`` pour un scénario absent ou un
    temps indisponible, le motif pour un effort indisponible."""
    if effort is None:
        return UNDEFINED, UNDEFINED
    projected = UNDEFINED
    if effort.projected_s is not None:
        projected = format_duration(effort.projected_s)
    if effort.effective_effort is not None:
        return projected, f"{effort.effective_effort:.2f}"
    assert effort.unavailability is not None  # contrat de ScenarioEffort
    return projected, METRIC_UNAVAILABILITY_LABELS[effort.unavailability]


def _effort_table(rows: Sequence[EffortRow]) -> list[dict[str, str]]:
    """Prévu contre réalisé, une ligne par horloge du rapport."""
    table = []
    for row in rows:
        usage_projected, usage_effort = _effort_cells(row.usage)
        control_projected, control_effort = _effort_cells(row.control)
        table.append(
            {
                "horloge": clock_label(row.clock),
                "temps réel": format_duration(row.observed_s),
                "prévu sur ton préparé": usage_projected,
                "effort sur ton préparé": usage_effort,
                "prévu sur le chemin suivi": control_projected,
                "effort sur le chemin suivi": control_effort,
            }
        )
    return table


def _gap_chart(found: Gaps) -> dict[str, Any]:
    """L'écart cumulé sous l'écoulé, en minutes, de l'origine aux points du préfixe.
    Une seule couche : dans un ``"layer"``, les données restent dans la
    spécification."""
    values = [{"distance (m)": found.origin_m, "écart cumulé (min)": 0.0}]
    for row in found.rows:
        elapsed_s = row.errors_s[0]
        if elapsed_s is not None:
            values.append(
                {"distance (m)": row.distance_m, "écart cumulé (min)": elapsed_s / 60}
            )
    return {
        "layer": [
            {
                "data": {"values": values},
                "mark": {"type": "line", "point": True},
                "encoding": {
                    "x": DISTANCE_AXIS,
                    "y": {"field": "écart cumulé (min)", "type": "quantitative"},
                },
            }
        ]
    }


def _gap_table(found: Gaps, clocks: Sequence[Clock]) -> list[dict[str, str]]:
    """Les écarts cumulés, une ligne par point du préfixe, une colonne par horloge."""
    return [
        {
            "point": row.name,
            "distance (m)": format_count(row.distance_m),
            **{
                clock_label(clock): UNDEFINED
                if error_s is None
                else format_signed_duration(error_s)
                for clock, error_s in zip(clocks, row.errors_s, strict=True)
            },
        }
        for row in found.rows
    ]


def _show(match: OutingMatch, check: OutingCheck, shown: _Shown | None) -> None:
    """Le résultat gardé : points 7 à 12 du § 6.5 du brief M5-2 ; avec une courbe à
    l'origine ou d'une plage (OG-UI), sa légende, ses lignes et ses avertissements."""
    curve = match.curve
    assert curve is not None  # check_outing exige la courbe
    if check.in_curve_window:
        estimation = curve.curve.estimation
        st.warning(
            "Sortie dans la période d'estimation de la courbe "
            f"({estimation.date_from:%d/%m/%Y} – {estimation.date_to:%d/%m/%Y}) : "
            "l'écart y est optimiste."
        )
    st.caption(
        f"Contrôle de la sortie du {check.day:%d/%m/%Y} (jour à Paris du premier "
        "instant de la trace) par v0 brut, à l'effort 1."
    )
    if shown is not None:
        if shown.course is not None:
            st.caption(_origin_caption(shown.course))
        st.code("\n".join(shown.lines), language=None)
        for warning in shown.warnings:
            st.warning(f"Avertissement : {warning}")
        if shown.course is not None:
            st.markdown(WINDOW_LINK)

    st.subheader("Le tracé suivi")
    followed = followed_route(match.result)
    st.write(
        f"Partie comparée : {format_share(followed.admitted_share)} du préparé "
        f"({format_count(followed.admitted_m)} m sur "
        f"{format_count(followed.reference_length_m)} m)."
    )
    st.write(
        "Points de score : "
        + ", ".join(
            f"{POINT_STATUS_LABELS[status]} {count}"
            for status, count in followed.point_counts
        )
        + "."
    )
    st.vega_lite_chart(
        spec=_followed_chart(admitted_spans(match.result), match.profile),
        width="stretch",
    )
    if followed.admitted_m == 0:
        st.info("La trace ne suit aucune partie comparable du préparé.")
        return
    st.write(
        f"Préfixe comparable jusqu'à {format_count(followed.prefix_end_m)} m : les "
        "écarts aux points s'arrêtent là."
    )

    st.subheader("Prévu contre réalisé")
    st.dataframe(
        _effort_table(effort_rows(check.scores, check.clocks)), hide_index=True
    )
    st.caption(CLOCK_LEGEND)
    st.caption(EFFORT_LIMITS)

    found = gaps(check.scores, match.passages, check.clocks)
    if found is not None and found.rows:
        st.subheader("Écart cumulé, prévu − réel")
        st.vega_lite_chart(spec=_gap_chart(found), width="stretch")
        st.dataframe(_gap_table(found, check.clocks), hide_index=True)
        st.write(
            "Plus grand écart, en valeur absolue : "
            + ", ".join(
                f"{clock_label(clock)} "
                + (UNDEFINED if max_abs_s is None else format_duration(max_abs_s))
                for clock, max_abs_s in zip(check.clocks, found.max_abs_s, strict=True)
            )
            + "."
        )
    st.caption("Le détail (régimes, enveloppes, épisodes) : mperf match --curve.")


def outing_page() -> None:
    """La page « sortie »."""
    st.title("Sortie")
    data = data_folder()
    if data is None:
        return
    file_adder(data)
    routes = list_files(data, FileKind.ROUTE)
    if not routes:
        st.info("Aucun préparé dans routes/ : ajoute un GPX (barre latérale).")
        return
    traces = list_files(data, FileKind.OUTING)
    if not traces:
        st.info("Aucune trace dans sorties/ : ajoute un GPX horodaté (barre latérale).")
        return
    curves = list_curves(data)
    today = paris_today()

    with st.sidebar:
        route = st.selectbox("Préparé", routes, format_func=_name, key="sortie.prepare")
        trace = st.selectbox("Trace", traces, format_func=_name, key="sortie.trace")
        source = curve_source_inputs("sortie.", curves, today, with_day=False)
        clicked = st.button("Comparer", key="sortie.comparer")

    if isinstance(source, FileSource) and source.path is None:
        st.info("Aucune courbe (CSV et son .meta.json) dans reference/.")
        return

    chosen = (route, trace, source)
    # Le calcul au clic seulement ; le résultat est gardé pour les relances suivantes.
    if clicked:
        st.session_state.pop(RESULT_KEY, None)
        shown: _Shown | None = None
        try:
            curve: Path | CurveBytes
            lines: tuple[str, ...] = ()
            course: CourseOrigin | None = None
            history: OriginHistory | None = None
            if isinstance(source, OriginSource):
                # La trace d'abord : son jour donne l'origine (source.day n'est pas lu).
                day = outing_day(trace)
                found = cached_origin_curve(data, day, today, source.window)
                lines = origin_curve_lines(found)
                course = found.course
                history = found.result.history
                if found.curve is None:
                    st.code("\n".join(lines), language=None)
                    st.info(
                        f"Aucune courbe à l'origine : {found.result.absence_reason}"
                    )
                    return
                curve = found.curve
            elif isinstance(source, FileSource):
                assert source.path is not None  # contrôlé avant le clic
                curve = source.path
            else:
                ranged = cached_range_curve(data, source.date_from, source.date_to)
                lines = range_curve_lines(ranged)
                if ranged.curve is None:
                    st.code("\n".join(lines), language=None)
                    st.info(f"Aucune courbe sur la plage : {ranged.absence_reason}")
                    return
                curve = ranged.curve
            match = match_outing(route, trace, curve, {})
            check = check_outing(match)
            if not isinstance(source, FileSource):
                share = outing_support_share(match)
                shown = _Shown(
                    (*lines, *outing_support_lines(match, share)),
                    curve_warnings(history, share),
                    course,
                )
        except (
            GpxError,
            ProfileError,
            TraceError,
            CurveError,
            ContractError,
            InterimError,
            OSError,
        ) as error:
            st.error(str(error))
            return
        st.session_state[RESULT_KEY] = (chosen, match, check, shown)

    kept = st.session_state.get(RESULT_KEY)
    if kept is None or kept[0] != chosen:
        st.info("Choisis un préparé, une trace et une courbe, puis « Comparer ».")
        return
    _, match, check, shown = kept
    _show(match, check, shown)
