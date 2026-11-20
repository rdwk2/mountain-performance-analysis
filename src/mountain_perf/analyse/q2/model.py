"""Le modèle de Q2 (AN3-3b, ``docs/decisions/0023``) : le budget et ses retraits, les
deux étages, la régression inverse, ``b_inv`` et la lecture bornée, ``κ``.

**Étage 1** (par régime, MCO sans constante, centré par journée) :
``s²_ε = rᵀr / (N − J − q)`` (le centrage consomme ``J`` degrés de liberté : ce
n'est pas ``LinearFit.scale``), ``d_s = s²_ε / n_s``. **Étage 2** : GLS de ``ȳ_s``
sur les colonnes retenues, ``V = diag(d_s) + τ²·I + s²_u·exp(−|Δt|/φ)``,
``(τ², s²_u, φ)`` par REML. **Inverse** : ``h̄_s`` sur les mêmes colonnes sans la FC,
plus ``ȳ_s`` ; ``b_inv = −d̂/k̂``.

Les matrices sont des listes Python ; tout calcul matriciel passe par
``mountain_perf.analyse.inference``. Les générateurs de numpy s'annotent ``Any`` :
numpy est fermé à ``inference/`` (``docs/decisions/0021``).
"""

from __future__ import annotations

import math
import multiprocessing
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
from functools import partial
from typing import Any

from mountain_perf.analyse.inference.base import (
    InferenceError,
    Interval,
    order_quantile,
)
from mountain_perf.analyse.inference.bootstrap import parametric_draws
from mountain_perf.analyse.inference.linear import (
    fraction_per_year,
    gls,
    gls_operator,
    ols,
    student_interval,
)
from mountain_perf.analyse.inference.readings import Reading, reading
from mountain_perf.analyse.inference.reml import RemlFit, reml_fit, three_component_cov
from mountain_perf.analyse.inference.spline import natural_cubic_basis
from mountain_perf.analyse.normals import integer_parameter
from mountain_perf.analyse.q2.data import HeartRate, Q2Climb, Q2Day
from mountain_perf.analyse.q2.routes import route_groups
from mountain_perf.schemas import ParameterSet
from mountain_perf.schemas.processed import ClimbRegime

YEAR_DAYS = 365.25
K_LEVEL = 0.95
"""Le niveau de l'intervalle de ``k̂`` : 95 %, toujours (plan § 7)."""

KNOTS_EQUAL = "nœuds de la spline de la FC égaux"
"""Le motif d'une spline de FC aux nœuds égaux (doute 2 du plan, validé)."""


class Measure(StrEnum):
    """Les deux mesures de Q2."""

    MP = "M-P"
    MS = "M-S"


class NotEstimableError(ValueError):
    """Une comparaison, un étage ou une variante ne s'estime pas : le message est le
    motif rapporté (Q-49 (i))."""


# --- les colonnes, le budget, les retraits ----------------------------------

CONSTANT = "constante"
DATE = "date"
SEASON = ("saison_sin", "saison_cos")
SPLINE = ("fc_1", "fc_2")
LINEAR_HR = "fc"
LOG_VAM = "log_vam"
KAPPA = "log_reserve"
EXTRA_PRECEDING_MOVING = "temps_avant"
HR_COLUMNS = (*SPLINE, LINEAR_HR)


def base_columns(
    measure: Measure, regime: ClimbRegime, withdrawals: Sequence[int]
) -> tuple[str, ...]:
    """Les colonnes de l'étage 2 sans les indicatrices de parcours, dans l'ordre du
    § 6.2, après les retraits ``withdrawals``."""
    columns: list[str] = [CONSTANT, DATE]
    if regime is not ClimbRegime.SKI_TOURING:
        columns += SEASON
    if measure is Measure.MP:
        columns += [LINEAR_HR] if 3 in withdrawals else SPLINE
    columns += ["log_gain", "pente", "altitude", "d_plus_avant"]
    if 1 not in withdrawals:
        columns.append("d_moins_avant")
    if 2 not in withdrawals:
        columns.append("heure")
    if 5 not in withdrawals:
        columns.append("e_s")
    return tuple(columns)


def day_in_sample(day: Q2Day, measure: Measure, step5_applied: bool) -> bool:
    """La journée est-elle dans l'échantillon de ``measure`` : l'étape 5 si elle
    s'applique ; pour M-S, l'étape 6 de journée et au moins une montée de réserve
    positive."""
    if step5_applied and day.step5 is not None:
        return False
    if measure is Measure.MS:
        return day.step6 is None and any(m is None for m in day.reserve)
    return True


