"""Fourchettes (``0010`` D11 ; précision de M4d-2) : la bibliothèque
``backtest/bands.py``.

Fonctions élémentaires (rangs, quantiles, score d'intervalle), membres du réservoir et
résidus (les totaux de D9.2, le calage du membre), fourchette d'un modèle (ordre des
statuts, bornes gardées sans observation, agrégats, ``n = 1``, médiane), assemblage
(``evaluation_bands``). Mondes construits par ``fixtures.bands`` : segments de 100 m,
rapports ``p_i / e_i`` par modèle non calé, ``K`` et points donnés.
"""

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from fractions import Fraction
from typing import Any

import pytest

from fixtures.bands import WINDOW, BandSpec, BandWorld, Element, world
from fixtures.calibration import A, D, F
from mountain_perf.backtest import (
    band_quantiles,
    clock_scores,
    evaluation_bands,
    interval_score,
    member_residual,
    member_totals,
    model_band,
    outing_bands,
    quantile_rank,
    reservoir_member,
)
from mountain_perf.schemas import (
    BAND_MODELS,
    BAND_QUANTILE_ORDERS,
    MetricValue,
    ModelBand,
    ModelKind,
    OutingLabel,
    Scenario,
    Unavailability,
)

U = Unavailability
M = ModelKind
TRAINING, RACE = OutingLabel.TRAINING, OutingLabel.RACE
SEGMENTS = ((A, 600.0), (F, 300.0), (D, 200.0))
UNSCALED = (M.V0_RAW, M.CONSTANT_SPEED, M.NAISMITH, M.TOBLER)


def ratios(
    v0: float, c: float = 1.1, n: float = 1.2, t: float = 0.9, k: int = 3
) -> dict[ModelKind, tuple[float, ...]]:
    return {
        M.V0_RAW: (v0,) * k,
        M.CONSTANT_SPEED: (c,) * k,
        M.NAISMITH: (n,) * k,
        M.TOBLER: (t,) * k,
    }


def forecasts(value: float | None) -> dict[ModelKind, float | None]:
    """Le même cumul non calé pour les quatre modèles."""
    return dict.fromkeys(UNSCALED, value)


def member_spec(i: int, day: str, v0: float, **changes: Any) -> BandSpec:
    """Un entraînement de 1 100 s d'écoulé, v0 au rapport ``v0``."""
    base = BandSpec(f"m{i}", day, TRAINING, SEGMENTS, ratios(v0), ratios(v0))
    return replace(base, **changes)


def target_spec(**changes: Any) -> BandSpec:
    """La sortie évaluée, le 2026-06-30 : ``K`` de trois éléments (deux lieux,
    l'arrivée), deux points de ``C_k``."""
    base = BandSpec(
        "j",
        "2026-06-30",
        TRAINING,
        SEGMENTS,
        ratios(1.0),
        ratios(1.0),
        targets=(
            Element(150.0, 400.0, forecasts(380.0)),
            Element(250.0, 700.0, forecasts(650.0)),
            Element(300.0, 1100.0, forecasts(1050.0)),
        ),
        points=(
            Element(100.0, 300.0, forecasts(290.0)),
            Element(200.0, 650.0, forecasts(620.0)),
        ),
    )
    return replace(base, **changes)


def members(*v0: float) -> list[BandSpec]:
    days = [
        "2026-06-01",
        "2026-06-05",
        "2026-06-10",
        "2026-06-12",
        "2026-06-15",
        "2026-06-18",
    ]
    return [member_spec(i, days[i], r) for i, r in enumerate(v0)]


def band_of(w: BandWorld, model: ModelKind, outing_id: str = "j") -> ModelBand:
    return w.of(outing_id).models[BAND_MODELS.index(model)]


def calibration_of(w: BandWorld, day: str, model: ModelKind) -> Any:
    performance = next(
        c for c in w.calibration if c.population.civil_date == date.fromisoformat(day)
    )
    entry = next(
        e
        for e in performance.outings
        if e.control.model is model and e.usage is not None
    )
    assert entry.usage is not None
    return entry.usage.clocks[0].calibration


def refused(message: str) -> Any:
    """Le message **exact** de la précondition (§ 6.2 du brief)."""
    return pytest.raises(ValueError, match=f"^{re.escape(message)}$")


# ---------------------------------------------------------------------------
# Rangs, quantiles, score d'intervalle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", range(1, 41))
def test_quantile_rank_is_the_integer_ceiling(n: int) -> None:
    """Rang ``⌈n a / b⌉`` exact, pour les quatre ordres et pour 1/1."""
    for a, b in (*BAND_QUANTILE_ORDERS, (1, 1), (3, 7)):
        expected = -(-Fraction(n * a, b).numerator // Fraction(n * a, b).denominator)
        assert quantile_rank(n, a, b) == expected
        assert 1 <= quantile_rank(n, a, b) <= n


def test_quantile_rank_preconditions() -> None:
    with refused("quantile_rank : n = 0 < 1."):
        quantile_rank(0, 1, 2)
    with refused("quantile_rank : ordre 0/10 hors de ]0 ; 1]."):
        quantile_rank(5, 0, 10)
    with refused("quantile_rank : ordre 11/10 hors de ]0 ; 1]."):
        quantile_rank(5, 11, 10)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([0.3], (0.3, 0.3, 0.3, 0.3)),
        ([0.2, -0.1], (-0.1, -0.1, 0.2, 0.2)),
        ([0.0, 0.5, -0.5], (-0.5, 0.0, 0.0, 0.5)),
        ([4.0, 1.0, 3.0, 2.0], (1.0, 2.0, 3.0, 4.0)),
        ([float(v) for v in range(9, 0, -1)], (1.0, 5.0, 6.0, 9.0)),
        ([float(v) for v in range(10)], (0.0, 4.0, 6.0, 8.0)),
        ([float(v) for v in range(20)], (1.0, 9.0, 13.0, 17.0)),
        ([0.1, 0.1, 0.1, -0.2, -0.2], (-0.2, 0.1, 0.1, 0.1)),
    ],
)
def test_band_quantiles(values: list[float], expected: tuple[float, ...]) -> None:
    """Rangs 1/10, 1/2 (inférieure centrale), 2/3, 9/10 ; ``n <= 9`` : du plus petit au
    plus grand ; ex æquo et négatifs."""
    assert band_quantiles(values).values == expected


