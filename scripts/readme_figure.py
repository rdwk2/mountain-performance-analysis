"""Écrit ``docs/img/chaine.svg``, la figure de la chaîne dans le README.

Usage : ``just figure``. Un tracé GPX inventé et une trace synthétique sont écrits
dans un dossier temporaire, puis la vraie chaîne s'exécute par les fonctions
publiques de ``mountain_perf``, comme ``mperf match --curve`` dans ``cli.py`` :
lecture, profil, courbe, chronologie v0, appariement, horloges, scores de v0 brut.
:func:`render_svg`, pure, met en forme ce que la chaîne a produit : aucun calcul de
modèle ni de métrique ici, seulement des données synthétiques et du dessin.
"""

import math
import tempfile
from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import escape
from itertools import accumulate
from pathlib import Path

from mountain_perf.backtest import (
    MATCHING_PARAMETER_SPECS,
    build_series,
    clock_partition,
    match_trace,
    observe_passages,
    reference_geometry,
    v0_scores,
)
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS, build_profile, read_gpx
from mountain_perf.gpx.geo import deduplicated_polyline
from mountain_perf.gpx.trace_reader import read_trace
from mountain_perf.model import (
    PROJECTION_PARAMETER_SPECS,
    PaceModel,
    projected_timeline,
    read_curve,
)
from mountain_perf.schemas import (
    CLOCKS,
    ClockKind,
    MetricValue,
    OutingScores,
    ParameterSet,
    RegimeClass,
)
from mountain_perf.units import format_duration, ms_to_kmh

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "img" / "chaine.svg"

# ---------------------------------------------------------------------------
# Données synthétiques
# ---------------------------------------------------------------------------

CURVE = ROOT / "tests" / "fixtures" / "courbe_synthetique.csv"
"""La courbe des fixtures, lue comme fichier (support −20 % … +20 %)."""

LEGS: tuple[tuple[float, float], ...] = (
    # Montée vers « Col » : 3,5 km, ≈ +400 m.
    (500.0, 0.07),
    (1500.0, 0.13),
    (1500.0, 0.11),
    # Descente vers « Refuge » : 3,2 km, ≈ −350 m.
    (1600.0, -0.12),
    (1600.0, -0.10),
    # Plat jusqu'à l'arrivée.
    (650.0, 0.01),
    (650.0, -0.01),
)
"""Tronçons du tracé : (longueur en m, pente en fraction). Temps v0 de la montée
≈ 2 × celui de la descente, pour que ×1,10 et ×0,85 se compensent à l'arrivée."""

PLACES: tuple[tuple[str, int], ...] = (("Col", 3), ("Refuge", 5))
"""Lieux nommés : (nom, nombre de tronçons parcourus avant le lieu)."""

START_ELEVATION_M = 1200.0
START_LATITUDE_DEG = 45.0
START_LONGITUDE_DEG = 6.0
M_PER_DEG_LONGITUDE = 111_320.0 * math.cos(math.radians(START_LATITUDE_DEG))
"""Le tracé file plein est, sur le parallèle du départ."""

RAW_STEP_M = 40.0
"""Un ``<trkpt>`` du GPX de référence tous les 40 m."""

ELEVATION_JITTER_M = 1.5
"""Bruit déterministe (sinus) sur l'altitude brute, que le lissage du profil efface."""

ASCENT_FACTOR = 1.10
DESCENT_FACTOR = 0.85
FACTOR_THRESHOLD = 0.05
"""La trace va ×1,10 plus vite que v0 sur les pentes > +5 %, ×0,85 sous −5 %, ×1
ailleurs — pente lissée du profil, celle que voit le modèle."""

TRACE_STEP_S = 5.0
"""Un enregistrement toutes les 5 s, sous ``MAX_STEP_S`` (10 s) : aucun trou."""

TRACE_START = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
GENERATED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
"""Instants fixés : la figure ne dépend pas du jour où on la régénère."""

MAX_GRADE = 0.15
"""Aucune pente du profil au-delà de ±15 % : rien hors du support de la courbe."""


# ---------------------------------------------------------------------------
# La chaîne
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Place:
    """Un lieu annoté : abscisse (km), altitude lissée (m), temps v0 et réalisé (s)."""

    name: str
    distance_km: float
    elevation_m: float
    projected_s: float
    realized_s: float


