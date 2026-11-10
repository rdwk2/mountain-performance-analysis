"""Le sort de chaque activité d'une estimation (OG-1, ``docs/decisions/0020`` ; le motif
d'écart de ``0017``, P2.6, attaché à sa référence) et l'absence de tranche, rendue sans
exception avec son diagnostic. Les intervalles sont construits à la main (règle 1)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from mountain_perf.estimation.curve import (
    ActivityExclusion,
    BinValue,
    CurveEstimate,
    NoCurve,
    estimate_curve,
    estimate_curve_outcome,
)
from mountain_perf.estimation.intervals import ActivityIntervals, TraceRefusal
from mountain_perf.model.curve_io import CurveError
from test_estimation_curve import (
    DEFAULTS,
    GRADES,
    activity,
    interval,
    selection,
    uniform,
)

Fate = tuple[str, ActivityExclusion | None, bool]
Candidates = list[ActivityIntervals | TraceRefusal]


def fates(outcome: CurveEstimate | NoCurve) -> list[Fate]:
    return [
        (f.activity_ref, f.exclusion, f.contributes) for f in outcome.activity_fates
    ]


def outcome_of(
    candidates: Sequence[ActivityIntervals | TraceRefusal],
    refs: Sequence[str],
    value: BinValue = BinValue.POOLED,
    **changes: float,
) -> CurveEstimate | NoCurve:
    chosen = selection(value=value, **changes)
    return estimate_curve_outcome(candidates, refs, chosen, DEFAULTS)


def estimated(outcome: CurveEstimate | NoCurve) -> CurveEstimate:
    assert isinstance(outcome, CurveEstimate)
    return outcome


def absent(outcome: CurveEstimate | NoCurve) -> NoCurve:
    assert isinstance(outcome, NoCurve)
    return outcome


def _short() -> ActivityIntervals:
    """Une activité de 60 s."""
    return activity("court", [interval(GRADES[2])], 60.0)


def _stopped() -> ActivityIntervals:
    """50 m, 0 s de temps M, 60 s à l'arrêt."""
    return activity("arret", [interval(GRADES[2], 50.0, 0.0, stopped_s=60.0)])


def _brief() -> ActivityIntervals:
    """Un intervalle de 50 m en 25 s : sous le seuil de la médiane."""
    return activity("bref", [interval(GRADES[2], 50.0, 25.0)])


def test_two_inverse_assignments_give_the_same_bins_but_not_the_same_fates() -> None:
    """T21 : les mêmes candidates sous deux affectations inverses des références : mêmes
    tranches, mêmes comptes, mêmes écarts, pas les mêmes sorts."""
    candidates: Candidates = [
        uniform("k", 2.0, GRADES),
        TraceRefusal.NO_TRACE,
        _short(),
    ]
    first = estimated(outcome_of(candidates, ["k", "x", "y"], min_duration_s=600.0))
    other = estimated(outcome_of(candidates, ["k", "y", "x"], min_duration_s=600.0))
    assert first.bins == other.bins
    assert first.counts == other.counts
    assert first.excluded_activities == other.excluded_activities
    assert fates(first) == [
        ("k", None, True),
        ("x", ActivityExclusion.NO_TRACE, False),
        ("y", ActivityExclusion.SHORT, False),
    ]
    assert fates(other) == [
        ("k", None, True),
        ("y", ActivityExclusion.NO_TRACE, False),
        ("x", ActivityExclusion.SHORT, False),
    ]


def test_every_motive_is_attached_to_its_reference() -> None:
    candidates: Candidates = [
        activity("raide", [interval(1.5)]),
        uniform("k", 2.0, GRADES),
        TraceRefusal.NO_PROFILE,
        activity("long", [interval(GRADES[2])], 99999.0),
    ]
    refs = ["raide", "k", "p", "long"]
    assert fates(outcome_of(candidates, refs, max_duration_s=7200.0)) == [
        ("raide", ActivityExclusion.NO_INTERVAL, False),
        ("k", None, True),
        ("p", ActivityExclusion.NO_PROFILE, False),
        ("long", ActivityExclusion.LONG, False),
    ]


def test_with_the_median_a_retained_activity_may_not_contribute() -> None:
    """Avec (b), ``bref`` est retenue, mais n'a aucune cellule de la médiane ; avec (a),
    sa cellule de temps M positif la fait contribuer."""
    candidates: Candidates = [
        *(uniform(ref, 2.0, GRADES) for ref in ("a", "b", "c")),
        _brief(),
    ]
    refs = ["a", "b", "c", "bref"]
    median = estimated(outcome_of(candidates, refs, BinValue.MEDIAN))
    assert "bref" in median.activity_refs
    assert fates(median)[-1] == ("bref", None, False)
    assert fates(outcome_of(candidates, refs))[-1] == ("bref", None, True)


def test_a_retained_activity_without_moving_time_does_not_contribute() -> None:
    candidates: Candidates = [uniform("k", 2.0, GRADES), _stopped()]
    assert fates(outcome_of(candidates, ["k", "arret"])) == [
        ("k", None, True),
        ("arret", None, False),
    ]


def test_no_bin_is_an_outcome_with_its_diagnostic() -> None:
    candidates: Candidates = [_stopped(), TraceRefusal.NO_TRACE]
    refs = ["arret", "r"]
    outcome = absent(outcome_of(candidates, refs))
    reason = (
        "Aucune tranche estimée : aucun intervalle retenu n'a de temps en mouvement."
    )
    assert outcome.reason == reason
    assert fates(outcome) == [
        ("arret", None, False),
        ("r", ActivityExclusion.NO_TRACE, False),
    ]
    assert outcome.counts.retained == 1
    assert outcome.counts.candidates == 2
    assert outcome.counts.with_level == 0
    assert outcome.excluded_activities == ((ActivityExclusion.NO_TRACE, 1),)
    with pytest.raises(CurveError) as raised:
        estimate_curve(candidates, refs, selection(), DEFAULTS)
    assert str(raised.value) == reason


def test_no_bin_under_the_median_threshold_is_an_outcome() -> None:
    outcome = absent(outcome_of([_brief()], ["bref"], BinValue.MEDIAN))
    assert outcome.reason == (
        "Aucune tranche estimée : aucune activité n'a 60 s de temps en mouvement dans "
        "une même tranche (valeur (b))."
    )
    assert fates(outcome) == [("bref", None, False)]


def test_no_candidate_is_an_outcome() -> None:
    outcome = absent(outcome_of([], []))
    assert outcome.activity_fates == ()
    assert outcome.counts.candidates == 0


def test_the_outcome_is_the_estimate_when_bins_exist() -> None:
    candidates: Candidates = [uniform("k", 2.0, GRADES)]
    assert outcome_of(candidates, ["k"]) == estimate_curve(
        candidates, ["k"], selection(), DEFAULTS
    )
