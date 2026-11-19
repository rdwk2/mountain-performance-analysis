"""Les essais de Q2 (AN3-3b, ``docs/decisions/0023``, § 9) : la liste des 24 essais,
Holm (C12), la p-valeur bornée (C11 bis), les bornes (C23), chaque sensibilité
vérifiée, S14, l'autocorrélation. Sur des mondes inventés (``small_world``), à
tirages réduits."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from fixtures.q2_world import at, q2_activity, q2_climb, small_world
from mountain_perf.analyse.athlete import Periods
from mountain_perf.analyse.inference import clusters, linear
from mountain_perf.analyse.inference.linear import student_pvalue
from mountain_perf.analyse.inference.readings import bonferroni_level, holm
from mountain_perf.analyse.inference.reml import three_component_cov
from mountain_perf.analyse.q2 import trials
from mountain_perf.analyse.q2.data import q2_data
from mountain_perf.analyse.q2.model import (
    Measure,
    build_design,
    date_effect_at,
    fit_direct,
    model_spec,
    stage_one,
)
from mountain_perf.analyse.q2.parameters import Q2_PARAMETER_SPECS
from mountain_perf.analyse.q2.power import PowerLevel
from mountain_perf.analyse.q2.trials import (
    NOT_DONE,
    TRIALS,
    Q2Estimation,
    TrialRow,
    bounded_pvalue,
    imputed_bounds,
    q2_trials,
)
from mountain_perf.analyse.tables import Tables
from mountain_perf.schemas import ParameterSet
from mountain_perf.schemas.processed import ClimbFlag, ClimbRegime

LONG = ClimbRegime.LONG_CLIMB
EXACT = 1e-12
PERIODS = Periods(date(2025, 4, 1), date(2025, 5, 31))


def _params(**values: float) -> ParameterSet:
    return ParameterSet(
        Q2_PARAMETER_SPECS, {"power_draws": 3.0, "bootstrap_draws": 9.0, **values}
    )


def _row(estimation: Q2Estimation, name: str) -> TrialRow:
    (row,) = [r for r in estimation.rows if r.essai == name]
    return row


# --- la liste -----------------------------------------------------------------------


def test_the_24_trials_in_their_fixed_order() -> None:
    assert [(t.index, t.name) for t in TRIALS] == list(
        enumerate(
            [
                "P",
                "S-MP-cotes",
                "S-MP-ski",
                "S-MS-longues",
                "S-MS-cotes",
                "S-MS-ski",
                "S1",
                "S2",
                "S3",
                "S4",
                "S5",
                "S8",
                "S9",
                "S10",
                "S11",
                "S12",
                "S13",
                "S14",
                "S15",
                "S16",
                "S17",
                "S18",
                "S19",
                "S20",
            ]
        )
    )
    assert [t.family.value for t in TRIALS[:6]] == ["principale"] + ["secondaire"] * 5
    assert all(t.family.value == "sensibilite" for t in TRIALS[6:])
    assert [t.measure.value for t in TRIALS[1:6]] == ["M-P", "M-P", "M-S", "M-S", "M-S"]
    assert NOT_DONE == (
        "S6 : non estimable (saison fraîche trop courte)",
        "S7 : retirée",
    )


def test_c12_holm_over_the_five_secondaries() -> None:
    """C12 : seule la première est rejetée (le ski non estimable à p = 1)."""
    assert holm([0.004, 0.02, 0.03, 0.2, 1.0], 0.05) == (
        True,
        False,
        False,
        False,
        False,
    )


def test_c11_bis_the_bounded_pvalue() -> None:
    """C11 bis : ``max(0,01 ; 2·min(1/4 ; 3/4)) = 0,5`` ; ``k̂`` contenant 0 → 1."""
    assert bounded_pvalue(0.01, (-1.0, 2.0, 3.0, 4.0), False) == 0.5
    assert bounded_pvalue(0.01, (-1.0, 2.0, 3.0, 4.0), True) == 1.0
    assert bounded_pvalue(0.7, (1.0, 2.0, 3.0, 4.0), False) == 0.7


def test_c23_the_bounds() -> None:
    """C23 : ``s = √(1,44 + 0,81) = 1,5`` ; basse ``+s`` en découverte, ``−s`` ensuite ;
    puis ``b`` aux deux bornes, à ``V = 2·I`` : ``−33/700`` et ``27/700``."""
    low, high = imputed_bounds(
        [0.2, -0.1, 0.0], ["decouverte", "suite", "avant"], 1.44, 0.81
    )
    assert low == pytest.approx([1.7, -1.6, None], rel=EXACT)
    assert high == pytest.approx([-1.3, 1.4, None], rel=EXACT)
    t = [0.0, 5.0, 10.0, 20.0, 25.0, 30.0]
    x = [[1.0, ti] for ti in t]
    v = [[2.0 * (i == j) for j in range(6)] for i in range(6)]
    b_low, _ = date_effect_at(x, [0.0, 1.7, 0.0, 0.0, -1.6, 0.0], v, 1)
    b_high, _ = date_effect_at(x, [0.0, -1.3, 0.0, 0.0, 1.4, 0.0], v, 1)
    assert b_low == pytest.approx(-33 / 700, rel=1e-10)
    assert b_high == pytest.approx(27 / 700, rel=1e-10)
    assert b_low < b_high


# --- les mondes ---------------------------------------------------------------------


def _with_gaps(tables: Tables) -> Tables:
    """Une montée sur cinq sans FC sans décalage, une sur sept sans seconde moitié."""
    climbs = []
    for k, climb in enumerate(tables.climbs):
        changes: dict[str, Any] = {}
        if k % 5 == 0:
            changes.update(
                unlagged_moving_heart_rate_bpm=None,
                unlagged_moving_heart_rate_coverage=0.0,
            )
        if k % 7 == 0:
            changes.update(
                lagged_second_half_heart_rate_bpm=None,
                lagged_second_half_heart_rate_coverage=0.0,
            )
        climbs.append(dataclasses.replace(climb, **changes))
    return dataclasses.replace(tables, climbs=tuple(climbs))


def _with_missing_days(tables: Tables, count: int) -> Tables:
    """``count`` journées de découverte dont la seule montée longue est marquée
    (un manque)."""
    activities, climbs = list(tables.activities), list(tables.climbs)
    used = {a.start_time.date() for a in activities}
    free = [
        day
        for day in (date(2025, 4, 1) + timedelta(days=k) for k in range(61))
        if day not in used
    ]
    for i, day in enumerate(free[:count]):
        when = at(day, 18)
        ref = f"x{i:03d}"
        activities.append(q2_activity(ref, when))
        climbs.append(q2_climb(ref, when, flags=[ClimbFlag.SPIKE], gain_m=700.0))
    return dataclasses.replace(
        tables, activities=tuple(activities), climbs=tuple(climbs)
    )


@pytest.fixture(scope="module")
def with_periods() -> tuple[Q2Estimation, Any]:
    """Le monde à périodes, à FC de variantes manquantes et à journées de manque :
    tous les retraits jouent."""
    params = _params()
    tables = _with_missing_days(_with_gaps(small_world(1)), 12)
    data = q2_data(tables, PERIODS, params)
    return q2_trials(data, params, {}), data


@pytest.fixture(scope="module")
def without_periods() -> tuple[Q2Estimation, Any]:
    """Le monde sans période, toutes ses montées stables, au budget de 5 : le 5ᵉ
    retrait ne joue pas."""
    params = _params(min_residual_df=5)
    tables = small_world(1)
    tables = dataclasses.replace(
        tables,
        climbs=tuple(dataclasses.replace(c, stable=True) for c in tables.climbs),
    )
    data = q2_data(tables, None, params)
    return q2_trials(data, params, {}), data


# --- le principal et les secondaires -------------------------------------------------


def test_the_principal_is_bounded_at_its_level(
    with_periods: tuple[Q2Estimation, Any],
) -> None:
    estimation, _ = with_periods
    principal = _row(estimation, "P")
    assert principal.statut == "estime"
    assert principal.niveau == 0.95
    assert principal.k_contient_zero is not None
    assert principal.forme_fc == "lineaire"
    assert principal.mention is not None
    assert "puissance non calculée" in principal.mention
    assert principal.p_valeur is None
    assert principal.exploratoire is True


def test_the_short_climbs_use_bonferroni_and_say_the_heart_rate(
    with_periods: tuple[Q2Estimation, Any],
) -> None:
    """Contre-épreuve 22 : le niveau des côtes est ``bonferroni_level(0,05 ; 5)``."""
    estimation, _ = with_periods
    for name in ("S-MP-cotes", "S-MS-cotes", "S-MS-longues"):
        assert _row(estimation, name).niveau == bonferroni_level(0.05, 5)
    mention = _row(estimation, "S-MP-cotes").mention
    assert mention is not None
    assert "FC dépendante de la VAM sur ces durées" in mention


def test_a_calibrated_level_comes_from_the_power_result() -> None:
    params = _params()
    data = q2_data(small_world(1), None, params)
    power = {
        "long_climb": PowerLevel(True, True, 0.02),
        "short_climb": PowerLevel(True, True, None),
    }
    estimation = q2_trials(data, params, power)
    assert _row(estimation, "P").niveau == pytest.approx(0.98, rel=EXACT)
    cotes = _row(estimation, "S-MP-cotes")
    assert cotes.niveau == bonferroni_level(0.05, 5)
    assert cotes.mention is not None
    assert "valeur critique non calibrable" in cotes.mention
    assert _row(estimation, "S18").niveau == pytest.approx(0.98, rel=EXACT)


def test_pvalues_and_holm(with_periods: tuple[Q2Estimation, Any]) -> None:
    """Q-37 (a), (b) : la p-valeur bornée est au moins la directe ; la directe de M-S
    est celle de Student ; le ski non estimable vaut 1 ; Holm sur les cinq."""
    estimation, data = with_periods
    rows = estimation.rows
    assert rows[2].statut == "non_estimable"
    assert rows[2].p_valeur == 1.0
    assert rows[5].p_valeur == 1.0
    params = _params()
    spec = model_spec(data.days[LONG], Measure.MS, LONG, params)
    units = spec.units()
    direct = fit_direct(
        build_design(units, spec, stage_one(units, Measure.MS), params), params
    )
    assert rows[3].p_valeur == pytest.approx(
        student_pvalue(direct.b, direct.se, direct.df), rel=1e-9
    )
    p = [rows[i].p_valeur for i in range(1, 6)]
    assert all(v is not None for v in p)
    assert tuple(rows[i].holm_rejet for i in range(1, 6)) == holm(
        [v for v in p if v is not None], 0.05
    )
    assert all(r.holm_rejet is None for r in rows[6:])
    assert rows[2].n_journees == 0


def test_kappa_is_recalled_on_the_ms_rows(
    with_periods: tuple[Q2Estimation, Any],
) -> None:
    estimation, _ = with_periods
    assert _row(estimation, "S-MS-longues").kappa == _row(estimation, "S19").kappa
    assert _row(estimation, "S-MS-cotes").kappa == _row(estimation, "S20").kappa
    assert _row(estimation, "S19").intervalle_kappa is not None


# --- les sensibilités ---------------------------------------------------------------


def test_s1_s2_s16_keep_the_sample_and_count_removed_climbs(
    with_periods: tuple[Q2Estimation, Any],
) -> None:
    estimation, _ = with_periods
    principal = _row(estimation, "P")
    for name in ("S1", "S2", "S16"):
        row = _row(estimation, name)
        assert row.statut == "estime"
        assert row.n_journees == principal.n_journees
        assert row.variante_effective is True
        assert row.n_montees == (principal.n_montees or 0) - row.montees_retirees
    assert _row(estimation, "S1").montees_retirees > 0
    assert _row(estimation, "S2").montees_retirees > 0
    assert _row(estimation, "S16").montees_retirees == 0


def test_s3_takes_the_other_form(
    with_periods: tuple[Q2Estimation, Any],
    without_periods: tuple[Q2Estimation, Any],
) -> None:
    assert _row(with_periods[0], "S3").forme_fc == "spline"
    assert _row(without_periods[0], "P").forme_fc == "spline"
    assert _row(without_periods[0], "S3").forme_fc == "lineaire"


def test_s4_and_an_ineffective_variant(
    with_periods: tuple[Q2Estimation, Any],
    without_periods: tuple[Q2Estimation, Any],
) -> None:
    """S4 change l'échantillon là où des montées sont instables ; toutes stables, la
    ligne dit « identique au principal »."""
    s4 = _row(with_periods[0], "S4")
    assert s4.variante_effective is True
    assert (s4.n_montees or 0) < (_row(with_periods[0], "P").n_montees or 0)
    same = _row(without_periods[0], "S4")
    assert same.variante_effective is False
    assert same.mention == "identique au principal"


def test_s5_and_s9_need_the_periods(
    with_periods: tuple[Q2Estimation, Any],
    without_periods: tuple[Q2Estimation, Any],
) -> None:
    for name in ("S5", "S9"):
        row = _row(without_periods[0], name)
        assert (row.statut, row.motif) == ("non_faite", "sans [periodes]")
    principal = _row(with_periods[0], "P").n_journees or 0
    assert 0 < (_row(with_periods[0], "S5").n_journees or 0) < principal
    assert 0 < (_row(with_periods[0], "S9").n_journees or 0) <= principal


def test_s8_s13_s15_s17_change_their_columns(
    with_periods: tuple[Q2Estimation, Any],
) -> None:
    estimation, _ = with_periods
    p = _row(estimation, "P").p or 0
    assert _row(estimation, "S8").p == p - 2
    assert _row(estimation, "S13").p == p + 1
    assert (_row(estimation, "S15").p or 0) < p
    assert _row(estimation, "S17").p == p - 1
    assert all(
        _row(estimation, n).variante_effective for n in ("S8", "S13", "S15", "S17")
    )


def test_s10_in_both_cases_of_the_fifth_withdrawal(
    with_periods: tuple[Q2Estimation, Any],
    without_periods: tuple[Q2Estimation, Any],
) -> None:
    """Le 5ᵉ retrait a joué : S10 remet ``e_s`` (une colonne de plus) ; il n'a pas
    joué : S10 l'ôte (une de moins), toutes les journées."""
    played = with_periods[0]
    assert "5" in (_row(played, "P").retraits or "")
    assert _row(played, "S10").p == (_row(played, "P").p or 0) + 1
    other = without_periods[0]
    assert "5" not in (_row(other, "P").retraits or "")
    assert (_row(other, "S10").p or 0) <= (_row(other, "P").p or 0) - 1


