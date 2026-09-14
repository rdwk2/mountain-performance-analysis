"""Tests des contrats de la courbe : CurveProvenance, PaceCurve.

Un test de refus par invariant dur (chacun attend ``ContractError``), sur la fixture
à cinq tranches modifiée champ par champ par ``replace``.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fixtures.performance import FIVE_BIN_CURVE, MANUAL_PROVENANCE
from mountain_perf.schemas import ContractError, CurveProvenance, PaceCurve
from strategies import (
    blank_texts,
    curve_provenances,
    finite_floats,
    naive_datetimes,
    non_finite_floats,
    pace_curves,
)


def _with_value(values: Sequence[Any], index: int, value: Any) -> tuple[Any, ...]:
    return (*values[:index], value, *values[index + 1 :])


# ---------------------------------------------------------------------------
# CurveProvenance
# ---------------------------------------------------------------------------


@given(curve_provenances())
def test_valid_provenances_build(provenance: CurveProvenance) -> None:
    assert provenance.generated_at.tzinfo is UTC


def test_provenance_generated_at_is_normalised_to_utc() -> None:
    local = datetime(2026, 9, 14, 10, 0, tzinfo=timezone(timedelta(hours=2)))
    provenance = replace(MANUAL_PROVENANCE, generated_at=local)
    assert provenance.generated_at == datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
    assert provenance.generated_at.tzinfo is UTC


def test_provenance_zero_activities_and_no_filter_are_legitimate() -> None:
    assert MANUAL_PROVENANCE.activity_count == 0
    assert MANUAL_PROVENANCE.source_activity_types == frozenset()


def test_provenance_negative_activity_count_is_refused() -> None:
    with pytest.raises(ContractError, match="activity_count"):
        replace(MANUAL_PROVENANCE, activity_count=-1)


@pytest.mark.parametrize(
    ("center", "width"), [(150.0, None), (None, 10.0)], ids=["center", "width"]
)
def test_provenance_hr_window_half_given_is_refused(
    center: float | None, width: float | None
) -> None:
    with pytest.raises(ContractError, match="ensemble"):
        replace(MANUAL_PROVENANCE, hr_center_bpm=center, hr_width_bpm=width)


@given(
    st.one_of(
        finite_floats(250.001, 1e4), finite_floats(-1e4, 19.999), non_finite_floats()
    )
)
def test_provenance_bad_hr_center_is_refused(center: float) -> None:
    with pytest.raises(ContractError, match="hr_center_bpm"):
        replace(MANUAL_PROVENANCE, hr_center_bpm=center, hr_width_bpm=10.0)


@given(st.one_of(st.floats(max_value=0.0), non_finite_floats()))
def test_provenance_bad_hr_width_is_refused(width: float) -> None:
    with pytest.raises(ContractError, match="hr_width_bpm"):
        replace(MANUAL_PROVENANCE, hr_center_bpm=150.0, hr_width_bpm=width)


def test_provenance_date_window_reversed_is_refused() -> None:
    with pytest.raises(ContractError, match="date_from"):
        replace(MANUAL_PROVENANCE, date_from=date(2026, 7, 1))


@given(st.one_of(st.floats(max_value=-1e-9), non_finite_floats()))
def test_provenance_bad_min_duration_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match="min_duration_s"):
        replace(MANUAL_PROVENANCE, min_duration_s=value)


@given(blank_texts())
def test_provenance_blank_estimator_is_refused(estimator: str) -> None:
    with pytest.raises(ContractError, match="estimator"):
        replace(MANUAL_PROVENANCE, estimator=estimator)


@given(naive_datetimes())
def test_provenance_naive_generated_at_is_refused(generated_at: datetime) -> None:
    with pytest.raises(ContractError, match="generated_at"):
        replace(MANUAL_PROVENANCE, generated_at=generated_at)


# ---------------------------------------------------------------------------
# PaceCurve
# ---------------------------------------------------------------------------


@given(pace_curves())
def test_valid_curves_build(curve: PaceCurve) -> None:
    assert len(curve.grade) == len(curve.sample_count) >= 2


def test_curve_carries_its_provenance_and_sample_count() -> None:
    assert FIVE_BIN_CURVE.estimation is MANUAL_PROVENANCE
    assert FIVE_BIN_CURVE.sample_count == (10, 40, 100, 40, 10)


@pytest.mark.parametrize("name", ["grade", "speed_ms", "sample_count", "dispersion_ms"])
def test_curve_array_of_a_different_length_is_refused(name: str) -> None:
    changes: dict[str, Any] = {name: getattr(FIVE_BIN_CURVE, name)[:-1]}
    with pytest.raises(ContractError, match="longueurs différentes"):
        replace(FIVE_BIN_CURVE, **changes)


@pytest.mark.parametrize("name", ["grade", "speed_ms", "sample_count", "dispersion_ms"])
def test_curve_mutable_arrays_are_refused(name: str) -> None:
    changes: dict[str, Any] = {name: list(getattr(FIVE_BIN_CURVE, name))}
    with pytest.raises(ContractError, match=f"{name}.*tuple"):
        replace(FIVE_BIN_CURVE, **changes)


def test_curve_with_a_single_bin_is_refused() -> None:
    with pytest.raises(ContractError, match="au moins 2"):
        replace(
            FIVE_BIN_CURVE,
            grade=(0.0,),
            speed_ms=(3.0,),
            sample_count=(1,),
            dispersion_ms=None,
        )


@pytest.mark.parametrize("name", ["grade", "speed_ms", "dispersion_ms"])
@given(value=non_finite_floats())
def test_curve_non_finite_value_is_refused(name: str, value: float) -> None:
    changes: dict[str, Any] = {
        name: _with_value(getattr(FIVE_BIN_CURVE, name), 2, value)
    }
    with pytest.raises(ContractError, match=name):
        replace(FIVE_BIN_CURVE, **changes)


@pytest.mark.parametrize("repeated", [-0.2, -0.3])
def test_curve_grade_not_strictly_increasing_is_refused(repeated: float) -> None:
    grades = _with_value(FIVE_BIN_CURVE.grade, 2, repeated)
    with pytest.raises(ContractError, match=r"grade.*strictement croissante"):
        replace(FIVE_BIN_CURVE, grade=grades)


@pytest.mark.parametrize("grades", [(-40.0, -20.0, 0.0, 20.0, 40.0)])
def test_curve_grade_as_percentage_is_refused(grades: tuple[float, ...]) -> None:
    with pytest.raises(ContractError, match=r"grade\[0\]"):
        replace(FIVE_BIN_CURVE, grade=grades)


@given(finite_floats(-100.0, 0.0))
def test_curve_non_positive_speed_is_refused(speed: float) -> None:
    with pytest.raises(ContractError, match=r"speed_ms\[2\]"):
        replace(FIVE_BIN_CURVE, speed_ms=_with_value(FIVE_BIN_CURVE.speed_ms, 2, speed))


def test_curve_negative_sample_count_is_refused() -> None:
    counts = _with_value(FIVE_BIN_CURVE.sample_count, 2, -1)
    with pytest.raises(ContractError, match=r"sample_count\[2\]"):
        replace(FIVE_BIN_CURVE, sample_count=counts)


@given(finite_floats(-100.0, -1e-9))
def test_curve_negative_dispersion_is_refused(value: float) -> None:
    dispersion = _with_value(FIVE_BIN_CURVE.dispersion_ms or (), 2, value)
    with pytest.raises(ContractError, match=r"dispersion_ms\[2\]"):
        replace(FIVE_BIN_CURVE, dispersion_ms=dispersion)


def test_curve_dispersion_and_source_are_optional() -> None:
    curve = replace(FIVE_BIN_CURVE, dispersion_ms=None, source=None)
    assert curve.dispersion_ms is None
    assert curve.source is None
