"""Fixtures fixes du tracé — synthétiques, inventées, à valeurs rondes.

Un tracé en « sucette » de 6 km, calculable de tête :

::

    km   0     1     2     3     4     5     6
    alt  1000  1250  1500  1500  1500  1250  1000
         Départ Source Col                Source
         └ montée 25 % ┘└── plat ──┘└ descente 25 % ┘

- une tige de 1 km du départ à la source, puis une boucle carrée de 4 km
  (source → col → deux angles → source), puis 1 km de descente vers l'ouest ;
- la **Source** est traversée deux fois, à 1 km et à 5 km : c'est le cas du lieu
  qui donne deux passages ;
- D+ = D− = 500 m ; pente +0,25, +0,25, 0, 0, −0,25, −0,25.

Le profil n'est pas lissé (les altitudes sont déjà sur la grille) : la fixture sert
à raisonner sur le contrat, pas sur un algorithme.

Utilisées par ``tests/test_schemas_route.py`` ; destinées à servir de support de
discussion aux jalons suivants.
"""

from datetime import UTC, datetime

from mountain_perf.schemas import (
    NamedPoint,
    ParameterSet,
    ParameterSpec,
    PointKind,
    ResolvedPoint,
    Route,
    RouteProfile,
    SourceRef,
)

# À 45° de latitude : 0,009° de latitude ≈ 1 km ; 0,0127° de longitude ≈ 1 km.
_LAT_0, _LON_0 = 45.000, 6.000
_DLAT, _DLON = 0.009, 0.0127

SOURCE = SourceRef(
    kind="gpx",
    identifier="sucette.gpx",
    content_hash="0" * 64,
    retrieved_at=datetime(2026, 9, 13, 8, 0, tzinfo=UTC),
)

DEPART = NamedPoint(
    name="Départ",
    latitude_deg=_LAT_0,
    longitude_deg=_LON_0,
    elevation_m=1000.0,
    kind=PointKind.START,
)
SOURCE_POINT = NamedPoint(
    name="Source",
    latitude_deg=_LAT_0 + _DLAT,
    longitude_deg=_LON_0,
    elevation_m=1250.0,
    kind=PointKind.WATER,
)
COL = NamedPoint(
    name="Col",
    latitude_deg=_LAT_0 + 2 * _DLAT,
    longitude_deg=_LON_0,
    elevation_m=1500.0,
    kind=PointKind.COL,
)

LOLLIPOP_ROUTE = Route(
    name="Sucette",
    latitude_deg=(
        _LAT_0,
        _LAT_0 + _DLAT,
        _LAT_0 + 2 * _DLAT,
        _LAT_0 + 2 * _DLAT,
        _LAT_0 + _DLAT,
        _LAT_0 + _DLAT,
        _LAT_0 + _DLAT,
    ),
    longitude_deg=(
        _LON_0,
        _LON_0,
        _LON_0,
        _LON_0 + _DLON,
        _LON_0 + _DLON,
        _LON_0,
        _LON_0 - _DLON,
    ),
    elevation_m=(1000.0, 1250.0, 1500.0, 1500.0, 1500.0, 1250.0, 1000.0),
    named_points=(DEPART, SOURCE_POINT, COL),
    source=SOURCE,
)

STEP_SPEC = ParameterSpec(
    name="step",
    unit="m",
    default=1000.0,
    minimum=1.0,
    maximum=10000.0,
    description="Pas de grille inventé pour la fixture.",
)

LOLLIPOP_PROFILE = RouteProfile(
    route_name="Sucette",
    source=SOURCE,
    distance_m=(0.0, 1000.0, 2000.0, 3000.0, 4000.0, 5000.0, 6000.0),
    elevation_m=(1000.0, 1250.0, 1500.0, 1500.0, 1500.0, 1250.0, 1000.0),
    resolved_points=(
        ResolvedPoint(point=DEPART, distance_m=0.0, elevation_m=1000.0, offset_m=0.0),
        ResolvedPoint(
            point=SOURCE_POINT, distance_m=1000.0, elevation_m=1250.0, offset_m=3.0
        ),
        ResolvedPoint(point=COL, distance_m=2000.0, elevation_m=1500.0, offset_m=0.0),
        ResolvedPoint(
            point=SOURCE_POINT, distance_m=5000.0, elevation_m=1250.0, offset_m=3.0
        ),
    ),
    step_m=1000.0,
    build_parameters=ParameterSet(specs=(STEP_SPEC,)),
)
