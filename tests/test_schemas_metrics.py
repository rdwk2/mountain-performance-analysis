"""Tests des contrats des métriques (§ 6.1 et § 8.1, test 1, du brief M4b-1).

``0010`` D0, D5.4, D5.5, D7.1 à D7.5. Un test par invariant de ``MetricValue``,
``ClassMetrics``, ``SupportMetrics``, ``PositiveTimeDiagnostic``,
``LogRatioEnvelope``, ``PassageErrors``, ``TargetMember`` et ``UsageTarget`` : un
objet construit à la main qui le viole (``ContractError``, visé par son message), et
un objet valide à sa limite.

Les exemples valides sont écrits en nombres dyadiques, pour que l'identité de D7.2 y
tienne exactement : ``A = W + B − C_comp`` avec ``A = 0.5``, ``W = 0.375``,
``B = 0.25``, ``C_comp = 0.125``.
"""

import math
from dataclasses import FrozenInstanceError, replace
from typing import Any

import pytest

from mountain_perf.schemas import (
    METRIC_RELATIVE_TOLERANCE,
    WEIGHT_SUM_TOLERANCE,
    ClassMetrics,
    ContractError,
    LogRatioEnvelope,
    MetricValue,
    PassageErrors,
    PositiveTimeDiagnostic,
    RegimeClass,
    SupportMetrics,
    TargetMember,
    Unavailability,
    UsageTarget,
)
from mountain_perf.schemas._dictionary import DOCUMENTED_TYPES, render

TAU = METRIC_RELATIVE_TOLERANCE
INSUF = Unavailability.INSUFFICIENT_SUPPORT
ZERO = Unavailability.ZERO_TIME
ERR = Unavailability.MODEL_ERROR
ABSENT = Unavailability.ABSENT
ASCENT, FLAT, DESCENT, MIXED = RegimeClass


def value(v: float, count: int) -> MetricValue:
    return MetricValue(v, None, count)


def missing(motif: Unavailability, count: int) -> MetricValue:
    return MetricValue(None, motif, count)


def absent_class(regime: RegimeClass) -> ClassMetrics:
    """Une classe absente du support : « non évalué », ``insufficient_support (0)``."""
    return ClassMetrics(regime, 0, False, *(missing(INSUF, 0),) * 3)


def unavailable_class(
    regime: RegimeClass, count: int, motif: Unavailability
) -> ClassMetrics:
    return ClassMetrics(regime, count, 1 <= count < 3, *(missing(motif, count),) * 3)


ASCENT_2 = ClassMetrics(ASCENT, 2, True, value(0.5, 2), value(0.5, 2), value(0.25, 2))
"""Montée de deux segments : ``E_R = 0.5``, ``D_R = 0.5``, ``E_R − L = 0.25``."""

MIXED_1 = ClassMetrics(MIXED, 1, True, value(0.0, 1), value(0.0, 1), value(-0.25, 1))
"""Mixte d'un segment : ``D_R == 0.0`` exactement."""

VALID = SupportMetrics(
    segment_count=3,
    model_error=False,
    log_ratio=value(0.25, 3),
    dispersion=value(0.5, 3),
    within=value(0.375, 3),
    between=value(0.25, 3),
    compensation=value(0.125, 3),
    classes=(ASCENT_2, absent_class(FLAT), absent_class(DESCENT), MIXED_1),
)
"""Support de trois segments, deux classes présentes, valeurs dyadiques."""

EMPTY = SupportMetrics(
    0,
    False,
    *(missing(INSUF, 0),) * 5,
    classes=tuple(absent_class(regime) for regime in RegimeClass),
)
"""Support vide (D7.2, choix 4 de rdw)."""


def errored(n_ascent: int, n_mixed: int) -> SupportMetrics:
    """Support en erreur du modèle (« T22 », § 7.1)."""
    n = n_ascent + n_mixed
    return SupportMetrics(
        n,
        True,
        missing(ERR, n),
        *(missing(ERR, n),) * 4,
        classes=(
            unavailable_class(ASCENT, n_ascent, ERR),
            absent_class(FLAT),
            absent_class(DESCENT),
            unavailable_class(MIXED, n_mixed, ERR),
        ),
    )


