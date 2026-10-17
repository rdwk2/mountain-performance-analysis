"""Contrats du diagnostic de longue course (``0010`` D12 ; précisions de M4d-1 ;
arbitrages E1 à E4 de la passe experte).

Pour chaque contrat de ``schemas/drift.py`` : des objets valides, puis une violation par
invariant, refusée par ``ContractError`` avec le fragment de son message. Les contrats
ne sont pas stockés : aucun n'entre au registre (décision Q4 (e) de M4d). Aussi : les
constantes de D12 et la constante de présentation, ``local_error_min``,
``identifiable``, ``dof``, la place des types dans le dictionnaire.
"""

import math
import re
from dataclasses import replace
from typing import Any

import pytest

from mountain_perf.schemas import (
    CLOCKS,
    DRIFT_IDENTIFICATION_THRESHOLD,
    DRIFT_MODELS,
    DRIFT_RANK_TOLERANCE,
    DRIFT_REGIMES,
    DRIFT_UNAVAILABILITIES,
    DRIFT_WEAK_SEPARATION,
    DriftDiagnostic,
    DriftFit,
    DriftInterval,
    ModelKind,
    OutingDrift,
    Regime,
    Unavailability,
)
from mountain_perf.schemas._dictionary import DOCUMENTED_TYPES
from mountain_perf.validation import ContractError

ELAPSED, MOVING = CLOCKS[0], CLOCKS[3]


def refused(fragment: str) -> Any:
    return pytest.raises(ContractError, match=re.escape(fragment))


def interval(**changes: Any) -> DriftInterval:
    """Un intervalle valide de l'écoulé : 120 s observés pour 100 s projetés."""
    base = DriftInterval(
        start_m=0.0,
        end_m=100.0,
        observed_s=120.0,
        projected_s=100.0,
        log_ratio=math.log(1.2),
        position=0.5,
        fractions=(0.25, 0.25, 0.5),
        moving_s=110.0,
        stop_s=10.0,
    )
    return replace(base, **changes)


def moving_interval(**changes: Any) -> DriftInterval:
    return interval(moving_s=None, stop_s=None, **changes)


def fit(**changes: Any) -> DriftFit:
    """Un ajustement valide : trois intervalles, rang 2, pente 0,5 ; sans ``influence``
    donnée, une influence de somme nulle quand la pente est présente."""
    base: dict[str, Any] = {
        "slope": 0.5,
        "rho": 0.25,
        "u_mz_u": 0.01,
        "rank": 2,
        "count": 3,
    }
    base.update(changes)
    if "influence" not in changes:
        n = base["count"]
        base["influence"] = (
            None if base["slope"] is None or n < 2 else (-1.0, *([0.0] * (n - 2)), 1.0)
        )
    return DriftFit(**base)


def available(**changes: Any) -> DriftDiagnostic:
    """Un diagnostic disponible à trois intervalles, trois retraits dont deux
    identifiables."""
    intervals = (
        interval(),
        interval(start_m=100.0, end_m=200.0, position=0.7),
        interval(start_m=200.0, end_m=300.0, position=0.9),
    )
    withdrawals = (
        fit(count=2, rank=1, slope=0.1),
        fit(count=2, rank=1, slope=-0.2),
        fit(count=2, rank=1, slope=None, rho=0.0),
    )
    base = DriftDiagnostic(
        model=ModelKind.V0_RAW,
        clock=ELAPSED,
        intervals=intervals,
        reference_regime=Regime.ASCENT,
        cumulative_errors_s=(-20.0, -40.0, -60.0),
        recentred_s=(-0.0, 0.0, 0.0),
        fit=fit(),
        withdrawals=withdrawals,
        slope_range=(-0.2, 0.1),
        unavailability=None,
    )
    return replace(base, **changes)


def unavailable(reason: Unavailability, **changes: Any) -> DriftDiagnostic:
    base = DriftDiagnostic(
        ModelKind.TOBLER, ELAPSED, (), None, (), (), None, (), None, reason
    )
    return replace(base, **changes)


# --- constantes ---------------------------------------------------------------


