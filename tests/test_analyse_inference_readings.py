"""Holm, Bonferroni et les trois lectures (``mountain_perf.analyse.inference.readings``,
AN3-1, ``docs/decisions/0021``) : les cas H7 et H8 du brief, bornes et ``direction``
comprises, et des propriétés. Sautés sans numpy ou scipy (extra ``analyse``)."""

from __future__ import annotations

import random

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from hypothesis import given, settings
from hypothesis import strategies as st

from mountain_perf.analyse.inference.base import InferenceError, Interval
from mountain_perf.analyse.inference.readings import (
    Reading,
    bonferroni_level,
    direction,
    holm,
    reading,
)


def test_t17_holm_and_bonferroni_h7() -> None:
    """T17 : H7, Holm dans l'ordre d'entrée, arrêt au premier non-rejet, égalité à la
    borne (``≤``) ; ``bonferroni_level(0,05 ; 5) = 0,99``."""
    assert holm((0.04, 0.01, 0.03), 0.05) == (False, True, False)
    assert holm((0.01, 0.02, 0.02), 0.05) == (True, True, True)
    assert holm((0.025, 0.0125), 0.05) == (True, True)
    assert bonferroni_level(0.05, 5) == pytest.approx(0.99, rel=1e-12)
    with pytest.raises(InferenceError):
        holm((), 0.05)
    with pytest.raises(InferenceError):
        holm((0.5, 1.5), 0.05)
    with pytest.raises(InferenceError):
        holm((0.5,), 1.0)
    with pytest.raises(InferenceError):
        bonferroni_level(0.05, 0)


@settings(deadline=None, max_examples=100)
@given(
    st.lists(st.floats(0, 1), min_size=1, max_size=20),
    st.floats(0.001, 0.2),
    st.randoms(use_true_random=False),
)
def test_t17_holm_contains_bonferroni_and_ignores_the_order(
    pvalues: list[float], alpha: float, rand: random.Random
) -> None:
    """T17, propriétés : tout rejet de Bonferroni (``p ≤ alpha/m``)
    est un rejet de Holm ;
    l'ordre d'entrée ne change pas l'ensemble rejeté."""
    rejected = holm(pvalues, alpha)
    m = len(pvalues)
    for p, holm_rejects in zip(pvalues, rejected, strict=True):
        if p <= alpha / m:
            assert holm_rejects
    order = list(range(m))
    rand.shuffle(order)
    shuffled = holm([pvalues[i] for i in order], alpha)
    assert sorted(pvalues[i] for i, r in zip(order, shuffled, strict=True) if r) == (
        sorted(p for p, r in zip(pvalues, rejected, strict=True) if r)
    )


def _i(low: float, high: float) -> Interval:
    return Interval(low, high)


def test_t18_the_three_readings_h8() -> None:
    """T18 : H8 (``delta = 0,05``), bornes et ``direction`` comprises ; liste vide et
    ``delta ≤ 0`` refusés."""
    established = Reading.ESTABLISHED
    no_effect = Reading.NO_USEFUL_EFFECT
    undecided = Reading.UNDECIDED
    cases = [
        ([_i(0.0, 0.07)], undecided),
        ([_i(0.01, 0.04)], established),
        ([_i(-0.03, 0.04)], no_effect),
        ([_i(-0.03, 0.05)], undecided),
        ([_i(0.01, 0.04), _i(-0.01, 0.03)], no_effect),
        ([_i(0.01, 0.08), _i(-0.08, -0.01)], undecided),
        ([_i(-0.08, -0.01), _i(-0.09, -0.02)], established),
        ([_i(-0.04, 0.0)], no_effect),
        ([_i(-0.05, 0.02)], undecided),
    ]
    for intervals, expected in cases:
        assert reading(intervals, 0.05) is expected, intervals
    assert direction([_i(-0.08, -0.01), _i(-0.09, -0.02)]) == -1
    assert direction([_i(0.01, 0.04)]) == 1
    assert direction([_i(0.0, 0.07)]) == 0
    assert direction([_i(0.01, 0.08), _i(-0.08, -0.01)]) == 0
    assert Reading.ESTABLISHED.value == "établi"
    assert Reading.NO_USEFUL_EFFECT.value == "absence d'effet utile"
    assert Reading.UNDECIDED.value == "non tranché"
    with pytest.raises(InferenceError):
        reading([], 0.05)
    with pytest.raises(InferenceError):
        direction([])
    for delta in (0.0, -0.05):
        with pytest.raises(InferenceError):
            reading([_i(0.01, 0.04)], delta)
