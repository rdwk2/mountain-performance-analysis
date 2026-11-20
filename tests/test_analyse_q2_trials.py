"""Les essais de Q2 (AN3-3b, ``docs/decisions/0023``, § 9) : la liste des 24 essais,
Holm (C12), la p-valeur bornée (C11 bis), les bornes (C23), chaque sensibilité
vérifiée, S14, l'autocorrélation. Sur des mondes inventés (``small_world``), à
tirages réduits."""

from __future__ import annotations

import copy
import dataclasses
import math
import random
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any, cast

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from fixtures.q2_world import at, q2_activity, q2_climb, small_world
from mountain_perf.analyse.athlete import Periods
from mountain_perf.analyse.inference import clusters, linear
from mountain_perf.analyse.inference.base import Interval, child_rng
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


@dataclasses.dataclass(frozen=True)
class Run:
    """Une estimation de Q2 sur un monde de test : les tables, les données, les 24
    lignes, et, par sensibilité, les matrices que ``fit_direct`` a reçues pendant
    qu'elle se calculait (``""`` : hors des sensibilités)."""

    tables: Tables
    data: Any
    estimation: Q2Estimation
    designs: dict[str, list[Any]]


def _recorded_trials(
    tables: Tables,
    periods: Periods | None,
    params: ParameterSet,
    patch: pytest.MonkeyPatch,
) -> Run:
    """``q2_trials`` sous un espion de ``fit_direct`` qui range chaque matrice sous le
    nom de la sensibilité en cours."""
    from mountain_perf.analyse.q2 import model

    designs: dict[str, list[Any]] = {}
    current = [""]
    original = model.fit_direct

    def fit_spy(design: Any, parameters: Any, coefficient: str = "date") -> Any:
        designs.setdefault(current[0], []).append(design)
        return original(design, parameters, coefficient)

    patch.setattr(trials, "fit_direct", fit_spy)
    table = cast(dict[str, Any], trials.SENSITIVITIES)
    for name, function in list(table.items()):

        def wrapped(
            t: Any, c: Any, p: Any, _name: str = name, _f: Any = function
        ) -> Any:
            current[0] = _name
            try:
                return _f(t, c, p)
            finally:
                current[0] = ""

        patch.setitem(table, name, wrapped)
    data = q2_data(tables, periods, params)
    return Run(tables, data, q2_trials(data, params, {}), designs)


@pytest.fixture(scope="module")
def periods_run() -> Run:
    """Le monde à périodes, à FC de variantes manquantes et à journées de manque :
    tous les retraits jouent."""
    tables = _with_missing_days(_with_gaps(small_world(1)), 12)
    with pytest.MonkeyPatch.context() as patch:
        return _recorded_trials(tables, PERIODS, _params(), patch)


@pytest.fixture(scope="module")
def with_periods(periods_run: Run) -> tuple[Q2Estimation, Any]:
    """Les essais et les données de :func:`periods_run`."""
    return periods_run.estimation, periods_run.data


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


@dataclasses.dataclass(frozen=True)
class TwelveMonths:
    """Les essais d'un monde de plus de douze mois, les grappes et une copie du
    générateur que ``wild_cluster_interval`` a reçus."""

    estimation: Q2Estimation
    labels: list[list[Any]]
    generators: list[Any]


@pytest.fixture(scope="module")
def twelve_months() -> TwelveMonths:
    """S14 estimée : un monde de plus de douze mois, un espion de
    ``wild_cluster_interval``."""
    labels: list[list[Any]] = []
    generators: list[Any] = []
    original = clusters.wild_cluster_interval

    def spy(X: Any, y: Any, clusters: Any, *rest: Any) -> Any:  # noqa: N803
        labels.append(list(clusters))
        generators.append(copy.deepcopy(rest[-1]))
        return original(X, y, clusters, *rest)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(trials, "wild_cluster_interval", spy)
        params = _params()
        data = q2_data(small_world(4, span=420), PERIODS, params)
        estimation = q2_trials(data, params, {})
    return TwelveMonths(estimation, labels, generators)


def test_s14_estimated_with_integer_month_labels(twelve_months: TwelveMonths) -> None:
    """Sur un monde de plus de douze mois, les grappes sont des entiers 0, 1, 2…
    dans l'ordre des mois (la fonction refuse des chaînes)."""
    estimation = twelve_months.estimation
    assert _row(estimation, "S14").statut == "estime"
    (labels,) = twelve_months.labels
    assert all(isinstance(label, int) for label in labels)
    assert labels == sorted(labels)
    assert sorted(set(labels)) == list(range(max(labels) + 1))
    assert max(labels) + 1 >= 12
    assert estimation.bounds["long_climb"]["statut"] == "non declenchees"  # type: ignore[index]


