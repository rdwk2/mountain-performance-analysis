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
from datetime import date, timedelta
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
    les tests de bout en bout la remplacent) ; les clés ``(1, r, s)``. Correctifs de
    la PR #52, 3 bis.4 : pour chaque scénario ``s``, la fonction de tirage et celle
    d'estimation sont ``simulate_draw`` et ``estimate_draw`` liées à ``(monde, s)``,
    le même monde, celui du régime ; les seuils sont ``alpha × facteurs`` aux
    montées longues et ``alpha / 5 × facteurs`` aux côtes, écrits en dur. Contre une
    fonction de tirage liée au scénario 1 pour tous (P5d-1), les seuils des côtes
    pris à ``alpha`` seul (P5d-2)."""
    calls: list[tuple[tuple[float, ...], tuple[int, ...]]] = []
    bound: list[tuple[Any, Any, tuple[float, ...]]] = []

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
        bound.append((simulate, estimate, tuple(alphas)))
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
    long_alphas = (0.05, 0.04, 0.03, 0.025, 0.02, 0.015, 0.01, 0.005)
    short_alphas = (0.01, 0.008, 0.006, 0.005, 0.004, 0.003, 0.002, 0.001)
    for k, (simulate, estimate, alphas) in enumerate(bound):
        regime = (LONG, SHORT)[k // 4]
        scenario = k % 4 + 1
        assert simulate.func is simulate_draw
        assert estimate.func is estimate_draw
        assert simulate.args[1] == estimate.args[1] == scenario
        assert simulate.args[0] is estimate.args[0]
        assert simulate.args[0].regime is regime
        assert not simulate.keywords
        assert not estimate.keywords
        expected = long_alphas if regime is LONG else short_alphas
        assert alphas == pytest.approx(expected, rel=EXACT)


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
    # Correctifs de la PR #52, 3.7 (a) : aucun tirage n'est en échec sur ce monde
    # (contre une estimation simulée qui lève sans se voir, P3o).
    header, *lines = first.decode("utf-8").splitlines()
    column = header.split(",").index("tirages_en_echec")
    assert lines
    assert [line.split(",")[column] for line in lines] == ["0"] * len(lines)


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


# --- correctifs de la PR #52 : W, le scénario (4), le bootstrap à V fixée ------------


def _world_h_bar(world: PowerWorld) -> list[float]:
    """Les ``h̄_s`` réels du monde, calculés ici : la moyenne des FC de ses
    montées."""
    return [sum(c.h for c in u.climbs) / len(u.climbs) for u in world.units]


def _variance(values: Sequence[float]) -> float:
    """La variance d'échantillon (dénominateur ``n − 1``), calculée ici."""
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / (len(values) - 1)


@pytest.mark.parametrize("scenario", [2, 4])
def test_the_blocks_of_w_for_scenarios_two_and_four(
    monkeypatch: pytest.MonkeyPatch, world: PowerWorld, scenario: int
) -> None:
    """Correctifs de la PR #52, 3.6 : au scénario (2), le bloc de la composante lente
    est ``three_component_cov(t, 0, 0, 0,03², 45)`` (écart type et portée par
    défaut, écrits en dur) ; au scénario (4), le bloc du bruit de ``h̄`` est la
    diagonale ``var(h̄) · (1/0,85 − 1)``, ``h̄`` les FC réelles du monde. Contre la
    portée prise à ``φ̂`` (P3m), un bruit de variance ``s²_ε`` (P3n-1)."""
    seen = _spy(monkeypatch)
    simulate_draw(world, scenario, 0.0, child_rng(5, 1))
    ((_, w, _),) = seen
    j = len(world.units)
    n = sum(len(u.climbs) for u in world.units)
    start = 0 if world.residual_day_zero else j
    block = [row[start + n : start + n + j] for row in w[start + n : start + n + j]]
    assert len(block) == j
    if scenario == 2:
        expected = three_component_cov(
            list(world.t), [0.0] * j, 0.0, 0.03**2, 45.0
        ).tolist()
        for got, want in zip(block, expected, strict=True):
            assert got == pytest.approx(want, rel=EXACT)
    else:
        noise = _variance(_world_h_bar(world)) * (1.0 / 0.85 - 1.0)
        for i in range(j):
            assert block[i] == pytest.approx(
                [noise if k == i else 0.0 for k in range(j)], rel=1e-12, abs=0.0
            )


