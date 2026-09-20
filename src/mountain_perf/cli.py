"""Commandes mperf : lecture, appel de la bibliothèque et affichage.

Aucun calcul ici (règle 7 de ``CLAUDE.md``) : la commande lit des fichiers, appelle
``mountain_perf``, et met en forme. Si elle calculait quelque chose, c'est que ça
manquerait dans ``src/``.
"""

import argparse
import csv
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

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
from mountain_perf.model import (
    PROJECTION_PARAMETER_SPECS,
    CurveError,
    CurveReadResult,
    ProjectionDiagnostics,
    project_with_diagnostics,
    read_curve,
    route_endpoints,
)
from mountain_perf.schemas import ParameterSet, Projection, RouteProfile
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


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée mperf ; les erreurs d'entrée sont lisibles, sans traceback."""
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
        else:
            _run_profile(args)
    except (GpxError, ProfileError, CurveError, ContractError, OSError) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1
    return 0
