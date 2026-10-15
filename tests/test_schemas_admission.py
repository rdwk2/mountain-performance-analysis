"""Contrats de l'admission exploratoire (brief M4c-3, § 8.1 ; ``0010`` D10.2 à D10.6 ;
décisions E1 à E3 de M4c-3).

Pour chaque contrat de ``schemas/admission.py`` : des objets valides construits à la
main, à leurs limites, puis une violation par invariant de la rubrique « Invariants »,
refusée par ``ContractError`` avec un fragment exact de son message. Les seuils de D10
et ``ε = NUMERIC_TOLERANCE`` sont éprouvés de part et d'autre (un dommage à
``2η + 0,5e−6`` satisfait, à ``2η + 2e−6`` dépasse ; un gain de ``1e−7`` n'est pas un
succès) ; les frontières de « comparable » sont des comparaisons exactes. Constantes,
``required_successes`` et énumérations exactes. Aucune donnée réelle : trois jours de
mars 2026 inventés.
"""

import math
import re
from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from mountain_perf.schemas import (
    ADMISSION_RESERVE_DESCRIPTIONS,
    ADMISSION_VERDICT_DESCRIPTIONS,
    CLOCKS,
    COMPARABLE_DPLUS_PER_KM,
    COMPARABLE_MAX_S,
    FAILED_CONDITION_DESCRIPTIONS,
    GAIN_FLOOR,
    GAIN_SHARE,
    GUARD_METRICS,
    GUARD_STATUS_DESCRIPTIONS,
    HARM_FLOOR,
    HARM_MAX_FACTOR,
    HARM_SHARE,
    NON_EVALUABLE_DESCRIPTIONS,
    NUMERIC_TOLERANCE,
    PASSAGE_TOLERANCE,
    REGIME_MIN_SEGMENTS,
    REVIEW_CAUSE_DESCRIPTIONS,
    THRESHOLD_SOURCE_DESCRIPTIONS,
    Admission,
    AdmissionReserve,
    AdmissionVerdict,
    ContractError,
    EffortValue,
    ExperimentMetric,
    FailedCheck,
    FailedCondition,
    GuardOutcome,
    GuardStatus,
    GuardValue,
    MetricValue,
    NonEvaluable,
    PassageGuardOutcome,
    PassageValue,
    PerformanceAssessment,
    ReviewCause,
    ReviewReason,
    ThresholdSource,
    Unavailability,
    required_successes,
)
from mountain_perf.schemas._dictionary import ENUM_DESCRIPTIONS

M = ExperimentMetric
D1, D2, D3 = date(2026, 3, 2), date(2026, 3, 9), date(2026, 3, 16)
ETA = HARM_FLOOR
"""``η`` d'un garde-fou au seuil fixe."""
PEAK = HARM_MAX_FACTOR * HARM_FLOOR
"""``2η`` d'un garde-fou au seuil fixe."""
MISSING = MetricValue(None, Unavailability.MODEL_ERROR, 0)
"""Une cible ou une métrique en erreur du modèle."""
FREE_BASE = EffortValue(0.9, 0.9, False)
FREE_CANDIDATE = EffortValue(1.1, 1.1, False)
SATURATED_LOW = EffortValue(0.3, 0.5, True)
SATURATED_HIGH = EffortValue(2.0, 1.5, True)
FIXED_SOURCE: dict[str, Any] = {
    "source": ThresholdSource.FIXED,
    "local_unavailability": Unavailability.ABSENT,
    "reference": None,
    "threshold": GAIN_FLOOR,
}
BORROWED_SOURCE: dict[str, Any] = {
    "source": ThresholdSource.BORROWED,
    "local_unavailability": Unavailability.ABSENT,
    "reference": 0.08,
    "threshold": 0.02,
}


def _raises(instance: Any, fragment: str, **changes: Any) -> None:
    with pytest.raises(ContractError, match=re.escape(fragment)):
        replace(instance, **changes)


# ---------------------------------------------------------------------------
# Constantes, required_successes, énumérations
# ---------------------------------------------------------------------------


def test_thresholds_of_d10_are_exact() -> None:
    """D10.2 à D10.4, décision E2 : les seuils de la règle, au bit."""
    assert GAIN_FLOOR == 0.010
    assert GAIN_SHARE == 0.25
    assert HARM_FLOOR == 0.005
    assert HARM_SHARE == 0.10
    assert HARM_MAX_FACTOR == 2.0
    assert PASSAGE_TOLERANCE == 0.01
    assert NUMERIC_TOLERANCE == 1e-6
    assert COMPARABLE_MAX_S == 14400.0
    assert COMPARABLE_DPLUS_PER_KM == (50.0, 110.0)
    assert REGIME_MIN_SEGMENTS == 3


def test_guard_metrics_are_the_seven_of_d10_4_in_order() -> None:
    """D10.4 : la liste figée des garde-fous de métrique, ``|L|`` en tête."""
    assert GUARD_METRICS == (
        M.LEVEL,
        M.ASCENT_LEVEL,
        M.FLAT_LEVEL,
        M.DESCENT_LEVEL,
        M.ASCENT_DISPERSION,
        M.FLAT_DISPERSION,
        M.DESCENT_DISPERSION,
    )
    assert M.USAGE not in GUARD_METRICS


@pytest.mark.parametrize("n", range(1, 9))
def test_required_successes_is_the_ceiling_of_three_quarters(n: int) -> None:
    """D10.3 : ``⌈3n/4⌉``, en entiers."""
    required = required_successes(n)
    assert isinstance(required, int)
    assert required == math.ceil(3 * n / 4)


def test_required_successes_table() -> None:
    assert [required_successes(n) for n in range(1, 9)] == [1, 2, 3, 3, 4, 5, 6, 6]


@pytest.mark.parametrize(
    ("enum", "values"),
    [
        (AdmissionVerdict, ["provisional_candidate", "rejected", "to_review"]),
        (
            AdmissionReserve,
            [
                "comparator_saturated",
                "candidate_saturated",
                "central_sensitivity_remaining",
            ],
        ),
        (ThresholdSource, ["local", "borrowed", "fixed"]),
        (
            NonEvaluable,
            [
                "excluded",
                "multi_outing",
                "unscored",
                "no_usage",
                "insufficient_support",
                "zero_time",
                "underrepresented",
                "passage_unavailable",
                "not_calibrated",
            ],
        ),
        (GuardStatus, ["satisfied", "violated", "unavailable", "not_evaluable"]),
        (
            ReviewCause,
            [
                "target_unavailable",
                "guard_unavailable",
                "passages_unavailable",
                "passages_not_applicable",
            ],
        ),
        (FailedCondition, ["mean_gain", "vote", "loss", "guard", "passages"]),
    ],
)
def test_enum_members_in_order(enum: Any, values: list[str]) -> None:
    """D10.2 à D10.6 : membres et valeurs, dans l'ordre (celui de la règle)."""
    assert [member.value for member in enum] == values


@pytest.mark.parametrize(
    ("enum", "descriptions"),
    [
        (AdmissionVerdict, ADMISSION_VERDICT_DESCRIPTIONS),
        (AdmissionReserve, ADMISSION_RESERVE_DESCRIPTIONS),
        (ThresholdSource, THRESHOLD_SOURCE_DESCRIPTIONS),
        (NonEvaluable, NON_EVALUABLE_DESCRIPTIONS),
        (GuardStatus, GUARD_STATUS_DESCRIPTIONS),
        (ReviewCause, REVIEW_CAUSE_DESCRIPTIONS),
        (FailedCondition, FAILED_CONDITION_DESCRIPTIONS),
    ],
)
def test_enum_descriptions_cover_every_member(enum: Any, descriptions: Any) -> None:
    """Une description non vide par membre, dans l'ordre ; publiée au dictionnaire."""
    assert list(descriptions) == list(enum)
    assert all(text.strip() for text in descriptions.values())
    assert ENUM_DESCRIPTIONS[enum] is descriptions


# ---------------------------------------------------------------------------
# EffortValue (D9.2 ; décision E1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("free", "bounded", "saturated"),
    [
        (0.9, 0.9, False),
        (0.3, 0.5, True),
        (2.0, 1.5, True),
        (0.9, 0.9 + 5e-13, False),
    ],
    ids=["free", "saturated-low", "saturated-high", "bounded-within-tau"],
)
def test_effort_value_accepted(free: float, bounded: float, saturated: bool) -> None:
    """Décision E1 : un effort libre, puis saturé à chaque borne de ``EFFORT_BOUNDS`` ;
    ``bounded`` vérifié à ``τ`` près."""
    effort = EffortValue(free, bounded, saturated)
    assert (effort.free, effort.bounded, effort.saturated) == (free, bounded, saturated)


@pytest.mark.parametrize(
    ("fragment", "changes"),
    [
        ("free doit être fini", {"free": math.nan}),
        ("free doit être fini", {"free": math.inf}),
        ("bounded doit être fini", {"bounded": math.nan}),
        ("free doit être > 0, reçu 0.0.", {"free": 0.0, "bounded": 0.5}),
        ("free doit être > 0, reçu -0.5.", {"free": -0.5, "bounded": 0.5}),
        (
            "bounded doit valoir min(max(free, 0.5), 1.5) = 0.9, reçu",
            {"bounded": 0.9 + 2e-12},
        ),
        (
            "bounded doit valoir min(max(free, 0.5), 1.5) = 0.5, reçu 0.3.",
            {"free": 0.3, "bounded": 0.3, "saturated": True},
        ),
        (
            "bounded doit valoir min(max(free, 0.5), 1.5) = 1.5, reçu 2.0.",
            {"free": 2.0, "bounded": 2.0, "saturated": True},
        ),
        (
            "saturated vaut free hors de [0.5 ; 1.5], soit True, reçu False.",
            {"free": 0.3, "bounded": 0.5},
        ),
        (
            "saturated vaut free hors de [0.5 ; 1.5], soit True, reçu False.",
            {"free": 2.0, "bounded": 1.5},
        ),
        (
            "saturated vaut free hors de [0.5 ; 1.5], soit False, reçu True.",
            {"saturated": True},
        ),
        (
            "saturated vaut free hors de [0.5 ; 1.5], soit True, reçu False.",
            {"free": 0.5 - 2e-12, "bounded": 0.5},
        ),
        (
            "saturated vaut free hors de [0.5 ; 1.5], soit False, reçu True.",
            {"free": 0.5 + 2e-12, "bounded": 0.5 + 2e-12, "saturated": True},
        ),
    ],
)
def test_effort_value_invariants(fragment: str, changes: dict[str, Any]) -> None:
    """``free`` fini et ``> 0`` ; ``bounded = min(max(free, 0,5), 1,5)`` à ``τ`` près ;
    ``saturated`` vaut ``free`` hors des bornes, au-delà de ``τ`` d'une borne."""
    _raises(FREE_BASE, fragment, **changes)


