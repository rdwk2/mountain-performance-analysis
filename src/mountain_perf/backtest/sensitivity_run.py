"""L'exécution enregistrée de la sensibilité de ``0010`` D13 (M4d-3) : les neuf paires
``(Δ, ε)``, la DÉCLARATION de sensibilité, les dix-neuf configurations comparées à leur
comparateur, le RÉSULTAT ou l'ÉCHEC ; la vue composée.

Protocole : ``docs/decisions/0010`` D13 et D14 (et leurs précisions de M4d-3, dont
l'exception de D14), D10.1, D10.3, D10.6. La sensibilité qualifie la centrale que le
même processus vient d'écrire (décision C1) : ``run_backtest`` ou ``run_experiment``,
dont elle reprend les objets en mémoire pour la paire ``(250, 30)`` ; elle n'enchaîne
que des calculs des modules fusionnés. Ses messages ne portent aucun chemin absolu
(règle 1 de ``CLAUDE.md``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

from mountain_perf.backtest.admission import AdmissionInput, admit
from mountain_perf.backtest.codec import content_hash, encode_document
from mountain_perf.backtest.execution import (
    BacktestError,
    BacktestEvaluation,
    BacktestRun,
    TracedOuting,
    evaluate_traced,
    failure_reason,
    outing_outcomes,
    repeatability_references,
    trace_outings,
)
from mountain_perf.backtest.experiment import (
    ExperimentRun,
    ObservedOuting,
    admission_inputs,
    experiment_outcomes,
    experiment_scores,
    experiment_unscored,
    frozen_references,
    reference_documents,
)
from mountain_perf.backtest.geometry import ReferenceGeometry
from mountain_perf.backtest.matching import MATCHING_PARAMETER_SPECS
from mountain_perf.backtest.registry import (
    PairOutcome,
    append_declaration,
    append_failure,
    append_result,
    comparator_configuration,
    line_hash,
    load_sensitivity,
    read_registry,
)
from mountain_perf.backtest.scoring import observe_outing
from mountain_perf.backtest.sensitivity import (
    SENSITIVITY_CENTRAL_M,
    SENSITIVITY_CONFIGURATIONS,
    SENSITIVITY_PAIRS,
    Decision,
    SensitivityQualification,
    Side,
    compare_performance,
    configuration_outcome,
    qualify_sensitivity,
    sensitivity_outcome,
)
from mountain_perf.schemas import (
    CalibratedOutingScores,
    ConfigurationOutcome,
    ConfigurationReferences,
    Declaration,
    EventKind,
    Exclusion,
    Failure,
    FailureKind,
    ModelKind,
    OutingOutcome,
    OutingScores,
    PairReferences,
    ParameterSet,
    PerformanceComparison,
    PerformanceMotif,
    RegistryEvent,
    RegistryLog,
    RepeatabilityRecord,
    RepeatabilityReference,
    RouteProfile,
    SensitivityConfiguration,
    SensitivityDeclaration,
    SensitivityOutcome,
)

Pair = tuple[float, float]
"""Une paire ``(Δ, ε)`` (m)."""


class SensitivityError(ValueError):
    """Une sensibilité refusée avant sa DÉCLARATION : rien n'est écrit."""


def pair_matching(pair: Pair) -> ParameterSet:
    """L'appariement d'une paire ``(Δ, ε)`` (``0010`` D13) : ``r_c`` au défaut, fixe."""
    step_m, tolerance_m = pair
    return ParameterSet(
        MATCHING_PARAMETER_SPECS,
        {"score_step_m": step_m, "lateral_tolerance_m": tolerance_m},
    )


