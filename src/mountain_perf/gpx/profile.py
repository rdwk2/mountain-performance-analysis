"""Profil horizontal : rééchantillonner, puis lisser, puis résoudre les lieux.

Les défauts des paramètres sont provisoires, à caler sur des fichiers réels après
M2. Le profil n'est pas invariant au changement de pas de grille : celui-ci change
la fenêtre de lissage effective.
"""

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import accumulate

from mountain_perf.gpx.geo import deduplicated_polyline
from mountain_perf.schemas import ParameterSet, ParameterSpec, Route, RouteProfile

PROFILE_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        name="grid_step_m",
        unit="m",
        default=50,
        minimum=1,
        maximum=1000,
        description="Pas nominal de la grille horizontale, défaut provisoire.",
    ),
    ParameterSpec(
        name="smoothing_window_m",
        unit="m",
        default=150,
        minimum=0,
        maximum=5000,
        description="Fenêtre symétrique, quantifiée par le pas ; 0 = aucun lissage.",
    ),
    ParameterSpec(
        name="point_match_max_offset_m",
        unit="m",
        default=150,
        minimum=1,
        maximum=20000,
        description="Écart maximal d'un lieu au tracé pour retenir un passage.",
    ),
    ParameterSpec(
        name="point_match_min_separation_m",
        unit="m",
        default=500,
        minimum=0,
        maximum=100000,
        description="Séparation minimale des passages ; 0 = aucune contrainte.",
    ),
)


class ProfileError(ValueError):
    """Tracé de longueur nulle après dédoublonnage : aucun profil possible."""


@dataclass(frozen=True)
class ProfileBuildResult:
    """Profil et diagnostics du calcul, sans modification des contrats M1."""

    profile: RouteProfile
    smoothing_point_count: int

    @property
    def effective_smoothing_window_m(self) -> float:
        """Largeur nominale effective, avant rétrécissement aux bords."""
        return self.smoothing_point_count * self.profile.step_m


def _build_grid(total_m: float, step_m: float) -> tuple[float, ...]:
    """Termine exactement en L ; L < h donne (0, L), exempté de la borne h/2."""
    if total_m < step_m:
        return (0.0, total_m)
    n = int(total_m // step_m)
    grid_m = [i * step_m for i in range(n + 1)]
    if total_m - n * step_m < step_m / 2:
        grid_m[-1] = total_m
    else:
        grid_m.append(total_m)
    return tuple(grid_m)


def _interpolate(
    distance_m: Sequence[float], elevation_m: Sequence[float], at_m: float
) -> float:
    i = max(0, min(bisect_right(distance_m, at_m) - 1, len(distance_m) - 2))
    t = (at_m - distance_m[i]) / (distance_m[i + 1] - distance_m[i])
    return elevation_m[i] + t * (elevation_m[i + 1] - elevation_m[i])


def _smooth(
    elevation_m: tuple[float, ...], step_m: float, window_m: float
) -> tuple[tuple[float, ...], int]:
    """Moyenne centrée et taille effective, calculées ensemble ; coût O(n)."""
    k = int(window_m // (2 * step_m))
    if k == 0:
        return elevation_m, 1
    prefix_m = tuple(accumulate(elevation_m, initial=0.0))
    smoothed_m: list[float] = []
    for i in range(len(elevation_m)):
        first, end = max(0, i - k), min(len(elevation_m), i + k + 1)
        smoothed_m.append((prefix_m[end] - prefix_m[first]) / (end - first))
    return tuple(smoothed_m), 2 * k + 1


def build_profile(route: Route, parameters: ParameterSet) -> RouteProfile:
    """Construit le profil ; le lissage change le D+ et dépend du pas de grille."""
    return build_profile_with_diagnostics(route, parameters).profile


def build_profile_with_diagnostics(
    route: Route, parameters: ParameterSet
) -> ProfileBuildResult:
    """Même construction que build_profile, avec les diagnostics destinés à la CLI."""
    polyline = deduplicated_polyline(route.latitude_deg, route.longitude_deg)
    if len(polyline.indices) < 2 or polyline.distance_m[-1] == 0:
        raise ProfileError(
            "Tracé de longueur nulle après écartement des points confondus."
        )
    step_m = parameters["grid_step_m"]
    grid_m = _build_grid(polyline.distance_m[-1], step_m)
    raw_elevation_m = tuple(route.elevation_m[i] for i in polyline.indices)
    sampled_m = tuple(
        _interpolate(polyline.distance_m, raw_elevation_m, at_m) for at_m in grid_m
    )
    smoothed_m, point_count = _smooth(
        sampled_m, step_m, parameters["smoothing_window_m"]
    )
    profile = RouteProfile(
        route_name=route.name,
        source=route.source,
        distance_m=grid_m,
        elevation_m=smoothed_m,
        resolved_points=(),
        step_m=step_m,
        build_parameters=parameters,
        quality_flags=frozenset(),
    )
    return ProfileBuildResult(profile, point_count)
