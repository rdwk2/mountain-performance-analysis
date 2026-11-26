"""L'étage 2 du modèle de la montée, la Fenêtre
(``mountain_perf.analyse.ascent.window_fit``, AN4-2a) : W1 à W15 du brief. Le monde E
du § 12.2, aux tolérances de la seconde implémentation ; le poids du § 12.1. Valeurs
inventées (règle 1). Sautés sans numpy ou scipy (extra ``analyse``)."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from fixtures.ascent_world import (
    EXACT_FIRST,
    WORLD_E_LAST_DAY,
    exact_world,
    spread_offsets,
    world_e_tables,
)
from mountain_perf.analyse.ascent import window_fit
from mountain_perf.analyse.ascent.daily import Z
from mountain_perf.analyse.ascent.parameters import MONTH_DAYS
from mountain_perf.analyse.ascent.references import References, references
from mountain_perf.analyse.ascent.selection import AscentClimb, select_climbs
from mountain_perf.analyse.ascent.speed import HabitualSpeed, habitual_speed
from mountain_perf.analyse.ascent.states import AscentState, Unavailable
from mountain_perf.analyse.ascent.structure import Point, Structure, fit_structure
from mountain_perf.analyse.ascent.window_fit import (
    Band,
    Trend,
    WindowFit,
    blend,
    colour_scale,
    fit_window,
    g2_band,
    window_trend,
)
from mountain_perf.analyse.tables import Tables
from mountain_perf.analyse.window import Window

FIRST: dict[str, Any] = {"rel": 1e-6, "abs": 1e-9}
SUMMARY: dict[str, Any] = {"rel": 1e-4, "abs": 1e-9}
LAST_56 = Window(date(2001, 3, 12), WORLD_E_LAST_DAY)
"""La Fenêtre des 56 derniers jours du monde E."""
DEFAULT_SPEED = HabitualSpeed(0.03, False, 0, AscentState.DEFAULT)


def fitted(
    tables: Tables, last_day: date | None = None
) -> tuple[Structure, tuple[AscentClimb, ...]]:
    climbs = select_climbs(tables).climbs
    refs = references(climbs, last_day or max(c.day for c in climbs))
    assert isinstance(refs, References)
    structure = fit_structure(climbs, refs)
    assert isinstance(structure, Structure)
    return structure, climbs


def world_e() -> tuple[Structure, tuple[AscentClimb, ...]]:
    return fitted(world_e_tables(), WORLD_E_LAST_DAY)


def window_of(window: Window, tables: Tables | None = None) -> WindowFit:
    structure, climbs = world_e() if tables is None else fitted(tables)
    fit = fit_window(structure, climbs, window)
    assert isinstance(fit, WindowFit)
    return fit


def test_w1_world_e_last_56_days() -> None:
    """W1 : le monde E, la Fenêtre des 56 derniers jours (§ 12.2)."""
    fit = window_of(LAST_56)
    assert (fit.n_sorties, fit.n_multi) == (7, 6)
    assert fit.mean_day == pytest.approx(207 / 7, rel=1e-12)
    assert fit.level == pytest.approx(-1.7291484335587912, **SUMMARY)
    assert fit.level_variance == pytest.approx(0.0010430739856747003, **SUMMARY)
    trend = fit.trend
    assert isinstance(trend, Trend)
    assert trend.slope == pytest.approx(0.024915451778219015, **SUMMARY)
    assert trend.variance == pytest.approx(0.0028560898612138446, **SUMMARY)
    assert trend.se_own == pytest.approx(0.04170268505379482, **SUMMARY)
    assert trend.interval.low == pytest.approx(-0.0798297227648356, **SUMMARY)
    assert trend.interval.high == pytest.approx(0.12966062632127365, **SUMMARY)
    assert trend.direction == 0
    assert trend.speed.value == 0.03
    assert trend.speed.state is AscentState.DEFAULT
    assert trend.speed.periods == 2
    assert trend.weight == pytest.approx(0.23961088079749762, **SUMMARY)
    assert trend.shrunk == pytest.approx(0.005970013346046636, **SUMMARY)
    assert trend.scale == pytest.approx(0.06, rel=1e-12)
    assert trend.ratio == pytest.approx(0.09950022243411061, **SUMMARY)
    assert fit.colour is None
    assert fit.beta.window == pytest.approx(2.8389764382281477, **FIRST)
    assert fit.beta.window_variance == pytest.approx(1.45879499209496, **FIRST)
    assert fit.beta.weight == pytest.approx(0.01518941204829079, **FIRST)
    assert fit.beta.value == pytest.approx(1.9225604461451378, **FIRST)
    assert fit.beta.variance == pytest.approx(0.8995426279049864, **FIRST)
    assert fit.g.window == pytest.approx(0.050461935082043094, **FIRST)
    assert fit.g.window_variance == pytest.approx(0.005084232825143788, **FIRST)
    assert fit.g.weight == pytest.approx(0.15039521794982552, **FIRST)
    assert fit.g.value == pytest.approx(0.04981396792939461, **FIRST)
    assert fit.g.variance == pytest.approx(0.003011960265797865, **FIRST)
    assert fit.g_borrowed is True
    assert fit.hr_bounds_bpm == pytest.approx((134.1, 154.5), **FIRST)
    assert fit.states == (AscentState.DEVICE_RUPTURE, AscentState.BORROWED)


def test_w2_the_g2_curve() -> None:
    """W2 : ``g2_band`` à 150 bpm (§ 12.2) ; à la FC de référence, la variance du
    niveau."""
    structure, climbs = world_e()
    fit = fit_window(structure, climbs, LAST_56)
    assert isinstance(fit, WindowFit)
    found = g2_band(fit, structure, 150.0)
    assert isinstance(found, Band)
    assert found.centre == pytest.approx(-1.6639706512441808, **SUMMARY)
    assert found.variance == pytest.approx(0.0020769320063881, **SUMMARY)
    assert found.low == pytest.approx(-1.7532928140926112, **SUMMARY)
    assert found.high == pytest.approx(-1.5746484883957503, **SUMMARY)
    at_ref = g2_band(fit, structure, structure.references.hr_bpm)
    assert at_ref.variance == fit.level_variance
    assert at_ref.centre == fit.level


def test_w3_the_whole_history() -> None:
    """W3 : tout l'historique : β et ``g`` de l'histoire, ``NOT_APPLICABLE``."""
    structure, climbs = world_e()
    fit = fit_window(structure, climbs, Window(date(2001, 1, 5), WORLD_E_LAST_DAY))
    assert isinstance(fit, WindowFit)
    for blended, k in ((fit.beta, 0), (fit.g, 1)):
        assert blended.value == structure.coef[k]
        assert blended.variance == structure.cov[k][k]
        assert blended.weight is None
        assert blended.window is None
    assert AscentState.NOT_APPLICABLE in fit.states
    assert fit.g_borrowed is False
    assert fit.colour is AscentState.NOT_APPLICABLE


def test_w3_bis_the_whole_history_under_120_days() -> None:
    """W3 bis : le monde E sans e01 (114 jours), la Fenêtre = toute l'histoire :
    ``colour = NOT_APPLICABLE`` par la règle « tout l'historique »."""
    tables = world_e_tables()
    tables = dataclasses.replace(
        tables,
        activities=tuple(a for a in tables.activities if a.activity_ref != "e01"),
        climbs=tuple(c for c in tables.climbs if c.activity_ref != "e01"),
    )
    structure, climbs = fitted(tables, WORLD_E_LAST_DAY)
    assert structure.n_multi == 11
    window = Window(date(2001, 1, 13), WORLD_E_LAST_DAY)
    assert window.days == 114
    fit = fit_window(structure, climbs, window)
    assert isinstance(fit, WindowFit)
    assert fit.colour is AscentState.NOT_APPLICABLE