def test_s11_whitens_with_the_principal_covariance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Any] = []
    original = linear.whiten

    def spy(X: Any, y: Any, V: Any) -> Any:  # noqa: N803
        seen.append(V)
        return original(X, y, V)

    monkeypatch.setattr(trials, "whiten", spy)
    params = _params()
    data = q2_data(small_world(1), None, params)
    estimation = q2_trials(data, params, {})
    assert _row(estimation, "S11").statut == "estime"
    principal = estimation.principal
    assert principal is not None
    reml = principal.direct.reml
    design = principal.design
    expected = three_component_cov(
        list(design.t), list(design.d), reml.tau2, reml.s2u, reml.phi
    ).tolist()
    assert seen == [expected]


def test_s12_counts_its_removed_climbs(with_periods: tuple[Q2Estimation, Any]) -> None:
    row = _row(with_periods[0], "S12")
    assert row.variante_effective is True
    assert row.montees_retirees == 0


def test_s18_repeats_the_inverse_of_the_principal(
    with_periods: tuple[Q2Estimation, Any],
) -> None:
    estimation, _ = with_periods
    principal, s18 = _row(estimation, "P"), _row(estimation, "S18")
    assert s18.inverse_fraction == principal.inverse_fraction
    assert s18.intervalle_inverse_fraction == principal.intervalle_inverse_fraction
    assert s18.niveau == principal.niveau
    assert s18.estimation_fraction is None
    assert s18.intervalle_fraction is None
    assert s18.k_contient_zero == principal.k_contient_zero
    assert s18.phrase is not None
    assert "(régression inverse)" in s18.phrase or s18.phrase.startswith(
        ("les données", "la régression inverse")
    )


