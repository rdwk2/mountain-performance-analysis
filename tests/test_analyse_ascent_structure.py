"""Les références et l'étage 1 du modèle de la montée
(``mountain_perf.analyse.ascent.references``, ``…structure``, AN4-2a) : R1 à R5, T1 à
T12 du brief. Les valeurs du monde E viennent de la seconde implémentation de la
conception (§ 12.2 du brief), à ses tolérances. Valeurs inventées (règle 1). Sautés
sans numpy ou scipy (extra ``analyse``)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from fixtures.ascent_world import WORLD_E_LAST_DAY, world_e_tables
from fixtures.q2_world import at
from mountain_perf.analyse.ascent.references import References, references, round_to
from mountain_perf.analyse.ascent.selection import AscentClimb, select_climbs
from mountain_perf.analyse.ascent.states import AscentState, Unavailable
from mountain_perf.schemas.processed import ClimbRegime


def make_climb(
    day: date,
    *,
    ref: str = "a",
    hr_bpm: float = 145.0,
    altitude_km: float = 1.5,
    d_plus_km: float = 0.5,
    start: datetime | None = None,
) -> AscentClimb:
    """Une montée gardée écrite à la main."""
    return AscentClimb(
        activity_ref=ref,
        day=day,
        start=start or at(day, 9),
        regime=ClimbRegime.LONG_CLIMB,
        log_speed=-1.8,
        hr_bpm=hr_bpm,
        d_plus_km=d_plus_km,
        altitude_km=altitude_km,
        intermediate=False,
        device=("garmin", 1),
        journal=(),
        temperature_c=15.0,
    )


def world_e_references() -> References:
    result = references(select_climbs(world_e_tables()).climbs, WORLD_E_LAST_DAY)
    assert isinstance(result, References)
    return result


@pytest.mark.parametrize(
    ("value", "step", "expected"),
    [
        (147.5, 5.0, 150.0),
        (142.4999, 5.0, 140.0),
        (142.5, 5.0, 145.0),
        (1450.0, 100.0, 1500.0),
        (1449.99, 100.0, 1400.0),
    ],
)
def test_r1_round_half_up(value: float, step: float, expected: float) -> None:
    """R1 : les cinq arrondis du § 12.1, la moitié vers le haut."""
    assert round_to(value, step) == expected


def test_r2_world_e_references() -> None:
    """R2 : les références du monde E (§ 12.2)."""
    refs = world_e_references()
    assert refs.hr_bpm == 145.0
    assert refs.hr_low_bpm == 140.0
    assert refs.hr_high_bpm == 150.0
    assert refs.altitude_km == pytest.approx(1.5, rel=1e-6, abs=1e-9)
    assert refs.d_plus_km == pytest.approx(0.8335, rel=1e-6, abs=1e-9)
    assert refs.last_day == WORLD_E_LAST_DAY
    assert refs.first_day == WORLD_E_LAST_DAY - timedelta(days=364)


def test_r3_the_past_year() -> None:
    """R3 : une montée au jour ``last_day − 365`` n'entre pas ; une au jour
    ``last_day − 364`` entre."""
    last = date(2002, 6, 30)
    inside = [
        make_climb(last, hr_bpm=150.0),
        make_climb(last - timedelta(days=10), hr_bpm=150.0),
    ]
    outside = make_climb(last - timedelta(days=365), hr_bpm=100.0, d_plus_km=9.0)
    edge = make_climb(last - timedelta(days=364), hr_bpm=120.0, d_plus_km=2.0)
    without = references([*inside, outside], last)
    assert isinstance(without, References)
    assert without.hr_bpm == 150.0
    assert without.d_plus_km == pytest.approx(0.5, rel=1e-15)
    with_edge = references([*inside, edge], last)
    assert isinstance(with_edge, References)
    assert with_edge.d_plus_km == pytest.approx(1.0, rel=1e-15)
    assert with_edge.first_day == last - timedelta(days=364)


def test_r4_fewer_than_two_climbs() -> None:
    """R4 : moins de deux montées dans l'année écoulée : ``INSUFFICIENT``."""
    last = date(2002, 6, 30)
    for climbs in ([], [make_climb(last)]):
        result = references(climbs, last)
        assert isinstance(result, Unavailable)
        assert result.state is AscentState.INSUFFICIENT
        assert "2" in result.reason


def test_r5_inclusive_quartiles() -> None:
    """R5 : FC 130, 140, 150, 160 : 145, 140 et 155 (la méthode « exclusive »
    donnerait 135 et 160)."""
    last = date(2002, 6, 30)
    climbs = [
        make_climb(last - timedelta(days=k), hr_bpm=h)
        for k, h in enumerate((130.0, 140.0, 150.0, 160.0))
    ]
    refs = references(climbs, last)
    assert isinstance(refs, References)
    assert (refs.hr_bpm, refs.hr_low_bpm, refs.hr_high_bpm) == (145.0, 140.0, 155.0)
