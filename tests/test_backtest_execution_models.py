"""L'exécution à cinq modèles (§ 6.3, § 6.4 et § 8.1, test 3, du brief M4c-2 ;
``0010`` D14 et sa précision de M4c-2, D9.1, D9.2, D7.4).

- ``MODELS`` : les cinq modèles de D9.1, dans l'ordre, chacun avec sa version, ses
  paramètres et sa règle (``CALIBRATION_RULE``).
- Sur le monde de M4b-5 exécuté une fois par module (``world``) : les scores non calés
  des baselines de chaque sortie, **égaux au bit** à ``baseline_scores`` sur la même
  chaîne ; le calage, **égal au bit** à ``calibrate_performances`` sur les scores non
  calés ; ``CALIBRATION_ELAPSED`` (§ 7.2), le statut et ``β`` sous l'écoulé.
- Les deux rappels de ``run_backtest`` (décision 10) : ``on_declaration`` quand le
  journal n'a que la DÉCLARATION, ``before_result`` quand il n'a pas encore le
  RÉSULTAT ; une erreur ou une interruption dans l'un ou l'autre, un ÉCHEC technique ;
  sans performance, la DÉCLARATION annoncée puis l'ÉCHEC « non évaluable ».
- ``git_state`` : ``git --no-optional-locks status`` (ligne « (M4c, git) » de
  ``BACKLOG.md``).

La longueur de la référence de ``baseline_scores`` sans chronologie (§ 6.4) est tenue
par ``tests/test_backtest_calibration.py`` (correctif du § 2).
"""

import json
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import mountain_perf.backtest.execution as execution
from fixtures.backtest_values import CALIBRATION_ELAPSED
from fixtures.backtest_world import (
    COMMIT,
    COURBE,
    RECORDED_AT,
    RETRIEVED_AT,
    write_world,
)
from mountain_perf.backtest import (
    BASELINE_MODELS,
    CALIBRATION_RULE,
    MODELS,
    V0_RAW_MODEL,
    V0_RECALIBRATED_MODEL,
    BacktestError,
    BacktestEvaluation,
    BacktestRun,
    Preparation,
    baseline_scores,
    calibrate_performances,
    git_state,
    line_hash,
    prepare_backtest,
    read_registry,
    realized_profile,
    run_backtest,
)
from mountain_perf.model import (
    BASELINE_VERSION,
    BASELINES,
    ENGINE_VERSION,
    PROJECTION_PARAMETER_SPECS,
)
from mountain_perf.schemas import (
    CALIBRATED_MODELS,
    CLOCKS,
    EventKind,
    FailureKind,
    ModelKind,
    OutingScores,
    ParameterSet,
    RegistryEvent,
)


def _prepare(manifest: Path) -> Preparation:
    return prepare_backtest(
        manifest, COURBE, commit=COMMIT, tree_modified=False, retrieved_at=RETRIEVED_AT
    )


def _kinds(registry: Path) -> list[EventKind]:
    """Les types des lignes du journal, s'il existe."""
    if not registry.exists():
        return []
    return [event.kind for event in read_registry(registry).events]


@dataclass
class Seen:
    """Ce que les rappels ont vu : l'événement, l'empreinte reçue et le journal au
    moment de l'annonce ; le calcul et le journal au moment de ``before_result``."""

    declarations: list[tuple[RegistryEvent, str, list[EventKind]]] = field(
        default_factory=list
    )
    evaluations: list[tuple[BacktestEvaluation, list[EventKind]]] = field(
        default_factory=list
    )


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, BacktestRun, Seen]:
    """Le monde exécuté une fois, avec ses deux rappels : son manifeste, l'exécution,
    et ce que les rappels ont vu."""
    root = tmp_path_factory.mktemp("monde")
    manifest = write_world(root / "monde")
    registry = root / "registre"
    seen = Seen()

    def announce(event: RegistryEvent, seal: str) -> None:
        seen.declarations.append((event, seal, _kinds(registry)))

    def compute(evaluation: BacktestEvaluation) -> None:
        seen.evaluations.append((evaluation, _kinds(registry)))

    run = run_backtest(
        _prepare(manifest),
        registry,
        recorded_at=RECORDED_AT,
        on_declaration=announce,
        before_result=compute,
    )
    return manifest, run, seen


# ---------------------------------------------------------------------------
# Les modèles déclarés (D9.1, D9.2, D14)
# ---------------------------------------------------------------------------