def test_w4_the_120_days_rule() -> None:
    """W4 : 121 jours sans toute l'histoire : ``NOT_APPLICABLE`` ; 120 : la couleur
    se lit."""
    long = window_of(Window(WORLD_E_LAST_DAY - timedelta(days=120), WORLD_E_LAST_DAY))
    assert long.window.days == 121
    assert AscentState.NOT_APPLICABLE not in long.states
    assert long.colour is AscentState.NOT_APPLICABLE
    short = window_of(Window(WORLD_E_LAST_DAY - timedelta(days=119), WORLD_E_LAST_DAY))
    assert short.colour is None
    assert isinstance(short.trend, Trend)


def test_w5_five_then_six_sorties() -> None:
    """W5 : cinq sorties : pas de tendance, ``colour = INSUFFICIENT`` ; six : une
    tendance."""
    five = window_of(Window(date(2001, 4, 1), WORLD_E_LAST_DAY))
    assert five.n_sorties == 5
    assert isinstance(five.trend, Unavailable)
    assert five.trend.state is AscentState.INSUFFICIENT
    assert five.colour is AscentState.INSUFFICIENT
    six = window_of(Window(date(2001, 3, 20), WORLD_E_LAST_DAY))
    assert six.n_sorties == 6
    assert isinstance(six.trend, Trend)


