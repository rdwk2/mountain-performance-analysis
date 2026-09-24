"""Tests des contrats des horloges (§ 4.1 du brief M4a-1, ``0010`` D5)."""

from dataclasses import replace
from typing import Any

import pytest
from hypothesis import given

from mountain_perf.schemas import (
    CENTRAL_CONVENTION_INDEX,
    CLOCK_CONVENTIONS,
    CLOCK_KIND_DESCRIPTIONS,
    CLOCKS,
    INTERVAL_STATE_DESCRIPTIONS,
    Clock,
    ClockConvention,
    ClockKind,
    ClockPartition,
    ClockTotals,
    ContractError,
    IntervalState,
    StopEpisode,
)
from strategies import clock_partitions, non_finite_floats

M, S, U = IntervalState.MOVING, IntervalState.STOPPED, IntervalState.UNDETERMINED


@pytest.mark.parametrize(
    ("enum", "descriptions"),
    [
        (IntervalState, INTERVAL_STATE_DESCRIPTIONS),
        (ClockKind, CLOCK_KIND_DESCRIPTIONS),
    ],
)
def test_every_member_is_described(enum: Any, descriptions: Any) -> None:
    assert set(descriptions) == set(enum)
    assert all(text.strip() for text in descriptions.values())


# ---------------------------------------------------------------------------
# Conventions et horloges
# ---------------------------------------------------------------------------


def test_the_five_conventions_of_0010_d5_2_in_order() -> None:
    assert [
        (c.max_horizontal_speed_ms, c.max_vertical_speed_ms, c.min_stop_s)
        for c in CLOCK_CONVENTIONS
    ] == [
        (0.05, 0.015, 60.0),
        (0.10, 0.03, 60.0),
        (0.15, 0.045, 60.0),
        (0.10, 0.03, 30.0),
        (0.10, 0.03, 90.0),
    ]
    assert CLOCK_CONVENTIONS[CENTRAL_CONVENTION_INDEX] == ClockConvention(
        0.10, 0.03, 60.0
    )


@pytest.mark.parametrize(
    "name", ["max_horizontal_speed_ms", "max_vertical_speed_ms", "min_stop_s"]
)
@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf")])
def test_convention_values_are_finite_and_positive(name: str, value: float) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=name):
        replace(CLOCK_CONVENTIONS[0], **changes)


def test_the_eleven_clocks_in_order() -> None:
    """``0010`` D5.4 : écoulé, ``M_θ1…M_θ5``, ``(M+U)_θ1…(M+U)_θ5``."""
    assert [(clock.kind, clock.convention_index) for clock in CLOCKS] == [
        (ClockKind.ELAPSED, None),
        *((ClockKind.MOVING, i) for i in range(5)),
        *((ClockKind.MOVING_OR_UNDETERMINED, i) for i in range(5)),
    ]


def test_elapsed_clock_has_no_convention() -> None:
    with pytest.raises(ContractError, match="None pour l'écoulé"):
        Clock(ClockKind.ELAPSED, 0)


@pytest.mark.parametrize("kind", [ClockKind.MOVING, ClockKind.MOVING_OR_UNDETERMINED])
@pytest.mark.parametrize("index", [None, -1, 5])
def test_movement_clocks_have_a_convention_in_range(
    kind: ClockKind, index: int | None
) -> None:
    with pytest.raises(
        ContractError, match=r"convention_index doit être dans \[0, 4\]"
    ):
        Clock(kind, index)


# ---------------------------------------------------------------------------
# ClockPartition
# ---------------------------------------------------------------------------

PARTITION = ClockPartition(
    time_s=(0.0, 1.0, 2.0),
    states=((M, S), (M, S), (M, M), (U, S), (M, U)),
)


@given(clock_partitions())
def test_valid_partitions_build(partition: ClockPartition) -> None:
    assert all(len(states) == len(partition.time_s) - 1 for states in partition.states)


def test_partition_mutable_time_is_refused() -> None:
    time_s: Any = [0.0, 1.0, 2.0]
    with pytest.raises(ContractError, match=r"time_s.*tuple"):
        replace(PARTITION, time_s=time_s)


def test_partition_needs_two_instants() -> None:
    with pytest.raises(ContractError, match="au moins 2"):
        ClockPartition(time_s=(0.0,), states=((),) * 5)


@given(non_finite_floats())
def test_partition_non_finite_time_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match=r"time_s\[1\] doit être fini"):
        replace(PARTITION, time_s=(0.0, value, 2.0))


def test_partition_origin_is_zero() -> None:
    """L'origine de ``0010`` D5.3 est le premier enregistrement."""
    with pytest.raises(ContractError, match=r"time_s\[0\] doit valoir 0"):
        replace(PARTITION, time_s=(1.0, 2.0, 3.0))