@pytest.mark.parametrize(
    ("free", "bounded"),
    [
        (0.5, 0.5),
        (0.5 - 5e-13, 0.5),
        (0.5 + 5e-13, 0.5),
        (1.5, 1.5),
        (1.5 - 1e-12, 1.5),
        (1.5 + 1e-12, 1.5),
    ],
)
@pytest.mark.parametrize("saturated", [False, True])
def test_effort_saturation_is_indifferent_within_tau_of_a_bound(
    free: float, bounded: float, saturated: bool
) -> None:
    """Comme ``ModelCalibration`` : à ``τ`` près d'une borne, les deux valeurs de
    ``saturated`` sont acceptées."""
    assert EffortValue(free, bounded, saturated).saturated is saturated


# ---------------------------------------------------------------------------
# PerformanceAssessment (D10.2, D10.3, D10.5)
# ---------------------------------------------------------------------------


def _target(value: float | None) -> MetricValue:
    return MISSING if value is None else MetricValue(value, None, 5)


def _performance(
    day: date,
    base: float | None,
    candidate: float | None,
    raw: float | None = 0.12,
    **changes: Any,
) -> PerformanceAssessment:
    """Une performance évaluable : locale (``F = 0,08``, ``δ = 0,02``), comparable,
    efforts libres ; ``None`` : la cible en erreur du modèle ; gains par différence,
    absents quand une des deux cibles l'est."""
    gain = None if base is None or candidate is None else base - candidate
    raw_gain = None if raw is None or candidate is None else raw - candidate
    fields: dict[str, Any] = {
        "civil_date": day,
        "outing_ids": (f"s-{day:%m%d}",),
        "motif": None,
        "comparable": True,
        "comparable_unavailability": None,
        "dplus_per_km": 70.0,
        "projected_s": 7200.0,
        "source": ThresholdSource.LOCAL,
        "local_unavailability": None,
        "reference": 0.08,
        "threshold": 0.02,
        "base": _target(base),
        "candidate": _target(candidate),
        "raw": _target(raw),
        "gain": gain,
        "raw_gain": raw_gain,
        "base_effort": FREE_BASE,
        "candidate_effort": FREE_CANDIDATE,
    }
    return PerformanceAssessment(**(fields | changes))


G1, R1 = 0.10 - 0.06, 0.12 - 0.06
G3, R3 = 0.08 - 0.05, 0.09 - 0.05
P1 = _performance(D1, 0.10, 0.06)
"""Évaluable, locale : ``δ = 0,02``, ``G = 0,04``."""
P2 = PerformanceAssessment(
    civil_date=D2,
    outing_ids=("s-0309a", "s-0309b"),
    motif=NonEvaluable.MULTI_OUTING,
    comparable=False,
    comparable_unavailability=None,
    dplus_per_km=30.0,
    projected_s=3600.0,
    source=None,
    local_unavailability=None,
    reference=None,
    threshold=None,
    base=None,
    candidate=None,
    raw=None,
    gain=None,
    raw_gain=None,
    base_effort=None,
    candidate_effort=None,
)
"""Non évaluable : jour multi-sorties."""
P3 = _performance(D3, 0.08, 0.05, 0.09, **FIXED_SOURCE)
"""Évaluable, seuil fixe (sans référence du parcours) : ``δ = 0,010``, ``G = 0,03``."""


def test_valid_evaluable_performance() -> None:
    """D10.3 : source locale, ``F = 0,08`` donne ``δ = 0,25·F = 0,02`` ; gains par
    différence exacte des cibles."""
    assert P1.source is ThresholdSource.LOCAL
    assert P1.threshold == 0.02
    assert P1.base == MetricValue(0.10, None, 5)
    assert P1.gain == 0.10 - 0.06
    assert P1.raw_gain == 0.12 - 0.06
    assert P3.threshold == GAIN_FLOOR


def test_valid_not_evaluable_performance() -> None:
    """D10.2 : un motif, aucun champ d'évaluation ; la classification reste."""
    assert P2.motif is NonEvaluable.MULTI_OUTING
    assert P2.source is None
    assert P2.gain is None
    assert P2.base_effort is None
    assert P2.comparable is False


@pytest.mark.parametrize(
    "changes",
    [
        {"reference": 0.02, "threshold": GAIN_FLOOR},
        {"reference": 0.0, "threshold": GAIN_FLOOR},
        BORROWED_SOURCE,
        {"base_effort": None, "candidate_effort": None},
        {"base": MISSING, "gain": None},
        {"raw": MISSING, "raw_gain": None},
        {"candidate": MISSING, "gain": None, "raw_gain": None},
        {"dplus_per_km": 50.0},
        {"dplus_per_km": 110.0},
        {"projected_s": 14400.0},
        {"comparable": False, "dplus_per_km": 49.9, "projected_s": 14400.1},
        {"comparable": None, "dplus_per_km": None, "projected_s": None},
        {
            "comparable": None,
            "comparable_unavailability": Unavailability.MODEL_ERROR,
            "projected_s": None,
        },
    ],
    ids=[
        "floor",
        "zero-reference",
        "borrowed-comparable",
        "not-calibrated",
        "base-missing",
        "raw-missing",
        "candidate-missing",
        "dplus-low-bound",
        "dplus-high-bound",
        "duration-bound",
        "not-comparable",
        "not-classified",
        "classification-unavailable",
    ],
)
def test_evaluable_performance_accepted_at_its_limits(changes: dict[str, Any]) -> None:
    """Plancher de ``δ``, ``F = 0`` ; source empruntée d'une comparable ; efforts
    absents ; gains absents avec leur cible ; bornes exactes de « comparable »."""
    assert replace(P1, **changes).motif is None


EVALUATION_FIELDS: dict[str, Any] = {
    "source": ThresholdSource.LOCAL,
    "local_unavailability": Unavailability.ABSENT,
    "reference": 0.08,
    "threshold": 0.02,
    "base": _target(0.10),
    "candidate": _target(0.06),
    "raw": _target(0.12),
    "gain": G1,
    "raw_gain": R1,
    "base_effort": FREE_BASE,
    "candidate_effort": FREE_CANDIDATE,
}


@pytest.mark.parametrize(
    ("name", "value"), list(EVALUATION_FIELDS.items()), ids=list(EVALUATION_FIELDS)
)
def test_not_evaluable_carries_no_evaluation_field(name: str, value: Any) -> None:
    """Invariant 2 : un motif exclut source, motif de la locale, ``F``, seuil, cibles,
    gains et efforts."""
    _raises(
        P2,
        "une performance non évaluable (multi_outing) n'a ni source, ni motif de la "
        "locale, ni F, ni seuil, ni cible, ni gain, ni effort.",
        **{name: value},
    )


