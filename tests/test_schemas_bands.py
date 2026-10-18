"""Contrats des fourchettes (``0010`` D11 ; précision de M4d-2).

Pour chaque contrat de ``schemas/bands.py`` : des objets valides, puis une violation par
invariant, refusée par ``ContractError`` avec le fragment de son message. Les contrats
sont stockés (format 4) : le document ``OutingBands`` se relit à l'identique. Aussi :
les constantes de D11 et la place des types dans le dictionnaire.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from mountain_perf.backtest import decode_document, encode_document
from mountain_perf.schemas import (
    BAND_ALPHA,
    BAND_LABEL,
    BAND_MODELS,
    BAND_PENALTY,
    BAND_QUANTILE_ORDERS,
    BAND_UNAVAILABILITY,
    BANDS_FIRST_FORMAT,
    MEMBER_UNAVAILABILITY,
    METRIC_RELATIVE_TOLERANCE,
    RESIDUAL_UNAVAILABILITY,
    WEIGHT_SUM_TOLERANCE,
    BandElement,
    BandQuantiles,
    MetricValue,
    ModelBand,
    ModelKind,
    OutingBands,
    ReservoirMember,
    Unavailability,
)
from mountain_perf.schemas._dictionary import DOCUMENTED_TYPES
from mountain_perf.validation import ContractError

U = Unavailability
D1, D2, D3 = date(2026, 6, 1), date(2026, 6, 5), date(2026, 6, 20)
WINDOW = (date(2026, 6, 1), date(2026, 6, 10))


def refused(fragment: str) -> Any:
    return pytest.raises(ContractError, match=re.escape(fragment))


def member(**changes: Any) -> ReservoirMember:
    """Un membre valide : une sortie, trois segments, 300 m, 1 100 s."""
    base = ReservoirMember(
        civil_date=D1,
        in_window=True,
        outing_count=1,
        segment_count=3,
        support_m=300.0,
        observed_s=1100.0,
        unavailability=None,
    )
    return replace(base, **changes)


def score(lower: float, upper: float, observed: float) -> float:
    return math.fsum(
        (
            upper - lower,
            10.0 * max(lower - observed, 0.0),
            10.0 * max(observed - upper, 0.0),
        )
    )


def element(
    forecast: float = 1000.0,
    q: tuple[float, float, float, float] = (-0.1, 0.0, 0.05, 0.1),
    observed: float | None = 1050.0,
    *,
    weight: float = 1.0,
    base: float = 1000.0,
    covered: bool | None = None,
    motif: Unavailability | None = None,
    single: bool = False,
) -> BandElement:
    """Un élément valide : bornes ``P · exp(Q)``, ``IS`` et « couvert » cohérents."""
    lower, median, prudent, upper = (forecast * math.exp(v) for v in q)
    observed_s = observed if motif is None else None
    is_covered = covered
    if is_covered is None and observed_s is not None and not single:
        is_covered = lower <= observed_s <= upper
    return BandElement(
        forecast_s=forecast,
        weight=weight,
        base_s=base,
        lower_s=lower,
        median_s=median,
        prudent_s=prudent,
        upper_s=upper,
        width_s=upper - lower,
        observed_s=observed_s,
        observation=motif,
        score_s=None if observed_s is None else score(lower, upper, observed_s),
        covered=is_covered,
    )


def residuals(values: Sequence[float | Unavailability]) -> tuple[MetricValue, ...]:
    return tuple(
        MetricValue(None, v, 3)
        if isinstance(v, Unavailability)
        else MetricValue(v, None, 3)
        for v in values
    )


def projected(values: Sequence[float | Unavailability]) -> tuple[float | None, ...]:
    return tuple(None if isinstance(v, Unavailability) else 1000.0 for v in values)


def quantiles_of(values: list[float]) -> BandQuantiles:
    ordered = sorted(values)
    n = len(ordered)
    picked = [ordered[(n * a + b - 1) // b - 1] for a, b in BAND_QUANTILE_ORDERS]
    return BandQuantiles(*picked)


def band(
    values: Sequence[float | Unavailability] | None = None,
    *,
    model: ModelKind = ModelKind.V0_RAW,
    forecasts: tuple[float, ...] = (400.0, 1000.0),
    observed: tuple[float | None, ...] = (420.0, 1050.0),
    weights: tuple[float, ...] = (0.25, 0.75),
    bases: tuple[float, ...] | None = None,
    status: Unavailability | None = None,
    **changes: Any,
) -> ModelBand:
    """Une fourchette valide d'un modèle, calculée par la règle à partir des résidus."""
    values = [0.1, -0.1, 0.0] if values is None else values
    available = [v for v in values if not isinstance(v, Unavailability)]
    failed = any(v is U.MODEL_ERROR for v in values)
    if failed or not available:
        status = U.MODEL_ERROR if failed else U.INSUFFICIENT_SUPPORT
        result = ModelBand(
            model,
            residuals(values),
            projected(values),
            None,
            (),
            None,
            None,
            None,
            None,
            None,
            None,
            status,
        )
        return replace(result, **changes)
    q = quantiles_of(available)
    if status is not None:
        result = ModelBand(
            model,
            residuals(values),
            projected(values),
            q,
            (),
            None,
            None,
            None,
            None,
            None,
            None,
            status,
        )
        return replace(result, **changes)
    single = len(available) == 1
    bases = forecasts if bases is None else bases
    elements = tuple(
        element(
            p,
            q.values,
            t,
            weight=w,
            base=b,
            single=single,
            motif=None if t is not None else U.ABSENT,
        )
        for p, t, w, b in zip(forecasts, observed, weights, bases, strict=True)
    )
    seen = sum(e.observed for e in elements)
    missing = next((e.observation for e in elements if e.observation is not None), None)
    totals: tuple[MetricValue, MetricValue, MetricValue | None, bool | None]
    if missing is not None:
        absent = MetricValue(None, missing, seen)
        totals = (absent, absent, None if single else absent, None)
    else:
        total = math.fsum(
            e.weight * e.score_s for e in elements if e.score_s is not None
        )
        norm = math.fsum(
            e.weight * e.score_s / e.base_s for e in elements if e.score_s is not None
        )
        count = len(elements)
        cover = None
        every = None
        if not single:
            cover = MetricValue(
                math.fsum(e.weight for e in elements if e.covered), None, count
            )
            every = all(e.covered for e in elements)
        totals = (
            MetricValue(total, None, count),
            MetricValue(norm, None, count),
            cover,
            every,
        )
    result = ModelBand(
        model,
        residuals(values),
        projected(values),
        q,
        elements,
        *totals,
        MetricValue(0.05, None, 2),
        MetricValue(30.0, None, 2),
        None,
    )
    return replace(result, **changes)


