"""Backtest (M4) : observer les sorties réelles avant tout modèle (``0010``)."""

from mountain_perf.backtest.series import (
    MAX_STEP_S,
    SMOOTHING_HALF_WIDTH,
    TraceSeries,
    build_series,
)

__all__ = [
    "MAX_STEP_S",
    "SMOOTHING_HALF_WIDTH",
    "TraceSeries",
    "build_series",
]
