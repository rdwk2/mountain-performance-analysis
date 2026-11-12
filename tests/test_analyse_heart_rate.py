"""La FC d'une montée (``mountain_perf.analyse.heart_rate``, AN3-1a ;
``docs/decisions/0014``, précisions d'AN3-1a) : la moyenne de la FC sur un support de
morceaux, chacun décalé, par l'intégrale de l'outil du moteur ; la seconde moitié du
support, coupée exactement ; la couverture, bornée à 1.

La FC linéaire : ``100 + 0,2·t`` bpm, toutes les secondes de 0 à 200 s. Le support M :
une montée de 10 à 90 s, arrêtée de 30 à 40 s (70 s)."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fixtures.montees import FLAT, recording
from mountain_perf.analyse.climbs import motion_track
from mountain_perf.analyse.heart_rate import (
    HR_LAG_S,
    ClimbHeartRate,
    moving_pieces,
    second_half,
    support_heart_rate,
)
from mountain_perf.estimation.intervals import HeartRateSeries, heart_rate_series
from mountain_perf.schemas import (
    CENTRAL_CONVENTION_INDEX,
    CLOCK_CONVENTIONS,
    HeartRateChannel,
    IntervalState,
)
from test_schemas_interim import recording as interim_recording

M = ((10.0, 30.0), (40.0, 90.0))
"""Le support M (70 s)."""

M_BY_SECOND = tuple((float(t), float(t + 1)) for t in (*range(10, 30), *range(40, 90)))
"""Le même support, en pas d'une seconde."""


def series_of(times: Sequence[float], values: Sequence[float]) -> HeartRateSeries:
    """La série de FC d'un enregistrement minimal, à l'origine 0 (une autre origine
    effacerait les instants sous-normaux)."""
    rec = interim_recording(
        heart_rate=HeartRateChannel(
            tuple(float(t) for t in times), tuple(float(v) for v in values)
        )
    )
    series = heart_rate_series(rec, 0.0)
    assert series is not None
    return series


def linear(until_s: int = 200) -> HeartRateSeries:
    """La FC linéaire, toutes les secondes de 0 à ``until_s``."""
    times = [float(t) for t in range(until_s + 1)]
    return series_of(times, [100.0 + 0.2 * t for t in times])


def test_the_lagged_heart_rate_of_the_moving_support() -> None:
    """Les fenêtres décalées sont [70 ; 90] et [100 ; 150] : 8 570 / 70."""
    series = linear()
    result = support_heart_rate(series, M, HR_LAG_S)
    assert result.bpm == pytest.approx(8570 / 70, rel=1e-9)
    assert result.coverage == pytest.approx(1.0, rel=1e-9)
    by_second = support_heart_rate(series, M_BY_SECOND, HR_LAG_S)
    assert by_second.bpm == pytest.approx(8570 / 70, rel=1e-9)
    assert by_second.coverage == pytest.approx(1.0, rel=1e-9)


def test_the_unlagged_heart_rate() -> None:
    result = support_heart_rate(linear(), M, 0.0)
    assert result.bpm == pytest.approx(7730 / 70, rel=1e-9)
    assert result.coverage == pytest.approx(1.0, rel=1e-9)


def test_the_second_half_is_cut_exactly() -> None:
    """Le milieu du temps M (35 s) tombe à 55 s : garder des morceaux entiers ne
    garderait rien ici."""
    series = linear()
    half = second_half(M)
    assert half == ((55.0, 90.0),)
    result = support_heart_rate(series, half, HR_LAG_S)
    assert result.bpm == pytest.approx(126.5, rel=1e-9)
    assert result.coverage == pytest.approx(1.0, rel=1e-9)
    by_second = second_half(M_BY_SECOND)
    assert by_second[0] == (55.0, 56.0)
    assert len(by_second) == 35
    assert support_heart_rate(series, by_second, HR_LAG_S).bpm == pytest.approx(
        126.5, rel=1e-9
    )


def test_a_half_on_a_boundary_starts_the_next_piece() -> None:
    half = second_half(((0.0, 10.0), (20.0, 30.0)))
    assert half == ((20.0, 30.0),)
    assert support_heart_rate(linear(), half, HR_LAG_S).bpm == pytest.approx(
        117.0, rel=1e-9
    )
    assert second_half(()) == ()


def test_the_elapsed_window() -> None:
    result = support_heart_rate(linear(), ((10.0, 90.0),), HR_LAG_S)
    assert result.bpm == pytest.approx(122.0, rel=1e-9)
    assert result.coverage == pytest.approx(1.0, rel=1e-9)


