"""La puissance de Q2 (AN3-3b, ``docs/decisions/0023``, plan § 10), calculée avant toute
estimation (charte § 6).

**Le monde simulé** (M-P, montées longues et côtes) : l'échantillon de l'estimation,
le modèle **sans le terme de date** ajusté par REML (``μ_s``, ``τ̂²``, ``s²_u``,
``φ̂``) et ``s²_ε`` de l'étage 1 réel ; tout le reste du réel (dates, covariables,
``h``) est gardé. Aucun terme de date ajusté sur les données n'est calculé ici.

**Un tirage** : un seul appel de ``parametric_draws`` donne les résidus de journée, de
montée et, selon le scénario, la composante lente (2) ou le bruit de ``h̄`` (4) ; la
charnière (3) se calcule. **Une estimation simulée** : le même estimateur que sur le
réel, sauf le bootstrap de ``b_inv``, à ``V`` fixée (Q-45) : la puissance rapportée
est donc approchée.

``simulate_draw`` et ``estimate_draw`` sont des fonctions de premier niveau, liées à
leurs données par ``functools.partial`` : le pool « spawn » les réimporte. Les
générateurs de numpy s'annotent ``Any`` (numpy est fermé à ``inference/``) ; ce module
n'appelle aucune de leurs méthodes.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import partial
from typing import Any

from mountain_perf.analyse.inference.base import (
    InferenceError,
    percentile_interval,
)
from mountain_perf.analyse.inference.bootstrap import parametric_draws
from mountain_perf.analyse.inference.linear import fraction_per_year, student_interval
from mountain_perf.analyse.inference.power import (
    CalibratedAlpha,
    Outcome,
    PowerRow,
    calibrate_alpha,
    power_table,
    simulate_power,
    smallest_visible_effect,
)
from mountain_perf.analyse.inference.readings import Reading, direction
from mountain_perf.analyse.inference.reml import RemlFit, three_component_cov
from mountain_perf.analyse.normals import integer_parameter
from mountain_perf.analyse.q2.data import Period, Q2Data
from mountain_perf.analyse.q2.model import (
    DATE,
    Measure,
    ModelSpec,
    NotEstimableError,
    Unit,
    bounded_reading,
    build_design,
    fit_direct,
    fit_inverse,
    fit_reml,
    fitted_mean,
    fixed_v_bootstrap,
    fraction_interval,
    inverse_design,
    model_spec,
    stage_one,
    without_columns,
)
from mountain_perf.analyse.q2.parameters import (
    ALPHA_FACTORS,
    HINGE_DAYS,
    Q2_PARAMETER_SPECS,
    Q2_ROOT_SEED,
    SCENARIO_ONE_FRACTIONS,
)
from mountain_perf.schemas import ParameterSet
from mountain_perf.schemas.processed import ClimbRegime

POWER_REGIMES: tuple[ClimbRegime, ...] = (
    ClimbRegime.LONG_CLIMB,
    ClimbRegime.SHORT_CLIMB,
)
"""Les régimes simulés (Q-36), dans l'ordre de leur clé (0, 1)."""

SCENARIOS: tuple[int, ...] = (1, 2, 3, 4)
"""(1) le modèle ajusté ; (2) composante lente ; (3) saison en charnière ; (4) erreur
de mesure de ``h``."""

YEAR_DAYS = 365.25


# --- les grilles ---------------------------------------------------------------


@dataclass(frozen=True)
class PowerGrids:
    """Les effets de chaque scénario, en fraction par an, tels qu'écrits."""

    fractions: Mapping[int, tuple[float, ...]]

    def b_values(self, scenario: int) -> tuple[float, ...]:
        """Les effets du scénario en log par jour : ``ln(1 + f) / 365,25``."""
        return tuple(math.log(1.0 + f) / YEAR_DAYS for f in self.fractions[scenario])


def power_grids(parameters: ParameterSet) -> PowerGrids:
    """Les grilles de Q-36 : le scénario (1) avec ``delta`` à sa place s'il n'y est
    pas (Q-50 (e)) ; (2) à 0 ; (3) et (4) à 0 et ``delta``."""
    delta = parameters["delta"]
    first = tuple(sorted({*SCENARIO_ONE_FRACTIONS, delta}))
    return PowerGrids({1: first, 2: (0.0,), 3: (0.0, delta), 4: (0.0, delta)})