def test_the_five_declared_models() -> None:
    """D9.1, précision de D14 (M4c-2) : v0 brut ; v0 + effort recalé, aux paramètres
    de départ de v0 avec la règle de calage ; les trois baselines, sans paramètre fixé,
    avec cette règle — dans cet ordre."""
    assert CALIBRATION_RULE == (
        "calage D9.2 par performance évaluée, scénario et horloge, sur C_j^eff ; jour "
        "évalué exclu"
    )
    assert (V0_RAW_MODEL, V0_RECALIBRATED_MODEL, *BASELINE_MODELS) == MODELS
    assert [model.kind for model in MODELS] == [ModelKind.V0_RAW, *CALIBRATED_MODELS]
    assert [model.kind for model in BASELINE_MODELS] == list(BASELINES)
    defaults = ParameterSet(PROJECTION_PARAMETER_SPECS)
    assert (V0_RAW_MODEL.engine_version, V0_RAW_MODEL.parameters) == (
        ENGINE_VERSION,
        defaults,
    )
    assert V0_RAW_MODEL.estimation_rule is None
    assert (
        V0_RECALIBRATED_MODEL.engine_version,
        V0_RECALIBRATED_MODEL.parameters,
        V0_RECALIBRATED_MODEL.estimation_rule,
    ) == (ENGINE_VERSION, defaults, CALIBRATION_RULE)
    for model in BASELINE_MODELS:
        assert (model.engine_version, model.parameters, model.estimation_rule) == (
            BASELINE_VERSION,
            None,
            CALIBRATION_RULE,
        )


def test_the_declaration_carries_the_five_models(
    world: tuple[Path, BacktestRun, Seen],
) -> None:
    """``prepare_backtest`` déclare ``MODELS``."""
    _, run, _ = world
    assert run.preparation.declaration.models == MODELS


# ---------------------------------------------------------------------------
# Les baselines non calées et le calage, au bit (§ 6.3)
# ---------------------------------------------------------------------------


def test_baselines_are_those_of_baseline_scores(
    world: tuple[Path, BacktestRun, Seen],
) -> None:
    """§ 6.3, ``_score`` : les scores non calés des trois baselines, dans l'ordre de
    ``BASELINES``, égaux au bit à ``baseline_scores`` — contrôle sur le profil de la
    trace, usage sur celui de la référence (absent sans référence), de base la
    prévision d'usage de v0 brut (D7.4), datés de la DÉCLARATION."""
    _, run, _ = world
    generated_at = run.declaration_event.recorded_at
    for outing in run.outings:
        usage = outing.profile if outing.outing.reference is not None else None
        base = None if outing.scores.usage is None else outing.scores.usage.forecast
        realized = realized_profile(outing.trace)
        expected = tuple(
            (
                kind,
                baseline_scores(
                    outing.scores.observation,
                    usage,
                    realized,
                    kind,
                    base=base,
                    generated_at=generated_at,
                ),
            )
            for kind in BASELINES
        )
        assert outing.baselines == expected, outing.outing.outing_id
        for _, scores in outing.baselines:
            assert scores.control.forecast.generated_at == generated_at
            assert (scores.usage is None) == (usage is None)


def test_calibration_is_that_of_calibrate_performances(
    world: tuple[Path, BacktestRun, Seen],
) -> None:
    """§ 6.3, ``_evaluate`` : le calage de l'exécution, égal au bit à
    ``calibrate_performances`` sur les performances et les scores non calés de v0 brut
    et des baselines."""
    _, run, _ = world
    unscaled: dict[str, dict[ModelKind, OutingScores]] = {
        outing.outing.outing_id: {
            ModelKind.V0_RAW: outing.scores,
            **dict(outing.baselines),
        }
        for outing in run.outings
    }
    expected = calibrate_performances(run.preparation.performances, unscaled)
    assert run.calibration == expected
    assert len(run.calibration) == len(run.preparation.performances)


def test_calibration_under_the_elapsed_clock(
    world: tuple[Path, BacktestRun, Seen],
) -> None:
    """§ 7.2, ``CALIBRATION_ELAPSED`` (oracle ``mpmath`` indépendant) : pour chaque
    sortie scorée, le statut et ``β`` sous l'écoulé de chacun des quatre modèles calés,
    scénario par scénario, contre la clé de sa performance."""
    _, run, _ = world
    assert CLOCKS[0].kind.value == "elapsed"
    checked = 0
    for performance in run.calibration:
        day = performance.population.civil_date.isoformat()
        for entry in performance.outings:
            for scenario_scores in (entry.control, entry.usage):
                if scenario_scores is None:
                    continue
                calibration = scenario_scores.clocks[0].calibration
                key = (day, entry.control.model.value, scenario_scores.scenario.value)
                status, beta = CALIBRATION_ELAPSED[key]
                unavailability = calibration.unavailability
                assert (
                    None if unavailability is None else unavailability.value
                ) == status, key
                if beta is None:
                    assert calibration.beta is None, key
                else:
                    assert calibration.beta is not None, key
                    assert math.isclose(
                        calibration.beta, beta, rel_tol=1e-9, abs_tol=1e-12
                    ), key
                checked += 1
    # Douze sorties scorées, dont deux sans référence : 4 × (12 + 10) scénarios.
    assert checked == len(CALIBRATED_MODELS) * (12 + 10)


# ---------------------------------------------------------------------------
# Les rappels (décision 10 ; § 6.3)
# ---------------------------------------------------------------------------


