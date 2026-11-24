"""L'étage 2 du modèle de la montée, la Fenêtre (AN4-2a, ``docs/decisions/0024``) : le
niveau ``a_w`` et la tendance ``c`` des résumés de sortie de la Fenêtre, l'échelle des
couleurs, β et ``g`` de la Fenêtre mêlés à ceux de l'histoire par un poids continu, les
bornes de FC et la courbe de G2.

La tendance se juge sur l'intervalle à 95 % de sa pente, par la loi normale sur la
variance empruntée à l'étage 1 ; pas de bande simultanée : une seule tendance par
courbe, une seule décision de couleur. β et ``g`` de la Fenêtre prennent la covariance
classique à ``s²_e`` de l'étage 1, même sous dix sorties (``0024``, deux écarts à la
charte § 4 bis.2, ceux d'un tableau de bord).

Python pur : bibliothèque standard, et ``ols`` d'``analyse/inference/`` par des
listes.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from mountain_perf.analyse.ascent.daily import Band as Band
from mountain_perf.analyse.ascent.daily import Z, band
from mountain_perf.analyse.ascent.parameters import (
    BORROWED_BELOW,
    COLOUR_MAX_DAYS,
    HR_BOUNDS_CENTILES,
    MIN_TREND_SORTIES,
    MONTH_DAYS,
    SCALE_CAP,
    SCALE_FLOOR,
    TAU_BETA,
    TAU_G,
)
from mountain_perf.analyse.ascent.selection import AscentClimb
from mountain_perf.analyse.ascent.speed import HabitualSpeed, habitual_speed
from mountain_perf.analyse.ascent.states import AscentState, Unavailable
from mountain_perf.analyse.ascent.structure import CARRIED, Point, Structure
from mountain_perf.analyse.inference.base import InferenceError, Interval
from mountain_perf.analyse.inference.linear import ols
from mountain_perf.analyse.window import Window


@dataclass(frozen=True)
class Blend:
    """Un coefficient de l'histoire mêlé à celui de la Fenêtre : ``value = history +
    k·(window − history)``, ``variance = (1 − k)²·history_variance +
    k·window_variance``, ``k = τ² / (τ² + window_variance)`` ; ``window`` et
    ``weight`` à ``None`` quand la Fenêtre ne l'estime pas, ou couvre toute
    l'histoire."""

    history: float
    history_variance: float
    window: float | None
    window_variance: float | None
    weight: float | None
    value: float
    variance: float


@dataclass(frozen=True)
class Trend:
    """La tendance de la Fenêtre : la pente ``slope`` (log par mois), sa variance
    empruntée, l'erreur type de Student à variance propre (``se_own``, un contrôle,
    jamais lu pour la couleur), l'intervalle à 95 % et sa ``direction`` (+1, −1, 0
    quand il contient 0) ; la vitesse habituelle ``speed`` à la longueur de la
    Fenêtre, le poids ``k_c``, la pente rétrécie ``k_c·c``, l'échelle ``m`` et
    ``ratio = k_c·c / m`` ramené à ``[−1 ; 1]``."""

    slope: float
    variance: float
    se_own: float
    interval: Interval
    direction: int
    speed: HabitualSpeed
    weight: float
    shrunk: float
    scale: float
    ratio: float


@dataclass(frozen=True)
class WindowFit:
    """L'étage 2 sur une Fenêtre : ``n_sorties`` résumés dans la Fenêtre, dont
    ``n_multi`` sorties à deux montées ou plus ; ``mean_day``, la date moyenne en
    jours après ``window.first`` ; le niveau ``a_w`` et sa variance ; la tendance ;
    ``colour`` (``None`` : la couleur se lit sur ``trend.direction``) ; β et ``g``
    mêlés ; ``g_borrowed`` ; les centiles 5 et 95 des FC des montées de la Fenêtre ;
    les états, dans l'ordre ``DEVICE_RUPTURE``, ``NOT_APPLICABLE``, ``INSUFFICIENT``,
    ``BORROWED``."""

    window: Window
    n_sorties: int
    n_multi: int
    mean_day: float
    level: float
    level_variance: float
    trend: Trend | Unavailable
    colour: AscentState | None
    beta: Blend
    g: Blend
    g_borrowed: bool
    hr_bounds_bpm: tuple[float, float] | None
    states: tuple[AscentState, ...]