@dataclass(frozen=True)
class ModelSpec:
    """Le modèle retenu d'une mesure et d'un régime : les retraits joués (dans
    l'ordre), les colonnes, ``n``, ``p``, l'estimabilité et son motif ; les journées
    des étapes 1 à 4 (``days``), leur présence dans l'échantillon, leur groupe de
    parcours, et les groupes qui ont une colonne."""

    measure: Measure
    regime: ClimbRegime
    withdrawals: tuple[int, ...]
    columns: tuple[str, ...]
    n: int
    p: int
    estimable: bool
    reason: str | None
    days: tuple[Q2Day, ...]
    in_sample: tuple[bool, ...]
    groups: tuple[int | None, ...]
    route_columns: tuple[int, ...]

    @property
    def step5_applied(self) -> bool:
        """L'étape 5 s'applique tant que le 5ᵉ retrait n'a pas joué."""
        return 5 not in self.withdrawals

    def units(self) -> tuple[Unit, ...]:
        """Les journées de l'échantillon, avec les montées de la mesure."""
        return tuple(
            unit_of(day, self.measure)
            for day, kept in zip(self.days, self.in_sample, strict=True)
            if kept
        )

    def group_of(self, day: date) -> int | None:
        """Le groupe de parcours de la journée ``day``."""
        for candidate, group in zip(self.days, self.groups, strict=True):
            if candidate.day == day:
                return group
        return None


def route_columns_of(
    groups: Sequence[int | None], in_sample: Sequence[bool]
) -> tuple[int, ...]:
    """Les groupes qui ont une indicatrice : ceux d'au moins une journée de
    l'échantillon ; si aucune journée de l'échantillon n'est « autre », le groupe de
    la première devient la référence (Q-49 (h))."""
    present = [g for g, s in zip(groups, in_sample, strict=True) if s]
    seen = sorted({g for g in present if g is not None})
    if present and None not in present:
        first = present[0]
        seen = [g for g in seen if g != first]
    return tuple(seen)


def model_spec(
    days: Sequence[Q2Day],
    measure: Measure,
    regime: ClimbRegime,
    parameters: ParameterSet,
) -> ModelSpec:
    """Le budget et les retraits (§ 6.2) : tant que ``n − p < min_residual_df``, le
    retrait suivant, cumulatif ; puis « non estimable » sous ``min_estimable_df``."""
    min_residual = integer_parameter(parameters, "min_residual_df")
    min_estimable = integer_parameter(parameters, "min_estimable_df")
    min_route = integer_parameter(parameters, "min_route_days")
    ordered = tuple(sorted(days, key=lambda d: d.day))
    withdrawals: tuple[int, ...] = ()
    while True:
        applied = 5 not in withdrawals
        in_sample = tuple(day_in_sample(d, measure, applied) for d in ordered)
        max_other = min_route - 1 if 4 in withdrawals else 1
        groups = route_groups(ordered, parameters, max_other, in_sample)
        routes = route_columns_of(groups, in_sample)
        columns = (
            *base_columns(measure, regime, withdrawals),
            *(f"parcours_{g}" for g in routes),
        )
        n, p = sum(in_sample), len(columns)
        if n - p >= min_residual or len(withdrawals) == 5:
            break
        withdrawals = (*withdrawals, len(withdrawals) + 1)
    estimable = n - p >= min_estimable
    return ModelSpec(
        measure=measure,
        regime=regime,
        withdrawals=withdrawals,
        columns=columns,
        n=n,
        p=p,
        estimable=estimable,
        reason=None
        if estimable
        else f"n − p = {n - p}, sous min_estimable_df = {min_estimable}",
        days=ordered,
        in_sample=in_sample,
        groups=groups,
        route_columns=routes,
    )


# --- les journées de l'estimation --------------------------------------------


@dataclass(frozen=True)
class Unit:
    """Une journée de l'estimation : la journée, ses montées gardées, et la réponse
    ``y`` (ln de la VAM) de chacune."""

    day: Q2Day
    climbs: tuple[Q2Climb, ...]
    y: tuple[float, ...]


def unit_of(day: Q2Day, measure: Measure) -> Unit:
    """La journée ``day`` de ``measure`` : toutes ses montées pour M-P ; pour M-S,
    celles dont la réserve ``h − r`` est positive."""
    climbs = tuple(
        c
        for c, m in zip(day.climbs, day.reserve, strict=True)
        if measure is Measure.MP or m is None
    )
    return Unit(day, climbs, tuple(c.y for c in climbs))


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _heart(climb: Q2Climb, heart_rate: HeartRate) -> float:
    value = climb.heart_rate(heart_rate)
    if value is None:
        raise NotEstimableError(f"FC {heart_rate.value} absente d'une montée")
    return value