def test_s14_draws_under_its_own_key(twelve_months: TwelveMonths) -> None:
    """Correctifs de la PR #52, point 3 bis.9 : le générateur que reçoit
    ``wild_cluster_interval`` est celui de la clé du § 9.1, ``child_rng(20261115, 2,
    17, 1)`` (S14 est l'essai d'indice 17, usage 1), comparé par son premier tirage ;
    l'estimation de S14 est écrite. Contre une autre clé de générateur (P5j-2)."""
    (generator,) = twelve_months.generators
    assert generator.random() == child_rng(20261115, 2, 17, 1).random()
    assert _row(twelve_months.estimation, "S14").estimation_fraction is not None


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
« autre », dont une montée est à ``h − r ≤ 0`` ; l'autre dans un groupe qui a sa
colonne, avec une montée exclue le même jour), trois sans groupe (exclues aux étapes
1 à 3, d'une seule montée ; l'une sans altitude, une autre sans FC), une dans la
suite, une ``avant``."""


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
    l'échantillon n'est « autre »), et une montée exclue (un pic) le même jour ; la
    seconde montée de la journée « autre » a une FC de 48 bpm, sous sa normale de
    repos (50) : hors de la réserve de M-S (correctifs de la PR #52, lot 2)."""
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
                _lone_climb(ref, when, 47.2, offset_s=4000.0, gain_m=380.0, h=48.0),
            ]
        elif name == "colonne":
            climbs.append(
                _lone_climb(ref, when, 47.8, offset_s=5000.0, flags=[ClimbFlag.SPIKE])
            )
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
    perdue (P2c).

    Lot 2 des correctifs : la variance connue de chaque journée imputée, relue sur la
    diagonale de la covariance passée à la GLS, vaut ``s²_ε / n_s`` (``s²_ε`` : la
    variance de l'étage 1), ``n_s`` compté ici (les montées de sa journée des étapes
    1 à 4 et ses montées exclues : 2 pour les deux journées exclues à l'étape 5, 1
    pour les autres) (point 3.2, contre P6d) ;
    un D+ avant et un D− avant absents (retirés à la main des données : une table
    valide ne les laisse pas manquer) prennent la moyenne de leur période (point 3.3,
    contre P6e) ; les covariables de la journée « autre » sont les moyennes de ses
    deux montées, dont celle hors de la réserve de M-S (point 3.5, contre P6g)."""
    from mountain_perf.analyse.inference.linear import fraction_per_year, gls
    from mountain_perf.analyse.q2 import model
    from mountain_perf.analyse.q2.data import Period, Q2Motif
    from mountain_perf.analyse.q2.model import heart_rate_columns

    calls: list[tuple[list[list[float]], list[float], list[list[float]], int]] = []
    original = model.date_effect_at

    def spy(X: Any, y: Any, V: Any, date_column: int) -> Any:  # noqa: N803
        calls.append(([list(r) for r in X], list(y), [list(r) for r in V], date_column))
        return original(X, y, V, date_column)

    monkeypatch.setattr(trials, "date_effect_at", spy)
    params = _params(min_residual_df=10)
    data = q2_data(_bounds_world(), PERIODS, params)
    # Point 3.3 : un D+ avant absent (journée sans groupe) et un D− avant absent
    # (journée sans FC), posés à la main dans les données.
    missing_before = {
        BOUNDS_DAYS["sans_groupe"]: "preceding_ascent_m",
        BOUNDS_DAYS["sans_fc"]: "preceding_descent_m",
    }
    data = dataclasses.replace(
        data,
        excluded=tuple(
            dataclasses.replace(c, **{missing_before[c.day]: cast(Any, None)})
            if c.day in missing_before
            else c
            for c in data.excluded
        ),
    )
    estimation = q2_trials(data, params, {})
    principal = estimation.principal
    assert principal is not None
    spec, design = principal.spec, principal.design
    # Les conditions du monde : aucun retrait (l'étape 5 s'applique, la spline est au
    # modèle) ; la journée « autre » sans groupe, l'autre dans un groupe à colonne ;
    # la seconde montée de la journée « autre » hors de la réserve de M-S.
    (other_day,) = [d for d in spec.days if d.day == BOUNDS_DAYS["autre"]]
    assert other_day.step5 is not None
    assert other_day.reserve == (None, Q2Motif.MS_RESERVE)
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
        "autre": (_day_means([lone, second]), (146.0 + 48.0) / 2, disc),
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
    positions = {round(row[k]): i for i, row in enumerate(x_low)}
    reml = principal.direct.reml
    climb_counts = {
        "autre": 2,
        "colonne": 2,
        "sans_groupe": 1,
        "sans_altitude": 1,
        "sans_fc": 1,
        "suite": 1,
    }
    expected_low_y: dict[int, float] = {}
    expected_high_y: dict[int, float] = {}
    for name, (means, h, period) in expected_means.items():
        day = BOUNDS_DAYS[name]
        t = (day - origin).days
        row, low = rows_low[t]
        log_gain, grade, altitude, d_plus, d_minus, hour = means
        if name == "sans_altitude":
            altitude = mean_of(period, "altitude")
        if name == "sans_groupe":
            d_plus = mean_of(period, "d_plus_avant")
            assert d_plus > 0.0
        if name == "sans_fc":
            d_minus = mean_of(period, "d_moins_avant")
            assert d_minus > 0.0
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
        # Lot 2, point 3.2 : ``d_s = s²_ε / n_s``, sur la diagonale de ``V``
        # (``V_ss = d_s + τ̂² + s²_u``), la même aux deux bornes.
        i = positions[t]
        for v in (v_low, v_high):
            assert v[i][i] - reml.tau2 - reml.s2u == pytest.approx(
                principal.sigma2 / climb_counts[name], rel=1e-9
            ), name
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


# --- les tests de la relecture et du balayage (correctifs de la PR #52) -------------

SUITE_ONLY = Periods(date(2024, 1, 1), date(2024, 1, 31))
"""Une découverte avant toute activité : toutes les journées sont de la suite."""
ROUTE_C = (44.0, 6.0)
"""Le départ d'un troisième parcours, de deux journées dans :func:`_plain_world`."""
ROUTE_C_DAYS = (date(2025, 9, 15), date(2025, 9, 17))
"""Les deux journées du troisième parcours ; la seconde est exclue à l'étape 5."""


