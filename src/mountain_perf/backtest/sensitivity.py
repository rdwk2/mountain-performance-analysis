"""Sensibilité de ``0010`` D13 : les dix-neuf configurations (M4a-2b) et leur
comparaison au comparateur (M4d-3).

Protocole : ``docs/decisions/0010`` D13 (et sa précision de M4d-3), D7, D10.2 à D10.6.
Les configurations sont déclarées depuis M4a ; leur exécution enregistrée vit dans
``mountain_perf.backtest.sensitivity_run`` (M4d-3). Ce module en porte la comparaison,
en fonctions pures, sans lecture ni écriture : la valeur d'un modèle sous une horloge,
les signatures du support effectif, les trois axes d'une métrique (disponibilité,
support, valeur), les gains et les réserves d'une expérience, le document de
sensibilité et la vue composée de D10.6. Rien n'y est recalculé hors des scores, des
observations et des admissions reçus.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from mountain_perf.schemas import (
    CALIBRATED_KINDS,
    CLOCKS,
    Admission,
    Availability,
    CalibratedOutingScores,
    Clock,
    ClockScores,
    ConfigurationOutcome,
    GainComparison,
    MetricComparison,
    MetricValue,
    ModelKind,
    OutingObservation,
    OutingOutcome,
    OutingScores,
    PerformanceAssessment,
    PerformanceComparison,
    PerformanceMotif,
    RegimeClass,
    ReserveEntry,
    SensitivityConfiguration,
    SensitivityMetric,
    SensitivityOutcome,
    SensitivityReserve,
    SupportComponent,
    Unavailability,
)
from mountain_perf.schemas.sensitivity import (
    DOCUMENT_RESERVES,
    METRIC_COMPONENTS,
    common_set,
    guards_lost,
    sign_class,
)

SENSITIVITY_SCORE_STEPS_M = (100.0, 250.0, 500.0)
"""Pas de grille ``Δ`` de la sensibilité en écoulé (m, ``0010`` D13)."""

SENSITIVITY_LATERAL_TOLERANCES_M = (15.0, 30.0, 45.0)
"""Tolérances latérales ``ε`` de la sensibilité en écoulé (m, ``0010`` D13)."""

SENSITIVITY_CENTRAL_M = (250.0, 30.0)
"""``(Δ, ε)`` des configurations sous les dix horloges de mouvement (m, ``0010``
D13)."""

SENSITIVITY_CLUSTER_RADIUS_M = 15.0
"""``r_c``, fixe dans toutes les configurations (m, ``0010`` D13)."""

SENSITIVITY_CONFIGURATIONS: tuple[SensitivityConfiguration, ...] = (
    *(
        SensitivityConfiguration(
            step_m, tolerance_m, SENSITIVITY_CLUSTER_RADIUS_M, CLOCKS[0]
        )
        for step_m in SENSITIVITY_SCORE_STEPS_M
        for tolerance_m in SENSITIVITY_LATERAL_TOLERANCES_M
    ),
    *(
        SensitivityConfiguration(
            *SENSITIVITY_CENTRAL_M, SENSITIVITY_CLUSTER_RADIUS_M, clock
        )
        for clock in CLOCKS[1:]
    ),
)
"""Les dix-neuf configurations de ``0010`` D13, **dans cet ordre** : pour ``Δ`` puis
``ε``, les neuf en écoulé (``CLOCKS[0]``) ; puis ``(250, 30)`` sous les dix horloges
de mouvement ``CLOCKS[1:]``, dans leur ordre."""

SENSITIVITY_PAIRS: tuple[tuple[float, float], ...] = tuple(
    dict.fromkeys(
        (configuration.score_step_m, configuration.lateral_tolerance_m)
        for configuration in SENSITIVITY_CONFIGURATIONS
    )
)
"""Les neuf paires ``(Δ, ε)`` des configurations (m, ``0010`` D13 ; précision de
M4d-3), dans l'ordre de leur première apparition : une exécution géométrique chacune."""

_INSUFFICIENT = MetricValue(None, Unavailability.INSUFFICIENT_SUPPORT, 0)

