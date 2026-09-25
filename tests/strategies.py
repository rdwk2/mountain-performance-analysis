"""Stratégies Hypothesis des contrats de données — réutilisées par tous les jalons.

Deux familles :

- **valides** : chaque stratégie produit un objet qui se construit. Tous les
  flottants passent par :func:`finite_floats` (jamais de NaN ni d'infini), tous
  les tableaux sont des tuples ;
- **invalides ciblées** : des valeurs qui violent un invariant précis
  (:func:`non_finite_floats`, :func:`naive_datetimes`…). Un test prend un objet
  valide et remplace un seul champ par ``dataclasses.replace``, ce qui relance la
  validation.
"""

import hashlib
import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from itertools import accumulate
from typing import Literal

from hypothesis import assume
from hypothesis import strategies as st

from fixtures.matching import (
    MAX_STRAIGHT_RECORDS,
    MatchCase,
    Phase,
    StraightCase,
    matching_parameters,
    straight_case,
    wandering_case,
)
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS
from mountain_perf.gpx.geo import EARTH_RADIUS_M
from mountain_perf.schemas import (
    CLOCK_CONVENTIONS,
    ELEVATION_RANGE_M,
    GRADE_RANGE,
    HEART_RATE_RANGE_BPM,
    LATITUDE_RANGE_DEG,
    LONGITUDE_RANGE_DEG,
    Activity,
    ArtifactRef,
    ArtifactRole,
    ClockPartition,
    CurveProvenance,
    DataSet,
    IntervalState,
    NamedPoint,
    ObservedPassage,
    Outing,
    OutingLabel,
    PaceCurve,
    ParameterSet,
    ParameterSpec,
    Passage,
    Performance,
    PointKind,
    PointStatus,
    Projection,
    QualityFlag,
    RecordedTrace,
    ReferenceKind,
    ReferencePerformance,
    ResolvedPoint,
    Route,
    RouteProfile,
    RouteReference,
    ScorePointObservation,
    SourceRef,
    Sport,
    TimingConvention,
    TrackPointStream,
)

_MIN_DATETIME = datetime(1990, 1, 1)
_MAX_DATETIME = datetime(2100, 1, 1)

# ---------------------------------------------------------------------------
# Briques
# ---------------------------------------------------------------------------


def finite_floats(min_value: float, max_value: float) -> st.SearchStrategy[float]:
    """Flottants finis dans ``[min_value, max_value]`` — jamais NaN ni infini."""
    return st.floats(
        min_value=min_value,
        max_value=max_value,
        allow_nan=False,
        allow_infinity=False,
    )


def non_finite_floats() -> st.SearchStrategy[float]:
    """NaN, +inf ou −inf : pour vérifier que la finitude est exigée."""
    return st.sampled_from([float("nan"), float("inf"), float("-inf")])


def fixed_offset_timezones() -> st.SearchStrategy[timezone]:
    """Fuseaux à décalage fixe, de UTC−12 à UTC+14 (sans dépendre de tzdata)."""
    return st.integers(min_value=-12 * 60, max_value=14 * 60).map(
        lambda minutes: timezone(timedelta(minutes=minutes))
    )


def aware_datetimes() -> st.SearchStrategy[datetime]:
    """``datetime`` porteurs d'un fuseau."""
    return st.datetimes(
        min_value=_MIN_DATETIME,
        max_value=_MAX_DATETIME,
        timezones=fixed_offset_timezones(),
    )


def naive_datetimes() -> st.SearchStrategy[datetime]:
    """``datetime`` naïfs : doivent être refusés partout."""
    return st.datetimes(min_value=_MIN_DATETIME, max_value=_MAX_DATETIME)


def non_empty_texts() -> st.SearchStrategy[str]:
    """Texte avec au moins un caractère non blanc."""
    return st.text(min_size=1, max_size=30).filter(lambda text: bool(text.strip()))


def blank_texts() -> st.SearchStrategy[str]:
    """Texte vide ou fait d'espaces : doit être refusé là où un nom est exigé."""
    return st.text(alphabet=" \t\n", max_size=5)


def latitudes_deg() -> st.SearchStrategy[float]:
    return finite_floats(*LATITUDE_RANGE_DEG)


def longitudes_deg() -> st.SearchStrategy[float]:
    return finite_floats(*LONGITUDE_RANGE_DEG)


def elevations_m() -> st.SearchStrategy[float]:
    return finite_floats(*ELEVATION_RANGE_M)


def out_of_range_latitudes_deg() -> st.SearchStrategy[float]:
    return st.one_of(finite_floats(90.001, 1e6), finite_floats(-1e6, -90.001))


def out_of_range_longitudes_deg() -> st.SearchStrategy[float]:
    return st.one_of(finite_floats(180.001, 1e6), finite_floats(-1e6, -180.001))


def out_of_range_elevations_m() -> st.SearchStrategy[float]:
    return st.one_of(finite_floats(9000.001, 1e6), finite_floats(-1e6, -500.001))


# ---------------------------------------------------------------------------
# Communs
# ---------------------------------------------------------------------------


def sports() -> st.SearchStrategy[Sport]:
    return st.sampled_from(Sport)


def quality_flag_sets() -> st.SearchStrategy[frozenset[QualityFlag]]:
    return st.frozensets(st.sampled_from(QualityFlag))


