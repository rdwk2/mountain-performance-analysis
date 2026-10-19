"""Les valeurs du rapport D15 de ``just backtest`` (M4b-5, M4c-2) : agrégats des cinq
modèles, ensemble commun, référence D8 à côté des modèles, sous-classes de descente,
géométrie, provenance ; dérive (M4d-1) ; fourchettes (M4d-2).

Protocole : ``docs/decisions/0010`` D15 (et ses précisions de M4b-5 et M4c-2), D3,
D5.4, D6, D7, D8, D9. Fonctions pures sur les objets d'une exécution : aucune lecture,
aucune écriture — la mise en forme est dans ``cli.py``.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from mountain_perf.backtest.calendar import available_at_origin, civil_date
from mountain_perf.backtest.drift import outing_drift
from mountain_perf.backtest.execution import BacktestEvaluation, BacktestRun, OutingRun
from mountain_perf.backtest.metrics import (
    is_invalid_model_output,
    is_underrepresented,
    support_metrics,
)
from mountain_perf.backtest.scoring import report_clocks
from mountain_perf.backtest.segments import REGIME_GRADE_THRESHOLD, fine_overlaps
from mountain_perf.schemas import (
    CALIBRATED_MODELS,
    CLOCKS,
    AdmittedSegment,
    Availability,
    CalibratedOutingScores,
    CalibrationPopulation,
    Clock,
    ClockScores,
    ConfigurationOutcome,
    DataSet,
    MatchResult,
    MetricValue,
    ModelBand,
    ModelKind,
    OutingBands,
    OutingDrift,
    OutingObservation,
    OutingScores,
    ParameterSpec,
    PerformanceComparison,
    RegimeClass,
    RepeatabilityReference,
    RouteProfile,
    Scenario,
    ScenarioScores,
    SensitivityMetric,
    Unavailability,
)

REPORT_PARAMETER_SPECS = (
    ParameterSpec(
        "descent_subclass_threshold",
        None,
        0.80,
        0.60,
        1.0,
        "Fraction de sa longueur à partir de laquelle un segment de descente est "
        "roulant ou raide (diagnostic de 0010 D6).",
    ),
)
"""Le seuil des sous-classes de descente (précision de D6, M4b-5 ; décision Q5) :
0,80 par défaut, la règle des segments purs, réglable dans ``[0,60 ; 1]``. Publié par
la synthèse et le rapport, pas déclaré au registre : aucun score n'en dépend."""

STEEP_DESCENT_GRADE = -0.15
"""La pente sous laquelle une descente est raide (``0010`` D6) : roulante
``−0,15 <= g < −0,05``, raide ``g < −0,15``."""


class DescentSubclass(StrEnum):
    """Sous-classe d'un segment de classe descente (``0010`` D6 et sa précision de
    M4b-5) : roulante, raide, ou non départagée (comptée, jamais scorée)."""

    ROLLING = "rolling"
    STEEP = "steep"
    UNDECIDED = "undecided"


class ClockRole(StrEnum):
    """Le rôle d'une horloge du rapport (``0010`` D5.4) : l'écoulé, ``M`` sous
    ``θ_bas``, ``M + U`` sous ``θ_haut`` de chaque performance."""

    ELAPSED = "elapsed"
    LOW = "low"
    HIGH = "high"


class ReportMetric(StrEnum):
    """Les métriques agrégées du rapport (précision de D15, M4b-5) : biais signés
    (``L``, ``E_R − L``) et valeurs absolues."""

    LEVEL = "level"
    ABS_LEVEL = "abs_level"
    DISPERSION = "dispersion"
    WITHIN = "within"
    BETWEEN = "between"
    COMPENSATION = "compensation"
    SHAPE = "shape"
    ABS_CLASS_LEVEL = "abs_class_level"
    CLASS_DISPERSION = "class_dispersion"
    MAX_ABS_PASSAGE_ERROR = "max_abs_passage_error_s"
    USAGE_TARGET = "q_usage"


SUPPORT_METRICS = (
    ReportMetric.LEVEL,
    ReportMetric.ABS_LEVEL,
    ReportMetric.DISPERSION,
    ReportMetric.WITHIN,
    ReportMetric.BETWEEN,
    ReportMetric.COMPENSATION,
)
"""Les métriques du support : ``L``, ``|L|``, ``A``, ``W``, ``B``, ``C_comp``."""

CLASS_METRICS = (
    ReportMetric.SHAPE,
    ReportMetric.ABS_CLASS_LEVEL,
    ReportMetric.CLASS_DISPERSION,
)
"""Les métriques d'une classe : ``E_R − L``, ``|E_R|``, ``D_R``."""

USAGE_METRICS = (ReportMetric.MAX_ABS_PASSAGE_ERROR, ReportMetric.USAGE_TARGET)
"""Les métriques de l'usage seul : ``max |C_k|`` et ``q_usage``."""

UNDERREPRESENTED = "underrepresented"
"""Motif d'une valeur de classe trop peu représentée (``0010`` D7.5)."""

NOT_SCORED = "not_scored"
"""Motif d'une performance dont la sortie n'est pas scorée."""

