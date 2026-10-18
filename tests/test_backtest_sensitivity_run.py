"""L'exécution enregistrée de la sensibilité
(``mountain_perf.backtest.sensitivity_run`` ; ``0010`` D13, D14 et leurs précisions
de M4d-3, D10.6), sur le monde de M4b-5 (``fixtures.backtest_world``) et l'effet de
descente de ``fixtures.effects``.

- La sensibilité de ``just backtest`` (``run_world`` puis ``run_sensitivity``) : ses
  numéros, l'ordre de ses événements, leur format, ``verify_registry`` ; la
  DÉCLARATION recopie la centrale et fige les documents D8 de chaque paire ; le
  comparateur, sans réserve ; la paire ``(250, 30)`` est le RÉSULTAT central, rien n'y
  est réécrit ; les prévisions des huit autres paires sont datées de la DÉCLARATION de
  sensibilité ; ``on_pair``, ``on_declaration``, ``before_result``.
- Les sensibilités de deux expériences, l'une déclarée sous l'écoulé, l'autre sous
  ``M θ2`` : leur comparateur, ses références figées et sa décision (l'admission
  centrale), l'admission refaite sous chaque configuration, leurs réserves ; et,
  **mutualisé contre dédié**, l'admission d'une configuration lue dans la paire
  ``(250, 30)`` égale à celle d'une expérience dédiée déclarée sous son horloge.
- Les refus d'avant la DÉCLARATION (``SensitivityError``, le registre inchangé à
  l'octet) ; l'ÉCHEC technique d'une exception ou d'une interruption au clavier.
- La vue composée de D10.6 dans ses quatre états.

Les sensibilités du monde sont exécutées une fois par session
(``fixtures.sensitivity_world``) ; un test qui écrit au registre en copie un. Aucune
donnée réelle.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from fixtures.backtest_world import RECORDED_AT
from fixtures.effects import Identity
from fixtures.sensitivity_world import (
    EXPERIMENT_CLOCKS,
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
    prepare_mini,
    run_world_experiment,
)
from mountain_perf.backtest import (
    DOCUMENTS_DIR,
    EVENTS_FILE,
    SENSITIVITY_CONFIGURATIONS,
    SENSITIVITY_PAIRS,
    BacktestError,
    BacktestRun,
    ExperimentRun,
    Pair,
    SensitivityError,
    SensitivityEvaluation,
    SensitivityQualification,
    SensitivityStatus,
    append_declaration,
    append_failure,
    append_result,
    comparator_configuration,
    content_hash,
    count_trials,
    decode_document,
    line_hash,
    load_outcomes,
    pair_matching,
    read_registry,
    run_backtest,
    run_sensitivity,
    sensitivity_qualification,
    sensitivity_value,
    usage_clock_scores,
    verify_registry,
)
from mountain_perf.schemas import (
    CLOCKS,
    Availability,
    CalibratedOutingScores,
    ClassMetrics,
    Clock,
    ClockScores,
    Declaration,
    EventKind,
    Failure,
    FailureKind,
    MetricValue,
    ModelKind,
    OutingOutcome,
    OutingScores,
    ParameterSet,
    PerformanceMotif,
    RegimeClass,
    RegistryEvent,
    SensitivityConfiguration,
    SensitivityMetric,
    SensitivityOutcome,
    SupportComponent,
    Unavailability,
)
from mountain_perf.schemas.admission import AdmissionReserve

CENTRAL_PAIR: Pair = (250.0, 30.0)
ELAPSED_COMPARATOR = SensitivityConfiguration(250.0, 30.0, 15.0, CLOCKS[0])
OBSERVED_PAIRS = tuple(pair for pair in SENSITIVITY_PAIRS if pair != CENTRAL_PAIR)
"""Les huit paires observées par la sensibilité, dans l'ordre : toutes sauf
``(250, 30)``, l'exécution centrale."""
D, R, F = EventKind.DECLARATION, EventKind.RESULT, EventKind.FAILURE


# ---------------------------------------------------------------------------
# Aides et fixtures
# ---------------------------------------------------------------------------


