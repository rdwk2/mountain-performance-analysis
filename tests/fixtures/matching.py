"""Fixtures synthétiques de l'appariement (M4a-2a) — plan à 45° N, valeurs inventées.

Convention du § 7.0 du brief M4a-2a : références et traces sont décrites en mètres
``(x, y)``, ``x`` vers l'est et ``y`` vers le nord, et converties par
:func:`fixtures.traces.local_deg`, l'aide unique ; une autre latitude de base ne sert
qu'aux reconstructions à 0° et 60° (test 4 du § 8). Référence plate (0 m).
"""

from datetime import UTC, datetime

from fixtures.traces import local_deg
from mountain_perf.backtest import ReferenceGeometry, reference_geometry
from mountain_perf.schemas import Route, SourceRef

REFERENCE_SOURCE = SourceRef(
    kind="gpx",
    identifier="reference_synthetique.gpx",
    content_hash="1" * 64,
    retrieved_at=datetime(2026, 9, 24, tzinfo=UTC),
)

Point = tuple[float, float]
"""Un point ``(x, y)`` du plan de base, en mètres."""


def reference_route(*vertices_m: Point, base_latitude_deg: float = 45.0) -> Route:
    """Référence plate de sommets ``vertices_m``, sans lieu nommé."""
    positions = [
        local_deg(x_m, y_m, base_latitude_deg=base_latitude_deg)
        for x_m, y_m in vertices_m
    ]
    return Route(
        name="Référence synthétique",
        latitude_deg=tuple(lat for lat, _ in positions),
        longitude_deg=tuple(lon for _, lon in positions),
        elevation_m=(0.0,) * len(positions),
        named_points=(),
        source=REFERENCE_SOURCE,
    )


def reference(*vertices_m: Point, base_latitude_deg: float = 45.0) -> ReferenceGeometry:
    """Géométrie de référence de :func:`reference_route`."""
    return reference_geometry(
        reference_route(*vertices_m, base_latitude_deg=base_latitude_deg)
    )