def sha256_hex() -> st.SearchStrategy[str]:
    return st.binary(max_size=64).map(lambda data: hashlib.sha256(data).hexdigest())


def file_names() -> st.SearchStrategy[str]:
    """Noms de fichier plausibles, points compris (``trace.gpx``)."""
    return st.from_regex(r"[A-Za-z0-9_\-]{1,20}(\.[a-z]{2,4}){0,2}", fullmatch=True)


def path_like_identifiers() -> st.SearchStrategy[str]:
    """Identifiants qui sont des chemins : doivent être refusés."""
    return st.one_of(
        st.sampled_from([".", ".."]),
        st.tuples(file_names(), st.sampled_from(["/", "\\", ":"]), file_names()).map(
            "".join
        ),
    )


def source_refs() -> st.SearchStrategy[SourceRef]:
    return st.builds(
        SourceRef,
        kind=st.sampled_from(["gpx", "garmin_activity", "csv"]),
        identifier=file_names(),
        content_hash=sha256_hex(),
        retrieved_at=aware_datetimes(),
    )


# ---------------------------------------------------------------------------
# Paramètres
# ---------------------------------------------------------------------------


def parameter_names() -> st.SearchStrategy[str]:
    return st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True)


@st.composite
def parameter_specs(
    draw: st.DrawFn, name: st.SearchStrategy[str] | None = None
) -> ParameterSpec:
    """Specs inventées : bornes finies ordonnées, défaut entre les deux."""
    bound_a = draw(finite_floats(-1e6, 1e6))
    bound_b = draw(finite_floats(-1e6, 1e6))
    minimum, maximum = min(bound_a, bound_b), max(bound_a, bound_b)
    return ParameterSpec(
        name=draw(name if name is not None else parameter_names()),
        unit=draw(st.one_of(st.none(), st.sampled_from(["m", "s", "m/s", "K"]))),
        default=draw(finite_floats(minimum, maximum)),
        minimum=minimum,
        maximum=maximum,
        description=draw(non_empty_texts()),
    )


@st.composite
def parameter_sets(draw: st.DrawFn, max_size: int = 6) -> ParameterSet:
    """Jeux valides : noms uniques, une partie seulement des valeurs fournies."""
    names = draw(st.lists(parameter_names(), unique=True, max_size=max_size))
    specs = tuple(draw(parameter_specs(name=st.just(name))) for name in names)
    values: dict[str, float] = {}
    for spec in specs:
        if draw(st.booleans()):
            values[spec.name] = draw(finite_floats(spec.minimum, spec.maximum))
    return ParameterSet(specs=specs, values=values)


# ---------------------------------------------------------------------------
# Tracé
# ---------------------------------------------------------------------------


def named_points() -> st.SearchStrategy[NamedPoint]:
    return st.builds(
        NamedPoint,
        name=non_empty_texts(),
        latitude_deg=latitudes_deg(),
        longitude_deg=longitudes_deg(),
        elevation_m=st.one_of(st.none(), elevations_m()),
        kind=st.sampled_from(PointKind),
        raw_type=st.one_of(st.none(), st.text(max_size=20)),
        cutoff_s=st.one_of(st.none(), finite_floats(1.0, 1e6)),
        description=st.one_of(st.none(), st.text(max_size=40)),
    )


@st.composite
def routes(draw: st.DrawFn, max_points: int = 50) -> Route:
    """Tracés valides : tableaux parallèles en tuples, 2 points au moins."""
    n = draw(st.integers(min_value=2, max_value=max_points))
    return Route(
        name=draw(non_empty_texts()),
        latitude_deg=tuple(draw(st.lists(latitudes_deg(), min_size=n, max_size=n))),
        longitude_deg=tuple(draw(st.lists(longitudes_deg(), min_size=n, max_size=n))),
        elevation_m=tuple(draw(st.lists(elevations_m(), min_size=n, max_size=n))),
        named_points=tuple(draw(st.lists(named_points(), max_size=4))),
        source=draw(source_refs()),
    )


def resolved_points(
    max_distance_m: float, point: st.SearchStrategy[NamedPoint] | None = None
) -> st.SearchStrategy[ResolvedPoint]:
    """Passages valides dont l'abscisse est dans ``[0, max_distance_m]``."""
    return st.builds(
        ResolvedPoint,
        point=point if point is not None else named_points(),
        distance_m=finite_floats(0.0, max_distance_m),
        elevation_m=elevations_m(),
        offset_m=finite_floats(0.0, 1e4),
    )


@st.composite
def route_profiles(
    draw: st.DrawFn, max_points: int = 60, duplicate_named_point: bool = False
) -> RouteProfile:
    """Profils valides.

    Grille : incréments de 0,1 m à 1 km depuis 0, donc strictement croissante.
    Si ``duplicate_named_point``, un même ``NamedPoint`` est résolu à deux abscisses
    distinctes, en plus des autres passages.
    """
    n = draw(st.integers(min_value=2, max_value=max_points))
    increments = draw(
        st.lists(finite_floats(0.1, 1000.0), min_size=n - 1, max_size=n - 1)
    )
    distance_m = tuple(accumulate(increments, initial=0.0))
    elevation_m = tuple(draw(st.lists(elevations_m(), min_size=n, max_size=n)))
    passages = draw(st.lists(resolved_points(distance_m[-1]), max_size=5))
    if duplicate_named_point:
        place = draw(named_points())
        a, b = draw(
            st.lists(
                finite_floats(0.0, distance_m[-1]), min_size=2, max_size=2, unique=True
            )
        )
        for abscissa in (a, b):
            passages.append(
                ResolvedPoint(
                    point=place,
                    distance_m=abscissa,
                    elevation_m=draw(elevations_m()),
                    offset_m=draw(finite_floats(0.0, 1e4)),
                )
            )
    passages.sort(key=lambda passage: passage.distance_m)
    return RouteProfile(
        route_name=draw(non_empty_texts()),
        source=draw(source_refs()),
        distance_m=distance_m,
        elevation_m=elevation_m,
        resolved_points=tuple(passages),
        step_m=draw(finite_floats(0.1, 1000.0)),
        build_parameters=draw(parameter_sets(max_size=3)),
        quality_flags=draw(quality_flag_sets()),
    )


