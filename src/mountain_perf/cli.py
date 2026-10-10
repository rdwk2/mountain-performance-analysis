"""Commandes mperf : lecture, appel de la bibliothèque et affichage.

Aucun calcul ici (règle 7 de ``CLAUDE.md``) : la commande lit des fichiers, appelle
``mountain_perf``, et met en forme. Si elle calculait quelque chose, c'est que ça
manquerait dans ``src/``.
"""

import argparse
import contextlib
import csv
import io
import math
import os
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import TextIO

import mountain_perf
from mountain_perf.backtest import (
    MATCHING_PARAMETER_SPECS,
    NO_REFERENCE,
    NOT_SCORED,
    PARIS,
    REPORT_MODELS,
    REPORT_PARAMETER_SPECS,
    UNDERREPRESENTED,
    Aggregate,
    AggregateRow,
    BacktestError,
    BacktestEvaluation,
    BacktestRun,
    ClockRole,
    DescentSubclass,
    ManifestError,
    OutingRun,
    ReferenceGeometry,
    ReportMetric,
    ScoredPerformance,
    TraceSeries,
    aggregate_table,
    build_series,
    civil_date,
    clock_partition,
    common_row,
    curve_age_days,
    descent_fractions,
    descent_subclasses,
    dplus_per_km,
    failure_reason,
    geometry_diagnostic,
    git_state,
    match_trace,
    observe_passages,
    origins_before_curve,
    prepare_backtest,
    reference_geometry,
    report_clocks,
    route_comparisons,
    run_backtest,
    scored_performances,
    stop_episodes,
    subclass_metrics,
    third_clock_is_elapsed,
    v0_scores,
)
from mountain_perf.backtest.registry import RegistryError, read_registry
from mountain_perf.config import ConfigError, data_dir
from mountain_perf.gpx import (
    PROFILE_PARAMETER_SPECS,
    GpxError,
    GpxReadResult,
    ProfileBuildResult,
    ProfileError,
    build_profile,
    build_profile_with_diagnostics,
    read_gpx,
)
from mountain_perf.gpx.trace_reader import TraceError, read_trace
from mountain_perf.model import (
    PROJECTION_PARAMETER_SPECS,
    CurveError,
    CurveReadResult,
    ProjectionDiagnostics,
    project_with_diagnostics,
    read_curve,
    route_endpoints,
)
from mountain_perf.schemas import (
    CALIBRATED_MODELS,
    CENTRAL_CONVENTION_INDEX,
    CLOCKS,
    AdmittedTotals,
    CalibratedOutingScores,
    CalibratedScenarioScores,
    CalibrationPopulation,
    Clock,
    ClockKind,
    ClockScores,
    ClockTotals,
    DataSet,
    EpisodeOutcome,
    LogRatioEnvelope,
    MatchResult,
    MetricValue,
    ModelCalibration,
    ModelKind,
    ObservedPoint,
    OutingLabel,
    OutingObservation,
    OutingScores,
    ParameterSet,
    PassageMatchResult,
    PassageRole,
    PassageStatus,
    PointStatus,
    PopulationExclusionReason,
    Projection,
    RecordedTrace,
    Regime,
    RegimeClass,
    RegistryEvent,
    RepeatabilityReference,
    RouteProfile,
    Scenario,
    ScenarioScores,
    ScorePointObservation,
    SegmentExclusion,
    StopEpisode,
    SupportMetrics,
    Unavailability,
)
from mountain_perf.units import format_duration
from mountain_perf.validation import ContractError

_PROFILE_OPTIONS = {
    "--step-m": "grid_step_m",
    "--smoothing-m": "smoothing_window_m",
    "--max-offset-m": "point_match_max_offset_m",
    "--min-separation-m": "point_match_min_separation_m",
}

_PROJECTION_OPTIONS = {
    "--effort": "effort",
    "--min-support-min": "curve_min_support_min",
}

_MATCHING_OPTIONS = {
    "--delta-m": "score_step_m",
    "--eps-m": "lateral_tolerance_m",
}

POINT_STATUS_LABELS: Mapping[PointStatus, str] = {
    PointStatus.FOUND: "trouvé",
    PointStatus.ANCHORED: "ancré",
    PointStatus.AMBIGUOUS: "ambigu",
    PointStatus.ABSENT: "absent",
    PointStatus.OUT_OF_TOLERANCE: "hors ε",
    PointStatus.UNDEFINED_TANGENT: "tangente indéfinie",
}
"""Libellés d'affichage des statuts de point, ceux de ``0010`` D4.11."""

SEGMENT_EXCLUSION_LABELS: Mapping[SegmentExclusion, str] = {
    SegmentExclusion.UNOBSERVED_BOUND: "borne non observée",
    SegmentExclusion.GAP: "trou",
    SegmentExclusion.LENGTH_RATIO: "rapport de longueur",
    SegmentExclusion.INTERIOR_DEVIATION: "écart intérieur",
}
"""Libellés d'affichage des motifs d'exclusion, ceux de ``0010`` D4.9 et D4.10."""

REGIME_LABELS: Mapping[Regime, str] = {
    Regime.ASCENT: "montée",
    Regime.FLAT: "plat",
    Regime.DESCENT: "descente",
}
"""Libellés d'affichage des régimes (``0010`` D6)."""

PASSAGE_STATUS_LABELS: Mapping[PassageStatus, str] = {
    **{
        PassageStatus(status.value): label
        for status, label in POINT_STATUS_LABELS.items()
    },
    PassageStatus.OUTSIDE_PREFIX: "hors préfixe",
}
"""Libellés d'affichage des statuts de passage : ceux de ``POINT_STATUS_LABELS``,
dans le même ordre, puis « hors préfixe » (``0010`` D4.12)."""

PASSAGE_ROLE_LABELS: Mapping[PassageRole, str] = {
    PassageRole.DEPARTURE: "départ",
    PassageRole.ARRIVAL: "arrivée",
    PassageRole.INTERMEDIATE: "intermédiaire",
}
"""Libellés d'affichage des rôles d'une occurrence (``0010`` D4.12)."""

PASSAGE_UNAVAILABILITY_LABELS: Mapping[Unavailability, str] = {
    Unavailability.ABSENT: "absent",
    Unavailability.AMBIGUOUS: "ambigu",
    Unavailability.UNDEFINED_TANGENT: "tangente indéfinie",
    Unavailability.INSUFFICIENT_SUPPORT: "support insuffisant",
}
"""Libellés d'affichage des motifs d'une occurrence indisponible (``0010`` D0)."""

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

REGIME_CLASS_LABELS: Mapping[RegimeClass, str] = {
    RegimeClass.ASCENT: "montée",
    RegimeClass.FLAT: "plat",
    RegimeClass.DESCENT: "descente",
    RegimeClass.MIXED: "mixte",
}
"""Libellés d'affichage des classes de régime (``0010`` D6)."""

NO_REFERENCE_ERROR = (
    "Erreur : --no-reference : la référence doit être la trace elle-même (0010 D3)."
)
"""Le message de ``--no-reference`` sur deux fichiers différents (§ 6.7 du brief
M4b-2)."""

PASSAGE_CSV_HEADER = (
    "name",
    "distance_m",
    "elevation_m",
    "arrival_s",
    "departure_s",
    "moving_time_s",
    "segment_duration_s",
    "segment_distance_m",
    "segment_ascent_m",
    "segment_descent_m",
)
"""En-tête de l'export des passages. Les colonnes ``segment_*`` décrivent le tronçon
**qui précède** le passage ; elles sont vides sur la première ligne."""


def _number(value: float) -> str:
    """Entiers d'affichage, avec espaces ASCII pour séparer les milliers."""
    return f"{value:,.0f}".replace(",", " ")


def _percent(grade: float) -> str:
    """Pente en pourcentage, signe compris : ``+45 %``, ``−40 %``."""
    return f"{grade * 100:+.0f} %".replace("-", "−")


def _percent_of(share: float) -> str:
    """Fraction en pourcentage arrondi. La fraction, elle, vient du moteur."""
    return f"{100 * share:.0f} %"


def _coverage_percent(share: float | None) -> str:
    """Couverture en pourcentage à deux décimales, « non évalué » sans dénominateur.
    La fraction, elle, vient de ``Coverage``."""
    return "non évalué" if share is None else f"{100 * share:.2f} %"


def _print_csv(profile: RouteProfile) -> None:
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(("distance_m", "elevation_m", "grade"))
    grade = profile.grade
    for i, (distance_m, elevation_m) in enumerate(
        zip(profile.distance_m, profile.elevation_m, strict=True)
    ):
        writer.writerow((distance_m, elevation_m, grade[i] if i < len(grade) else ""))


def write_passages_csv(projection: Projection, stream: TextIO) -> None:
    """Écrit le tableau des passages, une ligne par passage.

    Les durées sont en secondes, brutes : ce tableau est fait pour être relu par un
    programme, ``format_duration`` ne sert qu'au rapport. Les colonnes ``segment_*``
    décrivent le tronçon **qui précède** le passage — ce ne sont donc pas des
    cumulés, et elles sont vides sur la première ligne, qui n'a rien avant elle.
    """
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(PASSAGE_CSV_HEADER)
    segments = projection.segments
    for i, passage in enumerate(projection.passages):
        # Vides sur la première ligne : elle n'a aucun tronçon avant elle.
        before: tuple[str | float, ...] = ("", "", "", "")
        if i > 0:
            segment = segments[i - 1]
            before = (
                segment.duration_s,
                segment.distance_m,
                segment.ascent_m,
                segment.descent_m,
            )
        writer.writerow(
            (
                passage.point.point.name,
                passage.point.distance_m,
                passage.point.elevation_m,
                passage.arrival_s,
                passage.departure_s,
                passage.moving_time_s,
                *before,
            )
        )


def _print_report(
    read: GpxReadResult, result: ProfileBuildResult, raw: RouteProfile
) -> None:
    profile = result.profile
    print(
        f"fichier      {profile.source.identifier}   "
        f"sha256 {profile.source.content_hash[:8]}…"
    )
    segments = f"{read.segment_count} tronçon{'s' if read.segment_count != 1 else ''}"
    if read.segment_count > 1:
        segments += f", saut maximal {_number(read.max_segment_gap_m)} m"
    print(
        f"lecture      {_number(read.point_count_read)} points, "
        f"{read.point_count_dropped} écartés (doublons), {segments}"
    )
    _print_grid(result)
    print(
        f"dénivelé     D+ {_number(profile.cumulative_ascent_m[-1])} m / "
        f"D− {_number(profile.cumulative_descent_m[-1])} m        "
        f"(brut : D+ {_number(raw.cumulative_ascent_m[-1])} m / "
        f"D− {_number(raw.cumulative_descent_m[-1])} m)"
    )
    print(
        f"points       {result.matched_point_count} résolus "
        f"sur {len(read.route.named_points)}, "
        f"{read.unnamed_waypoint_count} <wpt> sans nom ignoré(s)"
    )
    if result.unresolved_points:
        places = ", ".join(
            f"« {missing.point.name} » ({_number(missing.min_offset_m)} m)"
            for missing in result.unresolved_points
        )
        print(f"             non résolus : {places}")


