"""Les références et l'étage 1 du modèle de la montée
(``mountain_perf.analyse.ascent.references``, ``…structure``, AN4-2a) : R1 à R5, T1 à
T12 du brief. Les valeurs du monde E viennent de la seconde implémentation de la
conception (§ 12.2 du brief), à ses tolérances. Valeurs inventées (règle 1). Sautés
sans numpy ou scipy (extra ``analyse``)."""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from fixtures.ascent_world import (
    EXACT_COEF,
    EXACT_FIRST,
    EXACT_REF_HR,
    WORLD_E_LAST_DAY,
    ascent_climb,
    exact_world,
    spread_offsets,
    world_e_tables,
)
from fixtures.q2_world import at, q2_activity, q2_tables
from mountain_perf.analyse.ascent.references import References, references, round_to
from mountain_perf.analyse.ascent.selection import AscentClimb, select_climbs
from mountain_perf.analyse.ascent.states import AscentState, Unavailable
from mountain_perf.analyse.ascent.structure import Structure, fit_structure
from mountain_perf.analyse.tables import Tables
from mountain_perf.schemas.processed import ClimbRegime


def make_climb(
    day: date,
    *,
    ref: str = "a",
    hr_bpm: float = 145.0,
    altitude_km: float = 1.5,
    d_plus_km: float = 0.5,
    start: datetime | None = None,
) -> AscentClimb:
    """Une montée gardée écrite à la main."""
    return AscentClimb(
        activity_ref=ref,
        day=day,
        start=start or at(day, 9),
        regime=ClimbRegime.LONG_CLIMB,
        log_speed=-1.8,
        hr_bpm=hr_bpm,
        d_plus_km=d_plus_km,
        altitude_km=altitude_km,
        intermediate=False,
        device=("garmin", 1),
        journal=(),
        temperature_c=15.0,
    )


def world_e_references() -> References:
    result = references(select_climbs(world_e_tables()).climbs, WORLD_E_LAST_DAY)
    assert isinstance(result, References)
    return result


@pytest.mark.parametrize(
    ("value", "step", "expected"),
    [
        (147.5, 5.0, 150.0),
        (142.4999, 5.0, 140.0),
        (142.5, 5.0, 145.0),
        (1450.0, 100.0, 1500.0),
        (1449.99, 100.0, 1400.0),
    ],
)
def test_r1_round_half_up(value: float, step: float, expected: float) -> None:
    """R1 : les cinq arrondis du § 12.1, la moitié vers le haut."""
    assert round_to(value, step) == expected


def test_r2_world_e_references() -> None:
    """R2 : les références du monde E (§ 12.2)."""
    refs = world_e_references()
    assert refs.hr_bpm == 145.0
    assert refs.hr_low_bpm == 140.0
    assert refs.hr_high_bpm == 150.0
    assert refs.altitude_km == pytest.approx(1.5, rel=1e-6, abs=1e-9)
    assert refs.d_plus_km == pytest.approx(0.8335, rel=1e-6, abs=1e-9)
    assert refs.last_day == WORLD_E_LAST_DAY
    assert refs.first_day == WORLD_E_LAST_DAY - timedelta(days=364)


def test_r3_the_past_year() -> None:
    """R3 : une montée au jour ``last_day − 365`` n'entre pas ; une au jour
    ``last_day − 364`` entre."""
    last = date(2002, 6, 30)
    inside = [
        make_climb(last, hr_bpm=150.0),
        make_climb(last - timedelta(days=10), hr_bpm=150.0),
    ]
    outside = make_climb(last - timedelta(days=365), hr_bpm=100.0, d_plus_km=9.0)
    edge = make_climb(last - timedelta(days=364), hr_bpm=120.0, d_plus_km=2.0)
    without = references([*inside, outside], last)
    assert isinstance(without, References)
    assert without.hr_bpm == 150.0
    assert without.d_plus_km == pytest.approx(0.5, rel=1e-15)
    with_edge = references([*inside, edge], last)
    assert isinstance(with_edge, References)
    assert with_edge.d_plus_km == pytest.approx(1.0, rel=1e-15)
    assert with_edge.first_day == last - timedelta(days=364)


def test_r4_fewer_than_two_climbs() -> None:
    """R4 : moins de deux montées dans l'année écoulée : ``INSUFFICIENT``."""
    last = date(2002, 6, 30)
    for climbs in ([], [make_climb(last)]):
        result = references(climbs, last)
        assert isinstance(result, Unavailable)
        assert result.state is AscentState.INSUFFICIENT
        assert "2" in result.reason


