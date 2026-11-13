"""La demi-heure de FC la plus basse du jour (AN3-3a, ``docs/decisions/0019``) :
``lowest_heart_rate_window``, chaque étape de sa règle sur un cas à la main, puis une
propriété. Les FC sont entières : les sommes, et donc les égalités de moyennes, sont
exactes ; un résultat se compare par ``==``."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from itertools import pairwise

from hypothesis import given, settings
from hypothesis import strategies as st

from fixtures.days import source
from mountain_perf.analyse.days import lowest_heart_rate_window
from mountain_perf.schemas import DayFamily, HeartRateSeries

WINDOW_S = 1800.0
FRACTION = 0.8
"""Les défauts déclarés des deux paramètres."""


def series(times: Sequence[float], bpm: Sequence[float]) -> HeartRateSeries:
    """Une série de FC des jours, aux instants ``times`` (secondes depuis minuit)."""
    return HeartRateSeries(
        tuple(float(t) for t in times),
        tuple(float(b) for b in bpm),
        source(DayFamily.HEART_RATE),
    )


def lowest(
    times: Sequence[float],
    bpm: Sequence[float],
    window_s: float = WINDOW_S,
    fraction: float = FRACTION,
) -> float | None:
    return lowest_heart_rate_window(series(times, bpm), window_s, fraction)


def test_the_lowest_window_by_hand() -> None:
    """Compte minimal 2,4 : trois points ; la fenêtre de 1 200 s (55, 54, 57) a la plus
    basse moyenne ; son milieu, 1 200 + 900."""
    times = (0, 600, 1200, 1800, 2400, 3000)
    assert lowest(times, (60, 58, 55, 54, 57, 62)) == 2100.0


def test_the_minimum_count_at_its_exact_value() -> None:
    """Une fenêtre de exactement ``need`` points est admise (borne comprise)."""
    assert 0.8 * 1800.0 / 360.0 == 4.0
    times_a = [360.0 * k for k in range(31) if 360.0 * k != 5040.0]
    bpm_a = [50 if 3600.0 <= t < 5400.0 else 70 for t in times_a]
    assert statistics.median(b - a for a, b in pairwise(times_a)) == 360.0
    assert lowest(times_a, bpm_a) == 4500.0
    keep = [i for i, t in enumerate(times_a) if t != 4680.0]
    times_b = [times_a[i] for i in keep]
    bpm_b = [bpm_a[i] for i in keep]
    assert lowest(times_b, bpm_b) == 4140.0


def test_the_minimum_count_keeps_its_order() -> None:
    """``need`` vaut ``fraction × durée / pas``, de gauche à droite : 55 exactement,
    quand ``fraction × (durée / pas)`` le dépasse d'un arrondi."""
    assert 0.55 * 600.0 / 6.0 == 55.0
    assert 0.55 * (600.0 / 6.0) != 55.0
    times = [6.0 * k for k in range(55)]
    assert lowest(times, [60] * 55, 600.0, 0.55) == 300.0


def test_the_window_excludes_its_right_edge() -> None:
    """[t ; t + durée[ : le point de 1 800 s n'est pas dans la fenêtre de 0 s."""
    times = (0, 600, 1200, 1800, 2400)
    assert lowest(times, (60, 60, 60, 40, 90)) == 1500.0


def test_a_tie_keeps_the_earliest_window() -> None:
    """Les fenêtres de 600 s et de 3 000 s ont la même moyenne : la plus tôt reste."""
    times = [600.0 * k for k in range(8)]
    assert lowest(times, (70, 50, 55, 60, 70, 60, 55, 50)) == 1500.0


def test_the_step_is_the_median_gap() -> None:
    """Douze écarts : le pas est leur médiane (280), ni la basse, ni la haute, ni la
    moyenne."""
    times = (0, 200, 400, 600, 800, 1000, 1200, 1560, 1920, 2280, 2640, 3000, 3600)
    bpm = (60, 80, 50, 80, 70, 80, 50, 70, 80, 70, 50, 60, 60)
    assert lowest(times, bpm) == 1900.0


def test_the_mean_is_not_weighted_by_time() -> None:
    """La moyenne d'une fenêtre est celle de ses points, sans poids."""
    times = (0, 900, 1200, 1800, 2400)
    assert lowest(times, (60, 70, 55, 60, 65)) == 2100.0


def test_without_a_lowest_window() -> None:
    assert lowest_heart_rate_window(None, WINDOW_S, FRACTION) is None
    assert lowest((0,), (60,)) is None
    assert lowest((0, 600), (60, 60)) is None


def test_a_sparse_series_admits_a_single_point() -> None:
    """Pas médian de 12 h : le compte minimal est sous 1, une fenêtre d'un point est
    admise."""
    assert lowest((0, 43200), (55, 90)) == 900.0


def _windows(
    times: Sequence[float], bpm: Sequence[float], window_s: float, fraction: float
) -> list[tuple[float, float]]:
    """Les fenêtres admises, ``(début, moyenne)``, recomptées ici."""
    step = statistics.median(b - a for a, b in pairwise(times))
    need = fraction * window_s / step
    out: list[tuple[float, float]] = []
    for start in times:
        inside = [
            b for t, b in zip(times, bpm, strict=True) if start <= t < start + window_s
        ]
        if len(inside) >= need:
            out.append((start, sum(inside) / len(inside)))
    return out


@st.composite
def _drawn(draw: st.DrawFn) -> tuple[list[float], list[float]]:
    count = draw(st.integers(2, 40))
    first = draw(st.integers(-3600, 3600))
    gaps = draw(st.lists(st.integers(1, 900), min_size=count - 1, max_size=count - 1))
    times = [float(first)]
    for gap in gaps:
        times.append(times[-1] + gap)
    bpm = draw(st.lists(st.integers(20, 250), min_size=count, max_size=count))
    return times, [float(b) for b in bpm]


@settings(deadline=None)
@given(
    _drawn(),
    st.sampled_from([600.0, 1800.0, 2700.0]),
    st.sampled_from([0.0, 0.5, 0.8, 1.0]),
)
def test_the_lowest_window_is_the_lowest_admitted_mean(
    drawn: tuple[list[float], list[float]], window_s: float, fraction: float
) -> None:
    times, bpm = drawn
    admitted = _windows(times, bpm, window_s, fraction)
    result = lowest(times, bpm, window_s, fraction)
    if not admitted:
        assert result is None
        return
    assert result is not None
    start = result - window_s / 2
    assert start in times
    means = dict(admitted)
    assert start in means
    chosen = means[start]
    for other, mean in admitted:
        assert chosen <= mean
        if other < start:
            assert chosen < mean
