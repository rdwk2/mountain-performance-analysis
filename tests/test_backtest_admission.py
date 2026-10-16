"""La règle d'admission exploratoire (brief M4c-3, § 8.2 ; ``0010`` D10.2 à D10.6,
précisions P1 à P17, décisions Q1, Q6, Q7 et E1 à E5) : ``admit``,
``assess_performances``, ``metric_value``.

Les entrées sont construites par ``fixtures.admission`` — des jours d'une sortie, leurs
temps et les projections de v0 brut et du candidat, passés par les vrais producteurs
(``score_scenario``, ``score_outing``, ``calibrate_performances``) ; les essais sont
ceux de la passe experte (C1 à C26), repris un à un :

- le vote et sa tolérance ``ε`` (E2) : ``⌈3n/4⌉`` ; des gains d'arrondi — recalage
  flottant (C2bis), soustraction de grands cumuls (C26) — ne votent pas ; un effet de
  niveau absorbé par le recalage, l'identité ;
- la saturation, réserve sans veto (E1, C1) ;
- les motifs de non-évaluabilité et leur ordre (P1, Q1 ; C3, C12, C14, C15) ;
- les seuils : source locale, empruntée, fixe (P6, C10), « comparable » et ses bornes
  (Q7, C11), sa durée projetée à l'effort borné de (0) sous l'horloge déclarée, sans
  repli sur v0 brut après une erreur du modèle de (0) (E3), ``δ̄`` moyenne des ``δ_j``
  (C17) ;
- les garde-fous de métrique, propres à leur métrique (C8, C10, C16, C22, C23) et celui
  des passages, poids nul compris (P11, C14, C25) ;
- « à revoir » : cible, garde-fou ou passages non calculables (C4, C5, C6) ; les
  conditions calculables qui échouent restent publiées (P13) ; le vote compte un gain
  absent comme un succès possible ;
- la moyenne contre v0 brut, au dénominateur commun (C24), absente si un gain manque
  (E5, C6) ;
- ``K`` déclaré en préfixe, l'arrivée facultative (E4) ;
- le document d'admission relu au bit.

Les valeurs attendues sont des formes closes calculées à la main (rapports de temps,
logarithmes) ; aucune donnée réelle.
"""

import math
import re
from dataclasses import replace
from datetime import date
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from fixtures.admission import (
    EVALUATED,
    A,
    D,
    Day,
    F,
    UsageK,
    X,
    borrowed,
    day,
    experiment,
    history,
    inputs,
    local,
)
from fixtures.calibration import GENERATED_AT
from fixtures.outings import source
from mountain_perf.backtest import (
    AdmissionInput,
    admit,
    assess_performances,
    calibrated_scores,
    decode_document,
    encode_document,
    metric_value,
    score_scenario,
    usage_forecast,
)
from mountain_perf.model import ProjectedTimeline
from mountain_perf.schemas import (
    CLOCKS,
    AdmittedSegment,
    Clock,
    DeclaredUsageTarget,
    ExperimentDeclaration,
    ExperimentMetric,
    FrozenReference,
    ObservedPoint,
    OutingLabel,
    OutingObservation,
    ParameterSet,
    RegimeClass,
    TargetMember,
    Unavailability,
)
from mountain_perf.schemas.admission import (
    GAIN_FLOOR,
    GUARD_METRICS,
    NUMERIC_TOLERANCE,
    Admission,
    AdmissionReserve,
    AdmissionVerdict,
    FailedCheck,
    FailedCondition,
    GuardStatus,
    NonEvaluable,
    PerformanceAssessment,
    ReviewCause,
    ReviewReason,
    ThresholdSource,
    required_successes,
)

M = ExperimentMetric.DESCENT_LEVEL
USAGE = ExperimentMetric.USAGE
J = date(2026, 6, 10)
REGIME_GUARDS = tuple(m for m in GUARD_METRICS if m is not ExperimentMetric.LEVEL)
SENSITIVITY = (AdmissionReserve.SENSITIVITY_REMAINING,)


def _admit(
    days: list[Day],
    declared: ExperimentDeclaration | None = None,
    references: tuple[FrozenReference, ...] = (),
) -> Admission:
    """``admit`` sur les entrées de ``days``, une admission attendue."""
    exp = experiment(references=references) if declared is None else declared
    admitted = admit(exp, inputs(days), references)
    assert isinstance(admitted, Admission)
    return admitted


def _evaluated(admission: Admission) -> list[PerformanceAssessment]:
    return [a for a in admission.performances if a.motif is None]


def _unavailable_guards(
    metrics: tuple[ExperimentMetric, ...], *days: date
) -> list[ReviewReason]:
    return [ReviewReason(ReviewCause.GUARD_UNAVAILABLE, m, days) for m in metrics]


# ---------------------------------------------------------------------------
# Le vote (D10.3 ; décision E2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", range(1, 25))
def test_required_successes(n: int) -> None:
    """D10.3 : ``⌈3n/4⌉``, en entiers."""
    assert required_successes(n) == math.ceil(3 * n / 4)


def test_identity_gains_are_exactly_zero() -> None:
    """D10.5 : un candidat identique à v0 a des gains exactement nuls — ni succès, ni
    gain moyen — et aucun dommage ; il est rejeté au gain moyen et au vote."""
    days = [
        history(),
        day("j1", EVALUATED["j1"], [100.0] * 9, [110.0] * 9, [110.0] * 9),
        day("j2", EVALUATED["j2"], [100.0] * 9, [95.0] * 9, [95.0] * 9),
    ]
    admission = _admit(days)
    assert [a.gain for a in _evaluated(admission)] == [0.0, 0.0]
    assert admission.mean_gain == 0.0
    assert (admission.positive, admission.required) == (0, 2)
    assert all(g.mean_harm == 0.0 for g in admission.guards if g.values)
    assert admission.passages.status is GuardStatus.SATISFIED
    assert admission.review == ()
    assert admission.failures == (
        FailedCheck(FailedCondition.MEAN_GAIN, None, ()),
        FailedCheck(FailedCondition.VOTE, None, ()),
    )
    assert admission.verdict is AdmissionVerdict.REJECTED
    assert admission.reserves == SENSITIVITY


def test_level_effect_is_absorbed_by_recalibration() -> None:
    """D10.5 : un effet de niveau pur (allure × 0,95 partout) est absorbé par le
    recalage de (1) — effort 0,95 fois celui de (0) — ; ses gains ne sont que des
    arrondis, sous ``ε`` : aucun succès, rejeté."""
    days = [
        history(0.95),
        day("j1", EVALUATED["j1"], [100.0] * 9, [110.0] * 9, [104.5] * 9),
        day("j2", EVALUATED["j2"], [100.0] * 9, [95.0] * 9, [90.25] * 9),
    ]
    admission = _admit(days)
    for assessment in _evaluated(admission):
        assert assessment.gain is not None
        assert abs(assessment.gain) < 1e-12
        assert assessment.base_effort is not None
        assert assessment.candidate_effort is not None
        assert assessment.candidate_effort.free == pytest.approx(
            0.95 * assessment.base_effort.free, rel=1e-12
        )
    assert admission.positive == 0
    assert admission.verdict is AdmissionVerdict.REJECTED


_TIMES = st.lists(st.floats(min_value=30.0, max_value=3000.0), min_size=9, max_size=9)
_RATIOS = st.lists(st.floats(min_value=0.8, max_value=1.2), min_size=9, max_size=9)


@settings(max_examples=25, deadline=None)
@given(
    history_times=_TIMES,
    history_ratios=_RATIOS,
    day_times=_TIMES,
    day_ratios=_RATIOS,
    factor=st.floats(min_value=0.7, max_value=1.25),
)
def test_pure_level_effect_never_votes(
    history_times: list[float],
    history_ratios: list[float],
    day_times: list[float],
    day_ratios: list[float],
    factor: float,
) -> None:
    """Décision E2 (propriété de la passe experte) : un effet de niveau pur — le
    candidat ``factor`` fois v0 partout, sur un historique et un jour quelconques, v0 à
    ±20 % des temps — est absorbé par le recalage tant que les deux efforts restent
    libres : ``|G_j| < 1e−9``, aucun succès, jamais candidat provisoire."""
    history_v0 = [t * r for t, r in zip(history_times, history_ratios, strict=True)]
    day_v0 = [t * r for t, r in zip(day_times, day_ratios, strict=True)]
    days = [
        day(
            "historique",
            "2026-06-01",
            history_times,
            history_v0,
            [factor * v for v in history_v0],
        ),
        day("j", J.isoformat(), day_times, day_v0, [factor * v for v in day_v0]),
    ]
    entries = inputs(days)
    assert entries[-1].base is not None
    assert entries[-1].candidate is not None
    assume(not entries[-1].candidate.clocks[0].calibration.saturated)
    assume(not entries[-1].base.clocks[0].calibration.saturated)
    admission = _admit(days)
    gain = admission.performances[-1].gain
    assert gain is not None
    assert abs(gain) < 1e-9
    assert admission.positive == 0
    assert admission.verdict is not AdmissionVerdict.PROVISIONAL


