"""L'expérience d'admission enregistrée (``mountain_perf.backtest.experiment`` ;
``0010`` D10, D14 ; décisions Q2 à Q7 et E3 à E6 de M4c-3, P15, P17), sur le monde de
M4b-5 (``fixtures.backtest_world``) et les effets synthétiques de
``fixtures.effects``.

- ``prepare_experiment`` n'écrit rien ; sa DÉCLARATION : les trois modèles, l'expérience
  (effet, cible, horloge, scénario d'usage, base, candidat, sans date d'analyse), les
  références figées et les empreintes de leurs documents D8, les exclusions de ``just
  backtest`` puis les exclusions d'admission, préfixées, triées.
- Les références D8 et les références figées ne dépendent ni du candidat ni de la cible
  (E6, D10.3) ; ce sont celles que publie ``just backtest`` sur le même monde. Non
  promis : deux préparations du même monde figent des empreintes D8 différentes, par
  le seul instant de lecture.
- ``frozen_references`` (locales, puis l'empruntée à poids égal, sous l'horloge
  déclarée) et ``reference_documents`` (les seuls parcours contributeurs, dans l'ordre
  des références).
- ``run_experiment`` : la DÉCLARATION puis le RÉSULTAT au format 3, vérifié, relu
  égal ; les scores de v0 brut et de v0 recalé, ceux de ``just backtest`` ; les
  prévisions du candidat datées de la DÉCLARATION ; l'effet identité, un gain nul ; un
  effet sans chronologie, une erreur du modèle ; une exception d'un autre type, un
  ÉCHEC technique ; aucune performance évaluable, un ÉCHEC « non évaluable » ; une
  exclusion d'admission, retirée de ``n`` mais gardée dans l'historique.
- Le document d'admission de dix expériences, égal aux valeurs de l'oracle
  indépendant (``fixtures.admission_world``) ; le motif de l'observation avant
  l'erreur du modèle ; le D+/km publié, absent d'un jour de plusieurs sorties ; la
  durée projetée sur la portion déclarée (Q7).
- ``candidate_scores`` : sa précondition ; ``base``, le seul dénominateur de
  ``q_usage``.
- Les refus d'avant la DÉCLARATION (``ExperimentError``, rien d'écrit), dont un ``K``
  hors du ``K`` par défaut d'une sortie qui n'est pas la première de son parcours ; un
  ``K`` qui ne juge pas une sortie sans usage ; ``K`` en préfixe sur la cible
  ``q_usage``.

Repères du monde, cible ``descent_level`` sous l'écoulé (``CLOCKS[0]``) : 12
performances — 5 ``not_calibrated``, 1 jour multi-sorties, 1 sans usage, 2 non
scorées, 3 évaluables (2026-06-14, 06-25, 06-27).

Le manifeste et la courbe sont lus à l'instant de la préparation (``load_manifest`` et
``read_curve`` datent leurs sources de ``datetime.now``, comme ``just backtest`` depuis
M4b-5) : deux préparations du même monde ne diffèrent que par ces ``retrieved_at``, et
les comparaisons entre préparations se font sans eux (``_undated``, ``_redated``). Le
monde est écrit une fois par module ; chaque expérience y est exécutée une fois, à la
demande (``experiments``).
"""

import math
import re
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fixtures.admission_world import (
    ABS_TOLERANCE,
    ADMISSION_EXCLUSION,
    ELAPSED,
    EXPERIMENTS,
    K_PREFIX,
    MOVING_2,
    ORACLE,
    REL_TOLERANCE,
    Experiment,
)
from fixtures.backtest_world import (
    COMMIT,
    COURBE,
    RECORDED_AT,
    RETRIEVED_AT,
    write_world,
)
from fixtures.effects import Broken, Descent, Identity, Raising
from mountain_perf.backtest import (
    ADMISSION_EXCLUSION_PREFIX,
    CALIBRATION_RULE,
    CANDIDATE_MODEL,
    DOCUMENT_SUFFIX,
    DOCUMENTS_DIR,
    EVENTS_FILE,
    FROZEN_METRICS,
    MODELS,
    V0_RAW_MODEL,
    V0_RECALIBRATED_MODEL,
    BacktestError,
    BacktestRun,
    CandidateEffect,
    ExperimentError,
    ExperimentPreparation,
    ExperimentRun,
    ExperimentSpec,
    ObservedOuting,
    candidate_scores,
    content_hash,
    decode_document,
    encode_contract,
    encode_document,
    frozen_references,
    line_hash,
    load_outcomes,
    load_references,
    prepare_backtest,
    prepare_experiment,
    read_registry,
    reference_documents,
    repeatability_reference,
    run_backtest,
    run_experiment,
    v0_scores,
    verify_registry,
)
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS, build_profile, read_gpx
from mountain_perf.model import (
    ENGINE_VERSION,
    PROJECTION_PARAMETER_SPECS,
    CurveReadResult,
    projected_timeline,
    read_curve,
)
from mountain_perf.schemas import (
    Admission,
    CalibratedOutingScores,
    Clock,
    DeclaredEffect,
    DeclaredUsageTarget,
    EventKind,
    Exclusion,
    ExperimentMetric,
    FailureKind,
    FrozenReference,
    MetricValue,
    ModelForecast,
    ModelKind,
    OutingScores,
    ParameterSet,
    ReferenceSource,
    RegimeClass,
    RepeatabilityRecord,
    RepeatabilityReference,
    Scenario,
    TargetMember,
    Unavailability,
)
from mountain_perf.schemas.admission import (
    GAIN_FLOOR,
    AdmissionVerdict,
    FailedCheck,
    FailedCondition,
    NonEvaluable,
    PerformanceAssessment,
    ReviewCause,
    ReviewReason,
    ThresholdSource,
)
from test_backtest_execution import Manifest, outing, world_variant

TARGET = ExperimentMetric.DESCENT_LEVEL
CLOCK = ELAPSED
EVALUABLE = (date(2026, 6, 14), date(2026, 6, 25), date(2026, 6, 27))
"""Les jours évaluables de l'expérience sur ``descent_level`` sous l'écoulé."""

MOTIFS: dict[date, NonEvaluable | None] = {
    date(2026, 6, 3): NonEvaluable.NOT_CALIBRATED,
    date(2026, 6, 4): NonEvaluable.NOT_CALIBRATED,
    date(2026, 6, 6): NonEvaluable.NOT_CALIBRATED,
    date(2026, 6, 8): NonEvaluable.NOT_CALIBRATED,
    date(2026, 6, 10): NonEvaluable.NOT_CALIBRATED,
    date(2026, 6, 12): NonEvaluable.MULTI_OUTING,
    date(2026, 6, 14): None,
    date(2026, 6, 15): NonEvaluable.NO_USAGE,
    date(2026, 6, 16): NonEvaluable.UNSCORED,
    date(2026, 6, 20): NonEvaluable.UNSCORED,
    date(2026, 6, 25): None,
    date(2026, 6, 27): None,
}
"""Le motif de chaque performance déclarée, ``None`` : évaluable (D10.2)."""

ARRIVAL = TargetMember(None, True)
OUTSIDE = TargetMember(5, False)
"""Un élément de ``K`` hors du ``K`` par défaut de ``a`` (trois lieux nommés, rangs 0
à 2, puis l'arrivée)."""

PORTION_M = (1100.0, 3600.0)
"""Une portion déclarée du parcours ``a`` : du col à la source."""

LOCAL_EXPERIMENTS: dict[str, Experiment] = {
    "Raising(ValueError)/descent_level/elapsed": Experiment(
        Raising(ValueError("synthétique")), TARGET, ELAPSED
    ),
    "Raising(ArithmeticError)/descent_level/elapsed": Experiment(
        Raising(ArithmeticError("synthétique")), TARGET, ELAPSED
    ),
    "Identity/descent_level/elapsed/n0": Experiment(
        Identity(),
        TARGET,
        ELAPSED,
        exclusions=("a-2026-06-27", "b-2026-06-25", "b-2026-06-12", "a-2026-06-14"),
    ),
}
"""Les expériences de ce fichier hors de la table de l'oracle : un effet qui lève une
erreur du modèle ; les trois sorties évaluables exclues, et la deuxième sortie du jour
de plusieurs sorties, données hors de l'ordre des identifiants (``n = 0``)."""