@dataclass(frozen=True)
class FigureData:
    """Tout ce que la figure dessine, lu dans les sorties de la chaîne."""

    raw_km: tuple[float, ...]
    raw_elevation_m: tuple[float, ...]
    profile_km: tuple[float, ...]
    profile_elevation_m: tuple[float, ...]
    curve_grade: tuple[float, ...]
    curve_kmh: tuple[float, ...]
    curve_line: tuple[tuple[float, float], ...]
    route_grade_range: tuple[float, float]
    places: tuple[Place, ...]
    descents_km: tuple[tuple[float, float], ...]
    errors_min: tuple[tuple[float, float], ...]
    log_ratio: float
    ascent_log_ratio: float
    descent_log_ratio: float
    dispersion: float
    between: float


@dataclass(frozen=True)
class Chain:
    """Les sorties de la chaîne dont la figure a besoin."""

    figure: FigureData
    scores: OutingScores


def _design() -> tuple[list[float], list[float]]:
    """Abscisses et altitudes de conception du GPX de référence."""
    distances, elevations = [0.0], [START_ELEVATION_M]
    for length_m, grade in LEGS:
        start_m, start_ele = distances[-1], elevations[-1]
        steps = round(length_m / RAW_STEP_M)
        for k in range(1, steps + 1):
            distances.append(start_m + k * length_m / steps)
            elevations.append(start_ele + k * length_m / steps * grade)
    return distances, elevations


def _position(distance_m: float) -> tuple[float, float]:
    return START_LATITUDE_DEG, START_LONGITUDE_DEG + distance_m / M_PER_DEG_LONGITUDE


def _reference_gpx() -> str:
    distances, elevations = _design()
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="readme_figure" '
        'xmlns="http://www.topografix.com/GPX/1/1">',
    ]
    for name, legs in PLACES:
        at_m = sum(length_m for length_m, _ in LEGS[:legs])
        index = min(range(len(distances)), key=lambda i: abs(distances[i] - at_m))
        lat, lon = _position(distances[index])
        lines.append(
            f'  <wpt lat="{lat:.8f}" lon="{lon:.8f}">'
            f"<ele>{elevations[index]:.2f}</ele><name>{name}</name></wpt>"
        )
    lines.append("  <trk><name>Tracé synthétique</name><trkseg>")
    for distance_m, elevation_m in zip(distances, elevations, strict=True):
        lat, lon = _position(distance_m)
        jitter_m = ELEVATION_JITTER_M * math.sin(0.37 * distance_m)
        lines.append(
            f'    <trkpt lat="{lat:.8f}" lon="{lon:.8f}">'
            f"<ele>{elevation_m + jitter_m:.2f}</ele></trkpt>"
        )
    lines += ["  </trkseg></trk>", "</gpx>", ""]
    return "\n".join(lines)


def _factor(grade: float) -> float:
    if grade > FACTOR_THRESHOLD:
        return ASCENT_FACTOR
    if grade < -FACTOR_THRESHOLD:
        return DESCENT_FACTOR
    return 1.0


def _interpolate(xs: tuple[float, ...], ys: tuple[float, ...], x: float) -> float:
    j = min(max(bisect_right(xs, x) - 1, 0), len(xs) - 2)
    ratio = (x - xs[j]) / (xs[j + 1] - xs[j])
    return ys[j] + ratio * (ys[j + 1] - ys[j])