def test_constants_of_d12() -> None:
    """``0010`` D12 : tolérance relative du rang et seuil de ``rho_u`` à ``1e−10`` ;
    régimes dans l'ordre montée, plat, descente ; les cinq modèles de D9.1, dans
    l'ordre du rapport ; les motifs d'un diagnostic indisponible."""
    assert DRIFT_RANK_TOLERANCE == 1e-10
    assert DRIFT_IDENTIFICATION_THRESHOLD == 1e-10
    assert DRIFT_WEAK_SEPARATION == 0.10
    assert DRIFT_REGIMES == (Regime.ASCENT, Regime.FLAT, Regime.DESCENT)
    assert DRIFT_MODELS == (
        ModelKind.V0_RAW,
        ModelKind.V0_RECALIBRATED,
        ModelKind.CONSTANT_SPEED,
        ModelKind.NAISMITH,
        ModelKind.TOBLER,
    )
    assert DRIFT_UNAVAILABILITIES == (
        Unavailability.MULTI_OUTING_DAY,
        Unavailability.INSUFFICIENT_SUPPORT,
        Unavailability.NOT_CALIBRATED,
        Unavailability.MODEL_ERROR,
        Unavailability.ZERO_TIME,
    )


def test_types_in_the_dictionary() -> None:
    """Les quatre contrats se suivent dans le dictionnaire, dans l'ordre de lecture,
    juste avant ceux des fourchettes (M4d-2)."""
    first = DOCUMENTED_TYPES.index(DriftInterval)
    assert DOCUMENTED_TYPES[first : first + 4] == (
        DriftInterval,
        DriftFit,
        DriftDiagnostic,
        OutingDrift,
    )
    assert DOCUMENTED_TYPES[first + 4].__name__ == "ReservoirMember"


# --- DriftInterval ------------------------------------------------------------


def test_valid_intervals_and_local_error() -> None:
    """Valides : l'écoulé (déplacement et arrêt), une autre horloge (sans eux), un
    temps observé nul (sans ``log_ratio``) ; ``local_error_min = (t − p) / 60``."""
    assert interval().local_error_min == pytest.approx(20.0 / 60.0, rel=1e-15)
    assert moving_interval().moving_s is None
    zero = interval(observed_s=0.0, log_ratio=None, moving_s=0.0, stop_s=0.0)
    assert zero.local_error_min == -100.0 / 60.0


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"start_m": math.nan}, "start_m doit être fini, reçu nan."),
        ({"end_m": math.inf}, "end_m doit être fini, reçu inf."),
        ({"observed_s": math.nan, "log_ratio": None}, "observed_s doit être fini"),
        ({"position": math.nan}, "position doit être fini"),
        ({"end_m": 0.0}, "start_m (0.0) doit être < end_m (0.0)."),
        ({"projected_s": 0.0}, "projected_s doit être > 0, reçu 0.0."),
        ({"log_ratio": None}, "log_ratio doit être présent si et seulement si"),
        (
            {"observed_s": 0.0, "moving_s": -10.0},
            "log_ratio doit être présent si et seulement si observed_s > 0",
        ),
        ({"log_ratio": math.log(1.2) + 1e-9}, "log_ratio (0.1823215577"),
        ({"position": 0.0}, "position doit être dans ]0 ; 1[, reçu 0.0."),
        ({"position": 1.0}, "position doit être dans ]0 ; 1[, reçu 1.0."),
        ({"fractions": [0.25, 0.25, 0.5]}, "fractions doit être une séquence immuable"),
        ({"fractions": (0.5, 0.5)}, "fractions doit porter 3 valeurs, reçu 2."),
        ({"fractions": (1.5, -0.5, 0.0)}, "fractions[0] doit être dans [0 ; 1]"),
        ({"fractions": (0.25, 0.25, 0.25)}, "fractions doit sommer à 1, reçu 0.75."),
        ({"stop_s": None}, "moving_s et stop_s : tous deux présents ou absents."),
        ({"moving_s": 130.0, "stop_s": -10.0}, "stop_s doit être >= 0, reçu -10.0."),
        (
            {"moving_s": 100.0},
            "moving_s + stop_s (110.0) doit valoir observed_s (120.0).",
        ),
    ],
)
def test_interval_refusals(changes: dict[str, Any], fragment: str) -> None:
    with refused(fragment):
        interval(**changes)


def test_interval_tolerances() -> None:
    """``log_ratio``, la somme des fractions et ``moving_s + stop_s`` se vérifient à
    ``τ = 1e−12`` près (relatif), de part et d'autre."""
    exact = math.log(1.2)
    interval(log_ratio=exact * (1 + 5e-13))
    with refused("log_ratio ("):
        interval(log_ratio=exact * (1 + 1e-11))
    interval(fractions=(0.25, 0.25, 0.5 + 5e-13))
    with refused("fractions doit sommer à 1"):
        interval(fractions=(0.25, 0.25, 0.5 + 1e-11))
    interval(moving_s=110.0 + 5e-11)
    with refused("moving_s + stop_s"):
        interval(moving_s=110.0 + 1e-8)