_REGIME_METRICS: dict[SensitivityMetric, tuple[RegimeClass, str]] = {
    SensitivityMetric.ASCENT_LEVEL: (RegimeClass.ASCENT, "log_ratio"),
    SensitivityMetric.FLAT_LEVEL: (RegimeClass.FLAT, "log_ratio"),
    SensitivityMetric.DESCENT_LEVEL: (RegimeClass.DESCENT, "log_ratio"),
    SensitivityMetric.ASCENT_DISPERSION: (RegimeClass.ASCENT, "dispersion"),
    SensitivityMetric.FLAT_DISPERSION: (RegimeClass.FLAT, "dispersion"),
    SensitivityMetric.DESCENT_DISPERSION: (RegimeClass.DESCENT, "dispersion"),
}
"""Les métriques de régime : la classe et le champ de ``ClassMetrics`` de chacune
(``E_R`` : ``log_ratio`` ; ``D_R`` : ``dispersion`` ; D7.2)."""

_RESERVE_FLAGS: dict[SensitivityReserve, str] = {
    SensitivityReserve.SIGN_CHANGED: "sign_changed",
    SensitivityReserve.VERDICT_CHANGED: "verdict_changed",
    SensitivityReserve.EVALUABILITY_LOST: "evaluability_lost",
    SensitivityReserve.SIGN_UNVERIFIABLE: "sign_unverifiable",
}
"""Le drapeau de ``ConfigurationOutcome`` de chaque réserve du document."""


# ---------------------------------------------------------------------------
# Valeurs d'un modèle sous une horloge
# ---------------------------------------------------------------------------


def usage_clock_scores(
    scores: OutingScores | CalibratedOutingScores, clock: Clock
) -> ClockScores | Unavailability:
    """Les scores d'usage d'un modèle sous ``clock`` (précision de D13, M4d-3, « Trois
    axes ») : ceux de v0 brut tels quels ; pour un modèle calé, ses scores calés sous
    l'horloge, ou, sans calage sous elle, le statut de son calage (``not_calibrated``,
    ``model_error``) — même si l'observation a un motif (dérogation à la précision de
    D7.1). ``ValueError`` si la sortie n'a pas d'usage (D3)."""
    if scores.usage is None:
        raise ValueError("la sortie n'a pas d'usage (D3) : aucune valeur d'usage.")
    index = CLOCKS.index(clock)
    if isinstance(scores, OutingScores):
        return scores.usage.clocks[index]
    entry = scores.usage.clocks[index]
    if entry.scores is None:
        status = entry.calibration.unavailability
        assert status is not None  # contrat de CalibratedClockScores
        return status
    return entry.scores


def sensitivity_value(
    scores: ClockScores | Unavailability, metric: SensitivityMetric
) -> MetricValue:
    """La valeur d'une métrique dans les scores d'une horloge, telle quelle (précision
    de D13, M4d-3) : ``L`` (``support.log_ratio``), ``E_R`` et ``D_R`` de la classe
    (``log_ratio``, ``dispersion``), ``max |C_k|`` (``max_abs_error_s``), ``q_usage``
    (``usage_target.q_usage``) ; un statut de calage : ``MetricValue(None, statut, 0)``
    ; sans erreurs aux passages ou sans cible d'usage : ``support insuffisant``,
    d'effectif nul."""
    if isinstance(scores, Unavailability):
        return MetricValue(None, scores, 0)
    if metric is SensitivityMetric.LEVEL:
        return scores.support.log_ratio
    if metric in _REGIME_METRICS:
        regime, name = _REGIME_METRICS[metric]
        classes = {c.regime_class: c for c in scores.support.classes}
        value: MetricValue = getattr(classes[regime], name)
        return value
    if metric is SensitivityMetric.MAX_ABS_PASSAGE_ERROR:
        if scores.passage_errors is None:
            return _INSUFFICIENT
        return scores.passage_errors.max_abs_error_s
    if scores.usage_target is None:
        return _INSUFFICIENT
    return scores.usage_target.q_usage


# ---------------------------------------------------------------------------
# Support effectif (axe 2)
# ---------------------------------------------------------------------------


def _zero(times_s: tuple[float, ...] | None, index: int) -> bool | None:
    """Le temps sous l'horloge de rang ``index`` est nul ; ``None`` sans temps."""
    return None if times_s is None else times_s[index] == 0.0