@pytest.mark.parametrize(
    ("gain", "positive"),
    [
        (NUMERIC_TOLERANCE / 2, 0),
        (NUMERIC_TOLERANCE * 2, 1),
    ],
    ids=["sous-epsilon", "sur-epsilon"],
)
def test_success_is_a_gain_above_epsilon(gain: float, positive: int) -> None:
    """Décision E2 : un succès est un gain ``> ε`` (``ε = 1e−6``)."""
    days = [
        history(),
        day("j", J.isoformat(), [100.0] * 9, [100.0 * math.exp(gain)] * 9, [100.0] * 9),
    ]
    admission = _admit(days)
    assert admission.performances[-1].gain == pytest.approx(gain, rel=1e-6)
    assert admission.positive == positive


def test_rounding_gains_do_not_vote() -> None:
    """C2bis, décision E2 : trois jours neutres en arithmétique réelle (effet × 0,95,
    absorbé) ont, en machine, des gains d'arrondi dont deux sont ``> 0`` ; sous ``ε``,
    ils ne votent pas : un succès sur quatre, trois exigés — rejeté au vote seul, le
    gain moyen tenu par le jour utile."""
    t, p = 111.87260716975047, 143.6609579003177
    days = [
        history(0.95),
        day("utile", "2026-06-10", [100.0] * 9, [100 * math.exp(0.05)] * 9, [95.0] * 9),
        day("neutre1", "2026-06-11", [t] * 9, [p] * 9, [p * 0.95] * 9),
        day("neutre2", "2026-06-12", [t] * 9, [p] * 9, [p * 0.95] * 9),
        day("neutre3", "2026-06-13", [100.0] * 9, [100.0] * 9, [95.0] * 9),
    ]
    admission = _admit(days)
    gains = [a.gain for a in _evaluated(admission)]
    assert gains[0] == pytest.approx(0.05, abs=1e-12)
    assert all(g is not None and abs(g) < 1e-12 for g in gains[1:])
    assert sum(1 for g in gains if g is not None and g > 0) == 3
    assert (admission.positive, admission.required) == (1, 3)
    assert admission.failures == (FailedCheck(FailedCondition.VOTE, None, ()),)
    assert admission.verdict is AdmissionVerdict.REJECTED


def _cumulated(entry: AdmissionInput, raw: ProjectedTimeline, n: int) -> AdmissionInput:
    """C26 : la sortie d'``entry`` remplacée par trois segments de descente au bout
    d'un long tracé ; ses prévisions sont des différences de grands cumuls de
    chronologies ``raw`` (v0) et ``0,95·raw`` (le candidat)."""
    candidate = ProjectedTimeline(raw.grid_m, tuple(0.95 * p for p in raw.pace_s_per_m))
    segments = []
    for k in range(3):
        start = 50.0 * n + 250.0 * k
        end = start + 250.0
        elapsed = (raw.time_at(end) - raw.time_at(start)) / 1.1
        segments.append(
            AdmittedSegment(
                n // 5 + k,
                start,
                end,
                start,
                end,
                start,
                end,
                RegimeClass.DESCENT,
                (elapsed,) * len(CLOCKS),
            )
        )
    members = (TargetMember(0, False), TargetMember(None, True))
    targets = (
        ObservedPoint(50.0, None, 0, None, (raw.time_at(50.0),) * len(CLOCKS)),
        ObservedPoint(raw.length_m, n // 5 + 4, None, Unavailability.ABSENT, None),
    )
    seen = OutingObservation(
        raw.length_m, 0.0, 0.0, tuple(segments), (), members, targets, None
    )
    f0, f1 = (
        usage_forecast(
            seen,
            timeline,
            source=source("gpx", "chronologie-C26.gpx", "9"),
            curve_ref="synthese-C26",
            parameters=ParameterSet(()),
            generated_at=GENERATED_AT,
        )
        for timeline in (raw, candidate)
    )
    assert entry.base is not None
    assert entry.candidate is not None
    return replace(
        entry,
        observation=seen,
        raw=score_scenario(seen, f0),
        base=calibrated_scores(
            seen, f0, [c.calibration for c in entry.base.clocks], base=f0
        ),
        candidate=calibrated_scores(
            seen, f1, [c.calibration for c in entry.candidate.clocks], base=f0
        ),
        portion_s=raw.time_at(raw.length_m),
    )


def test_long_cumul_differences_do_not_vote() -> None:
    """C26, décision E2 : deux jours neutres en réels — effet × 0,95, absorbé — dont
    les prévisions de segment sont des différences de cumuls de 158 000 s ; leurs gains
    d'arrondi dépassent ``1e−12`` mais pas ``ε`` : un succès sur quatre, rejeté."""
    n = 2000
    raw = ProjectedTimeline(
        tuple(50.0 * i for i in range(n + 21)),
        (1.583794501489819,) * n + (0.1479395361306608,) * 20,
    )
    days = [
        history(0.95),
        day("utile", "2026-06-10", [100.0] * 9, [100 * math.exp(0.05)] * 9, [95.0] * 9),
        day("neutre1", "2026-06-11", [100.0] * 9, [100.0] * 9, [95.0] * 9),
        day("neutre2", "2026-06-12", [100.0] * 9, [100.0] * 9, [95.0] * 9),
        day("neutre3", "2026-06-13", [100.0] * 9, [100.0] * 9, [95.0] * 9),
    ]
    entries = inputs(days)
    for k in (2, 3):
        entries[k] = _cumulated(entries[k], raw, n)
    admitted = admit(experiment(), entries, ())
    assert isinstance(admitted, Admission)
    gains = [a.gain for a in _evaluated(admitted)]
    assert sum(1 for g in gains if g is not None and g > 1e-12) == 3
    assert all(g is not None and abs(g) < 1e-9 for g in gains[1:])
    assert (admitted.positive, admitted.required) == (1, 3)
    assert admitted.verdict is AdmissionVerdict.REJECTED
    for entry in entries:
        assert entry.base is not None
        assert entry.candidate is not None
        assert not entry.base.clocks[0].calibration.saturated
        assert not entry.candidate.clocks[0].calibration.saturated


def test_vote_counts_a_missing_gain_as_a_possible_success() -> None:
    """P13, D10.3 : sous « à revoir », le vote n'échoue que si les gains absents,
    comptés comme des succès, ne suffiraient pas — deux succès et un absent sur quatre
    tiennent ``⌈3·4/4⌉ = 3`` ; un succès et un absent non."""

    def admitted(useful: int) -> Admission:
        values = [[110.0] * 9] * useful + [[100.0] * 9] * (3 - useful)
        days = [
            history(),
            day("absent", "2026-06-10", [100.0] * 9, [110.0] * 9, [None] * 9),
            *(
                day(f"j{k}", f"2026-06-{11 + k}", [100.0] * 9, v0, [100.0] * 9)
                for k, v0 in enumerate(values)
            ),
        ]
        return _admit(days)

    two = admitted(2)
    assert (two.positive, two.required) == (2, 3)
    assert two.verdict is AdmissionVerdict.TO_REVIEW
    assert FailedCondition.VOTE not in [f.condition for f in two.failures]
    one = admitted(1)
    assert one.positive == 1
    assert one.verdict is AdmissionVerdict.TO_REVIEW
    assert [f.condition for f in one.failures] == [FailedCondition.VOTE]


@pytest.mark.parametrize(
    ("excess", "loss"),
    [(NUMERIC_TOLERANCE / 2, False), (3 * NUMERIC_TOLERANCE, True)],
    ids=["dans-epsilon", "au-dela"],
)
def test_loss_bound_is_read_within_epsilon(excess: float, loss: bool) -> None:
    """Décision E2, D10.3 : une perte de ``δ_j + excès`` — le candidat plus lent que
    la vérité, (0) juste — n'échoue à ``G_j ≥ −δ_j − ε`` qu'au-delà de ``ε`` ; le gain
    moyen et le vote échouent dans les deux cas."""
    days = [
        history(),
        day(
            "j",
            J.isoformat(),
            [100.0] * 9,
            [100.0] * 9,
            [100.0 * math.exp(GAIN_FLOOR + excess)] * 9,
        ),
    ]
    admission = _admit(days)
    assert admission.performances[-1].gain == pytest.approx(
        -(GAIN_FLOOR + excess), abs=1e-12
    )
    expected = [
        FailedCheck(FailedCondition.MEAN_GAIN, None, ()),
        FailedCheck(FailedCondition.VOTE, None, ()),
    ]
    if loss:
        expected.append(FailedCheck(FailedCondition.LOSS, None, (J,)))
    assert list(admission.failures[: len(expected)]) == expected
    conditions = [f.condition for f in admission.failures]
    assert (FailedCondition.LOSS in conditions) == loss


def test_failures_are_published_under_review() -> None:
    """P13 : « à revoir » l'emporte sur le rejet, et les conditions calculables qui
    échouent restent publiées — le vote, une perte au-delà de ``δ_j`` le jour où elle
    a lieu ; le gain moyen, incalculable, n'est pas jugé."""
    days = [
        history(),
        day("absent", "2026-06-10", [100.0] * 9, [110.0] * 9, [None] * 9),
        day("neutre", "2026-06-11", [100.0] * 9, [100.0] * 9, [100.0] * 9),
        day("perte", "2026-06-12", [100.0] * 9, [100.0] * 9, [110.0] * 9),
        day("neutre2", "2026-06-13", [100.0] * 9, [100.0] * 9, [100.0] * 9),
    ]
    admission = _admit(days)
    assert admission.mean_gain is None
    assert admission.verdict is AdmissionVerdict.TO_REVIEW
    assert admission.review[0] == ReviewReason(
        ReviewCause.TARGET_UNAVAILABLE, None, (date(2026, 6, 10),)
    )
    assert admission.failures[:2] == (
        FailedCheck(FailedCondition.VOTE, None, ()),
        FailedCheck(FailedCondition.LOSS, None, (date(2026, 6, 12),)),
    )


# ---------------------------------------------------------------------------
# La saturation, réserve sans veto (décision E1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("factor", "truth", "free", "bounded", "level", "usage"),
    [
        (2.0, 400 / 3, 2.0, 1.5, math.log(4 / 3), 1 / 3),
        (0.4, 80.0, 0.4, 0.5, math.log(5 / 4), 0.2),
    ],
    ids=["lent", "rapide"],
)
@pytest.mark.parametrize("target", [M, USAGE], ids=["descente", "usage"])
def test_saturated_candidate_is_a_reserve_without_veto(
    target: ExperimentMetric,
    factor: float,
    truth: float,
    free: float,
    bounded: float,
    level: float,
    usage: float,
) -> None:
    """C1, décision E1 : un candidat de niveau seul, calé à la borne d'effort — saturé
    — et que la vérité donne juste ; candidat provisoire sous la réserve « candidat
    saturé ». (0) est juste à l'historique, effort 1 ; (1) a l'effort libre
    ``factor``, borné à ``bounded`` ; sa prévision calée ``100·factor / bounded`` égale
    la vérité. Gain de niveau : ``log(100 / vérité)`` en valeur absolue ; d'usage :
    ``|900 − 9·vérité| / 900``."""
    days = [history(factor)] + [
        day(
            f"j{k}", f"2026-06-{10 + k}", [truth] * 9, [100.0] * 9, [100.0 * factor] * 9
        )
        for k in range(4)
    ]
    admission = _admit(days, experiment(target))
    expected = level if target is M else usage
    for assessment in _evaluated(admission):
        assert assessment.gain == pytest.approx(expected, rel=1e-12)
        assert assessment.base_effort is not None
        assert assessment.candidate_effort is not None
        assert not assessment.base_effort.saturated
        assert assessment.base_effort.bounded == pytest.approx(1.0, rel=1e-12)
        assert assessment.candidate_effort.saturated
        assert assessment.candidate_effort.free == pytest.approx(free, rel=1e-12)
        assert assessment.candidate_effort.bounded == bounded
    assert (admission.evaluable, admission.positive, admission.required) == (4, 4, 3)
    assert admission.verdict is AdmissionVerdict.PROVISIONAL
    assert admission.reserves == (
        AdmissionReserve.CANDIDATE_SATURATED,
        AdmissionReserve.SENSITIVITY_REMAINING,
    )