NOT_CLASSIFIED = (
    "une performance non classée (motif de comparabilité) n'a ni « comparable » ni "
    "durée projetée."
)
COMPARABLE = (
    "une performance comparable a un D+/km dans [50.0 ; 110.0] et une durée projetée "
    "d'au plus 14400.0 s (D10.3)."
)
EVALUABLE_FIELDS = (
    "une performance évaluable porte source, seuil et les cibles de (0), de (1) et de "
    "v0 brut."
)
PERFORMANCE_VIOLATIONS: list[tuple[str, dict[str, Any]]] = [
    # 1. les sorties
    ("outing_ids doit être une séquence immuable", {"outing_ids": ["s-0302"]}),
    ("outing_ids ne doit pas être vide.", {"outing_ids": ()}),
    ("outing_ids[0] ne doit pas être vide.", {"outing_ids": ("",)}),
    ("outing_ids[1] ne doit pas être vide.", {"outing_ids": ("s-0302", " ")}),
    (
        "les sorties d'une performance sont distinctes.",
        {"outing_ids": ("s-0302", "s-0302")},
    ),
    # 3. évaluable : les champs exigés
    *[
        (EVALUABLE_FIELDS, {name: None})
        for name in ("source", "threshold", "base", "candidate", "raw")
    ],
    # 3. la source et sa valeur
    (
        "une source fixed porte une valeur de référence si et seulement si elle n'est "
        "pas « fixed », reçu 0.08.",
        {"source": ThresholdSource.FIXED},
    ),
    (
        "une source local porte une valeur de référence si et seulement si",
        {"reference": None, "threshold": GAIN_FLOOR},
    ),
    (
        "une source borrowed porte une valeur de référence si et seulement si",
        BORROWED_SOURCE | {"reference": None, "threshold": GAIN_FLOOR},
    ),
    ("reference doit être >= 0, reçu -0.08.", {"reference": -0.08}),
    ("reference doit être fini", {"reference": math.nan}),
    ("reference doit être fini", {"reference": math.inf}),
    (
        "une référence locale utilisée n'a pas de motif d'indisponibilité.",
        {"local_unavailability": Unavailability.ABSENT},
    ),
    # 3. le seuil
    (
        "threshold doit valoir max(0.01 ; 0.25·F) = 0.02, reçu 0.08 (D10.3).",
        {"threshold": 0.08},
    ),
    (
        "threshold doit valoir max(0.01 ; 0.25·F) = 0.02, reçu",
        {"threshold": math.nextafter(0.02, 1.0)},
    ),
    (
        "threshold doit valoir max(0.01 ; 0.25·F) = 0.01, reçu 0.005 (D10.3).",
        {"reference": 0.02, "threshold": 0.005},
    ),
    (
        "threshold doit valoir max(0.01 ; 0.25·F) = 0.01, reçu 0.005 (D10.3).",
        FIXED_SOURCE | {"threshold": 0.005},
    ),
    # 3. les gains
    (f"gain doit valoir {G1!r}, reçu 0.05.", {"gain": 0.05}),
    (f"gain doit valoir {G1!r}, reçu None.", {"gain": None}),
    (
        "gain est absent quand une des deux cibles l'est.",
        {"candidate": MISSING, "raw_gain": None},
    ),
    ("gain est absent quand une des deux cibles l'est.", {"base": MISSING}),
    (f"raw_gain doit valoir {R1!r}, reçu 0.05.", {"raw_gain": 0.05}),
    ("raw_gain est absent quand une des deux cibles l'est.", {"raw": MISSING}),
    (
        "raw_gain est absent quand une des deux cibles l'est.",
        {"candidate": MISSING, "gain": None},
    ),
    # 4. la classification
    ("dplus_per_km doit être fini", {"dplus_per_km": math.nan}),
    ("dplus_per_km doit être >= 0, reçu -1.0.", {"dplus_per_km": -1.0}),
    ("projected_s doit être fini", {"projected_s": math.inf}),
    ("projected_s doit être >= 0, reçu -1.0.", {"projected_s": -1.0}),
    (NOT_CLASSIFIED, {"comparable_unavailability": Unavailability.MODEL_ERROR}),
    (
        NOT_CLASSIFIED,
        {"comparable_unavailability": Unavailability.MODEL_ERROR, "comparable": None},
    ),
    (
        NOT_CLASSIFIED,
        {
            "comparable_unavailability": Unavailability.MODEL_ERROR,
            "comparable": False,
            "projected_s": None,
        },
    ),
    (COMPARABLE, {"dplus_per_km": 49.9}),
    (COMPARABLE, {"dplus_per_km": 110.1}),
    (COMPARABLE, {"projected_s": 14400.1}),
    (COMPARABLE, {"dplus_per_km": None}),
    (COMPARABLE, {"projected_s": None}),
    (
        "une référence empruntée ne sert qu'à une performance comparable (D10.3).",
        BORROWED_SOURCE | {"comparable": False},
    ),
    (
        "une référence empruntée ne sert qu'à une performance comparable (D10.3).",
        BORROWED_SOURCE | {"comparable": None},
    ),
]


@pytest.mark.parametrize(("fragment", "changes"), PERFORMANCE_VIOLATIONS)
def test_performance_assessment_invariants(
    fragment: str, changes: dict[str, Any]
) -> None:
    """Invariants 1, 3 et 4 de ``PerformanceAssessment`` : une violation chacun, sur
    la performance évaluable locale."""
    _raises(P1, fragment, **changes)


def test_classification_applies_to_a_not_evaluable_performance() -> None:
    """Invariant 4 : la classification vaut aussi sans évaluation ; D+/km et durée
    projetée finis et ``>= 0`` même hors de « comparable », nuls acceptés."""
    _raises(P2, NOT_CLASSIFIED, comparable_unavailability=Unavailability.MODEL_ERROR)
    _raises(P2, COMPARABLE, comparable=True)
    _raises(P2, "projected_s doit être >= 0, reçu -1.0.", projected_s=-1.0)
    _raises(P2, "dplus_per_km doit être fini", dplus_per_km=math.inf)
    flat = replace(P2, dplus_per_km=0.0, projected_s=0.0)
    assert (flat.dplus_per_km, flat.projected_s) == (0.0, 0.0)
    unclassified = replace(
        P2,
        comparable=None,
        comparable_unavailability=Unavailability.MODEL_ERROR,
        projected_s=None,
    )
    assert unclassified.comparable is None


# ---------------------------------------------------------------------------
# GuardValue (D10.4)
# ---------------------------------------------------------------------------

GUARD_VALUE = GuardValue(
    civil_date=D1,
    base=MetricValue(0.03, None, 4),
    candidate=MetricValue(0.04, None, 4),
    harm=0.04 - 0.03,
    source=ThresholdSource.LOCAL,
    local_unavailability=None,
    reference=0.08,
    threshold=0.008,
)
"""Un garde-fou local : ``η = 0,10·F = 0,008``, ``H = candidate − base``."""


def test_valid_guard_values() -> None:
    """D10.4 : ``H = (q^(1) − q^(0))_+``, nul quand le candidat est meilleur ou égal ;
    seuil plancher ; sources fixe et empruntée ; ``H`` absent quand une valeur
    manque."""
    assert GUARD_VALUE.harm == 0.04 - 0.03
    better = replace(GUARD_VALUE, candidate=MetricValue(0.02, None, 4), harm=0.0)
    assert better.harm == 0.0
    equal = replace(GUARD_VALUE, candidate=MetricValue(0.03, None, 4), harm=0.0)
    assert equal.harm == 0.0
    floor = replace(GUARD_VALUE, reference=0.02, threshold=HARM_FLOOR)
    assert floor.threshold == HARM_FLOOR
    fixed = replace(
        GUARD_VALUE,
        source=ThresholdSource.FIXED,
        local_unavailability=Unavailability.ABSENT,
        reference=None,
        threshold=HARM_FLOOR,
    )
    assert fixed.reference is None
    borrowed = replace(
        GUARD_VALUE,
        source=ThresholdSource.BORROWED,
        local_unavailability=Unavailability.ABSENT,
    )
    assert borrowed.threshold == 0.008
    assert replace(GUARD_VALUE, candidate=MISSING, harm=None).harm is None
    assert replace(GUARD_VALUE, base=MISSING, harm=None).harm is None


HARM = "harm doit valoir max(0, candidate − base) ="


@pytest.mark.parametrize(
    ("fragment", "changes"),
    [
        (
            "threshold doit valoir max(0.005 ; 0.1·F) = 0.008, reçu 0.08 (D10.4).",
            {"threshold": 0.08},
        ),
        (
            "threshold doit valoir max(0.005 ; 0.1·F) = 0.005, reçu 0.002 (D10.4).",
            {"reference": 0.02, "threshold": 0.002},
        ),
        (
            "threshold doit valoir max(0.005 ; 0.1·F) = 0.005, reçu 0.01 (D10.4).",
            {"source": ThresholdSource.FIXED, "reference": None, "threshold": 0.01},
        ),
        (f"{HARM} {0.04 - 0.03!r}, reçu 0.02 (D10.4).", {"harm": 0.02}),
        (f"{HARM} {0.04 - 0.03!r}, reçu None (D10.4).", {"harm": None}),
        (
            f"{HARM} 0.0, reçu {0.02 - 0.03!r} (D10.4).",
            {"candidate": MetricValue(0.02, None, 4), "harm": 0.02 - 0.03},
        ),
        ("harm est absent quand une des deux valeurs l'est.", {"base": MISSING}),
        ("harm est absent quand une des deux valeurs l'est.", {"candidate": MISSING}),
        (
            "une source fixed porte une valeur de référence si et seulement si",
            {"source": ThresholdSource.FIXED},
        ),
        (
            "une source local porte une valeur de référence si et seulement si",
            {"reference": None, "threshold": HARM_FLOOR},
        ),
        (
            "une source borrowed porte une valeur de référence si et seulement si",
            {
                "source": ThresholdSource.BORROWED,
                "local_unavailability": Unavailability.ABSENT,
                "reference": None,
                "threshold": HARM_FLOOR,
            },
        ),
        ("reference doit être >= 0, reçu -0.01.", {"reference": -0.01}),
        ("reference doit être fini", {"reference": math.nan}),
        (
            "une référence locale utilisée n'a pas de motif d'indisponibilité.",
            {"local_unavailability": Unavailability.ABSENT},
        ),
    ],
)
def test_guard_value_invariants(fragment: str, changes: dict[str, Any]) -> None:
    """``GuardValue`` : seuil ``max(0,005 ; 0,10·F)``, ``H = max(0, candidate − base)``
    ou absent, source et valeur accordées."""
    _raises(GUARD_VALUE, fragment, **changes)


# ---------------------------------------------------------------------------
# GuardOutcome (D10.4)
# ---------------------------------------------------------------------------


def _harm(day: date, harm: float | None) -> GuardValue:
    """Un garde-fou au seuil fixe (``η = 0,005``) : base nulle, candidat ``H`` (absent :
    en erreur du modèle), donc ``H_jk = harm``."""
    candidate = MISSING if harm is None else MetricValue(harm, None, 3)
    return GuardValue(
        day,
        MetricValue(0.0, None, 3),
        candidate,
        harm,
        ThresholdSource.FIXED,
        Unavailability.ABSENT,
        None,
        HARM_FLOOR,
    )


def _guard(
    metric: ExperimentMetric, values: tuple[GuardValue, ...], status: GuardStatus
) -> GuardOutcome:
    """Un garde-fou de l'expérience, moyennes ``fsum(…) / |J_k|``, l'état donné."""
    harms = [value.harm for value in values if value.harm is not None]
    count = len(values)
    mean_harm = math.fsum(harms) / count if count and len(harms) == count else None
    thresholds = [value.threshold for value in values]
    mean_threshold = math.fsum(thresholds) / count if count else None
    return GuardOutcome(metric, values, mean_harm, mean_threshold, status)


