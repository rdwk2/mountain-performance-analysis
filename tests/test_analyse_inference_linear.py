"""Moindres carrés ordinaires et généralisés, Student, fraction par an
(``mountain_perf.analyse.inference.linear``, AN3-1, ``docs/decisions/0021``) : les cas
H1, H2, H3 et H6 du brief, et des propriétés. Sautés sans numpy ou scipy (extra
``analyse``)."""

from __future__ import annotations

import math
from collections.abc import Callable
from fractions import Fraction
from typing import cast

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

import numpy
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from mountain_perf.analyse.inference.base import FloatArray, InferenceError, Interval
from mountain_perf.analyse.inference.linear import (
    fraction_per_year,
    fraction_per_year_interval,
    gls,
    gls_operator,
    ols,
    student_interval,
)
from test_analyse_inference_base import assert_frozen

EXACT = 1e-12


def _f(numerator: int, denominator: int = 1) -> float:
    return float(Fraction(numerator, denominator))


def _h1() -> tuple[FloatArray, FloatArray]:
    t = numpy.array([0.0, 1.0, 2.0, 3.0])
    return numpy.column_stack([numpy.ones(4), t]), numpy.array([1.0, 3.0, 2.0, 5.0])


H2_V = numpy.array(
    [
        [_f(3, 2), _f(1, 2), _f(1, 8)],
        [_f(1, 2), _f(3, 2), _f(1, 4)],
        [_f(1, 8), _f(1, 4), _f(7, 4)],
    ]
)
H2_X = numpy.column_stack([numpy.ones(3), numpy.array([0.0, 1.0, 3.0])])
H2_Y = numpy.array([0.0, 1.0, 1.0])


def _well_conditioned(X: FloatArray) -> bool:  # noqa: N803
    singular = numpy.linalg.svd(X, compute_uv=False)
    return bool(singular.min() > 1e-6 * singular.max())


@st.composite
def _problems(draw: st.DrawFn) -> tuple[FloatArray, FloatArray]:
    """Une matrice de plan avec constante (``p ≤ 3``, ``n ≤ 30``) et une réponse,
    valeurs dans ``[−100 ; 100]``."""
    p = draw(st.integers(1, 3))
    n = draw(st.integers(p + 2, 30))
    values = st.floats(-100, 100, allow_nan=False, allow_infinity=False)
    columns = draw(arrays(numpy.float64, (n, p - 1), elements=values))
    X = numpy.column_stack([numpy.ones(n), columns])  # noqa: N806
    y = draw(arrays(numpy.float64, n, elements=values))
    assume(_well_conditioned(X))
    return X, y


def test_t4_ols_h1() -> None:
    """T4 : H1, ``coef``, ``resid``, ``scale``, ``cov[1, 1]``, ``df``."""
    X, y = _h1()  # noqa: N806
    fit = ols(X, y)
    assert fit.coef == pytest.approx([1.1, 1.1], rel=EXACT)
    assert fit.resid == pytest.approx([-0.1, 0.8, -1.3, 0.6], rel=EXACT, abs=EXACT)
    assert fit.scale == pytest.approx(1.35, rel=EXACT)
    assert fit.cov[1, 1] == pytest.approx(0.27, rel=EXACT)
    assert fit.df == 2
    assert not fit.coef.flags.writeable
    assert not fit.resid.flags.writeable


@settings(deadline=None, max_examples=100)
@given(_problems())
def test_t4_ols_residuals_are_orthogonal_and_order_free(
    problem: tuple[FloatArray, FloatArray],
) -> None:
    """T4, propriétés : ``Xᵀ·resid = 0`` (à ``1e−8 · max(1, ‖X‖·‖y‖)``), et ``ols``
    invariant par permutation commune des lignes de ``X`` et ``y``."""
    X, y = problem  # noqa: N806
    fit = ols(X, y)
    bound = 1e-8 * max(1.0, float(numpy.linalg.norm(X) * numpy.linalg.norm(y)))
    assert float(numpy.max(numpy.abs(X.T @ fit.resid))) <= bound
    order = numpy.random.default_rng(len(y)).permutation(len(y))
    permuted = ols(X[order], y[order])
    scale = max(1.0, float(numpy.max(numpy.abs(fit.coef))))
    assert permuted.coef == pytest.approx(fit.coef, rel=1e-8, abs=1e-8 * scale)
    assert permuted.resid == pytest.approx(fit.resid[order], rel=1e-7, abs=1e-6)


def test_t5_ols_refuses_bad_designs() -> None:
    """T5 : ``ols`` refuse ``n ≤ p``, une colonne nulle, deux colonnes égales, ``nan``,
    un ``y`` de mauvaise longueur."""
    X, y = _h1()  # noqa: N806
    with pytest.raises(InferenceError, match="n ≤ p"):
        ols(X[:2], y[:2])
    with pytest.raises(InferenceError, match="plein rang"):
        ols(numpy.column_stack([X, numpy.zeros(4)]), y)
    with pytest.raises(InferenceError, match="plein rang"):
        ols(numpy.column_stack([X, X[:, 1]]), y)
    with pytest.raises(InferenceError, match="non finies"):
        ols(X, numpy.array([1.0, math.nan, 2.0, 5.0]))
    with pytest.raises(InferenceError, match="non finies"):
        ols(numpy.where(X == 3.0, math.nan, X), y)
    with pytest.raises(InferenceError, match="y"):
        ols(X, y[:3])