def _print_grid(result: ProfileBuildResult) -> None:
    profile = result.profile
    print(
        f"grille       {_number(profile.distance_m[-1])} m, "
        f"{_number(len(profile.distance_m))} points, pas {_number(profile.step_m)} m"
    )
    effective = f"{_number(result.effective_smoothing_window_m)} m effectif"
    if result.smoothing_point_count == 1:
        effective = f"aucun lissage ({effective}, 1 point)"
    else:
        effective += f" ({result.smoothing_point_count} points)"
    print(
        f"lissage      {_number(profile.build_parameters['smoothing_window_m'])} "
        f"m demandé → {effective}"
    )


def _print_projection_report(
    result: ProfileBuildResult,
    read_result: CurveReadResult,
    projection: Projection,
    diagnostics: ProjectionDiagnostics,
) -> None:
    profile = result.profile
    estimation = read_result.curve.estimation
    source = read_result.source
    print(
        f"fichier      {profile.source.identifier}   "
        f"sha256 {profile.source.content_hash[:8]}…"
    )
    print(f"courbe       {source.identifier}   sha256 {source.content_hash[:8]}…")
    print(
        f"             {estimation.activity_count} activités, "
        f"{estimation.date_from} → {estimation.date_to}"
    )
    _print_grid(result)
    low, high = read_result.kept_grade_range
    threshold = projection.parameters["curve_min_support_min"]
    print(
        f"support      {read_result.bin_count_read} tranches lues, "
        f"{read_result.bin_count_kept} retenues (>= {threshold:g} min), "
        f"plage {_percent(low)} … {_percent(high)}"
    )
    print(
        f"             pentes rencontrées : {_percent(diagnostics.grade_min)} … "
        f"{_percent(diagnostics.grade_max)}"
    )
    total_s = projection.passages[-1].arrival_s
    print(
        f"             hors support : "
        f"{_percent_of(diagnostics.out_of_support_distance_share)} de la distance, "
        f"{_percent_of(diagnostics.out_of_support_time_share)} du temps"
    )
    print(f"effort       {projection.parameters['effort']:.2f}")
    print(
        f"durée        {format_duration(total_s)}   "
        f"(D+ {_number(profile.cumulative_ascent_m[-1])} m / "
        f"D− {_number(profile.cumulative_descent_m[-1])} m)"
    )
    resolved = len(profile.resolved_points)
    print(
        f"passages     {len(projection.passages)}   ({resolved} "
        f"lieu{'x' if resolved != 1 else ''} résolu{'s' if resolved != 1 else ''}, "
        "départ et arrivée synthétisés)"
    )
    width = max(len(_number(p.point.distance_m)) for p in projection.passages)
    for passage in projection.passages:
        distance = f"{_number(passage.point.distance_m)} m".rjust(width + 2)
        name = passage.point.point.name.ljust(22)
        print(f"  {distance}   {name} {format_duration(passage.arrival_s)}")


def _count(n: int, singular: str, plural: str) -> str:
    """``0 trou``, ``1 trou``, ``2 trous`` : le singulier jusqu'à 1, en français."""
    return f"{n} {singular if n <= 1 else plural}"


def _print_match_report(
    profile: RouteProfile,
    geometry: ReferenceGeometry,
    trace: RecordedTrace,
    series: TraceSeries,
    parameters: ParameterSet,
    points: Sequence[ScorePointObservation],
    *,
    out: TextIO | None = None,
) -> None:
    """Sections 1 à 4 du rapport d'appariement (§ 5a.9 du brief M4a-2a)."""
    source = profile.source
    print(
        f"référence    {source.identifier}   sha256 {source.content_hash[:8]}…",
        file=out,
    )
    print(
        f"             L {_number(geometry.length_m)} m, "
        f"D+/km {_number(dplus_per_km(profile))} m/km",
        file=out,
    )
    print(f"trace        {trace.sources[0].identifier}", file=out)
    records = _count(len(trace.time_s), "enregistrement", "enregistrements")
    dropped = _count(
        trace.dropped_same_instant_count,
        "instant dupliqué écarté",
        "instants dupliqués écartés",
    )
    print(
        f"             {records}, {dropped}, "
        f"écoulé {format_duration(trace.elapsed_s)}, "
        f"{_count(len(series.blocks), 'bloc', 'blocs')}, "
        f"{_count(sum(series.gap_after), 'trou', 'trous')}",
        file=out,
    )
    departure, arrival = points[0], points[-1]
    line = f"départ       {POINT_STATUS_LABELS[departure.status]}"
    if departure.time_s is not None:
        line += (
            f" — b_0 {departure.effective_m:.2f} m, "
            f"durée avant départ {format_duration(departure.time_s)}"
        )
    print(line, file=out)
    line = f"arrivée      {POINT_STATUS_LABELS[arrival.status]}"
    if arrival.time_s is not None:
        line += (
            f" — instant {format_duration(arrival.time_s)}, "
            f"b_K {arrival.effective_m:.2f} m"
        )
        if arrival.status is PointStatus.ANCHORED:
            # L − b_K est l'opposé du décalage d'ancrage que porte le contrat.
            line += f", L − b_K {0.0 - arrival.anchoring_offset_m:.2f} m"
    print(line, file=out)
    print(
        f"points       Δ {parameters['score_step_m']:g} m, "
        f"ε {parameters['lateral_tolerance_m']:g} m, "
        f"r_c {parameters['cluster_radius_m']:g} m — {len(points)} points",
        file=out,
    )
    counts = Counter(point.status for point in points)
    print(
        "             "
        + ", ".join(
            f"{label} {counts[status]}" for status, label in POINT_STATUS_LABELS.items()
        ),
        file=out,
    )
    ambiguous = [
        f"k = {point.index} (s_k = {_number(point.nominal_m)} m)"
        for point in points
        if point.status is PointStatus.AMBIGUOUS
    ]
    print(f"             ambigus : {', '.join(ambiguous) or 'aucun'}", file=out)


def _durations(totals: ClockTotals | AdmittedTotals) -> str:
    """``M / S / U`` d'un jeu de totaux, en ``format_duration``."""
    return " / ".join(
        format_duration(value)
        for value in (totals.moving_s, totals.stopped_s, totals.undetermined_s)
    )


def _print_segment_report(
    result: MatchResult, episodes: Sequence[StopEpisode], *, out: TextIO | None = None
) -> None:
    """Sections 5 à 9 du rapport d'appariement (§ 5b.11 du brief M4a-2b) : segments,
    couverture, préfixe, horloges, épisodes sous ``θ_c``. Seuls des comptes et des
    mises en forme : longueurs, temps et totaux sont lus dans le ``MatchResult``."""
    segments, coverage = result.segments, result.coverage
    counts = Counter(segment.exclusion for segment in segments)
    excluded_m = {
        SegmentExclusion.UNOBSERVED_BOUND: coverage.excluded_unobserved_bound_m,
        SegmentExclusion.GAP: coverage.excluded_gap_m,
        SegmentExclusion.LENGTH_RATIO: coverage.excluded_length_ratio_m,
        SegmentExclusion.INTERIOR_DEVIATION: coverage.excluded_interior_deviation_m,
    }
    motifs = [
        f"{label} {counts[exclusion]} ({excluded_m[exclusion]:.2f} m)"
        for exclusion, label in SEGMENT_EXCLUSION_LABELS.items()
    ]
    print(f"segments     {counts[None]} admis sur {len(segments)}", file=out)
    print(f"             {', '.join(motifs[:2])}", file=out)
    print(f"             {', '.join(motifs[2:])}", file=out)
    print(f"             ancrage exclu {coverage.anchoring_excluded_m:.2f} m", file=out)
    regimes = ", ".join(
        f"{label} {_coverage_percent(coverage.regime_fraction(regime))}"
        for regime, label in REGIME_LABELS.items()
    )
    print(f"couverture   {_coverage_percent(coverage.fraction)} — {regimes}", file=out)
    print(
        f"             écoulé admis {format_duration(coverage.admitted_elapsed_s)}",
        file=out,
    )
    excluded_s = {
        SegmentExclusion.GAP: coverage.excluded_gap_s,
        SegmentExclusion.LENGTH_RATIO: coverage.excluded_length_ratio_s,
        SegmentExclusion.INTERIOR_DEVIATION: coverage.excluded_interior_deviation_s,
    }
    times = ", ".join(
        f"{SEGMENT_EXCLUSION_LABELS[exclusion]} {format_duration(duration_s)}"
        for exclusion, duration_s in excluded_s.items()
    )
    print(f"             temps exclus : {times}", file=out)
    unknown = _count(counts[SegmentExclusion.UNOBSERVED_BOUND], "segment", "segments")
    print(f"             durées inconnues : {unknown}", file=out)
    end_s = coverage.prefix_end_s
    print(
        "préfixe      "
        f"{_count(coverage.prefix_segment_count, 'segment', 'segments')}, "
        f"b_m {coverage.prefix_end_m:.2f} m, "
        f"t*_m {'non daté' if end_s is None else format_duration(end_s)}, "
        f"dernier passage {coverage.prefix_last_passage or 'aucun'}",
        file=out,
    )
    print("horloges     M / S / U de la trace, puis du support admis", file=out)
    for k, (trace, admitted) in enumerate(
        zip(result.trace_totals, result.admitted_totals, strict=True)
    ):
        print(
            f"             θ{k + 1}  trace {_durations(trace)}"
            f"   admis {_durations(admitted)}",
            file=out,
        )
    low, high = result.low_convention_index, result.high_convention_index
    interval = result.admitted_sensitivity_range_s
    if low is None or high is None or interval is None:
        print("             θ_bas, θ_haut, I_sens,A : aucun segment admis", file=out)
    else:
        print(
            f"             θ_bas θ{low + 1}, θ_haut θ{high + 1}, I_sens,A "
            f"[{format_duration(interval[0])} ; {format_duration(interval[1])}]",
            file=out,
        )
    stopped_s = result.trace_totals[CENTRAL_CONVENTION_INDEX].stopped_s
    print(
        f"épisodes     sous θ_c : {_count(len(episodes), 'épisode', 'épisodes')}, "
        f"{format_duration(stopped_s)}",
        file=out,
    )


def _print_passage_report(
    result: PassageMatchResult, *, out: TextIO | None = None
) -> None:
    """Section 10 du rapport d'appariement (§ 6.10 du brief M4a-3) : passages nommés
    et épisodes sous ``θ_c``. Seuls des comptes et des mises en forme : statuts,
    instants et attributions sont lus dans le ``PassageMatchResult``."""
    passages = result.passages
    counts = Counter(passage.status for passage in passages)
    statuses = ", ".join(
        f"{label} {counts[status]}" for status, label in PASSAGE_STATUS_LABELS.items()
    )
    comparables = sum(passage.comparable for passage in passages)
    print(
        f"passages     {_count(len(passages), 'occurrence', 'occurrences')} — "
        f"{statuses} ; comparables {comparables}",
        file=out,
    )
    for passage in passages:
        line = (
            f"             {passage.point.point.name} — "
            f"{passage.point.distance_m:.2f} m, {PASSAGE_ROLE_LABELS[passage.role]}, "
            f"{PASSAGE_STATUS_LABELS[passage.status]}"
        )
        if passage.chronology_violation:
            line += " (chronologie)"
        if (
            passage.crossing_s is not None
            and passage.arrival_s is not None
            and passage.departure_s is not None
            and passage.stop_total_s is not None
        ):
            episodes = _count(passage.episode_count, "épisode", "épisodes")
            line += (
                f", t* {format_duration(passage.crossing_s)}, "
                f"arrivée {format_duration(passage.arrival_s)}, "
                f"départ {format_duration(passage.departure_s)}, "
                f"S {format_duration(passage.stop_total_s)}, {episodes}"
            )
        if passage.role is PassageRole.DEPARTURE:
            end = "non cible"
        elif passage.unavailability is None:
            end = "comparable"
        else:
            motive = PASSAGE_UNAVAILABILITY_LABELS[passage.unavailability]
            end = f"indisponible ({motive})"
        print(f"{line} ; {end}", file=out)
    outcomes = Counter(attribution.outcome for attribution in result.episodes)
    print(
        "             épisodes θ_c : "
        f"attribués {outcomes[EpisodeOutcome.ATTRIBUTED]}, "
        f"sans candidate {outcomes[EpisodeOutcome.NO_CANDIDATE]}, "
        f"non attribués {outcomes[EpisodeOutcome.TIE]}",
        file=out,
    )
    for attribution in result.episodes:
        if attribution.outcome is EpisodeOutcome.TIE:
            episode = attribution.episode
            print(
                f"             non attribué [{format_duration(episode.start_s)} ; "
                f"{format_duration(episode.end_s)}]",
                file=out,
            )


