"""L'expérience d'admission enregistrée, par API de bibliothèque (M4c-3).

``0010`` D10 et D14, et leurs précisions de M4c-3. Une expérience refait la chaîne de
``just backtest`` depuis le manifeste et la courbe (décision Q3) : elle observe chaque
sortie tracée sans aucune prévision, calcule les références D8 sur ces seules
observations et les fige **avant** sa DÉCLARATION, avec l'empreinte du document D8 de
chaque parcours contributeur (E6) ; puis, après la DÉCLARATION, les scores non calés de
v0 brut et du candidat, le calage de la base (0) et du candidat (1) par la règle de v0
(Q2), l'admission (``admit``), et le RÉSULTAT au format 3 qui cite le document
d'admission (Q4) — ou un ÉCHEC « non évaluable » sans performance évaluable. Une
expérience se déclare en usage, sans date d'analyse : pas de figement pour
confirmation dans ce lot (Q5). Pas de commande (M6a).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from mountain_perf.backtest.admission import REGIME_METRICS, AdmissionInput, admit
from mountain_perf.backtest.calibration import calibrate_performances
from mountain_perf.backtest.codec import content_hash, encode_document
from mountain_perf.backtest.execution import (
    CALIBRATION_RULE,
    V0_RAW_MODEL,
    V0_RECALIBRATED_MODEL,
    BacktestError,
    Preparation,
    TracedOuting,
    failure_reason,
    prepare_backtest,
    repeatability_references,
    trace_outing,
)
from mountain_perf.backtest.geometry import ReferenceGeometry
from mountain_perf.backtest.registry import (
    append_declaration,
    append_failure,
    append_result,
    line_hash,
)
from mountain_perf.backtest.scoring import (
    control_forecast,
    observe_outing,
    realized_profile,
    score_outing,
    score_scenario,
    usage_forecast,
    v0_scores,
)
from mountain_perf.model import (
    ENGINE_VERSION,
    PROJECTION_PARAMETER_SPECS,
    ProjectedTimeline,
    projected_timeline,
)
from mountain_perf.schemas import (
    CalibratedOutingScores,
    Clock,
    Declaration,
    DeclaredEffect,
    DeclaredModel,
    DeclaredUsageTarget,
    Exclusion,
    ExperimentDeclaration,
    ExperimentMetric,
    Failure,
    FailureKind,
    FrozenReference,
    MetricValue,
    ModelForecast,
    ModelKind,
    OutingObservation,
    OutingOutcome,
    OutingScores,
    PaceCurve,
    ParameterSet,
    ReferenceSource,
    RegimeClass,
    RegistryEvent,
    RepeatabilityRecord,
    RepeatabilityReference,
    RouteProfile,
    Scenario,
)
from mountain_perf.schemas.admission import (
    Admission,
    NonEvaluable,
    PerformanceAssessment,
)

ADMISSION_EXCLUSION_PREFIX = "exclusion d'admission : "
"""Le début du motif d'une sortie que l'expérience retire de l'admission (P17) : elle
reste dans l'historique (calage des autres, références D8)."""

FROZEN_METRICS: tuple[ExperimentMetric, ...] = (
    ExperimentMetric.LEVEL,
    ExperimentMetric.ASCENT_LEVEL,
    ExperimentMetric.FLAT_LEVEL,
    ExperimentMetric.DESCENT_LEVEL,
    ExperimentMetric.ASCENT_DISPERSION,
    ExperimentMetric.FLAT_DISPERSION,
    ExperimentMetric.DESCENT_DISPERSION,
)
"""Les métriques dont une référence se fige (``0010`` D10.3, D10.4) : toutes sauf
``q_usage``, au seuil fixe."""

CANDIDATE_MODEL = DeclaredModel(
    ModelKind.CANDIDATE,
    ENGINE_VERSION,
    ParameterSet(PROJECTION_PARAMETER_SPECS),
    CALIBRATION_RULE,
)
"""Le candidat déclaré (``0010`` D10.1 ; choix 24) : v0 aux paramètres de départ, la
règle de calage de v0 ; l'effet est déclaré à part (``DeclaredEffect``)."""

_UNTRACED = "sortie non tracée"


