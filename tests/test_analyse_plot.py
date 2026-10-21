"""Le rendu de la figure de Q1 (``mountain_perf.analyse.plot``, AN1-2c,
``docs/decisions/0015``) : une page autonome, déterministe, deux vues ; dans chaque vue,
les facettes, les points montrés, leurs symboles, les axes et les changements
d'appareil. Sautés sans plotly (extra ``analyse``)."""

from __future__ import annotations

import dataclasses
import math
import re
from typing import Any

import pytest

pytest.importorskip("plotly")

from fixtures.figure import (
    activity,
    climb,
    same_in_every_variant,
    start,
    tables_of,
)
from mountain_perf.analyse import plot
from mountain_perf.analyse.plot import DIV_IDS, figure_html
from mountain_perf.analyse.q1 import (
    PointStatus,
    Q1Figure,
    View,
    q1_figure,
)
from mountain_perf.schemas.processed import (
    AltitudeStratum,
    ClimbRegime,
    GradeStratum,
)


@pytest.fixture(scope="module")
def figure() -> Q1Figure:
    """Six activités : cinq montées longues modérées (une facette montrée, la
    première instable, les autres stables), dont une en altitude moyenne ; une montée
    raide (facette cachée) ; un changement d'appareil à la quatrième."""
    activities = [
        activity(f"w{i}", start(i), device_product=1 if i < 3 else 2) for i in range(6)
    ]
    climbs = [
        climb(
            f"w{i}",
            start(i),
            600,
            2400,
            300 + 30 * i,
            1800,
            altitude=AltitudeStratum.MID if i == 4 else AltitudeStratum.LOW,
        )
        for i in range(5)
    ]
    climbs.append(climb("w5", start(5), 600, 1200, 150, 600, grade=GradeStratum.STEEP))
    variants = [r for r in same_in_every_variant(climbs) if r.activity_ref != "w0"]
    return q1_figure(tables_of(activities, climbs, variants))


@pytest.fixture(scope="module")
def page(figure: Q1Figure) -> str:
    return figure_html(figure)


def _markers(fig: Any) -> list[Any]:
    """Les traces des points, sans les entrées de la légende."""
    return [
        trace for trace in fig.data if trace.mode == "markers" and not trace.showlegend
    ]


def _legend(fig: Any) -> list[Any]:
    """Les entrées de la légende."""
    return [trace for trace in fig.data if trace.showlegend]


def _axis(fig: Any, letter: str, n: int) -> Any:
    """L'axe ``letter`` (``x`` ou ``y``) de la facette ``n`` (1 à 9, rangée par
    rangée)."""
    return fig.layout[f"{letter}axis{'' if n == 1 else n}"]


MARGIN = 1.15
"""La marge de l'axe de VAM : 15 % de chaque côté (décision de rdw)."""

HEAD = (
    '<!DOCTYPE html>\n<html lang="fr">\n<head>\n<meta charset="utf-8">\n'
    "<title>Q1 — vitesse ascensionnelle</title>\n"
    '<script type="text/javascript">'
)
HEADER = (
    "<h1>Q1 — la vitesse ascensionnelle, par régime</h1>"
    "<p>Figure descriptive, exploratoire : ni tendance ni intervalle d'inférence ; "
    "l'enveloppe des horloges, au survol, n'est pas un intervalle. Un point : une "
    "activité, dans un panneau, une strate de pente (la colonne) et une strate "
    "d'altitude (la couleur) ; sa VAM est le gain pris en mouvement divisé par le "
    "temps en mouvement, sommés sur ses montées ; sa taille croît avec ce temps en "
    "mouvement, sur une même échelle pour les deux vues. Symbole creux, dans la "
    "vue principale seulement : point instable sous les variantes de la "
    "définition. Trait pointillé : changement d'appareil.</p>"
)


def _body(page: str) -> list[str]:
    """Les lignes du corps de la page, après son en-tête HTML et plotly.js."""
    assert page.startswith(HEAD)
    script, body = page.removeprefix(HEAD).split("</script>\n</head>\n<body>\n")
    assert script == vars(plot)["get_plotlyjs"]()
    assert body.endswith("\n</body>\n</html>\n")
    return body.removesuffix("\n</body>\n</html>\n").split("\n")