def _files(root: Path) -> dict[str, bytes]:
    """Les fichiers du registre et leurs octets."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _documents(root: Path) -> set[str]:
    return {path.name for path in (root / DOCUMENTS_DIR).iterdir()}


def _declaration(event: RegistryEvent) -> Declaration:
    assert event.declaration is not None
    return event.declaration


def _forecast_dates(outcome: OutingOutcome) -> set[object]:
    """Les instants de génération de chaque prévision d'une sortie scorée, tous
    modèles et scénarios."""
    dates: set[object] = set()
    for _, scores in outcome.scores:
        for scenario in (scores.control, scores.usage):
            if scenario is not None:
                dates.add(scenario.forecast.generated_at)
    return dates


def _has_usage(outcome: OutingOutcome) -> bool:
    (v0,) = [s for _, s in outcome.scores if isinstance(s, OutingScores)]
    return v0.usage is not None


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


class PanneError(RuntimeError):
    """Une exception synthétique."""


@pytest.fixture(scope="module")
def mini(tmp_path_factory: pytest.TempPathFactory) -> MiniCentral:
    """La centrale du petit monde, seule dans son registre."""
    return mini_central(tmp_path_factory)


@pytest.fixture(scope="module")
def failed(
    mini: MiniCentral, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, BacktestError, dict[str, bytes]]:
    """Une sensibilité dont ``before_result`` lève : sur une copie du registre de la
    centrale du petit monde ; le registre, l'erreur, et les fichiers d'avant."""
    root = copy_registry(mini.registry, tmp_path_factory.mktemp("echec") / "r")
    before = _files(root)

    def broken(evaluation: SensitivityEvaluation) -> None:
        raise PanneError("panne synthétique")

    with pytest.raises(BacktestError) as caught:
        run_sensitivity(
            mini.central,
            root,
            recorded_at=SENSITIVITY_RECORDED_AT,
            before_result=broken,
        )
    return root, caught.value, before


# ---------------------------------------------------------------------------
# La sensibilité de just backtest
# ---------------------------------------------------------------------------


def test_events_of_the_backtest_sensitivity(world: BacktestSensitivity) -> None:
    """Précision de D14 (M4d-3) : la DÉCLARATION de sensibilité (3) puis son RÉSULTAT
    (4), au format 5, après la centrale (1, 2) ; elle nomme la centrale, son RÉSULTAT
    et les empreintes de leurs lignes ; le registre se vérifie ; le sceau est
    l'empreinte de la dernière ligne ; la sensibilité compte à part."""
    log = verify_registry(world.registry)
    assert [e.kind for e in log.events] == [D, R, D, R]
    assert [e.format_version for e in log.events] == [5, 5, 5, 5]
    central, answer, declared, result = log.events
    assert (world.central.declaration_event, world.central.result_event) == (
        central,
        answer,
    )
    assert world.run.evaluation.declaration_event == declared
    assert world.run.answer_event == result
    assert result.answers == 3
    assert declared.recorded_at == result.recorded_at == SENSITIVITY_RECORDED_AT
    sensitivity = _declaration(declared).sensitivity
    assert sensitivity is not None
    assert (sensitivity.central, sensitivity.answer) == (1, 2)
    assert (sensitivity.central_hash, sensitivity.answer_hash) == (
        line_hash(central),
        line_hash(answer),
    )
    journal = (world.registry / EVENTS_FILE).read_bytes()
    assert journal.startswith((world.central_only / EVENTS_FILE).read_bytes())
    assert world.run.seal == content_hash(journal.split(b"\n")[-2])
    assert world.run.seal == line_hash(result)
    trials = count_trials(log)
    assert (trials.declarations, trials.without_effect, trials.sensitivities) == (
        2,
        1,
        1,
    )


def test_declaration_recopies_the_central(world: BacktestSensitivity) -> None:
    """Précision et exception de D14 (M4d-3) : la DÉCLARATION de sensibilité recopie à
    l'identique la déclaration centrale, déclare les dix-neuf configurations dans leur
    ordre, fige les documents D8 de chaque paire dans l'ordre de première apparition —
    ceux que le RÉSULTAT publie, ceux du RÉSULTAT central pour ``(250, 30)`` — et, sans
    expérience, aucune référence figée."""
    log = read_registry(world.registry)
    declared = _declaration(log.events[2])
    sensitivity = declared.sensitivity
    assert sensitivity is not None
    assert replace(declared, sensitivity=None) == _declaration(log.events[0])
    assert sensitivity.configurations == SENSITIVITY_CONFIGURATIONS
    assert [(p.score_step_m, p.lateral_tolerance_m) for p in sensitivity.pairs] == (
        list(SENSITIVITY_PAIRS)
    )
    assert sensitivity.frozen is None
    result = log.events[3].result
    central = log.events[1].result
    assert result is not None
    assert central is not None
    assert [p.references for p in sensitivity.pairs] == [
        p.references for p in result.pairs
    ]
    assert sensitivity.pairs[SENSITIVITY_PAIRS.index(CENTRAL_PAIR)].references == (
        central.references
    )


def test_comparator_of_just_backtest(world: BacktestSensitivity) -> None:
    """Précision de D13 (M4d-3) : le comparateur de ``just backtest`` est ``(250, 30)``
    sous l'écoulé ; il se compare à lui-même sans composante de support changée ni
    écart non nul ; aucune réserve, aucune expérience."""
    outcome = world.run.evaluation.outcome
    declared = _declaration(world.run.evaluation.declaration_event)
    assert comparator_configuration(declared) == ELAPSED_COMPARATOR
    assert outcome.comparator == SENSITIVITY_CONFIGURATIONS.index(ELAPSED_COMPARATOR)
    assert tuple(c.configuration for c in outcome.configurations) == (
        SENSITIVITY_CONFIGURATIONS
    )
    assert outcome.reserves == ()
    assert not outcome.experiment
    itself = outcome.configurations[outcome.comparator]
    metrics = [m for p in itself.performances for m in p.metrics]
    assert metrics
    assert all(m.support == () for m in metrics)
    assert all(m.difference in (None, 0.0) for m in metrics)
    assert {m.availability for m in metrics} <= {
        Availability.BOTH,
        Availability.NEITHER,
    }


def test_central_pair_is_not_rewritten(world: BacktestSensitivity) -> None:
    """Précision de D14 (M4d-3) : la paire ``(250, 30)`` est le RÉSULTAT central —
    mêmes sorties, mêmes documents (mêmes empreintes), mêmes sorties non scorées, mêmes
    références D8 ; aucun document de la centrale n'est réécrit."""
    log = read_registry(world.registry)
    central, result = log.events[1].result, log.events[3].result
    assert central is not None
    assert result is not None
    pair = result.pairs[SENSITIVITY_PAIRS.index(CENTRAL_PAIR)]
    assert (pair.outings, pair.unscored, pair.references) == (
        central.outings,
        central.unscored,
        central.references,
    )
    before = _files(world.central_only)
    after = _files(world.registry)
    assert {name: after[name] for name in before if name != EVENTS_FILE} == {
        name: data for name, data in before.items() if name != EVENTS_FILE
    }


