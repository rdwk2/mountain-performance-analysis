"""Propriétés des segments (§ 8.2b, test 6, du brief M4a-2b ; ``0010`` D4.9, D4.10).

1. **Trace qui suit une référence droite** (stratégie de la première propriété de
   M4a-2a, sans trou) : aucun segment ``unobserved_bound``, ``gap`` ni
   ``interior_deviation`` ; sans écart latéral, ``H_2 = 0`` et ``rho >= 1`` à
   ``1e−6`` près ; avec l'écart latéral de M4a-2a, ``H_2 <= 10`` à ``1e−6`` près.
   Rien de plus : les positions lissées avancent ou retardent quand le pas change et
   au bord du bloc, et un segment court peut sortir de ``[0,6 ; 1,6]``.
2. **Traces quelconques** (stratégie de la seconde propriété de M4a-2a, avec ses
   ``@example``, plus rho bas et Coin pour exercer les deux motifs de contrôle à
   chaque exécution) : ``match_trace`` rend un ``MatchResult`` ; motif et prédicats
   cohérents ; totaux du support admis sous ceux de la trace ; ``I_sens,A`` ordonné à
   ``1e−9·max(1, E_A)`` près.
"""

from collections.abc import Callable

import pytest
from hypothesis import Phase, example, find, given, settings

from fixtures import matching as cases
from fixtures import segments as segment_cases
from fixtures.matching import MatchCase, StraightCase, straight_case
from fixtures.segments import matched, observed
from mountain_perf.backtest import interior_ok, length_ratio_ok
from mountain_perf.schemas import ScoreSegmentObservation, SegmentExclusion
from strategies import straight_cases, wandering_cases

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


@settings(deadline=None)
@given(wandering_cases())
@example(cases.t05())
@example(cases.x03_bis())
@example(cases.window())
@example(cases.x01())
@example(segment_cases.low_ratio())
@example(cases.corner())
def test_properties_of_match_trace(case: MatchCase) -> None:
    """Exemples fixés : T05 (trou), X03-bis (retour), Fenêtre (point non daté), X01
    (extrémités ancrées), rho bas (``length_ratio``), Coin (``interior_deviation``).
    ``match_trace`` rend un ``MatchResult`` : ses invariants tiennent."""
    result = matched(case)
    tolerance_m = case.parameters["lateral_tolerance_m"]
    for segment in result.segments:
        ratio, deviation_m = segment.length_ratio, segment.interior_deviation_m
        if segment.exclusion in (None, RATIO, INTERIOR):
            assert ratio is not None
            assert deviation_m is not None
            ratio_ok = length_ratio_ok(ratio)
            deviation_ok = interior_ok(deviation_m, tolerance_m)
            if segment.exclusion is None:
                assert ratio_ok
                assert deviation_ok
            elif segment.exclusion is RATIO:
                assert not ratio_ok
            else:
                assert ratio_ok
                assert not deviation_ok
    for trace, support in zip(result.trace_totals, result.admitted_totals, strict=True):
        assert support.moving_s <= trace.moving_s + TOLERANCE
        assert support.stopped_s <= trace.stopped_s + TOLERANCE
        assert support.undetermined_s <= trace.undetermined_s + TOLERANCE
    if result.admitted_sensitivity_range_s is not None:
        low_s, high_s = result.admitted_sensitivity_range_s
        elapsed_s = result.coverage.admitted_elapsed_s
        assert low_s <= high_s + 1e-9 * max(1.0, elapsed_s)


RATIO = SegmentExclusion.LENGTH_RATIO
INTERIOR = SegmentExclusion.INTERIOR_DEVIATION

_SEARCH = settings(
    max_examples=2000, database=None, deadline=None, phases=[Phase.generate]
)
"""Seule l'existence compte : pas de réduction de l'exemple trouvé, qui coûtait
jusqu'à une minute par motif."""


def _has(exclusion: SegmentExclusion | None) -> Callable[[MatchCase], bool]:
    def condition(case: MatchCase) -> bool:
        return any(s.exclusion is exclusion for s in observed(case)[1])

    condition.__name__ = f"has_{exclusion or 'admitted'}"
    return condition


@pytest.mark.parametrize(
    "exclusion",
    [None, RATIO, INTERIOR, SegmentExclusion.GAP, SegmentExclusion.UNOBSERVED_BOUND],
)
# L'exemple trouvé n'est pas réduit (_SEARCH) : son repr est long, et inutile ici.
@pytest.mark.filterwarnings("ignore:Generating overly large repr")
def test_wandering_strategy_reaches(exclusion: SegmentExclusion | None) -> None:
    """La stratégie des traces quelconques produit des segments admis et de chaque
    motif."""
    find(wandering_cases(), _has(exclusion), settings=_SEARCH)
