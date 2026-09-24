"""Géométrie de référence de l'appariement : polyligne, plan local, repère, projection.

``0010`` D4.1 : le profil ``0008`` est inchangé, et la géométrie horizontale du
tracé de référence l'accompagne — polyligne dédoublonnée, abscisses haversine
cumulées, celles dont la grille du profil est issue ; *(précision)* la position à
l'abscisse ``s`` s'obtient par interpolation linéaire en latitude et longitude.

``0010`` D4.3 : plan local de ``0008`` (``x = R·cos φ_ancre·Δλ``, ``y = R·Δφ``), ancré
au point de score ; tangente unitaire ``τ`` = corde entre les positions à
``s − 25`` et ``s + 25`` m, bornées à ``[0 ; L]`` ; normale ``n`` = ``τ`` tournée de
+90°, donc **positive à gauche** du sens de parcours.

Les interpolations s'écrivent ``(1 − t)·a + t·b`` : exactes en ``t = 0`` et
``t = 1``, ce que ``a + t·(b − a)`` n'est pas en ``t = 1``.
"""

import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from mountain_perf.gpx import ProfileError
from mountain_perf.gpx.geo import EARTH_RADIUS_M, deduplicated_polyline
from mountain_perf.schemas import RecordedTrace, Route

HALF_CHORD_M = 25.0
"""Demi-corde de la tangente (m) : ``τ`` est la corde entre les positions à
``s − 25`` et ``s + 25`` m, bornées à ``[0 ; L]``, unilatérale aux bords (``0010``
D4.3)."""

MIN_CHORD_M = 1e-6
"""Corde en deçà de laquelle la tangente est indéfinie (m, ``0010`` D4.3) : statut
``tangente indéfinie``, jamais une normale non finie propagée."""

ANCHOR_TIE_M = 0.01
"""Égalité de la projection d'ancrage (m, ``0010`` D4.8, *précision*).

Deux minima sont à égalité si l'écart de leur distance au minimum est
**strictement inférieur** à 1 cm ; l'ancrage est ambigu si deux minima à égalité ont
des abscisses distantes de **strictement plus** de 1 cm.
"""


@dataclass(frozen=True)
class ReferenceGeometry:
    """Polyligne horizontale du tracé de référence — interne au paquet ``backtest``.

    - ``latitude_deg``, ``longitude_deg`` : sommets de la polyligne dédoublonnée par
      ``deduplicated_polyline`` (``0008``), la même que ``build_profile`` ;
    - ``distance_m`` : leurs abscisses haversine cumulées, ``0`` au premier sommet,
      strictement croissantes.
    """

    latitude_deg: tuple[float, ...]
    longitude_deg: tuple[float, ...]
    distance_m: tuple[float, ...]

    @property
    def length_m(self) -> float:
        """``L`` (m) : exactement ``profile.distance_m[-1]`` du profil ``0008``."""
        return self.distance_m[-1]


def reference_geometry(route: Route) -> ReferenceGeometry:
    """Géométrie de référence d'un tracé ; même refus que ``build_profile``.

    Moins de deux sommets ou longueur nulle après dédoublonnage : ``ProfileError``.
    """
    polyline = deduplicated_polyline(route.latitude_deg, route.longitude_deg)
    if len(polyline.indices) < 2 or polyline.distance_m[-1] == 0:
        raise ProfileError(
            "Tracé de longueur nulle après écartement des points confondus."
        )
    return ReferenceGeometry(
        latitude_deg=tuple(route.latitude_deg[i] for i in polyline.indices),
        longitude_deg=tuple(route.longitude_deg[i] for i in polyline.indices),
        distance_m=polyline.distance_m,
    )


def position_at(geometry: ReferenceGeometry, s_m: float) -> tuple[float, float]:
    """``(latitude, longitude)`` à l'abscisse ``s``, bornée à ``[0 ; L]``.

    Interpolation linéaire sur le segment dont le début est le dernier sommet
    d'abscisse ``<= s`` (plafonné à l'avant-dernier). Exacte aux sommets : pour ``s``
    égal à une abscisse de sommet, ``L`` compris, le sommet est rendu bit pour bit.
    """
    distance_m = geometry.distance_m
    at_m = min(max(s_m, 0.0), geometry.length_m)
    i = min(bisect_right(distance_m, at_m) - 1, len(distance_m) - 2)
    t = (at_m - distance_m[i]) / (distance_m[i + 1] - distance_m[i])
    lat, lon = geometry.latitude_deg, geometry.longitude_deg
    return (1 - t) * lat[i] + t * lat[i + 1], (1 - t) * lon[i] + t * lon[i + 1]


