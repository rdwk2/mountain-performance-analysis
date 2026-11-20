"""Les 24 essais de Q2 (AN3-3b, ``docs/decisions/0023``, plan §§ 12, 13) : le
principal, les cinq secondaires, les sensibilités ; Holm ; l'autocorrélation des
résidus ; les bornes.

Les essais s'écrivent dans l'ordre fixe de :data:`TRIALS` ; leur indice sert de clé
aux générateurs : ``child_rng(Q2_ROOT_SEED, 2, indice, usage)``, ``usage`` 0 pour le
bootstrap de ``b_inv``, 1 pour S14, 2 pour la bande de la figure (essai 0). Une
sensibilité part du modèle du principal et ne change que ce qu'elle dit ; elle vérifie
que son paramètre effectif change, sinon sa ligne le dit (« identique au principal »).

Les générateurs de numpy s'annotent ``Any`` : numpy est fermé à ``inference/``.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum
from typing import Any

from mountain_perf.analyse.inference.autocorrelation import residual_autocorrelation
from mountain_perf.analyse.inference.base import (
    InferenceError,
    Interval,
    child_rng,
    percentile_interval,
)
from mountain_perf.analyse.inference.clusters import wild_cluster_interval
from mountain_perf.analyse.inference.linear import (
    fraction_per_year,
    ols,
    student_interval,
    student_pvalue,
    whiten,
)
from mountain_perf.analyse.inference.readings import (
    Reading,
    bonferroni_level,
    holm,
)
from mountain_perf.analyse.inference.reml import RemlFit, three_component_cov
from mountain_perf.analyse.inference.robust import huber
from mountain_perf.analyse.normals import integer_parameter
from mountain_perf.analyse.q2.data import (
    HeartRate,
    Period,
    Q2Data,
    Q2Day,
    Q2Motif,
)
from mountain_perf.analyse.q2.model import (
    DATE,
    EXTRA_PRECEDING_MOVING,
    HR_COLUMNS,
    LINEAR_HR,
    SEASON,
    SPLINE,
    Design,
    DirectFit,
    InverseFit,
    KappaFit,
    Measure,
    ModelSpec,
    NotEstimableError,
    Unit,
    base_columns,
    bounded_reading,
    build_design,
    date_effect_at,
    day_features,
    day_in_sample,
    fit_direct,
    fit_inverse,
    fraction_interval,
    heart_rate_columns,
    inverse_bootstrap,
    inverse_design,
    kappa_fit,
    model_spec,
    route_columns_of,
    row_values,
    stage_one,
    unit_of,
)
from mountain_perf.analyse.q2.parameters import (
    AUTOCORRELATION_CLASSES,
    Q2_REGIMES,
    Q2_ROOT_SEED,
)
from mountain_perf.analyse.q2.power import PowerLevel
from mountain_perf.analyse.q2.routes import route_groups
from mountain_perf.schemas import ParameterSet
from mountain_perf.schemas.processed import ClimbRegime

LONG = ClimbRegime.LONG_CLIMB
SHORT = ClimbRegime.SHORT_CLIMB
SKI = ClimbRegime.SKI_TOURING
SENSITIVITY_LEVEL = 0.95
KAPPA_LEVEL = 0.95


class Family(StrEnum):
    """La famille d'un essai."""

    PRINCIPAL = "principale"
    SECONDARY = "secondaire"
    SENSITIVITY = "sensibilite"


class Status(StrEnum):
    """Le statut d'une ligne d'essai."""

    ESTIMATED = "estime"
    NOT_ESTIMABLE = "non_estimable"
    NOT_DONE = "non_faite"


@dataclass(frozen=True)
class Trial:
    """Un essai : son indice, son nom, sa famille, son régime et sa mesure."""

    index: int
    name: str
    family: Family
    regime: ClimbRegime
    measure: Measure


def _sensitivity(index: int, name: str) -> Trial:
    return Trial(index, name, Family.SENSITIVITY, LONG, Measure.MP)


SENSITIVITY_NAMES: tuple[str, ...] = (
    "S1",
    "S2",
    "S3",
    "S4",
    "S5",
    "S8",
    "S9",
    "S10",
    "S11",
    "S12",
    "S13",
    "S14",
    "S15",
    "S16",
    "S17",
)

TRIALS: tuple[Trial, ...] = (
    Trial(0, "P", Family.PRINCIPAL, LONG, Measure.MP),
    Trial(1, "S-MP-cotes", Family.SECONDARY, SHORT, Measure.MP),
    Trial(2, "S-MP-ski", Family.SECONDARY, SKI, Measure.MP),
    Trial(3, "S-MS-longues", Family.SECONDARY, LONG, Measure.MS),
    Trial(4, "S-MS-cotes", Family.SECONDARY, SHORT, Measure.MS),
    Trial(5, "S-MS-ski", Family.SECONDARY, SKI, Measure.MS),
    *(_sensitivity(6 + k, name) for k, name in enumerate(SENSITIVITY_NAMES)),
    _sensitivity(21, "S18"),
    Trial(22, "S19", Family.SENSITIVITY, LONG, Measure.MS),
    Trial(23, "S20", Family.SENSITIVITY, SHORT, Measure.MS),
)
"""Les 24 essais, dans leur ordre fixe (§ 9.1)."""

NOT_DONE: tuple[str, ...] = (
    "S6 : non estimable (saison fraîche trop courte)",
    "S7 : retirée",
)
"""Les deux sensibilités du plan qui ne sont pas des essais, et leur raison."""

MENTION_INTENSITY = "dépend de l'intensité choisie"
MENTION_SHORT = "FC dépendante de la VAM sur ces durées"
MENTION_OPTIMISTIC = "optimiste"
MENTION_UNCALIBRATED = "valeur critique non calibrable"
MENTION_NO_POWER = "puissance non calculée"
MENTION_REMOVED = "plus de 1 % de tirages retirés"
MENTION_SAME = "identique au principal"
NO_PERIODS = "sans [periodes]"


