"""L'autocorrélation des résidus par classe d'écart en jours (AN3-1,
``docs/decisions/0021``, ``docs/analyse/CHARTE.md`` § 4 bis.3) : résidus centrés,
moyenne des produits par paire, divisée par la variance (sur ``n``)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy

from mountain_perf.analyse.inference.base import InferenceError, as_vector


@dataclass(frozen=True)
class LagClass:
    """Une classe d'écart : bornes ``low`` et ``high`` en jours, comprises (``high``
    à ``None`` : sans borne haute), le nombre de paires, la corrélation (``None``
    sans paire)."""

    low: int
    high: int | None
    pairs: int
    correlation: float | None


def _check_classes(
    classes: Sequence[tuple[int, int | None]],
) -> tuple[tuple[int, int | None], ...]:
    checked = tuple((low, high) for low, high in classes)
    if not checked:
        raise InferenceError("classes : la suite est vide")
    previous_high: int | None = 0
    for low, high in checked:
        if low < 1:
            raise InferenceError(f"classes : low < 1 ({low})")
        if high is not None and high < low:
            raise InferenceError(f"classes : high < low ({low}, {high})")
        if previous_high is None or low <= previous_high:
            raise InferenceError(
                "classes : des classes qui se recouvrent ou ne croissent pas"
            )
        previous_high = high
    return checked


def residual_autocorrelation(
    t: object, resid: object, classes: Sequence[tuple[int, int | None]]
) -> tuple[LagClass, ...]:
    """Pour chaque classe ``(low, high)``, les paires ``i < j`` d'écart
    ``low ≤ |t_i − t_j| ≤ high`` et ``Σ e_i·e_j / (pairs · s²)``, avec
    ``e = resid − mean(resid)`` et ``s² = Σ e_i² / n``."""
    days = as_vector(t, "t", min_size=2)
    values = as_vector(resid, "resid", min_size=2)
    if values.shape != days.shape:
        raise InferenceError(f"resid : {values.shape[0]} valeurs pour {days.shape[0]}")
    checked = _check_classes(classes)
    centred = values - float(numpy.mean(values))
    variance = float(centred @ centred) / centred.shape[0]
    if variance == 0.0:
        raise InferenceError("resid : résidus constants, variance nulle")
    upper = numpy.triu_indices(days.shape[0], k=1)
    gaps = numpy.abs(days[upper[0]] - days[upper[1]])
    products = centred[upper[0]] * centred[upper[1]]
    result: list[LagClass] = []
    for low, high in checked:
        inside = gaps >= low
        if high is not None:
            inside &= gaps <= high
        pairs = int(numpy.count_nonzero(inside))
        correlation = (
            float(numpy.sum(products[inside])) / (pairs * variance) if pairs else None
        )
        result.append(LagClass(low, high, pairs, correlation))
    return tuple(result)
