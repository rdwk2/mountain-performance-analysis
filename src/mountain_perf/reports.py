"""Les textes des rapports de ``mperf profile`` et ``mperf project``, communs à la
commande et à l'interface : la commande les imprime, l'interface les affiche tels
quels."""

from mountain_perf.gpx import ProfileBuildResult
from mountain_perf.runs import RouteProjection
from mountain_perf.schemas import Projection
from mountain_perf.units import (
    format_count,
    format_duration,
    format_grade,
    format_share,
)


def grid_lines(result: ProfileBuildResult) -> tuple[str, str]:
    """Les lignes « grille » et « lissage » des rapports de ``mperf profile`` et
    ``mperf project``."""
    profile = result.profile
    grid = (
        f"grille       {format_count(profile.distance_m[-1])} m, "
        f"{format_count(len(profile.distance_m))} points, "
        f"pas {format_count(profile.step_m)} m"
    )
    effective = f"{format_count(result.effective_smoothing_window_m)} m effectif"
    if result.smoothing_point_count == 1:
        effective = f"aucun lissage ({effective}, 1 point)"
    else:
        effective += f" ({result.smoothing_point_count} points)"
    smoothing = (
        f"lissage      {format_count(profile.build_parameters['smoothing_window_m'])} "
        f"m demandé → {effective}"
    )
    return grid, smoothing


def projection_summary_lines(run: RouteProjection) -> tuple[str, ...]:
    """La synthèse du rapport de ``mperf project``, de « fichier » à « passages »."""
    result, read_result = run.built, run.curve
    projection, diagnostics = run.projection, run.diagnostics
    profile = result.profile
    estimation = read_result.curve.estimation
    source = read_result.source
    low, high = read_result.kept_grade_range
    threshold = projection.parameters["curve_min_support_min"]
    total_s = projection.passages[-1].arrival_s
    resolved = len(profile.resolved_points)
    return (
        f"fichier      {profile.source.identifier}   "
        f"sha256 {profile.source.content_hash[:8]}…",
        f"courbe       {source.identifier}   sha256 {source.content_hash[:8]}…",
        f"             {estimation.activity_count} activités, "
        f"{estimation.date_from} → {estimation.date_to}",
        *grid_lines(result),
        f"support      {read_result.bin_count_read} tranches lues, "
        f"{read_result.bin_count_kept} retenues (>= {threshold:g} min), "
        f"plage {format_grade(low)} … {format_grade(high)}",
        f"             pentes rencontrées : {format_grade(diagnostics.grade_min)} … "
        f"{format_grade(diagnostics.grade_max)}",
        f"             hors support : "
        f"{format_share(diagnostics.out_of_support_distance_share)} de la distance, "
        f"{format_share(diagnostics.out_of_support_time_share)} du temps",
        f"effort       {projection.parameters['effort']:.2f}",
        f"durée        {format_duration(total_s)}   "
        f"(D+ {format_count(profile.cumulative_ascent_m[-1])} m / "
        f"D− {format_count(profile.cumulative_descent_m[-1])} m)",
        f"passages     {len(projection.passages)}   ({resolved} "
        f"lieu{'x' if resolved != 1 else ''} résolu{'s' if resolved != 1 else ''}, "
        "départ et arrivée synthétisés)",
    )


def passage_lines(projection: Projection) -> tuple[str, ...]:
    """La liste des passages du rapport de ``mperf project`` : distance, nom, temps."""
    width = max(len(format_count(p.point.distance_m)) for p in projection.passages)
    lines = []
    for passage in projection.passages:
        distance = f"{format_count(passage.point.distance_m)} m".rjust(width + 2)
        name = passage.point.point.name.ljust(22)
        lines.append(f"  {distance}   {name} {format_duration(passage.arrival_s)}")
    return tuple(lines)