def blend(
    history: float,
    history_variance: float,
    window: float | None,
    window_variance: float | None,
    tau: float,
) -> Blend:
    """Le mélange de ``history`` et ``window`` au poids ``k = τ² / (τ² +
    window_variance)`` ; sans valeur de la Fenêtre, l'histoire seule."""
    if window is None or window_variance is None:
        return Blend(
            history, history_variance, None, None, None, history, history_variance
        )
    weight = tau**2 / (tau**2 + window_variance)
    return Blend(
        history=history,
        history_variance=history_variance,
        window=window,
        window_variance=window_variance,
        weight=weight,
        value=history + weight * (window - history),
        variance=(1 - weight) ** 2 * history_variance + weight * window_variance,
    )


def colour_scale(tau: float) -> float:
    """L'échelle des couleurs ``m = 2·τ``, ramenée à ``[SCALE_FLOOR ; SCALE_CAP]``."""
    return min(max(2 * tau, SCALE_FLOOR), SCALE_CAP)


def _trend_refusal(points: Sequence[Point]) -> Unavailable | None:
    """``INSUFFICIENT`` sous ``MIN_TREND_SORTIES`` points ou sur un seul jour."""
    if len(points) < MIN_TREND_SORTIES:
        return Unavailable(
            AscentState.INSUFFICIENT,
            f"{len(points)} sorties dans la Fenêtre, {MIN_TREND_SORTIES} au moins "
            "pour une tendance.",
        )
    if len({p.day for p in points}) < 2:
        return Unavailable(
            AscentState.INSUFFICIENT,
            "1 jour distinct dans la Fenêtre, 2 au moins pour une tendance.",
        )
    return None


def window_trend(
    points: Sequence[Point], first: date, speed: HabitualSpeed
) -> Trend | Unavailable:
    """La tendance des ``points`` (les résumés de la Fenêtre), les jours comptés en
    mois depuis ``first`` (le premier jour de la Fenêtre) : ``c = Σ u_j·(s_j − a_w) /
    S``, ``var(c) = Σ u_j²·v_j / S²``, l'intervalle ``c ± Z·√var(c)`` ; ``k_c =
    τ(w)² / (τ(w)² + var(c))``, ``τ(w) = speed.value``. Sous ``MIN_TREND_SORTIES``
    points, ou sur un seul jour : ``INSUFFICIENT``."""
    refusal = _trend_refusal(points)
    if refusal is not None:
        return refusal
    n = len(points)
    t = [(p.day - first).days / MONTH_DAYS for p in points]
    t_bar = statistics.fmean(t)
    u = [v - t_bar for v in t]
    level = statistics.fmean(p.value for p in points)
    spread = sum(v * v for v in u)
    slope = sum(v * (p.value - level) for v, p in zip(u, points, strict=True)) / spread
    variance = (
        sum(v * v * p.variance for v, p in zip(u, points, strict=True)) / spread**2
    )
    rss = sum(
        (p.value - level - slope * v) ** 2 for v, p in zip(u, points, strict=True)
    )
    se_own = math.sqrt(rss / (n - 2) / spread)
    half = Z * math.sqrt(variance)
    interval = Interval(slope - half, slope + half)
    direction = 1 if interval.low > 0 else -1 if interval.high < 0 else 0
    tau = speed.value
    weight = tau**2 / (tau**2 + variance) if tau > 0 else 0.0
    shrunk = weight * slope
    scale = colour_scale(tau)
    return Trend(
        slope=slope,
        variance=variance,
        se_own=se_own,
        interval=interval,
        direction=direction,
        speed=speed,
        weight=weight,
        shrunk=shrunk,
        scale=scale,
        ratio=min(max(shrunk / scale, -1.0), 1.0),
    )


def _window_slopes(
    structure: Structure, climbs: Sequence[AscentClimb]
) -> tuple[int, tuple[float, float, float, float] | None]:
    """Le nombre de sorties de ``climbs`` à deux montées ou plus, et ``(β_w, var,
    g_w, var)`` de la Fenêtre, ou ``None`` quand elle ne les estime pas."""
    groups: dict[str, list[AscentClimb]] = {}
    for climb in climbs:
        groups.setdefault(climb.activity_ref, []).append(climb)
    multi = [g for g in groups.values() if len(g) >= 2]
    n_climbs = sum(len(g) for g in multi)
    if len(multi) < 2 or n_climbs - len(multi) - 2 < 1:
        return len(multi), None
    hr_ref = structure.references.hr_bpm
    lam, rho = structure.coef[2], structure.coef[3]
    rows: list[list[float]] = []
    response: list[float] = []
    for group in multi:
        x = [math.log(c.hr_bpm / hr_ref) for c in group]
        d = [c.d_plus_km for c in group]
        y = [
            c.log_speed - lam * c.altitude_km - rho * (1.0 if c.intermediate else 0.0)
            for c in group
        ]
        x_bar, d_bar, y_bar = (statistics.fmean(v) for v in (x, d, y))
        for xi, di, yi in zip(x, d, y, strict=True):
            rows.append([xi - x_bar, di - d_bar])
            response.append(yi - y_bar)
    if not all(any(abs(row[k]) > CARRIED for row in rows) for k in (0, 1)):
        return len(multi), None
    try:
        fitted: Any = ols(rows, response).coef
    except InferenceError:
        return len(multi), None
    sxx = sum(r[0] * r[0] for r in rows)
    sxd = sum(r[0] * r[1] for r in rows)
    sdd = sum(r[1] * r[1] for r in rows)
    det = sxx * sdd - sxd * sxd
    return len(multi), (
        float(fitted[0]),
        structure.s2_e * sdd / det,
        float(fitted[1]),
        structure.s2_e * sxx / det,
    )


