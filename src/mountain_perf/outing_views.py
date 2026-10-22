"""Ce que la page « sortie » affiche d'une sortie comparée à son préparé — le tracé
suivi, prévu contre réalisé et l'effort effectif, les écarts cumulés aux points — et
les libellés que ``mperf match`` et la page partagent.

Il lit les contrats seuls (``schemas/``) et n'importe ni ``backtest/``, ni ``ui/``, ni
``analyse/``.
"""

from collections.abc import Mapping

from mountain_perf.schemas import (
    Clock,
    ClockKind,
    ObservedPoint,
    PassageMatchResult,
    PointStatus,
    Unavailability,
)

POINT_STATUS_LABELS: Mapping[PointStatus, str] = {
    PointStatus.FOUND: "trouvé",
    PointStatus.ANCHORED: "ancré",
    PointStatus.AMBIGUOUS: "ambigu",
    PointStatus.ABSENT: "absent",
    PointStatus.OUT_OF_TOLERANCE: "hors ε",
    PointStatus.UNDEFINED_TANGENT: "tangente indéfinie",
}
"""Libellés d'affichage des statuts de point, ceux de ``0010`` D4.11."""

METRIC_UNAVAILABILITY_LABELS: Mapping[Unavailability, str] = {
    Unavailability.INSUFFICIENT_SUPPORT: "support insuffisant",
    Unavailability.ZERO_TIME: "temps nul",
    Unavailability.MODEL_ERROR: "erreur du modèle",
    Unavailability.ABSENT: "absent",
    Unavailability.AMBIGUOUS: "ambigu",
    Unavailability.UNDEFINED_TANGENT: "tangente indéfinie",
}
"""Libellés d'affichage d'une valeur indisponible des scores (``0010`` D0 ; § 6.7 du
brief M4b-2)."""


def clock_label(clock: Clock) -> str:
    """``écoulé``, ``M θ<n>``, ``(M+U) θ<n>`` (§ 6.7)."""
    if clock.convention_index is None:
        return "écoulé"
    kind = "M" if clock.kind is ClockKind.MOVING else "(M+U)"
    return f"{kind} θ{clock.convention_index + 1}"


def point_name(point: ObservedPoint, passages: PassageMatchResult) -> str:
    """``point k`` ou le nom du lieu."""
    if point.passage_index is not None:
        return passages.passages[point.passage_index].point.point.name
    return f"point {point.score_index}"
