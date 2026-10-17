"""La bibliothèque du diagnostic de longue course (``backtest/drift.py`` ; ``0010``
D12 ; précisions de M4d-1 ; arbitrages E1 à E4 de la passe experte de M4d).

Les valeurs attendues de l'algèbre viennent d'un oracle indépendant (SVD de ``mpmath`` à
70 chiffres, sur les mêmes entrées flottantes), recopiées en littéraux : la suite ne
dépend pas de ``mpmath``. Les cas portent les noms de l'avis expert (D12-A à D12-L).
"""

import dataclasses
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from fixtures.backtest_world import run_world
from fixtures.segments import hand_profile
from mountain_perf.backtest import BacktestRun, OutingRun
from mountain_perf.backtest import drift as drift_module
from mountain_perf.backtest.calibration import calibrated_forecast
from mountain_perf.backtest.drift import (
    DRIFT_JACOBI_NEGLIGIBLE,
    annihilate,
    drift_diagnostic,
    drift_fit,
    drift_sequence,
    drift_withdrawals,
    jacobi_svd,
    nuisance_basis,
    outing_drift,
    regime_projected_s,
)
from mountain_perf.backtest.report import outing_drift_report
from mountain_perf.backtest.scoring import report_clocks
from mountain_perf.model.engine import ProjectedTimeline
from mountain_perf.schemas import (
    CLOCKS,
    DRIFT_MODELS,
    ClockKind,
    DriftDiagnostic,
    EpisodeAttribution,
    EpisodeOutcome,
    ModelKind,
    OutingDrift,
    OutingScores,
    Regime,
    StopEpisode,
    Unavailability,
)

ELAPSED = CLOCKS[0]
U5 = (0.1, 0.3, 0.5, 0.7, 0.9)
V5 = (1.0, -2.0, 0.0, 2.0, -1.0)


def midpoints(projected: list[float]) -> list[float]:
    total = sum(projected)
    out, acc = [], 0.0
    for p in projected:
        out.append((acc + p / 2.0) / total)
        acc += p
    return out


def d12a() -> tuple[list[float], tuple[float, ...], list[float]]:
    """D12-A : cinq intervalles de 1 000 s, faible séparation, 4,4 s déplacés."""
    f = [a + 0.028 * b for a, b in zip(U5, V5, strict=True)]
    t = (1000.0, 1004.4, 995.6, 1000.0, 1000.0)
    return [math.log(x / 1000.0) for x in t], U5, f


def d12b(delta: float, level: float = 0.0) -> tuple[list[float], list[float]]:
    """D12-B : ``f = u + δ v``, ``y = 1 + 0,2 u + 0,4 f`` (+ un niveau)."""
    f = [a + delta * b for a, b in zip(U5, V5, strict=True)]
    y = [level + 1.0 + 0.2 * a + 0.4 * c for a, c in zip(U5, f, strict=True)]
    return y, f


# --- SVD de Jacobi et base des nuisances ----------------------------------------------


def test_jacobi_svd_orthogonal_columns() -> None:
    sigma, left = jacobi_svd([[3.0, 0.0], [0.0, 4.0]])
    assert sigma == (3.0, 4.0)
    assert left == ((1.0, 0.0), (0.0, 1.0))


def test_jacobi_svd_rank_deficient_converges() -> None:
    """Trois colonnes sur deux lignes (un retrait du monde) : la colonne qui s'annule
    n'est plus tournée au niveau du bruit (``DRIFT_JACOBI_NEGLIGIBLE``) ; la SVD
    converge, le rang est 2, la base orthonormée."""
    columns = [[1.0, 1.0], [0.0, 0.4696296296296297], [0.0, 0.530370370370369]]
    sigma, _ = jacobi_svd(columns)
    frob = math.sqrt(math.fsum(x * x for col in columns for x in col))
    assert min(sigma) <= DRIFT_JACOBI_NEGLIGIBLE * frob
    basis = nuisance_basis(columns)
    assert len(basis) == 2
    for i, a in enumerate(basis):
        for j, b in enumerate(basis):
            dot = math.fsum(x * y for x, y in zip(a, b, strict=True))
            assert dot == pytest.approx(1.0 if i == j else 0.0, abs=1e-15)


