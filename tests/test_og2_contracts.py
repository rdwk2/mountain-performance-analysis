"""Les invariants des contrats du format 6 (OG-2, § 6.5) que la suite ne tenait pas
(relecture C du bloc 1, mutation 7) ; les aides sont celles de
``test_og2_format6.py``."""

from __future__ import annotations

import dataclasses
import math
from datetime import date
from typing import Any

import pytest

from mountain_perf.backtest import SENSITIVITY_CONFIGURATIONS
from mountain_perf.schemas import (
    CLOCKS,
    AbsentCurve,
    CalibrationTerm,
    CalibrationTerms,
    CurveStatus,
    ModelKind,
    RollingPerformance,
    RollingResult,
    Scenario,
    ScenarioClockTerms,
    SensitivityDeclaration,
    ShareScope,
    ShareUnavailability,
)
from mountain_perf.validation import ContractError
from test_backtest_registry_format5 import _pairs_of
from test_og2_correspondence import DAY_END, DAY_START, outing
from test_og2_documents import frozen_curve, rolling_rule
from test_og2_format6 import (
    SHA_A,
    SHA_B,
    absent_performance,
    curve_performance,
    rolling,
    rolling_declaration,
    terms,
)


def _instances() -> list[Any]:
    term = CalibrationTerm(date(2026, 6, 1), 3600.0, 3500.0)
    clock_terms = ScenarioClockTerms(Scenario.USAGE, CLOCKS[0], (term,))
    return [
        rolling_rule(),
        frozen_curve(),
        AbsentCurve("{}"),
        curve_performance(),
        rolling(),
        term,
        clock_terms,
        CalibrationTerms(ModelKind.V0_RECALIBRATED, (clock_terms,)),
        RollingResult(SHA_A, (SHA_B,), (None,)),
    ]


@pytest.mark.parametrize("instance", _instances(), ids=lambda v: type(v).__name__)
def test_every_new_contract_is_frozen(instance: Any) -> None:
    field = dataclasses.fields(instance)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, field, getattr(instance, field))


def test_curve_sha256_must_be_a_sha256() -> None:
    bad = "z" * 64
    with pytest.raises(ContractError, match="curve_sha256"):
        RollingPerformance(
            CurveStatus.CURVE,
            SHA_A,
            bad,
            f"og2.csv#{bad[:12]}",
            0.1,
            ShareScope.USAGE,
            None,
        )


def test_an_unavailable_share_has_no_scope() -> None:
    with pytest.raises(ContractError, match="n'a pas de share_scope"):
        dataclasses.replace(absent_performance(), share_scope=ShareScope.USAGE)


@pytest.mark.parametrize("field", ["command_windows", "performances"])
def test_rolling_declaration_sequences_are_tuples(field: str) -> None:
    value = list(getattr(rolling(), field))
    with pytest.raises(ContractError, match="séquence immuable"):
        rolling(**{field: value})


@pytest.mark.parametrize("tolerance", [math.inf, math.nan])
def test_the_coverage_tolerance_is_finite(tolerance: float) -> None:
    with pytest.raises(ContractError, match="coverage_tolerance_s"):
        rolling(coverage_tolerance_s=tolerance)


@pytest.mark.parametrize("field", ["observed_s", "forecast_s"])
def test_calibration_terms_are_finite(field: str) -> None:
    values: dict[str, Any] = {
        "civil_date": date(2026, 6, 1),
        "observed_s": 1.0,
        "forecast_s": 1.0,
    }
    values[field] = math.inf
    with pytest.raises(ContractError, match=field):
        CalibrationTerm(**values)


def test_terms_and_sets_are_tuples() -> None:
    term = CalibrationTerm(date(2026, 6, 1), 1.0, 1.0)
    with pytest.raises(ContractError, match="séquence immuable"):
        ScenarioClockTerms(Scenario.USAGE, CLOCKS[0], [term])  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="séquence immuable"):
        CalibrationTerms(ModelKind.V0_RECALIBRATED, list(terms().sets))  # type: ignore[arg-type]


def test_rolling_result_fields() -> None:
    with pytest.raises(ContractError, match="rule"):
        RollingResult("x", (SHA_B,), (None,))
    with pytest.raises(ContractError, match="séquence immuable"):
        RollingResult(SHA_A, [SHA_B], (None,))  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="séquence immuable"):
        RollingResult(SHA_A, (SHA_B,), [None])  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="calibration_terms"):
        RollingResult(SHA_A, (SHA_B,), ("x",))


def test_a_rolling_declaration_refuses_a_sensitivity() -> None:
    """Invariant 11, D-OG2-8 : dans le contrat, pas seulement à la commande."""
    sensitivity = SensitivityDeclaration(
        central=1,
        central_hash=SHA_A,
        answer=2,
        answer_hash=SHA_B,
        configurations=SENSITIVITY_CONFIGURATIONS,
        pairs=_pairs_of(SENSITIVITY_CONFIGURATIONS),
        frozen=None,
    )
    with pytest.raises(ContractError) as error:
        rolling_declaration(sensitivity=sensitivity)
    assert str(error.value) == (
        "une DÉCLARATION de sensibilité n'existe pas en mode glissant : hors du jalon "
        "(0010 D13, précision OG-2)."
    )


def test_outing_activity_refs_is_a_tuple() -> None:
    with pytest.raises(ContractError, match="séquence immuable"):
        dataclasses.replace(outing(DAY_START, DAY_END, ()), activity_refs=["A"])  # type: ignore[arg-type]


def test_share_unavailability_without_curve() -> None:
    """Constat de comportement : une performance ``curve`` dont la part est
    indisponible au motif ``no_curve`` est admise par le contrat."""
    performance = dataclasses.replace(
        curve_performance(),
        out_of_support_share=None,
        share_scope=None,
        share_unavailability=ShareUnavailability.NO_CURVE,
    )
    assert performance.status is CurveStatus.CURVE