def _ms_response(unit: Unit, heart_rate: HeartRate) -> list[float]:
    r = unit.day.r
    if r is None:
        raise NotEstimableError("normale absente d'une journée de M-S")
    return [
        y - math.log(_heart(c, heart_rate) - r)
        for c, y in zip(unit.climbs, unit.y, strict=True)
    ]


def _covariates(climb: Q2Climb) -> list[float]:
    return [
        climb.log_gain,
        climb.grade,
        climb.elevation_m,
        climb.preceding_ascent_m,
        climb.preceding_descent_m,
    ]


# --- l'étage 1 ---------------------------------------------------------------


@dataclass(frozen=True)
class StageOne:
    """L'étage 1 : ``sigma2`` (``s²_ε``), ``df`` (``N − J − q``), ``d`` par journée,
    les pentes intra-journée, et ``eta_within``, la pente de ``h`` (M-P)."""

    sigma2: float
    df: int
    d: tuple[float, ...]
    slopes: tuple[float, ...]
    eta_within: float | None = None


def centered_stage_one(
    groups: Sequence[Sequence[tuple[float, Sequence[float]]]],
) -> StageOne:
    """L'étage 1 centré par journée : ``groups`` donne, par journée, les couples
    (réponse, covariables) ; MCO sans constante des écarts aux moyennes de journée ;
    ``s²_ε = rᵀr / (N − J − q)``, ``d_s = s²_ε / n_s``. :class:`NotEstimableError` si
    ``N − J − q < 1`` ou si ``ols`` refuse la matrice."""
    if not groups or any(not g for g in groups):
        raise NotEstimableError("étage 1 : une journée sans montée")
    q = len(groups[0][0][1])
    total = sum(len(g) for g in groups)
    df = total - len(groups) - q
    if df < 1:
        raise NotEstimableError(f"étage 1 : N − J − q = {df}")
    rows: list[list[float]] = []
    response: list[float] = []
    for group in groups:
        y_bar = _mean([y for y, _ in group])
        x_bar = [_mean([x[k] for _, x in group]) for k in range(q)]
        for y, x in group:
            response.append(y - y_bar)
            rows.append([x[k] - x_bar[k] for k in range(q)])
    try:
        fit = ols(rows, response)
    except InferenceError as error:
        raise NotEstimableError(f"étage 1 : {error}") from error
    rss = sum(float(e) ** 2 for e in fit.resid.tolist())
    sigma2 = rss / df
    return StageOne(
        sigma2=sigma2,
        df=df,
        d=tuple(sigma2 / len(g) for g in groups),
        slopes=tuple(float(c) for c in fit.coef.tolist()),
    )


def stage_one(
    days: Sequence[Unit],
    measure: Measure,
    heart_rate: HeartRate = HeartRate.LAGGED,
) -> StageOne:
    """L'étage 1 de ``measure`` sur ``days`` : M-P, réponse ``y``, six covariables
    (``h`` d'abord, puis ln du gain, pente, altitude, D+ et D− avant) ; M-S, réponse
    ``y_MS = y − ln(h − r)``, les cinq mêmes sans ``h``."""
    groups: list[list[tuple[float, Sequence[float]]]] = []
    for unit in days:
        if measure is Measure.MP:
            groups.append(
                [
                    (y, [_heart(c, heart_rate), *_covariates(c)])
                    for c, y in zip(unit.climbs, unit.y, strict=True)
                ]
            )
        else:
            groups.append(
                [
                    (y, _covariates(c))
                    for c, y in zip(
                        unit.climbs, _ms_response(unit, heart_rate), strict=True
                    )
                ]
            )
    result = centered_stage_one(groups)
    if measure is Measure.MP:
        return replace(result, eta_within=result.slopes[0])
    return result


def response_stage_one(days: Sequence[Unit]) -> StageOne:
    """L'étage 1 de ``y`` aux cinq covariables de M-S (sans ``h``) : les ``d_s`` de
    ``κ`` (§ 7.5)."""
    return centered_stage_one(
        [
            [(y, _covariates(c)) for c, y in zip(u.climbs, u.y, strict=True)]
            for u in days
        ]
    )


def inverse_stage_one(
    days: Sequence[Unit], heart_rate: HeartRate = HeartRate.LAGGED
) -> StageOne:
    """L'étage 1 de ``h`` (Q-49 (a)) : réponse ``h``, covariables ``y`` et les cinq de
    M-S, centrées par journée ; ses ``d_s`` sont ceux de la régression inverse."""
    return centered_stage_one(
        [
            [
                (_heart(c, heart_rate), [y, *_covariates(c)])
                for c, y in zip(u.climbs, u.y, strict=True)
            ]
            for u in days
        ]
    )


