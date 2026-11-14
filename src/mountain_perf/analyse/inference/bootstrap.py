"""Le bootstrap paramétrique, le bootstrap sauvage des résidus et la bande simultanée
max-t (AN3-1, ``docs/decisions/0021``). Chaque fonction qui tire le fait en un seul
appel du générateur."""

from __future__ import annotations

from dataclasses import dataclass

import numpy

from mountain_perf.analyse.inference.base import (
    FloatArray,
    InferenceError,
    as_matrix,
    as_vector,
    check_level,
    frozen,
    order_quantile,
)
from mountain_perf.analyse.inference.linear import cholesky_of


def _check_draws(B: int) -> None:  # noqa: N803
    if isinstance(B, bool) or not isinstance(B, int) or B < 1:
        raise InferenceError(f"B : un entier ≥ 1 est attendu ({B!r})")


def parametric_draws(
    mean: object,
    V: object,  # noqa: N803
    B: int,  # noqa: N803
    rng: numpy.random.Generator,
) -> FloatArray:
    """``B`` tirages (B × n) de la loi normale de moyenne ``mean`` et de covariance
    ``V`` : ``Y = mean + Z·Lᵀ``, ``V = LLᵀ``, ``Z`` en un seul
    ``rng.standard_normal(size=(B, n))``."""
    centre = as_vector(mean, "mean")
    _check_draws(B)
    lower = cholesky_of(V, centre.shape[0])
    normals = rng.standard_normal(size=(B, centre.shape[0]))
    return numpy.asarray(centre + normals @ lower.T, dtype=numpy.float64)


def wild_residual_draws(
    fitted: object,
    resid: object,
    B: int,  # noqa: N803
    rng: numpy.random.Generator,
) -> FloatArray:
    """``B`` tirages (B × n) du bootstrap sauvage des résidus : un poids de Rademacher
    par ligne, appliqué au résidu tel quel, sans correction de levier :
    ``Y = fitted + S·resid``, ``S`` en un seul ``rng.integers(0, 2, size=(B, n))``."""
    centre = as_vector(fitted, "fitted")
    residuals = as_vector(resid, "resid")
    if residuals.shape != centre.shape:
        raise InferenceError("resid : une valeur par valeur ajustée est attendue")
    _check_draws(B)
    signs = 2 * rng.integers(0, 2, size=(B, centre.shape[0])) - 1
    return numpy.asarray(centre + signs * residuals, dtype=numpy.float64)


@dataclass(frozen=True)
class Band:
    """Une bande simultanée sur une grille : ``low``, ``high``, la valeur critique,
    et les points de grille sans dispersion (exclus du maximum, où la bande vaut
    l'estimation)."""

    low: FloatArray
    high: FloatArray
    critical: float
    excluded: tuple[int, ...]


def max_t_band(estimate: object, draws: object, level: float) -> Band:
    """La bande max-t : ``se* = draws.std(axis=0, ddof=1)`` ;
    ``T_b = max_x |draws[b, x] − estimate[x]| / se*[x]`` sur les points de ``se* > 0`` ;
    ``critical = order_quantile(T, level)`` ; ``estimate ± critical·se*``."""
    centre = as_vector(estimate, "estimate")
    curves = as_matrix(draws, "draws")
    check_level(level)
    if curves.shape[1] != centre.shape[0]:
        raise InferenceError("draws : une colonne par point de grille est attendue")
    if curves.shape[0] < 2:
        raise InferenceError("draws : au moins 2 tirages sont attendus")
    spread = curves.std(axis=0, ddof=1)
    kept = spread > 0.0
    if not numpy.any(kept):
        raise InferenceError("draws : aucun point de grille n'a de dispersion")
    ratios = numpy.abs(curves[:, kept] - centre[kept]) / spread[kept]
    critical = order_quantile(ratios.max(axis=1), level)
    return Band(
        low=frozen(centre - critical * spread),
        high=frozen(centre + critical * spread),
        critical=critical,
        excluded=tuple(int(i) for i in numpy.flatnonzero(~kept)),
    )