# --- la page --------------------------------------------------------------------


def test_the_same_figure_gives_the_same_bytes(figure: Q1Figure, page: str) -> None:
    assert figure_html(figure) == page


def test_plotly_js_is_embedded_once_and_nothing_is_fetched(page: str) -> None:
    """plotly.js, une fois, dans l'en-tête (son bandeau de licence, une fois) ;
    aucun script chargé d'ailleurs. Le test n'importe pas plotly (TID251) : il lit
    la fonction que ``plot.py`` en importe."""
    assert page.count(vars(plot)["get_plotlyjs"]()) == 1
    assert len(re.findall(r"\* plotly\.js v\d+\.\d+\.\d+", page)) == 1
    assert page.index("plotly.js v") < page.index("</head>")
    assert "<script src=" not in page


def test_the_two_views_in_order(page: str) -> None:
    ids = re.findall(r'<div id="(q1-[a-z]+)"', page)
    assert ids == [DIV_IDS[View.MAIN], DIV_IDS[View.STABLE_ONLY]]
    assert DIV_IDS == {View.MAIN: "q1-principale", View.STABLE_ONLY: "q1-stables"}


def test_the_page_skeleton(page: str) -> None:
    """L'en-tête HTML (langue, encodage, titre), plotly.js, puis, dans le corps,
    l'en-tête de la figure et une ligne par vue, dans l'ordre : chacune une division
    sans page entière ni plotly.js, sans le logo de plotly."""
    header, main, stable = _body(page)
    assert header.startswith("<h1>")
    for line, view in ((main, View.MAIN), (stable, View.STABLE_ONLY)):
        assert line.startswith('<div style="height:'), view
        assert line.endswith("</div>"), view
        assert f'<div id="{DIV_IDS[view]}" class="plotly-graph-div"' in line
        assert "plotly.js v" not in line
        assert '"displaylogo": false' in line


def test_the_header(figure: Q1Figure, page: str) -> None:
    """L'en-tête de la figure, entier : ce qu'elle est et n'est pas, ce qu'est un
    point, puis la période et l'empreinte d'interim/."""
    assert _body(page)[0] == (
        HEADER + "<p>Période : 2024-03-04 → 2024-04-08. Empreinte d'interim/ : "
        f"{figure.provenance.interim_sha256}.</p>"
    )


def test_the_header_without_activity() -> None:
    empty = q1_figure(tables_of([], []))
    assert _body(figure_html(empty))[0] == (
        HEADER + "<p>Période : —. Empreinte d'interim/ : "
        f"{empty.provenance.interim_sha256}.</p>"
    )


# --- une vue --------------------------------------------------------------------


def test_nine_facets_with_their_titles(figure: Q1Figure) -> None:
    fig = plot._figure(figure, View.MAIN)
    titles = [a.text for a in fig.layout.annotations if a.text.startswith("(")]
    assert titles == [
        f"{panel}, {stratum}"
        for panel in ("(a) montées longues", "(b) côtes", "(c) ski de randonnée")
        for stratum in ("pente modérée", "pente raide", "pente très raide")
    ]
    empty = [t for t in fig.data if t.mode != "markers"]
    assert len(empty) == 9


def test_only_shown_points_are_drawn(figure: Q1Figure) -> None:
    fig = plot._figure(figure, View.MAIN)
    drawn = sum(len(trace.x) for trace in _markers(fig))
    shown = [
        p
        for p in figure.points
        if p.view is View.MAIN and p.status is PointStatus.SHOWN
    ]
    assert drawn == len(shown) == 5


@pytest.mark.parametrize("view", list(View))
def test_a_hidden_facet_says_so(figure: Q1Figure, view: View) -> None:
    """Même dessin dans les deux vues : la facette raide des montées longues,
    sous le minimum, porte sa mention au centre, sans flèche."""
    fig = plot._figure(figure, view)
    notes = [a for a in fig.layout.annotations if a.text == "moins de 5 activités"]
    assert len(notes) == 1
    assert (notes[0].xref, notes[0].yref) == ("x2 domain", "y2 domain")
    assert (notes[0].x, notes[0].y, notes[0].showarrow) == (0.5, 0.5, False)


