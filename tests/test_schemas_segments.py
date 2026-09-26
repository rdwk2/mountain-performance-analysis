"""Tests des contrats de segments et de couverture (§ 5b.1 du brief M4a-2b).

``0010`` D4.2, D4.9 à D4.11, D5.4, D6, D13. Un test par invariant des huit types
neufs ; quand la violation d'un invariant en entraîne logiquement une autre, le test
vise l'invariant par le message de l'exception, qui le nomme. Exemple valide : X01
(§ 7.2a et § 7.2b), deux extrémités ancrées, trois segments admis.
"""

from collections.abc import Mapping
from dataclasses import FrozenInstanceError, replace
from enum import Enum
from typing import Any

import pytest
from hypothesis import given

from fixtures.matching import x01
from fixtures.segments import matched
from mountain_perf.backtest import MATCHING_PARAMETER_SPECS, FineOverlap
from mountain_perf.schemas import (
    CLOCKS,
    REGIME_CLASS_DESCRIPTIONS,
    REGIME_DESCRIPTIONS,
    SEGMENT_EXCLUSION_DESCRIPTIONS,
    AdmittedTotals,
    ClockTotals,
    ContractError,
    Coverage,
    MatchResult,
    ParameterSet,
    PointStatus,
    Regime,
    RegimeClass,
    ScorePointObservation,
    ScoreSegmentObservation,
    SegmentExclusion,
    SensitivityConfiguration,
)
from mountain_perf.schemas._dictionary import render
from strategies import non_finite_floats

X01_LENGTH_M = 529.999999847
"""``L`` de la référence de X01 (§ 7.2a)."""

X01_POINTS = (
    ScorePointObservation(
        index=0,
        nominal_m=0.0,
        effective_m=25.0,
        status=PointStatus.ANCHORED,
        position=0.0,
        time_s=0.0,
        lateral_m=8.0,
        realized_m=0.0,
        candidate_count=0,
        event_count=0,
    ),
    ScorePointObservation(
        index=1,
        nominal_m=250.0,
        effective_m=250.0,
        status=PointStatus.FOUND,
        position=75.0,
        time_s=150.0,
        lateral_m=1.4375,
        realized_m=225.095516,
        candidate_count=1,
        event_count=1,
    ),
    ScorePointObservation(
        index=2,
        nominal_m=500.0,
        effective_m=500.0,
        status=PointStatus.FOUND,
        position=158.333333,
        time_s=316.666667,
        lateral_m=-5.854167,
        realized_m=475.201917,
        candidate_count=1,
        event_count=1,
    ),
    ScorePointObservation(
        index=3,
        nominal_m=X01_LENGTH_M,
        effective_m=505.0,
        status=PointStatus.ANCHORED,
        position=160.0,
        time_s=320.0,
        lateral_m=-6.0,
        realized_m=480.204048,
        candidate_count=0,
        event_count=0,
    ),
)
"""Les quatre points de X01 (§ 7.2a)."""


def _segment(
    k: int,
    ratio: float,
    h1_m: float,
    h2_m: float,
    points: tuple[ScorePointObservation, ...] = X01_POINTS,
) -> ScoreSegmentObservation:
    start, end = points[k], points[k + 1]
    return ScoreSegmentObservation(
        index=k,
        nominal_start_m=start.nominal_m,
        nominal_end_m=end.nominal_m,
        start_m=start.effective_m,
        end_m=end.effective_m,
        ascent_fraction=0.0,
        flat_fraction=1.0,
        descent_fraction=0.0,
        regime_class=RegimeClass.FLAT,
        exclusion=None,
        length_ratio=ratio,
        h1_m=h1_m,
        h2_m=h2_m,
        start_s=start.time_s,
        end_s=end.time_s,
        realized_start_m=start.realized_m,
        realized_end_m=end.realized_m,
    )


X01_SEGMENTS = (
    _segment(0, 1.000425, 7.86875, 7.996599),
    _segment(1, 1.000426, 5.825, 5.851678),
    _segment(2, 1.000426, 5.86875, 5.99745),
)
"""Les trois segments admis de X01 (§ 7.2b)."""

ADMITTED = X01_SEGMENTS[0]

UNOBSERVED = replace(
    ADMITTED,
    exclusion=SegmentExclusion.UNOBSERVED_BOUND,
    length_ratio=None,
    h1_m=None,
    h2_m=None,
    end_s=None,
    realized_end_m=None,
)
"""Un segment dont la borne de fin n'est pas datée."""

GAP = replace(
    ADMITTED,
    exclusion=SegmentExclusion.GAP,
    length_ratio=None,
    h1_m=None,
    h2_m=None,
)