def test_saturated_comparator_and_candidate_reserves_in_order() -> None:
    """D10.6, décision E1 : (0) et (1) saturés tous deux — v0 et le candidat deux fois
    trop lents à l'historique — : les deux réserves, dans l'ordre, puis la sensibilité
    restante."""
    slow = day("historique", "2026-06-01", [100.0] * 9, [200.0] * 9, [200.0] * 9)
    days = [slow, day("j", J.isoformat(), [100.0] * 9, [200.0] * 9, [190.0] * 9)]
    admission = _admit(days)
    assert admission.reserves == (
        AdmissionReserve.COMPARATOR_SATURATED,
        AdmissionReserve.CANDIDATE_SATURATED,
        AdmissionReserve.SENSITIVITY_REMAINING,
    )


# ---------------------------------------------------------------------------
# L'évaluabilité (D10.2 ; P1, P2, P11 ; décision Q1)
# ---------------------------------------------------------------------------


def test_zero_time_outside_the_target_blocks_every_regime_metric() -> None:
    """C3, D5.5 : un temps nul sous l'horloge déclarée, sur un segment de montée,
    rend non évaluable une cible de descente (``ZERO_TIME``) ; sous une cible
    ``q_usage``, il rend indisponibles les six garde-fous de régime, exigés : « à
    revoir »."""
    days = [
        history(),
        day("j", J.isoformat(), [100.0] * 9, [100.0] * 9, [90.0] * 9, zero=(0,)),
    ]
    assessed = admit(experiment(M, CLOCKS[1]), inputs(days), ())
    assert not isinstance(assessed, Admission)
    assert [a.motif for a in assessed] == [
        NonEvaluable.NOT_CALIBRATED,
        NonEvaluable.ZERO_TIME,
    ]
    admission = _admit(days, experiment(USAGE, CLOCKS[1]))
    assert admission.evaluable == 1
    assert admission.guards[0].status is GuardStatus.SATISFIED
    assert list(admission.review) == _unavailable_guards(REGIME_GUARDS, J)
    assert admission.verdict is AdmissionVerdict.TO_REVIEW


@pytest.mark.parametrize(
    ("regimes", "zero", "motif"),
    [
        ((A,) * 9, (0,), NonEvaluable.INSUFFICIENT_SUPPORT),
        ((A,) * 7 + (D,) * 2, (0,), NonEvaluable.ZERO_TIME),
        ((A,) * 6 + (D,) * 3, (0,), NonEvaluable.ZERO_TIME),
        ((A,) * 7 + (D,) * 2, (), NonEvaluable.UNDERREPRESENTED),
    ],
    ids=["classe-absente", "temps-nul-avant-sous-representee", "temps-nul", "deux"],
)
def test_observation_motifs_in_order(
    regimes: tuple[str, ...], zero: tuple[int, ...], motif: NonEvaluable
) -> None:
    """C12, P2 : l'ordre des motifs d'observation d'une cible de régime — classe
    absente, puis temps nul, puis moins de trois segments de la classe."""
    days = [
        history(),
        day(
            "j", J.isoformat(), [100.0] * 9, [100.0] * 9, [90.0] * 9, regimes, zero=zero
        ),
    ]
    assert (
        assess_performances(experiment(M, CLOCKS[1]), inputs(days), ())[-1].motif
        is motif
    )