def bands(**changes: Any) -> OutingBands:
    """Un document valide : trois membres, cinq modèles."""
    members = (member(), member(civil_date=D2), member(civil_date=D3, in_window=False))
    base = OutingBands(
        outing_id="o",
        window_from=WINDOW[0],
        window_to=WINDOW[1],
        label=BAND_LABEL,
        multi_outing=False,
        members=members,
        models=tuple(
            band(
                model=m,
                forecasts=(400.0, 1000.0) if m is ModelKind.V0_RAW else (380.0, 950.0),
                bases=(400.0, 1000.0),
            )
            for m in BAND_MODELS
        ),
    )
    return replace(base, **changes)


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------


def test_band_constants_follow_0010_d11() -> None:
    """``alpha = 0,20`` ; ``2/alpha = 10`` ; quantiles 0,1, 0,5, 2/3, 0,9 en fractions
    exactes ; l'étiquette obligatoire ; les cinq modèles dans l'ordre ; le format 4."""
    assert BAND_ALPHA == 0.2
    assert BAND_PENALTY == 10.0
    assert BAND_QUANTILE_ORDERS == ((1, 10), (1, 2), (2, 3), (9, 10))
    assert BAND_LABEL == "plage de scénarios — calibration non disponible"
    assert BAND_MODELS == (
        ModelKind.V0_RAW,
        ModelKind.V0_RECALIBRATED,
        ModelKind.CONSTANT_SPEED,
        ModelKind.NAISMITH,
        ModelKind.TOBLER,
    )
    assert BANDS_FIRST_FORMAT == 4
    assert {U.INSUFFICIENT_SUPPORT, U.ZERO_TIME} == MEMBER_UNAVAILABILITY
    assert {
        U.INSUFFICIENT_SUPPORT,
        U.ZERO_TIME,
        U.MODEL_ERROR,
        U.NOT_CALIBRATED,
    } == RESIDUAL_UNAVAILABILITY
    assert {
        U.INSUFFICIENT_SUPPORT,
        U.MODEL_ERROR,
        U.NOT_CALIBRATED,
    } == BAND_UNAVAILABILITY