_INDENT = " " * 13
"""La colonne d'étiquette des sections 1 à 13 : treize caractères."""


def _log(value: float) -> str:
    """Métrique logarithmique : ``+0.123456``, ``−0.693147`` (§ 6.7)."""
    return f"{value:+z.6f}".replace("-", "−")


def _plain(value: float) -> str:
    """``min |L|``, ``q_usage``, ``q | préfixe``, poids : ``0.625000``."""
    return f"{value:z.6f}"


def _seconds(value: float) -> str:
    """``C_k`` et ses extrêmes signés, en secondes : ``−75.0``, ``+0.2``."""
    return f"{value:+z.1f}".replace("-", "−")


def _abs_seconds(value: float) -> str:
    """``max |C_k|``, en secondes : ``160.0``."""
    return f"{value:z.1f}"


def _cell(value: MetricValue, formatted: Callable[[float], str]) -> str:
    """Une valeur de M4b-1 mise en forme, ou le libellé de son motif."""
    if value.value is not None:
        return formatted(value.value)
    assert value.unavailability is not None  # contrat de MetricValue
    return METRIC_UNAVAILABILITY_LABELS[value.unavailability]


def _row(label: str, cells: Sequence[str]) -> str:
    """Une ligne de tableau : étiquette de 16 caractères, cellules de 20, sans espace
    en fin de ligne (§ 6.7)."""
    return (_INDENT + f"{label:<16}" + "".join(f"{c:<20}" for c in cells)).rstrip()


def _clock_label(clock: Clock) -> str:
    """``écoulé``, ``M θ<n>``, ``(M+U) θ<n>`` (§ 6.7)."""
    if clock.convention_index is None:
        return "écoulé"
    kind = "M" if clock.kind is ClockKind.MOVING else "(M+U)"
    return f"{kind} θ{clock.convention_index + 1}"


def _envelope(envelope: LogRatioEnvelope | None) -> str:
    """``[lower ; upper], min |L| x``, suivi du motif quand elle en a un ; le motif
    seul sans valeur ; ``non évalué`` sans enveloppe (§ 6.7)."""
    if envelope is None:
        return "non évalué"
    motif = envelope.unavailability
    lower, upper, min_abs = envelope.lower, envelope.upper, envelope.min_abs
    if lower is None or upper is None or min_abs is None:
        assert motif is not None  # contrat de LogRatioEnvelope
        return METRIC_UNAVAILABILITY_LABELS[motif]
    high = "+∞" if math.isinf(upper) else _log(upper)
    text = f"[{_log(lower)} ; {high}], min |L| {_plain(min_abs)}"
    if motif is not None:
        text += f" ({METRIC_UNAVAILABILITY_LABELS[motif]})"
    return text


def _support_rows(
    supports: Sequence[SupportMetrics | None],
) -> list[tuple[str, list[str]]]:
    """Les dix-sept lignes de métriques, une cellule par horloge montrée ; ``—`` sous
    une horloge sans valeur (diagnostic absent)."""

    def cells(values: Sequence[MetricValue | None]) -> list[str]:
        return ["—" if value is None else _cell(value, _log) for value in values]

    def of_support(pick: Callable[[SupportMetrics], MetricValue]) -> list[str]:
        return cells([None if s is None else pick(s) for s in supports])

    rows = [
        ("L", of_support(lambda s: s.log_ratio)),
        ("A", of_support(lambda s: s.dispersion)),
        ("W", of_support(lambda s: s.within)),
        ("B", of_support(lambda s: s.between)),
        ("C_comp", of_support(lambda s: s.compensation)),
    ]
    for r, regime in enumerate(RegimeClass):
        label = REGIME_CLASS_LABELS[regime]
        classes = [None if s is None else s.classes[r] for s in supports]
        rows += [
            (
                f"{label} E_R",
                cells([None if c is None else c.log_ratio for c in classes]),
            ),
            (
                f"{label} D_R",
                cells([None if c is None else c.dispersion for c in classes]),
            ),
            (
                f"{label} E_R−L",
                cells([None if c is None else c.shape for c in classes]),
            ),
        ]
    return rows


def _shown(scenario: ScenarioScores, clocks: Sequence[Clock]) -> list[ClockScores]:
    """Les scores des horloges du rapport, lus parmi les onze."""
    return [scenario.clocks[CLOCKS.index(clock)] for clock in clocks]


def _print_scenario(
    label: str,
    scenario: ScenarioScores,
    observation: OutingObservation,
    clocks: Sequence[Clock],
    *,
    out: TextIO | None = None,
) -> None:
    """Points 1 à 4 de la section 12 (§ 6.7 du brief M4b-2) : tracé projeté et
    effectifs, enveloppes, métriques sous les horloges du rapport, diagnostic."""
    shown = _shown(scenario, clocks)
    support = shown[0].support
    segments = _count(support.segment_count, "segment admis", "segments admis")
    classes = ", ".join(
        f"{REGIME_CLASS_LABELS[regime.regime_class]} {regime.segment_count}"
        + (" (trop peu représenté)" if regime.underrepresented else "")
        for regime in support.classes
    )
    print(
        f"{label:<13}{scenario.forecast.source.identifier} ; {segments} : {classes}",
        file=out,
    )
    print(f"{_INDENT}{'enveloppe':<16}support {_envelope(scenario.envelope)}", file=out)
    for regime, envelope in zip(RegimeClass, scenario.class_envelopes, strict=True):
        print(
            f"{_INDENT}{'':<16}{REGIME_CLASS_LABELS[regime]} {_envelope(envelope)}",
            file=out,
        )
    print(_row("", [_clock_label(clock) for clock in clocks]), file=out)
    for row_label, cells in _support_rows([s.support for s in shown]):
        print(_row(row_label, cells), file=out)
    diagnostics = [s.diagnostic for s in shown]
    if all(diagnostic is None for diagnostic in diagnostics):
        return
    print(
        f"{_INDENT}{'diagnostic':<16}sous-support à temps positifs, "
        "ni cible ni garde-fou",
        file=out,
    )
    kept, zero = [], []
    for diagnostic in diagnostics:
        if diagnostic is None:
            kept.append("—")
            zero.append("—")
            continue
        mask = diagnostic.mask
        kept.append(f"{sum(mask)} sur {len(mask)}")
        zero.append(
            ", ".join(
                f"k {segment.index}"
                for segment, positive in zip(observation.segments, mask, strict=True)
                if not positive
            )
        )
    print(_row("segments", kept), file=out)
    print(_row("temps nuls", zero), file=out)
    metrics = [None if d is None else d.metrics for d in diagnostics]
    for row_label, cells in _support_rows(metrics):
        print(_row(row_label, cells), file=out)


def _point_name(point: ObservedPoint, passages: PassageMatchResult) -> str:
    """``point k`` ou le nom du lieu."""
    if point.passage_index is not None:
        return passages.passages[point.passage_index].point.point.name
    return f"point {point.score_index}"


def _print_passage_errors(
    scenario: ScenarioScores,
    observation: OutingObservation,
    passages: PassageMatchResult,
    clocks: Sequence[Clock],
    *,
    out: TextIO | None = None,
) -> None:
    """Point 5 de la section 12 : ``C_k`` (``0010`` D7.3)."""
    points = observation.error_points
    scored = sum(point.score_index is not None for point in points)
    print(
        f"{'C_k':<13}{_count(len(points), 'point', 'points')} du préfixe "
        f"({_count(scored, 'point de score', 'points de score')}, "
        f"{_count(len(points) - scored, 'lieu', 'lieux')}), origine exclue ; secondes",
        file=out,
    )
    print(_row("", [_clock_label(clock) for clock in clocks]), file=out)
    errors = [s.passage_errors for s in _shown(scenario, clocks)]
    present = [e for e in errors if e is not None]
    print(
        _row("max |C_k|", [_cell(e.max_abs_error_s, _abs_seconds) for e in present]),
        file=out,
    )
    print(_row("max C_k", [_cell(e.max_error_s, _seconds) for e in present]), file=out)
    print(_row("min C_k", [_cell(e.min_error_s, _seconds) for e in present]), file=out)
    if not points:
        return
    print(f"{_INDENT}sous l'écoulé", file=out)
    elapsed = scenario.clocks[0].passage_errors
    assert elapsed is not None  # contrat de ScenarioScores, en usage
    for point, error in zip(points, elapsed.errors_s, strict=True):
        print(
            f"{_INDENT}  {_point_name(point, passages):<24}{point.distance_m:>11.2f} m"
            f"   {_cell(error, _seconds)}",
            file=out,
        )


def _print_targets(
    scenario: ScenarioScores,
    observation: OutingObservation,
    passages: PassageMatchResult,
    clocks: Sequence[Clock],
    *,
    out: TextIO | None = None,
) -> None:
    """Point 6 de la section 12 : ``K`` et la cible d'usage (``0010`` D7.4)."""
    targets, members = observation.targets, observation.members
    places = sum(not member.arrival for member in members)
    of_k = "l'arrivée"
    if places:
        of_k = f"{_count(places, 'lieu', 'lieux')} et l'arrivée"
    elapsed = scenario.clocks[0].usage_target
    assert elapsed is not None  # contrat de ScenarioScores, en usage
    available = _count(elapsed.available_count, "passage", "passages")
    print(
        f"{'K':<13}{_count(len(targets), 'élément', 'éléments')} ({of_k}) — "
        f"{available} sur {elapsed.target_count}",
        file=out,
    )
    print(_row("", [_clock_label(clock) for clock in clocks]), file=out)
    shown = [s.usage_target for s in _shown(scenario, clocks)]
    present = [t for t in shown if t is not None]
    print(_row("q_usage", [_cell(t.q_usage, _plain) for t in present]), file=out)
    print(
        _row("q | préfixe", [_cell(t.q_usage_prefix, _plain) for t in present]),
        file=out,
    )
    print(
        _row(
            "comparables",
            [f"{sum(t.comparable)} sur {len(t.comparable)}" for t in present],
        ),
        file=out,
    )
    for k, (member, target) in enumerate(zip(members, targets, strict=True)):
        name = "arrivée"
        if member.occurrence_index is not None:
            place = passages.passages[member.occurrence_index].point.point.name
            name = f"arrivée ({place})" if member.arrival else place
        weight = "—" if elapsed.weights is None else _plain(elapsed.weights[k])
        state = "disponible"
        if target.unavailability is not None:
            state = METRIC_UNAVAILABILITY_LABELS[target.unavailability]
        print(
            f"{_INDENT}  {name:<24}{target.distance_m:>11.2f} m   poids {weight}"
            f"   {state}",
            file=out,
        )
    gap_m = observation.arrival_anchor_gap_m
    if gap_m is not None:
        print(f"{_INDENT}arrivée ancrée, L − b_K {gap_m:.2f} m", file=out)