def test_performance_motifs_in_order() -> None:
    """C12, P1, décision Q1 : exclue, puis multi-sorties, puis non scorée, puis sans
    usage — chaque motif l'emporte sur les suivants."""
    entry = inputs(
        [history(), day("j", J.isoformat(), [100.0] * 9, [106.0] * 9, [100.0] * 9)]
    )[-1]
    performance = entry.performance
    first = performance.outings[0]
    second = replace(
        first,
        outing_id="autre",
        start_time=first.end_time,
        end_time=first.end_time.replace(hour=15),
    )
    multi = replace(
        entry,
        performance=replace(performance, outings=(first, second)),
        excluded=True,
        observation=None,
    )
    cases = [
        multi,
        replace(multi, excluded=False),
        replace(entry, observation=None),
        replace(entry, raw=None, base=None, candidate=None),
    ]
    motifs = [assess_performances(experiment(), [c], ())[0].motif for c in cases]
    assert motifs == [
        NonEvaluable.EXCLUDED,
        NonEvaluable.MULTI_OUTING,
        NonEvaluable.UNSCORED,
        NonEvaluable.NO_USAGE,
    ]


def test_partial_usage_scores_are_refused() -> None:
    """Précondition d'``assess_performances`` : les scores d'usage de v0 brut, de (0) et
    de (1) sont tous trois présents ou tous trois absents."""
    entry = inputs(
        [history(), day("j", J.isoformat(), [100.0] * 9, [106.0] * 9, [100.0] * 9)]
    )[-1]
    with pytest.raises(ValueError, match="tous présents ou tous absents"):
        assess_performances(experiment(), [replace(entry, base=None)], ())


def test_excluded_history_still_calibrates() -> None:
    """C13, P17 : un historique exclu de l'admission n'est pas évaluable, mais reste
    dans la population de calage du jour suivant."""
    days = [
        replace(history(), excluded=True),
        day("j", J.isoformat(), [100.0] * 9, [106.0] * 9, [100.0] * 9),
    ]
    entries = inputs(days)
    admission = _admit(days)
    assert admission.performances[0].motif is NonEvaluable.EXCLUDED
    assert entries[-1].base is not None
    population = entries[-1].base.clocks[0].calibration.population
    assert date(2026, 6, 1) in population
    assert admission.verdict is AdmissionVerdict.PROVISIONAL


def test_no_evaluable_performance_returns_assessments() -> None:
    """C15, décision Q4 : ``n = 0`` — toutes exclues — : aucune admission, les seules
    évaluations, pour l'ÉCHEC « non évaluable »."""
    days = [replace(history(), excluded=True), replace(history(), excluded=True)]
    days[1] = replace(days[1], outing_id="j", day=J.isoformat())
    assessed = admit(experiment(), inputs(days), ())
    assert not isinstance(assessed, Admission)
    assert [a.motif for a in assessed] == [NonEvaluable.EXCLUDED] * 2


# ---------------------------------------------------------------------------
# Les seuils (D10.3 ; P6, P7 ; décisions Q7 et E3)
# ---------------------------------------------------------------------------


def _one_day(**options: Any) -> list[Day]:
    """L'historique, puis un jour évalué : v0 trop lent de 6 %, le candidat juste ;
    ``options`` remplace des champs du jour évalué."""
    evaluated = day("j", J.isoformat(), [100.0] * 9, [106.0] * 9, [100.0] * 9)
    return [history(), replace(evaluated, **options)]


def test_references_are_read_under_the_declared_clock() -> None:
    """D10.3 : ``F_j`` est la référence de la métrique **sous l'horloge déclarée** —
    une locale de 0,4 sous ``CLOCKS[1]`` donne ``δ = 0,1`` ; la locale de l'écoulé,
    nulle, n'est pas lue."""
    refs = (local(M, 0.4, clock=CLOCKS[1]), local(M, 0.0, clock=CLOCKS[0]))
    declared = experiment(M, CLOCKS[1], references=refs[:1])
    assessed = assess_performances(declared, inputs(_one_day()), refs)[-1]
    assert assessed.source is ThresholdSource.LOCAL
    assert assessed.reference == 0.4
    assert assessed.threshold == pytest.approx(0.1)


def test_borrowed_reference_when_local_is_unavailable() -> None:
    """C10, P6 : la locale du parcours indisponible, une performance comparable prend
    l'empruntée — ``δ = 0,25·0,4`` — et la locale y laisse son motif ; le gain
    ``log(1,06)`` n'atteint pas ``δ`` : rejeté au gain moyen."""
    refs = (local(M, None), local(M, 0.4, "b"), borrowed(M, 0.4))
    admission = _admit(_one_day(), experiment(references=refs), refs)
    assessed = admission.performances[-1]
    assert assessed.comparable is True
    assert assessed.source is ThresholdSource.BORROWED
    assert assessed.local_unavailability is Unavailability.INSUFFICIENT_SUPPORT
    assert assessed.reference == 0.4
    assert assessed.threshold == pytest.approx(0.1)
    assert assessed.gain == pytest.approx(math.log(1.06), rel=1e-12)
    assert admission.verdict is AdmissionVerdict.REJECTED
    assert admission.failures[0] == FailedCheck(FailedCondition.MEAN_GAIN, None, ())


@pytest.mark.parametrize(
    ("refs", "dplus", "source", "reference", "threshold", "motif"),
    [
        ((local(M, 0.0),), 70.0, ThresholdSource.LOCAL, 0.0, GAIN_FLOOR, None),
        (
            (local(M, None), local(M, 0.4, "b"), borrowed(M, 0.4)),
            120.0,
            ThresholdSource.FIXED,
            None,
            GAIN_FLOOR,
            Unavailability.INSUFFICIENT_SUPPORT,
        ),
        (
            (local(M, 0.4, "b"), borrowed(M, 0.4)),
            70.0,
            ThresholdSource.BORROWED,
            0.4,
            0.1,
            Unavailability.ABSENT,
        ),
        ((), 70.0, ThresholdSource.FIXED, None, GAIN_FLOOR, Unavailability.ABSENT),
    ],
    ids=["locale-nulle", "non-comparable", "sans-locale", "aucune"],
)
def test_threshold_source(
    refs: tuple[FrozenReference, ...],
    dplus: float,
    source: ThresholdSource,
    reference: float | None,
    threshold: float,
    motif: Unavailability | None,
) -> None:
    """C10, P6 : la locale disponible, même nulle ; sinon l'empruntée pour une
    performance comparable ; sinon le seuil fixe — ``δ = max(0,010 ; 0,25·F)``."""
    assessed = assess_performances(
        experiment(references=refs), inputs(_one_day(dplus_per_km=dplus)), refs
    )[-1]
    assert assessed.source is source
    assert assessed.reference == reference
    assert assessed.threshold == pytest.approx(threshold)
    assert assessed.local_unavailability is motif


def test_guard_threshold_uses_its_own_metric() -> None:
    """C10, D10.4 : le seuil d'un garde-fou vient de la référence de **sa** métrique —
    ``|L|`` locale 0,2, ``η = 0,10·0,2`` — non de celle de la cible (empruntée)."""
    refs = (
        local(M, None),
        local(M, 0.4, "b"),
        borrowed(M, 0.4),
        local(ExperimentMetric.LEVEL, 0.2),
    )
    admission = _admit(_one_day(), experiment(references=refs), refs)
    assert admission.mean_threshold == pytest.approx(0.1)
    level = admission.guards[0]
    assert level.metric is ExperimentMetric.LEVEL
    assert level.values[0].source is ThresholdSource.LOCAL
    assert level.values[0].threshold == pytest.approx(0.02)


def test_mean_threshold_is_the_mean_of_daily_thresholds() -> None:
    """C17, D10.3 : ``δ̄`` est la moyenne des ``δ_j`` — chaque jour sa locale, 0 puis
    0,08 : ``(0,010 + 0,020) / 2`` —, non le seuil de la moyenne des ``F``."""
    days = [
        history(),
        day("j1", EVALUATED["j1"], [100.0] * 9, [106.0] * 9, [100.0] * 9),
        day("j2", EVALUATED["j2"], [100.0] * 9, [106.0] * 9, [100.0] * 9, route="b"),
    ]
    refs = (local(M, 0.0, "a"), local(M, 0.08, "b"))
    admission = _admit(days, experiment(references=refs), refs)
    assert [a.threshold for a in _evaluated(admission)] == [0.01, pytest.approx(0.02)]
    assert admission.mean_threshold == pytest.approx(0.015)


COMPARABLE_CASES = [
    (49.999999, 14399.0, False),
    (49.999999, 14400.0, False),
    (49.999999, 14401.0, False),
    (50.0, 14399.0, True),
    (50.0, 14400.0, True),
    (50.0, 14401.0, False),
    (110.0, 14399.0, True),
    (110.0, 14400.0, True),
    (110.0, 14401.0, False),
    (110.000001, 14399.0, False),
    (110.000001, 14400.0, False),
    (110.000001, 14401.0, False),
]