class _Rows:
    """Un faux tableau de ``parametric_draws`` : une ligne connue."""

    def __init__(self, row: Sequence[float]) -> None:
        self.row = list(row)

    def tolist(self) -> list[list[float]]:
        return [list(self.row)]


@pytest.mark.parametrize("scenario", [1, 2])
def test_each_simulated_speed_reads_its_place_in_z(
    monkeypatch: pytest.MonkeyPatch, world: PowerWorld, scenario: int
) -> None:
    """Correctifs de la PR #52, 3 bis.4 (§ 8.2) : un espion de ``parametric_draws``
    rend ``z = (0, 1, 2, …)`` ; sur un monde dont les résidus de journée ne sont pas
    nuls, ``y*`` de la montée ``i`` (rang global) de la journée ``s`` vaut ``μ_s +
    b·t_s + z[s] + z[J + i]``, plus ``z[J + N + s]`` au scénario (2). Contre des
    ``ε`` lus un rang trop loin (P5e-1), la composante lente oubliée (P5e-2)."""
    assert not world.residual_day_zero

    def known(mean: Any, V: Any, B: int, rng: Any) -> _Rows:  # noqa: N803
        return _Rows([float(k) for k in range(len(mean))])

    monkeypatch.setattr(power, "parametric_draws", known)
    b = 0.001
    data = simulate_draw(world, scenario, b, child_rng(5, 1))
    j = len(world.units)
    n = sum(len(u.climbs) for u in world.units)
    i = 0
    for s, unit in enumerate(world.units):
        expected = []
        for _ in unit.climbs:
            value = world.mu[s] + b * world.t[s] + s + (j + i)
            if scenario == 2:
                value += j + n + s
            expected.append(value)
            i += 1
        assert data.y[s] == pytest.approx(expected, rel=EXACT), s


def test_fixed_v_bootstrap_is_the_inverse_at_the_fitted_v(
    monkeypatch: pytest.MonkeyPatch, world: PowerWorld
) -> None:
    """Correctifs de la PR #52, 3.7 (b) : chaque ``b_inv`` tiré par
    ``fixed_v_bootstrap`` égale ``−d̂*/k̂*`` de la GLS de la ``h̄*`` tirée (relue par
    un espion de ``parametric_draws``) sur la matrice inverse, à ``V̂`` fixée,
    calculé ici par ``inverse_effect_at``. Contre un tirage absent rendu à la place
    de chaque ``b_inv`` (P3o), ``+d̂*/k̂*`` (P3p)."""
    from mountain_perf.analyse.q2.model import (
        build_design,
        fit_inverse,
        fixed_v_bootstrap,
        inverse_design,
        inverse_effect_at,
        stage_one,
    )

    params = world.parameters
    units = list(world.units)
    design = build_design(units, world.spec, stage_one(units, model.Measure.MP), params)
    inverse = fit_inverse(inverse_design(design, units), params)
    seen: list[list[list[float]]] = []
    original = bootstrap.parametric_draws

    def spy(mean: Any, V: Any, B: int, rng: Any) -> Any:  # noqa: N803
        drawn = original(mean, V, B, rng)
        seen.append(drawn.tolist())
        return drawn

    monkeypatch.setattr(model, "parametric_draws", spy)
    draws = fixed_v_bootstrap(inverse, 5, child_rng(9, 9))
    (block,) = seen
    reml = inverse.reml
    v = three_component_cov(
        list(inverse.design.t), list(inverse.design.d), reml.tau2, reml.s2u, reml.phi
    ).tolist()
    columns = inverse.design.columns
    expected = [
        inverse_effect_at(
            inverse.design.X,
            h,
            v,
            columns.index("date"),
            columns.index("log_vam"),
        ).b_inv
        for h in block
    ]
    assert draws.removed == 0
    assert len(draws.draws) == 5
    assert list(draws.draws) == pytest.approx(expected, rel=1e-10)


# --- correctifs de la PR #52 : un régime non estimable -------------------------------


