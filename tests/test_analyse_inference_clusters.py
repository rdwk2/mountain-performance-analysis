"""CR2 et le bootstrap sauvage par grappes
(``mountain_perf.analyse.inference.clusters``, AN3-1, ``docs/decisions/0021``) :
les cas H10 et H11 du brief, la propriété HC2, le levier 1, les tirages en un seul
appel (générateur espion), le chemin énuméré, et la couverture simulée T24. Le
générateur espion vit ici ; les autres fichiers du paquet l'importent. Sautés
sans numpy ou scipy (extra ``analyse``)."""

from __future__ import annotations

import itertools
import math
from fractions import Fraction
from typing import Any, NoReturn, cast

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

import numpy
import numpy.typing
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from mountain_perf.analyse.inference.base import FloatArray, InferenceError, child_rng
from mountain_perf.analyse.inference.clusters import (
    WEBB,
    cluster_weights,
    cr2_cov,
    wild_cluster_interval,
)
from mountain_perf.analyse.inference.linear import ols


class SpyGenerator:
    """Un générateur espion : il note chaque appel d'``integers`` et de
    ``standard_normal`` (nom, arguments par position et par nom), puis délègue au
    générateur qu'il porte. Classe non dérivée, passée par
    ``typing.cast(numpy.random.Generator, …)`` (piège 9 du brief)."""

    def __init__(self, seed: int) -> None:
        self.generator = numpy.random.Generator(numpy.random.PCG64(seed))
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def integers(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("integers", args, kwargs))
        return self.generator.integers(*args, **kwargs)

    def standard_normal(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("standard_normal", args, kwargs))
        return self.generator.standard_normal(*args, **kwargs)

    def as_generator(self) -> numpy.random.Generator:
        return cast(numpy.random.Generator, self)

    def highs(self) -> list[Any]:
        """L'argument ``high`` de chaque appel d'``integers``."""
        return [
            args[1] if len(args) > 1 else kwargs["high"]
            for name, args, kwargs in self.calls
            if name == "integers"
        ]