X01_COVERAGE = Coverage(
    reference_length_m=X01_LENGTH_M,
    admitted_m=480.0,
    excluded_unobserved_bound_m=0.0,
    excluded_gap_m=0.0,
    excluded_length_ratio_m=0.0,
    excluded_interior_deviation_m=0.0,
    anchoring_excluded_m=25.0 + (X01_LENGTH_M - 505.0),
    ascent_length_m=0.0,
    flat_length_m=X01_LENGTH_M,
    descent_length_m=0.0,
    admitted_ascent_m=0.0,
    admitted_flat_m=480.0,
    admitted_descent_m=0.0,
    admitted_elapsed_s=320.0,
    excluded_gap_s=0.0,
    excluded_length_ratio_s=0.0,
    excluded_interior_deviation_s=0.0,
    prefix_segment_count=3,
    prefix_end_m=505.0,
    prefix_end_s=320.0,
    prefix_last_passage=None,
)
"""Couverture de X01 (§ 7.2b) : 0,90566, ancrage 50 m, écoulé admis 320 s."""

X01_ADMITTED_TOTALS = AdmittedTotals(320.0, 284.0, 0.0, 36.0)

X01_RESULT = MatchResult(
    parameters=ParameterSet(MATCHING_PARAMETER_SPECS),
    points=X01_POINTS,
    segments=X01_SEGMENTS,
    coverage=X01_COVERAGE,
    departure_delay_s=0.0,
    trace_totals=(ClockTotals(320.0, 284.0, 0.0, 36.0),) * 5,
    admitted_totals=(X01_ADMITTED_TOTALS,) * 5,
    low_convention_index=0,
    high_convention_index=0,
    admitted_sensitivity_range_s=(284.0, 320.0),
)
"""Le ``MatchResult`` de X01 (§ 7.2b) : horloges ``284/0/36`` partout."""


def _no_admitted_result() -> MatchResult:
    """X01 où les trois segments sont exclus par rapport de longueur."""
    segments = tuple(
        replace(s, exclusion=SegmentExclusion.LENGTH_RATIO) for s in X01_SEGMENTS
    )
    coverage = replace(
        X01_COVERAGE,
        admitted_m=0.0,
        excluded_length_ratio_m=480.0,
        admitted_flat_m=0.0,
        admitted_elapsed_s=0.0,
        excluded_length_ratio_s=320.0,
        prefix_segment_count=0,
        prefix_end_m=25.0,
        prefix_end_s=0.0,
    )
    return replace(
        X01_RESULT,
        segments=segments,
        coverage=coverage,
        admitted_totals=(AdmittedTotals(0.0, 0.0, 0.0, 0.0),) * 5,
        low_convention_index=None,
        high_convention_index=None,
        admitted_sensitivity_range_s=None,
    )


def _with_segment(k: int, **changes: Any) -> tuple[ScoreSegmentObservation, ...]:
    segments = list(X01_SEGMENTS)
    segments[k] = replace(segments[k], **changes)
    return tuple(segments)


def _with_point(k: int, **changes: Any) -> tuple[ScorePointObservation, ...]:
    points = list(X01_POINTS)
    points[k] = replace(points[k], **changes)
    return tuple(points)


# ---------------------------------------------------------------------------
# Énumérations et tables de descriptions
# ---------------------------------------------------------------------------

ENUM_TABLES: tuple[tuple[type[Enum], Mapping[Any, str]], ...] = (
    (SegmentExclusion, SEGMENT_EXCLUSION_DESCRIPTIONS),
    (Regime, REGIME_DESCRIPTIONS),
    (RegimeClass, REGIME_CLASS_DESCRIPTIONS),
)


@pytest.mark.parametrize(("enum", "table"), ENUM_TABLES, ids=lambda x: str(x)[:30])
def test_every_member_is_described(enum: type[Enum], table: Mapping[Any, str]) -> None:
    assert set(table) == set(enum)
    assert all(text.strip() for text in table.values())


@pytest.mark.parametrize(("enum", "table"), ENUM_TABLES, ids=lambda x: str(x)[:30])
def test_descriptions_are_read_only(enum: type[Enum], table: Mapping[Any, str]) -> None:
    writable: Any = table
    with pytest.raises(TypeError):
        writable[next(iter(enum))] = "Autre description."


def test_values_of_0010() -> None:
    """D4.9, D4.10 (motifs) et D6 (régimes, classes)."""
    assert [e.value for e in SegmentExclusion] == [
        "unobserved_bound",
        "gap",
        "length_ratio",
        "interior_deviation",
    ]
    assert [r.value for r in Regime] == ["ascent", "flat", "descent"]
    assert [c.value for c in RegimeClass] == ["ascent", "flat", "descent", "mixed"]


