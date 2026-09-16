"""Géométries inventées de M2, sans donnée personnelle."""

import math
from collections.abc import Sequence
from dataclasses import replace
from itertools import pairwise

from fixtures.routes import SOURCE
from mountain_perf.gpx.geo import EARTH_RADIUS_M
from mountain_perf.schemas import NamedPoint, Route


def meridian_route(
    base_m: float = 1500.0,
    amplitude_m: float = 20.0,
    wavelength_m: float = 400.0,
    length_m: float = 2000.0,
    spacing_m: float = 50.0,
) -> Route:
    """Méridien sinusoïdal : distance analytique R·Δφ, dernier point conservé."""
    distance_m = [i * spacing_m for i in range(int(length_m // spacing_m) + 1)]
    if distance_m[-1] < length_m:
        distance_m.append(length_m)
    return Route(
        name="Méridien synthétique",
        latitude_deg=tuple(45 + math.degrees(d / EARTH_RADIUS_M) for d in distance_m),
        longitude_deg=(6.0,) * len(distance_m),
        elevation_m=tuple(
            base_m + amplitude_m * math.sin(math.tau * d / wavelength_m)
            for d in distance_m
        ),
        named_points=(),
        source=SOURCE,
    )


def subdivide_route(route: Route) -> Route:
    """Insère les milieux, altitude interpolée ; exact sur un méridien."""

    def subdivide(values: Sequence[float]) -> tuple[float, ...]:
        return (
            *(v for a, b in pairwise(values) for v in (a, (a + b) / 2)),
            values[-1],
        )

    return replace(
        route,
        latitude_deg=subdivide(route.latitude_deg),
        longitude_deg=subdivide(route.longitude_deg),
        elevation_m=subdivide(route.elevation_m),
    )


def flat_route_with_confused_points() -> Route:
    """Arrêt au km 1 : trois points confondus, dérive de 1500 à 1530 m."""
    route = meridian_route(amplitude_m=0, spacing_m=1000)
    indices = (0, 1, 1, 1, 2)
    return replace(
        route,
        latitude_deg=tuple(route.latitude_deg[i] for i in indices),
        longitude_deg=(6.0,) * len(indices),
        elevation_m=(1500.0, 1500.0, 1515.0, 1530.0, 1500.0),
        named_points=(NamedPoint("Arrêt", route.latitude_deg[1], 6.0, None),),
    )
