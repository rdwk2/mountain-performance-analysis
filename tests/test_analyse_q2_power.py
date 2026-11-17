"""La puissance de Q2 (AN3-3b, ``docs/decisions/0023``, § 8) : un tirage sans hasard
(C14), la charnière (C14 bis), le bruit du scénario (4) (C15), les comptes (C19), les
grilles, ``W`` et son unique tirage, un tirage en échec, la reproductibilité en
processus neufs (C20), un fil BLAS dans le pool. Sur des mondes inventés."""

from __future__ import annotations

import dataclasses
import inspect
import math
import multiprocessing
import os
import subprocess
import sys
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("pyarrow")

from fixtures import q2_run
from fixtures.q2_world import small_world
from mountain_perf import cli
from mountain_perf.analyse.athlete import Periods
from mountain_perf.analyse.inference import bootstrap
from mountain_perf.analyse.inference.base import InferenceError, child_rng
from mountain_perf.analyse.inference.power import Outcome
from mountain_perf.analyse.inference.readings import Reading
from mountain_perf.analyse.inference.reml import three_component_cov
from mountain_perf.analyse.q2 import model, power
from mountain_perf.analyse.q2.data import q2_data
from mountain_perf.analyse.q2.parameters import Q2_PARAMETER_SPECS
from mountain_perf.analyse.q2.power import (
    PowerWorld,
    alpha_grid,
    estimate_draw,
    hinge_shift,
    power_grids,
    power_summary,
    power_world,
    reliability_noise_variance,
    run_power,
    simulate_draw,
    simulated_responses,
)
from mountain_perf.schemas import ParameterSet
from mountain_perf.schemas.processed import ClimbRegime

LONG = ClimbRegime.LONG_CLIMB
SHORT = ClimbRegime.SHORT_CLIMB
EXACT = 1e-12
TESTS = Path(__file__).resolve().parent


def _params(**values: float) -> ParameterSet:
    return ParameterSet(Q2_PARAMETER_SPECS, values)


# --- C14, C14 bis, C15 --------------------------------------------------------------


def test_c14_a_draw_without_chance() -> None:
    y = simulated_responses(
        (0.1, 0.2),
        0.001,
        (0.0, 30.0),
        (0.01, -0.02),
        ((0.01, -0.01, 0.03), (0.02, 0.0)),
    )
    assert y[0] == pytest.approx((0.12, 0.10, 0.14), rel=EXACT)
    assert y[1] == pytest.approx((0.23, 0.21), rel=EXACT)
    assert [sum(d) / len(d) for d in y] == pytest.approx([0.12, 0.22], rel=EXACT)
    shifted = simulated_responses(
        (0.1, 0.2),
        0.001,
        (0.0, 30.0),
        (0.01, -0.02),
        ((0.01, -0.01, 0.03), (0.02, 0.0)),
        (0.0, -0.05),
    )
    assert shifted[1] == pytest.approx((0.18, 0.16), rel=EXACT)


@pytest.mark.parametrize(
    ("day", "discovery", "expected"),
    [
        (100, False, 0.0),
        (150, False, 0.0),
        (250, False, 0.0),
        (260, False, 0.0),
        (175, False, -0.04169080446952551),
        (225, False, -0.04169080446952551),
        (200, False, -0.08338160893905101),
        (225, True, -0.09298409885707609),
        (100, True, -0.05129329438755058),
    ],
)
def test_c14_bis_the_hinge_is_affine_in_log(
    day: int, discovery: bool, expected: float
) -> None:
    """C14 bis : affine en log (en fraction, le jour 175 donnerait
    -0,040821994520255166)."""
    assert hinge_shift(day, discovery, _params()) == pytest.approx(
        expected, rel=EXACT, abs=EXACT
    )


def test_c15_the_noise_of_scenario_four() -> None:
    assert reliability_noise_variance([145.0, 147.0, 150.0, 153.0, 155.0], 0.85) == (
        pytest.approx(3.0, rel=EXACT)
    )