# ---------------------------------------------------------------------------
# Construction du profil (M2)
# ---------------------------------------------------------------------------


@st.composite
def plausible_routes(draw: st.DrawFn) -> Route:
    """Marche bornée autour de 45°N, altitudes proches, lieux près du tracé."""
    steps = draw(
        st.lists(
            st.tuples(st.integers(-40, 40), st.integers(5, 50)),
            min_size=1,
            max_size=15,
        )
    )
    x_m, y_m = 0.0, 0.0
    latitude_deg, longitude_deg = [45.0], [6.0]
    for dx_m, dy_m in steps:
        x_m += dx_m
        y_m += dy_m
        latitude_deg.append(45 + math.degrees(y_m / EARTH_RADIUS_M))
        longitude_deg.append(
            6 + math.degrees(x_m / (EARTH_RADIUS_M * math.cos(math.pi / 4)))
        )
    places: list[NamedPoint] = []
    for i in range(draw(st.integers(1, 3))):
        at = draw(st.integers(0, len(steps)))
        # Le premier lieu est sur un sommet, les autres à proximité.
        offset_m = 0.0 if i == 0 else draw(finite_floats(-20, 20))
        places.append(
            NamedPoint(
                name=f"Lieu {i}",
                latitude_deg=latitude_deg[at],
                elevation_m=None,
                longitude_deg=longitude_deg[at]
                + math.degrees(
                    offset_m
                    / (EARTH_RADIUS_M * math.cos(math.radians(latitude_deg[at])))
                ),
            )
        )
    return Route(
        name="Marche synthétique",
        latitude_deg=tuple(latitude_deg),
        longitude_deg=tuple(longitude_deg),
        elevation_m=tuple(
            draw(
                st.lists(
                    finite_floats(1490, 1510),
                    min_size=len(steps) + 1,
                    max_size=len(steps) + 1,
                )
            )
        ),
        named_points=tuple(places),
        source=draw(source_refs()),
    )


@st.composite
def profile_parameter_sets(draw: st.DrawFn) -> ParameterSet:
    """Bornes M2, avec h >= 10 m pour garder une grille de taille modeste."""
    return ParameterSet(
        specs=PROFILE_PARAMETER_SPECS,
        values={
            spec.name: draw(
                finite_floats(
                    max(10.0, spec.minimum)
                    if spec.name == "grid_step_m"
                    else spec.minimum,
                    spec.maximum,
                )
            )
            for spec in PROFILE_PARAMETER_SPECS
        },
    )


# ---------------------------------------------------------------------------
# Projection (M3)
# ---------------------------------------------------------------------------


@st.composite
def projectable_route_profiles(
    draw: st.DrawFn, max_points: int = 15, duplicate_passage: bool = False
) -> RouteProfile:
    """Profils à pentes **bornées**, propres à être projetés.

    :func:`route_profiles` suit le contrat, qui autorise des pas de 0,1 m et des
    altitudes sur toute la plage ``[−500, 9000]`` : il en sort des pentes jusqu'à
    95 000, très au-delà du domaine ``|g| <= 1000`` où l'allure du modèle est
    garantie finie. Ici les pentes sont tirées d'abord, puis intégrées en altitudes
    écrêtées, ce qui les borne par construction — l'écrêtage ne fait que réduire
    une pente, jamais l'augmenter.

    ``duplicate_passage`` force deux passages résolus à la **même abscisse**, le cas
    où le moteur doit rendre exactement le même temps.
    """
    n = draw(st.integers(min_value=2, max_value=max_points))
    steps_m = draw(st.lists(finite_floats(10.0, 200.0), min_size=n - 1, max_size=n - 1))
    grades = draw(st.lists(finite_floats(-1.0, 1.0), min_size=n - 1, max_size=n - 1))
    distance_m = tuple(accumulate(steps_m, initial=0.0))
    elevation_m = [1500.0]
    for step_m, grade in zip(steps_m, grades, strict=True):
        elevation_m.append(min(3000.0, max(0.0, elevation_m[-1] + step_m * grade)))
    end_m = distance_m[-1]
    abscissae = sorted(
        draw(st.lists(finite_floats(0.0, end_m), min_size=1, max_size=3))
        if duplicate_passage
        else draw(st.lists(finite_floats(0.0, end_m), max_size=3))
    )
    if duplicate_passage:
        abscissae = sorted([*abscissae, abscissae[0]])
    return RouteProfile(
        route_name="Profil projetable",
        source=draw(source_refs()),
        distance_m=distance_m,
        elevation_m=tuple(elevation_m),
        resolved_points=tuple(
            ResolvedPoint(
                point=NamedPoint(f"Lieu {i}", 45.0, 6.0, None),
                distance_m=at_m,
                elevation_m=1500.0,
                offset_m=0.0,
            )
            for i, at_m in enumerate(abscissae)
        ),
        step_m=draw(finite_floats(10.0, 200.0)),
        build_parameters=draw(profile_parameter_sets()),
    )