def test_band_types_are_documented_in_reading_order() -> None:
    """Les cinq contrats ferment le dictionnaire, dans l'ordre de lecture, juste après
    ceux de la dérive (M4d-1)."""
    assert DOCUMENTED_TYPES[-5:] == (
        ReservoirMember,
        BandQuantiles,
        BandElement,
        ModelBand,
        OutingBands,
    )
    assert DOCUMENTED_TYPES[-6].__name__ == "OutingDrift"


# ---------------------------------------------------------------------------
# ReservoirMember
# ---------------------------------------------------------------------------


def test_member_accepts_the_three_states() -> None:
    assert member().available
    unsupported = member(
        outing_count=0,
        segment_count=0,
        support_m=0.0,
        observed_s=None,
        unavailability=U.INSUFFICIENT_SUPPORT,
    )
    assert not unsupported.available
    zero = member(observed_s=None, unavailability=U.ZERO_TIME)
    assert zero.unavailability is U.ZERO_TIME
    contributing_without_segment = member(
        segment_count=0,
        support_m=0.0,
        observed_s=None,
        unavailability=U.INSUFFICIENT_SUPPORT,
    )
    assert contributing_without_segment.outing_count == 1


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"outing_count": -1}, "outing_count doit être >= 0, reçu -1."),
        ({"segment_count": -1}, "segment_count doit être >= 0, reçu -1."),
        ({"outing_count": 0}, "des segments admis viennent d'une sortie contributrice"),
        ({"support_m": math.inf}, "support_m"),
        (
            {"support_m": 0.0},
            "support_m est nul si et seulement s'il n'y a aucun segment",
        ),
        (
            {
                "segment_count": 0,
                "observed_s": None,
                "unavailability": U.INSUFFICIENT_SUPPORT,
            },
            "support_m est nul si et seulement s'il n'y a aucun segment",
        ),
        ({"support_m": -1.0}, "support_m doit être >= 0, reçu -1.0."),
        ({"observed_s": None}, "exactement un de observed_s et unavailability"),
        (
            {"unavailability": U.ZERO_TIME},
            "exactement un de observed_s et unavailability",
        ),
        ({"observed_s": 0.0}, "observed_s doit être > 0, reçu 0.0."),
        ({"observed_s": math.nan}, "observed_s"),
        (
            {"observed_s": None, "unavailability": U.MODEL_ERROR},
            "motif d'un membre hors de la liste",
        ),
        (
            {"observed_s": None, "unavailability": U.INSUFFICIENT_SUPPORT},
            "support insuffisant si et seulement si aucun segment admis",
        ),
        (
            {
                "segment_count": 0,
                "support_m": 0.0,
                "observed_s": None,
                "unavailability": U.ZERO_TIME,
            },
            "support insuffisant si et seulement si aucun segment admis",
        ),
    ],
)
def test_member_refusals(changes: dict[str, Any], fragment: str) -> None:
    with refused(fragment):
        member(**changes)


def test_member_negative_support_is_refused_before_its_sign() -> None:
    """Un support négatif avec des segments : refusé par la règle « nul si et seulement
    si aucun segment » n'est pas en cause ; c'est le signe qui l'est."""
    with refused("support_m doit être >= 0"):
        member(support_m=-5.0)


# ---------------------------------------------------------------------------
# BandQuantiles et BandElement
# ---------------------------------------------------------------------------


