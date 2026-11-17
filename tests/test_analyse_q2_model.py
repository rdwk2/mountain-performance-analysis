"""Le modèle de Q2 (AN3-3b, ``docs/decisions/0023``) : budget et retraits (C7), étage
1 centré (C8), effet de la date à ``V`` connue (C9), inverse (C10), lecture bornée et
ses phrases (C11), intervalle de ``k̂`` (C11 bis), ``κ``, et les deux bootstraps de
``b_inv``. Sur des journées inventées."""

from __future__ import annotations

import math
import random
import subprocess
import sys
from collections.abc import Callable
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from fixtures.q2_world import at, make_climb, make_day, small_world
from mountain_perf.analyse.inference.base import Interval, child_rng
from mountain_perf.analyse.inference.readings import Reading
from mountain_perf.analyse.q2 import model
from mountain_perf.analyse.q2.data import Q2Day, Q2Motif, q2_data
from mountain_perf.analyse.q2.model import (
    KNOTS_EQUAL,
    Measure,
    NotEstimableError,
    base_columns,
    bounded_reading,
    build_design,
    centered_stage_one,
    date_effect_at,
    fit_direct,
    fit_inverse,
    fixed_v_bootstrap,
    heart_rate_columns,
    inverse_bootstrap,
    inverse_design,
    inverse_effect_at,
    k_contains_zero,
    kappa_fit,
    model_spec,
    phi_bounds,
    stage_one,
)
from mountain_perf.analyse.q2.parameters import Q2_PARAMETER_SPECS
from mountain_perf.schemas import ParameterSet
from mountain_perf.schemas.processed import ClimbRegime

LONG = ClimbRegime.LONG_CLIMB
SKI = ClimbRegime.SKI_TOURING
EXACT = 1e-12


def _params(**values: float) -> ParameterSet:
    return ParameterSet(Q2_PARAMETER_SPECS, values)


# --- C7 -----------------------------------------------------------------------


def c7_days() -> list[Q2Day]:
    """C7 : 20 journées, 17 avec ``e_s`` ; deux groupes de deux journées (avec
    ``e_s``) ; les autres seules, les trois sans ``e_s`` aussi."""
    first = date(2025, 1, 1)
    days = []
    for i in range(20):
        lat = 45.0 if i < 2 else 45.5 if i < 4 else 40.0 + 0.1 * i
        climbs = [make_climb(lat=lat), make_climb(lat=lat, y=-0.9)]
        step5 = Q2Motif.RESTING_INVALID if i >= 17 else None
        days.append(make_day(first + timedelta(days=7 * i), climbs, step5=step5))
    return days


@pytest.mark.parametrize(
    ("residual", "estimable_df", "withdrawals", "n", "p", "estimable"),
    [
        (5, 3, (1, 2, 3), 17, 12, True),
        (5, 10, (1, 2, 3), 17, 12, False),
        (8, 3, (1, 2, 3, 4, 5), 20, 9, True),
        (12, 10, (1, 2, 3, 4, 5), 20, 9, True),
        (12, 12, (1, 2, 3, 4, 5), 20, 9, False),
    ],
)
def test_c7_the_budget_and_cumulative_withdrawals(
    residual: int,
    estimable_df: int,
    withdrawals: tuple[int, ...],
    n: int,
    p: int,
    estimable: bool,
) -> None:
    """C7 : les comptes du cas, dits comme tels."""
    spec = model_spec(
        c7_days(),
        Measure.MP,
        LONG,
        _params(min_residual_df=residual, min_estimable_df=estimable_df),
    )
    assert (spec.withdrawals, spec.n, spec.p, spec.estimable) == (
        withdrawals,
        n,
        p,
        estimable,
    )
    assert spec.p == len(spec.columns)
    if not estimable:
        assert spec.reason == f"n − p = {n - p}, sous min_estimable_df = {estimable_df}"


def test_c7_the_full_model_has_fifteen_columns() -> None:
    spec = model_spec(c7_days(), Measure.MP, LONG, _params(min_residual_df=1))
    assert spec.withdrawals == ()
    assert spec.columns == (
        "constante",
        "date",
        "saison_sin",
        "saison_cos",
        "fc_1",
        "fc_2",
        "log_gain",
        "pente",
        "altitude",
        "d_plus_avant",
        "d_moins_avant",
        "heure",
        "e_s",
        "parcours_0",
        "parcours_1",
    )


def test_c7_ms_and_the_ski_without_season() -> None:
    params = _params(min_residual_df=5, min_estimable_df=3)
    ms = model_spec(c7_days(), Measure.MS, LONG, params)
    assert (ms.withdrawals, ms.n, ms.p) == ((1,), 17, 12)
    assert not any(c.startswith("fc") for c in ms.columns)
    ski = model_spec(c7_days(), Measure.MP, SKI, params)
    assert (ski.withdrawals, ski.n, ski.p) == ((1,), 17, 12)
    assert "saison_sin" not in ski.columns
    assert "saison_cos" not in ski.columns


