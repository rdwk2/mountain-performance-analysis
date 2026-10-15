"""L'admission exploratoire d'un effet : évaluabilité, seuils, gains, garde-fous,
verdict (M4c-3).

``0010`` D10 et ses précisions de M4c-3 ; décisions Q1, Q6, Q7 et E1 à E5 du brief.
Fonctions pures : aucune lecture, aucune écriture. Les entrées sont, par performance
déclarée, l'observation d'usage de sa sortie et les scores d'usage de v0 brut, de la
base (0) et du candidat (1), avec les références figées de la DÉCLARATION ; les seuils
et ``ε`` sont les constantes de ``mountain_perf.schemas.admission``. Le document rendu
(``Admission``) recalcule lui-même ce qui découle de ses valeurs : ce module en est le
seul producteur.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from mountain_perf.backtest.calibration import calibrated_forecast
from mountain_perf.backtest.metrics import is_invalid_model_output, usage_target
from mountain_perf.schemas import (
    CLOCKS,
    CalibratedScenarioScores,
    ClockScores,
    ExperimentDeclaration,
    ExperimentMetric,
    FrozenReference,
    MetricValue,
    ModelCalibration,
    OutingObservation,
    Performance,
    ReferenceSource,
    RegimeClass,
    ScenarioScores,
    TargetMember,
    Unavailability,
)
from mountain_perf.schemas.admission import (
    COMPARABLE_DPLUS_PER_KM,
    COMPARABLE_MAX_S,
    GAIN_FLOOR,
    GAIN_SHARE,
    GUARD_METRICS,
    HARM_FLOOR,
    HARM_MAX_FACTOR,
    HARM_SHARE,
    NUMERIC_TOLERANCE,
    PASSAGE_TOLERANCE,
    REGIME_MIN_SEGMENTS,
    Admission,
    AdmissionReserve,
    AdmissionVerdict,
    EffortValue,
    FailedCheck,
    FailedCondition,
    GuardOutcome,
    GuardStatus,
    GuardValue,
    NonEvaluable,
    PassageGuardOutcome,
    PassageValue,
    PerformanceAssessment,
    ReviewCause,
    ReviewReason,
    ThresholdSource,
    required_successes,
)

REGIME_METRICS: Mapping[ExperimentMetric, tuple[RegimeClass, str]] = MappingProxyType(
    {
        ExperimentMetric.ASCENT_LEVEL: (RegimeClass.ASCENT, "level"),
        ExperimentMetric.FLAT_LEVEL: (RegimeClass.FLAT, "level"),
        ExperimentMetric.DESCENT_LEVEL: (RegimeClass.DESCENT, "level"),
        ExperimentMetric.ASCENT_DISPERSION: (RegimeClass.ASCENT, "dispersion"),
        ExperimentMetric.FLAT_DISPERSION: (RegimeClass.FLAT, "dispersion"),
        ExperimentMetric.DESCENT_DISPERSION: (RegimeClass.DESCENT, "dispersion"),
    }
)
"""La classe et la nature (``level`` : ``|E_R|``, ``dispersion`` : ``D_R``) de chaque
métrique de régime (``0010`` D10.1, D10.4)."""

_Keyed = Mapping[tuple[ExperimentMetric, ReferenceSource, str | None], FrozenReference]


@dataclass(frozen=True)
class AdmissionInput:
    """Ce que l'expérience sait d'une performance déclarée (en mémoire, jamais
    stockée).

    - ``performance`` : la performance ;
    - ``excluded`` : une de ses sorties est l'objet d'une exclusion d'admission ;
    - ``observation`` : l'observation de sa sortie ; absente pour un jour
      multi-sorties ou une sortie non scorée ;
    - ``raw``, ``base``, ``candidate`` : les scores d'**usage** de v0 brut (non
      calés), de (0) et de (1) (calés) ; tous trois présents si la sortie a un
      scénario d'usage, tous trois absents sinon ;
    - ``dplus_per_km`` : le D+/km du profil de domaine (m/km), absent pour un jour
      multi-sorties ;
    - ``portion_s`` : la durée de v0 brut à l'effort 1 sur la portion déclarée (s ;
      décision Q7).
    """

    performance: Performance
    excluded: bool
    observation: OutingObservation | None
    raw: ScenarioScores | None
    base: CalibratedScenarioScores | None
    candidate: CalibratedScenarioScores | None
    dplus_per_km: float | None
    portion_s: float | None


def metric_value(scores: ClockScores, metric: ExperimentMetric) -> MetricValue:
    """Une métrique autre que ``q_usage`` dans les scores d'une horloge (``0010``
    D10.1) : ``|L|``, le niveau de tout le support en valeur absolue ; ``|E_R|``, le
    niveau de la classe ``R`` en valeur absolue ; ``D_R``, sa dispersion telle quelle.
    Indisponible, elle garde son motif et son effectif (la valeur absolue ne touche que
    ``value``).

    Précondition (``ValueError``) : ``metric`` n'est pas ``q_usage``.
    """
    if metric is ExperimentMetric.USAGE:
        raise ValueError("metric_value : q_usage n'est pas une métrique du support.")
    if metric is ExperimentMetric.LEVEL:
        return _absolute(scores.support.log_ratio)
    regime_class, kind = REGIME_METRICS[metric]
    metrics = scores.support.classes[list(RegimeClass).index(regime_class)]
    if kind == "dispersion":
        return metrics.dispersion
    return _absolute(metrics.log_ratio)


def _absolute(value: MetricValue) -> MetricValue:
    if value.value is None:
        return value
    return MetricValue(abs(value.value), value.unavailability, value.count)


# ---------------------------------------------------------------------------
# Évaluabilité, seuils, cibles
# ---------------------------------------------------------------------------


def _route(entry: AdmissionInput) -> str | None:
    """Le parcours de la performance : celui de sa première sortie."""
    return entry.performance.outings[0].route_id


def _members(
    experiment: ExperimentDeclaration,
    route_id: str | None,
    observation: OutingObservation,
) -> tuple[tuple[int, ...], tuple[float, ...] | None]:
    """Les rangs de ``K`` dans le ``K`` par défaut de l'observation, et ses poids : le
    ``K`` déclaré pour ce parcours s'il y en a un, sinon tout le ``K`` par défaut et
    ses poids par défaut (D7.4)."""
    declared = next(
        (target for target in experiment.usage_targets if target.route_id == route_id),
        None,
    )
    if declared is None:
        return tuple(range(len(observation.members))), None
    absent: list[TargetMember] = [
        member for member in declared.members if member not in observation.members
    ]
    if absent:
        raise ValueError(
            f"admit : K du parcours {route_id!r}, éléments hors du K par défaut de "
            f"l'observation : {absent}"
        )
    ranks = tuple(observation.members.index(member) for member in declared.members)
    return ranks, declared.weights


def _observation_motif(
    experiment: ExperimentDeclaration,
    route_id: str | None,
    observation: OutingObservation,
    i: int,
) -> NonEvaluable | None:
    """Le motif d'observation de la cible sous l'horloge ``i`` (D10.2 ; P2, P11)."""
    if experiment.target is ExperimentMetric.USAGE:
        ranks, _ = _members(experiment, route_id, observation)
        if any(observation.targets[k].unavailability is not None for k in ranks):
            return NonEvaluable.PASSAGE_UNAVAILABLE
        return None
    regime_class, _ = REGIME_METRICS[experiment.target]
    segments = observation.segments
    count = sum(1 for segment in segments if segment.regime_class is regime_class)
    if not segments or not count:
        return NonEvaluable.INSUFFICIENT_SUPPORT
    if any(segment.times_s[i] == 0 for segment in segments):
        return NonEvaluable.ZERO_TIME
    if count < REGIME_MIN_SEGMENTS:
        return NonEvaluable.UNDERREPRESENTED
    return None


def _motif(
    experiment: ExperimentDeclaration, entry: AdmissionInput, i: int
) -> NonEvaluable | None:
    """Le premier motif de non-évaluabilité, dans l'ordre de ``NonEvaluable``."""
    if entry.excluded:
        return NonEvaluable.EXCLUDED
    if entry.performance.is_multi_outing:
        return NonEvaluable.MULTI_OUTING
    if entry.observation is None:
        return NonEvaluable.UNSCORED
    if entry.base is None:
        return NonEvaluable.NO_USAGE
    motif = _observation_motif(experiment, _route(entry), entry.observation, i)
    if motif is not None:
        return motif
    unavailability = entry.base.clocks[i].calibration.unavailability
    if unavailability is Unavailability.NOT_CALIBRATED:
        return NonEvaluable.NOT_CALIBRATED
    return None