def all_zero() -> SupportMetrics:
    """« Tout nul, erreur » (§ 7.1) : ``T = 0``, drapeau levé, tout en ``zero_time``
    (l'observation avant le modèle)."""
    return SupportMetrics(
        2,
        True,
        *(missing(ZERO, 2),) * 5,
        classes=(
            unavailable_class(ASCENT, 2, ZERO),
            absent_class(FLAT),
            absent_class(DESCENT),
            absent_class(MIXED),
        ),
    )


def zero_timed(model_error: bool) -> SupportMetrics:
    """« Temps nul » (§ 7.1) : ``L`` présent, vectoriel et classes en ``zero_time``."""
    return SupportMetrics(
        2,
        model_error,
        missing(ERR, 2) if model_error else value(0.6931471805599453, 2),
        *(missing(ZERO, 2),) * 4,
        classes=(
            unavailable_class(ASCENT, 1, ZERO),
            absent_class(FLAT),
            unavailable_class(DESCENT, 1, ZERO),
            absent_class(MIXED),
        ),
    )


def _raises(instance: Any, match: str, **changes: Any) -> None:
    with pytest.raises(ContractError, match=match):
        replace(instance, **changes)


# ---------------------------------------------------------------------------
# MetricValue
# ---------------------------------------------------------------------------


def test_metric_value_limits_build() -> None:
    """Valeur d'effectif 1 ; indisponibilité d'effectif 0 (D0, D7.5)."""
    assert value(0.0, 1).available
    assert not missing(INSUF, 0).available
    assert value(-3.5, 7).value == -3.5


@pytest.mark.parametrize(
    ("v", "motif"), [(1.0, INSUF), (None, None)], ids=["both", "neither"]
)
def test_metric_value_has_exactly_one_of_value_and_unavailability(
    v: float | None, motif: Unavailability | None
) -> None:
    with pytest.raises(ContractError, match="exactement un de value et unavailability"):
        MetricValue(v, motif, 1)


@pytest.mark.parametrize("v", [math.nan, math.inf, -math.inf])
def test_metric_value_is_finite(v: float) -> None:
    with pytest.raises(ContractError, match="value doit être fini"):
        MetricValue(v, None, 1)


def test_metric_value_count_is_not_negative() -> None:
    with pytest.raises(ContractError, match="count doit être >= 0"):
        MetricValue(None, INSUF, -1)


def test_present_value_has_a_positive_count() -> None:
    """Une valeur n'est jamais « zéro par défaut » : présente, elle a un support."""
    with pytest.raises(ContractError, match="effectif >= 1"):
        MetricValue(0.0, None, 0)


# ---------------------------------------------------------------------------
# ClassMetrics
# ---------------------------------------------------------------------------


def test_class_examples_build() -> None:
    assert replace(ASCENT_2) == ASCENT_2
    assert replace(MIXED_1) == MIXED_1
    assert absent_class(FLAT).segment_count == 0


def test_class_segment_count_is_not_negative() -> None:
    with pytest.raises(ContractError, match="segment_count doit être >= 0"):
        ClassMetrics(FLAT, -1, False, *(missing(INSUF, 0),) * 3)


@pytest.mark.parametrize("field", ["log_ratio", "dispersion", "shape"])
def test_class_values_count_the_class_segments(field: str) -> None:
    _raises(ASCENT_2, f"{field}.count", **{field: value(0.5, 3)})


def test_class_values_share_one_motif() -> None:
    _raises(ASCENT_2, "même motif", log_ratio=missing(ZERO, 2))
    _raises(unavailable_class(ASCENT, 2, ZERO), "même motif", shape=missing(ERR, 2))


def test_class_motif_is_a_support_motif() -> None:
    with pytest.raises(ContractError, match="hors des motifs du support"):
        unavailable_class(ASCENT, 2, ABSENT)


def test_absent_class_is_insufficient_support() -> None:
    """Choix 3 de rdw : « non évalué » est ``insufficient_support``, d'effectif 0."""
    with pytest.raises(ContractError, match="classe absente"):
        unavailable_class(FLAT, 0, ZERO)