def test_guard_outcome_means_are_fsum_over_j_k() -> None:
    """D10.4 : ``moyenne_{J_k} H`` et ``moyenne_{J_k} η`` ; ``mean_harm`` absente si un
    ``H`` manque, les deux absentes si ``J_k`` est vide."""
    values = (_harm(D1, 0.0), _harm(D3, 0.01))
    outcome = GuardOutcome(M.ASCENT_LEVEL, values, 0.005, 0.005, GuardStatus.SATISFIED)
    assert (outcome.mean_harm, outcome.mean_threshold) == (0.005, 0.005)
    unavailable = GuardOutcome(
        M.ASCENT_LEVEL,
        (_harm(D1, 0.0), _harm(D3, None)),
        None,
        0.005,
        GuardStatus.UNAVAILABLE,
    )
    assert unavailable.mean_harm is None
    empty = GuardOutcome(M.ASCENT_LEVEL, (), None, None, GuardStatus.NOT_EVALUABLE)
    assert empty.values == ()


GUARD_CASES = [
    pytest.param((), GuardStatus.NOT_EVALUABLE, id="empty"),
    pytest.param(
        (_harm(D1, 0.0), _harm(D3, None)), GuardStatus.UNAVAILABLE, id="harm-missing"
    ),
    pytest.param(
        (_harm(D1, 0.004), _harm(D3, 0.006)), GuardStatus.SATISFIED, id="satisfied"
    ),
    pytest.param(
        (_harm(D1, 0.009), _harm(D3, 0.009)), GuardStatus.VIOLATED, id="mean-alone"
    ),
    pytest.param(
        (_harm(D1, 0.0), _harm(D2, 0.0), _harm(D3, 0.011)),
        GuardStatus.VIOLATED,
        id="peak-alone",
    ),
    pytest.param(
        (_harm(D1, 0.0), _harm(D2, 0.0), _harm(D3, PEAK + 0.5e-6)),
        GuardStatus.SATISFIED,
        id="peak-within-eps",
    ),
    pytest.param(
        (_harm(D1, 0.0), _harm(D2, 0.0), _harm(D3, PEAK + 2e-6)),
        GuardStatus.VIOLATED,
        id="peak-beyond-eps",
    ),
    pytest.param(
        (_harm(D1, ETA + 0.5e-6), _harm(D3, ETA + 0.5e-6)),
        GuardStatus.SATISFIED,
        id="mean-within-eps",
    ),
    pytest.param(
        (_harm(D1, ETA + 2e-6), _harm(D3, ETA + 2e-6)),
        GuardStatus.VIOLATED,
        id="mean-beyond-eps",
    ),
]


@pytest.mark.parametrize(("values", "status"), GUARD_CASES)
def test_guard_outcome_status_is_recomputed(
    values: tuple[GuardValue, ...], status: GuardStatus
) -> None:
    """D10.4 : non évaluable sans valeur, indisponible si un ``H`` manque, sinon
    satisfait si et seulement si ``H̄ <= η̄ + ε`` et ``H <= 2η + ε`` partout — dépassé
    par la moyenne seule, ou par un seul ``H`` ; tout autre état est refusé."""
    outcome = _guard(M.ASCENT_LEVEL, values, status)
    assert outcome.status is status
    for other in GuardStatus:
        if other is not status:
            _raises(
                outcome,
                f"le garde-fou ascent_level est {status}, reçu {other} (D10.4).",
                status=other,
            )


GUARD_SATISFIED = _guard(
    M.ASCENT_LEVEL, (_harm(D1, 0.0), _harm(D3, 0.01)), GuardStatus.SATISFIED
)
GUARD_UNAVAILABLE = _guard(
    M.ASCENT_LEVEL, (_harm(D1, 0.0), _harm(D3, None)), GuardStatus.UNAVAILABLE
)
GUARD_EMPTY = _guard(M.ASCENT_LEVEL, (), GuardStatus.NOT_EVALUABLE)
MEANS = "les moyennes du garde-fou ascent_level valent fsum(…) / |J_k| :"


@pytest.mark.parametrize(
    ("outcome", "fragment", "changes"),
    [
        (
            GUARD_SATISFIED,
            f"{MEANS} 0.005 et 0.005, reçu 0.004 et 0.005.",
            {"mean_harm": 0.004},
        ),
        (
            GUARD_SATISFIED,
            f"{MEANS} 0.005 et 0.005, reçu 0.005 et 0.006.",
            {"mean_threshold": 0.006},
        ),
        (
            GUARD_SATISFIED,
            f"{MEANS} 0.005 et 0.005, reçu None et 0.005.",
            {"mean_harm": None},
        ),
        (
            GUARD_SATISFIED,
            f"{MEANS} 0.005 et 0.005, reçu 0.005 et None.",
            {"mean_threshold": None},
        ),
        (
            GUARD_UNAVAILABLE,
            f"{MEANS} None et 0.005, reçu 0.0 et 0.005.",
            {"mean_harm": 0.0},
        ),
        (GUARD_EMPTY, f"{MEANS} None et None, reçu 0.0 et None.", {"mean_harm": 0.0}),
        (
            GUARD_EMPTY,
            f"{MEANS} None et None, reçu None et 0.005.",
            {"mean_threshold": 0.005},
        ),
        (
            GUARD_SATISFIED,
            "values doit être strictement croissant par jour.",
            {"values": (_harm(D3, 0.01), _harm(D1, 0.0))},
        ),
        (
            GUARD_SATISFIED,
            "values doit être strictement croissant par jour.",
            {"values": (_harm(D1, 0.0), _harm(D1, 0.01))},
        ),
        (
            GUARD_SATISFIED,
            "values doit être une séquence immuable",
            {"values": list(GUARD_SATISFIED.values)},
        ),
    ],
)
def test_guard_outcome_invariants(
    outcome: GuardOutcome, fragment: str, changes: dict[str, Any]
) -> None:
    """``GuardOutcome`` : un tuple de jours strictement croissants ; moyennes
    recalculées, présentes et absentes à leur place."""
    _raises(outcome, fragment, **changes)


# ---------------------------------------------------------------------------
# PassageValue, PassageGuardOutcome (D10.4)
# ---------------------------------------------------------------------------

PASSAGE = PassageValue(D1, 2, 0.004)


def test_valid_passage_values() -> None:
    """D10.4 : au moins un passage comparable ; ``worst`` nul, positif ou absent."""
    assert replace(PASSAGE, passages=1).passages == 1
    assert replace(PASSAGE, worst=0.0).worst == 0.0
    assert replace(PASSAGE, worst=None).worst is None


@pytest.mark.parametrize(
    ("fragment", "changes"),
    [
        ("passages doit être >= 1, reçu 0.", {"passages": 0}),
        ("passages doit être >= 1, reçu -1.", {"passages": -1}),
        ("worst doit être fini", {"worst": math.nan}),
        ("worst doit être fini", {"worst": math.inf}),
        ("worst doit être >= 0, reçu -1e-09.", {"worst": -1e-9}),
    ],
)
def test_passage_value_invariants(fragment: str, changes: dict[str, Any]) -> None:
    _raises(PASSAGE, fragment, **changes)


PASSAGE_CASES = [
    pytest.param((), GuardStatus.NOT_EVALUABLE, id="empty"),
    pytest.param(
        (PassageValue(D1, 1, None), PassageValue(D3, 2, 0.0)),
        GuardStatus.UNAVAILABLE,
        id="worst-missing",
    ),
    pytest.param(
        (PassageValue(D1, 1, 0.0), PassageValue(D3, 2, PASSAGE_TOLERANCE + 0.5e-6)),
        GuardStatus.SATISFIED,
        id="within-eps",
    ),
    pytest.param(
        (PassageValue(D1, 1, 0.0), PassageValue(D3, 2, 0.0101)),
        GuardStatus.VIOLATED,
        id="beyond-one-percent",
    ),
]


@pytest.mark.parametrize(("values", "status"), PASSAGE_CASES)
def test_passage_guard_status_is_recomputed(
    values: tuple[PassageValue, ...], status: GuardStatus
) -> None:
    """D10.4 : non évaluable sans valeur, indisponible si un ``worst`` manque, sinon
    satisfait si et seulement si chaque ``worst <= 1 % + ε`` ; tout autre état est
    refusé."""
    outcome = PassageGuardOutcome(values, status)
    assert outcome.status is status
    for other in GuardStatus:
        if other is not status:
            _raises(
                outcome,
                f"le garde-fou des passages est {status}, reçu {other} (D10.4).",
                status=other,
            )


def test_passage_guard_outcome_form() -> None:
    """Un tuple, de jours strictement croissants."""
    outcome = PassageGuardOutcome((PASSAGE,), GuardStatus.SATISFIED)
    _raises(outcome, "values doit être une séquence immuable", values=[PASSAGE])
    later = PassageValue(D3, 1, 0.0)
    _raises(
        outcome,
        "values doit être strictement croissant par jour.",
        values=(later, PASSAGE),
    )
    _raises(
        outcome,
        "values doit être strictement croissant par jour.",
        values=(PASSAGE, PASSAGE),
    )


# ---------------------------------------------------------------------------
# ReviewReason, FailedCheck (D10.2 à D10.4 ; P13)
# ---------------------------------------------------------------------------

TARGET_MISSING = ReviewReason(ReviewCause.TARGET_UNAVAILABLE, None, (D1,))
GUARD_MISSING = ReviewReason(ReviewCause.GUARD_UNAVAILABLE, M.FLAT_LEVEL, (D1, D3))
PASSAGES_MISSING = ReviewReason(ReviewCause.PASSAGES_UNAVAILABLE, None, (D3,))
NOT_APPLICABLE = ReviewReason(ReviewCause.PASSAGES_NOT_APPLICABLE, None, ())