def test_w5_bis_six_sorties_on_one_day() -> None:
    """W5 bis : six sorties le même jour : pas de tendance, sans exception."""
    last = EXACT_FIRST + timedelta(days=70)
    days = [EXACT_FIRST + timedelta(days=7 * j) for j in range(8)] + [last] * 6
    refs = [f"x{j:02d}" for j in range(14)]
    hours = [9] * 8 + [6, 8, 10, 12, 14, 16]
    tables = exact_world(
        spread_offsets(14), noise=0.02, days=days, refs=refs, hours=hours
    )
    structure, climbs = fitted(tables)
    fit = fit_window(structure, climbs, Window(last, last))
    assert isinstance(fit, WindowFit)
    assert fit.n_sorties == 6
    assert isinstance(fit.trend, Unavailable)
    assert fit.trend.state is AscentState.INSUFFICIENT
    assert fit.colour is AscentState.INSUFFICIENT


def test_w6_no_sortie_in_the_window() -> None:
    """W6 : aucune sortie dans la Fenêtre : ``INSUFFICIENT``."""
    structure, climbs = world_e()
    result = fit_window(structure, climbs, Window(date(2001, 1, 6), date(2001, 1, 12)))
    assert isinstance(result, Unavailable)
    assert result.state is AscentState.INSUFFICIENT


def test_w7_a_single_multi_climb_sortie() -> None:
    """W7 : une seule sortie à deux montées (e15) : β et ``g`` de l'histoire,
    ``INSUFFICIENT`` et ``BORROWED``."""
    structure, climbs = world_e()
    fit = fit_window(structure, climbs, Window(date(2001, 4, 26), date(2001, 5, 5)))
    assert isinstance(fit, WindowFit)
    assert fit.n_multi == 1
    assert fit.beta.value == structure.coef[0]
    assert fit.g.value == structure.coef[1]
    assert (fit.beta.weight, fit.g.weight) == (None, None)
    assert AscentState.INSUFFICIENT in fit.states
    assert AscentState.BORROWED in fit.states
    assert fit.g_borrowed is True


def test_w7_bis_two_sorties_of_two_climbs() -> None:
    """W7 bis : e13 et e14, deux montées chacune (``N_w − G_w − 2 = 0``) : β et
    ``g`` de l'histoire, ``INSUFFICIENT``."""
    structure, climbs = world_e()
    fit = fit_window(structure, climbs, Window(date(2001, 4, 5), date(2001, 4, 20)))
    assert isinstance(fit, WindowFit)
    assert fit.n_multi == 2
    assert fit.beta.window is None
    assert fit.g.window is None
    assert AscentState.INSUFFICIENT in fit.states


def test_w8_one_device() -> None:
    """W8 : un seul appareil : pas de ``DEVICE_RUPTURE``."""
    fit = window_of(Window(date(2001, 3, 12), date(2001, 4, 20)))
    assert AscentState.DEVICE_RUPTURE not in fit.states


def test_w8_bis_a_known_device_and_none() -> None:
    """W8 bis : un appareil connu et une montée sans appareil : ``DEVICE_RUPTURE``."""
    tables = world_e_tables()
    tables = dataclasses.replace(
        tables,
        climbs=tuple(
            dataclasses.replace(c, device_product=None)
            if c.activity_ref == "e14"
            else c
            for c in tables.climbs
        ),
    )
    structure, climbs = fitted(tables, WORLD_E_LAST_DAY)
    fit = fit_window(structure, climbs, Window(date(2001, 4, 5), date(2001, 4, 20)))
    assert isinstance(fit, WindowFit)
    assert {c.device for c in climbs if c.activity_ref in ("e13", "e14")} == {
        ("garmin", 1),
        None,
    }
    assert AscentState.DEVICE_RUPTURE in fit.states


