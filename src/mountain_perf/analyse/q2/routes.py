"""Les groupes de parcours de Q2 (AN3-3b, ``docs/decisions/0023``, Q-50 (a)).

Deux montées sont du même parcours si leurs départs, et leurs arrivées, sont à moins de
``route_radius_m`` (``haversine_m``) et si le rapport de leurs gains ne dépasse pas
``route_max_gain_ratio`` ; les groupes sont les composantes connexes de cette relation,
formées une fois sur les montées de toutes les journées des étapes 1 à 4. Le groupe
d'une journée est celui de sa montée de plus grand gain (à égalité, la plus tôt), jamais
de la plus longue en durée. La taille d'un groupe se compte sur les journées de
l'échantillon qui lui sont affectées ; un groupe d'au plus ``max_other_days`` journées
est « autre » (``None``).
"""

from __future__ import annotations

from collections.abc import Sequence

from mountain_perf.analyse.q2.data import Q2Climb, Q2Day
from mountain_perf.gpx.geo import haversine_m
from mountain_perf.schemas import ParameterSet


def _linked(a: Q2Climb, b: Q2Climb, radius_m: float, max_ratio: float) -> bool:
    if haversine_m(*a.start, *b.start) >= radius_m:
        return False
    if haversine_m(*a.end, *b.end) >= radius_m:
        return False
    return max(a.gain_m, b.gain_m) / min(a.gain_m, b.gain_m) <= max_ratio


def _find(parent: list[int], i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def _representative(day: Q2Day) -> int:
    """L'indice de la montée de plus grand gain ; à égalité, la plus tôt."""
    return min(
        range(len(day.climbs)),
        key=lambda i: (
            -day.climbs[i].gain_m,
            day.climbs[i].local_start_time,
            day.climbs[i].activity_ref,
        ),
    )


def route_groups(
    days: Sequence[Q2Day],
    parameters: ParameterSet,
    max_other_days: int,
    in_sample: Sequence[bool],
) -> tuple[int | None, ...]:
    """Le groupe de chaque journée de ``days`` (toutes les journées des étapes 1 à 4,
    triées par date), ``None`` pour « autre » : un groupe d'au plus ``max_other_days``
    journées affectées de l'échantillon (``in_sample``) est « autre » ; les autres sont
    numérotés 0, 1, 2… dans l'ordre de leur première journée affectée de
    l'échantillon."""
    if len(in_sample) != len(days):
        raise ValueError("in_sample : une valeur par journée est attendue")
    radius = parameters["route_radius_m"]
    ratio = parameters["route_max_gain_ratio"]
    climbs: list[Q2Climb] = []
    first_index: list[int] = []
    for day in days:
        first_index.append(len(climbs))
        climbs.extend(day.climbs)
    parent = list(range(len(climbs)))
    for i in range(len(climbs)):
        for j in range(i + 1, len(climbs)):
            if _linked(climbs[i], climbs[j], radius, ratio):
                a, b = _find(parent, i), _find(parent, j)
                if a != b:
                    parent[max(a, b)] = min(a, b)
    component = [
        _find(parent, first_index[k] + _representative(day))
        for k, day in enumerate(days)
    ]
    sizes: dict[int, int] = {}
    first: dict[int, int] = {}
    for k, root in enumerate(component):
        if in_sample[k]:
            sizes[root] = sizes.get(root, 0) + 1
            first.setdefault(root, k)
    kept = sorted(
        (root for root, size in sizes.items() if size > max_other_days),
        key=lambda root: (days[first[root]].day, first[root]),
    )
    number = {root: n for n, root in enumerate(kept)}
    return tuple(number.get(root) for root in component)