# --- DriftFit -----------------------------------------------------------------


def test_valid_fits() -> None:
    """Valides : identifiable ; non identifiable (``rho`` au seuil exact, ``rho`` nul,
    ``rho`` absent, rang égal au nombre d'intervalles) ; un seul intervalle. ``dof`` =
    ``count − rank − 1`` avec la pente, absent sans elle."""
    assert fit().identifiable
    assert fit().dof == 0
    assert fit(count=6, rank=2).dof == 3
    assert not fit(slope=None, rho=DRIFT_IDENTIFICATION_THRESHOLD).identifiable
    assert not fit(slope=None, rho=0.0).identifiable
    assert fit(slope=None, rho=0.5, rank=3, count=3).dof is None
    assert not fit(slope=None, rho=None, count=1, rank=1).identifiable
    assert fit(influence=(-0.5, 2.0, -1.5)).influence == (-0.5, 2.0, -1.5)


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"count": 0, "rank": 0}, "count doit être >= 1, reçu 0."),
        ({"rank": 0}, "rank doit être dans [1 ; 3], reçu 0."),
        ({"rank": 4}, "rank doit être dans [1 ; 3], reçu 4."),
        ({"count": 2, "rank": 3}, "rank doit être dans [1 ; 2], reçu 3."),
        ({"u_mz_u": math.nan}, "u_mz_u doit être fini"),
        ({"u_mz_u": -1e-18}, "u_mz_u doit être >= 0, reçu -1e-18."),
        ({"rho": math.inf}, "rho doit être fini"),
        ({"rho": -0.5, "slope": None}, "rho doit être >= 0, reçu -0.5."),
        ({"slope": None}, "slope doit être présente si et seulement si rho >"),
        ({"rho": 1e-10}, "slope doit être présente si et seulement si rho >"),
        ({"rho": None}, "slope doit être présente si et seulement si rho >"),
        ({"slope": math.nan}, "slope doit être fini"),
        ({"rank": 3}, "slope doit être présente si et seulement si rho >"),
        ({"influence": None}, "influence doit être présente si et seulement si"),
        (
            {"slope": None, "rho": 0.0, "influence": (0.0, 0.0, 0.0)},
            "influence doit être présente si et seulement si",
        ),
        ({"influence": [-1.0, 0.0, 1.0]}, "influence doit être une séquence immuable"),
        ({"influence": (-1.0, 1.0)}, "influence doit porter 3 valeurs, reçu 2."),
        ({"influence": (-1.0, math.inf, 1.0)}, "influence[1] doit être fini"),
    ],
)
def test_fit_refusals(changes: dict[str, Any], fragment: str) -> None:
    with refused(fragment):
        fit(**changes)


def test_influence_need_not_sum_to_zero() -> None:
    """``Σ a_h = 0`` n'est pas un invariant : sous troncature du rang, la constante
    n'est dans ``Z`` qu'à la tolérance près (oracle de M4d-1, cas M2)."""
    assert fit(influence=(-1.0, 0.0, 1.0 + 8e-12)).influence is not None


# --- DriftDiagnostic ----------------------------------------------------------