_REGIME_FIELDS: dict[ExperimentMetric, tuple[str, RegimeClass]] = {
    ExperimentMetric.ASCENT_LEVEL: ("log_ratios", RegimeClass.ASCENT),
    ExperimentMetric.FLAT_LEVEL: ("log_ratios", RegimeClass.FLAT),
    ExperimentMetric.DESCENT_LEVEL: ("log_ratios", RegimeClass.DESCENT),
    ExperimentMetric.ASCENT_DISPERSION: ("dispersions", RegimeClass.ASCENT),
    ExperimentMetric.FLAT_DISPERSION: ("dispersions", RegimeClass.FLAT),
    ExperimentMetric.DESCENT_DISPERSION: ("dispersions", RegimeClass.DESCENT),
}
"""Le champ de ``ClockReference`` et la classe de chaque métrique de régime (D8.4)."""


# ---------------------------------------------------------------------------
# Aides
# ---------------------------------------------------------------------------


def _prepare(
    manifest: Path,
    effect: CandidateEffect,
    target: ExperimentMetric = TARGET,
    clock: Clock = CLOCK,
    **spec: Any,
) -> ExperimentPreparation:
    """L'expérience préparée sur le monde, sous ``clock`` (l'écoulé par défaut) ;
    ``spec`` complète l'``ExperimentSpec`` (``K``, exclusions d'admission)."""
    return prepare_experiment(
        manifest,
        COURBE,
        ExperimentSpec(effect, target, clock, **spec),
        commit=COMMIT,
        tree_modified=False,
        retrieved_at=RETRIEVED_AT,
    )


def _run(preparation: ExperimentPreparation, root: Path) -> tuple[Path, ExperimentRun]:
    """L'expérience exécutée, registre dans ``root / "registre"``, à
    ``RECORDED_AT``."""
    registry = root / "registre"
    return registry, run_experiment(preparation, registry, recorded_at=RECORDED_AT)


class Experiments:
    """Les expériences du module sur le monde, par nom (``EXPERIMENTS``, puis
    ``LOCAL_EXPERIMENTS``) : chacune exécutée une fois, à la demande, dans son propre
    registre."""

    def __init__(self, manifest: Path, root: Path) -> None:
        self._manifest = manifest
        self._root = root
        self._runs: dict[str, tuple[Path, ExperimentRun]] = {}

    def __call__(self, name: str) -> tuple[Path, ExperimentRun]:
        if name not in self._runs:
            experiment = {**EXPERIMENTS, **LOCAL_EXPERIMENTS}[name]
            preparation = _prepare(
                self._manifest,
                experiment.effect,
                experiment.target,
                experiment.clock,
                usage_targets=experiment.usage_targets,
                admission_exclusions=dict.fromkeys(
                    experiment.exclusions, ADMISSION_EXCLUSION
                ),
            )
            root = self._root / f"experience-{len(self._runs)}"
            root.mkdir()
            self._runs[name] = _run(preparation, root)
        return self._runs[name]


def _files(root: Path) -> dict[str, bytes]:
    """Les fichiers sous ``root`` et leurs octets."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _strip(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            key: None if key == "retrieved_at" else _strip(value)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_strip(value) for value in data]
    return data


def _undated(value: object) -> Any:
    """L'écriture de ``value`` (``encode_contract``), chaque ``retrieved_at`` effacé :
    l'instant de lecture d'un fichier, propre à chaque préparation."""
    return _strip(encode_contract(value))


def _redated(
    references: tuple[tuple[str, RepeatabilityReference], ...],
) -> tuple[tuple[str, RepeatabilityReference], ...]:
    """Les références D8, le fichier de chacune lu à ``RETRIEVED_AT``."""
    return tuple(
        (
            route_id,
            replace(
                reference,
                reference=replace(reference.reference, retrieved_at=RETRIEVED_AT),
            ),
        )
        for route_id, reference in references
    )


def _kinds(registry: Path) -> list[EventKind]:
    return [event.kind for event in read_registry(registry).events]


def _by_day(run: ExperimentRun) -> dict[date, PerformanceAssessment]:
    return {assessment.civil_date: assessment for assessment in run.assessments}


def _close(actual: float | None, expected: float | None) -> bool:
    """Absents ensemble, ou égaux à ``REL_TOLERANCE`` près, ``ABS_TOLERANCE`` près de
    0."""
    if actual is None or expected is None:
        return actual is expected
    return actual == pytest.approx(expected, rel=REL_TOLERANCE, abs=ABS_TOLERANCE)


def _value(
    reference: RepeatabilityReference, metric: ExperimentMetric, clock: Clock = CLOCK
) -> MetricValue:
    """``F`` de ``metric`` sous ``clock`` dans une référence D8 (D8.4) : ``F_|L|``, ou
    le ``F`` de niveau ou de dispersion de la classe."""
    (entry,) = [c for c in reference.clocks if c.clock == clock]
    if metric is ExperimentMetric.LEVEL:
        return entry.level
    name, regime = _REGIME_FIELDS[metric]
    values: tuple[MetricValue, ...] = getattr(entry, name)
    return values[list(RegimeClass).index(regime)]


def _expected_frozen(
    references: tuple[tuple[str, RepeatabilityReference], ...], clock: Clock = CLOCK
) -> tuple[FrozenReference, ...]:
    """Les références figées attendues sous ``clock`` (D10.3 ; P6, P7) : par métrique,
    une locale par parcours, puis l'empruntée si une locale au moins est disponible —
    moyenne à poids égal, ses donneurs, l'effectif la somme de leurs ``m_q``."""
    frozen: list[FrozenReference] = []
    for metric in FROZEN_METRICS:
        values = [(route, _value(ref, metric, clock)) for route, ref in references]
        frozen += [
            FrozenReference(metric, clock, ReferenceSource.LOCAL, route_id, value, ())
            for route_id, value in values
        ]
        available = [
            (route_id, value.value, value.count)
            for route_id, value in values
            if value.value is not None
        ]
        if available:
            mean = math.fsum(v for _, v, _ in available) / len(available)
            frozen.append(
                FrozenReference(
                    metric,
                    clock,
                    ReferenceSource.BORROWED,
                    None,
                    MetricValue(mean, None, sum(count for _, _, count in available)),
                    tuple(route_id for route_id, _, _ in available),
                )
            )
    return tuple(frozen)