@dataclass(frozen=True)
class PairEvaluation:
    """Une paire ``(Δ, ε)`` calculée, en mémoire : ses sorties scorées et non scorées,
    ses références D8 ; pour ``just backtest``, l'évaluation de la paire (sorties
    tracées, calage, fourchettes : le rapport s'en sert) ; pour une expérience, la
    décision de chacune de ses configurations, dans l'ordre des configurations."""

    pair: Pair
    outcomes: tuple[OutingOutcome, ...]
    unscored: tuple[Exclusion, ...]
    references: tuple[tuple[str, RepeatabilityReference], ...]
    evaluation: BacktestEvaluation | None


@dataclass(frozen=True)
class SensitivityEvaluation:
    """Le calcul d'une sensibilité, avant son RÉSULTAT (le rapport s'y calcule) : la
    centrale, la DÉCLARATION de sensibilité, les neuf paires dans l'ordre, et le
    document de sensibilité."""

    central: BacktestRun | ExperimentRun
    declaration_event: RegistryEvent
    pairs: tuple[PairEvaluation, ...]
    outcome: SensitivityOutcome


@dataclass(frozen=True)
class SensitivityRun:
    """Une sensibilité enregistrée : son calcul, son RÉSULTAT, et le sceau (l'empreinte
    de la ligne du RÉSULTAT)."""

    evaluation: SensitivityEvaluation
    answer_event: RegistryEvent
    seal: str


# ---------------------------------------------------------------------------
# Contrôles d'avant la DÉCLARATION
# ---------------------------------------------------------------------------


def _central_events(central: BacktestRun | ExperimentRun) -> tuple[RegistryEvent, ...]:
    if isinstance(central, BacktestRun):
        return central.declaration_event, central.result_event
    return central.declaration_event, central.answer_event


def _check_central(central: BacktestRun | ExperimentRun, log: RegistryLog) -> None:
    """Les refus d'avant la DÉCLARATION (``SensitivityError``), dans l'ordre : une
    centrale en ÉCHEC n'a rien à qualifier ; une centrale appariée hors de
    ``(250, 30)``, ``r_c = 15`` m, n'a pas de comparateur parmi les dix-neuf ; sa
    DÉCLARATION et sa réponse sont celles du registre (mêmes événements) ; la
    DÉCLARATION est en vigueur et la réponse est sa réponse en vigueur."""
    declared, answer = _central_events(central)
    if answer.kind is not EventKind.RESULT:
        raise SensitivityError(
            "la centrale a reçu un ÉCHEC : une sensibilité qualifie un RÉSULTAT (D13)."
        )
    declaration = declared.declaration
    assert declaration is not None  # une DÉCLARATION
    if declaration.matching != pair_matching(SENSITIVITY_CENTRAL_M):
        raise SensitivityError(
            "la centrale n'est pas appariée à (250, 30), r_c 15 m : son comparateur "
            "n'est pas une des dix-neuf configurations (D13)."
        )
    for event in (declared, answer):
        if event.number > len(log.events) or log.event(event.number) != event:
            raise SensitivityError(
                f"l'événement {event.number} de la centrale n'est pas celui du "
                "registre."
            )
    in_force = log.answer(declared.number)
    if not log.in_force(declared.number) or in_force != answer:
        raise SensitivityError(
            "la centrale n'est pas en vigueur au registre (corrigée, ou sa réponse "
            "l'est)."
        )


# ---------------------------------------------------------------------------
# Comparaisons
# ---------------------------------------------------------------------------


def _motif(
    declaration: Declaration, outcomes: Mapping[str, OutingOutcome], rank: int
) -> PerformanceMotif | None:
    performance = declaration.performances[rank].performance
    first = performance.outings[0]
    if performance.is_multi_outing:
        return PerformanceMotif.MULTI_OUTING
    if first.outing_id not in outcomes:
        return PerformanceMotif.NOT_SCORED
    if first.reference is None:
        return PerformanceMotif.NO_REFERENCE
    return None