NEW_TYPES = (
    SegmentExclusion,
    Regime,
    RegimeClass,
    ScoreSegmentObservation,
    Coverage,
    AdmittedTotals,
    SensitivityConfiguration,
    MatchResult,
)


def test_new_types_are_in_the_dictionary() -> None:
    text = render()
    for cls in NEW_TYPES:
        assert f"## `{cls.__name__}`" in text
    for enum, _ in ENUM_TABLES:
        for member in enum:
            assert f"| `{member.name}` | `{member.value}` |" in text


@pytest.mark.parametrize(
    ("instance", "field"),
    [
        (ADMITTED, "exclusion"),
        (X01_COVERAGE, "admitted_m"),
        (X01_ADMITTED_TOTALS, "moving_s"),
        (SensitivityConfiguration(250.0, 30.0, 15.0, CLOCKS[0]), "score_step_m"),
        (X01_RESULT, "coverage"),
        (FineOverlap(30.0, 0.1), "length_m"),
    ],
    ids=lambda x: type(x).__name__ if not isinstance(x, str) else x,
)
def test_new_types_are_frozen(instance: object, field: str) -> None:
    """Les huit contrats, et ``FineOverlap`` (§ 5b.4, R2 des correctifs de la PR
    #10)."""
    with pytest.raises(FrozenInstanceError):
        setattr(instance, field, None)


# ---------------------------------------------------------------------------
# ScoreSegmentObservation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "segment",
    [
        *X01_SEGMENTS,
        UNOBSERVED,
        GAP,
        replace(ADMITTED, exclusion=SegmentExclusion.LENGTH_RATIO),
        replace(ADMITTED, exclusion=SegmentExclusion.INTERIOR_DEVIATION),
    ],
)
def test_segment_examples_build(segment: ScoreSegmentObservation) -> None:
    assert replace(segment) == segment


def test_segment_computed_properties() -> None:
    assert ADMITTED.admitted
    assert not GAP.admitted
    assert ADMITTED.length_m == 225.0
    assert ADMITTED.interior_deviation_m == 7.996599
    assert UNOBSERVED.interior_deviation_m is None


def test_segment_index_is_non_negative() -> None:
    with pytest.raises(ContractError, match="index doit être >= 0"):
        replace(ADMITTED, index=-1)


@pytest.mark.parametrize(
    "name", ["nominal_start_m", "nominal_end_m", "start_m", "end_m"]
)
@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_segment_abscissas_are_finite_and_non_negative(name: str, value: float) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=f"{name} doit être"):
        replace(ADMITTED, **changes)


def test_nominal_start_precedes_nominal_end() -> None:
    with pytest.raises(ContractError, match=r"nominal_start_m .* doit précéder"):
        replace(ADMITTED, nominal_end_m=0.0)


def test_effective_start_precedes_effective_end() -> None:
    with pytest.raises(ContractError, match=r"start_m .* doit précéder end_m"):
        replace(ADMITTED, end_m=25.0)


@given(non_finite_floats())
def test_fractions_are_finite(value: float) -> None:
    with pytest.raises(ContractError, match="descent_fraction doit être fini"):
        replace(ADMITTED, descent_fraction=value)


@pytest.mark.parametrize(
    ("fractions", "name"),
    [
        ((-2e-9, 1.0 + 2e-9, 0.0), "ascent_fraction"),
        ((0.0, 1.0 + 2e-9, -2e-9), "flat_fraction"),
        ((0.5, 0.5 + 2e-9, -2e-9), "descent_fraction"),
    ],
)
def test_each_fraction_is_in_the_unit_interval(
    fractions: tuple[float, float, float], name: str
) -> None:
    """Chaque fraction dans ``[0 ; 1]`` à ``1e−9`` près ; la somme vaut ici 1."""
    ascent, flat, descent = fractions
    with pytest.raises(ContractError, match=f"{name} doit être dans"):
        replace(
            ADMITTED,
            ascent_fraction=ascent,
            flat_fraction=flat,
            descent_fraction=descent,
            regime_class=RegimeClass.MIXED,
        )


@pytest.mark.parametrize(
    ("fractions", "regime_class"),
    [
        ((1.0000000000000002, 0.0, 0.0), RegimeClass.ASCENT),
        ((0.0, 1.0000000000000002, 0.0), RegimeClass.FLAT),
        ((-5e-10, 1.0 + 5e-10, 0.0), RegimeClass.FLAT),
        ((0.0, 5e-10, 1.0 - 5e-10), RegimeClass.DESCENT),
    ],
)
def test_fractions_pass_within_the_tolerance(
    fractions: tuple[float, float, float], regime_class: RegimeClass
) -> None:
    """B2 : une borne effective d'ancrage peut rendre ``1,0000000000000002``."""
    ascent, flat, descent = fractions
    segment = replace(
        ADMITTED,
        ascent_fraction=ascent,
        flat_fraction=flat,
        descent_fraction=descent,
        regime_class=regime_class,
    )
    assert segment.regime_class is regime_class