def test_s14_is_not_done_under_ten_months(
    with_periods: tuple[Q2Estimation, Any],
) -> None:
    row = _row(with_periods[0], "S14")
    assert row.statut == "non_faite"
    assert row.motif is not None
    assert "sous s14_min_months = 10" in row.motif


def test_s14_estimated_with_integer_month_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sur un monde de plus de douze mois, les grappes sont des entiers 0, 1, 2…
    dans l'ordre des mois (la fonction refuse des chaînes)."""
    seen: list[Any] = []
    original = clusters.wild_cluster_interval

    def spy(X: Any, y: Any, clusters: Any, *rest: Any) -> Any:  # noqa: N803
        seen.append(list(clusters))
        return original(X, y, clusters, *rest)

    monkeypatch.setattr(trials, "wild_cluster_interval", spy)
    params = _params()
    data = q2_data(small_world(4, span=420), PERIODS, params)
    estimation = q2_trials(data, params, {})
    assert _row(estimation, "S14").statut == "estime"
    (labels,) = seen
    assert all(isinstance(label, int) for label in labels)
    assert labels == sorted(labels)
    assert sorted(set(labels)) == list(range(max(labels) + 1))
    assert max(labels) + 1 >= 12
    assert estimation.bounds["long_climb"]["statut"] == "non declenchees"  # type: ignore[index]


