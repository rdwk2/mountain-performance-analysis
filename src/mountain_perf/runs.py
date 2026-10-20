"""Les enchaînements des commandes, communs à ``mperf`` et à l'interface.

Une commande et une page qui font la même chose appellent la même fonction, donc dans
le même ordre, et la même erreur sort la première. (M5-2 y ajoutera celui de
``mperf match``.)
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from mountain_perf.gpx import (
    PROFILE_PARAMETER_SPECS,
    GpxReadResult,
    ProfileBuildResult,
    build_profile_with_diagnostics,
    read_gpx,
)
from mountain_perf.model import (
    PROJECTION_PARAMETER_SPECS,
    CurveReadResult,
    ProjectionDiagnostics,
    project_with_diagnostics,
    read_curve,
    route_endpoints,
)
from mountain_perf.schemas import ParameterSet, Projection


@dataclass(frozen=True)
class RouteProjection:
    """Tout ce que ``mperf project`` lit et calcule : le GPX lu, le profil et ses
    diagnostics, la courbe lue, la projection et ses diagnostics."""

    read: GpxReadResult
    built: ProfileBuildResult
    curve: CurveReadResult
    projection: Projection
    diagnostics: ProjectionDiagnostics


def project_route(
    route_path: Path,
    curve_path: Path,
    profile_values: Mapping[str, float],
    projection_values: Mapping[str, float],
) -> RouteProjection:
    """Projette le tracé ``route_path`` avec la courbe ``curve_path``.

    Dans l'ordre de ``mperf project`` : les deux jeux de paramètres (les valeurs
    absentes prennent le défaut de leur spec), la lecture du GPX, le profil, la lecture
    de la courbe, la projection. Les erreurs remontent telles quelles.
    """
    grid_parameters = ParameterSet(PROFILE_PARAMETER_SPECS, profile_values)
    model_parameters = ParameterSet(PROJECTION_PARAMETER_SPECS, projection_values)
    read = read_gpx(route_path)
    built = build_profile_with_diagnostics(read.route, grid_parameters)
    curve = read_curve(curve_path, model_parameters)
    projection, diagnostics = project_with_diagnostics(
        built.profile,
        curve.curve,
        model_parameters,
        curve_ref=curve.curve_ref,
        endpoints=route_endpoints(read.route),
    )
    return RouteProjection(read, built, curve, projection, diagnostics)
