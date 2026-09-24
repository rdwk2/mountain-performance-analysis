"""Tests des contrats des points de score (§ 5a.1 du brief M4a-2a, ``0010`` D4.2–D4.8).

Un test par invariant de ``ScorePointObservation``. Quand la violation d'un invariant
en entraîne logiquement une autre, le test vise l'invariant par le message de
l'exception, qui le nomme.
"""

from dataclasses import replace
from typing import Any

import pytest
from hypothesis import given

from mountain_perf.schemas import (
    POINT_STATUS_DESCRIPTIONS,
    ContractError,
    PointStatus,
    ScorePointObservation,
)
from mountain_perf.schemas._dictionary import render
from strategies import non_finite_floats, score_point_observations

FOUND_POINT = ScorePointObservation(
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
)
"""Point 1 de X01 (§ 7.2a)."""

ANCHORED_POINT = ScorePointObservation(
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
)
"""Départ ancré de X01 (§ 7.2a)."""

ABSENT_POINT = ScorePointObservation(
    index=2,
    nominal_m=500.0,
    effective_m=500.0,
    status=PointStatus.ABSENT,
    position=None,
    time_s=None,
    lateral_m=None,
    realized_m=None,
    candidate_count=0,
    event_count=0,
)

DATED_FIELDS = ("position", "time_s", "lateral_m", "realized_m")
UNDATED_STATUSES = (
    PointStatus.AMBIGUOUS,
    PointStatus.ABSENT,
    PointStatus.OUT_OF_TOLERANCE,
    PointStatus.UNDEFINED_TANGENT,
)


def _undated(status: PointStatus, **changes: Any) -> ScorePointObservation:
    return replace(ABSENT_POINT, status=status, **changes)


# ---------------------------------------------------------------------------
# PointStatus
# ---------------------------------------------------------------------------


def test_every_status_is_described() -> None:
    assert set(POINT_STATUS_DESCRIPTIONS) == set(PointStatus)
    assert all(text.strip() for text in POINT_STATUS_DESCRIPTIONS.values())


def test_the_six_statuses_of_0010() -> None:
    assert [status.value for status in PointStatus] == [
        "found",
        "anchored",
        "ambiguous",
        "absent",
        "out_of_tolerance",
        "undefined_tangent",
    ]


def test_status_and_observation_are_in_the_dictionary() -> None:
    text = render()
    assert "## `PointStatus`" in text
    assert "## `ScorePointObservation`" in text
    for status in PointStatus:
        assert f"| `{status.name}` | `{status.value}` |" in text


# ---------------------------------------------------------------------------
# Objets valides
# ---------------------------------------------------------------------------


@given(score_point_observations())
def test_valid_observations_build(point: ScorePointObservation) -> None:
    assert point.dated == (point.position is not None)


@pytest.mark.parametrize("point", [FOUND_POINT, ANCHORED_POINT, ABSENT_POINT])
def test_examples_build(point: ScorePointObservation) -> None:
    assert replace(point) == point


def test_dated_means_found_or_anchored() -> None:
    assert FOUND_POINT.dated
    assert ANCHORED_POINT.dated
    assert not any(_undated(status).dated for status in UNDATED_STATUSES)


def test_anchoring_offset_is_effective_minus_nominal() -> None:
    """``s'_0 >= 0`` au départ (X01 : 25 m), ``s'_K − L <= 0`` à l'arrivée (X01 :
    ``505 − 530``), nul hors ancrage."""
    assert ANCHORED_POINT.anchoring_offset_m == 25.0
    arrival = replace(ANCHORED_POINT, index=3, nominal_m=530.0, effective_m=505.0)
    assert arrival.anchoring_offset_m == -25.0
    assert FOUND_POINT.anchoring_offset_m == 0.0


def test_anchored_point_may_keep_its_nominal_bound() -> None:
    """Projection d'ancrage sur l'extrémité du tracé : décalage nul (constat F1)."""
    point = replace(ANCHORED_POINT, effective_m=0.0)
    assert point.anchoring_offset_m == 0.0


def test_lateral_offset_may_be_negative() -> None:
    """L'écart latéral est signé : négatif à droite du sens de parcours."""
    assert replace(FOUND_POINT, lateral_m=-29.0).lateral_m == -29.0


@pytest.mark.parametrize(("candidates", "events"), [(0, 0), (2, 2), (3, 2), (5, 4)])
def test_ambiguous_counts_that_build(candidates: int, events: int) -> None:
    point = _undated(
        PointStatus.AMBIGUOUS, candidate_count=candidates, event_count=events
    )
    assert point.status is PointStatus.AMBIGUOUS


# ---------------------------------------------------------------------------
# Invariants — un test chacun
# ---------------------------------------------------------------------------