def test_valid_review_reasons() -> None:
    """Une métrique pour un garde-fou indisponible seulement ; des jours, sauf pour
    l'absence de passage comparable."""
    assert GUARD_MISSING.metric is M.FLAT_LEVEL
    assert NOT_APPLICABLE.days == ()
    assert TARGET_MISSING.days == (D1,)
    assert PASSAGES_MISSING.metric is None


@pytest.mark.parametrize(
    ("reason", "fragment", "changes"),
    [
        (
            TARGET_MISSING,
            "une cause target_unavailable nomme une métrique si et seulement si elle "
            "est guard_unavailable.",
            {"metric": M.FLAT_LEVEL},
        ),
        (
            NOT_APPLICABLE,
            "une cause passages_not_applicable nomme une métrique si et seulement si",
            {"metric": M.LEVEL},
        ),
        (
            GUARD_MISSING,
            "une cause guard_unavailable nomme une métrique si et seulement si elle "
            "est guard_unavailable.",
            {"metric": None},
        ),
        (
            TARGET_MISSING,
            "une cause target_unavailable nomme ses jours.",
            {"days": ()},
        ),
        (
            GUARD_MISSING,
            "une cause guard_unavailable nomme ses jours.",
            {"days": ()},
        ),
        (
            PASSAGES_MISSING,
            "une cause passages_unavailable nomme ses jours.",
            {"days": ()},
        ),
        (
            NOT_APPLICABLE,
            "une cause passages_not_applicable ne nomme pas de jour.",
            {"days": (D1,)},
        ),
        (GUARD_MISSING, "days doit être une séquence immuable", {"days": [D1, D3]}),
        (
            GUARD_MISSING,
            "days doit être strictement croissant par jour.",
            {"days": (D3, D1)},
        ),
        (
            GUARD_MISSING,
            "days doit être strictement croissant par jour.",
            {"days": (D1, D1)},
        ),
    ],
)
def test_review_reason_invariants(
    reason: ReviewReason, fragment: str, changes: dict[str, Any]
) -> None:
    _raises(reason, fragment, **changes)


MEAN_GAIN_FAILS = FailedCheck(FailedCondition.MEAN_GAIN, None, ())
VOTE_FAILS = FailedCheck(FailedCondition.VOTE, None, ())
LOSS_FAILS = FailedCheck(FailedCondition.LOSS, None, (D1, D3))
GUARD_FAILS = FailedCheck(FailedCondition.GUARD, M.ASCENT_LEVEL, (D1,))
GUARD_MEAN_FAILS = FailedCheck(FailedCondition.GUARD, M.FLAT_LEVEL, ())
PASSAGES_FAIL = FailedCheck(FailedCondition.PASSAGES, None, (D3,))


def test_valid_failed_checks() -> None:
    """P13 : ni jour ni métrique pour le gain moyen et le vote ; un garde-fou dépassé
    par sa seule moyenne ne nomme aucun jour."""
    assert MEAN_GAIN_FAILS.days == ()
    assert VOTE_FAILS.days == ()
    assert LOSS_FAILS.days == (D1, D3)
    assert GUARD_FAILS.metric is M.ASCENT_LEVEL
    assert GUARD_MEAN_FAILS.days == ()
    assert PASSAGES_FAIL.days == (D3,)


@pytest.mark.parametrize(
    ("check", "fragment", "changes"),
    [
        (
            MEAN_GAIN_FAILS,
            "une condition mean_gain nomme une métrique si et seulement si elle est "
            "guard.",
            {"metric": M.LEVEL},
        ),
        (
            LOSS_FAILS,
            "une condition loss nomme une métrique si et seulement si elle est guard.",
            {"metric": M.LEVEL},
        ),
        (
            GUARD_FAILS,
            "une condition guard nomme une métrique si et seulement si elle est guard.",
            {"metric": None},
        ),
        (
            MEAN_GAIN_FAILS,
            "la condition mean_gain ne nomme pas de jour.",
            {"days": (D1,)},
        ),
        (VOTE_FAILS, "la condition vote ne nomme pas de jour.", {"days": (D1,)}),
        (LOSS_FAILS, "la condition loss nomme ses jours.", {"days": ()}),
        (PASSAGES_FAIL, "la condition passages nomme ses jours.", {"days": ()}),
        (LOSS_FAILS, "days doit être une séquence immuable", {"days": [D1, D3]}),
        (
            LOSS_FAILS,
            "days doit être strictement croissant par jour.",
            {"days": (D3, D1)},
        ),
        (
            GUARD_FAILS,
            "days doit être strictement croissant par jour.",
            {"days": (D1, D1)},
        ),
    ],
)
def test_failed_check_invariants(
    check: FailedCheck, fragment: str, changes: dict[str, Any]
) -> None:
    _raises(check, fragment, **changes)


# ---------------------------------------------------------------------------
# Admission (D10.2 à D10.6) : une admission minimale cohérente, puis ses variantes
# ---------------------------------------------------------------------------


def _guards(
    *outcomes: GuardOutcome, target: ExperimentMetric = M.DESCENT_LEVEL
) -> tuple[GuardOutcome, ...]:
    """Les garde-fous de ``GUARD_METRICS`` sans la cible, dans cet ordre : ceux donnés,
    les autres non évaluables (``J_k`` vide)."""
    given = {outcome.metric: outcome for outcome in outcomes}
    return tuple(
        given.get(metric, _guard(metric, (), GuardStatus.NOT_EVALUABLE))
        for metric in GUARD_METRICS
        if metric is not target
    )


LEVEL_OK = _guard(M.LEVEL, (_harm(D1, 0.0), _harm(D3, 0.0)), GuardStatus.SATISFIED)
PASSAGES_OK = PassageGuardOutcome((PassageValue(D1, 2, 0.0),), GuardStatus.SATISFIED)
NO_PASSAGES = PassageGuardOutcome((), GuardStatus.NOT_EVALUABLE)
SENSITIVITY = (AdmissionReserve.SENSITIVITY_REMAINING,)
MEAN_THRESHOLD = math.fsum((0.02, GAIN_FLOOR)) / 2


def _admission(**changes: Any) -> Admission:
    """L'admission minimale : cible ``descent_level``, trois performances (deux
    évaluables, une non évaluable), ``|L|`` satisfait, un passage comparable ;
    candidat provisoire."""
    fields: dict[str, Any] = {
        "target": M.DESCENT_LEVEL,
        "clock": CLOCKS[0],
        "performances": (P1, P2, P3),
        "evaluable": 2,
        "mean_gain": math.fsum((G1, G3)) / 2,
        "mean_threshold": MEAN_THRESHOLD,
        "positive": 2,
        "required": 2,
        "mean_raw_gain": math.fsum((R1, R3)) / 2,
        "raw_gains": 2,
        "guards": _guards(LEVEL_OK),
        "passages": PASSAGES_OK,
        "review": (),
        "failures": (),
        "verdict": AdmissionVerdict.PROVISIONAL,
        "reserves": SENSITIVITY,
    }
    return Admission(**(fields | changes))


ADMISSION = _admission()

# Rejeté : les cinq conditions échouent, dans l'ordre de la règle.
P3_LOSS = _performance(D3, 0.05, 0.10, 0.09, **FIXED_SOURCE)
"""``G = −0,05 < −δ − ε`` : une perte."""
ASCENT_PEAK = _guard(M.ASCENT_LEVEL, (_harm(D1, 0.011),), GuardStatus.VIOLATED)
"""Dépassé par ``H > 2η`` le 2 mars."""
FLAT_MEAN = _guard(
    M.FLAT_LEVEL, (_harm(D1, 0.009), _harm(D3, 0.009)), GuardStatus.VIOLATED
)
"""Dépassé par sa seule moyenne."""
PASSAGES_BAD = PassageGuardOutcome(
    (PassageValue(D1, 1, 0.0101), PassageValue(D3, 2, 0.005)), GuardStatus.VIOLATED
)
FAILURES = (
    MEAN_GAIN_FAILS,
    VOTE_FAILS,
    FailedCheck(FailedCondition.LOSS, None, (D3,)),
    FailedCheck(FailedCondition.GUARD, M.ASCENT_LEVEL, (D1,)),
    FailedCheck(FailedCondition.GUARD, M.FLAT_LEVEL, ()),
    FailedCheck(FailedCondition.PASSAGES, None, (D1,)),
)
REJECTED = _admission(
    performances=(P1, P2, P3_LOSS),
    mean_gain=math.fsum((G1, 0.05 - 0.10)) / 2,
    positive=1,
    mean_raw_gain=math.fsum((R1, 0.09 - 0.10)) / 2,
    guards=_guards(LEVEL_OK, ASCENT_PEAK, FLAT_MEAN),
    passages=PASSAGES_BAD,
    failures=FAILURES,
    verdict=AdmissionVerdict.REJECTED,
)

# À revoir : la cible de (1) en erreur le 16 mars, |L| aussi, aucun passage.
P3_MISSING = _performance(D3, 0.08, None, 0.09, **FIXED_SOURCE)
LEVEL_MISSING = _guard(
    M.LEVEL, (_harm(D1, 0.0), _harm(D3, None)), GuardStatus.UNAVAILABLE
)
REVIEW = (
    ReviewReason(ReviewCause.TARGET_UNAVAILABLE, None, (D3,)),
    ReviewReason(ReviewCause.GUARD_UNAVAILABLE, M.LEVEL, (D3,)),
    NOT_APPLICABLE,
)
TO_REVIEW = _admission(
    performances=(P1, P2, P3_MISSING),
    mean_gain=None,
    positive=1,
    mean_raw_gain=None,
    raw_gains=1,
    guards=_guards(LEVEL_MISSING),
    passages=NO_PASSAGES,
    review=REVIEW,
    verdict=AdmissionVerdict.TO_REVIEW,
)