def test_quantiles_accept_equal_values_and_refuse_disorder() -> None:
    assert BandQuantiles(0.0, 0.0, 0.0, 0.0).values == (0.0, 0.0, 0.0, 0.0)
    with refused("les quantiles sont dans l'ordre low <= median <= prudent <= high"):
        BandQuantiles(0.0, 0.1, 0.05, 0.2)
    with refused("les quantiles sont dans l'ordre"):
        BandQuantiles(0.2, 0.1, 0.15, 0.3)
    with refused("les quantiles sont dans l'ordre"):
        BandQuantiles(0.0, 0.1, 0.3, 0.2)
    with refused("high"):
        BandQuantiles(0.0, 0.1, 0.2, math.inf)


def test_element_accepts_observed_unobserved_and_single() -> None:
    assert element().observed
    assert element(observed=1200.0).covered is False
    assert element(observed=None, motif=U.ABSENT).score_s is None
    assert element(single=True).covered is None


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"forecast_s": 0.0}, "forecast_s doit être > 0"),
        ({"base_s": -1.0}, "base_s doit être > 0"),
        ({"weight": -0.1}, "weight doit être >= 0"),
        ({"weight": math.nan}, "weight"),
        ({"lower_s": 0.0}, "lower_s doit être > 0"),
        (
            {"median_s": 2000.0},
            "les bornes sont dans l'ordre lower <= median <= prudent <= upper",
        ),
        ({"upper_s": math.inf}, "upper_s"),
        ({"width_s": 1.0}, "width_s doit valoir upper_s − lower_s"),
        ({"observed_s": None}, "exactement un de observed_s et observation"),
        ({"observation": U.ABSENT}, "exactement un de observed_s et observation"),
        ({"observed_s": -1.0}, "observed_s doit être >= 0"),
        ({"score_s": 1.0}, "score_s doit valoir (u − l) + 10 (l − T)₊ + 10 (T − u)₊"),
        ({"score_s": None}, "score_s doit valoir"),
        ({"covered": False}, "covered vaut l <= T <= u"),
    ],
)
def test_element_refusals(changes: dict[str, Any], fragment: str) -> None:
    with refused(fragment):
        replace(element(), **changes)


def test_element_unobserved_refusals() -> None:
    hidden = element(observed=None, motif=U.ABSENT)
    with refused("motif d'observation hors de la liste"):
        replace(hidden, observation=U.MODEL_ERROR)
    with refused("un élément non observé n'a ni score_s ni covered."):
        replace(hidden, score_s=1.0)
    with refused("un élément non observé n'a ni score_s ni covered."):
        replace(hidden, covered=True)


def test_element_score_is_held_at_the_bit() -> None:
    """``IS`` revérifié au bit, sur un élément sous la borne et un au-dessus."""
    below = element(observed=100.0)
    assert below.score_s == math.fsum(
        (below.upper_s - below.lower_s, 10.0 * (below.lower_s - 100.0), 0.0)
    )
    above = element(observed=5000.0)
    assert above.score_s == math.fsum(
        (above.upper_s - above.lower_s, 0.0, 10.0 * (5000.0 - above.upper_s))
    )
    with refused("score_s doit valoir"):
        replace(above, score_s=math.nextafter(above.score_s, 0.0))


# ---------------------------------------------------------------------------
# ModelBand
# ---------------------------------------------------------------------------


def test_band_accepts_each_status() -> None:
    ok = band()
    assert ok.available
    assert ok.count == 3
    assert (
        band([U.NOT_CALIBRATED, U.ZERO_TIME]).unavailability is U.INSUFFICIENT_SUPPORT
    )
    assert band([0.1, U.MODEL_ERROR]).unavailability is U.MODEL_ERROR
    calibrated = band(model=ModelKind.NAISMITH, status=U.NOT_CALIBRATED)
    assert calibrated.quantiles is not None
    assert band(status=U.MODEL_ERROR).elements == ()
    assert band(observed=(420.0, None)).interval_score_s == MetricValue(
        None, U.ABSENT, 1
    )
    single = band([0.1])
    assert single.coverage is None
    assert single.all_covered is None