NO_REFERENCE = "no_reference"
"""Motif de l'usage d'une sortie sans référence (``0010`` D3)."""

SINGLE_RESIDUAL = "single_residual"
"""Motif de la couverture d'une fourchette d'un seul résidu : plage ponctuelle, aucune
couverture revendiquée (``0010`` D11)."""

MISSING_ORDER = (
    *(unavailability.value for unavailability in Unavailability),
    UNDERREPRESENTED,
    NOT_SCORED,
    NO_REFERENCE,
    SINGLE_RESIDUAL,
)
"""L'ordre des motifs d'une valeur manquante : ceux de ``Unavailability`` (D0), dans
leur ordre, puis ceux du rapport."""

REPORT_MODELS: tuple[ModelKind, ...] = (ModelKind.V0_RAW, *CALIBRATED_MODELS)
"""Les cinq modèles du rapport, dans l'ordre de ``0010`` D9.1 (précision de D15,
M4c-2)."""

_ROLE_INDEX = {ClockRole.ELAPSED: 0, ClockRole.LOW: 1, ClockRole.HIGH: 2}
_INSUFFICIENT = Unavailability.INSUFFICIENT_SUPPORT


# ---------------------------------------------------------------------------
# Agrégats (précision de D15, M4b-5 ; décision Q3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Aggregate:
    """Un agrégat : la moyenne des nombres (``None`` sans nombre), leur nombre, et
    les valeurs manquantes comptées par motif, dans l'ordre de ``MISSING_ORDER``."""

    value: float | None
    count: int
    missing: tuple[tuple[str, int], ...]


def aggregate(values: Sequence[float | str]) -> Aggregate:
    """La moyenne arithmétique d'une métrique sur son propre effectif (précision de
    D15, M4b-5) : un texte est le motif d'une valeur manquante ; ``value`` =
    ``fsum`` des nombres sur leur nombre ; ``missing`` = ``(motif, n)`` des motifs
    présents, dans l'ordre de ``MISSING_ORDER``. Un motif inconnu : ``ValueError``."""
    numbers = [value for value in values if not isinstance(value, str)]
    motifs = Counter(value for value in values if isinstance(value, str))
    unknown = sorted(set(motifs) - set(MISSING_ORDER))
    if unknown:
        raise ValueError(f"aggregate : motifs inconnus {unknown}")
    mean = math.fsum(numbers) / len(numbers) if numbers else None
    missing = tuple((motif, motifs[motif]) for motif in MISSING_ORDER if motifs[motif])
    return Aggregate(mean, len(numbers), missing)


@dataclass(frozen=True)
class ScoredPerformance:
    """Une performance déclarée vue par le rapport : son jour, les jeux de ses
    sorties, les parcours de ses sorties de répétabilité, les scores de sa sortie et
    ses horloges du rapport — ou le motif qui les remplace —, puis (M4c-2) les scores
    calés de sa sortie, un couple par modèle de ``CALIBRATED_MODELS`` dans l'ordre
    (vides sans scores), et sa population ``C_j`` ; enfin (M4d-2) les fourchettes de sa
    sortie, si elle en a."""

    civil_date: date
    datasets: tuple[DataSet, ...]
    routes: tuple[str, ...]
    scores: OutingScores | None
    clocks: tuple[Clock, ...]
    missing: str | None
    calibrated: tuple[tuple[ModelKind, CalibratedOutingScores], ...] = ()
    population: CalibrationPopulation | None = None
    bands: OutingBands | None = None


def scored_performances(
    run: BacktestRun | BacktestEvaluation,
) -> tuple[ScoredPerformance, ...]:
    """Une entrée par performance déclarée, dans l'ordre (``0010`` D0, D5.4, D15) :
    les jeux de **ses sorties** (une performance compte dans chacun), dans l'ordre de
    ``DataSet`` ; les parcours de ses sorties de répétabilité, triés ; une
    performance de plusieurs sorties, au motif ``jour multi-sorties`` ; une sortie non
    scorée, au motif ``not_scored`` ; sinon ses scores, ``report_clocks`` et ses scores
    calés (D9.2, M4c-2). La population ``C_j`` de chaque performance, toujours."""
    scored = {outing.outing.outing_id: outing for outing in run.outings}
    populations = {
        performance.population.civil_date: performance.population
        for performance in run.calibration
    }
    calibrated = {
        (entry.outing_id, entry.control.model): entry
        for performance in run.calibration
        for entry in performance.outings
    }
    bands = {entry.outing_id: entry for entry in run.bands}
    entries: list[ScoredPerformance] = []
    for declared in run.preparation.declaration.performances:
        performance = declared.performance
        present = {o.dataset for o in performance.outings}
        datasets = tuple(dataset for dataset in DataSet if dataset in present)
        routes = tuple(
            sorted(
                {
                    o.route_id
                    for o in performance.outings
                    if o.dataset is DataSet.REPEATABILITY and o.route_id is not None
                }
            )
        )
        day = performance.civil_date
        population = populations[day]
        if performance.is_multi_outing:
            missing = Unavailability.MULTI_OUTING_DAY.value
            entries.append(
                ScoredPerformance(
                    day, datasets, routes, None, (), missing, population=population
                )
            )
            continue
        outing_id = performance.outings[0].outing_id
        outing = scored.get(outing_id)
        if outing is None:
            entries.append(
                ScoredPerformance(
                    day, datasets, routes, None, (), NOT_SCORED, population=population
                )
            )
            continue
        clocks = report_clocks(outing.match)
        models = tuple(
            (model, calibrated[(outing_id, model)]) for model in CALIBRATED_MODELS
        )
        entries.append(
            ScoredPerformance(
                day,
                datasets,
                routes,
                outing.scores,
                clocks,
                None,
                models,
                population,
                bands.get(outing_id),
            )
        )
    return tuple(entries)