# Un gain de 1e−7 n'est pas un succès (décision E2) : le vote échoue.
P3_TINY = _performance(D3, 1e-7, 0.0, 0.0625, **FIXED_SOURCE)
TINY = _admission(
    performances=(P1, P2, P3_TINY),
    mean_gain=math.fsum((G1, 1e-7)) / 2,
    positive=1,
    mean_raw_gain=math.fsum((R1, 0.0625)) / 2,
    failures=(VOTE_FAILS,),
    verdict=AdmissionVerdict.REJECTED,
)

# Cible q_usage : seuil fixe partout, sans motif de la locale ; les sept garde-fous.
USAGE = _admission(
    target=M.USAGE,
    performances=(
        replace(P1, **(FIXED_SOURCE | {"local_unavailability": None})),
        P2,
        replace(P3, local_unavailability=None),
    ),
    mean_threshold=math.fsum((GAIN_FLOOR, GAIN_FLOOR)) / 2,
    guards=_guards(LEVEL_OK, target=M.USAGE),
)

# Réserves cumulées : (0) saturé le 2 mars, (1) le 16 mars.
SATURATED = _admission(
    performances=(
        replace(P1, base_effort=SATURATED_LOW),
        P2,
        replace(P3, candidate_effort=SATURATED_HIGH),
    ),
    reserves=(
        AdmissionReserve.COMPARATOR_SATURATED,
        AdmissionReserve.CANDIDATE_SATURATED,
        AdmissionReserve.SENSITIVITY_REMAINING,
    ),
)


def test_valid_minimal_admission() -> None:
    """D10.2 à D10.6 : deux évaluables sur trois, ``⌈3·2/4⌉ = 2`` succès, ``|L|`` sur
    les deux, six garde-fous (la cible retirée), un passage : candidat provisoire,
    réserve de sensibilité seule."""
    assert ADMISSION.evaluable == 2
    assert ADMISSION.required == 2
    assert ADMISSION.mean_threshold == 0.015
    assert [guard.metric for guard in ADMISSION.guards] == [
        M.LEVEL,
        M.ASCENT_LEVEL,
        M.FLAT_LEVEL,
        M.ASCENT_DISPERSION,
        M.FLAT_DISPERSION,
        M.DESCENT_DISPERSION,
    ]
    assert ADMISSION.verdict is AdmissionVerdict.PROVISIONAL
    assert ADMISSION.reserves == SENSITIVITY


def test_valid_rejected_admission_lists_every_failure_in_order() -> None:
    """P13 : gain moyen, vote, perte, garde-fous (par ``H > 2η`` ou par la moyenne
    seule), passages — dans cet ordre ; rien à revoir : rejeté."""
    assert REJECTED.review == ()
    assert REJECTED.failures == FAILURES
    assert REJECTED.verdict is AdmissionVerdict.REJECTED


def test_valid_admission_to_review() -> None:
    """D10.2, D10.4 : cible manquante, ``|L|`` indisponible, aucun passage
    comparable ; le vote compte le gain absent (``1 + 1 >= 2``) : pas d'échec."""
    assert TO_REVIEW.review == REVIEW
    assert TO_REVIEW.failures == ()
    assert TO_REVIEW.verdict is AdmissionVerdict.TO_REVIEW


TO_REVIEW_WITH_FAILURES = replace(
    REJECTED,
    passages=NO_PASSAGES,
    review=(NOT_APPLICABLE,),
    failures=FAILURES[:-1],
    verdict=AdmissionVerdict.TO_REVIEW,
)
"""Le rejeté sans passage comparable : à revoir, ses quatre premiers échecs publiés."""


def test_to_review_publishes_the_computable_failures() -> None:
    """P13 : sous « à revoir », les conditions calculables qui échouent restent
    publiées (les passages, sans objet, n'échouent pas) ; le verdict reste « à
    revoir »."""
    assert TO_REVIEW_WITH_FAILURES.review == (NOT_APPLICABLE,)
    assert TO_REVIEW_WITH_FAILURES.failures == FAILURES[:-1]
    assert TO_REVIEW_WITH_FAILURES.verdict is AdmissionVerdict.TO_REVIEW


P1_NULL = _performance(D1, 0.06, 0.061)
"""``G = −0,001`` : ni un succès ni une perte."""
VOTE_REVIEW = replace(
    TO_REVIEW,
    performances=(P1_NULL, P2, P3_MISSING),
    positive=0,
    failures=(VOTE_FAILS,),
)


def test_vote_counts_the_absent_gains() -> None:
    """D10.3 : le vote échoue quand ``positive`` plus les gains absents reste sous
    ``required`` (``0 + 1 < 2``) ; il est publié sous « à revoir »."""
    assert VOTE_REVIEW.positive == 0
    assert VOTE_REVIEW.failures == (VOTE_FAILS,)
    assert VOTE_REVIEW.verdict is AdmissionVerdict.TO_REVIEW


def test_a_gain_of_1e_7_is_not_a_success() -> None:
    """Décision E2 : ``G = 1e−7 <= ε`` ne compte pas dans ``positive`` ; le vote
    échoue (``1 < 2``), sans perte ni gain moyen insuffisant : rejeté."""
    assert P3_TINY.gain == 1e-7
    assert TINY.positive == 1
    assert TINY.failures == (VOTE_FAILS,)
    _raises(
        TINY,
        "mean_threshold, mean_gain, positive, mean_raw_gain et raw_gains valent",
        positive=2,
    )


@pytest.mark.parametrize(
    ("gain", "failures"),
    [(GAIN_FLOOR - 0.5e-6, ()), (GAIN_FLOOR - 2e-6, (MEAN_GAIN_FAILS,))],
    ids=["within-eps", "beyond-eps"],
)
def test_mean_gain_is_compared_within_epsilon(
    gain: float, failures: tuple[FailedCheck, ...]
) -> None:
    """Invariant 7, décision E2 : le gain moyen échoue si ``Ḡ < δ̄ − ε`` ; deux seuils
    fixes (``δ̄ = 0,010``), deux gains égaux à ``δ̄ − 0,5e−6`` puis ``δ̄ − 2e−6``."""
    performances = (
        _performance(D1, gain, 0.0, **FIXED_SOURCE),
        P2,
        _performance(D3, gain, 0.0, **FIXED_SOURCE),
    )
    verdict = AdmissionVerdict.REJECTED if failures else AdmissionVerdict.PROVISIONAL
    admission = _admission(
        performances=performances,
        mean_gain=math.fsum((gain, gain)) / 2,
        mean_threshold=GAIN_FLOOR,
        mean_raw_gain=0.12,
        failures=failures,
        verdict=verdict,
    )
    assert admission.failures == failures


@pytest.mark.parametrize(
    ("loss", "failures"),
    [
        (0.02 + 0.5e-6, (VOTE_FAILS,)),
        (0.02 + 2e-6, (VOTE_FAILS, FailedCheck(FailedCondition.LOSS, None, (D1,)))),
    ],
    ids=["within-eps", "beyond-eps"],
)
def test_loss_is_compared_within_epsilon(
    loss: float, failures: tuple[FailedCheck, ...]
) -> None:
    """Invariant 7 : une perte si ``G_j < −δ_j − ε`` ; le 2 mars, ``δ = 0,02`` et
    ``G = −0,02 − 0,5e−6`` puis ``−0,02 − 2e−6`` (le vote échoue dans les deux
    cas, le gain moyen jamais)."""
    performances = (
        _performance(D1, 0.0, loss),
        P2,
        _performance(D3, 0.20, 0.05, **FIXED_SOURCE),
    )
    admission = _admission(
        performances=performances,
        mean_gain=math.fsum((-loss, 0.20 - 0.05)) / 2,
        positive=1,
        mean_raw_gain=math.fsum((0.12 - loss, 0.12 - 0.05)) / 2,
        failures=failures,
        verdict=AdmissionVerdict.REJECTED,
    )
    assert admission.failures == failures


def test_valid_usage_admission() -> None:
    """D10.3 : ``q_usage`` a le seuil fixe partout, sans motif de la locale ; ses
    garde-fous sont les sept de ``GUARD_METRICS``."""
    assert USAGE.mean_threshold == GAIN_FLOOR
    assert tuple(guard.metric for guard in USAGE.guards) == GUARD_METRICS


def test_borrowed_source_with_the_local_motif_is_accepted() -> None:
    """P6 : une source empruntée porte le motif de la locale."""
    borrowed = replace(P1, **BORROWED_SOURCE)
    admission = replace(ADMISSION, performances=(borrowed, P2, P3))
    assert admission.performances[0].source is ThresholdSource.BORROWED


@pytest.mark.parametrize(
    ("performances", "reserves"),
    [
        (
            (replace(P1, base_effort=SATURATED_LOW), P2, P3),
            (AdmissionReserve.COMPARATOR_SATURATED, *SENSITIVITY),
        ),
        (
            (P1, P2, replace(P3, candidate_effort=SATURATED_HIGH)),
            (AdmissionReserve.CANDIDATE_SATURATED, *SENSITIVITY),
        ),
        (SATURATED.performances, SATURATED.reserves),
        (
            (replace(P1, base_effort=None, candidate_effort=None), P2, P3),
            SENSITIVITY,
        ),
    ],
    ids=["comparator", "candidate", "both", "not-calibrated"],
)
def test_reserves_accumulate_in_order(
    performances: tuple[PerformanceAssessment, ...],
    reserves: tuple[AdmissionReserve, ...],
) -> None:
    """D10.5, décision E1 : comparateur saturé, puis candidat saturé, puis toujours la
    sensibilité restante ; un effort absent ne sature pas."""
    admission = replace(ADMISSION, performances=performances, reserves=reserves)
    assert admission.reserves == reserves


