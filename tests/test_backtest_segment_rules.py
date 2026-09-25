"""Règles des segments, valeurs exactes (§ 7.2b du brief M4a-2b, « fonctions pures »).

Une assertion par cellule du tableau des fonctions pures : les égalités de seuil se
testent ici, sur des valeurs exactement représentables, jamais à travers une trace
(§ 7.0 de M4a-2a).
"""

import pytest

from fixtures.matching import local_trace
from mountain_perf.backtest import TraceSeries, build_series, gap_between


def _gap_series() -> TraceSeries:
    """Instants ``(0, 1, 12, 13, 14, 15)`` : seul trou, l'intervalle 1."""
    trace = local_trace([0, 1, 12, 13, 14, 15], [(float(x), 0.0) for x in range(6)])
    series = build_series(trace)
    assert series.gap_after == (False, True, False, False, False)
    return series


# ---------------------------------------------------------------------------
# gap_between (§ 5b.2 ; 0010 D4.7, D4.9)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("first", "second"), [(0.5, 1.5), (1.0, 2.0), (1.5, 1.7)])
def test_gap_between_sees_the_gap_interval(first: float, second: float) -> None:
    """``⌊first⌋ <= 1 <= ⌈second⌉ − 1``."""
    assert gap_between(_gap_series(), first, second)


@pytest.mark.parametrize(
    ("first", "second"), [(0.5, 1.0), (0.0, 1.0), (1.0, 1.0), (2.0, 3.5)]
)
def test_gap_between_ignores_the_other_intervals(first: float, second: float) -> None:
    """Un franchissement en ``π = 1`` exactement n'entre pas dans l'intervalle 1."""
    assert not gap_between(_gap_series(), first, second)


def test_gap_between_refuses_decreasing_positions() -> None:
    with pytest.raises(ValueError, match="positions décroissantes"):
        gap_between(_gap_series(), 2.5, 1.0)