# ---------------------------------------------------------------------------
# Le monde et les expériences partagées
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def manifest(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Le monde de M4b-5, écrit une fois."""
    return write_world(tmp_path_factory.mktemp("monde"))


@pytest.fixture(scope="module")
def experiments(
    manifest: Path, tmp_path_factory: pytest.TempPathFactory
) -> Experiments:
    """Les expériences du module, exécutées une fois chacune."""
    return Experiments(manifest, tmp_path_factory.mktemp("experiences"))


@pytest.fixture(scope="module")
def identity(experiments: Experiments) -> tuple[Path, ExperimentRun]:
    """L'effet identité sur ``descent_level``, sous l'écoulé."""
    return experiments("Identity/descent_level/elapsed")


@pytest.fixture(scope="module")
def descent(experiments: Experiments) -> tuple[Path, ExperimentRun]:
    """L'effet de descente sur ``descent_level``, sous l'écoulé."""
    return experiments("Descent/descent_level/elapsed")


@pytest.fixture(scope="module")
def usage(experiments: Experiments) -> tuple[Path, ExperimentRun]:
    """L'effet de descente sur ``q_usage``, au ``K`` par défaut."""
    return experiments("Descent/usage/elapsed")


@pytest.fixture(scope="module")
def usage_k(experiments: Experiments) -> tuple[Path, ExperimentRun]:
    """L'effet de descente sur ``q_usage``, ``K`` en préfixe sur ``a``."""
    return experiments("Descent/usage/elapsed/K_prefixe")


@pytest.fixture(scope="module")
def not_evaluable(experiments: Experiments) -> tuple[Path, ExperimentRun]:
    """L'effet identité, les trois sorties évaluables exclues de l'admission."""
    return experiments("Identity/descent_level/elapsed/n0")


@pytest.fixture(scope="module")
def backtest(
    manifest: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, BacktestRun]:
    """``just backtest`` sur le même monde, au même ``recorded_at``."""
    registry = tmp_path_factory.mktemp("backtest") / "registre"
    preparation = prepare_backtest(
        manifest, COURBE, commit=COMMIT, tree_modified=False, retrieved_at=RETRIEVED_AT
    )
    return registry, run_backtest(preparation, registry, recorded_at=RECORDED_AT)


# ---------------------------------------------------------------------------
# La préparation et la DÉCLARATION (D10.1, D10.3 ; Q3, Q5, E6)
# ---------------------------------------------------------------------------


def test_prepare_experiment_writes_nothing(tmp_path: Path) -> None:
    """Décision Q3 : ``prepare_experiment`` lit, observe et déclare sans rien écrire —
    elle ne reçoit pas de registre, et le dossier du monde est inchangé."""
    manifest = write_world(tmp_path / "monde")
    before = _files(tmp_path)
    preparation = _prepare(manifest, Identity())
    assert _files(tmp_path) == before
    assert [path.name for path in tmp_path.iterdir()] == ["monde"]
    assert preparation.declaration.experiment is not None


def test_declaration_of_the_experiment(identity: tuple[Path, ExperimentRun]) -> None:
    """D10.1, D10.3 ; décisions Q2, Q5 et E6 : la DÉCLARATION est celle de ``just
    backtest``, aux trois modèles près — v0 brut, la base (0) et le candidat (1), calé
    par la règle de v0 — et à l'expérience près : l'effet déclaré depuis l'effet, la
    cible et son horloge, le scénario d'usage, la base v0 recalé, le candidat, sans
    ``K`` ni date d'analyse, les références figées sous l'horloge déclarée et les
    empreintes de leurs documents D8."""
    _, run = identity
    preparation = run.preparation
    declaration = preparation.declaration
    assert declaration.models == (
        V0_RAW_MODEL,
        V0_RECALIBRATED_MODEL,
        CANDIDATE_MODEL,
    )
    assert CANDIDATE_MODEL.kind is ModelKind.CANDIDATE
    assert CANDIDATE_MODEL.engine_version == ENGINE_VERSION
    assert CANDIDATE_MODEL.parameters == ParameterSet(PROJECTION_PARAMETER_SPECS)
    assert CANDIDATE_MODEL.estimation_rule == CALIBRATION_RULE
    experiment = declaration.experiment
    assert experiment is not None
    effect = Identity()
    assert experiment.effect == DeclaredEffect(
        effect.name, effect.description, effect.parameters, None
    )
    assert (experiment.target, experiment.clock) == (TARGET, CLOCK)
    assert experiment.scenario is Scenario.USAGE
    assert experiment.base is ModelKind.V0_RECALIBRATED
    assert experiment.candidate is ModelKind.CANDIDATE
    assert experiment.usage_targets == ()
    assert experiment.analysis_date is None
    frozen = frozen_references(preparation.references, CLOCK)
    assert experiment.frozen_references == frozen
    assert experiment.reference_documents == reference_documents(
        preparation.references, frozen
    )
    assert declaration.exclusions == preparation.backtest.declaration.exclusions
    assert (
        replace(declaration, models=MODELS, experiment=None)
        == preparation.backtest.declaration
    )


def test_admission_exclusions_follow_those_of_just_backtest(
    not_evaluable: tuple[Path, ExperimentRun],
) -> None:
    """P17 : les exclusions déclarées sont celles de ``just backtest``, puis les
    exclusions d'admission, triées par identifiant, leur motif préfixé de
    ``ADMISSION_EXCLUSION_PREFIX``."""
    _, run = not_evaluable
    preparation = run.preparation
    assert ADMISSION_EXCLUSION_PREFIX == "exclusion d'admission : "
    reason = f"exclusion d'admission : {ADMISSION_EXCLUSION}"
    assert preparation.declaration.exclusions == (
        *preparation.backtest.declaration.exclusions,
        Exclusion("a-2026-06-14", reason),
        Exclusion("a-2026-06-27", reason),
        Exclusion("b-2026-06-12", reason),
        Exclusion("b-2026-06-25", reason),
    )


# ---------------------------------------------------------------------------
# Les références figées avant le candidat (E6, D10.3)
# ---------------------------------------------------------------------------


def test_references_are_frozen_before_the_candidate(
    identity: tuple[Path, ExperimentRun],
    descent: tuple[Path, ExperimentRun],
    usage: tuple[Path, ExperimentRun],
) -> None:
    """Décision E6, D10.3 : les références D8 se calculent sur les seules observations,
    avant le candidat — l'effet identité, l'effet de descente et la cible ``q_usage``
    donnent les mêmes références et les mêmes références figées."""
    first = identity[1].preparation
    for other in (descent[1].preparation, usage[1].preparation):
        assert [_undated(r) for _, r in other.references] == [
            _undated(r) for _, r in first.references
        ]
        assert [route for route, _ in other.references] == ["a", "b"]
        ours, theirs = other.declaration.experiment, first.declaration.experiment
        assert ours is not None
        assert theirs is not None
        assert ours.frozen_references == theirs.frozen_references


def test_d8_documents_of_two_preparations_differ_by_the_reading_instant(
    identity: tuple[Path, ExperimentRun], descent: tuple[Path, ExperimentRun]
) -> None:
    """Non promis (E6) : l'égalité des empreintes D8 n'est promise qu'à l'intérieur
    d'une expérience, de la DÉCLARATION au RÉSULTAT. Deux préparations du même monde
    figent des empreintes différentes, par le seul instant de lecture du fichier de
    chaque référence (``retrieved_at``, comme ``just backtest`` depuis M4b-5) : au même
    instant, leurs documents sont les mêmes."""
    first, second = identity[1].preparation, descent[1].preparation
    ours, theirs = first.declaration.experiment, second.declaration.experiment
    assert ours is not None
    assert theirs is not None
    assert ours.reference_documents is not None
    assert theirs.reference_documents is not None
    assert [r.route_id for r in ours.reference_documents] == ["a", "b"]
    assert [r.route_id for r in theirs.reference_documents] == ["a", "b"]
    for mine, other in zip(
        ours.reference_documents, theirs.reference_documents, strict=True
    ):
        assert mine.reference != other.reference
    assert reference_documents(_redated(first.references), ours.frozen_references) == (
        reference_documents(_redated(second.references), theirs.frozen_references)
    )
    for run in (identity[1], descent[1]):
        result = run.answer_event.result
        declared = run.preparation.declaration.experiment
        assert result is not None
        assert declared is not None
        assert result.references == declared.reference_documents


def test_references_are_those_of_just_backtest(
    identity: tuple[Path, ExperimentRun], backtest: tuple[Path, BacktestRun]
) -> None:
    """Décision E6, D8 : les références D8 de l'expérience sont celles que ``just
    backtest`` publie sur le même monde (relues du registre par ``load_references``),
    et leurs références figées les mêmes."""
    registry, _ = backtest
    published = load_references(registry, read_registry(registry), 2)
    preparation = identity[1].preparation
    assert [route for route, _ in published] == [r for r, _ in preparation.references]
    assert [_undated(r) for _, r in published] == [
        _undated(r) for _, r in preparation.references
    ]
    experiment = preparation.declaration.experiment
    assert experiment is not None
    assert frozen_references(published, CLOCK) == experiment.frozen_references


# ---------------------------------------------------------------------------
# frozen_references et reference_documents (D10.3 ; P6, P7 ; E6)
# ---------------------------------------------------------------------------


def test_frozen_metrics() -> None:
    """D10.3, D10.4 : une référence se fige pour chaque métrique sauf ``q_usage``, au
    seuil fixe."""
    assert FROZEN_METRICS == (
        ExperimentMetric.LEVEL,
        ExperimentMetric.ASCENT_LEVEL,
        ExperimentMetric.FLAT_LEVEL,
        ExperimentMetric.DESCENT_LEVEL,
        ExperimentMetric.ASCENT_DISPERSION,
        ExperimentMetric.FLAT_DISPERSION,
        ExperimentMetric.DESCENT_DISPERSION,
    )


def test_frozen_references_of_the_world(identity: tuple[Path, ExperimentRun]) -> None:
    """D10.3 ; P6, P7 : par métrique, la locale de chaque parcours, puis l'empruntée —
    la moyenne **à poids égal** des locales disponibles, ses donneurs, son effectif la
    somme de leurs ``m_q``."""
    references = identity[1].preparation.references
    frozen = frozen_references(references, CLOCK)
    assert frozen == _expected_frozen(references)
    assert len(frozen) == len(FROZEN_METRICS) * 3
    counts = {
        route_id: _value(reference, ExperimentMetric.LEVEL).count
        for route_id, reference in references
    }
    assert counts["a"] != counts["b"]


def test_references_are_frozen_under_the_declared_clock(
    experiments: Experiments,
) -> None:
    """D10.3 : les références se figent sous l'horloge déclarée de la cible — sous le
    temps en mouvement de la convention 2, chacune porte cette horloge, et ses valeurs
    sont celles de la référence D8 sous elle."""
    preparation = experiments("Descent/usage/moving_2")[1].preparation
    experiment = preparation.declaration.experiment
    assert experiment is not None
    assert experiment.clock == MOVING_2
    frozen = experiment.frozen_references
    assert frozen == _expected_frozen(preparation.references, MOVING_2)
    assert frozen == frozen_references(preparation.references, MOVING_2)
    assert {ref.clock for ref in frozen} == {MOVING_2}
    assert frozen != _expected_frozen(preparation.references)


def test_no_borrowed_reference_without_an_available_local(
    identity: tuple[Path, ExperimentRun],
) -> None:
    """D10.3 ; P6 : une locale indisponible est figée avec son motif ; sans aucune
    locale disponible, pas d'empruntée ; une locale indisponible n'est pas donneuse."""
    references = identity[1].preparation.references
    source = references[0][1].reference
    empty = repeatability_reference(source, [])
    alone = frozen_references((("v", empty),), CLOCK)
    assert [ref.source for ref in alone] == [ReferenceSource.LOCAL] * len(
        FROZEN_METRICS
    )
    assert all(ref.value.value is None for ref in alone)
    assert all(ref.value.unavailability is not None for ref in alone)
    mixed = (references[0], ("v", empty))
    frozen = frozen_references(mixed, CLOCK)
    assert frozen == _expected_frozen(mixed)
    borrowed = [ref for ref in frozen if ref.source is ReferenceSource.BORROWED]
    assert borrowed
    assert all(ref.donors == ("a",) for ref in borrowed)


def test_reference_documents_name_the_contributing_routes(
    identity: tuple[Path, ExperimentRun],
) -> None:
    """Décision E6 : l'empreinte du document D8 de chaque parcours dont une référence
    figée vient — locale ou donneur —, seulement ceux-là, dans l'ordre des
    références."""
    references = identity[1].preparation.references
    documents = {
        route_id: content_hash(encode_document(reference))
        for route_id, reference in references
    }
    frozen = frozen_references(references, CLOCK)
    both = (
        RepeatabilityRecord("a", documents["a"]),
        RepeatabilityRecord("b", documents["b"]),
    )
    assert reference_documents(references, frozen) == both
    assert reference_documents(references, tuple(reversed(frozen))) == both
    only_b = tuple(ref for ref in frozen if ref.route_id == "b")
    assert reference_documents(references, only_b) == (both[1],)
    donor_a = FrozenReference(
        ExperimentMetric.LEVEL,
        CLOCK,
        ReferenceSource.BORROWED,
        None,
        MetricValue(0.05, None, 3),
        ("a",),
    )
    assert reference_documents(references, (donor_a,)) == (both[0],)
    assert reference_documents(references, ()) == ()


# ---------------------------------------------------------------------------
# run_experiment : le RÉSULTAT (D14 ; Q2, Q4)
# ---------------------------------------------------------------------------


def test_result_of_the_experiment(identity: tuple[Path, ExperimentRun]) -> None:
    """D14, décision Q4 : la DÉCLARATION puis le RÉSULTAT, au format 4, vérifiés ; le
    RÉSULTAT cite le document d'admission, relu égal ; ses sorties se relisent égales,
    v0 brut, v0 recalé puis le candidat ; ses documents D8 sont ceux que la
    DÉCLARATION a figés ; le sceau est l'empreinte de sa ligne ; les évaluations sont
    celles du document."""
    registry, run = identity
    log = read_registry(registry)
    assert verify_registry(registry) == log
    assert [(e.kind, e.format_version) for e in log.events] == [
        (EventKind.DECLARATION, 5),
        (EventKind.RESULT, 5),
    ]
    assert log.events == (run.declaration_event, run.answer_event)
    assert log.events[0].declaration == run.preparation.declaration
    result = log.events[1].result
    assert result is not None
    assert run.admission is not None
    sha = content_hash(encode_document(run.admission))
    assert result.admission == sha
    data = (registry / DOCUMENTS_DIR / f"{sha}{DOCUMENT_SUFFIX}").read_bytes()
    assert decode_document(data, Admission) == run.admission
    assert load_outcomes(registry, log, 2) == run.outcomes
    assert [outcome.outing_id for outcome in run.outcomes] == list(
        run.preparation.observed
    )
    for outcome in run.outcomes:
        assert [kind for kind, _ in outcome.scores] == [
            ModelKind.V0_RAW,
            ModelKind.V0_RECALIBRATED,
            ModelKind.CANDIDATE,
        ]
    experiment = run.preparation.declaration.experiment
    assert experiment is not None
    assert result.references == experiment.reference_documents
    assert run.seal == line_hash(log.events[1])
    last = (registry / EVENTS_FILE).read_bytes().split(b"\n")[-2]
    assert run.seal == content_hash(last)
    assert run.assessments == run.admission.performances
    assert {a.civil_date: a.motif for a in run.assessments} == MOTIFS


def test_unscored_outings_of_the_result(
    identity: tuple[Path, ExperimentRun], backtest: tuple[Path, BacktestRun]
) -> None:
    """D0, D14 : les sorties déclarées non tracées sont écartées du RÉSULTAT, au motif
    du refus de leur trace par le manifeste, ou « sortie non tracée » — comme ``just
    backtest``."""
    _, run = identity
    result = run.answer_event.result
    assert result is not None
    refused = {e.outing_id: e.reason for e in run.preparation.backtest.manifest.refused}
    assert result.unscored == (
        Exclusion("c-2026-06-16", refused["c-2026-06-16"]),
        Exclusion("a-2026-06-20", "sortie non tracée"),
    )
    assert result.unscored == backtest[1].unscored


def test_scores_are_those_of_just_backtest(
    identity: tuple[Path, ExperimentRun], backtest: tuple[Path, BacktestRun]
) -> None:
    """Décisions Q2 et Q3 : la chaîne refaite depuis le manifeste et la courbe — les
    scores de v0 brut et de v0 recalé de l'expérience sont ceux de ``just backtest``
    sur le même monde, au même ``recorded_at``, la couverture aussi. Seul l'instant de
    lecture des fichiers (``retrieved_at`` des sources des prévisions) diffère, propre
    à chaque préparation ; ``generated_at`` est le même."""
    _, run = identity
    registry, _ = backtest
    published = load_outcomes(registry, read_registry(registry), 2)
    assert [o.outing_id for o in run.outcomes] == [o.outing_id for o in published]
    for ours, theirs in zip(run.outcomes, published, strict=True):
        assert ours.coverage == theirs.coverage
        mine, others = dict(ours.scores), dict(theirs.scores)
        for kind in (ModelKind.V0_RAW, ModelKind.V0_RECALIBRATED):
            assert _undated(mine[kind]) == _undated(others[kind])
            assert mine[kind].control.forecast.generated_at == RECORDED_AT


def test_candidate_forecasts_are_dated_by_the_declaration(
    identity: tuple[Path, ExperimentRun],
) -> None:
    """D14, § 6.5 : les prévisions du candidat sont datées de la DÉCLARATION (le
    ``recorded_at`` de son événement), comme celles de v0 — une projection datée par
    performance et modèle, une seule date par exécution."""
    _, run = identity
    assert run.declaration_event.recorded_at == RECORDED_AT
    assert run.outcomes
    for outcome in run.outcomes:
        candidate = dict(outcome.scores)[ModelKind.CANDIDATE]
        assert isinstance(candidate, CalibratedOutingScores)
        assert candidate.control.forecast.generated_at == RECORDED_AT
        if candidate.usage is not None:
            assert candidate.usage.forecast.generated_at == RECORDED_AT


# ---------------------------------------------------------------------------
# Le document d'admission et l'oracle indépendant (D10.2 à D10.6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(ORACLE))
def test_admission_matches_the_oracle(experiments: Experiments, name: str) -> None:
    """D10.2 à D10.6 ; décisions E1, E2, E5 : le document d'admission publie les
    valeurs de l'oracle indépendant (``fixtures.admission_world``) — ``n``, le verdict,
    ``Ḡ``, ``δ̄``, les succès et les succès exigés, la moyenne contre v0 brut ; par jour
    évaluable, ``G_j``, ``δ_j``, la source de ``F_j`` et l'effort libre de (0) et de
    (1) ; les causes de « à revoir » et les conditions qui échouent, avec leurs
    métriques et leurs jours ; chaque garde-fou (état, ``H̄``, ``η̄``), l'état des
    passages et les réserves. Énumérations, entiers et jours exacts ; nombres à
    ``REL_TOLERANCE`` près, ``ABS_TOLERANCE`` près de 0."""
    _, run = experiments(name)
    expected = ORACLE[name]
    admission = run.admission
    assert admission is not None
    assert (
        admission.evaluable,
        admission.verdict,
        admission.positive,
        admission.required,
    ) == (expected.evaluable, expected.verdict, expected.positive, expected.required)
    assert _close(admission.mean_gain, expected.mean_gain)
    assert _close(admission.mean_threshold, expected.mean_threshold)
    assert _close(admission.mean_raw_gain, expected.mean_raw_gain)
    days = {a.civil_date: a for a in admission.performances if a.motif is None}
    assert list(days) == list(expected.days)
    for day, values in expected.days.items():
        assessment = days[day]
        assert assessment.source is values.source
        assert _close(assessment.gain, values.gain)
        assert _close(assessment.threshold, values.threshold)
        efforts = (assessment.base_effort, assessment.candidate_effort)
        free = [None if effort is None else effort.free for effort in efforts]
        assert _close(free[0], values.base_effort)
        assert _close(free[1], values.candidate_effort)
    assert admission.review == expected.review
    assert admission.failures == expected.failures
    assert [guard.metric for guard in admission.guards] == list(expected.guards)
    for guard in admission.guards:
        values_ = expected.guards[guard.metric]
        assert guard.status is values_.status
        assert _close(guard.mean_harm, values_.mean_harm)
        assert _close(guard.mean_threshold, values_.mean_threshold)
    assert admission.passages.status is expected.passages
    assert admission.reserves == expected.reserves


def test_observation_motif_comes_before_the_model_error(
    experiments: Experiments,
) -> None:
    """Précision de D7.1 (M4b-1) ; arbitrage du coordinateur (M4c-3) : la métrique d'un
    modèle au calage en échec — le candidat sans chronologie, en erreur du modèle —
    prend d'abord le motif de l'observation (temps nul, support insuffisant), sinon
    celui de son calage. Sous ``moving_2``, le dernier segment de ``a`` a un temps nul :
    chaque valeur de garde-fou où (0), calé, porte un motif d'observation le porte aussi
    pour (1) ; ailleurs, (1) est en erreur du modèle."""
    _, run = experiments("Broken/usage/moving_2")
    admission = run.admission
    assert admission is not None
    observation = {Unavailability.ZERO_TIME, Unavailability.INSUFFICIENT_SUPPORT}
    seen: set[Unavailability] = set()
    for guard in admission.guards:
        for value in guard.values:
            base = value.base.unavailability
            if base in observation:
                assert value.candidate.unavailability is base
                seen.add(base)
            else:
                assert value.candidate.unavailability is Unavailability.MODEL_ERROR
    assert Unavailability.ZERO_TIME in seen


def test_dplus_of_a_multi_outing_day_is_absent(
    identity: tuple[Path, ExperimentRun],
) -> None:
    """D2.1, D10.3 ; arbitrage du coordinateur (M4c-3) : le D+/km d'une performance
    d'une sortie est celui de son profil de domaine, publié qu'elle soit scorée ou non ;
    un jour de plusieurs sorties n'a pas de profil de domaine unique, son D+/km est
    absent. Une performance d'une sortie scorée avec scénario d'usage est classée ;
    sans usage, non scorée ou de plusieurs sorties, elle ne l'est pas."""
    _, run = identity
    domains = {d.outing_id: d.dplus_per_km for d in run.preparation.backtest.domains}
    days = _by_day(run)
    multi = days[date(2026, 6, 12)]
    assert multi.motif is NonEvaluable.MULTI_OUTING
    assert (multi.dplus_per_km, multi.comparable, multi.projected_s) == (
        None,
        None,
        None,
    )
    observed = run.preparation.observed
    for performance in run.preparation.backtest.performances:
        if performance.is_multi_outing:
            continue
        (single,) = performance.outings
        assessment = days[performance.civil_date]
        dplus = domains[single.outing_id]
        assert dplus is not None
        assert assessment.dplus_per_km == dplus
        seen = observed.get(single.outing_id)
        classified = seen is not None and seen.traced.usage is not None
        assert (assessment.comparable is not None) is classified
        assert (assessment.projected_s is not None) is classified
    for day in (date(2026, 6, 16), date(2026, 6, 20)):
        assert days[day].motif is NonEvaluable.UNSCORED
        assert days[day].dplus_per_km is not None


def test_projected_duration_on_the_declared_portion(tmp_path: Path) -> None:
    """D10.3, décision Q7 : la durée projetée d'une performance est celle de v0 brut à
    l'effort 1 sur la portion déclarée de sa référence — tout le profil sans portion —,
    divisée par l'effort borné de (0) ; (0) ``non calé`` : celle de v0 brut. Contrôlée
    contre la chronologie de v0 sur le préparé du parcours ``a``, relu ici."""

    def with_portion(manifest: Manifest) -> None:
        outing(manifest, "a-2026-06-27")["portion_m"] = list(PORTION_M)

    path = world_variant(tmp_path / "monde", with_portion)
    _, run = _run(_prepare(path, Identity()), tmp_path)
    observed = run.preparation.observed["a-2026-06-27"].traced.outing
    assert observed.declared_portion_m == PORTION_M
    route = read_gpx(path.parent / "gpx" / "a" / "prepare.gpx").route
    profile = build_profile(route, ParameterSet(PROFILE_PARAMETER_SPECS))
    curve = read_curve(COURBE, ParameterSet(PROJECTION_PARAMETER_SPECS)).curve
    timeline = projected_timeline(
        profile, curve, ParameterSet(PROJECTION_PARAMETER_SPECS)
    )
    start, end = PORTION_M
    portion_s = timeline.time_at(end) - timeline.time_at(start)
    whole_s = timeline.time_at(timeline.length_m) - timeline.time_at(0.0)
    days = _by_day(run)
    durations = {date(2026, 6, 27): portion_s, date(2026, 6, 14): whole_s}
    for day, duration_s in durations.items():
        effort = days[day].base_effort
        assert effort is not None
        assert days[day].projected_s == duration_s / effort.bounded
    assert days[date(2026, 6, 3)].base_effort is None
    assert days[date(2026, 6, 3)].projected_s == whole_s


# ---------------------------------------------------------------------------
# L'effet identité : un gain nul (D10.5, D10.6)
# ---------------------------------------------------------------------------


def test_identity_gains_nothing(identity: tuple[Path, ExperimentRun]) -> None:
    """D10.3 à D10.6 : le candidat qui reproduit v0 a, jour par jour, l'effort de la
    base et un gain ``G_j`` de 0,0 exactement ; aucun dommage, ni de garde-fou ni de
    passage ; rejeté par le seul gain moyen et le vote, sans rien à revoir."""
    _, run = identity
    admission = run.admission
    assert admission is not None
    evaluable = [a for a in run.assessments if a.motif is None]
    assert [a.civil_date for a in evaluable] == list(EVALUABLE)
    for assessment in evaluable:
        assert assessment.gain == 0.0
        assert assessment.base_effort is not None
        assert assessment.candidate_effort == assessment.base_effort
    assert admission.evaluable == 3
    assert admission.mean_gain == 0.0
    assert admission.positive == 0
    assert all(guard.mean_harm == 0.0 for guard in admission.guards)
    assert [value.worst for value in admission.passages.values] == [0.0] * 3
    assert admission.review == ()
    assert admission.failures == (
        FailedCheck(FailedCondition.MEAN_GAIN, None, ()),
        FailedCheck(FailedCondition.VOTE, None, ()),
    )
    assert admission.verdict is AdmissionVerdict.REJECTED


def test_identity_candidate_scores_are_v0_scores(
    identity: tuple[Path, ExperimentRun],
) -> None:
    """Décision Q2, D7.4 : les scores non calés du candidat identité sont ceux de v0
    brut sur la même chaîne — contrôle sur la trace, usage sur la référence, de base
    la prévision d'usage de v0 —, et ceux que le RÉSULTAT porte pour v0 brut."""
    _, run = identity
    curve = run.preparation.backtest.curve
    raw = {o.outing_id: dict(o.scores)[ModelKind.V0_RAW] for o in run.outcomes}
    for outing_id, seen in run.preparation.observed.items():
        traced = seen.traced
        v0 = v0_scores(
            traced.usage,
            traced.trace,
            traced.match,
            traced.passages,
            traced.partition,
            curve.curve,
            curve_ref=curve.curve_ref,
            generated_at=RECORDED_AT,
        )
        candidate = candidate_scores(
            Identity(),
            seen.observation,
            traced.usage,
            seen.realized,
            curve.curve,
            curve_ref=curve.curve_ref,
            base=None if v0.usage is None else v0.usage.forecast,
            generated_at=RECORDED_AT,
        )
        assert candidate == v0
        assert candidate == raw[outing_id]


# ---------------------------------------------------------------------------
# L'erreur du modèle, l'erreur de l'expérience (D10.2 ; Q2)
# ---------------------------------------------------------------------------


def _without_values(scores: OutingScores) -> bool:
    """Aucune prévision, et une erreur du modèle sous toute horloge au support non
    vide."""
    for scenario in (scores.control, scores.usage):
        if scenario is None:
            continue
        forecast = scenario.forecast
        values = (*forecast.segment_s, *forecast.point_s, *forecast.target_s)
        if any(value is not None for value in values):
            return False
        for clock in scenario.clocks:
            support = clock.support
            if support.segment_count and not support.model_error:
                return False
    return True


@pytest.mark.parametrize(
    "name",
    [
        "Broken/descent_level/elapsed",
        "Raising(ValueError)/descent_level/elapsed",
        "Raising(ArithmeticError)/descent_level/elapsed",
    ],
    ids=["sans chronologie", "ValueError", "ArithmeticError"],
)
def test_effect_without_timeline_is_a_model_error(
    experiments: Experiments, name: str
) -> None:
    """``CandidateEffect``, D10.2 : un effet sans chronologie — ``None``, une
    ``ValueError`` ou une ``ArithmeticError`` — est une erreur du modèle, pas une
    exception : le RÉSULTAT s'écrit ; la cible du candidat manque sur les trois jours
    évaluables, le verdict est « à revoir », d'abord pour la cible ; ses scores non
    calés n'ont aucune valeur."""
    registry, run = experiments(name)
    assert _kinds(registry) == [EventKind.DECLARATION, EventKind.RESULT]
    verify_registry(registry)
    admission = run.admission
    assert admission is not None
    assert admission.verdict is AdmissionVerdict.TO_REVIEW
    assert admission.review[0] == ReviewReason(
        ReviewCause.TARGET_UNAVAILABLE, None, EVALUABLE
    )
    assert [a.gain for a in run.assessments if a.motif is None] == [None] * 3
    curve = run.preparation.backtest.curve
    for seen in run.preparation.observed.values():
        scores = candidate_scores(
            run.preparation.spec.effect,
            seen.observation,
            seen.traced.usage,
            seen.realized,
            curve.curve,
            curve_ref=curve.curve_ref,
            base=None,
            generated_at=RECORDED_AT,
        )
        assert _without_values(scores)


def test_other_exception_is_a_technical_failure(manifest: Path, tmp_path: Path) -> None:
    """D14 et sa précision de M4b-5 : une exception d'un autre type dans le calcul,
    après la DÉCLARATION, est un ÉCHEC technique au motif sans chemin, puis une
    ``BacktestError`` ; le registre relu porte la DÉCLARATION et l'ÉCHEC."""
    preparation = _prepare(manifest, Raising(RuntimeError("synthétique")))
    registry = tmp_path / "registre"
    with pytest.raises(
        BacktestError,
        match=re.escape(
            "échec de l'expérience, ÉCHEC enregistré : RuntimeError : synthétique"
        ),
    ) as raised:
        run_experiment(preparation, registry, recorded_at=RECORDED_AT)
    assert isinstance(raised.value.__cause__, RuntimeError)
    log = verify_registry(registry)
    assert [e.kind for e in log.events] == [EventKind.DECLARATION, EventKind.FAILURE]
    failure = log.events[1].failure
    assert failure is not None
    assert (failure.kind, failure.reason) == (
        FailureKind.TECHNICAL,
        "RuntimeError : synthétique",
    )
    assert log.events[1].answers == 1


# ---------------------------------------------------------------------------
# candidate_scores : la précondition, la base (D7.4 ; Q2)
# ---------------------------------------------------------------------------


def test_candidate_scores_requires_the_length_of_the_reference(
    identity: tuple[Path, ExperimentRun],
) -> None:
    """``candidate_scores``, précondition : en usage, la référence a la longueur ``L``
    de l'observation — sans chronologie, la garde de ``candidate_scores`` ; avec une
    chronologie, celle d'``usage_forecast``. Un profil d'un autre tracé est refusé
    (``ValueError``)."""
    _, run = identity
    observed = run.preparation.observed
    seen = observed["a-2026-06-14"]
    other = observed["b-2026-06-25"].traced.usage
    assert other is not None
    curve = run.preparation.backtest.curve
    length = seen.observation.reference_length_m

    def scores(effect: CandidateEffect) -> OutingScores:
        return candidate_scores(
            effect,
            seen.observation,
            other,
            seen.realized,
            curve.curve,
            curve_ref=curve.curve_ref,
            base=None,
            generated_at=RECORDED_AT,
        )

    with pytest.raises(
        ValueError,
        match=re.escape(
            f"candidate_scores : le profil a la longueur {other.distance_m[-1]}, "
            f"l'observation L = {length} : un autre tracé."
        ),
    ):
        scores(Broken())
    timeline = projected_timeline(
        other, curve.curve, ParameterSet(PROJECTION_PARAMETER_SPECS)
    )
    with pytest.raises(
        ValueError,
        match=re.escape(
            f"usage_forecast : la chronologie a la longueur {timeline.length_m}, "
            f"l'observation L = {length} : un autre tracé."
        ),
    ):
        scores(Identity())


def _candidate(
    effect: CandidateEffect,
    seen: ObservedOuting,
    curve: CurveReadResult,
    base: ModelForecast | None,
) -> OutingScores:
    """Les scores non calés du candidat ``effect`` sur une sortie observée, de base
    ``base``, datés de ``RECORDED_AT``."""
    return candidate_scores(
        effect,
        seen.observation,
        seen.traced.usage,
        seen.realized,
        curve.curve,
        curve_ref=curve.curve_ref,
        base=base,
        generated_at=RECORDED_AT,
    )


def test_candidate_base_is_the_denominator_of_q_usage(
    usage: tuple[Path, ExperimentRun],
) -> None:
    """D7.4, décision Q2 (même schéma que les baselines de ``just backtest``, M4c-2) :
    ``base`` — la prévision d'usage de v0 brut — n'est que le dénominateur de
    ``q_usage`` des scores non calés du candidat. Pour l'effet de descente, avec elle
    ou sans elle, le contrôle, l'observation, la prévision d'usage, ses enveloppes et
    chaque métrique d'horloge sont les mêmes ; la cible d'usage diffère sous chaque
    horloge — avec la base, ses poids sont ceux de v0 brut."""
    _, run = usage
    curve = run.preparation.backtest.curve
    compared = 0
    for seen in run.preparation.observed.values():
        traced = seen.traced
        if traced.usage is None:
            continue
        v0 = v0_scores(
            traced.usage,
            traced.trace,
            traced.match,
            traced.passages,
            traced.partition,
            curve.curve,
            curve_ref=curve.curve_ref,
            generated_at=RECORDED_AT,
        )
        assert v0.usage is not None
        based = _candidate(Descent(), seen, curve, v0.usage.forecast)
        unbased = _candidate(Descent(), seen, curve, None)
        assert based.observation == unbased.observation
        assert based.control == unbased.control
        assert based.usage is not None
        assert unbased.usage is not None
        assert based.usage.forecast == unbased.usage.forecast
        assert based.usage.envelope == unbased.usage.envelope
        assert based.usage.class_envelopes == unbased.usage.class_envelopes
        for ours, theirs, raw in zip(
            based.usage.clocks, unbased.usage.clocks, v0.usage.clocks, strict=True
        ):
            assert (ours.clock, ours.support, ours.diagnostic, ours.passage_errors) == (
                theirs.clock,
                theirs.support,
                theirs.diagnostic,
                theirs.passage_errors,
            )
            assert ours.usage_target != theirs.usage_target
            assert ours.usage_target is not None
            assert raw.usage_target is not None
            assert ours.usage_target.weights == raw.usage_target.weights
        compared += 1
    assert compared >= 3


# ---------------------------------------------------------------------------
# Aucune performance évaluable : l'ÉCHEC « non évaluable » (Q4, P15)
# ---------------------------------------------------------------------------


def test_no_evaluable_performance_is_a_not_evaluable_failure(
    not_evaluable: tuple[Path, ExperimentRun],
) -> None:
    """Décision Q4, P15 : les trois sorties évaluables exclues de l'admission (et une
    sortie du jour de plusieurs sorties), ``n`` vaut 0 — aucun document d'admission, un
    ÉCHEC « non évaluable » dont le motif compte les performances par motif, dans
    l'ordre de ``NonEvaluable`` ; les évaluations sont rendues ; le registre se
    vérifie."""
    registry, run = not_evaluable
    log = verify_registry(registry)
    assert [e.kind for e in log.events] == [EventKind.DECLARATION, EventKind.FAILURE]
    assert log.events == (run.declaration_event, run.answer_event)
    failure = run.answer_event.failure
    assert failure is not None
    assert failure.kind is FailureKind.NOT_EVALUABLE
    assert failure.reason == (
        "aucune performance évaluable : excluded 4, unscored 2, no_usage 1, "
        "not_calibrated 5"
    )
    assert run.admission is None
    assert run.outcomes == ()
    assert run.seal == line_hash(run.answer_event)
    excluded = (*EVALUABLE, date(2026, 6, 12))
    motifs = {a.civil_date: a.motif for a in run.assessments}
    assert motifs == {**MOTIFS, **dict.fromkeys(excluded, NonEvaluable.EXCLUDED)}


# ---------------------------------------------------------------------------
# L'exclusion d'admission (P17)
# ---------------------------------------------------------------------------


def test_exclusion_of_a_later_outing_of_a_multi_outing_day(
    not_evaluable: tuple[Path, ExperimentRun],
) -> None:
    """P17, P1 ; D10.2 : une exclusion d'admission qui nomme une sortie d'un jour de
    plusieurs sorties, **pas la première**, exclut la performance — n'importe laquelle
    de ses sorties y suffit ; le motif ``excluded``, celui de la déclaration, précède
    ``multi_outing``."""
    _, run = not_evaluable
    (multi,) = [p for p in run.preparation.backtest.performances if p.is_multi_outing]
    assert multi.civil_date == date(2026, 6, 12)
    outings = [outing.outing_id for outing in multi.outings]
    assert outings == ["a-2026-06-12", "b-2026-06-12", "libre-2026-06-12"]
    assert set(run.preparation.spec.admission_exclusions) & set(outings) == {
        "b-2026-06-12"
    }
    assert _by_day(run)[date(2026, 6, 12)].motif is NonEvaluable.EXCLUDED


def _efforts(run: ExperimentRun, day: date) -> tuple[Any, Any]:
    assessment = _by_day(run)[day]
    return assessment.base_effort, assessment.candidate_effort


def test_admission_exclusion_of_an_evaluable_outing(
    experiments: Experiments, descent: tuple[Path, ExperimentRun]
) -> None:
    """P17 : une sortie évaluable exclue de l'admission a le motif ``excluded`` et ne
    compte plus dans ``n`` ; les autres performances gardent leur motif et leurs
    efforts."""
    _, base = descent
    _, run = experiments("Descent/descent_level/elapsed/exclusion")
    assert run.admission is not None
    assert base.admission is not None
    assert run.admission.evaluable == base.admission.evaluable - 1 == 2
    expected = {**MOTIFS, date(2026, 6, 25): NonEvaluable.EXCLUDED}
    assert {a.civil_date: a.motif for a in run.assessments} == expected
    for day in (date(2026, 6, 14), date(2026, 6, 27)):
        assert _efforts(run, day) == _efforts(base, day)


def test_admission_exclusion_keeps_the_outing_in_the_history(
    experiments: Experiments, descent: tuple[Path, ExperimentRun]
) -> None:
    """P17 : exclue de l'admission, ``a-2026-06-10`` — un jour de répétabilité de
    ``a``, membre du calage des 25 et 27 juin — a le motif ``excluded`` ; elle reste
    dans l'historique : les références D8 et les références figées sont inchangées,
    et l'effort de (0) et de (1) des jours dont elle est membre du calage aussi."""
    _, base = descent
    _, run = experiments("Descent/descent_level/elapsed/exclusion_membre")
    assert run.admission is not None
    assert base.admission is not None
    assert run.admission.evaluable == base.admission.evaluable == 3
    expected = {**MOTIFS, date(2026, 6, 10): NonEvaluable.EXCLUDED}
    assert {a.civil_date: a.motif for a in run.assessments} == expected
    references = run.preparation.references
    assert date(2026, 6, 10) in dict(references)["a"].days
    assert [_undated(r) for _, r in references] == [
        _undated(r) for _, r in base.preparation.references
    ]
    ours, theirs = run.preparation.declaration, base.preparation.declaration
    assert ours.experiment is not None
    assert theirs.experiment is not None
    assert ours.experiment.frozen_references == theirs.experiment.frozen_references
    calibrations = {
        outcome.outing_id: dict(outcome.scores)[ModelKind.V0_RECALIBRATED]
        for outcome in run.outcomes
    }
    for outing_id, day in (
        ("b-2026-06-25", date(2026, 6, 25)),
        ("a-2026-06-27", date(2026, 6, 27)),
    ):
        scores = calibrations[outing_id]
        assert isinstance(scores, CalibratedOutingScores)
        assert scores.usage is not None
        calibration = scores.usage.clocks[0].calibration
        assert date(2026, 6, 10) in calibration.population
        assert _efforts(run, day) == _efforts(base, day)


# ---------------------------------------------------------------------------
# Les refus d'avant la DÉCLARATION (ExperimentError ; D7.4, Q5, Q6, E4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        (
            {"usage_targets": (DeclaredUsageTarget("z", (ARRIVAL,), None),)},
            "K du parcours 'z' : aucune sortie déclarée de ce parcours n'a de "
            "référence (D7.4).",
        ),
        (
            {"usage_targets": (DeclaredUsageTarget("a", (OUTSIDE,), None),)},
            "K du parcours 'a' : éléments hors du K par défaut (départ exclu, D7.4) : "
            "[TargetMember(occurrence_index=5, arrival=False)]",
        ),
        (
            {"admission_exclusions": {"velo-2026-06-06": "x", "inconnue": "x"}},
            "exclusion d'admission d'une sortie qui n'est pas celle d'une performance "
            "déclarée : ['inconnue', 'velo-2026-06-06']",
        ),
    ],
    ids=["K sans référence", "K hors du défaut", "exclusion inconnue"],
)
def test_refusals_before_the_declaration(
    manifest: Path, spec: dict[str, Any], message: str
) -> None:
    """D7.4, décisions Q6 et E4, P17 : un ``K`` déclaré pour un parcours dont aucune
    sortie n'a de référence ; un élément de ``K`` hors du ``K`` par défaut d'une sortie
    observée du parcours ; une exclusion d'admission qui ne nomme pas une sortie d'une
    performance déclarée — ``VTT`` non retenu compris : ``ExperimentError``, rien
    d'écrit."""
    before = _files(manifest.parent)
    with pytest.raises(ExperimentError, match=re.escape(message)):
        _prepare(manifest, Identity(), ExperimentMetric.USAGE, **spec)
    assert _files(manifest.parent) == before


