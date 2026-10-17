"""Séries dérivées d'une trace réalisée (M4a) : réexport du module commun
``mountain_perf.series`` (AN1-2a).

Trous, blocs, lissage par bloc et ``d_r`` (``0010`` D4.4) vivent dans le module
commun au moteur et à la piste analyse. Ce module ne définit rien : il réexporte
les mêmes objets, pour que le paquet ``backtest`` garde ses imports.
"""

from mountain_perf.series import (
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