def test_underrepresented_needs_a_segment() -> None:
    """D7.5 : « trop peu représenté » vaut pour un effectif de 1 ou 2, pas 0."""
    _raises(absent_class(FLAT), "underrepresented exige", underrepresented=True)
    assert replace(MIXED_1, underrepresented=True).underrepresented


def test_class_dispersion_is_not_negative() -> None:
    _raises(ASCENT_2, "dispersion doit être >= 0", dispersion=value(-1e-300, 2))
    assert replace(ASCENT_2, dispersion=value(0.0, 2)).dispersion.value == 0.0


def test_one_segment_dispersion_is_exactly_zero() -> None:
    """D7.2 : un seul segment dans ``R`` → ``D_R = 0`` exactement ; ``5e−324`` est
    refusé, à un segment seulement."""
    _raises(MIXED_1, "D_R vaut 0 exactement", dispersion=value(5e-324, 1))
    two = replace(ASCENT_2, dispersion=value(5e-324, 2))
    assert two.dispersion.value == 5e-324


# ---------------------------------------------------------------------------
# SupportMetrics
# ---------------------------------------------------------------------------


def test_support_examples_build() -> None:
    for support in (
        VALID,
        EMPTY,
        errored(2, 1),
        zero_timed(False),
        zero_timed(True),
        all_zero(),
    ):
        assert replace(support) == support


def test_support_classes_are_a_tuple() -> None:
    _raises(VALID, "séquence immuable", classes=list(VALID.classes))


@pytest.mark.parametrize(
    "order",
    [
        (MIXED, FLAT, DESCENT, ASCENT),
        (ASCENT, FLAT, DESCENT),
        (ASCENT, FLAT, DESCENT, MIXED, MIXED),
    ],
    ids=["order", "three", "five"],
)
def test_support_has_the_four_classes_in_order(order: tuple[RegimeClass, ...]) -> None:
    """Choix 4 du brief : quatre classes, toujours, dans l'ordre de ``RegimeClass``."""
    by_class = {metrics.regime_class: metrics for metrics in VALID.classes}
    _raises(VALID, "quatre classes", classes=tuple(by_class[r] for r in order))


def test_class_counts_sum_to_the_support_count() -> None:
    classes = (ASCENT_2, absent_class(FLAT), absent_class(DESCENT), absent_class(MIXED))
    _raises(VALID, "somme des segment_count", classes=classes)


@pytest.mark.parametrize(
    "field", ["log_ratio", "dispersion", "within", "between", "compensation"]
)
def test_support_values_count_the_support_segments(field: str) -> None:
    current: MetricValue = getattr(VALID, field)
    assert current.value is not None
    _raises(VALID, f"{field}.count", **{field: value(current.value, 2)})


@pytest.mark.parametrize("field", ["dispersion", "within", "between", "compensation"])
def test_vector_values_share_one_motif(field: str) -> None:
    _raises(VALID, "même motif", **{field: missing(ZERO, 3)})


def test_support_motifs_are_support_motifs() -> None:
    _raises(VALID, "hors des motifs du support", log_ratio=missing(ABSENT, 3))
    vector = {name: missing(ABSENT, 3) for name in ("dispersion", "within", "between")}
    _raises(
        VALID, "hors des motifs du support", compensation=missing(ABSENT, 3), **vector
    )


def test_empty_support_iff_insufficient_level_and_vector() -> None:
    """Choix 4 de rdw : support vide ⇔ ``L`` et motif vectoriel en
    ``insufficient_support``."""
    _raises(EMPTY, "si et seulement si", log_ratio=missing(ZERO, 0))
    insufficient = {
        name: missing(INSUF, 3)
        for name in ("log_ratio", "dispersion", "within", "between", "compensation")
    }
    classes = (
        unavailable_class(ASCENT, 2, INSUF),
        absent_class(FLAT),
        absent_class(DESCENT),
        unavailable_class(MIXED, 1, INSUF),
    )
    _raises(VALID, "si et seulement si", classes=classes, **insufficient)


