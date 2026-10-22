"""L'enchaînement de ``mperf match`` en bibliothèque : ``match_outing``,
``check_outing``, ``in_curve_window`` (§ 6.1 et § 8.2 du brief M5-2 ; ``0010`` D2.2,
D3).

Sur la paire commitée (``appariement_reference.gpx``, ``appariement_trace_x01.gpx``)
et la courbe synthétique ; sans Streamlit.
"""

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from fixtures.matching import MATCH_REFERENCE_GPX, MATCH_TRACE_GPX
from mountain_perf.backtest.geometry import reference_geometry
from mountain_perf.backtest.matching import MATCHING_PARAMETER_SPECS
from mountain_perf.backtest.passages import observe_passages
from mountain_perf.backtest.scoring import report_clocks, v0_scores
from mountain_perf.backtest.segments import match_trace
from mountain_perf.cli import main
from mountain_perf.clocks import clock_partition
from mountain_perf.gpx import (
    PROFILE_PARAMETER_SPECS,
    GpxError,
    build_profile,
    read_gpx,
)
from mountain_perf.gpx.trace_reader import read_trace
from mountain_perf.model import PROJECTION_PARAMETER_SPECS, CurveError, read_curve
from mountain_perf.runs import OutingMatch, check_outing, in_curve_window, match_outing
from mountain_perf.schemas import CurveProvenance, ParameterSet
from mountain_perf.series import build_series
from mountain_perf.validation import ContractError

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = FIXTURES / MATCH_REFERENCE_GPX
TRACE = FIXTURES / MATCH_TRACE_GPX
CURVE = FIXTURES / "courbe_synthetique.csv"
NO_TRKPT_GPX = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">\n'
    "</gpx>\n"
)


def _match(curve: Path | None = CURVE) -> OutingMatch:
    return match_outing(REFERENCE, TRACE, curve, {})


def _unreadable(path: Path) -> Path:
    path.write_text("pas un fichier lisible\n", encoding="utf-8")
    return path


def _estimation(first: date, last: date) -> CurveProvenance:
    """La provenance de la courbe commitée, sa fenêtre remplacée par ``[first ;
    last]``."""
    curve = read_curve(CURVE, ParameterSet(PROJECTION_PARAMETER_SPECS)).curve
    return replace(curve.estimation, date_from=first, date_to=last)


# ---------------------------------------------------------------------------
# match_outing
# ---------------------------------------------------------------------------


def test_match_outing_equals_the_previous_chain() -> None:
    """L'enchaînement d'avant, écrit ici avec les fonctions de ``backtest/`` : mêmes
    points, segments, couverture et passages."""
    parameters = ParameterSet(MATCHING_PARAMETER_SPECS)
    read = read_gpx(REFERENCE)
    profile = build_profile(read.route, ParameterSet(PROFILE_PARAMETER_SPECS))
    geometry = reference_geometry(read.route)
    trace = read_trace([TRACE])
    series = build_series(trace)
    partition = clock_partition(trace, series)
    result = match_trace(geometry, profile, trace, series, partition, parameters)
    passages = observe_passages(result, geometry, profile, trace, series, partition)

    match = _match()
    assert match.parameters == parameters
    assert match.result.points == result.points
    assert match.result.segments == result.segments
    assert match.result.coverage == result.coverage
    assert match.passages == passages
    assert match.curve is not None


def test_without_curve_the_curve_is_none() -> None:
    assert _match(None).curve is None


def test_an_unreadable_curve_comes_before_an_unreadable_route(tmp_path: Path) -> None:
    """La courbe est lue avant le préparé (``mperf match`` : une erreur de lecture de
    la courbe laisse la sortie vide)."""
    route = _unreadable(tmp_path / "prepare.gpx")
    curve = _unreadable(tmp_path / "courbe.csv")
    with pytest.raises(CurveError):
        match_outing(route, TRACE, curve, {})


def test_the_matching_parameters_come_before_an_unreadable_curve(
    tmp_path: Path,
) -> None:
    curve = _unreadable(tmp_path / "courbe.csv")
    with pytest.raises(ContractError, match="score_step_m"):
        match_outing(REFERENCE, TRACE, curve, {"score_step_m": -1.0})


def test_an_unreadable_route_comes_before_an_unreadable_trace(tmp_path: Path) -> None:
    """``read_gpx`` n'écrit pas le nom du fichier dans ses messages ; le préparé est
    donc sans ``<trkpt>``, la trace mal formée, et le message dit lequel a été lu."""
    route = tmp_path / "prepare.gpx"
    route.write_text(NO_TRKPT_GPX, encoding="utf-8")
    trace = _unreadable(tmp_path / "trace.gpx")
    with pytest.raises(GpxError) as caught:
        match_outing(route, trace, None, {})
    assert str(caught.value) == "Aucun <trkpt> dans le fichier GPX."
    with pytest.raises(GpxError, match=r"^trace\.gpx : "):
        match_outing(REFERENCE, trace, None, {})


# ---------------------------------------------------------------------------
# check_outing
# ---------------------------------------------------------------------------


def test_check_outing_without_curve_is_refused() -> None:
    with pytest.raises(ValueError, match=r"^check_outing ") as caught:
        check_outing(_match(None))
    assert str(caught.value) == "check_outing : l'appariement n'a pas de courbe."