def test_the_coverage_is_bounded_by_one() -> None:
    """Le couvert, une différence de cumulés, dépasse la fenêtre d'un arrondi."""
    series = series_of([0.0, 0.1, 0.2, 0.3, 0.4, 0.5], [140.0] * 6)
    assert series.integral(0.01, 0.15)[1] / (0.15 - 0.01) > 1.0
    result = support_heart_rate(series, ((0.01, 0.15),), 0.0)
    assert result.coverage == 1.0
    assert result.bpm == pytest.approx(140.0, rel=1e-9)


@st.composite
def series_and_support(
    draw: st.DrawFn,
) -> tuple[HeartRateSeries, tuple[tuple[float, float], ...], float]:
    """Une série aux instants ``>= 0`` (sous-normaux permis), un support et un
    décalage."""
    instants = st.floats(0.0, 500.0, allow_subnormal=True)
    times = sorted(set(draw(st.lists(instants, min_size=2, max_size=30))))
    if len(times) < 2:
        times = [0.0, 1.0]
    values = draw(
        st.lists(st.floats(20.0, 250.0), min_size=len(times), max_size=len(times))
    )
    bounds = draw(st.lists(st.tuples(instants, instants), max_size=8))
    pieces = tuple((min(a, b), max(a, b)) for a, b in bounds if a != b)
    lag = draw(st.sampled_from([0.0, HR_LAG_S]) | st.floats(-100.0, 100.0))
    return series_of(times, values), pieces, lag


@settings(deadline=None)
@given(series_and_support())
def test_the_coverage_stays_a_fraction(
    case: tuple[HeartRateSeries, tuple[tuple[float, float], ...], float],
) -> None:
    series, pieces, lag = case
    result = support_heart_rate(series, pieces, lag)
    assert 0.0 <= result.coverage <= 1.0
    assert (result.bpm is None) == (result.coverage == 0.0)


def test_a_heart_rate_that_stops_lowers_the_coverage() -> None:
    """La FC s'arrête à 130 s : la fenêtre [100 ; 150] n'est couverte que jusqu'à
    130 s, et la moyenne divise par la durée couverte."""
    series = linear(until_s=130)
    result = support_heart_rate(series, M, HR_LAG_S)
    assert result.bpm == pytest.approx(6010 / 50, rel=1e-9)
    assert result.coverage == pytest.approx(50 / 70, rel=1e-9)
    elapsed = support_heart_rate(series, ((10.0, 90.0),), HR_LAG_S)
    assert elapsed.bpm == pytest.approx(120.0, rel=1e-9)
    assert elapsed.coverage == pytest.approx(0.75, rel=1e-9)


def test_without_heart_rate_or_support() -> None:
    nothing = ClimbHeartRate(None, 0.0)
    assert support_heart_rate(None, M, HR_LAG_S) == nothing
    assert support_heart_rate(linear(), (), HR_LAG_S) == nothing
    late = series_of([500.0, 501.0], [140.0, 140.0])
    assert support_heart_rate(late, M, HR_LAG_S) == nothing
    assert HR_LAG_S == 60.0


def test_a_coverage_that_rounds_to_zero_has_no_value() -> None:
    """Un couvert positif mais infime devant le support s'écrit 0 en fraction : pas de
    moyenne avec une couverture nulle."""
    series = series_of([0.0, 5e-324], [100.0, 100.0])
    covered = series.integral(0.0, 100.0)[1]
    assert covered > 0.0
    assert covered / 100.0 == 0.0
    assert support_heart_rate(series, ((0.0, 100.0),), 0.0) == ClimbHeartRate(None, 0.0)


def test_the_moving_pieces_of_a_climb() -> None:
    """Une vue aux instants 0, 10, 20, 30, 40 s ; sous la convention centrale, les
    quatre pas sont M, S, M, M ; sous les autres, tous S : seule la centrale compte."""
    track = motion_track(recording([FLAT], noise=False))
    assert track is not None
    m, s = IntervalState.MOVING, IntervalState.STOPPED
    states = tuple(
        (m, s, m, m) if k == CENTRAL_CONVENTION_INDEX else (s, s, s, s)
        for k in range(len(CLOCK_CONVENTIONS))
    )
    view = dataclasses.replace(
        track, time_s=(0.0, 10.0, 20.0, 30.0, 40.0), states=states
    )
    assert moving_pieces(view, 5.0, 40.0) == (
        (5.0, 10.0),
        (20.0, 30.0),
        (30.0, 40.0),
    )
    assert moving_pieces(view, 10.0, 35.0) == ((20.0, 30.0), (30.0, 35.0))


def test_a_climb_heart_rate_is_frozen() -> None:
    value = ClimbHeartRate(140.0, 1.0)
    field = "bpm"
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, field, 150.0)