def _keys(scenario: Scenario) -> list[tuple[ReportMetric, RegimeClass | None]]:
    keys: list[tuple[ReportMetric, RegimeClass | None]] = [
        (metric, None) for metric in SUPPORT_METRICS
    ]
    keys += [(metric, regime) for regime in RegimeClass for metric in CLASS_METRICS]
    if scenario is Scenario.USAGE:
        keys += [(metric, None) for metric in USAGE_METRICS]
    return keys


def _number(metric: MetricValue, absolute: bool = False) -> float | str:
    """La valeur d'une ``MetricValue``, ou la valeur de son motif."""
    if metric.value is None:
        assert metric.unavailability is not None  # contrat de MetricValue
        return metric.unavailability.value
    return abs(metric.value) if absolute else metric.value


def role_clock_scores(
    entry: ScoredPerformance, scenario: Scenario, role: ClockRole, model: ModelKind
) -> ClockScores | str:
    """Les scores d'un modèle sous un scénario et le rôle d'une horloge, ou le motif
    qui les remplace (précisions de D15, M4b-5 et M4c-2 ; D5.4, D9.2), **dans cet
    ordre** : le motif de la performance ; son scénario absent, ``no_reference`` ; le
    rôle au-delà des horloges du rapport, ``insufficient_support`` ; pour un modèle
    calé, une horloge non calée, la valeur de son statut (``not_calibrated``,
    ``model_error``). L'horloge du rôle se lit parmi les onze (``CLOCKS``) ; un modèle
    calé se lit sur ses scores calés, v0 brut sur les siens."""
    scores = entry.scores
    if entry.missing is not None or scores is None:
        return entry.missing if entry.missing is not None else NOT_SCORED
    index = _ROLE_INDEX[role]
    usage = scenario is Scenario.USAGE
    if model is ModelKind.V0_RAW:
        raw = scores.usage if usage else scores.control
        if raw is None:
            return NO_REFERENCE
        if index >= len(entry.clocks):
            return _INSUFFICIENT.value
        return raw.clocks[CLOCKS.index(entry.clocks[index])]
    scaled = dict(entry.calibrated)[model]
    calibrated = scaled.usage if usage else scaled.control
    if calibrated is None:
        return NO_REFERENCE
    if index >= len(entry.clocks):
        return _INSUFFICIENT.value
    clock = calibrated.clocks[CLOCKS.index(entry.clocks[index])]
    if clock.scores is None:
        status = clock.calibration.unavailability
        assert status is not None  # contrat de CalibratedClockScores
        return status.value
    return clock.scores


def performance_values(
    entry: ScoredPerformance,
    scenario: Scenario,
    role: ClockRole,
    model: ModelKind = ModelKind.V0_RAW,
) -> dict[tuple[ReportMetric, RegimeClass | None], float | str]:
    """Les valeurs d'un modèle pour une performance sous un scénario et le rôle d'une
    horloge (précisions de D15, M4b-5 et M4c-2 ; D5.4, D7.5) — les six métriques du
    support, les trois de chaque classe, puis, en usage seulement, ``max |C_k|`` et
    ``q_usage``. Un motif partout, s'il y en a un : celui de ``role_clock_scores``.
    Une classe trop peu représentée donne ``underrepresented`` à ses valeurs
    disponibles."""
    keys = _keys(scenario)
    clock_scores = role_clock_scores(entry, scenario, role, model)
    if isinstance(clock_scores, str):
        return dict.fromkeys(keys, clock_scores)
    support = clock_scores.support
    values: dict[tuple[ReportMetric, RegimeClass | None], float | str] = {
        (ReportMetric.LEVEL, None): _number(support.log_ratio),
        (ReportMetric.ABS_LEVEL, None): _number(support.log_ratio, absolute=True),
        (ReportMetric.DISPERSION, None): _number(support.dispersion),
        (ReportMetric.WITHIN, None): _number(support.within),
        (ReportMetric.BETWEEN, None): _number(support.between),
        (ReportMetric.COMPENSATION, None): _number(support.compensation),
    }
    for regime, metrics in zip(RegimeClass, support.classes, strict=True):
        for metric, value in (
            (ReportMetric.SHAPE, _number(metrics.shape)),
            (ReportMetric.ABS_CLASS_LEVEL, _number(metrics.log_ratio, absolute=True)),
            (ReportMetric.CLASS_DISPERSION, _number(metrics.dispersion)),
        ):
            available = not isinstance(value, str)
            under = available and metrics.underrepresented
            values[(metric, regime)] = UNDERREPRESENTED if under else value
    if scenario is Scenario.USAGE:
        errors, target = clock_scores.passage_errors, clock_scores.usage_target
        values[(ReportMetric.MAX_ABS_PASSAGE_ERROR, None)] = (
            _INSUFFICIENT.value if errors is None else _number(errors.max_abs_error_s)
        )
        values[(ReportMetric.USAGE_TARGET, None)] = (
            _INSUFFICIENT.value if target is None else _number(target.q_usage)
        )
    return {key: values[key] for key in keys}