def _trace_gpx(
    grid_m: tuple[float, ...],
    pace_s_per_m: tuple[float, ...],
    grades: tuple[float, ...],
    raw_m: tuple[float, ...],
    raw_lat: tuple[float, ...],
    raw_lon: tuple[float, ...],
    raw_ele: tuple[float, ...],
) -> str:
    """La trace : l'allure de v0 de chaque intervalle divisée par le facteur de sa
    pente, échantillonnée toutes les ``TRACE_STEP_S`` sur la polyligne brute."""
    paces = tuple(p / _factor(g) for p, g in zip(pace_s_per_m, grades, strict=True))
    lengths = (grid_m[i + 1] - grid_m[i] for i in range(len(grid_m) - 1))
    cumulative_s = tuple(
        accumulate((d * p for d, p in zip(lengths, paces, strict=True)), initial=0.0)
    )
    end_s = cumulative_s[-1]
    instants = [k * TRACE_STEP_S for k in range(math.ceil(end_s / TRACE_STEP_S))]
    instants.append(end_s)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="readme_figure" '
        'xmlns="http://www.topografix.com/GPX/1/1">',
        "  <trk><name>Trace synthétique</name><trkseg>",
    ]
    for t_s in instants:
        i = min(max(bisect_right(cumulative_s, t_s) - 1, 0), len(paces) - 1)
        at_m = min(grid_m[i] + (t_s - cumulative_s[i]) / paces[i], raw_m[-1])
        when = (TRACE_START + timedelta(seconds=t_s)).isoformat()
        lines.append(
            f'    <trkpt lat="{_interpolate(raw_m, raw_lat, at_m):.8f}" '
            f'lon="{_interpolate(raw_m, raw_lon, at_m):.8f}">'
            f"<ele>{_interpolate(raw_m, raw_ele, at_m):.2f}</ele>"
            f"<time>{when}</time></trkpt>"
        )
    lines += ["  </trkseg></trk>", "</gpx>", ""]
    return "\n".join(lines)


def _value(metric: MetricValue, what: str) -> float:
    if metric.value is None:
        raise SystemExit(f"readme_figure : {what} indisponible ({metric}).")
    return metric.value


def _present(value: float | None, what: str) -> float:
    if value is None:
        raise SystemExit(f"readme_figure : {what} indisponible.")
    return value


def run_chain() -> Chain:
    """Écrit les deux GPX dans un dossier temporaire et exécute la chaîne."""
    with tempfile.TemporaryDirectory() as folder:
        reference_path = Path(folder) / "chaine_reference.gpx"
        trace_path = Path(folder) / "chaine_trace.gpx"
        reference_path.write_text(_reference_gpx(), encoding="utf-8", newline="\n")
        # Comme ``mperf match --curve`` : même fonction, mêmes paramètres.
        curve_read = read_curve(CURVE, ParameterSet(PROJECTION_PARAMETER_SPECS))
        read = read_gpx(reference_path)
        profile = build_profile(read.route, ParameterSet(PROFILE_PARAMETER_SPECS))
        low, high = curve_read.kept_grade_range
        grades = tuple(profile.grade)
        if min(grades) < max(low, -MAX_GRADE) or max(grades) > min(high, MAX_GRADE):
            raise SystemExit(
                f"readme_figure : pentes {min(grades):+.3f} … {max(grades):+.3f} hors "
                f"de ±{MAX_GRADE} ou du support {low:+.2f} … {high:+.2f}."
            )
        timeline = projected_timeline(
            profile, curve_read.curve, ParameterSet(PROJECTION_PARAMETER_SPECS)
        )
        route = read.route
        raw_m = tuple(
            deduplicated_polyline(route.latitude_deg, route.longitude_deg).distance_m
        )
        trace_path.write_text(
            _trace_gpx(
                tuple(profile.distance_m),
                timeline.pace_s_per_m,
                grades,
                raw_m,
                tuple(route.latitude_deg),
                tuple(route.longitude_deg),
                tuple(route.elevation_m),
            ),
            encoding="utf-8",
            newline="\n",
        )
        geometry = reference_geometry(route)
        trace = read_trace([trace_path])
        series = build_series(trace)
        partition = clock_partition(trace, series)
        match = match_trace(
            geometry,
            profile,
            trace,
            series,
            partition,
            ParameterSet(MATCHING_PARAMETER_SPECS),
        )
        passages = observe_passages(match, geometry, profile, trace, series, partition)
        scores = v0_scores(
            profile,
            trace,
            match,
            passages,
            partition,
            curve_read.curve,
            curve_ref=curve_read.curve_ref,
            generated_at=GENERATED_AT,
        )
    usage = scores.usage
    if usage is None:
        raise SystemExit("readme_figure : aucun scénario d'usage.")
    # L'horloge écoulé, choisie par son type.
    elapsed = next(i for i, c in enumerate(CLOCKS) if c.kind is ClockKind.ELAPSED)
    clock = usage.clocks[elapsed]
    assert clock.clock.kind is ClockKind.ELAPSED
    errors = clock.passage_errors
    assert errors is not None  # contrat de ScenarioScores, en usage
    observation = scores.observation
    places = []
    for j, point in enumerate(observation.error_points):
        if point.passage_index is None or point.times_s is None:
            continue
        resolved = passages.passages[point.passage_index].point
        places.append(
            Place(
                resolved.point.name,
                resolved.distance_m / 1000,
                resolved.elevation_m,
                _present(usage.forecast.point_s[j], f"P_k de {resolved.point.name}"),
                point.times_s[elapsed],
            )
        )
    arrival = observation.targets[-1]
    if arrival.times_s is None:
        raise SystemExit("readme_figure : arrivée indisponible.")
    places.append(
        Place(
            "Arrivée",
            arrival.distance_m / 1000,
            profile.elevation_m[-1],
            _present(usage.forecast.target_s[-1], "P de l'arrivée"),
            arrival.times_s[elapsed],
        )
    )
    support = clock.support
    classes = {c.regime_class: c for c in support.classes}
    model = PaceModel(curve_read.curve)
    figure = FigureData(
        raw_km=tuple(d / 1000 for d in raw_m),
        raw_elevation_m=tuple(route.elevation_m),
        profile_km=tuple(d / 1000 for d in profile.distance_m),
        profile_elevation_m=tuple(profile.elevation_m),
        curve_grade=tuple(curve_read.curve.grade),
        curve_kmh=tuple(ms_to_kmh(v) for v in curve_read.curve.speed_ms),
        curve_line=tuple(
            (g, ms_to_kmh(model.speed_ms(g)))
            for g in (low + k * (high - low) / 80 for k in range(81))
        ),
        route_grade_range=(min(grades), max(grades)),
        places=tuple(places),
        descents_km=tuple(
            (s.start_m / 1000, s.end_m / 1000)
            for s in observation.segments
            if s.regime_class is RegimeClass.DESCENT
        ),
        errors_min=tuple(
            (point.distance_m / 1000, error.value / 60)
            for point, error in zip(
                observation.error_points, errors.errors_s, strict=True
            )
            if point.score_index is not None and error.value is not None
        ),
        log_ratio=_value(support.log_ratio, "L"),
        ascent_log_ratio=_value(classes[RegimeClass.ASCENT].log_ratio, "E_R montée"),
        descent_log_ratio=_value(
            classes[RegimeClass.DESCENT].log_ratio, "E_R descente"
        ),
        dispersion=_value(support.dispersion, "A"),
        between=_value(support.between, "B"),
    )
    return Chain(figure, scores)


