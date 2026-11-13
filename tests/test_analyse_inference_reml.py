"""La covariance à trois composantes et son REML
(``mountain_perf.analyse.inference.reml``, AN3-1, ``docs/decisions/0021``) : les cas
H2, H4 et H5 du brief, les cas tirés T14, T15 et T15 bis (valeurs de l'oracle de la
conception), des propriétés. Sautés sans numpy ou scipy (extra ``analyse``)."""

from __future__ import annotations

import math
from fractions import Fraction
from functools import cache

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

import numpy
from hypothesis import given, settings
from hypothesis import strategies as st

from mountain_perf.analyse.inference.base import FloatArray, InferenceError
from mountain_perf.analyse.inference.linear import gls
from mountain_perf.analyse.inference.reml import (
    RemlFit,
    reml_criterion,
    reml_fit,
    three_component_cov,
)

EXACT = 1e-12
LN2 = math.log(2.0)

type Case = tuple[FloatArray, FloatArray, FloatArray, FloatArray, tuple[float, float]]


def _f(numerator: int, denominator: int = 1) -> float:
    return float(Fraction(numerator, denominator))


def _h5() -> Case:
    t = numpy.arange(0.0, 60.0, 10.0)
    X = numpy.column_stack([numpy.ones(6), t])  # noqa: N806
    y = numpy.array([(-1.0) ** i for i in range(6)]) + 0.1 * t
    return X, y, t, numpy.full(6, 0.25), (2.0, 25.0)


def _drawn(
    seed: int, days: int, noise_d: float | None, truth: tuple[float, float, float]
) -> Case:
    """Le tirage de T14, T15 et T15 bis, dans l'ordre des appels du brief."""
    g = numpy.random.default_rng(seed)
    t = numpy.sort(g.choice(numpy.arange(days), 60, replace=False)).astype(float)
    d = g.uniform(0.1, 0.4, 60)
    X = numpy.column_stack([numpy.ones(60), (t - t.mean()) / 100])  # noqa: N806
    tau2, s2u, phi = truth
    noise = d if noise_d is None else numpy.full(60, noise_d)
    V = three_component_cov(t, noise, tau2, s2u, phi)  # noqa: N806
    y = X @ numpy.array([1.0, 0.3]) + numpy.linalg.cholesky(V) @ g.standard_normal(60)
    return X, y, t, d, (3.0, 300.0)


def _t14() -> Case:
    return _drawn(20261162, 600, None, (0.5, 2.0, 45.0))


def _t15() -> Case:
    return _drawn(20261168, 600, None, (1.0, 0.06, 300.0))


def _t15_bis() -> Case:
    return _drawn(20261152, 120, 0.01, (0.0, 2.0, 1.0))


CASES = {"t13": _h5, "t14": _t14, "t15": _t15, "t15_bis": _t15_bis}


@cache
def _fit(name: str) -> RemlFit:
    return reml_fit(*CASES[name]())


def _assert_fit_is_the_gls_at_the_estimate(name: str) -> None:
    X, y, t, d, _ = CASES[name]()  # noqa: N806
    result = _fit(name)
    expected = gls(X, y, three_component_cov(t, d, result.tau2, result.s2u, result.phi))
    assert result.fit.coef == pytest.approx(expected.coef, rel=EXACT, abs=EXACT)
    assert result.fit.cov == pytest.approx(expected.cov, rel=EXACT, abs=EXACT)
    assert result.fit.resid == pytest.approx(expected.resid, rel=EXACT, abs=EXACT)


