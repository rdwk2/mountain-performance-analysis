"""Sensibilités du monde de M4b-5 (M4d-3 ; ``0010`` D13, D14) — inventées de bout en
bout, exécutées **une fois par session de tests** et partagées entre les modules.

Une sensibilité du monde dure une vingtaine de secondes : chaque module la demande à
une fonction de ce module, qui l'exécute au premier appel, dans un dossier de la base
temporaire de pytest (``tmp_path_factory``), puis rend la même à chaque appel suivant.
Un test qui écrit au registre le **copie** d'abord (``copy_registry``) : les registres
rendus ici ne changent jamais.

- ``backtest_sensitivity`` : ``run_world`` (la DÉCLARATION 1 et son RÉSULTAT 2, à
  ``RECORDED_AT``), puis ``run_sensitivity`` à ``SENSITIVITY_RECORDED_AT`` (la
  DÉCLARATION de sensibilité 3 et son RÉSULTAT 4) ; les appels de ``on_pair``,
  ``on_declaration`` et ``before_result`` notés ; une copie du registre prise entre la
  centrale et sa sensibilité (``central_only``).
- ``experiment_sensitivity`` : l'expérience de l'effet de descente sur
  ``descent_level`` (``EXPERIMENT_EFFECT``, ``EXPERIMENT_TARGET``), déclarée sous
  l'écoulé (``"ecoule"``) ou sous ``M θ2`` (``"mouvement"``, ``CLOCKS[3]``), chacune
  dans son registre, sur un même monde écrit une fois, puis sa sensibilité.

- ``mini_central`` : la centrale de ``just backtest`` sur un **petit monde** — le monde
  réduit à deux sorties du parcours ``a``, ``MINI_OUTINGS`` —, seule dans son registre :
  sa sensibilité dure quelques secondes, pour les refus et les ÉCHECS.

Les deux horodatages diffèrent d'une heure : les prévisions de la centrale et celles
des huit autres paires se distinguent par leur date (précision de D13, M4d-3).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest

from fixtures.backtest_world import (
    COMMIT,
    COURBE,
    RECORDED_AT,
    RETRIEVED_AT,
    run_world,
    write_world,
)
from fixtures.effects import Descent
from mountain_perf.backtest import (
    BacktestRun,
    CandidateEffect,
    ExperimentRun,
    ExperimentSpec,
    Pair,
    Preparation,
    SensitivityEvaluation,
    SensitivityRun,
    prepare_backtest,
    prepare_experiment,
    read_registry,
    run_backtest,
    run_experiment,
    run_sensitivity,
)
from mountain_perf.schemas import CLOCKS, Clock, ExperimentMetric, RegistryEvent

SENSITIVITY_RECORDED_AT = RECORDED_AT + timedelta(hours=1)
"""L'instant d'enregistrement des événements des sensibilités, une heure après la
centrale."""

EXPERIMENT_EFFECT = Descent()
"""L'effet des expériences : l'allure de v0 multipliée sur les descentes."""
EXPERIMENT_TARGET = ExperimentMetric.DESCENT_LEVEL
"""La cible des expériences."""
EXPERIMENT_CLOCKS: dict[str, Clock] = {"ecoule": CLOCKS[0], "mouvement": CLOCKS[3]}
"""L'horloge déclarée de chaque expérience : l'écoulé, ``M θ2``."""


@dataclass(frozen=True)
class BacktestSensitivity:
    """La sensibilité de ``just backtest`` sur le monde, et ce que ses rappels ont
    vu."""

    root: Path
    registry: Path
    central_only: Path
    central: BacktestRun
    run: SensitivityRun
    pairs_seen: tuple[Pair, ...]
    declared_seen: tuple[RegistryEvent, str]
    events_before_result: int
    evaluation_before_result: SensitivityEvaluation


@dataclass(frozen=True)
class ExperimentSensitivity:
    """Une expérience du monde et sa sensibilité, dans leur registre."""

    manifest: Path
    registry: Path
    central: ExperimentRun
    run: SensitivityRun


MINI_OUTINGS = ("a-2026-06-03", "a-2026-06-14")
"""Les sorties du petit monde : un jour de répétabilité et la course de développement
du parcours ``a``."""


@dataclass(frozen=True)
class MiniCentral:
    """La centrale de ``just backtest`` sur le petit monde, seule dans son registre."""

    manifest: Path
    registry: Path
    central: BacktestRun


_BACKTEST: list[BacktestSensitivity] = []
_MINI: list[MiniCentral] = []
_MANIFEST: list[Path] = []
_EXPERIMENTS: dict[str, ExperimentSensitivity] = {}


def copy_registry(source: Path, target: Path) -> Path:
    """Une copie du registre ``source`` dans ``target`` (qui ne doit pas exister) ;
    rend ``target``."""
    shutil.copytree(source, target)
    return target


def backtest_sensitivity(factory: pytest.TempPathFactory) -> BacktestSensitivity:
    """La sensibilité de ``just backtest`` sur le monde, exécutée au premier appel."""
    if _BACKTEST:
        return _BACKTEST[0]
    root = factory.mktemp("sensibilite-backtest")
    central = run_world(root)
    registry = root / "registre"
    central_only = copy_registry(registry, root / "registre-centrale")
    seen: list[Pair] = []
    declared: list[tuple[RegistryEvent, str]] = []
    before: list[tuple[int, SensitivityEvaluation]] = []

    def on_before(evaluation: SensitivityEvaluation) -> None:
        before.append((len(read_registry(registry).events), evaluation))

    run = run_sensitivity(
        central,
        registry,
        recorded_at=SENSITIVITY_RECORDED_AT,
        on_pair=seen.append,
        on_declaration=lambda event, seal: declared.append((event, seal)),
        before_result=on_before,
    )
    ((events, evaluation),) = before
    (declared_seen,) = declared
    _BACKTEST.append(
        BacktestSensitivity(
            root,
            registry,
            central_only,
            central,
            run,
            tuple(seen),
            declared_seen,
            events,
            evaluation,
        )
    )
    return _BACKTEST[0]


def experiment_manifest(factory: pytest.TempPathFactory) -> Path:
    """Le monde des expériences, écrit au premier appel ; son manifeste."""
    if not _MANIFEST:
        _MANIFEST.append(write_world(factory.mktemp("monde-experiences")))
    return _MANIFEST[0]


def run_world_experiment(
    manifest: Path,
    registry: Path,
    clock: Clock,
    *,
    effect: CandidateEffect = EXPERIMENT_EFFECT,
    target: ExperimentMetric = EXPERIMENT_TARGET,
    exclusions: dict[str, str] | None = None,
) -> ExperimentRun:
    """Une expérience du monde, préparée et exécutée à ``RECORDED_AT`` dans
    ``registry``."""
    preparation = prepare_experiment(
        manifest,
        COURBE,
        ExperimentSpec(effect, target, clock, admission_exclusions=exclusions or {}),
        commit=COMMIT,
        tree_modified=False,
        retrieved_at=RETRIEVED_AT,
    )
    return run_experiment(preparation, registry, recorded_at=RECORDED_AT)


def experiment_sensitivity(
    factory: pytest.TempPathFactory, name: str
) -> ExperimentSensitivity:
    """L'expérience ``name`` (``EXPERIMENT_CLOCKS``) et sa sensibilité, exécutées au
    premier appel."""
    if name not in _EXPERIMENTS:
        manifest = experiment_manifest(factory)
        registry = factory.mktemp(f"sensibilite-{name}") / "registre"
        central = run_world_experiment(manifest, registry, EXPERIMENT_CLOCKS[name])
        run = run_sensitivity(central, registry, recorded_at=SENSITIVITY_RECORDED_AT)
        _EXPERIMENTS[name] = ExperimentSensitivity(manifest, registry, central, run)
    return _EXPERIMENTS[name]


def write_mini_world(root: Path) -> Path:
    """Le petit monde écrit dans ``root`` : le monde, son manifeste réduit aux sorties
    de ``MINI_OUTINGS`` ; rend le chemin du manifeste."""
    manifest = write_world(root)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["outings"] = [o for o in data["outings"] if o["id"] in MINI_OUTINGS]
    manifest.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def prepare_mini(manifest: Path) -> Preparation:
    """La préparation de ``just backtest`` sur le petit monde."""
    return prepare_backtest(
        manifest, COURBE, commit=COMMIT, tree_modified=False, retrieved_at=RETRIEVED_AT
    )


def mini_central(factory: pytest.TempPathFactory) -> MiniCentral:
    """Le petit monde écrit, et sa centrale exécutée à ``RECORDED_AT``, au premier
    appel."""
    if not _MINI:
        root = factory.mktemp("petit-monde")
        manifest = write_mini_world(root / "monde")
        registry = root / "registre"
        central = run_backtest(
            prepare_mini(manifest), registry, recorded_at=RECORDED_AT
        )
        _MINI.append(MiniCentral(manifest, registry, central))
    return _MINI[0]