def test_valid_diagnostics() -> None:
    """Valides : disponible (étendue des deux retraits identifiables) ; disponible à
    un seul intervalle (aucun retrait, aucune étendue) ; temps nul (intervalles,
    cumuls, ni ajustement ni retraits) ; chaque autre motif (rien) ; une autre horloge
    sans déplacement ni arrêt."""
    assert available().slope_range == (-0.2, 0.1)
    single = available(
        intervals=(interval(),),
        cumulative_errors_s=(-20.0,),
        recentred_s=(0.0,),
        fit=fit(count=1, rank=1, slope=None, rho=None),
        withdrawals=(),
        slope_range=None,
    )
    assert single.fit is not None
    zero = available(
        intervals=(
            interval(),
            interval(
                start_m=100.0,
                end_m=200.0,
                observed_s=0.0,
                log_ratio=None,
                moving_s=0.0,
                stop_s=0.0,
                position=0.7,
            ),
        ),
        cumulative_errors_s=(-20.0, 80.0),
        recentred_s=(120.0, 0.0),
        fit=None,
        withdrawals=(),
        slope_range=None,
        unavailability=Unavailability.ZERO_TIME,
    )
    assert zero.fit is None
    for reason in DRIFT_UNAVAILABILITIES:
        if reason is not Unavailability.ZERO_TIME:
            assert unavailable(reason).intervals == ()
    moving = available(
        clock=MOVING,
        intervals=tuple(
            replace(iv, moving_s=None, stop_s=None) for iv in available().intervals
        ),
    )
    assert moving.clock == MOVING


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        (
            {"model": ModelKind.CANDIDATE},
            "model doit être l'un des cinq modèles de D9.1.",
        ),
        ({"intervals": [interval()]}, "intervals doit être une séquence immuable"),
        (
            {"cumulative_errors_s": (-20.0, math.nan, -60.0)},
            "cumulative_errors_s[1] doit être fini",
        ),
        (
            {"unavailability": Unavailability.AMBIGUOUS},
            "unavailability doit être dans DRIFT_UNAVAILABILITIES",
        ),
        (
            {"intervals": (), "cumulative_errors_s": (), "recentred_s": ()},
            "un diagnostic disponible a des intervalles.",
        ),
        ({"fit": None}, "fit doit porter tous les intervalles."),
        ({"fit": fit(count=2, rank=1)}, "fit doit porter tous les intervalles."),
        ({"withdrawals": ()}, "withdrawals doit porter 3 ajustements, reçu 0."),
        (
            {"withdrawals": (fit(count=2, rank=1), fit(count=2, rank=1), fit(count=3))},
            "chaque retrait porte H − 1 intervalles.",
        ),
        (
            {"slope_range": (-0.2, 0.2)},
            "slope_range ((-0.2, 0.2)) doit valoir (-0.2, 0.1).",
        ),
        ({"slope_range": None}, "slope_range (None) doit valoir (-0.2, 0.1)."),
        (
            {"reference_regime": None},
            "R_0 doit être présent quand il y a des intervalles.",
        ),
        (
            {"recentred_s": (0.0, 0.0)},
            "cumulative_errors_s et recentred_s : une valeur par intervalle.",
        ),
        (
            {"recentred_s": (0.0, 0.0, 1e-9)},
            "le dernier B_k doit valoir 0, reçu 1e-09.",
        ),
        (
            {"clock": MOVING},
            "intervals[0] : déplacement et arrêt sous l'écoulé seulement.",
        ),
    ],
)
def test_diagnostic_refusals(changes: dict[str, Any], fragment: str) -> None:
    with refused(fragment):
        available(**changes)


def test_available_diagnostic_refuses_a_zero_time() -> None:
    """Disponible : tous les temps observés > 0 (sinon, le motif ``temps nul``)."""
    intervals = (
        interval(),
        interval(
            start_m=100.0,
            end_m=200.0,
            observed_s=0.0,
            log_ratio=None,
            moving_s=0.0,
            stop_s=0.0,
            position=0.7,
        ),
        interval(start_m=200.0, end_m=300.0, position=0.9),
    )
    with refused("disponible : tous les temps observés > 0."):
        available(intervals=intervals)


def test_zero_time_and_other_reasons() -> None:
    """``ZERO_TIME`` : un temps observé ``<= 0`` exigé, ni ajustement ni retraits ;
    les autres motifs : ni intervalle, ni cumul, ni ``R_0``, ni ajustement."""
    with refused("ZERO_TIME : des intervalles, l'un au moins de temps observé <= 0."):
        available(
            fit=None,
            withdrawals=(),
            slope_range=None,
            unavailability=Unavailability.ZERO_TIME,
        )
    with refused("ZERO_TIME : des intervalles, l'un au moins de temps observé <= 0."):
        unavailable(Unavailability.ZERO_TIME)
    zero_intervals = (
        interval(observed_s=0.0, log_ratio=None, moving_s=0.0, stop_s=0.0),
    )
    with refused("ZERO_TIME : ni ajustement, ni retraits, ni étendue."):
        available(
            intervals=zero_intervals,
            cumulative_errors_s=(100.0,),
            recentred_s=(0.0,),
            fit=fit(count=1, rank=1, slope=None, rho=None),
            withdrawals=(),
            slope_range=None,
            unavailability=Unavailability.ZERO_TIME,
        )
    with refused("insufficient_support : aucun intervalle ni cumul."):
        unavailable(Unavailability.INSUFFICIENT_SUPPORT, cumulative_errors_s=(1.0,))
    with refused("not_calibrated : aucun intervalle ni cumul."):
        unavailable(Unavailability.NOT_CALIBRATED, intervals=(interval(),))
    with refused("model_error : ni R_0, ni ajustement, ni retraits."):
        unavailable(Unavailability.MODEL_ERROR, reference_regime=Regime.FLAT)
    with refused("multi_outing_day : ni R_0, ni ajustement, ni retraits."):
        unavailable(Unavailability.MULTI_OUTING_DAY, fit=fit())


