"""Garanties de l'exécution de la sensibilité (M4d-3, ``backtest/sensitivity_run.py``)
que les tests joints ne tenaient pas — correctifs de la relecture de la PR #32
(relecture C en deux passes, balayage de mutation de la conception).

- L'appariement de chaque paire : ``pair_matching`` pour les neuf paires (``Δ``, ``ε``,
  ``r_c = 15`` m), et l'appariement sous lequel chaque sortie de chaque paire a été
  tracée. Le monde n'exerce pas ``ε`` (ses traces restent à ±1 m de leur référence) :
  seul l'appariement transmis le montre.
- ``just backtest`` : la référence D8, le calage et les fourchettes de chaque paire,
  recalculés sur ses seules observations et ses scores.
- Une expérience : les observations des huit autres paires (celles de la même paire
  dans la sensibilité de ``just backtest``, même monde), leurs références D8, les
  références figées de chaque configuration ; les sorties non scorées au motif du
  manifeste sous chaque paire ; les exclusions d'admission et le ``K`` déclaré sous
  chaque configuration, mutualisé contre dédié ; une configuration sans performance
  évaluable, sans décision.
- Une exception, ou une interruption au clavier, dans le calcul d'une paire (pas dans
  un crochet) : un ÉCHEC technique après la DÉCLARATION, dont l'empreinte a été publiée
  avant le calcul.
- La vue composée sur un registre à deux centrales.

Aucune donnée réelle : le monde de M4b-5 et l'effet de descente de ``fixtures.effects``.
"""

from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

import mountain_perf.backtest.sensitivity_run as sensitivity_run
from fixtures.admission_world import ADMISSION_EXCLUSION, K_PREFIX
from fixtures.backtest_world import COMMIT, COURBE, RECORDED_AT, RETRIEVED_AT
from fixtures.sensitivity_world import (
    EXPERIMENT_CLOCKS,
    EXPERIMENT_EFFECT,
    EXPERIMENT_TARGET,
    SENSITIVITY_RECORDED_AT,
    BacktestSensitivity,
    ExperimentSensitivity,
    MiniCentral,
    backtest_sensitivity,
    copy_registry,
    experiment_manifest,
    experiment_sensitivity,
    mini_central,
)
from mountain_perf.backtest import (
    DOCUMENTS_DIR,
    MATCHING_PARAMETER_SPECS,
    SENSITIVITY_CONFIGURATIONS,
    SENSITIVITY_PAIRS,
    BacktestError,
    ExperimentRun,
    ExperimentSpec,
    Pair,
    PairEvaluation,
    SensitivityQualification,
    SensitivityRun,
    SensitivityStatus,
    append_declaration,
    append_failure,
    append_result,
    calibrate_performances,
    content_hash,
    encode_document,
    evaluation_bands,
    failure_reason,
    frozen_references,
    line_hash,
    load_outcomes,
    pair_matching,
    prepare_experiment,
    read_registry,
    repeatability_references,
    run_experiment,
    run_sensitivity,
    sensitivity_qualification,
    verify_registry,
)
from mountain_perf.schemas import (
    CLOCKS,
    CalibratedOutingScores,
    ClockKind,
    Declaration,
    EventKind,
    ExperimentMetric,
    Failure,
    FailureKind,
    ModelKind,
    OutingObservation,
    OutingScores,
    ParameterSet,
    RegistryEvent,
    RepeatabilityRecord,
    SensitivityConfiguration,
)
from mountain_perf.schemas.admission import NonEvaluable

D, R, F = EventKind.DECLARATION, EventKind.RESULT, EventKind.FAILURE
CENTRAL_PAIR: Pair = (250.0, 30.0)
OTHER_PAIR: Pair = (100.0, 15.0)
"""Une paire autre que la centrale, dont les documents diffèrent sur le monde."""
MOVING_2 = SensitivityConfiguration(250.0, 30.0, 15.0, CLOCKS[3])
"""La configuration ``(250, 30)`` sous ``M θ2`` : le comparateur d'une expérience
dédiée déclarée sous cette horloge."""
EXCLUDED_OUTING = "b-2026-06-25"
"""La sortie exclue de l'admission : une performance évaluable du monde."""


