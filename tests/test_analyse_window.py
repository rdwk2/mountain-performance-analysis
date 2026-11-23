"""La Fenêtre (AN4-1, § 5 et § 8 du brief) : ses bornes, l'étendue des données, le
filtre. Valeurs inventées ; l'étendue du monde des tests de la page « récupération »
(``fixtures.recovery_world``) : du 2000-01-03 au 2000-05-21."""

from __future__ import annotations

import ast
import dataclasses
import sys
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from fixtures.recovery_world import base_tables, day_of, world_rows
from mountain_perf.analyse import window as window_module
from mountain_perf.analyse.tables import Tables
from mountain_perf.analyse.window import (
    DEFAULT_CHOICE,
    DEFAULT_DAYS,
    Window,
    WindowChoice,
    chosen_window,
    data_span,
    date_range,
    last_days,
    within,
)
from mountain_perf.schemas.processed import ClimbRow
from test_backtest_metrics_reuse import _imported_modules

SPAN = Window(date(2000, 1, 3), date(2000, 5, 21))
PLUS_2 = timezone(timedelta(hours=2))
MINUS_5 = timezone(timedelta(hours=-5))
D = date


@dataclasses.dataclass(frozen=True)
class Refused:
    """Un cas qui lève ``ValueError``, son message lu par ``match``."""

    match: str


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> Tables:
    return base_tables(tmp_path_factory.mktemp("base"))


def _climb(base: Tables, start: datetime) -> ClimbRow:
    assert base.climbs
    return dataclasses.replace(base.climbs[0], local_start_time=start)


# W1 : le tableau du § 5, ligne à ligne.

CASES = [
    (
        "last_days 28",
        lambda: last_days(SPAN, 28),
        Window(D(2000, 4, 24), SPAN.last),
        28,
    ),
    ("last_days 56", lambda: last_days(SPAN, 56), Window(day_of(84), SPAN.last), 56),
    ("last_days 90", lambda: last_days(SPAN, 90), Window(day_of(50), SPAN.last), 90),
    (
        "last_days court",
        lambda: last_days(Window(D(2000, 5, 1), D(2000, 5, 21)), 28),
        Window(D(2000, 5, 1), D(2000, 5, 21)),
        21,
    ),
    ("last_days 1", lambda: last_days(SPAN, 1), Window(SPAN.last, SPAN.last), 1),
    ("last_days 0", lambda: last_days(SPAN, 0), Refused("au moins un jour"), None),
    ("tout", lambda: chosen_window(SPAN, WindowChoice.ALL), SPAN, 140),
    (
        "plage",
        lambda: date_range(SPAN, D(2000, 5, 10), D(2000, 5, 12)),
        Window(D(2000, 5, 10), D(2000, 5, 12)),
        3,
    ),
    (
        "plage avant",
        lambda: date_range(SPAN, D(1999, 12, 1), D(2000, 1, 10)),
        Window(D(2000, 1, 3), D(2000, 1, 10)),
        8,
    ),
    (
        "plage d'un jour",
        lambda: date_range(SPAN, D(2000, 5, 21), D(2000, 5, 21)),
        Window(D(2000, 5, 21), D(2000, 5, 21)),
        1,
    ),
    (
        "plage inversée",
        lambda: date_range(SPAN, D(2000, 5, 12), D(2000, 5, 10)),
        None,
        None,
    ),
    (
        "plage hors",
        lambda: date_range(SPAN, D(2000, 6, 1), D(2000, 6, 30)),
        None,
        None,
    ),
    (
        "plage sans premier jour",
        lambda: chosen_window(SPAN, WindowChoice.RANGE, None, D(2000, 5, 10)),
        Refused("deux jours"),
        None,
    ),
    (
        "fenêtre inversée",
        lambda: Window(D(2000, 5, 2), D(2000, 5, 1)),
        Refused("vient après"),
        None,
    ),
]