# --- la matrice de l'étage 2 -------------------------------------------------


@dataclass(frozen=True)
class Design:
    """Une matrice de l'étage 2 : ``columns``, ``X`` (une ligne par journée), la
    réponse ``y``, ``t`` (jours depuis la première journée), ``d``, les dates, ``h̄``
    par journée, les nœuds de la spline de FC et les moyennes de chaque journée."""

    columns: tuple[str, ...]
    X: tuple[tuple[float, ...], ...]
    y: tuple[float, ...]
    t: tuple[float, ...]
    d: tuple[float, ...]
    days: tuple[date, ...]
    h_bar: tuple[float, ...]
    knots: tuple[float, float, float] | None

    @property
    def n(self) -> int:
        """Le nombre de journées."""
        return len(self.y)

    @property
    def p(self) -> int:
        """Le nombre de colonnes."""
        return len(self.columns)

    def index(self, column: str) -> int:
        """L'indice de ``column``."""
        return self.columns.index(column)

    def column(self, column: str) -> list[float]:
        """Les valeurs de ``column``."""
        k = self.index(column)
        return [row[k] for row in self.X]


def without_columns(design: Design, names: Sequence[str]) -> Design:
    """``design`` sans les colonnes ``names`` (celles qui n'y sont pas sont
    ignorées)."""
    keep = [k for k, c in enumerate(design.columns) if c not in names]
    return replace(
        design,
        columns=tuple(design.columns[k] for k in keep),
        X=tuple(tuple(row[k] for k in keep) for row in design.X),
    )


def with_column(
    design: Design, name: str, values: Sequence[float], position: int | None = None
) -> Design:
    """``design`` avec la colonne ``name`` (en ``position``, à la fin par défaut)."""
    at = len(design.columns) if position is None else position
    return replace(
        design,
        columns=(*design.columns[:at], name, *design.columns[at:]),
        X=tuple(
            (*row[:at], v, *row[at:]) for row, v in zip(design.X, values, strict=True)
        ),
    )


def spline_knots(
    h_bar: Sequence[float], parameters: ParameterSet
) -> tuple[float, float, float]:
    """Les nœuds de ``f`` : les quantiles ``spline_knot_low``, ``_mid``, ``_high`` de
    ``h̄_s`` (``order_quantile``)."""
    return (
        order_quantile(list(h_bar), parameters["spline_knot_low"]),
        order_quantile(list(h_bar), parameters["spline_knot_mid"]),
        order_quantile(list(h_bar), parameters["spline_knot_high"]),
    )


def heart_rate_columns(
    h_bar: Sequence[float], knots: tuple[float, float, float]
) -> list[tuple[float, float]]:
    """Les colonnes ``fc_1``, ``fc_2`` : ``natural_cubic_basis(h̄, nœuds)`` ;
    :class:`NotEstimableError` (:data:`KNOTS_EQUAL`) à nœuds égaux."""
    try:
        basis = natural_cubic_basis(list(h_bar), list(knots)).tolist()
    except InferenceError as error:
        raise NotEstimableError(KNOTS_EQUAL) from error
    return [(float(row[0]), float(row[1])) for row in basis]


def day_features(unit: Unit, heart_rate: HeartRate) -> dict[str, float]:
    """Les moyennes de journée de ``unit`` (sans pondération) : ``y``, ``h``, et les
    covariables de l'étage 2."""
    climbs = unit.climbs
    return {
        "y": _mean(unit.y),
        "h": _mean([_heart(c, heart_rate) for c in climbs]),
        "log_gain": _mean([c.log_gain for c in climbs]),
        "pente": _mean([c.grade for c in climbs]),
        "altitude": _mean([c.elevation_m for c in climbs]),
        "d_plus_avant": _mean([c.preceding_ascent_m for c in climbs]),
        "d_moins_avant": _mean([c.preceding_descent_m for c in climbs]),
        "heure": _mean([c.hour for c in climbs]) - 12.0,
        EXTRA_PRECEDING_MOVING: _mean([c.preceding_moving_s for c in climbs]),
    }


def season(day: date) -> tuple[float, float]:
    """``(sin, cos)`` de ``2π·j/365,25``, ``j`` le jour de l'année."""
    angle = 2 * math.pi * day.timetuple().tm_yday / YEAR_DAYS
    return (math.sin(angle), math.cos(angle))