def _keyed(
    experiment: ExperimentDeclaration, references: Sequence[FrozenReference]
) -> _Keyed:
    """Les références reçues sous l'horloge de l'expérience seulement, par clé
    ``(métrique, source, parcours)``."""
    return {
        (reference.metric, reference.source, reference.route_id): reference
        for reference in references
        if reference.clock == experiment.clock
    }


def _reference(
    keyed: _Keyed,
    metric: ExperimentMetric,
    route_id: str | None,
    comparable: bool,
) -> tuple[ThresholdSource, float | None, Unavailability | None]:
    """La source, ``F`` et le motif de la locale (D10.3 ; P6) : la locale disponible ;
    sinon l'empruntée disponible d'une performance comparable ; sinon le seuil fixe. Le
    motif de la locale est publié quand elle n'est pas la source (``absent`` sans
    locale du parcours)."""
    local = keyed.get((metric, ReferenceSource.LOCAL, route_id))
    if local is not None and local.value.value is not None:
        return ThresholdSource.LOCAL, local.value.value, None
    motif = Unavailability.ABSENT if local is None else local.value.unavailability
    borrowed = keyed.get((metric, ReferenceSource.BORROWED, None))
    if comparable and borrowed is not None and borrowed.value.value is not None:
        return ThresholdSource.BORROWED, borrowed.value.value, motif
    return ThresholdSource.FIXED, None, motif