def support_signature(
    component: SupportComponent,
    metric: SensitivityMetric,
    observation: OutingObservation,
    scores: OutingScores | CalibratedOutingScores,
    clock: Clock,
) -> tuple[object, ...]:
    """La signature d'une composante du support effectif de ``metric`` sous ``clock``
    (précision de D13, M4d-3, axe (ii)) : deux signatures égales, c'est la même
    composante, à l'égalité exacte de ses entrées.

    - segments : ``(début, fin, classe)`` effectifs de chaque segment admis, dans
      l'ordre (ceux de la classe seulement pour une métrique de régime) ;
    - temps nuls : ``(début, fin)`` de chaque segment admis de temps nul sous
      l'horloge (D5.5), toutes classes ;
    - points : ``(abscisse, motif, temps nul)`` de chaque point de ``C_k``, « temps
      nul » valant ``None`` sans temps ;
    - éléments : ``(membre, abscisse, motif, temps nul)`` de chaque élément de ``K`` ;
    - population : pour un modèle calé, ``(population, retraits)`` de son calage
      d'usage sous l'horloge, quel que soit son statut ; ``()`` pour v0 brut.
      ``ValueError`` pour un modèle calé sans usage.
    """
    index = CLOCKS.index(clock)
    if component is SupportComponent.SEGMENTS:
        segments = observation.segments
        if metric in _REGIME_METRICS:
            regime = _REGIME_METRICS[metric][0]
            segments = tuple(s for s in segments if s.regime_class is regime)
        return tuple((s.start_m, s.end_m, s.regime_class) for s in segments)
    if component is SupportComponent.ZERO_TIMES:
        return tuple(
            (s.start_m, s.end_m)
            for s in observation.segments
            if s.times_s[index] == 0.0
        )
    if component is SupportComponent.POINTS:
        return tuple(
            (p.distance_m, p.unavailability, _zero(p.times_s, index))
            for p in observation.error_points
        )
    if component is SupportComponent.TARGETS:
        return tuple(
            (member, t.distance_m, t.unavailability, _zero(t.times_s, index))
            for member, t in zip(observation.members, observation.targets, strict=True)
        )
    if isinstance(scores, OutingScores):
        return ()
    if scores.usage is None:
        raise ValueError("un modèle calé sans usage n'a pas de population d'usage.")
    calibration = scores.usage.clocks[index].calibration
    return (calibration.population, calibration.withdrawals)


# ---------------------------------------------------------------------------
# Une métrique, une performance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Side:
    """Un côté d'une comparaison : une sortie scorée (``outcome``) sous l'horloge d'une
    configuration (``clock``) — celle du comparateur, ou celle de la configuration
    comparée (précision de D13, M4d-3)."""

    outcome: OutingOutcome
    clock: Clock


def _model_scores(
    outcome: OutingOutcome, model: ModelKind
) -> OutingScores | CalibratedOutingScores:
    for kind, scores in outcome.scores:
        if kind is model:
            return scores
    raise ValueError(f"la sortie {outcome.outing_id} n'a pas de scores de {model}.")


def compare_metric(
    model: ModelKind, metric: SensitivityMetric, comparator: Side, side: Side
) -> MetricComparison:
    """Une métrique d'un modèle comparée au comparateur (précision de D13, M4d-3,
    « Trois axes ») : la valeur de chaque côté, lue dans ses scores sous son horloge
    (``usage_clock_scores``, ``sensitivity_value``) ; la disponibilité, par leurs
    présences ; les composantes de ``METRIC_COMPONENTS[metric]`` dont la signature
    change d'un côté à l'autre, chacun sur son observation et sous son horloge (la
    population pour un modèle calé seulement) ; l'écart ``valeur − comparateur``."""
    values: list[MetricValue] = []
    signatures: list[dict[SupportComponent, tuple[object, ...]]] = []
    components = tuple(
        component
        for component in METRIC_COMPONENTS[metric]
        if component is not SupportComponent.POPULATION or model in CALIBRATED_KINDS
    )
    for current in (comparator, side):
        scores = _model_scores(current.outcome, model)
        values.append(
            sensitivity_value(usage_clock_scores(scores, current.clock), metric)
        )
        signatures.append(
            {
                component: support_signature(
                    component, metric, scores.observation, scores, current.clock
                )
                for component in components
            }
        )
    reference, value = values
    changed = tuple(c for c in components if signatures[0][c] != signatures[1][c])
    if reference.value is not None and value.value is not None:
        difference: float | None = value.value - reference.value
    else:
        difference = None
    return MetricComparison(
        model,
        metric,
        reference,
        value,
        _availability(reference, value),
        changed,
        difference,
    )


def _availability(comparator: MetricValue, value: MetricValue) -> Availability:
    """L'axe (i) : la disponibilité que donnent les présences des deux valeurs."""
    if comparator.value is not None:
        return Availability.BOTH if value.value is not None else Availability.LOST
    return Availability.GAINED if value.value is not None else Availability.NEITHER


