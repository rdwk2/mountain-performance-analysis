"""Séries dérivées (§ 4.3 du brief M4a-1, ``0010`` D4.4) : blocs, lissage, d_r."""

from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fixtures.traces import equatorial_x_m, planar_trace
from mountain_perf.backtest.series import (
    MAX_STEP_S,
    SMOOTHING_HALF_WIDTH,
    build_series,
)
from mountain_perf.gpx.geo import haversine_m
from mountain_perf.gpx.trace_reader import read_trace
from mountain_perf.schemas import RecordedTrace
from strategies import eventful_traces

TRONCONS = Path(__file__).parent / "fixtures" / "trace_troncons.gpx"


def test_constants_of_0010_d4_4() -> None:
    assert MAX_STEP_S == 10.0
    assert SMOOTHING_HALF_WIDTH == 2


def test_block_smoothing_is_truncated_at_block_edges() -> None:
    """§ 7.1 : un bloc de 7 enregistrements à ``x = 0 … 6`` m."""
    series = build_series(planar_trace(range(7), [float(x) for x in range(7)]))
    smoothed_x = [equatorial_x_m(lon) for lon in series.smoothed_longitude_deg]
    assert smoothed_x == pytest.approx([1, 1.5, 2, 3, 4, 4.5, 5], abs=1e-6)
    assert series.smoothing_complete == (False, False, True, True, True, False, False)


def test_troncons_fixture_blocks_gaps_and_smoothing() -> None:
    """§ 7.1 : deux blocs, un trou sur le seul intervalle 5, lissage complet en 2, 3,
    8 et 9, sans rien prolonger à travers le trou."""
    series = build_series(read_trace([TRONCONS]))
    assert series.blocks == ((0, 5), (6, 11))
    assert series.block_of == (0,) * 6 + (1,) * 6
    assert series.gap_after == tuple(i == 5 for i in range(11))
    assert [i for i, ok in enumerate(series.smoothing_complete) if ok] == [2, 3, 8, 9]
    smoothed_x = [equatorial_x_m(lon) for lon in series.smoothed_longitude_deg]
    # Bloc 1 aux x bruts 0, 1, 2, 3, 5, 6 ; bloc 2 à 7 … 12.
    assert smoothed_x == pytest.approx(
        [1, 1.5, 2.2, 3.4, 4, 14 / 3, 8, 8.5, 9, 10, 10.5, 11], abs=1e-6
    )


def test_troncons_fixture_realized_distance() -> None:
    """§ 7.1 : positions brutes, doublon écarté, raccord à travers le trou compris."""
    series = build_series(read_trace([TRONCONS]))
    assert series.realized_distance_m == pytest.approx(
        [0, 1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12], abs=1e-6
    )


@pytest.mark.parametrize(
    ("step_s", "is_gap"), [(10.0, False), (10.001, True), (9.999, False)]
)
def test_gap_threshold_is_strict(step_s: float, is_gap: bool) -> None:
    """``0010`` D4.9 : 10 s n'est pas un trou, 10,001 s en est un."""
    series = build_series(planar_trace((0.0, 1.0, 1.0 + step_s), [0.0, 1.0, 2.0]))
    assert series.gap_after == (False, is_gap)
    assert len(series.blocks) == (2 if is_gap else 1)


# ---------------------------------------------------------------------------
# Propriétés, sur des traces qui contiennent toujours un trou
# ---------------------------------------------------------------------------


@given(eventful_traces())
def test_blocks_partition_the_records_at_the_gaps(trace: RecordedTrace) -> None:
    series = build_series(trace)
    assert any(series.gap_after)
    assert series.blocks[0][0] == 0
    assert series.blocks[-1][1] == len(trace.time_s) - 1
    for (_, last), (first, _) in pairwise(series.blocks):
        assert first == last + 1
        assert series.gap_after[last]
    for first, last in series.blocks:
        assert not any(series.gap_after[first:last])
        assert set(series.block_of[first : last + 1]) == {
            series.block_of[first],
        }


@given(eventful_traces())
def test_smoothing_is_complete_iff_five_records_without_gap(
    trace: RecordedTrace,
) -> None:
    series = build_series(trace)
    n = len(trace.time_s)
    for i, complete in enumerate(series.smoothing_complete):
        window = range(i - SMOOTHING_HALF_WIDTH, i + SMOOTHING_HALF_WIDTH)
        expected = (
            i - SMOOTHING_HALF_WIDTH >= 0
            and i + SMOOTHING_HALF_WIDTH <= n - 1
            and not any(series.gap_after[j] for j in window)
        )
        assert complete == expected


@given(eventful_traces())
def test_smoothed_values_stay_within_their_block_window(trace: RecordedTrace) -> None:
    series = build_series(trace)
    raw = (trace.latitude_deg, trace.longitude_deg, trace.elevation_m)
    smoothed = (
        series.smoothed_latitude_deg,
        series.smoothed_longitude_deg,
        series.smoothed_elevation_m,
    )
    for i in range(len(trace.time_s)):
        first, last = series.blocks[series.block_of[i]]
        lo = max(first, i - SMOOTHING_HALF_WIDTH)
        hi = min(last, i + SMOOTHING_HALF_WIDTH)
        for values, means in zip(raw, smoothed, strict=True):
            window = values[lo : hi + 1]
            assert min(window) - 1e-9 <= means[i] <= max(window) + 1e-9


@given(eventful_traces(), st.data())
def test_a_block_never_influences_another(
    trace: RecordedTrace, data: st.DataObject
) -> None:
    """Jamais prolongé à travers un trou : déplacer un bloc ne change pas les autres."""
    series = build_series(trace)
    b = data.draw(st.integers(min_value=0, max_value=len(series.blocks) - 1))
    first, last = series.blocks[b]
    moved = replace(
        trace,
        elevation_m=tuple(
            z + 100.0 if first <= i <= last else z
            for i, z in enumerate(trace.elevation_m)
        ),
        longitude_deg=tuple(
            lon + 1e-4 if first <= i <= last else lon
            for i, lon in enumerate(trace.longitude_deg)
        ),
    )
    other = build_series(moved)
    for i in range(len(trace.time_s)):
        if not first <= i <= last:
            assert other.smoothed_elevation_m[i] == series.smoothed_elevation_m[i]
            assert other.smoothed_longitude_deg[i] == series.smoothed_longitude_deg[i]


@given(eventful_traces())
def test_realized_distance_is_cumulative_and_bounded_below(
    trace: RecordedTrace,
) -> None:
    series = build_series(trace)
    d_r = series.realized_distance_m
    assert d_r[0] == 0
    assert all(b >= a for a, b in pairwise(d_r))
    chord_m = haversine_m(
        trace.latitude_deg[0],
        trace.longitude_deg[0],
        trace.latitude_deg[-1],
        trace.longitude_deg[-1],
    )
    assert d_r[-1] >= chord_m - 1e-6
