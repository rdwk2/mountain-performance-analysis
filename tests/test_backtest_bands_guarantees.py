"""Fourchettes (``0010`` D11 ; précision de M4d-2) : garanties de la bibliothèque
``backtest/bands.py`` que la batterie jointe n'exerçait pas (relecture C de la PR
M4d-2).

Le calage du membre lu sur sa première sortie **qui a l'usage** ; les bornes d'un modèle
calé sur **son** ``P_k`` ; le statut de la prévision de ``j`` jugé avant les poids et
``P⁰_k`` (une fourchette calculée seule) ; des fonctions pures — entrées laissées
intactes, rien de gardé d'un appel à l'autre, les résidus d'un jour partagés par ses
sorties. Mondes construits par ``fixtures.bands`` et les aides de
``test_backtest_bands.py``.
"""

import math
from dataclasses import replace

from fixtures.bands import WINDOW, world
from fixtures.calibration import A, D, F
from mountain_perf.backtest import (
    evaluation_bands,
    member_residual,
    model_band,
    outing_bands,
    reservoir_member,
)
from mountain_perf.schemas import (
    BAND_MODELS,
    MetricValue,
    ModelKind,
    Unavailability,
)
from test_backtest_bands import (
    band_of,
    calibration_of,
    member_spec,
    members,
    target_spec,
)

U = Unavailability
M = ModelKind


def test_member_calibration_is_read_on_its_first_outing_with_usage() -> None:
    """Un jour membre de deux sorties scorées, la première sans usage : le résidu d'un
    modèle calé lit le calage du membre sur la première sortie **qui a l'usage** (§ 6.2,
    point 5.3 du brief ; précision de D11, « Résidus », point 2)."""
    earlier = member_spec(0, "2026-05-20", 1.0)
    first = member_spec(1, "2026-06-01", 1.0, hour=8, usage={})
    second = member_spec(2, "2026-06-01", 0.8, hour=11)
    w = world([earlier, first, second, target_spec()])
    effort = calibration_of(w, "2026-06-01", M.V0_RECALIBRATED).effort
    assert effort is not None
    p_src = math.fsum((0.8 * 600.0, 0.8 * 300.0, 0.8 * 200.0))
    residual = band_of(w, M.V0_RECALIBRATED).residuals[1]
    assert residual == MetricValue(math.log(1100.0 / (p_src / effort)), None, 3)


def test_bounds_of_a_calibrated_model_are_its_forecast_times_exp_quantile() -> None:
    """Les bornes d'un modèle calé valent ``P_k · exp(Q)`` sur **son** ``P_k`` calé, et
    non sur ``P⁰_k`` (pour v0 brut, ``P_k = P⁰_k`` : la valeur ne distingue pas)."""
    w = world([*members(0.9, 1.1, 0.8, 1.2, 1.0), target_spec()])
    for model in BAND_MODELS[1:]:
        band = band_of(w, model)
        assert band.quantiles is not None
        factors = [math.exp(q) for q in band.quantiles.values]
        assert len(band.elements) == 3
        for element in band.elements:
            assert element.forecast_s != element.base_s
            bounds = (
                element.lower_s,
                element.median_s,
                element.prudent_s,
                element.upper_s,
            )
            assert bounds == tuple(element.forecast_s * f for f in factors)


def test_status_of_the_target_forecast_comes_before_the_weights_and_the_base() -> None:
    """Une fourchette calculée seule (précision de D11, statut 3 : « la règle vaut pour
    une fourchette calculée seule ») : la prévision de ``j`` indisponible donne son
    statut, quantiles publiés, même avec des poids absents ou un ``P⁰_k`` invalide
    (statut 4, jugé après)."""
    w = world([*members(0.9, 1.1), target_spec()])
    scores = w.scores["j"][M.V0_RAW]
    assert scores.usage is not None
    base = scores.usage.forecast
    invalid_base = replace(base, target_s=(base.target_s[0], None, *base.target_s[2:]))
    pairs = [(MetricValue(0.1, None, 3), 1000.0), (MetricValue(-0.1, None, 3), 1200.0)]
    for weights, p0 in ((None, base), ((0.2, 0.3, 0.5), invalid_base)):
        band = model_band(
            M.NAISMITH, pairs, scores.observation, U.NOT_CALIBRATED, p0, weights
        )
        assert band.unavailability is U.NOT_CALIBRATED
        assert band.quantiles is not None
        assert band.quantiles.values == (-0.1, -0.1, 0.1, 0.1)


