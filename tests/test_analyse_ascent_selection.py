"""La sélection des montées du modèle de la montée
(``mountain_perf.analyse.ascent.selection``, AN4-2a) : S1 à S9 du brief. Valeurs
inventées (règle 1). Sautés sans numpy ou scipy (extra ``analyse``)."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from fixtures.ascent_world import ascent_climb, world_e_tables
from fixtures.q2_world import at, q2_activity, q2_climb, q2_day_row, q2_tables
from mountain_perf.analyse.ascent.selection import AscentMotif, select_climbs
from mountain_perf.analyse.ascent.states import AscentError
from mountain_perf.schemas.processed import (
    ClimbFlag,
    ClimbRegime,
    JournalEventType,
)

DAY = date(2001, 2, 3)


def _counts(**nonzero: int) -> dict[AscentMotif, int]:
    counts = dict.fromkeys(AscentMotif, 0)
    for name, value in nonzero.items():
        counts[AscentMotif[name]] = value
    return counts


def test_s1_each_motif_alone() -> None:
    """S1 : une montée par motif, chacune écartée par lui seul ; ``excluded`` a les
    six clés, dans l'ordre, zéros compris."""
    a = q2_activity("a", at(DAY, 9))
    b = q2_activity("b", at(DAY, 14), sessions=2)
    climbs = [
        ascent_climb("a", DAY, 0),
        ascent_climb("b", DAY, 0),
        ascent_climb("a", DAY, 1, regime=ClimbRegime.SKI_TOURING),
        q2_climb("a", at(DAY, 9), offset_s=7200.0, flags=(ClimbFlag.SPIKE,)),
        q2_climb("a", at(DAY, 9), offset_s=10800.0, vertical_speed_ms=None),
        q2_climb("a", at(DAY, 9), offset_s=14400.0, moving_mean_elevation_m=None),
        q2_climb("a", at(DAY, 9), offset_s=18000.0, h=None),
    ]
    selection = select_climbs(q2_tables([a, b], climbs))
    assert len(selection.climbs) == 1
    assert list(selection.excluded) == list(AscentMotif)
    assert dict(selection.excluded) == dict.fromkeys(AscentMotif, 1)
    alone = select_climbs(q2_tables([a], [ascent_climb("a", DAY, 0)]))
    assert dict(alone.excluded) == _counts()
    assert list(alone.excluded) == list(AscentMotif)


def test_s1_a_speed_at_zero_is_absent() -> None:
    """S1 : une VAM nulle compte pour ``vitesse_absente``."""
    a = q2_activity("a", at(DAY, 9))
    climb = q2_climb("a", at(DAY, 9), vertical_speed_ms=0.0)
    assert dict(select_climbs(q2_tables([a], [climb])).excluded) == _counts(NO_SPEED=1)


@pytest.mark.parametrize(
    ("sessions", "changes", "expected"),
    [
        (2, {"flags": (ClimbFlag.SPIKE,)}, "SESSIONS"),
        (1, {"regime": ClimbRegime.SHORT_CLIMB, "h": None}, "REGIME"),
        (1, {"regime": ClimbRegime.SKI_TOURING, "flags": (ClimbFlag.SPIKE,)}, "REGIME"),
        (1, {"vertical_speed_ms": None, "moving_mean_elevation_m": None}, "NO_SPEED"),
    ],
)
def test_s2_the_order_of_the_motifs(
    sessions: int, changes: dict[str, Any], expected: str
) -> None:
    """S2 : une montée à deux motifs compte pour le premier dans l'ordre."""
    a = q2_activity("a", at(DAY, 9), sessions=sessions)
    climb = q2_climb("a", at(DAY, 9), **changes)
    selection = select_climbs(q2_tables([a], [climb]))
    assert selection.climbs == ()
    assert dict(selection.excluded) == _counts(**{expected: 1})


def test_s3_slow_moving_alone_is_kept() -> None:
    """S3 : ``slow_moving`` n'écarte pas."""
    a = q2_activity("a", at(DAY, 9))
    climb = q2_climb("a", at(DAY, 9), flags=(ClimbFlag.SLOW_MOVING,))
    selection = select_climbs(q2_tables([a], [climb]))
    assert len(selection.climbs) == 1
    assert dict(selection.excluded) == _counts()


def test_s4_the_coverage_bound() -> None:
    """S4 : la couverture à 0,8 garde la montée ; à 0,79, ``fc_indefinie``."""
    a = q2_activity("a", at(DAY, 9))
    kept = q2_climb("a", at(DAY, 9), coverage=0.8)
    lost = q2_climb("a", at(DAY, 9), offset_s=3600.0, coverage=0.79)
    selection = select_climbs(q2_tables([a], [kept, lost]))
    assert [c.start for c in selection.climbs] == [kept.local_start_time]
    assert dict(selection.excluded) == _counts(NO_HEART_RATE=1)