def _effort(calibration: ModelCalibration) -> EffortValue | None:
    """L'effort libre ``exp(−β)``, borné et saturé d'un calage disponible (E1)."""
    if (
        calibration.unavailability is not None
        or calibration.beta is None
        or calibration.effort is None
    ):
        return None
    return EffortValue(
        math.exp(-calibration.beta), calibration.effort, calibration.saturated
    )


def _classification(
    entry: AdmissionInput, i: int
) -> tuple[bool | None, Unavailability | None, float | None]:
    """« Comparable » (D10.3 ; décisions Q7 et E3) : ``(comparable, motif,
    durée projetée)``."""
    if entry.portion_s is None or entry.base is None or entry.dplus_per_km is None:
        return None, None, None
    calibration = entry.base.clocks[i].calibration
    if calibration.unavailability is None and calibration.effort is not None:
        projected = entry.portion_s / calibration.effort
    elif calibration.unavailability is Unavailability.NOT_CALIBRATED:
        projected = entry.portion_s
    else:
        return None, calibration.unavailability, None
    low, high = COMPARABLE_DPLUS_PER_KM
    comparable = (
        entry.performance.all_training
        and low <= entry.dplus_per_km <= high
        and projected <= COMPARABLE_MAX_S
    )
    return comparable, None, projected


def _calibrated_metric(
    scores: CalibratedScenarioScores,
    raw: ScenarioScores,
    i: int,
    metric: ExperimentMetric,
) -> MetricValue:
    """La métrique des scores calés sous l'horloge ``i`` ; sans scores calés, la
    métrique de v0 brut si elle y est indisponible au motif de l'observation (support
    insuffisant, temps nul : l'observation passe avant le modèle, précision de D7.1),
    sinon indisponible au motif du calage (choix 21)."""
    entry = scores.clocks[i]
    if entry.scores is not None:
        return metric_value(entry.scores, metric)
    observed = metric_value(raw.clocks[i], metric)
    if observed.unavailability in (
        Unavailability.INSUFFICIENT_SUPPORT,
        Unavailability.ZERO_TIME,
    ):
        return observed
    motif = entry.calibration.unavailability or Unavailability.MODEL_ERROR
    return MetricValue(None, motif, 0)


def _unavailable(calibration: ModelCalibration) -> MetricValue:
    return MetricValue(
        None, calibration.unavailability or Unavailability.MODEL_ERROR, 0
    )