def test_library_functions_leave_their_inputs_unchanged() -> None:
    """Fonctions pures (§ 6.2 du brief) : ``reservoir_member``, ``member_residual``,
    ``model_band``, ``outing_bands`` et ``evaluation_bands`` laissent intactes les
    séquences et les tables qu'elles reçoivent, même modifiables (leurs éléments sont
    des contrats gelés) ; ``outing_bands`` et ``model_band`` rappelées sur les pièces de
    l'exécution rendent son document."""
    w = world([*members(0.9, 1.1, 1.0), target_spec()])
    document = w.of("j")
    performance = w.performances[-1]
    calibrated = w.calibration[-1]
    outings = [w.scores["m0"][M.V0_RAW]]
    received = list(outings)
    member = reservoir_member(performance.civil_date, outings, WINDOW)
    member_residual(M.NAISMITH, member, outings, w.calibration[0])
    assert outings == received

    residuals = {
        band.model: list(zip(band.residuals, band.projected_s, strict=True))
        for band in document.models
    }
    scores = dict(w.scores["j"])
    member_list = list(document.members)
    before = (
        {model: list(pairs) for model, pairs in residuals.items()},
        dict(scores),
        list(member_list),
    )
    rebuilt = outing_bands(
        "j", performance, calibrated, member_list, residuals, scores, WINDOW
    )
    assert rebuilt == document
    assert (residuals, scores, member_list) == before

    raw = w.scores["j"][M.V0_RAW]
    assert raw.usage is not None
    target = raw.usage.clocks[0].usage_target
    assert target is not None
    assert target.weights is not None
    weights = list(target.weights)
    pairs = list(residuals[M.V0_RAW])
    kept = (list(weights), list(pairs))
    forecast = raw.usage.forecast
    band = model_band(M.V0_RAW, pairs, raw.observation, forecast, forecast, weights)
    assert band == document.models[0]
    assert (weights, pairs) == kept

    all_scores = {key: dict(value) for key, value in w.scores.items()}
    snapshot = {key: dict(value) for key, value in all_scores.items()}
    assert evaluation_bands(w.performances, all_scores, w.calibration, WINDOW) == (
        w.bands
    )
    assert all_scores == snapshot


def test_both_outings_of_a_multi_outing_day_carry_the_same_residuals() -> None:
    """Deux sorties évaluées le même jour (``jour multi-sorties``, en diagnostic) :
    mêmes membres et **mêmes résidus** pour chaque modèle — un résidu par jour du
    réservoir, partagé par les sorties du jour."""
    specs = [
        *members(0.9, 1.1, 0.8),
        target_spec(outing_id="j1", hour=8),
        target_spec(outing_id="j2", hour=11),
    ]
    w = world(specs)
    first, second = w.of("j1"), w.of("j2")
    assert first.multi_outing
    assert second.multi_outing
    assert first.members == second.members
    for one, other in zip(first.models, second.models, strict=True):
        assert one.residuals == other.residuals
        assert one.projected_s == other.projected_s
    assert second.models[0].count == 3


def test_bands_do_not_depend_on_an_earlier_call() -> None:
    """Rien n'est gardé d'un appel à l'autre (« Le calcul ne dépend que de ses
    arguments », § 6.2 du brief) : deux mondes aux mêmes jours, aux temps différents,
    calculés l'un après l'autre, ont chacun les membres de leurs propres sorties."""
    days = ("2026-06-01", "2026-06-05", "2026-06-10")
    slower = ((A, 700.0), (F, 300.0), (D, 200.0))
    w_a = world([*members(0.9, 1.1, 1.0), target_spec()])
    w_b = world(
        [
            *(member_spec(i, day, 1.0, segments=slower) for i, day in enumerate(days)),
            target_spec(),
        ]
    )
    assert [m.observed_s for m in w_a.of("j").members] == [1100.0] * 3
    assert [m.observed_s for m in w_b.of("j").members] == [1200.0] * 3
    again = evaluation_bands(w_a.performances, w_a.scores, w_a.calibration, WINDOW)
    assert again == w_a.bands