def test_band_quantiles_are_order_statistics_at_integer_ranks() -> None:
    """Rangs ⌈n q⌉ : pour n = 10, rangs 1, 5, 7, 9."""
    values = [float(v) for v in (9, 1, 8, 2, 7, 3, 6, 4, 5, 0)]
    q = band(values).quantiles
    assert q is not None
    assert q.values == (0.0, 4.0, 6.0, 8.0)
    with refused("les quantiles sont les statistiques d'ordre de rang ⌈n q⌉"):
        band(values, quantiles=BandQuantiles(0.0, 5.0, 6.0, 8.0))


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        (
            {"model": ModelKind.CANDIDATE},
            "model doit être l'un des cinq modèles du rapport",
        ),
        (
            {"projected_s": (1000.0,)},
            "projected_s (1) et residuals (3) ont la même longueur.",
        ),
        (
            {"projected_s": (None, 1000.0, 1000.0)},
            "projected_s[0] est présent si et seulement si",
        ),
        ({"projected_s": (0.0, 1000.0, 1000.0)}, "projected_s[0] doit être > 0"),
        ({"unavailability": U.ZERO_TIME}, "statut de la fourchette hors de la liste"),
        ({"quantiles": None}, "des résidus disponibles ont leurs quantiles."),
        (
            {"unavailability": U.MODEL_ERROR},
            "les éléments sont vides si et seulement si",
        ),
        ({"elements": ()}, "les éléments sont vides si et seulement si"),
        ({"median_usage_target": None}, "une fourchette à bornes publie sa médiane."),
        ({"interval_score_s": None}, "une fourchette à bornes publie ses scores."),
        ({"coverage": None}, "n >= 2 : la couverture est publiée."),
        ({"all_covered": False}, "all_covered vaut « tous couverts »"),
    ],
)
def test_band_refusals(changes: dict[str, Any], fragment: str) -> None:
    with refused(fragment):
        band(**changes)


def test_band_refuses_a_residual_motif_outside_the_list() -> None:
    with refused("residuals[1] : motif hors de la liste"):
        band([0.1, U.ABSENT, 0.0])


def test_band_status_order() -> None:
    """Erreur du modèle avant support insuffisant ; sans quantiles ni éléments."""
    with refused("un résidu en erreur du modèle : statut model_error"):
        band([U.MODEL_ERROR], unavailability=U.INSUFFICIENT_SUPPORT)
    with refused("aucun résidu : statut insufficient_support"):
        band([U.ZERO_TIME], model=ModelKind.NAISMITH, unavailability=U.NOT_CALIBRATED)
    with refused("aucun résidu : statut insufficient_support"):
        band([U.ZERO_TIME], quantiles=BandQuantiles(0.0, 0.0, 0.0, 0.0))
    with refused("v0 brut n'est jamais non calé"):
        band(status=U.NOT_CALIBRATED)
    with refused("support insuffisant : aucun résidu disponible (n = 0), reçu n = 2."):
        band([0.1, -0.1], status=U.INSUFFICIENT_SUPPORT)


def test_band_weights_sum_to_one() -> None:
    """Les poids ``w_k`` des éléments somment à 1 (D7.4), à ``WEIGHT_SUM_TOLERANCE``
    près ; une somme de 1,5 (couverture possible de 1,5) est refusée."""
    assert band(weights=(0.25, 0.75 + 0.5 * WEIGHT_SUM_TOLERANCE)).available
    with refused("les poids des éléments somment à 1 à 1e-09 près (D7.4), reçu 1.5."):
        band(weights=(0.5, 1.0))
    with refused("les poids des éléments somment à 1 à"):
        band(weights=(0.25, 0.75 + 3 * WEIGHT_SUM_TOLERANCE))


@pytest.mark.parametrize(
    "name",
    [
        "interval_score_s",
        "normalised_score",
        "coverage",
        "median_usage_target",
        "median_max_abs_error_s",
        "all_covered",
    ],
)
def test_band_without_elements_carries_nothing_else(name: str) -> None:
    unavailable = band(status=U.MODEL_ERROR)
    changes: dict[str, Any] = {
        name: True if name == "all_covered" else MetricValue(1.0, None, 1)
    }
    with refused(
        "une fourchette sans éléments n'a ni scores, ni couverture, ni médiane."
    ):
        replace(unavailable, **changes)