def alpha_nominal(regime: ClimbRegime, parameters: ParameterSet) -> float:
    """``alpha`` aux montées longues ; ``alpha / secondary_family_size`` aux côtes."""
    alpha = parameters["alpha"]
    if regime is ClimbRegime.LONG_CLIMB:
        return alpha
    return alpha / integer_parameter(parameters, "secondary_family_size")


def alpha_grid(regime: ClimbRegime, parameters: ParameterSet) -> tuple[float, ...]:
    """La grille des seuils (Q-49 (l)) ; l'indice 0 est le seuil nominal."""
    nominal = alpha_nominal(regime, parameters)
    return tuple(nominal * factor for factor in ALPHA_FACTORS)


# --- le monde ------------------------------------------------------------------


@dataclass(frozen=True)
class PowerWorld:
    """Le monde simulé d'un régime : son modèle (``spec``), ses journées (``units``,
    triées), le modèle sans date (colonnes, ``μ_s``, le REML), ``s²_ε``, les nœuds de
    ``f``, les jours de l'année et la découverte de chaque journée, et les valeurs des
    seuils (un ``ParameterSet`` ne se transmet pas à un processus)."""

    regime: ClimbRegime
    spec: ModelSpec
    units: tuple[Unit, ...]
    columns: tuple[str, ...]
    mu: tuple[float, ...]
    tau2: float
    s2u: float
    phi: float
    s2e: float
    reml: RemlFit
    knots: tuple[float, float, float] | None
    t: tuple[float, ...]
    day_of_year: tuple[int, ...]
    discovery: tuple[bool, ...]
    values: tuple[tuple[str, float], ...]

    @property
    def parameters(self) -> ParameterSet:
        """Les seuils du monde."""
        return ParameterSet(Q2_PARAMETER_SPECS, dict(self.values))

    @property
    def residual_day_zero(self) -> bool:
        """Le REML sans date rend ``τ̂² = s²_u = 0`` : les résidus de journée sont
        nuls (leur bloc est omis de ``W``)."""
        return self.reml.tau2_at_zero and self.reml.s2u_at_zero


def power_world(
    data: Q2Data, regime: ClimbRegime, parameters: ParameterSet
) -> PowerWorld:
    """Le monde de ``regime`` ; :class:`NotEstimableError` si le modèle de M-P ne
    s'estime pas."""
    spec = model_spec(data.days[regime], Measure.MP, regime, parameters)
    if not spec.estimable:
        raise NotEstimableError(spec.reason or "non estimable")
    units = spec.units()
    stage = stage_one(units, Measure.MP)
    design = build_design(units, spec, stage, parameters)
    without_date = without_columns(design, [DATE])
    if without_date.n - without_date.p < 1:
        raise NotEstimableError(f"n − p = {without_date.n - without_date.p}")
    reml = fit_reml(without_date, parameters)
    return PowerWorld(
        regime=regime,
        spec=spec,
        units=units,
        columns=without_date.columns,
        mu=tuple(fitted_mean(without_date, reml)),
        tau2=reml.tau2,
        s2u=reml.s2u,
        phi=reml.phi,
        s2e=stage.sigma2,
        reml=reml,
        knots=design.knots,
        t=design.t,
        day_of_year=tuple(u.day.day.timetuple().tm_yday for u in units),
        discovery=tuple(u.day.period is Period.DISCOVERY for u in units),
        values=tuple(parameters.values.items()),
    )


# --- un tirage -----------------------------------------------------------------


def simulated_responses(
    mu: Sequence[float],
    b: float,
    t: Sequence[float],
    u: Sequence[float],
    eps: Sequence[Sequence[float]],
    g: Sequence[float] | None = None,
) -> tuple[tuple[float, ...], ...]:
    """``y*_i = μ_s + b·t_s + u_s + ε_i (+ g_s)`` pour chaque montée ``i`` de chaque
    journée ``s`` (``g`` : la composante lente, la charnière, ou leur somme)."""
    shift = [0.0] * len(mu) if g is None else list(g)
    return tuple(
        tuple(m + b * ts + us + gs + e for e in day)
        for m, ts, us, gs, day in zip(mu, t, u, shift, eps, strict=True)
    )


