"""Fabriques de la sensibilité (``0010`` D13 ; précision de M4d-3) — objets construits à
la main, minuscules et synthétiques, sans GPX ni appariement.

Sorties scorées (les trois axes d'une métrique) :

- :func:`times`, :func:`segment`, :func:`point`, :func:`target`, :func:`observation` :
  une observation — segments admis de 100 m (bornes effectives, classe, temps nuls
  sous des horloges choisies), points de ``C_k``, éléments de ``K`` ; les onze temps
  d'un segment ou d'un cumul sont ceux de ``clock_times`` (``fixtures.calibration``) ;
- :func:`forecast`, :func:`raw_scores` : la prévision au rapport ``p_i / e_i`` donné et
  les scores de v0 brut, par les vrais producteurs (``score_scenario``) ;
- :class:`Calage`, :class:`Calibrated`, :func:`calibrated_scores` : un modèle calé, son
  calage sous chaque horloge (calé, ``non calé``, ``erreur du modèle`` ; population et
  retraits) et ses scores calés, lus de sa prévision avec pour base de ``q_usage`` la
  prévision d'usage de v0 brut (précision de D9.2) ;
- :func:`outcome` : l'``OutingOutcome`` d'une sortie (v0 brut, puis les modèles calés).

Décisions, gains, comparaisons :

- :func:`assessment`, :func:`decision` : une évaluation, et une admission minimale et
  valide (cible ``q_usage``, seuil fixe ; garde-fous et passages à l'état voulu), ou
  les seules évaluations quand aucune performance n'est évaluable ;
- :func:`expected_class`, :func:`gain_comparison` : la classe de signe écrite d'après
  la règle, et un ``GainComparison`` ;
- :func:`metric_comparison`, :func:`performance_comparison` : des comparaisons de
  métriques valides, pour les contrats.

Aucune donnée réelle : des jours de juillet 2026 inventés.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from fixtures.calibration import (
    GENERATED_AT,
    REFERENCE,
    SEGMENT_M,
    TRACE,
    clock_times,
)
from mountain_perf.backtest import clock_scores, score_outing, score_scenario
from mountain_perf.schemas import (
    CLOCKS,
    EFFORT_MODELS,
    GAIN_FLOOR,
    GUARD_METRICS,
    HARM_FLOOR,
    HARM_MAX_FACTOR,
    NUMERIC_TOLERANCE,
    PASSAGE_TOLERANCE,
    Admission,
    AdmissionReserve,
    AdmissionVerdict,
    AdmittedSegment,
    Availability,
    CalibratedClockScores,
    CalibratedOutingScores,
    CalibratedScenarioScores,
    CalibrationWithdrawal,
    Clock,
    Coverage,
    ExperimentMetric,
    FailedCheck,
    FailedCondition,
    GainComparison,
    GuardOutcome,
    GuardStatus,
    GuardValue,
    MetricComparison,
    MetricValue,
    ModelCalibration,
    ModelForecast,
    ModelKind,
    NonEvaluable,
    ObservedPoint,
    OutingObservation,
    OutingOutcome,
    OutingScores,
    ParameterSet,
    PassageGuardOutcome,
    PassageValue,
    PerformanceAssessment,
    PerformanceComparison,
    PerformanceMotif,
    RegimeClass,
    ReviewCause,
    ReviewReason,
    Scenario,
    SensitivityMetric,
    SupportComponent,
    TargetMember,
    ThresholdSource,
    Unavailability,
    required_successes,
)

A, F, D, X = "ascent", "flat", "descent", "mixed"
U = Unavailability
EPSILON = 1e-6
"""``ε`` de D10.3, écrit d'après la règle (les tests vérifient qu'il vaut
``NUMERIC_TOLERANCE``)."""

DAYS: tuple[date, ...] = tuple(date(2026, 7, d) for d in range(1, 16))
"""Les jours des performances des tests, strictement croissants."""

HISTORY = date(2026, 6, 1)
"""Le membre de population d'un calage par défaut."""

LENGTH_M = 1000.0
"""``L`` d'une observation : fixe, pour que la longueur ne change rien au support."""

ERR = "erreur du modèle"
"""Une performance évaluable dont le gain manque (cible de (1) en erreur du modèle)."""

GainSpec = float | str | NonEvaluable
"""Une performance d'une décision : son gain (évaluable), ``ERR`` (évaluable, gain
absent), ou son motif de non-évaluabilité."""

