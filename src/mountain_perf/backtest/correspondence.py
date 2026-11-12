"""La correspondance entre une sortie du manifeste et les activités d'``interim/`` que
l'humain a déclarées (OG-2, ``0010`` D2.6) : trois contrôles, chacun un refus, avant
tout écrit."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from mountain_perf.estimation.origin import ActivityEnd
from mountain_perf.schemas import Outing, RecordedTrace
from mountain_perf.validation import ContractError


def _utc(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _points(outing: Outing, trace: RecordedTrace | None) -> list[datetime]:
    """Les points de la sortie : les instants de sa trace, ou, sans trace, ses deux
    instants déclarés."""
    if trace is None:
        return [outing.start_time, outing.end_time]
    return [trace.start_time + timedelta(seconds=t) for t in trace.time_s]


def _start(end: ActivityEnd) -> datetime:
    """Le début de l'intervalle d'une activité : le plus tôt de ``index_start`` et de
    ``recording_start`` (s'il existe)."""
    if end.recording_start is None:
        return end.index_start
    return min(end.index_start, end.recording_start)


def check_correspondence(
    outing: Outing,
    trace: RecordedTrace | None,
    activities: Sequence[ActivityEnd],
    origins: Sequence[datetime],
    tolerance_s: float,
) -> None:
    """Les trois contrôles de la correspondance d'une sortie (OG-2, ``0010`` D2.6),
    chacun un refus (``ContractError``), dans cet ordre :

    0. ``tolerance_s`` fini et ``>= 0`` ; ``activities`` portent exactement les
       références de ``outing.activity_refs``, dans leur ordre ;
    1. chaque activité a une fin connue et recouvre la sortie (un instant commun
       suffit) ;
    2. ensemble, elles couvrent la sortie point par point, chaque intervalle élargi de
       ``tolerance_s`` de chaque côté (les comparaisons en secondes depuis le premier
       point) ;
    3. à chaque origine de ``origins`` (triées), la fin du manifeste et la plus tardive
       des fins sûres sont du même côté.

    Les points de la sortie : les instants de sa trace, ou ses deux instants déclarés
    sans trace. L'intervalle d'une activité : du plus tôt de ``index_start`` et de
    ``recording_start`` à ``safe_end``. Les instants des messages sont en UTC. Rien
    n'est vérifié à la borne basse ; la fonction ne lit ni fichier ni horloge."""
    if not math.isfinite(tolerance_s) or tolerance_s < 0:
        raise ContractError(
            f"tolerance_s : un nombre fini >= 0 attendu, reçu {tolerance_s}."
        )
    if tuple(end.activity_ref for end in activities) != outing.activity_refs:
        raise ContractError(
            f"activities : celles de la sortie {outing.outing_id} attendues."
        )
    where = f"sortie {outing.outing_id}"
    points = _points(outing, trace)
    first, last = points[0], points[-1]
    intervals: list[tuple[datetime, datetime]] = []
    for end in activities:
        if end.safe_end is None:
            raise ContractError(
                f"{where} : l'activité {end.activity_ref} n'a pas de fin connue ; sa "
                "correspondance ne se vérifie pas."
            )
        start = _start(end)
        if end.safe_end < first or start > last:
            raise ContractError(
                f"{where} : l'activité {end.activity_ref} ({_utc(start)} – "
                f"{_utc(end.safe_end)}) ne recouvre pas la sortie ({_utc(first)} – "
                f"{_utc(last)})."
            )
        intervals.append((start, end.safe_end))
    widened = [
        (
            (start - first).total_seconds() - tolerance_s,
            (stop - first).total_seconds() + tolerance_s,
        )
        for start, stop in intervals
    ]
    for point in points:
        at = (point - first).total_seconds()
        if not any(low <= at <= high for low, high in widened):
            raise ContractError(
                f"{where} : à {_utc(point)}, la trace n'est dans aucune activité "
                f"déclarée, à {tolerance_s:g} s près."
            )
    latest = max(activities, key=lambda end: end.safe_end or first)
    latest_end = latest.safe_end
    assert latest_end is not None  # contrôle 1
    for origin in origins:
        if (outing.end_time < origin) != (latest_end < origin):
            raise ContractError(
                f"{where} : à l'origine {_utc(origin)}, la fin du manifeste "
                f"({_utc(outing.end_time)}) et la fin sûre de l'activité "
                f"{latest.activity_ref} ({_utc(latest_end)}) ne sont pas du même côté."
            )
