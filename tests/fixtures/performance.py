"""Fixtures fixes de la performance — synthétiques, inventées, à valeurs rondes.

- ``FIVE_BIN_CURVE`` : une ``PaceCurve`` à cinq tranches, de −40 % à +40 % par pas de
  20 %, figée « à la main » (``activity_count = 0``, pas de filtre).
- ``THREE_POINT_PROJECTION`` : la projection à trois points du brief M1b, sur un profil
  de 30 km non lissé :

  ::

      km    0     6     12    20    30
      alt   1000  1800  1400  2000  1200
            Départ      Ravito A    Arrivée

      Point     abscisse   mouvement  arrivée   départ
      Départ    0 m        0 s        0 s       0 s
      Ravito A  12 000 m   4 500 s    4 500 s   4 800 s
      Arrivée   30 000 m   12 900 s   13 200 s  13 200 s

  Segments : 4 500 s puis 8 400 s ; arrêts intérieurs : 300 s ;
  4 500 + 8 400 + 300 = 13 200. D+ 800 puis 600, D− 400 puis 800, altitudes
  1000–1800 puis 1200–2000.
- ``OFF_GRID_PROJECTION`` : la même, plus une borne à 1 500 m, **hors grille**, au
  quart de la première maille. Seul oracle chiffré de l'interpolation linéaire :
  altitude 1200, D+ cumulé 200, D− 0 ; segment 0 → 1 500 m de D+ 200, D− 0,
  altitudes 1000–1200. Sans elle, tous les passages tombent sur la grille et un
  accrochage à la maille la plus proche passerait vert.

- ``THREE_PASSAGE_REFERENCE`` : une ``ReferencePerformance`` à trois passages, dont
  un en ``UNKNOWN`` — le cas réel d'un relevé qui ne dit pas sa convention.

Utilisées par ``tests/test_schemas_curve.py``, ``tests/test_schemas_projection.py`` et
``tests/test_schemas_reference.py``.
"""

from datetime import UTC, date, datetime

from mountain_perf.schemas import (
    CurveProvenance,
    NamedPoint,
    ObservedPassage,
    PaceCurve,
    ParameterSet,
    Passage,
    PointKind,
    Projection,
    ReferencePerformance,
    ResolvedPoint,
    RouteProfile,
    SourceRef,
    Sport,
    TimingConvention,
)

GENERATED_AT = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)

CURVE_SOURCE = SourceRef(
    kind="csv",
    identifier="courbe.csv",
    content_hash="0" * 64,
    retrieved_at=GENERATED_AT,
)

MANUAL_PROVENANCE = CurveProvenance(
    activity_count=0,
    hr_center_bpm=None,
    hr_width_bpm=None,
    date_from=date(2026, 1, 1),
    date_to=date(2026, 6, 30),
    source_activity_types=frozenset(),
    min_duration_s=None,
    estimator="saisie manuelle",
    generated_at=GENERATED_AT,
)

FIVE_BIN_CURVE = PaceCurve(
    sport=Sport.FOOT,
    grade=(-0.4, -0.2, 0.0, 0.2, 0.4),
    speed_ms=(2.0, 3.0, 3.0, 1.5, 0.75),
    sample_count=(10, 40, 100, 40, 10),
    dispersion_ms=(0.5, 0.5, 0.25, 0.25, 0.25),
    estimation=MANUAL_PROVENANCE,
    source=CURVE_SOURCE,
)

# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

ROUTE_SOURCE = SourceRef(
    kind="gpx",
    identifier="trente.gpx",
    content_hash="0" * 64,
    retrieved_at=GENERATED_AT,
)

THIRTY_KM_PROFILE = RouteProfile(
    route_name="Trente",
    source=ROUTE_SOURCE,
    distance_m=(0.0, 6000.0, 12000.0, 20000.0, 30000.0),
    elevation_m=(1000.0, 1800.0, 1400.0, 2000.0, 1200.0),
    resolved_points=(),
    step_m=6000.0,
    build_parameters=ParameterSet(specs=()),
)


def _passage(
    name: str,
    kind: PointKind,
    distance_m: float,
    elevation_m: float,
    times_s: tuple[float, float, float],
) -> Passage:
    moving, arrival, departure = times_s
    point = NamedPoint(
        name=name,
        latitude_deg=45.0,
        longitude_deg=6.0,
        elevation_m=elevation_m,
        kind=kind,
    )
    return Passage(
        point=ResolvedPoint(
            point=point, distance_m=distance_m, elevation_m=elevation_m, offset_m=0.0
        ),
        moving_time_s=moving,
        arrival_s=arrival,
        departure_s=departure,
    )


START = _passage("Départ", PointKind.START, 0.0, 1000.0, (0.0, 0.0, 0.0))
AID_A = _passage(
    "Ravito A", PointKind.AID_STATION, 12000.0, 1400.0, (4500.0, 4500.0, 4800.0)
)
FINISH = _passage(
    "Arrivée", PointKind.FINISH, 30000.0, 1200.0, (12900.0, 13200.0, 13200.0)
)
MARKER = _passage(
    "Borne 1,5 km", PointKind.UNKNOWN, 1500.0, 1200.0, (562.5, 562.5, 562.5)
)

THREE_POINT_PROJECTION = Projection(
    profile=THIRTY_KM_PROFILE,
    curve_ref="courbe.csv",
    parameters=ParameterSet(specs=()),
    passages=(START, AID_A, FINISH),
    start_time=None,
    engine_version="fixture",
    generated_at=GENERATED_AT,
)

OFF_GRID_PROJECTION = Projection(
    profile=THIRTY_KM_PROFILE,
    curve_ref="courbe.csv",
    parameters=ParameterSet(specs=()),
    passages=(START, MARKER, AID_A, FINISH),
    start_time=None,
    engine_version="fixture",
    generated_at=GENERATED_AT,
)

# ---------------------------------------------------------------------------
# Référence
# ---------------------------------------------------------------------------

THREE_PASSAGE_REFERENCE = ReferencePerformance(
    athlete_ref="athlete-a",
    event_name="Trail inventé",
    date=date(2026, 6, 20),
    passages=(
        ObservedPassage("Départ", 0.0, 0.0, TimingConvention.DEPARTURE),
        ObservedPassage("Ravito A", 4800.0, 12000.0, TimingConvention.UNKNOWN),
        ObservedPassage("Arrivée", 13200.0, 30000.0, TimingConvention.ARRIVAL),
    ),
    source=SourceRef(
        kind="csv",
        identifier="passages.csv",
        content_hash="0" * 64,
        retrieved_at=GENERATED_AT,
    ),
)