def test_other_pairs_are_dated_by_the_sensitivity_declaration(
    world: BacktestSensitivity,
) -> None:
    """Précision de D13 (M4d-3) : les prévisions des huit autres paires sont datées de
    la DÉCLARATION de sensibilité, celles de ``(250, 30)`` de la centrale ; chaque
    paire publie les fourchettes de ses sorties avec usage (``just backtest``) ; une
    sortie non scorée l'est au même motif sous toutes les paires."""
    pairs = world.run.evaluation.pairs
    assert [p.pair for p in pairs] == list(SENSITIVITY_PAIRS)
    for pair in pairs:
        expected = RECORDED_AT if pair.pair == CENTRAL_PAIR else SENSITIVITY_RECORDED_AT
        assert pair.outcomes
        for outcome in pair.outcomes:
            assert _forecast_dates(outcome) == {expected}
            assert (outcome.bands is not None) == _has_usage(outcome)
        assert pair.unscored == world.central.unscored
        assert pair.evaluation is not None


def test_callbacks_of_the_sensitivity(world: BacktestSensitivity) -> None:
    """``run_sensitivity`` (M4d-3) : ``on_pair`` après chacune des huit paires
    observées, dans l'ordre, sans ``(250, 30)`` ; ``on_declaration`` avec la
    DÉCLARATION de sensibilité et l'empreinte de sa ligne ; ``before_result`` avant le
    RÉSULTAT (trois événements au registre), avec le calcul rendu."""
    log = read_registry(world.registry)
    assert world.pairs_seen == OBSERVED_PAIRS
    assert world.declared_seen == (log.events[2], line_hash(log.events[2]))
    assert world.events_before_result == 3
    assert world.evaluation_before_result is world.run.evaluation


# ---------------------------------------------------------------------------
# Les sensibilités de deux expériences
# ---------------------------------------------------------------------------


def _comparator_of(experiment: ExperimentSensitivity) -> SensitivityConfiguration:
    declared = _declaration(experiment.central.declaration_event)
    assert declared.experiment is not None
    return SensitivityConfiguration(250.0, 30.0, 15.0, declared.experiment.clock)


def test_events_of_an_experiment_sensitivity(
    experiment: ExperimentSensitivity,
) -> None:
    """Précisions de D13 et D14 (M4d-3) : la sensibilité d'une expérience (3, 4)
    qualifie son RÉSULTAT central (2) ; le registre se vérifie ; la paire ``(250, 30)``
    est le RÉSULTAT central ; les autres paires sont datées de la DÉCLARATION de
    sensibilité, sans fourchettes ; la sensibilité ne compte pas comme essai de
    l'effet."""
    log = verify_registry(experiment.registry)
    assert [e.kind for e in log.events] == [D, R, D, R]
    assert [e.format_version for e in log.events] == [5, 5, 5, 5]
    assert experiment.central.answer_event == log.events[1]
    assert experiment.run.answer_event == log.events[3]
    sensitivity = _declaration(log.events[2]).sensitivity
    assert sensitivity is not None
    assert (sensitivity.central, sensitivity.answer) == (1, 2)
    central, result = log.events[1].result, log.events[3].result
    assert central is not None
    assert result is not None
    pair = result.pairs[SENSITIVITY_PAIRS.index(CENTRAL_PAIR)]
    assert (pair.outings, pair.unscored, pair.references) == (
        central.outings,
        central.unscored,
        central.references,
    )
    for evaluated in experiment.run.evaluation.pairs:
        expected = (
            RECORDED_AT if evaluated.pair == CENTRAL_PAIR else SENSITIVITY_RECORDED_AT
        )
        assert evaluated.evaluation is None
        for outcome in evaluated.outcomes:
            assert _forecast_dates(outcome) == {expected}
            assert outcome.bands is None
    trials = count_trials(log)
    assert (trials.declarations, trials.without_effect, trials.sensitivities) == (
        2,
        0,
        1,
    )
    assert [t.count for t in trials.by_experiment] == [1]


def test_comparator_of_an_experiment(experiment: ExperimentSensitivity) -> None:
    """Précision de D13 (M4d-3) : le comparateur d'une expérience est ``(250, 30)``
    sous son horloge déclarée ; ses références figées sont celles de l'expérience
    centrale, sa décision est l'admission centrale ; chaque configuration fige les
    siennes, sous son horloge, dans l'ordre des configurations."""
    declared = _declaration(experiment.run.evaluation.declaration_event)
    assert declared.experiment is not None
    sensitivity = declared.sensitivity
    assert sensitivity is not None
    assert sensitivity.frozen is not None
    comparator = _comparator_of(experiment)
    assert comparator_configuration(declared) == comparator
    outcome = experiment.run.evaluation.outcome
    rank = SENSITIVITY_CONFIGURATIONS.index(comparator)
    assert outcome.comparator == rank
    assert outcome.experiment
    assert outcome.configurations[rank].admission == experiment.central.admission
    assert [e.configuration for e in sensitivity.frozen] == list(
        SENSITIVITY_CONFIGURATIONS
    )
    for entry in sensitivity.frozen:
        assert entry.frozen_references
        assert {r.clock for r in entry.frozen_references} == {entry.configuration.clock}
    assert sensitivity.frozen[rank].frozen_references == (
        declared.experiment.frozen_references
    )


def test_admission_is_redone_under_each_configuration(
    experiment: ExperimentSensitivity,
) -> None:
    """Précision de D13 (M4d-3) : l'admission est refaite sous chaque configuration —
    sous son horloge, pour la cible déclarée —, jamais recopiée ; sans performance
    évaluable, la configuration n'a que ses évaluations ; le verdict de la centrale
    reste celui du comparateur."""
    outcome = experiment.run.evaluation.outcome
    decided = 0
    for configuration in outcome.configurations:
        admission = configuration.admission
        if admission is None:
            assert configuration.assessments is not None
            continue
        decided += 1
        assert admission.clock == configuration.configuration.clock
        assert admission.target is EXPERIMENT_TARGET
    central = experiment.central.admission
    assert central is not None
    assert decided >= 2
    assert any(
        c.admission is not None and c.admission.clock != central.clock
        for c in outcome.configurations
    )
    assert outcome.configurations[outcome.comparator].verdict is central.verdict


