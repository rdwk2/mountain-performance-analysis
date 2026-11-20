"""Les groupes de parcours de Q2 (AN3-3b, ``docs/decisions/0023``, Q-50 (a)) : le cas
C6 du brief, la symétrie et l'égalité de gain. Sur des tables inventées."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from fixtures.q2_world import at, q2_activity, q2_climb, q2_tables
from mountain_perf.analyse.q2.data import Q2Day, q2_data
from mountain_perf.analyse.q2.parameters import Q2_PARAMETER_SPECS
from mountain_perf.analyse.q2.routes import route_groups
from mountain_perf.schemas import ParameterSet
from mountain_perf.schemas.processed import ClimbRegime, ClimbRow

DEFAULTS = ParameterSet(Q2_PARAMETER_SPECS)
FIRST = date(2025, 7, 1)

C6 = {
    # nom : (départ, arrivée, gain, journée, temps en mouvement)
    "A": (45.0000, 45.0300, 300.0, 1, 900.0),
    "B": (45.0007, 45.0305, 320.0, 2, 900.0),
    "C": (45.0015, 45.0312, 345.0, 3, 900.0),
    "D": (45.1000, 45.1300, 300.0, 4, 900.0),
    "E": (45.0001, 45.0299, 340.0, 5, 600.0),
    "F": (45.2000, 45.2300, 100.0, 5, 1200.0),
}


def _days(names: list[str]) -> tuple[Q2Day, ...]:
    activities, climbs = [], []
    seen: set[int] = set()
    for k, name in enumerate(names):
        start, end, gain, day_number, moving = C6[name]
        when = at(FIRST + timedelta(days=day_number), 9)
        ref = f"j{day_number}"
        if day_number not in seen:
            seen.add(day_number)
            activities.append(q2_activity(ref, when))
        climbs.append(_climb(ref, when, k, start, end, gain, moving))
    data = q2_data(q2_tables(activities, climbs), None, DEFAULTS)
    return data.days[ClimbRegime.LONG_CLIMB]


def _climb(
    ref: str,
    when: object,
    k: int,
    start: float,
    end: float,
    gain: float,
    moving: float,
) -> ClimbRow:
    return q2_climb(
        ref,
        when,  # type: ignore[arg-type]
        offset_s=2000.0 * k,
        gain_m=gain,
        moving_s=moving,
        start_latitude_deg=start,
        start_longitude_deg=6.0,
        end_latitude_deg=end,
        end_longitude_deg=6.0,
    )


ALL = ["A", "B", "C", "D", "E", "F"]


@pytest.mark.parametrize(
    ("max_other", "expected"),
    [(1, (0, 0, 0, None, 0)), (2, (0, 0, 0, None, 0)), (4, (None,) * 5)],
)
def test_c6_connected_components_and_the_largest_gain(
    max_other: int, expected: tuple[int | None, ...]
) -> None:
    """C6 : un groupe {A, B, C, E} (A et C, A et E y sont sans lien direct), D seul ;
    J5 suit E, sa montée de plus grand gain, pas F, la plus longue en durée."""
    days = _days(ALL)
    assert len(days) == 5
    assert route_groups(days, DEFAULTS, max_other, [True] * 5) == expected


def test_c6_without_b_nothing_is_linked() -> None:
    days = _days(["A", "C", "D", "E", "F"])
    assert route_groups(days, DEFAULTS, 1, [True] * 4) == (None,) * 4


@pytest.mark.parametrize(
    ("max_other", "expected"), [(2, (0, 0, 0, None, 0)), (3, (None,) * 5)]
)
def test_c6_components_form_on_all_days_sizes_on_the_sample(
    max_other: int, expected: tuple[int | None, ...]
) -> None:
    """Q-50 (a) : J2 hors de l'échantillon ; ses montées lient encore A, C, E ; la
    taille du groupe 0 est 3, et J2 en reçoit le groupe."""
    days = _days(ALL)
    in_sample = [True, False, True, True, True]
    assert route_groups(days, DEFAULTS, max_other, in_sample) == expected


def test_the_order_of_the_climbs_does_not_change_the_groups() -> None:
    assert route_groups(_days(ALL), DEFAULTS, 1, [True] * 5) == route_groups(
        _days(list(reversed(ALL))), DEFAULTS, 1, [True] * 5
    )


def test_groups_are_numbered_by_their_first_day() -> None:
    names = ["D", "A", "B"]
    C6["G"] = (45.1002, 45.1301, 310.0, 6, 900.0)
    try:
        days = _days([*names, "G"])
    finally:
        del C6["G"]
    assert route_groups(days, DEFAULTS, 1, [True] * 4) == (0, 0, 1, 1)


def test_at_equal_gain_the_earliest_climb_gives_the_group() -> None:
    """Deux montées de même gain dans J5 : la plus tôt donne le groupe."""
    when = at(FIRST + timedelta(days=5), 9)
    other = at(FIRST + timedelta(days=1), 9)
    activities = [q2_activity("j5", when), q2_activity("j1", other)]
    climbs = [
        _climb("j5", when, 1, 45.2000, 45.2300, 300.0, 900.0),
        _climb("j5", when, 0, 45.0001, 45.0299, 300.0, 900.0),
        _climb("j1", other, 0, 45.0000, 45.0300, 300.0, 900.0),
    ]
    days = q2_data(q2_tables(activities, climbs), None, DEFAULTS).days[
        ClimbRegime.LONG_CLIMB
    ]
    assert route_groups(days, DEFAULTS, 1, [True, True]) == (0, 0)
    late = [
        _climb("j5", when, 0, 45.2000, 45.2300, 300.0, 900.0),
        _climb("j5", when, 1, 45.0001, 45.0299, 300.0, 900.0),
        climbs[2],
    ]
    days = q2_data(q2_tables(activities, late), None, DEFAULTS).days[
        ClimbRegime.LONG_CLIMB
    ]
    assert route_groups(days, DEFAULTS, 1, [True, True]) == (None, None)