@dataclass(frozen=True)
class AggregateRow:
    """Une ligne d'une table d'agrégats : la métrique, sa classe (``None`` hors
    classe), un agrégat par jeu dans l'ordre de ``DataSet``."""

    metric: ReportMetric
    regime_class: RegimeClass | None
    by_set: tuple[Aggregate, ...]


def aggregate_table(
    entries: Sequence[ScoredPerformance],
    scenario: Scenario,
    role: ClockRole,
    model: ModelKind = ModelKind.V0_RAW,
) -> tuple[AggregateRow, ...]:
    """La table d'agrégats d'un modèle (précisions de D15, M4b-5 et M4c-2 ; décision
    Q3) : une ligne par clé de ``performance_values``, un agrégat par jeu, à poids égal
    par performance, jamais mélangés — une performance compte dans chacun des jeux de
    ses sorties."""
    values = [performance_values(entry, scenario, role, model) for entry in entries]
    return tuple(
        AggregateRow(
            metric,
            regime,
            tuple(
                aggregate(
                    [
                        value[(metric, regime)]
                        for entry, value in zip(entries, values, strict=True)
                        if dataset in entry.datasets
                    ]
                )
                for dataset in DataSet
            ),
        )
        for metric, regime in _keys(scenario)
    )


@dataclass(frozen=True)
class CommonRow:
    """Une métrique sur l'**ensemble commun** (précision de D15, M4c-2 ; décision
    Q5) : la métrique, sa classe (``None`` hors classe), et par jeu, dans l'ordre de
    ``DataSet``, un agrégat par modèle de ``REPORT_MODELS``."""

    metric: ReportMetric
    regime_class: RegimeClass | None
    by_set: tuple[tuple[Aggregate, ...], ...]


def common_row(
    entries: Sequence[ScoredPerformance],
    scenario: Scenario,
    role: ClockRole,
    metric: ReportMetric,
    regime: RegimeClass | None = None,
) -> CommonRow:
    """Une métrique sur l'ensemble commun de chaque jeu (précision de D15, M4c-2 ;
    décision Q5) : les performances de ce jeu où **chacun des cinq modèles** a un
    nombre pour ``(metric, regime)`` ; puis, pour chaque modèle, l'agrégat de ses
    valeurs sur elles — même effectif pour les cinq, aucun motif compté. Un jeu sans
    telle performance : cinq agrégats vides."""
    key = (metric, regime)
    values = [
        [
            performance_values(entry, scenario, role, model)[key]
            for model in REPORT_MODELS
        ]
        for entry in entries
    ]
    by_set: list[tuple[Aggregate, ...]] = []
    for dataset in DataSet:
        common = [
            row
            for entry, row in zip(entries, values, strict=True)
            if dataset in entry.datasets
            and not any(isinstance(value, str) for value in row)
        ]
        by_set.append(
            tuple(
                aggregate([row[m] for row in common]) for m in range(len(REPORT_MODELS))
            )
        )
    return CommonRow(metric, regime, tuple(by_set))


# ---------------------------------------------------------------------------
# Référence D8 à côté des modèles (décision Q4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RouteComparison:
    """Un parcours de répétabilité : ses jours, « un seul contraste », et par ligne
    la métrique, la classe, le ``F`` du parcours sous l'écoulé et l'agrégat en usage
    sous l'écoulé sur ses jours de chaque modèle de ``REPORT_MODELS`` (v0 brut en
    premier ; M4c-2)."""

    route_id: str
    days: int
    single_contrast: bool
    rows: tuple[
        tuple[ReportMetric, RegimeClass | None, MetricValue, tuple[Aggregate, ...]],
        ...,
    ]


def route_comparisons(
    entries: Sequence[ScoredPerformance],
    references: Sequence[tuple[str, RepeatabilityReference]],
) -> tuple[RouteComparison, ...]:
    """Pour chaque parcours à référence, dans l'ordre (précisions de D15, M4b-5 et
    M4c-2 ; ``0010`` D8) : sous l'écoulé, ``F_|L|`` à côté de l'agrégat de ``|L|`` en
    usage de chaque modèle sur les performances de ce parcours, puis par classe
    ``F_|E_R|`` et ``F_D_R`` à côté de ``|E_R|`` et ``D_R`` — supports différents :
    ``F`` pli par pli, les modèles sur le support admis de chaque jour."""
    comparisons: list[RouteComparison] = []
    for route_id, reference in references:
        elapsed = reference.clocks[0]
        values = {
            model: [
                performance_values(entry, Scenario.USAGE, ClockRole.ELAPSED, model)
                for entry in entries
                if route_id in entry.routes
            ]
            for model in REPORT_MODELS
        }
        pairs: list[tuple[ReportMetric, RegimeClass | None, MetricValue]] = [
            (ReportMetric.ABS_LEVEL, None, elapsed.level)
        ]
        for r, regime in enumerate(RegimeClass):
            pairs.append((ReportMetric.ABS_CLASS_LEVEL, regime, elapsed.log_ratios[r]))
            pairs.append(
                (ReportMetric.CLASS_DISPERSION, regime, elapsed.dispersions[r])
            )
        rows = tuple(
            (
                metric,
                regime,
                f,
                tuple(
                    aggregate([value[(metric, regime)] for value in values[model]])
                    for model in REPORT_MODELS
                ),
            )
            for metric, regime, f in pairs
        )
        comparisons.append(
            RouteComparison(
                route_id, len(reference.days), reference.single_contrast, rows
            )
        )
    return tuple(comparisons)