def test_partition_time_is_strictly_increasing() -> None:
    with pytest.raises(ContractError, match="strictement croissante"):
        replace(PARTITION, time_s=(0.0, 1.0, 1.0))


def test_partition_mutable_states_are_refused() -> None:
    states: Any = list(PARTITION.states)
    with pytest.raises(ContractError, match=r"states.*tuple"):
        replace(PARTITION, states=states)
    inner: Any = (list(PARTITION.states[0]), *PARTITION.states[1:])
    with pytest.raises(ContractError, match=r"states\[0\].*tuple"):
        replace(PARTITION, states=inner)


@pytest.mark.parametrize("count", [4, 6])
def test_partition_has_five_conventions(count: int) -> None:
    with pytest.raises(ContractError, match="5 conventions"):
        replace(PARTITION, states=((M, M),) * count)


def test_partition_has_one_state_per_interval() -> None:
    states = ((M, S), (M, S), (M,), (U, S), (M, U))
    with pytest.raises(ContractError, match=r"states\[2\] doit porter 2 états"):
        replace(PARTITION, states=states)


# ---------------------------------------------------------------------------
# ClockTotals
# ---------------------------------------------------------------------------

TOTALS = ClockTotals(
    elapsed_s=180.0, moving_s=0.0, stopped_s=146.0, undetermined_s=34.0
)
TOTAL_NAMES = ("elapsed_s", "moving_s", "stopped_s", "undetermined_s")


@pytest.mark.parametrize("name", TOTAL_NAMES)
@given(value=non_finite_floats())
def test_totals_non_finite_is_refused(name: str, value: float) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=rf"{name} doit être fini"):
        replace(TOTALS, **changes)


def test_totals_negative_is_refused() -> None:
    """Un total négatif qui garde l'identité vraie : seul ``>= 0`` est violé."""
    with pytest.raises(ContractError, match="moving_s doit être >= 0"):
        replace(TOTALS, moving_s=-1.0, stopped_s=147.0)
    with pytest.raises(ContractError, match="elapsed_s doit être >= 0"):
        ClockTotals(elapsed_s=-1.0, moving_s=0.0, stopped_s=0.0, undetermined_s=0.0)


def test_totals_identity_m_plus_s_plus_u_is_e() -> None:
    """``0010`` D5.2 : ``M + S + U = E``."""
    with pytest.raises(ContractError, match="doit valoir elapsed_s"):
        replace(TOTALS, undetermined_s=35.0)


@pytest.mark.parametrize(
    ("elapsed_s", "gap_s", "accepted"),
    [
        (1e5, 5e-5, True),
        (1e5, 2e-4, False),
        (0.5, 5e-10, True),
        (0.5, 2e-9, False),
    ],
)
def test_totals_identity_tolerance_is_relative_to_max_1_e(
    elapsed_s: float, gap_s: float, accepted: bool
) -> None:
    def build() -> ClockTotals:
        return ClockTotals(
            elapsed_s=elapsed_s,
            moving_s=elapsed_s + gap_s,
            stopped_s=0.0,
            undetermined_s=0.0,
        )

    if accepted:
        assert build().moving_s == elapsed_s + gap_s
    else:
        with pytest.raises(ContractError, match="doit valoir elapsed_s"):
            build()


# ---------------------------------------------------------------------------
# StopEpisode
# ---------------------------------------------------------------------------

EPISODE = StopEpisode(start_s=17.0, end_s=163.0, first_record=17, last_record=163)


@pytest.mark.parametrize("name", ["start_s", "end_s"])
@given(value=non_finite_floats())
def test_episode_non_finite_is_refused(name: str, value: float) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=rf"{name} doit être fini"):
        replace(EPISODE, **changes)


def test_episode_starts_at_or_after_zero() -> None:
    with pytest.raises(ContractError, match="start_s doit être >= 0"):
        replace(EPISODE, start_s=-1.0)


@pytest.mark.parametrize("end_s", [17.0, 10.0])
def test_episode_start_precedes_end(end_s: float) -> None:
    with pytest.raises(ContractError, match=r"start_s .* doit précéder end_s"):
        replace(EPISODE, end_s=end_s)


def test_episode_first_record_is_not_negative() -> None:
    with pytest.raises(ContractError, match="first_record doit être >= 0"):
        replace(EPISODE, first_record=-1)


@pytest.mark.parametrize("last_record", [17, 3])
def test_episode_first_record_precedes_last(last_record: int) -> None:
    with pytest.raises(ContractError, match=r"first_record .* doit précéder"):
        replace(EPISODE, last_record=last_record)