def _tiny_world() -> Any:
    """Quatre journées de montées longues, chacune à un départ que nulle autre ne
    partage, aucune côte, sans ligne de ``jours`` : tous les retraits jouent, ``n =
    4``, ``p = 9`` (constante, date, saison, ``fc``, quatre covariables)."""
    from fixtures.q2_world import at, q2_activity, q2_climb, q2_tables

    activities, climbs = [], []
    for k in range(4):
        when = at(date(2025, 6, 2) + timedelta(days=20 * k), 9)
        ref = f"t{k}"
        activities.append(q2_activity(ref, when))
        for m in range(2):
            lat = 44.0 + 0.5 * k + 0.1 * m
            climbs.append(
                q2_climb(
                    ref,
                    when,
                    offset_s=3000.0 * m,
                    start_latitude_deg=lat,
                    start_longitude_deg=8.0,
                    end_latitude_deg=lat + 0.03,
                    end_longitude_deg=8.0,
                )
            )
    return q2_tables(activities, climbs)


def test_run_power_on_regimes_that_are_not_estimable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Correctifs de la PR #52, 3.9 : ``run_power`` lui-même rend, pour un régime non
    estimable, ni monde ni comptes, et son motif (écrit en dur) ; le résumé de la
    commande dit « puissance non calculée » et ce motif. Contre un motif perdu."""
    params = _params(power_draws=2, bootstrap_draws=9)
    result = run_power(q2_data(_tiny_world(), None, params), params)
    assert [r.regime for r in result.regimes] == [LONG, SHORT]
    assert [(r.world, r.summary) for r in result.regimes] == [(None, None)] * 2
    assert [r.reason for r in result.regimes] == [
        "n − p = -5, sous min_estimable_df = 10",
        "n − p = -9, sous min_estimable_df = 10",
    ]
    cli._print_power(result, params)
    assert capsys.readouterr().out.splitlines() == [
        "long_climb : puissance non calculée (n − p = -5, sous min_estimable_df = 10)",
        "short_climb : puissance non calculée (n − p = -9, sous min_estimable_df = 10)",
        "puissance approchée : covariance fixée dans la simulation (0023)",
    ]


# --- correctifs de la PR #52 : le monde riche, l'estimation simulée -------------------


@pytest.fixture(scope="module")
def rich() -> PowerWorld:
    """Le monde de ``rich_world(2)`` (montées longues, la spline de la FC au modèle,
    l'inverse bien identifiée), à ``bootstrap_draws = 9``."""
    from fixtures.q2_world import rich_world

    params = _params(bootstrap_draws=9)
    return power_world(q2_data(rich_world(2), None, params), LONG, params)


def test_the_simulated_estimate_is_the_real_estimator(rich: PowerWorld) -> None:
    """Correctifs de la PR #52, 3 bis.2 : sur des données simulées qui portent les
    ``y`` et les ``h̄`` du monde, ``estimate_draw`` rend le ``b̂`` de ``fit_direct`` sur
    la même matrice, faite ici ; pour chaque seuil, la lecture est ``bounded_reading``
    des deux intervalles calculés ici à ce niveau (Student pour ``b``, percentile des
    tirages de ``fixed_v_bootstrap`` sous la même clé), le sens ``direction`` des
    deux ; au moins une lecture « établi ». Contre la branche où ``k̂`` exclut 0 qui
    lit un intervalle absent (P5a-1), la lecture d'un seuil prise au seuil suivant
    (P5a-2)."""
    from mountain_perf.analyse.inference.base import percentile_interval
    from mountain_perf.analyse.inference.linear import student_interval
    from mountain_perf.analyse.inference.readings import direction
    from mountain_perf.analyse.q2.model import (
        bounded_reading,
        build_design,
        fit_direct,
        fit_inverse,
        fixed_v_bootstrap,
        fraction_interval,
        inverse_design,
        stage_one,
    )
    from mountain_perf.analyse.q2.power import SimulatedData

    params = rich.parameters
    units = list(rich.units)
    h_bar = _world_h_bar(rich)
    data = SimulatedData(y=tuple(u.y for u in units), h_bar=tuple(h_bar))
    alphas = (0.2, 0.05, 0.001)
    outcome = estimate_draw(rich, 1, data, alphas, child_rng(7, 7))
    design = build_design(
        units, rich.spec, stage_one(units, model.Measure.MP), params, knots=rich.knots
    )
    direct = fit_direct(design, params)
    assert outcome.estimate == pytest.approx(direct.b, rel=1e-12)
    inverse = fit_inverse(inverse_design(design, units), params)
    assert not inverse.k_contains_zero
    draws = list(fixed_v_bootstrap(inverse, 9, child_rng(7, 7)).draws)
    readings, directions = [], []
    for alpha in alphas:
        level = 1.0 - alpha
        d = fraction_interval(student_interval(direct.b, direct.se, direct.df, level))
        i = fraction_interval(percentile_interval(draws, level))
        readings.append(bounded_reading(d, i, None, 0.05, False)[0])
        directions.append(direction([d, i]))
    assert outcome.readings == tuple(readings)
    assert outcome.directions == tuple(directions)
    assert Reading.ESTABLISHED in outcome.readings
    assert len(set(outcome.readings)) > 1


def test_the_world_variance_is_the_mp_stage_one(rich: PowerWorld) -> None:
    """Correctifs de la PR #52, 3 bis.2 : ``s2e`` du monde est la variance de
    l'étage 1 de M-P (réponse ``y``, six covariables, ``h`` d'abord), calculée ici
    par ``centered_stage_one`` sur des couples faits ici ; celle de M-S (réponse
    ``y − ln(h − r)``, cinq covariables) en diffère sur ce monde. Contre le monde
    qui prend la variance de l'étage 1 de M-S (P5b)."""
    import math as m

    from mountain_perf.analyse.q2.model import centered_stage_one

    def covariates(c: Any) -> list[float]:
        return [
            c.log_gain,
            c.grade,
            c.elevation_m,
            c.preceding_ascent_m,
            c.preceding_descent_m,
        ]

    mp = centered_stage_one(
        [[(c.y, [c.h, *covariates(c)]) for c in u.climbs] for u in rich.units]
    )
    ms = centered_stage_one(
        [
            [(c.y - m.log(c.h - (u.day.r or 0.0)), covariates(c)) for c in u.climbs]
            for u in rich.units
        ]
    )
    assert rich.s2e == pytest.approx(mp.sigma2, rel=1e-12)
    assert ms.sigma2 != pytest.approx(mp.sigma2, rel=1e-3)


def test_the_world_knots_and_scenario_four(
    monkeypatch: pytest.MonkeyPatch, rich: PowerWorld
) -> None:
    """Correctifs de la PR #52, 3 bis.3 et 3.6 : les nœuds du monde sont les
    quantiles 0,10, 0,50 et 0,90 (écrits en dur) de la ``h̄`` réelle ; au scénario
    (4), la ``h̄`` simulée diffère de la réelle par le tirage du bloc du bruit (relu
    par un espion de ``parametric_draws``), et la matrice de l'estimation (un espion
    de ``heart_rate_columns``) prend cette ``h̄`` bruitée aux nœuds du monde, pas à
    ceux de la ``h̄`` bruitée. Contre la ``h̄`` du scénario (4) ignorée par la matrice
    simulée (P3n-2), la spline recalculée sur les nœuds de la ``h̄`` bruitée (P5c)."""
    from mountain_perf.analyse.inference.base import order_quantile

    h_bar = _world_h_bar(rich)
    assert rich.knots is not None
    assert rich.knots == pytest.approx(
        [order_quantile(h_bar, q) for q in (0.10, 0.50, 0.90)], rel=EXACT
    )
    drawn: list[list[float]] = []
    original_draws = bootstrap.parametric_draws

    def keep(mean: Any, V: Any, B: int, rng: Any) -> Any:  # noqa: N803
        result = original_draws(mean, V, B, rng)
        drawn.append(result.tolist()[0])
        return result

    monkeypatch.setattr(power, "parametric_draws", keep)
    data = simulate_draw(rich, 4, 0.0, child_rng(5, 4))
    (z,) = drawn
    j = len(rich.units)
    n = sum(len(u.climbs) for u in rich.units)
    start = 0 if rich.residual_day_zero else j
    noise = [h - real for h, real in zip(data.h_bar, h_bar, strict=True)]
    assert noise == pytest.approx(z[start + n : start + n + j], rel=1e-9, abs=1e-9)
    assert any(v != 0.0 for v in noise)
    noisy_knots = [order_quantile(list(data.h_bar), q) for q in (0.10, 0.50, 0.90)]
    assert noisy_knots != pytest.approx(list(rich.knots), rel=1e-9)
    seen: list[tuple[list[float], tuple[float, ...]]] = []
    original = model.heart_rate_columns

    def spy(values: Any, knots: Any) -> Any:
        seen.append((list(values), tuple(knots)))
        return original(values, knots)

    monkeypatch.setattr(model, "heart_rate_columns", spy)
    alphas = alpha_grid(LONG, rich.parameters)
    estimate_draw(rich, 4, data, alphas, child_rng(5, 4, 1))
    assert seen
    values, knots = seen[0]
    assert values == pytest.approx(list(data.h_bar), rel=EXACT)
    assert knots == pytest.approx(list(rich.knots), rel=EXACT)


# --- correctifs de la PR #52 : les comptes de la puissance ----------------------------


def _outcome(estimate: float, established_at: int = 0) -> Outcome:
    """Un résultat de tirage : « établi » positif aux ``established_at`` premiers
    seuils, « non tranché » aux autres."""
    readings = tuple(
        Reading.ESTABLISHED if k < established_at else Reading.UNDECIDED
        for k in range(8)
    )
    return Outcome(estimate, readings, tuple(int(k < established_at) for k in range(8)))


def _summary(lines: dict[int, list[list[Outcome]]]) -> Any:
    params = _params()
    grids = power_grids(params)
    outcomes = {
        s: lines.get(s, [[_outcome(0.0)] * 4 for _ in grids.fractions[s]])
        for s in (1, 2, 3, 4)
    }
    return power_summary(
        grids, outcomes, alpha_grid(LONG, params), params, long_climbs=True
    )


def test_the_bias_under_scenarios_three_and_four() -> None:
    """Correctifs de la PR #52, 3 bis.5 : le biais aux scénarios (3) et (4), à
    ``b = 0`` et à δ, est ``fraction_per_year`` de la moyenne des ``b̂`` finis moins
    ``f`` (un tirage en échec ignoré), écrit en dur ; ``puissance.csv`` le porte dans
    sa colonne, vide aux scénarios (1) et (2). Contre un biais vide (P5f-1), ``f`` de
    signe changé (P5f-2)."""
    from mountain_perf.analyse.q2.power import PowerResult, RegimePower
    from mountain_perf.analyse.q2.results import power_csv

    def at_rate(fraction: float) -> float:
        return math.log(1.0 + fraction) / 365.25

    failed = Outcome(math.nan, (Reading.UNDECIDED,) * 8, (0,) * 8)
    lines = {
        3: [
            [_outcome(at_rate(0.02))] * 3 + [failed],
            [_outcome(at_rate(0.08))] * 4,
        ],
        4: [[_outcome(at_rate(-0.01))] * 4, [_outcome(at_rate(0.04))] * 4],
    }
    summary = _summary(lines)
    assert summary.bias[3] == pytest.approx((0.02, 0.03), rel=1e-9)
    assert summary.bias[4] == pytest.approx((-0.01, -0.01), rel=1e-9)
    result = PowerResult(
        power_grids(_params()),
        (RegimePower(LONG, None, summary, None, alpha_grid(LONG, _params())),),
    )
    header, *rows = power_csv(result).splitlines()
    column = header.split(",").index("biais_fraction_par_an")
    by_scenario: dict[str, list[str]] = {}
    for row in rows:
        cells = row.split(",")
        by_scenario.setdefault(cells[1], []).append(cells[column])
    assert set(by_scenario["1"]) == set(by_scenario["2"]) == {""}
    assert [float(v) for v in by_scenario["3"]] == pytest.approx([0.02, 0.03], rel=1e-9)
    assert [float(v) for v in by_scenario["4"]] == pytest.approx(
        [-0.01, -0.01], rel=1e-9
    )


def test_a_calibration_between_the_first_two_thresholds() -> None:
    """Correctifs de la PR #52, 3 bis.5 : 200 tirages à ``b = 0`` au scénario (1),
    20 « établi » au seuil nominal (10 %, au-dessus de 7,5 %) dont 9 aussi au seuil
    d'indice 1 (4,5 %, entre 0,04 et 0,05) : la calibration est déclenchée et
    l'``alpha`` retenu est celui d'indice 1, 0,04."""
    params = _params()
    grids = power_grids(params)
    zero = [_outcome(0.0, 2)] * 9 + [_outcome(0.0, 1)] * 11 + [_outcome(0.0)] * 180
    first = [zero if f == 0.0 else [_outcome(0.0)] * 4 for f in grids.fractions[1]]
    summary = _summary({1: first})
    assert summary.calibration.triggered is True
    assert summary.calibration.alpha == pytest.approx(0.04, rel=EXACT)