@dataclass(frozen=True)
class TrialRow:
    """Une ligne d'essai : une ligne d'``essais.csv`` et d'``essais.jsonl``. Les noms
    sont ceux des colonnes écrites ; les fractions sont par an (0,05 = 5 %) ; un
    intervalle est un couple ``(bas, haut)``."""

    essai: str
    indice: int
    famille: str
    regime: str
    mesure: str
    statut: str
    motif: str | None = None
    n_journees: int | None = None
    n_montees: int | None = None
    p: int | None = None
    retraits: str | None = None
    niveau: float | None = None
    estimation_fraction: float | None = None
    intervalle_fraction: tuple[float, float] | None = None
    inverse_fraction: float | None = None
    intervalle_inverse_fraction: tuple[float, float] | None = None
    k_contient_zero: bool | None = None
    lecture: str | None = None
    phrase: str | None = None
    p_valeur: float | None = None
    holm_rejet: bool | None = None
    kappa: float | None = None
    intervalle_kappa: tuple[float, float] | None = None
    mention: str | None = None
    tau2: float | None = None
    s2u: float | None = None
    phi: float | None = None
    tau2_a_zero: bool | None = None
    s2u_a_zero: bool | None = None
    phi_a_la_borne_basse: bool | None = None
    phi_a_la_borne_haute: bool | None = None
    phi_identifie: bool | None = None
    tirages_retires: int = 0
    variante_effective: bool | None = None
    montees_retirees: int = 0
    forme_fc: str | None = None
    exploratoire: bool = True


INTERVAL_FIELDS: tuple[str, ...] = (
    "intervalle_fraction",
    "intervalle_inverse_fraction",
    "intervalle_kappa",
)
"""Les champs de :class:`TrialRow` qui sont des intervalles."""


# --- les p-valeurs, les bornes ---------------------------------------------------


def bounded_pvalue(
    p_direct: float,
    inverse_draws: Sequence[float],
    k_interval_contains_zero: bool,
) -> float:
    """La p-valeur d'une comparaison bornée (Q-37 (a), Q-49 (r)) :
    ``max(p_direct, 2·min(part des b* ≤ 0, part des b* ≥ 0))`` ; 1 si l'intervalle
    de ``k̂`` contient 0."""
    if k_interval_contains_zero or not inverse_draws:
        return 1.0
    count = len(inverse_draws)
    below = sum(1 for b in inverse_draws if b <= 0) / count
    above = sum(1 for b in inverse_draws if b >= 0) / count
    return max(p_direct, min(1.0, 2.0 * min(below, above)))


def imputed_bounds(
    fitted: Sequence[float],
    periods: Sequence[str],
    tau2: float,
    s2u: float,
) -> tuple[list[float | None], list[float | None]]:
    """Les ``ȳ`` imputés des bornes (Q-49 (j), Q-50 (f)) : la valeur ajustée ``± s``,
    ``s = √(τ̂² + s²_u)`` ; borne basse ``+s`` en découverte et ``−s`` ensuite, borne
    haute l'inverse ; ``None`` pour une journée ``avant``."""
    s = math.sqrt(tau2 + s2u)
    low: list[float | None] = []
    high: list[float | None] = []
    for value, period in zip(fitted, periods, strict=True):
        if period == Period.DISCOVERY.value:
            low.append(value + s)
            high.append(value - s)
        elif period == Period.AFTER.value:
            low.append(value - s)
            high.append(value + s)
        else:
            low.append(None)
            high.append(None)
    return low, high


# --- les lignes -----------------------------------------------------------------


def _pair(interval: Interval | None) -> tuple[float, float] | None:
    return None if interval is None else (interval.low, interval.high)


def _reml_fields(fit: RemlFit | None) -> dict[str, Any]:
    if fit is None:
        return {}
    return {
        "tau2": fit.tau2,
        "s2u": fit.s2u,
        "phi": fit.phi,
        "tau2_a_zero": fit.tau2_at_zero,
        "s2u_a_zero": fit.s2u_at_zero,
        "phi_a_la_borne_basse": fit.phi_at_lower,
        "phi_a_la_borne_haute": fit.phi_at_upper,
        "phi_identifie": fit.phi_identified,
    }


def _base(trial: Trial, status: Status, **values: Any) -> TrialRow:
    return TrialRow(
        essai=trial.name,
        indice=trial.index,
        famille=trial.family.value,
        regime=trial.regime.value,
        mesure=trial.measure.value,
        statut=status.value,
        **values,
    )


def _withdrawals(spec: ModelSpec) -> str:
    return "-".join(str(w) for w in spec.withdrawals)


def _mentions(*items: str | None) -> str | None:
    kept = [i for i in items if i]
    return " ; ".join(dict.fromkeys(kept)) if kept else None


def _not(
    trial: Trial,
    status: Status,
    reason: str,
    spec: ModelSpec | None = None,
    **extra: Any,
) -> TrialRow:
    values: dict[str, Any] = {"motif": reason}
    if spec is not None:
        values.update(n_journees=spec.n, p=spec.p, retraits=_withdrawals(spec))
    values.update(extra)
    return _base(trial, status, **values)


def _climbs(units: Sequence[Unit]) -> int:
    return sum(len(u.climbs) for u in units)


# --- le contexte d'une estimation --------------------------------------------------


@dataclass(frozen=True)
class Fitted:
    """Une comparaison estimée : le modèle, ses journées, l'étage 1, la matrice, le
    direct, et, pour une comparaison bornée, l'inverse, ses tirages et leur
    intervalle."""

    spec: ModelSpec
    units: tuple[Unit, ...]
    stage_eta: float | None
    sigma2: float
    design: Design
    direct: DirectFit
    inverse: InverseFit | None = None
    draws: tuple[float, ...] = ()
    removed: int = 0
    inverse_interval: Interval | None = None


@dataclass(frozen=True)
class Q2Estimation:
    """L'estimation de Q2 : les 24 lignes, les modèles retenus, le principal estimé
    (``None`` s'il ne l'est pas), le niveau de chaque essai, les bornes et
    l'autocorrélation."""

    rows: tuple[TrialRow, ...]
    specs: Mapping[tuple[ClimbRegime, Measure], ModelSpec]
    principal: Fitted | None
    levels: Mapping[str, float]
    bounds: Mapping[str, object]
    autocorrelation: tuple[tuple[str, str, int, int | None, int, float | None], ...]


@dataclass
class _Context:
    data: Q2Data
    parameters: ParameterSet
    power: Mapping[str, PowerLevel]
    workers: int
    specs: dict[tuple[ClimbRegime, Measure], ModelSpec] = field(default_factory=dict)

    @property
    def delta(self) -> float:
        return self.parameters["delta"]

    @property
    def periods_declared(self) -> bool:
        return self.data.periods is not None

    def spec(self, regime: ClimbRegime, measure: Measure) -> ModelSpec:
        return self.specs[(regime, measure)]