@pytest.mark.parametrize(("dplus", "portion", "comparable"), COMPARABLE_CASES)
def test_comparable_bounds_are_inclusive_and_exact(
    dplus: float, portion: float, comparable: bool
) -> None:
    """C11, décision Q7 : comparable — entraînement, D+/km dans ``[50 ; 110]`` et durée
    projetée par (0) d'au plus 4 h —, bornes incluses, comparées exactement (sans
    ``ε``) ; (0) d'effort 1, la durée projetée est celle de la portion."""
    entry = inputs(_one_day())[-1]
    entry = replace(entry, portion_s=portion, dplus_per_km=dplus)
    assessed = assess_performances(experiment(), [entry], ())[0]
    assert assessed.comparable is comparable
    assert assessed.projected_s == pytest.approx(portion, rel=1e-12)


def test_projected_duration_divides_by_the_bounded_effort() -> None:
    """Décision Q7, précision de D10.3 : la durée projetée divise la durée de v0 brut
    par l'effort **borné** de (0). L'historique est deux fois trop lent pour v0 : (0)
    a l'effort libre 2, borné à 1,5, saturé ; une portion de 24 000 s fait 16 000 s,
    au-delà de 4 h — non comparable, seuil fixe, la locale indisponible y laissant son
    motif (à l'effort libre, 12 000 s auraient pris l'empruntée, ``δ = 0,1``)."""
    slow = day("historique", "2026-06-01", [100.0] * 9, [200.0] * 9, [200.0] * 9)
    evaluated = day(
        "j", J.isoformat(), [100.0] * 9, [200.0] * 9, [190.0] * 9, portion_s=24000.0
    )
    refs = (local(M, None), local(M, 0.4, "b"), borrowed(M, 0.4))
    assessed = assess_performances(
        experiment(references=refs), inputs([slow, evaluated]), refs
    )[-1]
    effort = assessed.base_effort
    assert effort is not None
    assert effort.free == pytest.approx(2.0, rel=1e-12)
    assert (effort.bounded, effort.saturated) == (1.5, True)
    assert assessed.projected_s == 16000.0
    assert assessed.comparable is False
    assert assessed.source is ThresholdSource.FIXED
    assert assessed.reference is None
    assert assessed.local_unavailability is Unavailability.INSUFFICIENT_SUPPORT
    assert assessed.threshold == GAIN_FLOOR


@pytest.mark.parametrize(
    ("clock", "effort", "projected", "comparable", "source", "threshold"),
    [
        (CLOCKS[3], 100.0 / 82.0, 12300.0, True, ThresholdSource.BORROWED, 0.1),
        (CLOCKS[0], 1.0, 15000.0, False, ThresholdSource.FIXED, GAIN_FLOOR),
    ],
    ids=["M θ3", "écoulé"],
)
def test_projected_duration_uses_the_declared_clock(
    clock: Clock,
    effort: float,
    projected: float,
    comparable: bool,
    source: ThresholdSource,
    threshold: float,
) -> None:
    """Décision Q7, précision de D10.3 : la durée projetée prend l'effort de (0) **sous
    l'horloge déclarée**. Sous ``CLOCKS[3]`` (``M θ3``, temps ``0,82·e``), (0) a
    l'effort ``100/82`` ; une portion de 15 000 s fait 12 300 s — comparable,
    l'empruntée, ``δ = 0,1``. Sous l'écoulé, effort 1 : 15 000 s, non comparable,
    seuil fixe."""
    days = [
        history(),
        day(
            "j", J.isoformat(), [100.0] * 9, [100.0] * 9, [90.0] * 9, portion_s=15000.0
        ),
    ]
    refs = (
        local(M, None, clock=clock),
        local(M, 0.4, "b", clock=clock),
        borrowed(M, 0.4, clock=clock),
    )
    assessed = assess_performances(
        experiment(M, clock, references=refs), inputs(days), refs
    )[-1]
    assert assessed.base_effort is not None
    assert assessed.base_effort.bounded == pytest.approx(effort, rel=1e-12)
    assert assessed.projected_s == pytest.approx(projected, rel=1e-12)
    assert assessed.comparable is comparable
    assert assessed.source is source
    assert assessed.threshold == pytest.approx(threshold, rel=1e-12)


def test_race_is_not_comparable() -> None:
    """D10.3 : une performance qui n'est pas d'entraînement n'est pas comparable."""
    assessed = assess_performances(
        experiment(), inputs(_one_day(label=OutingLabel.RACE)), ()
    )[-1]
    assert assessed.comparable is False


def test_model_error_of_the_base_gets_no_fallback() -> None:
    """C11, décision E3 : (0) en erreur du modèle à l'apprentissage (une projection de
    v0 absente à l'historique) — la performance n'est pas classée, au motif de son
    calage, sans repli sur la durée de v0 brut ; donc pas d'empruntée : seuil fixe.
    (0) non calé (l'historique lui-même) : la durée de v0 brut, pour cette seule
    classification."""
    refs = (local(M, None), local(M, 0.4, "b"), borrowed(M, 0.4))
    broken = replace(history(), v0=(None,) + (100.0,) * 8)
    days = [
        broken,
        day(
            "j", J.isoformat(), [100.0] * 9, [106.0] * 9, [100.0] * 9, portion_s=14400.0
        ),
    ]
    admission = _admit(days, experiment(references=refs), refs)
    first, assessed = admission.performances
    assert first.motif is NonEvaluable.NOT_CALIBRATED
    assert (first.comparable, first.projected_s) == (True, 800.0)
    assert assessed.comparable is None
    assert assessed.comparable_unavailability is Unavailability.MODEL_ERROR
    assert assessed.projected_s is None
    assert assessed.source is ThresholdSource.FIXED
    assert assessed.gain is None
    assert admission.verdict is AdmissionVerdict.TO_REVIEW


# ---------------------------------------------------------------------------
# Les garde-fous (D10.4 ; P11)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "metrics"),
    [
        (M, tuple(m for m in GUARD_METRICS if m is not M)),
        (USAGE, GUARD_METRICS),
    ],
    ids=["descente", "usage"],
)
def test_guards_are_the_frozen_list_without_the_target(
    target: ExperimentMetric, metrics: tuple[ExperimentMetric, ...]
) -> None:
    """D10.4 : les garde-fous sont ceux de ``GUARD_METRICS``, dans cet ordre, sans la
    cible."""
    admission = _admit(_one_day(), experiment(target))
    assert tuple(g.metric for g in admission.guards) == metrics


def test_level_shift_onto_ascent_is_caught_by_its_guard() -> None:
    """C8, D10.4 : un candidat juste en descente seulement à l'historique ramène le
    recalage de (1) à l'effort ``570/600`` ; le jour évalué, il gagne en descente
    ``log(10/9) − log(20/19)`` mais dégrade la montée de ``log(20/19)``, au-delà de
    ``2η`` : rejeté par le garde-fou de montée, ce jour-là."""
    regimes = (A,) * 3 + (D,) * 3
    days = [
        day(
            "historique",
            "2026-06-01",
            [100.0] * 6,
            [100.0] * 6,
            [100.0] * 3 + [90.0] * 3,
            regimes,
        ),
        day(
            "j",
            J.isoformat(),
            [100.0] * 3 + [90.0] * 3,
            [100.0] * 6,
            [100.0] * 3 + [90.0] * 3,
            regimes,
        ),
    ]
    admission = _admit(days)
    assert admission.mean_gain == pytest.approx(math.log(19 / 18), rel=1e-12)
    ascent = admission.guards[1]
    assert ascent.metric is ExperimentMetric.ASCENT_LEVEL
    assert ascent.mean_harm == pytest.approx(math.log(20 / 19), rel=1e-12)
    assert ascent.status is GuardStatus.VIOLATED
    assert admission.failures == (
        FailedCheck(FailedCondition.GUARD, ExperimentMetric.ASCENT_LEVEL, (J,)),
    )
    assert admission.verdict is AdmissionVerdict.REJECTED