def test_fractions_sum_to_one() -> None:
    with pytest.raises(ContractError, match="somme des fractions"):
        replace(
            ADMITTED,
            ascent_fraction=0.5,
            flat_fraction=0.4,
            regime_class=RegimeClass.MIXED,
        )


def test_fractions_sum_to_one_within_the_tolerance() -> None:
    segment = replace(
        ADMITTED,
        ascent_fraction=0.5,
        flat_fraction=0.5 + 5e-10,
        regime_class=RegimeClass.MIXED,
    )
    assert segment.regime_class is RegimeClass.MIXED


def test_fractions_sum_beyond_the_tolerance() -> None:
    """R4 (correctifs de la PR #10) : ``(0,5 ; 0,5 + 2e−9 ; 0)``, chaque fraction
    dans ``[0 ; 1]``, somme ``1 + 2e−9`` : refusée par la tolérance de la **somme**,
    et non par la borne d'une fraction."""
    with pytest.raises(ContractError, match="somme des fractions"):
        replace(
            ADMITTED,
            ascent_fraction=0.5,
            flat_fraction=0.5 + 2e-9,
            regime_class=RegimeClass.MIXED,
        )


def test_class_is_mixed_or_a_largest_fraction() -> None:
    with pytest.raises(ContractError, match="MIXED ou le régime d'une plus grande"):
        replace(
            ADMITTED,
            ascent_fraction=0.6,
            flat_fraction=0.4,
            regime_class=RegimeClass.FLAT,
        )


@pytest.mark.parametrize(
    "regime_class", [RegimeClass.ASCENT, RegimeClass.FLAT, RegimeClass.MIXED]
)
def test_class_may_be_any_largest_fraction(regime_class: RegimeClass) -> None:
    """Le contrat ignore le seuil de 0,80 : à égalité, chaque plus grande fraction
    est admise, et mixte toujours."""
    segment = replace(
        ADMITTED, ascent_fraction=0.5, flat_fraction=0.5, regime_class=regime_class
    )
    assert segment.regime_class is regime_class


@pytest.mark.parametrize(
    "fractions", [(1.0, 0.0, 0.0), (1.0 - 5e-10, 5e-10, 0.0), (0.0, 0.0, 1.0)]
)
def test_a_fraction_of_one_imposes_its_class(
    fractions: tuple[float, float, float],
) -> None:
    ascent, flat, descent = fractions
    with pytest.raises(ContractError, match="une fraction égale à 1 impose sa classe"):
        replace(
            ADMITTED,
            ascent_fraction=ascent,
            flat_fraction=flat,
            descent_fraction=descent,
            regime_class=RegimeClass.MIXED,
        )


def test_a_fraction_just_below_one_may_be_mixed() -> None:
    segment = replace(
        ADMITTED,
        ascent_fraction=1.0 - 2e-9,
        flat_fraction=2e-9,
        regime_class=RegimeClass.MIXED,
    )
    assert segment.regime_class is RegimeClass.MIXED


@pytest.mark.parametrize(
    ("time_name", "realized_name"),
    [("start_s", "realized_start_m"), ("end_s", "realized_end_m")],
)
def test_time_and_realized_abscissa_go_together(
    time_name: str, realized_name: str
) -> None:
    for name in (time_name, realized_name):
        changes: dict[str, Any] = {name: None}
        with pytest.raises(ContractError, match=f"{time_name} doit être présent si"):
            replace(ADMITTED, **changes)


@pytest.mark.parametrize(
    "name", ["start_s", "end_s", "realized_start_m", "realized_end_m"]
)
@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_dating_values_are_finite_and_non_negative(name: str, value: float) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=f"{name} doit être"):
        replace(ADMITTED, **changes)


def test_start_time_precedes_end_time() -> None:
    with pytest.raises(ContractError, match=r"start_s .* doit précéder end_s"):
        replace(ADMITTED, end_s=0.0)


def test_realized_start_is_not_after_realized_end() -> None:
    with pytest.raises(ContractError, match=r"realized_start_m .* doit être <="):
        replace(ADMITTED, realized_start_m=300.0)


def test_realized_abscissas_may_be_equal() -> None:
    """Un arrêt sur tout le segment : ``d_r`` inchangé, temps croissant."""
    segment = replace(ADMITTED, realized_end_m=0.0)
    assert segment.realized_end_m == segment.realized_start_m


