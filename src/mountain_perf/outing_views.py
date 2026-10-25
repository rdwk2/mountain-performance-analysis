"""Ce que la page « sortie » affiche d'une sortie comparée à son préparé — le tracé
suivi, prévu contre réalisé et l'effort effectif, les écarts cumulés aux points — et
les libellés que ``mperf match`` et la page partagent.

Il lit les contrats seuls (``schemas/``) et n'importe ni ``backtest/``, ni ``ui/``, ni
``analyse/``.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from mountain_perf.schemas import (
    CLOCKS,
    Clock,
    ClockKind,
    MatchResult,
    ObservedPoint,
    OutingScores,
    PassageMatchResult,
    PointStatus,
    ScenarioScores,
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


# ---------------------------------------------------------------------------
# Le tracé suivi (0010 D4.11)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FollowedRoute:
    """La part du préparé que la trace a suivie, lue dans ``MatchResult.coverage``.

    Champs
    ------
    - ``reference_length_m`` — mètres — longueur ``L`` du préparé.
    - ``admitted_m`` — mètres — longueur des segments admis : la partie comparée.
    - ``admitted_share`` — sans unité — ``Coverage.fraction``, ``admitted_m / L``.
    - ``point_counts`` — sans unité — pour chaque ``PointStatus``, dans l'ordre de
      l'énumération, le nombre de points de score de ce statut.
    - ``prefix_end_m`` — mètres — fin du préfixe comparable, ``b_m``.
    """

    reference_length_m: float
    admitted_m: float
    admitted_share: float
    point_counts: tuple[tuple[PointStatus, int], ...]
    prefix_end_m: float


def followed_route(result: MatchResult) -> FollowedRoute:
    """Le tracé suivi de ``result`` : la partie comparée (tous les segments admis) et
    le préfixe comparable (jusqu'au premier segment non admis, ``b_m``) sont deux
    publications distinctes de ``0010`` D4.11 ; la première peut aller au-delà de la
    seconde. La couverture est celle qu'écrit ``mperf match`` : la vue ne la recalcule
    pas."""
    coverage = result.coverage
    return FollowedRoute(
        reference_length_m=coverage.reference_length_m,
        admitted_m=coverage.admitted_m,
        admitted_share=coverage.fraction,
        point_counts=tuple(
            (status, sum(point.status is status for point in result.points))
            for status in PointStatus
        ),
        prefix_end_m=coverage.prefix_end_m,
    )


def admitted_spans(result: MatchResult) -> tuple[tuple[float, float], ...]:
    """Les bornes ``(start_m, end_m)`` des segments admis, dans l'ordre ; deux
    segments admis qui se touchent restent deux intervalles."""
    return tuple(
        (segment.start_m, segment.end_m)
        for segment in result.segments
        if segment.admitted
    )


# ---------------------------------------------------------------------------
# Prévu contre réalisé, l'effort effectif (0010 D3, D7.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioEffort:
    """Le temps prévu par v0 brut sur le support comparé d'un scénario, sous une
    horloge, et l'effort effectif ``e* = exp(L)``.

    ``L`` est le niveau du support (``ClockScores.support.log_ratio``, ``0010`` D7.1),
    celui que publie ``mperf match`` — jamais celui du sous-support à temps positifs
    (D5.5), qui est un diagnostic. Pour v0, la durée prévue est inversement
    proportionnelle à l'effort : ``e* = P / T``, l'effort auquel v0 aurait prévu le
    temps réel ``T`` sur le support comparé.

    Ses limites : il est rétrospectif ; limité au support comparé ; faussé par les
    arrêts sous l'écoulé ; il mêle l'effort du jour et l'erreur du modèle (la courbe,
    les pentes) ; sur le préparé (usage), s'y ajoute l'écart entre le préparé et le
    chemin suivi (raccourcis, détours, GPS), que mesure l'écart entre l'usage et le
    contrôle (``0010`` D3 : ``G = L_usage − L_contrôle``, leur rapport vaut
    ``exp(G)``).

    Champs
    ------
    - ``projected_s`` — secondes — ``P``, la somme des durées prévues des segments
      admis ; ``None`` quand ``L`` est indisponible.
    - ``log_ratio`` — sans unité — ``L`` ; ``None`` quand il est indisponible.
    - ``unavailability`` — le motif de ``L`` indisponible, ``None`` sinon.
    - ``effective_effort`` — sans unité — ``e* = exp(L)`` ; ``None`` quand ``L`` est
      indisponible.
    """

    projected_s: float | None
    log_ratio: float | None
    unavailability: Unavailability | None
    effective_effort: float | None


@dataclass(frozen=True)
class EffortRow:
    """Une ligne de « prévu contre réalisé » : sous une horloge du rapport, le temps
    réel ``T`` sur les segments admis — le même pour les deux scénarios —, puis
    l'usage (``None`` sans référence) et le contrôle."""

    clock: Clock
    observed_s: float
    usage: ScenarioEffort | None
    control: ScenarioEffort