def test_jacobi_svd_raises_without_convergence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sans convergence dans le nombre de balayages : ``ArithmeticError``, jamais un
    résultat non convergé (arbitrage E3)."""
    monkeypatch.setattr(drift_module, "DRIFT_JACOBI_MAX_SWEEPS", 1)
    with pytest.raises(ArithmeticError, match="pas de convergence en 1 balayages"):
        jacobi_svd([[1.0, 2.0, 3.0], [2.0, 1.0, 0.5], [0.3, 0.1, 2.0]])


def test_nuisance_basis_rank_tolerance() -> None:
    """Rang de ``[1, f]`` : 2 si ``f`` s'écarte de la constante bien au-dessus de la
    tolérance relative ``1e−10``, 1 bien au-dessous ; base vide pour une matrice
    nulle."""
    ones = [1.0, 1.0, 1.0]
    assert len(nuisance_basis([ones, [1.0, 1.0, 1.0 + 1e-6]])) == 2
    assert len(nuisance_basis([ones, [1.0, 1.0, 1.0 + 1e-13]])) == 1
    assert nuisance_basis([[0.0, 0.0]]) == ()


@pytest.mark.parametrize("scale", [1.0, 1e-6])
def test_nuisance_basis_tolerance_is_relative(scale: float) -> None:
    """La tolérance du rang est relative à ``sigma_max`` (``0010`` D12) : ``[1, f]``
    dont ``f`` s'écarte de la constante de ``3e−9`` a ``sigma_min / sigma_max ≈
    7,1e−10``, rang 2 à toute échelle ; à ``1e−11`` (``≈ 2,4e−12``), rang 1."""
    ones = [scale] * 3
    assert len(nuisance_basis([ones, [scale, scale, scale * (1.0 + 3e-9)]])) == 2
    assert len(nuisance_basis([ones, [scale, scale, scale * (1.0 + 1e-11)]])) == 1


def test_annihilate_removes_the_basis() -> None:
    basis = ((1.0, 0.0, 0.0),)
    assert annihilate((3.0, 4.0, 5.0), basis) == (0.0, 4.0, 5.0)


# --- L'ajustement ---------------------------------------------------------------------


def test_fit_recovers_a_separable_slope() -> None:
    """D12-C : fractions de descente ``(0 ; 0 ; 1 ; 1)``, intervalles égaux, ``y = 0,1 +
    0,3 u + 0,2 f`` : ``b = 0,3`` retrouvée, ``rho_u = 0,2``, rang 2, un degré de
    liberté."""
    u = midpoints([1000.0] * 4)
    f = [0.0, 0.0, 1.0, 1.0]
    y = [0.1 + 0.3 * a + 0.2 * c for a, c in zip(u, f, strict=True)]
    fit = drift_fit(y, u, [f])
    assert fit.slope == pytest.approx(0.3, abs=1e-12)
    assert fit.rho == pytest.approx(0.2, rel=1e-12)
    assert (fit.rank, fit.count, fit.dof) == (2, 4, 1)


@pytest.mark.parametrize("level", [0.0, 20.0])
def test_fit_near_the_threshold_matches_the_oracle(level: float) -> None:
    """D12-B, ``δ = 2,00001e−6`` (``rho_u ≈ 1,00001e−10``) : l'oracle donne ``b =
    0,20000000002969828`` ; un niveau ajouté à ``y`` ne la change pas (le calcul
    instable donnait 0,19998 puis 0,19981)."""
    y, f = d12b(2.00001e-6, level)
    fit = drift_fit(y, U5, [f])
    assert fit.slope == pytest.approx(0.20000000002969828, abs=1e-9)
    assert fit.rho == pytest.approx(1.0000099999222744e-10, rel=1e-6)
    assert fit.influence is not None
    scale = math.fsum(abs(a) for a in fit.influence)
    assert abs(math.fsum(fit.influence)) <= 1e-12 * scale


def test_fit_identification_decisions_at_the_boundary() -> None:
    """D12-I : 201 valeurs ``δ = 2e−6 (1 + k·1e−8)`` ; l'oracle rend la pente
    identifiable exactement pour ``k >= 1``."""
    for k in range(-100, 101):
        y, f = d12b(2e-6 * (1 + k * 1e-8))
        assert drift_fit(y, U5, [f]).identifiable is (k >= 1), k


def test_fit_is_descriptive_under_a_nonlinear_mixture() -> None:
    """D12-D : temps doublé en descente, aucun effet de l'avancement ; le log-rapport
    n'est pas linéaire en fractions : ``b = +0,0831`` avec ``rho_u = 0,971`` (oracle).
    D'où le nom « pente descriptive »."""
    f = [0.0, 1.0, 0.5, 0.5, 0.5, 0.5]
    y = [math.log((1 - z) + 2 * z) for z in f]
    fit = drift_fit(y, midpoints([1000.0] * 6), [f])
    assert fit.slope == pytest.approx(0.08314096634568247, rel=1e-12)
    assert fit.rho == pytest.approx(0.9714285714285714, rel=1e-12)


def test_fit_equal_weights_and_a_short_interval() -> None:
    """D12-E : cinq intervalles de 3 600 s puis un de 30 s qui en prend 90 : poids
    égaux, ``b = 0,754`` (oracle), rang 1, quatre degrés de liberté."""
    p = [3600.0] * 5 + [30.0]
    t = [3600.0] * 5 + [90.0]
    y = [math.log(a / b) for a, b in zip(t, p, strict=True)]
    fit = drift_fit(y, midpoints(p), [])
    assert fit.slope == pytest.approx(0.7541229194560057, rel=1e-12)
    assert fit.rho == pytest.approx(1.0, rel=1e-12)
    assert (fit.rank, fit.dof) == (1, 4)