def test_the_markers(figure: Q1Figure) -> None:
    """Couleur et légende par strate d'altitude ; VAM en m/h ; symbole creux pour le
    point instable ; des points de même ``Σ M`` ont la même taille (la croissance de
    la taille : le test de la racine, plus bas)."""
    fig = plot._figure(figure, View.MAIN)
    low, mid = _markers(fig)
    assert (low.name, mid.name) == ("altitude basse", "altitude moyenne")
    assert low.marker.color == plot.ALTITUDE_COLORS[AltitudeStratum.LOW]
    assert list(low.y) == pytest.approx(
        [(300 + 30 * i) / 1800 * 3600 for i in range(4)]
    )
    assert list(low.marker.symbol) == ["circle-open", "circle", "circle", "circle"]
    assert list(mid.marker.symbol) == ["circle"]
    assert set(low.marker.size) == {18.0}
    assert low.x[0] == "2024-03-04T09:00:00"
    assert "instable : retrouvé dans 0% des variantes" in low.text[0]
    assert low.hovertemplate == "%{text}<extra></extra>"
    assert low.cliponaxis is False


def test_the_stable_only_view_has_no_open_symbol(figure: Q1Figure) -> None:
    fig = plot._figure(figure, View.STABLE_ONLY)
    symbols = [s for trace in _markers(fig) for s in trace.marker.symbol]
    assert symbols == ["circle"] * 5


def test_the_axes(figure: Q1Figure) -> None:
    """y logarithmique, même étendue sur les trois facettes d'un panneau, tirée des
    points montrés avec une marge ; un panneau sans point : pas de graduation ; x,
    la période."""
    fig = plot._figure(figure, View.MAIN)
    ranges = dict(figure.vertical_speed_range_ms)
    span = ranges[ClimbRegime.LONG_CLIMB]
    assert span is not None
    expected = [
        math.log10(span[0] * 3600 / MARGIN),
        math.log10(span[1] * 3600 * MARGIN),
    ]
    for name in ("yaxis", "yaxis2", "yaxis3"):
        axis = fig.layout[name]
        assert axis.type == "log"
        assert list(axis.range) == pytest.approx(expected)
    for name in ("yaxis4", "yaxis9"):
        assert fig.layout[name].type == "log"
        assert fig.layout[name].showticklabels is False
    assert figure.period is not None
    assert list(fig.layout.xaxis.range) == [
        figure.period[0].replace(tzinfo=None).isoformat(),
        figure.period[1].replace(tzinfo=None).isoformat(),
    ]


@pytest.mark.parametrize("view", list(View))
def test_a_dotted_line_at_each_device_change(figure: Q1Figure, view: View) -> None:
    """Même dessin dans les deux vues : un trait pointillé au changement
    d'appareil, dans chacune des neuf facettes."""
    fig = plot._figure(figure, view)
    lines = [s for s in fig.layout.shapes if s.type == "line"]
    assert len(figure.device_changes) == 1
    assert len(lines) == 9
    assert {s.x0 for s in lines} == {"2024-03-25T09:00:00"}
    assert {s.line.dash for s in lines} == {"dot"}
    assert sorted(s.xref for s in lines) == ["x"] + [f"x{n}" for n in range(2, 10)]


def test_no_fitted_curve(figure: Q1Figure) -> None:
    """Ni courbe ajustée ni lissage : aucune trace en lignes ; une trace sans mode n'a
    aucun point (plotly.js relie par défaut les points peu nombreux d'une trace sans
    mode)."""
    for view in View:
        fig = plot._figure(figure, view)
        assert all(trace.mode in (None, "markers") for trace in fig.data)
        assert all(not trace.x for trace in fig.data if trace.mode is None)


# --- les relectures du prototype (AN1-2c) ----------------------------------------