def test_t6_gls_h2() -> None:
    """T6 : H2, ``coef``, ``cov`` et ``resid`` (sur l'échelle d'origine) ;
    ``gls_operator`` rend ``coef``."""
    fit = gls(H2_X, H2_Y, H2_V)
    assert fit.coef == pytest.approx([_f(13, 57), _f(6, 19)], rel=EXACT)
    expected_cov = [[_f(1199, 912), _f(-135, 304)], [_f(-135, 304), _f(101, 304)]]
    assert fit.cov.tolist() == [pytest.approx(row, rel=EXACT) for row in expected_cov]
    assert fit.resid == pytest.approx([_f(-13, 57), _f(26, 57), _f(-10, 57)], rel=EXACT)
    assert fit.scale == 1.0
    assert fit.df == 1
    assert gls_operator(H2_X, H2_V) @ H2_Y == pytest.approx(fit.coef, rel=EXACT)


def test_t7_gls_with_a_multiple_of_the_identity_is_ols() -> None:
    """T7 : H3, ``V = 2·I`` : ``coef`` de ``gls`` = celui d'``ols``,
    ``cov = 2·(XᵀX)⁻¹``,
    ``gls_operator(X, 2·I)·y = coef``."""
    X, y = _h1()  # noqa: N806
    fit = gls(X, y, 2.0 * numpy.eye(4))
    assert fit.coef == pytest.approx(ols(X, y).coef, rel=EXACT)
    assert fit.cov.tolist() == [
        pytest.approx([1.4, -0.6], rel=EXACT),
        pytest.approx([-0.6, 0.4], rel=EXACT),
    ]
    assert gls_operator(X, 2.0 * numpy.eye(4)) @ y == pytest.approx(fit.coef, rel=EXACT)


@st.composite
def _gls_problems(draw: st.DrawFn) -> tuple[FloatArray, FloatArray, FloatArray]:
    X, y = draw(_problems())  # noqa: N806
    n = len(y)
    m = draw(arrays(numpy.float64, (n, n), elements=st.floats(-1, 1)))
    return X, y, m @ m.T + numpy.eye(n)


@settings(deadline=None, max_examples=100)
@given(_gls_problems(), st.floats(0.01, 100))
def test_t8_gls_properties(
    problem: tuple[FloatArray, FloatArray, FloatArray], c: float
) -> None:
    """T8 : ``coef`` de ``gls`` invariant si ``V`` est multipliée par ``c > 0`` et
    ``cov`` multipliée par ``c`` ; invariance par permutation commune des lignes de
    ``X``, ``y`` et de ``V`` ; ``gls_operator(X, V)·X = I``."""
    X, y, V = problem  # noqa: N806
    fit = gls(X, y, V)
    scale = max(1.0, float(numpy.max(numpy.abs(fit.coef))))
    scaled = gls(X, y, c * V)
    assert scaled.coef == pytest.approx(fit.coef, rel=1e-7, abs=1e-8 * scale)
    cov_scale = float(numpy.max(numpy.abs(fit.cov)))
    assert scaled.cov == pytest.approx(c * fit.cov, rel=1e-7, abs=1e-9 * c * cov_scale)
    order = numpy.random.default_rng(len(y)).permutation(len(y))
    permuted = gls(X[order], y[order], V[numpy.ix_(order, order)])
    assert permuted.coef == pytest.approx(fit.coef, rel=1e-7, abs=1e-8 * scale)
    operator = gls_operator(X, V)
    assert operator @ X == pytest.approx(numpy.eye(X.shape[1]), abs=1e-8)


def test_t9_gls_refuses_a_bad_covariance() -> None:
    """T9 : ``gls`` refuse une ``V`` non symétrique, non définie positive, de mauvaise
    taille."""
    with pytest.raises(InferenceError, match="symétrique"):
        gls(H2_X, H2_Y, H2_V + numpy.triu(numpy.full((3, 3), 0.01), 1))
    with pytest.raises(InferenceError, match="définie positive"):
        gls(H2_X, H2_Y, numpy.diag([1.0, 1.0, -1.0]))
    with pytest.raises(InferenceError, match="V"):
        gls(H2_X, H2_Y, numpy.eye(4))