def _level(context: _Context, regime: ClimbRegime) -> tuple[float, str | None]:
    """Le niveau d'une comparaison bornée de M-P : nominal (``1 − alpha`` au
    principal, Bonferroni ailleurs) ou calibré (§ 7.2, Q-49 (g))."""
    parameters = context.parameters
    alpha = parameters["alpha"]
    size = integer_parameter(parameters, "secondary_family_size")
    nominal = 1.0 - alpha if regime is LONG else bonferroni_level(alpha, size)
    if regime is SKI:
        return nominal, None
    level = context.power.get(regime.value)
    if level is None or not level.computed:
        return nominal, MENTION_NO_POWER
    if not level.triggered:
        return nominal, None
    if level.alpha is None:
        return nominal, MENTION_UNCALIBRATED
    return 1.0 - level.alpha, None


def _fit(
    spec: ModelSpec,
    parameters: ParameterSet,
    *,
    units: Sequence[Unit] | None = None,
    heart_rate: HeartRate = HeartRate.LAGGED,
    columns: Sequence[str] | None = None,
    knots: tuple[float, float, float] | None = None,
) -> Fitted:
    chosen = spec.units() if units is None else tuple(units)
    if not chosen:
        raise NotEstimableError("aucune journée")
    stage = stage_one(chosen, spec.measure, heart_rate)
    design = build_design(
        chosen,
        spec,
        stage,
        parameters,
        heart_rate=heart_rate,
        columns=columns,
        knots=knots,
    )
    return Fitted(
        spec=spec,
        units=tuple(chosen),
        stage_eta=stage.eta_within,
        sigma2=stage.sigma2,
        design=design,
        direct=fit_direct(design, parameters),
    )


def _with_inverse(
    fitted: Fitted, context: _Context, index: int, level: float
) -> Fitted:
    inverse = fit_inverse(
        inverse_design(fitted.design, fitted.units), context.parameters
    )
    if inverse.k_contains_zero:
        return replace(fitted, inverse=inverse)
    draws = inverse_bootstrap(
        inverse,
        context.parameters,
        child_rng(Q2_ROOT_SEED, 2, index, 0),
        context.workers,
    )
    if not draws.draws:
        raise NotEstimableError("aucun tirage de b_inv gardé")
    interval = fraction_interval(percentile_interval(list(draws.draws), level))
    return replace(
        fitted,
        inverse=inverse,
        draws=draws.draws,
        removed=draws.removed,
        inverse_interval=interval,
    )


def _direct_interval(fitted: Fitted, level: float) -> Interval:
    d = fitted.direct
    return fraction_interval(student_interval(d.b, d.se, d.df, level))


def _optimistic(fitted: Fitted, context: _Context) -> str | None:
    limit = integer_parameter(context.parameters, "optimistic_below_days")
    return MENTION_OPTIMISTIC if fitted.design.n < limit else None


def _removed_mention(fitted: Fitted) -> str | None:
    total = len(fitted.draws) + fitted.removed
    return MENTION_REMOVED if total and fitted.removed > 0.01 * total else None


def _estimated_values(fitted: Fitted, level: float) -> dict[str, Any]:
    d = fitted.direct
    return {
        "n_journees": fitted.design.n,
        "n_montees": _climbs(fitted.units),
        "p": fitted.design.p,
        "retraits": _withdrawals(fitted.spec),
        "niveau": level,
        "estimation_fraction": fraction_per_year(d.b),
        "intervalle_fraction": _pair(_direct_interval(fitted, level)),
        **_reml_fields(d.reml),
    }


# --- le principal et les secondaires ---------------------------------------------


def _bounded_row(
    trial: Trial, context: _Context, extra_mention: str | None = None
) -> tuple[TrialRow, Fitted | None, float]:
    """Une comparaison bornée de M-P (principal, côtes, ski) ; rend la ligne, la
    comparaison estimée (ou ``None``) et sa p-valeur."""
    spec = context.spec(trial.regime, Measure.MP)
    level, level_mention = _level(context, trial.regime)
    if not spec.estimable:
        return (
            _not(trial, Status.NOT_ESTIMABLE, spec.reason or "", spec, niveau=level),
            None,
            1.0,
        )
    try:
        fitted = _with_inverse(
            _fit(spec, context.parameters), context, trial.index, level
        )
    except (NotEstimableError, InferenceError) as error:
        return (
            _not(trial, Status.NOT_ESTIMABLE, str(error), spec, niveau=level),
            None,
            1.0,
        )
    inverse = fitted.inverse
    assert inverse is not None
    direct_interval = _direct_interval(fitted, level)
    k_interval = student_interval(inverse.k, inverse.se_k, inverse.df, KAPPA_LEVEL)
    reading, sentence = bounded_reading(
        direct_interval,
        fitted.inverse_interval,
        k_interval,
        context.delta,
        context.periods_declared,
    )
    if inverse.k_contains_zero:
        reading, sentence = Reading.UNDECIDED, "les données ne tranchent pas"
    d = fitted.direct
    p_value = bounded_pvalue(
        student_pvalue(d.b, d.se, d.df), fitted.draws, inverse.k_contains_zero
    )
    form = None
    if trial.index == 0:
        form = "lineaire" if LINEAR_HR in fitted.design.columns else "spline"
    row = _base(
        trial,
        Status.ESTIMATED,
        **_estimated_values(fitted, level),
        inverse_fraction=fraction_per_year(inverse.b_inv),
        intervalle_inverse_fraction=_pair(fitted.inverse_interval),
        k_contient_zero=inverse.k_contains_zero,
        lecture=reading.value,
        phrase=sentence,
        mention=_mentions(
            level_mention,
            extra_mention,
            _optimistic(fitted, context),
            _removed_mention(fitted),
        ),
        tirages_retires=fitted.removed,
        forme_fc=form,
    )
    return row, fitted, p_value


