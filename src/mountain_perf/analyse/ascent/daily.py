"""L'étage 3 du modèle de la montée, le jour (AN4-2a, ``docs/decisions/0024``) : le
niveau des ``N`` jours qui finissent à la dernière sortie au plus tard le jour lu, lu à
cette dernière sortie, la pente rétrécie par ``k = τ² / (τ² + e²)``. **La valeur est
gelée à la dernière sortie** : entre deux sorties la fenêtre ne glisse pas, seule la
variance s'ouvre de ``(τ·Δ)²`` ; la courbe s'arrête ``FREEZE_DAYS`` jours après la
dernière sortie. L'étage 3 ne lit que l'étage 1, jamais la Fenêtre.

Python pur : bibliothèque standard.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import NormalDist

from mountain_perf.analyse.ascent.parameters import (
    FREEZE_DAYS,
    MIN_SLOPE_SORTIES,
    MONTH_DAYS,
)
from mountain_perf.analyse.ascent.speed import point_slope
from mountain_perf.analyse.ascent.states import AscentError
from mountain_perf.analyse.ascent.structure import Point, Structure

Z = NormalDist().inv_cdf(0.975)
"""Le quantile de la loi normale des bandes à 95 %."""


@dataclass(frozen=True)
class Band:
    """Une bande ponctuelle à 95 % : ``centre ∓ Z·√variance``."""

    centre: float
    variance: float
    low: float
    high: float


def band(centre: float, variance: float) -> Band:
    """La bande à 95 % par la loi normale autour de ``centre``."""
    half = Z * math.sqrt(variance)
    return Band(centre, variance, centre - half, centre + half)


@dataclass(frozen=True)
class Level:
    """Le niveau du jour ``day`` : ``value``, lu au dernier point ``last_day`` (au
    plus tard ``day``) ; ``weight``, ``slope``, ``slope_variance`` : ``k``, ``ĉ``,
    ``e²`` (``None`` sous ``MIN_SLOPE_SORTIES`` points ou sur un seul jour) ;
    ``provisional`` : ``day > last_day``."""

    day: date
    n_points: int
    last_day: date
    value: float
    variance: float
    weight: float | None
    slope: float | None
    slope_variance: float | None
    provisional: bool


def shrunk_level(
    points: Sequence[Point], day: date, n_days: int, tau: float
) -> Level | None:
    """Le niveau du jour ``day`` sur les points des ``n_days`` jours qui finissent au
    dernier point au plus tard ``day`` : ``m̄ + k·ĉ·l`` (``l`` l'écart en mois du
    dernier point à la date moyenne), de variance ``Σ v_j / n² + l²·k·e² +
    (τ·Δ)²`` (``Δ`` en mois depuis le dernier point) ; ``None`` sans point au plus
    tard ``day`` ou plus de ``FREEZE_DAYS`` jours après le dernier.
    ``n_days < 1`` ou ``tau < 0`` : :class:`AscentError`."""
    if n_days < 1:
        raise AscentError(f"N vaut au moins un jour, reçu {n_days}.")
    if not tau >= 0.0:
        raise AscentError(f"τ est positif ou nul, reçu {tau}.")
    before = [p.day for p in points if p.day <= day]
    if not before:
        return None
    last = max(before)
    if (day - last).days > FREEZE_DAYS:
        return None
    first = last - timedelta(days=n_days - 1)
    members = [p for p in points if first <= p.day <= last]
    n = len(members)
    mean = statistics.fmean(p.value for p in members)
    variance = sum(p.variance for p in members) / n**2
    value = mean
    weight: float | None = None
    slope: float | None = None
    slope_variance: float | None = None
    fitted = point_slope(members) if n >= MIN_SLOPE_SORTIES else None
    if fitted is not None:
        slope, slope_variance = fitted
        weight = tau**2 / (tau**2 + slope_variance) if tau > 0.0 else 0.0
        lever = -statistics.fmean((p.day - last).days / MONTH_DAYS for p in members)
        value = mean + weight * slope * lever
        variance += lever**2 * weight * slope_variance
    gap = (day - last).days / MONTH_DAYS
    variance += (tau * gap) ** 2
    return Level(
        day=day,
        n_points=n,
        last_day=last,
        value=value,
        variance=variance,
        weight=weight,
        slope=slope,
        slope_variance=slope_variance,
        provisional=day > last,
    )


@dataclass(frozen=True)
class DailyLevel:
    """Le niveau du jour lu à la FC ``hr_bpm`` et sa bande."""

    level: Level
    hr_bpm: float
    band: Band


def daily_level(
    structure: Structure, day: date, n_days: int, tau: float, hr_bpm: float
) -> DailyLevel | None:
    """Le niveau du jour ``day`` à la FC ``hr_bpm`` : ``centre = level.value +
    β·x_q`` (``x_q = ln(hr_bpm / FC_réf)``), de variance ``level.variance + qᵀ·cov·q +
    wᵀ·gamma_cov·w``, ``q = (x_q − x̄, D_ref − D̄, A_ref − Ā, −Ī)``, ``w = (−(D̄ −
    D_ref), −(Ā − A_ref))``, sur les moyennes des résumés du lissage ; ``None`` quand
    :func:`shrunk_level` rend ``None``. ``hr_bpm ≤ 0`` : :class:`AscentError`."""
    if not hr_bpm > 0.0:
        raise AscentError(f"Une FC est positive, reçu {hr_bpm}.")
    level = shrunk_level(structure.points, day, n_days, tau)
    if level is None:
        return None
    first = level.last_day - timedelta(days=n_days - 1)
    used = [s for s in structure.summaries if first <= s.day <= level.last_day]
    refs = structure.references
    x_bar = statistics.fmean(s.mean_x for s in used)
    d_bar = statistics.fmean(s.mean_d_plus_km for s in used)
    a_bar = statistics.fmean(s.mean_altitude_km for s in used)
    i_bar = statistics.fmean(s.intermediate_share for s in used)
    x_q = math.log(hr_bpm / refs.hr_bpm)
    q = (x_q - x_bar, refs.d_plus_km - d_bar, refs.altitude_km - a_bar, -i_bar)
    w = (-(d_bar - refs.d_plus_km), -(a_bar - refs.altitude_km))
    variance = (
        level.variance
        + sum(q[a] * structure.cov[a][b] * q[b] for a in range(4) for b in range(4))
        + sum(
            w[a] * structure.gamma_cov[a][b] * w[b] for a in range(2) for b in range(2)
        )
    )
    centre = level.value + structure.coef[0] * x_q
    return DailyLevel(level=level, hr_bpm=hr_bpm, band=band(centre, variance))