# --- les grilles --------------------------------------------------------------------


def test_the_grids_of_q36() -> None:
    grids = power_grids(_params())
    assert grids.fractions[1] == (
        0.0,
        0.01,
        0.02,
        0.03,
        0.04,
        0.05,
        0.075,
        0.10,
        0.15,
        0.20,
    )
    assert grids.fractions[2] == (0.0,)
    assert grids.fractions[3] == grids.fractions[4] == (0.0, 0.05)
    assert grids.b_values(1)[5] == math.log(1.05) / 365.25
    assert grids.b_values(1)[0] == 0.0


def test_delta_outside_the_table_takes_its_place() -> None:
    """Q-50 (e)."""
    grids = power_grids(_params(delta=0.06))
    assert grids.fractions[1] == (
        0.0,
        0.01,
        0.02,
        0.03,
        0.04,
        0.05,
        0.06,
        0.075,
        0.10,
        0.15,
        0.20,
    )
    assert grids.fractions[3] == (0.0, 0.06)


def test_the_alpha_grids() -> None:
    """Q-49 (l) ; Bonferroni aux côtes : ``bonferroni_level(0,05 ; 5)`` donne le
    niveau nominal des côtes."""
    factors = (1.0, 0.8, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1)
    assert alpha_grid(LONG, _params()) == tuple(0.05 * f for f in factors)
    assert alpha_grid(SHORT, _params()) == tuple(0.01 * f for f in factors)


# --- C19 ----------------------------------------------------------------------------

ESTABLISHED = Outcome(0.0002, (Reading.ESTABLISHED,) * 8, (1,) * 8)
UNDECIDED = Outcome(0.0001, (Reading.UNDECIDED,) * 8, (0,) * 8)
NOMINAL_ONLY = Outcome(
    0.0, (Reading.ESTABLISHED,) + (Reading.UNDECIDED,) * 7, (1,) + (0,) * 7
)


def _c19(at_delta: int) -> Any:
    params = _params()
    grids = power_grids(params)
    outcomes: dict[int, list[list[Outcome]]] = {}
    for scenario in (1, 2, 3, 4):
        lines = []
        for fraction in grids.fractions[scenario]:
            if fraction == 0.0 and scenario in (1, 2):
                lines.append([NOMINAL_ONLY] + [UNDECIDED] * 3)
            elif scenario == 1 and fraction == 0.05:
                lines.append([ESTABLISHED] * at_delta + [UNDECIDED] * (4 - at_delta))
            elif scenario == 1 and fraction == 0.075:
                lines.append([ESTABLISHED] * 4)
            else:
                lines.append([UNDECIDED] * 4)
        outcomes[scenario] = lines
    alphas = alpha_grid(LONG, params)
    return power_summary(grids, outcomes, alphas, params, long_climbs=True), alphas


def test_c19_the_power_counts() -> None:
    summary, alphas = _c19(3)
    assert summary.power_at_delta == 0.75
    assert summary.no_effect_out_of_reach is True
    assert summary.undecided_expected is False
    assert summary.smallest_visible == 0.075
    assert summary.insufficient is True
    assert summary.calibration.triggered is True
    assert summary.calibration.alpha == alphas[1]
    assert summary.at_zero[1] == (0.25, 0.0)


def test_c19_an_effect_visible_at_delta_needs_no_message() -> None:
    summary, _ = _c19(4)
    assert summary.smallest_visible == 0.05
    assert summary.insufficient is False


# --- le monde, W, un tirage ---------------------------------------------------------


@pytest.fixture(scope="module")
def world() -> PowerWorld:
    params = _params(bootstrap_draws=9)
    return power_world(q2_data(small_world(1), None, params), LONG, params)


def _spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, Any, int]]:
    seen: list[tuple[Any, Any, int]] = []
    original = bootstrap.parametric_draws

    def spy(mean: Any, V: Any, B: int, rng: Any) -> Any:  # noqa: N803
        seen.append((mean, V, B))
        return original(mean, V, B, rng)

    monkeypatch.setattr(power, "parametric_draws", spy)
    return seen