def efforts() -> st.SearchStrategy[float]:
    """Facteurs d'effort dans les bornes de la spec du moteur."""
    return finite_floats(0.5, 1.5)


# ---------------------------------------------------------------------------
# Activité
# ---------------------------------------------------------------------------


def heart_rates_bpm() -> st.SearchStrategy[float]:
    return finite_floats(*HEART_RATE_RANGE_BPM)


@st.composite
def activities(draw: st.DrawFn) -> Activity:
    """Activités valides, ``start_time`` dans un fuseau à décalage fixe."""
    elapsed = draw(finite_floats(1.0, 1e6))
    hr_a, hr_b = draw(st.lists(heart_rates_bpm(), min_size=2, max_size=2))
    with_hr = draw(st.booleans())
    return Activity(
        activity_ref=draw(non_empty_texts()),
        sport=draw(sports()),
        source_activity_type=draw(st.one_of(st.none(), st.text(max_size=20))),
        start_time=draw(aware_datetimes()),
        elapsed_duration_s=elapsed,
        moving_duration_s=draw(finite_floats(min(1.0, elapsed), elapsed)),
        distance_m=draw(finite_floats(0.0, 1e6)),
        ascent_m=draw(finite_floats(0.0, 1e5)),
        descent_m=draw(finite_floats(0.0, 1e5)),
        average_hr_bpm=min(hr_a, hr_b) if with_hr else None,
        max_hr_bpm=max(hr_a, hr_b) if with_hr else None,
        stream_ref=draw(st.one_of(st.none(), file_names())),
        source=draw(source_refs()),
        quality_flags=draw(quality_flag_sets()),
    )


@st.composite
def track_point_streams(draw: st.DrawFn, max_points: int = 50) -> TrackPointStream:
    """Flux valides : temps strictement croissant, distance à paliers possibles."""
    n = draw(st.integers(min_value=1, max_value=max_points))
    start = draw(finite_floats(0.0, 1e3))
    time_increments = draw(
        st.lists(finite_floats(0.1, 60.0), min_size=n - 1, max_size=n - 1)
    )
    # 0 autorisé : un arrêt fait un palier de distance.
    distance_increments = draw(
        st.lists(finite_floats(0.0, 100.0), min_size=n - 1, max_size=n - 1)
    )

    def optional(values: st.SearchStrategy[float]) -> tuple[float, ...] | None:
        if draw(st.booleans()):
            return None
        return tuple(draw(st.lists(values, min_size=n, max_size=n)))

    return TrackPointStream(
        activity_ref=draw(non_empty_texts()),
        time_s=tuple(accumulate(time_increments, initial=start)),
        latitude_deg=optional(latitudes_deg()),
        longitude_deg=optional(longitudes_deg()),
        elevation_m=optional(elevations_m()),
        distance_m=(
            tuple(accumulate(distance_increments, initial=0.0))
            if draw(st.booleans())
            else None
        ),
        speed_ms=optional(finite_floats(0.0, 30.0)),
        heart_rate_bpm=optional(heart_rates_bpm()),
        source=draw(source_refs()),
        quality_flags=draw(quality_flag_sets()),
    )


# ---------------------------------------------------------------------------
# Courbe
# ---------------------------------------------------------------------------


@st.composite
def curve_provenances(draw: st.DrawFn) -> CurveProvenance:
    with_hr = draw(st.booleans())
    day_a, day_b = draw(st.lists(st.dates(), min_size=2, max_size=2))
    return CurveProvenance(
        activity_count=draw(st.integers(min_value=0, max_value=5000)),
        hr_center_bpm=draw(heart_rates_bpm()) if with_hr else None,
        hr_width_bpm=draw(finite_floats(0.1, 100.0)) if with_hr else None,
        date_from=min(day_a, day_b),
        date_to=max(day_a, day_b),
        source_activity_types=draw(st.frozensets(st.text(max_size=20), max_size=3)),
        min_duration_s=draw(st.one_of(st.none(), finite_floats(0.0, 1e5))),
        estimator=draw(non_empty_texts()),
        generated_at=draw(aware_datetimes()),
    )