Decision = Admission | tuple[PerformanceAssessment, ...]
"""L'admission d'une configuration, ou ses seules évaluations sans évaluable."""


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------


def times(elapsed: float, zero: Iterable[int] = ()) -> tuple[float, ...]:
    """Les onze temps de ``clock_times(elapsed)``, nuls sous les horloges de rangs
    ``zero`` (jamais l'écoulé d'un segment admis)."""
    zeros = frozenset(zero)
    return tuple(
        0.0 if i in zeros else value for i, value in enumerate(clock_times(elapsed))
    )


def segment(
    k: int,
    regime: str,
    elapsed: float = 100.0,
    *,
    bounds: tuple[float, float] | None = None,
    nominal: tuple[float, float] | None = None,
    zero: Iterable[int] = (),
) -> AdmittedSegment:
    """Le segment admis ``k`` : nominal ``[100·k ; 100·(k + 1)]`` (ou ``nominal``),
    bornes effectives ``bounds`` (les nominales par défaut), classe ``regime``, écoulé
    ``elapsed``, temps nuls sous les horloges ``zero``."""
    cell = (SEGMENT_M * k, SEGMENT_M * (k + 1)) if nominal is None else nominal
    start, end = cell if bounds is None else bounds
    return AdmittedSegment(
        k,
        *cell,
        start,
        end,
        *cell,
        RegimeClass(regime),
        times(elapsed, zero),
    )


def point(
    distance_m: float,
    elapsed: float | None = 100.0,
    *,
    index: int = 1,
    passage: bool = False,
    motif: Unavailability = U.ABSENT,
    zero: Iterable[int] = (),
) -> ObservedPoint:
    """Un point de ``C_k`` : point de score ``index`` (ou lieu ``index`` si
    ``passage``), observé à l'écoulé ``elapsed`` (``None`` : non observé, au motif
    ``motif``), cumul nul sous les horloges ``zero``."""
    score_index, passage_index = (None, index) if passage else (index, None)
    if elapsed is None:
        return ObservedPoint(distance_m, score_index, passage_index, motif, None)
    return ObservedPoint(
        distance_m, score_index, passage_index, None, times(elapsed, zero)
    )


def target(
    distance_m: float,
    elapsed: float | None = 1000.0,
    *,
    occurrence: int | None = None,
    arrival: bool | None = None,
    motif: Unavailability = U.ABSENT,
    zero: Iterable[int] = (),
    score_index: int = 10,
) -> tuple[TargetMember, ObservedPoint]:
    """Un élément de ``K`` et son observation : le lieu ``occurrence`` (``None`` :
    l'arrivée de la grille), observé à l'écoulé ``elapsed`` (``None`` : au motif
    ``motif``), cumul nul sous les horloges ``zero``. ``arrival`` : l'élément est
    l'arrivée (par défaut, si et seulement s'il n'a pas de lieu)."""
    is_arrival = occurrence is None if arrival is None else arrival
    member = TargetMember(occurrence, is_arrival)
    index = score_index if is_arrival else None
    observed = (
        ObservedPoint(distance_m, index, occurrence, motif, None)
        if elapsed is None
        else ObservedPoint(distance_m, index, occurrence, None, times(elapsed, zero))
    )
    return member, observed


ARRIVAL = target(LENGTH_M)
"""L'arrivée observée par défaut : ``L``, 1 000 s d'écoulé."""


def observation(
    segments: Sequence[AdmittedSegment],
    points: Sequence[ObservedPoint] = (),
    targets: Sequence[tuple[TargetMember, ObservedPoint]] = (ARRIVAL,),
) -> OutingObservation:
    """L'observation d'une sortie, de longueur ``LENGTH_M`` et d'origine 0 (datée) :
    ses segments admis, ses points de ``C_k`` et son ``K`` (l'arrivée seule par
    défaut)."""
    return OutingObservation(
        reference_length_m=LENGTH_M,
        origin_m=0.0,
        origin_s=0.0,
        segments=tuple(segments),
        error_points=tuple(points),
        members=tuple(member for member, _ in targets),
        targets=tuple(observed for _, observed in targets),
        arrival_anchor_gap_m=None,
    )