@pytest.mark.parametrize("name", ["length_ratio", "h1_m", "h2_m"])
def test_controls_are_all_present_or_all_absent(name: str) -> None:
    changes: dict[str, Any] = {name: None}
    with pytest.raises(ContractError, match="tous présents ou tous absents"):
        replace(ADMITTED, **changes)


@pytest.mark.parametrize("name", ["length_ratio", "h1_m", "h2_m"])
@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_controls_are_finite_and_non_negative(name: str, value: float) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=f"{name} doit être"):
        replace(ADMITTED, **changes)


def test_admitted_segment_publishes_its_ratio() -> None:
    with pytest.raises(ContractError, match="un segment admis publie"):
        replace(ADMITTED, length_ratio=None, h1_m=None, h2_m=None)


def test_admitted_segment_publishes_both_times() -> None:
    with pytest.raises(ContractError, match="un segment admis publie"):
        replace(ADMITTED, end_s=None, realized_end_m=None)


def test_unobserved_bound_publishes_no_ratio() -> None:
    with pytest.raises(ContractError, match="unobserved_bound ne publie pas"):
        replace(UNOBSERVED, length_ratio=1.0, h1_m=0.0, h2_m=0.0)


def test_unobserved_bound_has_an_undated_bound() -> None:
    with pytest.raises(ContractError, match="unobserved_bound a une borne non datée"):
        replace(
            ADMITTED,
            exclusion=SegmentExclusion.UNOBSERVED_BOUND,
            length_ratio=None,
            h1_m=None,
            h2_m=None,
        )


def test_gap_publishes_no_ratio() -> None:
    with pytest.raises(ContractError, match="un segment gap ne publie pas"):
        replace(ADMITTED, exclusion=SegmentExclusion.GAP)


def test_gap_publishes_both_times() -> None:
    with pytest.raises(ContractError, match="un segment gap publie start_s et end_s"):
        replace(GAP, end_s=None, realized_end_m=None)


@pytest.mark.parametrize(
    "exclusion", [SegmentExclusion.LENGTH_RATIO, SegmentExclusion.INTERIOR_DEVIATION]
)
@pytest.mark.parametrize(
    "changes",
    [
        {"length_ratio": None, "h1_m": None, "h2_m": None},
        {"start_s": None, "realized_start_m": None},
    ],
)
def test_ratio_and_interior_exclusions_publish_ratio_and_times(
    exclusion: SegmentExclusion, changes: dict[str, Any]
) -> None:
    with pytest.raises(ContractError, match=f"un segment {exclusion} publie"):
        replace(ADMITTED, exclusion=exclusion, **changes)


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------

COVERAGE_FLOATS = (
    "reference_length_m",
    "admitted_m",
    "excluded_unobserved_bound_m",
    "excluded_gap_m",
    "excluded_length_ratio_m",
    "excluded_interior_deviation_m",
    "anchoring_excluded_m",
    "ascent_length_m",
    "flat_length_m",
    "descent_length_m",
    "admitted_ascent_m",
    "admitted_flat_m",
    "admitted_descent_m",
    "admitted_elapsed_s",
    "excluded_gap_s",
    "excluded_length_ratio_s",
    "excluded_interior_deviation_s",
    "prefix_end_m",
    "prefix_end_s",
)


def test_coverage_fractions() -> None:
    """X01 : couverture 0,90566, plat 0,90566, montée et descente non évaluées."""
    assert X01_COVERAGE.fraction == pytest.approx(0.90566, abs=1e-6)
    assert X01_COVERAGE.regime_fraction(Regime.FLAT) == pytest.approx(0.90566, abs=1e-6)
    assert X01_COVERAGE.regime_fraction(Regime.ASCENT) is None
    assert X01_COVERAGE.regime_fraction(Regime.DESCENT) is None


@pytest.mark.parametrize("name", COVERAGE_FLOATS)
@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_coverage_values_are_finite_and_non_negative(name: str, value: float) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=f"{name} doit être"):
        replace(X01_COVERAGE, **changes)


def test_prefix_end_time_may_be_absent() -> None:
    assert replace(X01_COVERAGE, prefix_end_s=None).prefix_end_s is None


def test_reference_length_is_positive() -> None:
    with pytest.raises(ContractError, match="reference_length_m doit être > 0"):
        replace(X01_COVERAGE, reference_length_m=0.0)


def test_admitted_excluded_and_anchoring_sum_to_the_length() -> None:
    with pytest.raises(ContractError, match="anchoring_excluded_m doit valoir"):
        replace(X01_COVERAGE, admitted_m=470.0)