def test_s5_the_quantities_of_a_kept_climb() -> None:
    """S5 : les grandeurs d'une montée gardée ; le journal du jour, ``()`` sans
    ligne."""
    a = q2_activity("a", at(DAY, 9))
    other = date(2001, 2, 4)
    b = q2_activity("b", at(other, 9))
    climbs = [
        ascent_climb(
            "a",
            DAY,
            0,
            regime=ClimbRegime.INTERMEDIATE,
            vertical_speed_ms=0.2,
            hr_bpm=151.0,
            preceding_ascent_m=400.0,
            profile_ascent_m=300.0,
            altitude_m=1840.0,
            product=7,
        ),
        ascent_climb("b", other, 0),
    ]
    days = [q2_day_row(DAY, journal=(JournalEventType.ILLNESS,))]
    first, second = select_climbs(q2_tables([a, b], climbs, days)).climbs
    assert first.activity_ref == "a"
    assert first.day == DAY
    assert first.start == climbs[0].local_start_time
    assert first.regime is ClimbRegime.INTERMEDIATE
    assert first.log_speed == pytest.approx(math.log(0.2), rel=1e-15)
    assert first.hr_bpm == 151.0
    assert first.d_plus_km == pytest.approx(0.55, rel=1e-15)
    assert first.altitude_km == pytest.approx(1.84, rel=1e-15)
    assert first.intermediate is True
    assert first.device == ("garmin", 7)
    assert first.journal == (JournalEventType.ILLNESS,)
    assert first.temperature_c == 15.0
    assert second.intermediate is False
    assert second.journal == ()


def test_s6_two_devices_are_marked_not_filtered() -> None:
    """S6 : deux appareils, les deux montées gardées, chacune son ``device``."""
    a = q2_activity("a", at(DAY, 9), product=1)
    b = q2_activity("b", at(DAY, 15), product=2)
    climbs = [
        ascent_climb("a", DAY, 0, product=1),
        ascent_climb("b", DAY, 0, product=2, hour=15),
    ]
    selection = select_climbs(q2_tables([a, b], climbs))
    assert [c.device for c in selection.climbs] == [("garmin", 1), ("garmin", 2)]


def test_s6_a_climb_without_device_is_marked_none() -> None:
    """S6 : une montée sans numéro de produit garde ``device = None``."""
    a = q2_activity("a", at(DAY, 9))
    selection = select_climbs(q2_tables([a], [ascent_climb("a", DAY, 0, product=None)]))
    assert selection.climbs[0].device is None


def test_s7_a_climb_without_activity() -> None:
    """S7 : une montée sans activité lève ``AscentError``, qui nomme la référence."""
    a = q2_activity("a", at(DAY, 9))
    with pytest.raises(AscentError, match="orpheline"):
        select_climbs(q2_tables([a], [ascent_climb("orpheline", DAY, 0)]))


def test_s8_the_sort_and_the_day_after_midnight() -> None:
    """S8 : le tri ``(day, start, activity_ref)`` ; une montée partie après minuit
    reste au jour de son activité."""
    late = q2_activity("late", at(DAY, 22))
    b = q2_activity("b", at(date(2001, 2, 4), 9))
    a = q2_activity("a", at(date(2001, 2, 4), 9))
    climbs = [
        q2_climb("b", at(date(2001, 2, 4), 9)),
        q2_climb("late", at(DAY, 22), offset_s=3 * 3600.0),
        q2_climb("a", at(date(2001, 2, 4), 9)),
        q2_climb("late", at(DAY, 22)),
    ]
    selection = select_climbs(q2_tables([late, b, a], climbs))
    assert [(c.activity_ref, c.day) for c in selection.climbs] == [
        ("late", DAY),
        ("late", DAY),
        ("a", date(2001, 2, 4)),
        ("b", date(2001, 2, 4)),
    ]
    assert selection.climbs[1].start.date() == date(2001, 2, 4)


def test_s9_world_e() -> None:
    """S9 : le monde E, 32 montées gardées, dans l'ordre du fichier, aucun motif."""
    tables = world_e_tables()
    selection = select_climbs(tables)
    assert len(selection.climbs) == 32
    assert dict(selection.excluded) == _counts()
    assert [c.start for c in selection.climbs] == [
        c.local_start_time for c in tables.climbs
    ]