ADMISSION_VIOLATIONS: list[tuple[str, dict[str, Any]]] = [
    # 1. tuples, cible, performances
    *[
        (
            f"{name} doit être une séquence immuable",
            {name: list(getattr(ADMISSION, name))},
        )
        for name in ("performances", "guards", "review", "failures", "reserves")
    ],
    ("|L| n'est pas une cible (D10.1).", {"target": M.LEVEL}),
    ("performances ne doit pas être vide.", {"performances": ()}),
    (
        "performances doit être strictement croissant par jour.",
        {"performances": (P1, P3, P2)},
    ),
    (
        "performances doit être strictement croissant par jour.",
        {"performances": (P1, P1, P2, P3)},
    ),
    # 2. evaluable, required
    (
        "evaluable compte les performances évaluables, 2, reçu 3.",
        {"evaluable": 3},
    ),
    ("evaluable compte les performances évaluables, 2, reçu 1.", {"evaluable": 1}),
    *[
        (
            "une admission a au moins une performance évaluable (n = 0 : aucun "
            "document, un ÉCHEC « non évaluable », D10.2).",
            changes,
        )
        for changes in (
            {"performances": (P2,)},
            {"performances": (P2,), "evaluable": 0, "required": 0},
        )
    ],
    ("required vaut ⌈3n/4⌉ = 2, reçu 1 (D10.3).", {"required": 1}),
    ("required vaut ⌈3n/4⌉ = 2, reçu 3 (D10.3).", {"required": 3}),
    # 3. les sources
    (
        "q_usage a le seuil fixe pour toute performance, sans motif de la locale "
        "(D10.3), reçu local le 2026-03-02.",
        {"target": M.USAGE},
    ),
    (
        "le 2026-03-16, la source fixed porte le motif de la référence locale (P6).",
        {"performances": (P1, P2, replace(P3, local_unavailability=None))},
    ),
    (
        "le 2026-03-02, la source borrowed porte le motif de la référence locale (P6).",
        {
            "performances": (
                replace(P1, **(BORROWED_SOURCE | {"local_unavailability": None})),
                P2,
                P3,
            )
        },
    ),
    # 5. les garde-fous
    *[
        (
            "guards porte level, ascent_level, flat_level, ascent_dispersion, "
            "flat_dispersion, descent_dispersion, dans cet ordre (D10.4).",
            {"guards": guards},
        )
        for guards in (
            (ADMISSION.guards[1], ADMISSION.guards[0], *ADMISSION.guards[2:]),
            _guards(LEVEL_OK, target=M.USAGE),
            ADMISSION.guards[:-1],
        )
    ],
    (
        "le garde-fou ascent_level porte un jour non évaluable.",
        {
            "guards": _guards(
                LEVEL_OK,
                _guard(M.ASCENT_LEVEL, (_harm(D2, 0.0),), GuardStatus.SATISFIED),
            )
        },
    ),
    (
        "le garde-fou level porte un jour non évaluable.",
        {
            "guards": _guards(
                _guard(
                    M.LEVEL,
                    (_harm(D1, 0.0), _harm(D2, 0.0), _harm(D3, 0.0)),
                    GuardStatus.SATISFIED,
                )
            )
        },
    ),
    (
        "|L| est exigé sur toute performance évaluable (D10.4).",
        {"guards": _guards(_guard(M.LEVEL, (_harm(D1, 0.0),), GuardStatus.SATISFIED))},
    ),
    ("|L| est exigé sur toute performance évaluable (D10.4).", {"guards": _guards()}),
    (
        "le garde-fou des passages porte un jour non évaluable.",
        {
            "passages": PassageGuardOutcome(
                (PassageValue(D2, 1, 0.0),), GuardStatus.SATISFIED
            )
        },
    ),
]


@pytest.mark.parametrize(("fragment", "changes"), ADMISSION_VIOLATIONS)
def test_admission_invariants(fragment: str, changes: dict[str, Any]) -> None:
    """Invariants 1, 2, 3 et 5 de ``Admission`` : un champ remplacé à la fois sur
    l'admission minimale."""
    _raises(ADMISSION, fragment, **changes)


def test_usage_target_refuses_a_local_motif() -> None:
    """Invariant 3 : sous ``q_usage``, la source fixe ne porte pas le motif de la
    locale."""
    _raises(
        USAGE,
        "q_usage a le seuil fixe pour toute performance, sans motif de la locale "
        "(D10.3), reçu fixed le 2026-03-16.",
        performances=(USAGE.performances[0], P2, P3),
    )


LOCAL_GUARD: dict[str, Any] = {
    "source": ThresholdSource.LOCAL,
    "local_unavailability": None,
    "reference": 0.08,
    "threshold": 0.008,
}
BORROWED_GUARD: dict[str, Any] = LOCAL_GUARD | {
    "source": ThresholdSource.BORROWED,
    "local_unavailability": Unavailability.ABSENT,
}


def _ascent(*values: GuardValue) -> tuple[GuardOutcome, ...]:
    """Les garde-fous de l'admission minimale, ``ascent_level`` porté par
    ``values``."""
    outcome = _guard(M.ASCENT_LEVEL, values, GuardStatus.SATISFIED)
    return _guards(LEVEL_OK, outcome)


def test_guard_values_with_local_or_borrowed_sources_are_accepted() -> None:
    """Invariant 5 : une valeur locale sans motif, une valeur empruntée sur une
    performance comparable avec le motif de la locale."""
    guards = _ascent(
        replace(_harm(D1, 0.0), **LOCAL_GUARD),
        replace(_harm(D3, 0.0), **BORROWED_GUARD),
    )
    assert replace(ADMISSION, guards=guards).guards == guards


NOT_COMPARABLE = (P1, P2, replace(P3, comparable=False))
"""Le 16 mars n'est pas comparable (sa source est fixe : la cible l'accepte)."""
P6_GUARD = "porte le motif de la référence locale (P6)."


@pytest.mark.parametrize(
    ("fragment", "changes"),
    [
        (
            f"le 2026-03-02, la source fixed du garde-fou ascent_level {P6_GUARD}",
            {"guards": _ascent(replace(_harm(D1, 0.0), local_unavailability=None))},
        ),
        (
            f"le 2026-03-16, la source fixed du garde-fou level {P6_GUARD}",
            {
                "guards": _guards(
                    _guard(
                        M.LEVEL,
                        (
                            _harm(D1, 0.0),
                            replace(_harm(D3, 0.0), local_unavailability=None),
                        ),
                        GuardStatus.SATISFIED,
                    )
                )
            },
        ),
        (
            f"le 2026-03-02, la source borrowed du garde-fou ascent_level {P6_GUARD}",
            {
                "guards": _ascent(
                    replace(
                        _harm(D1, 0.0),
                        **(BORROWED_GUARD | {"local_unavailability": None}),
                    )
                )
            },
        ),
        *[
            (
                "le 2026-03-16, une référence empruntée du garde-fou ascent_level ne "
                "sert qu'à une performance comparable (D10.3, D10.4).",
                {
                    "performances": (P1, P2, replace(P3, comparable=comparable)),
                    "guards": _ascent(replace(_harm(D3, 0.0), **BORROWED_GUARD)),
                },
            )
            for comparable in (False, None)
        ],
    ],
)
def test_guard_value_sources_in_the_admission(
    fragment: str, changes: dict[str, Any]
) -> None:
    """Invariant 5 : une valeur de garde-fou de source autre que locale porte le motif
    de la locale (P6) ; une source empruntée demande une performance comparable."""
    _raises(ADMISSION, fragment, **changes)


REGIME_TARGETS = (M.DESCENT_LEVEL, M.ASCENT_DISPERSION)
COMMON_MOTIFS = (
    NonEvaluable.EXCLUDED,
    NonEvaluable.MULTI_OUTING,
    NonEvaluable.UNSCORED,
    NonEvaluable.NO_USAGE,
    NonEvaluable.NOT_CALIBRATED,
)
REGIME_MOTIFS = (
    NonEvaluable.INSUFFICIENT_SUPPORT,
    NonEvaluable.ZERO_TIME,
    NonEvaluable.UNDERREPRESENTED,
)
USAGE_MOTIFS = (NonEvaluable.PASSAGE_UNAVAILABLE,)


def test_motifs_are_split_between_common_regime_and_usage() -> None:
    """Les trois groupes de motifs couvrent l'énumération, sans recouvrement."""
    groups = (*COMMON_MOTIFS, *REGIME_MOTIFS, *USAGE_MOTIFS)
    assert sorted(groups) == sorted(NonEvaluable)
    assert len(set(groups)) == len(groups)


def _with_motif(
    target: ExperimentMetric, motif: NonEvaluable
) -> tuple[Admission, dict[str, Any]]:
    """L'admission valide de la cible (l'admission minimale, ou celle de
    ``q_usage``) et le remplacement qui donne le motif à la non évaluable du 9 mars."""
    not_evaluable = replace(P2, motif=motif)
    if target is M.USAGE:
        first, _, last = USAGE.performances
        return USAGE, {"performances": (first, not_evaluable, last)}
    return ADMISSION, {
        "target": target,
        "guards": _guards(LEVEL_OK, target=target),
        "performances": (P1, not_evaluable, P3),
    }


@pytest.mark.parametrize(
    ("target", "motif"),
    [
        *[(t, m) for t in REGIME_TARGETS for m in (*COMMON_MOTIFS, *REGIME_MOTIFS)],
        *[(M.USAGE, m) for m in (*COMMON_MOTIFS, *USAGE_MOTIFS)],
    ],
)
def test_motifs_of_the_target_are_accepted(
    target: ExperimentMetric, motif: NonEvaluable
) -> None:
    """Invariant 3 : sous une cible de régime, les motifs communs et ceux du support ;
    sous ``q_usage``, les motifs communs et l'élément de ``K`` indisponible."""
    admission, changes = _with_motif(target, motif)
    assert replace(admission, **changes).performances[1].motif is motif