def test_band_bounds_are_checked_against_forecast_and_quantiles() -> None:
    ok = band()
    first = ok.elements[0]
    moved = replace(
        first,
        upper_s=first.upper_s * (1 + 1e-9),
        width_s=first.upper_s * (1 + 1e-9) - first.lower_s,
        score_s=score(first.lower_s, first.upper_s * (1 + 1e-9), 420.0),
    )
    with refused("elements[0] : chaque borne vaut P_k · exp(Q)"):
        replace(ok, elements=(moved, *ok.elements[1:]))
    # Un exp(Q) qui déborde, des bornes finies (P_k minuscule) : branche défensive.
    bound = 1e-300 * math.exp(100.0) * math.exp(700.0)
    tiny = BandElement(
        1e-300, 1.0, 1e-300, bound, bound, bound, bound, 0.0, None, U.ABSENT, None, None
    )
    with refused("quantiles hors du domaine d'exp"):
        ModelBand(
            ModelKind.V0_RAW,
            residuals([800.0, 800.0]),
            projected([800.0, 800.0]),
            BandQuantiles(800.0, 800.0, 800.0, 800.0),
            (tiny,),
            MetricValue(None, U.ABSENT, 0),
            MetricValue(None, U.ABSENT, 0),
            MetricValue(None, U.ABSENT, 0),
            None,
            MetricValue(0.1, None, 1),
            MetricValue(1.0, None, 1),
            None,
        )


def test_band_single_residual_rules() -> None:
    single = band([0.1])
    first = single.elements[0]
    with refused("elements[0] : n = 1, aucun élément n'est dit couvert"):
        replace(single, elements=(replace(first, covered=False), *single.elements[1:]))
    with refused("n = 1 : ni couverture, ni « tous couverts »"):
        replace(single, coverage=MetricValue(1.0, None, 2))
    many = band()
    with refused("elements[0] : un élément observé dit s'il est couvert"):
        replace(
            many, elements=(replace(many.elements[0], covered=None), *many.elements[1:])
        )


def test_band_aggregates_are_held_at_the_bit() -> None:
    ok = band()
    assert ok.interval_score_s is not None
    value = ok.interval_score_s.value
    assert value is not None
    with refused("scores et couverture de K observé"):
        replace(ok, interval_score_s=MetricValue(math.nextafter(value, 0.0), None, 2))
    with refused("scores et couverture de K observé"):
        replace(ok, interval_score_s=MetricValue(value, None, 3))
    norm = ok.normalised_score
    assert norm is not None
    assert norm.value == math.fsum(
        e.weight * e.score_s / e.base_s for e in ok.elements if e.score_s is not None
    )


def test_band_unobserved_element_makes_aggregates_unavailable() -> None:
    partial = band(observed=(None, 1050.0))
    assert partial.interval_score_s == MetricValue(None, U.ABSENT, 1)
    assert partial.coverage == MetricValue(None, U.ABSENT, 1)
    assert partial.all_covered is None
    with refused("un élément non observé : scores et couverture indisponibles"):
        replace(partial, interval_score_s=MetricValue(None, U.ABSENT, 2))
    with refused("un élément non observé : pas de « tous couverts »."):
        replace(partial, all_covered=False)


# ---------------------------------------------------------------------------
# OutingBands
# ---------------------------------------------------------------------------


def test_outing_bands_accept_and_round_trip_at_format_4() -> None:
    document = bands()
    data = encode_document(document, BANDS_FIRST_FORMAT)
    assert decode_document(data, OutingBands, BANDS_FIRST_FORMAT) == document
    with pytest.raises(TypeError):
        encode_document(document, BANDS_FIRST_FORMAT - 1)


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"outing_id": ""}, "outing_id"),
        (
            {"window_from": date(2026, 6, 11)},
            "window_from (2026-06-11) précède window_to",
        ),
        ({"label": "plage"}, "label doit valoir"),
        ({"models": ()}, "models porte les cinq modèles du rapport dans l'ordre"),
    ],
)
def test_outing_bands_refusals(changes: dict[str, Any], fragment: str) -> None:
    with refused(fragment):
        bands(**changes)


