"""La simulation de puissance et le seuil calibré
(``mountain_perf.analyse.inference.power``, AN3-1, ``docs/decisions/0021``) : les cas
H16 et H17 du brief, les graines par ``(i, k)``, le générateur propre d'``estimate``,
l'indépendance au nombre de processus, les comptes de ``power_table``. Les fonctions
passées aux processus sont de premier niveau (contexte « spawn »). Sautés sans numpy
ou scipy (extra ``analyse``)."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, cast

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

import numpy
import scipy.stats

from mountain_perf.analyse.inference.base import InferenceError, child_rng
from mountain_perf.analyse.inference.power import (
    CalibratedAlpha,
    Outcome,
    PowerRow,
    calibrate_alpha,
    power_table,
    simulate_power,
    smallest_visible_effect,
)
from mountain_perf.analyse.inference.readings import Reading
from test_analyse_inference_base import assert_frozen

ESTABLISHED = Reading.ESTABLISHED
NO_EFFECT = Reading.NO_USEFUL_EFFECT
UNDECIDED = Reading.UNDECIDED


def normal_draw(b: float, rng: numpy.random.Generator) -> float:
    """H16 : ``b`` plus un bruit normal centré réduit."""
    return b + float(rng.standard_normal())


def threshold_estimate(
    x: float, alphas: tuple[float, ...], rng: numpy.random.Generator
) -> Outcome:
    """H16 : « établi » si ``|x| > Φ⁻¹(1 − alpha/2)``, de sens ``signe(x)`` ;
    ``rng`` n'est pas lu."""
    readings = []
    directions = []
    for alpha in alphas:
        if abs(x) > float(scipy.stats.norm.ppf(1.0 - alpha / 2.0)):
            readings.append(ESTABLISHED)
            directions.append(1 if x > 0 else -1)
        else:
            readings.append(UNDECIDED)
            directions.append(0)
    return Outcome(x, tuple(readings), tuple(directions))


def seed_draw(b: float, rng: numpy.random.Generator) -> int:
    """T35 : la première valeur du générateur de ``simulate``."""
    return int(rng.integers(1 << 30))


def data_estimate(
    data: int, alphas: tuple[float, ...], rng: numpy.random.Generator
) -> Outcome:
    """T35 : rend la donnée simulée."""
    return Outcome(float(data), (UNDECIDED,) * len(alphas), (0,) * len(alphas))


def rng_estimate(
    data: int, alphas: tuple[float, ...], rng: numpy.random.Generator
) -> Outcome:
    """T35 : rend la première valeur du générateur d'``estimate``."""
    value = float(rng.integers(1 << 30))
    return Outcome(value, (UNDECIDED,) * len(alphas), (0,) * len(alphas))


def test_t34_power_on_a_known_law_h16() -> None:
    """T34 : H16, puissance à ``b = 2`` près de ``Φ(2 − 1,96)`` (à
    ``4·√(p(1 − p)/2 000)``), erreur S sous 0,01, taux à ``b = 0`` à ``0,05 ± 0,02`` ;
    ``workers = 1`` et ``workers = 2`` rendent les mêmes résultats."""
    args = (normal_draw, threshold_estimate, (0.0, 2.0), (0.05,), 2000, 20261112)
    outcomes = simulate_power(*args)
    rows = power_table((0.0, 2.0), outcomes)
    expected = float(scipy.stats.norm.cdf(2.0 - 1.959964))
    assert rows[1].power is not None
    assert rows[1].power == pytest.approx(
        expected, abs=4 * math.sqrt(expected * (1 - expected) / 2000)
    )
    assert rows[1].s_error is not None
    assert rows[1].s_error <= 0.01
    assert rows[0].p_established == pytest.approx(0.05, abs=0.02)
    assert simulate_power(*args, workers=2) == outcomes


def test_t35_seeds_depend_on_i_and_k_only() -> None:
    """T35, avec un ``key`` non vide : ``simulate`` tire sous
    ``child_rng(root_seed, *key, i, k)``, ``estimate`` sous
    ``child_rng(root_seed, *key, i, k, 1)`` ; ``workers = 2`` = ``workers = 1``."""
    key = (7, 3)
    b_values = (0.0, 0.5, 1.0)
    for estimate, extra in ((data_estimate, ()), (rng_estimate, (1,))):
        outcomes = simulate_power(
            seed_draw, estimate, b_values, (0.05, 0.01), 4, 99, key=key
        )
        assert len(outcomes) == 3
        for i, draws in enumerate(outcomes):
            assert len(draws) == 4
            for k, outcome in enumerate(draws):
                rng = child_rng(99, *key, i, k, *extra)
                assert outcome.estimate == float(rng.integers(1 << 30))
        parallel = simulate_power(
            seed_draw, estimate, b_values, (0.05, 0.01), 4, 99, key=key, workers=2
        )
        assert parallel == outcomes


def _outcome(estimate: float, reading: Reading, direction: int) -> Outcome:
    return Outcome(estimate, (reading,), (direction,))