class RaisingGenerator:
    """Un générateur qui lève à la lecture : il montre qu'un chemin ne tire rien."""

    def integers(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise AssertionError("le générateur ne devait pas être lu")

    def standard_normal(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise AssertionError("le générateur ne devait pas être lu")

    def as_generator(self) -> numpy.random.Generator:
        return cast(numpy.random.Generator, self)


def _clustered(
    seed: int, groups: int, per_group: int
) -> tuple[FloatArray, FloatArray, numpy.typing.NDArray[numpy.int_]]:
    g = numpy.random.default_rng(seed)
    n = groups * per_group
    x = g.normal(size=n)
    labels = numpy.repeat(numpy.arange(groups), per_group)
    y = 1.0 + 0.5 * x + numpy.repeat(g.normal(size=groups), per_group)
    y = y + g.normal(size=n)
    return numpy.column_stack([numpy.ones(n), x]), y, labels


def test_t20_cr2_h10() -> None:
    """T20 : H10, ``cr2_cov = (3/2)·32/36 = 4/3`` (CR0 donnerait 8/9)."""
    X = numpy.ones((6, 1))  # noqa: N806
    y = numpy.array([0.0, 2.0, 1.0, 5.0, 3.0, 7.0])
    fit = ols(X, y)
    cov = cr2_cov(X, fit.resid, numpy.array([0, 0, 1, 1, 2, 2]))
    assert cov[0, 0] == pytest.approx(float(Fraction(4, 3)), rel=1e-12)


@st.composite
def _designs(draw: st.DrawFn) -> tuple[FloatArray, FloatArray]:
    p = draw(st.integers(1, 3))
    n = draw(st.integers(p + 3, 30))
    values = st.floats(-100, 100, allow_nan=False, allow_infinity=False)
    columns = draw(arrays(numpy.float64, (n, p - 1), elements=values))
    X = numpy.column_stack([numpy.ones(n), columns])  # noqa: N806
    singular = numpy.linalg.svd(X, compute_uv=False)
    assume(singular.min() > 1e-6 * singular.max())
    leverage = numpy.diag(X @ numpy.linalg.pinv(X.T @ X) @ X.T)
    assume(float(leverage.max()) < 0.99)
    return X, draw(arrays(numpy.float64, n, elements=values))


@settings(deadline=None, max_examples=100)
@given(_designs())
def test_t20_cr2_with_one_row_per_cluster_is_hc2(
    problem: tuple[FloatArray, FloatArray],
) -> None:
    """T20, propriété : une grappe par ligne, ``cr2_cov = M·Σ x_i x_iᵀ e_i²/(1 −
    h_ii)·M`` (HC2, à ``1e−9``)."""
    X, y = problem  # noqa: N806
    e = ols(X, y).resid
    bread = numpy.linalg.inv(X.T @ X)
    h = numpy.einsum("ij,jk,ik->i", X, bread, X)
    meat = (X * (e**2 / (1.0 - h))[:, None]).T @ X
    expected = bread @ meat @ bread
    got = cr2_cov(X, e, numpy.arange(len(y)))
    scale = max(1e-300, float(numpy.max(numpy.abs(expected))))
    assert got == pytest.approx(expected, rel=1e-9, abs=1e-9 * scale)


def test_t21_a_cluster_with_leverage_one_is_refused() -> None:
    """T21 : une grappe qui porte seule une colonne indicatrice a un levier de 1."""
    X = numpy.column_stack(  # noqa: N806
        [numpy.ones(6), [1.0, 1.0, 0.0, 0.0, 0.0, 0.0], numpy.arange(6.0)]
    )
    y = numpy.array([0.0, 2.0, 1.0, 5.0, 3.0, 7.0])
    with pytest.raises(InferenceError, match="levier de 1"):
        cr2_cov(X, ols(X, y).resid, numpy.array([0, 0, 1, 1, 2, 2]))


def test_t22_cluster_weights_h11() -> None:
    """T22 : H11, ``WEBB`` (moyenne 0, variance 1) ; Rademacher énuméré à ``B = 10``
    et à la frontière ``B = 8``, sans lire ``rng`` ; Webb, un seul
    ``integers(0, 6, size=(B, G))`` ; Rademacher sans énumération, un seul
    ``integers(0, 2, size=(B, G))``."""
    expected = (
        -math.sqrt(1.5),
        -1.0,
        -math.sqrt(0.5),
        math.sqrt(0.5),
        1.0,
        math.sqrt(1.5),
    )
    assert pytest.approx(expected, abs=1e-15) == WEBB
    assert sum(WEBB) == pytest.approx(0.0, abs=1e-15)
    assert sum(w * w for w in WEBB) / 6 == pytest.approx(1.0, rel=1e-15)
    enumeration = [list(row) for row in itertools.product((-1.0, 1.0), repeat=3)]
    for b in (10, 8):
        weights = cluster_weights("rademacher", 3, b, RaisingGenerator().as_generator())
        assert weights.tolist() == enumeration
    spy = SpyGenerator(22)
    webb = cluster_weights("webb", 5, 7, spy.as_generator())
    assert webb.shape == (7, 5)
    assert set(webb.ravel().tolist()) <= set(WEBB)
    assert len(spy.calls) == 1
    name, args, kwargs = spy.calls[0]
    assert name == "integers"
    assert spy.highs() == [6]
    assert (args[0] if args else kwargs["low"]) == 0
    assert kwargs.get("size", args[2] if len(args) > 2 else None) == (7, 5)
    spy = SpyGenerator(22)
    signs = cluster_weights("rademacher", 4, 10, spy.as_generator())
    assert signs.shape == (10, 4)
    assert set(signs.ravel().tolist()) <= {-1.0, 1.0}
    assert len(spy.calls) == 1
    assert spy.highs() == [2]
    _, args, kwargs = spy.calls[0]
    assert kwargs.get("size", args[2] if len(args) > 2 else None) == (10, 4)
    with pytest.raises(InferenceError):
        cluster_weights("normal", 3, 10, RaisingGenerator().as_generator())


def test_t23_wild_cluster_interval_paths() -> None:
    """T23 : refus à 9 grappes, accepté à 10 ; à ``B = 99``, Webb à 10 et 11 grappes,
    Rademacher à 12 (lu par l'espion) ; déterminisme par graine ; intervalle qui
    contient ``coef[j]``, symétrique autour de lui ; le chemin énuméré : à 12 grappes,
    ``B = 4 096`` et ``B = 5 000`` rendent le même intervalle au bit près, sans lire
    ``rng``."""
    X, y, labels = _clustered(23, 9, 3)  # noqa: N806
    with pytest.raises(InferenceError, match="sous 10 grappes"):
        wild_cluster_interval(X, y, labels, 1, 0.95, 99, child_rng(23))
    for groups, high in ((10, 6), (11, 6), (12, 2)):
        X, y, labels = _clustered(23 + groups, groups, 3)  # noqa: N806
        spy = SpyGenerator(groups)
        interval = wild_cluster_interval(X, y, labels, 1, 0.95, 99, spy.as_generator())
        assert spy.highs() == [high]
        assert len(spy.calls) == 1
        coef = float(ols(X, y).coef[1])
        assert interval.low < coef < interval.high
        assert coef - interval.low == pytest.approx(interval.high - coef, rel=1e-9)
        again = wild_cluster_interval(X, y, labels, 1, 0.95, 99, child_rng(groups))
        same = wild_cluster_interval(X, y, labels, 1, 0.95, 99, child_rng(groups))
        assert again == same
    X, y, labels = _clustered(1223, 12, 2)  # noqa: N806
    exact = wild_cluster_interval(
        X, y, labels, 1, 0.95, 4096, RaisingGenerator().as_generator()
    )
    beyond = wild_cluster_interval(
        X, y, labels, 1, 0.95, 5000, RaisingGenerator().as_generator()
    )
    assert exact == beyond


def test_t24_wild_cluster_interval_coverage() -> None:
    """T24 : couverture simulée (graine 20261124, 100 jeux, 12 grappes de 5 lignes,
    ``B = 99``) : entre 96 et 98 intervalles contiennent la pente vraie 0 (oracle :
    97)."""
    g = numpy.random.default_rng(20261124)
    labels = numpy.repeat(numpy.arange(12), 5)
    covered = 0
    for s in range(100):
        x = g.normal(size=60)
        u = g.normal(size=12)
        e = g.normal(size=60)
        X = numpy.column_stack([numpy.ones(60), x])  # noqa: N806
        y = 1.0 + numpy.repeat(u, 5) + e
        interval = wild_cluster_interval(
            X, y, labels, 1, 0.95, 99, child_rng(20261124, s)
        )
        covered += interval.low <= 0.0 <= interval.high
    assert 96 <= covered <= 98