def test_t11_three_component_cov_h2() -> None:
    """T11 : H2, ``three_component_cov`` rend la ``V`` écrite en fractions."""
    V = three_component_cov(  # noqa: N806
        [0.0, 1.0, 3.0], [0.25, 0.25, 0.5], 0.25, 1.0, 1.0 / LN2
    )
    expected = [
        [_f(3, 2), _f(1, 2), _f(1, 8)],
        [_f(1, 2), _f(3, 2), _f(1, 4)],
        [_f(1, 8), _f(1, 4), _f(7, 4)],
    ]
    assert V.tolist() == [pytest.approx(row, rel=EXACT) for row in expected]
    with pytest.raises(InferenceError):
        three_component_cov([0.0, 1.0], [0.1, -0.1], 0.1, 1.0, 1.0)
    with pytest.raises(InferenceError):
        three_component_cov([0.0, 1.0], [0.1, 0.1], 0.1, 1.0, 0.0)


@settings(deadline=None, max_examples=100)
@given(
    st.lists(st.integers(0, 100), min_size=1, max_size=30).flatmap(
        lambda t: st.tuples(
            st.just(t),
            st.lists(st.floats(0, 1), min_size=len(t), max_size=len(t)),
        )
    ),
    st.floats(0.1, 10),
    st.floats(0, 10),
    st.floats(1, 100),
)
def test_t11_three_component_cov_is_a_covariance(
    days_and_d: tuple[list[int], list[float]], tau2: float, s2u: float, phi: float
) -> None:
    """T11, propriétés : symétrique, de diagonale ``d + τ² + σ²_u``, définie positive
    (Cholesky réussit), ``t`` entiers distincts ou non."""
    days, d = days_and_d
    V = three_component_cov(numpy.array(days, float), d, tau2, s2u, phi)  # noqa: N806
    assert numpy.array_equal(V, V.T)
    assert numpy.diag(V) == pytest.approx(numpy.array(d) + tau2 + s2u, rel=EXACT)
    numpy.linalg.cholesky(V)


def test_t12_reml_criterion_h4() -> None:
    """T12 : H4, ``reml_criterion = ln(1207/64) + 3616/1207``."""
    t = numpy.array([0.0, 1.0, 2.0, 3.0])
    X = numpy.column_stack([numpy.ones(4), t])  # noqa: N806
    y = numpy.array([1.0, 3.0, 2.0, 5.0])
    V = three_component_cov(t, numpy.full(4, 0.25), 0.25, 1.0, 1.0 / LN2)  # noqa: N806
    expected = math.log(1207 / 64) + 3616 / 1207
    assert reml_criterion(X, y, V) == pytest.approx(expected, rel=EXACT)
    assert gls(X, y, V).coef == pytest.approx([_f(1256, 1207), _f(83, 71)], rel=EXACT)


def test_t13_reml_at_the_boundary_h5() -> None:
    """T13 : H5, ``s2u`` estimé nul (drapeau), ``φ`` non identifié, ``τ̂² = 157/140`` (à
    ``1e−6``), critère au plus égal à celui de ``(157/140, 0, φ)`` plus ``1e−8`` pour
    chaque ``φ`` de la grille ; ``fit`` = la GLS aux paramètres rendus."""
    X, y, t, d, _ = _h5()  # noqa: N806
    result = _fit("t13")
    assert result.s2u_at_zero
    assert not result.phi_identified
    assert result.tau2 == pytest.approx(_f(157, 140), rel=1e-6)
    for phi, _ in result.profile:
        at_truth = reml_criterion(X, y, three_component_cov(t, d, 157 / 140, 0.0, phi))
        assert result.criterion <= at_truth + 1e-8
    _assert_fit_is_the_gls_at_the_estimate("t13")


T14_PROFILE = (
    116.99133342375183,
    112.33200418430606,
    107.63168733594378,
    103.49631627789867,
    100.69509657853129,
    99.46777462438929,
    99.49779532465062,
    100.17737248379639,
    100.97920731808233,
    101.63237209294026,
    102.0739267494876,
    102.33892768624287,
)