def test_t10_student_interval_and_fraction_per_year_h6() -> None:
    """T10 : H6, Student à 2 ddl sur le coefficient 1 de H1 ; ``fraction_per_year`` et
    ``fraction_per_year_interval`` ; refus de ``se ≤ 0`` et ``df < 1``."""
    t_quantile = 4.302652729749462
    se = math.sqrt(0.27)
    interval = student_interval(1.1, se, 2, 0.95)
    assert interval.low == pytest.approx(1.1 - t_quantile * se, abs=1e-9)
    assert interval.high == pytest.approx(1.1 + t_quantile * se, abs=1e-9)
    assert fraction_per_year(math.log(1.05) / 365.25) == pytest.approx(0.05, rel=EXACT)
    assert fraction_per_year(0.0) == 0.0
    yearly = fraction_per_year_interval(
        Interval(math.log(1.02) / 365.25, math.log(1.05) / 365.25)
    )
    assert yearly.low == pytest.approx(0.02, rel=EXACT)
    assert yearly.high == pytest.approx(0.05, rel=EXACT)
    for bad_se in (0.0, -1.0, math.nan):
        with pytest.raises(InferenceError, match="se"):
            student_interval(1.0, bad_se, 2, 0.95)
    with pytest.raises(InferenceError, match="df"):
        student_interval(1.0, 1.0, 0, 0.95)
    with pytest.raises(InferenceError, match="level"):
        student_interval(1.0, 1.0, 2, 1.0)


@settings(deadline=None, max_examples=100)
@given(
    st.floats(-100, 100),
    st.floats(0.01, 100),
    st.integers(1, 200),
    st.floats(0.01, 0.98),
    st.floats(0.001, 0.01),
)
def test_t10_a_higher_level_gives_a_wider_interval(
    estimate: float, se: float, df: int, level: float, step: float
) -> None:
    """T10, propriété : à niveau plus haut, intervalle plus large, qui contient
    l'autre."""
    narrow = student_interval(estimate, se, df, level)
    wide = student_interval(estimate, se, df, level + step)
    assert wide.low < narrow.low
    assert narrow.high < wide.high


def _rank_ratio(X: FloatArray) -> float:  # noqa: N803
    diagonal = numpy.abs(numpy.diag(numpy.linalg.qr(X, mode="r")))
    return float(diagonal.min() / diagonal.max())


def test_t5_the_rank_threshold() -> None:
    """T5, le seuil de rang (A5) : la seconde colonne vaut la première plus
    ``δ·(1, −1, 1, −1)`` ; le rapport ``min |R_ii| / max |R_ii|`` vaut ``δ`` (calculé) ;
    à ``δ = 1e−9`` (dix fois au-dessus de ``1e−10``) accepté, à ``1e−11`` refusé."""
    ones = numpy.ones(4)
    wiggle = numpy.array([1.0, -1.0, 1.0, -1.0])
    y = numpy.array([1.0, 3.0, 2.0, 5.0])
    above = numpy.column_stack([ones, ones + 1e-9 * wiggle])
    below = numpy.column_stack([ones, ones + 1e-11 * wiggle])
    assert _rank_ratio(above) == pytest.approx(1e-9, rel=1e-3)
    assert _rank_ratio(below) == pytest.approx(1e-11, rel=1e-2)
    ols(above, y)
    with pytest.raises(InferenceError, match="plein rang"):
        ols(below, y)


def test_t9_the_symmetry_threshold_and_a_non_finite_covariance() -> None:
    """T9, le seuil de symétrie (A5) : ``V = 2·I`` plus ``ε`` en ``(0, 1)`` ;
    l'asymétrie relative ``ε / max|V|`` (calculée) à ``1e−11`` refusée, à ``1e−13``
    acceptée ; une ``V`` non finie dans son triangle supérieur, que Cholesky ne lit
    pas, refusée (A2)."""
    X = numpy.column_stack([numpy.ones(3), numpy.array([0.0, 1.0, 3.0])])  # noqa: N806
    for relative, refused in ((1e-11, True), (1e-13, False)):
        V = 2.0 * numpy.eye(3)  # noqa: N806
        V[0, 1] += relative * 2.0
        assert float(numpy.max(numpy.abs(V - V.T)) / numpy.max(numpy.abs(V))) == (
            pytest.approx(relative, rel=1e-3)
        )
        if refused:
            with pytest.raises(InferenceError, match="symétrique"):
                gls(X, H2_Y, V)
        else:
            gls(X, H2_Y, V)
    broken = H2_V.copy()
    broken[0, 1] = math.nan
    with pytest.raises(InferenceError, match="non finies"):
        gls(H2_X, H2_Y, broken)


def test_t6_a_linear_fit_is_frozen() -> None:
    """T6, immuabilité (A4) : la ``LinearFit`` de ``gls``."""
    assert_frozen(gls(H2_X, H2_Y, H2_V))


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (lambda: student_interval(1.0, 1.0, cast(int, True), 0.95), "^df :"),
        (lambda: fraction_per_year(math.nan), "^b_per_day :"),
        (lambda: fraction_per_year(math.inf), "^b_per_day :"),
    ],
)
def test_t10_refusals_at_the_bounds(call: Callable[[], object], match: str) -> None:
    """T10, refus (L4, L5, D1) : ``df`` booléen, pente non finie ; le message nomme
    l'argument."""
    with pytest.raises(InferenceError, match=match):
        call()


def test_t10_acceptances_next_to_the_bounds() -> None:
    """T10, acceptations juste à côté : ``df = 1``, pente nulle."""
    student_interval(1.0, 1.0, 1, 0.95)
    assert fraction_per_year(0.0) == 0.0