# ---------------------------------------------------------------------------
# Sous-classes de descente (D6 et sa précision de M4b-5 ; décision Q5)
# ---------------------------------------------------------------------------


def descent_fractions(
    profile: RouteProfile, segments: Sequence[AdmittedSegment]
) -> tuple[tuple[float, float], ...]:
    """Les fractions roulante et raide de chaque segment admis, sur ses bornes
    effectives et la grille fine du profil (``0010`` D6) : longueurs de pente
    ``−0,15 <= g < −0,05``, puis ``g < −0,15``, sommées par ``fsum``, sur la longueur
    du segment."""
    fractions: list[tuple[float, float]] = []
    for segment in segments:
        overlaps = fine_overlaps(profile, segment.start_m, segment.end_m)
        rolling = math.fsum(
            overlap.length_m
            for overlap in overlaps
            if STEEP_DESCENT_GRADE <= overlap.grade < -REGIME_GRADE_THRESHOLD
        )
        steep = math.fsum(
            overlap.length_m
            for overlap in overlaps
            if overlap.grade < STEEP_DESCENT_GRADE
        )
        length_m = segment.end_m - segment.start_m
        fractions.append((rolling / length_m, steep / length_m))
    return tuple(fractions)


def descent_subclasses(
    segments: Sequence[AdmittedSegment],
    fractions: Sequence[tuple[float, float]],
    threshold: float,
) -> tuple[DescentSubclass | None, ...]:
    """La sous-classe de chaque segment (précision de D6, M4b-5) : aucune hors de la
    classe descente ; roulante si sa fraction roulante **atteint** le seuil, sinon
    raide si sa fraction raide l'atteint, sinon non départagée."""
    subclasses: list[DescentSubclass | None] = []
    for segment, (rolling, steep) in zip(segments, fractions, strict=True):
        if segment.regime_class is not RegimeClass.DESCENT:
            subclasses.append(None)
        elif rolling >= threshold:
            subclasses.append(DescentSubclass.ROLLING)
        elif steep >= threshold:
            subclasses.append(DescentSubclass.STEEP)
        else:
            subclasses.append(DescentSubclass.UNDECIDED)
    return tuple(subclasses)


@dataclass(frozen=True)
class SubclassMetrics:
    """Les métriques d'une sous-classe sous une horloge : ses segments, « trop peu
    représentée », ``E_R``, ``D_R`` et ``E_R − L`` contre le ``L`` de la sortie."""

    subclass: DescentSubclass
    segment_count: int
    underrepresented: bool
    log_ratio: MetricValue
    dispersion: MetricValue
    shape: MetricValue


def subclass_metrics(
    observation: OutingObservation,
    scenario: ScenarioScores,
    subclasses: Sequence[DescentSubclass | None],
    clock: Clock,
) -> tuple[SubclassMetrics, SubclassMetrics]:
    """Les métriques des descentes roulantes, puis raides, sous ``clock`` (précision
    de D6, M4b-5 ; D7.2, D7.5) : ``support_metrics`` sur les prévisions du scénario et
    les temps sous l'horloge des segments de la sous-classe, classés descente — son
    ``L`` est l'``E_R``, sa dispersion le ``D_R`` de la sous-classe ; ``E_R − L``
    contre le ``L`` du scénario sous la même horloge (``E_R`` absent : son motif ;
    ``L`` absent : le motif de ``L``) ; trop peu représentée sous 3 segments."""
    h = CLOCKS.index(clock)
    level = scenario.clocks[h].support.log_ratio
    forecast = scenario.forecast.segment_s
    result: list[SubclassMetrics] = []
    for subclass in (DescentSubclass.ROLLING, DescentSubclass.STEEP):
        indices = [i for i, value in enumerate(subclasses) if value is subclass]
        metrics = support_metrics(
            [forecast[i] for i in indices],
            [observation.segments[i].times_s[h] for i in indices],
            [RegimeClass.DESCENT] * len(indices),
        )
        e_r = metrics.log_ratio
        if e_r.value is None:
            shape = e_r
        elif level.value is None:
            shape = MetricValue(None, level.unavailability, e_r.count)
        else:
            shape = MetricValue(e_r.value - level.value, None, e_r.count)
        result.append(
            SubclassMetrics(
                subclass,
                len(indices),
                is_underrepresented(len(indices)),
                e_r,
                metrics.dispersion,
                shape,
            )
        )
    return result[0], result[1]