def _usage_values(
    experiment: ExperimentDeclaration, entry: AdmissionInput, i: int
) -> tuple[MetricValue, MetricValue, MetricValue]:
    """``q_usage`` de (0), de (1) et de v0 brut sous l'horloge ``i``, au dénominateur
    commun ``P^(0)``, la prévision **calée** de (0) (D7.4 dans une expérience)."""
    assert entry.observation is not None  # performance évaluable
    assert entry.raw is not None
    assert entry.base is not None
    assert entry.candidate is not None
    observation = entry.observation
    ranks, weights = _members(experiment, _route(entry), observation)
    targets = [observation.targets[k] for k in ranks]
    observed = [None if t.times_s is None else t.times_s[i] for t in targets]
    motifs = [target.unavailability for target in targets]
    base_calibration = entry.base.clocks[i].calibration
    if base_calibration.unavailability is not None:
        missing = _unavailable(base_calibration)
        return missing, missing, missing
    base_s = calibrated_forecast(entry.base.forecast, base_calibration).target_s
    base_k = [base_s[k] for k in ranks]

    def q(projected: Sequence[float | None]) -> MetricValue:
        target = usage_target(
            [projected[k] for k in ranks], base_k, observed, motifs, weights=weights
        )
        return target.q_usage

    candidate_calibration = entry.candidate.clocks[i].calibration
    if candidate_calibration.unavailability is not None:
        candidate = _unavailable(candidate_calibration)
    else:
        forecast = calibrated_forecast(entry.candidate.forecast, candidate_calibration)
        candidate = q(forecast.target_s)
    return q(base_s), candidate, q(entry.raw.forecast.target_s)


def _target_values(
    experiment: ExperimentDeclaration, entry: AdmissionInput, i: int
) -> tuple[MetricValue, MetricValue, MetricValue]:
    """La cible de (0), de (1) et de v0 brut sous l'horloge ``i``."""
    if experiment.target is ExperimentMetric.USAGE:
        return _usage_values(experiment, entry, i)
    assert entry.raw is not None
    assert entry.base is not None
    assert entry.candidate is not None
    target = experiment.target
    return (
        _calibrated_metric(entry.base, entry.raw, i, target),
        _calibrated_metric(entry.candidate, entry.raw, i, target),
        metric_value(entry.raw.clocks[i], target),
    )


def _difference(first: MetricValue, second: MetricValue) -> float | None:
    if first.value is None or second.value is None:
        return None
    return first.value - second.value


def _gain_threshold(reference: float | None) -> float:
    if reference is None:
        return GAIN_FLOOR
    return max(GAIN_FLOOR, GAIN_SHARE * reference)


def _harm_threshold(reference: float | None) -> float:
    if reference is None:
        return HARM_FLOOR
    return max(HARM_FLOOR, HARM_SHARE * reference)


def assess_performances(
    experiment: ExperimentDeclaration,
    inputs: Sequence[AdmissionInput],
    references: Sequence[FrozenReference],
) -> tuple[PerformanceAssessment, ...]:
    """L'évaluation de chaque performance déclarée, dans l'ordre reçu (``0010`` D10.2,
    D10.3, D10.5 ; précisions de M4c-3).

    Pour chaque entrée : le premier motif de non-évaluabilité ; la classification
    « comparable », publiée pour toute performance (choix 23) ; pour une évaluable, la
    source de ``F_j`` — fixe, sans ``F`` ni motif, sous ``q_usage`` (choix 22) —,
    ``δ_j``, les cibles de (0), de (1) et de v0 brut sous l'horloge déclarée, ``G_j``,
    ``G_j^brut`` et les efforts de (0) et de (1).

    Précondition (``ValueError``) : par entrée, les scores d'usage de v0 brut, de (0)
    et de (1) tous présents ou tous absents ; et celle de ``_members`` (un ``K`` déclaré
    inclus dans le ``K`` par défaut de l'observation).
    """
    for entry in inputs:
        present = {
            score is not None for score in (entry.raw, entry.base, entry.candidate)
        }
        if len(present) > 1:
            raise ValueError(
                "assess_performances : les scores d'usage de v0 brut, de (0) et de (1) "
                "sont tous présents ou tous absents."
            )
    i = CLOCKS.index(experiment.clock)
    keyed = _keyed(experiment, references)
    return tuple(_assess(experiment, entry, keyed, i) for entry in inputs)


