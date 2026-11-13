"""La base de la spline cubique naturelle (``mountain_perf.analyse.inference.spline``,
AN3-1, ``docs/decisions/0021``) : les cas H13 et H13 bis du brief, les refus, et la
propriété d'affinité au-delà des nœuds extrêmes. Sautés sans numpy ou scipy (extra
``analyse``)."""

from __future__ import annotations

import itertools
from fractions import Fraction

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from mountain_perf.analyse.inference.base import InferenceError
from mountain_perf.analyse.inference.spline import natural_cubic_basis

EXACT = 1e-12


def _f(numerator: int, denominator: int = 1) -> float:
    return float(Fraction(numerator, denominator))


def test_t32_natural_cubic_basis_h13() -> None:
    """T32 : H13 (``K = 3``) et H13 bis (``K = 4``, où ``d_k − d_{K−1}`` et
    ``d_k − d_{k+1}`` diffèrent) ; nœuds non croissants et ``K < 3`` refusés."""
    x = [-1.0, 0.5, 1.5, 3.0, 4.0]
    basis = natural_cubic_basis(x, [0.0, 1.0, 2.0])
    assert basis.shape == (5, 2)
    assert basis[:, 0] == pytest.approx(x, rel=EXACT)
    assert basis[:, 1] == pytest.approx(
        [0.0, 0.0625, 1.5625, 6.0, 9.0], rel=EXACT, abs=EXACT
    )
    x_bis = [-1.0, 0.5, 1.5, 3.0, 5.0]
    basis = natural_cubic_basis(x_bis, [0.0, 1.0, 2.0, 4.0])
    assert basis.shape == (5, 3)
    assert basis[:, 1] == pytest.approx(
        [0.0, _f(1, 32), _f(27, 32), _f(25, 4), 18.0], rel=EXACT, abs=EXACT
    )
    assert basis[:, 2] == pytest.approx(
        [0.0, 0.0, _f(1, 24), _f(13, 6), 8.0], rel=EXACT, abs=EXACT
    )
    for knots in ([0.0, 2.0, 1.0], [0.0, 1.0, 1.0], [0.0, 1.0]):
        with pytest.raises(InferenceError, match="knots"):
            natural_cubic_basis(x, knots)


@settings(deadline=None, max_examples=100)
@given(
    st.lists(st.floats(-10, 10), min_size=3, max_size=8, unique=True),
    st.floats(0.01, 5),
    st.floats(0, 5),
    st.booleans(),
)
def test_t33_each_column_is_affine_beyond_the_extreme_knots(
    raw_knots: list[float], step: float, offset: float, above: bool
) -> None:
    """T33, propriété : au-delà du dernier nœud (ou en deçà du premier), chaque
    colonne est affine : ``|f(x₀) − 2f(x₁) + f(x₂)| ≤ 1e−9 · max(1, |f|)`` sur trois
    points équidistants de ``[−20 ; 20]``."""
    knots = sorted(raw_knots)
    assume(min(b - a for a, b in itertools.pairwise(knots)) >= 0.1)
    start = knots[-1] + offset if above else knots[0] - offset - 2 * step
    points = [start, start + step, start + 2 * step]
    assume(points[0] >= -20.0 and points[2] <= 20.0)
    basis = natural_cubic_basis(points, knots)
    for column in basis.T:
        f0, f1, f2 = (float(v) for v in column)
        bound = 1e-9 * max(1.0, abs(f0), abs(f1), abs(f2))
        assert abs(f0 - 2 * f1 + f2) <= bound
