"""Fixtures synthétiques des passages (M4a-3) — plan à 45° N, valeurs inventées.

Convention du § 7.0 du brief M4a-3 : références et traces décrites en mètres
``(x, y)``, converties par :func:`fixtures.traces.local_deg` ; chemins par
:class:`fixtures.matching.TracePath` et :func:`fixtures.segments.stay`, traces par
formule par :func:`fixtures.matching.local_trace`, positions calculées rang par rang.

- le repère direct du § 7.3.2 et ses traces à 1 Hz, pour ``crossing_candidates``
  borné et ``occurrence_crossing``.

Utilisées par ``tests/test_backtest_crossing_bound.py``.
"""

from collections.abc import Sequence

from fixtures.matching import local_trace
from fixtures.traces import local_deg
from mountain_perf.backtest.geometry import LocalFrame
from mountain_perf.schemas import RecordedTrace

_ANCHOR = local_deg(0.0, 0.0)

DIRECT_FRAME = LocalFrame(
    anchor_lat_deg=_ANCHOR[0],
    anchor_lon_deg=_ANCHOR[1],
    tangent=(1.0, 0.0),
    normal=(-0.0, 1.0),
)
"""Repère direct du § 7.3.2 : ancre ``local_deg(0, 0)``, tangente ``(1, 0)``,
normale ``(−0,0 ; 1)`` ; ``h = x`` et l'écart latéral ``= y`` dans le plan de
l'ancre. Un enregistrement en ``x = 0`` a exactement les flottants de l'ancre
(``h = 0``) ; ``x = −1`` et ``x = 1`` ont des ``h`` opposés au bit près."""


def direct_trace(
    x_m: Sequence[float],
    y_m: float = 0.0,
    time_s: Sequence[float] | None = None,
) -> RecordedTrace:
    """Trace ``local_trace`` sur l'axe du repère direct : positions ``(x, y)``,
    instants ``0, 1, 2, …`` sauf mention."""
    times = list(time_s) if time_s is not None else [float(t) for t in range(len(x_m))]
    return local_trace(times, [(x, y_m) for x in x_m])