def _scenario_effort(scenario: ScenarioScores, index: int) -> ScenarioEffort:
    """L'effort effectif d'un scénario sous l'horloge ``CLOCKS[index]``."""
    metric = scenario.clocks[index].support.log_ratio
    if metric.value is None:
        return ScenarioEffort(None, None, metric.unavailability, None)
    # L disponible : chaque sortie du modèle est valide (0010 D7.1).
    projected_s = math.fsum(p for p in scenario.forecast.segment_s if p is not None)
    return ScenarioEffort(projected_s, metric.value, None, math.exp(metric.value))


def effort_rows(scores: OutingScores, clocks: Sequence[Clock]) -> tuple[EffortRow, ...]:
    """Une ligne par horloge de ``clocks`` (celles du rapport), dans leur ordre."""
    rows = []
    for clock in clocks:
        index = CLOCKS.index(clock)
        observed_s = math.fsum(
            segment.times_s[index] for segment in scores.observation.segments
        )
        usage = None
        if scores.usage is not None:
            usage = _scenario_effort(scores.usage, index)
        rows.append(
            EffortRow(clock, observed_s, usage, _scenario_effort(scores.control, index))
        )
    return tuple(rows)


# ---------------------------------------------------------------------------
# L'écart cumulé aux points (0010 D7.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GapRow:
    """Un point du préfixe : son nom, sa distance sur le préparé (mètres) et
    l'écart cumulé ``C_k`` (secondes, prévu − réel) sous chaque horloge de ``clocks``,
    ``None`` quand il est indisponible."""

    name: str
    distance_m: float
    errors_s: tuple[float | None, ...]


@dataclass(frozen=True)
class Gaps:
    """Les écarts cumulés de l'usage : l'origine commune ``b_0`` (mètres), où
    ``C_0 = 0`` par construction (``0010`` D7.3), une ligne par point du préfixe, et
    ``max |C_k|`` (secondes) sous chaque horloge, ``None`` quand il est
    indisponible."""

    origin_m: float
    rows: tuple[GapRow, ...]
    max_abs_s: tuple[float | None, ...]


def gaps(
    scores: OutingScores, passages: PassageMatchResult, clocks: Sequence[Clock]
) -> Gaps | None:
    """Les écarts cumulés aux points de l'usage sous les horloges de ``clocks``, dans
    leur ordre ; ``None`` sans usage. ``max |C_k|`` est celui de ``passage_errors`` :
    la vue ne le recalcule pas."""
    usage = scores.usage
    if usage is None:
        return None
    errors = []
    for clock in clocks:
        clock_errors = usage.clocks[CLOCKS.index(clock)].passage_errors
        assert clock_errors is not None  # contrat de ScenarioScores, en usage
        errors.append(clock_errors)
    rows = tuple(
        GapRow(
            name=point_name(point, passages),
            distance_m=point.distance_m,
            errors_s=tuple(e.errors_s[k].value for e in errors),
        )
        for k, point in enumerate(scores.observation.error_points)
    )
    return Gaps(
        origin_m=scores.observation.origin_m,
        rows=rows,
        max_abs_s=tuple(e.max_abs_error_s.value for e in errors),
    )
