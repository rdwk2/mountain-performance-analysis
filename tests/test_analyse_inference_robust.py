"""La régression de Huber (``mountain_perf.analyse.inference.robust``, AN3-1,
``docs/decisions/0021``) : le cas H12 du brief, l'échelle estimée, l'accord avec les
MCO sans écart au-delà de ``c``, les valeurs de l'oracle de T31, les refus. Sautés sans
numpy ou scipy (extra ``analyse``)."""

from __future__ import annotations

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

import numpy

from mountain_perf.analyse.inference.base import InferenceError
from mountain_perf.analyse.inference.linear import ols
from mountain_perf.analyse.inference.robust import huber

H12_Y = numpy.array([0.0, 0.0, 0.0, 0.0, 10.0])


def test_t29_huber_h12_and_estimated_scale() -> None:
    """T29 : H12 à échelle fixe 1 (``m = c/4 = 0,33625``, 9 itérations) ; à échelle
    estimée, ``y = (0, 1, 2, 3, 100)`` en position seule donne la médiane, 2."""
    fit = huber(numpy.ones((5, 1)), H12_Y, scale=1.0)
    assert fit.coef[0] == pytest.approx(0.33625, abs=1e-9)
    assert fit.iterations == 9
    assert fit.scale == 1.0
    assert fit.weights[:4] == pytest.approx([1.0] * 4)
    assert fit.weights[4] == pytest.approx(1.345 / (10.0 - 0.33625), rel=1e-8)
    assert fit.df == 4
    estimated = huber(numpy.ones((5, 1)), numpy.array([0.0, 1.0, 2.0, 3.0, 100.0]))
    assert estimated.coef[0] == pytest.approx(2.0, abs=1e-6)


def test_t30_huber_without_outliers_is_ols() -> None:
    """T30 : sans écart au-delà de ``c`` (droite plus petit bruit, ``c`` grand),
    ``huber`` rend les ``coef`` des MCO."""
    t = numpy.arange(10.0)
    X = numpy.column_stack([numpy.ones(10), t])  # noqa: N806
    noise = numpy.random.default_rng(30).normal(scale=0.01, size=10)
    y = 0.5 + 2.0 * t + noise
    assert huber(X, y, c=1e6).coef == pytest.approx(ols(X, y).coef, rel=1e-9, abs=1e-9)


def test_t31_huber_oracle_values_and_refusals() -> None:
    """T31 : ``coef``, ``scale`` et ``cov`` (H1) de l'oracle sur une droite à un
    point aberrant ; non-convergence et échelle nulle refusées."""
    X = numpy.column_stack([numpy.ones(8), numpy.arange(8.0)])  # noqa: N806
    y = numpy.array([0.1, 1.2, 1.9, 3.2, 3.9, 5.1, 14.0, 7.0])
    fit = huber(X, y)
    assert fit.coef == pytest.approx(
        [0.08141322427814214, 1.0025619826584697], rel=1e-8, abs=1e-8
    )
    assert fit.scale == pytest.approx(0.16822021442421242, rel=1e-8, abs=1e-8)
    expected = [
        [0.015444157783361213, -0.003088831556672242],
        [-0.003088831556672242, 0.000882523301906355],
    ]
    assert fit.cov.tolist() == [pytest.approx(row, rel=1e-7) for row in expected]
    with pytest.raises(InferenceError, match="convergence"):
        huber(numpy.ones((5, 1)), H12_Y, max_iter=1)
    with pytest.raises(InferenceError, match="échelle nulle"):
        huber(numpy.ones((5, 1)), numpy.zeros(5))
