"""CR2 et le bootstrap sauvage par grappes
(``mountain_perf.analyse.inference.clusters``, AN3-1, ``docs/decisions/0021``) :
les cas H10 et H11 du brief, la propriété HC2, le levier 1, les tirages en un seul
appel (générateur espion), le chemin énuméré, et la couverture simulée T24. Le
générateur espion vit ici ; les autres fichiers du paquet l'importent. Sautés
sans numpy ou scipy (extra ``analyse``)."""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable
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
    bell_mccaffrey_df,
    cluster_weights,
    cr2_cov,
    cr2_interval,
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


def test_t21_the_rank_in_cr2() -> None:
    """T21, le rang dans ``cr2_cov`` (B1) : deux lignes et trois colonnes ; une
    colonne nulle ; deux colonnes égales : ``InferenceError``, « plein rang » pour les
    deux derniers."""
    labels = numpy.array([0, 0, 1, 1, 2, 2])
    resid = numpy.array([1.0, -1.0, 0.5, -0.5, 2.0, -2.0])
    with pytest.raises(InferenceError, match="n ≤ p"):
        cr2_cov(numpy.ones((2, 3)), resid[:2], labels[:2])
    column = numpy.arange(6.0)
    with pytest.raises(InferenceError, match="plein rang"):
        cr2_cov(numpy.column_stack([numpy.ones(6), numpy.zeros(6)]), resid, labels)
    with pytest.raises(InferenceError, match="plein rang"):
        cr2_cov(numpy.column_stack([numpy.ones(6), column, column]), resid, labels)


def _ten_clusters() -> tuple[FloatArray, FloatArray, numpy.typing.NDArray[numpy.int_]]:
    return _clustered(1021, 10, 2)


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (
            lambda: cluster_weights("webb", 0, 5, RaisingGenerator().as_generator()),
            "^G et B :",
        ),
        (
            lambda: cluster_weights("webb", 3, 0, RaisingGenerator().as_generator()),
            "^G et B :",
        ),
        (
            lambda: wild_cluster_interval(
                *_ten_clusters()[:2], _ten_clusters()[2], 2, 0.95, 9, child_rng(1)
            ),
            "^j :",
        ),
        (
            lambda: cr2_cov(numpy.ones((4, 1)), numpy.ones(4), numpy.zeros(3, int)),
            "^clusters :",
        ),
        (
            lambda: cr2_cov(numpy.ones((4, 1)), numpy.ones(4), numpy.zeros(4, int)),
            "^clusters :",
        ),
    ],
)
def test_t23_refusals_at_the_bounds(call: Callable[[], object], match: str) -> None:
    """T23, refus (L4, L5) : ``G = 0``, ``B = 0``, ``j`` égal au nombre de colonnes,
    des étiquettes de mauvaise longueur, une seule grappe ; le message nomme
    l'argument."""
    with pytest.raises(InferenceError, match=match):
        call()


def test_t23_acceptances_next_to_the_bounds() -> None:
    """T23, acceptations juste à côté : ``B = 1`` ; ``j = 0``."""
    assert cluster_weights("webb", 3, 1, SpyGenerator(1).as_generator()).shape == (1, 3)
    X, y, labels = _ten_clusters()  # noqa: N806
    wild_cluster_interval(X, y, labels, 0, 0.95, 9, child_rng(1))


# Les degrés de Bell-McCaffrey et l'intervalle CR2 (AN4-2a, § 7.5 du brief) : K1 à
# K6, valeurs de la seconde implémentation de la conception.