@pytest.mark.parametrize(
    ("target", "motif"),
    [
        *[(t, m) for t in REGIME_TARGETS for m in USAGE_MOTIFS],
        *[(M.USAGE, m) for m in REGIME_MOTIFS],
    ],
)
def test_motifs_of_another_target_are_refused(
    target: ExperimentMetric, motif: NonEvaluable
) -> None:
    """Invariant 3 : ``passage_unavailable`` n'existe que pour ``q_usage`` ; support,
    temps nul et classe sous-représentée que pour une cible de régime (D10.2)."""
    admission, changes = _with_motif(target, motif)
    _raises(
        admission,
        f"le 2026-03-09, le motif {motif} n'existe pas pour la cible {target} (D10.2).",
        **changes,
    )


AGGREGATES = ("mean_threshold", "mean_gain", "positive", "mean_raw_gain", "raw_gains")


@pytest.mark.parametrize(
    ("admission", "changes"),
    [
        (ADMISSION, {"mean_threshold": 0.02}),
        (ADMISSION, {"mean_threshold": math.nextafter(MEAN_THRESHOLD, 1.0)}),
        (ADMISSION, {"mean_gain": None}),
        (ADMISSION, {"mean_gain": G1}),
        (ADMISSION, {"positive": 1}),
        (ADMISSION, {"mean_raw_gain": None}),
        (ADMISSION, {"mean_raw_gain": R1}),
        (ADMISSION, {"raw_gains": 1}),
        (TO_REVIEW, {"mean_gain": G1 / 2}),
        (TO_REVIEW, {"mean_raw_gain": R1 / 2}),
        (TO_REVIEW, {"raw_gains": 2}),
        (TO_REVIEW, {"positive": 2}),
        (TINY, {"positive": 2}),
    ],
)
def test_admission_aggregates_are_recomputed(
    admission: Admission, changes: dict[str, Any]
) -> None:
    """Invariant 4 : ``δ̄ = fsum(δ_j) / n`` ; ``Ḡ`` et la moyenne contre v0 brut,
    absentes si un gain manque ; ``positive = #{G_j > ε}`` ; ``raw_gains``."""
    expected = tuple(getattr(admission, name) for name in AGGREGATES)
    received = tuple(changes.get(name, getattr(admission, name)) for name in AGGREGATES)
    _raises(
        admission,
        f"mean_threshold, mean_gain, positive, mean_raw_gain et raw_gains valent "
        f"{expected!r}, reçu {received!r} (D10.3, D10.5).",
        **changes,
    )


PASSAGES_UNAVAILABLE = PassageGuardOutcome(
    (PassageValue(D1, 1, None),), GuardStatus.UNAVAILABLE
)
PASSAGES_REVIEW = ReviewReason(ReviewCause.PASSAGES_UNAVAILABLE, None, (D1,))


def test_passages_unavailable_is_a_review_cause() -> None:
    """D10.4 : une prévision manque à un passage comparable : ses jours, à la place
    de l'absence de passage comparable."""
    review = (*REVIEW[:2], PASSAGES_REVIEW)
    admission = replace(TO_REVIEW, passages=PASSAGES_UNAVAILABLE, review=review)
    assert admission.review == review


@pytest.mark.parametrize(
    ("admission", "expected", "changes"),
    [
        pytest.param(
            ADMISSION,
            (NOT_APPLICABLE,),
            {"passages": NO_PASSAGES},
            id="missing",
        ),
        pytest.param(
            ADMISSION,
            (),
            {"review": (ReviewReason(ReviewCause.TARGET_UNAVAILABLE, None, (D1,)),)},
            id="extra",
        ),
        pytest.param(
            TO_REVIEW,
            REVIEW,
            {"review": (REVIEW[1], REVIEW[0], REVIEW[2])},
            id="order",
        ),
        pytest.param(
            TO_REVIEW,
            REVIEW,
            {"review": (REVIEW[2], REVIEW[0], REVIEW[1])},
            id="order-passages-first",
        ),
        pytest.param(
            TO_REVIEW,
            REVIEW,
            {
                "review": (
                    ReviewReason(ReviewCause.TARGET_UNAVAILABLE, None, (D1, D3)),
                    *REVIEW[1:],
                )
            },
            id="days",
        ),
        pytest.param(
            TO_REVIEW,
            REVIEW,
            {"review": REVIEW[:2]},
            id="not-applicable-missing",
        ),
        pytest.param(
            TO_REVIEW,
            (*REVIEW[:2], PASSAGES_REVIEW),
            {"passages": PASSAGES_UNAVAILABLE},
            id="passages-unavailable",
        ),
    ],
)
def test_admission_review_is_implied_by_the_values(
    admission: Admission,
    expected: tuple[ReviewReason, ...],
    changes: dict[str, Any],
) -> None:
    """Invariant 6 : ``review`` est celui que les valeurs publiées impliquent — cible
    manquante, garde-fou indisponible, passages indisponibles ou sans objet, dans cet
    ordre, avec leurs jours ; manquant, en trop ou dans le désordre, il est refusé."""
    received = changes.get("review", admission.review)
    _raises(
        admission,
        f"review vaut {expected!r}, reçu {received!r} (D10.2, D10.4).",
        **changes,
    )


@pytest.mark.parametrize(
    ("admission", "expected", "changes"),
    [
        pytest.param(REJECTED, FAILURES, {"failures": FAILURES[:-1]}, id="missing"),
        pytest.param(REJECTED, FAILURES, {"failures": FAILURES[1:]}, id="no-mean"),
        pytest.param(
            REJECTED,
            FAILURES,
            {"failures": (FAILURES[1], FAILURES[0], *FAILURES[2:])},
            id="order",
        ),
        pytest.param(
            REJECTED,
            FAILURES,
            {"failures": (*FAILURES[:3], FAILURES[4], FAILURES[3], FAILURES[5])},
            id="guard-order",
        ),
        pytest.param(
            REJECTED,
            FAILURES,
            {
                "failures": (
                    *FAILURES[:4],
                    FailedCheck(FailedCondition.GUARD, M.FLAT_LEVEL, (D1, D3)),
                    FAILURES[5],
                )
            },
            id="guard-days",
        ),
        pytest.param(
            REJECTED,
            FAILURES,
            {
                "failures": (
                    *FAILURES[:2],
                    FailedCheck(FailedCondition.LOSS, None, (D1, D3)),
                    *FAILURES[3:],
                )
            },
            id="loss-days",
        ),
        pytest.param(ADMISSION, (), {"failures": (VOTE_FAILS,)}, id="extra"),
        pytest.param(TO_REVIEW, (), {"failures": (VOTE_FAILS,)}, id="vote-counted"),
        pytest.param(
            VOTE_REVIEW, (VOTE_FAILS,), {"failures": ()}, id="vote-with-absent-gain"
        ),
        pytest.param(TINY, (VOTE_FAILS,), {"failures": ()}, id="vote-tiny-gain"),
    ],
)
def test_admission_failures_are_implied_by_the_values(
    admission: Admission,
    expected: tuple[FailedCheck, ...],
    changes: dict[str, Any],
) -> None:
    """Invariant 7 : ``failures`` est celui que les valeurs publiées impliquent —
    gain moyen, vote (gains absents comptés), pertes, garde-fous dépassés, passages,
    dans cet ordre, avec leurs jours ; manquant, en trop ou dans le désordre, il est
    refusé."""
    received = changes.get("failures", admission.failures)
    _raises(
        admission,
        f"failures vaut {expected!r}, reçu {received!r} (D10.3, D10.4).",
        **changes,
    )


@pytest.mark.parametrize(
    "admission",
    [ADMISSION, REJECTED, TO_REVIEW, TO_REVIEW_WITH_FAILURES, VOTE_REVIEW, TINY],
    ids=["provisional", "rejected", "to-review", "to-review-failures", "vote", "tiny"],
)
def test_admission_verdict_is_implied(admission: Admission) -> None:
    """Invariant 8 : « à revoir » si ``review`` n'est pas vide, sinon rejeté si
    ``failures`` n'est pas vide, sinon candidat provisoire ; tout autre verdict est
    refusé."""
    for other in AdmissionVerdict:
        if other is not admission.verdict:
            _raises(
                admission,
                f"le verdict est {admission.verdict}, reçu {other} (D10.6).",
                verdict=other,
            )


COMPARATOR = AdmissionReserve.COMPARATOR_SATURATED
CANDIDATE_RESERVE = AdmissionReserve.CANDIDATE_SATURATED


@pytest.mark.parametrize(
    ("admission", "reserves"),
    [
        pytest.param(ADMISSION, (), id="sensitivity-absent"),
        pytest.param(ADMISSION, (COMPARATOR, *SENSITIVITY), id="comparator-extra"),
        pytest.param(SATURATED, SENSITIVITY, id="saturation-not-signalled"),
        pytest.param(
            SATURATED, (COMPARATOR, *SENSITIVITY), id="candidate-not-signalled"
        ),
        pytest.param(SATURATED, (COMPARATOR, CANDIDATE_RESERVE), id="no-sensitivity"),
        pytest.param(
            SATURATED, (CANDIDATE_RESERVE, COMPARATOR, *SENSITIVITY), id="order"
        ),
        pytest.param(
            SATURATED, (*SENSITIVITY, COMPARATOR, CANDIDATE_RESERVE), id="order-last"
        ),
    ],
)
def test_admission_reserves_are_implied(
    admission: Admission, reserves: tuple[AdmissionReserve, ...]
) -> None:
    """Invariant 9 : comparateur saturé, candidat saturé, puis toujours la sensibilité
    restante, dans cet ordre ; absente, en trop ou dans le désordre, refusée."""
    expected = [reserve.value for reserve in admission.reserves]
    received = [reserve.value for reserve in reserves]
    _raises(
        admission,
        f"reserves vaut {expected}, reçu {received} (D10.5, D10.6).",
        reserves=reserves,
    )