def test_the_columns_and_their_order_after_each_withdrawal() -> None:
    assert base_columns(Measure.MP, LONG, (1, 2, 3)) == (
        "constante",
        "date",
        "saison_sin",
        "saison_cos",
        "fc",
        "log_gain",
        "pente",
        "altitude",
        "d_plus_avant",
        "e_s",
    )
    assert base_columns(Measure.MS, SKI, (1, 2, 3, 4, 5)) == (
        "constante",
        "date",
        "log_gain",
        "pente",
        "altitude",
        "d_plus_avant",
    )


# --- C8 -----------------------------------------------------------------------


def test_c8_the_centered_stage_one() -> None:
    """C8 : ``s²_ε = RSS/(N − J − q)`` (pas ``LinearFit.scale``), ``d_s = s²/n_s``."""
    stage = centered_stage_one(
        [
            [(10.0, [1.0]), (13.0, [2.0]), (17.0, [3.0])],
            [(20.0, [1.0]), (25.0, [3.0]), (27.0, [5.0])],
        ]
    )
    assert stage.slopes == pytest.approx((float(Fraction(21, 10)),), rel=EXACT)
    assert stage.df == 3
    assert stage.sigma2 == pytest.approx(float(Fraction(197, 90)), rel=EXACT)
    assert stage.d == pytest.approx(
        (float(Fraction(197, 270)), float(Fraction(197, 270))), rel=EXACT
    )


def test_a_stage_one_without_degrees_of_freedom_is_not_estimable() -> None:
    with pytest.raises(NotEstimableError, match="N − J − q = 0"):
        centered_stage_one([[(1.0, [1.0]), (2.0, [2.0])]])


def test_the_ms_stage_one_has_five_covariates_and_mp_six() -> None:
    data = q2_data(small_world(3), None, _params())
    spec = model_spec(data.days[LONG], Measure.MS, LONG, _params())
    units = spec.units()
    ms = stage_one(units, Measure.MS)
    assert len(ms.slopes) == 5
    assert ms.eta_within is None
    mp = stage_one(units, Measure.MP)
    assert len(mp.slopes) == 6
    assert mp.eta_within == mp.slopes[0]


# --- C9, C10 ------------------------------------------------------------------


def test_c9_the_date_effect_at_a_known_v() -> None:
    t = [0.0, 10.0, 20.0, 30.0, 40.0]
    v = [[0.0] * 5 for _ in range(5)]
    for i, value in enumerate((1.0, 2.0, 1.0, 2.0, 1.0)):
        v[i][i] = value
    b, se = date_effect_at([[1.0, x] for x in t], [1.0, 2.0, 2.0, 4.0, 5.0], v, 1)
    assert b == pytest.approx(0.1, rel=EXACT)
    assert se == pytest.approx(1 / 30, rel=EXACT)


def test_c10_an_exactly_linear_inverse() -> None:
    """C10 : ``b_inv = −d/k = 1/100`` ; le signe compte."""
    t = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]
    h = [140.0, 150.0, 145.0, 160.0, 155.0, 150.0]
    y = [2 + 0.01 * ti + 0.5 * hi for ti, hi in zip(t, h, strict=True)]
    identity = [[float(i == j) for j in range(6)] for i in range(6)]
    effect = inverse_effect_at(
        [[1.0, ti, yi] for ti, yi in zip(t, y, strict=True)], h, identity, 1, 2
    )
    assert effect.k == pytest.approx(2.0, abs=1e-9)
    assert effect.b_inv == pytest.approx(0.01, abs=1e-9)


# --- C11, C11 bis -------------------------------------------------------------

ESTABLISHED_PERIODS = (
    "la tendance est comprise entre 1,0 et 11,0 %/an (régressions directe et"
    " inverse) ; elle se lit comme un écart entre la période de découverte et la"
    " suite, saison non séparée ; exploratoire"
)


def _i(low: float, high: float) -> Interval:
    return Interval(low, high)


