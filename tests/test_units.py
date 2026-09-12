"""Tests du module d'unités : exemples choisis et propriétés (hypothesis).

Plages des stratégies : physiquement plausibles, sans NaN ni infini.
Les aller-retours sont vérifiés en tolérance relative, jamais en égalité stricte.
"""

import math
import re

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from mountain_perf.units import (
    UNDEFINED,
    format_pace,
    format_vam,
    kmh_to_ms,
    ms_to_kmh,
    pace_s_per_km,
    speed_ms_from_pace,
    vertical_speed_from_grade,
)

# Vitesses horizontales : de l'arrêt au sprint.
speeds = st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)
# Pour tout ce qui touche à l'allure : borne basse à 0,5 m/s (déjà 33 min/km).
# En dessous, hypothesis produirait des 1e-300 et des allures absurdes.
pace_speeds = st.floats(
    min_value=0.5, max_value=10.0, allow_nan=False, allow_infinity=False
)
# Pentes : -60 % à +60 %.
grades = st.floats(min_value=-0.6, max_value=0.6, allow_nan=False, allow_infinity=False)

PACE_RE = re.compile(r"^\d+:[0-5]\d /km$")
VAM_RE = re.compile(r"^-?\d+ m/h$")


# ---------------------------------------------------------------------------
# Exemples
# ---------------------------------------------------------------------------


def test_ten_kmh_is_about_2_78_ms() -> None:
    assert kmh_to_ms(10.0) == pytest.approx(2.7777777, rel=1e-6)
    assert ms_to_kmh(2.7777777) == pytest.approx(10.0, rel=1e-6)


def test_pace_of_5_42_per_km() -> None:
    assert pace_s_per_km(1000 / 342) == pytest.approx(342.0)
    assert speed_ms_from_pace(342.0) == pytest.approx(1000 / 342)


@pytest.mark.parametrize("speed_ms", [0.0, -1.0])
def test_pace_calculation_is_strict(speed_ms: float) -> None:
    with pytest.raises(ValueError, match="> 0"):
        pace_s_per_km(speed_ms)


@pytest.mark.parametrize("pace", [0.0, -30.0])
def test_speed_from_pace_is_strict(pace: float) -> None:
    with pytest.raises(ValueError, match="> 0"):
        speed_ms_from_pace(pace)


def test_vertical_speed_examples() -> None:
    # 1 m/s à 10 % : 0,1 m/s vertical, soit 360 m/h.
    assert vertical_speed_from_grade(1.0, 0.10) == pytest.approx(0.10)
    assert vertical_speed_from_grade(1.0, -0.10) == pytest.approx(-0.10)
    assert vertical_speed_from_grade(1.0, 0.0) == 0.0
    assert vertical_speed_from_grade(0.0, 0.3) == 0.0


def test_format_pace_example() -> None:
    assert format_pace(1000 / 342) == "5:42 /km"


def test_format_pace_carries_seconds_into_minutes() -> None:
    # 359,6 s/km → arrondi à 360 → 6:00, pas 5:60.
    assert format_pace(1000 / 359.6) == "6:00 /km"


@pytest.mark.parametrize("speed_ms", [0.0, -1.0, math.nan, math.inf])
def test_format_pace_is_total(speed_ms: float) -> None:
    assert format_pace(speed_ms) == UNDEFINED


def test_format_vam_examples() -> None:
    assert format_vam(620 / 3600) == "620 m/h"
    assert format_vam(-450 / 3600) == "-450 m/h"
    assert format_vam(0.0) == "0 m/h"


def test_format_vam_never_shows_negative_zero() -> None:
    assert format_vam(-1e-9) == "0 m/h"
    assert format_vam(-0.0) == "0 m/h"


@pytest.mark.parametrize("vertical_speed_ms", [math.nan, math.inf, -math.inf])
def test_format_vam_is_total(vertical_speed_ms: float) -> None:
    assert format_vam(vertical_speed_ms) == UNDEFINED


# ---------------------------------------------------------------------------
# Propriétés
# ---------------------------------------------------------------------------


@given(speeds)
def test_kmh_ms_round_trip(speed_ms: float) -> None:
    assert kmh_to_ms(ms_to_kmh(speed_ms)) == pytest.approx(speed_ms, rel=1e-9)


@given(pace_speeds)
def test_pace_speed_round_trip(speed_ms: float) -> None:
    assert speed_ms_from_pace(pace_s_per_km(speed_ms)) == pytest.approx(
        speed_ms, rel=1e-9
    )


@given(speeds, speeds)
def test_ms_to_kmh_is_increasing(a: float, b: float) -> None:
    assume(b > a + 1e-9)
    assert ms_to_kmh(a) < ms_to_kmh(b)


@given(pace_speeds, pace_speeds)
def test_pace_decreases_when_speed_increases(a: float, b: float) -> None:
    assume(b > a + 1e-9)
    assert pace_s_per_km(a) > pace_s_per_km(b)


@given(speeds, grades)
def test_vertical_speed_has_the_sign_of_the_grade(
    speed_ms: float, grade: float
) -> None:
    vertical_speed_ms = vertical_speed_from_grade(speed_ms, grade)
    if speed_ms == 0 or grade == 0:
        assert vertical_speed_ms == 0
    else:
        assert math.copysign(1, vertical_speed_ms) == math.copysign(1, grade)


@given(speeds, grades)
def test_vertical_speed_is_linear_in_speed(speed_ms: float, grade: float) -> None:
    doubled = vertical_speed_from_grade(2 * speed_ms, grade)
    assert doubled == pytest.approx(2 * vertical_speed_from_grade(speed_ms, grade))


@given(pace_speeds)
def test_format_pace_shape(speed_ms: float) -> None:
    assert PACE_RE.match(format_pace(speed_ms))


@given(speeds, grades)
def test_format_vam_shape_and_no_negative_zero(speed_ms: float, grade: float) -> None:
    text = format_vam(vertical_speed_from_grade(speed_ms, grade))
    assert VAM_RE.match(text)
    assert text != "-0 m/h"
