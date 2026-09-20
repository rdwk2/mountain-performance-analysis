"""Profil synthétique du M3 et ce que la projection doit en faire — valeurs exactes.

Sept points au pas de 100 m, altitudes rondes, un lieu nommé résolu à 250 m ::

    abscisse   0     100    200    300    400    500    600
    altitude   1000  1010   1000   1000   1020   1060   1020
    pente        +10 %  −10 %   0 %   +20 %  +40 %  −40 %
                                  ▲
                                  Refuge, à 250 m

Longueur 600 m, D+ 70 m, D− 50 m. Le profil est volontairement extrême : un tiers
de sa distance sort du support de ``SUPPORT_CURVE`` (±40 % contre ±20 %), ce qui
rend le prolongement observable au lieu d'en faire un chemin mort dans les tests.

Aucun GPX n'est nécessaire — et aucun ne conviendrait : les distances haversine
d'un méridien synthétique tombent à 599,999 999 999 7 m, et les pentes à
0,100 000 000 000 3, ce qui ferait perdre l'exactitude de toutes les valeurs
ci-dessous.
"""

from datetime import UTC, datetime

from mountain_perf.gpx import PROFILE_PARAMETER_SPECS
from mountain_perf.schemas import (
    NamedPoint,
    ParameterSet,
    PointKind,
    ResolvedPoint,
    RouteProfile,
    SourceRef,
)

PROFILE_SOURCE = SourceRef(
    kind="gpx",
    identifier="profil_six_intervalles.gpx",
    content_hash="2" * 64,
    retrieved_at=datetime(2026, 2, 1, 11, 0, tzinfo=UTC),
)

REFUGE = NamedPoint(
    name="Refuge",
    latitude_deg=45.0,
    longitude_deg=6.0,
    elevation_m=1000.0,
)

GRID_PARAMETERS = ParameterSet(
    PROFILE_PARAMETER_SPECS,
    {"grid_step_m": 100.0, "smoothing_window_m": 0.0},
)

SIX_INTERVAL_PROFILE = RouteProfile(
    route_name="Profil à six intervalles",
    source=PROFILE_SOURCE,
    distance_m=(0.0, 100.0, 200.0, 300.0, 400.0, 500.0, 600.0),
    elevation_m=(1000.0, 1010.0, 1000.0, 1000.0, 1020.0, 1060.0, 1020.0),
    resolved_points=(
        ResolvedPoint(point=REFUGE, distance_m=250.0, elevation_m=1000.0, offset_m=0.0),
    ),
    step_m=100.0,
    build_parameters=GRID_PARAMETERS,
)

ENDPOINTS = (
    NamedPoint(
        name="Départ",
        latitude_deg=45.0,
        longitude_deg=6.0,
        elevation_m=1000.0,
        kind=PointKind.START,
    ),
    NamedPoint(
        name="Arrivée",
        latitude_deg=45.01,
        longitude_deg=6.0,
        elevation_m=1020.0,
        kind=PointKind.FINISH,
    ),
)
"""Extrémités passées au moteur, telles que ``route_endpoints`` les fabrique.

Le ``kind`` est posé ici sans inférence : ces deux lieux ne sont pas lus dans un
fichier, ils sont fabriqués par le programme, qui sait ce qu'ils sont.
"""

CURVE_REF = "courbe_synthetique.csv#111111111111"

# Détail par intervalle à effort 1 : 200/3 + 40 + 100/3 + 100 + 200 + 100.
TOTAL_DURATION_S = 540.0
REFUGE_ARRIVAL_S = 370 / 3
TOTAL_DURATION_AT_EFFORT_0_8_S = 675.0
OUT_OF_SUPPORT_DISTANCE_M = 200.0
OUT_OF_SUPPORT_TIME_S = 300.0