def fit_window(
    structure: Structure, climbs: Sequence[AscentClimb], window: Window
) -> WindowFit | Unavailable:
    """L'étage 2 sur ``window`` : ``climbs``, la sélection entière (les montées de
    la Fenêtre s'y lisent) ; ``INSUFFICIENT`` sans résumé dans la Fenêtre."""
    inside = [s for s in structure.summaries if s.day in window]
    if not inside:
        return Unavailable(
            AscentState.INSUFFICIENT, "0 sortie dans la Fenêtre, 1 au moins."
        )
    count = len(inside)
    level = statistics.fmean(s.value for s in inside)
    level_variance = sum(s.variance for s in inside) / count**2
    mean_day = statistics.fmean(float((s.day - window.first).days) for s in inside)
    points = [Point(s.day, s.value, s.variance) for s in inside]
    trend: Trend | Unavailable | None = _trend_refusal(points)
    if trend is None:
        speed = habitual_speed(
            structure.points, window.days, structure.references.last_day
        )
        trend = window_trend(points, window.first, speed)
    days = [s.day for s in structure.summaries]
    whole = window.first <= min(days) and window.last >= max(days)
    if window.days > COLOUR_MAX_DAYS or whole:
        colour: AscentState | None = AscentState.NOT_APPLICABLE
    elif isinstance(trend, Unavailable):
        colour = AscentState.INSUFFICIENT
    else:
        colour = None
    own = [c for c in climbs if c.day in window]
    beta_history = (structure.coef[0], structure.cov[0][0])
    g_history = (structure.coef[1], structure.cov[1][1])
    n_multi, slopes = _window_slopes(structure, own)
    states: list[AscentState] = []
    if len({c.device for c in own}) > 1:
        states.append(AscentState.DEVICE_RUPTURE)
    if whole:
        beta = blend(*beta_history, None, None, TAU_BETA)
        g = blend(*g_history, None, None, TAU_G)
        borrowed = False
        states.append(AscentState.NOT_APPLICABLE)
    else:
        if slopes is None:
            beta = blend(*beta_history, None, None, TAU_BETA)
            g = blend(*g_history, None, None, TAU_G)
            states.append(AscentState.INSUFFICIENT)
        else:
            beta = blend(*beta_history, slopes[0], slopes[1], TAU_BETA)
            g = blend(*g_history, slopes[2], slopes[3], TAU_G)
        borrowed = g.weight is None or g.weight < BORROWED_BELOW
        if borrowed:
            states.append(AscentState.BORROWED)
    hearts = [c.hr_bpm for c in own]
    bounds: tuple[float, float] | None = None
    if len(hearts) >= 2:
        q = statistics.quantiles(hearts, n=20, method="inclusive")
        low, high = (q[c // 5 - 1] for c in HR_BOUNDS_CENTILES)
        bounds = (low, high)
    return WindowFit(
        window=window,
        n_sorties=count,
        n_multi=n_multi,
        mean_day=mean_day,
        level=level,
        level_variance=level_variance,
        trend=trend,
        colour=colour,
        beta=beta,
        g=g,
        g_borrowed=borrowed,
        hr_bounds_bpm=bounds,
        states=tuple(states),
    )


def g2_band(fit: WindowFit, structure: Structure, hr_bpm: float) -> Band:
    """La courbe de G2 à la FC ``hr_bpm`` : ``centre = a_w + β·x``, ``x = ln(hr_bpm /
    FC_réf)``, β mêlé ; ``variance = var(a_w) + x²·var(β)`` (la covariance de ``a_w``
    et de β est négligée, ``0024``)."""
    x = math.log(hr_bpm / structure.references.hr_bpm)
    return band(
        fit.level + fit.beta.value * x, fit.level_variance + x * x * fit.beta.variance
    )