def _offset(ref: str) -> int:
    return int(ref[1:])


def _plain_world() -> Tables:
    """``small_world(1)`` retouché : la FC des montées longues tirée sans lien avec la
    VAM (l'intervalle de ``k̂`` contient 0) ; les montées longues des journées du
    parcours qui n'est pas celui de la première journée toutes instables, les autres
    stables ; une montée longue sur neuf sans VAM « en mouvement ou indéterminée », les
    autres à la VAM ; deux journées d'un troisième parcours, dont la seconde a une FC
    de repos ``provisional``."""
    from fixtures.q2_world import q2_day_row
    from mountain_perf.schemas.days import RestingHrStatus

    tables = small_world(1)
    rnd = random.Random(7)
    longs = [c for c in tables.climbs if c.regime is LONG]
    first = min(_offset(c.activity_ref) for c in longs)
    climbs = []
    index = 0
    for climb in tables.climbs:
        if climb.regime is LONG:
            unstable = _offset(climb.activity_ref) % 2 != first % 2
            climb = dataclasses.replace(
                climb,
                lagged_moving_heart_rate_bpm=rnd.uniform(130.0, 160.0),
                stable=not unstable,
                moving_or_undetermined_vertical_speed_ms=None
                if index % 9 == 0
                else climb.vertical_speed_ms,
            )
            index += 1
        climbs.append(climb)
    activities = list(tables.activities)
    for k, day in enumerate(ROUTE_C_DAYS):
        when = at(day, 7)
        ref = f"c{k}"
        activities.append(q2_activity(ref, when))
        climbs.append(
            q2_climb(
                ref,
                when,
                gain_m=750.0,
                h=140.0 + 5.0 * k,
                start_latitude_deg=ROUTE_C[0],
                start_longitude_deg=ROUTE_C[1],
                end_latitude_deg=ROUTE_C[0] + 0.03,
                end_longitude_deg=ROUTE_C[1],
            )
        )
    days = [
        q2_day_row(
            row.day, resting=row.resting_hr_bpm, status=RestingHrStatus.PROVISIONAL
        )
        if row.day == ROUTE_C_DAYS[1]
        else row
        for row in tables.days
    ]
    return dataclasses.replace(
        tables, activities=tuple(activities), climbs=tuple(climbs), days=tuple(days)
    )


@pytest.fixture(scope="module")
def plain_run() -> Run:
    """Le monde de :func:`_plain_world`, toutes ses journées dans la suite, au budget
    de 5 : aucun retrait ne joue, l'étape 5 s'applique."""
    with pytest.MonkeyPatch.context() as patch:
        return _recorded_trials(
            _plain_world(), SUITE_ONLY, _params(min_residual_df=5), patch
        )


@pytest.fixture(scope="module")
def rich_run() -> Run:
    """``rich_world(2)`` à ``[periodes]`` ; chaque bootstrap de ``b_inv`` rend un
    tirage retiré de plus (sur dix : plus de 1 %)."""
    from fixtures.q2_world import rich_world
    from mountain_perf.analyse.q2 import model

    original = model.inverse_bootstrap

    def one_more_removed(*args: Any, **kwargs: Any) -> Any:
        return dataclasses.replace(original(*args, **kwargs), removed=1)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(trials, "inverse_bootstrap", one_more_removed)
        return _recorded_trials(rich_world(2), PERIODS, _params(), patch)


@pytest.fixture(scope="module")
def short_only() -> Q2Estimation:
    """Des côtes seules, une montée par journée : le principal n'a aucune journée,
    l'étage 1 des côtes n'a aucun degré de liberté."""
    tables = small_world(2, regimes=(ClimbRegime.SHORT_CLIMB,))
    seen: set[str] = set()
    climbs = []
    for climb in tables.climbs:
        if climb.activity_ref not in seen:
            seen.add(climb.activity_ref)
            climbs.append(climb)
    params = _params()
    data = q2_data(dataclasses.replace(tables, climbs=tuple(climbs)), None, params)
    return q2_trials(data, params, {})


def _days(design: Any) -> list[date]:
    return list(design.days)


def _in_discovery(day: date) -> bool:
    return date(2025, 4, 1) <= day <= date(2025, 5, 31)


# --- 3.4 : l'identité des sensibilités ---------------------------------------------


def test_s5_drops_exactly_the_discovery(periods_run: Run) -> None:
    """Point 3.4 : l'échantillon de S5 n'a aucune journée de la découverte (du 1er
    avril au 31 mai 2025) et a toutes les autres journées du principal. Contre S5 qui
    retire la suite au lieu de la découverte (P3f)."""
    principal = _days(periods_run.designs[""][0])
    (s5,) = periods_run.designs["S5"]
    assert any(_in_discovery(d) for d in principal)
    assert _days(s5) == [d for d in principal if not _in_discovery(d)]


def test_s1_and_s2_count_the_climbs_without_their_heart_rate(periods_run: Run) -> None:
    """Point 3.4 : ``montees_retirees`` de S1 est le nombre de montées longues gardées
    du monde sans FC sans décalage, celui de S2 sans FC de la seconde moitié (les
    deux nombres diffèrent sur ce monde). Contre S1 et S2 échangées (P3g)."""
    kept = [
        c
        for c in periods_run.tables.climbs
        if c.regime is LONG and ClimbFlag.SPIKE not in c.flags
    ]
    unlagged = sum(1 for c in kept if c.unlagged_moving_heart_rate_bpm is None)
    second = sum(1 for c in kept if c.lagged_second_half_heart_rate_bpm is None)
    assert unlagged != second
    estimation = periods_run.estimation
    assert _row(estimation, "S1").montees_retirees == unlagged
    assert _row(estimation, "S2").montees_retirees == second


