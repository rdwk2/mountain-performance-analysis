"""Les ruptures, les jours incertains et la normale à cheval, cas par cas (AN2-2). Les
jours des cas sont numérotés depuis 1 ; 45 jours par défaut, une valeur admise de 50."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import astuple, replace
from typing import Any, cast

import pytest

from mountain_perf.analyse.normals import (
    MEASURE_SPECS,
    NORMAL_PARAMETER_SPECS,
    MeasureNormal,
    NormalMeasure,
    measure_normals,
    rank_ruptures,
    straddles,
    uncertain_days,
    version_ruptures,
)
from mountain_perf.schemas import ParameterSet

DEFAULT = ParameterSet(NORMAL_PARAMETER_SPECS)
SIX = list(NormalMeasure)
Ranks = list[tuple[int, ...]]


def params(**values: float) -> ParameterSet:
    return ParameterSet(NORMAL_PARAMETER_SPECS, values)


@pytest.mark.parametrize(
    "change",
    [{"maximum": 366.0}, {"minimum": 2.0}, {"default": 27.0}],
    ids=["borne haute", "borne basse", "défaut"],
)
def test_straddles_refuses_another_set_with_the_same_names(
    change: dict[str, Any],
) -> None:
    other = ParameterSet(
        (replace(NORMAL_PARAMETER_SPECS[0], **change), *NORMAL_PARAMETER_SPECS[1:])
    )
    with pytest.raises(ValueError, match=r"^parameters ") as caught:
        straddles([False], [False], other)
    assert str(caught.value) == (
        "parameters doit être un ParameterSet de NORMAL_PARAMETER_SPECS, reçu "
        f"{other!r}."
    )


def days(flags: Sequence[bool]) -> list[int]:
    """Les numéros, depuis 1, des jours où ``flags`` est vrai."""
    return [i + 1 for i, flag in enumerate(flags) if flag]


def from_rule(n: int, rule: Callable[[int], tuple[int, ...]]) -> Ranks:
    return [rule(day) for day in range(1, n + 1)]


REFERENCE = from_rule(45, lambda d: (1,) if d <= 3 else (1, 2) if d <= 5 else (2,))


def normals_of(
    measure: NormalMeasure,
    ranks: Sequence[tuple[int, ...]],
    versions: Sequence[int | None] | None = None,
) -> tuple[MeasureNormal, ...]:
    n = len(ranks)
    if versions is None and MEASURE_SPECS[measure].version is not None:
        versions = [1] * n
    return measure_normals(measure, [50.0] * n, [True] * n, ranks, versions, DEFAULT)


def test_the_reference_ranks() -> None:
    breaks = rank_ruptures(REFERENCE)
    uncertain = uncertain_days(REFERENCE)
    assert days(breaks) == [4]
    assert days(uncertain) == [4, 5]
    assert days(straddles(breaks, uncertain, DEFAULT)) == list(range(5, 34))


@pytest.mark.parametrize("measure", SIX)
def test_the_reference_ranks_for_each_measure(measure: NormalMeasure) -> None:
    normals = normals_of(measure, REFERENCE)
    assert days([n.rupture for n in normals]) == [4]
    assert days([n.straddles for n in normals]) == list(range(5, 34))


def test_the_rupture_and_the_uncertain_days_separately() -> None:
    breaks = [day == 4 for day in range(1, 46)]
    none = [False] * 45
    assert days(straddles(breaks, none, DEFAULT)) == list(range(5, 32))
    uncertain = [day in (4, 5) for day in range(1, 46)]
    assert days(straddles(none, uncertain, DEFAULT)) == list(range(5, 34))


@pytest.mark.parametrize(
    "measure",
    [
        NormalMeasure.MEASURED_SLEEP,
        NormalMeasure.NIGHT_STRESS,
        NormalMeasure.NIGHT_RESPIRATION,
    ],
)
def test_a_version_that_changes_breaks_its_family(measure: NormalMeasure) -> None:
    versions: list[int | None] = [1 if day <= 9 else 2 for day in range(1, 46)]
    ranks: Ranks = [(1,)] * 45
    assert days(version_ruptures(versions)) == [10]
    normals = normals_of(measure, ranks, versions)
    assert days([n.rupture for n in normals]) == [10]
    assert days([n.straddles for n in normals]) == list(range(11, 38))
    assert days(uncertain_days(ranks)) == []


@pytest.mark.parametrize(
    "measure",
    [NormalMeasure.HRV, NormalMeasure.RESTING_HR, NormalMeasure.NIGHT_SPO2],
)
def test_no_version_breaks_the_other_measures(measure: NormalMeasure) -> None:
    normals = normals_of(measure, [(1,)] * 45)
    assert not any(n.rupture for n in normals)
    assert not any(n.straddles for n in normals)


def test_a_rank_rupture_and_a_version_rupture() -> None:
    ranks = from_rule(60, lambda d: (1,) if d <= 4 else (2,))
    versions: list[int | None] = [3 if d <= 19 else 4 for d in range(1, 61)]
    sleep = normals_of(NormalMeasure.MEASURED_SLEEP, ranks, versions)
    assert days([n.rupture for n in sleep]) == [5, 20]
    assert days([n.straddles for n in sleep]) == list(range(6, 48))
    hrv = normals_of(NormalMeasure.HRV, ranks)
    assert days([n.rupture for n in hrv]) == [5]
    assert days([n.straddles for n in hrv]) == list(range(6, 33))
    assert days(uncertain_days(ranks)) == []


def test_no_rupture_at_the_first_ranks_nor_at_the_first_version() -> None:
    assert not any(rank_ruptures([(2,), (2,)]))
    assert not any(rank_ruptures([(), (), (3,), (3,)]))
    assert not any(version_ruptures([7, 7]))
    assert not any(version_ruptures([None, None, 7]))
    assert rank_ruptures([]) == ()
    assert version_ruptures([]) == ()
    assert uncertain_days([]) == ()
    ranks: Ranks = [(2,)] * 45
    assert not any(n.straddles for n in normals_of(NormalMeasure.HRV, ranks))


def test_the_return_to_an_old_watch_is_a_rupture() -> None:
    ranks = from_rule(9, lambda d: (1,) if d <= 3 else (2,) if d <= 6 else (1,))
    assert days(rank_ruptures(ranks)) == [4, 7]
    assert rank_ruptures([(1,), (2,), (1,)]) == (False, True, True)


def test_two_watches_the_same_day() -> None:
    ranks: Ranks = [(1, 2), (1,), (1, 2), (2,), (1, 2, 3)]
    assert days(rank_ruptures(ranks)) == [3, 5]
    assert days(uncertain_days(ranks)) == [1, 3, 5]


def test_a_rank_that_disappears_breaks_nothing_a_new_one_does() -> None:
    assert days(rank_ruptures([(1, 2), (1,)])) == []
    assert days(rank_ruptures([(1,), (1, 3)])) == [2]


def test_days_without_rank_before_a_rupture_are_uncertain() -> None:
    ranks: Ranks = from_rule(45, lambda d: (1,) if d <= 2 else () if d <= 4 else (2,))
    breaks = rank_ruptures(ranks)
    uncertain = uncertain_days(ranks)
    assert days(breaks) == [5]
    assert days(uncertain) == [3, 4]
    assert days(straddles(breaks, uncertain, DEFAULT)) == list(range(4, 33))


@pytest.mark.parametrize(
    ("ranks", "breaks", "uncertain"),
    [
        ([(1,), (), (), (1,)], [], []),
        ([(1,), (1,), (), ()], [], []),
        ([(), (), (1,), (2,)], [4], []),
        ([(1,), (), (1,), (), (), (2,)], [6], [4, 5]),
    ],
)
def test_the_other_days_without_rank(
    ranks: Ranks, breaks: list[int], uncertain: list[int]
) -> None:
    assert days(rank_ruptures(ranks)) == breaks
    assert days(uncertain_days(ranks)) == uncertain


def test_an_old_watch_a_gap_then_a_new_watch() -> None:
    ranks = from_rule(45, lambda d: (1,) if d <= 3 else () if d <= 5 else (2,))
    breaks = rank_ruptures(ranks)
    uncertain = uncertain_days(ranks)
    assert days(breaks) == [6]
    assert days(uncertain) == [4, 5]
    assert days(straddles(breaks, uncertain, DEFAULT)) == list(range(5, 34))


@pytest.mark.parametrize(
    ("versions", "expected"),
    [
        ([1, None, None, 1], []),
        ([1, None, 2, None, 2], [3]),
        ([0, 1, 0], [2, 3]),
    ],
)
def test_a_version_compares_to_the_last_day_that_has_one(
    versions: list[int | None], expected: list[int]
) -> None:
    assert days(version_ruptures(versions)) == expected


def _at(day: int, n: int = 45) -> list[bool]:
    return [d == day for d in range(1, n + 1)]


def test_the_bounds_of_straddling() -> None:
    none = [False] * 45
    assert days(straddles(_at(10), none, DEFAULT)) == list(range(11, 38))
    assert days(straddles(none, _at(10), DEFAULT)) == list(range(11, 39))
    three = params(window_days=3)
    assert days(straddles(_at(10), none, three)) == [11, 12]
    assert days(straddles(none, _at(10), three)) == [11, 12, 13]
    one = params(window_days=1, min_admitted_days=1)
    assert days(straddles(_at(10), none, one)) == []
    assert days(straddles(none, _at(10), one)) == [11]


def test_straddles_checks_its_entries() -> None:
    with pytest.raises(ValueError, match="ruptures=2, uncertain=1"):
        straddles([False, False], [False], DEFAULT)
    with pytest.raises(ValueError, match=r"uncertain\[0\]"):
        straddles([False], cast(Any, [1]), DEFAULT)
    with pytest.raises(ValueError, match="parameters"):
        straddles([False], [False], ParameterSet(()))
    with pytest.raises(ValueError, match="window_days"):
        straddles([False], [False], params(window_days=2.5))


def test_a_rupture_excludes_nothing_and_does_not_cut_the_segments() -> None:
    n = 45
    values = [25000.0 + 60.0 * ((5 * d) % 11) for d in range(n)]
    admitted = [d % 4 != 0 for d in range(n)]
    versions: list[int | None] = [1 if day <= 9 else 2 for day in range(1, n + 1)]
    broken = measure_normals(
        NormalMeasure.MEASURED_SLEEP, values, admitted, REFERENCE, versions, DEFAULT
    )
    plain = measure_normals(
        NormalMeasure.MEASURED_SLEEP, values, admitted, [()] * n, [1] * n, DEFAULT
    )
    assert any(normal.rupture for normal in broken)
    for a, b in zip(broken, plain, strict=True):
        assert astuple(a)[:9] == astuple(b)[:9]
    assert not any(normal.rupture or normal.straddles for normal in plain)
