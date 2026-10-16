"""Entrées construites de l'admission exploratoire (M4c-3) : des jours d'une sortie,
leurs temps et les projections de v0 brut et du candidat, passés par les vrais
producteurs (``score_scenario``, ``score_outing``, ``calibrate_performances``), sans GPX
ni appariement — la forme des essais de la passe experte (C1 à C26).

- :class:`Day` : une sortie, un jour ; ses segments (classe, écoulé), les projections
  de v0 brut et du candidat par segment (``None`` : absente) ; options (exclusion,
  parcours, D+/km, portion, temps nul, arrivée non observée, ``K`` et cumulés
  d'usage) ;
- :func:`history` : le jour d'historique du 1er juin, membre du calage des jours
  suivants ;
- :func:`inputs` : les ``AdmissionInput`` de jours, calés pour (0) et (1) ;
- :func:`experiment`, :func:`local`, :func:`borrowed` : une expérience et des
  références figées.

Les temps d'un segment sous les onze horloges sont ceux du monde du calage
(``clock_times``) ; un jour du 10 juin ou après a pour population le seul historique
(``o_j`` à J−7).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from fixtures.calibration import (
    TRAINING,
    OutingSpec,
    WorldSpec,
    forecast,
    observation,
    world_performances,
)
from fixtures.outings import PREPARED
from mountain_perf.backtest import (
    AdmissionInput,
    calibrate_performances,
    score_outing,
    score_scenario,
)
from mountain_perf.schemas import (
    CLOCKS,
    Clock,
    DeclaredEffect,
    DeclaredUsageTarget,
    ExperimentDeclaration,
    ExperimentMetric,
    FrozenReference,
    MetricValue,
    ModelKind,
    ObservedPoint,
    OutingLabel,
    OutingObservation,
    OutingScores,
    ParameterSet,
    ReferenceSource,
    Scenario,
    TargetMember,
    Unavailability,
)

A, F, D, X = "ascent", "flat", "descent", "mixed"
NINE = (A,) * 3 + (F,) * 3 + (D,) * 3
"""Trois segments de chaque classe : tous les garde-fous de régime sont exigés."""
BASE, CANDIDATE, RAW = ModelKind.V0_RECALIBRATED, ModelKind.CANDIDATE, ModelKind.V0_RAW


@dataclass(frozen=True)
class UsageK:
    """``K`` d'une sortie et ses cumulés : les éléments, les points observés (sous
    les onze horloges), et les cumulés d'usage de v0 brut et du candidat."""

    members: tuple[TargetMember, ...]
    points: tuple[ObservedPoint, ...]
    v0: tuple[float | None, ...]
    candidate: tuple[float | None, ...]


@dataclass(frozen=True)
class Day:
    """Une sortie d'un jour. ``elapsed`` : l'écoulé de chaque segment ; ``v0`` et
    ``candidate`` : les projections (s) de chaque segment, ``None`` absente ;
    ``regimes`` : les classes ; ``zero`` : des rangs de segment dont le temps est nul
    sous l'horloge ``zero_clock`` (l'arrivée suit) ; ``no_arrival`` : l'arrivée n'est
    pas observée ; ``usage_k`` : un ``K`` et ses cumulés à la place de l'arrivée
    seule ; ``portion_s`` : la durée de v0 brut sur la portion déclarée (défaut : la
    somme des projections de v0)."""

    outing_id: str
    day: str
    elapsed: tuple[float, ...]
    v0: tuple[float | None, ...]
    candidate: tuple[float | None, ...]
    regimes: tuple[str, ...] = NINE
    label: OutingLabel | None = TRAINING
    route: str = "a"
    excluded: bool = False
    dplus_per_km: float | None = 70.0
    portion_s: float | None = None
    zero: tuple[int, ...] = ()
    zero_clock: int = 1
    no_arrival: bool = False
    usage_k: UsageK | None = field(default=None)


def day(
    outing_id: str,
    on: str,
    elapsed: Sequence[float],
    v0: Sequence[float | None],
    candidate: Sequence[float | None],
    regimes: tuple[str, ...] = NINE,
    **options: Any,
) -> Day:
    """Un :class:`Day`, les séquences converties en tuples."""
    return Day(
        outing_id,
        on,
        tuple(elapsed),
        tuple(v0),
        tuple(candidate),
        regimes,
        **options,
    )


def history(factor: float = 1.0, regimes: tuple[str, ...] = NINE) -> Day:
    """L'historique du 1er juin : temps et v0 à 100 s par segment, le candidat à
    ``100·factor``."""
    n = len(regimes)
    return day(
        "historique",
        "2026-06-01",
        [100.0] * n,
        [100.0] * n,
        [100.0 * factor] * n,
        regimes,
    )


def _ratios(
    projections: tuple[float | None, ...], elapsed: tuple[float, ...]
) -> tuple[float, ...]:
    return tuple(
        math.nan if p is None else p / t
        for p, t in zip(projections, elapsed, strict=True)
    )


def _spec(entry: Day) -> OutingSpec:
    ratios = {
        RAW: _ratios(entry.v0, entry.elapsed),
        CANDIDATE: _ratios(entry.candidate, entry.elapsed),
    }
    return OutingSpec(
        entry.outing_id,
        entry.day,
        entry.label,
        tuple(zip(entry.regimes, entry.elapsed, strict=True)),
        ratios,
        ratios,
    )