def test_s9_keeps_the_days_inside_the_common_support(periods_run: Run) -> None:
    """Point 3.4 : l'échantillon de S9 est fait des journées du principal dont la FC
    moyenne est dans l'intersection des étendues de la découverte et de la suite,
    calculées ici sur les montées ; il est strictement plus petit que celui du
    principal. Contre l'union des supports au lieu de leur intersection (P3h)."""
    principal = periods_run.estimation.principal
    assert principal is not None
    means = {
        u.day.day: sum(c.h for c in u.climbs) / len(u.climbs) for u in principal.units
    }
    discovery = [h for d, h in means.items() if _in_discovery(d)]
    after = [h for d, h in means.items() if d > date(2025, 5, 31)]
    low, high = max(min(discovery), min(after)), min(max(discovery), max(after))
    expected = [d for d in sorted(means) if low <= means[d] <= high]
    (s9,) = periods_run.designs["S9"]
    assert _days(s9) == expected
    assert len(expected) < len(means)


# --- 3.5 : les mentions écrites par le brief ------------------------------------------


def _mentions(row: TrialRow) -> list[str]:
    return [] if row.mention is None else row.mention.split(" ; ")


def test_the_three_mentions_word_for_word(rich_run: Run, periods_run: Run) -> None:
    """Point 3.5 (§ 9.1) : « plus de 1 % de tirages retirés » (un tirage retiré sur
    dix au principal), « optimiste » (sous 40 journées ; le monde riche en a plus),
    « dépend de l'intensité choisie » (``κ`` hors de 1 à S19 et à M-S des longues),
    chacune lue sur une ligne qui la porte. Contre une mention changée d'un mot
    (P3i)."""
    rich = rich_run.estimation
    principal = _row(rich, "P")
    assert principal.tirages_retires == 1
    assert "plus de 1 % de tirages retirés" in _mentions(principal)
    assert "optimiste" not in _mentions(principal)
    assert "optimiste" in _mentions(_row(periods_run.estimation, "P"))
    assert _row(rich, "S19").mention == "dépend de l'intensité choisie"
    assert "dépend de l'intensité choisie" in _mentions(_row(rich, "S-MS-longues"))


# --- 3.9 : des branches jamais exécutées ----------------------------------------------


def test_without_a_principal_the_sensitivities_are_not_done(
    short_only: Q2Estimation,
) -> None:
    """Point 3.9 : le principal non estimé, chaque sensibilité qui en part (S1 à S18)
    est « non faite », motif « principal non estimé », et il n'y a pas de principal
    pour la figure. Contre un principal non estimé qui laisserait les sensibilités
    se calculer, ou une figure tirée d'un principal absent."""
    assert short_only.principal is None
    assert short_only.rows[0].statut == "non_estimable"
    for row in short_only.rows[6:22]:
        assert (row.statut, row.motif) == ("non_faite", "principal non estimé"), (
            row.essai
        )


def test_a_dropped_route_indicator_is_said(plain_run: Run) -> None:
    """Point 3.9, dernier tiret (§ 9.2) : S4 garde les montées stables ; toutes les
    journées du parcours qui a la colonne ``parcours_1`` sortent, l'indicatrice est
    retirée et la ligne le dit. Contre une indicatrice sans journée gardée (une
    colonne nulle) ou retirée sans le dire."""
    row = _row(plain_run.estimation, "S4")
    assert row.statut == "estime"
    assert row.mention == "indicatrice de parcours retirée : parcours_1"
    (s4,) = plain_run.designs["S4"]
    assert "parcours_1" not in s4.columns
    assert "parcours_1" in plain_run.designs[""][0].columns


# --- 3 bis.7 : le principal borné -----------------------------------------------------


def _percent(value: float) -> str:
    return format(100 * value, ".1f").replace(".", ",")


def test_the_bounded_principal_and_its_sentence(rich_run: Run) -> None:
    """Point 3 bis.7 : sur le monde riche à ``[periodes]``, l'intervalle de l'inverse
    du principal est écrit ; « établi », sa phrase est bâtie ici sur les bornes
    extrêmes des deux intervalles ; sa mention ne porte pas celle des côtes. Contre
    la mention des côtes posée sur le principal (P5h-1)."""
    row = _row(rich_run.estimation, "P")
    assert row.intervalle_inverse_fraction is not None
    assert row.intervalle_fraction is not None
    assert row.lecture == "établi"
    low = min(row.intervalle_fraction[0], row.intervalle_inverse_fraction[0])
    high = max(row.intervalle_fraction[1], row.intervalle_inverse_fraction[1])
    assert row.phrase == (
        f"la tendance est comprise entre {_percent(low)} et {_percent(high)} %/an "
        "(régressions directe et inverse) ; elle se lit comme un écart entre la "
        "période de découverte et la suite, saison non séparée ; exploratoire"
    )
    assert "FC dépendante de la VAM sur ces durées" not in _mentions(row)


def test_the_bounded_pvalue_counts_the_draws_at_zero() -> None:
    """Point 3 bis.7 : ``2·min(1/4 ; 3/4) = 0,5`` sur des tirages sous 1 en valeur
    absolue. Contre la part des tirages ``≥ 1`` au lieu de ``≥ 0`` (P5h-2)."""
    assert bounded_pvalue(0.01, (-0.001, 0.0005, 0.001, 0.002), False) == 0.5


