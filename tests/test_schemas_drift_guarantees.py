"""Garanties des contrats de la dérive (``schemas/drift.py``) que la batterie jointe
n'exerçait pas : balayage par mutation de la PR #28 (lacunes L1 et L5). Des lacunes de
la conception, pas des défauts du code."""

import math

import pytest

from mountain_perf.schemas import ContractError, Unavailability
from test_schemas_drift import available, interval, outing


def test_close_has_an_absolute_floor() -> None:
    """Près de 0, la tolérance des égalités est absolue (``1e−12``) : un dernier
    ``B_k`` de ``1e−13`` s est accepté."""
    diagnostic = available(recentred_s=(0.0, 0.0, 1e-13))
    assert diagnostic.recentred_s[-1] == 1e-13


def test_zero_time_needs_a_zero_interval_even_with_short_ones() -> None:
    """« temps nul » exige un temps observé ``<= 0`` ; un intervalle de 0,5 s n'en est
    pas un."""
    short = interval(
        observed_s=0.5, log_ratio=math.log(0.005), moving_s=0.5, stop_s=0.0
    )
    with pytest.raises(ContractError):
        available(
            intervals=(short, *available().intervals[1:]),
            fit=None,
            withdrawals=(),
            slope_range=None,
            unavailability=Unavailability.ZERO_TIME,
        )


def test_short_durations_are_valid() -> None:
    """Les bornes sont à 0 : un intervalle de 0,5 s observé pour 0,4 s projeté, et un
    horizon de 0,5 s, sont valides."""
    short = interval(
        observed_s=0.5,
        projected_s=0.4,
        log_ratio=math.log(0.5 / 0.4),
        moving_s=0.5,
        stop_s=0.0,
    )
    assert short.observed_s == 0.5
    assert outing(horizon_s=0.5).horizon_s == 0.5
