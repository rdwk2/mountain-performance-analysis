"""Garanties de l'expérience d'admission (M4c-3, ``backtest/experiment.py``) que les
tests joints ne tenaient pas — correctifs de la relecture de la PR #25 (balayage de
mutation de la conception, relecture C).

- ``prepare_experiment`` : les trois refus d'avant la DÉCLARATION, dans l'ordre ; rien
  d'écrit sous ``MPA_DATA_DIR`` ; l'instant de lecture transmis à ``prepare_backtest`` ;
  dans un jour de plusieurs sorties, les sorties tracées qui suivent une sortie non
  tracée sont observées ;
- ``run_experiment`` : chaque réponse (RÉSULTAT, ÉCHEC « non évaluable », ÉCHEC
  technique) porte l'instant passé ; une interruption au clavier dans le calcul est un
  ÉCHEC technique ;
- lecture seule : les tables neuves en ``MappingProxyType``, les objets neufs gelés,
  leurs séquences en tuples.
"""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from fixtures.admission_world import ADMISSION_EXCLUSION
from fixtures.backtest_world import COMMIT, COURBE, RECORDED_AT, write_world
from fixtures.effects import Identity, Raising
from mountain_perf.backtest import (
    BacktestError,
    ExperimentError,
    ExperimentSpec,
    encode_contract,
    execution,
    prepare_experiment,
    read_registry,
    run_experiment,
    verify_registry,
)
from mountain_perf.backtest import admission as rule
from mountain_perf.backtest import experiment as exp
from mountain_perf.config import data_dir
from mountain_perf.schemas import (
    CLOCKS,
    DeclaredUsageTarget,
    EventKind,
    ExperimentMetric,
    FailureKind,
)
from mountain_perf.schemas import admission as contracts
from mountain_perf.schemas.admission import NonEvaluable
from test_backtest_execution import untraced, world_variant
from test_backtest_experiment import (
    ARRIVAL,
    LOCAL_EXPERIMENTS,
    OUTSIDE,
    _prepare,
)

M = ExperimentMetric.DESCENT_LEVEL
OTHER_READING = datetime(2026, 10, 5, 8, 15, tzinfo=UTC)


