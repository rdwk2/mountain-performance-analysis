"""Garanties de M5-2 sans test à la tête de la PR #35 (relecture de la PR : la C et
la conception), sans Streamlit : le signe d'un écart d'une seconde ; ce que
``match_outing`` publie du GPX lu ; les écarts d'un ``C_k`` indisponible et d'un lieu
nommé ; les écarts et les efforts sous chacune des horloges du rapport ; le jour et la
fenêtre d'une trace qui passe minuit à Paris, et le changement d'heure d'octobre ; les
six modules de ``backtest/`` que ``runs.py`` peut importer ; les objets gelés.

Les écarts et les efforts se lisent sur des cas construits par objets
(``tests/fixtures/scoring.py``), dont les valeurs attendues sont écrites en dur.
"""

import re
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from fixtures.matching import MATCH_REFERENCE_GPX, MATCH_TRACE_GPX
from fixtures.scoring import chain, scores
from mountain_perf.backtest.calendar import PARIS
from mountain_perf.backtest.scoring import report_clocks
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS, build_profile
from mountain_perf.model import PROJECTION_PARAMETER_SPECS, read_curve
from mountain_perf.outing_views import (
    EffortRow,
    FollowedRoute,
    GapRow,
    Gaps,
    ScenarioEffort,
    effort_rows,
    gaps,
)
from mountain_perf.runs import (
    OutingCheck,
    OutingMatch,
    check_outing,
    in_curve_window,
    match_outing,
)
from mountain_perf.schemas import CLOCKS, CurveProvenance, ParameterSet
from mountain_perf.units import format_signed_duration
from test_ui_imports import RUNS_BACKTEST_MODULES

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = FIXTURES / MATCH_REFERENCE_GPX
TRACE = FIXTURES / MATCH_TRACE_GPX
CURVE = FIXTURES / "courbe_synthetique.csv"


def test_a_one_second_gap_keeps_its_sign() -> None:
    """La borne entre zéro et le premier écart signé."""
    assert format_signed_duration(1.0) == "+0:01"
    assert format_signed_duration(1.4) == "+0:01"
    assert format_signed_duration(-1.0) == "−0:01"


def test_match_outing_publishes_the_route_it_profiled() -> None:
    """``OutingMatch.read`` est le GPX dont le profil publié est construit."""
    match = match_outing(REFERENCE, TRACE, None, {})
    profile = build_profile(match.read.route, ParameterSet(PROFILE_PARAMETER_SPECS))
    assert profile == match.profile


def test_a_named_place_of_a_route_names_its_gap_row(tmp_path: Path) -> None:
    """De bout en bout : le préparé commité, un ``<wpt>`` « Col » posé sur son tracé ;
    la ligne d'écarts de ce lieu porte son nom."""
    text = REFERENCE.read_text(encoding="utf-8")
    assert text.count("  <trk>") == 1
    route = tmp_path / "prepare_nomme.gpx"
    route.write_text(
        text.replace(
            "  <trk>", '  <wpt lat="45.0" lon="6.003"><name>Col</name></wpt>\n  <trk>'
        ),
        encoding="utf-8",
    )
    match = match_outing(route, TRACE, CURVE, {})
    check = check_outing(match)
    found = gaps(check.scores, match.passages, check.clocks)
    assert found is not None
    assert [row.name for row in found.rows] == ["Col", "point 1", "point 2", "point 3"]


def test_gaps_keep_an_unavailable_point_as_none() -> None:
    """« Chronologie » : W1 et W2 ambigus sous les trois horloges, leurs écarts
    ``None`` ; le plus grand écart reste celui de ``passage_errors``."""
    c, s = chain("Chronologie"), scores("Chronologie")
    found = gaps(s, c.passages, report_clocks(c.match))
    assert found is not None
    assert [row.name for row in found.rows] == [
        "point 1",
        "W1",
        "W2",
        "point 2",
        "point 3",
        "point 4",
        "point 5",
    ]
    assert [row.errors_s for row in found.rows[1:3]] == [(None,) * 3, (None,) * 3]
    others = found.rows[:1] + found.rows[3:]
    assert all(error is not None for row in others for error in row.errors_s)
    assert found.max_abs_s == pytest.approx(
        (908.3325461602751, 665.6666666666667, 698.3325461602751), rel=1e-12
    )


def test_gaps_name_the_places() -> None:
    """« Passages » : les lieux B et A, nommés comme dans ``mperf match``."""
    c, s = chain("Passages"), scores("Passages")
    found = gaps(s, c.passages, report_clocks(c.match))
    assert found is not None
    assert [row.name for row in found.rows] == [
        "point 1",
        "B",
        "A",
        "point 2",
        "point 3",
    ]