def test_c11_the_four_readings_and_their_sentences() -> None:
    k_out = _i(0.1, 0.5)
    assert bounded_reading(_i(0.01, 0.06), _i(0.025, 0.11), k_out, 0.05, True) == (
        Reading.ESTABLISHED,
        ESTABLISHED_PERIODS,
    )
    assert bounded_reading(_i(0.01, 0.06), _i(0.025, 0.11), k_out, 0.05, False) == (
        Reading.ESTABLISHED,
        "la tendance est comprise entre 1,0 et 11,0 %/an (régressions directe et"
        " inverse) ; exploratoire",
    )
    assert bounded_reading(_i(-0.03, 0.04), _i(-0.02, 0.045), k_out, 0.05, False) == (
        Reading.NO_USEFUL_EFFECT,
        "ni la régression directe ni l'inverse ne laissent place à un effet de 5 %/an",
    )
    assert bounded_reading(_i(0.01, 0.06), _i(-0.01, 0.08), k_out, 0.05, False) == (
        Reading.UNDECIDED,
        "les données ne tranchent pas",
    )
    assert bounded_reading(
        _i(0.01, 0.06), _i(0.025, 0.11), _i(-0.1, 0.3), 0.05, False
    ) == (Reading.UNDECIDED, "les données ne tranchent pas")


def test_c11_negative_and_rounded_bounds() -> None:
    _, sentence = bounded_reading(
        _i(-0.025, -0.01), _i(-0.02, -0.005), _i(0.1, 0.5), 0.05, False
    )
    assert sentence.startswith("la tendance est comprise entre -2,5 et -0,5 %/an")
    _, sentence = bounded_reading(
        _i(0.0168, 0.06), _i(0.025, 0.11), _i(0.1, 0.5), 0.05, False
    )
    assert sentence == (
        "la tendance est comprise entre 1,7 et 11,0 %/an (régressions directe et"
        " inverse) ; exploratoire"
    )


def test_c11_direct_only_and_inverse_only_sentences() -> None:
    """Q-49 (p) et la correction B (S18) : les phrases d'une seule régression."""
    assert bounded_reading(_i(0.01, 0.06), None, None, 0.05, False) == (
        Reading.ESTABLISHED,
        "la tendance est comprise entre 1,0 et 6,0 %/an (régression directe) ;"
        " exploratoire",
    )
    assert bounded_reading(_i(-0.01, 0.02), None, None, 0.05, True) == (
        Reading.NO_USEFUL_EFFECT,
        "la régression directe ne laisse pas place à un effet de 5 %/an",
    )
    assert bounded_reading(None, _i(0.01, 0.06), None, 0.05, True)[1] == (
        "la tendance est comprise entre 1,0 et 6,0 %/an (régression inverse) ;"
        " elle se lit comme un écart entre la période de découverte et la suite,"
        " saison non séparée ; exploratoire"
    )
    assert bounded_reading(None, _i(-0.01, 0.02), None, 0.05, True)[1] == (
        "la régression inverse ne laisse pas place à un effet de 5 %/an"
    )
    assert bounded_reading(_i(-0.01, 0.08), None, None, 0.05, True)[1] == (
        "les données ne tranchent pas"
    )


def test_c11_bis_the_k_interval_is_always_at_95_percent() -> None:
    """C11 bis : à 95 %, ``[0,0828… ; 0,9171…]`` exclut 0 ; à 99 %, il le
    contiendrait."""
    assert k_contains_zero(0.5, 0.2, 20) is False
    assert k_contains_zero(0.1, 0.2, 20) is True


# --- φ, nœuds -----------------------------------------------------------------


def test_phi_bounds() -> None:
    assert phi_bounds([0.0, 4.0, 10.0], _params()) == (2.0, 5.0)
    with pytest.raises(NotEstimableError, match="période trop courte"):
        phi_bounds([0.0, 4.0], _params())


def test_equal_knots_are_not_estimable() -> None:
    with pytest.raises(NotEstimableError) as error:
        heart_rate_columns([150.0, 150.0, 150.0], (150.0, 150.0, 150.0))
    assert str(error.value) == KNOTS_EQUAL


# --- κ ------------------------------------------------------------------------


def test_kappa_is_one_when_the_speed_is_proportional_to_the_reserve() -> None:
    """``κ̂ = 1`` (à ``1e-9``) à ``V`` connue, sur un monde où la VAM est exactement
    proportionnelle à ``h − r`` : la matrice et la réponse sont celles de
    ``kappa_fit``."""
    rnd = random.Random(5)
    days = []
    for i in range(20):
        h = 120.0 + 2.0 * i + rnd.uniform(-1.0, 1.0)
        climbs = [
            make_climb(
                when=at(date(2025, 1, 1) + timedelta(days=9 * i), 7 + k, 10 * i % 60),
                y=math.log(0.01) + math.log(h - 50.0),
                h=h,
                lat=40.0 + 0.1 * i,
                gain_m=rnd.uniform(400.0, 900.0),
                grade=rnd.uniform(0.1, 0.3),
                elevation_m=rnd.uniform(500.0, 2500.0),
                d_plus=rnd.uniform(0.0, 500.0),
                d_minus=rnd.uniform(0.0, 500.0),
            )
            for k in range(2)
        ]
        days.append(
            make_day(
                date(2025, 1, 1) + timedelta(days=9 * i),
                climbs,
                e_s=rnd.uniform(-3.0, 3.0),
                r=50.0,
            )
        )
    params = _params(min_residual_df=1, min_estimable_df=1)
    spec = model_spec(days, Measure.MS, LONG, params)
    assert spec.withdrawals == ()
    identity = [[float(i == j) for j in range(20)] for i in range(20)]
    fit = kappa_fit(spec, params, known_v=identity)
    assert fit.kappa == pytest.approx(1.0, abs=1e-9)
    assert fit.interval.low <= 1.0 <= fit.interval.high


