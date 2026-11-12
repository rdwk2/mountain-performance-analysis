"""La décision de la règle sur des instants et la borne basse, écrites une fois (OG-2,
``estimation/decision.py`` ; § 6.1 du brief OG-2).

Cas calculés à la main : ``o`` = 2026-03-30 00:00 à Paris (= 2026-03-29 22:00 UTC,
l'heure d'été a commencé le 29), ``W`` = 28. Les instants sont à fuseau : les tests ne
dépendent pas du fuseau local (ils se rejouent sous ``TZ=UTC`` et
``TZ=America/New_York``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mountain_perf.estimation import decision, origin
from mountain_perf.estimation.decision import (
    ALL_PAST,
    PARIS,
    TemporalDecision,
    decide_on_index,
    decide_on_safe_end,
    window_lower_bound,
)

ORIGIN = datetime(2026, 3, 30, tzinfo=PARIS)
BOUND = datetime(2026, 3, 1, 23, tzinfo=UTC)
MICRO = timedelta(microseconds=1)
OLD = datetime(2000, 1, 1, tzinfo=UTC)


def test_lower_bound_crosses_the_clock_change() -> None:
    """La fenêtre de 28 jours dure 27 jours et 23 heures, pas 28 × 24 h."""
    assert ORIGIN.astimezone(UTC) == datetime(2026, 3, 29, 22, tzinfo=UTC)
    bound = window_lower_bound(ORIGIN, 28)
    assert bound == BOUND
    assert bound is not None
    assert bound.tzinfo is UTC
    assert ORIGIN - bound == timedelta(days=27, hours=23)
    assert window_lower_bound(ORIGIN, ALL_PAST) is None


def test_decide_on_index_by_hand() -> None:
    o = ORIGIN.astimezone(UTC)
    assert decide_on_index(o, o, BOUND) is TemporalDecision.AFTER_ORIGIN
    assert decide_on_index(o + MICRO, o, BOUND) is TemporalDecision.AFTER_ORIGIN
    assert decide_on_index(o - MICRO, o, BOUND) is None
    assert decide_on_index(BOUND, o, BOUND) is None
    assert decide_on_index(BOUND - MICRO, o, BOUND) is TemporalDecision.BEFORE_WINDOW
    assert decide_on_index(None, o, BOUND) is None
    assert decide_on_index(OLD, o, None) is None
    assert decide_on_index(o, o, None) is TemporalDecision.AFTER_ORIGIN


def test_decide_on_safe_end_by_hand() -> None:
    o = ORIGIN.astimezone(UTC)
    assert decide_on_safe_end(None, o, BOUND) is TemporalDecision.UNKNOWN_END
    assert decide_on_safe_end(o, o, BOUND) is TemporalDecision.AFTER_ORIGIN
    assert decide_on_safe_end(o - MICRO, o, BOUND) is TemporalDecision.CANDIDATE
    assert decide_on_safe_end(BOUND, o, BOUND) is TemporalDecision.CANDIDATE
    assert decide_on_safe_end(BOUND - MICRO, o, BOUND) is TemporalDecision.BEFORE_WINDOW
    assert decide_on_safe_end(OLD, o, None) is TemporalDecision.CANDIDATE
    assert decide_on_safe_end(None, o, None) is TemporalDecision.UNKNOWN_END


def test_the_decisions_compare_instants_not_wall_clocks() -> None:
    """Le même instant, sous deux fuseaux, reçoit la même décision."""
    o = ORIGIN.astimezone(UTC)
    just_before = (o - MICRO).astimezone(PARIS)
    assert decide_on_safe_end(just_before, o, BOUND) is TemporalDecision.CANDIDATE
    assert (
        decide_on_index(o.astimezone(PARIS), o, BOUND) is TemporalDecision.AFTER_ORIGIN
    )


@pytest.mark.parametrize(
    "name",
    [
        "PARIS",
        "ALL_PAST",
        "OriginWindow",
        "check_origin",
        "check_window",
        "window_lower_bound",
        "TemporalDecision",
    ],
)
def test_the_rule_reexports_what_moved(name: str) -> None:
    """Aucun importeur ne change : ``origin`` réexporte les noms déplacés, les mêmes
    objets."""
    assert getattr(origin, name) is getattr(decision, name)