class CandidateEffect(Protocol):
    """Un effet candidat : un changement du moteur, à paramètres fixés (``0010``
    D10.1 ; décision Q2).

    ``timeline(profil, chronologie de v0 à l'effort 1)`` rend la chronologie
    transformée. ``None``, une allure invalide (refusée par ``ProjectedTimeline``), une
    ``ValueError`` ou une ``ArithmeticError`` sont une **erreur du modèle**, jamais une
    exception de l'expérience. Sa règle d'estimation propre (D9.3) n'est pas
    implémentée dans ce lot (M6a).
    """

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def parameters(self) -> ParameterSet: ...

    def timeline(
        self, profile: RouteProfile, base: ProjectedTimeline
    ) -> ProjectedTimeline | None: ...


@dataclass(frozen=True)
class ExperimentSpec:
    """Ce que l'appelant déclare d'une expérience : l'effet, la cible et son horloge,
    les ``K`` déclarés (cible ``q_usage``), les exclusions d'admission (sortie →
    motif)."""

    effect: CandidateEffect
    target: ExperimentMetric
    clock: Clock
    usage_targets: tuple[DeclaredUsageTarget, ...] = ()
    admission_exclusions: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )


class ExperimentError(ValueError):
    """Une expérience refusée avant sa DÉCLARATION : rien n'est écrit."""


@dataclass(frozen=True)
class ObservedOuting:
    """Une sortie tracée observée, sans prévision : la chaîne de ``mperf match``,
    l'observation de ses scores (``observe_outing``) et le profil de sa trace (le
    contrôle, ``realized_profile``)."""

    traced: TracedOuting
    observation: OutingObservation
    realized: RouteProfile


@dataclass(frozen=True)
class ExperimentPreparation:
    """Une expérience préparée, rien d'écrit : la préparation de ``just backtest``, la
    spécification, les sorties observées (par identifiant, dans l'ordre des
    performances), les références D8 par parcours et la DÉCLARATION. N'est pas un
    contrat stocké."""

    backtest: Preparation
    spec: ExperimentSpec
    observed: Mapping[str, ObservedOuting]
    references: tuple[tuple[str, RepeatabilityReference], ...]
    declaration: Declaration


@dataclass(frozen=True)
class ExperimentRun:
    """Une expérience enregistrée : sa préparation, sa DÉCLARATION et sa réponse (le
    RÉSULTAT, ou l'ÉCHEC « non évaluable »), les sorties scorées (vides sur un ÉCHEC),
    le document d'admission (absent sur un ÉCHEC), les évaluations, et le sceau
    (l'empreinte de la ligne de la réponse)."""

    preparation: ExperimentPreparation
    declaration_event: RegistryEvent
    answer_event: RegistryEvent
    outcomes: tuple[OutingOutcome, ...]
    admission: Admission | None
    assessments: tuple[PerformanceAssessment, ...]
    seal: str


# ---------------------------------------------------------------------------
# Références figées (D10.1, D10.3 ; E6)
# ---------------------------------------------------------------------------


def _frozen_value(
    reference: RepeatabilityReference, clock: Clock, metric: ExperimentMetric
) -> MetricValue:
    """``F`` de ``metric`` sous ``clock`` dans une référence D8 (D8.4)."""
    (entry,) = [item for item in reference.clocks if item.clock == clock]
    if metric is ExperimentMetric.LEVEL:
        return entry.level
    regime_class, kind = REGIME_METRICS[metric]
    rank = list(RegimeClass).index(regime_class)
    if kind == "dispersion":
        return entry.dispersions[rank]
    return entry.log_ratios[rank]


def frozen_references(
    references: tuple[tuple[str, RepeatabilityReference], ...], clock: Clock
) -> tuple[FrozenReference, ...]:
    """Les références figées sous ``clock`` (``0010`` D10.3 ; P6, P7) : pour chaque
    métrique de ``FROZEN_METRICS``, dans cet ordre, la **locale** de chaque parcours,
    dans l'ordre de ``references``, disponible ou au motif de son indisponibilité ;
    puis, si une locale au moins est disponible, l'**empruntée** — moyenne à poids égal
    des locales disponibles, ses donneurs dans l'ordre, son effectif la somme de leurs
    ``m_q``."""
    frozen: list[FrozenReference] = []
    for metric in FROZEN_METRICS:
        values = [
            (route_id, _frozen_value(reference, clock, metric))
            for route_id, reference in references
        ]
        frozen.extend(
            FrozenReference(metric, clock, ReferenceSource.LOCAL, route_id, value, ())
            for route_id, value in values
        )
        available = [
            (route_id, value.value, value.count)
            for route_id, value in values
            if value.value is not None
        ]
        if not available:
            continue
        mean = math.fsum(value for _, value, _ in available) / len(available)
        count = sum(count for _, _, count in available)
        frozen.append(
            FrozenReference(
                metric,
                clock,
                ReferenceSource.BORROWED,
                None,
                MetricValue(mean, None, count),
                tuple(route_id for route_id, _, _ in available),
            )
        )
    return tuple(frozen)