def row_values(
    features: Mapping[str, float],
    t: float,
    day: date,
    e_s: float | None,
    group: int | None,
    route_columns: Sequence[int],
    fc: tuple[float, float],
) -> dict[str, float]:
    """Les valeurs de toutes les colonnes possibles d'une journée."""
    sin, cos = season(day)
    values = {
        CONSTANT: 1.0,
        DATE: t,
        SEASON[0]: sin,
        SEASON[1]: cos,
        SPLINE[0]: fc[0],
        SPLINE[1]: fc[1],
        LINEAR_HR: features["h"],
        "e_s": math.nan if e_s is None else e_s,
        **{k: features[k] for k in features if k not in ("y", "h")},
    }
    for g in route_columns:
        values[f"parcours_{g}"] = 1.0 if group == g else 0.0
    return values


def build_design(
    units: Sequence[Unit],
    spec: ModelSpec,
    stage1: StageOne,
    parameters: ParameterSet,
    *,
    heart_rate: HeartRate = HeartRate.LAGGED,
    columns: Sequence[str] | None = None,
    knots: tuple[float, float, float] | None = None,
    h_bar: Sequence[float] | None = None,
    response: Sequence[float] | None = None,
) -> Design:
    """La matrice de l'étage 2 de ``units`` (triées par date) sous ``spec`` : réponse
    ``ȳ_s`` (ou ``response``), ``t_s`` depuis la première journée, ``d_s`` de
    ``stage1``. ``h_bar`` remplace les ``h̄_s`` des colonnes de FC (scénario (4)) ;
    ``knots``, les nœuds (ceux du principal, pour les variantes)."""
    chosen = tuple(spec.columns if columns is None else columns)
    first = units[0].day.day
    features = [day_features(u, heart_rate) for u in units]
    hr = [f["h"] for f in features] if h_bar is None else list(h_bar)
    uses_spline = any(c in chosen for c in SPLINE)
    if uses_spline and knots is None:
        knots = spline_knots(hr, parameters)
    fc = (
        heart_rate_columns(hr, knots)
        if uses_spline and knots is not None
        else [(0.0, 0.0)] * len(units)
    )
    rows: list[tuple[float, ...]] = []
    for unit, feature, h, pair in zip(units, features, hr, fc, strict=True):
        values = row_values(
            {**feature, "h": h},
            float((unit.day.day - first).days),
            unit.day.day,
            unit.day.e_s,
            spec.group_of(unit.day.day),
            spec.route_columns,
            pair,
        )
        row = tuple(values[c] for c in chosen)
        if any(math.isnan(v) for v in row):
            raise NotEstimableError("une covariable absente d'une journée")
        rows.append(row)
    return Design(
        columns=chosen,
        X=tuple(rows),
        y=tuple(f["y"] for f in features) if response is None else tuple(response),
        t=tuple(float((u.day.day - first).days) for u in units),
        d=stage1.d,
        days=tuple(u.day.day for u in units),
        h_bar=tuple(hr),
        knots=knots if uses_spline else None,
    )


def phi_bounds(t: Sequence[float], parameters: ParameterSet) -> tuple[float, float]:
    """``(phi_min_days, max(t)/2)`` ; :class:`NotEstimableError` si la borne haute
    ne dépasse pas la basse."""
    low = parameters["phi_min_days"]
    high = max(t) / 2
    if high <= low:
        raise NotEstimableError(
            f"période trop courte pour φ : max(t)/2 = {high} ≤ {low}"
        )
    return (low, high)


def fit_reml(design: Design, parameters: ParameterSet) -> RemlFit:
    """Le REML de ``design`` (``φ`` borné par :func:`phi_bounds`) ;
    :class:`NotEstimableError` si ``reml_fit`` lève."""
    return _reml(design, parameters)


def _reml(design: Design, parameters: ParameterSet) -> RemlFit:
    bounds = phi_bounds(design.t, parameters)
    try:
        return reml_fit(
            [list(r) for r in design.X],
            list(design.y),
            list(design.t),
            list(design.d),
            bounds,
        )
    except InferenceError as error:
        raise NotEstimableError(f"REML : {error}") from error


def covariance(design: Design, fit: RemlFit) -> list[list[float]]:
    """``V̂`` de ``fit`` sur ``design``, en listes."""
    cov: list[list[float]] = three_component_cov(
        list(design.t), list(design.d), fit.tau2, fit.s2u, fit.phi
    ).tolist()
    return cov


# --- l'étage 2 direct ----------------------------------------------------------


@dataclass(frozen=True)
class DirectFit:
    """L'étage 2 direct : la matrice, le REML, ``b`` (log par jour), son erreur type
    et ``df = n − p``."""

    design: Design
    reml: RemlFit
    b: float
    se: float
    df: int


