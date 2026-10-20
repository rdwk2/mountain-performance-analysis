"""``ParameterDisplay``, ``parameter_controls``, ``changed_values`` et les plages
déclarées (§ 6.2 et 6.3, § 8.2 du brief M5-1)."""

import math
from collections.abc import Callable

import pytest

from mountain_perf.controls import ParameterControl, changed_values, parameter_controls
from mountain_perf.gpx import PROFILE_PARAMETER_DISPLAYS, PROFILE_PARAMETER_SPECS
from mountain_perf.model import (
    CURVE_PARAMETER_DISPLAYS,
    MODEL_PARAMETER_DISPLAYS,
    PROJECTION_PARAMETER_DISPLAYS,
    PROJECTION_PARAMETER_SPECS,
)
from mountain_perf.schemas import ParameterDisplay, ParameterSpec
from mountain_perf.validation import ContractError

ALPHA = ParameterSpec(
    name="alpha",
    unit="m",
    default=50,
    minimum=1,
    maximum=1000,
    description="Un paramètre en mètres.",
)
BETA = ParameterSpec(
    name="beta",
    unit=None,
    default=1.0,
    minimum=0.5,
    maximum=1.5,
    description="Un coefficient sans unité.",
)
GAMMA = ParameterSpec(
    name="gamma",
    unit="min",
    default=10.0,
    minimum=0.0,
    maximum=1440.0,
    description="Un paramètre en minutes.",
)
SPECS = (ALPHA, BETA, GAMMA)


def _display(
    name: str = "alpha",
    label: str = "Alpha (m)",
    low: float = 10,
    high: float = 200,
    step: float = 5,
) -> ParameterDisplay:
    return ParameterDisplay(name=name, label=label, low=low, high=high, step=step)


# ---------------------------------------------------------------------------
# ParameterDisplay
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (lambda: _display(name=""), "name ne doit pas être vide."),
        (lambda: _display(name="  "), "name ne doit pas être vide."),
        (lambda: _display(label=""), "alpha.label ne doit pas être vide."),
        (lambda: _display(low=math.nan), "alpha.low doit être fini, reçu nan."),
        (lambda: _display(low=-math.inf), "alpha.low doit être fini, reçu -inf."),
        (lambda: _display(high=math.inf), "alpha.high doit être fini, reçu inf."),
        (lambda: _display(step=math.nan), "alpha.step doit être fini, reçu nan."),
        (lambda: _display(low=200), "alpha : low (200) doit être < high (200)."),
        (lambda: _display(low=300), "alpha : low (300) doit être < high (200)."),
        (lambda: _display(step=0), "alpha : step (0) doit être > 0."),
        (lambda: _display(step=-5), "alpha : step (-5) doit être > 0."),
    ],
)
def test_display_invariants(
    build: Callable[[], ParameterDisplay], message: str
) -> None:
    with pytest.raises(ContractError) as error:
        build()
    assert str(error.value) == message


def test_display_invariants_are_checked_in_order() -> None:
    """Nom vide et libellé vide : le nom d'abord ; borne non finie et ``low >= high`` :
    la finitude d'abord ; ``low >= high`` et pas nul : les bornes d'abord."""
    with pytest.raises(ContractError, match=r"^name "):
        ParameterDisplay(name="", label="", low=1, high=2, step=1)
    with pytest.raises(ContractError, match=r"alpha\.high doit être fini"):
        ParameterDisplay(name="alpha", label="A", low=3, high=math.nan, step=1)
    with pytest.raises(ContractError, match=r"low \(3\) doit être < high \(2\)"):
        ParameterDisplay(name="alpha", label="A", low=3, high=2, step=0)


def test_display_accepted_at_the_limit() -> None:
    high = 1.0
    low = math.nextafter(high, -math.inf)
    display = ParameterDisplay(name="beta", label="Bêta", low=low, high=high, step=1e-9)
    assert display.low < display.high


# ---------------------------------------------------------------------------
# parameter_controls
# ---------------------------------------------------------------------------


def test_one_control_per_spec_in_the_order_of_the_specs() -> None:
    displays = (
        _display("gamma", "Gamma (min)", 0, 60, 1),
        _display("alpha", "Alpha (m)", 10, 200, 5),
    )
    controls = parameter_controls(SPECS, displays)
    assert [control.spec for control in controls] == [ALPHA, BETA, GAMMA]
    assert controls[0] == ParameterControl(
        spec=ALPHA, label="Alpha (m)", low=10.0, high=200.0, step=5.0, default=50.0
    )
    assert controls[2] == ParameterControl(
        spec=GAMMA, label="Gamma (min)", low=0.0, high=60.0, step=1.0, default=10.0
    )
    assert controls[0].slider
    assert controls[2].slider


def test_controls_are_floats() -> None:
    (control,) = parameter_controls((ALPHA,), (_display(),))
    for value in (control.low, control.high, control.step, control.default):
        assert type(value) is float
    (free,) = parameter_controls((ALPHA,), ())
    for value in (free.low, free.high, free.default):
        assert type(value) is float


def test_a_spec_without_display_is_a_free_field_within_the_guards() -> None:
    controls = parameter_controls(SPECS, ())
    assert controls == (
        ParameterControl(
            spec=ALPHA, label="alpha (m)", low=1.0, high=1000.0, step=None, default=50.0
        ),
        ParameterControl(
            spec=BETA, label="beta", low=0.5, high=1.5, step=None, default=1.0
        ),
        ParameterControl(
            spec=GAMMA,
            label="gamma (min)",
            low=0.0,
            high=1440.0,
            step=None,
            default=10.0,
        ),
    )
    assert not any(control.slider for control in controls)