def _print_v0_report(
    read_result: CurveReadResult,
    outing: OutingScores,
    passages: PassageMatchResult,
    clocks: Sequence[Clock],
    *,
    out: TextIO | None = None,
) -> None:
    """Sections 11 à 13 du rapport d'appariement (§ 6.7 du brief M4b-2) : v0 brut,
    usage, contrôle, sous les horloges du rapport. Seules des mises en forme : les
    valeurs sont lues dans l'``OutingScores``."""
    source = read_result.source
    forecast = outing.control.forecast
    print(
        f"{'v0 brut':<13}courbe {source.identifier}   "
        f"sha256 {source.content_hash[:8]}…",
        file=out,
    )
    shown = ", ".join(_clock_label(clock) for clock in clocks)
    if len(clocks) == 1:
        shown += " (aucun segment admis)"
    print(
        f"{_INDENT}effort {forecast.parameters['effort']:.2f}, moteur "
        f"{forecast.engine_version} ; horloges du rapport : {shown}",
        file=out,
    )
    observation = outing.observation
    if outing.usage is None:
        print(
            f"{'usage':<13}sans référence : scénario contrôle seul (0010 D3)", file=out
        )
    else:
        _print_scenario("usage", outing.usage, observation, clocks, out=out)
        _print_passage_errors(outing.usage, observation, passages, clocks, out=out)
        _print_targets(outing.usage, observation, passages, clocks, out=out)
    _print_scenario("contrôle", outing.control, observation, clocks, out=out)


# ---------------------------------------------------------------------------
# mperf backtest : synthèse et rapport D15 (§ 6.3 du brief M4b-5)
# ---------------------------------------------------------------------------

DATA_SET_LABELS: Mapping[DataSet, str] = {
    DataSet.REPEATABILITY: "répétabilité",
    DataSet.DEVELOPMENT: "développement",
    DataSet.CONFIRMATION: "confirmation",
}
"""Libellés d'affichage des jeux (``0010`` D2.3)."""

OUTING_LABEL_LABELS: Mapping[OutingLabel, str] = {
    OutingLabel.RACE: "course",
    OutingLabel.TRAINING: "entraînement",
}
"""Libellés d'affichage des étiquettes d'une sortie."""

MISSING_LABELS: Mapping[str, str] = {
    Unavailability.ABSENT.value: "absent",
    Unavailability.AMBIGUOUS.value: "ambigu",
    Unavailability.UNDEFINED_TANGENT.value: "tangente indéfinie",
    Unavailability.GAP.value: "trou",
    Unavailability.INTERIOR_DEVIATION.value: "écart intérieur",
    Unavailability.INSUFFICIENT_SUPPORT.value: "support insuffisant",
    Unavailability.ZERO_TIME.value: "temps nul",
    Unavailability.UNIDENTIFIED_REFERENCE.value: "référence non identifiée",
    Unavailability.NON_CONVERGENCE.value: "non-convergence",
    Unavailability.MODEL_ERROR.value: "erreur du modèle",
    Unavailability.NOT_CALIBRATED.value: "non calé",
    Unavailability.MULTI_OUTING_DAY.value: "jour multi-sorties",
    UNDERREPRESENTED: "trop peu représenté",
    NOT_SCORED: "non scorée",
    NO_REFERENCE: "sans référence",
}
"""Libellés d'affichage des motifs d'une valeur manquante, dans l'ordre de
``MISSING_ORDER`` : ceux de ``mperf match``, les autres noms de ``0010`` D0, puis ceux
du rapport (§ 6.3 du brief M4b-5). Invariables : ``2 non scorée``."""

SUBCLASS_LABELS: Mapping[DescentSubclass, tuple[str, str]] = {
    DescentSubclass.ROLLING: ("roulante", "roulantes"),
    DescentSubclass.STEEP: ("raide", "raides"),
    DescentSubclass.UNDECIDED: ("non départagée", "non départagées"),
}
"""Libellés d'affichage des sous-classes de descente, singulier et pluriel (``0010``
D6)."""

REPORT_METRIC_LABELS: Mapping[ReportMetric, str] = {
    ReportMetric.LEVEL: "L",
    ReportMetric.ABS_LEVEL: "|L|",
    ReportMetric.DISPERSION: "A",
    ReportMetric.WITHIN: "W",
    ReportMetric.BETWEEN: "B",
    ReportMetric.COMPENSATION: "C_comp",
    ReportMetric.SHAPE: "E_R−L",
    ReportMetric.ABS_CLASS_LEVEL: "|E_R|",
    ReportMetric.CLASS_DISPERSION: "D_R",
    ReportMetric.MAX_ABS_PASSAGE_ERROR: "max |C_k|",
    ReportMetric.USAGE_TARGET: "q_usage",
}
"""Libellés d'affichage des métriques agrégées ; une métrique de classe est précédée
du libellé de sa classe (``montée E_R−L``)."""

CLOCK_ROLE_LABELS: Mapping[ClockRole, str] = {
    ClockRole.ELAPSED: "écoulé",
    ClockRole.LOW: "M sous θ_bas de chaque performance",
    ClockRole.HIGH: "M + U sous θ_haut de chaque performance",
}
"""Libellés d'affichage des horloges d'une table d'agrégats (``0010`` D5.4)."""

SCENARIO_LABELS: Mapping[Scenario, str] = {
    Scenario.USAGE: "usage",
    Scenario.CONTROL: "contrôle",
}
"""Libellés d'affichage des scénarios (``0010`` D3)."""

MODEL_LABELS: Mapping[ModelKind, str] = {
    ModelKind.V0_RAW: "v0 brut",
    ModelKind.V0_RECALIBRATED: "v0 + effort recalé",
    ModelKind.CONSTANT_SPEED: "vitesse constante",
    ModelKind.NAISMITH: "Naismith",
    ModelKind.TOBLER: "Tobler",
}
"""Libellés d'affichage des cinq modèles du rapport (``0010`` D9.1 ; précision de
D15, M4c-2)."""

EXCLUSION_LABELS: Mapping[PopulationExclusionReason, str] = {
    PopulationExclusionReason.RACE: "course",
    PopulationExclusionReason.UNLABELLED: "étiquette manquante",
}
"""Libellés d'affichage des motifs d'exclusion de ``C_j`` (``0010`` D2.4)."""

DECLARATION_RECORDED = "{label}{number} enregistrée ; dernière ligne sha256 {seal}"
"""La première ligne de la sortie standard de ``mperf backtest``, imprimée dès l'ajout
de la DÉCLARATION (précision de D14, M4c-2) : un processus tué avant le RÉSULTAT
laisse publiée l'empreinte de la ligne de la DÉCLARATION."""

LEGEND = (
    "lecture de la compensation : sur des régimes homogènes, C_comp et W restent "
    "proches de 0 même quand des erreurs de signe opposé se compensent dans le total ; "
    "ce qui montre un total juste qui cache des erreurs est l'écart entre A (grand) et "
    "|L| (proche de 0), et B quand l'écart vient des régimes. C_comp ne mesure que la "
    "compensation entre l'écart d'un segment à son régime et l'écart de ce régime au "
    "global.",
    "scores rétrospectifs (0010 D2.2) ; répétabilité : scores d'« apprentissage » "
    "(D2.3)",
    "âge de la courbe : jours du jour J (ou de o_j) depuis son estimation ; négatif, "
    "elle est postérieure au jour",
    "F (0010 D8) se calcule pli par pli, sur les segments du jour retiré qu'un autre "
    "jour observe ; les modèles, sur le support admis de chaque jour : mêmes jours, "
    "supports différents",
    "temps nul sous un M θ : un segment admis sans temps en mouvement sous ce seuil, "
    "souvent le dernier d'une trace arrêtée à l'arrivée (fenêtre de 0010 D5.2) ; D8 ne "
    "l'ajuste pas (cellule nulle, choix M02) : |L| du pli et F indisponibles",
    "modèles calés (0010 D9.2) : v0 + effort recalé, vitesse constante, Naismith, "
    "Tobler, calés par performance, scénario et horloge sur C_j^eff (entraînements "
    "terminés avant o_j) ; prévision = prévision non calée ÷ effort e (v0) ou × "
    "facteur a (baselines) ; non calé : C_j^eff vide ; pas d'enveloppe",
    "ensemble commun : par jeu, les performances où les cinq modèles ont une valeur ; "
    "les cinq moyennes y portent sur les mêmes performances",
    "gains, garde-fous, admission d'un effet (0010 D10) : non implémentée dans ce lot "
    "(M4c-3)",
    "fourchettes (0010 D11) : non implémentée dans ce lot (M4d)",
    "dérive de longue course (0010 D12) : non implémentée dans ce lot (M4d)",
    "sensibilité (0010 D13) : non implémentée dans ce lot (M4d)",
)
"""La légende du rapport (§ 6.3, point 8, et § 7.4 du brief M4b-5 ; § 6.6 du brief
M4c-2) : la lecture de la compensation, les scores rétrospectifs, l'âge de la courbe,
les supports de F et des modèles, le temps nul sous un ``M θ``, les modèles calés,
l'ensemble commun, puis les quatre rubriques des lots futurs (D15)."""

REPORTS_DIR = "rapports"
"""Le dossier des rapports D15 sous ``MPA_DATA_DIR``, jamais réécrits."""

REGISTRY_DIR = "registre"
"""Le dossier du registre des expériences sous ``MPA_DATA_DIR`` (``0010`` D14)."""

BACKTEST_CURVE_ERROR = (
    "Erreur : --curve est obligatoire : la courbe est une entrée déclarée de "
    "l'exécution (0010 D2.6)."
)
"""Le message de ``mperf backtest`` sans ``--curve`` (§ 6.3 du brief M4b-5)."""

MODIFIED_TREE_ERROR = (
    "Erreur : l'arbre de travail porte des modifications non commitées : just "
    "backtest enregistre le commit du code exécuté (0010 D14). Committer d'abord ; "
    "rien n'est écrit."
)
"""Le refus d'un arbre de travail modifié (décision Q7 du brief M4b-5)."""

REPORT_EXISTS_ERROR = (
    "Erreur : le rapport {name} existe déjà : il n'est jamais réécrit. Un registre "
    "neuf à côté d'anciens rapports ? Déplacer ces rapports ; rien n'est écrit."
)
"""Le refus d'un rapport prévu déjà présent (§ 6.3, étape 4, du brief M4b-5)."""

REPORT_NOT_WRITTEN_ERROR = (
    "Erreur : RÉSULTAT enregistré (événement {number} ; dernière ligne sha256 {seal}) "
    "; rapport {name} non écrit : {reason}"
)
"""L'erreur d'un rapport qui ne s'écrit pas après le RÉSULTAT (depuis M4c-2, le
rapport se calcule avant le RÉSULTAT, et une erreur de ce calcul est un ÉCHEC) : elle
publie le sceau (décisions Q15 et Q17 du brief M4b-5)."""


def _report_name(number: int) -> str:
    """``rapports/backtest-0002.txt`` : le rapport du RÉSULTAT ``number``."""
    return f"{REPORTS_DIR}/backtest-{number:04d}.txt"


def _age(days: int) -> str:
    """Un âge de la courbe, toujours signé : ``+16``, ``−49``, ``+0``."""
    return f"{days:+d}".replace("-", "−")