def hinge_shift(
    day_of_year: int, in_discovery: bool, parameters: ParameterSet
) -> float:
    """La saison en charnière du scénario (3), en log (Q-49 (k)) : affine en log entre
    les jours 150 (0), 200 (``ln(1 − hinge_peak)``) et 250 (0), nulle ailleurs ; plus
    ``ln(1 − discovery_step)`` sur la période de découverte."""
    start, peak, end = HINGE_DAYS
    top = math.log(1.0 - parameters["hinge_peak"])
    if start < day_of_year <= peak:
        hinge = top * (day_of_year - start) / (peak - start)
    elif peak < day_of_year < end:
        hinge = top * (end - day_of_year) / (end - peak)
    else:
        hinge = 0.0
    step = math.log(1.0 - parameters["discovery_step"]) if in_discovery else 0.0
    return hinge + step


def reliability_noise_variance(h_bar: Sequence[float], reliability: float) -> float:
    """La variance du bruit de ``h̄`` du scénario (4) :
    ``var(h̄) · (1 / reliability − 1)``."""
    return statistics.variance(h_bar) * (1.0 / reliability - 1.0)


def _block_diagonal(blocks: Sequence[Sequence[Sequence[float]]]) -> list[list[float]]:
    size = sum(len(b) for b in blocks)
    matrix = [[0.0] * size for _ in range(size)]
    offset = 0
    for block in blocks:
        for i, row in enumerate(block):
            matrix[offset + i][offset : offset + len(row)] = list(row)
        offset += len(block)
    return matrix


def _diagonal(value: float, size: int) -> list[list[float]]:
    return [[value if i == j else 0.0 for j in range(size)] for i in range(size)]


def _real_h_bar(world: PowerWorld) -> list[float]:
    return [statistics.fmean(c.h for c in u.climbs) for u in world.units]


def draw_covariance(world: PowerWorld, scenario: int) -> list[list[float]]:
    """``W``, diagonale par blocs, dans cet ordre : résidus de journée (omis s'ils
    sont nuls), résidus de montée, composante lente (2), bruit de ``h̄`` (4)."""
    j = len(world.units)
    n = sum(len(u.climbs) for u in world.units)
    zeros = [0.0] * j
    blocks: list[list[list[float]]] = []
    if not world.residual_day_zero:
        blocks.append(
            three_component_cov(
                list(world.t), zeros, world.tau2, world.s2u, world.phi
            ).tolist()
        )
    blocks.append(_diagonal(world.s2e, n))
    parameters = world.parameters
    if scenario == 2:
        blocks.append(
            three_component_cov(
                list(world.t),
                zeros,
                0.0,
                parameters["slow_component_sd"] ** 2,
                parameters["slow_component_days"],
            ).tolist()
        )
    if scenario == 4:
        variance = reliability_noise_variance(
            _real_h_bar(world), parameters["heart_rate_reliability"]
        )
        blocks.append(_diagonal(variance, j))
    return _block_diagonal(blocks)


@dataclass(frozen=True)
class SimulatedData:
    """Ce que reçoit une estimation simulée : les ``y*`` des montées, par journée, et
    les ``h̄`` de l'estimation (bruitées au scénario (4))."""

    y: tuple[tuple[float, ...], ...]
    h_bar: tuple[float, ...]


def simulate_draw(
    world: PowerWorld, scenario: int, b: float, rng: Any
) -> SimulatedData:
    """Un tirage à ``b`` imposé (log par jour) : un seul appel de
    ``parametric_draws`` (§ 8.2). ``rng`` : un ``numpy.random.Generator``, annoté
    ``Any`` (numpy est fermé à ``inference/``)."""
    covariance = draw_covariance(world, scenario)
    z: list[float] = parametric_draws(
        [0.0] * len(covariance), covariance, 1, rng
    ).tolist()[0]
    j = len(world.units)
    position = 0
    if world.residual_day_zero:
        u = [0.0] * j
    else:
        u, position = z[:j], j
    eps: list[list[float]] = []
    for unit in world.units:
        eps.append(z[position : position + len(unit.climbs)])
        position += len(unit.climbs)
    shift = [0.0] * j
    if scenario == 2:
        shift = z[position : position + j]
        position += j
    if scenario == 3:
        parameters = world.parameters
        shift = [
            hinge_shift(d, disc, parameters)
            for d, disc in zip(world.day_of_year, world.discovery, strict=True)
        ]
    h_bar = _real_h_bar(world)
    if scenario == 4:
        h_bar = [
            h + nu for h, nu in zip(h_bar, z[position : position + j], strict=True)
        ]
    return SimulatedData(
        y=simulated_responses(world.mu, b, world.t, u, eps, shift),
        h_bar=tuple(h_bar),
    )