def _k3() -> tuple[FloatArray, FloatArray, numpy.typing.NDArray[numpy.int_]]:
    """K3 : 21 lignes, ``X_i = (1, i mod 7, i² mod 5)``, ``y_i = sin(i)``, deux
    lignes par grappe, trois pour la dernière."""
    i = numpy.arange(21)
    X = numpy.column_stack([numpy.ones(21), i % 7, (i * i) % 5]).astype(float)  # noqa: N806
    labels = numpy.minimum(i // 2, 9)
    return X, numpy.sin(i.astype(float)), labels


def test_k1_a_mean_over_equal_clusters() -> None:
    """K1 : une constante seule, 10 grappes de 3 lignes : ``G − 1 = 9`` degrés."""
    labels = numpy.repeat(numpy.arange(10), 3)
    assert bell_mccaffrey_df(numpy.ones((30, 1)), labels, 0) == pytest.approx(
        9.0, rel=1e-9
    )


def test_k2_a_mean_over_unequal_clusters() -> None:
    """K2 : une constante seule, grappes de 2, 2, 3, 3, 4, 4, 5, 5, 6, 6 lignes."""
    labels = numpy.repeat(numpy.arange(10), [2, 2, 3, 3, 4, 4, 5, 5, 6, 6])
    df = bell_mccaffrey_df(numpy.ones((labels.shape[0], 1)), labels, 0)
    assert df == pytest.approx(7.899655499441329, rel=1e-9)


def test_k3_a_slope_and_its_interval() -> None:
    """K3 : ``df`` de la colonne 1, et l'intervalle à 90 % (coefficient et erreur
    type CR2 de la seconde implémentation)."""
    X, y, labels = _k3()  # noqa: N806
    assert bell_mccaffrey_df(X, labels, 1) == pytest.approx(5.143946261922288, rel=1e-9)
    fit = ols(X, y)
    assert float(fit.coef[1]) == pytest.approx(-0.15448164462363873, rel=1e-9)
    se = math.sqrt(float(cr2_cov(X, fit.resid, labels)[1, 1]))
    assert se == pytest.approx(0.08253602224578607, rel=1e-9)
    interval, df = cr2_interval(X, y, labels, 1, 0.90)
    assert df == pytest.approx(5.143946261922288, rel=1e-9)
    assert interval.low == pytest.approx(-0.3197731413681643, rel=1e-9)
    assert interval.high == pytest.approx(0.010809852120886865, rel=1e-9)


def test_k4_invariances() -> None:
    """K4 : des étiquettes renommées (une permutation des entiers) ne changent pas
    ``df`` ; la colonne ``j`` multipliée par 3 non plus."""
    X, _, labels = _k3()  # noqa: N806
    reference = bell_mccaffrey_df(X, labels, 1)
    permutation = numpy.array([7, 3, 9, 0, 5, 1, 8, 2, 6, 4])
    assert bell_mccaffrey_df(X, permutation[labels], 1) == pytest.approx(
        reference, rel=1e-9
    )
    scaled = X.copy()
    scaled[:, 1] *= 3.0
    assert bell_mccaffrey_df(scaled, labels, 1) == pytest.approx(reference, rel=1e-9)


def test_k5_refusals() -> None:
    """K5 : une grappe ; neuf grappes (``cr2_interval``, le message de la charte) ;
    ``j`` hors des colonnes ; des étiquettes non entières ; un levier de 1."""
    X, y, labels = _k3()  # noqa: N806
    with pytest.raises(InferenceError, match="au moins 2 grappes"):
        bell_mccaffrey_df(X, numpy.zeros(21, dtype=int), 1)
    nine = numpy.minimum(numpy.arange(21) // 2, 8)
    with pytest.raises(InferenceError, match="sous 10 grappes, on agrège"):
        cr2_interval(X, y, nine, 1, 0.95)
    for j in (3, -1):
        with pytest.raises(InferenceError, match=r"^j :"):
            bell_mccaffrey_df(X, labels, j)
        with pytest.raises(InferenceError, match=r"^j :"):
            cr2_interval(X, y, labels, j, 0.95)
    with pytest.raises(InferenceError, match="entières"):
        bell_mccaffrey_df(X, labels.astype(float), 1)
    with pytest.raises(InferenceError, match="entières"):
        cr2_interval(X, y, labels.astype(float), 1, 0.95)
    lever = numpy.column_stack([X, (labels == 0).astype(float)])
    with pytest.raises(InferenceError, match="levier de 1"):
        bell_mccaffrey_df(lever, labels, 1)
    with pytest.raises(InferenceError, match="levier de 1"):
        cr2_interval(lever, y, labels, 1, 0.95)


def test_k6_cr2_interval_coverage() -> None:
    """K6 : couverture simulée (graine 20261125, 200 jeux, 12 grappes de 5 lignes) :
    entre 187 et 189 intervalles contiennent la pente vraie 0 (oracle : 188 ; à
    ``G − 1`` ddl : 185)."""
    g = numpy.random.default_rng(20261125)
    labels = numpy.repeat(numpy.arange(12), 5)
    covered = 0
    for _ in range(200):
        x = numpy.repeat(g.normal(size=12), 5) + 0.5 * g.normal(size=60)
        u = g.normal(size=12)
        e = g.normal(size=60)
        X = numpy.column_stack([numpy.ones(60), x])  # noqa: N806
        y = 1.0 + numpy.repeat(u, 5) + e
        interval, _ = cr2_interval(X, y, labels, 1, 0.95)
        covered += interval.low <= 0.0 <= interval.high
    assert 187 <= covered <= 189