# --- les bornes, l'autocorrélation --------------------------------------------------


def test_the_bounds_are_triggered_when_the_shares_differ(
    with_periods: tuple[Q2Estimation, Any],
) -> None:
    bound = with_periods[0].bounds["long_climb"]
    assert isinstance(bound, dict)
    assert bound["statut"] == "declenchees"
    assert bound["journees_imputees"] == 12
    parts = bound["parts"]
    assert parts["suite"] == 0.0
    assert parts["decouverte"] > 0.3
    assert math.isfinite(bound["b_basse_fraction"])
    assert math.isfinite(bound["b_haute_fraction"])


def test_without_periods_there_are_no_bounds(
    without_periods: tuple[Q2Estimation, Any],
) -> None:
    assert without_periods[0].bounds["long_climb"] == {"statut": "sans période"}


def test_the_autocorrelation_classes(with_periods: tuple[Q2Estimation, Any]) -> None:
    rows = [r for r in with_periods[0].autocorrelation if r[0] == "long_climb"]
    assert [(r[2], r[3]) for r in rows] == [
        (1, 7),
        (8, 14),
        (15, 28),
        (29, 56),
        (57, None),
    ]
    assert all(r[1] == "M-P" for r in rows)


# --- les bornes de bout en bout (correctifs de la PR #52, points 1 et 2) ------------