def reference_documents(
    references: tuple[tuple[str, RepeatabilityReference], ...],
    frozen: tuple[FrozenReference, ...],
) -> tuple[RepeatabilityRecord, ...]:
    """L'empreinte du document D8 de chaque parcours contributeur — le parcours d'une
    locale figée, ou un donneur d'une empruntée —, dans l'ordre de ``references``
    (décision E6)."""
    contributors: set[str] = set()
    for reference in frozen:
        if reference.route_id is not None:
            contributors.add(reference.route_id)
        contributors.update(reference.donors)
    return tuple(
        RepeatabilityRecord(route_id, content_hash(encode_document(reference)))
        for route_id, reference in references
        if route_id in contributors
    )


# ---------------------------------------------------------------------------
# Préparation : lecture, observation, DÉCLARATION (Q3)
# ---------------------------------------------------------------------------


def prepare_experiment(
    manifest_path: Path,
    curve_path: Path,
    spec: ExperimentSpec,
    *,
    commit: str,
    tree_modified: bool,
    retrieved_at: datetime | None = None,
) -> ExperimentPreparation:
    """Lit, observe et déclare, **sans rien écrire** (décisions Q3 et E6) :

    1. ``prepare_backtest`` (mêmes arguments) ;
    2. l'observation de chaque sortie tracée des performances déclarées, dans leur
       ordre (``trace_outing``), sans aucune prévision ;
    3. les refus (``ExperimentError``), dans l'ordre : un ``K`` déclaré pour un
       parcours dont aucune sortie déclarée n'a de référence ; un élément d'un ``K``
       déclaré absent du ``K`` par défaut d'une sortie observée **avec usage** de son
       parcours (D7.4, départ exclu) ; une exclusion d'admission d'une sortie qui n'est
       celle d'aucune performance déclarée ;
    4. les références D8, sur les seules observations ;
    5. la DÉCLARATION : celle de ``just backtest``, ses exclusions suivies des
       exclusions d'admission (motif préfixé, triées par identifiant), les trois
       modèles (v0 brut, (0), (1)), et l'expérience — l'effet déclaré, la cible et son
       horloge, en usage, ses ``K``, ses références figées sous l'horloge déclarée et
       les empreintes de leurs documents D8, sans date d'analyse.
    """
    backtest = prepare_backtest(
        manifest_path,
        curve_path,
        commit=commit,
        tree_modified=tree_modified,
        retrieved_at=retrieved_at,
    )
    read = backtest.manifest
    profiles: dict[Path, tuple[RouteProfile, ReferenceGeometry]] = {}
    observed: dict[str, ObservedOuting] = {}
    for performance in backtest.performances:
        for outing in performance.outings:
            trace = read.traces.get(outing.outing_id)
            if trace is None:
                continue
            traced = trace_outing(read, outing, trace, profiles)
            observed[outing.outing_id] = ObservedOuting(
                traced,
                observe_outing(traced.match, traced.passages, traced.partition),
                realized_profile(trace),
            )
    _refuse(backtest, spec, observed)
    references = repeatability_references(
        backtest.performances,
        {outing_id: seen.observation for outing_id, seen in observed.items()},
    )
    frozen = frozen_references(references, spec.clock)
    effect = spec.effect
    experiment = ExperimentDeclaration(
        effect=DeclaredEffect(effect.name, effect.description, effect.parameters, None),
        target=spec.target,
        clock=spec.clock,
        scenario=Scenario.USAGE,
        base=ModelKind.V0_RECALIBRATED,
        candidate=ModelKind.CANDIDATE,
        usage_targets=spec.usage_targets,
        frozen_references=frozen,
        reference_documents=reference_documents(references, frozen),
        analysis_date=None,
    )
    exclusions = tuple(
        Exclusion(outing_id, ADMISSION_EXCLUSION_PREFIX + reason)
        for outing_id, reason in sorted(spec.admission_exclusions.items())
    )
    declaration = replace(
        backtest.declaration,
        exclusions=(*backtest.declaration.exclusions, *exclusions),
        models=(V0_RAW_MODEL, V0_RECALIBRATED_MODEL, CANDIDATE_MODEL),
        experiment=experiment,
    )
    return ExperimentPreparation(backtest, spec, observed, references, declaration)