def test_empty_support_raises_no_model_error_flag() -> None:
    """§ 7.2, Tout nul, erreur : le support vide passe avant l'erreur du modèle."""
    _raises(EMPTY, "support vide ne lève pas model_error", model_error=True)


def test_model_error_publishes_no_value() -> None:
    """D7.1 : sous erreur du modèle, aucune valeur, ni du support ni des classes."""
    _raises(VALID, "aucune valeur présente", model_error=True)
    classes = (
        unavailable_class(ASCENT, 1, ZERO),
        absent_class(FLAT),
        ClassMetrics(DESCENT, 1, True, value(0.5, 1), value(0.0, 1), value(0.5, 1)),
        absent_class(MIXED),
    )
    with pytest.raises(ContractError, match="aucune valeur présente"):
        replace(zero_timed(True), classes=classes)


def test_model_error_motif_needs_the_flag() -> None:
    _raises(errored(2, 1), "sans le drapeau", model_error=False)


def test_zero_time_level_needs_zero_time_vector() -> None:
    """D5.5 : ``L`` n'est ``zero_time`` que si ``T = 0``, et alors tout le vectoriel
    l'est aussi."""
    _raises(errored(2, 1), "log_ratio en zero_time", log_ratio=missing(ZERO, 3))


def test_present_dispersion_needs_the_level() -> None:
    _raises(VALID, "dispersion présente exige log_ratio", log_ratio=missing(INSUF, 3))


def test_present_class_carries_the_vector_motif() -> None:
    classes = (
        unavailable_class(ASCENT, 2, ZERO),
        absent_class(FLAT),
        absent_class(DESCENT),
        MIXED_1,
    )
    _raises(VALID, "porte le motif", classes=classes)
    zero_classes = (
        unavailable_class(ASCENT, 1, ZERO),
        absent_class(FLAT),
        unavailable_class(DESCENT, 1, INSUF),
        absent_class(MIXED),
    )
    _raises(zero_timed(False), "porte le motif", classes=zero_classes)


def test_shape_is_exactly_class_level_minus_level() -> None:
    """D7.2, diagnostic de forme : ``E_R − L`` par une seule soustraction."""
    shifted = replace(ASCENT_2, shape=value(math.nextafter(0.25, 1.0), 2))
    _raises(VALID, "exactement", classes=(shifted, *VALID.classes[1:]))


@pytest.mark.parametrize("field", ["dispersion", "within", "between"])
def test_vector_values_are_not_negative(field: str) -> None:
    _raises(VALID, f"{field} doit être >= 0", **{field: value(-0.125, 3)})


def _identity(a: float, w: float, b: float, c: float) -> SupportMetrics:
    return replace(
        VALID,
        dispersion=value(a, 3),
        within=value(w, 3),
        between=value(b, 3),
        compensation=value(c, 3),
    )


def test_identity_holds_at_tau_times_scale() -> None:
    """Choix 7 de rdw : ``|A − (W + B − C_comp)| <= τ·S`` ; écart ``τ·S/2`` accepté,
    ``2·τ·S`` refusé."""
    scale = 0.5 + 0.375 + 0.25 + 0.125
    accepted = _identity(0.5 + TAU * scale / 2, 0.375, 0.25, 0.125)
    assert accepted.dispersion.value == 0.5 + TAU * scale / 2
    with pytest.raises(ContractError, match="A = W \\+ B − C_comp"):
        _identity(0.5 + 2 * TAU * scale, 0.375, 0.25, 0.125)
    with pytest.raises(ContractError, match="A = W \\+ B − C_comp"):
        _identity(0.5 - 2 * TAU * scale, 0.375, 0.25, 0.125)


def test_compensation_is_not_below_minus_tau_times_scale() -> None:
    """Choix 7 de rdw : ``C_comp >= −τ·S`` ; ``−τ·S/2`` accepté, ``−2·τ·S`` refusé,
    l'identité tenant dans les deux cas."""
    scale = 0.375 + 0.25 + 0.625
    small = TAU * scale / 2
    accepted = _identity(0.625 + small, 0.375, 0.25, -small)
    assert accepted.compensation.value == -small
    large = 2 * TAU * scale
    with pytest.raises(ContractError, match="compensation doit être >= −τ·S"):
        _identity(0.625 + large, 0.375, 0.25, -large)