def test_the_size_grows_as_the_square_root_on_one_scale_for_both_views() -> None:
    """La taille croît comme la racine de ``Σ M``, sur une seule échelle pour les deux
    vues : le plus grand ``Σ M`` des points montrés (``w5``, instable, absent de la
    vue de sensibilité) fixe l'échelle des deux ; un point caché plus long (la montée
    raide de ``w0``, seule dans sa facette) n'y entre pas."""
    activities = [activity(f"w{i}", start(i)) for i in range(6)]
    times = [450.0, 1800.0, 1800.0, 1800.0, 1800.0, 3600.0]
    climbs = [
        climb(f"w{i}", start(i), 600, 600 + m, 300, m, stable=i < 5)
        for i, m in enumerate(times)
    ]
    climbs.append(
        climb("w0", start(0), 9000, 16200, 300, 7200, grade=GradeStratum.STEEP)
    )
    figure = q1_figure(tables_of(activities, climbs))

    def size(m: float) -> float:
        return 6.0 + 12.0 * math.sqrt(m / 3600.0)

    (main,) = _markers(plot._figure(figure, View.MAIN))
    (stable,) = _markers(plot._figure(figure, View.STABLE_ONLY))
    assert list(main.marker.size) == pytest.approx([size(m) for m in times])
    assert list(stable.marker.size) == pytest.approx([size(m) for m in times[:5]])


def test_the_hover_text() -> None:
    """Le texte entier du survol d'un point à l'enveloppe ouverte, aux conventions
    toutes différentes : la date et l'heure, la VAM de θc, l'enveloppe, le nombre de
    montées, ``Σ G_M`` puis ``Σ M``, la stabilité."""
    c = climb(
        "a",
        start(0),
        100,
        1300,
        300,
        1000,
        moving_gain_m_by_convention=(280.0, 300.0, 300.0, 300.0, 310.0),
        moving_s_by_convention=(1100.0, 1200.0, 1000.0, 1000.0, 950.0),
    )
    (point,) = [
        p
        for p in q1_figure(tables_of([activity("a", start(0))], [c])).points
        if p.view is View.MAIN
    ]
    assert plot._hover(point).split("<br>") == [
        "2024-03-04 09:00",
        "VAM 900 m/h",
        "enveloppe des horloges [900 ; 1175] m/h",
        "1 montée(s), ΣG_M 300 m, ΣM 20.0 min",
        "stable : retrouvé dans 100% des variantes, écart max 0.0%",
    ]


def test_a_facet_without_a_positive_summary_says_so() -> None:
    """Six activités, chacune au résumé négatif dans la même facette : la facette dit
    « aucun résumé positif », pas « moins de 5 activités » ; une facette sans point
    reste vide, sans mention."""
    activities = [activity(f"w{i}", start(i)) for i in range(6)]
    climbs = [
        dataclasses.replace(
            climb(f"w{i}", start(i), 600, 1200, 5, 600),
            moving_gain_m_by_convention=(-30.0,) * 5,
        )
        for i in range(6)
    ]
    fig = plot._figure(q1_figure(tables_of(activities, climbs)), View.MAIN)
    notes = [a.text for a in fig.layout.annotations if not a.text.startswith("(")]
    assert notes == ["aucun résumé positif"]


# --- le balayage par mutation du prototype v3 (AN1-2c) ---------------------------


def _two_facets() -> Q1Figure:
    """Dix activités : cinq montées longues modérées en altitude basse ; cinq raides,
    quatre en altitude basse et une en altitude haute, aucune en altitude moyenne."""
    activities = [activity(f"w{i}", start(i)) for i in range(10)]
    climbs = [climb(f"w{i}", start(i), 600, 2400, 300, 1800) for i in range(5)]
    climbs += [
        climb(
            f"w{i}",
            start(i),
            600,
            1200,
            150,
            600,
            grade=GradeStratum.STEEP,
            altitude=AltitudeStratum.HIGH if i == 9 else AltitudeStratum.LOW,
        )
        for i in range(5, 10)
    ]
    return q1_figure(tables_of(activities, climbs))