def fit_direct(
    design: Design, parameters: ParameterSet, coefficient: str = DATE
) -> DirectFit:
    """La GLS à ``V̂`` du REML ; ``b`` le coefficient de ``coefficient``."""
    if design.n - design.p < 1:
        raise NotEstimableError(f"n − p = {design.n - design.p}")
    fit = _reml(design, parameters)
    k = design.index(coefficient)
    return DirectFit(
        design=design,
        reml=fit,
        b=float(fit.fit.coef[k]),
        se=math.sqrt(float(fit.fit.cov[k, k])),
        df=design.n - design.p,
    )


def date_effect_at(
    X: Sequence[Sequence[float]],  # noqa: N803
    y: Sequence[float],
    V: Sequence[Sequence[float]],  # noqa: N803
    date_column: int,
) -> tuple[float, float]:
    """``(b, se)`` du coefficient ``date_column`` de la GLS à ``V`` connue."""
    fit = gls([list(r) for r in X], list(y), [list(r) for r in V])
    return (
        float(fit.coef[date_column]),
        math.sqrt(float(fit.cov[date_column, date_column])),
    )


# --- la régression inverse ---------------------------------------------------


@dataclass(frozen=True)
class InverseEffect:
    """``b_inv = −d̂/k̂``, ``k̂`` et son erreur type."""

    b_inv: float
    k: float
    se_k: float


def inverse_effect_at(
    X: Sequence[Sequence[float]],  # noqa: N803
    h: Sequence[float],
    V: Sequence[Sequence[float]],  # noqa: N803
    date_column: int,
    response_column: int,
) -> InverseEffect:
    """La régression de ``h̄`` sur ``X`` à ``V`` connue : ``b_inv = −d̂/k̂``, ``d̂``
    le coefficient de ``date_column``, ``k̂`` celui de ``response_column``."""
    fit = gls([list(r) for r in X], list(h), [list(r) for r in V])
    d_hat = float(fit.coef[date_column])
    k = float(fit.coef[response_column])
    if k == 0.0:
        raise NotEstimableError("k̂ = 0")
    return InverseEffect(
        b_inv=-d_hat / k,
        k=k,
        se_k=math.sqrt(float(fit.cov[response_column, response_column])),
    )


def k_contains_zero(k: float, se_k: float, df: int) -> bool:
    """L'intervalle de Student de ``k̂`` à 95 %, toujours (plan § 7), contient-il
    0 ?"""
    interval = student_interval(k, se_k, df, K_LEVEL)
    return interval.low <= 0.0 <= interval.high


@dataclass(frozen=True)
class InverseFit:
    """La régression inverse : la matrice (réponse ``h̄_s``, ``d_s`` de l'étage 1 de
    ``h``), le REML, ``b_inv``, ``k̂``, son erreur type, ``df`` et si l'intervalle à
    95 % de ``k̂`` contient 0."""

    design: Design
    reml: RemlFit
    b_inv: float
    k: float
    se_k: float
    df: int
    k_contains_zero: bool


def inverse_design(
    direct: Design, units: Sequence[Unit], heart_rate: HeartRate = HeartRate.LAGGED
) -> Design:
    """La matrice de l'inverse : les colonnes du direct sans la FC, plus ``ȳ_s``
    (``log_vam``) après ``date`` ; réponse ``h̄_s`` ; ``d_s = s²_h / n_s``."""
    stage = inverse_stage_one(units, heart_rate)
    base = without_columns(direct, HR_COLUMNS)
    design = with_column(base, LOG_VAM, list(direct.y), base.index(DATE) + 1)
    return replace(design, y=direct.h_bar, d=stage.d)


def _inverse_from(design: Design, fit: RemlFit) -> InverseFit:
    j, k_col = design.index(DATE), design.index(LOG_VAM)
    k = float(fit.fit.coef[k_col])
    if k == 0.0:
        raise NotEstimableError("k̂ = 0")
    se_k = math.sqrt(float(fit.fit.cov[k_col, k_col]))
    df = design.n - design.p
    return InverseFit(
        design=design,
        reml=fit,
        b_inv=-float(fit.fit.coef[j]) / k,
        k=k,
        se_k=se_k,
        df=df,
        k_contains_zero=k_contains_zero(k, se_k, df),
    )


def fit_inverse(design: Design, parameters: ParameterSet) -> InverseFit:
    """Le REML propre de l'inverse, ``b_inv`` et l'intervalle de ``k̂``."""
    if design.n - design.p < 1:
        raise NotEstimableError(f"inverse : n − p = {design.n - design.p}")
    return _inverse_from(design, _reml(design, parameters))


