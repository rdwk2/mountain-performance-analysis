"""Drapeaux, régimes et strates (``mountain_perf.analyse.quality``,
``docs/decisions/0014``) : chaque seuil à sa frontière, sur des mesures écrites à la
main."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from mountain_perf.analyse.climbs import CLIMB_PARAMETER_SPECS, ClimbMeasure, ClimbSpan
from mountain_perf.analyse.quality import (
    DEFAULT_REFERENCE_VERTICAL_SPEED_MS,
    QUALITY_PARAMETER_SPECS,
    REGIME_PARAMETER_SPECS,
    altimetric_drift,
    altitude_stratum,
    climb_flags,
    grade_stratum,
    regime,
)
from mountain_perf.schemas import ParameterSet, Sport
from mountain_perf.schemas.processed import (
    AltitudeStratum,
    ClimbFlag,
    ClimbRegime,
    GradeStratum,
)

QUALITY = ParameterSet(QUALITY_PARAMETER_SPECS)
CLIMB = ParameterSet(CLIMB_PARAMETER_SPECS)
REGIMES = ParameterSet(REGIME_PARAMETER_SPECS)
SPAN = ClimbSpan(0.0, 1000.0, 100.0, 0.0, 1000.0, 100.0, 100.0, 100.0)


BASE = ClimbMeasure(
    span=SPAN,
    step_s=1.0,
    longest_step_s=1.0,
    moving_distance_m=1000.0,
    moving_s=(600.0,) * 5,
    stopped_s=(0.0,) * 5,
    undetermined_s=(0.0,) * 5,
    moving_gain_m=(100.0,) * 5,
    stopped_gain_m=(0.0,) * 5,
    undetermined_gain_m=(0.0,) * 5,
    gap_gain_m=0.0,
    slow_moving_s=0.0,
    net_displacement_m=1000.0,
    max_vertical_rate_ms=0.5,
    low_elevation_m=1000.0,
    high_elevation_m=1100.0,
    moving_mean_elevation_m=1050.0,
)
"""Une montée de 100 m en 600 s de M (VAM 600 m/h), 1 000 m parcourus en M, en ligne
droite, sans arrêt ni pic."""


def measure(**changes: Any) -> ClimbMeasure:
    """:data:`BASE`, dont ``changes`` remplace des champs."""
    return dataclasses.replace(BASE, **changes)


def flags(
    m: ClimbMeasure, sport: Sport | None = Sport.FOOT, **options: bool
) -> set[ClimbFlag]:
    kwargs = {"barometric": True, "altimetric_drift": False, **options}
    return set(climb_flags(m, sport, climb=CLIMB, quality=QUALITY, **kwargs))


def test_a_clean_climb_has_no_flag() -> None:
    assert flags(measure()) == set()


def test_gain_outside_moving_from_its_threshold_excluded() -> None:
    # 20 % exactement : pas marqué ; au-delà : marqué.
    at = measure(moving_gain_m=(80.0,) * 5, undetermined_gain_m=(20.0,) * 5)
    above = measure(moving_gain_m=(79.0,) * 5, undetermined_gain_m=(21.0,) * 5)
    assert ClimbFlag.GAIN_OUTSIDE_MOVING not in flags(at)
    assert ClimbFlag.GAIN_OUTSIDE_MOVING in flags(above)


def test_gain_outside_moving_reads_the_central_convention() -> None:
    other = measure(
        moving_gain_m=(50.0, 100.0, 50.0, 50.0, 50.0),
        stopped_gain_m=(50.0, 0.0, 50.0, 50.0, 50.0),
    )
    assert ClimbFlag.GAIN_OUTSIDE_MOVING not in flags(other)


def test_slow_moving_from_ten_percent_excluded() -> None:
    assert ClimbFlag.SLOW_MOVING not in flags(measure(slow_moving_s=60.0))
    assert ClimbFlag.SLOW_MOVING in flags(measure(slow_moving_s=61.0))


def test_non_human_by_vertical_speed_for_any_sport() -> None:
    # 3 000 m/h exactement : pas marqué.
    at = measure(moving_s=(120.0,) * 5)
    above = measure(moving_s=(119.0,) * 5)
    for sport in (Sport.FOOT, Sport.SKI_TOURING, Sport.MTB, None):
        assert ClimbFlag.NON_HUMAN not in flags(at, sport)
        assert ClimbFlag.NON_HUMAN in flags(above, sport)


def test_non_human_by_horizontal_speed_on_foot_only() -> None:
    fast = measure(moving_distance_m=6001.0, net_displacement_m=6001.0)
    at = measure(moving_distance_m=6000.0, net_displacement_m=6000.0)
    assert ClimbFlag.NON_HUMAN in flags(fast, Sport.FOOT)
    assert ClimbFlag.NON_HUMAN not in flags(at, Sport.FOOT)
    assert ClimbFlag.NON_HUMAN not in flags(fast, Sport.MTB)


def test_spike_above_three_metres_per_second() -> None:
    assert ClimbFlag.SPIKE not in flags(measure(max_vertical_rate_ms=3.0))
    assert ClimbFlag.SPIKE in flags(measure(max_vertical_rate_ms=3.01))


@pytest.mark.parametrize(
    ("moving_gain_m", "flagged"), [(-10.0, True), (50.0, True), (50.1, False)]
)
def test_unresolved_grade_when_the_moving_grade_is_not_read(
    moving_gain_m: float, flagged: bool
) -> None:
    """Le drapeau suit la strate « non résolue » : une pente en M jusqu'à la pente
    minimale (5 % ; ici 50 m sur 1 000 m) n'est pas lue, en ligne droite. À 50 m, la
    montée est marquée alors qu'aucune part de son gain n'est prise hors de M."""
    m = measure(moving_gain_m=(moving_gain_m,) * 5)
    assert (ClimbFlag.UNRESOLVED_GRADE in flags(m)) is flagged
    stratum = grade_stratum(m, CLIMB, REGIMES, QUALITY)
    assert (stratum is GradeStratum.UNRESOLVED) is flagged
    if moving_gain_m > 0:
        assert ClimbFlag.GAIN_OUTSIDE_MOVING not in flags(m)


def test_unresolved_grade_reads_the_declared_minimum_grade() -> None:
    """La pente minimale est celle des paramètres de la montée : abaissée à 4 %, une
    pente en M de 5 % est lue."""
    m = measure(moving_gain_m=(50.0,) * 5)
    lower = ParameterSet(CLIMB_PARAMETER_SPECS, {**CLIMB.values, "min_grade": 0.04})
    found = climb_flags(
        m,
        Sport.FOOT,
        barometric=True,
        altimetric_drift=False,
        climb=lower,
        quality=QUALITY,
    )
    assert ClimbFlag.UNRESOLVED_GRADE not in found


def test_the_gain_of_a_stop_stays_out_of_the_principal_vertical_speed() -> None:
    """``G_M,θc / M_θc`` : le gain pris pendant S n'entre ni dans la VAM principale,
    ni dans sa variante ``(G_M + G_U) / (M + U)`` ; il compte dans la part du gain
    prise hors de M."""
    m = measure(stopped_gain_m=(20.0,) * 5)
    assert m.vertical_speed_ms == pytest.approx(100.0 / 600.0)
    assert m.moving_or_undetermined_vertical_speed_ms == pytest.approx(100.0 / 600.0)
    assert m.outside_moving_gain_fraction == pytest.approx(20.0 / 120.0)


def test_unresolved_grade_above_a_sinuosity_of_six() -> None:
    at = measure(net_displacement_m=1000.0 / 6)
    above = measure(net_displacement_m=1000.0 / 6.01)
    zero = measure(net_displacement_m=0.0)
    assert ClimbFlag.UNRESOLVED_GRADE not in flags(at)
    assert ClimbFlag.UNRESOLVED_GRADE in flags(above)
    assert ClimbFlag.UNRESOLVED_GRADE in flags(zero)


def test_activity_flags_are_passed_through() -> None:
    assert ClimbFlag.NON_BAROMETRIC in flags(measure(), barometric=False)
    assert ClimbFlag.ALTIMETRIC_DRIFT in flags(measure(), altimetric_drift=True)


def test_altimetric_drift_only_on_a_loop_above_five_metres_per_hour() -> None:
    assert altimetric_drift(49.0, 5.0, 3600.0, QUALITY) is False
    assert altimetric_drift(49.0, -5.01, 3600.0, QUALITY) is True
    assert altimetric_drift(50.0, 50.0, 3600.0, QUALITY) is False
    assert altimetric_drift(10.0, 1.0, 0.0, QUALITY) is False
    assert altimetric_drift(10.0, 1.0, 0.5, QUALITY) is True


@pytest.mark.parametrize(
    ("gain_m", "expected"),
    [
        (75.0, ClimbRegime.SHORT_CLIMB),
        (75.01, ClimbRegime.INTERMEDIATE),
        (224.99, ClimbRegime.INTERMEDIATE),
        (225.0, ClimbRegime.LONG_CLIMB),
    ],
)
def test_foot_regimes_at_v_ref_times_five_and_fifteen_minutes(
    gain_m: float, expected: ClimbRegime
) -> None:
    assert regime(gain_m, Sport.FOOT, DEFAULT_REFERENCE_VERTICAL_SPEED_MS, REGIMES) is (
        expected
    )


def test_regimes_follow_the_declared_reference_speed() -> None:
    v_ref = 600.0 / 3600.0
    assert regime(50.0, Sport.FOOT, v_ref, REGIMES) is ClimbRegime.SHORT_CLIMB
    assert regime(150.0, Sport.FOOT, v_ref, REGIMES) is ClimbRegime.LONG_CLIMB


def test_ski_touring_and_other_sports() -> None:
    v_ref = DEFAULT_REFERENCE_VERTICAL_SPEED_MS
    assert (
        regime(75.0, Sport.SKI_TOURING, v_ref, REGIMES) is ClimbRegime.SHORT_SKI_TOURING
    )
    assert regime(75.01, Sport.SKI_TOURING, v_ref, REGIMES) is ClimbRegime.SKI_TOURING
    assert regime(500.0, Sport.MTB, v_ref, REGIMES) is ClimbRegime.OTHER_SPORT
    assert regime(500.0, None, v_ref, REGIMES) is ClimbRegime.OTHER_SPORT


@pytest.mark.parametrize(
    ("moving_gain_m", "expected"),
    [
        (150.0, GradeStratum.MODERATE),
        (150.1, GradeStratum.STEEP),
        (300.0, GradeStratum.STEEP),
        (300.1, GradeStratum.VERY_STEEP),
    ],
)
def test_grade_strata_on_moving_gain_over_moving_length(
    moving_gain_m: float, expected: GradeStratum
) -> None:
    m = measure(moving_gain_m=(moving_gain_m,) * 5)
    assert grade_stratum(m, CLIMB, REGIMES, QUALITY) is expected


def test_grade_stratum_unresolved_above_the_sinuosity_threshold() -> None:
    m = measure(net_displacement_m=1000.0 / 6.01)
    assert grade_stratum(m, CLIMB, REGIMES, QUALITY) is GradeStratum.UNRESOLVED


@pytest.mark.parametrize(
    ("moving_gain_m", "expected"),
    [
        (-10.0, GradeStratum.UNRESOLVED),
        (50.0, GradeStratum.UNRESOLVED),
        (50.1, GradeStratum.MODERATE),
    ],
)
def test_a_grade_in_moving_time_up_to_the_minimum_is_not_read(
    moving_gain_m: float, expected: GradeStratum
) -> None:
    """Le filtre lit la pente de toute la montée : celle des intervalles M peut ne pas
    dépasser la pente minimale (5 % ; ici 50 m sur 1 000 m), quand le gain est pris
    hors de M. La strate ne la lit pas."""
    m = measure(moving_gain_m=(moving_gain_m,) * 5)
    assert grade_stratum(m, CLIMB, REGIMES, QUALITY) is expected


@pytest.mark.parametrize(
    ("elevation_m", "expected"),
    [
        (1499.9, AltitudeStratum.LOW),
        (1500.0, AltitudeStratum.MID),
        (2499.9, AltitudeStratum.MID),
        (2500.0, AltitudeStratum.HIGH),
    ],
)
def test_altitude_strata_on_the_moving_mean_elevation(
    elevation_m: float, expected: AltitudeStratum
) -> None:
    m = measure(moving_mean_elevation_m=elevation_m)
    assert altitude_stratum(m, REGIMES) is expected


def test_no_altitude_stratum_without_moving_time() -> None:
    assert altitude_stratum(measure(moving_mean_elevation_m=None), REGIMES) is None


def test_the_measure_properties() -> None:
    m = measure(
        moving_s=(500.0, 600.0, 700.0, 800.0, 900.0),
        undetermined_s=(100.0,) * 5,
        undetermined_gain_m=(20.0,) * 5,
        slow_moving_s=30.0,
    )
    assert m.vertical_speed_ms == pytest.approx(100.0 / 600.0)
    assert m.moving_or_undetermined_vertical_speed_ms == pytest.approx(120.0 / 700.0)
    assert m.vertical_speed_envelope_ms == pytest.approx((100.0 / 900.0, 100.0 / 500.0))
    assert m.slow_moving_fraction == pytest.approx(0.05)
    assert m.outside_moving_gain_fraction == pytest.approx(20.0 / 120.0)
    assert m.elapsed_s == 1000.0
    assert dataclasses.replace(m, moving_s=(0.0,) * 5).vertical_speed_ms is None
