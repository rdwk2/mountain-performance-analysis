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

from hypothesis import strategies as st

from mountain_perf.schemas import (
    ELEVATION_RANGE_M,
    LATITUDE_RANGE_DEG,
    LONGITUDE_RANGE_DEG,
    ParameterSet,
    ParameterSpec,
    QualityFlag,
    SourceRef,
    Sport,
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
