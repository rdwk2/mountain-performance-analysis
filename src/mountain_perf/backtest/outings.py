"""Sorties retenues, domaine et performances (``0010`` D0, D2.1).

Fonctions pures : la construction effective du profil de domaine (lecture du GPX,
``build_profile``) appartient à l'orchestration de M4b ; ici, ``in_domain`` reçoit
son D+/km déjà calculé.
"""

import math
from collections import defaultdict
from collections.abc import Iterable, Set
from datetime import date

from mountain_perf.backtest.calendar import civil_date
from mountain_perf.schemas import (
    ArtifactRef,
    Outing,
    Performance,
    RetentionDecision,
    RouteProfile,
    Sport,
)

RETENTION_LIMIT_S = 14_400.0
"""Durée écoulée cumulée d'un jour au-delà de laquelle une sortie suivante n'est plus
retenue : 4 h, **strictement** (``0010`` D0). La première sortie du jour est toujours
retenue."""

DOMAIN_MIN_DPLUS_PER_KM = 40.0
"""D+ minimal du profil, en mètres par kilomètre, pour entrer dans le domaine :
seuil **inclusif** (``0010`` D2.1)."""


def retain_outings(outings: Iterable[Outing]) -> tuple[RetentionDecision, ...]:
    """Rang et rétention de chaque sortie dans son jour civil (``0010`` D0).

    Les sorties sont regroupées par jour civil de leur départ, à Paris, tous sports
    confondus, puis ordonnées par ``(start_time, outing_id)``. Une sortie est retenue
    si elle est la première du jour, ou si le cumul des écoulés du jour jusqu'à elle
    incluse est ``< RETENTION_LIMIT_S``. Résultat ordonné par ``(civil_date, rank)``.
    """
    days: defaultdict[date, list[Outing]] = defaultdict(list)
    for outing in outings:
        days[civil_date(outing.start_time)].append(outing)
    decisions: list[RetentionDecision] = []
    for day in sorted(days):
        elapsed_s: list[float] = []
        ordered = sorted(days[day], key=lambda o: (o.start_time, o.outing_id))
        for rank, outing in enumerate(ordered, start=1):
            elapsed_s.append(outing.elapsed_s)
            cumulative_s = math.fsum(elapsed_s)
            decisions.append(
                RetentionDecision(
                    outing=outing,
                    civil_date=day,
                    rank=rank,
                    cumulative_elapsed_s=cumulative_s,
                    retained=rank == 1 or cumulative_s < RETENTION_LIMIT_S,
                )
            )
    return tuple(decisions)


def dplus_per_km(profile: RouteProfile) -> float:
    """D+ du profil lissé rapporté à sa longueur, en m/km (``0010`` D2.1)."""
    return profile.cumulative_ascent_m[-1] / profile.distance_m[-1] * 1000


def domain_profile_source(outing: Outing) -> tuple[ArtifactRef, ...]:
    """Fichier(s) du profil de domaine : le préparé ou la trace de référence désignée,
    à défaut les traces de la sortie, à défaut rien (``0010`` D2.1).

    Leurs chemins se retrouvent par ``ManifestReadResult.artifact_paths``.
    """
    if outing.reference is not None:
        return (outing.reference.artifact,)
    return outing.traces


def in_domain(
    outing: Outing, dplus_per_km: float | None, domain_start_date: date
) -> bool:
    """Trail à pied, parti au plus tôt le jour de début du domaine, profil de D+/km
    ``>= 40`` (``0010`` D2.1). Un D+/km inconnu (``None``) est hors domaine."""
    return (
        outing.sport is Sport.FOOT
        and civil_date(outing.start_time) >= domain_start_date
        and dplus_per_km is not None
        and dplus_per_km >= DOMAIN_MIN_DPLUS_PER_KM
    )


def group_performances(
    decisions: Iterable[RetentionDecision], in_domain_ids: Set[str]
) -> tuple[Performance, ...]:
    """Performances : par jour civil, les sorties retenues **et** dans le domaine,
    dans l'ordre des rangs (``0010`` D0). Un jour sans telle sortie ne donne rien ;
    résultat par dates croissantes."""
    days: defaultdict[date, list[RetentionDecision]] = defaultdict(list)
    for decision in decisions:
        if decision.retained and decision.outing.outing_id in in_domain_ids:
            days[decision.civil_date].append(decision)
    return tuple(
        Performance(
            civil_date=day,
            outings=tuple(
                decision.outing for decision in sorted(days[day], key=lambda d: d.rank)
            ),
        )
        for day in sorted(days)
    )