def compare_configuration(
    declaration: Declaration,
    configuration: SensitivityConfiguration,
    outcomes: Mapping[str, OutingOutcome],
    comparator: SensitivityConfiguration,
    comparator_outcomes: Mapping[str, OutingOutcome],
) -> tuple[PerformanceComparison, ...]:
    """La comparaison de chaque performance déclarée sous ``configuration`` (sorties
    ``outcomes``) avec le comparateur (``comparator_outcomes``), dans l'ordre des
    performances : un motif — jour multi-sorties, sortie non scorée, sans référence —,
    sinon les deux côtés de sa sortie (``compare_performance``)."""
    comparisons: list[PerformanceComparison] = []
    for rank, declared in enumerate(declaration.performances):
        performance = declared.performance
        outing_id = performance.outings[0].outing_id
        motif = _motif(declaration, outcomes, rank)
        if motif is not None:
            comparisons.append(
                compare_performance(
                    performance.civil_date, outing_id, motif, None, None
                )
            )
            continue
        comparisons.append(
            compare_performance(
                performance.civil_date,
                outing_id,
                None,
                Side(comparator_outcomes[outing_id], comparator.clock),
                Side(outcomes[outing_id], configuration.clock),
            )
        )
    return tuple(comparisons)


def _records(
    references: tuple[tuple[str, RepeatabilityReference], ...],
) -> tuple[RepeatabilityRecord, ...]:
    """Les empreintes des documents D8, telles que le RÉSULTAT les écrira."""
    return tuple(
        RepeatabilityRecord(route_id, content_hash(encode_document(reference)))
        for route_id, reference in references
    )


# ---------------------------------------------------------------------------
# Exécution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Observed:
    """Ce qu'une paire observe avant la DÉCLARATION : pour ``just backtest``, ses
    sorties tracées et non scorées ; pour une expérience, ses sorties observées ; ses
    références D8."""

    pair: Pair
    traced: tuple[TracedOuting, ...]
    unscored: tuple[Exclusion, ...]
    observed: Mapping[str, ObservedOuting]
    references: tuple[tuple[str, RepeatabilityReference], ...]


def _observe(
    central: BacktestRun | ExperimentRun,
    pair: Pair,
    profiles: dict[Path, tuple[RouteProfile, ReferenceGeometry]],
) -> _Observed:
    """L'observation d'une paire autre que ``(250, 30)``, sans prévision : chaque sortie
    tracée sous l'appariement de la paire, puis les références D8 sur ces seules
    observations (``0010`` D13 ; précision de D10.1, M4c-3)."""
    matching = pair_matching(pair)
    if isinstance(central, BacktestRun):
        preparation = central.preparation
        traced, unscored = trace_outings(preparation, profiles, matching)
        observations = {
            item.outing.outing_id: observe_outing(
                item.match, item.passages, item.partition
            )
            for item in traced
        }
        references = repeatability_references(preparation.performances, observations)
        return _Observed(pair, traced, unscored, MappingProxyType({}), references)
    experiment = central.preparation
    traced, unscored = trace_outings(experiment.backtest, profiles, matching)
    observed = {
        item.outing.outing_id: ObservedOuting(
            item,
            observe_outing(item.match, item.passages, item.partition),
            experiment.observed[item.outing.outing_id].realized,
        )
        for item in traced
    }
    references = repeatability_references(
        experiment.backtest.performances,
        {outing_id: seen.observation for outing_id, seen in observed.items()},
    )
    return _Observed(pair, (), unscored, MappingProxyType(observed), references)


def _central_references(
    central: BacktestRun | ExperimentRun,
) -> tuple[tuple[str, RepeatabilityReference], ...]:
    if isinstance(central, BacktestRun):
        return central.references
    return central.preparation.references