# ---------------------------------------------------------------------------
# PositiveTimeDiagnostic
# ---------------------------------------------------------------------------

DIAGNOSTIC = PositiveTimeDiagnostic((True, False, True, True), VALID)


def test_diagnostic_builds() -> None:
    assert replace(DIAGNOSTIC) == DIAGNOSTIC
    assert PositiveTimeDiagnostic((False, False), EMPTY).metrics == EMPTY
    assert PositiveTimeDiagnostic((), EMPTY).mask == ()


def test_diagnostic_mask_is_a_tuple_of_booleans() -> None:
    _raises(DIAGNOSTIC, "séquence immuable", mask=[True, False, True, True])
    _raises(DIAGNOSTIC, "doit être un booléen", mask=(True, 0, True, True))


def test_diagnostic_counts_the_kept_segments() -> None:
    _raises(DIAGNOSTIC, "nombre de vrais", mask=(True, False, True, False))


def test_diagnostic_has_no_zero_time() -> None:
    """D5.5 : le sous-support est à temps positifs."""
    with pytest.raises(ContractError, match="aucun motif zero_time"):
        PositiveTimeDiagnostic((True, True), zero_timed(False))


# ---------------------------------------------------------------------------
# LogRatioEnvelope
# ---------------------------------------------------------------------------

ENVELOPE = LogRatioEnvelope(-0.25, 0.5, 0.0, None)


@pytest.mark.parametrize(
    "envelope",
    [
        ENVELOPE,
        LogRatioEnvelope(0.25, 0.5, 0.25, None),
        LogRatioEnvelope(0.0, 0.0, 0.0, None),
        LogRatioEnvelope(None, None, None, ERR),
        LogRatioEnvelope(None, None, None, ZERO),
        LogRatioEnvelope(-0.5, math.inf, 0.0, ZERO),
        LogRatioEnvelope(0.5, math.inf, 0.5, ZERO),
    ],
)
def test_envelope_limits_build(envelope: LogRatioEnvelope) -> None:
    """D5.4 : les trois états permis."""
    assert replace(envelope) == envelope


def test_envelope_motif_is_zero_time_or_model_error() -> None:
    with pytest.raises(ContractError, match="ne porte que zero_time ou model_error"):
        LogRatioEnvelope(None, None, None, INSUF)


def test_envelope_without_motif_has_its_values() -> None:
    with pytest.raises(ContractError, match="sans motif a ses trois valeurs"):
        LogRatioEnvelope(None, None, None, None)


@pytest.mark.parametrize("motif", [None, ZERO])
@pytest.mark.parametrize("missing_field", ["lower", "upper", "min_abs"])
def test_envelope_values_are_all_present_or_all_absent(
    motif: Unavailability | None, missing_field: str
) -> None:
    upper = math.inf if motif is ZERO else 0.5
    base = LogRatioEnvelope(-0.25, upper, 0.0, motif)
    _raises(base, "toutes présentes ou toutes absentes", **{missing_field: None})


def test_model_error_envelope_has_no_value() -> None:
    _raises(ENVELOPE, "model_error n'a aucune valeur", unavailability=ERR)


def test_zero_time_envelope_has_an_infinite_upper_bound() -> None:
    """D5.4 : ``a = 0 < P`` donne une borne supérieure ``+∞`` et le statut temps nul."""
    _raises(ENVELOPE, "upper == inf", unavailability=ZERO)


def test_envelope_without_motif_is_finite() -> None:
    _raises(ENVELOPE, "upper doit être fini", upper=math.inf)
    _raises(ENVELOPE, "lower doit être fini", lower=-math.inf)
    _raises(ENVELOPE, "min_abs doit être fini", min_abs=math.nan)


def test_envelope_bounds_are_ordered() -> None:
    _raises(ENVELOPE, "lower .* doit être <= upper", lower=0.75, min_abs=0.5)


def test_envelope_min_abs_is_not_negative() -> None:
    _raises(ENVELOPE, "min_abs doit être >= 0", lower=0.25, min_abs=-0.25)