def _observation(entry: Day, spec: OutingSpec) -> OutingObservation:
    seen = observation(spec)
    if entry.zero:
        i = entry.zero_clock
        segments = tuple(
            replace(
                segment,
                times_s=tuple(
                    0.0 if c == i and k in entry.zero else time
                    for c, time in enumerate(segment.times_s)
                ),
            )
            for k, segment in enumerate(seen.segments)
        )
        totals = tuple(
            math.fsum(segment.times_s[c] for segment in segments)
            for c in range(len(CLOCKS))
        )
        seen = replace(
            seen, segments=segments, targets=(replace(seen.targets[0], times_s=totals),)
        )
    if entry.no_arrival:
        absent = replace(
            seen.targets[0], times_s=None, unavailability=Unavailability.ABSENT
        )
        seen = replace(seen, targets=(absent,))
    if entry.usage_k is not None:
        seen = replace(
            seen, members=entry.usage_k.members, targets=entry.usage_k.points
        )
    return seen


def inputs(days: Sequence[Day]) -> list[AdmissionInput]:
    """Les entrées de la règle : pour chaque jour, sa performance (une sortie, de
    référence ``PREPARED``, sur son parcours), son observation, les scores d'usage non
    calés de v0 brut, et ceux de (0) et de (1) calés par ``calibrate_performances`` sur
    les jours reçus."""
    specs = [_spec(entry) for entry in days]
    unscaled: dict[str, dict[ModelKind, OutingScores]] = {}
    for entry, spec in zip(days, specs, strict=True):
        seen = _observation(entry, spec)
        by_model: dict[ModelKind, OutingScores] = {}
        for model in (RAW, CANDIDATE):
            control = forecast(spec, model, Scenario.CONTROL)
            usage = forecast(spec, model, Scenario.USAGE)
            if entry.usage_k is not None:
                cumulated = (
                    entry.usage_k.v0 if model is RAW else entry.usage_k.candidate
                )
                usage = replace(usage, target_s=cumulated)
            by_model[model] = score_outing(
                seen, score_scenario(seen, control), score_scenario(seen, usage)
            )
        unscaled[entry.outing_id] = by_model
    world = WorldSpec(tuple(specs), frozenset(), ())
    performances = tuple(
        replace(
            performance,
            outings=tuple(
                replace(outing, route_id=entry.route, reference=PREPARED)
                for outing in performance.outings
            ),
        )
        for entry, performance in zip(days, world_performances(world), strict=True)
    )
    calibrated = calibrate_performances(
        performances, unscaled, models=(BASE, CANDIDATE)
    )
    entries: list[AdmissionInput] = []
    for entry, performance, calibration in zip(
        days, performances, calibrated, strict=True
    ):
        calibrated_usage = {
            scores.usage.model: scores.usage
            for scores in calibration.outings
            if scores.usage is not None
        }
        raw = unscaled[entry.outing_id][RAW]
        portion = entry.portion_s
        if portion is None:
            portion = math.fsum(p for p in entry.v0 if p is not None)
        entries.append(
            AdmissionInput(
                performance,
                entry.excluded,
                raw.observation,
                raw.usage,
                calibrated_usage[BASE],
                calibrated_usage[CANDIDATE],
                entry.dplus_per_km,
                portion,
            )
        )
    return entries


def experiment(
    target: ExperimentMetric = ExperimentMetric.DESCENT_LEVEL,
    clock: Clock = CLOCKS[0],
    references: tuple[FrozenReference, ...] = (),
    usage_targets: tuple[DeclaredUsageTarget, ...] = (),
) -> ExperimentDeclaration:
    """Une expérience : un effet synthétique, ``target`` sous ``clock``, en usage."""
    return ExperimentDeclaration(
        effect=DeclaredEffect(
            "synthétique", "entrées construites", ParameterSet(()), None
        ),
        target=target,
        clock=clock,
        scenario=Scenario.USAGE,
        base=BASE,
        candidate=CANDIDATE,
        usage_targets=usage_targets,
        frozen_references=references,
        reference_documents=None,
        analysis_date=None,
    )


def local(
    metric: ExperimentMetric,
    value: float | None,
    route: str = "a",
    count: int = 2,
    clock: Clock = CLOCKS[0],
) -> FrozenReference:
    """Une référence locale ; ``value`` absente : indisponible, ``support
    insuffisant``."""
    motif = Unavailability.INSUFFICIENT_SUPPORT if value is None else None
    return FrozenReference(
        metric,
        clock,
        ReferenceSource.LOCAL,
        route,
        MetricValue(value, motif, count),
        (),
    )


def borrowed(
    metric: ExperimentMetric,
    value: float,
    donors: tuple[str, ...] = ("b",),
    count: int = 2,
    clock: Clock = CLOCKS[0],
) -> FrozenReference:
    """Une référence empruntée."""
    return FrozenReference(
        metric,
        clock,
        ReferenceSource.BORROWED,
        None,
        MetricValue(value, None, count),
        donors,
    )


EVALUATED: Mapping[str, str] = {
    "j": "2026-06-10",
    "j1": "2026-06-10",
    "j2": "2026-06-11",
}
"""Les jours évalués habituels des tests (après l'historique et son ``o_j``)."""