def _refuse(
    backtest: Preparation,
    spec: ExperimentSpec,
    observed: Mapping[str, ObservedOuting],
) -> None:
    """Les refus d'avant la DÉCLARATION (``ExperimentError``), dans l'ordre de
    ``prepare_experiment``."""
    outings = [
        outing
        for performance in backtest.performances
        for outing in performance.outings
    ]
    for target in spec.usage_targets:
        route = target.route_id
        if not any(o.route_id == route and o.reference is not None for o in outings):
            raise ExperimentError(
                f"K du parcours {route!r} : aucune sortie déclarée de ce parcours n'a "
                "de référence (D7.4)."
            )
    for target in spec.usage_targets:
        for seen in observed.values():
            traced = seen.traced
            if traced.outing.route_id != target.route_id or traced.usage is None:
                continue
            members = seen.observation.members
            absent = [member for member in target.members if member not in members]
            if absent:
                raise ExperimentError(
                    f"K du parcours {target.route_id!r} : éléments hors du K par "
                    f"défaut (départ exclu, D7.4) : {absent}"
                )
    declared = {outing.outing_id for outing in outings}
    unknown = sorted(set(spec.admission_exclusions) - declared)
    if unknown:
        raise ExperimentError(
            "exclusion d'admission d'une sortie qui n'est pas celle d'une performance "
            f"déclarée : {unknown}"
        )


# ---------------------------------------------------------------------------
# Les scores du candidat (D9.3, Q2)
# ---------------------------------------------------------------------------


def candidate_scores(
    effect: CandidateEffect,
    observation: OutingObservation,
    reference: RouteProfile | None,
    realized: RouteProfile,
    curve: PaceCurve,
    *,
    curve_ref: str,
    base: ModelForecast | None,
    generated_at: datetime,
) -> OutingScores:
    """Les scores **non calés** du candidat sur une sortie (``0010`` D9.3 ; décision
    Q2) : la chronologie de v0 à l'effort 1, aux paramètres de départ, transformée par
    l'effet ; une ``ValueError`` ou une ``ArithmeticError`` de l'effet : pas de
    chronologie. En contrôle sur ``realized``, en usage sur ``reference`` s'il est
    présent ; sans chronologie, une prévision de même provenance sans aucune valeur
    (une erreur du modèle). ``base`` : la prévision d'usage de v0 brut, dénominateur de
    ``q_usage`` des scores non calés (D7.4), comme pour les baselines — sans effet sur
    le RÉSULTAT, le calage recalculant ses scores sur sa propre base.

    Précondition (``ValueError``), sans chronologie en usage : la longueur du profil de
    ``reference`` est ``L`` de l'observation (avec chronologie, celle
    d'``usage_forecast``).
    """
    parameters = ParameterSet(PROJECTION_PARAMETER_SPECS)

    def transformed(profile: RouteProfile) -> ProjectedTimeline | None:
        v0 = projected_timeline(profile, curve, parameters)
        try:
            return effect.timeline(profile, v0)
        except (ValueError, ArithmeticError):
            return None

    def empty(scenario: Scenario, profile: RouteProfile) -> ModelForecast:
        usage = scenario is Scenario.USAGE
        return ModelForecast(
            scenario=scenario,
            source=profile.source,
            curve_ref=curve_ref,
            parameters=parameters,
            engine_version=ENGINE_VERSION,
            generated_at=generated_at,
            segment_s=(None,) * len(observation.segments),
            point_s=(None,) * len(observation.error_points) if usage else (),
            target_s=(None,) * len(observation.targets) if usage else (),
        )

    timeline = transformed(realized)
    control = (
        empty(Scenario.CONTROL, realized)
        if timeline is None
        else control_forecast(
            observation,
            timeline,
            source=realized.source,
            curve_ref=curve_ref,
            parameters=parameters,
            generated_at=generated_at,
        )
    )
    usage = None
    if reference is not None:
        timeline = transformed(reference)
        if timeline is None:
            length = reference.distance_m[-1]
            if length != observation.reference_length_m:
                raise ValueError(
                    f"candidate_scores : le profil a la longueur {length}, "
                    f"l'observation L = {observation.reference_length_m} : un autre "
                    "tracé."
                )
            usage = empty(Scenario.USAGE, reference)
        else:
            usage = usage_forecast(
                observation,
                timeline,
                source=reference.source,
                curve_ref=curve_ref,
                parameters=parameters,
                generated_at=generated_at,
            )
    return score_outing(
        observation,
        score_scenario(observation, control),
        None if usage is None else score_scenario(observation, usage, base=base),
    )