# ---------------------------------------------------------------------------
# Géométrie (D3 et sa précision de M4b-5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GeometryDiagnostic:
    """Le diagnostic de géométrie d'une sortie à référence : ``G`` sur son support
    admis, puis ``G_R`` par classe, dans l'ordre de ``RegimeClass``."""

    total: MetricValue
    classes: tuple[MetricValue, ...]


def _log_sum_ratio(
    usage: Sequence[float | None], control: Sequence[float | None]
) -> MetricValue:
    if not usage:
        return MetricValue(None, _INSUFFICIENT, 0)
    if any(is_invalid_model_output(value) for value in (*usage, *control)):
        return MetricValue(None, Unavailability.MODEL_ERROR, len(usage))
    numerator = math.fsum(value for value in usage if value is not None)
    denominator = math.fsum(value for value in control if value is not None)
    return MetricValue(math.log(numerator / denominator), None, len(usage))


def geometry_diagnostic(scores: OutingScores) -> GeometryDiagnostic | None:
    """``G = ln(ΣP_usage / ΣP_contrôle)`` sur le support admis, puis par classe
    (précision de D3, M4b-5) : il ne dépend pas des temps observés ; ``None`` sans
    usage ; une prévision absente, non finie, nulle ou négative : ``erreur du
    modèle`` ; aucun segment : ``support insuffisant``. Diagnostic, ni cible ni
    garde-fou."""
    if scores.usage is None:
        return None
    usage = scores.usage.forecast.segment_s
    control = scores.control.forecast.segment_s
    segments = scores.observation.segments
    total = _log_sum_ratio(usage, control)
    classes = []
    for regime in RegimeClass:
        indices = [i for i, s in enumerate(segments) if s.regime_class is regime]
        classes.append(
            _log_sum_ratio([usage[i] for i in indices], [control[i] for i in indices])
        )
    return GeometryDiagnostic(total, tuple(classes))


# ---------------------------------------------------------------------------
# Provenance et horloges (D15, D2.5, D5.4)
# ---------------------------------------------------------------------------


def curve_age_days(available_at: datetime, day: date) -> int:
    """L'âge de la courbe au jour ``day``, en jours depuis le jour civil **à Paris**
    de son instant de disponibilité (``0010`` D15) ; négatif si elle est
    postérieure."""
    return (day - civil_date(available_at)).days


def origins_before_curve(available_at: datetime, origins: Sequence[datetime]) -> int:
    """Le nombre d'origines ``o_j`` auxquelles la courbe n'est pas disponible
    (``0010`` D15, D2.5 : disponible si **strictement** antérieure)."""
    return sum(not available_at_origin(available_at, o) for o in origins)


def third_clock_is_elapsed(match: MatchResult) -> bool:
    """``(M+U) θ_haut`` égale l'écoulé (précision de D15, M4b-5 ; décision Q13) : un
    ``θ_haut`` existe et aucun arrêt n'est confirmé sur le support admis sous lui."""
    high = match.high_convention_index
    return high is not None and match.admitted_totals[high].stopped_s == 0.0


# ---------------------------------------------------------------------------
# Diagnostic de longue course (D12, M4d-1)
# ---------------------------------------------------------------------------


def outing_drift_report(
    run: BacktestRun | BacktestEvaluation, outing: OutingRun
) -> OutingDrift | None:
    """La dérive d'une sortie scorée de l'exécution (``0010`` D12 ; M4d-1) : sous les
    horloges de son rapport, avec le calage de sa performance et la courbe de
    l'exécution ; ``None`` sans usage."""
    outing_id = outing.outing.outing_id
    performance = next(
        p for p in run.preparation.performances if outing.outing in p.outings
    )
    calibrated = next(
        p for p in run.calibration if any(e.outing_id == outing_id for e in p.outings)
    )
    return outing_drift(
        outing.scores,
        outing.passages,
        outing.profile,
        report_clocks(outing.match),
        calibrated,
        run.preparation.curve.curve,
        multi_outing=performance.is_multi_outing,
        outing_id=outing_id,
    )


# ---------------------------------------------------------------------------
# Fourchettes (D11, M4d-2)
# ---------------------------------------------------------------------------


class BandMetric(StrEnum):
    """Les métriques agrégées des fourchettes (précision de D11, M4d-2) : ``IS_j``,
    ``IS_j,norm``, la couverture, et le ``q_usage`` et le ``max |C_k|`` de la prévision
    médiane."""

    INTERVAL_SCORE = "interval_score_s"
    NORMALISED_SCORE = "normalised_score"
    COVERAGE = "coverage"
    MEDIAN_USAGE_TARGET = "median_q_usage"
    MEDIAN_MAX_ABS_ERROR = "median_max_abs_passage_error_s"


