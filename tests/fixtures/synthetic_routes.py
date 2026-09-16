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


def irregular_route() -> Route:
    """200 pas de 5 m, puis 222 pas de 9 m ; lieu à 1500 m, entre deux sommets."""
    distance_m = (*range(0, 1001, 5), *range(1009, 2999, 9))
    return Route(
        name="Espacement irrégulier",
        latitude_deg=tuple(45 + math.degrees(d / EARTH_RADIUS_M) for d in distance_m),
        longitude_deg=(6.0,) * len(distance_m),
        elevation_m=(1500.0,) * len(distance_m),
        named_points=(
            NamedPoint("Lieu", 45 + math.degrees(1500 / EARTH_RADIUS_M), 6, None),
        ),
        source=SOURCE,
    )


def switchback_route() -> Route:
    """Cinq jambes de 260 m, écarts 70/30/10/50/90 m, même côté du lieu."""
    xy_m = tuple(
        (x_m, y_m)
        for i, y_m in enumerate((70, 30, 10, 50, 90))
        for x_m in ((-130, 0, 130) if i % 2 == 0 else (130, 0, -130))
    )
    return Route(
        name="Lacets synthétiques",
        latitude_deg=tuple(45 + math.degrees(y / EARTH_RADIUS_M) for _, y in xy_m),
        longitude_deg=tuple(
            6 + math.degrees(x / (EARTH_RADIUS_M * math.cos(math.pi / 4)))
            for x, _ in xy_m
        ),
        elevation_m=(1500.0,) * len(xy_m),
        named_points=(NamedPoint("Lieu", 45, 6, None),),
        source=SOURCE,
    )


def out_and_back_route() -> Route:
    """Demi-tour sur un sommet : brins écartés de 20 m aux extrémités.

    À mi-longueur, le lieu est à 8 m de l'aller et environ 2 m du retour.
    Coordonnées équatoriales inventées : la subdivision linéaire y conserve les
    abscisses à 1e-9 m, sans confondre l'écart sphère/plan avec les candidats.
    """
    return Route(
        name="Aller-retour synthétique",
        latitude_deg=(0.0, 0.0, math.degrees(20 / EARTH_RADIUS_M)),
        longitude_deg=(0.0, math.degrees(1000 / EARTH_RADIUS_M), 0.0),
        elevation_m=(1500.0,) * 3,
        named_points=(
            NamedPoint(
                "Lieu",
                math.degrees(8 / EARTH_RADIUS_M),
                math.degrees(500 / EARTH_RADIUS_M),
                None,
            ),
        ),
        source=SOURCE,
    )