def _label(value: MetricValue, formatted: Callable[[float], str]) -> str:
    """Une ``MetricValue`` mise en forme, ou le libellé de son motif (tous ceux de
    ``0010`` D0)."""
    if value.value is not None:
        return formatted(value.value)
    assert value.unavailability is not None  # contrat de MetricValue
    return MISSING_LABELS[value.unavailability.value]


def _metric_format(metric: ReportMetric) -> Callable[[float], str]:
    """Biais signés (``L``, ``E_R − L``) à six décimales signées ; ``max |C_k|`` en
    secondes ; les autres valeurs absolues à six décimales sans signe."""
    if metric in (ReportMetric.LEVEL, ReportMetric.SHAPE):
        return _log
    if metric is ReportMetric.MAX_ABS_PASSAGE_ERROR:
        return _abs_seconds
    return _plain


def _metric_label(metric: ReportMetric, regime: RegimeClass | None) -> str:
    label = REPORT_METRIC_LABELS[metric]
    return label if regime is None else f"{REGIME_CLASS_LABELS[regime]} {label}"


def _aggregate_cell(value: Aggregate, formatted: Callable[[float], str]) -> str:
    """``+0.025018 (5)``, ``— (0)`` sans valeur."""
    shown = "—" if value.value is None else formatted(value.value)
    return f"{shown} ({value.count})"


def _missing(value: Aggregate) -> str:
    """``1 jour multi-sorties, 2 non scorée`` : les motifs comptés."""
    return ", ".join(f"{n} {MISSING_LABELS[motif]}" for motif, n in value.missing)


def _aggregate_lines(rows: Sequence[AggregateRow], *, with_missing: bool) -> list[str]:
    """L'en-tête des jeux, puis une ligne par métrique et, si demandé, la ligne de
    ses manquants jeu par jeu."""
    lines = [_row("", [DATA_SET_LABELS[dataset] for dataset in DataSet])]
    for row in rows:
        formatted = _metric_format(row.metric)
        lines.append(
            _row(
                _metric_label(row.metric, row.regime_class),
                [_aggregate_cell(value, formatted) for value in row.by_set],
            )
        )
        missing = [
            f"{DATA_SET_LABELS[dataset]} {_missing(value)}"
            for dataset, value in zip(DataSet, row.by_set, strict=True)
            if value.missing
        ]
        if with_missing and missing:
            lines.append(f"{_INDENT}{'  manquants':<16}{' ; '.join(missing)}")
    return lines


def _performance_lines(run: BacktestRun | BacktestEvaluation) -> list[str]:
    """Le tableau ``performances`` : une ligne par sortie déclarée, colonnes de
    largeur fixe (§ 6.3 du brief M4b-5)."""
    scored = {outing.outing.outing_id: outing for outing in run.outings}
    unscored = {exclusion.outing_id: exclusion.reason for exclusion in run.unscored}
    header = (
        f"{'jour':<12}{'sortie':<28}{'jeu':<15}{'étiquette':<14}{'couverture':<12}"
        f"{'préfixe':<11}{'L v0':<12}q_usage v0"
    )
    lines = [f"{'performances':<13}{header}"]
    for declared in run.preparation.declaration.performances:
        performance = declared.performance
        for outing in performance.outings:
            dataset = "—" if outing.dataset is None else DATA_SET_LABELS[outing.dataset]
            label = "—" if outing.label is None else OUTING_LABEL_LABELS[outing.label]
            start = (
                f"{_INDENT}{performance.civil_date.isoformat():<12}"
                f"{outing.outing_id:<28}{dataset:<15}{label:<14}"
            )
            if outing.outing_id in unscored:
                line = f"{start}non scorée : {unscored[outing.outing_id]}"
                if performance.is_multi_outing:
                    line += " (jour multi-sorties)"
                lines.append(line)
                continue
            run_ = scored[outing.outing_id]
            coverage = run_.match.coverage
            usage = run_.scores.usage
            scenario = run_.scores.control if usage is None else usage
            level = _label(scenario.clocks[0].support.log_ratio, _log)
            if usage is None:
                target = "sans référence"
            else:
                elapsed = usage.clocks[0].usage_target
                target = "—" if elapsed is None else _label(elapsed.q_usage, _plain)
            if performance.is_multi_outing:
                target += " (jour multi-sorties)"
            share = _coverage_percent(coverage.fraction)
            prefix = f"{coverage.prefix_end_m / 1000:.2f} km"
            lines.append(f"{start}{share:<12}{prefix:<11}{level:<12}{target}")
    return lines


def _comparison_lines(
    run: BacktestRun | BacktestEvaluation, entries: Sequence[ScoredPerformance]
) -> list[str]:
    """La référence de répétabilité dans la synthèse : par parcours, ses ``F`` sous
    l'écoulé à côté des cinq modèles sur ses jours (précision de D15, M4c-2) ; la
    colonne de ``F`` a une largeur par parcours. Sans parcours de répétabilité, aucune
    ligne (comme « écartée » sans exclusion)."""
    comparisons = route_comparisons(entries, run.references)
    if not comparisons:
        return []
    lines = [f"{'référence':<13}répétabilité (0010 D8)"]
    for comparison in comparisons:
        days = _count(comparison.days, "jour", "jours")
        single = ", un seul contraste" if comparison.single_contrast else ""
        lines.append(
            f"{_INDENT}{comparison.route_id} — {days}{single} ; écoulé, usage : F du "
            "parcours, les cinq modèles sur ses jours"
        )
        cells = [
            (
                _metric_label(metric, regime),
                f"{_label(f, _plain)} (m {f.count})",
                [_aggregate_cell(value, _plain) for value in by_model],
            )
            for metric, regime, f, by_model in comparison.rows
        ]
        width = max(20, max(len(f) for _, f, _ in cells) + 2)
        models = "".join(f"{MODEL_LABELS[model]:<20}" for model in REPORT_MODELS)
        lines.append(
            (_INDENT + " " * 16 + f"{'F du parcours':<{width}}" + models).rstrip()
        )
        lines += [
            (
                _INDENT + f"{label:<16}{f:<{width}}" + "".join(f"{c:<20}" for c in row)
            ).rstrip()
            for label, f, row in cells
        ]
    return lines


def _calibration_cell(calibration: ModelCalibration) -> str:
    """La cellule d'un calage (précision de D15, M4c-2) : ``e <effort>`` pour v0,
    suivi de `` saturé`` si l'effort est borné, ``a <facteur>`` pour une baseline, ou
    le libellé de son statut (``non calé``, ``erreur du modèle``)."""
    if calibration.unavailability is not None:
        return MISSING_LABELS[calibration.unavailability.value]
    if calibration.effort is not None:
        saturated = " saturé" if calibration.saturated else ""
        return f"e {_plain(calibration.effort)}{saturated}"
    assert calibration.factor is not None  # contrat de ModelCalibration
    return f"a {_plain(calibration.factor)}"


def _calibration_lines(run: BacktestRun | BacktestEvaluation) -> list[str]:
    """La ligne de calage de chaque performance (précision de D15, M4c-2 ; décision
    11) : son jour, ``|C_j|``, puis, lus sur sa **première sortie scorée**, sous
    l'écoulé, en usage — en contrôle sans référence, « (contrôle) » —, ``|C_j^eff|`` et
    la cellule de chaque modèle calé ; un jour multi-sorties le dit, avec cette
    sortie ; une performance sans sortie scorée, ``—`` et son motif."""
    lines = [
        f"{'calage':<13}0010 D9.2 sur C_j (entraînements terminés avant o_j) ; écoulé, "
        "usage (contrôle sans référence) ; e : effort de v0, a : facteur",
        (
            _INDENT
            + f"{'jour':<12}{'C_j':<5}{'C_j^eff':<9}"
            + "".join(f"{MODEL_LABELS[model]:<20}" for model in CALIBRATED_MODELS)
        ).rstrip(),
    ]
    multi = {
        declared.performance.civil_date: declared.performance.is_multi_outing
        for declared in run.preparation.declaration.performances
    }
    for performance in run.calibration:
        population = performance.population
        day = population.civil_date
        start = f"{_INDENT}{day.isoformat():<12}{len(population.members):<5}"
        if not performance.outings:
            lines.append(f"{start}{'—':<9}{MISSING_LABELS[NOT_SCORED]}")
            continue
        group = performance.outings[: len(CALIBRATED_MODELS)]
        control = group[0].usage is None
        scenarios = [entry.control if control else entry.usage for entry in group]
        elapsed = [scores.clocks[0].calibration for scores in scenarios if scores]
        effective = len(elapsed[0].population)
        cells = "".join(f"{_calibration_cell(c):<20}" for c in elapsed)
        line = f"{start}{effective:<9}{cells}".rstrip()
        notes = []
        if control:
            notes.append("contrôle")
        if multi[day]:
            notes.append(f"jour multi-sorties, {group[0].outing_id}")
        if notes:
            line += f" ({' ; '.join(notes)})"
        lines.append(line)
    return lines


def _model_aggregate_lines(entries: Sequence[ScoredPerformance]) -> list[str]:
    """Les agrégats d'usage sous l'écoulé de la synthèse (précision de D15, M4c-2) :
    par jeu, les cinq modèles côte à côte — ``L``, ``|L|``, ``max |C_k|``,
    ``q_usage``, chacun sur son propre effectif —, puis ``|L|`` sur l'ensemble commun
    du jeu (``common_row``)."""
    shown = (
        ReportMetric.LEVEL,
        ReportMetric.ABS_LEVEL,
        ReportMetric.MAX_ABS_PASSAGE_ERROR,
        ReportMetric.USAGE_TARGET,
    )
    tables = {
        model: {
            row.metric: row
            for row in aggregate_table(
                entries, Scenario.USAGE, ClockRole.ELAPSED, model
            )
            if row.regime_class is None
        }
        for model in REPORT_MODELS
    }
    common = common_row(
        entries, Scenario.USAGE, ClockRole.ELAPSED, ReportMetric.ABS_LEVEL
    )
    lines = [
        f"{'agrégats':<13}usage, écoulé ; moyenne à poids égal par performance "
        "(effectif) ; |L| commun : performances où les cinq modèles ont une valeur ; "
        "détail et motifs : rapport complet"
    ]
    for d, dataset in enumerate(DataSet):
        lines.append(
            _row(DATA_SET_LABELS[dataset], [MODEL_LABELS[m] for m in REPORT_MODELS])
        )
        for metric in shown:
            formatted = _metric_format(metric)
            lines.append(
                _row(
                    REPORT_METRIC_LABELS[metric],
                    [
                        _aggregate_cell(tables[model][metric].by_set[d], formatted)
                        for model in REPORT_MODELS
                    ],
                )
            )
        lines.append(
            _row(
                "|L| commun",
                [_aggregate_cell(value, _plain) for value in common.by_set[d]],
            )
        )
    return lines