def fitted_mean(design: Design, fit: RemlFit) -> list[float]:
    """``X·β̂`` de ``fit``."""
    coef = [float(c) for c in fit.fit.coef.tolist()]
    return [sum(x * b for x, b in zip(row, coef, strict=True)) for row in design.X]


def refit_inverse_draw(
    X: Sequence[Sequence[float]],  # noqa: N803
    t: Sequence[float],
    d: Sequence[float],
    bounds: tuple[float, float],
    date_column: int,
    k_column: int,
    draw: Sequence[float],
) -> float | None:
    """Un tirage du bootstrap de ``b_inv`` sur le réel : ``reml_fit`` sur ``draw``
    (``V`` réestimée), ``b* = −d*/k*`` ; ``None`` si le REML lève ou si ``k* = 0``.
    Fonction de premier niveau : le pool « spawn » la reçoit liée par
    ``partial``."""
    try:
        fit = reml_fit([list(r) for r in X], list(draw), list(t), list(d), bounds)
    except InferenceError:
        return None
    k = float(fit.fit.coef[k_column])
    if k == 0.0:
        return None
    return -float(fit.fit.coef[date_column]) / k


@dataclass(frozen=True)
class InverseDraws:
    """Les tirages gardés de ``b_inv`` et le compte des tirages retirés."""

    draws: tuple[float, ...]
    removed: int


def _draw_block(
    design: Design, fit: RemlFit, count: int, rng: Any
) -> list[list[float]]:
    # ``rng`` : un numpy.random.Generator, annoté Any (numpy est fermé à inference/).
    block: list[list[float]] = parametric_draws(
        fitted_mean(design, fit), covariance(design, fit), count, rng
    ).tolist()
    return block