def to_local(
    anchor_lat_deg: float, anchor_lon_deg: float, lat_deg: float, lon_deg: float
) -> tuple[float, float]:
    """``(x, y)`` en mètres dans le plan de ``0008`` ancré en ``anchor``.

    ``x = R·cos(φ_ancre)·Δλ``, ``y = R·Δφ`` : le facteur ``cos φ`` est **celui de
    l'ancre**. Même formule que ``project_point_on_segment`` (``gpx/geo.py``).
    """
    return (
        EARTH_RADIUS_M
        * math.cos(math.radians(anchor_lat_deg))
        * math.radians(lon_deg - anchor_lon_deg),
        EARTH_RADIUS_M * math.radians(lat_deg - anchor_lat_deg),
    )


@dataclass(frozen=True)
class LocalFrame:
    """Repère d'un point de score (``0010`` D4.3).

    - ``anchor_lat_deg``, ``anchor_lon_deg`` : ancre ``Q``, position à l'abscisse
      du point ;
    - ``tangent`` : ``τ = (τ_x, τ_y)``, unitaire, dans le plan ancré en ``Q`` ;
    - ``normal`` : ``n = (−τ_y, τ_x)``, positive à gauche du sens de parcours.
    """

    anchor_lat_deg: float
    anchor_lon_deg: float
    tangent: tuple[float, float]
    normal: tuple[float, float]

    def local(self, lat_deg: float, lon_deg: float) -> tuple[float, float]:
        """``P − Q`` en mètres, dans le plan ancré en ``Q``."""
        return to_local(self.anchor_lat_deg, self.anchor_lon_deg, lat_deg, lon_deg)

    def coordinates(self, lat_deg: float, lon_deg: float) -> tuple[float, float]:
        """``((P − Q)·τ, (P − Q)·n)`` en mètres : ``h`` le long de la tangente, puis
        l'écart latéral signé (``0010`` D4.5)."""
        x_m, y_m = self.local(lat_deg, lon_deg)
        return (
            x_m * self.tangent[0] + y_m * self.tangent[1],
            x_m * self.normal[0] + y_m * self.normal[1],
        )

    def distance_m(self, lat_deg: float, lon_deg: float) -> float:
        """``‖P − Q‖`` en mètres, dans le plan ancré en ``Q`` (``0010`` D4.7)."""
        return math.hypot(*self.local(lat_deg, lon_deg))


def frame_at(geometry: ReferenceGeometry, s_m: float) -> LocalFrame | None:
    """Repère au point d'abscisse ``s`` ; ``None`` si la tangente est indéfinie.

    Ancre ``Q = position_at(s)`` ; corde de ``position_at(max(0, s − 25))`` à
    ``position_at(min(L, s + 25))``, dans le plan ancré en ``Q`` ; norme
    ``< MIN_CHORD_M`` : tangente indéfinie.
    """
    anchor = position_at(geometry, s_m)
    x0_m, y0_m = to_local(*anchor, *position_at(geometry, max(0.0, s_m - HALF_CHORD_M)))
    x1_m, y1_m = to_local(
        *anchor, *position_at(geometry, min(geometry.length_m, s_m + HALF_CHORD_M))
    )
    dx_m, dy_m = x1_m - x0_m, y1_m - y0_m
    chord_m = math.hypot(dx_m, dy_m)
    if chord_m < MIN_CHORD_M:
        return None
    tangent_x, tangent_y = dx_m / chord_m, dy_m / chord_m
    return LocalFrame(
        anchor_lat_deg=anchor[0],
        anchor_lon_deg=anchor[1],
        tangent=(tangent_x, tangent_y),
        normal=(-tangent_y, tangent_x),
    )


def anchor_projection(
    candidates: Sequence[tuple[float, float]],
) -> tuple[float, float, bool]:
    """Choix et égalité de la projection d'ancrage (``0010`` D4.8, *précision*).

    ``candidates`` : suite non vide de ``(distance, abscisse)`` en mètres, les minima
    locaux de la distance le long de la polyligne restreinte. Rend ``(abscisse,
    distance, ambiguë)`` : le candidat de plus petite distance, de plus petite
    abscisse à distance égale ; ambiguë si, parmi les candidats dont
    ``distance − d_min < ANCHOR_TIE_M``, deux abscisses sont distantes de plus de
    ``ANCHOR_TIE_M``. Suite vide : ``ValueError``.
    """
    if not candidates:
        raise ValueError("anchor_projection : aucun candidat.")
    distance_m, along_m = min(candidates)
    tied_m = [s_m for d_m, s_m in candidates if d_m - distance_m < ANCHOR_TIE_M]
    return along_m, distance_m, max(tied_m) - min(tied_m) > ANCHOR_TIE_M


