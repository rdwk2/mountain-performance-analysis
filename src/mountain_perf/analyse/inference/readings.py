"""Familles de comparaisons et les trois lectures de la charte (AN3-1,
``docs/decisions/0021``, ``docs/analyse/CHARTE.md`` § 6) : Holm, le niveau de
Bonferroni, « établi », « absence d'effet utile », « non tranché »."""

from __future__ import annotations

import enum
import math
from collections.abc import Sequence

from mountain_perf.analyse.inference.base import InferenceError, Interval


def _check_alpha(alpha: float) -> None:
    if not 0.0 < alpha < 1.0:
        raise InferenceError(f"alpha : hors de ]0 ; 1[ ({alpha})")


def holm(pvalues: Sequence[float], alpha: float) -> tuple[bool, ...]:
    """Les rejets de Holm, dans l'ordre d'entrée : tri croissant stable ; la ``k``-ième
    p-valeur triée est rejetée si ``p₍k₎ ≤ alpha / (m − k + 1)`` ; au premier
    non-rejet, toutes les suivantes sont non rejetées."""
    _check_alpha(alpha)
    values = [float(p) for p in pvalues]
    if not values:
        raise InferenceError("pvalues : la suite est vide")
    for p in values:
        if not (math.isfinite(p) and 0.0 <= p <= 1.0):
            raise InferenceError(f"pvalues : hors de [0 ; 1] ({p})")
    m = len(values)
    order = sorted(range(m), key=lambda i: values[i])
    rejected = [False] * m
    for k, index in enumerate(order, start=1):
        if values[index] > alpha / (m - k + 1):
            break
        rejected[index] = True
    return tuple(rejected)


def bonferroni_level(alpha: float, m: int) -> float:
    """Le niveau des intervalles de Bonferroni : ``1 − alpha / m``."""
    _check_alpha(alpha)
    if isinstance(m, bool) or not isinstance(m, int) or m < 1:
        raise InferenceError(f"m : un entier ≥ 1 est attendu ({m!r})")
    return 1.0 - alpha / m


class Reading(enum.Enum):
    """Les trois lectures de la charte (§ 6)."""

    ESTABLISHED = "établi"
    NO_USEFUL_EFFECT = "absence d'effet utile"
    UNDECIDED = "non tranché"


def _intervals(intervals: Sequence[Interval]) -> tuple[Interval, ...]:
    result = tuple(intervals)
    if not result:
        raise InferenceError("intervals : la suite est vide")
    return result


def direction(intervals: Sequence[Interval]) -> int:
    """``+1`` si tous les intervalles ont ``low > 0``, ``−1`` si tous ont
    ``high < 0`` (au sens strict), ``0`` sinon."""
    checked = _intervals(intervals)
    if all(interval.low > 0.0 for interval in checked):
        return 1
    if all(interval.high < 0.0 for interval in checked):
        return -1
    return 0


def reading(intervals: Sequence[Interval], delta: float) -> Reading:
    """La lecture d'intervalles sur l'échelle de la lecture, ``delta > 0`` sur la même
    échelle : « établi » si chacun exclut 0 au sens strict, tous du même côté ; sinon
    « absence d'effet utile » si chacun tient dans ``]−delta ; +delta[`` ; sinon « non
    tranché ». « Établi » l'emporte."""
    checked = _intervals(intervals)
    if not (math.isfinite(delta) and delta > 0.0):
        raise InferenceError(f"delta : un réel > 0 est attendu ({delta})")
    if direction(checked) != 0:
        return Reading.ESTABLISHED
    if all(-delta < interval.low and interval.high < delta for interval in checked):
        return Reading.NO_USEFUL_EFFECT
    return Reading.UNDECIDED