def standard_segments(**changes: AdmittedSegment) -> tuple[AdmittedSegment, ...]:
    """Six segments : montée, montée, plat, plat, descente, descente (écoulés
    distincts) ; ``changes`` remplace un segment par son rang (``s0`` … ``s5``)."""
    base = (
        segment(0, A, 120.0),
        segment(1, A, 110.0),
        segment(2, F, 60.0),
        segment(3, F, 70.0),
        segment(4, D, 50.0),
        segment(5, D, 45.0),
    )
    return tuple(changes.get(f"s{k}", s) for k, s in enumerate(base))


PROFILE: tuple[float, ...] = (0.9, 1.05, 1.2, 0.95, 1.3, 0.8)
"""Les facteurs de prévision des six segments de ``standard_segments`` : des niveaux
et des dispersions distincts d'une classe à l'autre."""

STANDARD_POINTS: tuple[ObservedPoint, ...] = (
    point(200.0, 230.0, index=2),
    point(400.0, 360.0, index=4),
)
"""Deux points de score de ``C_k``, observés."""


def standard_targets() -> tuple[tuple[TargetMember, ObservedPoint], ...]:
    """``K`` : un lieu (occurrence 0, à 300 m), puis l'arrivée."""
    return (target(300.0, 300.0, occurrence=0), ARRIVAL)


def standard_observation(
    segments: Sequence[AdmittedSegment] | None = None,
    points: Sequence[ObservedPoint] | None = None,
    targets: Sequence[tuple[TargetMember, ObservedPoint]] | None = None,
) -> OutingObservation:
    """L'observation de référence des tests : ``standard_segments``,
    ``STANDARD_POINTS``, ``standard_targets`` ; chaque partie remplaçable."""
    return observation(
        standard_segments() if segments is None else segments,
        STANDARD_POINTS if points is None else points,
        standard_targets() if targets is None else targets,
    )


# ---------------------------------------------------------------------------
# Scores
# ---------------------------------------------------------------------------


def _cumulated(observed: ObservedPoint, ratio: float) -> float:
    elapsed = observed.distance_m if observed.times_s is None else observed.times_s[0]
    return ratio * elapsed


def forecast(
    obs: OutingObservation,
    ratio: float,
    scenario: Scenario,
    profile: Sequence[float] | None = None,
) -> ModelForecast:
    """La prévision d'un modèle : ``p_i = ratio · profile_i · e_i`` sur chaque segment
    (``profile`` : 1 partout par défaut) ; en usage, ses cumuls aux points de ``C_k``
    et aux éléments de ``K`` (``ratio`` fois l'écoulé observé, ou l'abscisse d'un
    élément non observé)."""
    usage = scenario is Scenario.USAGE
    factors = [1.0] * len(obs.segments) if profile is None else list(profile)
    if len(factors) != len(obs.segments):
        raise ValueError("forecast : un facteur de profil par segment.")
    return ModelForecast(
        scenario=scenario,
        source=REFERENCE if usage else TRACE,
        curve_ref="courbe-de-sensibilite",
        parameters=ParameterSet(()),
        engine_version="sensibilite",
        generated_at=GENERATED_AT,
        segment_s=tuple(
            ratio * factor * s.times_s[0]
            for factor, s in zip(factors, obs.segments, strict=True)
        ),
        point_s=tuple(_cumulated(p, ratio) for p in obs.error_points) if usage else (),
        target_s=tuple(_cumulated(t, ratio) for t in obs.targets) if usage else (),
    )


def raw_scores(
    obs: OutingObservation,
    ratio: float = 1.1,
    *,
    usage: bool = True,
    profile: Sequence[float] | None = None,
) -> OutingScores:
    """Les scores de v0 brut (``score_scenario``) ; ``usage`` faux : sortie sans
    référence (contrôle seul)."""
    control = score_scenario(obs, forecast(obs, ratio, Scenario.CONTROL, profile))
    scenario = (
        score_scenario(obs, forecast(obs, ratio, Scenario.USAGE, profile))
        if usage
        else None
    )
    return score_outing(obs, control, scenario)


@dataclass(frozen=True)
class Calage:
    """Le calage d'un modèle sous une horloge : ``C_j^eff``, ses retraits, et son
    statut (``None`` : calé, ``β = 0`` et facteur 1 ; ``NOT_CALIBRATED`` demande une
    population vide, ``MODEL_ERROR`` une population non vide)."""

    population: tuple[date, ...] = (HISTORY,)
    withdrawals: tuple[CalibrationWithdrawal, ...] = ()
    status: Unavailability | None = None

    def of(
        self, model: ModelKind, scenario: Scenario, clock: Clock
    ) -> ModelCalibration:
        """Le ``ModelCalibration`` de ce calage."""
        calibrated = self.status is None
        return ModelCalibration(
            model,
            scenario,
            clock,
            self.population,
            self.withdrawals,
            0.0 if calibrated else None,
            1.0 if calibrated and model in EFFORT_MODELS else None,
            1.0 if calibrated else None,
            False,
            self.status,
        )