@dataclass(frozen=True)
class RestrictedProjection:
    """Projection orthogonale d'un point sur la polyligne restreinte (``0010`` D4.8).

    - ``distance_along_m`` : abscisse de la projection retenue ;
    - ``offset_m`` : distance du point à cette projection, dans le plan de l'ancre ;
    - ``ambiguous`` : la distance minimale est atteinte à plusieurs abscisses
      (``anchor_projection``).
    """

    distance_along_m: float
    offset_m: float
    ambiguous: bool


def project_restricted(
    geometry: ReferenceGeometry,
    lat_deg: float,
    lon_deg: float,
    start_m: float,
    end_m: float,
    anchor: tuple[float, float],
) -> RestrictedProjection:
    """Projette un point sur la polyligne restreinte (``0010`` D4.8, *précision*).

    Restriction à ``[max(0, start_m) ; min(L, end_m)]``, dont les sommets sont ses
    deux bornes (``position_at``, avec leurs abscisses exactes) et les sommets
    d'abscisse strictement intérieure. Le point est projeté dans le plan ancré en
    ``anchor`` (``(latitude, longitude)``), paramètre ``t`` borné à ``[0 ; 1]`` sur
    chaque segment. Candidats selon la règle de ``0008`` sur ``t`` : intérieur
    (``0 < t < 1``), sommet (``t_i = 1`` et ``t_{i+1} = 0``), début (``t = 0`` sur le
    premier segment), fin (``t = 1`` sur le dernier) ; abscisse = début du segment
    ``+ t ·`` sa longueur en abscisses, et l'abscisse exacte du sommet quand
    ``t = 1``. Intervalle vide : ``ValueError``.
    """
    low_m = max(0.0, start_m)
    high_m = min(geometry.length_m, end_m)
    if not low_m < high_m:
        raise ValueError(f"project_restricted : intervalle vide [{low_m} ; {high_m}].")
    interior = [i for i, d_m in enumerate(geometry.distance_m) if low_m < d_m < high_m]
    along_m = [low_m, *(geometry.distance_m[i] for i in interior), high_m]
    vertices = [
        to_local(*anchor, *position_at(geometry, low_m)),
        *(
            to_local(*anchor, geometry.latitude_deg[i], geometry.longitude_deg[i])
            for i in interior
        ),
        to_local(*anchor, *position_at(geometry, high_m)),
    ]
    px_m, py_m = to_local(*anchor, lat_deg, lon_deg)
    projections: list[tuple[float, float]] = []
    for (ax_m, ay_m), (bx_m, by_m) in pairwise(vertices):
        ux_m, uy_m = bx_m - ax_m, by_m - ay_m
        squared_m2 = ux_m**2 + uy_m**2
        dot_m2 = (px_m - ax_m) * ux_m + (py_m - ay_m) * uy_m
        t = min(1.0, max(0.0, dot_m2 / squared_m2)) if squared_m2 > 0 else 0.0
        projections.append(
            (t, math.hypot(px_m - ax_m - t * ux_m, py_m - ay_m - t * uy_m))
        )
    last = len(projections) - 1
    candidates: list[tuple[float, float]] = []
    for i, (t, offset_m) in enumerate(projections):
        vertex = t == 1 and i < last and projections[i + 1][0] == 0
        if 0 < t < 1 or (i == 0 and t == 0) or (i == last and t == 1) or vertex:
            at_m = (
                along_m[i + 1]
                if t == 1
                else along_m[i] + t * (along_m[i + 1] - along_m[i])
            )
            candidates.append((offset_m, at_m))
    distance_along_m, offset_m, ambiguous = anchor_projection(candidates)
    return RestrictedProjection(distance_along_m, offset_m, ambiguous)


def trace_route(trace: RecordedTrace, name: str) -> Route:
    """Les positions **brutes** et altitudes d'une trace, en ``Route`` sans lieu
    nommé : le profil d'une sortie sans préparé (``0010`` D3)."""
    return Route(
        name=name,
        latitude_deg=trace.latitude_deg,
        longitude_deg=trace.longitude_deg,
        elevation_m=trace.elevation_m,
        named_points=(),
        source=trace.sources[0],
    )
