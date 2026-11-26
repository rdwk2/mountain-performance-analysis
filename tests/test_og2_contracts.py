"""Les invariants des contrats du format 6 (OG-2, § 6.5) que la suite ne tenait pas
(relecture C du bloc 1, mutation 7), et ceux de la règle en couches (M6b-3, § 6.3 (e)) ;
les aides sont celles de ``test_og2_format6.py``."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest

from fixtures.registry import declaration
from mountain_perf.backtest import SENSITIVITY_CONFIGURATIONS
from mountain_perf.schemas import (
    CLOCKS,
    AbsentCurve,
    CalibrationTerm,
    CalibrationTerms,
    CurveStatus,
    EventKind,
    LayeredRollingRule,
    ModelKind,
    RegistryEvent,
    RollingDeclaration,
    RollingPerformance,
    RollingResult,
    RollingRule,
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


@pytest.mark.parametrize(
    "field", ["command_windows", "performances", "command_level_windows"]
)
def test_rolling_declaration_sequences_are_tuples(field: str) -> None:
    fields: dict[str, Any] = {"command_level_windows": (None, None, None)}
    value = list(getattr(rolling(**fields), field))
    with pytest.raises(ContractError, match="séquence immuable"):
        rolling(**{**fields, field: value})


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


# --- La règle en couches (M6b-3) ------------------------------------------------------


def _layered_rule(**changes: Any) -> LayeredRollingRule:
    fields: dict[str, Any] = {
        f.name: getattr(rolling_rule(), f.name) for f in dataclasses.fields(RollingRule)
    }
    fields.update(level_window_days=28, level_kappa=0.5)
    fields.update(changes)
    return LayeredRollingRule(**fields)


def _layered_rolling(**changes: Any) -> RollingDeclaration:
    fields: dict[str, Any] = {"level_window_days": 28, "level_kappa": 0.5}
    fields.update(changes)
    return rolling(**fields)


LAYERED_BUILDERS: list[Callable[..., Any]] = [_layered_rule, _layered_rolling]


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"window_days": None}, "porte sa fenêtre de forme"),
        ({"level_window_days": 0}, r"level_window_days doit être dans \[1 ; 56\["),
        ({"level_window_days": 56}, r"level_window_days doit être dans \[1 ; 56\["),
        ({"level_kappa": 0.0}, r"level_kappa doit être dans \]0 ; 1\]"),
        ({"level_kappa": 1.5}, r"level_kappa doit être dans \]0 ; 1\]"),
        ({"level_kappa": math.nan}, "level_kappa"),
    ],
    ids=["sans-forme", "niveau-0", "niveau-56", "kappa-0", "kappa-1.5", "kappa-nan"],
)
@pytest.mark.parametrize("build", LAYERED_BUILDERS, ids=["regle", "declaration"])
def test_the_level_bounds(
    build: Callable[..., Any], changes: dict[str, Any], fragment: str
) -> None:
    """``_check_level`` : la fenêtre de forme posée, ``1 <= level_window_days <
    window_days``, ``0 < level_kappa <= 1``, fini."""
    with pytest.raises(ContractError, match=fragment):
        build(**changes)


@pytest.mark.parametrize("build", LAYERED_BUILDERS, ids=["regle", "declaration"])
def test_the_level_bounds_accepted(build: Callable[..., Any]) -> None:
    assert build(level_window_days=1).level_window_days == 1
    assert build(level_kappa=1.0).level_kappa == 1.0


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"level_window_days": 28}, "vont ensemble"),
        ({"level_kappa": 0.5}, "vont ensemble"),
        (
            {
                "level_window_days": 28,
                "level_kappa": 0.5,
                "command_level_windows": (28, None),
            },
            "une fenêtre de niveau par règle de la commande",
        ),
        (
            {
                "level_window_days": 28,
                "level_kappa": 0.5,
                "command_level_windows": (None, None, None),
            },
            "doivent contenir celle de la DÉCLARATION",
        ),
        (
            {
                "level_window_days": 28,
                "level_kappa": 0.5,
                "command_level_windows": (0, 28, None),
            },
            "command_level_windows : au moins 1 jour",
        ),
    ],
    ids=["niveau-seul", "kappa-seul", "longueur", "paire-absente", "niveau-0-commande"],
)
def test_the_layered_rolling_declaration(
    changes: dict[str, Any], fragment: str
) -> None:
    """Les champs de niveau ensemble ; ``command_level_windows`` parallèle à
    ``command_windows``, la paire de la DÉCLARATION parmi les siennes, ``>= 1``."""
    _layered_rolling()
    rolling(
        level_window_days=28, level_kappa=0.5, command_level_windows=(None, 28, None)
    )
    with pytest.raises(ContractError, match=fragment):
        rolling(**changes)


def _declaration_event(version: int, declared: RollingDeclaration) -> RegistryEvent:
    return RegistryEvent(
        format_version=version,
        number=1,
        kind=EventKind.DECLARATION,
        recorded_at=datetime(2026, 10, 3, 13, tzinfo=UTC),
        previous_hash=None,
        answers=None,
        corrects=None,
        correction_reason=None,
        declaration=declaration(
            curve_ref=None, curve=None, curve_metadata=None, rolling=declared
        ),
        result=None,
        failure=None,
    )


def test_the_layered_fields_and_the_format() -> None:
    """Invariant 2 : avant le format 7, une DÉCLARATION glissante ne porte pas la règle
    en couches ; à partir du format 7, elle porte ``command_level_windows``."""
    _declaration_event(6, rolling())
    _declaration_event(7, rolling(command_level_windows=(None, None, None)))
    with pytest.raises(ContractError, match="ne porte pas la règle en couches"):
        _declaration_event(6, _layered_rolling())
    with pytest.raises(ContractError, match="porte command_level_windows"):
        _declaration_event(7, rolling())
