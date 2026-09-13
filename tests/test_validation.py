"""Tests des vérifications partagées : chaque fonction accepte et refuse."""

import math
from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mountain_perf.validation import (
    ContractError,
    require_all_finite,
    require_all_in_range,
    require_aware,
    require_finite,
    require_immutable_sequence,
    require_in_range,
    require_increasing,
    require_min_length,
    require_non_empty,
    require_same_length,
)


def test_contract_error_is_a_value_error() -> None:
    assert issubclass(ContractError, ValueError)


def test_require_aware() -> None:
    require_aware(datetime(2026, 9, 13, tzinfo=UTC), "dt")
    require_aware(datetime(2026, 9, 13, tzinfo=timezone(timedelta(hours=2))), "dt")
    with pytest.raises(ContractError, match="fuseau"):
        require_aware(datetime(2026, 9, 13), "dt")


def test_require_same_length() -> None:
    require_same_length(a=(1.0, 2.0), b=(3.0, 4.0))
    require_same_length()
    with pytest.raises(ContractError, match="a=2, b=1"):
        require_same_length(a=(1.0, 2.0), b=(3.0,))


def test_require_min_length() -> None:
    require_min_length((1, 2), 2, "x")
    with pytest.raises(ContractError, match="au moins 2"):
        require_min_length((1,), 2, "x")


def test_require_increasing_strict_and_wide() -> None:
    require_increasing((0.0, 1.0, 2.0), "d", strict=True)
    require_increasing((0.0, 1.0, 1.0), "d", strict=False)
    with pytest.raises(ContractError, match="strictement"):
        require_increasing((0.0, 1.0, 1.0), "d", strict=True)
    with pytest.raises(ContractError, match=r"d\[2\]"):
        require_increasing((0.0, 1.0, 0.5), "d", strict=False)


def test_require_increasing_refuses_nan() -> None:
    with pytest.raises(ContractError):
        require_increasing((0.0, math.nan), "d", strict=False)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_require_finite_refuses_non_finite(value: float) -> None:
    with pytest.raises(ContractError, match="fini"):
        require_finite(value, "x")
    with pytest.raises(ContractError, match=r"x\[1\]"):
        require_all_finite((0.0, value), "x")


def test_require_in_range_bounds_are_inclusive() -> None:
    require_in_range(-90.0, -90.0, 90.0, "lat")
    require_in_range(90.0, -90.0, 90.0, "lat")
    with pytest.raises(ContractError, match=r"\[-90.0, 90.0\]"):
        require_in_range(90.0001, -90.0, 90.0, "lat")
    with pytest.raises(ContractError):
        require_in_range(math.nan, -90.0, 90.0, "lat")


def test_require_all_in_range() -> None:
    require_all_in_range((0.0, 1.0), 0.0, 1.0, "x")
    with pytest.raises(ContractError, match=r"x\[1\]"):
        require_all_in_range((0.0, 2.0), 0.0, 1.0, "x")


@pytest.mark.parametrize("text", ["", "   ", "\t\n"])
def test_require_non_empty(text: str) -> None:
    require_non_empty("a", "name")
    with pytest.raises(ContractError, match="vide"):
        require_non_empty(text, "name")


def test_require_immutable_sequence() -> None:
    require_immutable_sequence((1.0, 2.0), "x")
    with pytest.raises(ContractError, match="tuple"):
        require_immutable_sequence([1.0, 2.0], "x")


@given(st.lists(st.floats(allow_nan=False), min_size=2))
def test_sorted_sequences_are_increasing(values: list[float]) -> None:
    require_increasing(tuple(sorted(values)), "x", strict=False)
