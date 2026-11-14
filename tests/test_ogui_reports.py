"""Les textes de la courbe en mémoire (OG-UI, § 6.3 (a) du brief) : l'avertissement de
support et son repère, l'ordre des avertissements, la ligne « support » commune à la
synthèse de ``mperf project`` et à la page sortie."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from fixtures.matching import MATCH_REFERENCE_GPX, MATCH_TRACE_GPX
from mountain_perf.backtest.rolling import DEFAULT_BEYOND_MARKER
from mountain_perf.estimation.origin import OriginHistory, cold_start_warning
from mountain_perf.model import PROJECTION_PARAMETER_SPECS, read_curve
from mountain_perf.reports import (
    OUT_OF_SUPPORT_MARKER,
    curve_warnings,
    outing_support_lines,
    support_line,
    support_warning,
)
from mountain_perf.runs import match_outing
from mountain_perf.schemas import ParameterSet

FIXTURES = Path(__file__).parent / "fixtures"
CURVE = FIXTURES / "courbe_synthetique.csv"
REFERENCE = FIXTURES / MATCH_REFERENCE_GPX
TRACE = FIXTURES / MATCH_TRACE_GPX
HISTORY = OriginHistory(2, 0, 2, 0)
"""L'historique du monde ``interim/`` des fixtures : deux sorties à pied finies."""
SUPPORT_LINE = (
    "support      9 tranches lues, 5 retenues (>= 10 min), plage −20 % … +20 %"
)
"""La ligne de l'exemple du README, six espaces après « support »."""
TAIL = (
    " du temps prévu hors du support de la courbe : au-delà de 50 %, l'erreur mesurée "
    "croît, et la prévision est celle du prolongement."
)


def test_support_warning_at_the_marker() -> None:
    assert support_warning(0.5) is None
    assert support_warning(math.nextafter(0.5, 1)) == f"50 %{TAIL}"


def test_support_warning_of_a_profile_all_out_of_support() -> None:
    assert support_warning(1.0000000000000002) == f"100 %{TAIL}"


def test_support_warning_at_zero() -> None:
    assert support_warning(0.0) is None


def test_the_marker_is_the_beyond_marker_of_the_backtest() -> None:
    assert OUT_OF_SUPPORT_MARKER == DEFAULT_BEYOND_MARKER == 0.5


def test_curve_warnings_support_only() -> None:
    assert curve_warnings(None, 0.6) == (support_warning(0.6),)


def test_curve_warnings_cold_start_only() -> None:
    cold = cold_start_warning(HISTORY)
    assert cold is not None
    assert cold.startswith("moins de 20 sorties à pied passées (2) : ")
    assert curve_warnings(HISTORY, 0.0) == (cold,)


def test_curve_warnings_both_cold_start_first() -> None:
    assert curve_warnings(HISTORY, 0.6) == (
        cold_start_warning(HISTORY),
        support_warning(0.6),
    )


def test_support_line_of_the_readme() -> None:
    read = read_curve(CURVE, ParameterSet(PROJECTION_PARAMETER_SPECS))
    assert support_line(read, 10.0) == SUPPORT_LINE


def test_outing_support_lines() -> None:
    match = match_outing(REFERENCE, TRACE, CURVE, {})
    assert outing_support_lines(match, 0.0) == (
        SUPPORT_LINE,
        "             hors support : 0 % du temps prévu",
    )


def test_outing_support_lines_without_curve() -> None:
    match = match_outing(REFERENCE, TRACE, None, {})
    with pytest.raises(ValueError, match="pas de courbe"):
        outing_support_lines(match, 0.0)
