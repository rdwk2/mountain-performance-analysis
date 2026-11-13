"""Erreurs groupées : la covariance CR2 de Bell et McCaffrey et le bootstrap sauvage
par grappes, bootstrap-t non restreint studentisé par CR2 (AN3-1,
``docs/decisions/0021``, ``docs/analyse/CHARTE.md`` § 4 bis.2) : poids de Webb sous
12 grappes, Rademacher au-delà (tous les tirages, chacun une fois, quand il y en a au
plus autant que demandé) ; refus sous 10 grappes."""

from __future__ import annotations

import itertools
import math

import numpy
import numpy.typing
import scipy.linalg

from mountain_perf.analyse.inference.base import (
    FloatArray,
    InferenceError,
    Interval,
    as_matrix,
    as_vector,
    check_level,
    order_quantile,
)
from mountain_perf.analyse.inference.linear import design_and_response, ols

WEBB: tuple[float, ...] = (
    -math.sqrt(1.5),
    -1.0,
    -math.sqrt(0.5),
    math.sqrt(0.5),
    1.0,
    math.sqrt(1.5),
)
"""Les six poids de Webb, dans cet ordre (moyenne 0, variance 1)."""

LEVERAGE_TOLERANCE = 1e-12
"""Valeur propre de ``I − H_gg`` sous laquelle une grappe a un levier de 1."""

MIN_CLUSTERS = 10
"""Sous 10 grappes, on agrège (charte § 4 bis.2)."""

WEBB_BELOW = 12
"""Poids de Webb sous 12 grappes, Rademacher au-delà."""


def _labels(clusters: object, n: int) -> numpy.typing.NDArray[numpy.intp]:
    """L'indice de grappe de chaque ligne, grappes dans l'ordre de ``numpy.unique``."""
    labels = numpy.asarray(clusters)
    if labels.ndim != 1 or labels.shape[0] != n:
        raise InferenceError(f"clusters : {n} étiquettes attendues")
    if not numpy.issubdtype(labels.dtype, numpy.integer):
        raise InferenceError("clusters : des étiquettes entières sont attendues")
    _, inverse = numpy.unique(labels, return_inverse=True)
    return numpy.asarray(inverse, dtype=numpy.intp)


def _cr2(
    design: FloatArray, resid: FloatArray, groups: numpy.typing.NDArray[numpy.intp]
) -> FloatArray:
    count = int(groups.max()) + 1
    if count < 2:
        raise InferenceError("clusters : au moins 2 grappes sont attendues")
    _, r = numpy.linalg.qr(design)
    r_inv = scipy.linalg.solve_triangular(r, numpy.eye(r.shape[0]))
    bread = r_inv @ r_inv.T
    meat = numpy.zeros_like(bread)
    for g in range(count):
        rows = groups == g
        x_g = design[rows]
        leverage = x_g @ bread @ x_g.T
        eigenvalues, eigenvectors = numpy.linalg.eigh(
            numpy.eye(x_g.shape[0]) - leverage
        )
        if float(eigenvalues.min()) <= LEVERAGE_TOLERANCE:
            raise InferenceError("une grappe a un levier de 1")
        adjust = (eigenvectors / numpy.sqrt(eigenvalues)) @ eigenvectors.T
        score = x_g.T @ (adjust @ resid[rows])
        meat += numpy.outer(score, score)
    cov = bread @ meat @ bread
    return numpy.asarray((cov + cov.T) / 2.0, dtype=numpy.float64)


def cr2_cov(X: object, resid: object, clusters: object) -> FloatArray:  # noqa: N803
    """La covariance CR2 des coefficients MCO :
    ``M · (Σ_g X_gᵀ A_g e_g e_gᵀ A_g X_g) · M``, ``M = (XᵀX)⁻¹``,
    ``A_g = (I − H_gg)^(−1/2)`` symétrique ; au moins 2 grappes."""
    design = as_matrix(X, "X")
    residuals = as_vector(resid, "resid")
    if residuals.shape[0] != design.shape[0]:
        raise InferenceError("resid : une valeur par ligne de X est attendue")
    return _cr2(design, residuals, _labels(clusters, design.shape[0]))


def cluster_weights(
    kind: str,
    G: int,  # noqa: N803
    B: int,  # noqa: N803
    rng: numpy.random.Generator,
) -> FloatArray:
    """Les poids du bootstrap sauvage par grappes (une ligne par tirage, une colonne
    par grappe) : ``"webb"``, un seul ``rng.integers(0, 6, size=(B, G))`` ;
    ``"rademacher"``, les ``2**G`` lignes de l'énumération exacte si ``2**G ≤ B``
    (``rng`` n'est pas lu), sinon un seul ``rng.integers(0, 2, size=(B, G))``."""
    if G < 1 or B < 1:
        raise InferenceError(f"G et B : des entiers ≥ 1 sont attendus ({G}, {B})")
    if kind == "webb":
        return numpy.asarray(WEBB, dtype=numpy.float64)[rng.integers(0, 6, size=(B, G))]
    if kind == "rademacher":
        if 2**G <= B:
            return numpy.array(
                list(itertools.product((-1.0, 1.0), repeat=G)), dtype=numpy.float64
            )
        signs = 2 * rng.integers(0, 2, size=(B, G)) - 1
        return numpy.asarray(signs, dtype=numpy.float64)
    raise InferenceError(f"kind : « webb » ou « rademacher » attendu ({kind!r})")


def wild_cluster_interval(
    X: object,  # noqa: N803
    y: object,
    clusters: object,
    j: int,
    level: float,
    B: int,  # noqa: N803
    rng: numpy.random.Generator,
) -> Interval:
    """L'intervalle du bootstrap-t sauvage par grappes, non restreint, du coefficient
    ``j`` : ``t*_b = (coef*_j − coef_j) / se*_b``, ``se`` par CR2,
    ``c = order_quantile(|t*|, level)``, ``coef_j ± c·se``."""
    design, response = design_and_response(X, y)
    check_level(level)
    if not 0 <= j < design.shape[1]:
        raise InferenceError(f"j : hors des coefficients ({j})")
    groups = _labels(clusters, design.shape[0])
    count = int(groups.max()) + 1
    if count < MIN_CLUSTERS:
        raise InferenceError("sous 10 grappes, on agrège : charte § 4 bis.2")
    kind = "webb" if count < WEBB_BELOW else "rademacher"
    fit = ols(design, response)
    se = math.sqrt(float(_cr2(design, fit.resid, groups)[j, j]))
    if se == 0.0:
        raise InferenceError("se : l'erreur-type CR2 est nulle")
    weights = cluster_weights(kind, count, B, rng)
    fitted = design @ fit.coef
    statistics = numpy.empty(weights.shape[0])
    for b in range(weights.shape[0]):
        draw = ols(design, fitted + weights[b, groups] * fit.resid)
        se_star = math.sqrt(float(_cr2(design, draw.resid, groups)[j, j]))
        if se_star == 0.0:
            raise InferenceError("se* : une erreur-type bootstrap est nulle")
        statistics[b] = (float(draw.coef[j]) - float(fit.coef[j])) / se_star
    critical = order_quantile(numpy.abs(statistics), level)
    estimate = float(fit.coef[j])
    return Interval(estimate - critical * se, estimate + critical * se)