def test_useful_shape_learned_at_history_is_admitted() -> None:
    """C16 : la même forme, vraie à l'historique et le jour évalué — le recalage la
    garde : gain ``log(19/18)``, aucun dommage, candidat provisoire ; contre v0 brut,
    ``log(10/9)``."""
    regimes = (A,) * 3 + (D,) * 3
    truth = [100.0] * 3 + [90.0] * 3
    days = [
        day("historique", "2026-06-01", truth, [100.0] * 6, truth, regimes),
        day("j", J.isoformat(), truth, [100.0] * 6, truth, regimes),
    ]
    admission = _admit(days)
    assert admission.mean_gain == pytest.approx(math.log(19 / 18), rel=1e-12)
    assert admission.mean_raw_gain == pytest.approx(math.log(10 / 9), rel=1e-12)
    assert admission.failures == ()
    assert admission.verdict is AdmissionVerdict.PROVISIONAL


def test_guard_bound_is_inclusive() -> None:
    """C22, D10.4 : une montée dégradée de ``η = 0,005`` exactement en réels (``H`` et
    ``2η`` inclusifs, à ``ε`` près) : candidat provisoire."""
    regimes = (A,) * 3 + (D,) * 3
    days = [
        history(regimes=regimes),
        day(
            "j",
            J.isoformat(),
            [100.0] * 6,
            [100.0] * 3 + [110.0] * 3,
            [100 * math.exp(0.005)] * 3 + [100.0] * 3,
            regimes,
        ),
    ]
    admission = _admit(days)
    ascent = admission.guards[1]
    assert ascent.mean_harm == pytest.approx(0.005, abs=1e-12)
    assert ascent.status is GuardStatus.SATISFIED
    assert admission.verdict is AdmissionVerdict.PROVISIONAL


@pytest.mark.parametrize(
    ("excess", "status"),
    [
        (NUMERIC_TOLERANCE / 2, GuardStatus.SATISFIED),
        (3 * NUMERIC_TOLERANCE, GuardStatus.VIOLATED),
    ],
    ids=["dans-epsilon", "au-dela"],
)
def test_guard_bounds_are_read_within_epsilon(
    excess: float, status: GuardStatus
) -> None:
    """Décision E2, D10.4 : la montée du candidat dégradée de ``2η + excès`` le premier
    jour, intacte le second — ``H_jk`` dépasse ``2η`` et ``H̄`` dépasse ``η̄`` de
    ``excès / 2`` : sous ``ε``, le garde-fou tient (``H̄ ≤ η̄ + ε``, ``H_jk ≤ 2η_jk +
    ε``) ; au-delà, il est dépassé ce jour-là."""
    regimes = (A,) * 3 + (D,) * 3
    harm = 2 * 0.005 + excess
    j1, j2 = date(2026, 6, 10), date(2026, 6, 11)
    days = [
        history(regimes=regimes),
        day(
            "j1",
            j1.isoformat(),
            [100.0] * 6,
            [100.0] * 3 + [110.0] * 3,
            [100 * math.exp(harm)] * 3 + [100.0] * 3,
            regimes,
        ),
        day(
            "j2",
            j2.isoformat(),
            [100.0] * 6,
            [100.0] * 3 + [110.0] * 3,
            [100.0] * 6,
            regimes,
        ),
    ]
    admission = _admit(days)
    ascent = admission.guards[1]
    assert ascent.metric is ExperimentMetric.ASCENT_LEVEL
    assert [v.harm for v in ascent.values] == [pytest.approx(harm, abs=1e-12), 0.0]
    assert ascent.mean_threshold == 0.005
    assert ascent.status is status
    if status is GuardStatus.SATISFIED:
        assert admission.failures == ()
        assert admission.verdict is AdmissionVerdict.PROVISIONAL
    else:
        assert admission.failures == (
            FailedCheck(FailedCondition.GUARD, ExperimentMetric.ASCENT_LEVEL, (j1,)),
        )


@pytest.mark.parametrize(
    ("harm", "status"),
    [
        (0.008, GuardStatus.SATISFIED),
        (0.012, GuardStatus.VIOLATED),
    ],
    ids=["entre-eta-et-2eta", "au-dela-de-2eta"],
)
def test_guard_day_bound_is_twice_eta(harm: float, status: GuardStatus) -> None:
    """D10.4 : la montée dégradée de ``harm`` un jour sur trois, intacte les deux
    autres — ``H̄ = harm / 3`` reste sous ``η̄`` : seule la condition par jour,
    ``H_jk ≤ 2η_jk``, départage ; entre ``η`` et ``2η`` le garde-fou tient, au-delà il
    est dépassé ce jour-là."""
    regimes = (A,) * 3 + (D,) * 3
    days = [history(regimes=regimes)]
    on = [date(2026, 6, 10), date(2026, 6, 11), date(2026, 6, 12)]
    for k, when in enumerate(on):
        degraded = harm if k == 0 else 0.0
        days.append(
            day(
                f"j{k}",
                when.isoformat(),
                [100.0] * 6,
                [100.0] * 3 + [110.0] * 3,
                [100 * math.exp(degraded)] * 3 + [100.0] * 3,
                regimes,
            )
        )
    admission = _admit(days)
    ascent = admission.guards[1]
    assert ascent.mean_harm is not None
    assert ascent.mean_harm == pytest.approx(harm / 3, rel=1e-9)
    assert ascent.mean_harm < 0.005
    assert ascent.status is status
    expected = (
        ()
        if status is GuardStatus.SATISFIED
        else (
            FailedCheck(FailedCondition.GUARD, ExperimentMetric.ASCENT_LEVEL, (on[0],)),
        )
    )
    assert admission.failures == expected


def test_guard_violated_on_mean_names_no_day() -> None:
    """C23, D10.4 : ``|L|`` dégradé en moyenne au-delà de ``η̄`` sans qu'aucun jour
    dépasse ``2η`` — l'échec ne nomme aucun jour — ; la montée dégradée au-delà de
    ``2η`` le nomme ; le passage aggravé de 1 % exactement tient (borne incluse)."""
    regimes = (A,) * 3 + (D,) * 3
    days = [
        history(regimes=regimes),
        day(
            "j",
            J.isoformat(),
            [100.0] * 6,
            [100.0] * 3 + [110.0] * 3,
            [112.0] * 3 + [100.0] * 3,
            regimes,
        ),
    ]
    admission = _admit(days)
    assert admission.passages.status is GuardStatus.SATISFIED
    assert admission.passages.values[0].worst == pytest.approx(0.01, abs=1e-15)
    assert admission.failures == (
        FailedCheck(FailedCondition.GUARD, ExperimentMetric.LEVEL, ()),
        FailedCheck(FailedCondition.GUARD, ExperimentMetric.ASCENT_LEVEL, (J,)),
    )
    assert admission.verdict is AdmissionVerdict.REJECTED


def _passage_entry(early: float | None) -> list[AdmissionInput]:
    """C25 : un jour dont ``K`` est un passage de poids nul après trois segments de
    montée, puis l'arrivée ; (0) prévoit le passage juste (300 s) et l'arrivée en 990 s,
    (1) le passage en ``early`` et l'arrivée juste (900 s)."""
    support = 303.0 if early is None else early
    candidate = [support / 3] * 3 + [100.0] * 3 + [(600.0 - support) / 3] * 3
    days = [
        history(),
        day("j", J.isoformat(), [100.0] * 9, [100.0] * 6 + [130.0] * 3, candidate),
    ]
    entry = inputs(days)[-1]
    assert entry.observation is not None
    assert entry.base is not None
    assert entry.candidate is not None
    seen = entry.observation
    prefix = tuple(
        math.fsum(s.times_s[c] for s in seen.segments[:3]) for c in range(len(CLOCKS))
    )
    members = (TargetMember(0, False), TargetMember(None, True))
    seen = replace(
        seen,
        members=members,
        targets=(ObservedPoint(300.0, None, 0, None, prefix), seen.targets[0]),
    )
    f0 = replace(entry.base.forecast, target_s=(300.0, 990.0))
    f1 = replace(entry.candidate.forecast, target_s=(early, 900.0))
    return [
        replace(
            entry,
            observation=seen,
            raw=score_scenario(seen, f0),
            base=calibrated_scores(
                seen, f0, [c.calibration for c in entry.base.clocks], base=f0
            ),
            candidate=calibrated_scores(
                seen, f1, [c.calibration for c in entry.candidate.clocks], base=f0
            ),
        )
    ]


PASSAGE_K = DeclaredUsageTarget(
    "a", (TargetMember(0, False), TargetMember(None, True)), (0.0, 1.0)
)
PASSAGE_REFS = (local(ExperimentMetric.ASCENT_LEVEL, 0.2),)
"""La montée, dégradée de ``log(1,01)`` par le passage précoce, sous ``η = 0,02``."""


