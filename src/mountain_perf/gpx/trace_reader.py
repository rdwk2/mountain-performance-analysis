"""Lecture d'une trace réalisée : enregistrements horodatés, sans rien de dérivé (M4a).

``0010`` D4.4 : les fichiers sont lus dans l'ordre donné et leurs tronçons
concaténés ; un enregistrement de même instant que le dernier conservé est écarté et
compté, un instant antérieur fait refuser la trace. Ni dédoublonnage de positions, ni
lissage, ni traitement des trous : ce sont des séries dérivées
(``mountain_perf.backtest.series``).

Les messages d'erreur nomment le fichier par son **nom seul**, jamais par son chemin
(règle 1 de ``CLAUDE.md``).
"""

import hashlib
import math
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from mountain_perf.gpx.reader import GpxError, _children, _number, _text
from mountain_perf.schemas import RecordedTrace, SourceRef


class TraceError(ValueError):
    """Trace inutilisable pour le backtest (``0010`` D4.4) : instant décroissant,
    valeur non finie, moins de deux enregistrements conservés."""


def _instant(value: str | None, context: str) -> datetime:
    """Instant ISO 8601 ramené en UTC ; un instant sans fuseau est refusé (``0006``)."""
    if value is None:
        raise GpxError(f"{context} : instant manquant.")
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as error:
        raise GpxError(f"{context} : instant illisible {value!r}.") from error
    if instant.utcoffset() is None:
        raise GpxError(f"{context} : instant sans fuseau {value!r}.")
    return instant.astimezone(UTC)


def read_trace(paths: Sequence[Path]) -> RecordedTrace:
    """Lit et concatène les ``trkpt`` de ``paths``, dans l'ordre, en une trace.

    Chaque ``trkpt`` porte ``lat``, ``lon``, ``<ele>`` et ``<time>`` ; absent ou
    illisible : ``GpxError``. Valeur non finie, instant antérieur au dernier conservé
    (à travers tronçons et fichiers) ou moins de deux enregistrements : ``TraceError``.
    Une valeur hors plage physique reste une ``ContractError`` du contrat.
    """
    instants: list[datetime] = []
    latitude_deg: list[float] = []
    longitude_deg: list[float] = []
    elevation_m: list[float] = []
    sources: list[SourceRef] = []
    dropped = 0
    for path in paths:
        content = path.read_bytes()
        try:
            root = ET.fromstring(content)
        except ET.ParseError as error:
            raise GpxError(f"{path.name} : XML mal formé : {error}.") from error
        points = [
            point
            for track in _children(root, "trk")
            for segment in _children(track, "trkseg")
            for point in _children(segment, "trkpt")
        ]
        for index, point in enumerate(points):
            context = f"{path.name}, trkpt[{index}]"
            lat_deg = _number(point.get("lat"), f"{context}.lat")
            lon_deg = _number(point.get("lon"), f"{context}.lon")
            ele_m = _number(_text(point, "ele"), f"{context}.ele")
            instant = _instant(_text(point, "time"), f"{context}.time")
            if not all(math.isfinite(value) for value in (lat_deg, lon_deg, ele_m)):
                raise TraceError(f"{context} : valeur non finie.")
            if instants and instant <= instants[-1]:
                if instant == instants[-1]:
                    dropped += 1
                    continue
                raise TraceError(
                    f"{context} : instant antérieur au dernier enregistrement conservé."
                )
            instants.append(instant)
            latitude_deg.append(lat_deg)
            longitude_deg.append(lon_deg)
            elevation_m.append(ele_m)
        sources.append(
            SourceRef(
                kind="gpx",
                identifier=path.name,
                content_hash=hashlib.sha256(content).hexdigest(),
                retrieved_at=datetime.now(UTC),
            )
        )
    if len(instants) < 2:
        raise TraceError(
            f"La trace doit contenir au moins 2 enregistrements, reçu {len(instants)}."
        )
    start = instants[0]
    return RecordedTrace(
        start_time=start,
        time_s=tuple((instant - start).total_seconds() for instant in instants),
        latitude_deg=tuple(latitude_deg),
        longitude_deg=tuple(longitude_deg),
        elevation_m=tuple(elevation_m),
        sources=tuple(sources),
        dropped_same_instant_count=dropped,
    )