def test_fit_influence_identities() -> None:
    """``a_h = (M_Z u)_h / ‖M_Z u‖²`` : ``Σ a_h = 0`` (la constante est dans ``Z``),
    ``Σ a_h u_h = 1`` et ``b = Σ a_h y_h`` (D12-A)."""
    y, u, f = d12a()
    fit = drift_fit(y, u, [f])
    assert fit.influence is not None
    assert fit.slope == pytest.approx(0.02916445657287393, rel=1e-12)
    assert math.fsum(fit.influence) == pytest.approx(0.0, abs=1e-12)
    total = math.fsum(a * x for a, x in zip(fit.influence, u, strict=True))
    assert total == pytest.approx(1.0, rel=1e-12)
    weighted = math.fsum(a * x for a, x in zip(fit.influence, y, strict=True))
    assert weighted == pytest.approx(fit.slope, rel=1e-12)


@pytest.mark.parametrize("shift", [-3.0, 0.7, 20.0])
def test_fit_level_shift_leaves_slope_and_rho(shift: float) -> None:
    """Un facteur commun à tous les ``t_h`` (un calage) ajoute une constante à ``y`` :
    ``b``, ``rho_u`` et l'influence ne changent pas (D12-A)."""
    y, u, f = d12a()
    base = drift_fit(y, u, [f])
    moved = drift_fit([x + shift for x in y], u, [f])
    assert moved.slope == pytest.approx(base.slope, abs=1e-12)
    assert moved.rho == base.rho
    assert moved.influence == base.influence


def test_fit_saturated_degenerate_and_preconditions() -> None:
    """D12-H : deux intervalles sans nuisance, ``b = 1``, ajustement saturé (``dof =
    0``) ; rang égal au nombre d'intervalles : pas de pente ; un intervalle ou ``u``
    constant : ``rho_u`` absent ; lignes vides ou colonnes inégales : ``ValueError``."""
    fit = drift_fit([0.0, 0.5], [0.25, 0.75], [])
    assert fit.slope == pytest.approx(1.0, rel=1e-12)
    assert fit.dof == 0
    full = drift_fit([0.0, 0.5], [0.25, 0.75], [[0.0, 1.0]])
    assert (full.rank, full.slope, full.influence) == (2, None, None)
    assert drift_fit([0.1], [0.5], []).rho is None
    assert drift_fit([0.1, 0.2], [0.5, 0.5], []).rho is None
    with pytest.raises(ValueError, match="drift_fit"):
        drift_fit([], [], [])
    with pytest.raises(ValueError, match="drift_fit"):
        drift_fit([0.1, 0.2], [0.5], [])


def test_withdrawals() -> None:
    """D12-A : cinq retraits, tous identifiables, de signes différents (oracle) ;
    D12-H : deux retraits d'un intervalle, sans pente ; une ligne : aucun retrait."""
    y, u, f = d12a()
    fits = drift_withdrawals(y, u, [f])
    expected = (
        0.02922345904878163,
        -0.019528709021386006,
        0.029164456572873934,
        0.07785762216713397,
        0.02910545409696622,
    )
    assert [w.count for w in fits] == [4] * 5
    for w, b in zip(fits, expected, strict=True):
        assert w.slope == pytest.approx(b, abs=1e-12)
    pair = drift_withdrawals([0.0, 0.5], [0.25, 0.75], [])
    assert [(w.count, w.slope) for w in pair] == [(1, None), (1, None)]
    assert drift_withdrawals([0.1], [0.5], []) == ()


# --- Temps projeté par régime ---------------------------------------------------------

PROFILE = hand_profile([0.0, 100.0, 200.0, 300.0], [0.0, 10.0, 10.0, 0.0])
TIMELINE = ProjectedTimeline((0.0, 100.0, 200.0, 300.0), (1.0, 2.0, 3.0))


def test_regime_projected_s() -> None:
    """Pentes ``+0,1``, ``0``, ``−0,1`` ; allures 1, 2, 3 s/m : 100, 200, 300 s ; une
    portion de la grille au prorata."""
    assert regime_projected_s(PROFILE, TIMELINE, 0.0, 300.0) == (100.0, 200.0, 300.0)
    assert regime_projected_s(PROFILE, TIMELINE, 50.0, 250.0) == (50.0, 200.0, 150.0)
    assert regime_projected_s(PROFILE, TIMELINE, 120.0, 180.0) == (0.0, 120.0, 0.0)


# --- Le diagnostic --------------------------------------------------------------------