K_FIRST = DeclaredUsageTarget("a", (TargetMember(0, False),), None)
"""Un ``K`` déclaré sur ``a`` : son premier lieu nommé seul."""


def _reference_of_b(manifest: Manifest) -> None:
    """``a-2026-06-27`` rattachée à la référence de ``b`` (une trace désignée, sans lieu
    nommé) : son ``K`` par défaut est l'arrivée seule."""
    outing(manifest, "a-2026-06-27")["reference"] = dict(
        outing(manifest, "b-2026-06-25")["reference"]  # type: ignore[call-overload]
    )


def _without_reference(manifest: Manifest) -> None:
    """``a-2026-06-27`` sans référence : pas de scénario d'usage (D3)."""
    del outing(manifest, "a-2026-06-27")["reference"]


def test_declared_k_is_checked_on_every_outing_with_usage(tmp_path: Path) -> None:
    """Décision Q6, D7.4 : le ``K`` déclaré est vérifié sur **chaque** sortie observée
    avec usage de son parcours — ``K_FIRST`` est dans le ``K`` par défaut des premières
    sorties de ``a``, pas de ``a-2026-06-27`` rattachée à une autre référence : refus
    avant la DÉCLARATION, rien d'écrit (pas un ÉCHEC technique après)."""
    path = world_variant(tmp_path, _reference_of_b)
    before = _files(tmp_path)
    with pytest.raises(
        ExperimentError,
        match=re.escape(
            "K du parcours 'a' : éléments hors du K par défaut (départ exclu, D7.4) : "
            "[TargetMember(occurrence_index=0, arrival=False)]"
        ),
    ):
        _prepare(path, Identity(), ExperimentMetric.USAGE, usage_targets=(K_FIRST,))
    assert _files(tmp_path) == before