CALE = Calage()
"""Calé, population ``(HISTORY,)``, sans retrait."""
NOT_CALIBRATED = Calage((), (), U.NOT_CALIBRATED)
"""``non calé`` : population vide."""
MODEL_ERROR = Calage(status=U.MODEL_ERROR)
"""``erreur du modèle``, population ``(HISTORY,)``."""


@dataclass(frozen=True)
class Calibrated:
    """Un modèle calé d'une sortie : son rapport ``p_i / e_i``, et son calage en usage
    sous chaque horloge (``calages`` : rang d'horloge → calage ; ``CALE`` ailleurs, et
    en contrôle)."""

    kind: ModelKind
    ratio: float = 0.9
    calages: Mapping[int, Calage] = field(default_factory=dict)


def calibrated_scores(
    model: Calibrated,
    outing_id: str,
    obs: OutingObservation,
    *,
    base_ratio: float = 1.1,
    usage: bool = True,
    profile: Sequence[float] | None = None,
) -> CalibratedOutingScores:
    """Les scores calés d'un modèle : sous chaque horloge calée, ``clock_scores`` de sa
    prévision (en usage, base de ``q_usage`` la prévision d'usage de v0 brut, au
    rapport ``base_ratio``) ; sans scores sous une horloge non calée ou en erreur."""
    base = forecast(obs, base_ratio, Scenario.USAGE, profile)

    def scenario_scores(scenario: Scenario) -> CalibratedScenarioScores:
        """Les scores calés d'un scénario, sous les onze horloges."""
        own = forecast(obs, model.ratio, scenario, profile)
        in_usage = scenario is Scenario.USAGE
        entries = []
        for i, clock in enumerate(CLOCKS):
            calage = model.calages.get(i, CALE) if in_usage else CALE
            scores = (
                clock_scores(obs, own, i, base=base if in_usage else None)
                if calage.status is None
                else None
            )
            entries.append(
                CalibratedClockScores(calage.of(model.kind, scenario, clock), scores)
            )
        return CalibratedScenarioScores(model.kind, scenario, own, tuple(entries))

    return CalibratedOutingScores(
        outing_id,
        obs,
        scenario_scores(Scenario.CONTROL),
        scenario_scores(Scenario.USAGE) if usage else None,
    )


def coverage(obs: OutingObservation) -> Coverage:
    """Une couverture valide de l'observation (toute la longueur admise, en montée) ;
    la sensibilité ne la lit pas."""
    length_m = obs.reference_length_m
    return Coverage(
        reference_length_m=length_m,
        admitted_m=length_m,
        excluded_unobserved_bound_m=0.0,
        excluded_gap_m=0.0,
        excluded_length_ratio_m=0.0,
        excluded_interior_deviation_m=0.0,
        anchoring_excluded_m=0.0,
        ascent_length_m=length_m,
        flat_length_m=0.0,
        descent_length_m=0.0,
        admitted_ascent_m=length_m,
        admitted_flat_m=0.0,
        admitted_descent_m=0.0,
        admitted_elapsed_s=math.fsum(s.times_s[0] for s in obs.segments),
        excluded_gap_s=0.0,
        excluded_length_ratio_s=0.0,
        excluded_interior_deviation_s=0.0,
        prefix_segment_count=len(obs.segments),
        prefix_end_m=length_m,
        prefix_end_s=None,
        prefix_last_passage=None,
    )


def outcome(
    outing_id: str,
    obs: OutingObservation,
    *models: Calibrated,
    ratio: float = 1.1,
    usage: bool = True,
    profile: Sequence[float] | None = None,
) -> OutingOutcome:
    """L'``OutingOutcome`` d'une sortie : v0 brut au rapport ``ratio``, puis les
    modèles calés ``models``, dans cet ordre, sur la même observation ; ``profile`` :
    les facteurs de chaque segment, communs aux modèles."""
    scores: list[tuple[ModelKind, OutingScores | CalibratedOutingScores]] = [
        (ModelKind.V0_RAW, raw_scores(obs, ratio, usage=usage, profile=profile))
    ]
    scores.extend(
        (
            model.kind,
            calibrated_scores(
                model,
                outing_id,
                obs,
                base_ratio=ratio,
                usage=usage,
                profile=profile,
            ),
        )
        for model in models
    )
    return OutingOutcome(outing_id, coverage(obs), tuple(scores))