def _ms_row(
    trial: Trial, context: _Context, extra_mention: str | None = None
) -> tuple[TrialRow, float, KappaFit | None]:
    """Une comparaison directe de M-S, au niveau de Bonferroni ; et son ``κ`` (longues
    et côtes)."""
    spec = context.spec(trial.regime, Measure.MS)
    parameters = context.parameters
    level = bonferroni_level(
        parameters["alpha"], integer_parameter(parameters, "secondary_family_size")
    )
    if not spec.estimable:
        return (
            _not(trial, Status.NOT_ESTIMABLE, spec.reason or "", spec, niveau=level),
            1.0,
            None,
        )
    try:
        fitted = _fit(spec, parameters)
    except (NotEstimableError, InferenceError) as error:
        return (
            _not(trial, Status.NOT_ESTIMABLE, str(error), spec, niveau=level),
            1.0,
            None,
        )
    kappa: KappaFit | None = None
    intensity = None
    if trial.regime is not SKI:
        try:
            kappa = kappa_fit(spec, parameters)
        except (NotEstimableError, InferenceError):
            kappa = None
        if kappa is not None and not kappa.interval.low <= 1.0 <= kappa.interval.high:
            intensity = MENTION_INTENSITY
    reading, sentence = bounded_reading(
        _direct_interval(fitted, level),
        None,
        None,
        context.delta,
        context.periods_declared,
    )
    d = fitted.direct
    row = _base(
        trial,
        Status.ESTIMATED,
        **_estimated_values(fitted, level),
        lecture=reading.value,
        phrase=sentence,
        kappa=None if kappa is None else kappa.kappa,
        intervalle_kappa=None if kappa is None else _pair(kappa.interval),
        mention=_mentions(intensity, extra_mention, _optimistic(fitted, context)),
    )
    return row, student_pvalue(d.b, d.se, d.df), kappa


# --- les sensibilités ----------------------------------------------------------


def _drop_empty_routes(
    columns: Sequence[str], units: Sequence[Unit], spec: ModelSpec
) -> tuple[list[str], list[str]]:
    groups = {spec.group_of(u.day.day) for u in units}
    kept, dropped = [], []
    for column in columns:
        if column.startswith("parcours_") and int(column.split("_")[1]) not in groups:
            dropped.append(column)
        else:
            kept.append(column)
    return kept, dropped


def _sensitivity_row(
    trial: Trial,
    context: _Context,
    fitted: Fitted,
    *,
    effective: bool,
    mentions: Sequence[str | None] = (),
    removed_climbs: int = 0,
    form: str | None = None,
) -> TrialRow:
    reading, sentence = bounded_reading(
        _direct_interval(fitted, SENSITIVITY_LEVEL),
        None,
        None,
        context.delta,
        context.periods_declared,
    )
    return _base(
        trial,
        Status.ESTIMATED,
        **_estimated_values(fitted, SENSITIVITY_LEVEL),
        lecture=reading.value,
        phrase=sentence,
        mention=_mentions(*(None if effective else MENTION_SAME,), *mentions),
        variante_effective=effective,
        montees_retirees=removed_climbs,
        forme_fc=form,
    )


def _refit(
    trial: Trial,
    context: _Context,
    principal: Fitted,
    units: Sequence[Unit],
    *,
    effective: bool,
    heart_rate: HeartRate = HeartRate.LAGGED,
    columns: Sequence[str] | None = None,
    spec: ModelSpec | None = None,
    removed_climbs: int = 0,
    form: str | None = None,
    knots: tuple[float, float, float] | None = None,
) -> TrialRow:
    """Une sensibilité réestimée par la régression directe (REML, GLS), à 95 %."""
    model = principal.spec if spec is None else spec
    base_columns_ = list(principal.design.columns if columns is None else columns)
    chosen, dropped = _drop_empty_routes(base_columns_, units, model)
    mention = (
        f"indicatrice de parcours retirée : {', '.join(dropped)}" if dropped else None
    )
    try:
        fitted = _fit(
            model,
            context.parameters,
            units=sorted(units, key=lambda u: u.day.day),
            heart_rate=heart_rate,
            columns=chosen,
            knots=principal.design.knots if knots is None else knots,
        )
    except (NotEstimableError, InferenceError) as error:
        return _not(trial, Status.NOT_DONE, str(error), model)
    return _sensitivity_row(
        trial,
        context,
        fitted,
        effective=effective,
        mentions=(mention,),
        removed_climbs=removed_climbs,
        form=form,
    )


def _heart_rate_variant(
    trial: Trial, context: _Context, principal: Fitted, which: HeartRate
) -> TrialRow:
    """S1, S2, S16 : la FC de la variante aux étages 1 et 2, sur l'échantillon du
    principal ; une montée sans valeur est retirée et comptée ; nœuds du principal."""
    units: list[Unit] = []
    removed = 0
    effective = False
    for unit in principal.units:
        keep = [
            (c, y)
            for c, y in zip(unit.climbs, unit.y, strict=True)
            if c.heart_rate(which) is not None
        ]
        removed += len(unit.climbs) - len(keep)
        effective = effective or any(c.heart_rate(which) != c.h for c, _ in keep)
        if keep:
            units.append(
                Unit(unit.day, tuple(c for c, _ in keep), tuple(y for _, y in keep))
            )
    return _refit(
        trial,
        context,
        principal,
        units,
        effective=effective or removed > 0,
        heart_rate=which,
        removed_climbs=removed,
    )


def _other_form(trial: Trial, context: _Context, principal: Fitted) -> TrialRow:
    """S3 : l'autre forme de ``f`` (Q-49 (n))."""
    columns = list(principal.design.columns)
    if LINEAR_HR in columns:
        k = columns.index(LINEAR_HR)
        columns[k : k + 1] = list(SPLINE)
        form = "spline"
        knots = None
        try:
            from mountain_perf.analyse.q2.model import spline_knots

            knots = spline_knots(
                [day_features(u, HeartRate.LAGGED)["h"] for u in principal.units],
                context.parameters,
            )
            heart_rate_columns([knots[1]], knots)
        except (NotEstimableError, InferenceError) as error:
            return _not(trial, Status.NOT_DONE, str(error), principal.spec)
    else:
        k = columns.index(SPLINE[0])
        columns[k : k + 2] = [LINEAR_HR]
        form = "lineaire"
        knots = None
    try:
        fitted = _fit(
            principal.spec,
            context.parameters,
            units=principal.units,
            columns=columns,
            knots=knots,
        )
    except (NotEstimableError, InferenceError) as error:
        return _not(trial, Status.NOT_DONE, str(error), principal.spec)
    return _sensitivity_row(trial, context, fitted, effective=True, form=form)