def test_a_facet_draws_each_altitude_it_has() -> None:
    """Une facette a des points en altitude basse et haute, aucun en altitude
    moyenne : les deux strates sont dessinées."""
    fig = plot._figure(_two_facets(), View.MAIN)
    steep = [t for t in _markers(fig) if t.xaxis == "x2"]
    assert [(t.name, len(t.x)) for t in steep] == [
        ("altitude basse", 4),
        ("altitude haute", 1),
    ]


def test_the_legend_names_each_altitude_once() -> None:
    """La légende, sous son titre, nomme chaque strate montrée une fois, au symbole
    plein, sans survol ; chaque trace d'une strate est de son groupe, qu'un clic sur
    la légende cache dans toutes les facettes."""
    fig = plot._figure(_two_facets(), View.MAIN)
    legend = _legend(fig)
    assert [t.name for t in legend] == ["altitude basse", "altitude haute"]
    assert [t.legendgroup for t in legend] == ["low", "high"]
    assert [t.marker.color for t in legend] == [
        plot.ALTITUDE_COLORS[AltitudeStratum.LOW],
        plot.ALTITUDE_COLORS[AltitudeStratum.HIGH],
    ]
    assert {t.marker.symbol for t in legend} == {"circle"}
    assert {t.hoverinfo for t in legend} == {"skip"}
    assert {(t.x, t.y) for t in legend} == {((None,), (None,))}
    assert [(t.name, t.legendgroup, t.showlegend) for t in _markers(fig)] == [
        ("altitude basse", "low", False),
        ("altitude basse", "low", False),
        ("altitude haute", "high", False),
    ]
    assert fig.layout.legend.title.text == "Strate d'altitude"


def test_the_legend_of_an_unstable_first_point_is_full(figure: Q1Figure) -> None:
    """Le premier point en altitude basse est instable (creux) : l'entrée de la
    légende reste pleine."""
    fig = plot._figure(figure, View.MAIN)
    assert _markers(fig)[0].marker.symbol[0] == "circle-open"
    assert [(t.name, t.marker.symbol) for t in _legend(fig)] == [
        ("altitude basse", "circle"),
        ("altitude moyenne", "circle"),
    ]


def test_the_legend_of_each_view_names_its_own_altitudes() -> None:
    """Une montée en altitude moyenne, instable, n'est que dans la vue principale :
    la légende de la vue de sensibilité ne la nomme pas."""
    activities = [activity(f"w{i}", start(i)) for i in range(6)]
    climbs = [climb(f"w{i}", start(i), 600, 2400, 300, 1800) for i in range(5)]
    climbs.append(
        climb(
            "w5",
            start(5),
            600,
            2400,
            300,
            1800,
            altitude=AltitudeStratum.MID,
            stable=False,
        )
    )
    figure = q1_figure(tables_of(activities, climbs))
    names = {
        view: [t.name for t in _legend(plot._figure(figure, view))] for view in View
    }
    assert names == {
        View.MAIN: ["altitude basse", "altitude moyenne"],
        View.STABLE_ONLY: ["altitude basse"],
    }


def test_each_panel_has_its_own_vertical_range() -> None:
    """Deux panneaux montrés à des VAM différentes, puis un panneau vide : chaque
    rangée garde l'étendue de son panneau, ses graduations et sa grille ; la rangée
    vide n'a ni étendue, ni graduation, ni grille."""
    activities = [activity(f"w{i}", start(i)) for i in range(5)]
    climbs = [climb(f"w{i}", start(i), 600, 2400, 300, 1800) for i in range(5)]
    climbs += [
        climb(f"w{i}", start(i), 3000, 3300, 60, 300, regime=ClimbRegime.SHORT_CLIMB)
        for i in range(5)
    ]
    figure = q1_figure(tables_of(activities, climbs))
    fig = plot._figure(figure, View.MAIN)
    ranges = dict(figure.vertical_speed_range_ms)
    assert ranges[ClimbRegime.LONG_CLIMB] != ranges[ClimbRegime.SHORT_CLIMB]
    for row, panel in enumerate((ClimbRegime.LONG_CLIMB, ClimbRegime.SHORT_CLIMB)):
        span = ranges[panel]
        assert span is not None
        expected = [
            math.log10(span[0] * 3600 / MARGIN),
            math.log10(span[1] * 3600 * MARGIN),
        ]
        for n in range(3 * row + 1, 3 * row + 4):
            axis = _axis(fig, "y", n)
            assert list(axis.range) == pytest.approx(expected), n
            assert axis.showticklabels is not False, n
            assert axis.showgrid is not False, n
    for n in (7, 8, 9):
        axis = _axis(fig, "y", n)
        assert (axis.range, axis.showticklabels, axis.showgrid) == (None, False, False)


