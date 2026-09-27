"""Propriétés des passages (§ 8.3, test 6, du brief M4a-3 ; ``0010`` D4.12).

Stratégie :func:`strategies.passage_cases` — lieux nommés et arrêts sur une référence
droite, ingrédients étiquetés —, et les exemples fixés du § 7.3.1 qui exercent chaque
branche à chaque exécution : Passages, Égalité, Chronologie, Y01, Final hors
préfixe. Propriétés :

1. un épisode attribué désigne une seule occurrence, et la somme des
   ``episode_count`` égale le nombre d'épisodes attribués ;
2. ``arrival_s <= crossing_s <= departure_s`` pour toute occurrence à instants ;
3. toute occurrence comparable vérifie ``t*_0 <= arrival_s`` et
   ``departure_s <= t*_m`` ;
4. parmi les occurrences intermédiaires ``found``, ou ``ambiguous`` avec
   ``chronology_violation``, dans l'ordre ``(s_w, rang)``, deux consécutives toutes
   deux comparables vérifient ``départ <= arrivée de la suivante`` ;
5. une occurrence intermédiaire est hors préfixe si et seulement si ``m = 0`` ou
   ``s_w`` n'est pas dans ``[b_0 ; b_m]``.

Un test vérifie, par ``hypothesis.find``, que chaque étiquette produit le cas qu'elle
vise.
"""

from collections.abc import Callable
from itertools import pairwise

import pytest
from hypothesis import Phase, example, find, given, settings

from fixtures import passages as p
from fixtures.matching import MatchCase
from mountain_perf.schemas import (
    EpisodeOutcome,
    PassageMatchResult,
    PassageRole,
    PassageStatus,
)
from strategies import passage_cases

INTERMEDIATE = PassageRole.INTERMEDIATE


@settings(deadline=None)
@given(passage_cases())
@example(p.passages())
@example(p.tie())
@example(p.chronology())
@example(p.y01())
@example(p.final_outside_prefix())
def test_properties_of_observe_passages(case: MatchCase) -> None:
    """``0010`` D4.12 : attribution unique, enveloppes, maintien, chronologie des
    comparables, préfixe jugé sur ``[b_0 ; b_m]`` (choix 2, 10, 11, 12)."""
    match, result = p.observed_passages(case)
    passages = result.passages
    attributed = [e for e in result.episodes if e.outcome is EpisodeOutcome.ATTRIBUTED]
    assert sum(q.episode_count for q in passages) == len(attributed)
    for attribution in attributed:
        assert attribution.passage_index is not None
        assert passages[attribution.passage_index].episode_count >= 1
    origin_s, prefix_end_s = match.points[0].time_s, match.coverage.prefix_end_s
    for q in passages:
        if q.crossing_s is not None:
            assert q.arrival_s is not None
            assert q.departure_s is not None
            assert q.arrival_s <= q.crossing_s <= q.departure_s
        if q.comparable:
            assert q.arrival_s is not None
            assert q.departure_s is not None
            assert origin_s is not None
            assert prefix_end_s is not None
            assert origin_s <= q.arrival_s
            assert q.departure_s <= prefix_end_s
    judged = sorted(
        (
            rank
            for rank, q in enumerate(passages)
            if q.role is INTERMEDIATE
            and (
                q.status is PassageStatus.FOUND
                or (q.status is PassageStatus.AMBIGUOUS and q.chronology_violation)
            )
        ),
        key=lambda rank: (passages[rank].point.distance_m, rank),
    )
    for a, b in pairwise(judged):
        first, second = passages[a], passages[b]
        if first.comparable and second.comparable:
            assert first.departure_s is not None
            assert second.arrival_s is not None
            assert first.departure_s <= second.arrival_s
    m = match.coverage.prefix_segment_count
    start_m, end_m = match.points[0].effective_m, match.coverage.prefix_end_m
    for q in passages:
        if q.role is INTERMEDIATE:
            outside = m == 0 or not start_m <= q.point.distance_m <= end_m
            assert (q.status is PassageStatus.OUTSIDE_PREFIX) == outside


_SEARCH = settings(
    max_examples=2000, database=None, deadline=None, phases=[Phase.generate]
)
"""Seule l'existence compte : pas de réduction de l'exemple trouvé."""


def _has_outcome(outcome: EpisodeOutcome) -> Callable[[PassageMatchResult], bool]:
    return lambda result: any(e.outcome is outcome for e in result.episodes)


def _outside_intermediate(result: PassageMatchResult) -> bool:
    return any(
        q.role is INTERMEDIATE and q.status is PassageStatus.OUTSIDE_PREFIX
        for q in result.passages
    )


def _chronology_violation(result: PassageMatchResult) -> bool:
    return any(q.chronology_violation for q in result.passages)


def _not_maintained(result: PassageMatchResult) -> bool:
    return any(
        q.role is not PassageRole.DEPARTURE
        and q.status in (PassageStatus.FOUND, PassageStatus.ANCHORED)
        and not q.comparable
        for q in result.passages
    )


TARGETS: dict[str, tuple[frozenset[str], Callable[[PassageMatchResult], bool]]] = {
    "lieu près d'un arrêt, épisode attribué": (
        frozenset({"near_stop"}),
        _has_outcome(EpisodeOutcome.ATTRIBUTED),
    ),
    "paire symétrique, épisode non attribué": (
        frozenset({"tie_pair"}),
        _has_outcome(EpisodeOutcome.TIE),
    ),
    "arrêt, épisode sans candidate": (
        frozenset({"stop"}),
        _has_outcome(EpisodeOutcome.NO_CANDIDATE),
    ),
    "détour ou fin avant l'arrivée, lieu hors préfixe": (
        frozenset({"detour", "short"}),
        _outside_intermediate,
    ),
    "reptation, violation de chronologie": (
        frozenset({"creep"}),
        _chronology_violation,
    ),
    "départ en reptation, occurrence trouvée non maintenue": (
        frozenset({"start_creep"}),
        _not_maintained,
    ),
}
"""Chaque étiquette de construction, et le cas qu'elle doit savoir produire."""


@pytest.mark.parametrize("target", TARGETS, ids=TARGETS.keys())
# L'exemple trouvé n'est pas réduit (_SEARCH) : son repr est long, et inutile ici.
@pytest.mark.filterwarnings("ignore:Generating overly large repr")
def test_passage_strategy_reaches(target: str) -> None:
    labels, reached = TARGETS[target]

    def condition(case: MatchCase) -> bool:
        return bool(case.features & labels) and reached(p.observed_passages(case)[1])

    find(passage_cases(), condition, settings=_SEARCH)