# ---------------------------------------------------------------------------
# Décisions (admission minimale, cible q_usage)
# ---------------------------------------------------------------------------


def assessment(day: date, spec: GainSpec) -> PerformanceAssessment:
    """L'évaluation d'une performance sous ``q_usage`` (seuil fixe ``δ = 0,010``) :
    un gain ``g`` exact (``g >= 0`` : cibles ``g`` et 0 ; sinon 0 et ``−g``), ``ERR``
    (la cible de (1) en erreur du modèle, gain absent), ou un motif."""
    outing_ids = (f"s-{day:%m%d}",)
    if isinstance(spec, NonEvaluable):
        return PerformanceAssessment(
            civil_date=day,
            outing_ids=outing_ids,
            motif=spec,
            comparable=None,
            comparable_unavailability=None,
            dplus_per_km=None,
            projected_s=None,
            source=None,
            local_unavailability=None,
            reference=None,
            threshold=None,
            base=None,
            candidate=None,
            raw=None,
            gain=None,
            raw_gain=None,
            base_effort=None,
            candidate_effort=None,
        )
    if isinstance(spec, str):
        if spec != ERR:
            raise ValueError(f"assessment : spécification inconnue {spec!r}.")
        base = MetricValue(0.1, None, 3)
        candidate = MetricValue(None, U.MODEL_ERROR, 0)
        gain: float | None = None
    else:
        base = MetricValue(spec if spec >= 0 else 0.0, None, 3)
        candidate = MetricValue(0.0 if spec >= 0 else -spec, None, 3)
        assert base.value is not None
        assert candidate.value is not None
        gain = base.value - candidate.value
        assert gain == spec, (gain, spec)
    return PerformanceAssessment(
        civil_date=day,
        outing_ids=outing_ids,
        motif=None,
        comparable=None,
        comparable_unavailability=None,
        dplus_per_km=None,
        projected_s=None,
        source=ThresholdSource.FIXED,
        local_unavailability=None,
        reference=None,
        threshold=GAIN_FLOOR,
        base=base,
        candidate=candidate,
        raw=base,
        gain=gain,
        raw_gain=gain,
        base_effort=None,
        candidate_effort=None,
    )


_GUARD_CANDIDATE: Mapping[GuardStatus, MetricValue] = {
    GuardStatus.SATISFIED: MetricValue(0.1, None, 3),
    GuardStatus.VIOLATED: MetricValue(0.2, None, 3),
    GuardStatus.UNAVAILABLE: MetricValue(None, U.MODEL_ERROR, 0),
}
_PASSAGE_WORST: Mapping[GuardStatus, float | None] = {
    GuardStatus.SATISFIED: 0.0,
    GuardStatus.VIOLATED: 0.5,
    GuardStatus.UNAVAILABLE: None,
}


def guard(
    metric: ExperimentMetric, status: GuardStatus, days: Sequence[date]
) -> GuardOutcome:
    """Un garde-fou de métrique à l'état ``status`` sur ``days`` (seuil fixe ``η``) :
    dommage nul (satisfait), de 0,1 (violé), absent (indisponible) ; aucune valeur
    (non évaluable)."""
    if status is GuardStatus.NOT_EVALUABLE:
        return GuardOutcome(metric, (), None, None, status)
    candidate = _GUARD_CANDIDATE[status]
    base = MetricValue(0.1, None, 3)
    harm = None if candidate.value is None else max(0.0, candidate.value - 0.1)
    values = tuple(
        GuardValue(
            day,
            base,
            candidate,
            harm,
            ThresholdSource.FIXED,
            U.ABSENT,
            None,
            HARM_FLOOR,
        )
        for day in days
    )
    count = len(values)
    mean_harm = None if harm is None else math.fsum(harm for _ in values) / count
    mean_threshold = math.fsum(v.threshold for v in values) / count
    return GuardOutcome(metric, values, mean_harm, mean_threshold, status)


