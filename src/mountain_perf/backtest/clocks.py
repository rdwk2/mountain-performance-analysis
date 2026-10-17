"""Horloges d'une trace (M4a) : réexport du module commun ``mountain_perf.clocks``
(AN1-2a).

Fenêtres, qualification, confirmation des arrêts, partition M/S/U, horloges
cumulées, totaux et épisodes (``0010`` D5) vivent dans le module commun au moteur et
à la piste analyse. Ce module ne définit rien : il réexporte les mêmes objets, dont
deux aides privées que ses tests importent, pour que le paquet ``backtest`` garde
ses imports.
"""

from mountain_perf.clocks import (
    CLOCK_HALF_WINDOW_S,
    CLOCK_THRESHOLD_RELATIVE_TOLERANCE,
    Qualification,
    WindowMeasures,
    _diameter_m,
    _smoothed_at,
    clock_duration_s,
    clock_partition,
    confirm,
    cumulative_s,
    qualify,
    stop_episodes,
    trace_totals,
    window_measures,
)

__all__ = [
    "CLOCK_HALF_WINDOW_S",
    "CLOCK_THRESHOLD_RELATIVE_TOLERANCE",
    "Qualification",
    "WindowMeasures",
    "_diameter_m",
    "_smoothed_at",
    "clock_duration_s",
    "clock_partition",
    "confirm",
    "cumulative_s",
    "qualify",
    "stop_episodes",
    "trace_totals",
    "window_measures",
]