def _summary_parts(
    run: BacktestRun | BacktestEvaluation, threshold: float
) -> tuple[list[str], list[str]]:
    """La synthèse **sans ses lignes du registre ni sa ligne du rapport**, calculée
    avant le RÉSULTAT (précision de D14, M4c-2 ; décision 10) : sa première ligne,
    puis le reste — provenance, sorties écartées, une ligne par sortie déclarée,
    calage, agrégats des cinq modèles, référence de répétabilité, diagnostics."""
    preparation = run.preparation
    declaration = preparation.declaration
    matching = declaration.matching
    models = ", ".join(MODEL_LABELS[model] for model in REPORT_MODELS)
    head = [
        f"{'backtest':<13}cinq modèles ({models}), protocole "
        f"{declaration.protocol_record} — commit {declaration.commit[:12]} ; "
        f"Δ {matching['score_step_m']:g} m, ε {matching['lateral_tolerance_m']:g} m, "
        f"r_c {matching['cluster_radius_m']:g} m",
    ]
    lines: list[str] = []
    read = preparation.manifest
    present = {outing.outing_id for outing in read.outings}
    others = {entry.outing_id for entry in read.refused} - present
    performances = declaration.performances
    lines.append(
        f"{'manifeste':<13}{read.source.identifier}   "
        f"sha256 {read.source.content_hash[:8]}… — "
        f"{_count(len(read.outings) + len(others), 'sortie', 'sorties')}, "
        f"{_count(len(performances), 'performance', 'performances')}"
    )
    curve = declaration.curve
    available_at = curve.available_at
    ages = [
        curve_age_days(available_at, p.performance.civil_date) for p in performances
    ]
    later = origins_before_curve(available_at, [p.origin for p in performances])
    lines += [
        f"{'courbe':<13}{curve.source.identifier}   "
        f"sha256 {curve.source.content_hash[:8]}… — "
        f"estimée le {civil_date(available_at).isoformat()}",
        f"{_INDENT}âge au jour J : de {_age(min(ages))} à {_age(max(ages))} jours ; "
        f"postérieure à l'origine de {_count(later, 'performance', 'performances')} "
        f"sur {len(performances)}",
        f"{_INDENT}mouvement historique non harmonisé ; biais d'opérateur de pente "
        "(0009, 0010 D6)",
    ]
    lines += [
        f"{'écartée':<13}{exclusion.outing_id} — {exclusion.reason}"
        for exclusion in declaration.exclusions
    ]
    lines += _performance_lines(run)
    lines += _calibration_lines(run)
    entries = scored_performances(run)
    lines += _model_aggregate_lines(entries)
    lines += _comparison_lines(run, entries)
    lines.append(
        f"{'diagnostics':<13}descentes roulantes et raides au seuil {threshold:.2f} ; "
        "géométrie usage − contrôle : rapport complet"
    )
    return head, lines


def _summary(
    parts: tuple[list[str], list[str]],
    declaration: int,
    result: int,
    seal: str,
    report_name: str,
) -> list[str]:
    """La synthèse (§ 6.3 et § 7.3 du brief M4b-5 ; § 6.6 du brief M4c-2) : les
    parties calculées avant le RÉSULTAT, les deux lignes du registre insérées après la
    première, puis la ligne du rapport."""
    head, rest = parts
    registry = [
        f"{'registre':<13}déclaration {declaration}, résultat {result} ; dernière "
        f"ligne sha256 {seal}",
        f"{_INDENT}à recopier au JOURNAL : l'empreinte de la dernière ligne scelle le "
        "registre",
    ]
    return [*head, *registry, *rest, f"{'rapport':<13}{report_name}"]


def _fold_causes(reference: RepeatabilityReference) -> list[str]:
    """Les causes d'un ``|L|`` de pli indisponible, par horloge (décision Q4) : les
    motifs comptés, puis les cellules nulles des ajustements de ses plis ; des
    horloges consécutives de même texte partagent la ligne."""
    texts: list[tuple[str, str]] = []
    for clock in reference.clocks:
        folds = clock.folds
        motifs = Counter(
            fold.level.unavailability for fold in folds if fold.level.value is None
        )
        if not motifs:
            continue
        counted = ", ".join(
            f"{motifs[motif]} {MISSING_LABELS[motif.value]}"
            for motif in Unavailability
            if motifs[motif]
        )
        unavailable = sum(motifs.values())
        text = (
            f"|L| indisponible sur {_count(unavailable, 'pli', 'plis')} sur "
            f"{len(folds)} : {counted}"
        )
        zeros: dict[tuple[int, int], set[date]] = {}
        order = {regime: r for r, regime in enumerate(RegimeClass)}
        for fold in folds:
            for fit in fold.fits:
                for day, k in fit.zero_cells:
                    zeros.setdefault((order[fit.regime_class], k), set()).add(day)
        if zeros:
            cells = ", ".join(
                f"{REGIME_CLASS_LABELS[list(RegimeClass)[r]]} k {k} "
                f"({', '.join(day.isoformat() for day in sorted(days))})"
                for (r, k), days in sorted(zeros.items())
            )
            text += f" ; cellules nulles : {cells}"
        texts.append((_clock_label(clock.clock), text))
    lines: list[str] = []
    while texts:
        labels = [texts[0][0]]
        text = texts[0][1]
        texts = texts[1:]
        while texts and texts[0][1] == text:
            labels.append(texts[0][0])
            texts = texts[1:]
        lines.append(f"{_INDENT}{', '.join(labels)} : {text}")
    return lines


def _fold_lines(reference: RepeatabilityReference) -> list[str]:
    """Sous l'écoulé, chaque pli et ses quatre classes : état de l'ajustement,
    effectifs d'apprentissage, ``μ₂``, scores du jour retiré."""
    lines: list[str] = []
    for fold in reference.clocks[0].folds:
        lines.append(
            f"{_INDENT}pli {fold.day.isoformat()} (écoulé) : support "
            f"{fold.support_count}, prévu {fold.predicted_count}, "
            f"L {_label(fold.level, _log)}"
        )
        for fit, score in zip(fold.fits, fold.classes, strict=True):
            state = (
                "disponible"
                if fit.unavailability is None
                else MISSING_LABELS[fit.unavailability.value]
            )
            if fit.contraction is not None:
                contraction = _plain(fit.contraction)
            elif fit.contraction_unavailability is not None:
                contraction = MISSING_LABELS[fit.contraction_unavailability.value]
            else:
                contraction = "—"
            outside = "" if score.contributes else " (hors de F)"
            lines.append(
                f"{_INDENT}  {REGIME_CLASS_LABELS[fit.regime_class]:<10}{state} ; "
                f"apprentissage {_count(fit.training_days, 'jour', 'jours')}, "
                f"{_count(fit.training_segments, 'segment', 'segments')}, "
                f"{_count(fit.training_cells, 'cellule', 'cellules')} ; "
                f"μ₂ {contraction} ; jour retiré "
                f"{_count(score.segment_count, 'segment', 'segments')}, "
                f"E_R {_label(score.log_ratio, _log)}, "
                f"D_R {_label(score.dispersion, _plain)}{outside}"
            )
    return lines


def _reference_lines(route_id: str, reference: RepeatabilityReference) -> list[str]:
    """La référence D8 d'un parcours, entière (décision Q4) : ses jours, les ``F``
    sous les onze horloges (une largeur commune aux deux tableaux), les causes d'un
    ``|L|`` de pli indisponible, puis les plis sous l'écoulé."""
    days = (
        "jours " + ", ".join(day.isoformat() for day in reference.days)
        if reference.days
        else "aucun jour"
    )
    head = f"{'référence':<13}{route_id} — {days}"
    if reference.multi_outing_days:
        multi = ", ".join(day.isoformat() for day in reference.multi_outing_days)
        head += f" ; jours multi-sorties écartés {multi}"
    if reference.single_contrast:
        head += " ; un seul contraste"

    def cell(value: MetricValue) -> str:
        return f"{_label(value, _plain)} (m {value.count})"

    levels = [
        ["|L|", *(f"{REGIME_CLASS_LABELS[r]} |E_R|" for r in RegimeClass)],
        *(
            [_clock_label(c.clock), cell(c.level), *(cell(v) for v in c.log_ratios)]
            for c in reference.clocks
        ),
    ]
    dispersions = [
        [f"{REGIME_CLASS_LABELS[r]} D_R" for r in RegimeClass],
        *(
            [_clock_label(c.clock), *(cell(v) for v in c.dispersions)]
            for c in reference.clocks
        ),
    ]
    values = [*levels[0], *dispersions[0]]
    values += [text for row in (*levels[1:], *dispersions[1:]) for text in row[1:]]
    width = max(20, max(len(text) for text in values) + 2)

    def table(header: list[str], rows: Sequence[list[str]]) -> list[str]:
        lines = [
            (_INDENT + " " * 16 + "".join(f"{h:<{width}}" for h in header)).rstrip()
        ]
        lines += [
            (
                _INDENT + f"{row[0]:<16}" + "".join(f"{c:<{width}}" for c in row[1:])
            ).rstrip()
            for row in rows
        ]
        return lines

    return [
        head,
        *table(levels[0], levels[1:]),
        *table(dispersions[0], dispersions[1:]),
        *_fold_causes(reference),
        *_fold_lines(reference),
    ]


def _outing_scenario(outing: OutingRun) -> tuple[str, ScenarioScores]:
    """Le scénario du rapport d'une sortie : l'usage, le contrôle sans référence."""
    usage = outing.scores.usage
    if usage is None:
        return SCENARIO_LABELS[Scenario.CONTROL], outing.scores.control
    return SCENARIO_LABELS[Scenario.USAGE], usage


def _subclass_count(count: int, subclass: DescentSubclass, under: bool) -> str:
    """``3 roulantes``, ``1 raide (trop peu représentée)``, ``2 raides (trop peu
    représentées)``, ``0 raide``."""
    text = _count(count, *SUBCLASS_LABELS[subclass])
    if under:
        text += " (trop peu représentée)" if count <= 1 else " (trop peu représentées)"
    return text


def _descent_lines(
    run: BacktestRun | BacktestEvaluation, threshold: float
) -> list[str]:
    """Les sous-classes de descente de chaque sortie scorée, puis leur total
    (précision de D6, M4b-5 ; diagnostic, ni cible ni garde-fou)."""
    lines = [
        f"{'descentes':<13}roulantes et raides au seuil {threshold:.2f} (0010 D6) ; "
        "diagnostic, ni cible ni garde-fou"
    ]
    totals: Counter[DescentSubclass] = Counter()
    for outing in run.outings:
        name, scenario = _outing_scenario(outing)
        observation = outing.scores.observation
        segments = observation.segments
        fractions = descent_fractions(outing.profile, segments)
        subclasses = descent_subclasses(segments, fractions, threshold)
        counts = Counter(subclass for subclass in subclasses if subclass is not None)
        totals.update(counts)
        clocks = report_clocks(outing.match)
        measured = [
            subclass_metrics(observation, scenario, subclasses, clock)
            for clock in clocks
        ]
        rolling, steep = measured[0]
        lines.append(
            f"{_INDENT}{outing.outing.outing_id}, {name} — "
            + _subclass_count(
                counts[DescentSubclass.ROLLING],
                DescentSubclass.ROLLING,
                rolling.underrepresented,
            )
            + ", "
            + _subclass_count(
                counts[DescentSubclass.STEEP],
                DescentSubclass.STEEP,
                steep.underrepresented,
            )
            + ", "
            + _subclass_count(
                counts[DescentSubclass.UNDECIDED], DescentSubclass.UNDECIDED, False
            )
        )
        lines.append(_row("", [_clock_label(clock) for clock in clocks]))
        for index, subclass in enumerate(
            (DescentSubclass.ROLLING, DescentSubclass.STEEP)
        ):
            label = SUBCLASS_LABELS[subclass][0]
            by_clock = [pair[index] for pair in measured]
            lines += [
                _row(f"{label} E_R", [_label(m.log_ratio, _log) for m in by_clock]),
                _row(f"{label} D_R", [_label(m.dispersion, _plain) for m in by_clock]),
                _row(f"{label} E_R−L", [_label(m.shape, _log) for m in by_clock]),
            ]
    lines.append(
        f"{_INDENT}total : "
        + ", ".join(
            _count(totals[subclass], *SUBCLASS_LABELS[subclass])
            for subclass in DescentSubclass
        )
    )
    return lines


