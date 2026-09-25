"""Propriétés des segments (§ 8.2b, test 6, du brief M4a-2b ; ``0010`` D4.9, D4.10).

1. **Trace qui suit une référence droite** (stratégie de la première propriété de
   M4a-2a, sans trou) : aucun segment ``unobserved_bound``, ``gap`` ni
   ``interior_deviation`` ; sans écart latéral, ``H_2 = 0`` et ``rho >= 1`` à
   ``1e−6`` près ; avec l'écart latéral de M4a-2a, ``H_2 <= 10`` à ``1e−6`` près.
   Rien de plus : les positions lissées avancent ou retardent quand le pas change et
   au bord du bloc, et un segment court peut sortir de ``[0,6 ; 1,6]``.
"""

from hypothesis import example, given, settings

from fixtures.matching import StraightCase, straight_case
from fixtures.segments import observed
from mountain_perf.schemas import ScoreSegmentObservation, SegmentExclusion
from strategies import straight_cases

TOLERANCE = 1e-6
"""« à ``1e−6`` près » (§ 8.2b, test 6) : ``H_2`` dépasse 0 par arrondi, jusqu'à
``8e−10`` m mesuré en relecture."""

NEVER_ON_A_STRAIGHT_FOLLOW = frozenset(
    {
        SegmentExclusion.UNOBSERVED_BOUND,
        SegmentExclusion.GAP,
        SegmentExclusion.INTERIOR_DEVIATION,
    }
)

FAST = straight_case(260.0, -1.0, 0.0, [(3.0, 1)], [1.0, -1.0])
SLOW = straight_case(2999.0, -20.0, 10.0, [(0.3, 640)], [-1.0, 0.5])
MIXED = straight_case(1013.0, -7.5, -3.0, [(0.3, 1), (3.0, 640), (1.7, 97)], [0.25])
"""Les trois exemples de M4a-2a (``test_backtest_matching_properties.py``), tous avec
un écart latéral : pour la variante latérale seulement."""

LEVEL_FAST = straight_case(260.0, -1.0, 0.0, [(3.0, 1)], [0.0])
LEVEL_SLOW = straight_case(2999.0, -20.0, 0.0, [(0.3, 640)], [0.0])
LEVEL_MIXED = straight_case(1013.0, -7.5, 0.0, [(0.3, 1), (3.0, 640), (1.7, 97)], [0.0])
"""Leurs jumeaux à ``y_0 = 0`` et de pente nulle, pour la variante sans écart."""


def _followed(straight: StraightCase) -> tuple[ScoreSegmentObservation, ...]:
    _, segments = observed(straight.case)
    assert not {segment.exclusion for segment in segments} & NEVER_ON_A_STRAIGHT_FOLLOW
    return segments


@settings(deadline=None)
@given(straight_cases(lateral=False))
@example(LEVEL_FAST)
@example(LEVEL_SLOW)
@example(LEVEL_MIXED)
def test_level_trace_on_a_straight_reference(straight: StraightCase) -> None:
    """Écart latéral nul : ``H_2 <= 1e−6`` et ``rho >= 1 − 1e−6``."""
    for segment in _followed(straight):
        assert segment.h2_m is not None
        assert segment.length_ratio is not None
        assert segment.h2_m <= TOLERANCE
        assert segment.length_ratio >= 1 - TOLERANCE


@settings(deadline=None)
@given(straight_cases())
@example(FAST)
@example(SLOW)
@example(MIXED)
def test_trace_with_a_lateral_offset_on_a_straight_reference(
    straight: StraightCase,
) -> None:
    """Écart latéral ``|y| <= 10`` m : ``H_2 <= 10 + 1e−6``."""
    for segment in _followed(straight):
        assert segment.h2_m is not None
        assert segment.h2_m <= 10 + TOLERANCE
