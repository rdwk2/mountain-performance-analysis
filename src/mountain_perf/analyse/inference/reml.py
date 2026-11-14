"""La covariance à trois composantes ``V = diag(d) + τ²·I + σ²_u·exp(−Δ/φ)`` et son
estimation par REML (AN3-1, ``docs/decisions/0021``) : profil sur une grille
géométrique de 12 valeurs de ``φ``, puis un affinement gardé s'il fait au moins aussi
bien."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy
import scipy.linalg
import scipy.optimize

from mountain_perf.analyse.inference.base import (
    FloatArray,
    InferenceError,
    as_vector,
)
from mountain_perf.analyse.inference.linear import (
    LinearFit,
    cholesky_of,
    design_and_response,
    gls,
    ols,
)

GRID_SIZE = 12
"""Le nombre de valeurs de ``φ`` du profil, bornes comprises."""

AT_ZERO = 1e-8
"""Seuil relatif (à l'échelle ``s0``) d'une composante de variance à 0."""

AT_BOUND = 1e-6
"""Seuil relatif d'un ``φ`` à sa borne."""

IDENTIFIED_SHARE = 0.01
"""La part ``s2u / (tau2 + s2u)`` estimée sous laquelle ``φ`` n'est pas identifié."""


def _non_negative(value: float, name: str) -> float:
    if not (math.isfinite(value) and value >= 0.0):
        raise InferenceError(f"{name} : un réel ≥ 0 est attendu ({value})")
    return float(value)


def three_component_cov(
    t: object, d: object, tau2: float, s2u: float, phi: float
) -> FloatArray:
    """``V_ij = (d_i + tau2)·[i = j] + s2u · exp(−|t_i − t_j| / phi)`` ; ``t`` en jours,
    ``d ≥ 0``, ``tau2 ≥ 0``, ``s2u ≥ 0``, ``phi > 0``."""
    days = as_vector(t, "t")
    known = as_vector(d, "d")
    if known.shape != days.shape:
        raise InferenceError(f"d : {known.shape[0]} valeurs pour {days.shape[0]} jours")
    if float(known.min()) < 0.0:
        raise InferenceError("d : valeurs négatives")
    tau2 = _non_negative(tau2, "tau2")
    s2u = _non_negative(s2u, "s2u")
    if not (math.isfinite(phi) and phi > 0.0):
        raise InferenceError(f"phi : un réel > 0 est attendu ({phi})")
    gaps = numpy.abs(days[:, None] - days[None, :])
    cov = s2u * numpy.exp(-gaps / phi)
    cov[numpy.diag_indices_from(cov)] += known + tau2
    return numpy.asarray(cov, dtype=numpy.float64)


def reml_criterion(X: object, y: object, V: object) -> float:  # noqa: N803
    """``ln det V + ln det(XᵀV⁻¹X) + r̃ᵀr̃``, ``r̃ = L⁻¹(y − X·β̂_GLS)`` : ``−2`` fois la
    log-vraisemblance restreinte, sans la constante ``(n − p)·ln 2π``."""
    design, response = design_and_response(X, y)
    lower = cholesky_of(V, design.shape[0])
    x_w = scipy.linalg.solve_triangular(lower, design, lower=True)
    y_w = scipy.linalg.solve_triangular(lower, response, lower=True)
    q, r = numpy.linalg.qr(x_w)
    coef = scipy.linalg.solve_triangular(r, q.T @ y_w)
    whitened = y_w - x_w @ coef
    log_det_v = 2.0 * float(numpy.sum(numpy.log(numpy.diag(lower))))
    log_det_info = 2.0 * float(numpy.sum(numpy.log(numpy.abs(numpy.diag(r)))))
    return log_det_v + log_det_info + float(whitened @ whitened)


@dataclass(frozen=True)
class RemlFit:
    """L'estimation REML : ``tau2``, ``s2u``, ``phi``, ``criterion`` au point retenu ;
    ``fit``, la GLS à ``V̂`` ; les drapeaux de bornes et d'identification ;
    ``phi_bounds`` ; ``profile``, les 12 couples ``(φ_k, meilleur critère à φ_k)``,
    dans l'ordre de la grille."""

    tau2: float
    s2u: float
    phi: float
    criterion: float
    fit: LinearFit
    tau2_at_zero: bool
    s2u_at_zero: bool
    phi_at_lower: bool
    phi_at_upper: bool
    phi_identified: bool
    phi_bounds: tuple[float, float]
    profile: tuple[tuple[float, float], ...]


def _checked_bounds(phi_bounds: tuple[float, float]) -> tuple[float, float]:
    if len(phi_bounds) != 2:
        raise InferenceError("phi_bounds : un couple (lo, hi) est attendu")
    lo, hi = float(phi_bounds[0]), float(phi_bounds[1])
    if not (math.isfinite(lo) and math.isfinite(hi) and 0.0 < lo < hi):
        raise InferenceError(f"phi_bounds : 0 < lo < hi attendu ({lo}, {hi})")
    return lo, hi


def reml_fit(
    X: object,  # noqa: N803
    y: object,
    t: object,
    d: object,
    phi_bounds: tuple[float, float],
) -> RemlFit:
    """L'estimation REML de ``(τ², σ²_u, φ)``, ``φ`` borné par ``phi_bounds``, selon
    l'algorithme du brief (§ 6.4) : variables réduites ``u = τ²/s0``, ``v = σ²_u/s0`` ;
    profil sur 12 valeurs géométriques de ``φ`` ; affinement en ``(u, v, φ)`` gardé
    s'il fait au moins aussi bien."""
    lo, hi = _checked_bounds(phi_bounds)
    design, response = design_and_response(X, y)
    n = design.shape[0]
    days = as_vector(t, "t")
    known = as_vector(d, "d")
    if days.shape[0] != n:
        raise InferenceError(f"t : {days.shape[0]} valeurs pour {n} lignes")
    if known.shape[0] != n:
        raise InferenceError(f"d : {known.shape[0]} valeurs pour {n} lignes")
    if float(known.min()) < 0.0:
        raise InferenceError("d : valeurs négatives")
    s0 = ols(design, response).scale
    if s0 == 0.0:
        raise InferenceError("ajustement exact : la variance résiduelle est nulle")
    m = max(s0 - float(numpy.mean(known)), 0.01 * s0)
    start = m / (2.0 * s0)

    def criterion_at(u: float, v: float, phi: float) -> float:
        try:
            cov = three_component_cov(days, known, u * s0, v * s0, phi)
            value = reml_criterion(design, response, cov)
        except InferenceError:
            return math.inf
        return value if math.isfinite(value) else math.inf

    profile: list[tuple[float, float]] = []
    best: tuple[float, float, float, float] | None = None
    for k in range(GRID_SIZE):
        phi_k = lo * (hi / lo) ** (k / (GRID_SIZE - 1))

        def grid_criterion(w: FloatArray, phi_k: float = phi_k) -> float:
            return criterion_at(float(w[0]), float(w[1]), phi_k)

        result = scipy.optimize.minimize(
            grid_criterion,
            numpy.array([start, start]),
            method="L-BFGS-B",
            bounds=[(0, None), (0, None)],
            options={"maxiter": 500, "ftol": 1e-12, "gtol": 1e-9},
        )
        value = float(result.fun)
        profile.append((phi_k, value))
        if math.isfinite(value) and (best is None or value < best[0]):
            best = (value, float(result.x[0]), float(result.x[1]), phi_k)
    if best is None:
        raise InferenceError("aucun point de la grille de φ n'a de critère fini")

    def refine_criterion(w: FloatArray) -> float:
        return criterion_at(float(w[0]), float(w[1]), float(w[2]))

    refined = scipy.optimize.minimize(
        refine_criterion,
        numpy.array([best[1], best[2], best[3]]),
        method="L-BFGS-B",
        bounds=[(0, None), (0, None), (lo, hi)],
        options={"maxiter": 500, "ftol": 1e-12, "gtol": 1e-9},
    )
    if float(refined.fun) <= best[0]:
        u, v, phi = (float(value) for value in refined.x)
    else:
        u, v, phi = best[1], best[2], best[3]
    tau2, s2u = u * s0, v * s0
    cov_hat = three_component_cov(days, known, tau2, s2u, phi)
    total = tau2 + s2u
    return RemlFit(
        tau2=tau2,
        s2u=s2u,
        phi=phi,
        criterion=reml_criterion(design, response, cov_hat),
        fit=gls(design, response, cov_hat),
        tau2_at_zero=tau2 <= AT_ZERO * s0,
        s2u_at_zero=s2u <= AT_ZERO * s0,
        phi_at_lower=phi <= lo * (1.0 + AT_BOUND),
        phi_at_upper=phi >= hi * (1.0 - AT_BOUND),
        phi_identified=total > 0.0 and s2u / total >= IDENTIFIED_SHARE,
        phi_bounds=(lo, hi),
        profile=tuple(profile),
    )