def test_admission_reads_the_scores_of_its_pair(
    experiment: ExperimentSensitivity,
) -> None:
    """Précision de D13 (M4d-3 ; D13-D) : l'admission d'une configuration est refaite
    sur les scores de **sa** paire — la base ``(0)`` et le candidat ``(1)`` de chaque
    performance évaluée sont ``|E_R|`` de la descente de ses scores calés dans la paire
    de la configuration, sous son horloge ; sur le monde, une configuration au moins
    n'a pas les valeurs du comparateur."""
    outcome = experiment.run.evaluation.outcome
    by_pair = {pair.pair: pair for pair in experiment.run.evaluation.pairs}
    comparator = outcome.configurations[outcome.comparator].admission
    assert comparator is not None
    reference = [(a.base, a.candidate) for a in comparator.performances]
    checked = 0
    differs = False
    for configuration in outcome.configurations:
        admission = configuration.admission
        if admission is None:
            continue
        setting = configuration.configuration
        pair = by_pair[(setting.score_step_m, setting.lateral_tolerance_m)]
        outings = {o.outing_id: dict(o.scores) for o in pair.outcomes}
        for assessment in admission.performances:
            for kind, value in (
                (ModelKind.V0_RECALIBRATED, assessment.base),
                (ModelKind.CANDIDATE, assessment.candidate),
            ):
                if value is None or value.value is None:
                    continue
                scores = outings[assessment.outing_ids[0]][kind]
                assert isinstance(scores, CalibratedOutingScores)
                own = sensitivity_value(
                    usage_clock_scores(scores, setting.clock),
                    SensitivityMetric.DESCENT_LEVEL,
                )
                assert own.value is not None
                assert value.value == abs(own.value)
                assert value.count == own.count
                checked += 1
        values = [(a.base, a.candidate) for a in admission.performances]
        differs = differs or values != reference
    assert checked > 0
    assert differs


def test_reserves_of_an_experiment(experiment: ExperimentSensitivity) -> None:
    """Précisions de D13 et D10.6 (M4d-3) : les réserves de la sensibilité d'une
    expérience, chacune avec les rangs des configurations qui la portent, sans le
    comparateur ; la vue composée les rend, sans rien écrire."""
    outcome = experiment.run.evaluation.outcome
    assert outcome.reserves
    for entry in outcome.reserves:
        assert outcome.comparator not in entry.configurations or (
            entry.reserve.value == "sensitivity_sign_unverifiable"
        )
    before = _files(experiment.registry)
    assert sensitivity_qualification(experiment.registry, 1) == (
        SensitivityQualification(SensitivityStatus.RESERVED, outcome.reserves)
    )
    assert _files(experiment.registry) == before


def test_mutualised_equals_dedicated(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Précision de D13 (M4d-3), mutualisé contre dédié : sur le même monde, pour le
    même effet et la même cible, l'admission d'une configuration lue dans l'exécution
    ``(250, 30)`` sous une horloge est celle d'une expérience dédiée déclarée sous
    cette horloge — de ``M θ2`` lue dans l'expérience de l'écoulé, et de l'écoulé lue
    dans celle de ``M θ2`` ; leurs références figées aussi."""
    elapsed = experiment_sensitivity(tmp_path_factory, "ecoule")
    moving = experiment_sensitivity(tmp_path_factory, "mouvement")
    for mutualised, dedicated in ((elapsed, moving), (moving, elapsed)):
        configuration = _comparator_of(dedicated)
        rank = SENSITIVITY_CONFIGURATIONS.index(configuration)
        read = mutualised.run.evaluation.outcome.configurations[rank]
        assert dedicated.central.admission is not None
        assert read.admission == dedicated.central.admission
        sensitivity = _declaration(mutualised.run.evaluation.declaration_event)
        assert sensitivity.sensitivity is not None
        assert sensitivity.sensitivity.frozen is not None
        frozen = sensitivity.sensitivity.frozen[rank].frozen_references
        own = _declaration(dedicated.central.declaration_event).experiment
        assert own is not None
        assert frozen == own.frozen_references


# ---------------------------------------------------------------------------
# Les valeurs comparées : chaque configuration lue dans sa paire, sous son horloge
# ---------------------------------------------------------------------------


REGIMES: dict[SensitivityMetric, tuple[RegimeClass, bool]] = {
    SensitivityMetric.ASCENT_LEVEL: (RegimeClass.ASCENT, True),
    SensitivityMetric.FLAT_LEVEL: (RegimeClass.FLAT, True),
    SensitivityMetric.DESCENT_LEVEL: (RegimeClass.DESCENT, True),
    SensitivityMetric.ASCENT_DISPERSION: (RegimeClass.ASCENT, False),
    SensitivityMetric.FLAT_DISPERSION: (RegimeClass.FLAT, False),
    SensitivityMetric.DESCENT_DISPERSION: (RegimeClass.DESCENT, False),
}
"""La classe de chaque métrique de régime, et si c'est son niveau ``E_R`` (sinon sa
dispersion ``D_R``)."""
INSUFFICIENT = MetricValue(None, Unavailability.INSUFFICIENT_SUPPORT, 0)


def _clock_scores(
    scores: OutingScores | CalibratedOutingScores, clock: Clock
) -> ClockScores | MetricValue:
    """Les scores d'usage d'un modèle sous ``clock`` ; pour un modèle calé sans calage
    sous l'horloge, son statut, d'effectif nul (précision de D13, M4d-3)."""
    index = CLOCKS.index(clock)
    if isinstance(scores, OutingScores):
        assert scores.usage is not None
        return scores.usage.clocks[index]
    assert scores.usage is not None
    entry = scores.usage.clocks[index]
    if entry.scores is None:
        return MetricValue(None, entry.calibration.unavailability, 0)
    return entry.scores


def _value_of(
    scores: OutingScores | CalibratedOutingScores,
    clock: Clock,
    metric: SensitivityMetric,
) -> MetricValue:
    """La valeur d'une métrique sous ``clock``, lue dans les scores tels quels
    (précision de D13, M4d-3) : ``L``, ``E_R`` et ``D_R`` de sa classe, ``max |C_k|``
    et ``q_usage`` — ``support insuffisant``, d'effectif nul, sans erreur aux passages
    ou sans cible d'usage."""
    found = _clock_scores(scores, clock)
    if isinstance(found, MetricValue):
        return found
    if metric is SensitivityMetric.LEVEL:
        return found.support.log_ratio
    if metric in REGIMES:
        regime, level = REGIMES[metric]
        (classes,) = [c for c in found.support.classes if c.regime_class is regime]
        assert isinstance(classes, ClassMetrics)
        return classes.log_ratio if level else classes.dispersion
    if metric is SensitivityMetric.MAX_ABS_PASSAGE_ERROR:
        errors = found.passage_errors
        return INSUFFICIENT if errors is None else errors.max_abs_error_s
    target = found.usage_target
    return INSUFFICIENT if target is None else target.q_usage