def _assess(
    experiment: ExperimentDeclaration, entry: AdmissionInput, keyed: _Keyed, i: int
) -> PerformanceAssessment:
    performance = entry.performance
    motif = _motif(experiment, entry, i)
    comparable, comparable_unavailability, projected_s = _classification(entry, i)
    source: ThresholdSource | None = None
    local_unavailability: Unavailability | None = None
    reference: float | None = None
    threshold: float | None = None
    base: MetricValue | None = None
    candidate: MetricValue | None = None
    raw: MetricValue | None = None
    gain: float | None = None
    raw_gain: float | None = None
    base_effort: EffortValue | None = None
    candidate_effort: EffortValue | None = None
    if motif is None:
        assert entry.base is not None
        assert entry.candidate is not None
        if experiment.target is ExperimentMetric.USAGE:
            source = ThresholdSource.FIXED
        else:
            source, reference, local_unavailability = _reference(
                keyed, experiment.target, _route(entry), comparable is True
            )
        threshold = _gain_threshold(reference)
        base, candidate, raw = _target_values(experiment, entry, i)
        gain = _difference(base, candidate)
        raw_gain = _difference(raw, candidate)
        base_effort = _effort(entry.base.clocks[i].calibration)
        candidate_effort = _effort(entry.candidate.clocks[i].calibration)
    return PerformanceAssessment(
        civil_date=performance.civil_date,
        outing_ids=tuple(outing.outing_id for outing in performance.outings),
        motif=motif,
        comparable=comparable,
        comparable_unavailability=comparable_unavailability,
        dplus_per_km=entry.dplus_per_km,
        projected_s=projected_s,
        source=source,
        local_unavailability=local_unavailability,
        reference=reference,
        threshold=threshold,
        base=base,
        candidate=candidate,
        raw=raw,
        gain=gain,
        raw_gain=raw_gain,
        base_effort=base_effort,
        candidate_effort=candidate_effort,
    )


# ---------------------------------------------------------------------------
# Garde-fous et conclusion
# ---------------------------------------------------------------------------


def _guard(
    metric: ExperimentMetric,
    inputs: Sequence[AdmissionInput],
    assessed: Sequence[PerformanceAssessment],
    keyed: _Keyed,
    i: int,
) -> GuardOutcome:
    """Le garde-fou de ``metric`` sur ``J_k`` (``0010`` D10.4 ; P8) : les évaluables,
    et pour un garde-fou de régime celles où la classe compte au moins
    ``REGIME_MIN_SEGMENTS`` segments (compte de l'observation, toutes horloges)."""
    regime = REGIME_METRICS.get(metric)
    values: list[GuardValue] = []
    for entry, assessment in zip(inputs, assessed, strict=True):
        if assessment.motif is not None:
            continue
        assert entry.observation is not None
        assert entry.raw is not None
        assert entry.base is not None
        assert entry.candidate is not None
        if regime is not None:
            count = sum(
                1
                for segment in entry.observation.segments
                if segment.regime_class is regime[0]
            )
            if count < REGIME_MIN_SEGMENTS:
                continue
        base = _calibrated_metric(entry.base, entry.raw, i, metric)
        candidate = _calibrated_metric(entry.candidate, entry.raw, i, metric)
        harm = None
        if base.value is not None and candidate.value is not None:
            harm = max(0.0, candidate.value - base.value)
        source, reference, local_unavailability = _reference(
            keyed, metric, _route(entry), assessment.comparable is True
        )
        values.append(
            GuardValue(
                assessment.civil_date,
                base,
                candidate,
                harm,
                source,
                local_unavailability,
                reference,
                _harm_threshold(reference),
            )
        )
    if not values:
        return GuardOutcome(metric, (), None, None, GuardStatus.NOT_EVALUABLE)
    count = len(values)
    mean_threshold = math.fsum(value.threshold for value in values) / count
    harms = [value.harm for value in values]
    if any(harm is None for harm in harms):
        return GuardOutcome(
            metric, tuple(values), None, mean_threshold, GuardStatus.UNAVAILABLE
        )
    mean_harm = math.fsum(harm or 0.0 for harm in harms) / count
    satisfied = mean_harm <= mean_threshold + NUMERIC_TOLERANCE and all(
        value.harm is not None
        and value.harm <= HARM_MAX_FACTOR * value.threshold + NUMERIC_TOLERANCE
        for value in values
    )
    status = GuardStatus.SATISFIED if satisfied else GuardStatus.VIOLATED
    return GuardOutcome(metric, tuple(values), mean_harm, mean_threshold, status)