@pytest.mark.parametrize(
    ("displays", "message"),
    [
        (
            (_display("delta", "Delta"),),
            "Plage d'affichage d'un paramètre inconnu : delta.",
        ),
        (
            (_display(), _display(low=20)),
            "Deux plages d'affichage pour alpha.",
        ),
        (
            (_display(low=0.5),),
            "alpha : plage [0.5, 200] hors des garde-fous [1, 1000].",
        ),
        (
            (_display(high=1001),),
            "alpha : plage [10, 1001] hors des garde-fous [1, 1000].",
        ),
        (
            (_display(low=60),),
            "alpha : défaut 50 hors de la plage [60, 200].",
        ),
        (
            (_display(high=40),),
            "alpha : défaut 50 hors de la plage [10, 40].",
        ),
    ],
)
def test_parameter_controls_refusals(
    displays: tuple[ParameterDisplay, ...], message: str
) -> None:
    with pytest.raises(ContractError) as error:
        parameter_controls(SPECS, displays)
    assert str(error.value) == message


def test_refusals_come_in_order() -> None:
    """Les plages d'abord (inconnue avant doublon), puis spec par spec (garde-fous
    avant défaut)."""
    with pytest.raises(ContractError, match="inconnu : delta"):
        parameter_controls(SPECS, (_display(), _display(), _display("delta", "D")))
    with pytest.raises(ContractError, match="Deux plages"):
        parameter_controls(SPECS, (_display(low=0), _display(low=0)))
    with pytest.raises(ContractError, match="garde-fous"):
        parameter_controls(SPECS, (_display(low=0, high=40),))
    with pytest.raises(ContractError, match=r"^alpha : "):
        parameter_controls(SPECS, (_display("gamma", "G", 20, 60, 1), _display(low=60)))


def test_display_equal_to_the_guards_and_default_on_a_bound_are_accepted() -> None:
    (control,) = parameter_controls((ALPHA,), (_display(low=1, high=1000),))
    assert (control.low, control.high) == (1.0, 1000.0)
    (low,) = parameter_controls((ALPHA,), (_display(low=50, high=100),))
    assert low.low == low.default == 50.0
    (high,) = parameter_controls((ALPHA,), (_display(low=10, high=50),))
    assert high.high == high.default == 50.0


# ---------------------------------------------------------------------------
# changed_values
# ---------------------------------------------------------------------------


def test_changed_values_keeps_only_the_changes_in_the_given_order() -> None:
    controls = parameter_controls(SPECS, ())
    values = {"gamma": 20.0, "alpha": 50.0, "beta": 0.9}
    changed = changed_values(controls, values)
    assert changed == {"gamma": 20.0, "beta": 0.9}
    assert list(changed) == ["gamma", "beta"]


def test_changed_values_is_empty_at_the_defaults() -> None:
    controls = parameter_controls(SPECS, ())
    assert changed_values(controls, {"alpha": 50.0, "beta": 1.0, "gamma": 10.0}) == {}
    assert changed_values(controls, {}) == {}


def test_changed_values_refuses_unknown_names() -> None:
    controls = parameter_controls(SPECS, ())
    with pytest.raises(ContractError) as error:
        changed_values(controls, {"zeta": 1.0, "alpha": 2.0, "eta": 3.0})
    assert str(error.value) == "Paramètres inconnus : eta, zeta."


# ---------------------------------------------------------------------------
# Les déclarations du § 6.2, en littéraux
# ---------------------------------------------------------------------------

PROFILE_TABLE = (
    ("grid_step_m", "Pas de la grille (m)", 10, 200, 5),
    ("smoothing_window_m", "Lissage de l'altitude (m)", 0, 500, 25),
    ("point_match_max_offset_m", "Écart maximal d'un lieu au tracé (m)", 10, 500, 10),
    ("point_match_min_separation_m", "Séparation des passages (m)", 0, 2000, 50),
)
CURVE_TABLE = (
    ("curve_min_support_min", "Support minimal d'une tranche (min)", 0, 60, 1),
)
MODEL_TABLE = (("effort", "Effort", 0.7, 1.2, 0.01),)


def _rows(displays: tuple[ParameterDisplay, ...]) -> tuple[tuple[object, ...], ...]:
    return tuple((d.name, d.label, d.low, d.high, d.step) for d in displays)


def test_declared_displays_are_those_of_the_brief() -> None:
    assert _rows(PROFILE_PARAMETER_DISPLAYS) == PROFILE_TABLE
    assert _rows(CURVE_PARAMETER_DISPLAYS) == CURVE_TABLE
    assert _rows(MODEL_PARAMETER_DISPLAYS) == MODEL_TABLE
    assert _rows(PROJECTION_PARAMETER_DISPLAYS) == MODEL_TABLE + CURVE_TABLE


@pytest.mark.parametrize(
    ("specs", "displays"),
    [
        (PROFILE_PARAMETER_SPECS, PROFILE_PARAMETER_DISPLAYS),
        (PROJECTION_PARAMETER_SPECS, PROJECTION_PARAMETER_DISPLAYS),
    ],
)
def test_declared_displays_pass_and_every_spec_has_one(
    specs: tuple[ParameterSpec, ...], displays: tuple[ParameterDisplay, ...]
) -> None:
    controls = parameter_controls(specs, displays)
    assert [control.spec for control in controls] == list(specs)
    assert all(control.slider for control in controls)