def _level_support(
    theirs: OutingScores | CalibratedOutingScores,
    their_clock: Clock,
    mine: OutingScores | CalibratedOutingScores,
    my_clock: Clock,
) -> tuple[SupportComponent, ...]:
    """Les composantes du support de ``L`` qui changent (précision de D13, M4d-3), dans
    l'ordre : les segments admis (début et fin effectifs, classe), les temps nuls sous
    l'horloge de chaque côté, et, pour un modèle calé, sa population de calage en
    usage sous l'horloge (``C_j^eff`` et ses retraits)."""

    def segments(scores: OutingScores | CalibratedOutingScores) -> object:
        return [
            (s.start_m, s.end_m, s.regime_class) for s in scores.observation.segments
        ]

    def zeros(scores: OutingScores | CalibratedOutingScores, clock: Clock) -> object:
        index = CLOCKS.index(clock)
        return [
            (s.start_m, s.end_m)
            for s in scores.observation.segments
            if s.times_s[index] == 0.0
        ]

    def population(scores: CalibratedOutingScores, clock: Clock) -> object:
        assert scores.usage is not None
        calibration = scores.usage.clocks[CLOCKS.index(clock)].calibration
        return (calibration.population, calibration.withdrawals)

    changed: list[SupportComponent] = []
    if segments(theirs) != segments(mine):
        changed.append(SupportComponent.SEGMENTS)
    if zeros(theirs, their_clock) != zeros(mine, my_clock):
        changed.append(SupportComponent.ZERO_TIMES)
    if (
        isinstance(theirs, CalibratedOutingScores)
        and isinstance(mine, CalibratedOutingScores)
        and population(theirs, their_clock) != population(mine, my_clock)
    ):
        changed.append(SupportComponent.POPULATION)
    return tuple(changed)


def _sensitivity(
    factory: pytest.TempPathFactory, source: str
) -> tuple[SensitivityEvaluation, Declaration]:
    """Le calcul d'une sensibilité du monde : ``backtest``, ou une expérience."""
    if source == "backtest":
        run = backtest_sensitivity(factory).run
    else:
        run = experiment_sensitivity(factory, source).run
    return run.evaluation, _declaration(run.evaluation.declaration_event)


@pytest.mark.parametrize(
    ("source", "rank"),
    [
        ("backtest", 0),
        ("backtest", 8),
        ("backtest", 9),
        ("backtest", 14),
        ("mouvement", 0),
        ("mouvement", 16),
    ],
    ids=[
        "backtest-100-15",
        "backtest-500-45",
        "backtest-M1",
        "backtest-MU1",
        "M2-100-15",
        "M2-MU2",
    ],
)
def test_compared_values_are_read_in_each_pair(
    tmp_path_factory: pytest.TempPathFactory, source: str, rank: int
) -> None:
    """Précision de D13 (M4d-3) : chaque performance porte son motif, dans l'ordre —
    jour de plusieurs sorties, première sortie non scorée, sans référence — ou, modèle
    par modèle et métrique par métrique, la valeur sous la configuration (les scores de
    sa paire, sous son horloge) et celle du comparateur (la paire ``(250, 30)``, sous
    son horloge), la disponibilité, l'écart ``valeur − comparateur`` au bit, et pour
    ``L`` les composantes de support changées."""
    evaluation, declared = _sensitivity(tmp_path_factory, source)
    outcome = evaluation.outcome
    configuration = outcome.configurations[rank]
    spec = configuration.configuration
    their_clock = outcome.configurations[outcome.comparator].configuration.clock
    by_pair = {p.pair: {o.outing_id: o for o in p.outcomes} for p in evaluation.pairs}
    mine = by_pair[(spec.score_step_m, spec.lateral_tolerance_m)]
    theirs = by_pair[CENTRAL_PAIR]
    compared = 0
    for comparison, entry in zip(
        configuration.performances, declared.performances, strict=True
    ):
        first = entry.performance.outings[0]
        assert (comparison.civil_date, comparison.outing_id) == (
            entry.performance.civil_date,
            first.outing_id,
        )
        motif = (
            PerformanceMotif.MULTI_OUTING
            if entry.performance.is_multi_outing
            else PerformanceMotif.NOT_SCORED
            if first.outing_id not in mine
            else PerformanceMotif.NO_REFERENCE
            if first.reference is None
            else None
        )
        assert comparison.motif is motif
        if motif is not None:
            continue
        my_scores = dict(mine[first.outing_id].scores)
        their_scores = dict(theirs[first.outing_id].scores)
        assert comparison.models == tuple(
            kind for kind, _ in mine[first.outing_id].scores
        )
        for metric in comparison.metrics:
            value = _value_of(my_scores[metric.model], spec.clock, metric.metric)
            reference = _value_of(
                their_scores[metric.model], their_clock, metric.metric
            )
            assert (metric.value, metric.comparator) == (value, reference)
            if reference.available:
                expected = Availability.BOTH if value.available else Availability.LOST
            else:
                expected = (
                    Availability.GAINED if value.available else Availability.NEITHER
                )
            assert metric.availability is expected
            if value.value is None or reference.value is None:
                assert metric.difference is None
            else:
                assert metric.difference == value.value - reference.value
            if metric.metric is SensitivityMetric.LEVEL:
                assert metric.support == _level_support(
                    their_scores[metric.model],
                    their_clock,
                    my_scores[metric.model],
                    spec.clock,
                )
            compared += 1
    assert compared > 0


