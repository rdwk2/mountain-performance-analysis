"""Commandes mperf : lecture, appel de la bibliothèque et affichage.

Aucun calcul ici (règle 7 de ``CLAUDE.md``) : la commande lit des fichiers, appelle
``mountain_perf``, et met en forme. Si elle calculait quelque chose, c'est que ça
manquerait dans ``src/``.
"""

import argparse
import csv
import io
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

from mountain_perf.backtest import (
    MATCHING_PARAMETER_SPECS,
    ReferenceGeometry,
    TraceSeries,
    build_series,
    clock_partition,
    dplus_per_km,
    match_trace,
    observe_passages,
    reference_geometry,
    stop_episodes,
)
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
    CENTRAL_CONVENTION_INDEX,
    AdmittedTotals,
    ClockTotals,
    EpisodeOutcome,
    MatchResult,
    ParameterSet,
    PassageMatchResult,
    PassageRole,
    PassageStatus,
    PointStatus,
    Projection,
    RecordedTrace,
    Regime,
    RouteProfile,
    ScorePointObservation,
    SegmentExclusion,
    StopEpisode,
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
) -> None:
    """Sections 1 à 4 du rapport d'appariement (§ 5a.9 du brief M4a-2a)."""
    source = profile.source
    print(f"référence    {source.identifier}   sha256 {source.content_hash[:8]}…")
    print(
        f"             L {_number(geometry.length_m)} m, "
        f"D+/km {_number(dplus_per_km(profile))} m/km"
    )
    print(f"trace        {trace.sources[0].identifier}")
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
        f"{_count(sum(series.gap_after), 'trou', 'trous')}"
    )
    departure, arrival = points[0], points[-1]
    line = f"départ       {POINT_STATUS_LABELS[departure.status]}"
    if departure.time_s is not None:
        line += (
            f" — b_0 {departure.effective_m:.2f} m, "
            f"durée avant départ {format_duration(departure.time_s)}"
        )
    print(line)
    line = f"arrivée      {POINT_STATUS_LABELS[arrival.status]}"
    if arrival.time_s is not None:
        line += (
            f" — instant {format_duration(arrival.time_s)}, "
            f"b_K {arrival.effective_m:.2f} m"
        )
        if arrival.status is PointStatus.ANCHORED:
            # L − b_K est l'opposé du décalage d'ancrage que porte le contrat.
            line += f", L − b_K {0.0 - arrival.anchoring_offset_m:.2f} m"
    print(line)
    print(
        f"points       Δ {parameters['score_step_m']:g} m, "
        f"ε {parameters['lateral_tolerance_m']:g} m, "
        f"r_c {parameters['cluster_radius_m']:g} m — {len(points)} points"
    )
    counts = Counter(point.status for point in points)
    print(
        "             "
        + ", ".join(
            f"{label} {counts[status]}" for status, label in POINT_STATUS_LABELS.items()
        )
    )
    ambiguous = [
        f"k = {point.index} (s_k = {_number(point.nominal_m)} m)"
        for point in points
        if point.status is PointStatus.AMBIGUOUS
    ]
    print(f"             ambigus : {', '.join(ambiguous) or 'aucun'}")


def _durations(totals: ClockTotals | AdmittedTotals) -> str:
    """``M / S / U`` d'un jeu de totaux, en ``format_duration``."""
    return " / ".join(
        format_duration(value)
        for value in (totals.moving_s, totals.stopped_s, totals.undetermined_s)
    )


def _print_segment_report(result: MatchResult, episodes: Sequence[StopEpisode]) -> None:
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
    print(f"segments     {counts[None]} admis sur {len(segments)}")
    print(f"             {', '.join(motifs[:2])}")
    print(f"             {', '.join(motifs[2:])}")
    print(f"             ancrage exclu {coverage.anchoring_excluded_m:.2f} m")
    regimes = ", ".join(
        f"{label} {_coverage_percent(coverage.regime_fraction(regime))}"
        for regime, label in REGIME_LABELS.items()
    )
    print(f"couverture   {_coverage_percent(coverage.fraction)} — {regimes}")
    print(f"             écoulé admis {format_duration(coverage.admitted_elapsed_s)}")
    excluded_s = {
        SegmentExclusion.GAP: coverage.excluded_gap_s,
        SegmentExclusion.LENGTH_RATIO: coverage.excluded_length_ratio_s,
        SegmentExclusion.INTERIOR_DEVIATION: coverage.excluded_interior_deviation_s,
    }
    times = ", ".join(
        f"{SEGMENT_EXCLUSION_LABELS[exclusion]} {format_duration(duration_s)}"
        for exclusion, duration_s in excluded_s.items()
    )
    print(f"             temps exclus : {times}")
    unknown = _count(counts[SegmentExclusion.UNOBSERVED_BOUND], "segment", "segments")
    print(f"             durées inconnues : {unknown}")
    end_s = coverage.prefix_end_s
    print(
        "préfixe      "
        f"{_count(coverage.prefix_segment_count, 'segment', 'segments')}, "
        f"b_m {coverage.prefix_end_m:.2f} m, "
        f"t*_m {'non daté' if end_s is None else format_duration(end_s)}, "
        f"dernier passage {coverage.prefix_last_passage or 'aucun'}"
    )
    print("horloges     M / S / U de la trace, puis du support admis")
    for k, (trace, admitted) in enumerate(
        zip(result.trace_totals, result.admitted_totals, strict=True)
    ):
        print(
            f"             θ{k + 1}  trace {_durations(trace)}"
            f"   admis {_durations(admitted)}"
        )
    low, high = result.low_convention_index, result.high_convention_index
    interval = result.admitted_sensitivity_range_s
    if low is None or high is None or interval is None:
        print("             θ_bas, θ_haut, I_sens,A : aucun segment admis")
    else:
        print(
            f"             θ_bas θ{low + 1}, θ_haut θ{high + 1}, I_sens,A "
            f"[{format_duration(interval[0])} ; {format_duration(interval[1])}]"
        )
    stopped_s = result.trace_totals[CENTRAL_CONVENTION_INDEX].stopped_s
    print(
        f"épisodes     sous θ_c : {_count(len(episodes), 'épisode', 'épisodes')}, "
        f"{format_duration(stopped_s)}"
    )


def _print_passage_report(result: PassageMatchResult) -> None:
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
        f"{statuses} ; comparables {comparables}"
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
        print(f"{line} ; {end}")
    outcomes = Counter(attribution.outcome for attribution in result.episodes)
    print(
        "             épisodes θ_c : "
        f"attribués {outcomes[EpisodeOutcome.ATTRIBUTED]}, "
        f"sans candidate {outcomes[EpisodeOutcome.NO_CANDIDATE]}, "
        f"non attribués {outcomes[EpisodeOutcome.TIE]}"
    )
    for attribution in result.episodes:
        if attribution.outcome is EpisodeOutcome.TIE:
            episode = attribution.episode
            print(
                f"             non attribué [{format_duration(episode.start_s)} ; "
                f"{format_duration(episode.end_s)}]"
            )


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
    args = parser.parse_args(argv)
    if args.command == "project" and args.curve is None:
        print(project_parser.format_usage(), file=sys.stderr, end="")
        print(
            "Erreur : --curve est obligatoire. Une courbe implicite rendrait la "
            "projection non reproductible.",
            file=sys.stderr,
        )
        return 1
    try:
        if args.command == "project":
            _run_project(args)
        elif args.command == "match":
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
    ) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1
    return 0
