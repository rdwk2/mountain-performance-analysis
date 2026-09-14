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
from datetime import datetime, timedelta, timezone
from itertools import accumulate

from hypothesis import strategies as st

from mountain_perf.schemas import (
    ELEVATION_RANGE_M,
    HEART_RATE_RANGE_BPM,
    LATITUDE_RANGE_DEG,
    LONGITUDE_RANGE_DEG,
    Activity,
    NamedPoint,
    ParameterSet,
    ParameterSpec,
    PointKind,
    QualityFlag,
    ResolvedPoint,
    Route,
    RouteProfile,
    SourceRef,
    Sport,
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
