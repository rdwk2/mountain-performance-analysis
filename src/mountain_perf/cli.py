"""Commande M2 : lecture, appel de la bibliothèque et affichage des diagnostics."""

import argparse
import csv
import sys
from collections.abc import Sequence
from pathlib import Path

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
from mountain_perf.schemas import ParameterSet, RouteProfile
from mountain_perf.validation import ContractError

_PROFILE_OPTIONS = {
    "--step-m": "grid_step_m",
    "--smoothing-m": "smoothing_window_m",
    "--max-offset-m": "point_match_max_offset_m",
    "--min-separation-m": "point_match_min_separation_m",
}


def _number(value: float) -> str:
    """Entiers d'affichage, avec espaces ASCII pour séparer les milliers."""
    return f"{value:,.0f}".replace(",", " ")


def _print_csv(profile: RouteProfile) -> None:
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(("distance_m", "elevation_m", "grade"))
    grade = profile.grade
    for i, (distance_m, elevation_m) in enumerate(
        zip(profile.distance_m, profile.elevation_m, strict=True)
    ):
        writer.writerow((distance_m, elevation_m, grade[i] if i < len(grade) else ""))


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


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée mperf ; les erreurs d'entrée sont lisibles, sans traceback."""
    parser = argparse.ArgumentParser(prog="mperf")
    commands = parser.add_subparsers(dest="command", required=True)
    profile_parser = commands.add_parser(
        "profile", help="Construire le profil d'un GPX"
    )
    profile_parser.add_argument("path", type=Path, metavar="fichier.gpx")
    for option, parameter in _PROFILE_OPTIONS.items():
        profile_parser.add_argument(option, dest=parameter, type=float, metavar="F")
    profile_parser.add_argument(
        "--csv", action="store_true", help="Grille CSV sur stdout"
    )
    args = parser.parse_args(argv)
    try:
        parameters = ParameterSet(
            PROFILE_PARAMETER_SPECS,
            {
                name: getattr(args, name)
                for name in _PROFILE_OPTIONS.values()
                if getattr(args, name) is not None
            },
        )
        read = read_gpx(args.path)
        result = build_profile_with_diagnostics(read.route, parameters)
        if args.csv:
            _print_csv(result.profile)
        else:
            raw_parameters = ParameterSet(
                PROFILE_PARAMETER_SPECS,
                {
                    **parameters.values,
                    "smoothing_window_m": 0,
                },
            )
            _print_report(read, result, build_profile(read.route, raw_parameters))
    except (GpxError, ProfileError, ContractError, OSError) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1
    return 0