# ---------------------------------------------------------------------------
# Le rendu SVG
# ---------------------------------------------------------------------------

WIDTH, HEIGHT = 880, 512
SANS, MONO = "sans-serif", "monospace"
INK, MUTED, LINE, PANEL = "#1f2328", "#57606a", "#d0d7de", "#f6f8fa"
GRID, SHADE, RAW = "#eaeef2", "#e4e7eb", "#b4bcc5"
V0, REALIZED = "#0072B2", "#E69F00"
SLOWER, FASTER = "#009E73", "#D55E00"
"""Okabe-Ito : distinguables en daltonisme. La couleur va aux marques et aux traits,
jamais au texte (contraste)."""


def _f(value: float) -> str:
    return f"{value:.1f}"


def _signed(value: float, digits: int) -> str:
    return f"{value:+.{digits}f}".replace("-", "−")


def _text(
    x: float,
    y: float,
    content: str,
    *,
    size: int = 13,
    anchor: str = "start",
    fill: str = INK,
    bold: bool = False,
    family: str = SANS,
) -> str:
    weight = ' font-weight="bold"' if bold else ""
    return (
        f'<text x="{_f(x)}" y="{_f(y)}" font-family="{family}" font-size="{size}"'
        f' fill="{fill}" text-anchor="{anchor}"{weight}>{escape(content)}</text>'
    )


def _line(x1: float, y1: float, x2: float, y2: float, stroke: str, **extra: str) -> str:
    attrs = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in extra.items())
    return (
        f'<line x1="{_f(x1)}" y1="{_f(y1)}" x2="{_f(x2)}" y2="{_f(y2)}"'
        f' stroke="{stroke}"{attrs}/>'
    )


def _rect(x: float, y: float, w: float, h: float, fill: str, **extra: str) -> str:
    attrs = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in extra.items())
    return (
        f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}"'
        f' fill="{fill}"{attrs}/>'
    )