def _geometry_lines(run: BacktestRun | BacktestEvaluation) -> list[str]:
    """Le diagnostic de géométrie de chaque sortie scorée (précision de D3, M4b-5) :
    ``G`` et ses quatre classes, ou « sans référence »."""
    lines = [
        f"{'géométrie':<13}usage − contrôle = ln(ΣP_usage / ΣP_contrôle) sur le "
        "support admis (0010 D3), v0 brut"
    ]
    header = ["G", *(REGIME_CLASS_LABELS[regime] for regime in RegimeClass)]
    rows: list[tuple[str, list[str] | None]] = []
    for outing in run.outings:
        diagnostic = geometry_diagnostic(outing.scores)
        if diagnostic is None:
            rows.append((outing.outing.outing_id, None))
            continue
        values = [diagnostic.total, *diagnostic.classes]
        rows.append((outing.outing.outing_id, [_label(v, _log) for v in values]))
    names = max([16, *(len(name) + 2 for name, _ in rows)])
    cells = [*header, *(c for _, row in rows if row is not None for c in row)]
    width = max(20, max(len(c) for c in cells) + 2)
    lines.append(
        (_INDENT + " " * names + "".join(f"{h:<{width}}" for h in header)).rstrip()
    )
    for name, row in rows:
        shown = (
            "sans référence" if row is None else "".join(f"{c:<{width}}" for c in row)
        )
        lines.append((_INDENT + f"{name:<{names}}" + shown).rstrip())
    return lines


def _detail_lines(
    run: BacktestRun | BacktestEvaluation, outing: OutingRun
) -> list[str]:
    """Le détail d'une sortie scorée : son en-tête, puis les sections 1 à 13 de
    ``mperf match --curve``, écrites par leurs fonctions (au caractère près)."""
    preparation = run.preparation
    declared = next(
        p
        for p in preparation.declaration.performances
        if outing.outing in p.performance.outings
    )
    performance = declared.performance
    entry = outing.outing
    dataset = "—" if entry.dataset is None else DATA_SET_LABELS[entry.dataset]
    label = (
        "sans étiquette" if entry.label is None else OUTING_LABEL_LABELS[entry.label]
    )
    available_at = preparation.declaration.curve.available_at
    origin = declared.origin
    at_day = curve_age_days(available_at, performance.civil_date)
    at_origin = curve_age_days(available_at, civil_date(origin))
    lines = [
        f"{'performance':<13}{performance.civil_date.isoformat()} — "
        f"{entry.outing_id} ; parcours {entry.route_id or '—'} ; jeu {dataset} ; "
        f"{label}",
        f"{_INDENT}origine o_j {origin.astimezone(PARIS):%Y-%m-%d %H:%M} (Paris) ; "
        f"âge de la courbe {_age(at_day)} jours au jour J, {_age(at_origin)} à o_j",
    ]
    if performance.is_multi_outing:
        lines.append(f"{_INDENT}jour multi-sorties : hors des agrégats (0010 D0)")
    if third_clock_is_elapsed(outing.match):
        lines.append(
            f"{_INDENT}(M+U) θ_haut égale l'écoulé : aucun arrêt confirmé sur le "
            "support admis"
        )
    buffer = io.StringIO()
    _print_match_report(
        outing.profile,
        outing.geometry,
        outing.trace,
        outing.series,
        preparation.declaration.matching,
        outing.match.points,
        out=buffer,
    )
    _print_segment_report(
        outing.match,
        stop_episodes(outing.partition, CENTRAL_CONVENTION_INDEX),
        out=buffer,
    )
    _print_passage_report(outing.passages, out=buffer)
    _print_v0_report(
        preparation.curve,
        outing.scores,
        outing.passages,
        report_clocks(outing.match),
        out=buffer,
    )
    return lines + buffer.getvalue().splitlines()


def _population_line(population: CalibrationPopulation) -> str:
    """``C_j`` d'une performance (``0010`` D2.4 ; précision de D15, M4c-2) : ses
    membres, « aucun » sans membre, puis ses exclusions et leur motif s'il y en a."""
    members = population.members
    days = ", ".join(day.isoformat() for day in members) if members else "aucun"
    line = f"{'calage':<13}C_j {_count(len(members), 'membre', 'membres')} : {days}"
    if population.excluded:
        excluded = ", ".join(
            f"{exclusion.civil_date.isoformat()} {EXCLUSION_LABELS[exclusion.reason]}"
            for exclusion in population.excluded
        )
        line += f" ; exclues : {excluded}"
    return line


def _calibration_text(calibration: ModelCalibration) -> str:
    """Le calage sous une horloge (précision de D15, M4c-2) : ``C_j^eff``, ``β`` et la
    cellule du calage ; ``non calé`` ; ``erreur du modèle, C_j^eff <n>`` ; suivi des
    retraits et de leur motif s'il y en a."""
    effective = len(calibration.population)
    status = calibration.unavailability
    if status is None:
        assert calibration.beta is not None  # contrat de ModelCalibration
        text = (
            f"C_j^eff {effective}, β {_log(calibration.beta)}, "
            f"{_calibration_cell(calibration)}"
        )
    elif status is Unavailability.NOT_CALIBRATED:
        text = MISSING_LABELS[status.value]
    else:
        text = f"{MISSING_LABELS[status.value]}, C_j^eff {effective}"
    if calibration.withdrawals:
        withdrawals = ", ".join(
            f"{withdrawal.civil_date.isoformat()} "
            f"{MISSING_LABELS[withdrawal.reason.value]}"
            for withdrawal in calibration.withdrawals
        )
        text += f" (retraits : {withdrawals})"
    return text


def _calibrated_scenario_lines(
    label: str, scores: CalibratedScenarioScores, clocks: Sequence[Clock]
) -> list[str]:
    """Un scénario d'un modèle calé (précision de D15, M4c-2) : la source de sa
    prévision, son calage sous chaque horloge du rapport, les dix-sept lignes de
    métriques — le libellé du statut sous une horloge non calée —, puis, en usage,
    ``max |C_k|``, ``max C_k``, ``min C_k`` et ``q_usage`` (D7.3, D7.4). Ni
    enveloppe, ni diagnostic, ni détail des points (D9.2 ; décision 9)."""
    shown = [scores.clocks[CLOCKS.index(clock)] for clock in clocks]
    lines = [f"{label:<13}{scores.forecast.source.identifier}"]
    lines += [
        f"{_INDENT}{_clock_label(clock)} : {_calibration_text(entry.calibration)}"
        for clock, entry in zip(clocks, shown, strict=True)
    ]
    status = [
        None
        if entry.calibration.unavailability is None
        else MISSING_LABELS[entry.calibration.unavailability.value]
        for entry in shown
    ]

    def cells(values: Sequence[str]) -> list[str]:
        return [
            value if motif is None else motif
            for value, motif in zip(values, status, strict=True)
        ]

    supports = [None if e.scores is None else e.scores.support for e in shown]
    lines.append(_row("", [_clock_label(clock) for clock in clocks]))
    lines += [_row(name, cells(row)) for name, row in _support_rows(supports)]
    if scores.scenario is not Scenario.USAGE:
        return lines
    errors = [None if e.scores is None else e.scores.passage_errors for e in shown]
    targets = [None if e.scores is None else e.scores.usage_target for e in shown]
    lines += [
        _row(
            "max |C_k|",
            cells(
                [
                    "" if e is None else _cell(e.max_abs_error_s, _abs_seconds)
                    for e in errors
                ]
            ),
        ),
        _row(
            "max C_k",
            cells(
                ["" if e is None else _cell(e.max_error_s, _seconds) for e in errors]
            ),
        ),
        _row(
            "min C_k",
            cells(
                ["" if e is None else _cell(e.min_error_s, _seconds) for e in errors]
            ),
        ),
        _row(
            "q_usage",
            cells(["" if t is None else _cell(t.q_usage, _plain) for t in targets]),
        ),
    ]
    return lines


_CALIBRATION_RULES: Mapping[ModelKind, str] = {
    ModelKind.V0_RECALIBRATED: "v0 brut ÷ effort e",
    ModelKind.CONSTANT_SPEED: "prévision non calée × facteur a",
    ModelKind.NAISMITH: "prévision non calée × facteur a",
    ModelKind.TOBLER: "prévision non calée × facteur a",
}


def _calibrated_detail_lines(
    run: BacktestRun | BacktestEvaluation, outing: OutingRun
) -> list[str]:
    """Après le détail de v0 brut d'une sortie scorée (précision de D15, M4c-2) :
    ``C_j`` de sa performance, puis chaque modèle calé — usage (ou « sans référence »)
    et contrôle, sous les horloges du rapport."""
    outing_id = outing.outing.outing_id
    performance = next(
        p for p in run.calibration if any(e.outing_id == outing_id for e in p.outings)
    )
    clocks = report_clocks(outing.match)
    lines = [_population_line(performance.population)]
    for entry in performance.outings:
        if entry.outing_id != outing_id:
            continue
        lines += _calibrated_model_lines(entry, clocks)
    return lines


def _calibrated_model_lines(
    entry: CalibratedOutingScores, clocks: Sequence[Clock]
) -> list[str]:
    model = entry.control.model
    lines = [
        f"{'modèle':<13}{MODEL_LABELS[model]} — {_CALIBRATION_RULES[model]} ; sans "
        "enveloppe (0010 D9.2)"
    ]
    usage, control = SCENARIO_LABELS[Scenario.USAGE], SCENARIO_LABELS[Scenario.CONTROL]
    if entry.usage is None:
        lines.append(f"{usage:<13}sans référence : scénario contrôle seul (0010 D3)")
    else:
        lines += _calibrated_scenario_lines(usage, entry.usage, clocks)
    lines += _calibrated_scenario_lines(control, entry.control, clocks)
    return lines


def _report_body(run: BacktestRun | BacktestEvaluation, threshold: float) -> list[str]:
    """Le corps du rapport complet, calculé avant le RÉSULTAT (précision de D14,
    M4c-2 ; § 6.6 du brief M4c-2) : les tables d'agrégats de chaque modèle (usage puis
    contrôle, sous les trois rôles d'horloge) ; la référence D8 de chaque parcours ;
    les descentes ; la géométrie ; le détail de chaque sortie scorée, v0 brut puis les
    modèles calés ; les sorties non scorées ; la légende."""
    lines: list[str] = []
    entries = scored_performances(run)
    for model in REPORT_MODELS:
        for scenario in (Scenario.USAGE, Scenario.CONTROL):
            for role in ClockRole:
                lines.append(
                    f"{'agrégats':<13}{MODEL_LABELS[model]} — "
                    f"{SCENARIO_LABELS[scenario]}, {CLOCK_ROLE_LABELS[role]}"
                )
                table = aggregate_table(entries, scenario, role, model)
                lines += _aggregate_lines(table, with_missing=True)
    for route_id, reference in run.references:
        lines += _reference_lines(route_id, reference)
    lines += _descent_lines(run, threshold)
    lines += _geometry_lines(run)
    for outing in run.outings:
        lines += _detail_lines(run, outing)
        lines += _calibrated_detail_lines(run, outing)
    lines += [
        f"{'non scorée':<13}{exclusion.outing_id} — {exclusion.reason}"
        for exclusion in run.unscored
    ]
    lines.append(f"{'légende':<13}{LEGEND[0]}")
    lines += [f"{_INDENT}{text}" for text in LEGEND[1:]]
    return lines