def test_w9_the_hand_weight() -> None:
    """W9 : le poids du § 12.1."""
    found = blend(1.5, 0.01, 2.1, 0.45**2, 0.15)
    assert found.weight == pytest.approx(0.1, rel=1e-12)
    assert found.value == pytest.approx(1.56, rel=1e-12)
    assert found.variance == pytest.approx(0.02835, rel=1e-12)
    assert found.history == 1.5
    assert found.window == 2.1


def trend_points(slope: float) -> list[Point]:
    """W10 : six résumés aux jours 0 à 50, une pente sans écart de pente."""
    first = date(2001, 1, 1)
    shifts = (0.10, -0.10, 0.0, 0.0, -0.10, 0.10)
    return [
        Point(first + timedelta(days=d), slope * d / MONTH_DAYS + s, 1e-6)
        for d, s in zip(range(0, 60, 10), shifts, strict=True)
    ]


def test_w10_the_direction_reads_the_borrowed_variance() -> None:
    """W10 : ``slope = 0,05`` exactement ; la variance empruntée donne +1 (la
    variance propre, ``se_own ≈ 0,073``, donnerait 0) ; la pente opposée, −1."""
    up = window_trend(trend_points(0.05), date(2001, 1, 1), DEFAULT_SPEED)
    assert isinstance(up, Trend)
    assert up.slope == pytest.approx(0.05, rel=1e-12)
    assert up.se_own == pytest.approx(0.073, abs=5e-4)
    assert up.slope - 1.96 * up.se_own < 0
    assert up.direction == 1
    assert (up.interval.high - up.slope) / math.sqrt(up.variance) == pytest.approx(
        Z, rel=1e-12
    )
    down = window_trend(trend_points(-0.05), date(2001, 1, 1), DEFAULT_SPEED)
    assert isinstance(down, Trend)
    assert down.direction == -1


def test_w11_the_ratio_is_bounded() -> None:
    """W11 : ``ratio`` ramené à ``[−1 ; 1]``."""
    for slope, expected in ((5.0, 1.0), (-5.0, -1.0)):
        trend = window_trend(trend_points(slope), date(2001, 1, 1), DEFAULT_SPEED)
        assert isinstance(trend, Trend)
        assert abs(trend.shrunk / trend.scale) > 1
        assert trend.ratio == expected


def test_w12_the_scale() -> None:
    """W12 : ``τ(w) = 0,001`` → le plancher 0,01 ; ``τ(w) = 0,08`` → le plafond
    0,10."""
    assert colour_scale(0.001) == 0.01
    assert colour_scale(0.08) == 0.10
    assert colour_scale(0.03) == pytest.approx(0.06, rel=1e-15)


def test_w13_hr_bounds_need_two_climbs() -> None:
    """W13 : une seule montée dans la Fenêtre (e12) : ``hr_bounds_bpm is None``."""
    fit = window_of(Window(date(2001, 4, 1), date(2001, 4, 5)))
    assert fit.n_sorties == 1
    assert fit.hr_bounds_bpm is None


def test_w14_the_window_does_not_change_the_first_stage() -> None:
    """W14 : ``fit_structure`` rend le même objet avant et après ``fit_window``."""
    before, climbs = world_e()
    fit_window(before, climbs, LAST_56)
    after, _ = world_e()
    assert after == before


def test_w15_the_scale_speed_reads_the_whole_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W15 : ``fit_window`` appelle ``habitual_speed`` avec tous les points de
    l'étage 1, la longueur de la Fenêtre et le dernier jour des références."""
    calls: list[tuple[Sequence[Point], int, date]] = []
    original = habitual_speed

    def recording(points: Sequence[Point], length_days: int, end: date) -> Any:
        calls.append((points, length_days, end))
        return original(points, length_days, end)

    monkeypatch.setattr(window_fit, "habitual_speed", recording)
    structure, climbs = world_e()
    fit_window(structure, climbs, LAST_56)
    assert len(calls) == 1
    points, length, end = calls[0]
    assert tuple(points) == structure.points
    assert length == LAST_56.days == 56
    assert end == structure.references.last_day == WORLD_E_LAST_DAY