@pytest.mark.parametrize(("scenario", "extra"), [(1, 0), (2, 1), (3, 0), (4, 1)])
def test_one_draw_is_one_call_of_parametric_draws(
    monkeypatch: pytest.MonkeyPatch, world: PowerWorld, scenario: int, extra: int
) -> None:
    """§ 8.2 : un seul appel ; ``W`` a ``J + N`` lignes, plus ``J`` aux scénarios (2)
    et (4) ; le bloc des résidus de journée est ``three_component_cov(t, 0, τ̂²,
    s²_u, φ̂)`` : sans ``d_s``."""
    seen = _spy(monkeypatch)
    simulate_draw(world, scenario, 0.0, child_rng(5, 1))
    assert len(seen) == 1
    mean, w, count = seen[0]
    j = len(world.units)
    n = sum(len(u.climbs) for u in world.units)
    assert count == 1
    assert len(mean) == len(w) == j + n + extra * j
    expected = three_component_cov(
        list(world.t), [0.0] * j, world.tau2, world.s2u, world.phi
    ).tolist()
    assert [row[:j] for row in w[:j]] == expected
    assert all(w[j + i][j + i] == world.s2e for i in range(n))


def test_zero_day_residuals_are_omitted(
    monkeypatch: pytest.MonkeyPatch, world: PowerWorld
) -> None:
    zero = dataclasses.replace(
        world,
        reml=dataclasses.replace(world.reml, tau2_at_zero=True, s2u_at_zero=True),
    )
    seen = _spy(monkeypatch)
    simulate_draw(zero, 1, 0.0, child_rng(5, 1))
    n = sum(len(u.climbs) for u in world.units)
    assert len(seen[0][1]) == n


def _differences(world: PowerWorld) -> list[float]:
    one = simulate_draw(world, 1, 0.0, child_rng(5, 1))
    three = simulate_draw(world, 3, 0.0, child_rng(5, 1))
    return [b[0] - a[0] for a, b in zip(one.y, three.y, strict=True)]


def test_scenario_three_adds_the_hinge_with_and_without_periods() -> None:
    params = _params(bootstrap_draws=9)
    tables = small_world(1)
    plain = power_world(q2_data(tables, None, params), LONG, params)
    expected = [hinge_shift(d, False, params) for d in plain.day_of_year]
    assert _differences(plain) == pytest.approx(expected, abs=1e-12)
    periods = Periods(date(2025, 4, 1), date(2025, 5, 31))
    declared = power_world(q2_data(tables, periods, params), LONG, params)
    assert any(declared.discovery)
    expected = [
        hinge_shift(d, disc, params)
        for d, disc in zip(declared.day_of_year, declared.discovery, strict=True)
    ]
    assert _differences(declared) == pytest.approx(expected, abs=1e-12)