def diagnose(
    observed: list[float],
    model: list[float | None],
    positions: list[float],
    *,
    clock_index: int = 0,
    stops: list[float] | None = None,
) -> DriftDiagnostic:
    clock = CLOCKS[clock_index]
    if stops is None and clock.kind is ClockKind.ELAPSED:
        stops = [0.0] * len(observed)
    v0 = [TIMELINE.time_at(s) for s in positions]
    return drift_diagnostic(
        ModelKind.V0_RAW,
        clock,
        observed_s=observed,
        model_s=model,
        v0_s=v0,
        positions_m=positions,
        origin_m=0.0,
        profile=PROFILE,
        v0_timeline=TIMELINE,
        stops_s=stops,
    )


POSITIONS = [100.0, 200.0, 300.0]
FORECAST: list[float | None] = [100.0, 300.0, 600.0]


@pytest.mark.parametrize(
    ("observed", "model", "positions", "reason"),
    [
        ([], [], [], Unavailability.INSUFFICIENT_SUPPORT),
        (
            [120.0, 330.0],
            [100.0, 100.0],
            [100.0, 100.0],
            Unavailability.INSUFFICIENT_SUPPORT,
        ),
        (
            [120.0, 330.0, 640.0],
            [100.0, None, 600.0],
            POSITIONS,
            Unavailability.MODEL_ERROR,
        ),
        (
            [120.0, 330.0, 640.0],
            [100.0, math.nan, 600.0],
            POSITIONS,
            Unavailability.MODEL_ERROR,
        ),
        (
            [120.0, 330.0, 640.0],
            [100.0, 100.0, 600.0],
            POSITIONS,
            Unavailability.MODEL_ERROR,
        ),
        (
            [120.0, 330.0, 640.0],
            [100.0, 90.0, 600.0],
            POSITIONS,
            Unavailability.MODEL_ERROR,
        ),
        (
            [120.0, 330.0, 640.0],
            [100.0, 300.0, math.inf],
            POSITIONS,
            Unavailability.MODEL_ERROR,
        ),
    ],
)
def test_diagnostic_reasons(
    observed: list[float],
    model: list[float | None],
    positions: list[float],
    reason: Unavailability,
) -> None:
    """Séquence vide ou abscisses égales : support insuffisant ; prévision absente, non
    finie, projection nulle ou négative sur des abscisses croissantes : erreur du
    modèle (D12-K) ; rien d'autre n'est publié."""
    diagnostic = diagnose(observed, model, positions)
    assert diagnostic.unavailability is reason
    assert diagnostic.intervals == ()


def test_zero_time_keeps_intervals_and_cumulative_errors() -> None:
    """D12-L, sous ``M θ1`` : cumuls observés ``(0 ; 20 ; 40)`` ; temps nul, trois
    intervalles, ``C_k = P_k − T_k`` et ``B_k = T_k − c P_k``, ni ajustement ni
    retraits."""
    diagnostic = diagnose([0.0, 20.0, 40.0], FORECAST, POSITIONS, clock_index=1)
    assert diagnostic.unavailability is Unavailability.ZERO_TIME
    assert len(diagnostic.intervals) == 3
    assert diagnostic.cumulative_errors_s == (100.0, 280.0, 560.0)
    c = 40.0 / 600.0
    assert diagnostic.recentred_s == pytest.approx(
        (0.0 - c * 100.0, 20.0 - c * 300.0, 0.0), abs=1e-12
    )
    assert diagnostic.fit is None
    assert diagnostic.withdrawals == ()


def test_available_diagnostic() -> None:
    """Trois intervalles d'un régime chacun : fractions pures, ``u`` aux milieux de v0
    brut, ``R_0`` descente (le plus long), ``C_k``, ``B_k`` ; déplacement et arrêt sous
    l'écoulé."""
    diagnostic = diagnose(
        [120.0, 330.0, 640.0], FORECAST, POSITIONS, stops=[5.0, 0.0, 0.0]
    )
    assert diagnostic.unavailability is None
    assert [iv.fractions for iv in diagnostic.intervals] == [
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    ]
    assert [iv.position for iv in diagnostic.intervals] == pytest.approx(
        [50.0 / 600.0, 200.0 / 600.0, 450.0 / 600.0], rel=1e-15
    )
    assert diagnostic.reference_regime is Regime.DESCENT
    assert diagnostic.cumulative_errors_s == (-20.0, -30.0, -40.0)
    assert diagnostic.intervals[0].moving_s == 115.0
    assert diagnostic.intervals[0].stop_s == 5.0
    assert diagnostic.fit is not None
    assert diagnostic.fit.slope is None  # trois intervalles, trois régimes : rang 3


def test_reference_regime_ties_follow_the_order() -> None:
    """``R_0`` : à temps projetés égaux, l'ordre montée, plat, descente."""
    profile = hand_profile([0.0, 100.0, 200.0], [0.0, 10.0, 0.0])
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
    assert diagnostic.reference_regime is Regime.ASCENT