def _full_report(summary: Sequence[str], body: Sequence[str]) -> str:
    """Le rapport complet (§ 6.3 et § 7.4 du brief M4b-5 ; § 6.6 du brief M4c-2) : la
    synthèse, puis le corps. Aucune ligne vide, aucune espace en fin de ligne."""
    return "\n".join([*summary, *body]) + "\n"


def _given(args: argparse.Namespace, options: dict[str, str]) -> dict[str, float]:
    """Valeurs passées en ligne de commande ; les autres restent aux défauts."""
    return {
        name: getattr(args, name)
        for name in options.values()
        if getattr(args, name) is not None
    }


def _run_profile(args: argparse.Namespace) -> None:
    parameters = ParameterSet(PROFILE_PARAMETER_SPECS, _given(args, _PROFILE_OPTIONS))
    read = read_gpx(args.path)
    result = build_profile_with_diagnostics(read.route, parameters)
    if args.csv:
        _print_csv(result.profile)
        return
    raw_parameters = ParameterSet(
        PROFILE_PARAMETER_SPECS, {**parameters.values, "smoothing_window_m": 0}
    )
    _print_report(read, result, build_profile(read.route, raw_parameters))


def _run_project(args: argparse.Namespace) -> None:
    grid_parameters = ParameterSet(
        PROFILE_PARAMETER_SPECS, _given(args, _PROFILE_OPTIONS)
    )
    model_parameters = ParameterSet(
        PROJECTION_PARAMETER_SPECS, _given(args, _PROJECTION_OPTIONS)
    )
    read = read_gpx(args.path)
    result = build_profile_with_diagnostics(read.route, grid_parameters)
    read_result = read_curve(args.curve, model_parameters)
    projection, diagnostics = project_with_diagnostics(
        result.profile,
        read_result.curve,
        model_parameters,
        curve_ref=read_result.curve_ref,
        endpoints=route_endpoints(read.route),
    )
    if args.csv:
        write_passages_csv(projection, sys.stdout)
    else:
        _print_projection_report(result, read_result, projection, diagnostics)


def _run_match(args: argparse.Namespace) -> None:
    parameters = ParameterSet(MATCHING_PARAMETER_SPECS, _given(args, _MATCHING_OPTIONS))
    # La courbe est lue avant toute sortie : une erreur de lecture laisse stdout vide.
    curve_read = None
    if args.curve is not None:
        curve_read = read_curve(args.curve, ParameterSet(PROJECTION_PARAMETER_SPECS))
    read = read_gpx(args.reference)
    profile = build_profile(read.route, ParameterSet(PROFILE_PARAMETER_SPECS))
    geometry = reference_geometry(read.route)
    trace = read_trace([args.trace])
    series = build_series(trace)
    partition = clock_partition(trace, series)
    result = match_trace(geometry, profile, trace, series, partition, parameters)
    passages = observe_passages(result, geometry, profile, trace, series, partition)
    _print_match_report(profile, geometry, trace, series, parameters, result.points)
    _print_segment_report(result, stop_episodes(partition, CENTRAL_CONVENTION_INDEX))
    _print_passage_report(passages)
    if curve_read is None:
        return
    outing = v0_scores(
        None if args.no_reference else profile,
        trace,
        result,
        passages,
        partition,
        curve_read.curve,
        curve_ref=curve_read.curve_ref,
    )
    _print_v0_report(curve_read, outing, passages, report_clocks(result))


def _run_backtest(args: argparse.Namespace) -> int:
    """``mperf backtest`` (§ 6.3 du brief M4b-5 ; § 6.6 du brief M4c-2), dans cet
    ordre : le seuil des descentes ; ``MPA_DATA_DIR`` ; l'état git du paquet exécuté,
    un arbre modifié refusé ; le nom du rapport prévu, refusé s'il existe ; la
    préparation ; l'exécution enregistrée, qui publie l'empreinte de la DÉCLARATION
    dès son ajout (première ligne de la sortie standard) et calcule la synthèse et le
    corps du rapport avant le RÉSULTAT (une erreur y est un ÉCHEC technique) ; puis
    le rapport écrit (une erreur ou une interruption y publie le sceau, et retire le
    fichier commencé) ; la synthèse."""
    given = {}
    if args.descent_threshold is not None:
        given["descent_subclass_threshold"] = args.descent_threshold
    threshold = ParameterSet(REPORT_PARAMETER_SPECS, given)[
        "descent_subclass_threshold"
    ]
    data = data_dir()
    state = git_state(Path(mountain_perf.__file__).resolve().parent)
    if state.modified:
        print(MODIFIED_TREE_ERROR, file=sys.stderr)
        return 1
    registry = data / REGISTRY_DIR
    events = len(read_registry(registry).events) if registry.exists() else 0
    planned = _report_name(events + 2)
    if (data / planned).exists():
        print(REPORT_EXISTS_ERROR.format(name=planned), file=sys.stderr)
        return 1
    preparation = prepare_backtest(
        args.manifest, args.curve, commit=state.commit, tree_modified=False
    )
    computed: list[tuple[tuple[list[str], list[str]], list[str]]] = []

    def announce(event: RegistryEvent, seal: str) -> None:
        line = DECLARATION_RECORDED.format(
            label=f"{'déclaration':<13}", number=event.number, seal=seal
        )
        print(line, flush=True)

    def compute(evaluation: BacktestEvaluation) -> None:
        parts = _summary_parts(evaluation, threshold)
        computed.append((parts, _report_body(evaluation, threshold)))

    run = run_backtest(
        preparation, registry, on_declaration=announce, before_result=compute
    )
    ((parts, body),) = computed
    name = _report_name(run.result_event.number)
    summary = _summary(
        parts, run.declaration_event.number, run.result_event.number, run.seal, name
    )
    created: Path | None = None
    try:
        text = _full_report(summary, body)
        (data / REPORTS_DIR).mkdir(exist_ok=True)
        with (data / name).open("x", encoding="utf-8", newline="\n") as report:
            created = data / name
            report.write(text)
    except (Exception, KeyboardInterrupt) as error:
        if created is not None:
            # Un rapport interrompu pendant son écriture ne garde pas son nom : le
            # message dit « non écrit » (décision Q17 ; relecture de la PR #20).
            with contextlib.suppress(OSError):
                created.unlink()
        message = REPORT_NOT_WRITTEN_ERROR.format(
            number=run.result_event.number,
            seal=run.seal,
            name=name,
            reason=failure_reason(error),
        )
        print(message, file=sys.stderr)
        return 1
    for line in summary:
        print(line)
    return 0


def _write_utf8() -> None:
    """Sorties standard en UTF-8, quel que soit l'encodage de la console.

    Une sortie redirigée sous Windows s'ouvre en cp1252, qui n'a ni ``→``, ni ``−``,
    ni ``Δ``, ni ``ε``, ni ``↔`` : ``print`` lèverait ``UnicodeEncodeError``, aide
    comprise — d'où l'appel avant la lecture des arguments. Seul l'encodage change :
    le gestionnaire d'erreurs du flux est gardé, ``reconfigure`` le remettrait sinon
    à ``strict``. Un flux qui n'est pas un ``io.TextIOWrapper`` est laissé tel quel.
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors=stream.errors)


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée mperf ; les erreurs d'entrée sont lisibles, sans traceback."""
    _write_utf8()
    parser = argparse.ArgumentParser(prog="mperf")
    commands = parser.add_subparsers(dest="command", required=True)
    profile_parser = commands.add_parser(
        "profile", help="Construire le profil d'un GPX"
    )
    project_parser = commands.add_parser(
        "project", help="Projeter des temps de passage sur un GPX"
    )
    for subparser in (profile_parser, project_parser):
        subparser.add_argument("path", type=Path, metavar="fichier.gpx")
        for option, parameter in _PROFILE_OPTIONS.items():
            subparser.add_argument(option, dest=parameter, type=float, metavar="F")
    profile_parser.add_argument(
        "--csv", action="store_true", help="Grille CSV sur stdout"
    )
    # --curve est exigé, mais pas par argparse : sa sortie d'usage vaut 2, et le
    # contrat de la commande est de renvoyer 1 sur une erreur d'entrée.
    project_parser.add_argument(
        "--curve", type=Path, metavar="fichier.csv", help="Courbe allure↔pente"
    )
    for option, parameter in _PROJECTION_OPTIONS.items():
        project_parser.add_argument(option, dest=parameter, type=float, metavar="F")
    project_parser.add_argument(
        "--csv", action="store_true", help="Tableau des passages sur stdout"
    )
    match_parser = commands.add_parser(
        "match", help="Apparier une trace réalisée aux points de score d'un tracé"
    )
    match_parser.add_argument("reference", type=Path, metavar="référence.gpx")
    match_parser.add_argument("trace", type=Path, metavar="trace.gpx")
    for option, parameter in _MATCHING_OPTIONS.items():
        match_parser.add_argument(option, dest=parameter, type=float, metavar="F")
    match_parser.add_argument(
        "--curve",
        type=Path,
        metavar="courbe.csv",
        help="Courbe allure↔pente : scores de v0 brut (sections 11 à 13)",
    )
    match_parser.add_argument(
        "--no-reference",
        action="store_true",
        help="Sortie sans référence : la référence est la trace elle-même",
    )
    backtest_parser = commands.add_parser(
        "backtest", help="Exécution enregistrée du backtest de v0 brut et rapport D15"
    )
    backtest_parser.add_argument("manifest", type=Path, metavar="manifeste.json")
    # --curve est exigé, mais pas par argparse (code 1, comme mperf project).
    backtest_parser.add_argument(
        "--curve",
        type=Path,
        metavar="courbe.csv",
        help="Courbe allure↔pente, entrée déclarée de l'exécution (0010 D2.6)",
    )
    backtest_parser.add_argument(
        "--descent-threshold",
        dest="descent_threshold",
        type=float,
        metavar="F",
        help="Seuil des descentes roulantes et raides (diagnostic de 0010 D6)",
    )
    args = parser.parse_args(argv)
    if args.command == "project" and args.curve is None:
        print(project_parser.format_usage(), file=sys.stderr, end="")
        print(
            "Erreur : --curve est obligatoire. Une courbe implicite rendrait la "
            "projection non reproductible.",
            file=sys.stderr,
        )
        return 1
    if args.command == "backtest" and args.curve is None:
        print(backtest_parser.format_usage(), file=sys.stderr, end="")
        print(BACKTEST_CURVE_ERROR, file=sys.stderr)
        return 1
    try:
        if args.command == "backtest":
            return _run_backtest(args)
        if args.command == "project":
            _run_project(args)
        elif args.command == "match":
            # Contrôlé toujours, avant toute sortie (0010 D3 ; § 6.7 du brief M4b-2).
            if args.no_reference and not os.path.samefile(args.reference, args.trace):
                print(NO_REFERENCE_ERROR, file=sys.stderr)
                return 1
            _run_match(args)
        else:
            _run_profile(args)
    except (
        GpxError,
        TraceError,
        ProfileError,
        CurveError,
        ContractError,
        OSError,
        ConfigError,
        BacktestError,
        ManifestError,
        RegistryError,
    ) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1
    return 0