def test_band_quantiles_do_not_sort_in_place_and_need_a_residual() -> None:
    values = [0.3, -0.1, 0.2]
    band_quantiles(values)
    assert values == [0.3, -0.1, 0.2]
    with refused("band_quantiles : aucun résidu."):
        band_quantiles([])


@pytest.mark.parametrize(
    ("lower", "upper", "observed", "expected"),
    [
        (100.0, 120.0, 110.0, 20.0),
        (100.0, 120.0, 100.0, 20.0),
        (100.0, 120.0, 120.0, 20.0),
        (100.0, 120.0, 90.0, 120.0),
        (100.0, 120.0, 130.0, 120.0),
        (100.0, 100.0, 100.0, 0.0),
        (100.0, 100.0, 110.0, 100.0),
    ],
)
def test_interval_score(
    lower: float, upper: float, observed: float, expected: float
) -> None:
    """``(u − l) + 10 (l − T)₊ + 10 (T − u)₊`` ; bornes comprises sans pénalité."""
    assert interval_score(lower, upper, observed) == expected


def test_interval_score_is_summed_by_fsum() -> None:
    lower, upper, observed = 0.1, 1e16, 1e16 + 2.0
    assert interval_score(lower, upper, observed) == math.fsum(
        (upper - lower, 0.0, 10.0 * (observed - upper))
    )


# ---------------------------------------------------------------------------
# Membres du réservoir
# ---------------------------------------------------------------------------


def test_reservoir_member_of_a_day_of_several_outings() -> None:
    """Deux sorties avec usage et une sans : deux contributrices, segments, support et
    ``T_c`` sommés — un seul membre (D11-C/L)."""
    outings = [
        member_spec(0, "2026-06-02", 1.0, hour=8),
        member_spec(
            1,
            "2026-06-02",
            0.5,
            hour=10,
            segments=((A, 400.0),),
            usage=ratios(0.5, k=1),
            control=ratios(0.5, k=1),
        ),
        member_spec(2, "2026-06-02", 1.0, hour=12, usage={}),
    ]
    w = world([*outings, target_spec()])
    first = w.of("j").members[0]
    assert (first.outing_count, first.segment_count, first.support_m) == (2, 4, 400.0)
    assert first.observed_s == math.fsum((600.0, 300.0, 200.0, 400.0))
    residual = band_of(w, M.V0_RAW).residuals[0]
    assert residual.value == math.log(1500.0 / math.fsum((600.0, 300.0, 200.0, 200.0)))
    assert residual.count == 4


def test_reservoir_member_motifs() -> None:
    no_usage = member_spec(0, "2026-06-01", 1.0, usage={})
    no_segment = member_spec(
        1,
        "2026-06-05",
        1.0,
        segments=(),
        usage=ratios(1.0, k=0),
        control=ratios(1.0, k=0),
    )
    w = world([no_usage, no_segment, target_spec()])
    first, second = w.of("j").members
    assert (first.outing_count, first.segment_count, first.unavailability) == (
        0,
        0,
        U.INSUFFICIENT_SUPPORT,
    )
    assert (second.outing_count, second.segment_count, second.unavailability) == (
        1,
        0,
        U.INSUFFICIENT_SUPPORT,
    )
    for band in w.of("j").models:
        assert [r.unavailability for r in band.residuals] == [
            U.INSUFFICIENT_SUPPORT,
            U.INSUFFICIENT_SUPPORT,
        ]
        assert [r.count for r in band.residuals] == [0, 0]
        assert band.unavailability is U.INSUFFICIENT_SUPPORT


def test_reservoir_member_window_bounds_are_included() -> None:
    first, last = WINDOW
    days = ["2026-05-31", first.isoformat(), last.isoformat(), "2026-06-11"]
    w = world([member_spec(i, d, 1.0) for i, d in enumerate(days)] + [target_spec()])
    assert [m.in_window for m in w.of("j").members] == [False, True, True, False]


def test_reservoir_member_reuses_the_calibration_totals() -> None:
    """``T_c`` est celui de ``member_totals`` (précision de D9.2)."""
    spec = member_spec(0, "2026-06-01", 0.8)
    w = world([spec, target_spec()])
    totals = member_totals([w.scores["m0"][M.V0_RAW]], Scenario.USAGE, 0)
    assert not isinstance(totals, Unavailability)
    assert w.of("j").members[0].observed_s == totals[0]
    direct = reservoir_member(date(2026, 6, 1), [w.scores["m0"][M.V0_RAW]], WINDOW)
    assert direct == w.of("j").members[0]


def test_members_are_c_j() -> None:
    """Courses et étiquettes manquantes exclues, jours non finis avant ``o_j`` aussi
    (D2.4) ; dans l'ordre des jours."""
    specs = [
        member_spec(0, "2026-06-01", 1.0),
        member_spec(1, "2026-06-02", 1.0, label=RACE),
        member_spec(2, "2026-06-03", 1.0, label=None),
        member_spec(3, "2026-06-23", 1.0),
        member_spec(4, "2026-06-22", 1.0),
    ]
    w = world([*specs, target_spec()])
    assert [m.civil_date.isoformat() for m in w.of("j").members] == [
        "2026-06-01",
        "2026-06-22",
    ]


# ---------------------------------------------------------------------------
# Résidus
# ---------------------------------------------------------------------------