T36_OUTCOMES = (
    _outcome(0.2, ESTABLISHED, 1),
    _outcome(0.3, ESTABLISHED, 1),
    _outcome(-0.25, ESTABLISHED, -1),
    _outcome(0.01, NO_EFFECT, 0),
    _outcome(-0.01, NO_EFFECT, 0),
    *(_outcome(0.05, UNDECIDED, 0) for _ in range(5)),
)


def test_t36_power_table_counts() -> None:
    """T36 : 3 « établi » (deux de sens +1, un de sens −1), 2 « absence d'effet
    utile », 5 « non tranché » ; à ``b = 0,1``, ``b = −0,1`` et ``b = 0``."""
    rows = power_table((0.1, -0.1, 0.0), (T36_OUTCOMES,) * 3)
    plus, minus, zero = rows
    for row in rows:
        assert row.n_draws == 10
        assert row.p_established == pytest.approx(0.3, rel=1e-12)
        assert row.p_no_useful_effect == pytest.approx(0.2, rel=1e-12)
        assert row.mc_se_established == pytest.approx(math.sqrt(0.021), rel=1e-12)
    assert plus.power == pytest.approx(0.2, rel=1e-12)
    assert plus.s_error == pytest.approx(1 / 3, rel=1e-12)
    assert plus.m_error == pytest.approx(2.5, rel=1e-12)
    assert minus.power == pytest.approx(0.1, rel=1e-12)
    assert minus.s_error == pytest.approx(2 / 3, rel=1e-12)
    assert minus.m_error == pytest.approx(2.5, rel=1e-12)
    assert (zero.power, zero.s_error, zero.m_error) == (None, None, None)


def _row(b: float, power: float | None) -> PowerRow:
    return PowerRow(b, 10, 0.0, 0.0, 0.0, power, None, None)


def test_t37_smallest_visible_effect() -> None:
    """T37 : le plus petit ``|b|`` de puissance ≥ 0,8, sur la grille, sans
    interpolation ; ``None`` sans puissance suffisante."""
    grid = [_row(0.0, None), _row(0.1, 0.5), _row(0.2, 0.8), _row(0.3, 0.95)]
    assert smallest_visible_effect(grid) == 0.2
    signed = [_row(-0.3, 0.95), _row(-0.1, 0.85), _row(0.0, None), _row(0.2, 0.5)]
    assert smallest_visible_effect(signed) == 0.1
    weak = [_row(b, 0.5) for b in (0.1, 0.2, 0.3)]
    assert smallest_visible_effect(weak) is None


def _scenario(counts: tuple[int, ...], size: int) -> tuple[Outcome, ...]:
    """``size`` résultats, « établi » chez les ``counts[j]`` premiers au seuil ``j``."""
    return tuple(
        Outcome(
            0.0,
            tuple(ESTABLISHED if k < c else UNDECIDED for c in counts),
            tuple(1 if k < c else 0 for c in counts),
        )
        for k in range(size)
    )


def test_t38_calibrated_alpha_h17() -> None:
    """T38 : H17 (déclenché, ``alpha = 0,01``), non déclenché, non calibrable, le plus
    grand des seuils admissibles (``alpha = 0,03``) ; à la borne, 3 sur 40 au seuil
    nominal n'est pas déclenché."""
    alphas = (0.05, 0.03, 0.01)
    result = calibrate_alpha(
        [_scenario((4, 2, 1), 20), _scenario((2, 1, 0), 20)], alphas, 0.05
    )
    assert result.rates == pytest.approx((0.2, 0.1, 0.05), rel=1e-12)
    assert result.nominal_rate == pytest.approx(0.2, rel=1e-12)
    assert result.triggered
    assert result.alpha == 0.01
    calm = calibrate_alpha(
        [_scenario((1, 0, 0), 20), _scenario((1, 0, 0), 20)], alphas, 0.05
    )
    assert calm == CalibratedAlpha(0.05, False, 0.05, (0.05, 0.0, 0.0))
    hopeless = calibrate_alpha([_scenario((20, 20, 20), 20)], alphas, 0.05)
    assert hopeless.triggered
    assert hopeless.alpha is None
    largest = calibrate_alpha([_scenario((4, 1, 0), 20)], alphas, 0.05)
    assert largest.rates == pytest.approx((0.2, 0.05, 0.0), rel=1e-12)
    assert largest.nominal_rate == pytest.approx(0.2, rel=1e-12)
    assert largest.alpha == 0.03
    border = calibrate_alpha([_scenario((3, 0, 0), 40)], alphas, 0.05)
    assert border.rates[0] == 0.075
    assert not border.triggered
    assert border.alpha == 0.05


def test_t36_each_row_reads_its_b_and_the_refusals() -> None:
    """T36 (L3) : chaque ``PowerRow.b`` vaut le ``b`` de sa ligne ; des longueurs
    différentes et une liste de tirages vide sont refusées."""
    b_values = (0.1, -0.1, 0.0)
    rows = power_table(b_values, (T36_OUTCOMES,) * 3)
    assert tuple(row.b for row in rows) == b_values
    with pytest.raises(InferenceError, match=r"^outcomes :"):
        power_table((0.1, 0.2), (T36_OUTCOMES,))
    with pytest.raises(InferenceError, match=r"^outcomes :"):
        power_table((0.1,), ((),))