@pytest.mark.parametrize(
    ("early", "worst", "status", "verdict"),
    [
        (303.0, 0.01, GuardStatus.SATISFIED, AdmissionVerdict.PROVISIONAL),
        (303.03, 0.0101, GuardStatus.VIOLATED, AdmissionVerdict.REJECTED),
    ],
    ids=["un-pour-cent", "au-dela"],
)
def test_passage_guard_counts_a_zero_weight_passage(
    early: float, worst: float, status: GuardStatus, verdict: AdmissionVerdict
) -> None:
    """C25, D10.4, P11 : un passage de poids nul compte au garde-fou des passages —
    aggravé de 1 % exactement (``3/300``), il tient ; au-delà, l'admission est rejetée
    aux passages, ce jour-là. Le gain d'usage, à l'arrivée seule : ``90/990``."""
    exp = experiment(USAGE, references=PASSAGE_REFS, usage_targets=(PASSAGE_K,))
    admitted = admit(exp, _passage_entry(early), PASSAGE_REFS)
    assert isinstance(admitted, Admission)
    assert admitted.mean_gain == pytest.approx(90 / 990, rel=1e-12)
    value = admitted.passages.values[0]
    assert value.passages == 2
    assert value.worst == pytest.approx(worst, rel=1e-9)
    assert admitted.passages.status is status
    assert admitted.verdict is verdict
    failed = [f for f in admitted.failures if f.condition is FailedCondition.PASSAGES]
    assert failed == (
        [FailedCheck(FailedCondition.PASSAGES, None, (J,))]
        if status is GuardStatus.VIOLATED
        else []
    )


def test_missing_passage_forecast_is_to_review() -> None:
    """C25, D10.4 : la prévision du candidat au passage absente — cible et passages non
    calculables : « à revoir »."""
    exp = experiment(USAGE, references=PASSAGE_REFS, usage_targets=(PASSAGE_K,))
    admitted = admit(exp, _passage_entry(None), PASSAGE_REFS)
    assert isinstance(admitted, Admission)
    assert admitted.passages.status is GuardStatus.UNAVAILABLE
    causes = [r.cause for r in admitted.review]
    assert causes[0] is ReviewCause.TARGET_UNAVAILABLE
    assert causes[-1] is ReviewCause.PASSAGES_UNAVAILABLE
    assert admitted.verdict is AdmissionVerdict.TO_REVIEW


# ---------------------------------------------------------------------------
# « À revoir » (D10.2, D10.4 ; P13)
# ---------------------------------------------------------------------------


def test_no_observed_passage_is_to_review() -> None:
    """C4, D10.4 : l'arrivée non observée — la cible de descente se calcule, mais le
    garde-fou des passages ne s'applique à aucune performance évaluable : « à
    revoir »."""
    admission = _admit(_one_day(no_arrival=True))
    assert admission.mean_gain == pytest.approx(math.log(1.06), rel=1e-12)
    assert admission.passages.values == ()
    assert admission.passages.status is GuardStatus.NOT_EVALUABLE
    assert admission.review == (
        ReviewReason(ReviewCause.PASSAGES_NOT_APPLICABLE, None, ()),
    )
    assert admission.verdict is AdmissionVerdict.TO_REVIEW


def test_candidate_error_on_a_calibration_member_is_to_review() -> None:
    """C5, P13 : une projection du candidat absente à l'historique — (1) est en
    erreur du modèle le jour évalué, qui reste évaluable : cible, garde-fous et
    passages non calculables, « à revoir », aucun échec calculable."""
    broken = replace(history(), candidate=(None,) + (100.0,) * 8)
    admission = _admit(
        [broken, day("j", J.isoformat(), [100.0] * 9, [110.0] * 9, [100.0] * 9)]
    )
    assert admission.evaluable == 1
    assert list(admission.review) == [
        ReviewReason(ReviewCause.TARGET_UNAVAILABLE, None, (J,)),
        *_unavailable_guards(tuple(m for m in GUARD_METRICS if m is not M), J),
        ReviewReason(ReviewCause.PASSAGES_UNAVAILABLE, None, (J,)),
    ]
    assert admission.failures == ()
    assert admission.mean_raw_gain is None
    assert admission.verdict is AdmissionVerdict.TO_REVIEW


def test_raw_mean_is_absent_if_one_raw_gain_is_missing() -> None:
    """C6, décision E5 : un jour sans le candidat — la moyenne contre v0 brut n'est pas
    calculée sur les seuls jours restants ; elle est absente, le compte de ses gains
    publié."""
    days = [
        history(),
        day("j1", EVALUATED["j1"], [100.0] * 9, [110.0] * 9, [None] * 9),
        day("j2", EVALUATED["j2"], [100.0] * 9, [110.0] * 9, [100.0] * 9),
    ]
    admission = _admit(days)
    assert (admission.evaluable, admission.positive, admission.required) == (2, 1, 2)
    assert admission.mean_gain is None
    assert (admission.mean_raw_gain, admission.raw_gains) == (None, 1)
    assert admission.verdict is AdmissionVerdict.TO_REVIEW


def test_common_denominator_of_usage() -> None:
    """C24, D7.4 dans une expérience : ``q_usage`` de (0), de (1) et de v0 brut au
    dénominateur commun ``P^(0)`` calé — v0 brut à 990 s pour 900 s : 90/900. Sous
    ``q_usage``, le seuil est fixe, sans ``F`` ni motif de la locale (D10.3)."""
    days = [
        replace(history(), v0=(110.0,) * 9),
        day("j", J.isoformat(), [100.0] * 9, [110.0] * 9, [100.0] * 9),
    ]
    admission = _admit(days, experiment(USAGE))
    assessed = admission.performances[-1]
    assert assessed.base is not None
    assert assessed.candidate is not None
    assert assessed.raw is not None
    assert assessed.base.value == pytest.approx(0.0, abs=1e-12)
    assert assessed.candidate.value == pytest.approx(0.0, abs=1e-12)
    assert assessed.raw.value == pytest.approx(0.1, rel=1e-12)
    assert admission.mean_raw_gain == pytest.approx(0.1, rel=1e-12)
    assert assessed.source is ThresholdSource.FIXED
    assert (assessed.reference, assessed.local_unavailability) == (None, None)
    assert assessed.threshold == GAIN_FLOOR


def test_delta_bound_is_inclusive() -> None:
    """C9, décision E2 : un gain de ``log(exp(0,01))`` — sous 0,010 d'un arrondi —
    tient le seuil moyen à ``ε`` près : candidat provisoire."""
    days = [
        history(),
        day("j", J.isoformat(), [100.0] * 9, [100 * math.exp(0.01)] * 9, [100.0] * 9),
    ]
    admission = _admit(days)
    assert admission.mean_gain is not None
    assert admission.mean_gain < GAIN_FLOOR
    assert admission.mean_threshold == GAIN_FLOOR
    assert admission.verdict is AdmissionVerdict.PROVISIONAL


# ---------------------------------------------------------------------------
# K déclaré (D7.4 ; P11 ; décision E4)
# ---------------------------------------------------------------------------

_MEMBERS = (TargetMember(0, False), TargetMember(None, True))


def _k_day(points: tuple[ObservedPoint, ...], **options: Any) -> Day:
    """C14 : un segment mixte, puis une montée, un plat, une descente ; ``K`` un
    passage puis l'arrivée, de cumulés v0 (100 ; 400) et candidat (90 ; 360)."""
    return day(
        "j",
        J.isoformat(),
        [100.0] * 4,
        [100.0] * 4,
        [90.0] * 4,
        (X, A, F, D),
        usage_k=UsageK(_MEMBERS, points, (100.0, 400.0), (90.0, 360.0)),
        **options,
    )


_PASSAGE = ObservedPoint(100.0, None, 0, None, (100.0,) + (0.0,) * 10)
_ARRIVAL = ObservedPoint(400.0, 4, None, None, (400.0,) + (240.0,) * 10)
_ABSENT_ARRIVAL = ObservedPoint(400.0, 4, None, Unavailability.ABSENT, None)