def _badge(x: float, y: float, number: int) -> str:
    """Numéro d'étape dessiné : un disque et un chiffre, sans glyphe ①…⑤."""
    return f'<circle cx="{_f(x)}" cy="{_f(y)}" r="9" fill="{INK}"/>' + _text(
        x, y + 4.5, str(number), size=12, anchor="middle", fill="#ffffff", bold=True
    )


def _polyline(points: list[tuple[float, float]], stroke: str, width: float) -> str:
    path = " ".join(f"{_f(x)},{_f(y)}" for x, y in points)
    return (
        f'<polyline points="{path}" fill="none" stroke="{stroke}"'
        f' stroke-width="{width}" stroke-linejoin="round"/>'
    )


STEPS: tuple[tuple[str, str, bool, float], ...] = (
    ("GPX", "tracé + lieux nommés", False, 150),
    ("profil", "mperf profile", True, 132),
    ("courbe allure↔pente", "lue dans un CSV", False, 170),
    ("projection v0", "mperf project", True, 142),
    ("comparaison à une trace", "mperf match --curve", True, 198),
)
"""Le bandeau : titre, ligne 2, ligne 2 en commande, largeur (px)."""


def _banner() -> list[str]:
    parts, x, gap = [], 16.0, 14.0
    for n, (title, detail, command, width) in enumerate(STEPS, start=1):
        parts.append(_rect(x, 14, width, 52, PANEL, stroke=LINE, rx="8"))
        parts.append(_badge(x + 15, 40, n))
        parts.append(_text(x + 30, 35, title, bold=True))
        fill, family = (INK, MONO) if command else (MUTED, SANS)
        parts.append(_text(x + 30, 53, detail, size=12, fill=fill, family=family))
        if n < len(STEPS):
            end = x + width + gap
            parts.append(_line(x + width + 2, 40, end - 4, 40, MUTED))
            parts.append(
                f'<path d="M{_f(end - 2)},40 L{_f(end - 7)},37 L{_f(end - 7)},43 Z"'
                f' fill="{MUTED}"/>'
            )
        x += width + gap
    return parts


def _curve_panel(data: FigureData) -> list[str]:
    x0, x1, y0, y1 = 58.0, 250.0, 110.0, 190.0
    g_lo, g_hi, v_hi = -0.22, 0.22, 12.0

    def px(g: float) -> float:
        return x0 + (g - g_lo) / (g_hi - g_lo) * (x1 - x0)

    def py(v: float) -> float:
        return y1 - v / v_hi * (y1 - y0)

    parts = [_badge(24, 92, 3), _text(38, 96, "vitesse (km/h) selon la pente")]
    lo, hi = data.route_grade_range
    parts.append(_rect(px(lo), y0, px(hi) - px(lo), y1 - y0, "#e6f1f8"))
    for v in (0.0, 4.0, 8.0, 12.0):
        parts.append(_line(x0, py(v), x1, py(v), GRID))
        parts.append(_text(x0 - 6, py(v) + 4, f"{v:.0f}", size=12, anchor="end"))
    for g in (-0.2, -0.1, 0.0, 0.1, 0.2):
        parts.append(_line(px(g), y1, px(g), y1 + 4, MUTED))
        label = f"{g * 100:+.0f}".replace("-", "−") if g else "0"
        parts.append(_text(px(g), y1 + 16, label, size=12, anchor="middle"))
    parts.append(_line(x0, y1, x1, y1, MUTED))
    parts.append(_text((x0 + x1) / 2, y1 + 30, "pente (%)", size=12, anchor="middle"))
    parts.append(_polyline([(px(g), py(v)) for g, v in data.curve_line], V0, 2))
    for g, v in zip(data.curve_grade, data.curve_kmh, strict=True):
        parts.append(
            f'<circle cx="{_f(px(g))}" cy="{_f(py(v))}" r="3.5" fill="#ffffff"'
            f' stroke="{V0}" stroke-width="2"/>'
        )
    parts.append(_text(px(lo) + 4, y1 - 6, "pentes du tracé", size=12, fill=MUTED))
    return parts


def _sense(value: float) -> str:
    return (
        "v0 trop lent" if value > 0 else "v0 trop rapide" if value < 0 else "v0 juste"
    )