# --- le direct, l'inverse et les deux bootstraps --------------------------------


def _fitted(
    bootstrap_draws: int = 9,
) -> tuple[model.DirectFit, model.InverseFit, ParameterSet]:
    params = _params(bootstrap_draws=bootstrap_draws)
    data = q2_data(small_world(1), None, params)
    spec = model_spec(data.days[LONG], Measure.MP, LONG, params)
    units = spec.units()
    design = build_design(units, spec, stage_one(units, Measure.MP), params)
    direct = fit_direct(design, params)
    inverse = fit_inverse(inverse_design(design, units), params)
    return direct, inverse, params


def _counting(monkeypatch: pytest.MonkeyPatch, name: str) -> list[int]:
    calls: list[int] = []
    original: Callable[..., Any] = getattr(model, name)

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(model, name, spy)
    return calls


def test_the_inverse_design_has_no_heart_rate_column_and_the_mean_speed() -> None:
    direct, inverse, _ = _fitted()
    columns = inverse.design.columns
    assert columns[:3] == ("constante", "date", "log_vam")
    assert not any(c.startswith("fc") for c in columns)
    assert inverse.design.y == direct.design.h_bar
    assert inverse.design.column("log_vam") == list(direct.design.y)


def test_the_real_bootstrap_reestimates_v_at_each_draw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ 7.3 : ``1 + B`` appels à ``reml_fit`` pour l'inverse (son ajustement, puis
    un par tirage)."""
    _, fitted_inverse, params = _fitted()
    calls = _counting(monkeypatch, "reml_fit")
    refitted = fit_inverse(fitted_inverse.design, params)
    draws = inverse_bootstrap(refitted, params, child_rng(1, 2, 0, 0))
    assert len(calls) == 1 + 9
    assert len(draws.draws) + draws.removed == 9


def test_the_power_bootstrap_keeps_v_fixed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Q-45 : aucun ``reml_fit`` dans la boucle, ``gls_operator`` une fois."""
    _, fitted_inverse, _ = _fitted()
    reml_calls = _counting(monkeypatch, "reml_fit")
    operator_calls = _counting(monkeypatch, "gls_operator")
    draws = fixed_v_bootstrap(fitted_inverse, 9, child_rng(1, 2, 0, 0))
    assert reml_calls == []
    assert len(operator_calls) == 1
    assert len(draws.draws) + draws.removed == 9


BOOTSTRAP_IN_NEW_PROCESS = """
import os, sys
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[name] = "1"
sys.path.insert(0, {tests!r})
from mountain_perf.analyse.inference.base import child_rng
from mountain_perf.analyse.q2.model import inverse_bootstrap
from test_analyse_q2_model import _fitted

if __name__ == "__main__":
    _, inverse, params = _fitted(bootstrap_draws=4)
    one = inverse_bootstrap(inverse, params, child_rng(1, 2, 0, 0), 1)
    two = inverse_bootstrap(inverse, params, child_rng(1, 2, 0, 0), 2)
    print(one == two, len(one.draws) + one.removed)
"""


def test_the_bootstrap_does_not_depend_on_the_number_of_processes(
    tmp_path: Path,
) -> None:
    """§ 7.3 : les réajustements se répartissent sans changer la sortie ; dans un
    processus neuf, un fil BLAS posé avant numpy (Q-50 (b)), comme la commande."""
    tests = Path(__file__).resolve().parent
    script = tmp_path / "bootstrap.py"
    script.write_text(
        BOOTSTRAP_IN_NEW_PROCESS.format(tests=str(tests)), encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["True", "4"]


def test_a_reestimated_fit_reports_b_and_its_standard_error() -> None:
    direct, fitted_inverse, _ = _fitted()
    assert direct.df == direct.design.n - direct.design.p
    assert direct.se > 0
    assert fitted_inverse.df == fitted_inverse.design.n - fitted_inverse.design.p
    assert fitted_inverse.b_inv == pytest.approx(
        -fitted_inverse.reml.fit.coef[1] / fitted_inverse.k, rel=EXACT
    )