def _sensitivity_declaration(
    central: BacktestRun | ExperimentRun,
    references: Mapping[Pair, tuple[tuple[str, RepeatabilityReference], ...]],
) -> Declaration:
    """La DÉCLARATION de sensibilité (précision et exception de D14, M4d-3) : la
    déclaration centrale, plus la centrale et sa réponse (numéros, empreintes de leurs
    lignes), les dix-neuf configurations, les documents D8 de chaque paire et, pour une
    expérience, les références figées de chaque configuration, sous son horloge."""
    declared, answer = _central_events(central)
    declaration = declared.declaration
    assert declaration is not None  # une DÉCLARATION
    frozen = None
    if declaration.experiment is not None:
        frozen = tuple(
            ConfigurationReferences(
                configuration,
                frozen_references(
                    references[
                        (configuration.score_step_m, configuration.lateral_tolerance_m)
                    ],
                    configuration.clock,
                ),
            )
            for configuration in SENSITIVITY_CONFIGURATIONS
        )
    sensitivity = SensitivityDeclaration(
        central=declared.number,
        central_hash=line_hash(declared),
        answer=answer.number,
        answer_hash=line_hash(answer),
        configurations=SENSITIVITY_CONFIGURATIONS,
        pairs=tuple(
            PairReferences(*pair, _records(references[pair]))
            for pair in SENSITIVITY_PAIRS
        ),
        frozen=frozen,
    )
    return replace(declaration, sensitivity=sensitivity)


def run_sensitivity(
    central: BacktestRun | ExperimentRun,
    registry_root: Path,
    *,
    recorded_at: datetime | None = None,
    on_pair: Callable[[Pair], None] | None = None,
    on_declaration: Callable[[RegistryEvent, str], None] | None = None,
    before_result: Callable[[SensitivityEvaluation], None] | None = None,
) -> SensitivityRun:
    """La sensibilité enregistrée d'une centrale que le même processus vient d'écrire
    (``0010`` D13, D14 ; précisions de M4d-3 ; décision C1), dans cet ordre :

    1. les refus, rien d'écrit (``SensitivityError``) ;
    2. l'observation des huit autres paires, sans prévision, ``on_pair(paire)`` après
       chacune ; leurs références D8 ;
    3. la DÉCLARATION de sensibilité, puis ``on_declaration(événement, empreinte de sa
       ligne)`` ;
    4. par paire, les scores datés de cette DÉCLARATION, le calage et, pour ``just
       backtest``, les fourchettes ; la paire ``(250, 30)`` est celle de la centrale ;
       pour une expérience, l'admission de chaque configuration (celle de la centrale
       pour le comparateur) ; les comparaisons ; le document de sensibilité ;
       ``before_result(calcul)`` ; le RÉSULTAT ;
    5. une exception ou une interruption au clavier de 3 à 4 : un ÉCHEC technique au
       motif sans chemin, puis ``BacktestError`` (décision C9).
    """
    log = read_registry(registry_root)
    _check_central(central, log)
    profiles: dict[Path, tuple[RouteProfile, ReferenceGeometry]] = {}
    observed: dict[Pair, _Observed] = {}
    for pair in SENSITIVITY_PAIRS:
        if pair == SENSITIVITY_CENTRAL_M:
            continue
        observed[pair] = _observe(central, pair, profiles)
        if on_pair is not None:
            on_pair(pair)
    references = {pair: seen.references for pair, seen in observed.items()}
    references[SENSITIVITY_CENTRAL_M] = _central_references(central)
    declaration = _sensitivity_declaration(central, references)
    declared = append_declaration(registry_root, declaration, recorded_at=recorded_at)
    try:
        if on_declaration is not None:
            on_declaration(declared, line_hash(declared))
        evaluation = _evaluate(central, declared, observed)
        if before_result is not None:
            before_result(evaluation)
        answer = append_result(
            registry_root,
            declared.number,
            (),
            pairs=tuple(
                PairOutcome(*pair.pair, pair.outcomes, pair.unscored, pair.references)
                for pair in evaluation.pairs
            ),
            sensitivity=evaluation.outcome,
            recorded_at=recorded_at,
        )
    except (Exception, KeyboardInterrupt) as error:
        reason = failure_reason(error)
        failure = append_failure(
            registry_root,
            declared.number,
            Failure(FailureKind.TECHNICAL, reason),
            recorded_at=recorded_at,
        )
        raise BacktestError(
            f"échec de la sensibilité, ÉCHEC enregistré (événement {failure.number} ; "
            f"dernière ligne sha256 {line_hash(failure)}) : {reason}"
        ) from error
    return SensitivityRun(evaluation, answer, line_hash(answer))


