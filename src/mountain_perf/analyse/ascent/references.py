"""Les références du modèle de la montée (AN4-2a, ``docs/decisions/0024``) : sur
l'année écoulée (les ``YEAR_DAYS`` jours qui finissent au dernier jour des données,
que l'appelant donne), la FC de référence et ses quartiles 25 et 75 arrondis à 5 bpm,
l'altitude médiane arrondie à 100 m, le D+ moyen. Le régime de référence est la montée
longue. L'arrondi est « la moitié vers le haut », jamais l'arrondi bancaire.

Python pur : bibliothèque standard.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from mountain_perf.analyse.ascent.parameters import (
    ALTITUDE_STEP_M,
    HR_STEP_BPM,
    YEAR_DAYS,
)
from mountain_perf.analyse.ascent.selection import AscentClimb
from mountain_perf.analyse.ascent.states import AscentState, Unavailable


@dataclass(frozen=True)
class References:
    """Les références de l'année écoulée ``[first_day, last_day]``."""

    hr_bpm: float
    """La FC de référence : la médiane, arrondie à ``HR_STEP_BPM``."""
    hr_low_bpm: float
    """Le quartile 25 des FC, arrondi."""
    hr_high_bpm: float
    """Le quartile 75 des FC, arrondi."""
    altitude_km: float
    """L'altitude de référence : la médiane, arrondie à ``ALTITUDE_STEP_M``, en km."""
    d_plus_km: float
    """Le D+ de référence : la moyenne des D+ au milieu des montées, en km."""
    first_day: date
    """``last_day − (YEAR_DAYS − 1)`` jours."""
    last_day: date


def round_to(value: float, step: float) -> float:
    """``step · floor(value / step + 0.5)`` : la moitié vers le haut."""
    return step * math.floor(value / step + 0.5)


def references(
    climbs: Sequence[AscentClimb], last_day: date
) -> References | Unavailable:
    """Les références des montées de l'année écoulée qui finit à ``last_day`` (le
    dernier jour des données) ; moins de deux montées : ``INSUFFICIENT``."""
    first_day = last_day - timedelta(days=YEAR_DAYS - 1)
    year = [c for c in climbs if first_day <= c.day <= last_day]
    if len(year) < 2:
        return Unavailable(
            AscentState.INSUFFICIENT,
            f"{len(year)} montée(s) dans l'année écoulée, 2 au moins.",
        )
    hearts = [c.hr_bpm for c in year]
    quartiles = statistics.quantiles(hearts, n=4, method="inclusive")
    altitude_m = statistics.median(c.altitude_km * 1000 for c in year)
    return References(
        hr_bpm=round_to(statistics.median(hearts), HR_STEP_BPM),
        hr_low_bpm=round_to(quartiles[0], HR_STEP_BPM),
        hr_high_bpm=round_to(quartiles[2], HR_STEP_BPM),
        altitude_km=round_to(altitude_m, ALTITUDE_STEP_M) / 1000,
        d_plus_km=statistics.fmean(c.d_plus_km for c in year),
        first_day=first_day,
        last_day=last_day,
    )