def test_gaps_and_efforts_follow_each_report_clock() -> None:
    """« Passages » : écoulé, ``M θ3``, ``(M+U) θ1`` — trois horloges distinctes,
    ``(M+U) θ1`` différent de l'écoulé ; ``T`` lu dans les totaux admis de
    ``MatchResult``, un autre chemin que la somme des segments."""
    c, s = chain("Passages"), scores("Passages")
    clocks = report_clocks(c.match)
    assert [CLOCKS.index(clock) for clock in clocks] == [0, 3, 6]
    found = gaps(s, c.passages, clocks)
    assert found is not None
    assert found.max_abs_s == pytest.approx(
        (620.0000007853603, 503.00000078536027, 528.0000007853603), rel=1e-12
    )
    assert found.rows[2].errors_s == pytest.approx(
        (-363.00000013090704, -248.00000013090704, -271.00000013090704), rel=1e-12
    )
    totals = c.match.admitted_totals
    expected = (
        c.match.coverage.admitted_elapsed_s,
        totals[2].moving_s,
        totals[0].moving_s + totals[0].undetermined_s,
    )
    rows = effort_rows(s, clocks)
    assert [row.observed_s for row in rows] == pytest.approx(expected, rel=1e-9)


def _shifted_trace(folder: Path, first: datetime) -> Path:
    """La trace commitée, ses 33 instants décalés pour que le premier soit ``first``."""
    text = TRACE.read_text(encoding="utf-8")
    assert text.count("2026-06-01T08:") == 33
    delta = first - datetime(2026, 6, 1, 8, 0, tzinfo=UTC)

    def shift(found: re.Match[str]) -> str:
        instant = datetime.fromisoformat(found.group(1)) + delta
        return f"<time>{instant.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}</time>"

    path = folder / "trace_decalee.gpx"
    path.write_text(re.sub(r"<time>([^<]+)</time>", shift, text), encoding="utf-8")
    return path


def test_a_trace_over_midnight_in_paris_takes_the_day_of_its_first_instant(
    tmp_path: Path,
) -> None:
    """Premier instant le 31 janvier à 23 h 58 à Paris, dernier le 1er février à
    0 h 03 : le jour et la fenêtre (janvier) sont ceux du premier instant."""
    trace = _shifted_trace(tmp_path, datetime(2026, 1, 31, 22, 58, tzinfo=UTC))
    match = match_outing(REFERENCE, trace, CURVE, {})
    assert match.trace.start_time.astimezone(PARIS).date() == date(2026, 1, 31)
    assert match.trace.end_time.astimezone(PARIS).date() == date(2026, 2, 1)
    check = check_outing(match)
    assert check.day == date(2026, 1, 31)
    assert check.in_curve_window is True


def _estimation(first: date, last: date) -> CurveProvenance:
    curve = read_curve(CURVE, ParameterSet(PROJECTION_PARAMETER_SPECS)).curve
    return replace(curve.estimation, date_from=first, date_to=last)


@pytest.mark.parametrize(
    ("instant", "first", "last", "inside"),
    [
        (datetime(2026, 10, 24, 21, 59, tzinfo=UTC), 1, 24, True),
        (datetime(2026, 10, 24, 22, 0, tzinfo=UTC), 1, 24, False),
        (datetime(2026, 10, 25, 0, 30, tzinfo=UTC), 25, 25, True),
        (datetime(2026, 10, 25, 1, 30, tzinfo=UTC), 25, 25, True),
        (datetime(2026, 10, 25, 22, 59, tzinfo=UTC), 1, 25, True),
        (datetime(2026, 10, 25, 23, 0, tzinfo=UTC), 1, 25, False),
        (datetime(2026, 10, 24, 22, 0, tzinfo=UTC), 25, 31, True),
        (datetime(2026, 10, 24, 21, 59, tzinfo=UTC), 25, 31, False),
    ],
    ids=[
        "23 h 59 CEST le 24",
        "0 h 00 CEST le 25",
        "2 h 30 CEST le 25",
        "2 h 30 CET le 25",
        "23 h 59 CET le 25",
        "0 h 00 CET le 26",
        "date_from à 0 h 00 CEST",
        "date_from, la veille",
    ],
)
def test_the_window_across_the_october_time_change(
    instant: datetime, first: int, last: int, inside: bool
) -> None:
    """Le passage à l'heure d'hiver (25 octobre 2026) : le jour civil à Paris, bornes
    comprises, de part et d'autre du changement."""
    window = _estimation(date(2026, 10, first), date(2026, 10, last))
    assert in_curve_window(instant, window) is inside


def test_runs_backtest_modules_are_the_six_pure_modules() -> None:
    """Décision 5 du § 3 du brief M5-2 : les six modules purs, jamais le registre,
    l'exécution, l'expérience, la sensibilité enregistrée, le manifeste, le codec, ni le
    paquet lui-même. La liste ne s'élargit pas sans que ce test change."""
    prefix = "mountain_perf.backtest"
    excluded = {prefix} | {
        f"{prefix}.{name}"
        for name in (
            "registry",
            "execution",
            "experiment",
            "sensitivity_run",
            "manifest",
            "codec",
        )
    }
    assert not set(RUNS_BACKTEST_MODULES) & excluded
    assert set(RUNS_BACKTEST_MODULES) == {
        f"{prefix}.{name}"
        for name in (
            "calendar",
            "geometry",
            "matching",
            "passages",
            "scoring",
            "segments",
        )
    }


@pytest.mark.parametrize(
    "cls",
    [OutingMatch, OutingCheck, FollowedRoute, ScenarioEffort, EffortRow, GapRow, Gaps],
)
def test_new_objects_are_frozen(cls: type) -> None:
    assert vars(cls)["__dataclass_params__"].frozen