def _band_value(band: ModelBand, metric: BandMetric) -> float | str:
    """La valeur d'une métrique d'une fourchette, ou son motif : le statut de la
    fourchette ; ``single_residual`` pour la couverture d'un seul résidu ; le motif de
    la valeur."""
    if band.unavailability is not None:
        return band.unavailability.value
    value = {
        BandMetric.INTERVAL_SCORE: band.interval_score_s,
        BandMetric.NORMALISED_SCORE: band.normalised_score,
        BandMetric.COVERAGE: band.coverage,
        BandMetric.MEDIAN_USAGE_TARGET: band.median_usage_target,
        BandMetric.MEDIAN_MAX_ABS_ERROR: band.median_max_abs_error_s,
    }[metric]
    if value is None:
        return SINGLE_RESIDUAL
    return _number(value)


def band_values(
    entry: ScoredPerformance, model: ModelKind
) -> dict[BandMetric, float | str]:
    """Les métriques des fourchettes d'un modèle pour une performance (précision de
    D11, M4d-2), ou le motif qui les remplace, dans cet ordre : le motif de la
    performance (``jour multi-sorties`` : hors des agrégats, D0) ; sans usage,
    ``no_reference`` ; puis ceux de la fourchette (``_band_value``)."""
    if entry.missing is not None or entry.scores is None:
        motif = entry.missing if entry.missing is not None else NOT_SCORED
        return dict.fromkeys(BandMetric, motif)
    if entry.bands is None:
        return dict.fromkeys(BandMetric, NO_REFERENCE)
    band = entry.bands.models[REPORT_MODELS.index(model)]
    return {metric: _band_value(band, metric) for metric in BandMetric}


@dataclass(frozen=True)
class BandRow:
    """Une ligne de la table des fourchettes : la métrique, et par jeu, dans l'ordre de
    ``DataSet``, un agrégat par modèle de ``REPORT_MODELS``."""

    metric: BandMetric
    by_set: tuple[tuple[Aggregate, ...], ...]


def band_table(entries: Sequence[ScoredPerformance]) -> tuple[BandRow, ...]:
    """La table des fourchettes (précision de D11, M4d-2 ; D15) : par métrique, par jeu
    et par modèle, la moyenne à poids égal par performance sur son propre effectif,
    les manquants comptés par motif."""
    values = {
        model: [band_values(e, model) for e in entries] for model in REPORT_MODELS
    }
    return tuple(
        BandRow(
            metric,
            tuple(
                tuple(
                    aggregate(
                        [
                            row[metric]
                            for entry, row in zip(entries, values[model], strict=True)
                            if dataset in entry.datasets
                        ]
                    )
                    for model in REPORT_MODELS
                )
                for dataset in DataSet
            ),
        )
        for metric in BandMetric
    )


def band_common_row(
    entries: Sequence[ScoredPerformance], metric: BandMetric
) -> tuple[tuple[Aggregate, ...], ...]:
    """Une métrique des fourchettes sur l'ensemble commun de chaque jeu : les
    performances de ce jeu où chacun des cinq modèles a un nombre ; par jeu, un agrégat
    par modèle, même effectif pour les cinq."""
    rows = [[band_values(e, model)[metric] for model in REPORT_MODELS] for e in entries]
    by_set: list[tuple[Aggregate, ...]] = []
    for dataset in DataSet:
        common = [
            row
            for entry, row in zip(entries, rows, strict=True)
            if dataset in entry.datasets
            and not any(isinstance(value, str) for value in row)
        ]
        by_set.append(
            tuple(
                aggregate([row[m] for row in common]) for m in range(len(REPORT_MODELS))
            )
        )
    return tuple(by_set)


def band_window_counts(bands: OutingBands, band: ModelBand) -> tuple[int, int]:
    """Les résidus disponibles d'un modèle dans et hors de la fenêtre de la courbe
    (précision de D11 : le jour du membre, bornes comprises) : ``(dans, hors)``, de
    somme ``n``."""
    inside = sum(
        residual.available and member.in_window
        for residual, member in zip(band.residuals, bands.members, strict=True)
    )
    return inside, band.count - inside


def outing_bands_report(
    run: BacktestRun | BacktestEvaluation, outing: OutingRun
) -> OutingBands | None:
    """Les fourchettes d'une sortie scorée de l'exécution (``0010`` D11 ; M4d-2) ;
    ``None`` sans usage."""
    outing_id = outing.outing.outing_id
    return next((b for b in run.bands if b.outing_id == outing_id), None)


# ---------------------------------------------------------------------------
# Sensibilité (D13, M4d-3)
# ---------------------------------------------------------------------------


class SensitivityRowKind(StrEnum):
    """Les lignes de la table d'une configuration de la sensibilité (précision de D15,
    M4d-3) : celles de la synthèse de ``just backtest`` (``L``, ``|L|``, ``max |C_k|``,
    ``q_usage``), sous l'horloge de la configuration, puis ``|L|`` sur l'ensemble
    commun des modèles."""

    LEVEL = "L"
    ABS_LEVEL = "|L|"
    MAX_ABS_PASSAGE_ERROR = "max |C_k|"
    USAGE_TARGET = "q_usage"
    COMMON_ABS_LEVEL = "|L| commun"


@dataclass(frozen=True)
class SensitivityRow:
    """Une ligne de la table d'une configuration : sa nature, et par jeu, dans l'ordre
    de ``DataSet``, un agrégat par modèle comparé, dans l'ordre des modèles."""

    kind: SensitivityRowKind
    by_set: tuple[tuple[Aggregate, ...], ...]