def _worst(entry: AdmissionInput, comparable: Sequence[int], i: int) -> float | None:
    """Le plus grand dommage relatif ``(|P^(1) − T| − |P^(0) − T|)_+ / T`` aux passages
    comparables, sur les prévisions **calées** de (0) et de (1) ; absent si un calage
    est indisponible, ou une prévision absente ou invalide."""
    assert entry.observation is not None
    assert entry.base is not None
    assert entry.candidate is not None
    base_calibration = entry.base.clocks[i].calibration
    candidate_calibration = entry.candidate.clocks[i].calibration
    if (
        base_calibration.unavailability is not None
        or candidate_calibration.unavailability is not None
    ):
        return None
    base_s = calibrated_forecast(entry.base.forecast, base_calibration).target_s
    candidate_s = calibrated_forecast(
        entry.candidate.forecast, candidate_calibration
    ).target_s
    damages: list[float] = []
    for k in comparable:
        p0, p1 = base_s[k], candidate_s[k]
        if (
            p0 is None
            or p1 is None
            or is_invalid_model_output(p0)
            or is_invalid_model_output(p1)
        ):
            return None
        times = entry.observation.targets[k].times_s
        assert times is not None
        observed = times[i]
        damages.append(max(0.0, abs(p1 - observed) - abs(p0 - observed)) / observed)
    return max(damages)


def _passages(
    experiment: ExperimentDeclaration,
    inputs: Sequence[AdmissionInput],
    assessed: Sequence[PerformanceAssessment],
    i: int,
) -> PassageGuardOutcome:
    """Le garde-fou des passages (``0010`` D10.4 ; P11) : pour chaque évaluable, les
    éléments de ``K`` — même de poids nul — observés avec ``T_k > 0`` sous l'horloge
    déclarée."""
    values: list[PassageValue] = []
    for entry, assessment in zip(inputs, assessed, strict=True):
        if assessment.motif is not None:
            continue
        observation = entry.observation
        assert observation is not None
        ranks, _ = _members(experiment, _route(entry), observation)
        comparable = []
        for k in ranks:
            times = observation.targets[k].times_s
            if times is not None and times[i] > 0:
                comparable.append(k)
        if not comparable:
            continue
        values.append(
            PassageValue(
                assessment.civil_date, len(comparable), _worst(entry, comparable, i)
            )
        )
    if not values:
        return PassageGuardOutcome((), GuardStatus.NOT_EVALUABLE)
    if any(value.worst is None for value in values):
        return PassageGuardOutcome(tuple(values), GuardStatus.UNAVAILABLE)
    satisfied = all(
        value.worst is not None and value.worst <= PASSAGE_TOLERANCE + NUMERIC_TOLERANCE
        for value in values
    )
    status = GuardStatus.SATISFIED if satisfied else GuardStatus.VIOLATED
    return PassageGuardOutcome(tuple(values), status)


def _review(
    evaluable: Sequence[PerformanceAssessment],
    guards: Sequence[GuardOutcome],
    passages: PassageGuardOutcome,
) -> tuple[ReviewReason, ...]:
    """Les causes de « à revoir », dans l'ordre (D10.2, D10.4, D10.6)."""
    review: list[ReviewReason] = []
    missing = tuple(a.civil_date for a in evaluable if a.gain is None)
    if missing:
        review.append(ReviewReason(ReviewCause.TARGET_UNAVAILABLE, None, missing))
    for guard in guards:
        if guard.status is GuardStatus.UNAVAILABLE:
            days = tuple(v.civil_date for v in guard.values if v.harm is None)
            review.append(
                ReviewReason(ReviewCause.GUARD_UNAVAILABLE, guard.metric, days)
            )
    if passages.status is GuardStatus.UNAVAILABLE:
        days = tuple(v.civil_date for v in passages.values if v.worst is None)
        review.append(ReviewReason(ReviewCause.PASSAGES_UNAVAILABLE, None, days))
    elif passages.status is GuardStatus.NOT_EVALUABLE:
        review.append(ReviewReason(ReviewCause.PASSAGES_NOT_APPLICABLE, None, ()))
    return tuple(review)