def inverse_bootstrap(
    inverse: InverseFit,
    parameters: ParameterSet,
    rng: Any,
    workers: int = 1,
) -> InverseDraws:
    """Le bootstrap paramétrique de ``b_inv`` sur le réel (§ 7.3) : ``bootstrap_draws``
    tirages de ``h̄*`` en un bloc, puis, pour chacun, ``reml_fit`` (``V``
    réestimée) ; les réajustements se répartissent sur ``workers`` processus sans
    changer la sortie. ``rng`` : un ``numpy.random.Generator`` (annoté ``Any`` : numpy
    est fermé à ``inference/``)."""
    design = inverse.design
    count = integer_parameter(parameters, "bootstrap_draws")
    block = _draw_block(design, inverse.reml, count, rng)
    refit = partial(
        refit_inverse_draw,
        [list(r) for r in design.X],
        list(design.t),
        list(design.d),
        phi_bounds(design.t, parameters),
        design.index(DATE),
        design.index(LOG_VAM),
    )
    if workers == 1:
        results = [refit(draw) for draw in block]
    else:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
            results = list(
                pool.map(refit, block, chunksize=max(1, count // (4 * workers)))
            )
    kept = tuple(r for r in results if r is not None)
    return InverseDraws(kept, len(results) - len(kept))


def fixed_v_bootstrap(inverse: InverseFit, count: int, rng: Any) -> InverseDraws:
    """Le bootstrap de ``b_inv`` de la simulation de puissance, à ``V`` fixée
    (Q-45) : ``A = gls_operator(X, V̂)`` une fois, puis ``coef* = A·h̄*`` (seules les
    lignes de ``date`` et de ``log_vam`` servent)."""
    design = inverse.design
    block = _draw_block(design, inverse.reml, count, rng)
    operator: list[list[float]] = gls_operator(
        [list(r) for r in design.X], covariance(design, inverse.reml)
    ).tolist()
    d_row = operator[design.index(DATE)]
    k_row = operator[design.index(LOG_VAM)]
    kept: list[float] = []
    for draw in block:
        k = sum(a * h for a, h in zip(k_row, draw, strict=True))
        if k == 0.0:
            continue
        kept.append(-sum(a * h for a, h in zip(d_row, draw, strict=True)) / k)
    return InverseDraws(tuple(kept), len(block) - len(kept))


# --- la lecture bornée -------------------------------------------------------

_DISCOVERY_SUFFIX = (
    "elle se lit comme un écart entre la période de découverte et la suite, saison"
    " non séparée ; exploratoire"
)
UNDECIDED_SENTENCE = "les données ne tranchent pas"


def percent(value: float) -> str:
    """``value`` (une fraction) en %, une décimale, virgule décimale, arrondi."""
    return format(100 * value, ".1f").replace(".", ",")


def _delta_text(delta: float) -> str:
    return format(100 * delta, "g").replace(".", ",")


def bounded_reading(
    direct: Interval | None,
    inverse: Interval | None,
    k_interval: Interval | None,
    delta: float,
    periods_declared: bool,
) -> tuple[Reading, str]:
    """La lecture et sa phrase (§ 7.4), sur l'échelle de la fraction par an : les
    deux intervalles (bornée), le direct seul (M-S, sensibilités), ou l'inverse seul
    (S18). Bornée : « non tranché » si ``k_interval`` contient 0."""
    intervals = [i for i in (direct, inverse) if i is not None]
    if not intervals:
        raise ValueError("au moins un intervalle est attendu")
    both = direct is not None and inverse is not None
    if both and k_interval is not None and k_interval.low <= 0.0 <= k_interval.high:
        return Reading.UNDECIDED, UNDECIDED_SENTENCE
    result = reading(intervals, delta)
    if both:
        which, nobody = (
            "(régressions directe et inverse)",
            "ni la régression directe ni l'inverse ne laissent place",
        )
    elif direct is not None:
        which, nobody = (
            "(régression directe)",
            "la régression directe ne laisse pas place",
        )
    else:
        which, nobody = (
            "(régression inverse)",
            "la régression inverse ne laisse pas place",
        )
    if result is Reading.ESTABLISHED:
        low = min(i.low for i in intervals)
        high = max(i.high for i in intervals)
        suffix = _DISCOVERY_SUFFIX if periods_declared else "exploratoire"
        return result, (
            f"la tendance est comprise entre {percent(low)} et {percent(high)} %/an "
            f"{which} ; {suffix}"
        )
    if result is Reading.NO_USEFUL_EFFECT:
        return result, f"{nobody} à un effet de {_delta_text(delta)} %/an"
    return result, UNDECIDED_SENTENCE


def fraction_interval(interval: Interval) -> Interval:
    """L'intervalle d'une pente en log par jour, en fraction par an."""
    return Interval(fraction_per_year(interval.low), fraction_per_year(interval.high))


# --- κ (S19, S20) --------------------------------------------------------------


@dataclass(frozen=True)
class KappaFit:
    """``κ̂``, son erreur type, ``df``, l'intervalle de Student à 95 % et le REML
    (``None`` à ``V`` connue)."""

    kappa: float
    se: float
    df: int
    interval: Interval
    reml: RemlFit | None


def kappa_design(
    spec: ModelSpec, parameters: ParameterSet, heart_rate: HeartRate = HeartRate.LAGGED
) -> Design:
    """La matrice de ``κ`` (§ 7.5) : sur l'échantillon de M-S, les colonnes de M-S
    plus ``ln(h̄_s − r_s)`` ; réponse ``ȳ_s`` (le log de la VAM de M-P) ; ``d_s`` de
    l'étage 1 de ``y`` aux cinq covariables de M-S."""
    if spec.measure is not Measure.MS:
        raise ValueError("κ se calcule sur le modèle de M-S")
    units = spec.units()
    if not units:
        raise NotEstimableError("aucune journée de M-S")
    stage = response_stage_one(units)
    design = build_design(units, spec, stage, parameters, heart_rate=heart_rate)
    reserve = []
    for unit, h in zip(units, design.h_bar, strict=True):
        r = unit.day.r
        if r is None or h - r <= 0:
            raise NotEstimableError("réserve de FC non positive en moyenne")
        reserve.append(math.log(h - r))
    return with_column(design, KAPPA, reserve)


def kappa_fit(
    spec: ModelSpec,
    parameters: ParameterSet,
    *,
    known_v: Sequence[Sequence[float]] | None = None,
) -> KappaFit:
    """``κ̂`` : le coefficient de ``ln(h̄ − r)`` (REML, GLS ; à ``known_v`` si elle
    est donnée), intervalle de Student à 95 %. M-S se lit seule si 1 y est."""
    design = kappa_design(spec, parameters)
    df = design.n - design.p
    if df < 1:
        raise NotEstimableError(f"κ : n − p = {df}")
    column = design.index(KAPPA)
    reml: RemlFit | None = None
    if known_v is None:
        reml = _reml(design, parameters)
        kappa = float(reml.fit.coef[column])
        se = math.sqrt(float(reml.fit.cov[column, column]))
    else:
        kappa, se = date_effect_at(design.X, design.y, known_v, column)
    return KappaFit(
        kappa=kappa,
        se=se,
        df=df,
        interval=student_interval(kappa, se, df, K_LEVEL),
        reml=reml,
    )
