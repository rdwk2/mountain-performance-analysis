"""Le rendu de la figure de Q1 en HTML (AN1-2c, ``docs/decisions/0015``) : le seul
module du projet qui importe plotly (extra ``analyse``, ``docs/decisions/0011``).

Une page autonome, plotly.js inclus une fois, deux figures : la vue principale, puis
la vue sans les montées instables, chacune sous son titre. Dans chacune, une rangée
par panneau, une colonne par strate de pente ; x, le départ local de l'activité, sur
un axe de dates dans chaque facette, même sans point, même étendue partout (la période
des données ; un point au bord est dessiné entier) ; y, la VAM en m/h (conversion à
l'affichage, titre « VAM (m/h) » à gauche de chaque rangée), en échelle
logarithmique, même étendue pour les facettes d'un panneau et pour les deux vues,
propre à chaque panneau ; un panneau sans point n'a ni graduation ni grille. La
couleur dit la strate d'altitude (la légende, sous son titre, nomme chaque strate une
fois et la cache, d'un clic, dans toutes les facettes), la taille ``Σ M_θc`` (une
seule échelle pour les deux vues), le symbole la stabilité du point (plein : stable ;
creux : instable ; vue principale seulement). Une facette sous le minimum d'activités
reste vide, avec sa mention au centre, sans flèche, comme une facette dont aucun point
n'a un résumé positif ; une facette sans point reste vide, sans mention ; un trait
pointillé marque chaque changement d'appareil. Au survol, et seulement le texte du
point : la date, la VAM, l'enveloppe des horloges, le nombre de montées, ``Σ G_M`` et
``Σ M``, la stabilité. Ni courbe ajustée ni lissage.

Le rendu est déterministe : les identifiants des figures sont fixés, et la même figure
donne les mêmes octets.
"""

from __future__ import annotations

import html
import math
from typing import Any

import plotly.graph_objects as go
import plotly.io as pio
from plotly.offline import get_plotlyjs
from plotly.subplots import make_subplots

from mountain_perf.analyse.q1 import (
    ALTITUDE_STRATA,
    FACET_STRATA,
    Q1_PANELS,
    FigurePoint,
    PointStatus,
    Q1Figure,
    View,
)
from mountain_perf.schemas.processed import (
    AltitudeStratum,
    ClimbRegime,
    GradeStratum,
)

PANEL_TITLES: dict[ClimbRegime, str] = {
    ClimbRegime.LONG_CLIMB: "(a) montées longues",
    ClimbRegime.SHORT_CLIMB: "(b) côtes",
    ClimbRegime.SKI_TOURING: "(c) ski de randonnée",
}
STRATUM_TITLES: dict[GradeStratum, str] = {
    GradeStratum.MODERATE: "pente modérée",
    GradeStratum.STEEP: "pente raide",
    GradeStratum.VERY_STEEP: "pente très raide",
}
ALTITUDE_TITLES: dict[AltitudeStratum, str] = {
    AltitudeStratum.LOW: "altitude basse",
    AltitudeStratum.MID: "altitude moyenne",
    AltitudeStratum.HIGH: "altitude haute",
}
ALTITUDE_COLORS: dict[AltitudeStratum, str] = {
    AltitudeStratum.LOW: "#1b9e77",
    AltitudeStratum.MID: "#d95f02",
    AltitudeStratum.HIGH: "#7570b3",
}
VIEW_TITLES: dict[View, str] = {
    View.MAIN: "Vue principale : les montées non marquées",
    View.STABLE_ONLY: "Vue de sensibilité : les montées stables seulement",
}
DIV_IDS: dict[View, str] = {View.MAIN: "q1-principale", View.STABLE_ONLY: "q1-stables"}
_M_PER_H = 3600.0
_AXIS_MARGIN = 1.15
_MIN_SIZE, _SIZE_SPAN = 6.0, 12.0
_LEGEND_SIZE = 10.0


def _local(point: FigurePoint) -> str:
    return point.start_time.replace(tzinfo=None).isoformat()


def _speed_m_per_h(point: FigurePoint) -> float:
    """La VAM d'un point montré, en m/h (un point montré a un résumé positif)."""
    assert point.vertical_speed_ms is not None
    return point.vertical_speed_ms * _M_PER_H