def test_t14_reml_on_a_well_identified_case() -> None:
    """T14 : le cas bien identifié (graine 20261162) : paramètres à ``1e−3`` de
    l'oracle, critère au plus égal au sien plus ``1e−8``, ``φ`` identifié, aucun
    drapeau de borne ; le profil (``φ_k = 3·100^(k/11)`` et ses critères à ``1e−6``) ;
    ``fit`` = la GLS aux paramètres rendus."""
    result = _fit("t14")
    assert result.tau2 == pytest.approx(0.38025200900604716, rel=1e-3)
    assert result.s2u == pytest.approx(2.4382176262129898, rel=1e-3)
    assert result.phi == pytest.approx(29.2820201555651, rel=1e-3)
    assert result.criterion <= 99.35980722030156 + 1e-8
    assert result.phi_identified
    assert not result.tau2_at_zero
    assert not result.s2u_at_zero
    assert not result.phi_at_lower
    assert not result.phi_at_upper
    assert result.phi_bounds == (3.0, 300.0)
    assert len(result.profile) == 12
    for k, (phi_k, criterion) in enumerate(result.profile):
        assert phi_k == pytest.approx(3.0 * 100.0 ** (k / 11), rel=EXACT)
        assert criterion == pytest.approx(T14_PROFILE[k], abs=1e-6)
    _assert_fit_is_the_gls_at_the_estimate("t14")


def test_t15_reml_with_phi_at_the_upper_bound() -> None:
    """T15 : ``φ`` à la borne haute et rapport faible (graine 20261168) ; ``φ``
    identifié au seuil 0,01 ; bornes de ``φ`` invalides et ajustement exact
    refusés."""
    result = _fit("t15")
    assert result.phi_at_upper
    assert result.phi == pytest.approx(300.0, abs=1e-9)
    assert result.s2u / (result.tau2 + result.s2u) == pytest.approx(0.0477, abs=5e-4)
    assert result.tau2 == pytest.approx(1.1791133031662657, rel=1e-3)
    assert result.s2u == pytest.approx(0.05910641395460142, rel=1e-3)
    assert result.phi_identified
    X, y, t, d, _ = _h5()  # noqa: N806
    for bounds in [(0.0, 1.0), (5.0, 5.0), (5.0, 2.0), (-1.0, 2.0), (1.0, math.inf)]:
        with pytest.raises(InferenceError, match="phi_bounds"):
            reml_fit(X, y, t, d, bounds)
    line = numpy.arange(6.0)
    with pytest.raises(InferenceError, match="ajustement exact"):
        reml_fit(
            numpy.column_stack([numpy.ones(6), line]),
            numpy.zeros(6),
            line,
            numpy.full(6, 0.25),
            (2.0, 25.0),
        )


def test_t15_bis_reml_with_tau2_at_zero_and_phi_at_the_lower_bound() -> None:
    """T15 bis : ``τ²`` à 0 et ``φ`` à la borne basse (graine 20261152)."""
    result = _fit("t15_bis")
    assert result.tau2_at_zero
    assert result.phi_at_lower
    assert result.phi == pytest.approx(3.0, abs=1e-9)
    assert not result.s2u_at_zero
    assert not result.phi_at_upper
    assert result.phi_identified
    assert result.s2u == pytest.approx(1.9762186072478078, rel=1e-3)


def test_t16_reml_is_deterministic() -> None:
    """T16 : deux appels, mêmes sorties au bit près."""
    first, second = reml_fit(*_h5()), reml_fit(*_h5())
    assert (first.tau2, first.s2u, first.phi, first.criterion) == (
        second.tau2,
        second.s2u,
        second.phi,
        second.criterion,
    )
    assert first.profile == second.profile
    assert numpy.array_equal(first.fit.coef, second.fit.coef)
    assert numpy.array_equal(first.fit.cov, second.fit.cov)


@pytest.mark.parametrize("name", sorted(CASES))
def test_t16_the_criterion_is_at_most_the_best_of_the_profile(name: str) -> None:
    """T16, propriété (T13, T14, T15, T15 bis) : ``criterion`` au plus égal au plus
    petit critère du profil plus ``1e−10``."""
    result = _fit(name)
    assert result.criterion <= min(c for _, c in result.profile) + 1e-10