def test_index_is_non_negative() -> None:
    with pytest.raises(ContractError, match="index doit être >= 0"):
        replace(FOUND_POINT, index=-1)


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_nominal_is_finite_and_non_negative(value: float) -> None:
    with pytest.raises(ContractError, match="nominal_m doit être"):
        replace(FOUND_POINT, nominal_m=value, effective_m=value)


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_effective_is_finite_and_non_negative(value: float) -> None:
    with pytest.raises(ContractError, match="effective_m doit être"):
        replace(ANCHORED_POINT, effective_m=value)


@pytest.mark.parametrize("status", [PointStatus.FOUND, *UNDATED_STATUSES])
def test_only_an_anchored_point_has_an_effective_bound(status: PointStatus) -> None:
    point = FOUND_POINT if status is PointStatus.FOUND else _undated(status)
    with pytest.raises(ContractError, match="ne peut différer de nominal_m"):
        replace(point, effective_m=point.nominal_m + 1.0)


@pytest.mark.parametrize("name", DATED_FIELDS)
@pytest.mark.parametrize("point", [FOUND_POINT, ANCHORED_POINT])
def test_dated_point_has_all_dating_fields(
    point: ScorePointObservation, name: str
) -> None:
    changes: dict[str, Any] = {name: None}
    with pytest.raises(ContractError, match=f"{name} doit être présent"):
        replace(point, **changes)


@pytest.mark.parametrize("name", DATED_FIELDS)
@pytest.mark.parametrize("status", UNDATED_STATUSES)
def test_undated_point_has_no_dating_field(status: PointStatus, name: str) -> None:
    changes: dict[str, Any] = {name: 1.0}
    with pytest.raises(ContractError, match=f"{name} doit être absent"):
        _undated(status, **changes)


@pytest.mark.parametrize("name", DATED_FIELDS)
def test_dating_fields_are_finite(name: str) -> None:
    for value in (float("nan"), float("inf"), float("-inf")):
        changes: dict[str, Any] = {name: value}
        with pytest.raises(ContractError, match=f"{name} doit être fini"):
            replace(FOUND_POINT, **changes)


@given(non_finite_floats())
def test_dating_fields_refuse_any_non_finite_value(value: float) -> None:
    with pytest.raises(ContractError, match="lateral_m doit être fini"):
        replace(FOUND_POINT, lateral_m=value)


@pytest.mark.parametrize("name", ["position", "time_s", "realized_m"])
def test_position_time_and_realized_are_non_negative(name: str) -> None:
    changes: dict[str, Any] = {name: -0.5}
    with pytest.raises(ContractError, match=f"{name} doit être >= 0"):
        replace(FOUND_POINT, **changes)


def test_anchored_position_is_an_integer() -> None:
    """L'ancrage date par un enregistrement ; un point trouvé, lui, peut tomber entre
    deux."""
    assert replace(FOUND_POINT, position=2.5).position == 2.5
    with pytest.raises(ContractError, match="position doit être entière"):
        replace(ANCHORED_POINT, position=2.5)


@pytest.mark.parametrize("name", ["candidate_count", "event_count"])
def test_counts_are_non_negative(name: str) -> None:
    changes: dict[str, Any] = {name: -1}
    with pytest.raises(ContractError, match=f"{name} doit être >= 0"):
        _undated(PointStatus.AMBIGUOUS, **changes)


def test_events_never_outnumber_candidates() -> None:
    with pytest.raises(ContractError, match=r"event_count \(3\) doit être <="):
        _undated(PointStatus.AMBIGUOUS, candidate_count=2, event_count=3)


@pytest.mark.parametrize(("candidates", "events"), [(2, 0), (3, 2), (4, 3)])
def test_found_point_has_one_event(candidates: int, events: int) -> None:
    with pytest.raises(ContractError, match="event_count doit valoir 1"):
        replace(FOUND_POINT, candidate_count=candidates, event_count=events)


@pytest.mark.parametrize(
    "status",
    [
        PointStatus.ABSENT,
        PointStatus.OUT_OF_TOLERANCE,
        PointStatus.UNDEFINED_TANGENT,
    ],
)
def test_statuses_without_candidate(status: PointStatus) -> None:
    with pytest.raises(ContractError, match="candidate_count doit valoir 0"):
        _undated(status, candidate_count=1, event_count=1)


def test_anchored_point_has_no_candidate() -> None:
    """Un ancrage ne s'applique que sans candidat admissible (D4.8)."""
    with pytest.raises(ContractError, match="candidate_count doit valoir 0"):
        replace(ANCHORED_POINT, candidate_count=1, event_count=0)


@pytest.mark.parametrize(("candidates", "events"), [(1, 1), (1, 0), (3, 1)])
def test_ambiguous_point_has_two_events_or_no_candidate(
    candidates: int, events: int
) -> None:
    with pytest.raises(ContractError, match="au moins deux événements"):
        _undated(PointStatus.AMBIGUOUS, candidate_count=candidates, event_count=events)
