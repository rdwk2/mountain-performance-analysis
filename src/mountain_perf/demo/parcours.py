"""Les parcours des profils de démo (M5-3) : le repère plan, les tronçons à pente
linéaire, les six parcours (deux courses et quatre boucles).

Sur un tronçon de longueur ``L``, la pente varie linéairement de ``g0`` à ``g1`` ;
l'altitude gagnée à la distance ``u`` du début vaut ``g0 · u + (g1 − g0) · u² / (2 L)``.
Les distances sont horizontales, en mètres.
"""

from dataclasses import dataclass
from typing import Final, Literal

from mountain_perf.demo.constantes import (
    LOOP_EAST_SHARE,
    LOOP_NORTH_SHARE,
    ORIGIN_LAT_DEG,
    ORIGIN_LON_DEG,
    ROUTE_TABLE,
)
from mountain_perf.validation import ContractError

METRES_PER_DEGREE: Final = 111_195.0
"""Les mètres d'un degré, sur l'équateur comme sur un méridien : le degré du rayon
moyen de ``gpx/geo.py``, arrondi au mètre (un nombre de géodésie, pas inventé)."""


def to_lat_lon(x: float, y: float) -> tuple[float, float]:
    """Les coordonnées (latitude, longitude) en degrés d'un point ``(x, y)`` du repère
    plan (``x`` vers l'est, ``y`` vers le nord, en mètres)."""
    lat = ORIGIN_LAT_DEG + y / METRES_PER_DEGREE
    return lat, ORIGIN_LON_DEG + x / METRES_PER_DEGREE


@dataclass(frozen=True)
class Segment:
    """Un tronçon : sa longueur horizontale et ses pentes de début et de fin."""

    length_m: float
    grade_start: float
    grade_end: float


@dataclass(frozen=True)
class Route:
    """Un parcours : son nom, ses tronçons, son départ dans le repère plan, sa forme
    (``line`` vers l'est, ``loop`` en rectangle), son altitude de départ et ses lieux
    nommés (nom, distance depuis le départ)."""

    name: str
    segments: tuple[Segment, ...]
    start_xy: tuple[float, float]
    shape: Literal["line", "loop"]
    start_altitude_m: float
    waypoints: tuple[tuple[str, float], ...]


def _gain(segment: Segment, u: float) -> float:
    """L'altitude gagnée à la distance ``u`` du début du tronçon."""
    g0, g1, length = segment.grade_start, segment.grade_end, segment.length_m
    return g0 * u + (g1 - g0) * u * u / (2 * length)


def length_m(route: Route) -> float:
    """La longueur horizontale du parcours."""
    return sum(segment.length_m for segment in route.segments)


def _locate(route: Route, s: float) -> tuple[int, float, float]:
    """L'indice du tronçon qui porte ``s``, la distance au début de ce tronçon et
    l'altitude à ce début ; ``ContractError`` hors de ``[0 ; L]``."""
    total = length_m(route)
    if not 0.0 <= s <= total:
        raise ContractError(f"distance hors du parcours {route.name} : {s}")
    start = 0.0
    altitude = route.start_altitude_m
    last = len(route.segments) - 1
    for index, segment in enumerate(route.segments):
        end = start + segment.length_m
        if s < end or index == last:
            return index, s - start, altitude
        altitude += _gain(segment, segment.length_m)
        start = end
    raise ContractError(f"parcours sans tronçon : {route.name}")


def grade_at(route: Route, s: float) -> float:
    """La pente à la distance ``s`` du départ."""
    index, u, _ = _locate(route, s)
    segment = route.segments[index]
    return segment.grade_start + (segment.grade_end - segment.grade_start) * (
        u / segment.length_m
    )


def altitude_at(route: Route, s: float) -> float:
    """L'altitude à la distance ``s`` du départ."""
    index, u, altitude = _locate(route, s)
    return altitude + _gain(route.segments[index], u)


def xy_at(route: Route, s: float) -> tuple[float, float]:
    """Le point du repère plan à la distance ``s`` du départ : vers l'est pour une
    ligne ; pour une boucle, un rectangle de côtés ``a = 0,3 L`` et ``b = 0,2 L``
    parcouru vers l'est, le nord, l'ouest puis le sud."""
    _locate(route, s)
    x0, y0 = route.start_xy
    if route.shape == "line":
        return x0 + s, y0
    total = length_m(route)
    a = LOOP_EAST_SHARE * total
    b = LOOP_NORTH_SHARE * total
    if s <= a:
        return x0 + s, y0
    if s <= a + b:
        return x0 + a, y0 + (s - a)
    if s <= 2 * a + b:
        return x0 + a - (s - a - b), y0 + b
    return x0, y0 + b - (s - 2 * a - b)


def _positive_gain(segment: Segment) -> float:
    g0, g1, length = segment.grade_start, segment.grade_end, segment.length_m
    if g0 >= 0 and g1 >= 0:
        return length * (g0 + g1) / 2
    if g0 <= 0 and g1 <= 0:
        return 0.0
    crossing = length * g0 / (g0 - g1)
    if g0 > 0:
        return g0 * crossing / 2
    return g1 * (length - crossing) / 2


def climb_m(route: Route) -> float:
    """Le dénivelé positif : la somme des gains des tronçons de pente positive, plus la
    part positive d'un tronçon qui change de signe."""
    return sum(_positive_gain(segment) for segment in route.segments)


ROUTES: Final[tuple[Route, ...]] = tuple(
    Route(
        name=name,
        segments=tuple(Segment(*segment) for segment in segments),
        start_xy=start_xy,
        shape="line" if shape == "line" else "loop",
        start_altitude_m=altitude,
        waypoints=waypoints,
    )
    for name, shape, start_xy, altitude, segments, waypoints in ROUTE_TABLE
)
"""Les six parcours : ``deux_parties``, ``course_raide``, ``boucle_raide``,
``boucle_roulante``, ``boucle_moyenne``, ``boucle_douce``."""


def route(name: str) -> Route:
    """Le parcours nommé ``name`` ; ``ContractError`` pour un autre nom."""
    for found in ROUTES:
        if found.name == name:
            return found
    raise ContractError(f"parcours inconnu : {name}")