def _season_free(trial: Trial, context: _Context, principal: Fitted) -> TrialRow:
    """S8 : sans ``saison_sin``, ``saison_cos``."""
    columns = [c for c in principal.design.columns if c not in SEASON]
    effective = len(columns) != len(principal.design.columns)
    return _refit(
        trial, context, principal, principal.units, effective=effective, columns=columns
    )


def _subset(
    trial: Trial,
    context: _Context,
    principal: Fitted,
    keep: Callable[[Unit], bool],
) -> TrialRow:
    units = [u for u in principal.units if keep(u)]
    return _refit(
        trial,
        context,
        principal,
        units,
        effective=len(units) != len(principal.units),
    )


def _common_support(trial: Trial, context: _Context, principal: Fitted) -> TrialRow:
    """S9 : le support commun de ``h̄_s`` entre la découverte et la suite."""
    if context.data.periods is None:
        return _not(trial, Status.NOT_DONE, NO_PERIODS, principal.spec)
    by_period: dict[Period, list[float]] = {Period.DISCOVERY: [], Period.AFTER: []}
    for unit, h in zip(principal.units, principal.design.h_bar, strict=True):
        if unit.day.period in by_period:
            by_period[unit.day.period].append(h)
    if not all(by_period.values()):
        return _not(trial, Status.NOT_DONE, "une période sans journée", principal.spec)
    low = max(min(v) for v in by_period.values())
    high = min(max(v) for v in by_period.values())
    hs = dict(zip(principal.design.days, principal.design.h_bar, strict=True))
    return _subset(trial, context, principal, lambda u: low <= hs[u.day.day] <= high)


def _e_s_switch(trial: Trial, context: _Context, principal: Fitted) -> TrialRow:
    """S10 : l'autre version du 5ᵉ retrait ; les affectations du principal, les tailles
    recomptées sur l'échantillon de S10 (Q-50 (a))."""
    spec = principal.spec
    played = 5 in spec.withdrawals
    in_sample = tuple(
        day_in_sample(day, Measure.MP, step5_applied=played) for day in spec.days
    )
    withdrawals = (
        tuple(w for w in spec.withdrawals if w != 5)
        if played
        else (
            *spec.withdrawals,
            5,
        )
    )
    parameters = context.parameters
    max_other = (
        integer_parameter(parameters, "min_route_days") - 1
        if 4 in spec.withdrawals
        else 1
    )
    groups = route_groups(spec.days, parameters, max_other, in_sample)
    routes = route_columns_of(groups, in_sample)
    columns = (
        *base_columns(Measure.MP, spec.regime, withdrawals),
        *(f"parcours_{g}" for g in routes),
    )
    variant = replace(
        spec,
        withdrawals=withdrawals,
        columns=columns,
        in_sample=in_sample,
        groups=groups,
        route_columns=routes,
        n=sum(in_sample),
        p=len(columns),
    )
    units = variant.units()
    return _refit(
        trial,
        context,
        principal,
        units,
        effective=True,
        columns=columns,
        spec=variant,
    )


def _robust(trial: Trial, context: _Context, principal: Fitted) -> TrialRow:
    """S11 : ``whiten`` à la ``V̂`` du principal, puis Huber."""
    design = principal.design
    reml = principal.direct.reml
    covariance = three_component_cov(
        list(design.t), list(design.d), reml.tau2, reml.s2u, reml.phi
    ).tolist()
    try:
        x_w, y_w = whiten([list(r) for r in design.X], list(design.y), covariance)
        fit = huber(x_w, y_w)
        k = design.index(DATE)
        b = float(fit.coef[k])
        se = math.sqrt(float(fit.cov[k, k]))
        interval = fraction_interval(student_interval(b, se, fit.df, SENSITIVITY_LEVEL))
    except InferenceError as error:
        return _not(trial, Status.NOT_DONE, str(error), principal.spec)
    reading, sentence = bounded_reading(
        interval, None, None, context.delta, context.periods_declared
    )
    return _base(
        trial,
        Status.ESTIMATED,
        n_journees=design.n,
        n_montees=_climbs(principal.units),
        p=design.p,
        retraits=_withdrawals(principal.spec),
        niveau=SENSITIVITY_LEVEL,
        estimation_fraction=fraction_per_year(b),
        intervalle_fraction=_pair(interval),
        lecture=reading.value,
        phrase=sentence,
        variante_effective=True,
    )


def _moving_or_undetermined(
    trial: Trial, context: _Context, principal: Fitted
) -> TrialRow:
    """S12 : ``y`` en M ou U ; une montée sans valeur est retirée et comptée."""
    units: list[Unit] = []
    removed = 0
    effective = False
    for unit in principal.units:
        keep = [c for c in unit.climbs if c.y_s12 is not None]
        removed += len(unit.climbs) - len(keep)
        ys = tuple(c.y_s12 for c in keep if c.y_s12 is not None)
        effective = effective or any(c.y_s12 != c.y for c in keep)
        if keep:
            units.append(Unit(unit.day, tuple(keep), ys))
    return _refit(
        trial,
        context,
        principal,
        units,
        effective=effective or removed > 0,
        removed_climbs=removed,
    )


def _preceding_time(trial: Trial, context: _Context, principal: Fitted) -> TrialRow:
    """S13 : plus la moyenne de journée de ``preceding_moving_s``, à l'étage 2."""
    columns = [*principal.design.columns, EXTRA_PRECEDING_MOVING]
    return _refit(
        trial, context, principal, principal.units, effective=True, columns=columns
    )


def _clustered(trial: Trial, context: _Context, principal: Fitted) -> TrialRow:
    """S14 : l'étage 2 en MCO, intervalle du bootstrap sauvage par grappes de mois."""
    design = principal.design
    months = sorted({(d.year, d.month) for d in design.days})
    minimum = integer_parameter(context.parameters, "s14_min_months")
    if len(months) < minimum:
        return _not(
            trial,
            Status.NOT_DONE,
            f"{len(months)} mois non vides, sous s14_min_months = {minimum}",
            principal.spec,
        )
    labels = [months.index((d.year, d.month)) for d in design.days]
    k = design.index(DATE)
    try:
        fit = ols([list(r) for r in design.X], list(design.y))
        interval = wild_cluster_interval(
            [list(r) for r in design.X],
            list(design.y),
            labels,
            k,
            SENSITIVITY_LEVEL,
            integer_parameter(context.parameters, "bootstrap_draws"),
            child_rng(Q2_ROOT_SEED, 2, trial.index, 1),
        )
    except InferenceError as error:
        return _not(trial, Status.NOT_DONE, str(error), principal.spec)
    fraction = fraction_interval(interval)
    reading, sentence = bounded_reading(
        fraction, None, None, context.delta, context.periods_declared
    )
    return _base(
        trial,
        Status.ESTIMATED,
        n_journees=design.n,
        n_montees=_climbs(principal.units),
        p=design.p,
        retraits=_withdrawals(principal.spec),
        niveau=SENSITIVITY_LEVEL,
        estimation_fraction=fraction_per_year(float(fit.coef[k])),
        intervalle_fraction=_pair(fraction),
        lecture=reading.value,
        phrase=sentence,
        variante_effective=True,
    )