def compare_performance(
    civil_date: date,
    outing_id: str,
    motif: PerformanceMotif | None,
    comparator: Side | None,
    side: Side | None,
) -> PerformanceComparison:
    """Une performance déclarée comparée au comparateur (précision de D13, M4d-3) : un
    motif, sans côté ; sinon, chaque modèle des scores de la sortie, dans leur ordre,
    et chaque métrique de ``SensitivityMetric``, dans l'ordre (``compare_metric``).

    ``ValueError`` : un motif avec un côté ; sans motif, un côté absent, deux sorties
    différentes, ou des modèles différents ou dans un autre ordre."""
    if motif is not None:
        if comparator is not None or side is not None:
            raise ValueError("une performance à motif n'a pas de côté.")
        return PerformanceComparison(civil_date, outing_id, motif, ())
    if comparator is None or side is None:
        raise ValueError("sans motif, les deux côtés sont donnés.")
    if comparator.outcome.outing_id != side.outcome.outing_id:
        raise ValueError(
            f"deux sorties différentes : {comparator.outcome.outing_id} et "
            f"{side.outcome.outing_id}."
        )
    models = tuple(kind for kind, _ in comparator.outcome.scores)
    if tuple(kind for kind, _ in side.outcome.scores) != models:
        raise ValueError("mêmes modèles des deux côtés, dans le même ordre.")
    return PerformanceComparison(
        civil_date,
        outing_id,
        None,
        tuple(
            compare_metric(model, metric, comparator, side)
            for model in models
            for metric in SensitivityMetric
        ),
    )


# ---------------------------------------------------------------------------
# Une expérience : gains, réserves
# ---------------------------------------------------------------------------


Decision = Admission | tuple[PerformanceAssessment, ...]
"""Ce qu'``admit`` rend pour une configuration : l'admission, ou, sans performance
évaluable, les seules évaluations (``0010`` D10.6)."""


def _assessed(decision: Decision) -> tuple[PerformanceAssessment, ...]:
    if isinstance(decision, Admission):
        return decision.performances
    return decision


def _admission(decision: Decision) -> Admission | None:
    return decision if isinstance(decision, Admission) else None


def _class(gain: float | None) -> int | None:
    return None if gain is None else sign_class(gain)


def compare_gains(
    comparator: Decision, decision: Decision
) -> tuple[GainComparison, ...]:
    """Le gain de chaque performance au comparateur et sous la configuration
    (précision de D13, M4d-3, « Signes et ensembles ») : de chaque côté, le gain et le
    motif de son évaluation, tels quels, et la classe de signe du gain présent
    (``sign_class``). ``ValueError`` si les deux décisions n'évaluent pas les mêmes
    jours dans le même ordre."""
    theirs, mine = _assessed(comparator), _assessed(decision)
    if [a.civil_date for a in theirs] != [a.civil_date for a in mine]:
        raise ValueError("les deux décisions évaluent les mêmes jours, dans l'ordre.")
    return tuple(
        GainComparison(
            own.civil_date,
            reference.gain,
            reference.motif,
            own.gain,
            own.motif,
            _class(reference.gain),
            _class(own.gain),
        )
        for reference, own in zip(theirs, mine, strict=True)
    )


def evaluability_lost(
    comparator: Decision, decision: Decision, gains: Sequence[GainComparison]
) -> bool:
    """« Sensibilité : évaluabilité perdue » (précision de D13, M4d-3 ; D13-C) : une
    performance évaluable au comparateur ne l'est plus sous la configuration, ou un
    garde-fou calculé au comparateur ne l'est plus (``guards_lost``, passages
    compris) ; jamais sans décision au comparateur."""
    reference = _admission(comparator)
    if reference is None:
        return False
    lost = any(g.comparator_motif is None and g.motif is not None for g in gains)
    return lost or guards_lost(reference, _admission(decision))