def _hover(point: FigurePoint) -> str:
    def speed(value: float | None) -> str:
        return "—" if value is None else f"{value * _M_PER_H:.0f}"

    lines = [
        point.start_time.strftime("%Y-%m-%d %H:%M"),
        f"VAM {speed(point.vertical_speed_ms)} m/h",
        f"enveloppe des horloges [{speed(point.vertical_speed_low_ms)} ;"
        f" {speed(point.vertical_speed_high_ms)}] m/h",
        f"{point.climb_count} montée(s), ΣG_M {point.moving_gain_m:.0f} m,"
        f" ΣM {point.moving_s / 60:.1f} min",
    ]
    s = point.stability
    if s is not None:
        deviation = (
            "—"
            if s.max_relative_deviation is None
            else f"{s.max_relative_deviation:.1%}"
        )
        lines.append(
            f"{'stable' if s.stable else 'instable'} : retrouvé dans"
            f" {s.found_fraction:.0%} des variantes, écart max {deviation}"
        )
    return "<br>".join(lines)


def _facet_note(facet: list[FigurePoint], minimum: int) -> str | None:
    """La mention d'une facette qui a des points mais n'en montre aucun : « moins de N
    activités » si elle est sous le minimum, « aucun résumé positif » si tous ses
    points ont un résumé non positif ; ``None`` pour une facette qui montre ses points,
    ou qui n'en a pas (elle reste vide)."""
    statuses = {p.status for p in facet}
    if not facet or PointStatus.SHOWN in statuses:
        return None
    if PointStatus.SMALL_FACET in statuses:
        return f"moins de {minimum} activités"
    return "aucun résumé positif"


def _size(point: FigurePoint, largest_s: float) -> float:
    if largest_s <= 0:
        return _MIN_SIZE
    return _MIN_SIZE + _SIZE_SPAN * math.sqrt(point.moving_s / largest_s)


def _figure(figure: Q1Figure, view: View) -> Any:
    rows, cols = len(Q1_PANELS), len(FACET_STRATA)
    titles = [
        f"{PANEL_TITLES[panel]}, {STRATUM_TITLES[stratum]}"
        for panel in Q1_PANELS
        for stratum in FACET_STRATA
    ]
    fig = make_subplots(
        rows=rows,
        cols=cols,
        shared_xaxes=True,
        subplot_titles=titles,
        vertical_spacing=0.08,
        horizontal_spacing=0.05,
    )
    points = [p for p in figure.points if p.view is view]
    # Une seule échelle de taille pour les deux vues, comme l'axe de VAM : le plus
    # grand Σ M des points montrés de la figure.
    largest = max(
        (p.moving_s for p in figure.points if p.status is PointStatus.SHOWN),
        default=0.0,
    )
    minimum = int(figure.parameters["min_facet_activities"])
    for r, panel in enumerate(Q1_PANELS, start=1):
        for c, stratum in enumerate(FACET_STRATA, start=1):
            # Une trace vide dans chaque facette : plotly.js ne dessine pas les axes
            # d'une facette sans trace, ni la mention qui s'y place.
            fig.add_trace(
                go.Scatter(x=[], y=[], showlegend=False, hoverinfo="skip"),
                row=r,
                col=c,
            )
            facet = [
                p for p in points if p.panel is panel and p.grade_stratum is stratum
            ]
            shown = [p for p in facet if p.status is PointStatus.SHOWN]
            note = _facet_note(facet, minimum)
            if note is not None:
                fig.add_annotation(
                    text=note,
                    showarrow=False,
                    xref="x domain",
                    yref="y domain",
                    x=0.5,
                    y=0.5,
                    row=r,
                    col=c,
                )
            for altitude in ALTITUDE_STRATA:
                group = [p for p in shown if p.altitude_stratum is altitude]
                if not group:
                    continue
                symbols = [
                    "circle-open"
                    if p.stability is not None and not p.stability.stable
                    else "circle"
                    for p in group
                ]
                fig.add_trace(
                    go.Scatter(
                        x=[_local(p) for p in group],
                        y=[_speed_m_per_h(p) for p in group],
                        mode="markers",
                        marker={
                            "color": ALTITUDE_COLORS[altitude],
                            "size": [_size(p, largest) for p in group],
                            "symbol": symbols,
                            "line": {"width": 1.5, "color": ALTITUDE_COLORS[altitude]},
                        },
                        name=ALTITUDE_TITLES[altitude],
                        legendgroup=altitude.value,
                        showlegend=False,
                        text=[_hover(p) for p in group],
                        hovertemplate="%{text}<extra></extra>",
                        cliponaxis=False,
                    ),
                    row=r,
                    col=c,
                )
        span = dict(figure.vertical_speed_range_ms)[panel]
        if span is not None:
            low = math.log10(span[0] * _M_PER_H / _AXIS_MARGIN)
            high = math.log10(span[1] * _M_PER_H * _AXIS_MARGIN)
            fig.update_yaxes(type="log", range=[low, high], row=r)
        else:
            fig.update_yaxes(type="log", showticklabels=False, showgrid=False, row=r)
        fig.update_yaxes(title_text="VAM (m/h)", row=r, col=1)
    # La légende : une entrée par strate d'altitude montrée dans la vue, au symbole
    # plein (plotly.js montrerait le symbole du premier point de la strate, creux s'il
    # est instable) ; son groupe cache la strate dans toutes les facettes.
    drawn = {p.altitude_stratum for p in points if p.status is PointStatus.SHOWN}
    for altitude in ALTITUDE_STRATA:
        if altitude in drawn:
            fig.add_trace(
                go.Scatter(
                    x=[None],
                    y=[None],
                    mode="markers",
                    marker={
                        "color": ALTITUDE_COLORS[altitude],
                        "symbol": "circle",
                        "size": _LEGEND_SIZE,
                    },
                    name=ALTITUDE_TITLES[altitude],
                    legendgroup=altitude.value,
                    showlegend=True,
                    hoverinfo="skip",
                ),
                row=1,
                col=1,
            )
    # Un axe de dates partout : une facette sans point le devinerait numérique, ses
    # graduations et les traits des changements d'appareil n'y auraient plus de sens.
    fig.update_xaxes(type="date")
    if figure.period is not None:
        start, end = (
            figure.period[0].replace(tzinfo=None).isoformat(),
            figure.period[1].replace(tzinfo=None).isoformat(),
        )
        fig.update_xaxes(range=[start, end])
    for change in figure.device_changes:
        fig.add_vline(
            x=change.start_time.replace(tzinfo=None).isoformat(),
            line_dash="dot",
            line_color="#888888",
            line_width=1,
        )
    fig.update_layout(
        title_text=VIEW_TITLES[view],
        height=300 * rows,
        template="plotly_white",
        legend_title_text="Strate d'altitude",
    )
    return fig