def test_raw_residuals_are_the_terms_of_beta() -> None:
    """Les résidus de v0 brut sont les termes du ``β`` de v0 + effort recalé de ``j`` :
    leur moyenne vaut ``β`` au bit."""
    w = world([*members(0.9, 1.1, 0.7, 1.3), target_spec()])
    raw = band_of(w, M.V0_RAW)
    values = [r.value for r in raw.residuals]
    assert all(v is not None for v in values)
    beta = calibration_of(w, "2026-06-30", M.V0_RECALIBRATED).beta
    assert math.fsum(v for v in values if v is not None) / len(values) == beta
    assert values == [math.log(1100.0 / (r * 1100.0)) for r in (0.9, 1.1, 0.7, 1.3)]
    assert raw.projected_s == tuple(
        math.fsum((r * 600.0, r * 300.0, r * 200.0)) for r in (0.9, 1.1, 0.7, 1.3)
    )


def test_calibrated_residuals_use_the_member_calibration() -> None:
    """Le résidu d'un modèle calé lit le calage **du membre** : divisé par son effort
    (v0 + effort recalé, saturé compris), multiplié par son facteur (baseline)."""
    w = world([*members(0.9, 1.1, 0.3), target_spec()])
    third = "2026-06-10"
    effort = calibration_of(w, third, M.V0_RECALIBRATED)
    assert effort.effort is not None
    p_src = math.fsum((0.3 * 600.0, 0.3 * 300.0, 0.3 * 200.0))
    recal = band_of(w, M.V0_RECALIBRATED).residuals[2]
    assert recal.value == math.log(1100.0 / (p_src / effort.effort))
    tobler = calibration_of(w, third, M.TOBLER)
    assert tobler.factor is not None
    t_src = math.fsum((0.9 * 600.0, 0.9 * 300.0, 0.9 * 200.0))
    assert band_of(w, M.TOBLER).residuals[2].value == math.log(
        1100.0 / (t_src * tobler.factor)
    )
    assert band_of(w, M.TOBLER).projected_s[2] == t_src * tobler.factor
    first = band_of(w, M.NAISMITH).residuals[0]
    assert first == MetricValue(None, U.NOT_CALIBRATED, 3)


def test_saturated_effort_is_used_as_bounded() -> None:
    """Un membre dont l'effort est saturé : son résidu de v0 + effort recalé divise par
    l'effort borné."""
    specs = [member_spec(0, "2026-06-01", 0.2), member_spec(1, "2026-06-12", 0.2)]
    w = world([*specs, target_spec()])
    effort = calibration_of(w, "2026-06-12", M.V0_RECALIBRATED)
    assert effort.saturated
    assert effort.effort == 0.5
    p = math.fsum((0.2 * 600.0, 0.2 * 300.0, 0.2 * 200.0))
    residual = band_of(w, M.V0_RECALIBRATED).residuals[1]
    assert residual.value == math.log(1100.0 / (p / 0.5))


def test_residual_motif_order() -> None:
    """Le motif du membre d'abord ; puis une projection invalide (``erreur du modèle``,
    avant le calage du membre) ; puis le calage du membre."""
    nan = float("nan")
    bad = member_spec(
        0, "2026-06-01", 1.0, usage={**ratios(1.0), M.V0_RAW: (1.0, nan, 1.0)}
    )
    w = world([bad, target_spec()])
    raw = band_of(w, M.V0_RAW)
    assert raw.residuals[0] == MetricValue(None, U.MODEL_ERROR, 3)
    recal = band_of(w, M.V0_RECALIBRATED)
    assert recal.residuals[0] == MetricValue(None, U.MODEL_ERROR, 3)
    assert band_of(w, M.NAISMITH).residuals[0] == MetricValue(None, U.NOT_CALIBRATED, 3)


@pytest.mark.parametrize("value", [0.0, -1.0, math.inf])
def test_residual_of_an_invalid_projection(value: float) -> None:
    bad = member_spec(
        0, "2026-06-01", 1.0, usage={**ratios(1.0), M.TOBLER: (1.0, value, 1.0)}
    )
    w = world([bad, member_spec(1, "2026-06-05", 1.0), target_spec()])
    assert band_of(w, M.TOBLER).residuals[0] == MetricValue(None, U.MODEL_ERROR, 3)
    assert band_of(w, M.TOBLER).unavailability is U.MODEL_ERROR


def test_member_residual_directly() -> None:
    """``member_residual`` : un membre indisponible garde son motif et son effectif ;
    un membre de v0 brut sans calage."""
    w = world([member_spec(0, "2026-06-01", 0.8), target_spec()])
    member = w.of("j").members[0]
    scores = [w.scores["m0"][M.V0_RAW]]
    value, projected = member_residual(M.V0_RAW, member, scores, None)
    assert (
        value == MetricValue(math.log(1100.0 / projected), None, 3)
        if projected
        else False
    )
    hidden = replace(member, observed_s=None, unavailability=U.ZERO_TIME)
    assert member_residual(M.V0_RAW, hidden, scores, None) == (
        MetricValue(None, U.ZERO_TIME, 3),
        None,
    )


# ---------------------------------------------------------------------------
# Fourchette d'un modèle : statuts
# ---------------------------------------------------------------------------


def test_status_member_model_error_comes_first() -> None:
    """Un résidu en erreur du modèle rend la fourchette en erreur (D9.2), même avec
    d'autres résidus disponibles ; sans quantiles."""
    nan = float("nan")
    bad = member_spec(
        0, "2026-06-01", 1.0, usage={**ratios(1.0), M.V0_RAW: (nan, nan, nan)}
    )
    w = world(
        [bad, *members(0.9, 1.1)[1:], member_spec(5, "2026-06-12", 1.2), target_spec()]
    )
    raw = band_of(w, M.V0_RAW)
    assert raw.unavailability is U.MODEL_ERROR
    assert raw.quantiles is None
    assert raw.count == 2


def test_status_empty_reservoir() -> None:
    w = world([target_spec()])
    for band in w.of("j").models:
        assert band.unavailability is U.INSUFFICIENT_SUPPORT
        assert band.residuals == ()