def test_on_declaration_and_before_result(
    world: tuple[Path, BacktestRun, Seen],
) -> None:
    """Décision 10 : ``on_declaration`` reçoit l'événement de la DÉCLARATION et
    l'empreinte de sa ligne quand le journal n'a qu'elle ; ``before_result`` reçoit le
    calcul quand le journal n'a pas encore le RÉSULTAT."""
    _, run, seen = world
    ((event, seal, journal),) = seen.declarations
    assert event == run.declaration_event
    assert seal == line_hash(run.declaration_event)
    assert journal == [EventKind.DECLARATION]
    ((evaluation, journal),) = seen.evaluations
    assert journal == [EventKind.DECLARATION]
    assert evaluation.declaration_event == run.declaration_event
    assert evaluation.preparation is run.preparation
    assert evaluation.outings == run.outings
    assert evaluation.unscored == run.unscored
    assert evaluation.references == run.references
    assert evaluation.calibration == run.calibration


@pytest.mark.parametrize("where", ["on_declaration", "before_result"])
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (ValueError("rappel"), "ValueError : rappel"),
        (KeyboardInterrupt(), "KeyboardInterrupt"),
    ],
    ids=["erreur", "interruption"],
)
def test_error_in_a_callback_is_a_technical_failure(
    world: tuple[Path, BacktestRun, Seen],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    where: str,
    error: BaseException,
    reason: str,
) -> None:
    """§ 6.3, précision de D14 (M4c-2) : une erreur ou une interruption au clavier dans
    ``on_declaration`` ou ``before_result`` est un ÉCHEC technique au motif sans
    chemin ; aucun RÉSULTAT. Le calcul du monde est celui du module (``_evaluate``
    remplacé : il n'est pas l'objet du test)."""
    manifest, _, seen = world
    ((evaluation, _),) = seen.evaluations
    monkeypatch.setattr(execution, "_evaluate", lambda *args: evaluation)

    def raising(*args: Any) -> None:
        raise error

    registry = tmp_path / "registre"
    callbacks: dict[str, Any] = {where: raising}
    try:
        with pytest.raises(BacktestError) as raised:
            run_backtest(
                _prepare(manifest), registry, recorded_at=RECORDED_AT, **callbacks
            )
    except KeyboardInterrupt:
        pytest.fail("une interruption au clavier s'est échappée de run_backtest")
    assert raised.value.__cause__ is error
    assert str(raised.value).endswith(f" : {reason}")
    events = read_registry(registry).events
    assert [event.kind for event in events] == [
        EventKind.DECLARATION,
        EventKind.FAILURE,
    ]
    failure = events[-1].failure
    assert failure is not None
    assert (failure.kind, failure.reason) == (FailureKind.TECHNICAL, reason)


def test_no_performance_announces_the_declaration(tmp_path: Path) -> None:
    """§ 6.3, étape 3 : sans performance, la DÉCLARATION est annoncée, ``before_result``
    n'est jamais appelé, et l'ÉCHEC « non évaluable » suit."""
    manifest = write_world(tmp_path / "monde")
    data = json.loads(manifest.read_bytes())
    kept = {"velo-2026-05-30", "velo-2026-06-06", "velo-2026-06-09", "plat-2026-06-11"}
    data["outings"] = [o for o in data["outings"] if o["id"] in kept]
    manifest.write_bytes(
        (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
    )
    registry = tmp_path / "registre"
    announced: list[tuple[int, list[EventKind]]] = []
    computed: list[BacktestEvaluation] = []
    with pytest.raises(BacktestError, match="aucune performance dans le domaine"):
        run_backtest(
            _prepare(manifest),
            registry,
            recorded_at=RECORDED_AT,
            on_declaration=lambda event, seal: announced.append(
                (event.number, _kinds(registry))
            ),
            before_result=computed.append,
        )
    assert announced == [(1, [EventKind.DECLARATION])]
    assert computed == []
    failure = read_registry(registry).events[-1].failure
    assert failure is not None
    assert failure.kind is FailureKind.NOT_EVALUABLE


# ---------------------------------------------------------------------------
# git_state (ligne « (M4c, git) » de BACKLOG.md)
# ---------------------------------------------------------------------------


def test_git_status_takes_no_optional_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§ 6.3 : ``git rev-parse HEAD``, puis ``git --no-optional-locks status
    --porcelain --untracked-files=no`` — le statut ne pose aucun verrou de l'index."""
    calls: list[list[str]] = []

    def fake(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        stdout = f"{COMMIT}\n" if "rev-parse" in arguments else ""
        return subprocess.CompletedProcess(arguments, 0, stdout, "")

    monkeypatch.setattr(subprocess, "run", fake)
    state = git_state(tmp_path)
    assert (state.commit, state.modified) == (COMMIT, False)
    directory = str(tmp_path)
    assert calls == [
        ["git", "-C", directory, "rev-parse", "HEAD"],
        [
            "git",
            "-C",
            directory,
            "--no-optional-locks",
            "status",
            "--porcelain",
            "--untracked-files=no",
        ],
    ]