def test_calibration_invariance() -> None:
    """Précision P12.9 : un modèle multiplié par un facteur (un calage) garde ``b``,
    ``rho_u``, les retraits et ``B_k`` ; seul ``C_k`` change."""
    profile = hand_profile([0.0, 1000.0, 2000.0], [0.0, 30.0, 0.0])
    timeline = ProjectedTimeline((0.0, 1000.0, 2000.0), (0.8, 0.6))
    positions = [300.0, 700.0, 1000.0, 1400.0, 2000.0]
    v0 = [timeline.time_at(s) for s in positions]
    observed = [250.0, 600.0, 830.0, 1100.0, 1500.0]

    def run(factor: float) -> DriftDiagnostic:
        return drift_diagnostic(
            ModelKind.V0_RECALIBRATED,
            CLOCKS[1],
            observed_s=observed,
            model_s=[factor * v for v in v0],
            v0_s=v0,
            positions_m=positions,
            origin_m=0.0,
            profile=profile,
            v0_timeline=timeline,
        )

    base, scaled = run(1.0), run(1.7)
    assert base.fit is not None
    assert scaled.fit is not None
    assert base.fit.slope is not None
    assert scaled.fit.slope == pytest.approx(base.fit.slope, abs=1e-12)
    assert scaled.fit.rho == pytest.approx(base.fit.rho, rel=1e-12)
    assert [w.slope for w in scaled.withdrawals] == pytest.approx(
        [w.slope for w in base.withdrawals], abs=1e-12
    )
    assert scaled.recentred_s == pytest.approx(base.recentred_s, abs=1e-9)
    assert scaled.cumulative_errors_s != base.cumulative_errors_s


# --- La séquence et la sortie (monde synthétique) -------------------------------------


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> BacktestRun:
    return run_world(tmp_path_factory.mktemp("monde"))


def scored(world: BacktestRun) -> list[OutingRun]:
    return [run for run in world.outings if run.scores.usage is not None]


def longest(world: BacktestRun) -> OutingRun:
    return max(scored(world), key=lambda run: len(run.scores.observation.targets))


def test_sequence_is_k_until_the_first_unobserved_element(world: BacktestRun) -> None:
    """Arbitrages E1 et E2 : tout ``K`` observé, arrivée comprise, sans motif ; un
    élément rendu absent coupe la séquence avant lui, avec son motif ; un premier
    élément absent la vide."""
    observation = longest(world).scores.observation
    count = len(observation.targets)
    assert count >= 3
    assert drift_sequence(observation) == (tuple(range(count)), None)
    for at, ranks in ((2, (0, 1)), (0, ())):
        targets = list(observation.targets)
        targets[at] = dataclasses.replace(
            targets[at], times_s=None, unavailability=Unavailability.ABSENT
        )
        cut = dataclasses.replace(observation, targets=tuple(targets))
        assert drift_sequence(cut) == (ranks, Unavailability.ABSENT)


def test_world_outings(world: BacktestRun) -> None:
    """Chaque sortie scorée avec usage a sa dérive : la séquence et l'horizon (le cumul
    de v0 brut au dernier élément) ; cinq modèles par horloge du rapport ; jour
    multi-sorties : ce motif partout ; un modèle non calé : son motif ; une sortie sans
    usage : aucune dérive."""
    seen_multi = False
    for outing in world.outings:
        drift = outing_drift_report(world, outing)
        if outing.scores.usage is None:
            assert drift is None
            continue
        assert drift is not None
        observation = outing.scores.observation
        assert drift.targets == len(observation.targets)
        ranks, stop = drift_sequence(observation)
        assert (drift.elements, drift.stop) == (len(ranks), stop)
        if ranks:
            assert drift.horizon_s == outing.scores.usage.forecast.target_s[ranks[-1]]
        clocks = report_clocks(outing.match)
        assert len(drift.diagnostics) == len(clocks) * len(DRIFT_MODELS)
        for d in drift.diagnostics:
            elapsed = d.clock.kind is ClockKind.ELAPSED
            assert all((iv.stop_s is not None) is elapsed for iv in d.intervals)
        reasons = {d.unavailability for d in drift.diagnostics}
        if reasons == {Unavailability.MULTI_OUTING_DAY}:
            seen_multi = True
        else:
            assert Unavailability.MULTI_OUTING_DAY not in reasons
    assert seen_multi