def test_declared_k_ignores_an_outing_without_usage(tmp_path: Path) -> None:
    """D7.4, précision de D10.1 : un ``K`` n'existe qu'en usage — ``a-2026-06-27`` sans
    référence (son ``K`` par défaut : l'arrivée seule) n'est pas jugée ; ``K_FIRST`` est
    accepté et figé dans la DÉCLARATION."""
    path = world_variant(tmp_path, _without_reference)
    preparation = _prepare(
        path, Identity(), ExperimentMetric.USAGE, usage_targets=(K_FIRST,)
    )
    seen = preparation.observed["a-2026-06-27"]
    assert seen.traced.usage is None
    assert seen.observation.members == (ARRIVAL,)
    experiment = preparation.declaration.experiment
    assert experiment is not None
    assert experiment.usage_targets == (K_FIRST,)


@pytest.mark.parametrize("case", ["date d'analyse", "sans expérience"])
def test_run_experiment_refuses_without_exploratory_experiment(
    identity: tuple[Path, ExperimentRun], tmp_path: Path, case: str
) -> None:
    """Décision Q5, D10.7 : ``run_experiment`` n'exécute qu'une expérience d'admission
    exploratoire — une préparation dont l'expérience a une date d'analyse, ou sans
    expérience, est refusée avant la DÉCLARATION (``ExperimentError``), rien
    d'écrit."""
    preparation = identity[1].preparation
    experiment = preparation.declaration.experiment
    assert experiment is not None
    changed = (
        replace(experiment, analysis_date=date(2026, 7, 1))
        if case == "date d'analyse"
        else None
    )
    refused = replace(
        preparation, declaration=replace(preparation.declaration, experiment=changed)
    )
    registry = tmp_path / "registre"
    with pytest.raises(
        ExperimentError,
        match=re.escape(
            "run_experiment : une expérience d'admission exploratoire, sans date "
            "d'analyse (D10.7 : pas de figement pour confirmation dans ce lot)."
        ),
    ):
        run_experiment(refused, registry, recorded_at=RECORDED_AT)
    assert not registry.exists()
    assert issubclass(ExperimentError, ValueError)