def configuration_outcome(
    configuration: SensitivityConfiguration,
    performances: Sequence[PerformanceComparison],
    decision: Decision | None = None,
    comparator: Decision | None = None,
) -> ConfigurationOutcome:
    """Une configuration comparée au comparateur (précision de D13, M4d-3) : sans
    expérience, ses seules performances ; avec (``decision`` sous la configuration,
    ``comparator`` celle du comparateur), l'admission ou les évaluations, les gains
    comparés, l'ensemble commun, les classes de ``Ḡ`` et les quatre réserves — signe
    changé (classes de ``Ḡ`` présentes des deux côtés et différentes, ou un ``G_j``
    comparable de classe changée), verdict modifié (l'absence de décision comptant
    comme un verdict), évaluabilité perdue, signe non vérifiable (aucun gain
    comparable). ``ValueError`` si une seule des deux décisions est donnée."""
    if (decision is None) != (comparator is None):
        raise ValueError("les deux décisions sont données, ou aucune.")
    performances = tuple(performances)
    if decision is None or comparator is None:
        return ConfigurationOutcome(
            configuration,
            performances,
            None,
            None,
            (),
            None,
            None,
            None,
            False,
            False,
            False,
            False,
        )
    admission, reference = _admission(decision), _admission(comparator)
    gains = compare_gains(comparator, decision)
    mean_class = None if admission is None else _class(admission.mean_gain)
    comparator_class = None if reference is None else _class(reference.mean_gain)
    sign_changed = (
        mean_class is not None
        and comparator_class is not None
        and mean_class != comparator_class
    ) or any(g.class_changed for g in gains)
    verdict = None if admission is None else admission.verdict
    comparator_verdict = None if reference is None else reference.verdict
    return ConfigurationOutcome(
        configuration,
        performances,
        admission,
        None if admission is not None else _assessed(decision),
        gains,
        common_set(gains),
        mean_class,
        comparator_class,
        sign_changed,
        verdict != comparator_verdict,
        evaluability_lost(comparator, decision, gains),
        not any(g.comparable for g in gains),
    )


def sensitivity_outcome(
    comparator: int, configurations: Sequence[ConfigurationOutcome]
) -> SensitivityOutcome:
    """Le document de sensibilité (précision de D13 et de D14, M4d-3) : le rang du
    comparateur, les configurations, et pour chaque réserve de ``DOCUMENT_RESERVES``,
    dans l'ordre, les rangs de toutes les configurations qui la portent — aucune
    entrée pour une réserve qu'aucune ne porte."""
    configurations = tuple(configurations)
    reserves: list[ReserveEntry] = []
    for reserve in DOCUMENT_RESERVES:
        ranks = tuple(
            rank
            for rank, outcome in enumerate(configurations)
            if getattr(outcome, _RESERVE_FLAGS[reserve])
        )
        if ranks:
            reserves.append(ReserveEntry(reserve, ranks))
    return SensitivityOutcome(comparator, configurations, tuple(reserves))


# ---------------------------------------------------------------------------
# Vue composée (D10.6)
# ---------------------------------------------------------------------------


class SensitivityStatus(StrEnum):
    """L'état de la vue composée d'une centrale et de sa sensibilité (``0010`` D10.6 ;
    précision de M4d-3) — calculé à la lecture, jamais stocké : sans sensibilité
    déclarée, « centrale, sensibilité restante » ; déclarée sans RÉSULTAT,
    « sensibilité incomplète » ; un document à réserves, ses réserves ; sans réserve,
    « sensibilité faite »."""

    REMAINING = "central_sensitivity_remaining"
    INCOMPLETE = "sensitivity_incomplete"
    RESERVED = "sensitivity_reserved"
    DONE = "sensitivity_done"


@dataclass(frozen=True)
class SensitivityQualification:
    """La vue composée de D10.6 (précision de M4d-3) : l'état, et pour ``RESERVED``
    les réserves du document, telles quelles (chacune avec les configurations qui la
    portent) ; ``reserves`` vide sinon. Le verdict reste celui de la centrale."""

    status: SensitivityStatus
    reserves: tuple[ReserveEntry, ...]


def qualify_sensitivity(
    declared: bool, outcome: SensitivityOutcome | None
) -> SensitivityQualification:
    """La vue composée de D10.6 (précision de M4d-3) : ``declared`` dit qu'une
    sensibilité qualifie la centrale, ``outcome`` est le document de son RÉSULTAT en
    vigueur (absent pour un ÉCHEC ou un processus interrompu). ``ValueError`` : un
    document sans déclaration."""
    if not declared:
        if outcome is not None:
            raise ValueError("un document de sensibilité suppose sa déclaration.")
        return SensitivityQualification(SensitivityStatus.REMAINING, ())
    if outcome is None:
        return SensitivityQualification(SensitivityStatus.INCOMPLETE, ())
    if outcome.reserves:
        return SensitivityQualification(SensitivityStatus.RESERVED, outcome.reserves)
    return SensitivityQualification(SensitivityStatus.DONE, ())