_ROW_METRICS = {
    SensitivityRowKind.LEVEL: SensitivityMetric.LEVEL,
    SensitivityRowKind.ABS_LEVEL: SensitivityMetric.LEVEL,
    SensitivityRowKind.MAX_ABS_PASSAGE_ERROR: SensitivityMetric.MAX_ABS_PASSAGE_ERROR,
    SensitivityRowKind.USAGE_TARGET: SensitivityMetric.USAGE,
}


def _sensitivity_number(
    comparison: PerformanceComparison, model: ModelKind, kind: SensitivityRowKind
) -> float | str:
    """La valeur d'une ligne pour un modèle et une performance, sous la configuration,
    ou son motif : celui de la performance, sinon celui de la valeur."""
    if comparison.motif is not None:
        return comparison.motif.value
    metric = _ROW_METRICS[kind]
    (value,) = [
        c.value for c in comparison.metrics if c.model is model and c.metric is metric
    ]
    return _number(value, absolute=kind is SensitivityRowKind.ABS_LEVEL)


def sensitivity_table(
    configuration: ConfigurationOutcome,
    datasets: Sequence[tuple[DataSet, ...]],
    models: Sequence[ModelKind],
) -> tuple[SensitivityRow, ...]:
    """La table d'une configuration de la sensibilité (précision de D15, M4d-3) : pour
    chaque ligne de ``SensitivityRowKind``, chaque jeu et chaque modèle, la moyenne à
    poids égal par performance sur son propre effectif, les manquants comptés par motif
    (``aggregate``) ; ``|L|`` commun : sur les performances où tous les modèles ont
    ``|L|``. ``datasets`` : les jeux de chaque performance, dans l'ordre de la
    configuration (une performance compte dans le jeu de chacune de ses sorties)."""
    rows: list[SensitivityRow] = []
    performances = configuration.performances
    for kind in SensitivityRowKind:
        by_set: list[tuple[Aggregate, ...]] = []
        for dataset in DataSet:
            members = [
                p
                for p, sets in zip(performances, datasets, strict=True)
                if dataset in sets
            ]
            if kind is SensitivityRowKind.COMMON_ABS_LEVEL:
                common = [
                    p
                    for p in members
                    if all(
                        not isinstance(
                            _sensitivity_number(p, m, SensitivityRowKind.ABS_LEVEL), str
                        )
                        for m in models
                    )
                ]
                by_set.append(
                    tuple(
                        aggregate(
                            [
                                _sensitivity_number(p, m, SensitivityRowKind.ABS_LEVEL)
                                for p in common
                            ]
                        )
                        for m in models
                    )
                )
                continue
            by_set.append(
                tuple(
                    aggregate([_sensitivity_number(p, m, kind) for p in members])
                    for m in models
                )
            )
        rows.append(SensitivityRow(kind, tuple(by_set)))
    return tuple(rows)


@dataclass(frozen=True)
class AxisCounts:
    """Les trois axes d'une configuration pour un modèle (précision de D13, M4d-3) : sur
    les comparaisons des performances sans motif, combien perdent ou gagnent leur
    valeur, combien changent de support, combien changent de valeur (écart non nul)."""

    model: ModelKind
    compared: int
    lost: int
    gained: int
    support: int
    value: int


def axis_counts(
    configuration: ConfigurationOutcome, models: Sequence[ModelKind]
) -> tuple[AxisCounts, ...]:
    """Les comptes des trois axes, par modèle, dans l'ordre de ``models`` (précision de
    D13, M4d-3)."""
    counts: list[AxisCounts] = []
    for model in models:
        comparisons = [
            c for p in configuration.performances for c in p.metrics if c.model is model
        ]
        counts.append(
            AxisCounts(
                model,
                len(comparisons),
                sum(c.availability is Availability.LOST for c in comparisons),
                sum(c.availability is Availability.GAINED for c in comparisons),
                sum(bool(c.support) for c in comparisons),
                sum(c.difference not in (None, 0.0) for c in comparisons),
            )
        )
    return tuple(counts)


def drift_under(
    evaluation: BacktestEvaluation, outing: OutingRun, clock: Clock
) -> OutingDrift | None:
    """La dérive d'une sortie scorée d'une paire de la sensibilité sous l'horloge de la
    configuration (précision de D13, M4d-3 ; ``0010`` D12), précédée de l'écoulé si
    elle en est une autre (le diagnostic tient l'écoulé en premier) ; ``None`` sans
    usage."""
    outing_id = outing.outing.outing_id
    performance = next(
        p for p in evaluation.preparation.performances if outing.outing in p.outings
    )
    calibrated = next(
        p
        for p in evaluation.calibration
        if any(e.outing_id == outing_id for e in p.outings)
    )
    return outing_drift(
        outing.scores,
        outing.passages,
        outing.profile,
        (CLOCKS[0],) if clock == CLOCKS[0] else (CLOCKS[0], clock),
        calibrated,
        evaluation.preparation.curve.curve,
        multi_outing=performance.is_multi_outing,
        outing_id=outing_id,
    )