def figure_html(figure: Q1Figure) -> str:
    """La page HTML de ``figure`` : un en-tête, puis les deux vues."""
    period = (
        "—"
        if figure.period is None
        else f"{figure.period[0].date().isoformat()} → "
        f"{figure.period[1].date().isoformat()}"
    )
    header = (
        "<h1>Q1 — la vitesse ascensionnelle, par régime</h1>"
        "<p>Figure descriptive, exploratoire : ni tendance ni intervalle d'inférence ; "
        "l'enveloppe des horloges, au survol, n'est pas un intervalle. Un point : une "
        "activité, dans un panneau, une strate de pente (la colonne) et une strate "
        "d'altitude (la couleur) ; sa VAM est le gain pris en mouvement divisé par le "
        "temps en mouvement, sommés sur ses montées ; sa taille croît avec ce temps en "
        "mouvement, sur une même échelle pour les deux vues. Symbole creux, dans la "
        "vue principale seulement : point instable sous les variantes de la "
        "définition. Trait pointillé : changement d'appareil.</p>"
        f"<p>Période : {html.escape(period)}. Empreinte d'interim/ : "
        f"{html.escape(figure.provenance.interim_sha256)}.</p>"
    )
    parts = [
        pio.to_html(
            _figure(figure, view),
            full_html=False,
            include_plotlyjs=False,
            div_id=DIV_IDS[view],
            config={"displaylogo": False},
        )
        for view in View
    ]
    return (
        '<!DOCTYPE html>\n<html lang="fr">\n<head>\n<meta charset="utf-8">\n'
        "<title>Q1 — vitesse ascensionnelle</title>\n"
        f'<script type="text/javascript">{get_plotlyjs()}</script>\n'
        "</head>\n<body>\n"
        f"{header}\n" + "\n".join(parts) + "\n</body>\n</html>\n"
    )