# ---------------------------------------------------------------------------
# Exécution : DÉCLARATION, scores, calage, admission, RÉSULTAT ou ÉCHEC
# ---------------------------------------------------------------------------


def run_experiment(
    preparation: ExperimentPreparation,
    registry_root: Path,
    *,
    recorded_at: datetime | None = None,
) -> ExperimentRun:
    """L'expérience enregistrée (``0010`` D10, D14 ; décisions Q2 à Q5), dans cet
    ordre :

    1. précondition, avant tout écrit : la déclaration porte une expérience sans date
       d'analyse (``ExperimentError`` sinon) ;
    2. la DÉCLARATION ;
    3. pour chaque sortie observée, les scores non calés de v0 brut et du candidat,
       datés de la DÉCLARATION ; le calage de (0) et de (1) ; une entrée de la règle par
       performance déclarée ; ``admit`` sur les références figées de la DÉCLARATION ;
    4. sans performance évaluable, un ÉCHEC « non évaluable » dont le motif compte les
       performances par motif, dans l'ordre de ``NonEvaluable`` ;
    5. sinon le RÉSULTAT : v0 brut, (0) et (1) par sortie observée ; les sorties non
       scorées au motif du refus du manifeste, ou « sortie non tracée » ; les
       références D8 de la préparation ; le document d'admission ;
    6. une exception ou une interruption au clavier de 3 à 5 : un ÉCHEC technique au
       motif sans chemin, puis ``BacktestError``.
    """
    experiment = preparation.declaration.experiment
    if experiment is None or experiment.analysis_date is not None:
        raise ExperimentError(
            "run_experiment : une expérience d'admission exploratoire, sans date "
            "d'analyse (D10.7 : pas de figement pour confirmation dans ce lot)."
        )
    declared = append_declaration(
        registry_root, preparation.declaration, recorded_at=recorded_at
    )
    try:
        return _answer(preparation, experiment, declared, registry_root, recorded_at)
    except (Exception, KeyboardInterrupt) as error:
        reason = failure_reason(error)
        append_failure(
            registry_root,
            declared.number,
            Failure(FailureKind.TECHNICAL, reason),
            recorded_at=recorded_at,
        )
        raise BacktestError(
            f"échec de l'expérience, ÉCHEC enregistré : {reason}"
        ) from error