# ---------------------------------------------------------------------------
# Les refus d'avant la DÉCLARATION
# ---------------------------------------------------------------------------


def _refused(central: BacktestRun | ExperimentRun, root: Path, message: str) -> None:
    """``run_sensitivity`` refuse la centrale par ``message`` (une expression
    rationnelle) ; le registre reste à l'octet."""
    before = _files(root)
    with pytest.raises(SensitivityError, match=message):
        run_sensitivity(central, root, recorded_at=SENSITIVITY_RECORDED_AT)
    assert _files(root) == before


def test_central_answered_by_a_failure_is_refused(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Précision de D13 (M4d-3) : une centrale répondue par un ÉCHEC n'a rien à
    qualifier — refusée avant tout écrit (l'expérience de l'effet identité, ses
    performances évaluables exclues de l'admission : un ÉCHEC « non évaluable »)."""
    excluded = ("a-2026-06-14", "a-2026-06-27", "b-2026-06-12", "b-2026-06-25")
    root = tmp_path / "registre"
    central = run_world_experiment(
        experiment_manifest(tmp_path_factory),
        root,
        CLOCKS[0],
        effect=Identity(),
        exclusions=dict.fromkeys(excluded, "exclusion synthétique"),
    )
    assert central.answer_event.kind is F
    _refused(
        central,
        root,
        "la centrale a reçu un ÉCHEC : une sensibilité qualifie un RÉSULTAT \\(D13\\)",
    )


@pytest.mark.parametrize(
    "matching",
    [
        pair_matching((100.0, 15.0)),
        ParameterSet(pair_matching(CENTRAL_PAIR).specs, {"cluster_radius_m": 20.0}),
    ],
    ids=["100-15", "rayon-20"],
)
def test_central_matched_elsewhere_is_refused(
    tmp_path: Path, mini: MiniCentral, matching: ParameterSet
) -> None:
    """Précision de D13 (M4d-3) : une centrale appariée hors de ``(250, 30)``,
    ``r_c = 15`` m, n'a pas de comparateur parmi les dix-neuf — une centrale de ``just
    backtest`` (petit monde) dont la déclaration porte un autre appariement est refusée
    avant tout écrit."""
    preparation = prepare_mini(mini.manifest)
    preparation = replace(
        preparation, declaration=replace(preparation.declaration, matching=matching)
    )
    root = tmp_path / "registre"
    central = run_backtest(preparation, root, recorded_at=RECORDED_AT)
    assert _declaration(central.declaration_event).matching == matching
    _refused(
        central,
        root,
        "la centrale n'est pas appariée à \\(250, 30\\), r_c 15 m : son comparateur "
        "n'est pas une des dix-neuf configurations \\(D13\\)",
    )


def test_events_that_are_not_those_of_the_registry_are_refused(
    tmp_path: Path, world: BacktestSensitivity, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Décision C1 (M4d-3) : la sensibilité qualifie la centrale que le même processus
    vient d'écrire — dans un registre vide, ou dans un registre dont l'événement 1 est
    une autre DÉCLARATION, elle est refusée avant tout écrit."""
    empty = tmp_path / "vide"
    empty.mkdir()
    message = "l'événement 1 de la centrale n'est pas celui du registre"
    _refused(world.central, empty, message)
    other = copy_registry(
        experiment_sensitivity(tmp_path_factory, "ecoule").registry,
        tmp_path / "autre",
    )
    _refused(world.central, other, message)


def test_corrected_central_is_refused(tmp_path: Path, mini: MiniCentral) -> None:
    """Précision de D13 (M4d-3) : une sensibilité qualifie une DÉCLARATION centrale et
    un RÉSULTAT en vigueur — une centrale corrigée, ou dont le RÉSULTAT l'est, est
    refusée avant tout écrit."""
    message = (
        "la centrale n'est pas en vigueur au registre \\(corrigée, ou sa réponse "
        "l'est\\)"
    )
    root = copy_registry(mini.registry, tmp_path / "centrale")
    append_declaration(
        root,
        _declaration(mini.central.declaration_event),
        recorded_at=SENSITIVITY_RECORDED_AT,
        corrects=1,
        correction_reason="correction synthétique",
    )
    _refused(mini.central, root, message)
    root = copy_registry(mini.registry, tmp_path / "reponse")
    log = read_registry(root)
    append_result(
        root,
        1,
        load_outcomes(root, log, 2),
        unscored=mini.central.unscored,
        references=mini.central.references,
        recorded_at=SENSITIVITY_RECORDED_AT,
        corrects=2,
        correction_reason="correction synthétique",
    )
    _refused(mini.central, root, message)


# ---------------------------------------------------------------------------
# L'ÉCHEC technique ; l'interruption avant la DÉCLARATION
# ---------------------------------------------------------------------------


def test_exception_in_before_result_is_a_technical_failure(
    failed: tuple[Path, BacktestError, dict[str, bytes]],
) -> None:
    """Précision de D14 (M4d-3) : une exception entre la DÉCLARATION de sensibilité et
    son RÉSULTAT est un ÉCHEC technique de toute la sensibilité, au motif sans chemin,
    puis ``BacktestError``, qui publie l'empreinte de sa ligne ; aucune paire n'est
    gardée à part (aucun document écrit) ; la sensibilité compte à part."""
    root, error, before = failed
    log = verify_registry(root)
    assert [e.kind for e in log.events] == [D, R, D, F]
    failure = log.events[3].failure
    assert failure is not None
    assert failure == Failure(FailureKind.TECHNICAL, "PanneError : panne synthétique")
    assert log.events[3].answers == 3
    assert str(error) == (
        "échec de la sensibilité, ÉCHEC enregistré (événement 4 ; dernière ligne "
        f"sha256 {line_hash(log.events[3])}) : PanneError : panne synthétique"
    )
    assert isinstance(error.__cause__, PanneError)
    assert _documents(root) == {
        Path(name).name for name in before if name.startswith(DOCUMENTS_DIR)
    }
    assert (root / EVENTS_FILE).read_bytes().startswith(before[EVENTS_FILE])
    assert count_trials(log).sensitivities == 1


def test_keyboard_interrupt_after_the_declaration(
    tmp_path: Path, mini: MiniCentral
) -> None:
    """Précision de D14 (M4d-3) : une interruption au clavier après la DÉCLARATION de
    sensibilité (dans ``on_declaration``, petit monde) est un ÉCHEC technique au motif
    ``KeyboardInterrupt``, puis ``BacktestError`` ; aucune paire n'est gardée."""
    root = copy_registry(mini.registry, tmp_path / "registre")
    documents = _documents(root)

    def interrupt(event: RegistryEvent, seal: str) -> None:
        raise KeyboardInterrupt

    with pytest.raises(BacktestError) as caught:
        run_sensitivity(
            mini.central,
            root,
            recorded_at=SENSITIVITY_RECORDED_AT,
            on_declaration=interrupt,
        )
    assert isinstance(caught.value.__cause__, KeyboardInterrupt)
    log = verify_registry(root)
    assert [e.kind for e in log.events] == [D, R, D, F]
    assert log.events[3].failure == Failure(FailureKind.TECHNICAL, "KeyboardInterrupt")
    assert _documents(root) == documents


def test_file_error_is_a_failure_without_path(
    tmp_path: Path, mini: MiniCentral
) -> None:
    """Précision de D14 (M4d-3) : l'ÉCHEC technique d'une erreur de fichier entre la
    DÉCLARATION de sensibilité et son RÉSULTAT porte un motif sans chemin — son type et
    son numéro —, au registre comme dans le message."""
    root = copy_registry(mini.registry, tmp_path / "registre")
    secret = tmp_path / "secret" / "fichier.json"

    def missing(evaluation: SensitivityEvaluation) -> None:
        raise FileNotFoundError(2, "fichier absent", str(secret))

    with pytest.raises(BacktestError) as caught:
        run_sensitivity(
            mini.central,
            root,
            recorded_at=SENSITIVITY_RECORDED_AT,
            before_result=missing,
        )
    log = read_registry(root)
    assert log.events[-1].failure == Failure(
        FailureKind.TECHNICAL, "FileNotFoundError (errno 2)"
    )
    assert str(tmp_path) not in str(caught.value)
    assert str(tmp_path).encode() not in (root / EVENTS_FILE).read_bytes()


def test_keyboard_interrupt_before_the_declaration_writes_nothing(
    tmp_path: Path, mini: MiniCentral
) -> None:
    """``run_sensitivity`` (M4d-3) : les paires sont observées avant la DÉCLARATION —
    une interruption au clavier pendant l'observation remonte telle quelle et n'écrit
    rien."""
    root = copy_registry(mini.registry, tmp_path / "registre")
    before = _files(root)

    def interrupt(pair: Pair) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_sensitivity(
            mini.central, root, recorded_at=SENSITIVITY_RECORDED_AT, on_pair=interrupt
        )
    assert _files(root) == before


# ---------------------------------------------------------------------------
# La vue composée (D10.6)
# ---------------------------------------------------------------------------


REMAINING = SensitivityQualification(SensitivityStatus.REMAINING, ())
INCOMPLETE = SensitivityQualification(SensitivityStatus.INCOMPLETE, ())
DONE = SensitivityQualification(SensitivityStatus.DONE, ())


def test_composed_view_remaining(world: BacktestSensitivity) -> None:
    """Précision de D10.6 (M4d-3) : sans sensibilité déclarée, « centrale, sensibilité
    restante »."""
    assert sensitivity_qualification(world.central_only, 1) == REMAINING


def test_composed_view_incomplete(
    failed: tuple[Path, BacktestError, dict[str, bytes]],
    world: BacktestSensitivity,
    tmp_path: Path,
) -> None:
    """Précision de D10.6 (M4d-3) : une sensibilité déclarée sans RÉSULTAT — un ÉCHEC,
    ou un processus interrompu (la DÉCLARATION sans réponse) — : « sensibilité
    incomplète »."""
    assert sensitivity_qualification(failed[0], 1) == INCOMPLETE
    root = copy_registry(world.registry, tmp_path / "registre")
    lines = (root / EVENTS_FILE).read_bytes().split(b"\n")[:3]
    (root / EVENTS_FILE).write_bytes(b"".join(line + b"\n" for line in lines))
    assert sensitivity_qualification(root, 1) == INCOMPLETE


def test_composed_view_done(world: BacktestSensitivity) -> None:
    """Précisions de D10.6 et D13 (M4d-3) : la sensibilité de ``just backtest`` ne
    porte aucune réserve — « sensibilité faite » ; la vue se calcule à la lecture,
    rien n'est écrit."""
    before = _files(world.registry)
    assert sensitivity_qualification(world.registry, 1) == DONE
    assert _files(world.registry) == before


def test_composed_view_reserves(experiment: ExperimentSensitivity) -> None:
    """Précision de D10.6 (M4d-3) : un RÉSULTAT dont le document porte des réserves —
    la vue rend ces réserves, chacune avec les configurations qui la portent."""
    reserves = experiment.run.evaluation.outcome.reserves
    assert reserves
    assert sensitivity_qualification(experiment.registry, 1) == (
        SensitivityQualification(SensitivityStatus.RESERVED, reserves)
    )


def test_composed_view_reads_the_last_sensitivity_in_force(
    world: BacktestSensitivity, tmp_path: Path
) -> None:
    """Précision de D10.6 (M4d-3) : la vue lit la dernière DÉCLARATION de sensibilité
    en vigueur qui qualifie la centrale — une sensibilité faite, puis une autre en
    ÉCHEC : « sensibilité incomplète »."""
    root = copy_registry(world.registry, tmp_path / "registre")
    declared = _declaration(read_registry(root).events[2])
    append_declaration(root, declared, recorded_at=SENSITIVITY_RECORDED_AT)
    append_failure(
        root,
        5,
        Failure(FailureKind.TECHNICAL, "PanneError : synthétique"),
        recorded_at=SENSITIVITY_RECORDED_AT,
    )
    assert sensitivity_qualification(root, 1) == INCOMPLETE


def test_composed_view_reads_the_sensitivity_in_force(
    world: BacktestSensitivity, tmp_path: Path
) -> None:
    """Précision de D10.6 (M4d-3) : une DÉCLARATION de sensibilité corrigée n'est plus
    en vigueur — sa correction, sans réponse, rend la vue « sensibilité incomplète »,
    bien que la sensibilité corrigée ait son RÉSULTAT."""
    root = copy_registry(world.registry, tmp_path / "registre")
    declared = _declaration(read_registry(root).events[2])
    append_declaration(
        root,
        declared,
        recorded_at=SENSITIVITY_RECORDED_AT,
        corrects=3,
        correction_reason="correction synthétique",
    )
    assert sensitivity_qualification(root, 1) == INCOMPLETE
    assert count_trials(read_registry(root)).sensitivities == 2


def test_composed_view_ignores_a_corrected_sensitivity(
    world: BacktestSensitivity, tmp_path: Path
) -> None:
    """Précision de D10.6 (M4d-3) : une DÉCLARATION de sensibilité corrigée n'est plus
    en vigueur, même avec son RÉSULTAT — corrigée par une déclaration qui n'est pas une
    sensibilité, elle laisse la centrale sans sensibilité : « centrale, sensibilité
    restante »."""
    root = copy_registry(world.registry, tmp_path / "registre")
    central = _declaration(read_registry(root).events[0])
    append_declaration(
        root,
        central,
        recorded_at=SENSITIVITY_RECORDED_AT,
        corrects=3,
        correction_reason="correction synthétique",
    )
    assert sensitivity_qualification(root, 1) == REMAINING


def test_central_admission_is_never_rewritten(
    experiment: ExperimentSensitivity,
) -> None:
    """Précision de D10.6 (M4d-3) : le document d'admission central n'est jamais
    réécrit — sa réserve « centrale, sensibilité restante » y reste, celui de chaque
    configuration la porte aussi ; elle ne se lit remplacée que dans la vue
    composée."""
    central = experiment.central.admission
    assert central is not None
    assert AdmissionReserve.SENSITIVITY_REMAINING in central.reserves
    log = read_registry(experiment.registry)
    result = log.events[1].result
    assert result is not None
    assert result.admission is not None
    data = (
        experiment.registry / DOCUMENTS_DIR / f"{result.admission}.json"
    ).read_bytes()
    assert content_hash(data) == result.admission
    for configuration in experiment.run.evaluation.outcome.configurations:
        if configuration.admission is not None:
            assert (
                AdmissionReserve.SENSITIVITY_REMAINING
                in configuration.admission.reserves
            )
    assert sensitivity_qualification(experiment.registry, 1).status is (
        SensitivityStatus.RESERVED
    )


def test_calibrated_scores_follow_each_pair(world: BacktestSensitivity) -> None:
    """Précision de D13 (M4d-3) : chaque paire porte, pour chaque sortie scorée, v0
    brut puis les modèles calés, calés sur les scores de sa paire — la population de
    calage est celle de la performance, sous chaque horloge."""
    for pair in world.run.evaluation.pairs:
        for outcome in pair.outcomes:
            kinds = [kind for kind, _ in outcome.scores]
            assert len(kinds) == 5
            calibrated = [s for _, s in outcome.scores[1:]]
            assert all(isinstance(s, CalibratedOutingScores) for s in calibrated)
            for scores in calibrated:
                assert isinstance(scores, CalibratedOutingScores)
                if scores.usage is not None:
                    assert [c.calibration.clock for c in scores.usage.clocks] == list(
                        CLOCKS
                    )


def test_document_in_memory_is_the_stored_one(world: BacktestSensitivity) -> None:
    """Le document de sensibilité calculé avant le RÉSULTAT est celui que le RÉSULTAT
    cite."""
    result = read_registry(world.registry).events[3].result
    assert result is not None
    assert result.sensitivity is not None
    data = (world.registry / DOCUMENTS_DIR / f"{result.sensitivity}.json").read_bytes()
    assert decode_document(data, SensitivityOutcome, 5) == world.run.evaluation.outcome
