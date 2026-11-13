"""Le bootstrap paramétrique, le bootstrap sauvage des résidus et la bande max-t
(``mountain_perf.analyse.inference.bootstrap``, AN3-1, ``docs/decisions/0021``) : les
tirages en un seul appel (générateur espion), les moments simulés, les cas H14 et H14
ter du brief, la bande ponctuelle contenue, la couverture simultanée T28 bis. Sautés
sans numpy ou scipy (extra ``analyse``)."""

from __future__ import annotations

import math

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

import numpy
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from mountain_perf.analyse.inference.base import (
    FloatArray,
    InferenceError,
    child_rng,
    order_quantile,
)
from mountain_perf.analyse.inference.bootstrap import (
    max_t_band,
    parametric_draws,
    wild_residual_draws,
)
from mountain_perf.analyse.inference.linear import gls_operator, ols
from test_analyse_inference_base import assert_frozen
from test_analyse_inference_clusters import SpyGenerator

EXACT = 1e-12
H14_DRAWS = numpy.array(
    [[1.0, 2.0], [-1.0, 0.0], [2.0, -2.0], [0.0, 4.0], [-2.0, -4.0]]
)


def _size(spy: SpyGenerator) -> object:
    _, args, kwargs = spy.calls[0]
    return kwargs.get("size", args[-1] if args else None)


def test_t25_parametric_draws() -> None:
    """T25 : un seul ``standard_normal(size=(B, n))`` ; moyenne empirique à 0,1 de
    ``mean`` et covariance empirique entière à 0,2 de ``V`` (graine 20261125,
    ``B = 20 000``)."""
    V = numpy.array([[4.0, 2.0], [2.0, 9.0]])  # noqa: N806
    mean = numpy.array([1.0, -2.0])
    spy = SpyGenerator(25)
    draws = parametric_draws(mean, V, 7, spy.as_generator())
    assert draws.shape == (7, 2)
    assert [name for name, _, _ in spy.calls] == ["standard_normal"]
    assert _size(spy) == (7, 2)
    Y = parametric_draws(mean, V, 20000, numpy.random.default_rng(20261125))  # noqa: N806
    assert Y.mean(axis=0) == pytest.approx(mean, abs=0.1)
    assert numpy.cov(Y, rowvar=False) == pytest.approx(V, abs=0.2)


def test_t26_wild_residual_draws() -> None:
    """T26 : ``|Y − fitted| = |resid|`` partout ; un seul
    ``integers(0, 2, size=(B, n))``."""
    fitted = numpy.array([1.0, 2.0, 3.0, 4.0])
    resid = numpy.array([0.5, -1.5, 0.0, 2.25])
    spy = SpyGenerator(26)
    Y = wild_residual_draws(fitted, resid, 50, spy.as_generator())  # noqa: N806
    assert Y.shape == (50, 4)
    assert numpy.array_equal(
        numpy.abs(Y - fitted), numpy.tile(numpy.abs(resid), (50, 1))
    )
    assert len(spy.calls) == 1
    assert spy.highs() == [2]
    assert _size(spy) == (50, 4)


def test_t27_max_t_band_h14() -> None:
    """T27 : H14 (``critical = 2/√2,5``, bande ``(−2, −4)`` à ``(2, 4)``), une colonne
    constante exclue, la translation de la première colonne ; H14 ter (``critical =
    3/√10``) ; ``B < 2`` et tout exclu refusés."""
    band = max_t_band([0.0, 0.0], H14_DRAWS, 0.6)
    assert band.critical == pytest.approx(2 / math.sqrt(2.5), rel=EXACT)
    assert band.critical == pytest.approx(4 / math.sqrt(10), rel=EXACT)
    assert band.low == pytest.approx([-2.0, -4.0], rel=EXACT)
    assert band.high == pytest.approx([2.0, 4.0], rel=EXACT)
    assert band.excluded == ()
    constant = numpy.column_stack([H14_DRAWS, numpy.full(5, 5.0)])
    band = max_t_band([0.0, 0.0, 5.0], constant, 0.6)
    assert band.excluded == (2,)
    assert band.low == pytest.approx([-2.0, -4.0, 5.0], rel=EXACT)
    assert band.high == pytest.approx([2.0, 4.0, 5.0], rel=EXACT)
    band = max_t_band([3.0, 0.0], H14_DRAWS + numpy.array([3.0, 0.0]), 0.6)
    assert band.low == pytest.approx([1.0, -4.0], rel=EXACT)
    assert band.high == pytest.approx([5.0, 4.0], rel=EXACT)
    band = max_t_band([0.0, 1.0], H14_DRAWS, 0.6)
    assert band.critical == pytest.approx(3 / math.sqrt(10), rel=EXACT)
    assert band.low == pytest.approx([-1.5, -2.0], rel=EXACT)
    assert band.high == pytest.approx([1.5, 4.0], rel=EXACT)
    with pytest.raises(InferenceError, match="2 tirages"):
        max_t_band([0.0, 0.0], H14_DRAWS[:1], 0.6)
    with pytest.raises(InferenceError, match="dispersion"):
        max_t_band([5.0], numpy.full((5, 1), 5.0), 0.6)


