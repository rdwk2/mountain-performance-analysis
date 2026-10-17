"""Garanties de la bibliothèque du diagnostic de longue course (``backtest/drift.py`` ;
``0010`` D12 ; précisions de M4d-1) que la batterie jointe n'exerçait pas : relecture C
de la PR #28 (constats 1, 5 à 8) et balayage par mutation de la PR #28 (lacunes L1 à
L4). Des lacunes de la conception, pas des défauts du code."""

import ast
import dataclasses
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from fixtures.backtest_world import run_world
from fixtures.segments import hand_profile
from mountain_perf.backtest import BacktestRun
from mountain_perf.backtest import drift as drift_module
from mountain_perf.backtest.drift import (
    annihilate,
    drift_diagnostic,
    drift_fit,
    drift_sequence,
    drift_withdrawals,
    jacobi_svd,
    outing_drift,
)
from mountain_perf.backtest.scoring import report_clocks
from mountain_perf.model.engine import ProjectedTimeline
from mountain_perf.schemas import (
    CLOCKS,
    DRIFT_MODELS,
    CalibratedPerformance,
    ModelKind,
    OutingScores,
    Regime,
    Unavailability,
)
from test_backtest_drift import PROFILE, TIMELINE, _drift_of, longest

ELAPSED = CLOCKS[0]


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> BacktestRun:
    return run_world(tmp_path_factory.mktemp("monde"))


# --- fonctions pures, bibliothèque standard (relecture C, constats 1 et 8) ------------


def test_library_functions_leave_their_inputs_unchanged() -> None:
    """« Fonctions pures » (§ 6.0 du brief) : ni ``jacobi_svd``, ni ``annihilate``, ni
    ``drift_fit``, ni ``drift_withdrawals`` ne modifient une liste reçue —
    ``drift_diagnostic`` passe les mêmes listes à l'ajustement puis aux retraits, et un
    ``M_Z u`` laissé dans ``u`` fausserait le ``rho_u`` publié des retraits."""
    y = [0.01, -0.02, 0.03, 0.0, 0.05]
    u = [0.1, 0.3, 0.5, 0.7, 0.9]
    f = [0.1, 0.4, 0.2, 0.9, 0.5]
    columns = [[1.0] * 5, list(f)]
    copies = ([*y], [*u], [*f], [list(c) for c in columns])
    jacobi_svd(columns)
    annihilate(u, [[1.0 / 5**0.5] * 5])
    drift_fit(y, u, [f])
    drift_withdrawals(y, u, [f])
    assert (y, u, f, columns) == copies


def test_drift_module_imports_the_standard_library_only() -> None:
    """Python pur, sans lecture ni écriture (§ 6.0 du brief, règle 5 de ``CLAUDE.md``) :
    lu sur l'arbre syntaxique — la bibliothèque standard seule, ni ``os``, ``pathlib``,
    ``io``, ``shutil``, ``tempfile``, ni ``open``."""
    tree = ast.parse(Path(drift_module.__file__).read_text(encoding="utf-8"))
    tops = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            tops |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            tops.add(node.module.split(".")[0])
    assert tops - {"mountain_perf", "__future__"} <= set(sys.stdlib_module_names)
    assert not tops & {"os", "pathlib", "io", "shutil", "tempfile"}
    assert not any(isinstance(n, ast.Name) and n.id == "open" for n in ast.walk(tree))


# --- ordres et motifs (relecture C, constats 5 à 7 ; balayage, L1 et L2) --------------


def test_model_error_comes_before_zero_time() -> None:
    """§ 6.2, étapes 4 puis 8 : un ``p⁰_h <= 0`` de v0 brut est « erreur du modèle »
    même quand un autre intervalle a un temps observé nul."""
    profile = hand_profile([0.0, 100.0, 200.0, 300.0], [0.0, 10.0, 10.0, 0.0])
    timeline = ProjectedTimeline((0.0, 100.0, 200.0, 300.0), (1.0, 2.0, 3.0))
    diagnostic = drift_diagnostic(
        ModelKind.V0_RAW,
        ELAPSED,
        observed_s=[120.0, 120.0, 640.0],
        model_s=[100.0, 300.0, 600.0],
        v0_s=[100.0, 90.0, 600.0],
        positions_m=[100.0, 200.0, 300.0],
        origin_m=0.0,
        profile=profile,
        v0_timeline=timeline,
        stops_s=[0.0, 0.0, 0.0],
    )
    assert diagnostic.unavailability is Unavailability.MODEL_ERROR