def test_t38_the_refusals_of_calibrate_alpha() -> None:
    """T38 (L3) : deux seuils égaux, aucun scénario, un scénario vide : refusés."""
    with pytest.raises(InferenceError, match=r"^alphas :"):
        calibrate_alpha([_scenario((1, 1), 20)], (0.05, 0.05), 0.05)
    with pytest.raises(InferenceError, match=r"^null_outcomes :"):
        calibrate_alpha([], (0.05,), 0.05)
    with pytest.raises(InferenceError, match=r"^null_outcomes :"):
        calibrate_alpha([()], (0.05,), 0.05)


def test_t36_the_outputs_are_frozen() -> None:
    """T36, T38, immuabilité (A4) : un ``Outcome``, un ``PowerRow``, un
    ``CalibratedAlpha``."""
    assert_frozen(T36_OUTCOMES[0])
    assert_frozen(power_table((0.1,), (T36_OUTCOMES,))[0])
    assert_frozen(calibrate_alpha([_scenario((1,), 20)], (0.05,), 0.05))


def _simulate(**kwargs: Any) -> tuple[tuple[Outcome, ...], ...]:
    arguments: dict[str, Any] = {
        "simulate": normal_draw,
        "estimate": threshold_estimate,
        "b_values": (0.0,),
        "alphas": (0.05,),
        "n_draws": 1,
        "root_seed": 1,
    }
    return simulate_power(**{**arguments, **kwargs})


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (lambda: _simulate(workers=0), "^workers :"),
        (lambda: _simulate(workers=True), "^workers :"),
        (lambda: _simulate(workers=1.5), "^workers :"),
        (lambda: _simulate(alphas=(0.0,)), "^alphas :"),
        (lambda: _simulate(alphas=(0.05, 1.0)), "^alphas :"),
        (lambda: _simulate(n_draws=0), "^n_draws :"),
        (
            lambda: calibrate_alpha(
                [_scenario((1,), 20)], (0.05,), 0.05, trigger=math.nan
            ),
            "^trigger :",
        ),
        (
            lambda: calibrate_alpha([_scenario((1,), 20)], (0.05,), 0.05, trigger=0.0),
            "^trigger :",
        ),
        (
            lambda: calibrate_alpha([_scenario((1,), 20)], (0.05,), 0.05, trigger=1.0),
            "^trigger :",
        ),
        (
            lambda: calibrate_alpha([_scenario((1,), 20)], (0.05,), math.inf),
            "^alpha_target :",
        ),
        (
            lambda: calibrate_alpha([_scenario((1,), 20)], (0.05,), 0.0),
            "^alpha_target :",
        ),
        (
            lambda: calibrate_alpha([_scenario((1,), 20)], (0.05,), 1.0),
            "^alpha_target :",
        ),
        (lambda: smallest_visible_effect([], 0.0), "^target :"),
        (lambda: smallest_visible_effect([], 1.0 + 1e-12), "^target :"),
        (lambda: smallest_visible_effect([], math.nan), "^target :"),
        (lambda: power_table((0.1,), (T36_OUTCOMES,), alpha_index=1), "^alpha_index :"),
        (
            lambda: power_table((0.1,), (T36_OUTCOMES,), alpha_index=-1),
            "^alpha_index :",
        ),
        (
            lambda: power_table((0.1,), (T36_OUTCOMES,), alpha_index=cast(int, True)),
            "^alpha_index :",
        ),
    ],
)
def test_t35_refusals_at_the_bounds(call: Callable[[], object], match: str) -> None:
    """T35 à T38, refus aux bornes (L4, L5, D1) : ``workers`` 0, booléen ou non
    entier, ``alphas`` contenant 0 ou 1, ``n_draws = 0``, ``trigger`` et
    ``alpha_target`` non finis ou hors de ``]0 ; 1[``, ``target`` hors de ``]0 ; 1]``,
    ``alpha_index`` hors des lectures ou booléen ; le message nomme l'argument."""
    with pytest.raises(InferenceError, match=match):
        call()


def test_t35_acceptances_next_to_the_bounds() -> None:
    """T35 à T38, acceptations juste à côté : ``n_draws = 1``, ``workers = 1``,
    ``target = 1``, ``alpha_index = 0``, ``trigger`` et ``alpha_target`` dans
    ``]0 ; 1[``."""
    assert len(_simulate(n_draws=1, workers=1)) == 1
    assert smallest_visible_effect([], 1.0) is None
    assert power_table((0.1,), (T36_OUTCOMES,), alpha_index=0)[0].b == 0.1
    calibrate_alpha([_scenario((1,), 20)], (0.05,), 1e-9, trigger=1 - 1e-9)