def test_partition_of_the_length_within_the_tolerance() -> None:
    """``1e−6·max(1, L)`` : 5e−4 m passe sur 530 m, 6e−4 m non."""
    assert replace(X01_COVERAGE, admitted_m=480.0005).admitted_m == 480.0005
    with pytest.raises(ContractError, match="anchoring_excluded_m doit valoir"):
        replace(X01_COVERAGE, admitted_m=480.0006)


def test_regime_lengths_sum_to_the_length() -> None:
    with pytest.raises(ContractError, match="descent_length_m doit valoir"):
        replace(X01_COVERAGE, descent_length_m=10.0)


@pytest.mark.parametrize("regime", list(Regime))
def test_admitted_regime_length_is_not_above_its_length(regime: Regime) -> None:
    changes: dict[str, Any] = {f"admitted_{regime.value}_m": X01_LENGTH_M + 1.0}
    with pytest.raises(ContractError, match=f"admitted_{regime.value}_m .* <="):
        replace(X01_COVERAGE, **changes)


def test_prefix_segment_count_is_non_negative() -> None:
    with pytest.raises(ContractError, match="prefix_segment_count doit être >= 0"):
        replace(X01_COVERAGE, prefix_segment_count=-1)


@pytest.mark.parametrize("name", ["", "   "])
def test_prefix_last_passage_is_not_empty(name: str) -> None:
    with pytest.raises(ContractError, match="prefix_last_passage ne doit pas"):
        replace(X01_COVERAGE, prefix_last_passage=name)


# ---------------------------------------------------------------------------
# AdmittedTotals et SensitivityConfiguration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["elapsed_s", "moving_s", "stopped_s", "undetermined_s"]
)
@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_admitted_totals_are_finite_and_non_negative(name: str, value: float) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=f"{name} doit être"):
        replace(X01_ADMITTED_TOTALS, **changes)


def test_admitted_totals_identity() -> None:
    """``|M + S + U − E_A| <= 1e−9·max(1, E_A)`` : 3e−7 passe sur 320 s."""
    assert replace(X01_ADMITTED_TOTALS, moving_s=284.0000003).moving_s == 284.0000003
    with pytest.raises(ContractError, match="doit valoir elapsed_s"):
        replace(X01_ADMITTED_TOTALS, moving_s=284.000001)


def test_admitted_totals_are_not_trace_totals() -> None:
    """D5.4 : les deux jeux ne se mélangent jamais."""
    assert not issubclass(AdmittedTotals, ClockTotals)
    assert not issubclass(ClockTotals, AdmittedTotals)


CENTRAL = SensitivityConfiguration(250.0, 30.0, 15.0, CLOCKS[0])


@pytest.mark.parametrize(
    "name", ["score_step_m", "lateral_tolerance_m", "cluster_radius_m"]
)
@given(value=non_finite_floats())
def test_configuration_values_are_finite(name: str, value: float) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=f"{name} doit être fini"):
        replace(CENTRAL, **changes)


@pytest.mark.parametrize("name", ["score_step_m", "lateral_tolerance_m"])
@pytest.mark.parametrize("value", [0.0, -1.0])
def test_step_and_tolerance_are_positive(name: str, value: float) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=f"{name} doit être > 0"):
        replace(CENTRAL, **changes)


def test_cluster_radius_is_non_negative() -> None:
    assert replace(CENTRAL, cluster_radius_m=0.0).cluster_radius_m == 0.0
    with pytest.raises(ContractError, match="cluster_radius_m doit être >= 0"):
        replace(CENTRAL, cluster_radius_m=-1.0)


# ---------------------------------------------------------------------------
# MatchResult
# ---------------------------------------------------------------------------


def test_result_examples_build() -> None:
    assert replace(X01_RESULT) == X01_RESULT
    assert _no_admitted_result().low_convention_index is None


@pytest.mark.parametrize(
    "name", ["points", "segments", "trace_totals", "admitted_totals"]
)
def test_result_sequences_are_tuples(name: str) -> None:
    changes: dict[str, Any] = {name: list(getattr(X01_RESULT, name))}
    with pytest.raises(ContractError, match=f"{name} doit être une séquence immuable"):
        replace(X01_RESULT, **changes)


def test_result_has_at_least_two_points() -> None:
    with pytest.raises(ContractError, match="au moins 2 points"):
        replace(X01_RESULT, points=X01_POINTS[:1], segments=())


def test_result_has_one_segment_less_than_points() -> None:
    with pytest.raises(ContractError, match="len\\(points\\) − 1"):
        replace(X01_RESULT, segments=X01_SEGMENTS[:2])


def test_points_are_indexed_in_order() -> None:
    with pytest.raises(ContractError, match=r"points\[1\].index doit valoir 1"):
        replace(X01_RESULT, points=_with_point(1, index=5))