def test_r5_inclusive_quartiles() -> None:
    """R5 : FC 130, 140, 150, 160 : 145, 140 et 155 (la méthode « exclusive »
    donnerait 135 et 160)."""
    last = date(2002, 6, 30)
    climbs = [
        make_climb(last - timedelta(days=k), hr_bpm=h)
        for k, h in enumerate((130.0, 140.0, 150.0, 160.0))
    ]
    refs = references(climbs, last)
    assert isinstance(refs, References)
    assert (refs.hr_bpm, refs.hr_low_bpm, refs.hr_high_bpm) == (145.0, 140.0, 155.0)


# L'étage 1 (§ 7) : T1 à T12.

FIRST = {"rel": 1e-6, "abs": 1e-9}
SUMMARY = {"rel": 1e-4, "abs": 1e-9}

T1_TABLE = {
    "coef": (
        1.9084259310600151,
        0.04969926617252392,
        -0.015494988412671482,
        -0.13869160395538335,
    ),
    "se": (
        0.9511351735662662,
        0.05579754871484149,
        0.10127271399076752,
        0.05897600274693657,
    ),
    "df": (3.84181382245474, 4.732829580446465, 4.877521781389615, 5.466062233303568),
    "low": (
        -0.7757887543005668,
        -0.09620279031256541,
        -0.2778033327947651,
        -0.2864875735551461,
    ),
    "high": (
        4.5926406164205975,
        0.19560132265761326,
        0.2468133559694221,
        0.009104365644379414,
    ),
}


def _approx(value: float, tolerance: dict[str, float]) -> object:
    return pytest.approx(value, rel=tolerance["rel"], abs=tolerance["abs"])


def structure_of(tables: Tables, last_day: date | None = None) -> Structure:
    climbs = select_climbs(tables).climbs
    refs = references(climbs, last_day or max(c.day for c in climbs))
    assert isinstance(refs, References)
    result = fit_structure(climbs, refs)
    assert isinstance(result, Structure), result
    return result


def world_e_structure() -> Structure:
    return structure_of(world_e_tables(), WORLD_E_LAST_DAY)


def test_t1_world_e_first_step() -> None:
    """T1 : le premier temps du monde E (§ 12.2)."""
    s = world_e_structure()
    assert (s.n_multi, s.n_multi_climbs) == (12, 28)
    assert s.estimated == (True, True, True, True)
    for k in range(4):
        assert s.coef[k] == _approx(T1_TABLE["coef"][k], FIRST)
        assert math.sqrt(s.cov[k][k]) == _approx(T1_TABLE["se"][k], FIRST)
        df = s.dfs[k]
        assert df is not None
        assert df == _approx(T1_TABLE["df"][k], FIRST)
        interval = s.intervals[k]
        assert interval is not None
        assert interval.low == _approx(T1_TABLE["low"][k], FIRST)
        assert interval.high == _approx(T1_TABLE["high"][k], FIRST)
    assert s.s2_e == _approx(0.013939261444925542, FIRST)
    assert s.vif_beta == _approx(1.3408488880835978, FIRST)
    assert s.vif_g == _approx(1.3719381633742764, FIRST)
    assert s.states == ()
    assert s.altitude is AscentState.INSUFFICIENT


def test_t2_world_e_second_step() -> None:
    """T2 : le second temps du monde E (§ 12.2)."""
    s = world_e_structure()
    assert s.sigma_u2 == pytest.approx(0.0, abs=1e-9)
    assert s.sigma_u_at_zero is True
    assert s.level_at_zero is False
    assert s.phi_identified is True
    assert s.phi_at_bound is False
    assert s.level_process_variance == pytest.approx(0.00183411774304536, rel=1e-3)
    assert s.phi_days == pytest.approx(38.0748571718154, rel=1e-3)
    assert s.gamma[0] == _approx(-0.14668223378408718, SUMMARY)
    assert s.gamma[1] == _approx(-0.07675514746263926, SUMMARY)
    assert math.sqrt(s.gamma_cov[0][0]) == _approx(0.08281113859581643, SUMMARY)
    assert math.sqrt(s.gamma_cov[1][1]) == _approx(0.05643853533437115, SUMMARY)


def test_t3_world_e_summaries() -> None:
    """T3 : quatre résumés du monde E (§ 12.2)."""
    s = world_e_structure()
    found = {summary.activity_ref: summary for summary in s.summaries}
    assert len(s.summaries) == 16
    for ref, n, value, variance in (
        ("e01", 3, -1.74268087228, 0.004646420482),
        ("e03", 1, -1.66094414178, 0.013939261445),
        ("e09", 1, -1.857279786018, 0.013939261445),
        ("e16", 2, -1.668337964061, 0.006969630722),
    ):
        assert found[ref].n_climbs == n
        assert found[ref].value == _approx(value, SUMMARY)
        assert found[ref].variance == _approx(variance, SUMMARY)
    assert found["e16"].devices == (("garmin", 2),)