def test_s18_undecided_when_k_contains_zero(plain_run: Run) -> None:
    """Point 3 bis.7 : sur un monde où la FC n'a pas de lien avec la VAM, l'intervalle
    de ``k̂`` contient 0 et S18 dit « les données ne tranchent pas »."""
    principal, s18 = _row(plain_run.estimation, "P"), _row(plain_run.estimation, "S18")
    assert principal.k_contient_zero is True
    assert s18.k_contient_zero is True
    assert (s18.lecture, s18.phrase) == ("non tranché", "les données ne tranchent pas")


def test_no_useful_effect_names_its_delta() -> None:
    """Point 3 bis.7 : « absence d'effet utile » à ``delta = 0,025`` dit « à un effet
    de 2,5 %/an ». Contre un ``delta`` écrit en dur à 5 %."""
    from mountain_perf.analyse.q2.model import bounded_reading

    reading, sentence = bounded_reading(Interval(-0.01, 0.01), None, None, 0.025, False)
    assert reading.value == "absence d'effet utile"
    assert (
        sentence == "la régression directe ne laisse pas place à un effet de 2,5 %/an"
    )


# --- 3 bis.9 : les sensibilités restantes ---------------------------------------------


def test_s17_has_no_heart_rate_column(periods_run: Run) -> None:
    """Point 3 bis.9 : la matrice que S17 ajuste (espion de ``fit_direct``) n'a ni
    ``fc``, ni ``fc_1``, ni ``fc_2``, et celle du principal en a une. Contre S17 qui
    garde la colonne de FC (P5j-1)."""
    (s17,) = periods_run.designs["S17"]
    assert not {"fc", "fc_1", "fc_2"} & set(s17.columns)
    assert {"fc", "fc_1", "fc_2"} & set(periods_run.designs[""][0].columns)


def test_s12_counts_the_climbs_without_moving_speed(plain_run: Run) -> None:
    """Point 3 bis.9 : une montée longue sur neuf n'a pas de VAM « en mouvement ou
    indéterminée » : S12 en retire et en compte autant (la journée exclue à l'étape 5
    n'est pas de l'échantillon et a sa VAM)."""
    expected = sum(
        1
        for c in plain_run.tables.climbs
        if c.regime is LONG and c.moving_or_undetermined_vertical_speed_ms is None
    )
    assert expected > 0
    row = _row(plain_run.estimation, "S12")
    assert row.montees_retirees == expected
    assert row.variante_effective is True


def test_s12_equal_to_the_speed_everywhere_is_not_effective(plain_run: Run) -> None:
    """Point 3 bis.9 : la VAM « en mouvement ou indéterminée » égale à la VAM partout,
    S12 ne change rien : ``variante_effective`` faux, rien de retiré."""
    from mountain_perf.analyse.q2.model import Unit

    principal = plain_run.estimation.principal
    assert principal is not None
    same = dataclasses.replace(
        principal,
        units=tuple(
            Unit(
                u.day,
                tuple(dataclasses.replace(c, y_s12=c.y) for c in u.climbs),
                u.y,
            )
            for u in principal.units
        ),
    )
    context = trials._Context(plain_run.data, _params(min_residual_df=5), {}, 1)
    (trial,) = [t for t in TRIALS if t.name == "S12"]
    row = trials.SENSITIVITIES["S12"](trial, context, same)
    assert row.variante_effective is False
    assert row.montees_retirees == 0


def test_s10_gives_its_column_to_a_group_other_at_the_principal(plain_run: Run) -> None:
    """Point 3 bis.9 (Q-50 (a)) : le troisième parcours n'a qu'une journée dans
    l'échantillon du principal (l'autre est exclue à l'étape 5) : « autre », aucune
    indicatrice à 1 ; S10 rend la journée exclue, le groupe a deux journées et sa
    colonne, où ses deux journées valent 1, et elles seules."""
    principal = plain_run.designs[""][0]
    routes = [c for c in principal.columns if c.startswith("parcours_")]
    first = _days(principal).index(ROUTE_C_DAYS[0])
    assert ROUTE_C_DAYS[1] not in _days(principal)
    assert all(principal.X[first][principal.columns.index(c)] == 0.0 for c in routes)
    (s10,) = plain_run.designs["S10"]
    days = _days(s10)
    rows = [s10.X[days.index(d)] for d in ROUTE_C_DAYS]
    ones = [
        c
        for c in s10.columns
        if c.startswith("parcours_")
        and all(r[s10.columns.index(c)] == 1.0 for r in rows)
    ]
    assert len(ones) == 1
    k = s10.columns.index(ones[0])
    assert [d for d, r in zip(days, s10.X, strict=True) if r[k] == 1.0] == list(
        ROUTE_C_DAYS
    )


def test_s11_keeps_the_withdrawals_and_s19_its_covariance(
    periods_run: Run, rich_run: Run
) -> None:
    """Point 3 bis.9 : S11 rapporte les retraits du principal (les cinq, sur ce monde) ;
    S19 rapporte ``τ̂²``, ``s²_u`` et ``φ̂`` de son REML."""
    assert _row(periods_run.estimation, "S11").retraits == "1-2-3-4-5"
    s19 = _row(rich_run.estimation, "S19")
    assert s19.statut == "estime"
    assert s19.tau2 is not None
    assert s19.s2u is not None
    assert s19.phi is not None


