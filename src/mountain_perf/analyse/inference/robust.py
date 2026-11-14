"""La régression de Huber (AN3-1, ``docs/decisions/0021``) : ``c = 1,345``, échelle
par la MAD des résidus autour de 0 divisée par ``Φ⁻¹(3/4)``, réestimée à chaque
itération (ou fixée par l'appelant), moindres carrés pondérés itérés, covariance
« H1 » de Huber."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy
import scipy.linalg
import scipy.stats

from mountain_perf.analyse.inference.base import FloatArray, InferenceError, frozen
from mountain_perf.analyse.inference.linear import design_and_response, ols

CONVERGENCE = 1e-10
"""Arrêt quand ``max|β − β_avant| ≤ 1e−10 · max(1, max|β|)``."""


@dataclass(frozen=True)
class RobustFit:
    """L'ajustement de Huber : ``coef``, ``cov`` (H1), l'échelle finale ``scale``, les
    poids ``w(r/s)`` au point final, ``df = n − p``, et le nombre de moindres carrés
    pondérés faits."""

    coef: FloatArray
    cov: FloatArray
    scale: float
    weights: FloatArray
    df: int
    iterations: int


def _mad0(resid: FloatArray) -> float:
    """La MAD autour de 0, ``median(|r|) / Φ⁻¹(3/4)``."""
    return float(numpy.median(numpy.abs(resid))) / float(scipy.stats.norm.ppf(0.75))


def _checked_scale(value: float) -> float:
    if value == 0.0:
        raise InferenceError("échelle nulle : plus de la moitié des résidus à 0")
    return value


def _weights(z: FloatArray, c: float) -> FloatArray:
    magnitude = numpy.abs(z)
    outside = magnitude > c
    weights = numpy.ones_like(z)
    weights[outside] = c / magnitude[outside]
    return weights


def huber(
    X: object,  # noqa: N803
    y: object,
    c: float = 1.345,
    scale: float | None = None,
    max_iter: int = 100,
) -> RobustFit:
    """La régression de Huber par moindres carrés pondérés itérés, départ aux MCO ;
    l'échelle est ``scale`` si elle est donnée (fixe), sinon la MAD autour de 0,
    réestimée à chaque itération."""
    design, response = design_and_response(X, y)
    n, p = design.shape
    if not (math.isfinite(c) and c > 0.0):
        raise InferenceError(f"c : un réel > 0 est attendu ({c})")
    if scale is not None and not (math.isfinite(scale) and scale > 0.0):
        raise InferenceError(f"scale : un réel > 0 est attendu ({scale})")
    if max_iter < 1:
        raise InferenceError(f"max_iter : un entier ≥ 1 est attendu ({max_iter})")
    coef = numpy.array(ols(design, response).coef)
    resid = response - design @ coef
    s = _checked_scale(scale if scale is not None else _mad0(resid))
    iterations = 0
    for k in range(1, max_iter + 1):
        root = numpy.sqrt(_weights(resid / s, c))
        previous = coef
        coef = numpy.array(ols(root[:, None] * design, root * response).coef)
        resid = response - design @ coef
        if scale is None:
            s = _checked_scale(_mad0(resid))
        bound = CONVERGENCE * max(1.0, float(numpy.max(numpy.abs(coef))))
        if float(numpy.max(numpy.abs(coef - previous))) <= bound:
            iterations = k
            break
    else:
        raise InferenceError(f"huber : pas de convergence en {max_iter} itérations")
    z = resid / s
    inside = numpy.abs(z) <= c
    psi = numpy.where(inside, z, c * numpy.sign(z))
    psi_prime = inside.astype(numpy.float64)
    m = float(numpy.mean(psi_prime))
    if m == 0.0:
        raise InferenceError(
            "huber : aucun résidu dans [−c ; c], covariance impossible"
        )
    v = float(numpy.var(psi_prime))
    k_factor = 1.0 + (p / n) * v / m**2
    _, r = numpy.linalg.qr(design)
    r_inv = scipy.linalg.solve_triangular(r, numpy.eye(p))
    unscaled = r_inv @ r_inv.T
    cov = k_factor**2 * (float(psi @ psi) / (n - p)) * s**2 / m**2 * unscaled
    return RobustFit(
        coef=frozen(coef),
        cov=frozen(cov),
        scale=s,
        weights=frozen(_weights(z, c)),
        df=n - p,
        iterations=iterations,
    )