@pytest.mark.parametrize(
    ("lower", "upper", "min_abs"),
    [(0.25, 0.5, 0.0), (-0.25, 0.5, 0.25), (-0.5, -0.25, 0.0)],
)
def test_envelope_min_abs_is_zero_iff_zero_is_inside(
    lower: float, upper: float, min_abs: float
) -> None:
    with pytest.raises(ContractError, match="min_abs == 0 si et seulement si"):
        LogRatioEnvelope(lower, upper, min_abs, None)


# ---------------------------------------------------------------------------
# PassageErrors
# ---------------------------------------------------------------------------

PASSAGES = PassageErrors(
    errors_s=(value(-30.0, 1), value(10.0, 1), missing(ABSENT, 1), value(20.0, 1)),
    model_error=False,
    max_abs_error_s=value(30.0, 3),
    max_error_s=value(20.0, 3),
    min_error_s=value(-30.0, 3),
)
"""« Signes » du § 7.5."""

NOT_OBSERVED_ERROR = PassageErrors(
    (missing(ABSENT, 1), missing(ABSENT, 1)), True, *(missing(INSUF, 0),) * 3
)
"""« Aucun observé, erreur » du § 7.5 : effectif nul, drapeau levé."""


@pytest.mark.parametrize(
    "errors",
    [
        PASSAGES,
        NOT_OBSERVED_ERROR,
        PassageErrors((), False, *(missing(INSUF, 0),) * 3),
        PassageErrors((value(0.0, 1), missing(ERR, 1)), True, *(missing(ERR, 2),) * 3),
        PassageErrors(
            (value(-20.0, 1), missing(ABSENT, 1)), True, *(missing(ERR, 1),) * 3
        ),
    ],
    ids=["signs", "none-observed-error", "empty", "observed-error", "unobserved-error"],
)
def test_passage_errors_limits_build(errors: PassageErrors) -> None:
    """Choix 7 du brief : un ``C_k`` sain reste publié sous le drapeau."""
    assert replace(errors) == errors


def test_passage_errors_are_a_tuple() -> None:
    _raises(PASSAGES, "séquence immuable", errors_s=list(PASSAGES.errors_s))


def test_each_passage_error_counts_one_point() -> None:
    errors = (value(-30.0, 2), *PASSAGES.errors_s[1:])
    _raises(PASSAGES, "errors_s\\[0\\].count doit valoir 1", errors_s=errors)


def test_aggregates_share_one_motif() -> None:
    _raises(PASSAGES, "même motif", max_error_s=missing(ERR, 3))
    _raises(NOT_OBSERVED_ERROR, "même motif", min_error_s=missing(ERR, 0))


@pytest.mark.parametrize("field", ["max_abs_error_s", "max_error_s", "min_error_s"])
def test_aggregates_count_the_observed_points(field: str) -> None:
    current: MetricValue = getattr(PASSAGES, field)
    assert current.value is not None
    _raises(PASSAGES, f"{field}.count", **{field: value(current.value, 4)})


def test_no_observed_point_is_insufficient_support() -> None:
    """Choix 4 de rdw, D7.3 : aucun point observé → ``support insuffisant``, avant
    l'erreur du modèle."""
    _raises(
        NOT_OBSERVED_ERROR,
        "sans point observé",
        **dict.fromkeys(
            ("max_abs_error_s", "max_error_s", "min_error_s"), missing(ERR, 0)
        ),
    )


def test_observed_aggregates_are_model_error_iff_flag() -> None:
    """D7.3, précision : une sortie invalide en l'un des points → ``erreur du
    modèle``."""
    _raises(PASSAGES, "si et seulement si model_error", model_error=True)
    errored_passages = PassageErrors(
        (value(-20.0, 1), missing(ABSENT, 1)), True, *(missing(ERR, 1),) * 3
    )
    _raises(errored_passages, "si et seulement si model_error", model_error=False)


def test_model_error_point_needs_the_flag() -> None:
    errors = (value(-20.0, 1), missing(ERR, 1))
    with pytest.raises(ContractError, match="exige le drapeau"):
        PassageErrors(errors, False, value(20.0, 2), value(-20.0, 2), value(-20.0, 2))