def test_t4_the_exact_world() -> None:
    """T4 : le monde exact, β, ``g``, λ, ``rho`` retrouvés à ``1e-9`` près, quels que
    soient les décalages ; l'erreur type de λ est nulle : ``altitude is None``."""
    for seed in (7, 8):
        s = structure_of(exact_world(spread_offsets(14, seed)))
        assert s.estimated == (True, True, True, True)
        assert s.coef == pytest.approx(EXACT_COEF, abs=1e-9)
        assert s.altitude is None


def test_t5_centering_protects_beta() -> None:
    """T5 : des décalages liés à la FC moyenne de la sortie (``s_j = 3·x̄_j``) ne
    changent pas β."""
    plain = exact_world(spread_offsets(14))
    x_bar: dict[str, list[float]] = {}
    for c in select_climbs(plain).climbs:
        x_bar.setdefault(c.activity_ref, []).append(math.log(c.hr_bpm / EXACT_REF_HR))
    means = [statistics.fmean(x_bar[f"x{j:02d}"]) for j in range(14)]
    tied = exact_world([math.log(0.17) + 3 * m for m in means])
    assert structure_of(tied).coef[0] == pytest.approx(EXACT_COEF[0], abs=1e-9)


def test_t6_a_single_climb_sortie_changes_no_coefficient() -> None:
    """T6 : une sortie à une montée ajoutée ne change ni ``coef``, ni ``s2_e``, ni
    ``n_multi``, ni ``dfs``, ni ``intervals`` ; elle ajoute un résumé."""
    tables = world_e_tables()
    base = world_e_structure()
    extra_day = date(2001, 5, 1)
    more = q2_tables(
        [*tables.activities, q2_activity("e99", at(extra_day, 9))],
        [*tables.climbs, ascent_climb("e99", extra_day, 0, hr_bpm=139.0)],
    )
    climbs = select_climbs(more).climbs
    result = fit_structure(climbs, base.references)
    assert isinstance(result, Structure)
    assert result.coef == pytest.approx(base.coef, rel=1e-12, abs=1e-15)
    assert result.s2_e == pytest.approx(base.s2_e, rel=1e-12)
    assert result.n_multi == base.n_multi
    assert result.dfs == pytest.approx(base.dfs, rel=1e-12)
    for a, b in zip(result.intervals, base.intervals, strict=True):
        assert a is not None
        assert b is not None
        assert (a.low, a.high) == pytest.approx((b.low, b.high), rel=1e-12, abs=1e-15)
    assert len(result.summaries) == len(base.summaries) + 1


@pytest.mark.parametrize(
    "intermediate",
    [lambda j, i: False, lambda j, i: j == 0 and i == 0],
    ids=["no-sortie-mixes", "one-sortie-mixes"],
)
def test_t7_a_column_carried_by_fewer_than_two_sorties(
    intermediate: Callable[[int, int], bool],
) -> None:
    """T7 : aucune sortie ne mêle les régimes, puis une seule : ``rho`` sort du plan,
    sans exception."""
    s = structure_of(
        exact_world(spread_offsets(14), noise=0.02, intermediate=intermediate)
    )
    assert s.estimated[3] is False
    assert s.coef[3] == 0.0
    assert all(s.cov[3][k] == 0.0 and s.cov[k][3] == 0.0 for k in range(4))
    assert s.intervals[3] is None
    assert s.dfs[3] is None
    assert s.estimated[:3] == (True, True, True)


def test_t7_ter_beta_not_estimated() -> None:
    """T7 ter : la même FC sur toutes les montées de chaque sortie, sauf une : β n'est
    pas estimé, ``INSUFFICIENT``, la raison nomme β, sans exception."""

    def heart(j: int, i: int, d_km: float) -> float:
        return 140.0 + 5.0 * i if j == 0 else 150.0

    climbs = select_climbs(
        exact_world(spread_offsets(14), noise=0.02, heart=heart)
    ).climbs
    refs = references(climbs, max(c.day for c in climbs))
    assert isinstance(refs, References)
    result = fit_structure(climbs, refs)
    assert isinstance(result, Unavailable)
    assert result.state is AscentState.INSUFFICIENT
    assert "β" in result.reason


def test_t8_nine_multi_climb_sorties() -> None:
    """T8 : neuf sorties à deux montées : ``INSUFFICIENT``, la raison nomme 9 et 10."""
    climbs = select_climbs(exact_world(spread_offsets(9), noise=0.02)).climbs
    refs = references(climbs, max(c.day for c in climbs))
    assert isinstance(refs, References)
    result = fit_structure(climbs, refs)
    assert isinstance(result, Unavailable)
    assert result.state is AscentState.INSUFFICIENT
    assert "9" in result.reason
    assert "10" in result.reason


