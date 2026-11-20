"""Les données de la figure de Q2 (AN3-3b, ``docs/decisions/0023``, Q-37 (e), Q-38) :
les résidus partiels de la date du principal, leur courbe lissée (spline naturelle
à cinq nœuds, « 4 ddl ») et sa bande simultanée à 95 % (bootstrap sauvage des résidus
de l'étage 2, puis max-t) ; le dernier tronçon, au-delà du nœud à 75 %, est
provisoire (Q-50 (c)). Descriptive, sans verdict ; la bande ignore la corrélation
entre journées.

Les générateurs de numpy s'annotent ``Any`` : numpy est fermé à ``inference/``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from mountain_perf.analyse.inference.base import InferenceError, order_quantile
from mountain_perf.analyse.inference.bootstrap import max_t_band, wild_residual_draws
from mountain_perf.analyse.inference.linear import gls_operator
from mountain_perf.analyse.inference.spline import natural_cubic_basis
from mountain_perf.analyse.normals import integer_parameter
from mountain_perf.analyse.q2.model import CONSTANT, DATE, DirectFit
from mountain_perf.analyse.q2.parameters import FIGURE_KNOT_QUANTILES
from mountain_perf.schemas import ParameterSet

FIGURE_KEY: tuple[int, int, int] = (2, 0, 2)
"""La clé du générateur de la bande, sous ``Q2_ROOT_SEED`` (essai 0, usage 2)."""
BAND_LEVEL = 0.95


def partial_date_residuals(
    X: Sequence[Sequence[float]],  # noqa: N803
    y: Sequence[float],
    coef: Sequence[float],
    constant_column: int,
    date_column: int,
) -> list[float]:
    """``r_s = ȳ_s − Σ_c X_sc·β̂_c`` sur toutes les colonnes sauf la constante et la
    date."""
    skip = {constant_column, date_column}
    return [
        value
        - sum(
            x * b
            for k, (x, b) in enumerate(zip(row, coef, strict=True))
            if k not in skip
        )
        for row, value in zip(X, y, strict=True)
    ]


@dataclass(frozen=True)
class FigurePoint:
    """Une journée : sa date et son résidu partiel."""

    day: date
    residual: float


@dataclass(frozen=True)
class FigureCurve:
    """Un jour de la grille : sa date, la courbe, la bande, provisoire ou non."""

    day: date
    estimate: float
    low: float
    high: float
    provisional: bool


@dataclass(frozen=True)
class Q2Figure:
    """La figure de Q2 : les points, la courbe sur la grille des jours entiers, les
    cinq nœuds (en jours depuis la première journée), le nombre de tirages et la clé
    du générateur de la bande."""

    points: tuple[FigurePoint, ...]
    curve: tuple[FigureCurve, ...]
    knots: tuple[float, ...]
    draws: int
    key: tuple[int, int, int]


def _basis(t: Sequence[float], knots: Sequence[float]) -> list[list[float]]:
    rows: list[list[float]] = natural_cubic_basis(list(t), list(knots)).tolist()
    return [[1.0, *row] for row in rows]


def _apply(operator: Sequence[Sequence[float]], values: Sequence[float]) -> list[float]:
    return [sum(a * v for a, v in zip(row, values, strict=True)) for row in operator]


def q2_figure_data(
    direct: DirectFit, parameters: ParameterSet, rng: Any
) -> Q2Figure | None:
    """La figure du principal estimé (``direct``) ; ``None`` si la spline ne
    s'ajuste pas (nœuds égaux, trop peu de journées). ``rng`` : un
    ``numpy.random.Generator`` sous :data:`FIGURE_KEY` (annoté ``Any``)."""
    design = direct.design
    coef = [float(c) for c in direct.reml.fit.coef.tolist()]
    residuals = partial_date_residuals(
        design.X, design.y, coef, design.index(CONSTANT), design.index(DATE)
    )
    t = list(design.t)
    knots = (
        min(t),
        *(order_quantile(t, q) for q in FIGURE_KNOT_QUANTILES),
        max(t),
    )
    grid = [float(day) for day in range(int(max(t)) + 1)]
    try:
        basis = _basis(t, knots)
        grid_basis = _basis(grid, knots)
        identity = [[float(i == j) for j in range(len(t))] for i in range(len(t))]
        operator: list[list[float]] = gls_operator(basis, identity).tolist()
    except InferenceError:
        return None
    coefficients = _apply(operator, residuals)
    curve_grid = _apply(grid_basis, coefficients)
    curve_points = _apply(basis, coefficients)
    count = integer_parameter(parameters, "bootstrap_draws")
    draws: list[list[float]] = wild_residual_draws(
        curve_points, direct.reml.fit.resid.tolist(), count, rng
    ).tolist()
    curves = [_apply(grid_basis, _apply(operator, draw)) for draw in draws]
    band = max_t_band(curve_grid, curves, BAND_LEVEL)
    low, high = band.low.tolist(), band.high.tolist()
    first = design.days[0]
    return Q2Figure(
        points=tuple(
            FigurePoint(day, r) for day, r in zip(design.days, residuals, strict=True)
        ),
        curve=tuple(
            FigureCurve(
                first + timedelta(days=int(g)),
                estimate,
                float(lo),
                float(hi),
                g > knots[3],
            )
            for g, estimate, lo, hi in zip(grid, curve_grid, low, high, strict=True)
        ),
        knots=tuple(knots),
        draws=count,
        key=FIGURE_KEY,
    )