def test_elapsed_requires_moving_and_stop() -> None:
    with refused("intervals[0] : déplacement et arrêt sous l'écoulé seulement."):
        available(
            intervals=tuple(
                replace(iv, moving_s=None, stop_s=None) for iv in available().intervals
            )
        )


# --- OutingDrift ---------------------------------------------------------------


def group(
    clock: Any, models: tuple[ModelKind, ...] = DRIFT_MODELS
) -> tuple[DriftDiagnostic, ...]:
    return tuple(
        unavailable(Unavailability.INSUFFICIENT_SUPPORT, model=m, clock=clock)
        for m in models
    )


def with_available() -> tuple[DriftDiagnostic, ...]:
    """L'écoulé : v0 brut disponible à trois intervalles, les quatre autres non
    calés."""
    return (
        available(),
        *(
            unavailable(Unavailability.NOT_CALIBRATED, model=m)
            for m in DRIFT_MODELS[1:]
        ),
    )


def outing(**changes: Any) -> OutingDrift:
    base: dict[str, Any] = {
        "outing_id": "s",
        "targets": 4,
        "elements": 3,
        "stop": Unavailability.ABSENT,
        "horizon_s": 2400.0,
        "diagnostics": with_available(),
    }
    base.update(changes)
    return OutingDrift(**base)


def test_valid_outing_drift() -> None:
    """Valides : séquence arrêtée (motif d'observation) ; tout ``K`` retenu ; aucun
    élément (sans horizon) ; horizon absent (v0 brut sans prévision) ; trois horloges
    du rapport."""
    assert outing().elements == 3
    assert outing(targets=3, stop=None).stop is None
    assert outing(elements=0, horizon_s=None, diagnostics=group(ELAPSED)).elements == 0
    assert outing(horizon_s=None).horizon_s is None
    three = group(ELAPSED) + group(CLOCKS[2]) + group(CLOCKS[6])
    assert len(outing(diagnostics=three).diagnostics) == 15


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"outing_id": ""}, "outing_id ne doit pas être vide."),
        ({"targets": 0, "elements": 0}, "targets doit être >= 1, reçu 0."),
        ({"elements": 5}, "elements doit être dans [0 ; 4], reçu 5."),
        ({"elements": -1}, "elements doit être dans [0 ; 4], reçu -1."),
        ({"stop": None}, "stop doit être absent si et seulement si tout K est retenu."),
        ({"targets": 3}, "stop doit être absent si et seulement si tout K est retenu."),
        (
            {"stop": Unavailability.ZERO_TIME},
            "stop doit être un motif d'observation, reçu zero_time.",
        ),
        ({"horizon_s": math.nan}, "horizon_s doit être fini"),
        ({"horizon_s": 0.0}, "horizon_s : > 0, et seulement avec au moins un élément."),
        (
            {"elements": 0, "diagnostics": group(ELAPSED)},
            "horizon_s : > 0, et seulement avec au moins un élément.",
        ),
        (
            {"diagnostics": list(group(ELAPSED))},
            "diagnostics doit être une séquence immuable",
        ),
        ({"diagnostics": ()}, "multiple non nul de 5 diagnostics, reçu 0."),
        (
            {"diagnostics": group(ELAPSED)[:4]},
            "multiple non nul de 5 diagnostics, reçu 4.",
        ),
        (
            {"diagnostics": group(ELAPSED)[:4] + group(MOVING)[:1]},
            "un groupe de diagnostics porte une seule horloge.",
        ),
        (
            {"diagnostics": group(ELAPSED, DRIFT_MODELS[::-1])},
            "les cinq modèles, dans l'ordre de DRIFT_MODELS.",
        ),
        (
            {"diagnostics": group(ELAPSED) + group(ELAPSED)},
            "des horloges distinctes, l'écoulé d'abord.",
        ),
        (
            {"diagnostics": group(MOVING) + group(ELAPSED)},
            "des horloges distinctes, l'écoulé d'abord.",
        ),
        (
            {"elements": 2},
            "un diagnostic porte 3 intervalles, la séquence 2.",
        ),
    ],
)
def test_outing_drift_refusals(changes: dict[str, Any], fragment: str) -> None:
    with refused(fragment):
        outing(**changes)