@pytest.mark.parametrize(
    ("field", "wrong"),
    [("max_abs_error_s", 20.0), ("max_error_s", 10.0), ("min_error_s", -20.0)],
)
def test_aggregates_are_exactly_max_abs_max_min(field: str, wrong: float) -> None:
    _raises(PASSAGES, f"{field} .* doit valoir", **{field: value(wrong, 3)})


# ---------------------------------------------------------------------------
# TargetMember
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "member",
    [TargetMember(None, True), TargetMember(0, False), TargetMember(0, True)],
)
def test_target_member_limits_build(member: TargetMember) -> None:
    assert replace(member) == member


def test_member_without_occurrence_is_the_arrival() -> None:
    with pytest.raises(ContractError, match="arrival doit être vrai"):
        TargetMember(None, False)


def test_member_occurrence_index_is_not_negative() -> None:
    with pytest.raises(ContractError, match="occurrence_index doit être >= 0"):
        TargetMember(-1, False)


# ---------------------------------------------------------------------------
# UsageTarget
# ---------------------------------------------------------------------------

USAGE = UsageTarget(
    weights=(0.25, 0.75),
    q_usage=value(0.125, 2),
    q_usage_prefix=value(0.125, 2),
    comparable=(True, True),
    model_error=False,
    arrival_anchor_gap_m=None,
)
"""« Défaut » du § 7.7."""

PARTIAL = UsageTarget(
    (0.5, 0.5), missing(ABSENT, 1), value(0.0, 1), (True, False), False, None
)
"""« T21 » du § 7.7."""

BASE_ERROR = UsageTarget(
    None, missing(ERR, 2), missing(ERR, 2), (True, True), True, None
)
"""« Base invalide » du § 7.7."""


def test_usage_target_limits_build() -> None:
    for target in (USAGE, PARTIAL, BASE_ERROR):
        assert replace(target) == target
    assert replace(USAGE, arrival_anchor_gap_m=0.0).arrival_anchor_gap_m == 0.0
    assert replace(USAGE, weights=(0.5, 0.5 + 5e-10)).weights == (0.5, 0.5 + 5e-10)
    assert replace(USAGE, comparable=(False, False)).comparable == (False, False)


def test_usage_target_counts() -> None:
    """``N`` et ``n`` de « n passages sur N » (D7.4)."""
    assert (USAGE.target_count, USAGE.available_count) == (2, 2)
    assert (PARTIAL.target_count, PARTIAL.available_count) == (2, 1)


def test_comparable_is_a_non_empty_tuple() -> None:
    _raises(USAGE, "séquence immuable", comparable=[True, True])
    _raises(USAGE, "ne doit pas être vide", comparable=())


def test_weights_are_a_tuple_of_the_target_length() -> None:
    _raises(USAGE, "séquence immuable", weights=[0.25, 0.75])
    _raises(USAGE, "même longueur", weights=(0.25, 0.25, 0.5))


@pytest.mark.parametrize("weights", [(math.nan, 1.0), (0.25, math.inf)])
def test_weights_are_finite(weights: tuple[float, float]) -> None:
    _raises(USAGE, "doit être fini", weights=weights)


def test_weights_are_not_negative() -> None:
    _raises(USAGE, "weights\\[1\\] doit être >= 0", weights=(2.0, -1.0))


@pytest.mark.parametrize(
    "weights",
    [(0.5, 0.49), (0.5, 0.5 + 2e-9), (0.3333333, 0.3333333, 0.3333333)],
    ids=["0.99", "1+2e-9", "hand-rounded"],
)
def test_weights_sum_to_one(weights: tuple[float, ...]) -> None:
    """Choix 11 du brief : ``WEIGHT_SUM_TOLERANCE`` est une tolérance d'arrondi."""
    assert abs(math.fsum(weights) - 1.0) > WEIGHT_SUM_TOLERANCE
    comparable = (True,) * len(weights)
    counts = {
        "q_usage": value(0.125, len(weights)),
        "q_usage_prefix": value(0.125, len(weights)),
    }
    _raises(USAGE, "somment à 1", weights=weights, comparable=comparable, **counts)