def test_zero_passage_time_keeps_usage_computable() -> None:
    """C14 : un temps de passage nul sous l'horloge déclarée — la cible ``q_usage`` se
    calcule ; les garde-fous de régime, aucune classe de trois segments, ne sont pas
    exigés ; le passage nul ne compte pas au garde-fou des passages."""
    days = [history(regimes=(X, A, F, D)), _k_day((_PASSAGE, _ARRIVAL), zero=(0,))]
    admission = _admit(days, experiment(USAGE, CLOCKS[1]))
    assessed = admission.performances[-1]
    assert assessed.base is not None
    assert assessed.candidate is not None
    assert assessed.base.value == pytest.approx(0.4, rel=1e-12)
    assert assessed.candidate.value == pytest.approx(0.3, rel=1e-12)
    assert [(v.passages, v.worst) for v in admission.passages.values] == [(1, 0.0)]
    assert [g.status for g in admission.guards] == [GuardStatus.SATISFIED] + [
        GuardStatus.NOT_EVALUABLE
    ] * 6
    assert admission.verdict is AdmissionVerdict.PROVISIONAL


def test_zero_weight_member_must_be_observed() -> None:
    """C14, P11 : un élément de ``K`` de poids nul dont le passage n'est pas observé
    rend la performance non évaluable sous ``q_usage``."""
    absent = replace(_PASSAGE, times_s=None, unavailability=Unavailability.ABSENT)
    entries = inputs([history(regimes=(X, A, F, D)), _k_day((absent, _ARRIVAL))])
    target = DeclaredUsageTarget("a", _MEMBERS, (0.0, 1.0))
    exp = experiment(USAGE, CLOCKS[1], usage_targets=(target,))
    assessed = admit(exp, entries[-1:], ())
    assert not isinstance(assessed, Admission)
    assert [a.motif for a in assessed] == [NonEvaluable.PASSAGE_UNAVAILABLE]


def test_prefix_k_leaves_the_arrival_optional() -> None:
    """Décision E4 : l'arrivée non observée rend la performance non évaluable au ``K``
    par défaut ; au ``K`` déclaré en préfixe — le seul passage —, elle est évaluable
    sur ce passage."""
    days = [
        replace(history(regimes=(X, A, F, D)), route="h"),
        _k_day((_PASSAGE, _ABSENT_ARRIVAL)),
    ]
    default = assess_performances(experiment(USAGE), inputs(days), ())
    assert default[-1].motif is NonEvaluable.PASSAGE_UNAVAILABLE
    prefix = DeclaredUsageTarget("a", (TargetMember(0, False),), (1.0,))
    exp = experiment(USAGE, usage_targets=(prefix,))
    admission = _admit(days, exp)
    assessed = admission.performances[-1]
    assert assessed.motif is None
    assert assessed.base is not None
    assert assessed.candidate is not None
    assert assessed.base.value == pytest.approx(0.0, abs=1e-12)
    assert assessed.candidate.value == pytest.approx(0.1, rel=1e-12)


# ---------------------------------------------------------------------------
# metric_value ; le document d'admission
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("v0", [90.0, 110.0], ids=["rapide", "lent"])
def test_metric_value_is_absolute_for_levels(v0: float) -> None:
    """D10.1 : ``|L|`` et ``|E_R|`` en valeur absolue, ``D_R`` tel quel."""
    entry = inputs(_one_day())[-1]
    days = [history(), day("j", J.isoformat(), [100.0] * 9, [v0] * 9, [100.0] * 9)]
    entry = inputs(days)[-1]
    assert entry.raw is not None
    scores = entry.raw.clocks[0]
    expected = abs(math.log(v0 / 100.0))
    assert metric_value(scores, ExperimentMetric.LEVEL).value == pytest.approx(expected)
    for metric in (ExperimentMetric.ASCENT_LEVEL, M):
        assert metric_value(scores, metric).value == pytest.approx(expected)
    dispersion = metric_value(scores, ExperimentMetric.DESCENT_DISPERSION)
    descent = scores.support.classes[list(RegimeClass).index(RegimeClass.DESCENT)]
    assert dispersion == descent.dispersion


@pytest.mark.parametrize(
    "days",
    [
        [
            history(2.0),
            day("j", J.isoformat(), [400 / 3] * 9, [100.0] * 9, [200.0] * 9),
        ],
        [
            replace(history(), candidate=(None,) + (100.0,) * 8),
            day("j", J.isoformat(), [100.0] * 9, [110.0] * 9, [100.0] * 9),
        ],
        [history(), day("j", J.isoformat(), [100.0] * 9, [100.0] * 9, [110.0] * 9)],
    ],
    ids=["provisoire", "a-revoir", "rejete"],
)
def test_admission_document_round_trip(days: list[Day]) -> None:
    """Décision Q4 : le document d'admission, au format 3, se relit égal à l'objet
    écrit, au bit."""
    admission = _admit(days)
    data = encode_document(admission, 3)
    decoded = decode_document(data, Admission, 3)
    assert decoded == admission
    assert encode_document(decoded, 3) == data


def test_declared_k_outside_the_default_k_is_refused() -> None:
    """Précondition d'``admit`` (décisions Q6 et E4) : un ``K`` déclaré dont un élément
    n'est pas dans le ``K`` par défaut d'une observation de son parcours —
    l'historique, sans passage — est refusé ; ``prepare_experiment`` le refuse avant la
    DÉCLARATION."""
    days = [history(regimes=(X, A, F, D)), _k_day((_PASSAGE, _ARRIVAL))]
    prefix = DeclaredUsageTarget("a", (TargetMember(0, False),), (1.0,))
    with pytest.raises(
        ValueError,
        match=re.escape(
            "admit : K du parcours 'a', éléments hors du K par défaut de "
            "l'observation : [TargetMember(occurrence_index=0, arrival=False)]"
        ),
    ):
        admit(experiment(USAGE, usage_targets=(prefix,)), inputs(days), ())


def test_computable_failures_of_unavailable_guards_are_published() -> None:
    """P13, D10.4 : un garde-fou indisponible — le candidat sans prévision le premier
    jour — dont un jour calculable dépasse ``2η`` publie cet échec, ce jour-là ; de
    même le garde-fou des passages. La montée du candidat, trop lente de 10 % le
    second jour, dégrade ``|E_montée|`` de ``log(1,1)`` et ``|L|`` de ``log(930/900)``,
    l'arrivée de ``30/900``."""
    j1, j2 = date(2026, 6, 10), date(2026, 6, 11)
    days = [
        history(),
        day("j1", j1.isoformat(), [100.0] * 9, [100.0] * 9, [None] * 9),
        day("j2", j2.isoformat(), [100.0] * 9, [100.0] * 9, [110.0] * 3 + [100.0] * 6),
    ]
    admission = _admit(days)
    assert all(g.status is GuardStatus.UNAVAILABLE for g in admission.guards)
    assert admission.passages.status is GuardStatus.UNAVAILABLE
    level, ascent = admission.guards[0].values[1], admission.guards[1].values[1]
    assert level.harm == pytest.approx(math.log(930 / 900), rel=1e-12)
    assert ascent.harm == pytest.approx(math.log(1.1), rel=1e-12)
    assert admission.passages.values[1].worst == pytest.approx(30 / 900, rel=1e-12)
    assert admission.failures == (
        FailedCheck(FailedCondition.VOTE, None, ()),
        FailedCheck(FailedCondition.GUARD, ExperimentMetric.LEVEL, (j2,)),
        FailedCheck(FailedCondition.GUARD, ExperimentMetric.ASCENT_LEVEL, (j2,)),
        FailedCheck(FailedCondition.PASSAGES, None, (j2,)),
    )
    assert admission.verdict is AdmissionVerdict.TO_REVIEW


def test_observation_motif_precedes_a_failed_calibration() -> None:
    """Précision de D7.1 (M4b-1) : l'observation passe avant le modèle. Le candidat en
    erreur du modèle à l'apprentissage, et un temps nul sur le support le jour évalué :
    ses valeurs de classe sont indisponibles au motif ``temps nul``, comme celles de
    (0) ; son ``|L|``, calculable sur l'observation, l'est au motif ``erreur du
    modèle``."""
    broken = replace(history(), candidate=(None,) + (100.0,) * 8)
    days = [
        broken,
        day("j", J.isoformat(), [100.0] * 9, [110.0] * 9, [100.0] * 9, zero=(0,)),
    ]
    admission = _admit(days, experiment(USAGE, CLOCKS[1]))
    level = admission.guards[0].values[0]
    assert level.base.value is not None
    assert level.candidate.unavailability is Unavailability.MODEL_ERROR
    for guard in admission.guards[1:]:
        (value,) = guard.values
        assert value.base.unavailability is Unavailability.ZERO_TIME
        assert value.candidate == value.base