@st.composite
def model_pace_curves(draw: st.DrawFn, max_bins: int = 10) -> PaceCurve:
    """Courbes telles que la lecture du M3 les produit, pas telles que le contrat
    les tolère.

    Le plat est **strictement encadré** et les bords sont à au moins 1 % de pente ;
    les vitesses tiennent dans le garde-fou de lecture, ``[0,01 ; 100]`` km/h. Ce
    sont les préconditions dont ``PaceModel`` dépend sans les revérifier, et que
    :func:`pace_curves` — qui suit le contrat, plus large — ne garantit pas.
    """
    half = max(1, max_bins // 2)
    negatives = draw(
        st.lists(finite_floats(-2.0, -0.01), min_size=1, max_size=half, unique=True)
    )
    positives = draw(
        st.lists(finite_floats(0.01, 2.0), min_size=1, max_size=half, unique=True)
    )
    grades = sorted([*negatives, *([0.0] if draw(st.booleans()) else []), *positives])
    n = len(grades)
    return PaceCurve(
        sport=draw(sports()),
        grade=tuple(grades),
        speed_ms=tuple(
            draw(
                st.lists(finite_floats(0.01 / 3.6, 100.0 / 3.6), min_size=n, max_size=n)
            )
        ),
        sample_count=tuple(
            draw(
                st.lists(
                    st.integers(min_value=0, max_value=10**6), min_size=n, max_size=n
                )
            )
        ),
        dispersion_ms=None,
        estimation=draw(curve_provenances()),
        source=draw(source_refs()),
    )


@st.composite
def pace_curves(draw: st.DrawFn, max_bins: int = 30) -> PaceCurve:
    """Courbes valides : pentes distinctes triées dans ``[-2, 2]``."""
    grades = sorted(
        draw(
            st.lists(
                finite_floats(*GRADE_RANGE), min_size=2, max_size=max_bins, unique=True
            )
        )
    )
    n = len(grades)
    return PaceCurve(
        sport=draw(sports()),
        grade=tuple(grades),
        speed_ms=tuple(
            draw(st.lists(finite_floats(0.01, 30.0), min_size=n, max_size=n))
        ),
        sample_count=tuple(
            draw(
                st.lists(
                    st.integers(min_value=0, max_value=10**6), min_size=n, max_size=n
                )
            )
        ),
        dispersion_ms=(
            tuple(draw(st.lists(finite_floats(0.0, 10.0), min_size=n, max_size=n)))
            if draw(st.booleans())
            else None
        ),
        estimation=draw(curve_provenances()),
        source=draw(st.one_of(st.none(), source_refs())),
    )


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

_LONG_STOP_S = (3600, 86400)


@st.composite
def projections(
    draw: st.DrawFn,
    min_passages: int = 2,
    max_passages: int = 8,
    stops: Literal["none", "long", "any"] = "any",
    edge_stops: bool = False,
    same_abscissa: bool = False,
    repeated_place: bool = False,
    fractional_times: bool = False,
) -> Projection:
    """Projections valides.

    Temps en secondes entières (flottants exacts) : les invariants de temps se
    comparent sans bruit d'arrondi. Options :

    - ``stops`` : arrêts nuls, longs (1 h à 24 h) ou quelconques aux passages ;
    - ``edge_stops`` : arrêt non nul au premier **et** au dernier passage ;
    - ``same_abscissa`` : deux passages consécutifs à la même abscisse ;
    - ``repeated_place`` : un même lieu nommé à deux passages d'abscisses distinctes ;
    - ``fractional_times`` : durées et arrêts en secondes non entières, le mouvement
      valant parfois exactement la durée du segment — le cas où l'arrondi flottant
      fait diverger ``Δmoving_time_s`` et ``Δtemps écoulé`` d'un ulp.
    """
    profile = draw(route_profiles(max_points=20))
    end_m = profile.distance_m[-1]
    n = draw(st.integers(min_value=min_passages, max_value=max_passages))
    if same_abscissa:
        n = max(n, 3)
    inner = sorted(
        draw(st.lists(finite_floats(0.0, end_m), min_size=n - 2, max_size=n - 2))
    )
    abscissae = [0.0, *inner, end_m]
    if same_abscissa:
        j = draw(st.integers(min_value=1, max_value=n - 2))
        abscissae[j] = abscissae[j - 1]
    # Un petit vivier de lieux : générer cinquante lieux distincts est trop lent.
    pool = draw(st.lists(named_points(), min_size=1, max_size=3))
    places = [draw(st.sampled_from(pool)) for _ in range(n)]
    if repeated_place:
        i, j = draw(
            st.lists(
                st.integers(min_value=0, max_value=n - 1),
                min_size=2,
                max_size=2,
                unique=True,
            ).filter(lambda ij: abscissae[ij[0]] != abscissae[ij[1]])
        )
        places[j] = places[i]

    def seconds(low: float, high: float) -> float:
        if fractional_times:
            return draw(finite_floats(low, high))
        return float(draw(st.integers(min_value=int(low), max_value=int(high))))

    def stop(index: int) -> float:
        if edge_stops and index in (0, n - 1):
            return seconds(1, _LONG_STOP_S[1])
        if stops == "none":
            return 0.0
        low = _LONG_STOP_S[0] if stops == "long" else 0
        return seconds(low, _LONG_STOP_S[1])

    passages: list[Passage] = []
    arrival = seconds(0, 1000)
    moving = seconds(0, arrival)
    for index in range(n):
        if index > 0:
            duration = seconds(0, 100_000)
            arrival = passages[-1].departure_s + duration
            # Parfois tout le segment en mouvement : le cas limite de l'invariant.
            moving += duration if draw(st.booleans()) else seconds(0, duration)
        passages.append(
            Passage(
                point=ResolvedPoint(
                    point=places[index],
                    distance_m=abscissae[index],
                    elevation_m=draw(elevations_m()),
                    offset_m=draw(finite_floats(0.0, 1e4)),
                ),
                moving_time_s=moving,
                arrival_s=arrival,
                departure_s=arrival + stop(index),
            )
        )
    return Projection(
        profile=profile,
        curve_ref=draw(non_empty_texts()),
        parameters=draw(parameter_sets(max_size=3)),
        passages=tuple(passages),
        start_time=draw(st.one_of(st.none(), aware_datetimes())),
        engine_version=draw(non_empty_texts()),
        generated_at=draw(aware_datetimes()),
    )


# ---------------------------------------------------------------------------
# Référence
# ---------------------------------------------------------------------------


def observed_passages(
    elapsed_s: st.SearchStrategy[float] | None = None,
) -> st.SearchStrategy[ObservedPassage]:
    return st.builds(
        ObservedPassage,
        point_name=non_empty_texts(),
        elapsed_s=elapsed_s if elapsed_s is not None else finite_floats(0.0, 1e6),
        distance_m=st.one_of(st.none(), finite_floats(0.0, 1e6)),
        convention=st.sampled_from(TimingConvention),
    )


@st.composite
def reference_performances(
    draw: st.DrawFn, max_passages: int = 10
) -> ReferencePerformance:
    """Performances valides : temps écoulés triés, conventions mélangées."""
    times = sorted(
        draw(st.lists(finite_floats(0.0, 1e6), min_size=2, max_size=max_passages))
    )
    return ReferencePerformance(
        athlete_ref=draw(non_empty_texts()),
        event_name=draw(non_empty_texts()),
        date=draw(st.dates()),
        passages=tuple(draw(observed_passages(st.just(t))) for t in times),
        source=draw(source_refs()),
    )


# ---------------------------------------------------------------------------
# Backtest (M4a) : sorties, traces, partitions
# ---------------------------------------------------------------------------


def artifact_refs(role: ArtifactRole | None = None) -> st.SearchStrategy[ArtifactRef]:
    """Artefacts valides, d'un rôle imposé ou quelconque."""
    return st.builds(
        ArtifactRef,
        source=source_refs(),
        available_at=aware_datetimes(),
        role=st.just(role) if role is not None else st.sampled_from(ArtifactRole),
    )


def route_references() -> st.SearchStrategy[RouteReference]:
    return st.builds(
        RouteReference,
        kind=st.sampled_from(ReferenceKind),
        artifact=artifact_refs(ArtifactRole.FORECAST_INPUT),
    )


@st.composite
def outings(draw: st.DrawFn, athlete_ref: str | None = None) -> Outing:
    """Sorties valides : écoulé entier de 1 s à ~28 h, doublons seulement si tracée."""
    athlete = athlete_ref if athlete_ref is not None else draw(non_empty_texts())
    start = draw(aware_datetimes())
    evaluation = artifact_refs(ArtifactRole.EVALUATION_OBSERVATION)
    traces = tuple(draw(st.lists(evaluation, max_size=3)))
    duplicates = tuple(draw(st.lists(evaluation, max_size=2))) if traces else ()
    portion: tuple[float, float] | None = None
    if draw(st.booleans()):
        a = draw(finite_floats(0.0, 1e5))
        portion = (a, a + draw(finite_floats(1.0, 1e5)))
    records = tuple(
        replace(record, athlete_ref=athlete)
        for record in draw(st.lists(reference_performances(max_passages=3), max_size=2))
    )
    return Outing(
        outing_id=draw(non_empty_texts()),
        athlete_ref=athlete,
        sport=draw(sports()),
        start_time=start,
        end_time=start + timedelta(seconds=draw(st.integers(1, 100_000))),
        traces=traces,
        duplicates=duplicates,
        route_id=draw(st.one_of(st.none(), non_empty_texts())),
        variant=draw(st.one_of(st.none(), non_empty_texts())),
        declared_portion_m=portion,
        reference=draw(st.one_of(st.none(), route_references())),
        dataset=draw(st.one_of(st.none(), st.sampled_from(DataSet))),
        label=draw(st.one_of(st.none(), st.sampled_from(OutingLabel))),
        external_records=records,
    )


@st.composite
def performances(draw: st.DrawFn, max_outings: int = 3) -> Performance:
    """Performances valides : un athlète, identifiants distincts, ordre du rang."""
    athlete = draw(non_empty_texts())
    items = draw(
        st.lists(
            outings(athlete_ref=athlete),
            min_size=1,
            max_size=max_outings,
            unique_by=lambda outing: outing.outing_id,
        )
    )
    items.sort(key=lambda outing: (outing.start_time, outing.outing_id))
    return Performance(civil_date=draw(st.dates()), outings=tuple(items))


@st.composite
def recorded_traces(draw: st.DrawFn, max_records: int = 30) -> RecordedTrace:
    """Traces valides quelconques : pas de 0,1 à 60 s, positions sur toute la plage."""
    n = draw(st.integers(min_value=2, max_value=max_records))
    steps = draw(st.lists(finite_floats(0.1, 60.0), min_size=n - 1, max_size=n - 1))
    return RecordedTrace(
        start_time=draw(aware_datetimes()),
        time_s=tuple(accumulate(steps, initial=0.0)),
        latitude_deg=tuple(draw(st.lists(latitudes_deg(), min_size=n, max_size=n))),
        longitude_deg=tuple(draw(st.lists(longitudes_deg(), min_size=n, max_size=n))),
        elevation_m=tuple(draw(st.lists(elevations_m(), min_size=n, max_size=n))),
        sources=tuple(draw(st.lists(source_refs(), min_size=1, max_size=3))),
        dropped_same_instant_count=draw(st.integers(min_value=0, max_value=10)),
    )


_GAP_STEP_S = (10.001, 120.0)
"""Pas d'un trou dans :func:`eventful_traces` : strictement au-delà de 10 s."""


@st.composite
def eventful_traces(draw: st.DrawFn) -> RecordedTrace:
    """Traces plausibles qui **contiennent toujours** un trou, des pas irréguliers et
    une immobilité assez longue pour devenir un arrêt sous ``θ_c``.

    Construction dans un plan local métrique autour d'une origine tirée entre
    ±60° de latitude, puis conversion en degrés :

    - une phase immobile garantie de 100 à 150 enregistrements à 1 s, position
      exactement répétée : au moins 68 s d'intervalles immobiles de fenêtre valide ;
    - une à quatre autres phases, la première à pas irréguliers (0,2 à 10 s) : arrêt
      (position répétée ou bruitée à ±0,5 m) ou déplacement (jusqu'à 3 m/s à
      l'horizontale, ±0,5 m/s à la verticale) ;
    - entre deux phases, un raccord de 1 s ou un trou (10,001 à 120 s), dont au
      moins un trou.
    """
    lat0 = draw(finite_floats(-60.0, 60.0))
    lon0 = draw(finite_floats(-170.0, 170.0))
    others = draw(st.integers(min_value=1, max_value=4))
    still_at = draw(st.integers(min_value=0, max_value=others))
    phases: list[tuple[str, int, bool]] = []
    for k in range(others):
        kind = draw(st.sampled_from(["still", "noisy", "move"]))
        irregular = k == 0 or draw(st.booleans())
        phases.append((kind, draw(st.integers(min_value=5, max_value=60)), irregular))
    phases.insert(still_at, ("still", draw(st.integers(100, 150)), False))
    forced_gap = draw(st.integers(min_value=0, max_value=len(phases) - 2))

    t_s, x_m, y_m, z_m = 0.0, 0.0, 0.0, 1000.0
    times, xs, ys, zs = [t_s], [x_m], [y_m], [z_m]
    for index, (kind, count, irregular) in enumerate(phases):
        if index > 0:
            gap = index - 1 == forced_gap or draw(st.booleans())
            t_s += draw(finite_floats(*_GAP_STEP_S)) if gap else 1.0
            times.append(t_s)
            xs.append(x_m)
            ys.append(y_m)
            zs.append(z_m)
        vx, vy, vz = 0.0, 0.0, 0.0
        if kind == "move":
            vx, vy = draw(finite_floats(-3.0, 3.0)), draw(finite_floats(-3.0, 3.0))
            vz = draw(finite_floats(-0.5, 0.5))
        for _ in range(count):
            dt = draw(finite_floats(0.2, 10.0)) if irregular else 1.0
            t_s += dt
            x_m, y_m, z_m = x_m + vx * dt, y_m + vy * dt, z_m + vz * dt
            dx_m, dy_m = (
                (draw(finite_floats(-0.5, 0.5)), draw(finite_floats(-0.5, 0.5)))
                if kind == "noisy"
                else (0.0, 0.0)
            )
            times.append(t_s)
            xs.append(x_m + dx_m)
            ys.append(y_m + dy_m)
            zs.append(z_m)
    scale_m = EARTH_RADIUS_M * math.cos(math.radians(lat0))
    return RecordedTrace(
        start_time=draw(aware_datetimes()),
        time_s=tuple(times),
        latitude_deg=tuple(lat0 + math.degrees(y / EARTH_RADIUS_M) for y in ys),
        longitude_deg=tuple(lon0 + math.degrees(x / scale_m) for x in xs),
        elevation_m=tuple(zs),
        sources=(draw(source_refs()),),
        dropped_same_instant_count=0,
    )


@st.composite
def clock_partitions(draw: st.DrawFn, max_intervals: int = 40) -> ClockPartition:
    """Partitions valides : instants depuis 0, états quelconques par convention."""
    n = draw(st.integers(min_value=1, max_value=max_intervals))
    steps = draw(st.lists(finite_floats(0.1, 20.0), min_size=n, max_size=n))
    states = tuple(
        tuple(draw(st.lists(st.sampled_from(IntervalState), min_size=n, max_size=n)))
        for _ in CLOCK_CONVENTIONS
    )
    return ClockPartition(time_s=tuple(accumulate(steps, initial=0.0)), states=states)


# ---------------------------------------------------------------------------
# Points de score (M4a-2a)
# ---------------------------------------------------------------------------


@st.composite
def score_point_observations(
    draw: st.DrawFn, status: PointStatus | None = None
) -> ScorePointObservation:
    """Observations valides : champs datés si et seulement si le statut date, comptes
    cohérents avec le statut, borne effective distincte seulement pour un ancrage."""
    status = status if status is not None else draw(st.sampled_from(PointStatus))
    nominal_m = draw(finite_floats(0.0, 1e5))
    effective_m = nominal_m
    if status is PointStatus.ANCHORED and draw(st.booleans()):
        effective_m = draw(finite_floats(0.0, 1e5))
    position = time_s = lateral_m = realized_m = None
    if status in (PointStatus.FOUND, PointStatus.ANCHORED):
        position = (
            float(draw(st.integers(0, 100_000)))
            if status is PointStatus.ANCHORED
            else draw(finite_floats(0.0, 1e5))
        )
        time_s = draw(finite_floats(0.0, 1e6))
        lateral_m = draw(finite_floats(-1e3, 1e3))
        realized_m = draw(finite_floats(0.0, 1e6))
    candidates, events = 0, 0
    if status is PointStatus.FOUND:
        candidates, events = draw(st.integers(1, 20)), 1
    elif status is PointStatus.AMBIGUOUS and draw(st.booleans()):
        events = draw(st.integers(2, 20))
        candidates = draw(st.integers(events, 40))
    return ScorePointObservation(
        index=draw(st.integers(0, 1000)),
        nominal_m=nominal_m,
        effective_m=effective_m,
        status=status,
        position=position,
        time_s=time_s,
        lateral_m=lateral_m,
        realized_m=realized_m,
        candidate_count=candidates,
        event_count=events,
    )


@st.composite
def straight_cases(draw: st.DrawFn) -> StraightCase:
    """§ 8, test 5 du brief M4a-2a : référence droite sur le parallèle de base, de 260
    à 3 000 m, non multiple de ``Δ`` (reste ``>= 1`` m) ; trace partant de
    ``x_0 ∈ [−20 ; −1]``, ``x`` strictement croissant, 0,3 à 3 m/s, pas de temps
    multiples de ``1/64`` s de ``1/64`` à ``10`` s inclus, ``|y| <= 10`` m et
    ``|Δy| <= Δx`` ; motifs cyclés, plafonnés à ``MAX_STRAIGHT_RECORDS``."""
    length_m = float(draw(st.integers(260, 3000).filter(lambda n: n % 250 >= 1)))
    steps = draw(
        st.lists(
            st.tuples(finite_floats(0.3, 3.0), st.integers(1, 640)),
            min_size=1,
            max_size=8,
        )
    )
    mean_step_m = sum(v * m / 64 for v, m in steps) / len(steps)
    assume((length_m + 20) / mean_step_m < MAX_STRAIGHT_RECORDS)
    return straight_case(
        length_m,
        draw(finite_floats(-20.0, -1.0)),
        draw(finite_floats(-10.0, 10.0)),
        steps,
        draw(st.lists(finite_floats(-1.0, 1.0), min_size=1, max_size=8)),
    )


@st.composite
def wandering_cases(draw: st.DrawFn) -> MatchCase:
    """§ 8, test 5 du brief M4a-2a : référence en ligne brisée (1 à 5 branches de 60
    à 400 m, virages jusqu'à 120°) à 45° N, et trace qui erre autour : écarts
    jusqu'à 80 m, retours en arrière, arrêts, trous de 10,001 à 120 s. Début et fin
    tirés de part et d'autre des lignes de départ et d'arrivée (``±40`` m le long du
    tracé, ``±35`` m de côté) : ancrages, franchissements et absences possibles.
    ``Δ ∈ {100, 250}``, ``ε ∈ {15, 30, 45}``."""
    heading = draw(finite_floats(0.0, 2 * math.pi))
    vertices = [(0.0, 0.0)]
    total_m = 0.0
    for _ in range(draw(st.integers(1, 5))):
        length_m = draw(st.integers(60, 400))
        x_m, y_m = vertices[-1]
        vertices.append(
            (x_m + length_m * math.cos(heading), y_m + length_m * math.sin(heading))
        )
        total_m += length_m
        heading += math.radians(draw(st.integers(-120, 120)))
    phases: list[Phase] = []
    for _ in range(draw(st.integers(0, 5))):
        kind = draw(st.sampled_from(["follow", "back", "detour", "stop", "gap"]))
        speed_ms = draw(finite_floats(0.5, 3.0))
        step_s = draw(st.sampled_from([1.0, 2.0, 3.0, 5.0]))
        if kind == "follow":
            delta_m, offset_m = draw(st.integers(20, 300)), draw(finite_floats(-60, 60))
            phases.append(("move", delta_m, offset_m, speed_ms, step_s))
        elif kind == "back":
            delta_m, offset_m = (
                -draw(st.integers(10, 100)),
                draw(finite_floats(-60, 60)),
            )
            phases.append(("move", delta_m, offset_m, speed_ms, step_s))
        elif kind == "detour":
            delta_m, offset_m = draw(st.integers(0, 50)), draw(finite_floats(-80, 80))
            phases.append(("move", delta_m, offset_m, speed_ms, step_s))
        elif kind == "stop":
            phases.append(("stop", draw(st.integers(2, 30)), 0.0, 0.0, 0.0))
        else:
            gap_s = draw(finite_floats(10.001, 120.0))
            phases.append(("gap", draw(st.integers(-30, 60)), gap_s, 0.0, 0.0))
    phases.append(
        (
            "to",
            total_m + draw(st.integers(-40, 40)),
            draw(finite_floats(-35.0, 35.0)),
            draw(finite_floats(0.5, 3.0)),
            draw(st.sampled_from([1.0, 2.0, 3.0, 5.0])),
        )
    )
    parameters = matching_parameters(
        score_step_m=draw(st.sampled_from([100.0, 250.0])),
        lateral_tolerance_m=draw(st.sampled_from([15.0, 30.0, 45.0])),
    )
    start = (float(draw(st.integers(-40, 40))), draw(finite_floats(-35.0, 35.0)))
    return wandering_case(vertices, start, phases, parameters)