# ---------------------------------------------------------------------------
# K en préfixe sur la cible q_usage (D7.4 ; E4)
# ---------------------------------------------------------------------------


def test_usage_target_as_a_prefix(
    usage: tuple[Path, ExperimentRun], usage_k: tuple[Path, ExperimentRun]
) -> None:
    """D7.4, décision E4 : un ``K`` valide en préfixe — sans l'arrivée — sur la cible
    ``q_usage`` ; l'expérience aboutit, la DÉCLARATION relue porte le ``K``, chaque
    performance évaluable a le seuil fixe (D10.3). Il s'applique : au ``K`` par défaut,
    le 10 juin (trou d'enregistrement) a un élément indisponible ; au préfixe, non."""
    registry, run = usage_k
    log = verify_registry(registry)
    assert [e.kind for e in log.events] == [EventKind.DECLARATION, EventKind.RESULT]
    declaration = log.events[0].declaration
    assert declaration is not None
    assert declaration.experiment is not None
    assert declaration.experiment.usage_targets == (K_PREFIX,)
    assert declaration.experiment.target is ExperimentMetric.USAGE
    admission = run.admission
    assert admission is not None
    assert admission.target is ExperimentMetric.USAGE
    evaluable = [a for a in run.assessments if a.motif is None]
    assert evaluable
    for assessment in evaluable:
        assert assessment.source is ThresholdSource.FIXED
        assert assessment.threshold == GAIN_FLOOR
    default = _by_day(usage[1])[date(2026, 6, 10)]
    assert default.motif is NonEvaluable.PASSAGE_UNAVAILABLE
    assert _by_day(run)[date(2026, 6, 10)].motif is not (
        NonEvaluable.PASSAGE_UNAVAILABLE
    )
