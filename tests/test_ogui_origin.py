"""La règle à l'origine pour l'usage (OG-UI, § 6.1 du brief) : le cache des intervalles
dans la règle, les intervalles des candidates écrits une fois, l'empreinte de l'index
que portent l'estimation et que vérifient le compagnon et le document d'absence.

Le monde de ``tests/test_og1_origin.py`` : ses aides ``corpus``, ``_season`` et
``rule`` (l'aide ``corpus`` donne ``"b" * 64`` à tout corpus)."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from mountain_perf.backtest import rolling
from mountain_perf.estimation import origin
from mountain_perf.estimation.intervals import (
    ActivityIntervals,
    TraceRefusal,
    activity_intervals,
)
from mountain_perf.estimation.origin import (
    CurveCorpus,
    candidate_intervals,
    intervals_cache,
    origin_absence_document,
    origin_companion,
)
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS
from mountain_perf.schemas import ActivityIndex, ActivityRecording, ParameterSet
from mountain_perf.validation import ContractError
from test_estimation_curve import DEFAULTS
from test_og1_origin import (
    PROFILE,
    _season,
    at,
    corpus,
    origin_selection,
    rule,
)
from test_schemas_interim import SOURCE

OTHER_INDEX = "c" * 64


def _season_corpus() -> CurveCorpus:
    return corpus(_season())


def _call(
    cache: Any, recording: ActivityRecording, profile: ParameterSet
) -> ActivityIntervals | TraceRefusal:
    result: ActivityIntervals | TraceRefusal = cache(
        recording,
        profile,
        hr_lag_s=DEFAULTS["hr_lag_s"],
        hr_min_coverage=DEFAULTS["hr_min_coverage"],
        max_elapsed_s=None,
    )
    return result


# --- Le cache des intervalles ---------------------------------------------------------


def test_the_cache_returns_the_same_object() -> None:
    season = _season_corpus()
    cache = intervals_cache(season)
    recording = season.recordings["s0"]
    first = _call(cache, recording, PROFILE)
    assert _call(cache, recording, PROFILE) is first


def test_the_cache_key_holds_the_profile_parameters() -> None:
    season = _season_corpus()
    cache = intervals_cache(season)
    recording = season.recordings["s0"]
    first = _call(cache, recording, PROFILE)
    other = ParameterSet(PROFILE_PARAMETER_SPECS, {"smoothing_window_m": 50.0})
    assert other.values != PROFILE.values
    assert _call(cache, recording, other) is not first


def test_the_cache_lives_in_the_rule() -> None:
    assert rolling.intervals_cache is origin.intervals_cache


# --- Les intervalles des candidates ---------------------------------------------------


def _intervals(season: CurveCorpus, ref: str) -> ActivityIntervals | TraceRefusal:
    return activity_intervals(
        season.recordings[ref],
        PROFILE,
        hr_lag_s=DEFAULTS["hr_lag_s"],
        hr_min_coverage=DEFAULTS["hr_min_coverage"],
        max_elapsed_s=None,
    )


def _candidates(season: CurveCorpus, refs: list[str], provider: Any) -> Any:
    return candidate_intervals(
        season,
        refs,
        origin_selection(),
        DEFAULTS,
        PROFILE,
        intervals_of=provider,
    )


def test_candidate_intervals_refuses_intervals_of_another_activity() -> None:
    season = _season_corpus()
    other = _intervals(season, "s1")
    assert isinstance(other, ActivityIntervals)

    def provider(recording: ActivityRecording, *_: Any, **__: Any) -> Any:
        return other

    with pytest.raises(ContractError) as raised:
        _candidates(season, ["s0"], provider)
    assert str(raised.value) == "intervals_of : les intervalles de s1 rendus pour s0."


def test_candidate_intervals_passes_a_refusal() -> None:
    season = _season_corpus()
    refusal = TraceRefusal.NO_TRACE

    def provider(recording: ActivityRecording, *_: Any, **__: Any) -> Any:
        return refusal

    assert _candidates(season, ["s0"], provider) == (refusal,)


def test_candidate_intervals_refuses_a_missing_recording() -> None:
    season = _season_corpus()
    with pytest.raises(ContractError) as raised:
        _candidates(season, ["s0", "absente"], None)
    assert str(raised.value) == (
        "corpus incomplet : l'enregistrement de absente manque."
    )


def test_candidate_intervals_follow_the_order_of_refs() -> None:
    season = _season_corpus()
    calls: list[str] = []

    def provider(recording: ActivityRecording, *args: Any, **kwargs: Any) -> Any:
        calls.append(recording.activity_ref)
        return activity_intervals(recording, *args, **kwargs)

    found = _candidates(season, ["s3", "s0", "s2"], provider)
    assert calls == ["s3", "s0", "s2"]
    assert [item.activity_ref for item in found] == ["s3", "s0", "s2"]


# --- L'empreinte de l'index -----------------------------------------------------------


def _absent(season: CurveCorpus) -> Any:
    """La règle sans candidate : l'origine du 2024-03-20, avant tout départ."""
    return rule(season, origin=at(19, 23))


def test_the_estimate_carries_the_index_digest() -> None:
    season = dataclasses.replace(_season_corpus(), index_sha256="d" * 64)
    found = rule(season)
    assert found.estimate is not None
    assert found.index_sha256 == season.index_sha256
    absent = _absent(season)
    assert absent.estimate is None
    assert absent.index_sha256 == season.index_sha256


def _refusal_text() -> str:
    return (
        f"corpus : son index ({OTHER_INDEX[:12]}) n'est pas celui de la règle "
        f"({'b' * 12})."
    )


def test_origin_companion_refuses_another_index() -> None:
    season = _season_corpus()
    found = rule(season)
    other = dataclasses.replace(season, index_sha256=OTHER_INDEX)
    with pytest.raises(ContractError) as raised:
        origin_companion(
            found,
            other,
            origin_selection(),
            DEFAULTS,
            PROFILE,
            commit="c" * 40,
            generated_at=at(1, 12, month=4),
        )
    assert str(raised.value) == _refusal_text()


def test_origin_absence_document_refuses_another_index() -> None:
    season = _season_corpus()
    absent = _absent(season)
    other = dataclasses.replace(season, index_sha256=OTHER_INDEX)
    with pytest.raises(ContractError) as raised:
        origin_absence_document(absent, other)
    assert str(raised.value) == _refusal_text()
    assert origin_absence_document(absent, season)


def test_a_hand_made_corpus_without_the_retained_is_refused() -> None:
    season = _season_corpus()
    found = rule(season)
    assert found.estimate is not None
    after = next(e for e in season.index.entries if e.activity_ref == "apres")
    hand_made = CurveCorpus(
        season.athlete_ref,
        ActivityIndex((after,), (SOURCE,)),
        season.index_sha256,
        {"apres": season.recordings["apres"]},
        {"apres": season.recording_sha256["apres"]},
    )
    with pytest.raises(ContractError) as raised:
        origin_companion(
            found,
            hand_made,
            origin_selection(),
            DEFAULTS,
            PROFILE,
            commit="c" * 40,
            generated_at=at(1, 12, month=4),
        )
    assert str(raised.value) == (
        "corpus : aucune activité retenue par la règle n'est à son index."
    )