def test_segments_are_indexed_in_order() -> None:
    with pytest.raises(ContractError, match=r"segments\[2\].index doit valoir 2"):
        replace(X01_RESULT, segments=_with_segment(2, index=5))


def test_first_point_is_at_zero() -> None:
    with pytest.raises(ContractError, match=r"points\[0\].nominal_m doit valoir 0"):
        replace(X01_RESULT, points=_with_point(0, nominal_m=1.0))


def test_last_point_is_at_the_reference_length() -> None:
    with pytest.raises(ContractError, match=r"coverage.reference_length_m"):
        replace(X01_RESULT, points=_with_point(3, nominal_m=530.0))


def test_nominal_abscissas_increase() -> None:
    with pytest.raises(ContractError, match="nominal_m doit être strictement"):
        replace(X01_RESULT, points=_with_point(1, nominal_m=600.0, effective_m=600.0))


def test_effective_bounds_increase() -> None:
    with pytest.raises(ContractError, match="effective_m doit être strictement"):
        replace(X01_RESULT, points=_with_point(0, effective_m=260.0))


def test_only_the_ends_have_an_effective_bound() -> None:
    points = _with_point(
        1,
        status=PointStatus.ANCHORED,
        effective_m=260.0,
        candidate_count=0,
        event_count=0,
    )
    with pytest.raises(ContractError, match="qu'au premier et au dernier point"):
        replace(X01_RESULT, points=points)


@pytest.mark.parametrize(("name", "value"), [("position", 70.0), ("time_s", 100.0)])
def test_dated_points_increase_in_position_and_time(name: str, value: float) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=f"{name} doit être strictement croissant"):
        replace(X01_RESULT, points=_with_point(2, **changes))


@pytest.mark.parametrize(
    ("k", "name", "value"),
    [
        (0, "nominal_start_m", 1.0),
        (0, "start_m", 26.0),
        (0, "start_s", 1.0),
        (0, "realized_start_m", 1.0),
        (2, "nominal_end_m", 600.0),
        (2, "end_m", 504.0),
        (2, "end_s", 319.0),
        (2, "realized_end_m", 480.0),
    ],
)
def test_segment_bounds_are_those_of_their_points(
    k: int, name: str, value: float
) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=f"segments\\[{k}\\].{name} .* reprendre"):
        replace(X01_RESULT, segments=_with_segment(k, **changes))


def test_unobserved_segment_has_an_undated_bound() -> None:
    """Les deux bornes du segment 1 sont datées : il ne peut pas être
    ``unobserved_bound``."""
    segments = _with_segment(
        1,
        exclusion=SegmentExclusion.UNOBSERVED_BOUND,
        length_ratio=None,
        h1_m=None,
        h2_m=None,
        end_s=None,
        realized_end_m=None,
    )
    with pytest.raises(ContractError, match="unobserved_bound si et seulement si"):
        replace(X01_RESULT, segments=segments)


def test_segment_with_an_undated_bound_is_unobserved() -> None:
    """Point 2 absent : les segments 1 et 2, qui le touchent, sont
    ``unobserved_bound``."""
    points = _with_point(
        2,
        status=PointStatus.ABSENT,
        position=None,
        time_s=None,
        lateral_m=None,
        realized_m=None,
        candidate_count=0,
        event_count=0,
    )
    with pytest.raises(ContractError, match="unobserved_bound si et seulement si"):
        replace(X01_RESULT, points=points)


def test_prefix_does_not_exceed_the_segments() -> None:
    coverage = replace(X01_COVERAGE, prefix_segment_count=4)
    with pytest.raises(ContractError, match="dépasse le nombre de segments"):
        replace(X01_RESULT, coverage=coverage)


def test_prefix_segments_are_admitted() -> None:
    segments = _with_segment(1, exclusion=SegmentExclusion.LENGTH_RATIO)
    with pytest.raises(ContractError, match="premiers segments du préfixe"):
        replace(X01_RESULT, segments=segments)


def test_prefix_is_the_longest() -> None:
    coverage = replace(
        X01_COVERAGE,
        prefix_segment_count=2,
        prefix_end_m=500.0,
        prefix_end_s=316.666667,
    )
    with pytest.raises(ContractError, match="le préfixe comparable est le plus long"):
        replace(X01_RESULT, coverage=coverage)


def test_prefix_end_is_the_effective_bound_of_point_m() -> None:
    coverage = replace(X01_COVERAGE, prefix_end_m=X01_LENGTH_M)
    with pytest.raises(ContractError, match=r"prefix_end_m .* points\[3\]"):
        replace(X01_RESULT, coverage=coverage)