def test_t9_not_separable() -> None:
    """T9 : dans chaque sortie, ``ln FC`` suit le D+ de près (corrélation intra
    ≥ 0,999, pas 1) : ``NOT_SEPARABLE`` dans ``states``."""

    def heart(j: int, i: int, d_km: float) -> float:
        jitter = 0.0005 * (((7 * i + 3 * j) % 5) - 2)
        return EXACT_REF_HR * math.exp(0.2 * d_km + 0.01 * j + jitter)

    tables = exact_world(spread_offsets(14), noise=0.02, heart=heart)
    for activity in tables.activities:
        own = [
            (math.log(c.hr_bpm), c.d_plus_km)
            for c in select_climbs(tables).climbs
            if c.activity_ref == activity.activity_ref
        ]
        if len(own) >= 3:
            assert statistics.correlation(*zip(*own, strict=True)) >= 0.999
    s = structure_of(tables)
    assert s.vif_beta is not None
    assert s.vif_beta > 10.0
    assert AscentState.NOT_SEPARABLE in s.states


def test_t9_bis_rank_deficient() -> None:
    """T9 bis : ``ln FC`` égal à ``0,2·D`` à une constante près dans chaque sortie (la
    FC telle que calculée, jamais arrondie) : ``Unavailable(NOT_SEPARABLE)``."""

    def heart(j: int, i: int, d_km: float) -> float:
        return EXACT_REF_HR * math.exp(0.2 * d_km + 0.01 * j)

    climbs = select_climbs(
        exact_world(spread_offsets(14), noise=0.02, heart=heart)
    ).climbs
    refs = references(climbs, max(c.day for c in climbs))
    assert isinstance(refs, References)
    result = fit_structure(climbs, refs)
    assert isinstance(result, Unavailable)
    assert result.state is AscentState.NOT_SEPARABLE


def test_t10_the_summary_identity() -> None:
    """T10 : chaque résumé du monde E recalculé depuis ses montées (``1e-12``)."""
    s = world_e_structure()
    refs = s.references
    beta, g, lam, rho = s.coef
    climbs = select_climbs(world_e_tables()).climbs
    for summary in s.summaries:
        own = [c for c in climbs if c.activity_ref == summary.activity_ref]
        r_bar = statistics.fmean(
            c.log_speed
            - (
                beta * math.log(c.hr_bpm / refs.hr_bpm)
                + g * c.d_plus_km
                + lam * c.altitude_km
                + rho * (1.0 if c.intermediate else 0.0)
            )
            for c in own
        )
        d_bar = statistics.fmean(c.d_plus_km for c in own)
        a_bar = statistics.fmean(c.altitude_km for c in own)
        expected = (
            r_bar
            - s.gamma[0] * (d_bar - refs.d_plus_km)
            - s.gamma[1] * (a_bar - refs.altitude_km)
            + g * refs.d_plus_km
            + lam * refs.altitude_km
        )
        assert summary.value == pytest.approx(expected, rel=1e-12, abs=1e-12)


def test_t11_the_borrowed_variance() -> None:
    """T11 : ``variance = sigma_u2 + s2_e / n_climbs``, sur le monde E
    (``sigma_u2 = 0``) et sur un monde où ``sigma_u2 > 0``."""
    noisy = structure_of(noisy_world())
    assert noisy.sigma_u2 > 0.0
    for s in (world_e_structure(), noisy):
        for summary in s.summaries:
            assert summary.variance == pytest.approx(
                s.sigma_u2 + s.s2_e / summary.n_climbs, rel=1e-12
            )


def test_t12_two_sorties_on_the_same_day() -> None:
    """T12 : deux sorties le même jour (« b » puis « a », « b » partie plus tôt) :
    deux résumés, triés par ``(day, activity_ref)``, « a » d'abord."""
    same = EXACT_FIRST + timedelta(days=3)
    days = [same, same, *(EXACT_FIRST + timedelta(days=7 * j) for j in range(2, 16))]
    refs = ["b", "a", *(f"x{j:02d}" for j in range(2, 16))]
    hours = [7, 14, *([9] * 14)]
    s = structure_of(noisy_world(days=days, refs=refs, hours=hours))
    first, second = s.summaries[0], s.summaries[1]
    assert (first.activity_ref, second.activity_ref) == ("a", "b")
    assert first.day == second.day == same


def noisy_world(**changes: Any) -> Tables:
    """Le monde exact à décalages dispersés, plus un bruit dans la sortie d'une graine
    fixe : ``sigma_u2 > 0``."""
    return exact_world(
        [math.log(0.17) + 2.0 * (o - math.log(0.17)) for o in spread_offsets(16, 3)],
        noise=0.03,
        **changes,
    )