# --- 3 bis.10 : les lignes non estimées -----------------------------------------------


def test_the_ski_rows_without_ski(with_periods: tuple[Q2Estimation, Any]) -> None:
    """Point 3 bis.10 : sans ski, ``S-MP-ski`` et ``S-MS-ski`` sont « non estimable »,
    motif, niveau de Bonferroni (0,99), retraits et ``p`` écrits ici. Contre un motif
    vidé (P5k-1) ou un niveau vidé (P5k-2)."""
    estimation, _ = with_periods
    for name, p in (("S-MP-ski", 7), ("S-MS-ski", 6)):
        row = _row(estimation, name)
        assert row.statut == "non_estimable"
        assert row.motif == f"n − p = {-p}, sous min_estimable_df = 10"
        assert row.niveau == pytest.approx(0.99, rel=EXACT)
        assert row.retraits == "1-2-3-4-5"
        assert (row.n_journees, row.p) == (0, p)


def test_short_climbs_of_one_climb_per_day_are_not_estimable(
    short_only: Q2Estimation,
) -> None:
    """Point 3 bis.10 : chaque journée de côtes n'a qu'une montée, l'étage 1 lève :
    ``S-MP-cotes`` et ``S-MS-cotes`` « non estimable », motif, niveau, ``n``, ``p``,
    retraits écrits ici (30 journées ; après les cinq retraits, 9 colonnes en M-P et
    8 en M-S). Contre un motif vidé (P5k-1) ou un niveau vidé (P5k-2)."""
    for name, q, p in (("S-MP-cotes", 6, 9), ("S-MS-cotes", 5, 8)):
        row = _row(short_only, name)
        assert row.statut == "non_estimable"
        assert row.motif == f"étage 1 : N − J − q = {-q}"
        assert row.niveau == pytest.approx(0.99, rel=EXACT)
        assert (row.n_journees, row.p, row.retraits) == (30, p, "1-2-3-4-5")


def test_s9_not_done_without_a_discovery_day(plain_run: Run) -> None:
    """Point 3 bis.10 : la découverte n'a aucune journée au principal : S9 « non
    faite », motif « une période sans journée »."""
    row = _row(plain_run.estimation, "S9")
    assert (row.statut, row.motif) == ("non_faite", "une période sans journée")


# --- 3 bis.13 : les bornes, en plus du point 2 ----------------------------------------


def _bounds_world_without_column_after() -> Tables:
    """:func:`_bounds_world` sans les journées de la suite du parcours qui a sa
    colonne : dans la suite, aucune journée gardée n'a cette colonne."""
    from fixtures.q2_world import WORLD_START

    tables = _bounds_world()
    first = min(
        a.start_time.date() for a in tables.activities if a.activity_ref[0] == "w"
    )
    column_route = 1 - (first - WORLD_START).days % 2
    dropped = {
        a.activity_ref
        for a in tables.activities
        if a.activity_ref[0] == "w"
        and a.start_time.date() > date(2025, 5, 31)
        and (a.start_time.date() - WORLD_START).days % 2 == column_route
    }
    assert dropped
    return dataclasses.replace(
        tables,
        activities=tuple(a for a in tables.activities if a.activity_ref not in dropped),
        climbs=tuple(c for c in tables.climbs if c.activity_ref not in dropped),
    )