def test_outing_bands_members_order_and_window() -> None:
    document = bands()
    first, second, third = document.members
    with refused("les membres sont par jour strictement croissant"):
        replace(document, members=(second, first, third))
    with refused("les membres sont par jour strictement croissant"):
        replace(document, members=(first, first, third))
    with refused("le membre 2026-06-20 est hors de la fenêtre"):
        replace(document, members=(first, second, replace(third, in_window=True)))
    with refused("le membre 2026-06-01 est dans la fenêtre"):
        replace(document, members=(replace(first, in_window=False), second, third))
    edge = replace(document, window_from=D1, window_to=D2)
    assert [m.in_window for m in edge.members] == [True, True, False]
    with refused("le membre 2026-06-05 est hors de la fenêtre"):
        replace(document, window_to=D1)


def test_outing_bands_model_order() -> None:
    document = bands()
    swapped = (document.models[1], document.models[0], *document.models[2:])
    with refused("models porte les cinq modèles du rapport dans l'ordre"):
        replace(document, models=swapped)


def test_outing_bands_residuals_follow_members() -> None:
    document = bands()
    raw = document.models[0]
    with refused("v0_raw : un résidu par membre, reçu 2 pour 3 membres."):
        replace(document, models=(band([0.1, 0.0]), *document.models[1:]))
    unsupported = member(
        civil_date=D3,
        in_window=False,
        outing_count=0,
        segment_count=0,
        support_m=0.0,
        observed_s=None,
        unavailability=U.INSUFFICIENT_SUPPORT,
    )
    members = (*document.members[:2], unsupported)
    with refused("v0_raw, 2026-06-20 : l'effectif du résidu est le nombre de segments"):
        replace(document, members=members)
    zero = replace(document.members[2], observed_s=None, unavailability=U.ZERO_TIME)
    with refused(
        "v0_raw, 2026-06-20 : un membre indisponible donne un résidu à son motif"
    ):
        replace(document, members=(*document.members[:2], zero))
    with refused("v0_raw, 2026-06-01 : un membre disponible n'a pas le motif"):
        replace(document, models=(band([U.ZERO_TIME, -0.1, 0.0]), *document.models[1:]))
    del raw


def test_outing_bands_raw_never_not_calibrated() -> None:
    document = bands()
    with refused("v0 brut, 2026-06-01 : jamais non calé"):
        replace(
            document, models=(band([U.NOT_CALIBRATED, -0.1, 0.0]), *document.models[1:])
        )


def test_outing_bands_elements_agree_across_models() -> None:
    document = bands()
    other = band(
        model=ModelKind.V0_RECALIBRATED,
        observed=(421.0, 1050.0),
        forecasts=(380.0, 950.0),
        bases=(400.0, 1000.0),
    )
    with refused("v0_recalibrated : mêmes éléments de K que v0_raw"):
        replace(document, models=(document.models[0], other, *document.models[2:]))
    reweighted = band(
        model=ModelKind.V0_RECALIBRATED,
        weights=(0.5, 0.5),
        forecasts=(380.0, 950.0),
        bases=(400.0, 1000.0),
    )
    with refused("v0_recalibrated : mêmes éléments de K que v0_raw"):
        replace(document, models=(document.models[0], reweighted, *document.models[2:]))
    raw = band(forecasts=(400.0, 1000.0), bases=(400.0, 1001.0))
    others = tuple(
        band(model=m, forecasts=(380.0, 950.0), bases=(400.0, 1001.0))
        for m in BAND_MODELS[1:]
    )
    with refused("v0 brut : P_k vaut P⁰_k."):
        replace(document, models=(raw, *others))


def test_outing_bands_without_elements_skip_the_agreement() -> None:
    """Aucun modèle à bornes : rien à recouper entre modèles."""
    unavailable = tuple(
        band(model=m, status=U.MODEL_ERROR)
        if m is not ModelKind.V0_RAW
        else band(status=U.MODEL_ERROR)
        for m in BAND_MODELS
    )
    assert replace(bands(), models=unavailable).models[0].elements == ()