def test_a_zero_time_under_one_clock_keeps_the_sequence(world: BacktestRun) -> None:
    """D12-G, arbitrage E2 : un cumul nul sous ``M θ1`` au premier élément ne coupe pas
    la séquence ; v0 brut est « temps nul » sous cette horloge, avec ses ``H``
    intervalles, et reste disponible sous l'écoulé."""
    outing = longest(world)
    observation = outing.scores.observation
    clocks = report_clocks(outing.match)
    index = CLOCKS.index(clocks[1])
    first = observation.targets[0]
    assert first.times_s is not None
    times = list(first.times_s)
    times[index] = 0.0
    targets = (
        dataclasses.replace(first, times_s=tuple(times)),
        *observation.targets[1:],
    )
    scores = dataclasses.replace(
        outing.scores, observation=dataclasses.replace(observation, targets=targets)
    )
    outing_id = outing.outing.outing_id
    calibrated = next(
        p for p in world.calibration if any(e.outing_id == outing_id for e in p.outings)
    )
    drift = outing_drift(
        scores,
        outing.passages,
        outing.profile,
        clocks,
        calibrated,
        world.preparation.curve.curve,
        multi_outing=False,
        outing_id=outing_id,
    )
    assert drift is not None
    by_clock = {d.clock: d for d in drift.diagnostics if d.model is ModelKind.V0_RAW}
    assert by_clock[clocks[1]].unavailability is Unavailability.ZERO_TIME
    assert len(by_clock[clocks[1]].intervals) == drift.elements == len(targets)
    assert by_clock[ELAPSED].unavailability is None


def test_world_is_unchanged_on_disk(tmp_path: Path) -> None:
    """La dérive ne lit ni n'écrit : le module n'importe ni ``pathlib`` ni ``os``."""
    source = Path(drift_module.__file__).read_text(encoding="utf-8")
    assert "import os" not in source
    assert "pathlib" not in source


def test_reasons_are_checked_in_order() -> None:
    """Précision P12.4 : les abscisses avant les prévisions — abscisses égales et
    prévision absente : support insuffisant."""
    diagnostic = diagnose([120.0, 330.0], [100.0, None], [100.0, 100.0])
    assert diagnostic.unavailability is Unavailability.INSUFFICIENT_SUPPORT


def test_recentred_uses_the_model_forecast() -> None:
    """``B_k = T_k − c P_k`` avec ``P`` du modèle évalué (pas de v0 brut), ``c = T_H /
    P_H`` ; ``C_k = P_k − T_k``."""
    model: list[float | None] = [110.0, 290.0, 600.0]
    diagnostic = diagnose([120.0, 330.0, 640.0], model, POSITIONS, clock_index=1)
    c = 640.0 / 600.0
    assert diagnostic.recentred_s == pytest.approx(
        (120.0 - c * 110.0, 330.0 - c * 290.0, 0.0), abs=1e-12
    )
    assert diagnostic.cumulative_errors_s == (-10.0, -40.0, -40.0)


def test_calibrated_models_use_their_calibrated_forecast(world: BacktestRun) -> None:
    """Un modèle calé est lu calé (précision P12.4) : ses ``C_k`` sont ``P_k − T_k``
    avec la prévision calée sous l'horloge, pas la prévision brute (la pente et
    ``B_k`` n'en dépendent pas : précision P12.9)."""
    seen = 0
    for outing in world.outings:
        drift = outing_drift_report(world, outing)
        if drift is None or drift.elements == 0:
            continue
        outing_id = outing.outing.outing_id
        calibrated = next(
            p
            for p in world.calibration
            if any(e.outing_id == outing_id for e in p.outings)
        )
        entry = next(
            e.usage
            for e in calibrated.outings
            if e.outing_id == outing_id
            and e.usage is not None
            and e.usage.model is ModelKind.V0_RECALIBRATED
        )
        ranks, _ = drift_sequence(outing.scores.observation)
        for d in drift.diagnostics:
            if d.model is not ModelKind.V0_RECALIBRATED or d.unavailability is not None:
                continue
            index = CLOCKS.index(d.clock)
            values = calibrated_forecast(
                entry.forecast, entry.clocks[index].calibration
            ).target_s
            expected = []
            for k in ranks:
                times = outing.scores.observation.targets[k].times_s
                value = values[k]
                assert times is not None
                assert value is not None
                expected.append(value - times[index])
            assert d.cumulative_errors_s == pytest.approx(expected, abs=1e-9)
            seen += 1
    assert seen > 0


def test_fractions_never_exceed_one() -> None:
    """Oracle de M4d-1, cas M1 : une origine non nulle, des cumuls arrondis ; les
    fractions rapportées à la somme des régimes restent dans ``[0 ; 1]`` (rapportées à
    ``p⁰_h``, la seconde valait ``1 + 2e−16`` et le contrat la refusait)."""
    profile = hand_profile([0.0, 100.0], [0.0, 0.0])
    timeline = ProjectedTimeline((0.0, 100.0), (0.7,))
    forecast: list[float | None] = [1.3999999999999997, 69.3]
    diagnostic = drift_diagnostic(
        ModelKind.V0_RAW,
        CLOCKS[1],
        observed_s=[1.5, 70.0],
        model_s=forecast,
        v0_s=forecast,
        positions_m=[3.0, 100.0],
        origin_m=1.0,
        profile=profile,
        v0_timeline=timeline,
    )
    assert diagnostic.unavailability is None
    assert all(f <= 1.0 for iv in diagnostic.intervals for f in iv.fractions)
    assert [iv.fractions for iv in diagnostic.intervals] == [(0.0, 1.0, 0.0)] * 2


