"""Traces synthétiques du backtest (M4a) — plan équatorial, valeurs inventées.

Convention du § 7.0 du brief M4a-1 : une trace est décrite en mètres ``(x, y)``,
``x`` vers l'est et ``y`` vers le nord, et convertie par :func:`equatorial_deg`,
**l'aide unique** : deux positions de même ``(x, y)`` ont exactement les mêmes
flottants. Près de l'équateur, le plan local de ``0008`` rend ``(x, y)`` et la
haversine la distance euclidienne à mieux que ``1e−6`` m sur ces étendues.

- :func:`planar_trace` construit une ``RecordedTrace`` depuis des temps et des mètres ;
- :func:`gpx_document` écrit un GPX 1.1 à un ``trk``, un ``trkseg`` par liste de
  points, pour les variantes de lecture écrites dans ``tmp_path``.

Utilisées par ``tests/test_gpx_trace_reader.py``, ``tests/test_backtest_series.py``
et ``tests/test_backtest_clocks.py``.
"""

import math
from collections.abc import Sequence
from datetime import UTC, datetime

from mountain_perf.gpx.geo import EARTH_RADIUS_M
from mountain_perf.schemas import RecordedTrace, SourceRef

TRACE_START = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
TRACE_SOURCE = SourceRef(
    kind="gpx",
    identifier="trace_synthetique.gpx",
    content_hash="0" * 64,
    retrieved_at=datetime(2026, 9, 24, tzinfo=UTC),
)


def equatorial_deg(x_m: float, y_m: float) -> tuple[float, float]:
    """``(latitude, longitude)`` en degrés d'un point ``(x, y)`` du plan équatorial."""
    return math.degrees(y_m / EARTH_RADIUS_M), math.degrees(x_m / EARTH_RADIUS_M)


def parallel_deg(
    x_m: float, latitude_deg: float = 45.0, longitude0_deg: float = 6.0
) -> tuple[float, float]:
    """``(latitude, longitude)`` d'un point à ``x`` mètres à l'est de
    ``(latitude_deg, longitude0_deg)``, sur le même parallèle : ``Δλ = x / (R·cos φ)``.

    Hors de l'équateur, là où le facteur ``cos φ`` du plan local compte.
    """
    scale_m = EARTH_RADIUS_M * math.cos(math.radians(latitude_deg))
    return latitude_deg, longitude0_deg + math.degrees(x_m / scale_m)


def equatorial_x_m(longitude_deg: float) -> float:
    """Réciproque de :func:`equatorial_deg` pour ``x`` : mètres vers l'est."""
    return math.radians(longitude_deg) * EARTH_RADIUS_M


def planar_trace(
    time_s: Sequence[float],
    x_m: Sequence[float],
    y_m: Sequence[float] | None = None,
    elevation_m: Sequence[float] | None = None,
) -> RecordedTrace:
    """Trace à partir de temps et de positions planes ; ``y = 0`` et 1 000 m d'altitude
    par défaut."""
    ys = y_m if y_m is not None else [0.0] * len(x_m)
    positions = [equatorial_deg(x, y) for x, y in zip(x_m, ys, strict=True)]
    return RecordedTrace(
        start_time=TRACE_START,
        time_s=tuple(time_s),
        latitude_deg=tuple(lat for lat, _ in positions),
        longitude_deg=tuple(lon for _, lon in positions),
        elevation_m=(
            tuple(elevation_m) if elevation_m is not None else (1000.0,) * len(x_m)
        ),
        sources=(TRACE_SOURCE,),
        dropped_same_instant_count=0,
    )


def parallel_trace(
    time_s: Sequence[float], x_m: Sequence[float], latitude_deg: float = 45.0
) -> RecordedTrace:
    """Trace sur le parallèle ``latitude_deg``, positions par :func:`parallel_deg`,
    1 000 m d'altitude."""
    positions = [parallel_deg(x, latitude_deg) for x in x_m]
    return RecordedTrace(
        start_time=TRACE_START,
        time_s=tuple(time_s),
        latitude_deg=tuple(lat for lat, _ in positions),
        longitude_deg=tuple(lon for _, lon in positions),
        elevation_m=(1000.0,) * len(x_m),
        sources=(TRACE_SOURCE,),
        dropped_same_instant_count=0,
    )


GpxPoint = tuple[str, str, str | None, str | None]
"""Un ``trkpt`` : ``lat``, ``lon``, ``<ele>`` et ``<time>`` en texte ; ``None`` =
balise absente."""


def gpx_document(*segments: Sequence[GpxPoint]) -> str:
    """GPX 1.1 à un ``trk`` ; un ``trkseg`` par séquence de points."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="synthetic-tests" '
        'xmlns="http://www.topografix.com/GPX/1/1">',
        "  <trk><name>Trace synthétique</name>",
    ]
    for points in segments:
        lines.append("    <trkseg>")
        for lat, lon, ele, time in points:
            children = (f"<ele>{ele}</ele>" if ele is not None else "") + (
                f"<time>{time}</time>" if time is not None else ""
            )
            lines.append(f'      <trkpt lat="{lat}" lon="{lon}">{children}</trkpt>')
        lines.append("    </trkseg>")
    lines += ["  </trk>", "</gpx>", ""]
    return "\n".join(lines)


def equatorial_point(x_m: float, time: str, elevation_m: float = 1000.0) -> GpxPoint:
    """Un ``trkpt`` complet sur l'équateur, coordonnées écrites en ``repr`` exact."""
    lat, lon = equatorial_deg(x_m, 0.0)
    return (repr(lat), repr(lon), repr(elevation_m), time)