def test_element_width_is_exact_to_the_bit() -> None:
    """``width_s == upper_s − lower_s`` au bit : un ulp d'écart est refusé."""
    valid = element()
    with refused("width_s doit valoir upper_s − lower_s"):
        replace(valid, width_s=math.nextafter(valid.width_s, math.inf))


def test_unavailable_member_gives_its_own_motif() -> None:
    """Un membre indisponible donne à chaque modèle un résidu à **son** motif : ni une
    valeur, ni le motif d'un modèle (``erreur du modèle``)."""
    document = bands()
    zero = replace(document.members[2], observed_s=None, unavailability=U.ZERO_TIME)

    def five(last: Unavailability) -> tuple[ModelBand, ...]:
        return tuple(
            band(
                [0.1, -0.1, last if kind is ModelKind.NAISMITH else U.ZERO_TIME],
                model=kind,
                forecasts=(400.0, 1000.0)
                if kind is ModelKind.V0_RAW
                else (380.0, 950.0),
                bases=(400.0, 1000.0),
            )
            for kind in BAND_MODELS
        )

    members = (*document.members[:2], zero)
    valid = replace(document, members=members, models=five(U.ZERO_TIME))
    assert [r.unavailability for r in valid.models[3].residuals] == [
        None,
        None,
        U.ZERO_TIME,
    ]
    with refused(
        "naismith, 2026-06-20 : un membre indisponible donne un résidu à son motif"
    ):
        replace(valid, models=five(U.MODEL_ERROR))


def test_element_score_is_finite() -> None:
    """Invariant 4 : ``IS_k`` fini. Hors du domaine des métriques, une borne énorme et
    finie peut faire déborder sa pénalité : ce n'est pas promis, et le contrat le
    refuse au lieu de le stocker."""
    with refused("score_s doit être fini"):
        element(forecast=1.7e308, q=(0.0, 0.0, 0.0, 0.0), observed=0.0)


# ---------------------------------------------------------------------------
# Ce que le balayage mutmut du prototype a montré
# ---------------------------------------------------------------------------


def test_member_small_time_and_single_segment() -> None:
    """Un ``T_c`` sous 1 s est un temps ; un seul segment sans sortie contributrice est
    refusé comme plusieurs."""
    assert member(observed_s=0.5).observed_s == 0.5
    with refused("des segments admis viennent d'une sortie contributrice"):
        member(outing_count=0, segment_count=1, support_m=100.0)


def test_element_null_weight_and_bounds_under_one_second() -> None:
    """Un poids nul est un poids (``w_k >= 0``) ; des bornes positives sous 1 s sont des
    bornes."""
    assert element(weight=0.0).weight == 0.0
    small = element(0.5, observed=0.52, base=0.5)
    assert 0.0 < small.lower_s < small.upper_s < 1.0


def _with_forecast(band_: ModelBand, index: int, forecast_s: float) -> ModelBand:
    elements = list(band_.elements)
    elements[index] = replace(elements[index], forecast_s=forecast_s)
    return replace(band_, elements=tuple(elements))


def test_band_bound_tolerance_is_relative_above_one_second_absolute_below() -> None:
    """Chaque borne vaut ``P_k · exp(Q)`` à ``τ · max(1, |P_k · exp(Q)|)`` près :
    relatif au-dessus de 1 s, absolu en dessous (le ``P_k`` est décalé, les bornes
    gardées)."""
    tau = METRIC_RELATIVE_TOLERANCE
    large = band(model=ModelKind.NAISMITH)
    p = large.elements[1].forecast_s
    assert _with_forecast(large, 1, p * (1 + 0.5 * tau)).available
    with refused("elements[1] : chaque borne vaut P_k · exp(Q)"):
        _with_forecast(large, 1, p * (1 + 3 * tau))
    small = band(
        model=ModelKind.NAISMITH,
        forecasts=(0.4, 0.5),
        observed=(0.42, 0.52),
        bases=(0.4, 0.5),
    )
    assert all(e.upper_s < 1.0 for e in small.elements)
    assert _with_forecast(small, 1, 0.5 + 0.7 * tau).available
    with refused("elements[1] : chaque borne vaut P_k · exp(Q)"):
        _with_forecast(small, 1, 0.5 + 1.5 * tau)
