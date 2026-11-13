"""L'autocorrélation des résidus par classe d'écart
(``mountain_perf.analyse.inference.autocorrelation``, AN3-1, ``docs/decisions/0021``) :
les cas H9 et H9 bis du brief, et les refus. Sautés sans numpy ou scipy (extra
``analyse``)."""

from __future__ import annotations

from fractions import Fraction

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from mountain_perf.analyse.inference.autocorrelation import (
    LagClass,
    residual_autocorrelation,
)
from mountain_perf.analyse.inference.base import InferenceError

T = (0, 1, 2, 5, 6)
RESID = (1.0, -1.0, 2.0, 0.0, -2.0)


def _check(result: tuple[LagClass, ...], expected: list[LagClass]) -> None:
    assert len(result) == len(expected)
    for got, want in zip(result, expected, strict=True):
        assert (got.low, got.high, got.pairs) == (want.low, want.high, want.pairs)
        if want.correlation is None:
            assert got.correlation is None
        else:
            assert got.correlation == pytest.approx(want.correlation, rel=1e-12)


def test_t19_autocorrelation_h9() -> None:
    """T19 : H9 (trois classes, la dernière sans paire), le même résultat sur les
    résidus décalés de 10 (centrage) ; H9 bis (une classe sans borne haute, non
    vide)."""
    expected = [
        LagClass(1, 2, 4, float(Fraction(-1, 8))),
        LagClass(3, 6, 6, float(Fraction(-1, 3))),
        LagClass(7, None, 0, None),
    ]
    classes = ((1, 2), (3, 6), (7, None))
    _check(residual_autocorrelation(T, RESID, classes), expected)
    shifted = [r + 10.0 for r in RESID]
    _check(residual_autocorrelation(T, shifted, classes), expected)
    _check(
        residual_autocorrelation(T, RESID, ((1, 1), (4, None))),
        [
            LagClass(1, 1, 3, float(Fraction(-1, 2))),
            LagClass(4, None, 5, float(Fraction(-2, 5))),
        ],
    )


def test_t19_autocorrelation_refusals() -> None:
    """T19 : classes qui se recouvrent, décroissantes, ``low < 1``, après une classe
    sans borne haute ; résidus constants ; longueurs différentes."""
    for classes in [
        ((1, 3), (3, 6)),
        ((3, 6), (1, 2)),
        ((0, 2),),
        ((1, None), (5, 6)),
        ((3, 2),),
        (),
    ]:
        with pytest.raises(InferenceError, match="classes"):
            residual_autocorrelation(T, RESID, classes)
    with pytest.raises(InferenceError, match="constants"):
        residual_autocorrelation(T, (3.0,) * 5, ((1, 2),))
    with pytest.raises(InferenceError, match="resid"):
        residual_autocorrelation(T, RESID[:4], ((1, 2),))