@pytest.mark.parametrize(
    ("call", "expected", "days"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_w1_the_cases_by_hand(call: object, expected: object, days: int | None) -> None:
    assert callable(call)
    if isinstance(expected, Refused):
        with pytest.raises(ValueError, match=expected.match):
            call()
        return
    result = call()
    assert result == expected
    if days is not None:
        assert isinstance(result, Window)
        assert result.days == days


def test_w1_the_span_has_140_days() -> None:
    assert SPAN.days == 140
    assert Window(day_of(0), day_of(139)) == SPAN


# W7 : l'appartenance.


def test_w7_contains() -> None:
    window = Window(D(2000, 5, 10), D(2000, 5, 12))
    assert D(2000, 5, 10) in window
    assert D(2000, 5, 12) in window
    assert D(2000, 5, 11) in window
    assert D(2000, 5, 9) not in window
    assert D(2000, 5, 13) not in window
    assert "2000-05-11" not in window
    assert None not in window
    with pytest.raises(TypeError) as raised:
        _ = datetime(2000, 5, 10, 12, 0) in window
    assert str(raised.value) == "Un jour (date) est attendu, pas un instant (datetime)."
    with pytest.raises(TypeError, match="pas un instant"):
        within([1], window, lambda _: datetime(2000, 5, 10, 12, 0))


# W8 : l'étendue des données.


def test_w8_the_days_alone() -> None:
    assert data_span(world_rows(), ()) == SPAN


def test_w8_a_climb_after_the_days_counts_on_its_local_day(base: Tables) -> None:
    climb = _climb(base, datetime(2000, 6, 2, 1, 30, tzinfo=PLUS_2))
    assert climb.local_start_time.astimezone(UTC).date() == D(2000, 6, 1)
    assert data_span(world_rows(), (climb,)) == Window(D(2000, 1, 3), D(2000, 6, 2))


def test_w8_climbs_alone(base: Tables) -> None:
    climbs = (
        _climb(base, datetime(2000, 3, 5, 10, 0, tzinfo=PLUS_2)),
        _climb(base, datetime(1999, 12, 31, 23, 30, tzinfo=MINUS_5)),
    )
    assert climbs[1].local_start_time.astimezone(UTC).date() == D(2000, 1, 1)
    assert data_span((), climbs) == Window(D(1999, 12, 31), D(2000, 3, 5))


def test_w8_nothing() -> None:
    assert data_span((), ()) is None


# W9 : le choix.


def test_w9_each_choice() -> None:
    assert chosen_window(SPAN, WindowChoice.DAYS_28) == Window(
        D(2000, 4, 24), SPAN.last
    )
    assert chosen_window(SPAN, WindowChoice.DAYS_56) == Window(day_of(84), SPAN.last)
    assert chosen_window(SPAN, WindowChoice.DAYS_90) == Window(day_of(50), SPAN.last)
    assert chosen_window(SPAN, WindowChoice.ALL) == SPAN
    assert chosen_window(
        SPAN, WindowChoice.RANGE, D(2000, 5, 10), D(2000, 5, 12)
    ) == Window(D(2000, 5, 10), D(2000, 5, 12))


def test_w9_a_range_without_its_dates_is_refused() -> None:
    for first, last in ((None, None), (D(2000, 5, 10), None), (None, D(2000, 5, 10))):
        with pytest.raises(ValueError, match="deux jours"):
            chosen_window(SPAN, WindowChoice.RANGE, first, last)


def test_w9_the_other_choices_ignore_the_dates() -> None:
    assert chosen_window(
        SPAN, WindowChoice.DAYS_28, D(2000, 5, 10), D(2000, 5, 12)
    ) == Window(D(2000, 4, 24), SPAN.last)
    assert chosen_window(SPAN, WindowChoice.ALL, D(2000, 5, 12), D(2000, 5, 10)) == SPAN


# W10 : le filtre.


def test_w10_within_keeps_the_order_and_the_bounds() -> None:
    window = Window(D(2000, 5, 10), D(2000, 5, 12))
    days = [
        D(2000, 5, 13),
        D(2000, 5, 12),
        D(2000, 5, 9),
        D(2000, 5, 10),
        D(2000, 5, 11),
    ]
    assert within(days, window, lambda day: day) == (
        D(2000, 5, 12),
        D(2000, 5, 10),
        D(2000, 5, 11),
    )
    rows = world_rows()
    kept = within(rows, last_days(SPAN, DEFAULT_DAYS), lambda row: row.day)
    assert kept == rows[-56:]


# W11 : les choix et les valeurs par défaut.


def test_w11_the_choices() -> None:
    assert [choice.value for choice in WindowChoice] == [
        "28",
        "56",
        "90",
        "tout",
        "plage",
    ]
    assert DEFAULT_CHOICE is WindowChoice.DAYS_56
    assert DEFAULT_DAYS == 56


# W12 : le message d'une fenêtre inversée.


def test_w12_the_message_names_both_dates() -> None:
    with pytest.raises(ValueError, match="vient après") as raised:
        Window(D(2000, 5, 2), D(2000, 5, 1))
    message = str(raised.value)
    assert "2000-05-02" in message
    assert "2000-05-01" in message


# W13 : les imports.


def test_w13_only_the_standard_library_and_the_schemas() -> None:
    path = Path(window_module.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    modules = _imported_modules(tree, "mountain_perf.analyse")
    assert modules
    for module in modules:
        assert module.split(".")[0] in stdlib or module.startswith(
            "mountain_perf.schemas"
        ), module


# W14 : last_days reste dans l'étendue.


@pytest.mark.parametrize(
    "span", [SPAN, Window(D(2000, 5, 1), D(2000, 5, 21)), Window(SPAN.last, SPAN.last)]
)
def test_w14_last_days_stays_in_the_span(span: Window) -> None:
    for n in range(1, 201):
        window = last_days(span, n)
        assert span.first <= window.first <= window.last == span.last
        assert window.days == min(n, span.days)
