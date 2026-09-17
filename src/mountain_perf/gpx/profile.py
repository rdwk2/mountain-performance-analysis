"""Profil horizontal : rééchantillonner, puis lisser, puis résoudre les lieux.

Les défauts des paramètres sont provisoires, à caler sur des fichiers réels après
M2. Le profil n'est pas invariant au changement de pas de grille : celui-ci change
la fenêtre de lissage effective.
"""

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import accumulate

from mountain_perf.gpx.geo import (
    Polyline,
    deduplicated_polyline,
    project_point_on_segment,
)
from mountain_perf.schemas import (
    NamedPoint,
    ParameterSet,
    ParameterSpec,
    ResolvedPoint,
    Route,
    RouteProfile,
)

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
class UnresolvedPoint:
    """Lieu sans passage admissible et écart minimal issu de ses projections."""

    point: NamedPoint
    min_offset_m: float


@dataclass(frozen=True)
class ProfileBuildResult:
    """Profil et diagnostics du calcul, sans modification des contrats M1."""

    profile: RouteProfile
    smoothing_point_count: int
    unresolved_points: tuple[UnresolvedPoint, ...]
    matched_point_count: int

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


def _resolve(
    route: Route,
    polyline: Polyline,
    grid_m: tuple[float, ...],
    elevation_m: tuple[float, ...],
    parameters: ParameterSet,
) -> tuple[tuple[ResolvedPoint, ...], tuple[UnresolvedPoint, ...]]:
    """Candidats lus sur t, puis suppression non maximale gloutonne (0008).

    Intérieur : 0 < t < 1 ; sommet : t_i = 1 et t_{i+1} = 0 ; début :
    t_0 = 0 ; fin : t_dernier = 1. Les candidats de même abscisse sont confondus.
    Le tri (écart, abscisse) précède la suppression définitive des voisins trop
    proches : les écarts de segments voisins ne définissent jamais les candidats.
    """
    resolved: list[ResolvedPoint] = []
    unresolved: list[UnresolvedPoint] = []
    for point in route.named_points:
        projections = [
            project_point_on_segment(
                route.latitude_deg[a],
                route.longitude_deg[a],
                route.latitude_deg[b],
                route.longitude_deg[b],
                point.latitude_deg,
                point.longitude_deg,
            )
            for a, b in zip(polyline.indices[:-1], polyline.indices[1:], strict=True)
        ]
        candidates: dict[float, float] = {}
        for i, (t, offset_m) in enumerate(projections):
            interior = 0 < t < 1
            start = i == 0 and t == 0
            end = i == len(projections) - 1 and t == 1
            vertex = t == 1 and i + 1 < len(projections) and projections[i + 1][0] == 0
            if interior or start or end or vertex:
                # Aux sommets, reprendre l'abscisse exacte, sans nouvel arrondi.
                at_m = (
                    polyline.distance_m[i + 1]
                    if t == 1
                    else polyline.distance_m[i]
                    + t * (polyline.distance_m[i + 1] - polyline.distance_m[i])
                )
                candidates[at_m] = min(offset_m, candidates.get(at_m, offset_m))
        eligible = sorted(
            (
                (at_m, offset_m)
                for at_m, offset_m in candidates.items()
                if offset_m <= parameters["point_match_max_offset_m"]
            ),
            key=lambda candidate: (candidate[1], candidate[0]),
        )
        kept_m: list[float] = []
        for at_m, offset_m in eligible:
            if all(
                abs(at_m - other_m) >= parameters["point_match_min_separation_m"]
                for other_m in kept_m
            ):
                kept_m.append(at_m)
                resolved.append(
                    ResolvedPoint(
                        point=point,
                        distance_m=at_m,
                        elevation_m=_interpolate(grid_m, elevation_m, at_m),
                        offset_m=offset_m,
                    )
                )
        if not kept_m:
            unresolved.append(
                UnresolvedPoint(point, min(offset_m for _, offset_m in projections))
            )
    resolved.sort(key=lambda passage: passage.distance_m)
    return tuple(resolved), tuple(unresolved)


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
    resolved, unresolved = _resolve(route, polyline, grid_m, smoothed_m, parameters)
    profile = RouteProfile(
        route_name=route.name,
        source=route.source,
        distance_m=grid_m,
        elevation_m=smoothed_m,
        resolved_points=resolved,
        step_m=step_m,
        build_parameters=parameters,
        quality_flags=frozenset(),
    )
    return ProfileBuildResult(
        profile, point_count, unresolved, len(route.named_points) - len(unresolved)
    )