def test_absent_weights_need_the_model_error_flag() -> None:
    _raises(USAGE, "weights absents", weights=None)


def test_usage_counts_are_equal() -> None:
    _raises(PARTIAL, "doit valoir q_usage_prefix.count", q_usage_prefix=value(0.0, 2))


def test_usage_count_is_at_most_the_target_count() -> None:
    _raises(
        PARTIAL,
        "doit être <= len\\(comparable\\)",
        q_usage=missing(ABSENT, 3),
        q_usage_prefix=value(0.0, 3),
    )


def test_present_usage_covers_all_of_k() -> None:
    """D7.4 : ``q_usage`` disponible porte sur tout ``K``, sans repondération."""
    _raises(PARTIAL, "porte sur tout K", q_usage=value(0.0, 1))


def test_usage_values_are_not_negative() -> None:
    _raises(USAGE, "q_usage doit être >= 0", q_usage=value(-0.125, 2))
    _raises(USAGE, "q_usage_prefix doit être >= 0", q_usage_prefix=value(-0.125, 2))


def test_model_error_leaves_both_usages_unavailable() -> None:
    _raises(USAGE, "q_usage et q_usage_prefix sont indisponibles", model_error=True)
    _raises(
        BASE_ERROR,
        "q_usage et q_usage_prefix sont indisponibles",
        q_usage_prefix=value(0.125, 2),
    )


def test_model_error_motif_needs_the_usage_flag() -> None:
    _raises(BASE_ERROR, "sans le drapeau", model_error=False, weights=(0.5, 0.5))
    _raises(PARTIAL, "sans le drapeau", q_usage=missing(ERR, 1))


def test_comparable_passages_are_available() -> None:
    """D7.4 : un passage comparable est disponible."""
    _raises(PARTIAL, "passages comparables pour", comparable=(True, True))


@pytest.mark.parametrize("gap_m", [-1.0, math.nan, math.inf])
def test_arrival_anchor_gap_is_finite_and_not_negative(gap_m: float) -> None:
    _raises(USAGE, "arrival_anchor_gap_m doit être", arrival_anchor_gap_m=gap_m)


# ---------------------------------------------------------------------------
# Dictionnaire, gel
# ---------------------------------------------------------------------------

NEW_TYPES = (
    MetricValue,
    ClassMetrics,
    SupportMetrics,
    PositiveTimeDiagnostic,
    LogRatioEnvelope,
    PassageErrors,
    TargetMember,
    UsageTarget,
)


def test_new_types_follow_passage_match_result_in_the_dictionary() -> None:
    """§ 6.1 : documentés dans cet ordre, après ``PassageMatchResult``."""
    names = [cls.__name__ for cls in DOCUMENTED_TYPES]
    start = names.index("PassageMatchResult") + 1
    assert tuple(DOCUMENTED_TYPES[start : start + len(NEW_TYPES)]) == NEW_TYPES
    text = render()
    for cls in NEW_TYPES:
        assert f"## `{cls.__name__}`" in text


@pytest.mark.parametrize(
    ("instance", "field"),
    [
        (value(1.0, 1), "value"),
        (ASCENT_2, "segment_count"),
        (VALID, "model_error"),
        (DIAGNOSTIC, "mask"),
        (ENVELOPE, "lower"),
        (PASSAGES, "model_error"),
        (TargetMember(0, False), "arrival"),
        (USAGE, "weights"),
    ],
)
def test_new_types_are_frozen(instance: object, field: str) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(instance, field, None)


def test_tolerances_of_the_brief() -> None:
    """Choix 11 du brief."""
    assert METRIC_RELATIVE_TOLERANCE == 1e-12
    assert WEIGHT_SUM_TOLERANCE == 1e-9


def test_shape_is_checked_after_an_absent_class() -> None:
    """Correctif de la relecture : ``E_R − L`` est vérifié pour chaque classe
    présente, y compris après une classe absente (le mixte de ``VALID`` suit deux
    classes absentes)."""
    shifted = replace(MIXED_1, shape=value(math.nextafter(-0.25, 0.0), 1))
    _raises(VALID, "exactement", classes=(*VALID.classes[:3], shifted))