@pytest.mark.parametrize("value", [319.0, None])
def test_prefix_end_time_is_the_time_of_point_m(value: float | None) -> None:
    coverage = replace(X01_COVERAGE, prefix_end_s=value)
    with pytest.raises(ContractError, match=r"prefix_end_s .* points\[3\]"):
        replace(X01_RESULT, coverage=coverage)


@pytest.mark.parametrize("value", [1.0, None])
def test_departure_delay_is_the_time_of_the_first_point(value: float | None) -> None:
    with pytest.raises(ContractError, match=r"departure_delay_s .* points\[0\]"):
        replace(X01_RESULT, departure_delay_s=value)


@pytest.mark.parametrize("name", ["trace_totals", "admitted_totals"])
def test_five_totals_in_each_set(name: str) -> None:
    changes: dict[str, Any] = {name: getattr(X01_RESULT, name)[:4]}
    with pytest.raises(ContractError, match=f"{name} doit porter 5 totaux"):
        replace(X01_RESULT, **changes)


def test_admitted_elapsed_is_the_same_in_every_total() -> None:
    totals = (*(X01_ADMITTED_TOTALS,) * 4, AdmittedTotals(321.0, 285.0, 0.0, 36.0))
    with pytest.raises(ContractError, match=r"admitted_totals\[4\].elapsed_s"):
        replace(X01_RESULT, admitted_totals=totals)


def test_admitted_elapsed_is_that_of_the_coverage() -> None:
    """R5 (correctifs de la PR #10) : ``MatchResult`` de X01 par ``match_trace``
    (écoulé admis 320 s) ; les cinq totaux admis remplacés par
    ``(321, 285, 0, 36)``, égaux entre eux, identité tenue, extrêmes et ``I_sens,A``
    cohérents : seule l'égalité à ``coverage.admitted_elapsed_s`` est violée."""
    result = matched(x01())
    assert result.coverage.admitted_elapsed_s == pytest.approx(320.0, abs=1e-6)
    with pytest.raises(ContractError, match=r"coverage\.admitted_elapsed_s"):
        replace(
            result,
            admitted_totals=(AdmittedTotals(321.0, 285.0, 0.0, 36.0),) * 5,
            low_convention_index=0,
            high_convention_index=0,
            admitted_sensitivity_range_s=(285.0, 320.0),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"low_convention_index": 0},
        {"high_convention_index": 0},
        {"admitted_sensitivity_range_s": (0.0, 0.0)},
    ],
)
def test_extremes_are_absent_without_admitted_segment(changes: dict[str, Any]) -> None:
    with pytest.raises(ContractError, match="absents sans segment admis"):
        replace(_no_admitted_result(), **changes)


@pytest.mark.parametrize(
    "name",
    ["low_convention_index", "high_convention_index", "admitted_sensitivity_range_s"],
)
def test_extremes_are_present_with_an_admitted_segment(name: str) -> None:
    changes: dict[str, Any] = {name: None}
    with pytest.raises(ContractError, match="présents dès qu'un segment est admis"):
        replace(X01_RESULT, **changes)


def test_low_convention_is_the_first_minimum_of_moving() -> None:
    """Cinq totaux égaux : le premier indice, 0."""
    with pytest.raises(ContractError, match=r"low_convention_index .* premier indice"):
        replace(X01_RESULT, low_convention_index=1)


def test_high_convention_is_the_first_maximum_of_moving_or_undetermined() -> None:
    with pytest.raises(ContractError, match=r"high_convention_index .* premier indice"):
        replace(X01_RESULT, high_convention_index=4)


@pytest.mark.parametrize(
    ("interval", "bound"), [((283.0, 320.0), "basse"), ((284.0, 319.0), "haute")]
)
def test_sensitivity_range_is_min_moving_and_elapsed_minus_min_stopped(
    interval: tuple[float, float], bound: str
) -> None:
    with pytest.raises(ContractError, match=f"la borne {bound}"):
        replace(X01_RESULT, admitted_sensitivity_range_s=interval)


def test_sensitivity_range_within_the_tolerance() -> None:
    """``1e−9·max(1, E_A)`` = 3,2e−7 s sur 320 s ; la borne basse peut dépasser la
    haute d'un ulp sur un support entièrement mobile."""
    result = replace(X01_RESULT, admitted_sensitivity_range_s=(284.0000003, 320.0))
    assert result.admitted_sensitivity_range_s == (284.0000003, 320.0)
    mobile = AdmittedTotals(320.0, 320.0, 0.0, 0.0)
    all_mobile = replace(
        X01_RESULT,
        admitted_totals=(mobile,) * 5,
        admitted_sensitivity_range_s=(320.00000000000006, 320.0),
    )
    assert all_mobile.admitted_sensitivity_range_s == (320.00000000000006, 320.0)