def passage_guard(status: GuardStatus, days: Sequence[date]) -> PassageGuardOutcome:
    """Le garde-fou des passages à l'état ``status`` : pire dommage 0 (satisfait), 0,5
    (violé), absent (indisponible) ; aucune valeur (non évaluable)."""
    if status is GuardStatus.NOT_EVALUABLE:
        return PassageGuardOutcome((), status)
    worst = _PASSAGE_WORST[status]
    return PassageGuardOutcome(
        tuple(PassageValue(day, 1, worst) for day in days), status
    )


def decision(
    specs: Sequence[GainSpec],
    *,
    guards: Mapping[ExperimentMetric, GuardStatus] | None = None,
    passages: GuardStatus = GuardStatus.SATISFIED,
    clock: Clock = CLOCKS[0],
    days: Sequence[date] = DAYS,
) -> Decision:
    """La décision d'une configuration sur les performances ``specs`` (jours ``days``
    dans l'ordre) : l'admission sous ``clock``, cible ``q_usage`` — ``|L|`` satisfait
    et les autres garde-fous non évaluables par défaut (``guards`` les change),
    passages à l'état ``passages`` —, ou les seules évaluations si aucune n'est
    évaluable. Agrégats, causes de « à revoir », échecs et verdict écrits d'après
    D10.3 à D10.6 ; le contrat les revérifie."""
    assessed = tuple(
        assessment(day, spec) for day, spec in zip(days, specs, strict=False)
    )
    evaluable = tuple(a for a in assessed if a.motif is None)
    if not evaluable:
        return assessed
    on = tuple(a.civil_date for a in evaluable)
    statuses = {ExperimentMetric.LEVEL: GuardStatus.SATISFIED, **(guards or {})}
    outcomes = tuple(
        guard(m, statuses.get(m, GuardStatus.NOT_EVALUABLE), on) for m in GUARD_METRICS
    )
    passage = passage_guard(passages, on)
    n = len(evaluable)
    gains = [a.gain for a in evaluable]
    present = [g for g in gains if g is not None]
    mean_gain = math.fsum(present) / n if len(present) == n else None
    mean_threshold = math.fsum(GAIN_FLOOR for _ in evaluable) / n
    positive = sum(1 for g in present if g > NUMERIC_TOLERANCE)
    missing = tuple(a.civil_date for a in evaluable if a.gain is None)
    review: list[ReviewReason] = []
    if missing:
        review.append(ReviewReason(ReviewCause.TARGET_UNAVAILABLE, None, missing))
    review.extend(
        ReviewReason(ReviewCause.GUARD_UNAVAILABLE, g.metric, on)
        for g in outcomes
        if g.status is GuardStatus.UNAVAILABLE
    )
    if passage.status is GuardStatus.UNAVAILABLE:
        review.append(ReviewReason(ReviewCause.PASSAGES_UNAVAILABLE, None, on))
    elif passage.status is GuardStatus.NOT_EVALUABLE:
        review.append(ReviewReason(ReviewCause.PASSAGES_NOT_APPLICABLE, None, ()))
    failures: list[FailedCheck] = []
    if mean_gain is not None and not mean_gain >= mean_threshold - NUMERIC_TOLERANCE:
        failures.append(FailedCheck(FailedCondition.MEAN_GAIN, None, ()))
    required = required_successes(n)
    if positive + len(missing) < required:
        failures.append(FailedCheck(FailedCondition.VOTE, None, ()))
    losses = tuple(
        a.civil_date
        for a in evaluable
        if a.gain is not None and not a.gain >= -GAIN_FLOOR - NUMERIC_TOLERANCE
    )
    if losses:
        failures.append(FailedCheck(FailedCondition.LOSS, None, losses))
    for g in outcomes:
        bad = tuple(
            v.civil_date
            for v in g.values
            if v.harm is not None
            and not v.harm <= HARM_MAX_FACTOR * v.threshold + NUMERIC_TOLERANCE
        )
        if g.status is GuardStatus.VIOLATED or bad:
            failures.append(FailedCheck(FailedCondition.GUARD, g.metric, bad))
    bad_passages = tuple(
        v.civil_date
        for v in passage.values
        if v.worst is not None and not v.worst <= PASSAGE_TOLERANCE + NUMERIC_TOLERANCE
    )
    if passage.status is GuardStatus.VIOLATED or bad_passages:
        failures.append(FailedCheck(FailedCondition.PASSAGES, None, bad_passages))
    if review:
        verdict = AdmissionVerdict.TO_REVIEW
    elif failures:
        verdict = AdmissionVerdict.REJECTED
    else:
        verdict = AdmissionVerdict.PROVISIONAL
    return Admission(
        target=ExperimentMetric.USAGE,
        clock=clock,
        performances=assessed,
        evaluable=n,
        mean_gain=mean_gain,
        mean_threshold=mean_threshold,
        positive=positive,
        required=required,
        mean_raw_gain=mean_gain,
        raw_gains=len(present),
        guards=outcomes,
        passages=passage,
        review=tuple(review),
        failures=tuple(failures),
        verdict=verdict,
        reserves=(AdmissionReserve.SENSITIVITY_REMAINING,),
    )