def _route_free(trial: Trial, context: _Context, principal: Fitted) -> TrialRow:
    """S15 : sans les indicatrices de parcours."""
    columns = [c for c in principal.design.columns if not c.startswith("parcours_")]
    return _refit(
        trial,
        context,
        principal,
        principal.units,
        effective=len(columns) != len(principal.design.columns),
        columns=columns,
    )


def _within_day(trial: Trial, context: _Context, principal: Fitted) -> TrialRow:
    """S17 : réponse ``ȳ_s − η̂₁·h̄_s``, sans colonne de FC (Q-49 (f))."""
    eta = principal.stage_eta
    if eta is None:
        return _not(
            trial, Status.NOT_DONE, "pente intra-journée absente", principal.spec
        )
    design = principal.design
    response = [y - eta * h for y, h in zip(design.y, design.h_bar, strict=True)]
    columns = [c for c in design.columns if c not in HR_COLUMNS]
    reduced = replace(
        design,
        columns=tuple(columns),
        X=tuple(
            tuple(v for c, v in zip(design.columns, row, strict=True) if c in columns)
            for row in design.X
        ),
        y=tuple(response),
    )
    try:
        fitted = replace(
            principal, design=reduced, direct=fit_direct(reduced, context.parameters)
        )
    except (NotEstimableError, InferenceError) as error:
        return _not(trial, Status.NOT_DONE, str(error), principal.spec)
    return _sensitivity_row(trial, context, fitted, effective=True)


def _inverse_only(
    trial: Trial, context: _Context, principal: Fitted, level: float
) -> TrialRow:
    """S18 : la régression inverse du principal seule, au niveau du principal ;
    aucun calcul de plus (correction B)."""
    inverse = principal.inverse
    assert inverse is not None
    if inverse.k_contains_zero or principal.inverse_interval is None:
        reading, sentence = Reading.UNDECIDED, "les données ne tranchent pas"
    else:
        reading, sentence = bounded_reading(
            None,
            principal.inverse_interval,
            None,
            context.delta,
            context.periods_declared,
        )
    return _base(
        trial,
        Status.ESTIMATED,
        n_journees=principal.design.n,
        n_montees=_climbs(principal.units),
        p=inverse.design.p,
        retraits=_withdrawals(principal.spec),
        niveau=level,
        inverse_fraction=fraction_per_year(inverse.b_inv),
        intervalle_inverse_fraction=_pair(principal.inverse_interval),
        k_contient_zero=inverse.k_contains_zero,
        lecture=reading.value,
        phrase=sentence,
        tirages_retires=principal.removed,
        variante_effective=True,
        **_reml_fields(inverse.reml),
    )


def _kappa_row(trial: Trial, context: _Context) -> TrialRow:
    """S19, S20 : ``κ`` de M-S, intervalle à 95 %."""
    spec = context.spec(trial.regime, Measure.MS)
    if not spec.estimable:
        return _not(trial, Status.NOT_DONE, spec.reason or "", spec)
    try:
        fit = kappa_fit(spec, context.parameters)
    except (NotEstimableError, InferenceError) as error:
        return _not(trial, Status.NOT_DONE, str(error), spec)
    inside = fit.interval.low <= 1.0 <= fit.interval.high
    return _base(
        trial,
        Status.ESTIMATED,
        n_journees=spec.n,
        p=spec.p + 1,
        retraits=_withdrawals(spec),
        niveau=KAPPA_LEVEL,
        kappa=fit.kappa,
        intervalle_kappa=_pair(fit.interval),
        mention=None if inside else MENTION_INTENSITY,
        variante_effective=True,
        **_reml_fields(fit.reml),
    )


SENSITIVITIES: Mapping[str, Callable[[Trial, _Context, Fitted], TrialRow]] = {
    "S1": lambda t, c, p: _heart_rate_variant(t, c, p, HeartRate.UNLAGGED),
    "S2": lambda t, c, p: _heart_rate_variant(t, c, p, HeartRate.SECOND_HALF),
    "S3": _other_form,
    "S4": lambda t, c, p: _stable_only(t, c, p),
    "S5": lambda t, c, p: (
        _not(t, Status.NOT_DONE, NO_PERIODS, p.spec)
        if c.data.periods is None
        else _subset(t, c, p, lambda u: u.day.period is not Period.DISCOVERY)
    ),
    "S8": _season_free,
    "S9": _common_support,
    "S10": _e_s_switch,
    "S11": _robust,
    "S12": _moving_or_undetermined,
    "S13": _preceding_time,
    "S14": _clustered,
    "S15": _route_free,
    "S16": lambda t, c, p: _heart_rate_variant(t, c, p, HeartRate.ELAPSED),
    "S17": _within_day,
}


def _stable_only(trial: Trial, context: _Context, principal: Fitted) -> TrialRow:
    """S4 : les montées ``stable is True`` sans ``slow_moving`` seules."""
    units: list[Unit] = []
    for unit in principal.units:
        keep = [
            (c, y)
            for c, y in zip(unit.climbs, unit.y, strict=True)
            if c.stable is True and not c.slow_moving
        ]
        if keep:
            units.append(
                Unit(unit.day, tuple(c for c, _ in keep), tuple(y for _, y in keep))
            )
    effective = _climbs(units) != _climbs(principal.units)
    return _refit(trial, context, principal, units, effective=effective)


# --- l'autocorrélation, les bornes ----------------------------------------------


