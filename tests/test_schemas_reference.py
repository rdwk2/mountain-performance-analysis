"""Tests des contrats de la vérité terrain : TimingConvention, ObservedPassage,
ReferencePerformance.
"""

from dataclasses import replace
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fixtures.performance import THREE_PASSAGE_REFERENCE
from mountain_perf.schemas import (
    TIMING_CONVENTION_DESCRIPTIONS,
    ContractError,
    ReferencePerformance,
    TimingConvention,
)
from strategies import blank_texts, non_finite_floats, reference_performances

OBSERVED = THREE_PASSAGE_REFERENCE.passages[1]


def test_every_timing_convention_is_described() -> None:
    assert set(TIMING_CONVENTION_DESCRIPTIONS) == set(TimingConvention)
    assert all(text.strip() for text in TIMING_CONVENTION_DESCRIPTIONS.values())


# ---------------------------------------------------------------------------
# ObservedPassage
# ---------------------------------------------------------------------------


@given(blank_texts())
def test_observed_passage_blank_name_is_refused(name: str) -> None:
    with pytest.raises(ContractError, match="point_name"):
        replace(OBSERVED, point_name=name)


@given(st.one_of(st.floats(max_value=-1e-9), non_finite_floats()))
def test_observed_passage_bad_elapsed_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match="elapsed_s"):
        replace(OBSERVED, elapsed_s=value)


@given(st.one_of(st.floats(max_value=-1e-9), non_finite_floats()))
def test_observed_passage_bad_distance_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match="distance_m"):
        replace(OBSERVED, distance_m=value)


def test_observed_passage_distance_is_optional() -> None:
    assert replace(OBSERVED, distance_m=None).distance_m is None


# ---------------------------------------------------------------------------
# ReferencePerformance
# ---------------------------------------------------------------------------


@given(reference_performances())
def test_valid_reference_performances_build(reference: ReferencePerformance) -> None:
    assert len(reference.passages) >= 2


def test_reference_carries_athlete_and_per_passage_convention() -> None:
    assert THREE_PASSAGE_REFERENCE.athlete_ref == "athlete-a"
    assert [p.convention for p in THREE_PASSAGE_REFERENCE.passages] == [
        TimingConvention.DEPARTURE,
        TimingConvention.UNKNOWN,
        TimingConvention.ARRIVAL,
    ]


@pytest.mark.parametrize("name", ["athlete_ref", "event_name"])
@given(value=blank_texts())
def test_reference_blank_text_is_refused(name: str, value: str) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=name):
        replace(THREE_PASSAGE_REFERENCE, **changes)


def test_reference_mutable_passages_are_refused() -> None:
    passages: Any = list(THREE_PASSAGE_REFERENCE.passages)
    with pytest.raises(ContractError, match=r"passages.*tuple"):
        replace(THREE_PASSAGE_REFERENCE, passages=passages)


def test_reference_with_a_single_passage_is_refused() -> None:
    with pytest.raises(ContractError, match="au moins 2"):
        replace(THREE_PASSAGE_REFERENCE, passages=(OBSERVED,))


def test_reference_decreasing_elapsed_is_refused() -> None:
    first, second, third = THREE_PASSAGE_REFERENCE.passages
    with pytest.raises(ContractError, match=r"passages\.elapsed_s"):
        replace(THREE_PASSAGE_REFERENCE, passages=(first, third, second))


def test_reference_equal_elapsed_is_valid() -> None:
    first, second, _ = THREE_PASSAGE_REFERENCE.passages
    tie = replace(second, elapsed_s=0.0)
    assert replace(THREE_PASSAGE_REFERENCE, passages=(first, tie)).passages[1] == tie