def test_status_calibrated_member_needs_its_own_calibration() -> None:
    """Un seul membre, lui-même non calé : v0 brut a ses bornes ; un modèle calé a un
    résidu non calé, donc aucun résidu (support insuffisant). Deux membres espacés : le
    second est calé par le premier, son résidu existe. (Un ``j`` non calé avec des
    résidus n'arrive pas par ``evaluation_bands`` : un résidu de modèle calé demande un
    membre avec support, donc ``j`` calé ; ``model_band`` le reçoit par son API.)"""
    w = world([member_spec(0, "2026-06-01", 0.9), target_spec()])
    assert band_of(w, M.V0_RAW).available
    assert band_of(w, M.NAISMITH).unavailability is U.INSUFFICIENT_SUPPORT
    w2 = world(
        [
            member_spec(0, "2026-06-01", 0.9),
            member_spec(1, "2026-06-12", 1.0),
            target_spec(),
        ]
    )
    naismith = band_of(w2, M.NAISMITH)
    assert naismith.available
    assert [r.unavailability for r in naismith.residuals] == [U.NOT_CALIBRATED, None]


@pytest.mark.parametrize("value", [None, 0.0, -5.0, math.inf, math.nan])
def test_status_invalid_target_forecast(value: float | None) -> None:
    """Un ``P_k`` invalide d'un modèle : erreur du modèle, quantiles gardés ; v0 brut
    (``P⁰_k``) : tous les modèles."""
    bad = {**forecasts(650.0), M.NAISMITH: value}
    spec = target_spec(
        targets=(
            Element(150.0, 400.0, forecasts(380.0)),
            Element(250.0, 700.0, bad),
            Element(300.0, 1100.0, forecasts(1050.0)),
        )
    )
    w = world([*members(0.9, 1.1, 1.0), spec])
    naismith = band_of(w, M.NAISMITH)
    assert naismith.unavailability is U.MODEL_ERROR
    assert naismith.quantiles is not None
    assert band_of(w, M.TOBLER).available
    raw_bad = {**forecasts(650.0), M.V0_RAW: value}
    spec0 = replace(
        spec, targets=(spec.targets[0], Element(250.0, 700.0, raw_bad), spec.targets[2])
    )
    w0 = world([*members(0.9, 1.1, 1.0), spec0])
    assert all(b.unavailability is U.MODEL_ERROR for b in w0.of("j").models)


def test_status_exponential_overflow() -> None:
    """Un ``exp(Q)`` qui déborde (hors du domaine des métriques, par l'API de
    ``model_band``) : erreur du modèle, quantiles gardés."""
    w = world([*members(0.9, 1.1), target_spec()])
    scores = w.scores["j"][M.V0_RAW]
    assert scores.usage is not None
    pairs = [(MetricValue(800.0, None, 3), 1.0), (MetricValue(800.0, None, 3), 1.0)]
    target = scores.usage.clocks[0].usage_target
    assert target is not None
    band = model_band(
        M.V0_RAW,
        pairs,
        scores.observation,
        scores.usage.forecast,
        scores.usage.forecast,
        target.weights,
    )
    assert band.unavailability is U.MODEL_ERROR
    assert band.quantiles is not None
    assert band.quantiles.high == 800.0


def test_status_bound_that_is_not_finite() -> None:
    """``exp(Q)`` fini, ``P_k · exp(Q)`` infini : erreur du modèle."""
    w = world([*members(0.9, 1.1), target_spec()])
    scores = w.scores["j"][M.V0_RAW]
    assert scores.usage is not None
    pairs = [(MetricValue(709.0, None, 3), 1.0)]
    target = scores.usage.clocks[0].usage_target
    assert target is not None
    band = model_band(
        M.V0_RAW,
        pairs,
        scores.observation,
        scores.usage.forecast,
        scores.usage.forecast,
        target.weights,
    )
    assert band.unavailability is U.MODEL_ERROR


# ---------------------------------------------------------------------------
# Bornes, scores, couverture
# ---------------------------------------------------------------------------


def test_bounds_are_forecast_times_exp_quantile() -> None:
    w = world([*members(0.9, 1.1, 0.8, 1.2, 1.0), target_spec()])
    raw = band_of(w, M.V0_RAW)
    assert raw.quantiles is not None
    factors = [math.exp(q) for q in raw.quantiles.values]
    for element, p in zip(raw.elements, (380.0, 650.0, 1050.0), strict=True):
        assert element.forecast_s == p
        assert (
            element.lower_s,
            element.median_s,
            element.prudent_s,
            element.upper_s,
        ) == tuple(p * f for f in factors)
        assert element.width_s == element.upper_s - element.lower_s
    recal = band_of(w, M.V0_RECALIBRATED)
    effort = calibration_of(w, "2026-06-30", M.V0_RECALIBRATED).effort
    assert [e.forecast_s for e in recal.elements] == [
        p / effort for p in (380.0, 650.0, 1050.0)
    ]
    naismith = band_of(w, M.NAISMITH)
    factor = calibration_of(w, "2026-06-30", M.NAISMITH).factor
    assert [e.forecast_s for e in naismith.elements] == [
        p * factor for p in (380.0, 650.0, 1050.0)
    ]
    assert [e.base_s for e in naismith.elements] == [380.0, 650.0, 1050.0]


def test_bounds_are_kept_without_observation() -> None:
    """D11-A : un élément non observé garde ses bornes ; les agrégats sont indisponibles
    au motif du **premier** élément non observé, d'effectif les éléments observés."""
    spec = target_spec(
        targets=(
            Element(150.0, 400.0, forecasts(380.0)),
            Element(250.0, None, forecasts(650.0), motif=U.AMBIGUOUS),
            Element(300.0, None, forecasts(1050.0), motif=U.ABSENT),
        )
    )
    w = world([*members(0.9, 1.1, 1.0), spec])
    raw = band_of(w, M.V0_RAW)
    assert len(raw.elements) == 3
    assert [e.observation for e in raw.elements] == [None, U.AMBIGUOUS, U.ABSENT]
    assert raw.elements[1].lower_s > 0
    assert raw.interval_score_s == MetricValue(None, U.AMBIGUOUS, 1)
    assert raw.normalised_score == MetricValue(None, U.AMBIGUOUS, 1)
    assert raw.coverage == MetricValue(None, U.AMBIGUOUS, 1)
    assert raw.all_covered is None
    assert raw.elements[0].score_s is not None
    assert raw.elements[0].covered is not None