def test_a_truncated_rank_keeps_the_slope() -> None:
    """Oracle de M4d-1, cas M2 : une colonne de fractions presque constante, rang 1
    (le second ``sigma`` vaut ``3,8e−12 sigma_max``) ; ``b = 0,2`` comme l'oracle, et
    ``Σ a_h`` de l'ordre de ``1e−11`` : la constante n'est dans ``Z`` qu'à la tolérance
    près, sans exception."""
    fit = drift_fit(
        (0.0, 0.0, 0.1), (0.25, 0.5, 0.75), [(0.5, 0.5, 0.50000000001), (0.0, 0.0, 0.0)]
    )
    assert fit.rank == 1
    assert fit.slope == pytest.approx(0.2, rel=1e-9)
    assert fit.influence is not None
    assert abs(math.fsum(fit.influence)) < 1e-10


@pytest.mark.parametrize(
    "v0",
    [
        [None, 70.0],
        [math.nan, 70.0],
        [math.inf, 70.0],
        [35.0, math.inf],
        [35.0, 35.0],
        [35.0, 30.0],
    ],
)
def test_invalid_v0_is_a_model_error(v0: list[float | None]) -> None:
    """Oracle de M4d-1, cas M3 : v0 brut sans prévision valide (absente, non finie,
    ``p⁰_h <= 0``) rend le diagnostic de tout modèle « erreur du modèle »."""
    profile = hand_profile([0.0, 100.0], [0.0, 0.0])
    timeline = ProjectedTimeline((0.0, 100.0), (0.7,))
    diagnostic = drift_diagnostic(
        ModelKind.CONSTANT_SPEED,
        CLOCKS[1],
        observed_s=[30.0, 60.0],
        model_s=[25.0, 50.0],
        v0_s=v0,
        positions_m=[50.0, 100.0],
        origin_m=0.0,
        profile=profile,
        v0_timeline=timeline,
    )
    assert diagnostic.unavailability is Unavailability.MODEL_ERROR


@pytest.mark.parametrize(
    ("observed", "model"),
    [
        ([4000.0, 9778.1], [4000.0, 8937.3]),
        (
            [3600.0 * h * 1.03 + 0.3 * h for h in range(1, 31)],
            [3600.0 * h for h in range(1, 31)],
        ),
    ],
)
def test_last_recentred_error_is_exactly_zero(
    observed: list[float], model: list[float]
) -> None:
    """Passe 1 de B, constat 1 : ``B_k = T_k − T_H · (P_k / P_H)`` donne ``B_H = 0``
    au bit. Écrit ``T_k − (T_H / P_H) · P_k``, il valait ``1,8e−12`` s dès ``T_H >=
    8 192 s`` (une unité du dernier chiffre), au-delà de la tolérance du contrat : le
    diagnostic était refusé. Chacun des deux cas le montre seul : deux éléments à
    2 h 43, et trente à 30 h 54."""
    count = len(model)
    profile = hand_profile([0.0, 1000.0 * count], [0.0, 0.0])
    timeline = ProjectedTimeline((0.0, 1000.0 * count), (model[-1] / (1000.0 * count),))
    positions = [1000.0 * (h + 1) for h in range(count)]
    forecast: list[float | None] = list(model)
    diagnostic = drift_diagnostic(
        ModelKind.V0_RAW,
        CLOCKS[1],
        observed_s=observed,
        model_s=forecast,
        v0_s=forecast,
        positions_m=positions,
        origin_m=0.0,
        profile=profile,
        v0_timeline=timeline,
    )
    assert diagnostic.recentred_s[-1] == 0.0
    assert diagnostic.unavailability is None


@pytest.mark.parametrize("shift", [20.0, -3.0])
def test_level_shift_under_a_truncated_rank(shift: float) -> None:
    """Passe 1 de B, constat 5 : sous rang tronqué (cas M2), un niveau ajouté à ``y``
    ne change pas ``b`` à ``1e−12`` près — le rôle du centrage exact de ``u`` et ``y``
    et du numérateur sur ``M_Z y`` (sans eux, l'écart atteint ``1,6e−10``)."""
    args = ((0.25, 0.5, 0.75), [(0.5, 0.5, 0.50000000001), (0.0, 0.0, 0.0)])
    base = drift_fit((0.0, 0.0, 0.1), *args)
    moved = drift_fit((shift, shift, 0.1 + shift), *args)
    assert base.slope is not None
    assert moved.slope == pytest.approx(base.slope, abs=1e-12)


