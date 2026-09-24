"""Calendrier de Paris (§ 4.4 du brief M4a-1, ``0010`` D0, D2.5) : jour civil,
origine ``o_j``, disponibilité stricte."""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mountain_perf.backtest.calendar import (
    PARIS,
    available_at_origin,
    civil_date,
    origin,
)
from mountain_perf.schemas import ContractError
from strategies import aware_datetimes, naive_datetimes


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 7, 3), "2026-06-25T22:00Z"),
        (date(2026, 7, 17), "2026-07-09T22:00Z"),
        (date(2026, 9, 25), "2026-09-17T22:00Z"),
        (date(2026, 9, 30), "2026-09-22T22:00Z"),
        (date(2026, 10, 30), "2026-10-22T22:00Z"),
        (date(2026, 11, 2), "2026-10-25T23:00Z"),
        (date(2026, 3, 30), "2026-03-22T23:00Z"),
        (date(2026, 4, 3), "2026-03-26T23:00Z"),
    ],
    ids=str,
)
def test_origin_table(day: date, expected: str) -> None:
    """§ 7.1 : heure d'été, heure d'hiver, et les lendemains des deux changements."""
    assert origin(day) == _utc(expected)
    assert origin(day).tzinfo is UTC


@pytest.mark.parametrize(
    ("day", "instant", "available"),
    [
        (date(2026, 7, 3), "2026-06-26T10:00Z", False),  # T24
        (date(2026, 7, 17), "2026-07-04T00:25Z", True),
        (date(2026, 9, 25), "2026-09-22T00:00Z", False),  # T24 : figement postérieur
        (date(2026, 9, 30), "2026-09-24T08:00Z", False),  # X19
    ],
    ids=["T24", "fin-disponible", "T24-figement", "X19"],
)
def test_availability_checks_of_the_origin_table(
    day: date, instant: str, available: bool
) -> None:
    assert available_at_origin(_utc(instant), origin(day)) is available


def test_availability_is_strict_at_the_origin() -> None:
    """``0010`` D2.5 : **strictement** antérieur."""
    o_j = origin(date(2026, 7, 3))
    assert not available_at_origin(o_j, o_j)
    assert available_at_origin(o_j - timedelta(microseconds=1), o_j)


@given(naive_datetimes())
def test_availability_refuses_naive_instants(naive: datetime) -> None:
    o_j = origin(date(2026, 7, 3))
    with pytest.raises(ContractError, match="instant"):
        available_at_origin(naive, o_j)
    with pytest.raises(ContractError, match="origin"):
        available_at_origin(o_j, naive)


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        # « minuit » : départ d'une sortie qui finit le lendemain à 00:30 UTC.
        ("2026-07-17T20:30Z", date(2026, 7, 17)),
        ("2026-07-17T21:59:59Z", date(2026, 7, 17)),
        ("2026-07-17T22:00Z", date(2026, 7, 18)),
        ("2026-07-17T22:30Z", date(2026, 7, 18)),
        ("2026-01-15T22:59:59Z", date(2026, 1, 15)),
        ("2026-01-15T23:00Z", date(2026, 1, 16)),
    ],
    ids=str,
)
def test_civil_date_is_the_paris_calendar_day(instant: str, expected: date) -> None:
    assert civil_date(_utc(instant)) == expected


@given(naive_datetimes())
def test_civil_date_refuses_naive_instants(naive: datetime) -> None:
    with pytest.raises(ContractError, match="instant"):
        civil_date(naive)


@given(st.dates(min_value=date(1990, 1, 8), max_value=date(2099, 12, 31)))
def test_origin_is_paris_midnight_seven_days_before(day: date) -> None:
    local = origin(day).astimezone(PARIS)
    assert local.time() == time(0)
    assert local.date() == day - timedelta(days=7)
    assert civil_date(origin(day)) == day - timedelta(days=7)


@given(aware_datetimes(), aware_datetimes())
def test_civil_date_is_monotone(a: datetime, b: datetime) -> None:
    if a <= b:
        assert civil_date(a) <= civil_date(b)
    else:
        assert civil_date(a) >= civil_date(b)


@given(st.dates(min_value=date(1990, 1, 8), max_value=date(2099, 12, 31)))
def test_origins_are_increasing_and_about_a_day_apart(day: date) -> None:
    step = origin(day + timedelta(days=1)) - origin(day)
    assert timedelta(hours=23) <= step <= timedelta(hours=25)