def test_first_unobserved_element_is_taken_in_k_order() -> None:
    spec = target_spec(
        targets=(
            Element(150.0, None, forecasts(380.0), motif=U.UNDEFINED_TANGENT),
            Element(250.0, 700.0, forecasts(650.0)),
            Element(300.0, None, forecasts(1050.0), motif=U.ABSENT),
        )
    )
    w = world([*members(0.9, 1.1), spec])
    assert band_of(w, M.V0_RAW).interval_score_s == MetricValue(
        None, U.UNDEFINED_TANGENT, 1
    )


def test_scores_and_coverage_of_an_observed_k() -> None:
    """Un ``K`` observé en entier, un élément sous sa borne basse, un au-dessus de sa
    borne haute, un couvert : ``IS_k`` (pénalités comprises), ``IS_j``, ``IS_j,norm``,
    la couverture pondérée par ``w_k`` (pas la part des éléments couverts) et « tous
    couverts » faux."""
    spec = target_spec(
        targets=(
            Element(150.0, 300.0, forecasts(380.0)),
            Element(250.0, 900.0, forecasts(650.0)),
            Element(300.0, 1100.0, forecasts(1050.0)),
        )
    )
    w = world([*members(0.9, 1.1, 0.8, 1.2, 1.0), spec])
    raw = band_of(w, M.V0_RAW)
    elements = raw.elements
    weights = [e.weight for e in elements]
    assert weights == [380.0 / 2080.0, 650.0 / 2080.0, 1050.0 / 2080.0]
    scores = [
        interval_score(e.lower_s, e.upper_s, e.observed_s or 0.0) for e in elements
    ]
    assert [e.score_s for e in elements] == scores
    assert raw.interval_score_s == MetricValue(
        math.fsum(w * s for w, s in zip(weights, scores, strict=True)), None, 3
    )
    assert raw.normalised_score == MetricValue(
        math.fsum(
            e.weight * s / e.base_s for e, s in zip(elements, scores, strict=True)
        ),
        None,
        3,
    )
    covered = [e.lower_s <= (e.observed_s or 0.0) <= e.upper_s for e in elements]
    assert covered == [False, False, True]
    assert [e.covered for e in elements] == covered
    assert scores[0] > elements[0].width_s
    assert scores[1] > elements[1].width_s
    assert raw.coverage == MetricValue(
        math.fsum(w for w, c in zip(weights, covered, strict=True) if c), None, 3
    )
    assert raw.all_covered is all(covered)


def test_expert_case_d11_g() -> None:
    """D11-G : ``P⁰ = (100 ; 1000)``, erreurs ``(10 ; 100)``, plage ponctuelle →
    ``IS_j = 918,18…`` s, ``IS_j,norm = 1``."""
    spec = target_spec(
        segments=((A, 1100.0),),
        usage=ratios(1.0, k=1),
        control=ratios(1.0, k=1),
        targets=(
            Element(50.0, 110.0, forecasts(100.0)),
            Element(100.0, 1100.0, forecasts(1000.0)),
        ),
        points=(),
    )
    w = world([member_spec(0, "2026-06-01", 1.0), spec])
    raw = band_of(w, M.V0_RAW)
    assert raw.count == 1
    assert raw.quantiles is not None
    assert raw.quantiles.values == (0.0, 0.0, 0.0, 0.0)
    assert raw.interval_score_s is not None
    assert raw.interval_score_s.value == pytest.approx(10_100_000 / 11_000, rel=1e-15)
    assert raw.normalised_score is not None
    assert raw.normalised_score.value == pytest.approx(1.0, rel=1e-15)
    assert raw.coverage is None
    assert raw.all_covered is None
    assert all(e.covered is None for e in raw.elements)


def test_single_residual_publishes_its_score_only() -> None:
    w = world([member_spec(0, "2026-06-01", 0.9), target_spec()])
    raw = band_of(w, M.V0_RAW)
    assert raw.count == 1
    assert raw.interval_score_s is not None
    assert raw.interval_score_s.available
    assert raw.coverage is None
    assert [e.covered for e in raw.elements] == [None, None, None]


def test_two_residuals_publish_coverage() -> None:
    w = world([*members(0.9, 1.1), target_spec()])
    raw = band_of(w, M.V0_RAW)
    assert raw.count == 2
    assert raw.coverage is not None
    assert all(e.covered is not None for e in raw.elements)


# ---------------------------------------------------------------------------
# Médiane
# ---------------------------------------------------------------------------


def test_median_scores_are_those_of_the_median_forecast() -> None:
    """La prévision médiane est la prévision calée × ``exp(Q_0,5)`` ; ses ``q_usage`` et
    ``max |C_k|`` sont ceux de ``clock_scores`` sous l'écoulé, de base v0 brut — la
    prévision de v0, pas la médiane elle-même (``Q_0,5 != 0`` : les deux diffèrent)."""
    w = world([*members(0.9, 1.1, 0.8, 1.2, 0.85), target_spec()])
    raw = band_of(w, M.V0_RAW)
    scores = w.scores["j"][M.V0_RAW]
    assert scores.usage is not None
    assert raw.quantiles is not None
    factor = math.exp(raw.quantiles.median)
    forecast = scores.usage.forecast
    median = replace(
        forecast,
        segment_s=tuple(None if p is None else p * factor for p in forecast.segment_s),
        point_s=tuple(None if p is None else p * factor for p in forecast.point_s),
        target_s=tuple(None if p is None else p * factor for p in forecast.target_s),
    )
    expected = clock_scores(scores.observation, median, 0, base=scores.usage.forecast)
    assert expected.usage_target is not None
    assert expected.passage_errors is not None
    assert raw.median_usage_target == expected.usage_target.q_usage
    assert raw.median_max_abs_error_s == expected.passage_errors.max_abs_error_s
    assert factor == pytest.approx(1 / 0.9, rel=1e-12)
    t = [400.0, 700.0, 1100.0]
    q = math.fsum(
        abs(p * factor - tk) for p, tk in zip((380.0, 650.0, 1050.0), t, strict=True)
    ) / math.fsum((380.0, 650.0, 1050.0))
    assert raw.median_usage_target.value == pytest.approx(q, rel=1e-12)
    worst = max(abs(290.0 * factor - 300.0), abs(620.0 * factor - 650.0))
    assert raw.median_max_abs_error_s.value == worst
    assert [e.median_s for e in raw.elements] == [
        p * factor for p in (380.0, 650.0, 1050.0)
    ]


