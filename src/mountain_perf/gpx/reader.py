"""Lecture GPX 1.0, 1.1 ou sans espace de noms, sans inférence sur les lieux."""

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from mountain_perf.gpx.geo import deduplicated_polyline, haversine_m
from mountain_perf.schemas import NamedPoint, Route, SourceRef


class GpxError(ValueError):
    """Fichier GPX inutilisable : structure invalide ou contenu insuffisant."""


@dataclass(frozen=True)
class GpxReadResult:
    """Tracé lu et diagnostics des pertes et raccords effectués à la lecture."""

    route: Route
    point_count_read: int
    point_count_dropped: int
    unnamed_waypoint_count: int
    segment_count: int
    max_segment_gap_m: float


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if child.tag.rpartition("}")[2] == name]


def _text(element: ET.Element, name: str) -> str | None:
    children = _children(element, name)
    if not children:
        return None
    return (children[0].text or "").strip() or None


def _number(value: str | None, context: str) -> float:
    if value is None:
        raise GpxError(f"{context} : valeur numérique manquante.")
    try:
        return float(value)
    except ValueError as error:
        raise GpxError(f"{context} : valeur numérique illisible {value!r}.") from error


def read_gpx(path: Path) -> GpxReadResult:
    """Lit tous les tronçons dans l'ordre, conserve le premier point des doublons.

    Les nombres illisibles sont des ``GpxError`` ; les violations physiques restent
    des ``ContractError``. Aucun lieu n'est typé d'après son nom ou son type brut.
    """
    content = path.read_bytes()
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise GpxError(f"XML mal formé : {error}.") from error
    tracks = _children(root, "trk")
    latitude_deg: list[float] = []
    longitude_deg: list[float] = []
    elevation_m: list[float] = []
    segment_starts: list[int] = []
    segment_count = 0
    for track in tracks:
        for segment in _children(track, "trkseg"):
            segment_count += 1
            points = _children(segment, "trkpt")
            if points:
                segment_starts.append(len(latitude_deg))
            for point in points:
                context = f"trkpt[{len(latitude_deg)}]"
                latitude_deg.append(_number(point.get("lat"), f"{context}.lat"))
                longitude_deg.append(_number(point.get("lon"), f"{context}.lon"))
                elevation_m.append(_number(_text(point, "ele"), f"{context}.ele"))
    if not latitude_deg:
        raise GpxError("Aucun <trkpt> dans le fichier GPX.")
    if len(latitude_deg) < 2:
        raise GpxError("Le tracé doit contenir au moins 2 points distincts.")

    named_points: list[NamedPoint] = []
    unnamed_waypoint_count = 0
    for index, waypoint in enumerate(_children(root, "wpt")):
        context = f"wpt[{index}]"
        lat_deg = _number(waypoint.get("lat"), f"{context}.lat")
        lon_deg = _number(waypoint.get("lon"), f"{context}.lon")
        altitude_m = (
            _number(_text(waypoint, "ele"), f"{context}.ele")
            if _children(waypoint, "ele")
            else None
        )
        name = _text(waypoint, "name")
        if name is None:
            unnamed_waypoint_count += 1
            continue
        named_points.append(
            NamedPoint(
                name=name,
                latitude_deg=lat_deg,
                longitude_deg=lon_deg,
                elevation_m=altitude_m,
                raw_type=_text(waypoint, "type") or _text(waypoint, "sym"),
                description=_text(waypoint, "desc"),
            )
        )
    # Valider les valeurs avant la géométrie, y compris celles des points écartés.
    route = Route(
        name=_text(tracks[0], "name") or path.stem,
        latitude_deg=tuple(latitude_deg),
        longitude_deg=tuple(longitude_deg),
        elevation_m=tuple(elevation_m),
        named_points=tuple(named_points),
        source=SourceRef(
            kind="gpx",
            identifier=path.name,
            content_hash=hashlib.sha256(content).hexdigest(),
            retrieved_at=datetime.now(UTC),
        ),
    )
    polyline = deduplicated_polyline(route.latitude_deg, route.longitude_deg)
    if len(polyline.indices) < 2 or polyline.distance_m[-1] == 0:
        raise GpxError(
            "Le tracé doit contenir au moins 2 points distincts (longueur nulle)."
        )
    max_segment_gap_m = max(
        (
            haversine_m(
                latitude_deg[i - 1],
                longitude_deg[i - 1],
                latitude_deg[i],
                longitude_deg[i],
            )
            for i in segment_starts[1:]
        ),
        default=0.0,
    )
    return GpxReadResult(
        route=replace(
            route,
            latitude_deg=tuple(latitude_deg[i] for i in polyline.indices),
            longitude_deg=tuple(longitude_deg[i] for i in polyline.indices),
            elevation_m=tuple(elevation_m[i] for i in polyline.indices),
        ),
        point_count_read=len(latitude_deg),
        point_count_dropped=len(latitude_deg) - len(polyline.indices),
        unnamed_waypoint_count=unnamed_waypoint_count,
        segment_count=segment_count,
        max_segment_gap_m=max_segment_gap_m,
    )