def admission(
    specs: Sequence[GainSpec],
    *,
    guards: Mapping[ExperimentMetric, GuardStatus] | None = None,
    passages: GuardStatus = GuardStatus.SATISFIED,
    clock: Clock = CLOCKS[0],
) -> Admission:
    """``decision`` quand une performance au moins est évaluable : l'admission."""
    made = decision(specs, guards=guards, passages=passages, clock=clock)
    assert isinstance(made, Admission)
    return made


def assessments(specs: Sequence[GainSpec]) -> tuple[PerformanceAssessment, ...]:
    """``decision`` sans performance évaluable : les seules évaluations."""
    made = decision(specs)
    assert not isinstance(made, Admission)
    return made


# ---------------------------------------------------------------------------
# Gains et comparaisons
# ---------------------------------------------------------------------------


def expected_class(gain: float | None) -> int | None:
    """La classe de signe, écrite d'après la règle (précision de D13) : ``+1`` si
    ``g > ε``, ``−1`` si ``g < −ε``, ``0`` sinon ; absente sans gain."""
    if gain is None:
        return None
    if gain > EPSILON:
        return 1
    if gain < -EPSILON:
        return -1
    return 0


def _side(spec: GainSpec) -> tuple[float | None, NonEvaluable | None]:
    if isinstance(spec, NonEvaluable):
        return None, spec
    if isinstance(spec, str):
        return None, None
    return spec, None


def gain_comparison(day: date, comparator: GainSpec, value: GainSpec) -> GainComparison:
    """Le gain d'une performance au comparateur et sous la configuration, chaque côté
    un gain, ``ERR`` (évaluable, gain absent) ou un motif."""
    comparator_gain, comparator_motif = _side(comparator)
    gain, motif = _side(value)
    return GainComparison(
        day,
        comparator_gain,
        comparator_motif,
        gain,
        motif,
        expected_class(comparator_gain),
        expected_class(gain),
    )


def availability(comparator: MetricValue, value: MetricValue) -> Availability:
    """L'axe (i), écrit d'après la règle : sur la présence des deux valeurs."""
    if comparator.value is not None:
        return Availability.BOTH if value.value is not None else Availability.LOST
    return Availability.GAINED if value.value is not None else Availability.NEITHER


def metric_comparison(
    model: ModelKind,
    metric: SensitivityMetric,
    comparator: MetricValue,
    value: MetricValue,
    support: tuple[SupportComponent, ...] = (),
) -> MetricComparison:
    """Une comparaison valide : la disponibilité et l'écart ``value − comparator``
    déduits des deux valeurs."""
    difference = (
        None
        if comparator.value is None or value.value is None
        else value.value - comparator.value
    )
    return MetricComparison(
        model,
        metric,
        comparator,
        value,
        availability(comparator, value),
        support,
        difference,
    )


def performance_comparison(
    day: date,
    comparator: MetricValue,
    value: MetricValue,
    models: Sequence[ModelKind] = (ModelKind.V0_RAW,),
    *,
    outing_id: str | None = None,
    motif: PerformanceMotif | None = None,
) -> PerformanceComparison:
    """La comparaison d'une performance : son motif (sans métrique), ou chaque modèle
    de ``models`` avec ses neuf métriques, toutes à ``comparator`` et ``value``."""
    name = f"s-{day:%m%d}" if outing_id is None else outing_id
    if motif is not None:
        return PerformanceComparison(day, name, motif, ())
    return PerformanceComparison(
        day,
        name,
        None,
        tuple(
            metric_comparison(model, metric, comparator, value)
            for model in models
            for metric in SensitivityMetric
        ),
    )