def test_median_is_not_the_comparator() -> None:
    """D11-E : résidus ``(0 ; ln 2)`` → médiane inférieure ``0`` : la prévision médiane
    est v0 brut, le comparateur moyenne."""
    w = world([*members(1.0, 0.5), target_spec()])
    raw = band_of(w, M.V0_RAW)
    assert raw.quantiles is not None
    assert raw.quantiles.median == 0.0
    assert [e.median_s for e in raw.elements] == [380.0, 650.0, 1050.0]
    effort = calibration_of(w, "2026-06-30", M.V0_RECALIBRATED).effort
    assert effort == pytest.approx(1 / math.sqrt(2), rel=1e-12)


# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------


def test_evaluation_bands_order_and_scope() -> None:
    """Un document par sortie scorée avec usage, dans l'ordre des performances puis des
    sorties ; ni pour une sortie non scorée, ni sans usage ; jour de plusieurs sorties
    marqué."""
    specs = [
        member_spec(0, "2026-06-01", 1.0),
        member_spec(1, "2026-06-05", 1.0, usage={}),
        member_spec(2, "2026-06-10", 1.0),
        target_spec(outing_id="j1", hour=8),
        target_spec(outing_id="j2", hour=11),
    ]
    w = world(specs, unscored=frozenset({"m2"}))
    assert [b.outing_id for b in w.bands] == ["m0", "j1", "j2"]
    assert [b.multi_outing for b in w.bands] == [False, True, True]
    assert w.of("j1").members == w.of("j2").members


def test_evaluation_bands_preconditions() -> None:
    w = world([*members(1.0, 0.9), target_spec()])
    message = (
        "evaluation_bands : un calage par performance, dans l'ordre des performances."
    )
    with refused(message):
        evaluation_bands(w.performances, w.scores, w.calibration[:-1], WINDOW)
    swapped = (w.calibration[1], w.calibration[0], *w.calibration[2:])
    with refused(message):
        evaluation_bands(w.performances, w.scores, swapped, WINDOW)


def test_window_is_recopied() -> None:
    window = (date(2026, 1, 1), date(2026, 1, 31))
    w = world([member_spec(0, "2026-06-01", 1.0), target_spec()], window=window)
    document = w.of("j")
    assert (document.window_from, document.window_to) == window
    assert document.members[0].in_window is False


def test_model_band_directly_with_a_status_forecast() -> None:
    """``model_band`` reçoit le statut du calage de ``j`` à la place d'une prévision."""
    w = world([*members(0.9, 1.1), target_spec()])
    scores = w.scores["j"][M.V0_RAW]
    assert scores.usage is not None
    pairs = [(MetricValue(0.1, None, 3), 1000.0), (MetricValue(-0.1, None, 3), 1200.0)]
    band = model_band(
        M.NAISMITH,
        pairs,
        scores.observation,
        U.NOT_CALIBRATED,
        scores.usage.forecast,
        (0.2, 0.3, 0.5),
    )
    assert band.unavailability is U.NOT_CALIBRATED
    assert band.quantiles is not None
    none_weights = model_band(
        M.NAISMITH,
        pairs,
        scores.observation,
        scores.usage.forecast,
        scores.usage.forecast,
        None,
    )
    assert none_weights.unavailability is U.MODEL_ERROR


@pytest.mark.parametrize("value", [None, 0.0, math.inf])
def test_model_band_directly_with_an_invalid_base(value: float | None) -> None:
    """Par l'API de ``model_band`` (dans une exécution, ``P⁰_k`` invalide rend les poids
    absents) : un ``P⁰_k`` invalide de la base, poids donnés et ``P_k`` du modèle
    valides — erreur du modèle, quantiles gardés."""
    w = world([*members(0.9, 1.1), target_spec()])
    scores = w.scores["j"][M.V0_RAW]
    assert scores.usage is not None
    forecast = scores.usage.forecast
    base = replace(
        forecast, target_s=(forecast.target_s[0], value, *forecast.target_s[2:])
    )
    pairs = [(MetricValue(0.1, None, 3), 1000.0), (MetricValue(-0.1, None, 3), 1200.0)]
    band = model_band(
        M.NAISMITH, pairs, scores.observation, forecast, base, (0.2, 0.3, 0.5)
    )
    assert band.unavailability is U.MODEL_ERROR
    assert band.quantiles is not None
    assert model_band(
        M.NAISMITH, pairs, scores.observation, forecast, forecast, (0.2, 0.3, 0.5)
    ).available


def test_bands_are_unchanged_by_calling_twice() -> None:
    """Fonction pure : deux appels, mêmes documents ; les entrées non modifiées."""
    w = world([*members(0.9, 1.1, 1.0), target_spec()])
    again = evaluation_bands(w.performances, w.scores, w.calibration, WINDOW)
    assert again == w.bands


def _all_bands(mapping: Mapping[str, Sequence[ModelBand]]) -> None:
    del mapping


