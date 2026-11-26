"""La vitesse habituelle du niveau, ``τ`` (AN4-2a, ``docs/decisions/0024``) : de
combien le niveau change d'habitude, en log par mois, estimée sur des périodes
disjointes de la longueur voulue (``N`` pour l'étage 3, la longueur de la Fenêtre pour
l'échelle des couleurs), en remontant depuis ``end`` sur toute l'histoire.

Python pur : bibliothèque standard.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from mountain_perf.analyse.ascent.parameters import (
    MONTH_DAYS,
    TAU_CAP,
    TAU_DEFAULT,
    TAU_MIN_PERIODS,
    TAU_MIN_SORTIES,
)
from mountain_perf.analyse.ascent.states import AscentError, AscentState
from mountain_perf.analyse.ascent.structure import Point


@dataclass(frozen=True)
class HabitualSpeed:
    """``τ`` en log par mois ; ``estimated`` faux : ``TAU_DEFAULT`` ; ``periods`` : les
    périodes riches comptées ; ``state`` : ``ESTIMATED`` ou ``DEFAULT``."""

    value: float
    estimated: bool
    periods: int
    state: AscentState


def point_slope(points: Sequence[Point]) -> tuple[float, float] | None:
    """La pente ``ĉ`` des valeurs en mois, par moindres carrés, et sa variance
    empruntée ``e² = Σ (u_j − ū)²·variance_j / S²`` (``S = Σ (u_j − ū)²``) ; ``None``
    sous deux jours distincts. Ni l'une ni l'autre ne dépend de l'origine des
    ``u_j``."""
    if len({p.day for p in points}) < 2:
        return None
    origin = points[0].day
    u = [(p.day - origin).days / MONTH_DAYS for p in points]
    u_bar = statistics.fmean(u)
    m_bar = statistics.fmean(p.value for p in points)
    spread = sum((v - u_bar) ** 2 for v in u)
    slope = (
        sum((v - u_bar) * (p.value - m_bar) for v, p in zip(u, points, strict=True))
        / spread
    )
    variance = (
        sum((v - u_bar) ** 2 * p.variance for v, p in zip(u, points, strict=True))
        / spread**2
    )
    return slope, variance


def habitual_speed(
    points: Sequence[Point], length_days: int, end: date
) -> HabitualSpeed:
    """``τ`` sur les périodes disjointes ``[end − (k+1)·L + 1, end − k·L]``, ``k = 0,
    1, …``, tant que leur premier jour n'est pas avant le premier point ; une période
    est riche avec au moins ``TAU_MIN_SORTIES`` points sur deux jours distincts ; avec
    au moins ``TAU_MIN_PERIODS`` périodes riches, ``τ² = variance(ĉ_p) −
    moyenne(e²_p)``, ``τ = min(√max(τ², 0), TAU_CAP)`` ; sinon ``TAU_DEFAULT``.
    ``length_days < 1`` : :class:`AscentError`."""
    if length_days < 1:
        raise AscentError(f"Une période a au moins un jour, reçu {length_days}.")
    slopes: list[float] = []
    errors: list[float] = []
    if points:
        first = min(p.day for p in points)
        k = 0
        while (start := end - timedelta(days=(k + 1) * length_days - 1)) >= first:
            stop = end - timedelta(days=k * length_days)
            members = [p for p in points if start <= p.day <= stop]
            fitted = point_slope(members) if len(members) >= TAU_MIN_SORTIES else None
            if fitted is not None:
                slopes.append(fitted[0])
                errors.append(fitted[1])
            k += 1
    if len(slopes) < TAU_MIN_PERIODS:
        return HabitualSpeed(TAU_DEFAULT, False, len(slopes), AscentState.DEFAULT)
    tau2 = statistics.variance(slopes) - statistics.fmean(errors)
    value = min(math.sqrt(max(tau2, 0.0)), TAU_CAP)
    return HabitualSpeed(value, True, len(slopes), AscentState.ESTIMATED)