def _declaration(event: RegistryEvent) -> Declaration:
    assert event.declaration is not None
    return event.declaration


def _pair(world: BacktestSensitivity | ExperimentSensitivity, pair: Pair) -> Any:
    (evaluated,) = [p for p in world.run.evaluation.pairs if p.pair == pair]
    return evaluated


def _observations(evaluated: PairEvaluation) -> dict[str, OutingObservation]:
    """L'observation de chaque sortie scorée d'une paire, lue dans ses scores de v0
    brut."""
    return {
        outcome.outing_id: next(
            s for _, s in outcome.scores if isinstance(s, OutingScores)
        ).observation
        for outcome in evaluated.outcomes
    }


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> BacktestSensitivity:
    """La sensibilité de ``just backtest`` sur le monde."""
    return backtest_sensitivity(tmp_path_factory)


@pytest.fixture(scope="module", params=list(EXPERIMENT_CLOCKS))
def experiment(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> ExperimentSensitivity:
    """Les deux expériences du monde et leur sensibilité : sous l'écoulé, sous
    ``M θ2``."""
    name: str = request.param
    return experiment_sensitivity(tmp_path_factory, name)


@pytest.fixture(scope="module")
def mini(tmp_path_factory: pytest.TempPathFactory) -> MiniCentral:
    """La centrale du petit monde, seule dans son registre."""
    return mini_central(tmp_path_factory)


@dataclass(frozen=True)
class Variant:
    """Une expérience du monde déclarée sous l'écoulé et sa sensibilité ; la même
    expérience, dédiée, déclarée sous ``M θ2``."""

    central: ExperimentRun
    run: SensitivityRun
    dedicated: ExperimentRun


def _variant(
    factory: pytest.TempPathFactory, target: ExperimentMetric, **spec: Any
) -> Variant:
    """L'expérience de l'effet de descente sur ``target`` (``spec`` complète
    l'``ExperimentSpec``) : sous l'écoulé, suivie de sa sensibilité ; sous ``M θ2``,
    seule — chacune dans son registre."""
    manifest = experiment_manifest(factory)

    def declared_under(clock_index: int) -> tuple[Path, ExperimentRun]:
        preparation = prepare_experiment(
            manifest,
            COURBE,
            ExperimentSpec(EXPERIMENT_EFFECT, target, CLOCKS[clock_index], **spec),
            commit=COMMIT,
            tree_modified=False,
            retrieved_at=RETRIEVED_AT,
        )
        registry = factory.mktemp("variante") / "registre"
        return registry, run_experiment(preparation, registry, recorded_at=RECORDED_AT)

    registry, central = declared_under(0)
    run = run_sensitivity(central, registry, recorded_at=SENSITIVITY_RECORDED_AT)
    return Variant(central, run, declared_under(3)[1])


@pytest.fixture(scope="module")
def excluded(tmp_path_factory: pytest.TempPathFactory) -> Variant:
    """L'effet de descente sur la descente (``EXPERIMENT_TARGET``), ``b-2026-06-25``
    exclue de l'admission : sous l'écoulé, deux performances évaluables ; sous les cinq
    ``M θ``, aucune (les deux autres y ont un temps nul)."""
    return _variant(
        tmp_path_factory,
        EXPERIMENT_TARGET,
        admission_exclusions={EXCLUDED_OUTING: ADMISSION_EXCLUSION},
    )


@pytest.fixture(scope="module")
def declared_k(tmp_path_factory: pytest.TempPathFactory) -> Variant:
    """L'effet de descente sur ``q_usage``, ``K`` en préfixe sur ``a``
    (``K_PREFIX``)."""
    return _variant(tmp_path_factory, ExperimentMetric.USAGE, usage_targets=(K_PREFIX,))


# ---------------------------------------------------------------------------
# L'appariement de chaque paire (précision de D13)
# ---------------------------------------------------------------------------


def test_pair_matching_of_each_pair() -> None:
    """Précision de D13 (M4d-3) : la paire ``(Δ, ε)`` est appariée sous son pas et sa
    tolérance, ``r_c`` au défaut, 15 m ; ``(250, 30)`` est l'appariement par défaut, et
    les neuf appariements sont distincts."""
    matchings = [pair_matching(pair) for pair in SENSITIVITY_PAIRS]
    for (step_m, tolerance_m), matching in zip(
        SENSITIVITY_PAIRS, matchings, strict=True
    ):
        assert matching["score_step_m"] == step_m
        assert matching["lateral_tolerance_m"] == tolerance_m
        assert matching["cluster_radius_m"] == 15.0
    assert pair_matching(CENTRAL_PAIR) == ParameterSet(MATCHING_PARAMETER_SPECS)
    assert (
        len(
            {
                tuple(m[n] for n in ("score_step_m", "lateral_tolerance_m"))
                for m in matchings
            }
        )
        == 9
    )


def test_each_pair_is_traced_under_its_own_matching(world: BacktestSensitivity) -> None:
    """Précision de D13 (M4d-3) : chaque sortie déclarée de chaque paire est tracée sous
    **la** paire — son pas ``Δ``, sa tolérance ``ε``, ``r_c = 15`` m —, lus dans
    l'appariement de chaque sortie tracée."""
    seen = 0
    for evaluated in world.run.evaluation.pairs:
        evaluation = evaluated.evaluation
        assert evaluation is not None
        step_m, tolerance_m = evaluated.pair
        for run in evaluation.outings:
            parameters = run.match.parameters
            assert parameters == pair_matching(evaluated.pair)
            assert parameters["score_step_m"] == step_m
            assert parameters["lateral_tolerance_m"] == tolerance_m
            assert parameters["cluster_radius_m"] == 15.0
            seen += 1
    assert seen >= 9 * 3


# ---------------------------------------------------------------------------
# just backtest : références D8, calage et fourchettes de chaque paire
# ---------------------------------------------------------------------------


def _unscaled(evaluation: Any) -> dict[str, dict[ModelKind, OutingScores]]:
    return {
        run.outing.outing_id: {ModelKind.V0_RAW: run.scores, **dict(run.baselines)}
        for run in evaluation.outings
    }


def test_pair_d8_references_are_computed_on_its_observations(
    world: BacktestSensitivity,
) -> None:
    """Précision de D13 (M4d-3) : la référence D8 de chaque parcours, pour une paire,
    sur les observations **de la paire** — en mémoire, figée par la DÉCLARATION de
    sensibilité et publiée par son RÉSULTAT (les mêmes documents) ; pour
    ``(100, 15)``, pas celle de la centrale."""
    log = read_registry(world.registry)
    sensitivity = _declaration(log.events[2]).sensitivity
    result = log.events[3].result
    assert sensitivity is not None
    assert result is not None
    performances = world.central.preparation.performances
    for rank, evaluated in enumerate(world.run.evaluation.pairs):
        expected = repeatability_references(performances, _observations(evaluated))
        assert evaluated.references == expected
        records = tuple(
            RepeatabilityRecord(route_id, content_hash(encode_document(reference)))
            for route_id, reference in expected
        )
        assert sensitivity.pairs[rank].references == records
        assert result.pairs[rank].references == records
    assert _pair(world, OTHER_PAIR).references != world.central.references


def test_pair_calibration_is_computed_on_its_scores(world: BacktestSensitivity) -> None:
    """Précision de D13 (M4d-3) : « le calage de D9.2, horloge par horloge », par paire
    — les scores calés de chaque paire sont ceux que donne le calage sur les scores
    **de la paire** (``calibrate_performances``), pas les facteurs de la centrale
    réappliqués."""
    central = {
        (entry.outing_id, entry.control.model): entry
        for performance in world.central.calibration
        for entry in performance.outings
    }
    differs = False
    for evaluated in world.run.evaluation.pairs:
        evaluation = evaluated.evaluation
        assert evaluation is not None
        expected = {
            (entry.outing_id, entry.control.model): entry
            for performance in calibrate_performances(
                evaluation.preparation.performances, _unscaled(evaluation)
            )
            for entry in performance.outings
        }
        stored = {
            (outcome.outing_id, kind): scores
            for outcome in evaluated.outcomes
            for kind, scores in outcome.scores
            if isinstance(scores, CalibratedOutingScores)
        }
        assert stored == expected
        differs = differs or any(
            [c.calibration for c in stored[key].control.clocks]
            != [c.calibration for c in central[key].control.clocks]
            for key in stored
        )
    assert differs


def test_pair_bands_are_computed_on_its_scores(world: BacktestSensitivity) -> None:
    """Précision de D13 (M4d-3) : pour ``just backtest``, les fourchettes de D11 de
    chaque paire, calculées sur ses scores et son calage — pour ``(100, 15)``, pas
    celles de la centrale."""
    for evaluated in world.run.evaluation.pairs:
        evaluation = evaluated.evaluation
        assert evaluation is not None
        estimation = evaluation.preparation.curve.curve.estimation
        expected = evaluation_bands(
            evaluation.preparation.performances,
            _unscaled(evaluation),
            evaluation.calibration,
            (estimation.date_from, estimation.date_to),
        )
        assert expected
        published = tuple(o.bands for o in evaluated.outcomes if o.bands is not None)
        assert published == expected
    other = _pair(world, OTHER_PAIR)
    assert tuple(o.bands for o in other.outcomes if o.bands is not None) != (
        world.central.bands
    )


# ---------------------------------------------------------------------------
# Une expérience : la géométrie des huit autres paires
# ---------------------------------------------------------------------------


def test_experiment_pairs_are_observed_under_their_own_matching(
    world: BacktestSensitivity, experiment: ExperimentSensitivity
) -> None:
    """Précision de D13 (M4d-3) : pour une expérience aussi, chaque paire est observée
    sous son appariement — sur le même monde, les observations de chaque paire sont
    celles de la même paire de ``just backtest``, et pas toutes celles de
    ``(250, 30)``."""
    backtest = {p.pair: _observations(p) for p in world.run.evaluation.pairs}
    pairs = experiment.run.evaluation.pairs
    assert [p.pair for p in pairs] == list(SENSITIVITY_PAIRS)
    differs = 0
    for evaluated in pairs:
        own = _observations(evaluated)
        assert own
        assert own == backtest[evaluated.pair]
        differs += own != backtest[CENTRAL_PAIR]
    assert differs > 0


def test_experiment_pair_d8_references_are_computed_on_its_observations(
    experiment: ExperimentSensitivity,
) -> None:
    """Précision de D13 (M4d-3) : la référence D8 de chaque parcours, pour chaque paire
    d'une expérience, sur les observations de la paire — pas celle de la centrale."""
    performances = experiment.central.preparation.backtest.performances
    central = experiment.central.preparation.references
    differs = 0
    for evaluated in experiment.run.evaluation.pairs:
        expected = repeatability_references(performances, _observations(evaluated))
        assert evaluated.references == expected
        differs += expected != central
    assert differs > 0


def test_frozen_references_of_each_configuration_come_from_its_pair(
    experiment: ExperimentSensitivity,
) -> None:
    """Précision de D13 (M4d-3) : « les références de D8 de chaque paire, calculées sur
    ses seules observations, sont figées par configuration, sous son horloge » — celles
    de la paire de la configuration, pas de ``(250, 30)``."""
    sensitivity = _declaration(experiment.run.evaluation.declaration_event).sensitivity
    assert sensitivity is not None
    assert sensitivity.frozen is not None
    by_pair = {p.pair: p.references for p in experiment.run.evaluation.pairs}
    differs = 0
    for entry in sensitivity.frozen:
        configuration = entry.configuration
        pair = (configuration.score_step_m, configuration.lateral_tolerance_m)
        expected = frozen_references(by_pair[pair], configuration.clock)
        assert entry.frozen_references == expected
        differs += expected != frozen_references(
            by_pair[CENTRAL_PAIR], configuration.clock
        )
    assert differs > 0


def test_experiment_unscored_outings_keep_the_manifest_motif(
    experiment: ExperimentSensitivity,
) -> None:
    """Précision de D13 (M4d-3) : « une sortie non scorée l'est au motif du manifeste
    (non tracée, ou refusée), le même sous toutes les configurations » — pour une
    expérience, chaque paire porte les sorties non scorées de la centrale, la trace
    refusée du monde à son motif."""
    pairs = experiment.run.evaluation.pairs
    central = _pair(experiment, CENTRAL_PAIR).unscored
    assert any(entry.reason.startswith("trace refusée") for entry in central)
    for evaluated in pairs:
        assert evaluated.unscored == central


# ---------------------------------------------------------------------------
# Une expérience : exclusions, K et décision sous chaque configuration
# ---------------------------------------------------------------------------


def test_admission_exclusions_hold_under_each_configuration(excluded: Variant) -> None:
    """Précision de D13 (M4d-3) : « même candidat et mêmes paramètres, même base, même
    cible, mêmes exclusions » — la performance exclue de l'admission l'est sous chacune
    des dix-neuf configurations."""
    outcome = excluded.run.evaluation.outcome
    for configuration in outcome.configurations:
        (assessment,) = [
            a for a in configuration.assessed if a.outing_ids[0] == EXCLUDED_OUTING
        ]
        assert assessment.motif is NonEvaluable.EXCLUDED


def test_configuration_without_evaluable_performance_has_no_decision(
    excluded: Variant,
) -> None:
    """Précision de D13 (M4d-3) : « sans performance évaluable, la configuration n'a que
    ses évaluations, sans décision » — sous les cinq ``M θ``, et sous elles seules,
    l'expérience à exclusion n'a aucune performance évaluable ; sous ``M θ2``, ses
    évaluations sont celles de la même expérience dédiée, déclarée sous cette horloge
    (un ÉCHEC « non évaluable »)."""
    outcome = excluded.run.evaluation.outcome
    undecided = [c for c in outcome.configurations if c.admission is None]
    assert [c.configuration for c in undecided] == [
        c for c in SENSITIVITY_CONFIGURATIONS if c.clock.kind is ClockKind.MOVING
    ]
    for configuration in undecided:
        assert configuration.assessments is not None
        assert all(a.motif is not None for a in configuration.assessments)
    assert outcome.configurations[outcome.comparator].admission is not None
    dedicated = excluded.dedicated
    assert dedicated.admission is None
    assert dedicated.answer_event.kind is F
    read = outcome.configurations[SENSITIVITY_CONFIGURATIONS.index(MOVING_2)]
    assert read.admission is None
    assert read.assessments == dedicated.assessments


def test_declared_k_holds_under_each_configuration(declared_k: Variant) -> None:
    """Précision de D13 (M4d-3) : « … même ``K`` et mêmes poids » — mutualisé contre
    dédié, l'admission de ``(250, 30)`` sous ``M θ2``, lue dans la sensibilité de
    l'expérience à ``K`` déclaré, est celle de la même expérience dédiée, déclarée sous
    ``M θ2`` ; ses références figées aussi."""
    dedicated = declared_k.dedicated
    assert dedicated.admission is not None
    rank = SENSITIVITY_CONFIGURATIONS.index(MOVING_2)
    read = declared_k.run.evaluation.outcome.configurations[rank]
    assert read.admission == dedicated.admission
    sensitivity = _declaration(declared_k.run.evaluation.declaration_event).sensitivity
    assert sensitivity is not None
    assert sensitivity.frozen is not None
    own = _declaration(dedicated.declaration_event).experiment
    assert own is not None
    assert own.usage_targets == (K_PREFIX,)
    assert sensitivity.frozen[rank].frozen_references == own.frozen_references


# ---------------------------------------------------------------------------
# Une exception dans le calcul d'une paire (précision de D14, décision C9)
# ---------------------------------------------------------------------------


class PanneError(RuntimeError):
    """Une exception synthétique, levée dans le calcul d'une paire."""


@pytest.mark.parametrize(
    "raised",
    [PanneError("panne dans le calcul d'une paire"), KeyboardInterrupt()],
    ids=["exception", "clavier"],
)
def test_error_inside_a_pair_computation_is_a_technical_failure(
    tmp_path: Path,
    mini: MiniCentral,
    monkeypatch: pytest.MonkeyPatch,
    raised: BaseException,
) -> None:
    """Précision de D14 (M4d-3) : une exception, ou une interruption au clavier, entre
    la DÉCLARATION de sensibilité et son RÉSULTAT — ici dans le calcul d'une paire
    (``evaluate_traced``), pas dans un crochet — est un ÉCHEC technique de toute la
    sensibilité, puis ``BacktestError`` ; aucun document n'est écrit. La DÉCLARATION
    est ajoutée avant le calcul de toute prévision, et son empreinte publiée **dès son
    ajout** (précision de D15)."""
    root = copy_registry(mini.registry, tmp_path / "registre")
    documents = {path.name for path in (root / DOCUMENTS_DIR).iterdir()}
    published: list[tuple[RegistryEvent, str]] = []

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise raised

    monkeypatch.setattr(sensitivity_run, "evaluate_traced", broken)
    caught: BacktestError | None = None
    try:
        run_sensitivity(
            mini.central,
            root,
            recorded_at=SENSITIVITY_RECORDED_AT,
            on_declaration=lambda event, seal: published.append((event, seal)),
        )
    except BacktestError as error:
        caught = error
    except KeyboardInterrupt:
        pytest.fail("l'interruption au clavier s'est échappée, sans ÉCHEC")
    except PanneError:
        pytest.fail("l'exception s'est échappée, sans ÉCHEC")
    assert caught is not None
    assert caught.__cause__ is raised
    log = verify_registry(root)
    assert [event.kind for event in log.events] == [D, R, D, F]
    assert log.events[3].failure == Failure(
        FailureKind.TECHNICAL, failure_reason(raised)
    )
    assert {path.name for path in (root / DOCUMENTS_DIR).iterdir()} == documents
    assert published == [(log.events[2], line_hash(log.events[2]))]


# ---------------------------------------------------------------------------
# La vue composée sur un registre à deux centrales (précision de D10.6)
# ---------------------------------------------------------------------------


def test_composed_view_reads_the_sensitivities_of_its_central(
    world: BacktestSensitivity, tmp_path: Path
) -> None:
    """Précision de D10.6 (M4d-3) : la vue lit la dernière DÉCLARATION de sensibilité en
    vigueur **qui qualifie cette centrale** — sur un registre à deux centrales (A : 1,
    sa sensibilité faite ; B : 5), B est « centrale, sensibilité restante » ; après une
    sensibilité de B en ÉCHEC, B est « sensibilité incomplète » et A reste
    « sensibilité faite »."""
    root = copy_registry(world.registry, tmp_path / "registre")
    log = read_registry(root)
    later = SENSITIVITY_RECORDED_AT + timedelta(minutes=10)
    append_declaration(root, _declaration(log.events[0]), recorded_at=later)
    append_result(
        root,
        5,
        load_outcomes(root, log, 2),
        unscored=world.central.unscored,
        references=world.central.references,
        recorded_at=later,
    )
    done = SensitivityQualification(SensitivityStatus.DONE, ())
    assert sensitivity_qualification(root, 1) == done
    assert sensitivity_qualification(root, 5) == (
        SensitivityQualification(SensitivityStatus.REMAINING, ())
    )
    log = read_registry(root)
    declared = _declaration(log.events[2])
    assert declared.sensitivity is not None
    of_b = replace(
        declared.sensitivity,
        central=5,
        central_hash=line_hash(log.events[4]),
        answer=6,
        answer_hash=line_hash(log.events[5]),
    )
    append_declaration(root, replace(declared, sensitivity=of_b), recorded_at=later)
    append_failure(
        root,
        7,
        Failure(FailureKind.TECHNICAL, "PanneError : synthétique"),
        recorded_at=later,
    )
    assert sensitivity_qualification(root, 1) == done
    assert sensitivity_qualification(root, 5) == (
        SensitivityQualification(SensitivityStatus.INCOMPLETE, ())
    )
