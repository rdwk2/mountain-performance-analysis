"""Les GPX des profils de démo (M5-3) : les préparés (lieux nommés et tracé au pas de
10 m) et la trace témoin d'une sortie. Des textes déterministes : les nombres
s'écrivent à format fixe, l'en-tête et l'espace de noms du GPX 1.1."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final
from xml.sax.saxutils import escape

from mountain_perf.demo.constantes import ROUTE_POINT_STEP_M
from mountain_perf.demo.parcours import Route, altitude_at, length_m, to_lat_lon, xy_at

if TYPE_CHECKING:
    from mountain_perf.demo.sorties import Outing

XML_HEADER: Final = '<?xml version="1.0" encoding="UTF-8"?>'
"""L'en-tête XML des GPX écrits."""

GPX_OPEN: Final = (
    '<gpx version="1.1" creator="mountain_perf demo" '
    'xmlns="http://www.topografix.com/GPX/1/1">'
)
"""La balise ouvrante d'un GPX 1.1."""


def _point(tag: str, lat: float, lon: float, ele: float, inner: str = "") -> str:
    return f'<{tag} lat="{lat:.7f}" lon="{lon:.7f}"><ele>{ele:.2f}</ele>{inner}</{tag}>'


def write_route_gpx(route: Route, path: Path) -> None:
    """Le préparé de ``route`` en GPX 1.1 : un ``wpt`` par lieu nommé, puis un ``trk``
    dont les points sont pris tous les ``ROUTE_POINT_STEP_M`` de 0 à la longueur
    comprise."""
    lines = [XML_HEADER, GPX_OPEN]
    for name, distance in route.waypoints:
        lat, lon = to_lat_lon(*xy_at(route, distance))
        inner = f"<name>{escape(name)}</name>"
        lines.append(_point("wpt", lat, lon, altitude_at(route, distance), inner))
    lines.append(f"<trk><name>{escape(route.name)}</name><trkseg>")
    total = length_m(route)
    count = round(total / ROUTE_POINT_STEP_M)
    for index in range(count + 1):
        s = min(total, index * ROUTE_POINT_STEP_M)
        lat, lon = to_lat_lon(*xy_at(route, s))
        lines.append(_point("trkpt", lat, lon, altitude_at(route, s)))
    lines.append("</trkseg></trk>")
    lines.append("</gpx>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_trace_gpx(outing: Outing, path: Path) -> None:
    """La trace d'une sortie en GPX 1.1 : un ``trkpt`` par enregistrement, avec
    l'altitude enregistrée et l'instant ``départ + t`` en UTC."""
    lines = [XML_HEADER, GPX_OPEN, "<trk><trkseg>"]
    for record in outing.records:
        instant = (outing.start + timedelta(seconds=record.elapsed_s)).isoformat()
        inner = f"<time>{instant}</time>"
        lines.append(_point("trkpt", record.lat, record.lon, record.altitude_m, inner))
    lines.append("</trkseg></trk>")
    lines.append("</gpx>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
