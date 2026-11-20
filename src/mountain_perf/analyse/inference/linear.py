"""Moindres carrés ordinaires et généralisés, intervalle de Student, tendance en
fraction par an (AN3-1, ``docs/decisions/0021``). Aucun inverse explicite dans un
calcul d'estimation : QR, Cholesky, puis des résolutions triangulaires ; l'inverse
n'apparaît que comme sortie (une covariance), calculée par résolution."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy
import scipy.linalg
import scipy.stats

from mountain_perf.analyse.inference.base import (
    FloatArray,
    FractionInterval,
    InferenceError,
    Interval,
    as_matrix,
    as_vector,
    check_design,
    check_level,
    frozen,
)

SYMMETRY_TOLERANCE = 1e-12
"""Écart relatif toléré entre ``V`` et sa transposée, rapporté à ``max |V|``."""


@dataclass(frozen=True)
class LinearFit:
    """Un ajustement linéaire : ``coef`` (p), ``cov`` (p × p), ``resid`` (n,
    ``y − X·coef``, sur l'échelle d'origine), ``df = n − p``, ``scale`` (la variance
    résiduelle de l'échelle de ``cov`` ; 1 pour les moindres carrés généralisés)."""

    coef: FloatArray
    cov: FloatArray
    resid: FloatArray
    df: int
    scale: float


def design_and_response(
    X: object,  # noqa: N803
    y: object,
) -> tuple[FloatArray, FloatArray]:
    """``X`` (n × p, de plein rang, ``n > p``) et ``y`` (n), contrôlés."""
    design = as_matrix(X, "X")
    response = as_vector(y, "y")
    if response.shape[0] != design.shape[0]:
        raise InferenceError(
            f"y : {response.shape[0]} valeurs pour {design.shape[0]} lignes de X"
        )
    check_design(design)
    return design, response


def _least_squares(
    design: FloatArray, response: FloatArray
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """``coef``, ``R`` et ``Q`` de la QR réduite de ``design``."""
    q, r = numpy.linalg.qr(design)
    coef = scipy.linalg.solve_triangular(r, q.T @ response)
    return numpy.asarray(coef, dtype=numpy.float64), r, q


def _unscaled_cov(r: FloatArray) -> FloatArray:
    """``(XᵀX)⁻¹ = R⁻¹R⁻ᵀ``, par résolution sur ``R``."""
    r_inv = scipy.linalg.solve_triangular(r, numpy.eye(r.shape[0]))
    cov = r_inv @ r_inv.T
    return numpy.asarray((cov + cov.T) / 2.0, dtype=numpy.float64)


def ols(X: object, y: object) -> LinearFit:  # noqa: N803
    """Les moindres carrés ordinaires : ``coef`` par QR, ``scale = rᵀr / (n − p)``,
    ``cov = scale · (XᵀX)⁻¹``."""
    design, response = design_and_response(X, y)
    n, p = design.shape
    coef, r, _ = _least_squares(design, response)
    resid = response - design @ coef
    scale = float(resid @ resid) / (n - p)
    return LinearFit(
        coef=frozen(coef),
        cov=frozen(scale * _unscaled_cov(r)),
        resid=frozen(resid),
        df=n - p,
        scale=scale,
    )


def cholesky_of(V: object, n: int) -> FloatArray:  # noqa: N803
    """Le facteur de Cholesky inférieur de ``V`` (n × n), symétrique (à
    ``1e−12 · max |V|``) et définie positive ; sinon ``InferenceError``."""
    cov = as_matrix(V, "V")
    if cov.shape != (n, n):
        raise InferenceError(f"V : {n} × {n} attendue, {cov.shape} reçue")
    if float(numpy.max(numpy.abs(cov - cov.T))) > SYMMETRY_TOLERANCE * float(
        numpy.max(numpy.abs(cov))
    ):
        raise InferenceError("V n'est pas symétrique")
    try:
        lower = numpy.linalg.cholesky(cov)
    except numpy.linalg.LinAlgError as error:
        raise InferenceError("V n'est pas définie positive") from error
    return numpy.asarray(lower, dtype=numpy.float64)


def _whitened(
    design: FloatArray, response: FloatArray, lower: FloatArray
) -> tuple[FloatArray, FloatArray]:
    x_w = scipy.linalg.solve_triangular(lower, design, lower=True)
    y_w = scipy.linalg.solve_triangular(lower, response, lower=True)
    return (
        numpy.asarray(x_w, dtype=numpy.float64),
        numpy.asarray(y_w, dtype=numpy.float64),
    )


def gls(X: object, y: object, V: object) -> LinearFit:  # noqa: N803
    """Les moindres carrés généralisés à ``V`` connue : blanchiment par ``L⁻¹``
    (``V = LLᵀ``), MCO des données blanchies ; ``cov = (XᵀV⁻¹X)⁻¹`` sans facteur
    d'échelle, ``scale = 1`` ; ``resid = y − X·coef``, sur l'échelle d'origine."""
    design, response = design_and_response(X, y)
    n, p = design.shape
    lower = cholesky_of(V, n)
    x_w, y_w = _whitened(design, response, lower)
    coef, r, _ = _least_squares(x_w, y_w)
    return LinearFit(
        coef=frozen(coef),
        cov=frozen(_unscaled_cov(r)),
        resid=frozen(response - design @ coef),
        df=n - p,
        scale=1.0,
    )


def gls_operator(X: object, V: object) -> FloatArray:  # noqa: N803
    """La matrice ``A`` (p × n) telle que ``coef = A·y`` pour tout ``y`` :
    ``A = (XᵀV⁻¹X)⁻¹XᵀV⁻¹ = R⁻¹Qᵀ L⁻¹``, par résolutions."""
    design = as_matrix(X, "X")
    check_design(design)
    n = design.shape[0]
    lower = cholesky_of(V, n)
    x_w = scipy.linalg.solve_triangular(lower, design, lower=True)
    q, r = numpy.linalg.qr(x_w)
    left = scipy.linalg.solve_triangular(r, q.T)
    operator = scipy.linalg.solve_triangular(lower, left.T, lower=True, trans="T").T
    return numpy.array(operator, dtype=numpy.float64)


def student_interval(estimate: float, se: float, df: int, level: float) -> Interval:
    """``estimate ± t(1 − (1 − level)/2 ; df) · se``."""
    if not (math.isfinite(se) and se > 0.0):
        raise InferenceError(f"se : un réel > 0 est attendu ({se})")
    if not math.isfinite(estimate):
        raise InferenceError(f"estimate : non fini ({estimate})")
    if isinstance(df, bool) or not isinstance(df, int) or df < 1:
        raise InferenceError(f"df : un entier ≥ 1 est attendu ({df!r})")
    check_level(level)
    quantile = float(scipy.stats.t.ppf(1.0 - (1.0 - level) / 2.0, df))
    return Interval(estimate - quantile * se, estimate + quantile * se)


def fraction_per_year(b_per_day: float) -> float:
    """La tendance en fraction par an (0,05 = 5 %) d'une pente en log par jour :
    ``expm1(365,25 · b_per_day)`` ; ``math.inf`` quand le calcul déborde (sa limite,
    AN3-4)."""
    if not math.isfinite(b_per_day):
        raise InferenceError(f"b_per_day : une pente finie est attendue ({b_per_day})")
    try:
        return math.expm1(365.25 * b_per_day)
    except OverflowError:
        return math.inf


def fraction_per_year_interval(interval: Interval) -> FractionInterval:
    """``fraction_per_year`` sur chaque borne (la transformation est croissante) ;
    la borne haute, ou les deux, peuvent valoir +∞."""
    return FractionInterval(
        fraction_per_year(interval.low), fraction_per_year(interval.high)
    )


def whiten(
    X: object,  # noqa: N803
    y: object,
    V: object,  # noqa: N803
) -> tuple[FloatArray, FloatArray]:
    """``(L⁻¹X, L⁻¹y)``, ``V = LLᵀ`` (``cholesky_of``), par résolution triangulaire,
    jamais l'inverse de ``L`` (AN3-3b). ``X`` n × p, ``y`` n, ``V`` n × n ; refuse des
    dimensions qui ne s'accordent pas, ``V`` non symétrique ou non définie positive ;
    ne contrôle pas le plan (``n ≤ p``, rang) : ``whiten`` ne régresse pas."""
    design = as_matrix(X, "X")
    response = as_vector(y, "y")
    n = design.shape[0]
    if response.shape[0] != n:
        raise InferenceError(f"y : {response.shape[0]} valeurs pour {n} lignes de X")
    lower = cholesky_of(V, n)
    return _whitened(design, response, lower)


def student_pvalue(estimate: float, se: float, df: int) -> float:
    """La p-valeur bilatérale de Student ``2 · P(T_df ≥ |estimate / se|)`` (AN3-3b) ;
    ``se > 0`` fini, ``estimate`` fini, ``df ≥ 1`` entier, sinon ``InferenceError``."""
    if not (math.isfinite(se) and se > 0.0):
        raise InferenceError(f"se : un réel > 0 est attendu ({se})")
    if not math.isfinite(estimate):
        raise InferenceError(f"estimate : non fini ({estimate})")
    if isinstance(df, bool) or not isinstance(df, int) or df < 1:
        raise InferenceError(f"df : un entier ≥ 1 est attendu ({df!r})")
    return float(2.0 * scipy.stats.t.sf(abs(estimate / se), df))
