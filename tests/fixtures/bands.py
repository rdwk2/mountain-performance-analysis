"""Monde synthétique des fourchettes (M4d-2) — objets construits directement, sans GPX
ni appariement, sur le modèle du monde du calage (``fixtures.calibration``).

Une sortie (:class:`BandSpec`) : son jour, son étiquette, ses segments admis
``(classe, écoulé)`` de 100 m, les rapports ``p_i / e_i`` de chaque modèle non calé en
usage et en contrôle (``fixtures.calibration``) ; et, en usage, son ``K`` (des
:class:`Element` : abscisse, cumul observé sous l'écoulé ou motif, puis cumul non calé
de chaque modèle) et ses points de ``C_k`` (D7.3, même forme). Sans ``K`` donné : la
seule arrivée, en ``L``, observée au total des segments, prévue à la somme des
projections (comme le monde du calage).

:func:`world` : les performances, les scores non calés (v0 brut et les trois
baselines, base de ``q_usage`` la prévision d'usage de v0 brut), le calage
(``calibrate_performances``) et les fourchettes (``evaluation_bands``) d'un monde.

Les onze temps d'un segment ou d'un cumul observé : ceux de ``clock_times``
(l'écoulé, puis des fractions distinctes de lui).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from fixtures.calibration import (
    GENERATED_AT,
    REFERENCE,
    SEGMENT_M,
    TRACE,
    UNSCALED,
    OutingSpec,
    Ratios,
    clock_times,
    world_performances,
)
from mountain_perf.backtest import (
    calibrate_performances,
    evaluation_bands,
    score_outing,
    score_scenario,
)
from mountain_perf.schemas import (
    AdmittedSegment,
    CalibratedPerformance,
    ModelForecast,
    ModelKind,
    ObservedPoint,
    OutingBands,
    OutingLabel,
    OutingObservation,
    OutingScores,
    ParameterSet,
    Performance,
    RegimeClass,
    Scenario,
    TargetMember,
    Unavailability,
)

WINDOW: tuple[date, date] = (date(2026, 6, 1), date(2026, 6, 10))
"""La fenêtre de la courbe du monde, bornes comprises."""


@dataclass(frozen=True)
class Element:
    """Un élément de ``K`` ou un point de ``C_k`` : son abscisse, son cumul observé
    sous l'écoulé (``None`` : non observé, au motif ``motif``), et le cumul non calé de
    chaque modèle (``None`` : absent)."""

    distance_m: float
    observed_s: float | None
    forecast_s: Mapping[ModelKind, float | None]
    motif: Unavailability = Unavailability.ABSENT


@dataclass(frozen=True)
class BandSpec:
    """Une sortie du monde des fourchettes (voir le module)."""

    outing_id: str
    day: str
    label: OutingLabel | None
    segments: tuple[tuple[str, float], ...]
    control: Ratios
    usage: Ratios = field(default_factory=dict)
    targets: tuple[Element, ...] = ()
    points: tuple[Element, ...] = ()
    hour: int = 9
    duration_h: float = 1.0

    @property
    def outing(self) -> OutingSpec:
        """La sortie du monde du calage (performances, segments, rapports)."""
        return OutingSpec(
            self.outing_id,
            self.day,
            self.label,
            self.segments,
            self.control,
            dict(self.usage),
            self.hour,
            self.duration_h,
        )


def _segments(spec: BandSpec) -> tuple[AdmittedSegment, ...]:
    return tuple(
        AdmittedSegment(
            k,
            SEGMENT_M * k,
            SEGMENT_M * (k + 1),
            SEGMENT_M * k,
            SEGMENT_M * (k + 1),
            SEGMENT_M * k,
            SEGMENT_M * (k + 1),
            RegimeClass(regime),
            clock_times(elapsed),
        )
        for k, (regime, elapsed) in enumerate(spec.segments)
    )


def _projections(
    spec: BandSpec, model: ModelKind, scenario: Scenario
) -> list[float | None]:
    ratios = (spec.usage if scenario is Scenario.USAGE else spec.control)[model]
    return [
        None if math.isnan(ratio) else ratio * elapsed
        for ratio, (_, elapsed) in zip(ratios, spec.segments, strict=True)
    ]


def _default_arrival(spec: BandSpec) -> tuple[Element, ...]:
    total = (
        math.fsum(elapsed for _, elapsed in spec.segments) if spec.segments else None
    )
    forecast: dict[ModelKind, float | None] = {}
    for model in UNSCALED:
        if not spec.usage:
            forecast[model] = None
            continue
        values = _projections(spec, model, Scenario.USAGE)
        present = [p for p in values if p is not None]
        forecast[model] = (
            math.fsum(present) if values and len(present) == len(values) else None
        )
    return (Element(_length(spec), total, forecast),)


def _length(spec: BandSpec) -> float:
    distances = [e.distance_m for e in (*spec.targets, *spec.points)]
    return max([SEGMENT_M * max(1, len(spec.segments)), *distances])


def _targets(spec: BandSpec) -> tuple[Element, ...]:
    return spec.targets if spec.targets else _default_arrival(spec)


def _observed(element: Element, **indices: int | None) -> ObservedPoint:
    if element.observed_s is None:
        return ObservedPoint(
            element.distance_m, **indices, unavailability=element.motif, times_s=None
        )
    return ObservedPoint(
        element.distance_m,
        **indices,
        unavailability=None,
        times_s=clock_times(element.observed_s),
    )


def observation(spec: BandSpec) -> OutingObservation:
    """L'observation d'une sortie : ses segments ; en usage, ses points de ``C_k``
    (score ``1, 2…``) et son ``K`` (lieux ``0, 1…``, puis l'arrivée de la grille)."""
    targets = _targets(spec)
    members = (
        *(TargetMember(k, False) for k in range(len(targets) - 1)),
        TargetMember(None, True),
    )
    observed = (
        *(
            _observed(element, score_index=None, passage_index=k)
            for k, element in enumerate(targets[:-1])
        ),
        _observed(targets[-1], score_index=len(spec.segments), passage_index=None),
    )
    points = tuple(
        _observed(element, score_index=k + 1, passage_index=None)
        for k, element in enumerate(spec.points)
    )
    return OutingObservation(
        reference_length_m=_length(spec),
        origin_m=0.0,
        origin_s=0.0,
        segments=_segments(spec),
        error_points=points,
        members=members,
        targets=observed,
        arrival_anchor_gap_m=None,
    )


def forecast(spec: BandSpec, model: ModelKind, scenario: Scenario) -> ModelForecast:
    """La prévision non calée de ``model`` dans un scénario ; en usage, ses cumuls aux
    points de ``C_k`` et aux éléments de ``K``."""
    usage = scenario is Scenario.USAGE
    return ModelForecast(
        scenario=scenario,
        source=REFERENCE if usage else TRACE,
        curve_ref="courbe-du-monde",
        parameters=ParameterSet(()),
        engine_version="monde",
        generated_at=GENERATED_AT,
        segment_s=tuple(_projections(spec, model, scenario)),
        point_s=tuple(e.forecast_s[model] for e in spec.points) if usage else (),
        target_s=tuple(e.forecast_s[model] for e in _targets(spec)) if usage else (),
    )


def outing_scores(spec: BandSpec) -> dict[ModelKind, OutingScores]:
    """Les scores non calés d'une sortie, sous les quatre modèles non calés ; en usage,
    de base la prévision de v0 brut (D7.4)."""
    obs = observation(spec)
    base = forecast(spec, ModelKind.V0_RAW, Scenario.USAGE) if spec.usage else None
    scores: dict[ModelKind, OutingScores] = {}
    for model in UNSCALED:
        usage = None
        if spec.usage:
            usage = score_scenario(
                obs, forecast(spec, model, Scenario.USAGE), base=base
            )
        control = score_scenario(obs, forecast(spec, model, Scenario.CONTROL))
        scores[model] = score_outing(obs, control, usage)
    return scores


@dataclass(frozen=True)
class BandWorld:
    """Un monde exécuté : performances, scores non calés, calage, fourchettes."""

    performances: tuple[Performance, ...]
    scores: dict[str, dict[ModelKind, OutingScores]]
    calibration: tuple[CalibratedPerformance, ...]
    bands: tuple[OutingBands, ...]

    def of(self, outing_id: str) -> OutingBands:
        """Les fourchettes d'une sortie."""
        return next(b for b in self.bands if b.outing_id == outing_id)


def world(
    specs: Sequence[BandSpec],
    *,
    unscored: frozenset[str] = frozenset(),
    window: tuple[date, date] = WINDOW,
) -> BandWorld:
    """Les performances (une par jour), les scores des sorties scorées, le calage de
    chaque performance et les fourchettes du monde."""
    from fixtures.calibration import WorldSpec

    performances = world_performances(
        WorldSpec(tuple(s.outing for s in specs), unscored, ())
    )
    scores = {
        s.outing_id: outing_scores(s) for s in specs if s.outing_id not in unscored
    }
    calibration = calibrate_performances(performances, scores)
    bands = evaluation_bands(performances, scores, calibration, window)
    return BandWorld(performances, scores, calibration, bands)