def _drift_of(world: BacktestRun, outing: OutingRun, **changes: Any) -> OutingDrift:
    """``outing_drift`` sur une sortie du monde ; ``changes`` remplace l'observation
    (``observation``) ou les passages (``passages``) — un appui minimal porte
    ``usage`` et ``observation``, que seuls ``outing_drift`` lit."""
    outing_id = outing.outing.outing_id
    calibrated = next(
        p for p in world.calibration if any(e.outing_id == outing_id for e in p.outings)
    )
    scores = SimpleNamespace(
        usage=outing.scores.usage,
        observation=changes.get("observation", outing.scores.observation),
    )
    drift = outing_drift(
        cast(OutingScores, scores),
        changes.get("passages", outing.passages),
        outing.profile,
        report_clocks(outing.match),
        calibrated,
        world.preparation.curve.curve,
        multi_outing=False,
        outing_id=outing_id,
    )
    assert drift is not None
    return drift


def _v0_elapsed(drift: OutingDrift) -> DriftDiagnostic:
    return next(
        d
        for d in drift.diagnostics
        if d.model is ModelKind.V0_RAW and d.clock == ELAPSED
    )


def test_stops_are_departure_minus_arrival(world: BacktestRun) -> None:
    """Passe 1 de B, constat 6 : l'arrêt d'un élément est ``D − A`` de son passage
    (D4.12), pas la somme ``S`` des épisodes attribués : deux épisodes attribués au
    premier passage, ``[c − 42 ; c − 30]`` et ``[c − 20 ; c − 2]``, donnent ``D − A =
    42 s`` (``S = 30 s``) ; le déplacement est ``t_h − 42``."""
    outing = longest(world)
    observation = outing.scores.observation
    index = observation.targets[0].passage_index
    assert index is not None
    passage = outing.passages.passages[index]
    c = passage.crossing_s
    assert c is not None
    episodes = (
        StopEpisode(c - 42.0, c - 30.0, 1, 2),
        StopEpisode(c - 20.0, c - 2.0, 3, 4),
    )
    changed = dataclasses.replace(
        passage, arrival_s=c - 42.0, departure_s=c, stop_total_s=30.0, episode_count=2
    )
    passages = dataclasses.replace(
        outing.passages,
        passages=tuple(
            changed if j == index else p for j, p in enumerate(outing.passages.passages)
        ),
        episodes=tuple(
            EpisodeAttribution(e, EpisodeOutcome.ATTRIBUTED, index, 45.0, 6.0)
            for e in episodes
        ),
    )
    first = _v0_elapsed(_drift_of(world, outing, passages=passages)).intervals[0]
    assert first.stop_s == 42.0
    assert first.moving_s == pytest.approx(first.observed_s - 42.0, abs=1e-9)


def test_origin_is_the_observation_origin(world: BacktestRun) -> None:
    """Passe 1 de B, constat 6 : le premier intervalle part de ``b_0`` de l'observation
    (ici 500 m, les segments et points d'avant retirés), pas de 0."""
    outing = longest(world)
    observation = outing.scores.observation
    moved = dataclasses.replace(
        observation,
        origin_m=500.0,
        segments=tuple(s for s in observation.segments if s.start_m >= 500.0),
        error_points=tuple(
            p for p in observation.error_points if p.distance_m >= 500.0
        ),
    )
    first = _v0_elapsed(_drift_of(world, outing, observation=moved)).intervals[0]
    assert first.start_m == 500.0


def test_an_element_at_the_origin_is_insufficient_support(world: BacktestRun) -> None:
    """Passe 1 de B, constat 3 : un premier élément observé exactement en ``b_0``
    (``P⁰_1 = 0``) donne « support insuffisant » à tous les diagnostics — les abscisses
    avant les prévisions —, pas « erreur du modèle »."""
    outing = longest(world)
    observation = outing.scores.observation
    targets = (
        dataclasses.replace(observation.targets[0], distance_m=observation.origin_m),
        *observation.targets[1:],
    )
    usage = outing.scores.usage
    assert usage is not None
    forecast = dataclasses.replace(
        usage.forecast, target_s=(0.0, *usage.forecast.target_s[1:])
    )
    stub_usage = SimpleNamespace(forecast=forecast)
    drift = outing_drift(
        cast(
            OutingScores,
            SimpleNamespace(
                usage=stub_usage,
                observation=dataclasses.replace(observation, targets=targets),
            ),
        ),
        outing.passages,
        outing.profile,
        report_clocks(outing.match),
        next(
            p
            for p in world.calibration
            if any(e.outing_id == outing.outing.outing_id for e in p.outings)
        ),
        world.preparation.curve.curve,
        multi_outing=False,
        outing_id=outing.outing.outing_id,
    )
    assert drift is not None
    reasons = {d.unavailability for d in drift.diagnostics}
    assert Unavailability.MODEL_ERROR not in reasons
    assert Unavailability.INSUFFICIENT_SUPPORT in reasons
