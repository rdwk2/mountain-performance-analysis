"""Prévisions de v0 brut : ``usage_forecast``, ``control_forecast`` (§ 6.4 et § 8.1,
test 5, du brief M4b-2 ; ``0010`` D3, D4.2, D16 ; choix 3, 4, 5 et 11).

Les ``p_i`` et ``P_k`` du § 7.3 à la tolérance du § 7.0 ; le réemploi au bit de la
chronologie (§ 7.4) ; les champs de provenance publiés tels que reçus ; un contrôle
sans point ni élément (précision 2 de la relecture du plan) ; les préconditions.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from fixtures.metrics import raises_value_error
from fixtures.scoring import (
    CONSTRUCTED,
    SCORING_CASES,
    chain,
    close,
    curve_read,
    observation,
    scores,
    trace_profile,
)
from fixtures.scoring_values import VALUES
from mountain_perf.backtest import control_forecast, usage_forecast
from mountain_perf.model import (
    ENGINE_VERSION,
    PROJECTION_PARAMETER_SPECS,
    ProjectedTimeline,
    projected_timeline,
)
from mountain_perf.schemas import (
    CLOCKS,
    AdmittedSegment,
    OutingObservation,
    ParameterSet,
    RegimeClass,
    Scenario,
    SourceRef,
    TargetMember,
)

V0 = ParameterSet(PROJECTION_PARAMETER_SPECS)


def _closes(actual: tuple[float | None, ...], expected: tuple[float, ...]) -> bool:
    return len(actual) == len(expected) and all(
        close(a, e) for a, e in zip(actual, expected, strict=True)
    )


def _usage_timeline(name: str) -> ProjectedTimeline:
    return projected_timeline(chain(name).profile, curve_read().curve, V0)


def _control_timeline(name: str) -> ProjectedTimeline:
    trace = chain(name).case.trace
    return projected_timeline(trace_profile(trace), curve_read().curve, V0)


@pytest.mark.parametrize("name", CONSTRUCTED)
def test_usage_forecast_values(name: str) -> None:
    """``0010`` D3 (usage) ; choix 3 : ``p_i`` sur ``[b_i ; b_{i+1}]`` et ``P_k``
    depuis ``b_0`` (points de ``C_k``, éléments de ``K``) du § 7.3."""
    usage = scores(name).usage
    assert usage is not None
    expected = VALUES[name].usage
    assert _closes(usage.forecast.segment_s, expected.segment_s)
    assert expected.point_s is not None
    assert expected.target_s is not None
    assert _closes(usage.forecast.point_s, expected.point_s)
    assert _closes(usage.forecast.target_s, expected.target_s)


@pytest.mark.parametrize("name", SCORING_CASES)
def test_control_forecast_values(name: str) -> None:
    """``0010`` D3 (contrôle, correspondance) ; choix 4 : ``p_i`` sur
    ``[d_r(π_i) ; d_r(π_{i+1})]`` du profil de la trace, du § 7.3."""
    expected = VALUES["Régimes" if name == "Régimes sans référence" else name]
    assert _closes(scores(name).control.forecast.segment_s, expected.control.segment_s)


@pytest.mark.parametrize("name", SCORING_CASES)
def test_control_forecast_has_no_point(name: str) -> None:
    """Précision 2 : en contrôle, ``point_s == ()`` et ``target_s == ()`` — ``C_k``
    et ``q_usage`` en usage seulement (décision 4, Q4 a)."""
    forecast = scores(name).control.forecast
    assert forecast.scenario is Scenario.CONTROL
    assert forecast.point_s == ()
    assert forecast.target_s == ()


@pytest.mark.parametrize("name", CONSTRUCTED)
def test_usage_forecast_reads_the_reference_timeline_at_the_bit(name: str) -> None:
    """§ 7.4 ; ``0010`` D16 : ``p_i == time_at(b_{i+1}) − time_at(b_i)`` ;
    ``P_k == time_at(x_k) − time_at(b_0)`` sur la chronologie de la référence."""
    forecast, observed = scores(name).usage, observation(name)
    assert forecast is not None
    timeline = _usage_timeline(name)
    origin_s = timeline.time_at(observed.origin_m)
    assert forecast.forecast.segment_s == tuple(
        timeline.time_at(s.end_m) - timeline.time_at(s.start_m)
        for s in observed.segments
    )
    assert forecast.forecast.point_s == tuple(
        timeline.time_at(p.distance_m) - origin_s for p in observed.error_points
    )
    assert forecast.forecast.target_s == tuple(
        timeline.time_at(p.distance_m) - origin_s for p in observed.targets
    )


@pytest.mark.parametrize("name", SCORING_CASES)
def test_control_forecast_reads_the_trace_timeline_at_the_bit(name: str) -> None:
    """§ 7.4 ; choix 4 : ``p_i == time_at(d_r(π_{i+1})) − time_at(d_r(π_i))`` sur la
    chronologie du profil de la trace."""
    timeline = _control_timeline(name)
    assert scores(name).control.forecast.segment_s == tuple(
        timeline.time_at(s.realized_end_m) - timeline.time_at(s.realized_start_m)
        for s in observation(name).segments
    )


def test_forecasts_publish_their_provenance_as_received() -> None:
    """Choix 5 et § 8.1, test 5 : ``source``, ``curve_ref``, ``parameters``,
    ``engine_version``, ``generated_at`` publiés tels que reçus (fuseau compris) ;
    ``engine_version`` par défaut : celle du moteur."""
    observed = observation("Passages")
    source = SourceRef(
        kind="gpx",
        identifier="essai.gpx",
        content_hash="3" * 64,
        retrieved_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    parameters = ParameterSet(PROJECTION_PARAMETER_SPECS, {"effort": 0.8})
    at = datetime(2026, 9, 30, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    for function, timeline in (
        (usage_forecast, _usage_timeline("Passages")),
        (control_forecast, _control_timeline("Passages")),
    ):
        forecast = function(
            observed,
            timeline,
            source=source,
            curve_ref="courbe#essai",
            parameters=parameters,
            generated_at=at,
            engine_version="essai-1",
        )
        assert forecast.source is source
        assert forecast.curve_ref == "courbe#essai"
        assert forecast.parameters is parameters
        assert forecast.engine_version == "essai-1"
        assert forecast.generated_at is at
        assert forecast.generated_at.utcoffset() == timedelta(hours=2)
        default = function(
            observed,
            timeline,
            source=source,
            curve_ref="courbe#essai",
            parameters=parameters,
            generated_at=at,
        )
        assert default.engine_version == ENGINE_VERSION


def test_usage_forecast_refuses_the_timeline_of_another_route() -> None:
    """Choix 11 : une chronologie dont la longueur n'est pas ``L`` de l'observation
    lève ``ValueError`` — ici celle de la trace de Passages."""
    with raises_value_error("usage_forecast : la chronologie a la longueur"):
        usage_forecast(
            observation("Passages"),
            _control_timeline("Passages"),
            source=chain("Passages").profile.source,
            curve_ref=curve_read().curve_ref,
            parameters=V0,
            generated_at=datetime(2026, 9, 30, tzinfo=UTC),
        )


def test_control_forecast_refuses_a_realized_abscissa_beyond_the_trace() -> None:
    """Choix 11 et § 6.4 : une abscisse réalisée au-delà de ``L_c`` (observation
    écrite à la main) lève ``ValueError``, par ``time_at``."""
    segment = AdmittedSegment(
        0, 0.0, 250.0, 0.0, 250.0, 0.0, 100.5, RegimeClass.FLAT, (10.0,) * len(CLOCKS)
    )
    observed = OutingObservation(
        1000.0,
        0.0,
        0.0,
        (segment,),
        (),
        (TargetMember(None, True),),
        (observation("Passages").targets[-1],),
        None,
    )
    with raises_value_error("time_at"):
        control_forecast(
            observed,
            ProjectedTimeline((0.0, 100.0), (1.0,)),
            source=chain("Passages").profile.source,
            curve_ref=curve_read().curve_ref,
            parameters=V0,
            generated_at=datetime(2026, 9, 30, tzinfo=UTC),
        )