# --- une estimation simulée ----------------------------------------------------


def _failed(alphas: Sequence[float]) -> Outcome:
    count = len(alphas)
    return Outcome(math.nan, (Reading.UNDECIDED,) * count, (0,) * count)


def estimate_draw(
    world: PowerWorld,
    scenario: int,
    data: SimulatedData,
    alphas: tuple[float, ...],
    rng: Any,
) -> Outcome:
    """Le même estimateur que sur le réel (§ 7), bootstrap de ``b_inv`` à ``V``
    fixée ; pour chaque seuil, la lecture bornée et le sens. Un tirage dont un
    ajustement lève rend ``Outcome(nan, …)``. ``rng`` : un ``numpy.random.Generator``
    (annoté ``Any``)."""
    parameters = world.parameters
    delta = parameters["delta"]
    try:
        units = [replace(u, y=y) for u, y in zip(world.units, data.y, strict=True)]
        stage = stage_one(units, Measure.MP)
        design = build_design(
            units,
            world.spec,
            stage,
            parameters,
            knots=world.knots,
            h_bar=data.h_bar if scenario == 4 else None,
        )
        direct = fit_direct(design, parameters)
        inverse = fit_inverse(inverse_design(design, units), parameters)
        draws = fixed_v_bootstrap(
            inverse, integer_parameter(parameters, "bootstrap_draws"), rng
        )
        readings: list[Reading] = []
        directions: list[int] = []
        for alpha in alphas:
            level = 1.0 - alpha
            low_high = student_interval(direct.b, direct.se, direct.df, level)
            direct_interval = fraction_interval(low_high)
            if inverse.k_contains_zero:
                readings.append(Reading.UNDECIDED)
                directions.append(0)
                continue
            inverse_interval = fraction_interval(
                percentile_interval(list(draws.draws), level)
            )
            result, _ = bounded_reading(
                direct_interval, inverse_interval, None, delta, False
            )
            readings.append(result)
            directions.append(direction([direct_interval, inverse_interval]))
    except (NotEstimableError, InferenceError):
        return _failed(alphas)
    return Outcome(direct.b, tuple(readings), tuple(directions))


# --- les comptes ---------------------------------------------------------------


@dataclass(frozen=True)
class PowerSummary:
    """Ce qui se rapporte d'un régime (§ 8.4) : les lignes de chaque scénario, les
    tirages en échec par ligne, le plus petit effet visible (fraction par an, ou
    ``None``), la puissance et les erreurs S et M à δ, les parts à ``b = 0``, le biais
    sous (3) et (4), la calibration, les lectures hors d'atteinte et le message."""

    rows: Mapping[int, tuple[PowerRow, ...]]
    failed: Mapping[int, tuple[int, ...]]
    smallest_visible: float | None
    power_at_delta: float | None
    s_error_at_delta: float | None
    m_error_at_delta: float | None
    at_zero: Mapping[int, tuple[float, float]]
    bias: Mapping[int, tuple[float | None, ...]]
    calibration: CalibratedAlpha
    no_effect_out_of_reach: bool
    undecided_expected: bool | None
    insufficient: bool


def _bias(outcomes: Sequence[Outcome], fraction: float) -> float | None:
    finite = [o.estimate for o in outcomes if math.isfinite(o.estimate)]
    if not finite:
        return None
    return fraction_per_year(statistics.fmean(finite)) - fraction