def _answer(
    preparation: ExperimentPreparation,
    experiment: ExperimentDeclaration,
    declared: RegistryEvent,
    registry_root: Path,
    recorded_at: datetime | None,
) -> ExperimentRun:
    """Les étapes 3 à 5 de ``run_experiment``."""
    backtest = preparation.backtest
    curve = backtest.curve
    generated_at = declared.recorded_at
    raw: dict[str, OutingScores] = {}
    unscaled: dict[str, dict[ModelKind, OutingScores]] = {}
    for outing_id, seen in preparation.observed.items():
        traced = seen.traced
        v0 = v0_scores(
            traced.usage,
            traced.trace,
            traced.match,
            traced.passages,
            traced.partition,
            curve.curve,
            curve_ref=curve.curve_ref,
            generated_at=generated_at,
        )
        candidate = candidate_scores(
            preparation.spec.effect,
            seen.observation,
            traced.usage,
            seen.realized,
            curve.curve,
            curve_ref=curve.curve_ref,
            base=None if v0.usage is None else v0.usage.forecast,
            generated_at=generated_at,
        )
        raw[outing_id] = v0
        unscaled[outing_id] = {ModelKind.V0_RAW: v0, ModelKind.CANDIDATE: candidate}
    calibration = calibrate_performances(
        backtest.performances,
        unscaled,
        models=(ModelKind.V0_RECALIBRATED, ModelKind.CANDIDATE),
    )
    calibrated: dict[tuple[str, ModelKind], CalibratedOutingScores] = {
        (entry.outing_id, entry.control.model): entry
        for performance in calibration
        for entry in performance.outings
    }
    inputs = _inputs(preparation, raw, calibrated)
    admitted = admit(experiment, inputs, experiment.frozen_references)
    if not isinstance(admitted, Admission):
        counts = Counter(assessment.motif for assessment in admitted)
        reason = "aucune performance évaluable : " + ", ".join(
            f"{motif} {counts[motif]}" for motif in NonEvaluable if counts[motif]
        )
        failure = append_failure(
            registry_root,
            declared.number,
            Failure(FailureKind.NOT_EVALUABLE, reason),
            recorded_at=recorded_at,
        )
        return ExperimentRun(
            preparation, declared, failure, (), None, admitted, line_hash(failure)
        )
    outcomes = tuple(
        OutingOutcome(
            outing_id,
            seen.traced.match.coverage,
            (
                (ModelKind.V0_RAW, raw[outing_id]),
                (
                    ModelKind.V0_RECALIBRATED,
                    calibrated[(outing_id, ModelKind.V0_RECALIBRATED)],
                ),
                (ModelKind.CANDIDATE, calibrated[(outing_id, ModelKind.CANDIDATE)]),
            ),
        )
        for outing_id, seen in preparation.observed.items()
    )
    refused = {entry.outing_id: entry.reason for entry in backtest.manifest.refused}
    unscored = tuple(
        Exclusion(outing.outing_id, refused.get(outing.outing_id, _UNTRACED))
        for performance in backtest.performances
        for outing in performance.outings
        if outing.outing_id not in preparation.observed
    )
    result = append_result(
        registry_root,
        declared.number,
        outcomes,
        unscored=unscored,
        references=preparation.references,
        admission=admitted,
        recorded_at=recorded_at,
    )
    return ExperimentRun(
        preparation,
        declared,
        result,
        outcomes,
        admitted,
        admitted.performances,
        line_hash(result),
    )


def _inputs(
    preparation: ExperimentPreparation,
    raw: Mapping[str, OutingScores],
    calibrated: Mapping[tuple[str, ModelKind], CalibratedOutingScores],
) -> list[AdmissionInput]:
    """Une entrée de la règle par performance déclarée : sa première sortie ;
    l'observation, sauf pour un jour multi-sorties ; les scores d'usage de v0 brut,
    (0) et (1) si elle a un scénario d'usage ; exclue si **une** de ses sorties l'est ;
    le D+/km du domaine de sa première sortie, absent pour un jour multi-sorties ; la
    durée de v0 brut sur la portion déclarée (décision Q7)."""
    backtest = preparation.backtest
    excluded = set(preparation.spec.admission_exclusions)
    domains = {domain.outing_id: domain.dplus_per_km for domain in backtest.domains}
    curve = backtest.curve.curve
    entries: list[AdmissionInput] = []
    for performance in backtest.performances:
        first = performance.outings[0]
        outing_id = first.outing_id
        multi = performance.is_multi_outing
        seen = preparation.observed.get(outing_id)
        scores = raw.get(outing_id)
        usage = None if scores is None else scores.usage
        base = calibrated.get((outing_id, ModelKind.V0_RECALIBRATED))
        candidate = calibrated.get((outing_id, ModelKind.CANDIDATE))
        portion_s = None
        if seen is not None and seen.traced.usage is not None:
            portion_s = _portion_s(seen.traced, curve)
        entries.append(
            AdmissionInput(
                performance,
                any(outing.outing_id in excluded for outing in performance.outings),
                None if multi or seen is None else seen.observation,
                usage,
                None if usage is None or base is None else base.usage,
                None if usage is None or candidate is None else candidate.usage,
                None if multi else domains.get(outing_id),
                portion_s,
            )
        )
    return entries


def _portion_s(traced: TracedOuting, curve: PaceCurve) -> float | None:
    """La durée de v0 brut à l'effort 1 sur la portion déclarée de la sortie, de
    ``time_at(début)`` à ``time_at(fin)`` ; tout le profil sans portion ; absente sans
    référence (décision Q7)."""
    profile = traced.usage
    if profile is None:
        return None
    timeline = projected_timeline(
        profile, curve, ParameterSet(PROJECTION_PARAMETER_SPECS)
    )
    portion = traced.outing.declared_portion_m
    start, end = (0.0, timeline.length_m) if portion is None else portion
    return timeline.time_at(end) - timeline.time_at(start)
