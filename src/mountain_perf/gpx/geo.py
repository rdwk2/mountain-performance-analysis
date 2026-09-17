"""Géométrie horizontale partagée par la lecture et le profil, sans altitude."""

from collections.abc import Sequence
from dataclasses import dataclass
from math import asin, cos, hypot, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_008.8  # Rayon moyen de l'ellipsoïde WGS84 (R1, IUGG).


def haversine_m(
    lat1_deg: float, lon1_deg: float, lat2_deg: float, lon2_deg: float
) -> float:
    """Distance orthodromique sur la sphère, en mètres, sans altitude."""
    a = sin(radians(lat2_deg - lat1_deg) / 2) ** 2 + (
        cos(radians(lat1_deg))
        * cos(radians(lat2_deg))
        * sin(radians(lon2_deg - lon1_deg) / 2) ** 2
    )
    # L'arrondi flottant peut dépasser 1 aux antipodes.
    return 2 * EARTH_RADIUS_M * asin(sqrt(min(1.0, max(0.0, a))))


@dataclass(frozen=True)
class Polyline:
    """Indices conservés et abscisses communes à la grille et aux passages."""

    indices: tuple[int, ...]
    distance_m: tuple[float, ...]


def deduplicated_polyline(
    latitude_deg: Sequence[float], longitude_deg: Sequence[float]
) -> Polyline:
    """Écarte les pas nuls ; conserve le premier de chaque série confondue."""
    if not latitude_deg:
        return Polyline((), ())
    indices = [0]
    distance_m = [0.0]
    for i in range(1, len(latitude_deg)):
        previous = indices[-1]
        step_m = haversine_m(
            latitude_deg[previous],
            longitude_deg[previous],
            latitude_deg[i],
            longitude_deg[i],
        )
        if step_m > 0:
            indices.append(i)
            distance_m.append(distance_m[-1] + step_m)
    return Polyline(tuple(indices), tuple(distance_m))


def project_point_on_segment(
    lat_a_deg: float,
    lon_a_deg: float,
    lat_b_deg: float,
    lon_b_deg: float,
    lat_p_deg: float,
    lon_p_deg: float,
) -> tuple[float, float]:
    """Renvoie (t borné à [0, 1], écart en m), dans le plan local ancré en A."""
    longitude_scale_m = EARTH_RADIUS_M * cos(radians(lat_a_deg))
    bx_m = longitude_scale_m * radians(lon_b_deg - lon_a_deg)
    by_m = EARTH_RADIUS_M * radians(lat_b_deg - lat_a_deg)
    px_m = longitude_scale_m * radians(lon_p_deg - lon_a_deg)
    py_m = EARTH_RADIUS_M * radians(lat_p_deg - lat_a_deg)
    squared_length_m2 = bx_m**2 + by_m**2
    t = (
        min(1.0, max(0.0, (px_m * bx_m + py_m * by_m) / squared_length_m2))
        if squared_length_m2 > 0
        else 0.0
    )
    return t, hypot(px_m - t * bx_m, py_m - t * by_m)