def autocorrelation_rows(
    regime: ClimbRegime, fitted: Fitted
) -> list[tuple[str, str, int, int | None, int, float | None]]:
    """Les classes de l'autocorrélation des résidus de M-P d'un régime estimé."""
    classes = residual_autocorrelation(
        list(fitted.design.t),
        fitted.direct.reml.fit.resid.tolist(),
        AUTOCORRELATION_CLASSES,
    )
    return [
        (regime.value, Measure.MP.value, c.low, c.high, c.pairs, c.correlation)
        for c in classes
    ]


MANQUE: frozenset[Q2Motif] = frozenset(
    {
        Q2Motif.FLAG,
        Q2Motif.NO_SPEED,
        Q2Motif.NO_HEART_RATE,
        Q2Motif.JOURNAL,
        Q2Motif.RESTING_INVALID,
        Q2Motif.NO_NORMAL,
        Q2Motif.STRADDLING,
        Q2Motif.UNCERTAIN,
        Q2Motif.RESTING_AFTER,
    }
)
"""Les motifs « manque » des bornes (§ 9.6, Q-50 (f))."""


@dataclass(frozen=True)
class _Missing:
    """Une journée exclue par un manque : sa date, sa période, ses moyennes (``None``
    pour une grandeur absente), son groupe de parcours, le nombre de ses montées, et si
    elle est parmi les journées des étapes 1 à 4 (exclue à l'étape 5)."""

    day: date
    period: Period
    features: dict[str, float | None]
    group: int | None
    count: int
    kept: bool


def _period_mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _missing_days(
    data: Q2Data, fitted: Fitted
) -> tuple[list[_Missing], dict[Period, tuple[int, int]]]:
    """Les journées exclues par un manque et, par période, ``(manques, journées)``."""
    regime = fitted.spec.regime
    spec = fitted.spec
    sample = {u.day.day for u in fitted.units}
    kept_days = {d.day: d for d in spec.days}
    excluded: dict[date, list[Any]] = {}
    for climb in data.excluded:
        if climb.regime is regime:
            excluded.setdefault(climb.day, []).append(climb)
    days = sorted({*kept_days, *excluded})
    counts: dict[Period, list[int]] = {
        Period.DISCOVERY: [0, 0],
        Period.AFTER: [0, 0],
    }
    missing: list[_Missing] = []
    for day in days:
        climbs = excluded.get(day, [])
        q2_day = kept_days.get(day)
        defining = [c for c in climbs if c.motif is Q2Motif.SHORT_GAIN]
        if q2_day is None and len(defining) == len(climbs):
            continue
        period = q2_day.period if q2_day else climbs[0].period
        if period in counts:
            counts[period][1] += 1
        if day in sample:
            continue
        motifs = {c.motif for c in climbs}
        if q2_day is not None:
            if not spec.step5_applied or q2_day.step5 is None:
                continue
            motifs.add(q2_day.step5)
        if not motifs & MANQUE:
            continue
        if period in counts:
            counts[period][0] += 1
        if period not in counts:
            continue
        missing.append(_imputable(day, period, q2_day, climbs, spec))
    return missing, {p: (c[0], c[1]) for p, c in counts.items()}


def _imputable(
    day: date,
    period: Period,
    q2_day: Q2Day | None,
    climbs: Sequence[Any],
    spec: ModelSpec,
) -> _Missing:
    def mean(values: Sequence[float | None]) -> float | None:
        present = [v for v in values if v is not None]
        return statistics.fmean(present) if present else None

    if q2_day is not None:
        unit = unit_of(q2_day, Measure.MP)
        features: dict[str, float | None] = dict(day_features(unit, HeartRate.LAGGED))
        features["e_s"] = None
        count = len(q2_day.climbs) + len(climbs)
        group = spec.group_of(day)
    else:
        features = {
            "h": mean([c.h for c in climbs]),
            "log_gain": mean([c.log_gain for c in climbs]),
            "pente": mean([c.grade for c in climbs]),
            "altitude": mean([c.elevation_m for c in climbs]),
            "d_plus_avant": mean([c.preceding_ascent_m for c in climbs]),
            "d_moins_avant": mean([c.preceding_descent_m for c in climbs]),
            "heure": mean([c.hour for c in climbs]),
            EXTRA_PRECEDING_MOVING: None,
            "e_s": None,
        }
        heure = features["heure"]
        features["heure"] = None if heure is None else heure - 12.0
        count = len(climbs)
        group = None
    return _Missing(day, period, features, group, max(1, count), q2_day is not None)


def bounds(context: _Context, fitted: Fitted) -> dict[str, object]:
    """Les bornes d'un régime estimé (§ 9.6) : les parts exclues par les manques en
    découverte et ensuite ; déclenchées au-delà de ``bounds_trigger``, ``b`` aux deux
    bornes (GLS à la ``V`` du principal sur l'échantillon augmenté)."""
    if context.data.periods is None:
        return {"statut": "sans période"}
    missing, counts = _missing_days(context.data, fitted)
    parts = {
        p.value: (m / total if total else None) for p, (m, total) in counts.items()
    }
    values = [v for v in parts.values() if v is not None]
    triggered = (
        len(values) == 2
        and abs(values[0] - values[1]) > context.parameters["bounds_trigger"]
    )
    if not triggered or not missing:
        return {"statut": "non declenchees", "parts": parts}
    design = fitted.direct.design
    reml = fitted.direct.reml
    coef = [float(c) for c in reml.fit.coef.tolist()]
    by_period: dict[Period, list[list[float]]] = {}
    for unit, row in zip(fitted.units, design.X, strict=True):
        by_period.setdefault(unit.day.period, []).append(list(row))
    first = design.days[0]
    rows: list[list[float]] = []
    for item in missing:
        kept_rows = by_period.get(item.period, [])
        averages = [
            _period_mean([r[k] for r in kept_rows]) for k in range(len(design.columns))
        ]
        rows.append(_imputed_row(item, design, averages, first))
    fitted_values = [sum(x * b for x, b in zip(row, coef, strict=True)) for row in rows]
    low, high = imputed_bounds(
        fitted_values, [m.period.value for m in missing], reml.tau2, reml.s2u
    )
    s2e = fitted.sigma2
    augmented: list[tuple[date, list[float], float, float, float]] = [
        (day, list(values), y, d, y)
        for day, values, y, d in zip(
            design.days, design.X, design.y, design.d, strict=True
        )
    ]
    for m, imputed, lo, hi in zip(missing, rows, low, high, strict=True):
        if lo is None or hi is None:
            continue
        augmented.append((m.day, imputed, lo, s2e / m.count, hi))
    augmented.sort(key=lambda entry: entry[0])
    origin = augmented[0][0]
    k = design.index(DATE)
    t = [float((entry[0] - origin).days) for entry in augmented]
    matrix: list[list[float]] = []
    for entry, ti in zip(augmented, t, strict=True):
        line = list(entry[1])
        line[k] = ti
        matrix.append(line)
    covariance = three_component_cov(
        t, [entry[3] for entry in augmented], reml.tau2, reml.s2u, reml.phi
    ).tolist()
    y_low = [entry[2] for entry in augmented]
    y_high = [entry[4] for entry in augmented]
    try:
        b_low, _ = date_effect_at(matrix, y_low, covariance, k)
        b_high, _ = date_effect_at(matrix, y_high, covariance, k)
    except InferenceError as error:
        return {"statut": "non calculees", "parts": parts, "motif": str(error)}
    return {
        "statut": "declenchees",
        "parts": parts,
        "journees_imputees": len(missing),
        "b_basse_fraction": fraction_per_year(b_low),
        "b_haute_fraction": fraction_per_year(b_high),
    }