def test_check_outing_scores_are_those_of_v0_scores() -> None:
    """Les scores de ``v0_scores`` appelé ici, au même ``generated_at``."""
    match = _match()
    check = check_outing(match)
    assert match.curve is not None
    assert check.scores.usage is not None
    generated_at = check.scores.control.forecast.generated_at
    assert check.scores.usage.forecast.generated_at == generated_at
    expected = v0_scores(
        match.profile,
        match.trace,
        match.result,
        match.passages,
        match.partition,
        match.curve.curve,
        curve_ref=match.curve.curve_ref,
        generated_at=generated_at,
    )
    assert check.scores == expected


def test_without_reference_there_is_no_usage() -> None:
    match = _match()
    assert check_outing(match).scores.usage is not None
    check = check_outing(match, with_reference=False)
    assert check.scores.usage is None
    assert match.curve is not None
    expected = v0_scores(
        None,
        match.trace,
        match.result,
        match.passages,
        match.partition,
        match.curve.curve,
        curve_ref=match.curve.curve_ref,
        generated_at=check.scores.control.forecast.generated_at,
    )
    assert check.scores == expected


def test_check_outing_clocks_day_and_window() -> None:
    match = _match()
    check = check_outing(match)
    assert check.clocks == report_clocks(match.result)
    assert check.day == date(2026, 6, 1)
    assert check.in_curve_window is False


def test_the_day_is_the_civil_day_in_paris_end_to_end(tmp_path: Path) -> None:
    """Les 33 instants de la trace passés de 08:00:00–08:05:20 UTC le 1er juin à
    23:00:00–23:05:20 UTC le 31 janvier, soit le 1er février à Paris : le jour est le
    1er février, hors de la fenêtre de janvier de la courbe — sur la date UTC, le 31
    janvier, il y serait."""
    text = TRACE.read_text(encoding="utf-8")
    assert text.count("2026-06-01T08:") == 33
    trace = tmp_path / "trace_minuit.gpx"
    trace.write_text(text.replace("2026-06-01T08:", "2026-01-31T23:"), encoding="utf-8")
    match = match_outing(REFERENCE, trace, CURVE, {})
    assert match.trace.start_time.date() == date(2026, 1, 31)
    assert match.curve is not None
    estimation = match.curve.curve.estimation
    assert estimation.date_from <= date(2026, 1, 31) <= estimation.date_to
    check = check_outing(match)
    assert check.day == date(2026, 2, 1)
    assert check.in_curve_window is False


def test_mperf_match_prints_the_reports_before_the_scores(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Piège 1 : une erreur de ``v0_scores`` laisse les sections 1 à 10 imprimées,
    ligne pour ligne celles de ``mperf match`` sans courbe ; l'erreur sur la sortie
    d'erreur."""
    assert main(["match", str(REFERENCE), str(TRACE)]) == 0
    without = capsys.readouterr().out.splitlines()
    assert len(without) == 28

    def failing(*args: object, **kwargs: object) -> None:
        raise ContractError("essai")

    monkeypatch.setattr("mountain_perf.runs.v0_scores", failing)
    code = main(["match", str(REFERENCE), str(TRACE), "--curve", str(CURVE)])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out.splitlines() == without
    assert captured.err == "Erreur : essai\n"


# ---------------------------------------------------------------------------
# in_curve_window (0010 D2.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("instant", "inside"),
    [
        (datetime(2026, 1, 10, 9, 0, tzinfo=UTC), True),
        (datetime(2026, 1, 20, 9, 0, tzinfo=UTC), True),
        (datetime(2026, 1, 15, 9, 0, tzinfo=UTC), True),
        (datetime(2026, 1, 9, 9, 0, tzinfo=UTC), False),
        (datetime(2026, 1, 21, 9, 0, tzinfo=UTC), False),
    ],
    ids=["date_from", "date_to", "milieu", "veille", "lendemain"],
)
def test_the_window_includes_its_bounds(instant: datetime, inside: bool) -> None:
    estimation = _estimation(date(2026, 1, 10), date(2026, 1, 20))
    assert in_curve_window(instant, estimation) is inside


@pytest.mark.parametrize(
    ("instant", "last", "inside"),
    [
        (datetime(2026, 1, 31, 22, 30, tzinfo=UTC), date(2026, 1, 31), True),
        (datetime(2026, 1, 31, 23, 30, tzinfo=UTC), date(2026, 1, 31), False),
        (datetime(2026, 7, 31, 22, 30, tzinfo=UTC), date(2026, 7, 31), False),
    ],
    ids=["23 h 30 à Paris", "0 h 30 à Paris", "0 h 30 à Paris, heure d'été"],
)
def test_the_window_uses_the_civil_day_in_paris(
    instant: datetime, last: date, inside: bool
) -> None:
    estimation = _estimation(date(2026, 1, 1), last)
    assert in_curve_window(instant, estimation) is inside


def test_a_naive_instant_is_refused() -> None:
    estimation = _estimation(date(2026, 1, 1), date(2026, 1, 31))
    with pytest.raises(ContractError):
        in_curve_window(datetime(2026, 1, 15, 9, 0), estimation)