def test_the_bounds_impute_e_s_and_a_column_absent_from_a_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Point 3 bis.13 : la colonne ``e_s`` de chaque journée imputée (aucune n'a
    ``e_s``) vaut la moyenne de sa période parmi les journées gardées ; la journée
    sans groupe de la suite, où aucune journée gardée n'a la colonne du parcours,
    vaut 0 dans cette colonne. Contre une moyenne prise hors de la période, ou une
    case absente."""
    from mountain_perf.analyse.q2 import model

    calls: list[list[list[float]]] = []
    original = model.date_effect_at

    def spy(X: Any, y: Any, V: Any, date_column: int) -> Any:  # noqa: N803
        calls.append([list(r) for r in X])
        return original(X, y, V, date_column)

    monkeypatch.setattr(trials, "date_effect_at", spy)
    params = _params(min_residual_df=5, min_estimable_df=3)
    data = q2_data(_bounds_world_without_column_after(), PERIODS, params)
    estimation = q2_trials(data, params, {})
    principal = estimation.principal
    assert principal is not None
    design = principal.design
    columns = list(design.columns)
    assert "e_s" in columns
    bound = estimation.bounds["long_climb"]
    assert isinstance(bound, dict)
    assert bound["statut"] == "declenchees"
    groups = dict(
        zip([d.day for d in principal.spec.days], principal.spec.groups, strict=True)
    )
    column = f"parcours_{groups[BOUNDS_DAYS['colonne']]}"
    assert column in columns
    after = [i for i, u in enumerate(principal.units) if u.day.day > date(2025, 5, 31)]
    assert after
    assert all(design.X[i][columns.index(column)] == 0.0 for i in after)
    assert len(calls) == 2
    origin = design.days[0]
    rows = {round(r[columns.index("date")]): r for r in calls[0]}
    for name in ("autre", "colonne", "sans_groupe", "suite"):
        day = BOUNDS_DAYS[name]
        in_period = [
            i
            for i, u in enumerate(principal.units)
            if (u.day.day > date(2025, 5, 31)) == (name == "suite")
            and u.day.day >= date(2025, 4, 1)
        ]
        e_s = sum(design.X[i][columns.index("e_s")] for i in in_period) / len(in_period)
        row = rows[(day - origin).days]
        assert row[columns.index("e_s")] == pytest.approx(e_s, rel=EXACT), name
    assert rows[(BOUNDS_DAYS["suite"] - origin).days][columns.index(column)] == 0.0


# --- correctifs de la PR #52, lot 2 ---------------------------------------------------

RICH_STEP5_DAY = date(2025, 4, 16)
"""La journée de ``rich_world`` exclue à l'étape 5 en découverte, dans le groupe de la
première journée (la référence : sans colonne au modèle)."""


def _bounds_rows(
    monkeypatch: pytest.MonkeyPatch,
    data: Any,
    fitted: Any,
    params: ParameterSet,
) -> tuple[dict[str, object], list[list[float]]]:
    """Les bornes de ``fitted`` et la matrice de leur première GLS (un espion de
    ``date_effect_at``)."""
    from mountain_perf.analyse.q2 import model

    calls: list[list[list[float]]] = []
    original = model.date_effect_at

    def spy(X: Any, y: Any, V: Any, date_column: int) -> Any:  # noqa: N803
        calls.append([list(r) for r in X])
        return original(X, y, V, date_column)

    monkeypatch.setattr(trials, "date_effect_at", spy)
    bound = trials.bounds(trials._Context(data, params, {}, 1), fitted)
    return bound, (calls[0] if calls else [])


def test_the_rich_run_world_does_what_it_must(rich_run: Run) -> None:
    """Correctifs de la PR #52, lot 2, point 4 : les prémisses des tests qui lisent
    ``rich_run`` : aucun retrait au principal M-P (la spline de la FC au modèle), au
    moins une journée exclue à l'étape 5 (elle s'applique), ``e_s`` au modèle. Contre
    ``rich_run`` construit sur un monde plus petit, où le 3ᵉ retrait joue (P6h)."""
    principal = rich_run.estimation.principal
    assert principal is not None
    spec = principal.spec
    assert spec.withdrawals == ()
    assert spec.step5_applied
    sample = {u.day.day for u in principal.units}
    step5 = [d.day for d in spec.days if d.step5 is not None]
    assert step5
    assert not set(step5) & sample
    assert "e_s" in principal.design.columns
    assert {"fc_1", "fc_2"} <= set(principal.design.columns)


def test_a_step5_day_of_a_group_without_column(
    monkeypatch: pytest.MonkeyPatch, rich_run: Run
) -> None:
    """Correctifs de la PR #52, lot 2, point 3.1 (le quatrième cas du point 1) : sur
    ``rich_world(2)`` à ``[periodes]``, la journée du 2025-04-16, exclue à l'étape 5,
    est du groupe 0, le groupe de la première journée, sans colonne au modèle (aucune
    journée de l'échantillon n'est « autre », Q-49 (h)) ; aux bornes (déclenchées ici
    par ``bounds_trigger = 0,05`` : les parts sont 1/8 et 1/33), sa ligne imputée vaut
    0 dans chaque colonne de parcours, et la journée exclue à l'étape 5 de la suite,
    du groupe 1, vaut 1 dans la sienne. Contre une journée d'un groupe sans colonne
    qui reçoit 1 dans la première colonne de parcours (P6c)."""
    principal = rich_run.estimation.principal
    assert principal is not None
    spec, design = principal.spec, principal.design
    (day,) = [d for d in spec.days if d.day == RICH_STEP5_DAY]
    assert spec.step5_applied
    assert day.step5 is not None
    assert RICH_STEP5_DAY not in {u.day.day for u in principal.units}
    assert spec.group_of(RICH_STEP5_DAY) == 0
    assert 0 not in spec.route_columns
    routes = [c for c in design.columns if c.startswith("parcours_")]
    assert routes == ["parcours_1"]
    bound, matrix = _bounds_rows(
        monkeypatch, rich_run.data, principal, _params(bounds_trigger=0.05)
    )
    assert bound["statut"] == "declenchees"
    assert bound["journees_imputees"] == 2
    k = design.columns.index("date")
    origin = min(design.days[0], RICH_STEP5_DAY)
    rows = {round(r[k]): r for r in matrix}
    row = rows[(RICH_STEP5_DAY - origin).days]
    assert [row[design.columns.index(c)] for c in routes] == [0.0]
    after = rows[(date(2025, 9, 10) - origin).days]
    assert after[design.columns.index("parcours_1")] == 1.0


def _linear_heart_rate_world() -> Tables:
    """``rich_world(2, days=38)`` (le 3ᵉ retrait joue : la FC linéaire au modèle) et
    trois journées de manque au début de la découverte, d'une montée longue chacune,
    sans groupe : la première sans FC, les deux autres marquées d'un pic."""
    from fixtures.q2_world import rich_world

    tables = rich_world(2, days=38)
    used = {a.start_time.date() for a in tables.activities}
    added = (date(2025, 4, 1), date(2025, 4, 2), date(2025, 4, 3))
    assert not used & set(added)
    activities, climbs = list(tables.activities), list(tables.climbs)
    for i, day in enumerate(added):
        when = at(day, 7)
        ref = f"m{i}"
        activities.append(q2_activity(ref, when))
        if i == 0:
            climbs.append(q2_climb(ref, when, gain_m=700.0, h=None))
        else:
            climbs.append(q2_climb(ref, when, gain_m=700.0, flags=[ClimbFlag.SPIKE]))
    return dataclasses.replace(
        tables, activities=tuple(activities), climbs=tuple(climbs)
    )