def _summary(data: FigureData) -> list[str]:
    arrival = data.places[-1]
    gap_s = arrival.projected_s - arrival.realized_s
    gap = f"{_signed(gap_s, 0)} s ({_signed(100 * gap_s / arrival.realized_s, 1)} %)"
    parts = [
        _rect(16, 228, 246, 258, PANEL, stroke=LINE, rx="8"),
        _text(28, 248, "Scores de v0 (horloge écoulé)", bold=True),
        _text(28, 270, "arrivée"),
        _rect(96, 260, 10, 10, V0),
        _text(110, 270, format_duration(arrival.projected_s), size=12),
        _rect(170, 260, 10, 10, REALIZED),
        _text(184, 270, format_duration(arrival.realized_s), size=12),
        _text(28, 289, "écart"),
        _text(96, 289, gap),
    ]
    spread = f"écart moyen par segment (≈ {100 * math.expm1(data.dispersion):.0f} %)"
    up, down = data.ascent_log_ratio, data.descent_log_ratio
    rows = (
        ("L", _signed(data.log_ratio, 3), "total presque juste", True),
        ("A", f"{data.dispersion:.3f}", spread, True),
        ("E_R montée", _signed(up, 3), _sense(up), False),
        ("E_R descente", _signed(down, 3), _sense(down), False),
        ("B", f"{data.between:.3f}", "l'écart vient des régimes", True),
    )
    y = 311.0
    for label, value, note, below in rows:
        parts.append(_text(28, y, label))
        parts.append(_text(164, y, value, anchor="end"))
        x, dy = (40.0, 16.0) if below else (170.0, 0.0)
        parts.append(_text(x, y + dy, note, size=12))
        y += 36 if below else 18
    parts.append(_text(28, 459, "L, E_R = ln(prévu / réalisé)", size=12, fill=MUTED))
    parts.append(_text(28, 475, "sur les segments admis", size=12, fill=MUTED))
    return parts