def _evaluate(
    central: BacktestRun | ExperimentRun,
    declared: RegistryEvent,
    observed: Mapping[Pair, _Observed],
) -> SensitivityEvaluation:
    """L'étape 4 de ``run_sensitivity``, sans rien écrire."""
    declaration = declared.declaration
    assert declaration is not None  # une DÉCLARATION
    assert declaration.sensitivity is not None  # de sensibilité
    if isinstance(central, BacktestRun):
        pairs = tuple(
            _backtest_pair(central, declared, observed.get(pair), pair)
            for pair in SENSITIVITY_PAIRS
        )
        decisions: dict[SensitivityConfiguration, Decision] = {}
    else:
        pairs, decisions = _experiment_pairs(central, declared, observed, declaration)
    comparator = comparator_configuration(declaration)
    by_pair = {
        pair.pair: {outcome.outing_id: outcome for outcome in pair.outcomes}
        for pair in pairs
    }
    comparator_outcomes = by_pair[SENSITIVITY_CENTRAL_M]
    configurations: list[ConfigurationOutcome] = []
    for configuration in SENSITIVITY_CONFIGURATIONS:
        pair = (configuration.score_step_m, configuration.lateral_tolerance_m)
        performances = compare_configuration(
            declaration, configuration, by_pair[pair], comparator, comparator_outcomes
        )
        if decisions:
            configurations.append(
                configuration_outcome(
                    configuration,
                    performances,
                    decisions[configuration],
                    decisions[comparator],
                )
            )
        else:
            configurations.append(configuration_outcome(configuration, performances))
    outcome = sensitivity_outcome(
        SENSITIVITY_CONFIGURATIONS.index(comparator), tuple(configurations)
    )
    return SensitivityEvaluation(central, declared, pairs, outcome)


def _backtest_pair(
    central: BacktestRun,
    declared: RegistryEvent,
    seen: _Observed | None,
    pair: Pair,
) -> PairEvaluation:
    """Une paire de la sensibilité de ``just backtest`` : celle de la centrale pour
    ``(250, 30)`` ; sinon ``evaluate_traced`` sur ses sorties tracées, prévisions datées
    de la DÉCLARATION de sensibilité."""
    if seen is None:
        evaluation = BacktestEvaluation(
            central.preparation,
            central.declaration_event,
            central.outings,
            central.unscored,
            central.references,
            central.calibration,
            central.bands,
        )
    else:
        evaluation = evaluate_traced(
            central.preparation,
            declared,
            seen.traced,
            seen.unscored,
        )
    return PairEvaluation(
        pair,
        outing_outcomes(evaluation.outings, evaluation.calibration, evaluation.bands),
        evaluation.unscored,
        evaluation.references,
        evaluation,
    )