def _imputed_row(
    item: _Missing, design: Design, averages: Sequence[float | None], first: date
) -> list[float]:
    """La ligne d'une journée imputée : ses covariables, une covariable absente prise
    à la moyenne de sa période parmi les journées gardées (Q-49 (j)). Ses indicatrices
    de parcours : une journée sans groupe (exclue aux étapes 1 à 3, sans journée des
    étapes 1 à 4) prend, dans chacune, la moyenne de sa période parmi les journées
    gardées ; une journée exclue à l'étape 5 garde le groupe que ``route_groups`` lui
    rend : 1 dans sa colonne et 0 ailleurs, 0 partout si ce groupe est « autre » (la
    référence, Q-49 (h)) ou n'a pas de colonne au modèle."""
    features = dict(item.features)
    names = list(design.columns)
    covariates = (
        "log_gain",
        "pente",
        "altitude",
        "d_plus_avant",
        "d_moins_avant",
        "heure",
        "e_s",
    )
    for name in covariates:
        if features.get(name) is None and name in names:
            features[name] = averages[names.index(name)]
    if features.get("h") is None:
        if LINEAR_HR in names:
            features["h"] = averages[names.index(LINEAR_HR)]
        elif SPLINE[0] in names:
            features["h"] = averages[names.index(SPLINE[0])]
    h = features.get("h") or 0.0
    fc = (
        heart_rate_columns([h], design.knots)[0]
        if design.knots is not None
        else (h, 0.0)
    )
    full = {k: (0.0 if v is None else v) for k, v in features.items()}
    full.setdefault(EXTRA_PRECEDING_MOVING, 0.0)
    values = row_values(
        full,
        float((item.day - first).days),
        item.day,
        full.get("e_s", 0.0),
        item.group,
        [int(c.split("_")[1]) for c in names if c.startswith("parcours_")],
        fc,
    )
    row = []
    for k, name in enumerate(names):
        if name.startswith("parcours_") and not item.kept:
            row.append(averages[k] or 0.0)
        else:
            row.append(values[name])
    return row


# --- les 24 essais ------------------------------------------------------------------


def q2_trials(
    data: Q2Data,
    parameters: ParameterSet,
    power: Mapping[str, PowerLevel],
    workers: int = 1,
) -> Q2Estimation:
    """Les 24 essais de Q2, dans leur ordre, avec les niveaux tirés du dernier résultat
    de puissance (``power``, par régime), Holm sur les cinq secondaires, les bornes et
    l'autocorrélation."""
    context = _Context(data, parameters, power, workers)
    for regime in Q2_REGIMES:
        for measure in Measure:
            context.specs[(regime, measure)] = model_spec(
                data.days[regime], measure, regime, parameters
            )
    rows: dict[int, TrialRow] = {}
    pvalues: dict[int, float] = {}
    fitted_mp: dict[ClimbRegime, Fitted] = {}
    for trial in TRIALS[:3]:
        extra = MENTION_SHORT if trial.regime is SHORT else None
        row, fitted, p_value = _bounded_row(trial, context, extra)
        rows[trial.index] = row
        pvalues[trial.index] = p_value
        if fitted is not None:
            fitted_mp[trial.regime] = fitted
    kappas: dict[ClimbRegime, KappaFit | None] = {}
    for trial in TRIALS[3:6]:
        extra = MENTION_SHORT if trial.regime is SHORT else None
        row, p_value, kappa = _ms_row(trial, context, extra)
        rows[trial.index] = row
        pvalues[trial.index] = p_value
        kappas[trial.regime] = kappa
    rejected = holm([pvalues[i] for i in range(1, 6)], parameters["alpha"])
    for i, reject in zip(range(1, 6), rejected, strict=True):
        rows[i] = replace(rows[i], p_valeur=pvalues[i], holm_rejet=reject)
    principal = fitted_mp.get(LONG)
    sensitivities = SENSITIVITIES
    principal_level, _ = _level(context, LONG)
    for trial in TRIALS[6:]:
        if trial.name in ("S19", "S20"):
            rows[trial.index] = _kappa_row(trial, context)
            continue
        if principal is None:
            rows[trial.index] = _not(
                trial,
                Status.NOT_DONE,
                "principal non estimé",
                context.spec(LONG, Measure.MP),
            )
            continue
        if trial.name == "S18":
            rows[trial.index] = _inverse_only(
                trial, context, principal, principal_level
            )
            continue
        rows[trial.index] = sensitivities[trial.name](trial, context, principal)
    levels = {
        TRIALS[i].name: rows[i].niveau for i in range(24) if rows[i].niveau is not None
    }
    bound_documents: dict[str, object] = {}
    autocorrelation: list[tuple[str, str, int, int | None, int, float | None]] = []
    for regime in Q2_REGIMES:
        fitted = fitted_mp.get(regime)
        if fitted is None:
            continue
        bound_documents[regime.value] = bounds(context, fitted)
        autocorrelation.extend(autocorrelation_rows(regime, fitted))
    return Q2Estimation(
        rows=tuple(rows[i] for i in range(24)),
        specs=dict(context.specs),
        principal=principal,
        levels={k: v for k, v in levels.items() if v is not None},
        bounds=bound_documents,
        autocorrelation=tuple(autocorrelation),
    )