def _main_panels(data: FigureData) -> list[str]:
    x0, x1 = 334.0, 852.0
    y0, y1 = 112.0, 286.0
    b0, b1 = 324.0, 404.0
    length_km = float(math.ceil(data.profile_km[-1]))
    e_min, e_max = min(data.raw_elevation_m), max(data.raw_elevation_m)
    e_lo = math.floor((e_min - 60) / 100) * 100
    e_hi = math.ceil((e_max + 0.45 * (e_max - e_min)) / 100) * 100
    c_top = max(1.0, float(math.ceil(max(c for _, c in data.errors_min))))
    c_bottom = max(1.0, float(math.ceil(-min(c for _, c in data.errors_min))))

    def px(km: float) -> float:
        return x0 + km / length_km * (x1 - x0)

    def py(e: float) -> float:
        return y1 - (e - e_lo) / (e_hi - e_lo) * (y1 - y0)

    def pc(c: float) -> float:
        return b0 + (c_top - c) / (c_top + c_bottom) * (b1 - b0)

    parts = [
        _badge(298, 92, 2),
        _text(312, 96, "profil : altitude (m)"),
        _badge(470, 92, 4),
        _text(484, 96, "temps de passage projetés (v0) et réalisés"),
    ]
    for start, end in data.descents_km:
        parts.append(_rect(px(start), y0, px(end) - px(start), y1 - y0, SHADE))
        parts.append(_rect(px(start), b0, px(end) - px(start), b1 - b0, SHADE))
    for km in range(round(length_km) + 1):
        parts.append(_line(px(km), y0, px(km), y1, GRID))
        parts.append(_line(px(km), b0, px(km), b1, GRID))
        parts.append(_text(px(km), b1 + 16, str(km), size=12, anchor="middle"))
    step = 100 if e_hi - e_lo <= 600 else 200
    for e in range(e_lo, e_hi + 1, step):
        parts.append(_line(x0, py(e), x1, py(e), GRID))
        parts.append(
            _text(x0 - 6, py(e) + 4, f"{e:,}".replace(",", " "), size=12, anchor="end")
        )
    parts.append(_line(x0, y1, x1, y1, MUTED))
    # Points bruts sous le profil lissé : ils dépassent de part et d'autre du trait.
    parts += [
        f'<circle cx="{_f(px(km))}" cy="{_f(py(e))}" r="2.3" fill="{RAW}"/>'
        for km, e in zip(data.raw_km, data.raw_elevation_m, strict=True)
    ]
    parts.append(
        _polyline(
            [
                (px(km), py(e))
                for km, e in zip(data.profile_km, data.profile_elevation_m, strict=True)
            ],
            V0,
            1.6,
        )
    )
    xs = [px(place.distance_km) for place in data.places]
    for k, place in enumerate(data.places):
        x, y = xs[k], py(place.elevation_m)
        # Étiquette centrée, ou à gauche du repère si le lieu suivant est proche.
        crowded = k == len(xs) - 1 or xs[k + 1] - x < 150
        left = x - 70 if crowded else x - 33
        parts.append(_line(x, 160, x, y - 5, MUTED, stroke_dasharray="2 3"))
        parts.append(
            f'<circle cx="{_f(x)}" cy="{_f(y)}" r="4" fill="#ffffff" stroke="{INK}"'
            f' stroke-width="1.5"/>'
        )
        parts.append(_text(left + 33, 122, place.name, anchor="middle", bold=True))
        parts.append(_rect(left, 128, 10, 10, V0))
        parts.append(_text(left + 14, 138, format_duration(place.projected_s), size=12))
        parts.append(_rect(left, 144, 10, 10, REALIZED))
        parts.append(_text(left + 14, 154, format_duration(place.realized_s), size=12))
    # Bande ⑤ : C_k aux points de score.
    parts.append(_badge(298, 306, 5))
    parts.append(
        _text(
            312, 310, "écart projeté − réalisé (min), tous les 250 m · C_k = P_k − T_k"
        )
    )
    parts.append(_rect(652, 427, 10, 10, SLOWER))
    parts.append(_text(666, 436, "v0 trop lent", size=12))
    parts.append(_rect(748, 427, 10, 10, FASTER))
    parts.append(_text(762, 436, "v0 trop rapide", size=12))
    for c in (-c_bottom, 0.0, c_top):
        parts.append(_line(x0, pc(c), x1, pc(c), MUTED if c == 0 else GRID))
        label = _signed(c, 0) if c else "0"
        parts.append(_text(x0 - 6, pc(c) + 4, label, size=12, anchor="end"))
    for at_km, c in data.errors_min:
        top, bottom = sorted((pc(c), pc(0.0)))
        fill = SLOWER if c > 0 else FASTER
        parts.append(_rect(px(at_km) - 3.5, top, 7, max(bottom - top, 0.5), fill))
    parts.append(
        _text((x0 + x1) / 2, b1 + 32, "distance (km)", size=12, anchor="middle")
    )
    # Légende du panneau principal.
    y = 458.0
    parts.append(f'<circle cx="{_f(x0 + 4)}" cy="{_f(y - 4)}" r="2.5" fill="{RAW}"/>')
    parts.append(_text(x0 + 12, y, "points bruts du GPX", size=12))
    parts.append(_line(x0 + 136, y - 4, x0 + 154, y - 4, V0, stroke_width="1.6"))
    parts.append(_text(x0 + 160, y, "profil lissé", size=12))
    parts.append(_rect(x0 + 236, y - 10, 12, 12, SHADE))
    parts.append(_text(x0 + 252, y, "descente (classe des segments)", size=12))
    parts.append(_rect(x0 + 428, y - 9, 10, 10, V0))
    parts.append(_text(x0 + 442, y, "v0", size=12))
    parts.append(_rect(x0 + 464, y - 9, 10, 10, REALIZED))
    parts.append(_text(x0 + 478, y, "réalisé", size=12))
    return parts


def render_svg(data: FigureData) -> str:
    """Le texte du SVG : fonction pure de ``data``, fins de ligne LF."""
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}"'
        f' viewBox="0 0 {WIDTH} {HEIGHT}" role="img">',
        _rect(0.5, 0.5, WIDTH - 1, HEIGHT - 1, "#ffffff", stroke=LINE, rx="14"),
        *_banner(),
        *_curve_panel(data),
        *_summary(data),
        *_main_panels(data),
        _text(
            16,
            500,
            "Données synthétiques : tracé inventé ; la trace va à la vitesse de la "
            "courbe ×1.10 sur les pentes > +5 %, ×0.85 sous −5 %, ×1 ailleurs, "
            "sans arrêt.",
            size=12,
            fill=MUTED,
        ),
        "</svg>",
        "",
    ]
    return "\n".join(parts)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render_svg(run_chain().figure), encoding="utf-8", newline="\n")
    print(f"-> {OUTPUT.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