def test_the_vertical_title_is_on_the_left_of_each_row(figure: Q1Figure) -> None:
    fig = plot._figure(figure, View.MAIN)
    titles = [_axis(fig, "y", n).title.text for n in range(1, 10)]
    assert titles == ["VAM (m/h)", None, None] * 3


def test_each_view_has_its_title(figure: Q1Figure) -> None:
    titles = [plot._figure(figure, view).layout.title.text for view in View]
    assert titles == [
        "Vue principale : les montées non marquées",
        "Vue de sensibilité : les montées stables seulement",
    ]


def test_every_horizontal_axis_is_a_date_axis(figure: Q1Figure) -> None:
    """Même une facette sans point a un axe de dates, à l'étendue de la période : ses
    graduations sont des dates, et le trait d'un changement d'appareil s'y place.
    Sans activité, les axes restent des axes de dates, sans étendue."""
    assert figure.period is not None
    expected = [moment.replace(tzinfo=None).isoformat() for moment in figure.period]
    for view in View:
        fig = plot._figure(figure, view)
        for n in range(1, 10):
            axis = _axis(fig, "x", n)
            assert (axis.type, list(axis.range)) == ("date", expected), (view, n)
        lines = [s for s in fig.layout.shapes if s.type == "line"]
        assert {s.xref for s in lines} == {"x", *(f"x{n}" for n in range(2, 10))}
    empty = plot._figure(q1_figure(tables_of([], [])), View.MAIN)
    for n in range(1, 10):
        assert (_axis(empty, "x", n).type, _axis(empty, "x", n).range) == ("date", None)


def test_the_hover_text_of_a_point_found_in_no_variant() -> None:
    """Un point qu'aucune variante ne retrouve : instable, sans écart, « — »."""
    c = climb("a", start(0), 100, 1300, 300, 1000)
    (point,) = [
        p
        for p in q1_figure(tables_of([activity("a", start(0))], [c], [])).points
        if p.view is View.MAIN
    ]
    assert plot._hover(point).split("<br>")[-1] == (
        "instable : retrouvé dans 0% des variantes, écart max —"
    )


def test_the_size_scale_under_a_second() -> None:
    """Le plus grand ``Σ M`` montré fait moins d'une seconde : l'échelle tient
    encore, et le plus grand point a la plus grande taille."""
    activities = [activity(f"w{i}", start(i)) for i in range(5)]
    times = [0.5, 0.25, 0.5, 0.5, 0.5]
    climbs = [climb(f"w{i}", start(i), 600, 601, m / 2, m) for i, m in enumerate(times)]
    (trace,) = _markers(
        plot._figure(q1_figure(tables_of(activities, climbs)), View.MAIN)
    )
    assert list(trace.marker.size) == pytest.approx(
        [6.0 + 12.0 * math.sqrt(m / 0.5) for m in times]
    )


# --- la relecture du paquet (AN1-2c) ----------------------------------------------


def _wider_in_the_stable_view() -> Q1Figure:
    """Cinq activités, une montée longue modérée chacune ; ``w0`` en a deux, une
    rapide et stable (900 m en 600 s), une lente et instable (100 m en 1800 s) :
    son point fait 1000 m en 2400 s dans la vue principale, 900 m en 600 s dans la
    vue de sensibilité, plus vite que tout point de la vue principale."""
    activities = [activity(f"w{i}", start(i)) for i in range(5)]
    climbs = [climb(f"w{i}", start(i), 600, 2400, 300, 1800) for i in range(1, 5)]
    climbs += [
        climb("w0", start(0), 600, 1200, 900, 600),
        climb("w0", start(0), 1300, 3100, 100, 1800, stable=False),
    ]
    return q1_figure(tables_of(activities, climbs))