@pytest.mark.parametrize(
    ("elevation", "expected"),
    [([0.0, 0.0, -10.0], Regime.FLAT), ([0.0, 10.0, 10.0], Regime.ASCENT)],
)
def test_reference_regime_ties_involving_flat(
    elevation: list[float], expected: Regime
) -> None:
    """``R_0`` : à temps projetés égaux, plat devant descente et montée devant plat
    (ordre montée, plat, descente) — les deux paires que le cas joint (montée contre
    descente) ne départage pas."""
    profile = hand_profile([0.0, 100.0, 200.0], elevation)
    timeline = ProjectedTimeline((0.0, 100.0, 200.0), (1.0, 1.0))
    diagnostic = drift_diagnostic(
        ModelKind.V0_RAW,
        CLOCKS[1],
        observed_s=[110.0, 220.0],
        model_s=[100.0, 200.0],
        v0_s=[100.0, 200.0],
        positions_m=[100.0, 200.0],
        origin_m=0.0,
        profile=profile,
        v0_timeline=timeline,
    )
    assert diagnostic.reference_regime is expected


def test_a_sub_second_interval_is_available() -> None:
    """Les bornes sont à 0, pas à 1 s : un intervalle de 0,5 s observé pour 0,4 s
    projeté (``t_h``, ``p_h``, ``p⁰_h`` et la somme des temps par régime ``> 0``) a son
    ``log_ratio`` et le diagnostic reste disponible."""
    positions = [100.0, 100.2, 300.0]
    v0: list[float | None] = [TIMELINE.time_at(s) for s in positions]
    projected = TIMELINE.time_at(100.2) - TIMELINE.time_at(100.0)
    assert projected < 1.0
    diagnostic = drift_diagnostic(
        ModelKind.V0_RAW,
        ELAPSED,
        observed_s=[120.0, 120.5, 640.0],
        model_s=v0,
        v0_s=v0,
        positions_m=positions,
        origin_m=0.0,
        profile=PROFILE,
        v0_timeline=TIMELINE,
        stops_s=[0.0, 0.0, 0.0],
    )
    assert diagnostic.unavailability is None
    assert diagnostic.intervals[1].observed_s == 0.5
    assert diagnostic.intervals[1].log_ratio == pytest.approx(math.log(0.5 / projected))


def test_an_interval_outside_the_profile_is_a_model_error() -> None:
    """§ 6.2, étape 5 : un intervalle dont les régimes ne portent aucun temps projeté
    (au-delà du profil) est une erreur du modèle, du modèle et de l'horloge demandés."""
    diagnostic = drift_diagnostic(
        ModelKind.CONSTANT_SPEED,
        CLOCKS[1],
        observed_s=[120.0, 330.0, 700.0],
        model_s=[100.0, 300.0, 650.0],
        v0_s=[100.0, 300.0, 650.0],
        positions_m=[100.0, 300.0, 350.0],
        origin_m=0.0,
        profile=PROFILE,
        v0_timeline=TIMELINE,
    )
    assert diagnostic.unavailability is Unavailability.MODEL_ERROR
    assert diagnostic.model is ModelKind.CONSTANT_SPEED
    assert diagnostic.clock == CLOCKS[1]


