"""Tests de ParameterSpec et ParameterSet, sur des specs inventées."""

from dataclasses import FrozenInstanceError, replace
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mountain_perf.schemas import ContractError, ParameterSet, ParameterSpec
from strategies import blank_texts, non_finite_floats, parameter_sets, parameter_specs

# Deux specs de fixture, à valeurs rondes. Aucune n'est un paramètre réel du modèle.
SPEED_FACTOR = ParameterSpec(
    name="speed_factor",
    unit=None,
    default=1.0,
    minimum=0.5,
    maximum=1.5,
    description="Coefficient multiplicatif inventé.",
)
STEP = ParameterSpec(
    name="step",
    unit="m",
    default=10.0,
    minimum=1.0,
    maximum=100.0,
    description="Pas inventé.",
)
SPECS = (SPEED_FACTOR, STEP)


# ---------------------------------------------------------------------------
# ParameterSpec
# ---------------------------------------------------------------------------


@given(parameter_specs())
def test_valid_specs_build(spec: ParameterSpec) -> None:
    assert spec.minimum <= spec.default <= spec.maximum


@given(blank_texts())
def test_blank_name_is_refused(name: str) -> None:
    with pytest.raises(ContractError, match="name"):
        replace(STEP, name=name)


@given(blank_texts())
def test_blank_unit_is_refused(unit: str) -> None:
    with pytest.raises(ContractError, match="unit"):
        replace(STEP, unit=unit)


@given(blank_texts())
def test_blank_description_is_refused(description: str) -> None:
    with pytest.raises(ContractError, match="description"):
        replace(STEP, description=description)


@given(non_finite_floats())
def test_non_finite_default_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match="default"):
        replace(STEP, default=value)


@given(non_finite_floats())
def test_non_finite_minimum_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match="minimum"):
        replace(STEP, minimum=value)


@given(non_finite_floats())
def test_non_finite_maximum_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match="maximum"):
        replace(STEP, maximum=value)


@pytest.mark.parametrize("default", [0.999, 100.001])
def test_default_outside_bounds_is_refused(default: float) -> None:
    with pytest.raises(ContractError, match="default"):
        replace(STEP, default=default)


def test_inverted_bounds_are_refused() -> None:
    with pytest.raises(ContractError, match="default"):
        replace(STEP, minimum=100.0, maximum=1.0, default=50.0)


# ---------------------------------------------------------------------------
# ParameterSet
# ---------------------------------------------------------------------------


@given(parameter_sets())
def test_valid_sets_are_completed_with_one_value_per_spec(
    parameters: ParameterSet,
) -> None:
    assert list(parameters.values) == [spec.name for spec in parameters.specs]
    for spec in parameters.specs:
        assert spec.minimum <= parameters[spec.name] <= spec.maximum


def test_missing_key_takes_its_default() -> None:
    parameters = ParameterSet(specs=SPECS, values={"step": 25.0})
    assert parameters["step"] == 25.0
    assert parameters["speed_factor"] == 1.0
    assert ParameterSet(specs=SPECS)["step"] == 10.0


def test_bounds_are_inclusive() -> None:
    parameters = ParameterSet(specs=SPECS, values={"step": 1.0, "speed_factor": 1.5})
    assert parameters["step"] == 1.0


@given(st.one_of(st.floats(max_value=0.999), st.floats(min_value=100.001)))
def test_value_outside_bounds_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match="step"):
        ParameterSet(specs=SPECS, values={"step": value})


@given(non_finite_floats())
def test_non_finite_value_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match="step"):
        ParameterSet(specs=SPECS, values={"step": value})


def test_unknown_key_is_refused() -> None:
    with pytest.raises(ContractError, match="inconnus : smoothing"):
        ParameterSet(specs=SPECS, values={"smoothing": 3.0})


def test_duplicate_spec_names_are_refused() -> None:
    with pytest.raises(ContractError, match="double : step"):
        ParameterSet(specs=(STEP, replace(STEP, description="Autre.")))


def test_specs_must_be_a_tuple() -> None:
    # Any : on passe volontairement une list là où le type exige un tuple.
    mutable_specs: Any = list(SPECS)
    with pytest.raises(ContractError, match="tuple"):
        ParameterSet(specs=mutable_specs)


def test_set_is_frozen_and_its_table_is_read_only() -> None:
    source_values = {"step": 25.0}
    parameters = ParameterSet(specs=SPECS, values=source_values)
    with pytest.raises(FrozenInstanceError):
        parameters.values = {}  # type: ignore[misc]
    with pytest.raises(TypeError):
        parameters.values["step"] = 50.0  # type: ignore[index]
    source_values["step"] = 50.0
    assert parameters["step"] == 25.0


def test_unknown_name_lookup_raises_key_error() -> None:
    with pytest.raises(KeyError):
        ParameterSet(specs=SPECS)["smoothing"]