BOUNDS_DAYS = {
    "autre": date(2025, 4, 9),
    "colonne": date(2025, 4, 23),
    "sans_groupe": date(2025, 5, 7),
    "sans_altitude": date(2025, 5, 14),
    "sans_fc": date(2025, 5, 21),
    "suite": date(2025, 7, 9),
    "avant": date(2025, 3, 1),
}
"""Les journées de manque du monde des bornes : deux exclues à l'étape 5 (l'une
« autre », l'autre dans un groupe qui a sa colonne), trois sans groupe (exclues aux
étapes 1 à 3 ; l'une sans altitude, une autre sans FC), une dans la suite, une
``avant``."""


def _lone_climb(ref: str, when: Any, lat: float, **changes: Any) -> Any:
    """Une montée longue à un départ que nulle autre ne partage (``lat``, longitude
    9,0), de gain 400 m par défaut ; ``changes`` remplace d'autres champs."""
    fields: dict[str, Any] = {
        "gain_m": 400.0,
        "h": 146.0,
        "grade": 0.2,
        "start_latitude_deg": lat,
        "start_longitude_deg": 9.0,
        "end_latitude_deg": lat + 0.03,
        "end_longitude_deg": 9.0,
        "preceding_ascent_m": 120.0,
        "preceding_descent_m": 80.0,
        **changes,
    }
    return q2_climb(ref, when, **fields)