def test_w16_a_window_from_before_the_history_to_before_its_end() -> None:
    """W16 : une Fenêtre qui part avant l'histoire et finit avant sa fin n'est pas
    « tout l'historique »."""
    fit = window_of(Window(date(2001, 1, 1), date(2001, 3, 1)))
    assert AscentState.NOT_APPLICABLE not in fit.states
    assert fit.beta.window is not None
    assert fit.colour is None


def test_w17_the_scale_speed_at_the_window_length_from_the_last_day() -> None:
    """W17 : ``τ(w)`` à la longueur de la Fenêtre (42 jours), ancré au dernier jour
    des données (une semaine après la dernière sortie)."""
    last_day = date(2001, 5, 13)
    structure, climbs = fitted(world_e_tables(), last_day)
    fit = fit_window(structure, climbs, Window(date(2001, 3, 9), date(2001, 4, 19)))
    assert isinstance(fit, WindowFit)
    assert isinstance(fit.trend, Trend)
    assert fit.trend.speed == habitual_speed(structure.points, 42, last_day)
    assert fit.trend.speed.periods == 3


def test_w18_g_not_borrowed() -> None:
    """W18 : le poids de ``g`` atteint 0,2 (celui de β non) : ``g`` n'est pas
    « emprunté à l'histoire »."""
    fit = window_of(Window(date(2001, 1, 5), date(2001, 5, 5)))
    assert fit.g.weight is not None
    assert fit.beta.weight is not None
    assert fit.g.weight >= 0.2
    assert fit.beta.weight < 0.2
    assert fit.g_borrowed is False
    assert AscentState.BORROWED not in fit.states


def test_w19_the_order_of_the_states() -> None:
    """W19 : les états dans l'ordre du § 8.4 : rupture d'appareil, données
    insuffisantes, emprunté."""
    tables = world_e_tables()
    tables = dataclasses.replace(
        tables,
        climbs=tuple(
            dataclasses.replace(c, device_product=None)
            if c.activity_ref == "e14"
            else c
            for c in tables.climbs
        ),
    )
    structure, climbs = fitted(tables, WORLD_E_LAST_DAY)
    fit = fit_window(structure, climbs, Window(date(2001, 4, 5), date(2001, 4, 20)))
    assert isinstance(fit, WindowFit)
    assert fit.states == (
        AscentState.DEVICE_RUPTURE,
        AscentState.INSUFFICIENT,
        AscentState.BORROWED,
    )


def test_w20_the_first_window_estimate_of_beta_and_g() -> None:
    """W20 : deux sorties à deux montées ou plus (e10, trois ; e11, deux),
    ``N_w − G_w − 2 = 1`` : β et ``g`` de la Fenêtre sont estimés."""
    fit = window_of(Window(date(2001, 3, 10), date(2001, 3, 30)))
    assert fit.n_multi == 2
    assert fit.beta.window is not None
    assert fit.g.window is not None
    assert AscentState.INSUFFICIENT not in fit.states


def test_w21_a_zero_scale_speed() -> None:
    """W21 : ``τ(w) = 0`` : le poids et la pente rétrécie sont nuls."""
    speed = HabitualSpeed(0.0, True, 12, AscentState.ESTIMATED)
    trend = window_trend(trend_points(0.05), date(2001, 1, 1), speed)
    assert isinstance(trend, Trend)
    assert trend.weight == 0.0
    assert trend.shrunk == 0.0


def test_w15_bis_the_scale_speed_reads_beyond_the_past_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W15 bis (contre-épreuve F33) : sur une histoire de plus d'un an,
    ``habitual_speed`` reçoit aussi les points d'avant l'année écoulée."""
    calls: list[Sequence[Point]] = []
    original = habitual_speed

    def recording(points: Sequence[Point], length_days: int, end: date) -> Any:
        calls.append(points)
        return original(points, length_days, end)

    monkeypatch.setattr(window_fit, "habitual_speed", recording)
    structure, climbs = fitted(exact_world(spread_offsets(60), noise=0.02))
    assert any(p.day < structure.references.first_day for p in structure.points)
    last = structure.references.last_day
    fit = fit_window(structure, climbs, Window(last - timedelta(days=55), last))
    assert isinstance(fit, WindowFit)
    assert len(calls) == 1
    assert tuple(calls[0]) == structure.points