def power_summary(
    grids: PowerGrids,
    outcomes: Mapping[int, Sequence[Sequence[Outcome]]],
    alphas: Sequence[float],
    parameters: ParameterSet,
    *,
    long_climbs: bool,
) -> PowerSummary:
    """Les comptes d'un régime depuis les résultats de chaque scénario (une suite par
    valeur de ``b``, dans l'ordre de la grille)."""
    delta = parameters["delta"]
    rows = {s: power_table(grids.b_values(s), outcomes[s], 0) for s in outcomes}
    failed = {
        s: tuple(sum(1 for o in draws if not math.isfinite(o.estimate)) for draws in d)
        for s, d in outcomes.items()
    }
    first = grids.fractions[1]
    b_first = grids.b_values(1)
    visible_b = smallest_visible_effect(rows[1], parameters["power_target_visible"])
    visible = None if visible_b is None else first[b_first.index(visible_b)]
    at_delta = rows[1][first.index(delta)]
    b_delta = b_first[first.index(delta)]
    at_zero = {
        s: (r[0].p_established, r[0].p_no_useful_effect)
        for s, r in rows.items()
        if grids.fractions[s][0] == 0.0
    }
    bias = {
        s: tuple(
            _bias(draws, fraction)
            for draws, fraction in zip(outcomes[s], grids.fractions[s], strict=True)
        )
        for s in (3, 4)
        if s in outcomes
    }
    zero_one = outcomes[1][first.index(0.0)]
    zero_two = outcomes[2][grids.fractions[2].index(0.0)]
    calibration = calibrate_alpha(
        [zero_one, zero_two], alphas, alphas[0], parameters["calibration_trigger"]
    )
    power = at_delta.power
    return PowerSummary(
        rows=rows,
        failed=failed,
        smallest_visible=visible,
        power_at_delta=power,
        s_error_at_delta=at_delta.s_error,
        m_error_at_delta=at_delta.m_error,
        at_zero=at_zero,
        bias=bias,
        calibration=calibration,
        no_effect_out_of_reach=power is None
        or power < parameters["power_target_no_effect"],
        undecided_expected=(
            power is None or power < parameters["power_target_undecided"]
        )
        if long_climbs
        else None,
        insufficient=visible_b is None or visible_b > b_delta,
    )


@dataclass(frozen=True)
class PowerLevel:
    """Ce que l'estimation lit de la puissance d'un régime : calculée ou non, la
    calibration déclenchée ou non, et le seuil retenu (``None`` : non calibrable, ou
    puissance non calculée)."""

    computed: bool
    triggered: bool
    alpha: float | None


# --- la simulation complète ----------------------------------------------------


@dataclass(frozen=True)
class RegimePower:
    """La puissance d'un régime : son monde et ses comptes, ou le motif qui l'a
    empêchée (``world`` à ``None``)."""

    regime: ClimbRegime
    world: PowerWorld | None
    summary: PowerSummary | None
    reason: str | None
    alphas: tuple[float, ...]


@dataclass(frozen=True)
class PowerResult:
    """Les grilles et la puissance de chaque régime simulé."""

    grids: PowerGrids
    regimes: tuple[RegimePower, ...]


def run_power(data: Q2Data, parameters: ParameterSet, workers: int = 1) -> PowerResult:
    """La simulation de puissance de Q2 (§ 8.3) : pour chaque régime ``r`` et chaque
    scénario ``s``, ``simulate_power`` sous la clé ``(1, r, s − 1)``, sur la grille de
    :func:`power_grids`."""
    grids = power_grids(parameters)
    draws = integer_parameter(parameters, "power_draws")
    results: list[RegimePower] = []
    for r, regime in enumerate(POWER_REGIMES):
        alphas = alpha_grid(regime, parameters)
        try:
            world = power_world(data, regime, parameters)
        except NotEstimableError as error:
            results.append(RegimePower(regime, None, None, str(error), alphas))
            continue
        outcomes = {
            s: simulate_power(
                partial(simulate_draw, world, s),
                partial(estimate_draw, world, s),
                grids.b_values(s),
                alphas,
                draws,
                Q2_ROOT_SEED,
                key=(1, r, s - 1),
                workers=workers,
            )
            for s in SCENARIOS
        }
        summary = power_summary(
            grids,
            outcomes,
            alphas,
            parameters,
            long_climbs=regime is ClimbRegime.LONG_CLIMB,
        )
        results.append(RegimePower(regime, world, summary, None, alphas))
    return PowerResult(grids, tuple(results))