def _bounds_world() -> Tables:
    """``small_world`` (longues seules) et les journées de :data:`BOUNDS_DAYS` ; les
    deux journées exclues à l'étape 5 ont un statut de FC de repos ``provisional``.
    La journée dans un groupe à colonne a sa montée sur le parcours qui n'est pas celui
    de la première journée (ce dernier est la référence : aucune journée de
    l'échantillon n'est « autre »)."""
    from fixtures.q2_world import ROUTES, WORLD_START, q2_day_row
    from mountain_perf.schemas.days import RestingHrStatus

    tables = small_world(3, regimes=(LONG,), days=26, span=150)
    used = {a.start_time.date() for a in tables.activities}
    assert not used & set(BOUNDS_DAYS.values())
    first = min(used)
    route = ROUTES[1 - (first - WORLD_START).days % 2]
    activities, climbs = list(tables.activities), list(tables.climbs)
    for name, day in BOUNDS_DAYS.items():
        when = at(day, 8)
        ref = f"b-{name}"
        activities.append(q2_activity(ref, when))
        if name == "autre":
            climbs += [
                _lone_climb(ref, when, 47.1),
                _lone_climb(ref, when, 47.2, offset_s=4000.0, gain_m=380.0),
            ]
        elif name == "colonne":
            climbs.append(
                q2_climb(
                    ref,
                    when,
                    gain_m=750.0,
                    h=141.0,
                    grade=0.18,
                    start_latitude_deg=route[0] + 0.0001,
                    start_longitude_deg=route[1],
                    end_latitude_deg=route[0] + 0.0301,
                    end_longitude_deg=route[1],
                    preceding_ascent_m=200.0,
                    preceding_descent_m=150.0,
                )
            )
        elif name == "sans_altitude":
            climbs.append(_lone_climb(ref, when, 47.4, moving_mean_elevation_m=None))
        elif name == "sans_fc":
            climbs.append(_lone_climb(ref, when, 47.5, h=None))
        else:
            lat = {"sans_groupe": 47.3, "suite": 47.6, "avant": 47.7}[name]
            climbs.append(_lone_climb(ref, when, lat, flags=[ClimbFlag.SPIKE]))
    provisional = {BOUNDS_DAYS["autre"], BOUNDS_DAYS["colonne"]}
    days = [
        q2_day_row(
            row.day, resting=row.resting_hr_bpm, status=RestingHrStatus.PROVISIONAL
        )
        if row.day in provisional
        else row
        for row in tables.days
    ]
    return dataclasses.replace(
        tables,
        activities=tuple(activities),
        climbs=tuple(climbs),
        days=tuple(days),
    )


def _day_means(
    climbs: Sequence[tuple[float, float, float, float, float, float]],
) -> Any:
    """Les moyennes ``(ln gain, pente, altitude, D+, D−, heure − 12)`` de montées
    données par ``(gain, pente, altitude, D+, D−, heure)``."""
    count = len(climbs)
    return (
        sum(math.log(c[0]) for c in climbs) / count,
        sum(c[1] for c in climbs) / count,
        sum(c[2] for c in climbs) / count,
        sum(c[3] for c in climbs) / count,
        sum(c[4] for c in climbs) / count,
        sum(c[5] for c in climbs) / count - 12.0,
    )