def test_both_views_share_the_vertical_range_of_a_panel() -> None:
    """L'axe de VAM d'un panneau est le même dans les deux vues, tiré des points
    montrés des deux : le point le plus rapide n'est que dans la vue de
    sensibilité, et l'axe de la vue principale va jusqu'à lui."""
    figure = _wider_in_the_stable_view()
    expected = [
        math.log10(300 / 1800 * 3600 / MARGIN),
        math.log10(900 / 600 * 3600 * MARGIN),
    ]
    for view in View:
        fig = plot._figure(figure, view)
        for n in (1, 2, 3):
            axis = _axis(fig, "y", n)
            assert list(axis.range) == pytest.approx(expected), (view, n)


def test_a_mixed_hidden_facet_says_fewer_than_n() -> None:
    """Une facette sous le minimum a aussi un point au résumé non positif : trois
    de ses points sont positifs, elle dit « moins de 5 activités », pas « aucun
    résumé positif »."""
    activities = [activity(f"w{i}", start(i)) for i in range(4)]
    climbs = [climb(f"w{i}", start(i), 600, 2400, 300, 1800) for i in range(3)]
    climbs.append(
        dataclasses.replace(
            climb("w3", start(3), 600, 2400, 300, 1800),
            moving_gain_m_by_convention=(-50.0,) * 5,
        )
    )
    figure = q1_figure(tables_of(activities, climbs))
    statuses = {p.status for p in figure.points if p.view is View.MAIN}
    assert statuses == {PointStatus.SMALL_FACET, PointStatus.NON_POSITIVE}
    fig = plot._figure(figure, View.MAIN)
    notes = [a.text for a in fig.layout.annotations if not a.text.startswith("(")]
    assert notes == ["moins de 5 activités"]


# --- la passe 1 de la B (AN1-2c) --------------------------------------------------


def test_each_altitude_has_its_own_color_in_the_points_and_the_legend() -> None:
    """Les trois strates d'altitude montrées : chaque trace de points a la couleur de
    l'entrée de la légende qui porte son nom, et les trois couleurs diffèrent (la
    couleur dit la strate d'altitude)."""
    altitudes = [AltitudeStratum.LOW, AltitudeStratum.MID, AltitudeStratum.HIGH] * 2
    activities = [activity(f"w{i}", start(i)) for i in range(6)]
    climbs = [
        climb(f"w{i}", start(i), 600, 2400, 300, 1800, altitude=a)
        for i, a in enumerate(altitudes)
    ]
    fig = plot._figure(q1_figure(tables_of(activities, climbs)), View.MAIN)
    legend = {t.name: t.marker.color for t in _legend(fig)}
    assert list(legend) == ["altitude basse", "altitude moyenne", "altitude haute"]
    assert len(set(legend.values())) == 3
    markers = _markers(fig)
    assert [t.name for t in markers] == list(legend)
    assert [t.marker.color for t in markers] == list(legend.values())


def test_a_dotted_line_at_each_of_two_device_changes() -> None:
    """Deux changements d'appareil (le produit 1, puis 2, puis 1 de nouveau) : deux
    traits dans chacune des neuf facettes, à leurs dates."""
    products = [1, 1, 2, 2, 1]
    activities = [
        activity(f"w{i}", start(i), device_product=p) for i, p in enumerate(products)
    ]
    climbs = [climb(f"w{i}", start(i), 600, 2400, 300, 1800) for i in range(5)]
    figure = q1_figure(tables_of(activities, climbs))
    assert len(figure.device_changes) == 2
    fig = plot._figure(figure, View.MAIN)
    lines = [s for s in fig.layout.shapes if s.type == "line"]
    assert len(lines) == 18
    assert sorted({s.x0 for s in lines}) == [
        when.replace(tzinfo=None).isoformat() for when in (start(2), start(4))
    ]
