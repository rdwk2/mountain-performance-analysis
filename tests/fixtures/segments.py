"""Fixtures synthétiques des segments (M4a-2b) — plan à 45° N, valeurs inventées.

Convention du § 7.0 des briefs M4a-2a et M4a-2b : références et traces décrites en
mètres ``(x, y)``, converties par :func:`fixtures.traces.local_deg`. Les lignes du
§ 7.2b reprises de M4a-2a sont construites par ``fixtures.matching`` ; celles-ci
ajoutent l'altitude des références, les profils écrits à la main et les lignes
neuves du § 7.2b.

Utilisées par ``tests/test_backtest_segment_rules.py`` et
``tests/test_backtest_segments.py``.
"""

from collections.abc import Sequence

from fixtures.matching import REFERENCE_SOURCE
from fixtures.traces import local_deg
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS
from mountain_perf.schemas import ParameterSet, Route, RouteProfile

ElevatedPoint = tuple[float, float, float]
"""Un sommet ``(x, y, z)`` : mètres vers l'est, vers le nord, altitude."""


def elevated_route(*vertices: ElevatedPoint) -> Route:
    """Référence de sommets ``(x, y, z)``, sans lieu nommé."""
    positions = [local_deg(x_m, y_m) for x_m, y_m, _ in vertices]
    return Route(
        name="Référence synthétique à altitude",
        latitude_deg=tuple(lat for lat, _ in positions),
        longitude_deg=tuple(lon for _, lon in positions),
        elevation_m=tuple(z_m for _, _, z_m in vertices),
        named_points=(),
        source=REFERENCE_SOURCE,
    )


def hand_profile(
    distance_m: Sequence[float], elevation_m: Sequence[float]
) -> RouteProfile:
    """``RouteProfile`` écrit à la main : grille et altitudes données telles quelles."""
    return RouteProfile(
        route_name="Profil écrit à la main",
        source=REFERENCE_SOURCE,
        distance_m=tuple(distance_m),
        elevation_m=tuple(elevation_m),
        resolved_points=(),
        step_m=50.0,
        build_parameters=ParameterSet(PROFILE_PARAMETER_SPECS),
    )