@pytest.fixture(scope="module")
def manifest(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Le monde de M4b-5, écrit une fois."""
    return write_world(tmp_path_factory.mktemp("monde"))


# ---------------------------------------------------------------------------
# prepare_experiment
# ---------------------------------------------------------------------------

NO_REFERENCE = DeclaredUsageTarget("z", (ARRIVAL,), None)
OUTSIDE_A = DeclaredUsageTarget("a", (OUTSIDE,), None)
UNKNOWN = MappingProxyType({"inconnue": "x"})
A_MESSAGE = "K du parcours 'z' : aucune sortie déclarée de ce parcours n'a de"
B_MESSAGE = "K du parcours 'a' : éléments hors du K par défaut"


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ({"usage_targets": (OUTSIDE_A, NO_REFERENCE)}, A_MESSAGE),
        ({"usage_targets": (OUTSIDE_A,), "admission_exclusions": UNKNOWN}, B_MESSAGE),
        (
            {"usage_targets": (NO_REFERENCE,), "admission_exclusions": UNKNOWN},
            A_MESSAGE,
        ),
    ],
    ids=["A avant B", "B avant C", "A avant C"],
)
def test_refusals_in_order(manifest: Path, spec: dict[str, Any], message: str) -> None:
    """§ 6.5, 3 : les refus, dans l'ordre — un ``K`` sans référence (A), un ``K`` hors
    du ``K`` par défaut (B), une exclusion d'une sortie inconnue (C) ; une
    spécification qui en viole deux reçoit le message du premier."""
    with pytest.raises(ExperimentError, match=re.escape(message)):
        _prepare(manifest, Identity(), ExperimentMetric.USAGE, **spec)


def _all_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file())


def test_prepare_experiment_writes_nothing_under_the_data_dir(manifest: Path) -> None:
    """Décision Q3 : ``prepare_experiment`` n'écrit rien — ni à côté du monde, ni sous
    ``MPA_DATA_DIR``, où vit le registre réel —, qu'elle accepte ou refuse."""
    before = _all_files(data_dir())
    _prepare(manifest, Identity())
    with pytest.raises(ExperimentError):
        _prepare(
            manifest,
            Identity(),
            ExperimentMetric.USAGE,
            usage_targets=(OUTSIDE_A,),
        )
    assert _all_files(data_dir()) == before


def test_the_declared_curve_is_read_at_the_given_instant(manifest: Path) -> None:
    """§ 6.5, 1 : ``prepare_backtest`` avec les mêmes arguments — l'instant de lecture
    passé se retrouve dans la DÉCLARATION."""
    preparation = prepare_experiment(
        manifest,
        COURBE,
        ExperimentSpec(Identity(), M, CLOCKS[0]),
        commit=COMMIT,
        tree_modified=False,
        retrieved_at=OTHER_READING,
    )
    written = json.dumps(encode_contract(preparation.declaration))
    assert OTHER_READING.isoformat() in written


def test_a_multi_outing_day_with_an_untraced_first_outing(tmp_path: Path) -> None:
    """§ 6.5, 2 : chaque sortie tracée des performances déclarées est observée — dans
    un jour de plusieurs sorties dont la **première** n'a pas de trace, les suivantes
    le sont."""

    def change(manifest: Any) -> None:
        untraced(
            manifest,
            "a-2026-06-12",
            "2026-06-12T06:00:00+02:00",
            "2026-06-12T07:00:00+02:00",
        )

    world = world_variant(tmp_path / "monde", change)
    preparation = prepare_experiment(
        world,
        COURBE,
        ExperimentSpec(Identity(), M, CLOCKS[0]),
        commit=COMMIT,
        tree_modified=False,
    )
    assert "a-2026-06-12" not in preparation.observed
    assert {"b-2026-06-12", "libre-2026-06-12"} <= set(preparation.observed)


# ---------------------------------------------------------------------------
# run_experiment : l'instant des réponses, l'interruption au clavier
# ---------------------------------------------------------------------------


def test_the_result_is_recorded_at_the_given_instant(
    manifest: Path, tmp_path: Path
) -> None:
    """D14 : le RÉSULTAT porte, comme la DÉCLARATION, l'instant passé à
    ``run_experiment``."""
    run = run_experiment(
        _prepare(manifest, Identity()), tmp_path / "registre", recorded_at=RECORDED_AT
    )
    assert run.answer_event.kind is EventKind.RESULT
    assert run.answer_event.recorded_at == RECORDED_AT


def test_a_not_evaluable_failure_is_recorded_at_the_given_instant(
    manifest: Path, tmp_path: Path
) -> None:
    """Décision Q4, D14 : l'ÉCHEC « non évaluable » porte l'instant passé."""
    n0 = LOCAL_EXPERIMENTS["Identity/descent_level/elapsed/n0"]
    preparation = _prepare(
        manifest,
        n0.effect,
        n0.target,
        n0.clock,
        admission_exclusions=dict.fromkeys(n0.exclusions, ADMISSION_EXCLUSION),
    )
    run = run_experiment(preparation, tmp_path / "registre", recorded_at=RECORDED_AT)
    assert run.answer_event.kind is EventKind.FAILURE
    assert run.answer_event.recorded_at == RECORDED_AT


def test_a_technical_failure_is_recorded_at_the_given_instant(
    manifest: Path, tmp_path: Path
) -> None:
    """D14 : l'ÉCHEC technique porte l'instant passé."""
    preparation = _prepare(manifest, Raising(RuntimeError("synthétique")))
    registry = tmp_path / "registre"
    with pytest.raises(BacktestError):
        run_experiment(preparation, registry, recorded_at=RECORDED_AT)
    events = verify_registry(registry).events
    assert [e.kind for e in events] == [EventKind.DECLARATION, EventKind.FAILURE]
    assert [e.recorded_at for e in events] == [RECORDED_AT, RECORDED_AT]


@pytest.mark.parametrize("where", ["admit", "calibrate_performances"])
def test_keyboard_interrupt_is_a_technical_failure(
    manifest: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """§ 6.5, 3 et 6 : le ``try`` attrape ``Exception`` **et** ``KeyboardInterrupt`` ;
    une interruption dans le calage ou dans ``admit`` est un ÉCHEC technique."""
    preparation = _prepare(manifest, Identity())

    def interrupted(*args: Any, **kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(exp, where, interrupted)
    registry = tmp_path / "registre"
    try:
        with pytest.raises(BacktestError, match="KeyboardInterrupt"):
            run_experiment(preparation, registry, recorded_at=RECORDED_AT)
    except KeyboardInterrupt:
        pytest.fail("KeyboardInterrupt non rattrapé : aucun ÉCHEC technique")
    events = read_registry(registry).events
    assert [e.kind for e in events] == [EventKind.DECLARATION, EventKind.FAILURE]
    assert events[1].failure is not None
    assert events[1].failure.kind is FailureKind.TECHNICAL


# ---------------------------------------------------------------------------
# Lecture seule
# ---------------------------------------------------------------------------

TABLES: list[tuple[str, object]] = [
    ("REGIME_METRICS", rule.REGIME_METRICS),
    ("ADMISSION_VERDICT_DESCRIPTIONS", contracts.ADMISSION_VERDICT_DESCRIPTIONS),
    ("ADMISSION_RESERVE_DESCRIPTIONS", contracts.ADMISSION_RESERVE_DESCRIPTIONS),
    ("THRESHOLD_SOURCE_DESCRIPTIONS", contracts.THRESHOLD_SOURCE_DESCRIPTIONS),
    ("NON_EVALUABLE_DESCRIPTIONS", contracts.NON_EVALUABLE_DESCRIPTIONS),
    ("GUARD_STATUS_DESCRIPTIONS", contracts.GUARD_STATUS_DESCRIPTIONS),
    ("REVIEW_CAUSE_DESCRIPTIONS", contracts.REVIEW_CAUSE_DESCRIPTIONS),
    ("FAILED_CONDITION_DESCRIPTIONS", contracts.FAILED_CONDITION_DESCRIPTIONS),
]


@pytest.mark.parametrize(
    "table", [table for _, table in TABLES], ids=[n for n, _ in TABLES]
)
def test_new_tables_are_read_only(table: object) -> None:
    """§§ 6.0 et 6.4 : les tables neuves sont en lecture seule."""
    assert isinstance(table, MappingProxyType)


FROZEN: list[type] = [
    rule.AdmissionInput,
    execution.TracedOuting,
    exp.ExperimentSpec,
    exp.ObservedOuting,
    exp.ExperimentPreparation,
    exp.ExperimentRun,
]


@pytest.mark.parametrize("cls", FROZEN, ids=[cls.__name__ for cls in FROZEN])
def test_new_objects_are_frozen(cls: type) -> None:
    """§§ 6.4 et 6.5 : les objets neufs sont des dataclasses gelées."""
    instance: object = object.__new__(cls)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, dataclasses.fields(cls)[0].name, None)


def test_default_spec_exclusions_are_read_only() -> None:
    """§ 6.5 : les exclusions d'admission par défaut d'``ExperimentSpec``."""
    spec = ExperimentSpec(Identity(), ExperimentMetric.USAGE, CLOCKS[0])
    assert isinstance(spec.admission_exclusions, MappingProxyType)


def test_preparation_and_run_sequences_are_tuples(
    manifest: Path, tmp_path: Path
) -> None:
    """§ 6.5 : les séquences d'``ExperimentPreparation`` et d'``ExperimentRun``."""
    preparation = _prepare(manifest, Identity())
    assert type(preparation.references) is tuple
    run = run_experiment(preparation, tmp_path / "registre", recorded_at=RECORDED_AT)
    assert type(run.outcomes) is tuple
    assert type(run.assessments) is tuple


# ---------------------------------------------------------------------------
# La préparation fige ce qu'elle déclare (D14)
# ---------------------------------------------------------------------------


def test_admission_exclusions_are_frozen_by_the_preparation(
    manifest: Path, tmp_path: Path
) -> None:
    """D14, décision 25 : le calcul applique les exclusions que la DÉCLARATION
    enregistre — l'appelant qui vide ensuite le dictionnaire qu'il a passé ne change
    rien."""
    supplied = {"a-2026-06-14": ADMISSION_EXCLUSION}
    preparation = _prepare(manifest, Identity(), admission_exclusions=supplied)
    declared = preparation.declaration
    supplied.clear()
    run = run_experiment(preparation, tmp_path / "registre", recorded_at=RECORDED_AT)
    assert run.declaration_event.declaration == declared
    excluded = [a for a in run.assessments if a.civil_date.isoformat() == "2026-06-14"]
    assert [a.motif for a in excluded] == [NonEvaluable.EXCLUDED]


def test_preparation_mappings_are_read_only(manifest: Path) -> None:
    """§ 6.5 : les exclusions d'admission de la préparation — copiées, même quand
    l'appelant passe un ``dict`` — et ses sorties observées sont en lecture seule."""
    preparation = _prepare(
        manifest, Identity(), admission_exclusions={"a-2026-06-14": "x"}
    )
    assert isinstance(preparation.spec.admission_exclusions, MappingProxyType)
    assert isinstance(preparation.observed, MappingProxyType)
