"""L'intégrale de la FC d'une fenêtre (``HeartRateSeries.integral``, AN3-1a) : l'outil
du moteur (``docs/decisions/0017``, P5.1), commun avec la piste analyse. La fenêtre est
rognée à la série ; les opérations sont celles de ``mean``, dont la moyenne vaut
exactement l'intégrale divisée par la durée couverte."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import accumulate, pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mountain_perf.estimation.intervals import (
    MAX_HR_STEP_S,
    HeartRateSeries,
    heart_rate_series,
)
from mountain_perf.schemas import HeartRateChannel
from test_schemas_interim import recording as interim_recording


def series_of(times: Sequence[float], values: Sequence[float]) -> HeartRateSeries:
    """La série de FC d'un enregistrement minimal, à l'origine 0."""
    rec = interim_recording(
        heart_rate=HeartRateChannel(
            tuple(float(t) for t in times), tuple(float(v) for v in values)
        )
    )
    series = heart_rate_series(rec, 0.0)
    assert series is not None
    return series


def linear() -> HeartRateSeries:
    """La FC linéaire : ``100 + 0,2·t`` bpm, toutes les secondes de 0 à 200 s."""
    times = [float(t) for t in range(201)]
    return series_of(times, [100.0 + 0.2 * t for t in times])


def test_the_integral_of_a_window_inside_the_series() -> None:
    """L'intégrale de la FC interpolée, pas la moyenne des échantillons (116,67)."""
    series = series_of([0.0, 1.0, 6.0], [100.0, 100.0, 150.0])
    integral, covered = series.integral(0.0, 6.0)
    assert (integral, covered) == pytest.approx((725.0, 6.0), rel=1e-9)
    assert integral / covered == pytest.approx(725.0 / 6.0, rel=1e-9)
    assert series_of([0.0, 10.0], [120.0, 130.0]).integral(2.0, 6.0) == pytest.approx(
        (496.0, 4.0), rel=1e-9
    )


def test_a_gap_is_neither_integrated_nor_covered() -> None:
    series = series_of([0.0, 10.0, 25.0], [120.0, 130.0, 140.0])
    assert series.integral(5.0, 20.0) == pytest.approx((637.5, 5.0), rel=1e-9)
    linked = series_of([0.0, 10.0], [100.0, 120.0])
    assert linked.integral(0.0, 10.0) == pytest.approx((1100.0, 10.0), rel=1e-9)
    unlinked = series_of([0.0, 10.001], [100.0, 120.0])
    assert unlinked.integral(0.0, 10.0) == (0.0, 0.0)


def test_a_window_is_clipped_to_the_series() -> None:
    series = series_of([0.0, 10.0], [120.0, 130.0])
    assert series.integral(8.0, 14.0) == pytest.approx((258.0, 2.0), rel=1e-9)
    assert series.mean(8.0, 14.0, 0.0) is None
    assert series.integral(12.0, 14.0) == (0.0, 0.0)
    assert series.integral(-5.0, -1.0) == (0.0, 0.0)
    assert series.integral(-2.0, 12.0) == pytest.approx((1250.0, 10.0), rel=1e-9)


@st.composite
def series_and_window(
    draw: st.DrawFn,
) -> tuple[HeartRateSeries, float, float]:
    """Une série (des pas de part et d'autre de :data:`MAX_HR_STEP_S`, et parfois ce
    pas exactement) et une fenêtre ``low < high`` dans ``[t0 ; tN]``."""
    start = draw(st.floats(0.0, 1000.0))
    steps = draw(
        st.lists(
            st.one_of(
                st.floats(1e-3, 2 * MAX_HR_STEP_S),
                st.just(MAX_HR_STEP_S),
            ),
            min_size=1,
            max_size=30,
        )
    )
    times = list(accumulate(steps, initial=start))
    if any(b <= a for a, b in pairwise(times)):
        times = sorted(set(times))
    if len(times) < 2:
        times = [start, start + 1.0]
    values = draw(
        st.lists(st.floats(20.0, 250.0), min_size=len(times), max_size=len(times))
    )
    series = series_of(times, values)
    t0, tn = times[0], times[-1]
    u = draw(st.floats(0.0, 1.0))
    v = draw(st.floats(0.0, 1.0))
    low, high = sorted((t0 + u * (tn - t0), t0 + v * (tn - t0)))
    low, high = max(low, t0), min(high, tn)
    if not high > low:
        low, high = t0, tn
    return series, low, high


@settings(deadline=None)
@given(series_and_window())
def test_the_mean_is_the_integral_over_the_covered_time(
    case: tuple[HeartRateSeries, float, float],
) -> None:
    series, low, high = case
    mean = series.mean(low, high, 0.0)
    if mean is not None:
        integral, covered = series.integral(low, high)
        assert mean == integral / covered


def test_the_engine_window_is_unchanged() -> None:
    series = linear()
    assert series.mean(70.0, 90.0, 0.8) == pytest.approx(116.0, rel=1e-9)
    assert series.mean(70.0, 210.0, 0.8) is None