@settings(deadline=None, max_examples=100)
@given(
    st.integers(2, 30).flatmap(
        lambda b: st.integers(1, 5).flatmap(
            lambda m: st.tuples(
                arrays(numpy.float64, (b, m), elements=st.floats(-100, 100)),
                arrays(numpy.float64, m, elements=st.floats(-100, 100)),
            )
        )
    ),
    st.floats(0.05, 0.99),
)
def test_t28_the_max_t_band_contains_the_pointwise_band(
    data: tuple[FloatArray, FloatArray], level: float
) -> None:
    """T28, propriété : la bande max-t contient la bande point par point au même
    niveau (bornes ponctuelles par ``order_quantile`` des ``|draws − estimate|/se*``
    colonne par colonne)."""
    draws, estimate = data
    spread = draws.std(axis=0, ddof=1)
    assume(bool(numpy.any(spread > 0)))
    band = max_t_band(estimate, draws, level)
    for x in range(len(estimate)):
        if spread[x] == 0:
            continue
        c_x = order_quantile(numpy.abs(draws[:, x] - estimate[x]) / spread[x], level)
        tolerance = 1e-9 * max(1.0, abs(estimate[x]) + band.critical * spread[x])
        assert band.low[x] <= estimate[x] - c_x * spread[x] + tolerance
        assert estimate[x] + c_x * spread[x] <= band.high[x] + tolerance


def test_t28_bis_simultaneous_coverage() -> None:
    """T28 bis : couverture simultanée simulée (graine 20261128, 200 jeux, droite sur
    30 points, grille de 11 points, 199 tirages sauvages des résidus) : entre 181 et
    183 jeux où la courbe vraie tient dans la bande en chaque point (oracle : 182)."""
    x = numpy.linspace(0.0, 1.0, 30)
    X = numpy.column_stack([numpy.ones(30), x])  # noqa: N806
    u = numpy.linspace(0.0, 1.0, 11)
    G = numpy.column_stack([numpy.ones(11), u])  # noqa: N806
    truth = G @ numpy.array([1.0, 2.0])
    A = gls_operator(X, numpy.eye(30))  # noqa: N806
    g = numpy.random.default_rng(20261128)
    covered = 0
    for s in range(200):
        y = 1.0 + 2.0 * x + g.normal(size=30)
        f = ols(X, y)
        Y = wild_residual_draws(X @ f.coef, f.resid, 199, child_rng(20261128, s))  # noqa: N806
        curves = (Y @ A.T) @ G.T
        band = max_t_band(G @ f.coef, curves, 0.95)
        covered += bool(numpy.all((band.low <= truth) & (truth <= band.high)))
    assert 181 <= covered <= 183


def test_t25_the_draws_follow_the_formula() -> None:
    """T25, la formule et non seulement la loi (L1) : avec un générateur jumeau (même
    graine, même ``standard_normal(size=(B, n))``), les tirages valent
    ``mean + Z·Lᵀ`` à ``1e−12`` ; une ``V`` non finie dans son triangle supérieur est
    refusée (A2)."""
    V = numpy.array([[4.0, 2.0], [2.0, 9.0]])  # noqa: N806
    mean = numpy.array([1.0, -2.0])
    draws = parametric_draws(mean, V, 50, numpy.random.default_rng(2025))
    z = numpy.random.default_rng(2025).standard_normal(size=(50, 2))
    expected = mean + z @ numpy.linalg.cholesky(V).T
    assert draws == pytest.approx(expected, rel=1e-12, abs=1e-12)
    broken = numpy.array(
        [[1.5, math.nan, 0.125], [0.5, 1.5, 0.25], [0.125, 0.25, 1.75]]
    )
    with pytest.raises(InferenceError, match="non finies"):
        parametric_draws(numpy.zeros(3), broken, 5, numpy.random.default_rng(1))


def test_t26_the_draws_follow_the_formula() -> None:
    """T26, la formule (L1) : avec un jumeau (même ``integers(0, 2, size=(B, n))``),
    les tirages valent exactement ``fitted + S·resid``."""
    fitted = numpy.array([1.0, 2.0, 3.0, 4.0])
    resid = numpy.array([0.5, -1.5, 0.25, 2.25])
    draws = wild_residual_draws(fitted, resid, 40, numpy.random.default_rng(2026))
    signs = 2 * numpy.random.default_rng(2026).integers(0, 2, size=(40, 4)) - 1
    assert numpy.array_equal(draws, fitted + signs * resid)


def test_t27_a_band_is_frozen() -> None:
    """T27, immuabilité (A4) : une ``Band``."""
    assert_frozen(max_t_band([0.0, 0.0], H14_DRAWS, 0.6))


def test_t25_refusals_and_acceptances_at_the_bounds() -> None:
    """T25, aux bornes (L4, L5) : ``B = 0`` refusé (message qui nomme ``B``),
    ``B = 1`` accepté."""
    with pytest.raises(InferenceError, match=r"^B :"):
        parametric_draws([0.0], [[1.0]], 0, numpy.random.default_rng(1))
    assert parametric_draws([0.0], [[1.0]], 1, numpy.random.default_rng(1)).shape == (
        1,
        1,
    )