def _experiment_pairs(
    central: ExperimentRun,
    declared: RegistryEvent,
    observed: Mapping[Pair, _Observed],
    declaration: Declaration,
) -> tuple[tuple[PairEvaluation, ...], dict[SensitivityConfiguration, Decision]]:
    """Les paires de la sensibilité d'une expérience, et la décision de chaque
    configuration (précision de D13, M4d-3 ; D13-D, D13-E) : l'admission refaite sous
    la configuration — son horloge, les références figées de la DÉCLARATION de
    sensibilité — sur les entrées de sa paire ; celle de la centrale pour le
    comparateur."""
    experiment = declaration.experiment
    sensitivity = declaration.sensitivity
    assert experiment is not None  # appelant
    assert sensitivity is not None  # appelant
    assert sensitivity.frozen is not None  # contrat de Declaration
    preparation = central.preparation
    inputs: dict[Pair, list[AdmissionInput]] = {}
    pairs: list[PairEvaluation] = []
    for pair in SENSITIVITY_PAIRS:
        seen = observed.get(pair)
        if seen is None:
            prepared = preparation
            outcomes = central.outcomes
            raw = {
                outcome.outing_id: _scores_of(outcome, ModelKind.V0_RAW)
                for outcome in outcomes
            }
            calibrated = {
                (outcome.outing_id, kind): _calibrated_of(outcome, kind)
                for outcome in outcomes
                for kind in (ModelKind.V0_RECALIBRATED, ModelKind.CANDIDATE)
            }
            unscored = experiment_unscored(preparation)
            references = preparation.references
        else:
            prepared = replace(
                preparation, observed=seen.observed, references=seen.references
            )
            scores = experiment_scores(prepared, declared.recorded_at)
            outcomes, unscored = experiment_outcomes(prepared, scores)
            raw, calibrated = dict(scores.raw), dict(scores.calibrated)
            references = seen.references
        inputs[pair] = admission_inputs(prepared, raw, calibrated)
        pairs.append(PairEvaluation(pair, outcomes, unscored, references, None))
    comparator = comparator_configuration(declaration)
    by_pair = {pair.pair: pair.references for pair in pairs}
    decisions: dict[SensitivityConfiguration, Decision] = {}
    for entry in sensitivity.frozen:
        configuration = entry.configuration
        if configuration == comparator:
            decisions[configuration] = (
                central.admission
                if central.admission is not None
                else central.assessments
            )
            continue
        pair = (configuration.score_step_m, configuration.lateral_tolerance_m)
        local = replace(
            experiment,
            clock=configuration.clock,
            frozen_references=entry.frozen_references,
            reference_documents=reference_documents(
                by_pair[pair], entry.frozen_references
            ),
        )
        decisions[configuration] = admit(local, inputs[pair], entry.frozen_references)
    return tuple(pairs), decisions


def _scores_of(outcome: OutingOutcome, kind: ModelKind) -> OutingScores:
    scores = dict(outcome.scores)[kind]
    assert isinstance(scores, OutingScores)  # v0 brut
    return scores


def _calibrated_of(outcome: OutingOutcome, kind: ModelKind) -> CalibratedOutingScores:
    scores = dict(outcome.scores)[kind]
    assert isinstance(scores, CalibratedOutingScores)  # un modèle calé
    return scores


# ---------------------------------------------------------------------------
# Vue composée (D10.6)
# ---------------------------------------------------------------------------


def sensitivity_qualification(root: Path, central: int) -> SensitivityQualification:
    """La vue composée de la DÉCLARATION centrale ``central`` (``0010`` D10.6 ;
    précision de M4d-3) : la dernière DÉCLARATION de sensibilité en vigueur qui la
    qualifie, et sa réponse en vigueur — un RÉSULTAT donne son document (ses réserves,
    ou « sensibilité faite »), un ÉCHEC ou aucune réponse « sensibilité incomplète » ;
    aucune sensibilité : « centrale, sensibilité restante »."""
    log = read_registry(root)
    candidates = [
        event
        for event in log.events
        if event.declaration is not None
        and event.declaration.sensitivity is not None
        and event.declaration.sensitivity.central == central
        and log.in_force(event.number)
    ]
    if not candidates:
        return qualify_sensitivity(False, None)
    answer = log.answer(candidates[-1].number)
    if answer is None or answer.kind is not EventKind.RESULT:
        return qualify_sensitivity(True, None)
    return qualify_sensitivity(True, load_sensitivity(root, log, answer.number))
