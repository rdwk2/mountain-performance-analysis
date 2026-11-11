"""Garanties d'OG-1 que la suite ne tenait pas (balayage mutmut de la PR #41, G1 à G10).

Le chargement du corpus (``runs.load_curve_corpus``) prend exactement les décisions que
``select_at_origin`` prend sur l'index seul : aux bornes exactes (fin d'index égale à
l'origine, égale à la borne basse), et quand une activité qui finit après l'origine
précède, dans l'ordre de l'index, une activité à lire. Puis les champs d'une absence et
d'une courbe à l'origine, « contribue » aux bornes, et les écarts d'une absence de
tranche.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

from fixtures.processed import write_interim
from mountain_perf.config import data_dir
from mountain_perf.estimation.curve import (
    CURVE_ESTIMATION_PARAMETER_SPECS,
    BinValue,
    IntervalExclusion,
)
from mountain_perf.estimation.origin import (
    OriginHistory,
    OriginOutcome,
    TemporalDecision,
    estimate_at_origin,
    origin_history,
    retained_start_days,
    window_lower_bound,
)
from mountain_perf.ingest.interim import read_index, read_recording, write_activities
from mountain_perf.runs import load_curve_corpus
from mountain_perf.schemas import ActivityIndex, ParameterSet
from test_estimation_curve import GRADES, activity, interval
from test_ingest_interim import REPORT
from test_og1_cli_at import ORIGIN_0325, TRAIL, activities, damage
from test_og1_fates import absent, fates, outcome_of
from test_og1_origin import (
    ORIGIN,
    PROFILE,
    _season,
    activity_pair,
    at,
    corpus,
    inspected,
    origin_selection,
    rule,
)
from test_og1_origin import (
    TRAIL as TRAIL_O,
)
from test_schemas_interim import SOURCE, entry


def _rewrite(changes: dict[str, tuple[timedelta, float]]) -> None:
    """Réécrit l'index des fixtures : pour chaque référence, départ = origine +
    décalage, écoulé donné ; enregistrements recalés sur leur départ ; entrées
    retriées."""
    folder = data_dir()
    write_interim(folder)
    index = read_index(folder)
    entries = []
    for item in index.entries:
        if item.activity_ref in changes:
            shift, elapsed = changes[item.activity_ref]
            item = dataclasses.replace(
                item, start_time=ORIGIN_0325 + shift, elapsed_duration_s=elapsed
            )
        entries.append(item)
    entries.sort(key=lambda e: (e.start_time, e.activity_ref))
    recordings = [
        dataclasses.replace(
            read_recording(folder, item.activity_ref), start_time=item.start_time
        )
        for item in entries
        if item.has_recording
    ]
    write_activities(
        folder, dataclasses.replace(index, entries=tuple(entries)), recordings, REPORT
    )


def test_g1_index_end_exactly_at_the_lower_bound_is_read_and_at_the_origin_is_not() -> (
    None
):
    lower = window_lower_bound(ORIGIN_0325, 7)
    assert lower is not None
    elapsed = 3723.5
    _rewrite(
        {
            "a1": (lower - ORIGIN_0325 - timedelta(seconds=elapsed), elapsed),
            "a3": (-timedelta(seconds=elapsed), elapsed),
        }
    )
    damage(activities("recordings", "a3.json"))
    corpus = load_curve_corpus(data_dir(), "x", TRAIL, ORIGIN_0325, 7)
    assert list(corpus.recordings) == ["a1"]


def test_g2_an_activity_ending_after_the_origin_does_not_stop_the_reading() -> None:
    _rewrite(
        {
            "a1": (-timedelta(days=2), 3 * 86400.0),
            "a3": (-timedelta(days=1), 3723.5),
        }
    )
    damage(activities("recordings", "a1.json"))
    corpus = load_curve_corpus(data_dir(), "x", TRAIL, ORIGIN_0325, 56)
    assert list(corpus.recordings) == ["a3"]


# --- La règle (estimation/origin.py) et l'estimateur (estimation/curve.py) ------------


def test_g3_an_index_end_at_the_origin_decides_without_the_recording() -> None:
    pair = activity_pair(
        "o", ORIGIN - timedelta(seconds=600), index_elapsed_s=600.0, recording_s=300.0
    )
    found = inspected([(pair[0], None)])["o"]
    assert found.decision is TemporalDecision.AFTER_ORIGIN
    assert found.recording_sha256 is None


def test_g4_an_activity_started_at_the_origin_is_not_in_the_history() -> None:
    index = ActivityIndex(
        (entry(activity_ref="a", start_time=ORIGIN, elapsed_duration_s=None),),
        (SOURCE,),
    )
    assert origin_history(index, ORIGIN, TRAIL_O) == OriginHistory(0, 0, 0, 0)


def test_g5_an_absence_without_candidate_keeps_its_inputs() -> None:
    season = corpus(_season())
    result = rule(season, window=1, support_threshold_min=12.5)
    assert result.outcome is OriginOutcome.ABSENT
    assert result.candidates == ()
    assert result.athlete_ref == "x"
    assert result.window == 1
    assert result.lower_bound == at(30, 23)
    assert result.activity_types == TRAIL_O
    assert result.support_threshold_min == 12.5
    assert retained_start_days(result, season) is None


def test_g6_an_absence_with_retained_candidates_dates_its_last_retained() -> None:
    """Avec (b) et un seuil de la médiane hors d'atteinte : huit retenues, aucune
    tranche ; la dernière retenue finit le 27 à 09:00."""
    parameters = ParameterSet(
        CURVE_ESTIMATION_PARAMETER_SPECS, {"median_min_moving_s": 3600.0}
    )
    result = estimate_at_origin(
        corpus(_season()),
        "x",
        ORIGIN,
        56,
        origin_selection(value=BinValue.MEDIAN),
        parameters,
        PROFILE,
    )
    assert result.outcome is OriginOutcome.ABSENT
    assert [fate.exclusion for fate in result.activity_fates] == [None] * 8
    assert result.last_retained_end == at(27, 9)


def test_g7_a_curve_at_the_origin_keeps_its_athlete_and_types() -> None:
    result = rule(corpus(_season()))
    assert result.outcome is not OriginOutcome.ABSENT
    assert result.athlete_ref == "x"
    assert result.activity_types == TRAIL_O


def test_g8_a_cell_of_less_than_one_second_contributes() -> None:
    mini = activity("mini", [interval(GRADES[2], 1.0, 0.5)])
    assert fates(outcome_of([mini], ["mini"]))[-1] == ("mini", None, True)


def test_g9_with_the_median_a_cell_exactly_at_the_threshold_contributes() -> None:
    exact = activity("juste", [interval(GRADES[2], 120.0, 60.0)])
    outcome = outcome_of([exact], ["juste"], BinValue.MEDIAN)
    assert fates(outcome)[-1] == ("juste", None, True)


def test_g10_no_bin_keeps_its_interval_exclusions() -> None:
    """Un intervalle de 50 m en 1 s (hors d'échelle) et un intervalle à l'arrêt : aucune
    tranche ; l'écart de l'intervalle reste au diagnostic."""
    fast = activity(
        "vite",
        [
            interval(GRADES[2], 50.0, 1.0),
            interval(GRADES[2], 50.0, 0.0, stopped_s=60.0),
        ],
    )
    outcome = absent(outcome_of([fast], ["vite"]))
    assert outcome.excluded_intervals == ((IntervalExclusion.ABERRANT, 1),)