def _failures(
    evaluable: Sequence[PerformanceAssessment],
    mean_gain: float | None,
    mean_threshold: float,
    positive: int,
    guards: Sequence[GuardOutcome],
    passages: PassageGuardOutcome,
) -> tuple[FailedCheck, ...]:
    """Les conditions calculables qui échouent, dans l'ordre, publiées sous les trois
    verdicts (D10.3, D10.4 ; P13, choix 20)."""
    epsilon = NUMERIC_TOLERANCE
    failures: list[FailedCheck] = []
    if mean_gain is not None and not mean_gain >= mean_threshold - epsilon:
        failures.append(FailedCheck(FailedCondition.MEAN_GAIN, None, ()))
    absent = sum(1 for a in evaluable if a.gain is None)
    if positive + absent < required_successes(len(evaluable)):
        failures.append(FailedCheck(FailedCondition.VOTE, None, ()))
    losses = tuple(
        a.civil_date
        for a in evaluable
        if a.gain is not None and not a.gain >= -(a.threshold or 0.0) - epsilon
    )
    if losses:
        failures.append(FailedCheck(FailedCondition.LOSS, None, losses))
    for guard in guards:
        days = tuple(
            v.civil_date
            for v in guard.values
            if v.harm is not None
            and not v.harm <= HARM_MAX_FACTOR * v.threshold + epsilon
        )
        if guard.status is GuardStatus.VIOLATED or days:
            failures.append(FailedCheck(FailedCondition.GUARD, guard.metric, days))
    days = tuple(
        v.civil_date
        for v in passages.values
        if v.worst is not None and not v.worst <= PASSAGE_TOLERANCE + epsilon
    )
    if passages.status is GuardStatus.VIOLATED or days:
        failures.append(FailedCheck(FailedCondition.PASSAGES, None, days))
    return tuple(failures)


def admit(
    experiment: ExperimentDeclaration,
    inputs: Sequence[AdmissionInput],
    references: Sequence[FrozenReference],
) -> Admission | tuple[PerformanceAssessment, ...]:
    """L'admission exploratoire d'un effet (``0010`` D10.2 à D10.6 ; précisions et
    décisions de M4c-3).

    ``assess_performances`` ; sans performance évaluable (``n = 0``), les évaluations
    seules — aucune décision, l'appelant enregistre l'ÉCHEC « non évaluable »
    (décision Q4). Sinon : les garde-fous de ``GUARD_METRICS`` sans la cible, dans cet
    ordre, puis les passages ; ``δ̄``, ``Ḡ`` (absent si un ``G_j`` manque), la moyenne
    contre v0 brut (de même, E5), les succès ``G_j > ε`` ; les causes de « à revoir »,
    les conditions calculables qui échouent, le verdict ; les réserves (comparateur
    saturé, candidat saturé, sensibilité restante). ``references`` : les références
    que l'appelant fige (``run_experiment`` passe ``experiment.frozen_references``).
    """
    assessed = assess_performances(experiment, inputs, references)
    evaluable = [a for a in assessed if a.motif is None]
    if not evaluable:
        return assessed
    i = CLOCKS.index(experiment.clock)
    keyed = _keyed(experiment, references)
    guards = tuple(
        _guard(metric, inputs, assessed, keyed, i)
        for metric in GUARD_METRICS
        if metric is not experiment.target
    )
    passages = _passages(experiment, inputs, assessed, i)
    n = len(evaluable)
    mean_threshold = math.fsum(a.threshold or 0.0 for a in evaluable) / n
    gains = [a.gain for a in evaluable if a.gain is not None]
    raw_gains = [a.raw_gain for a in evaluable if a.raw_gain is not None]
    mean_gain = math.fsum(gains) / n if len(gains) == n else None
    mean_raw_gain = math.fsum(raw_gains) / n if len(raw_gains) == n else None
    positive = sum(1 for gain in gains if gain > NUMERIC_TOLERANCE)
    review = _review(evaluable, guards, passages)
    failures = _failures(
        evaluable, mean_gain, mean_threshold, positive, guards, passages
    )
    if review:
        verdict = AdmissionVerdict.TO_REVIEW
    elif failures:
        verdict = AdmissionVerdict.REJECTED
    else:
        verdict = AdmissionVerdict.PROVISIONAL
    reserves: list[AdmissionReserve] = []
    if any(a.base_effort is not None and a.base_effort.saturated for a in evaluable):
        reserves.append(AdmissionReserve.COMPARATOR_SATURATED)
    if any(
        a.candidate_effort is not None and a.candidate_effort.saturated
        for a in evaluable
    ):
        reserves.append(AdmissionReserve.CANDIDATE_SATURATED)
    reserves.append(AdmissionReserve.SENSITIVITY_REMAINING)
    return Admission(
        target=experiment.target,
        clock=experiment.clock,
        performances=assessed,
        evaluable=n,
        mean_gain=mean_gain,
        mean_threshold=mean_threshold,
        positive=positive,
        required=required_successes(n),
        mean_raw_gain=mean_raw_gain,
        raw_gains=len(raw_gains),
        guards=guards,
        passages=passages,
        review=review,
        failures=failures,
        verdict=verdict,
        reserves=tuple(reserves),
    )