def test_unavailable_calibration_keeps_its_reason(world: BacktestRun) -> None:
    """§ 6.2, ``outing_drift``, étape 4 : un calage indisponible « donne un diagnostic
    indisponible avec ce motif » — ici « erreur du modèle », l'autre motif qu'un calage
    peut porter (le monde n'a que des calages « non calé »). Le calage est un appui
    minimal : seuls ``outing_id``, ``usage.model`` et
    ``usage.clocks[i].calibration.unavailability`` sont lus."""
    outing = longest(world)
    outing_id = outing.outing.outing_id
    broken = SimpleNamespace(unavailability=Unavailability.MODEL_ERROR)
    calibrated = SimpleNamespace(
        outings=[
            SimpleNamespace(
                outing_id=outing_id,
                usage=SimpleNamespace(
                    model=model,
                    clocks=[SimpleNamespace(calibration=broken)] * len(CLOCKS),
                ),
            )
            for model in DRIFT_MODELS[1:]
        ]
    )
    drift = outing_drift(
        outing.scores,
        outing.passages,
        outing.profile,
        report_clocks(outing.match),
        cast(CalibratedPerformance, calibrated),
        world.preparation.curve.curve,
        multi_outing=False,
        outing_id=outing_id,
    )
    assert drift is not None
    reasons = {
        d.unavailability for d in drift.diagnostics if d.model is not ModelKind.V0_RAW
    }
    assert reasons == {Unavailability.MODEL_ERROR}


# --- Jacobi et l'horizon (balayage, L3 et L4) -----------------------------------------


def test_jacobi_svd_values() -> None:
    """Les valeurs singulières de ``[[1, 1], [0, 1]]`` (par colonnes) sont le nombre
    d'or et son inverse, et les vecteurs à gauche sont unitaires et orthogonaux : une
    rotation non orthogonale garderait l'espace engendré, pas les valeurs."""
    sigma, left = jacobi_svd([[1.0, 0.0], [1.0, 1.0]])
    golden = (1.0 + math.sqrt(5.0)) / 2.0
    assert sorted(sigma) == pytest.approx([golden - 1.0, golden], rel=1e-14)
    for i, a in enumerate(left):
        for j, b in enumerate(left):
            dot = math.fsum(x * y for x, y in zip(a, b, strict=True))
            assert dot == pytest.approx(1.0 if i == j else 0.0, abs=1e-14)


@pytest.mark.parametrize(
    ("last", "expected"),
    [(math.inf, None), (-5.0, None), (0.0, None), (0.5, 0.5), (None, None)],
)
def test_horizon(
    world: BacktestRun, last: float | None, expected: float | None
) -> None:
    """§ 6.2, ``outing_drift``, étape 2 : l'horizon est le dernier cumul de v0 brut s'il
    existe, est fini et ``> 0`` (0,5 s compris), sinon absent."""
    outing = longest(world)
    usage = outing.scores.usage
    assert usage is not None
    observation = outing.scores.observation
    ranks, _ = drift_sequence(observation)
    assert ranks
    target_s: list[float | None] = list(usage.forecast.target_s)
    target_s[ranks[-1]] = last
    scores = SimpleNamespace(
        usage=SimpleNamespace(forecast=SimpleNamespace(target_s=tuple(target_s))),
        observation=observation,
    )
    outing_id = outing.outing.outing_id
    calibrated = next(
        p for p in world.calibration if any(e.outing_id == outing_id for e in p.outings)
    )
    drift = outing_drift(
        cast(OutingScores, scores),
        outing.passages,
        outing.profile,
        report_clocks(outing.match),
        calibrated,
        world.preparation.curve.curve,
        multi_outing=False,
        outing_id=outing_id,
    )
    assert drift is not None
    assert drift.horizon_s == expected


def test_an_empty_sequence_has_no_horizon(world: BacktestRun) -> None:
    """Premier élément non observé : séquence vide, pas d'horizon, pas d'exception."""
    outing = longest(world)
    observation = outing.scores.observation
    targets = list(observation.targets)
    targets[0] = dataclasses.replace(
        targets[0], times_s=None, unavailability=Unavailability.ABSENT
    )
    changed = dataclasses.replace(observation, targets=tuple(targets))
    drift = _drift_of(cast(Any, world), outing, observation=changed)
    assert drift.elements == 0
    assert drift.horizon_s is None