def test_a_missing_h_bar_under_the_linear_heart_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Correctifs de la PR #52, lot 2, point 3.4 : sur un monde où le 3ᵉ retrait joue
    (la colonne ``fc`` linéaire au modèle, pas la spline), à ``[periodes]`` et bornes
    déclenchées, la journée imputée du 2025-04-01, sans FC, a dans sa colonne ``fc``
    la moyenne de sa période parmi les journées gardées : la moyenne, sur les
    journées de la découverte de l'échantillon, de la moyenne des FC de leurs
    montées, faite ici. Contre la ``h̄`` absente laissée absente, prise à 0 (P6f)."""
    from mountain_perf.analyse.q2.data import Period

    params = _params()
    data = q2_data(_linear_heart_rate_world(), PERIODS, params)
    spec = model_spec(data.days[LONG], Measure.MP, LONG, params)
    assert 3 in spec.withdrawals
    fitted = trials._fit(spec, params)
    design = fitted.design
    assert "fc" in design.columns
    assert not {"fc_1", "fc_2"} & set(design.columns)
    bound, matrix = _bounds_rows(monkeypatch, data, fitted, params)
    assert bound["statut"] == "declenchees"
    discovery = [u for u in fitted.units if u.day.period is Period.DISCOVERY]
    assert discovery
    expected = sum(sum(c.h for c in u.climbs) / len(u.climbs) for u in discovery) / len(
        discovery
    )
    k = design.columns.index("date")
    origin = min(design.days[0], date(2025, 4, 1))
    rows = {round(r[k]): r for r in matrix}
    row = rows[(date(2025, 4, 1) - origin).days]
    assert expected > 100.0
    assert row[design.columns.index("fc")] == pytest.approx(expected, rel=1e-12)


def _strict_json(text: str) -> Any:
    """``text`` décodé en JSON standard : ``Infinity``, ``-Infinity`` et ``NaN``
    échouent par assertion."""
    import json

    def refuse(name: str) -> Any:
        raise AssertionError(f"constante JSON non standard : {name}")

    return json.loads(text, parse_constant=refuse)


def test_an3_4_the_real_path_keeps_an_infinite_inverse_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """AN3-4, le chemin du réel : ``rich_world(2)`` à ``[periodes]``, le bootstrap de
    ``b_inv`` du principal remplacé par un espion qui rend des tirages pour moitié à
    −0,001 et pour moitié à 5,0. Prémisse : l'intervalle à 95 % de ``k̂`` du principal
    exclut 0 (sinon aucun bootstrap). L'exécution va au bout ; le principal est estimé,
    « non tranché », la borne haute de son intervalle inverse vaut +∞ ; sa case
    d'``essais.csv`` vaut ``inf`` ; sa valeur dans ``essais.jsonl`` vaut ``null`` ;
    aucun fichier JSON écrit (``essais.jsonl``, ``provenance.json``) ne contient de
    constante non standard. Contre l'intervalle tourné en « non estimable » (B6) et
    la borne écrite ``Infinity`` dans ``essais.jsonl`` (B7)."""
    import csv
    from pathlib import Path

    from fixtures.q2_world import rich_world
    from mountain_perf.analyse.inference.linear import student_interval
    from mountain_perf.analyse.q2.model import InverseDraws
    from mountain_perf.analyse.q2.results import (
        JOURNAL,
        TRIALS_FILE,
        StoredPower,
        append_trials,
        write_estimation_results,
    )

    calls: list[int] = []

    def heavy_tail(inverse: Any, parameters: Any, rng: Any, workers: int = 1) -> Any:
        k = student_interval(inverse.k, inverse.se_k, inverse.df, 0.95)
        assert not k.low <= 0.0 <= k.high
        calls.append(workers)
        return InverseDraws((-0.001,) * 5 + (5.0,) * 5, 0)

    monkeypatch.setattr(trials, "inverse_bootstrap", heavy_tail)
    tables = rich_world(2)
    params = _params()
    data = q2_data(tables, PERIODS, params)
    try:
        estimation = q2_trials(data, params, {})
    except OverflowError as error:
        pytest.fail(f"le débordement de la fraction doit rendre +∞ : {error}")
    assert calls
    row = _row(estimation, "P")
    assert row.statut == "estime"
    assert row.lecture == "non tranché"
    assert row.intervalle_inverse_fraction is not None
    assert row.intervalle_inverse_fraction[1] == math.inf
    assert "inf" not in (row.phrase or "")
    folder = write_estimation_results(
        tmp_path,
        estimation,
        data,
        None,
        "<p>x</p>",
        tables.provenance,
        params,
        StoredPower(tmp_path / "puissance" / "2026-11-15_aaaaaaaaaaaa", "f" * 64, {}),
        commit="0" * 40,
        package_version="0.0.1",
        generated_on=date(2026, 11, 20),
    )
    with (folder / TRIALS_FILE).open(encoding="utf-8", newline="") as stream:
        (principal,) = [r for r in csv.DictReader(stream) if r["essai"] == "P"]
    assert principal["intervalle_inverse_fraction_haut"] == "inf"
    append_trials(tmp_path, "e1", "0" * 40, estimation.rows)
    lines = (tmp_path / JOURNAL).read_text(encoding="utf-8").splitlines()
    records = [_strict_json(line) for line in lines]
    (essai,) = [r["essai"] for r in records if r["essai"]["essai"] == "P"]
    assert essai["intervalle_inverse_fraction"][1] is None
    for path in Path(folder).glob("*.json"):
        _strict_json(path.read_text(encoding="utf-8"))