def test_a_failed_draw_gives_nan_and_is_counted(
    monkeypatch: pytest.MonkeyPatch, world: PowerWorld
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise InferenceError("refusé")

    data = simulate_draw(world, 1, 0.0, child_rng(5, 1))
    monkeypatch.setattr(model, "reml_fit", refuse)
    alphas = alpha_grid(LONG, world.parameters)
    outcome = estimate_draw(world, 1, data, alphas, child_rng(5, 1, 1))
    assert math.isnan(outcome.estimate)
    assert outcome.readings == (Reading.UNDECIDED,) * 8
    grids = power_grids(world.parameters)
    lines = {s: [[outcome] for _ in grids.fractions[s]] for s in (1, 2, 3, 4)}
    summary = power_summary(grids, lines, alphas, world.parameters, long_climbs=True)
    assert summary.failed[1] == (1,) * 10


def test_an_estimated_draw_reads_each_alpha(world: PowerWorld) -> None:
    data = simulate_draw(world, 1, 0.0, child_rng(5, 1))
    alphas = alpha_grid(LONG, world.parameters)
    outcome = estimate_draw(world, 1, data, alphas, child_rng(5, 1, 1))
    assert math.isfinite(outcome.estimate)
    assert len(outcome.readings) == len(outcome.directions) == 8


def test_run_power_reads_the_grids_of_power_grids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La grille de ``run_power`` est celle de ``power_grids`` non remplacée (seuls
    les tests de bout en bout la remplacent) ; les clés ``(1, r, s)``."""
    calls: list[tuple[tuple[float, ...], tuple[int, ...]]] = []

    def fake(
        simulate: Any,
        estimate: Any,
        b_values: Sequence[float],
        alphas: Sequence[float],
        n_draws: int,
        root_seed: int,
        key: tuple[int, ...] = (),
        workers: int = 1,
    ) -> tuple[tuple[Outcome, ...], ...]:
        calls.append((tuple(b_values), key))
        undecided = Outcome(0.0, (Reading.UNDECIDED,) * len(alphas), (0,) * len(alphas))
        return tuple((undecided,) * n_draws for _ in b_values)

    monkeypatch.setattr(power, "simulate_power", fake)
    params = _params(power_draws=2)
    run_power(q2_data(small_world(1), None, params), params)
    grids = power_grids(params)
    assert calls == [
        (grids.b_values(s), (1, r, s - 1)) for r in (0, 1) for s in (1, 2, 3, 4)
    ]
    assert len(calls[0][0]) == 10


def test_the_pool_functions_are_module_functions() -> None:
    for function in (simulate_draw, estimate_draw):
        assert inspect.getmodule(function) is power
        assert "<locals>" not in function.__qualname__


# --- C20, un fil BLAS ---------------------------------------------------------------


def _run_in_new_process(
    folder: Path, processus: int, reverse: bool, hash_seed: str
) -> bytes:
    # Comme la commande en production, les variables BLAS sont posées avant que numpy
    # ne se charge (ici, par les imports des fixtures) : sinon le processus principal
    # calculerait sur plusieurs fils (Q-50 (b)). Le cas « posées seulement pour
    # N > 1 » est tenu par le test des valeurs de ``_run_q2`` à ``--processus 1``.
    code = (
        "import os, sys\n"
        "for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):\n"
        "    os.environ[name] = '1'\n"
        f"sys.path.insert(0, {str(TESTS)!r})\n"
        "from fixtures.q2_run import run_power_in_new_process\n"
        f"run_power_in_new_process({str(folder)!r}, {processus}, {reverse})\n"
    )
    environment = {**os.environ, "PYTHONHASHSEED": hash_seed}
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    (written,) = (folder / "resultats" / "Q2" / "puissance").iterdir()
    return (written / "puissance.csv").read_bytes()


def test_c20_the_output_depends_neither_on_processes_nor_on_order(
    tmp_path: Path,
) -> None:
    """C20 : deux processus neufs, l'un à un processus, lignes dans l'ordre et
    ``PYTHONHASHSEED=1``, l'autre à deux processus « spawn », lignes inversées et
    ``PYTHONHASHSEED=2`` : ``puissance.csv`` identique à l'octet."""
    one, two = tmp_path / "un", tmp_path / "deux"
    one.mkdir()
    two.mkdir()
    first = _run_in_new_process(one, 1, False, "1")
    second = _run_in_new_process(two, 2, True, "2")
    assert first == second


def test_the_pool_computes_on_one_blas_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Q-50 (b) : après ``_run_q2`` (ici sans tables : il s'arrête tôt), un processus
    « spawn » voit les trois variables à ``"1"``, une valeur ``"4"`` posée avant
    comprise."""
    for name in q2_run.BLAS:
        monkeypatch.setenv(name, "4")
    assert cli._run_q2("puissance", 1) == 1
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=context) as pool:
        (seen,) = list(pool.map(q2_run.blas_environment, [0]))
    assert seen == ("1", "1", "1")