def test_the_bounds_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """Correctifs de la PR #52, points 1 et 2 : sur un monde à ``[periodes]`` où
    l'étape 5 s'applique, la GLS des bornes (un espion garde sa matrice, sa réponse et
    sa covariance) reçoit, pour chaque journée imputée : ses indicatrices de parcours
    (0 partout pour une journée « autre » exclue à l'étape 5, 1 dans sa colonne pour
    une journée d'un groupe qui en a une, la moyenne de sa période pour une journée
    sans groupe) ; la valeur ajustée ``± s`` (``s = √(τ̂² + s²_u)`` ; ``+`` en
    découverte et ``−`` dans la suite pour la borne basse, l'inverse pour la haute) ;
    une altitude ou une ``h̄``
    absente à la moyenne de sa période, la spline aux nœuds du principal ; les
    grandeurs des montées exclues, écrites en dur. La journée ``avant`` n'est ni
    imputée ni comptée. Les deux pentes rendues sont celles de la GLS sur les matrices
    de l'espion. Contre : la moyenne de période donnée à une journée « autre » exclue
    à l'étape 5 (P2a), les bornes échangées (P2b), une grandeur d'une montée exclue
    perdue (P2c)."""
    from mountain_perf.analyse.inference.linear import fraction_per_year, gls
    from mountain_perf.analyse.q2 import model
    from mountain_perf.analyse.q2.data import Period
    from mountain_perf.analyse.q2.model import heart_rate_columns

    calls: list[tuple[list[list[float]], list[float], list[list[float]], int]] = []
    original = model.date_effect_at

    def spy(X: Any, y: Any, V: Any, date_column: int) -> Any:  # noqa: N803
        calls.append(([list(r) for r in X], list(y), [list(r) for r in V], date_column))
        return original(X, y, V, date_column)

    monkeypatch.setattr(trials, "date_effect_at", spy)
    params = _params(min_residual_df=10)
    data = q2_data(_bounds_world(), PERIODS, params)
    estimation = q2_trials(data, params, {})
    principal = estimation.principal
    assert principal is not None
    spec, design = principal.spec, principal.design
    # Les conditions du monde : aucun retrait (l'étape 5 s'applique, la spline est au
    # modèle) ; la journée « autre » sans groupe, l'autre dans un groupe à colonne.
    assert spec.withdrawals == ()
    assert "fc_1" in design.columns
    groups = dict(zip([d.day for d in spec.days], spec.groups, strict=True))
    assert groups[BOUNDS_DAYS["autre"]] is None
    column_group = groups[BOUNDS_DAYS["colonne"]]
    assert column_group is not None
    assert column_group in spec.route_columns
    route_names = [c for c in design.columns if c.startswith("parcours_")]
    bound = estimation.bounds["long_climb"]
    assert isinstance(bound, dict)
    assert bound["statut"] == "declenchees"
    assert len(calls) == 2
    (x_low, y_low, v_low, k), (x_high, y_high, v_high, k_high) = calls
    assert k == k_high == design.columns.index("date")
    assert x_low == x_high

    columns = list(design.columns)
    origin = design.days[0]
    coef = [float(c) for c in principal.direct.reml.fit.coef.tolist()]
    sigma = math.sqrt(principal.direct.reml.tau2 + principal.direct.reml.s2u)

    def kept(period: Period) -> list[int]:
        return [i for i, u in enumerate(principal.units) if u.day.period is period]

    def mean_of(period: Period, name: str) -> float:
        rows = kept(period)
        return sum(design.X[i][columns.index(name)] for i in rows) / len(rows)

    def mean_h(period: Period) -> float:
        rows = kept(period)
        return sum(design.h_bar[i] for i in rows) / len(rows)

    disc, after = Period.DISCOVERY, Period.AFTER
    # Les grandeurs des montées, écrites en dur (``_lone_climb``, ``_bounds_world``) :
    # (gain, pente, altitude moyenne en mouvement, D+, D−, heure locale de départ).
    lone = (400.0, 0.2, 1200.0, 120.0, 80.0, 8.0)
    second = (380.0, 0.2, 1190.0, 120.0, 80.0, 8.0 + 4000.0 / 3600.0)
    expected_means = {
        "autre": (_day_means([lone, second]), 146.0, disc),
        "colonne": (
            _day_means([(750.0, 0.18, 1375.0, 200.0, 150.0, 8.0)]),
            141.0,
            disc,
        ),
        "sans_groupe": (_day_means([lone]), 146.0, disc),
        "sans_altitude": (_day_means([lone]), 146.0, disc),
        "sans_fc": (_day_means([lone]), None, disc),
        "suite": (_day_means([lone]), 146.0, after),
    }
    assert design.knots is not None
    rows_low = {round(row[k]): (row, y) for row, y in zip(x_low, y_low, strict=True)}
    rows_high = {round(row[k]): y for row, y in zip(x_high, y_high, strict=True)}
    assert len(x_low) == design.n + len(expected_means)
    assert bound["journees_imputees"] == len(expected_means)
    expected_low_y: dict[int, float] = {}
    expected_high_y: dict[int, float] = {}
    for name, (means, h, period) in expected_means.items():
        day = BOUNDS_DAYS[name]
        t = (day - origin).days
        row, low = rows_low[t]
        log_gain, grade, altitude, d_plus, d_minus, hour = means
        if name == "sans_altitude":
            altitude = mean_of(period, "altitude")
        heart = mean_h(period) if h is None else h
        fc_1, fc_2 = heart_rate_columns([heart], design.knots)[0]
        angle = 2.0 * math.pi * day.timetuple().tm_yday / 365.25
        values = {
            "constante": 1.0,
            "date": float(t),
            "saison_sin": math.sin(angle),
            "saison_cos": math.cos(angle),
            "fc_1": fc_1,
            "fc_2": fc_2,
            "log_gain": log_gain,
            "pente": grade,
            "altitude": altitude,
            "d_plus_avant": d_plus,
            "d_moins_avant": d_minus,
            "heure": hour,
            "e_s": mean_of(period, "e_s"),
        }
        for column in route_names:
            if name == "autre":
                values[column] = 0.0
            elif name == "colonne":
                values[column] = float(column == f"parcours_{column_group}")
            else:
                values[column] = mean_of(period, column)
        expected = [values[c] for c in columns]
        # 1 : les indicatrices de parcours.
        for column in route_names:
            got = row[columns.index(column)]
            if name in ("autre", "colonne"):
                assert got == values[column], (name, column)
            else:
                assert got == pytest.approx(values[column], rel=EXACT), (name, column)
        # 3 et 4 : les covariables (une absente à la moyenne de sa période), la
        # spline aux nœuds du principal, les grandeurs des montées exclues.
        for column, value in zip(columns, expected, strict=True):
            assert row[columns.index(column)] == pytest.approx(
                value, rel=1e-10, abs=1e-12
            ), (name, column)
        # 2 : la réponse imputée, la valeur ajustée ± s.
        fitted = sum(x * b for x, b in zip(expected, coef, strict=True))
        sign = 1.0 if period is disc else -1.0
        expected_low_y[t] = fitted + sign * sigma
        expected_high_y[t] = fitted - sign * sigma
        assert low == pytest.approx(expected_low_y[t], rel=1e-10), name
        assert rows_high[t] == pytest.approx(expected_high_y[t], rel=1e-10), name
    # 5 : la journée ``avant`` n'est ni imputée ni comptée dans les parts.
    assert (BOUNDS_DAYS["avant"] - origin).days not in rows_low
    n_disc, n_after = len(kept(disc)), len(kept(after))
    assert bound["parts"] == {
        "decouverte": pytest.approx(5 / (n_disc + 5), rel=EXACT),
        "suite": pytest.approx(1 / (n_after + 1), rel=EXACT),
    }
    # 6 : les deux pentes rendues : la GLS sur les matrices gardées par l'espion, à
    # la réponse attendue de chaque borne (les journées gardées à leur ȳ).
    for i, t_kept in enumerate(design.t):
        expected_low_y[round(t_kept)] = design.y[i]
        expected_high_y[round(t_kept)] = design.y[i]
    response_low = [expected_low_y[round(r[k])] for r in x_low]
    response_high = [expected_high_y[round(r[k])] for r in x_high]
    assert y_low == pytest.approx(response_low, rel=1e-10)
    b_low = float(gls(x_low, response_low, v_low).coef[k])
    b_high = float(gls(x_high, response_high, v_high).coef[k])
    assert bound["b_basse_fraction"] == pytest.approx(
        fraction_per_year(b_low), rel=1e-9
    )
    assert bound["b_haute_fraction"] == pytest.approx(
        fraction_per_year(b_high), rel=1e-9
    )