# ---------------------------------------------------------------------------
# Imports (§ 6.0 du brief)
# ---------------------------------------------------------------------------


def test_bands_import_only_the_named_modules() -> None:
    """§ 6.0 du brief : la bibliothèque des fourchettes importe le calage
    (``calibrated_forecast``, ``member_totals``), le jugement des sorties de modèle, les
    scores de M4b-2 (``clock_scores``) et des contrats ; ni registre, ni exécution, ni
    rapport ; hors du projet, de quoi calculer seulement (aucune E/S)."""
    import ast
    import inspect

    import mountain_perf.backtest.bands as module

    tree = ast.parse(inspect.getsource(module))
    imported: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.setdefault(node.module, set()).update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.setdefault(alias.name, set())
    project = {m for m in imported if m.startswith("mountain_perf")}
    assert project == {
        "mountain_perf.backtest.calibration",
        "mountain_perf.backtest.metrics",
        "mountain_perf.backtest.scoring",
        "mountain_perf.schemas.bands",
        "mountain_perf.schemas.calibration",
        "mountain_perf.schemas.metrics",
        "mountain_perf.schemas.outing",
        "mountain_perf.schemas.scoring",
    }
    assert imported["mountain_perf.backtest.calibration"] == {
        "calibrated_forecast",
        "member_totals",
    }
    assert imported["mountain_perf.backtest.metrics"] == {"is_invalid_model_output"}
    assert imported["mountain_perf.backtest.scoring"] == {"clock_scores"}
    outside = {m.split(".")[0] for m in imported} - {"mountain_perf"}
    assert outside <= {"__future__", "collections", "dataclasses", "datetime", "math"}


# ---------------------------------------------------------------------------
# Ce que la bibliothèque garantit sans ses contrats (campagne, contrats neutralisés)
# ---------------------------------------------------------------------------


def test_coverage_includes_both_bounds() -> None:
    """« couvert » vaut ``l_k <= T_k <= u_k`` : un ``T_k`` égal à une borne, au bit, est
    couvert, sans pénalité (``IS_k`` = la largeur)."""
    from fixtures.calibration import clock_times

    w = world([*members(0.9, 1.1, 0.8), target_spec()])
    scores = w.scores["j"][M.V0_RAW]
    assert scores.usage is not None
    target = scores.usage.clocks[0].usage_target
    assert target is not None
    pairs = [
        (residual, projected)
        for residual, projected in zip(
            band_of(w, M.V0_RAW).residuals,
            band_of(w, M.V0_RAW).projected_s,
            strict=True,
        )
    ]
    observation = scores.observation
    first = model_band(
        M.V0_RAW,
        pairs,
        observation,
        scores.usage.forecast,
        scores.usage.forecast,
        target.weights,
    )
    lower, upper = first.elements[0].lower_s, first.elements[1].upper_s
    targets = list(observation.targets)
    targets[0] = replace(targets[0], times_s=clock_times(lower))
    targets[1] = replace(targets[1], times_s=clock_times(upper))
    on_bounds = replace(observation, targets=tuple(targets))
    band = model_band(
        M.V0_RAW,
        pairs,
        on_bounds,
        scores.usage.forecast,
        scores.usage.forecast,
        target.weights,
    )
    assert [e.observed_s for e in band.elements[:2]] == [lower, upper]
    assert [e.covered for e in band.elements[:2]] == [True, True]
    assert [e.score_s for e in band.elements[:2]] == [
        e.width_s for e in band.elements[:2]
    ]


def test_single_residual_with_an_unobserved_element() -> None:
    """``n = 1`` et un élément non observé : ``IS_j`` et ``IS_j,norm`` indisponibles au
    motif de l'élément ; ni couverture (pas même indisponible), ni « tous couverts »."""
    spec = target_spec(
        targets=(
            Element(150.0, 400.0, forecasts(380.0)),
            Element(250.0, None, forecasts(650.0)),
            Element(300.0, 1100.0, forecasts(1050.0)),
        )
    )
    w = world([member_spec(0, "2026-06-01", 0.9), spec])
    raw = band_of(w, M.V0_RAW)
    assert raw.count == 1
    assert raw.interval_score_s == MetricValue(None, U.ABSENT, 2)
    assert raw.normalised_score == MetricValue(None, U.ABSENT, 2)
    assert raw.coverage is None
    assert raw.all_covered is None


def test_normalised_score_divides_by_the_v0_cumulative() -> None:
    """``IS_j,norm = Σ w_k IS_k / P⁰_k`` : pour un modèle calé, ``P⁰_k`` (v0 brut), pas
    son propre ``P_k``."""
    w = world([*members(0.9, 1.1, 0.3), target_spec()])
    tobler = band_of(w, M.TOBLER)
    assert tobler.available
    elements = tobler.elements
    assert all(e.forecast_s != e.base_s for e in elements)
    scores = [e.score_s for e in elements]
    assert all(s is not None for s in scores)
    assert tobler.normalised_score == MetricValue(
        math.fsum(
            e.weight * s / e.base_s
            for e, s in zip(elements, scores, strict=True)
            if s is not None
        ),
        None,
        3,
    )


# ---------------------------------------------------------------------------
# Ce que le balayage mutmut du prototype a montré
# ---------------------------------------------------------------------------


def test_outing_bands_precondition() -> None:
    w = world([*members(1.0, 0.9), target_spec(), member_spec(9, "2026-07-02", 1.0)])
    from fixtures.bands import outing_scores

    scores = outing_scores(target_spec(outing_id="x", usage={}))
    performance = w.performances[-1]
    with refused("outing_bands : x n'a pas d'usage."):
        outing_bands(
            "x",
            performance,
            w.calibration[-1],
            w.of("m9").members,
            {model: [] for model in BAND_MODELS},
            scores,
            WINDOW,
        )


@pytest.mark.parametrize("unscored", [False, True])
def test_an_outing_without_bands_does_not_stop_its_day(unscored: bool) -> None:
    """Un jour de deux sorties dont la première n'a pas de fourchettes (sans usage, ou
    non scorée) : la seconde a les siennes."""
    first = target_spec(outing_id="j0", hour=8, **({} if unscored else {"usage": {}}))
    specs = [
        member_spec(0, "2026-06-01", 1.0),
        first,
        target_spec(outing_id="j1", hour=11),
    ]
    w = world(specs, unscored=frozenset({"j0"}) if unscored else frozenset())
    assert [b.outing_id for b in w.bands] == ["m0", "j1"]
    assert w.of("j1").multi_outing


def test_each_calibrated_model_reads_its_own_member_calibration() -> None:
    """Le résidu d'un modèle calé lit le calage **de ce modèle** pour le membre : effort
    de v0 + effort recalé, facteur propre de chaque baseline — des valeurs toutes
    différentes ici."""

    def spec(i: int, day: str, v0: float, c: float, n: float, t: float) -> BandSpec:
        r = ratios(v0, c, n, t)
        return member_spec(i, day, v0, control=r, usage=r)

    w = world(
        [
            spec(0, "2026-06-01", 0.9, 1.3, 0.7, 0.6),
            spec(1, "2026-06-05", 1.1, 1.25, 0.75, 0.5),
            spec(2, "2026-06-10", 0.3, 1.0, 1.0, 1.0),
            target_spec(),
        ]
    )
    source = {M.V0_RECALIBRATED: 0.3, M.CONSTANT_SPEED: 1.0, M.NAISMITH: 1.0}
    source[M.TOBLER] = 1.0
    projected = {}
    for model, ratio in source.items():
        calibration = calibration_of(w, "2026-06-10", model)
        src = math.fsum((ratio * 600.0, ratio * 300.0, ratio * 200.0))
        if model is M.V0_RECALIBRATED:
            assert calibration.effort is not None
            p = src / calibration.effort
        else:
            assert calibration.factor is not None
            p = src * calibration.factor
        band = band_of(w, model)
        assert band.residuals[2] == MetricValue(math.log(1100.0 / p), None, 3)
        assert band.projected_s[2] == p
        projected[model] = p
    assert len(set(projected.values())) == 4


def test_residual_of_a_calibrated_projection_that_overflows() -> None:
    """Hors du domaine des métriques : un membre dont la projection source est finie,
    mais dont le facteur de son propre calage la rend infinie — ``erreur du modèle``
    (``P_c`` non fini), la fourchette aussi."""

    def spec(i: int, day: str, t: float) -> BandSpec:
        r = ratios(1.0, t=t)
        return member_spec(i, day, 1.0, control=r, usage=r)

    w = world(
        [
            spec(0, "2026-06-01", 1e-300),
            spec(1, "2026-06-05", 1e-300),
            spec(2, "2026-06-10", 1e8),
            target_spec(),
        ]
    )
    calibration = calibration_of(w, "2026-06-10", M.TOBLER)
    assert calibration.unavailability is None
    assert calibration.factor is not None
    assert math.isfinite(calibration.factor)
    tobler = band_of(w, M.TOBLER)
    assert tobler.residuals[2] == MetricValue(None, U.MODEL_ERROR, 3)
    assert tobler.projected_s[2] is None
    assert tobler.unavailability is U.MODEL_ERROR


def _direct(
    values: Sequence[float], **forecast_changes: Any
) -> tuple[ModelBand, Any, Any]:
    """``model_band`` de v0 brut appelée seule sur la sortie évaluée, avec ces
    résidus (et une prévision retouchée)."""
    w = world([*members(0.9, 1.1), target_spec()])
    scores = w.scores["j"][M.V0_RAW]
    assert scores.usage is not None
    target = scores.usage.clocks[0].usage_target
    assert target is not None
    forecast = replace(scores.usage.forecast, **forecast_changes)
    pairs = [(MetricValue(v, None, 3), 1000.0) for v in values]
    band = model_band(
        M.V0_RAW,
        pairs,
        scores.observation,
        forecast,
        scores.usage.forecast,
        target.weights,
    )
    return band, scores, forecast


def test_a_bound_that_underflows_to_zero_is_a_model_error() -> None:
    """``exp(Q)`` qui s'annule (hors du domaine) : une borne nulle, ``erreur du
    modèle``, quantiles gardés."""
    band, _, _ = _direct([-800.0, -800.0])
    assert band.unavailability is U.MODEL_ERROR
    assert band.quantiles is not None
    assert band.quantiles.low == -800.0


def test_bounds_under_one_second_are_bounds() -> None:
    """Des bornes positives sous 1 s restent des bornes."""
    band, _, _ = _direct([-7.0, -7.5])
    assert band.available
    assert all(0.0 < e.lower_s < e.upper_s < 1.0 for e in band.elements)


def test_an_absent_value_of_the_median_forecast_stays_absent() -> None:
    """Par l'API : une prévision dont un point de ``C_k`` est absent (cumuls de ``K``
    valides) — la prévision médiane le garde absent, et ses scores sont ceux de
    ``clock_scores`` sur elle."""
    w = world([*members(0.9, 1.1), target_spec()])
    scores = w.scores["j"][M.V0_RAW]
    assert scores.usage is not None
    point_s = (None, *scores.usage.forecast.point_s[1:])
    band, scores, forecast = _direct([0.1, -0.1], point_s=point_s)
    assert band.available
    assert band.quantiles is not None
    factor = math.exp(band.quantiles.median)
    median = replace(
        forecast,
        segment_s=tuple(None if p is None else p * factor for p in forecast.segment_s),
        point_s=tuple(None if p is None else p * factor for p in forecast.point_s),
        target_s=tuple(None if p is None else p * factor for p in forecast.target_s),
    )
    assert median.point_s[0] is None
    assert scores.usage is not None
    expected = clock_scores(scores.observation, median, 0, base=scores.usage.forecast)
    assert expected.passage_errors is not None
    assert band.median_max_abs_error_s == expected.passage_errors.max_abs_error_s
