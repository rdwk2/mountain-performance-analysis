"""La règle à l'origine (OG-1, ``docs/decisions/0020``) : les fins d'une activité, le
corpus, la sélection à l'origine, l'historique, l'estimation et ses trois issues, le
compagnon. Jours, heures et activités inventés (règle 1) ; les cas T01 à T23 sont ceux
de la passe experte."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any

import pytest

from fixtures.montees import FLAT, climb_at
from fixtures.montees import recording as montee
from mountain_perf.estimation.curve import (
    CURVE_ESTIMATION_PARAMETER_SPECS,
    ActivityExclusion,
    CurveEstimate,
    CurveSelection,
    estimate_curve,
    select_candidates,
)
from mountain_perf.estimation.intervals import (
    ActivityIntervals,
    TraceRefusal,
    activity_intervals,
)
from mountain_perf.estimation.origin import (
    NO_CANDIDATE,
    CurveCorpus,
    EndMethod,
    Inspection,
    OriginEstimate,
    OriginHistory,
    OriginOutcome,
    OriginWindow,
    TemporalDecision,
    activity_end,
    check_origin,
    check_window,
    cold_start_warning,
    estimate_at_origin,
    origin_document,
    origin_history,
    recording_end,
    retained_start_days,
    select_at_origin,
    window_lower_bound,
)
from mountain_perf.gpx.profile import PROFILE_PARAMETER_SPECS
from mountain_perf.schemas import (
    ActivityIndex,
    ActivityRecording,
    HeartRateChannel,
    IndexedActivity,
    ParameterSet,
    PositionChannel,
    RecordingSession,
    TimerEvent,
    TimerEventType,
)
from mountain_perf.validation import ContractError
from test_estimation_curve import DEFAULTS, selection
from test_schemas_interim import SOURCE, entry
from test_schemas_interim import recording as bare_recording

SHA = "a" * 64

Pair = tuple[IndexedActivity, ActivityRecording | None]


def at(day: int, hour: int, minute: int = 0, month: int = 3) -> datetime:
    """Un instant de 2024, en UTC."""
    return datetime(2024, month, day, hour, minute, tzinfo=UTC)


def activity_pair(
    ref: str,
    start: datetime,
    *,
    index_elapsed_s: float | None,
    recording_s: float,
    activity_type: str = "trail_running",
    recorded_start: datetime | None = None,
    descent: bool = True,
) -> tuple[IndexedActivity, ActivityRecording]:
    """Une entrée et un enregistrement sans bruit : un replat, 500 m à 20 % et, si
    ``descent``, 400 m à −15 %, dont les temps sont mis à l'échelle pour que le dernier
    instant soit à ``recording_s`` de son départ."""
    segments = [FLAT, climb_at(600.0, 0.2, 100.0)]
    if descent:
        segments.append((400.0, -0.15, 1.5))
    base = montee(segments, noise=False, activity_ref=ref)
    assert base.position is not None
    assert base.elevation is not None
    factor = recording_s / base.position.time_s[-1]
    scaled = tuple(t * factor for t in base.position.time_s)
    return (
        entry(
            activity_ref=ref,
            start_time=start,
            elapsed_duration_s=index_elapsed_s,
            source_activity_type=activity_type,
        ),
        dataclasses.replace(
            base,
            start_time=recorded_start if recorded_start is not None else start,
            position=dataclasses.replace(base.position, time_s=scaled),
            elevation=dataclasses.replace(base.elevation, time_s=scaled),
        ),
    )


def corpus(pairs: Sequence[Pair], *, athlete: str = "x") -> CurveCorpus:
    """Le corpus de ``pairs`` : l'index trié, l'empreinte ``"b" * 64``, les
    enregistrements présents, ``SHA`` pour chacun."""
    entries = sorted(
        (pair[0] for pair in pairs),
        key=lambda item: (item.start_time.timestamp(), item.activity_ref),
    )
    recordings = {
        pair[0].activity_ref: pair[1] for pair in pairs if pair[1] is not None
    }
    return CurveCorpus(
        athlete,
        ActivityIndex(tuple(entries), (SOURCE,)),
        "b" * 64,
        recordings,
        dict.fromkeys(recordings, SHA),
    )


def _bare_recording(**changes: object) -> ActivityRecording:
    """Un enregistrement de ``test_schemas_interim``, parti le 30 à 08:00."""
    return bare_recording(start_time=at(30, 8), **changes)


ORIGIN = at(31, 22)
"""00:00 à Paris le 2024-04-01, heure d'été."""
LOWER_56 = at(4, 23, month=2)
"""La borne basse d'une fenêtre de 56 jours à :data:`ORIGIN`."""
TRAIL = frozenset({"trail_running"})
PROFILE = ParameterSet(PROFILE_PARAMETER_SPECS)


def origin_selection(**changes: Any) -> CurveSelection:
    """``trail_running``, sans dates ni durées ni plafond ni FC, valeur (a)."""
    return selection(date_from=None, date_to=None, **changes)


def _season(recording_s: float = 3600.0) -> list[Pair]:
    """Huit trails ``s0`` à ``s7``, partis les 20 à 27 mars à 08:00 UTC, sans écoulé
    d'index ; et ``apres``, parti le 2 avril."""
    pairs: list[Pair] = [
        activity_pair(
            f"s{k}", at(20 + k, 8), index_elapsed_s=None, recording_s=recording_s
        )
        for k in range(8)
    ]
    pairs.append(
        activity_pair(
            "apres", at(2, 8, month=4), index_elapsed_s=3600.0, recording_s=3600.0
        )
    )
    return pairs


def rule(
    season: CurveCorpus,
    *,
    window: OriginWindow = 56,
    origin: datetime = ORIGIN,
    chosen: CurveSelection | None = None,
    athlete: str = "x",
    support_threshold_min: float = 10.0,
) -> OriginEstimate:
    """La règle à l'origine sur ``season``, aux paramètres par défaut."""
    return estimate_at_origin(
        season,
        athlete,
        origin,
        window,
        origin_selection() if chosen is None else chosen,
        DEFAULTS,
        PROFILE,
        support_threshold_min=support_threshold_min,
    )


# --- Les fins -----------------------------------------------------------------------


def test_the_recording_end_is_the_latest_instant_of_every_channel() -> None:
    """T03 : la position jusqu'à +600 s, la FC jusqu'à +1 200 s."""
    rec = _bare_recording(
        position=PositionChannel((0.0, 600.0), (45.0, 45.1), (6.0, 6.1)),
        heart_rate=HeartRateChannel((0.0, 1200.0), (120.0, 121.0)),
        sessions=(RecordingSession("running", "trail", 0.0, None, None, None),),
    )
    assert recording_end(rec) == at(30, 8, 20)


def _sessions_end(*sessions: RecordingSession) -> datetime | None:
    return recording_end(_bare_recording(sessions=sessions))


def test_disjoint_sessions_end_at_the_last_one() -> None:
    """T04 : sessions de 1 800 s à +0 et +7 200 s : +9 000 s, jamais la somme."""
    assert _sessions_end(
        RecordingSession("running", "trail", 0.0, 1800.0, None, None),
        RecordingSession("running", "trail", 7200.0, 1800.0, None, None),
    ) == at(30, 8) + timedelta(seconds=9000)


def test_overlapping_sessions_do_not_add_up() -> None:
    assert _sessions_end(
        RecordingSession("running", "trail", 0.0, 5400.0, None, None),
        RecordingSession("running", "trail", 0.0, 5400.0, None, None),
    ) == at(30, 8) + timedelta(seconds=5400)


def test_a_late_timer_event_ends_the_recording() -> None:
    rec = _bare_recording(
        sessions=(RecordingSession("running", "trail", 0.0, None, None, None),),
        timer_events=(TimerEvent(4000.0, TimerEventType.STOP, None),),
    )
    assert recording_end(rec) == at(30, 8) + timedelta(seconds=4000)


def test_a_session_without_elapsed_counts_by_its_start() -> None:
    assert _sessions_end(
        RecordingSession("running", "trail", 0.0, None, None, None),
        RecordingSession("running", "trail", 3000.0, None, None, None),
    ) == at(30, 8) + timedelta(seconds=3000)


def test_both_ends_give_the_latest() -> None:
    """T01 : départ 31/21:40, index 600 s, montre 2 400 s."""
    end = activity_end(
        *activity_pair("a", at(31, 21, 40), index_elapsed_s=600.0, recording_s=2400.0)
    )
    assert end.method is EndMethod.BOTH
    assert end.index_end == at(31, 21, 50)
    assert end.recording_end == at(31, 22, 20)
    assert end.safe_end == at(31, 22, 20)
    assert end.disagreement_s == 1800.0


def test_the_index_end_wins_when_later() -> None:
    """T08 : départ 31/21:00, index 4 200 s, montre 3 000 s."""
    end = activity_end(
        *activity_pair("a", at(31, 21), index_elapsed_s=4200.0, recording_s=3000.0)
    )
    assert end.safe_end == at(31, 22, 10)
    assert end.disagreement_s == -1200.0


def test_without_elapsed_the_end_is_inferred() -> None:
    end = activity_end(
        *activity_pair("a", at(30, 8), index_elapsed_s=None, recording_s=3600.0)
    )
    assert end.method is EndMethod.INFERRED
    assert end.index_end is None
    assert end.safe_end == at(30, 9)
    assert end.disagreement_s is None


def test_without_recording_the_end_is_the_index_one_or_unknown() -> None:
    timed = entry(activity_ref="a", start_time=at(30, 8), elapsed_duration_s=60.0)
    end = activity_end(timed, None)
    assert (end.method, end.safe_end) == (EndMethod.INDEX_ONLY, at(30, 8, 1))
    bare = entry(activity_ref="a", start_time=at(30, 8), elapsed_duration_s=None)
    end = activity_end(bare, None)
    assert (end.method, end.safe_end) == (EndMethod.UNKNOWN, None)


def test_the_recording_start_counts_from_the_recording() -> None:
    """T02 : l'index part à 31/21:00, 3 000 s ; la montre à 31/21:20, 3 000 s."""
    end = activity_end(
        *activity_pair(
            "a",
            at(31, 21),
            index_elapsed_s=3000.0,
            recording_s=3000.0,
            recorded_start=at(31, 21, 20),
        )
    )
    assert end.index_end == at(31, 21, 50)
    assert end.recording_start == at(31, 21, 20)
    assert end.safe_end == at(31, 22, 10)


def test_a_recording_of_another_activity_is_refused() -> None:
    a = activity_pair("a", at(30, 8), index_elapsed_s=60.0, recording_s=60.0)
    b = activity_pair("b", at(30, 8), index_elapsed_s=60.0, recording_s=60.0)
    with pytest.raises(ContractError, match="n'est pas celui"):
        activity_end(a[0], b[1])


# --- Le corpus ----------------------------------------------------------------------


def _pair(ref: str) -> tuple[IndexedActivity, ActivityRecording]:
    return activity_pair(ref, at(30, 8), index_elapsed_s=60.0, recording_s=60.0)


def test_the_corpus_is_frozen() -> None:
    """Les dictionnaires sont copiés : ajouter ``b`` à ceux de l'appelant ne change pas
    le corpus contrôlé."""
    a = _pair("a")
    b = _pair("b")
    index = ActivityIndex((a[0], b[0]), (SOURCE,))
    assert a[1] is not None
    recordings = {"a": a[1]}
    hashes = {"a": SHA}
    built = CurveCorpus("x", index, "b" * 64, recordings, hashes)
    assert isinstance(built.recordings, MappingProxyType)
    assert isinstance(built.recording_sha256, MappingProxyType)
    recordings["b"] = b[1]
    hashes["b"] = SHA
    assert list(built.recordings) == ["a"]
    assert list(built.recording_sha256) == ["a"]


def test_the_corpus_refuses_an_empty_athlete() -> None:
    with pytest.raises(ContractError, match="athlete_ref"):
        corpus([_pair("a")], athlete="  ")


def test_the_corpus_refuses_a_recording_under_another_key() -> None:
    """T19 : la clé ``b`` porte l'enregistrement de ``a``."""
    a = _pair("a")
    b = _pair("b")
    with pytest.raises(ContractError, match="la clé b porte l'enregistrement de a"):
        CurveCorpus(
            "x",
            ActivityIndex((a[0], b[0]), (SOURCE,)),
            "b" * 64,
            {"b": a[1]},
            {"b": SHA},
        )


def test_the_corpus_refuses_a_recording_out_of_the_index() -> None:
    a = _pair("a")
    b = _pair("b")
    with pytest.raises(ContractError, match="b n'est pas à l'index"):
        CurveCorpus(
            "x", ActivityIndex((a[0],), (SOURCE,)), "b" * 64, {"b": b[1]}, {"b": SHA}
        )


def test_the_corpus_refuses_a_recording_the_index_does_not_promise() -> None:
    a = _pair("a")
    silent = dataclasses.replace(a[0], has_recording=False)
    with pytest.raises(ContractError, match="n'a pas d'enregistrement"):
        CurveCorpus(
            "x", ActivityIndex((silent,), (SOURCE,)), "b" * 64, {"a": a[1]}, {"a": SHA}
        )


@pytest.mark.parametrize(
    "hashes",
    [
        {},
        {"a": SHA, "b": SHA},
        {"a": "A" * 64},
        {"a": "a" * 63},
    ],
)
def test_the_corpus_wants_one_valid_hash_per_recording(hashes: dict[str, str]) -> None:
    a = _pair("a")
    with pytest.raises(ContractError, match="recording_sha256"):
        CurveCorpus(
            "x", ActivityIndex((a[0],), (SOURCE,)), "b" * 64, {"a": a[1]}, hashes
        )


def test_the_corpus_wants_a_valid_index_hash() -> None:
    a = _pair("a")
    with pytest.raises(ContractError, match="index_sha256"):
        CurveCorpus(
            "x", ActivityIndex((a[0],), (SOURCE,)), "nope", {"a": a[1]}, {"a": SHA}
        )


# --- L'origine et la fenêtre --------------------------------------------------------


def test_an_utc_instant_at_paris_midnight_is_an_origin() -> None:
    assert check_origin(ORIGIN) == ORIGIN
    winter = datetime(2024, 1, 15, tzinfo=timezone(timedelta(hours=1)))
    assert check_origin(winter) == datetime(2024, 1, 14, 23, tzinfo=UTC)
    assert check_origin(winter).tzinfo is UTC


@pytest.mark.parametrize(
    "moment",
    [datetime(2024, 4, 1), at(31, 23), ORIGIN + timedelta(microseconds=1)],
)
def test_other_instants_are_not_origins(moment: datetime) -> None:
    with pytest.raises(ContractError, match="origin"):
        check_origin(moment)


def test_a_naive_midnight_is_not_an_origin() -> None:
    with pytest.raises(ContractError, match="fuseau horaire"):
        check_origin(datetime(2024, 4, 1))


@pytest.mark.parametrize("window", [1, 28, 56, "all"])
def test_valid_windows(window: object) -> None:
    check_window(window)


@pytest.mark.parametrize("window", [True, False, 0, -1, 1.5, "ALL", "56", None])
def test_invalid_windows(window: object) -> None:
    with pytest.raises(ContractError, match="window"):
        check_window(window)


def test_the_lower_bound_is_a_paris_midnight_across_the_spring_change() -> None:
    """T06 : la fenêtre d'un jour dure 23 h le jour du passage à l'heure d'été."""
    lower = window_lower_bound(ORIGIN, 1)
    assert lower == at(30, 23)
    assert lower is not None
    assert ORIGIN - lower == timedelta(hours=23)


def test_the_lower_bound_is_a_paris_midnight_across_the_autumn_change() -> None:
    """T06 : la fenêtre d'un jour dure 25 h le jour du passage à l'heure d'hiver."""
    origin = at(27, 23, month=10)
    lower = window_lower_bound(origin, 1)
    assert lower == at(26, 22, month=10)
    assert lower is not None
    assert origin - lower == timedelta(hours=25)


def test_all_past_has_no_lower_bound() -> None:
    assert window_lower_bound(ORIGIN, "all") is None


def test_a_window_out_of_the_calendar_is_a_contract_error() -> None:
    origin = datetime(1, 1, 7, 23, 50, 39, tzinfo=UTC)
    with pytest.raises(ContractError, match="calendrier"):
        window_lower_bound(origin, 10)


# --- La sélection -------------------------------------------------------------------


def inspected(
    pairs: Sequence[Pair], window: OriginWindow = 56
) -> dict[str, Inspection]:
    """Les inspections de ``pairs`` à :data:`ORIGIN`, par référence."""
    found = select_at_origin(corpus(pairs), ORIGIN, window, TRAIL)
    return {inspection.end.activity_ref: inspection for inspection in found}


def _ending_at(ref: str, end: datetime) -> Pair:
    """Une activité dont l'index fait finir à ``end``, la montre plus tôt."""
    return activity_pair(
        ref, end - timedelta(seconds=600), index_elapsed_s=600.0, recording_s=300.0
    )


def test_an_activity_crossing_the_origin_is_excluded_entirely() -> None:
    """T01 : l'index la fait finir avant l'origine, la montre après."""
    found = inspected(
        [activity_pair("a", at(31, 21, 40), index_elapsed_s=600.0, recording_s=2400.0)]
    )
    assert found["a"].decision is TemporalDecision.AFTER_ORIGIN


def test_the_bounds_are_exact() -> None:
    """T05 : la fin à la borne basse entre, 1 µs avant non ; à l'origine non, 1 µs avant
    oui."""
    lower = at(30, 23)
    tick = timedelta(microseconds=1)
    found = inspected(
        [
            _ending_at("bas", lower),
            _ending_at("avant", lower - tick),
            _ending_at("origine", ORIGIN),
            _ending_at("juste", ORIGIN - tick),
        ],
        1,
    )
    assert found["bas"].decision is TemporalDecision.CANDIDATE
    assert found["juste"].decision is TemporalDecision.CANDIDATE
    assert found["avant"].decision is TemporalDecision.BEFORE_WINDOW
    assert found["origine"].decision is TemporalDecision.AFTER_ORIGIN


def test_a_watch_end_at_the_origin_is_after_it() -> None:
    """T05, la montre : sa fin exactement à l'origine n'est pas avant l'origine."""
    start = ORIGIN - timedelta(seconds=600)
    found = inspected(
        [
            activity_pair("o", start, index_elapsed_s=599.5, recording_s=600.0),
            activity_pair("n", start, index_elapsed_s=None, recording_s=600.0),
            activity_pair(
                "e",
                start - timedelta(microseconds=1),
                index_elapsed_s=None,
                recording_s=600.0,
            ),
        ]
    )
    for ref in ("o", "n"):
        assert found[ref].decision is TemporalDecision.AFTER_ORIGIN
        assert found[ref].end.safe_end == ORIGIN
    assert found["e"].decision is TemporalDecision.CANDIDATE


def test_an_activity_started_before_the_window_and_ended_in_it_is_a_candidate() -> None:
    """T20 : c'est la fin qui compte."""
    found = inspected(
        [
            activity_pair(
                "a",
                LOWER_56 - timedelta(hours=1),
                index_elapsed_s=7200.0,
                recording_s=7200.0,
            )
        ]
    )
    assert found["a"].decision is TemporalDecision.CANDIDATE


def test_an_index_end_in_the_window_admits_older_samples() -> None:
    """T23 : la fin basse est celle de l'index, la montre finit avant la borne."""
    found = inspected(
        [
            activity_pair(
                "a",
                LOWER_56 - timedelta(minutes=40),
                index_elapsed_s=3000.0,
                recording_s=1800.0,
            )
        ]
    )
    assert found["a"].decision is TemporalDecision.CANDIDATE


def test_a_watch_end_in_the_window_does_not_bring_an_index_end_before_it() -> None:
    """F : l'index décide seul, l'enregistrement n'est pas lu (absent du corpus)."""
    pair = activity_pair(
        "a",
        LOWER_56 - timedelta(minutes=40),
        index_elapsed_s=1800.0,
        recording_s=3000.0,
    )
    found = inspected([(pair[0], None)])
    assert found["a"].decision is TemporalDecision.BEFORE_WINDOW
    assert found["a"].recording_sha256 is None
    assert found["a"].end.method is EndMethod.INDEX_ONLY


def test_the_decisions_do_not_depend_on_extra_recordings() -> None:
    """F : les décisions sur l'index seul sont les mêmes, les enregistrements chargés en
    plus ou non."""
    early = activity_pair(
        "e",
        LOWER_56 - timedelta(hours=2, minutes=50),
        index_elapsed_s=3600.0,
        recording_s=3600.0,
    )
    late = activity_pair("l", ORIGIN, index_elapsed_s=3600.0, recording_s=3600.0)
    loaded = select_at_origin(corpus([early, late]), ORIGIN, 56, TRAIL)
    bare = select_at_origin(
        corpus([(early[0], None), (late[0], None)]), ORIGIN, 56, TRAIL
    )
    assert loaded == bare
    assert [i.decision for i in bare] == [
        TemporalDecision.BEFORE_WINDOW,
        TemporalDecision.AFTER_ORIGIN,
    ]


def test_without_index_elapsed_the_low_end_is_the_safe_end() -> None:
    found = inspected(
        [
            activity_pair(
                "i",
                LOWER_56 - timedelta(minutes=5),
                index_elapsed_s=None,
                recording_s=600.0,
            ),
            activity_pair(
                "b",
                LOWER_56 - timedelta(minutes=30),
                index_elapsed_s=None,
                recording_s=600.0,
            ),
        ]
    )
    assert found["i"].decision is TemporalDecision.CANDIDATE
    assert found["b"].decision is TemporalDecision.BEFORE_WINDOW
    assert found["i"].end.method is EndMethod.INFERRED
    assert found["b"].end.method is EndMethod.INFERRED


def test_a_recording_absent_from_the_corpus_is_refused_when_needed() -> None:
    pair = activity_pair("a", at(30, 8), index_elapsed_s=60.0, recording_s=60.0)
    with pytest.raises(ContractError, match="corpus incomplet"):
        inspected([(pair[0], None)])


def test_a_future_recording_need_not_be_loaded() -> None:
    pair = activity_pair("a", ORIGIN, index_elapsed_s=60.0, recording_s=60.0)
    found = inspected([(pair[0], None)])["a"]
    assert found.decision is TemporalDecision.AFTER_ORIGIN
    assert found.recording_sha256 is None
    assert found.end.recording_end is None


def test_only_selected_types_with_a_recording_are_inspected() -> None:
    trail = activity_pair("t", at(30, 8), index_elapsed_s=60.0, recording_s=60.0)
    road = activity_pair(
        "r", at(30, 9), index_elapsed_s=60.0, recording_s=60.0, activity_type="running"
    )
    silent = entry(
        activity_ref="n",
        start_time=at(30, 10),
        elapsed_duration_s=60.0,
        has_recording=False,
    )
    found = inspected([trail, road, (silent, None)])
    assert list(found) == ["t"]
    assert found["t"].recording_sha256 == SHA


def test_the_candidates_grow_with_the_window() -> None:
    pairs = [
        activity_pair(
            f"d{k}",
            ORIGIN - timedelta(days=k, hours=3),
            index_elapsed_s=600.0,
            recording_s=600.0,
        )
        for k in range(5)
    ]

    def candidates(window: OriginWindow) -> set[str]:
        return {
            ref
            for ref, inspection in inspected(pairs, window).items()
            if inspection.decision is TemporalDecision.CANDIDATE
        }

    assert candidates(1) == {"d0"}
    assert candidates(1) < candidates(3) < candidates("all")
    assert candidates("all") == {f"d{k}" for k in range(5)}


# --- L'historique -------------------------------------------------------------------


def test_the_history_counts_foot_activities_on_the_index() -> None:
    """T10 : selon l'index seul, enregistrement ou non, à pied ou des types choisis."""
    timed = [
        entry(activity_ref="t1", start_time=at(10, 8), elapsed_duration_s=60.0),
        entry(activity_ref="t2", start_time=at(11, 8), elapsed_duration_s=None),
        *(
            entry(
                activity_ref=f"r{k}",
                start_time=at(12 + k, 8),
                elapsed_duration_s=60.0,
                source_activity_type="running",
                has_recording=False,
            )
            for k in range(3)
        ),
        entry(
            activity_ref="v",
            start_time=at(16, 8),
            elapsed_duration_s=60.0,
            source_activity_type="mountain_biking",
        ),
        entry(
            activity_ref="futur", start_time=at(1, 8, month=4), elapsed_duration_s=60.0
        ),
        entry(
            activity_ref="futur2", start_time=at(1, 9, month=4), elapsed_duration_s=None
        ),
    ]
    index = ActivityIndex(tuple(timed), (SOURCE,))
    assert origin_history(index, ORIGIN, TRAIL) == OriginHistory(4, 1, 1, 1)


def test_an_activity_ending_at_the_origin_is_not_in_the_history() -> None:
    index = ActivityIndex(
        (
            entry(
                activity_ref="a",
                start_time=ORIGIN - timedelta(seconds=60),
                elapsed_duration_s=60.0,
            ),
        ),
        (SOURCE,),
    )
    assert origin_history(index, ORIGIN, TRAIL).foot_index_finished == 0


def test_the_cold_start_warning() -> None:
    assert cold_start_warning(OriginHistory(20, 0, 0, 0)) is None
    assert cold_start_warning(OriginHistory(19, 0, 0, 0)) == (
        "moins de 20 sorties à pied passées (19) : repère indicatif, la courbe d'un "
        "athlète ne bat celle d'une population qu'au-delà d'une vingtaine"
    )
    assert cold_start_warning(OriginHistory(12, 2, 0, 0)) == (
        "moins de 20 sorties passées confirmées dans l'historique fourni (12, et 2 "
        "sans écoulé à l'index) ; historique incomplet"
    )
    assert cold_start_warning(OriginHistory(20, 5, 0, 0)) is None


# --- La règle -----------------------------------------------------------------------


def _intervals(
    pairs: Sequence[tuple[IndexedActivity, ActivityRecording | None]],
    profile: ParameterSet = PROFILE,
    *,
    hr_lag_s: float = 60.0,
    hr_min_coverage: float = 0.8,
    max_elapsed_s: float | None = None,
) -> list[ActivityIntervals | TraceRefusal]:
    found = []
    for _, recorded in pairs:
        assert recorded is not None
        found.append(
            activity_intervals(
                recorded,
                profile,
                hr_lag_s=hr_lag_s,
                hr_min_coverage=hr_min_coverage,
                max_elapsed_s=max_elapsed_s,
            )
        )
    return found


def test_the_rule_estimates_on_its_candidates_like_0017() -> None:
    pairs = _season()
    result = rule(corpus(pairs))
    assert result.outcome is OriginOutcome.PROJECTABLE
    trails = pairs[:8]
    assert [i.end.activity_ref for i in result.candidates] == [
        p[0].activity_ref for p in trails
    ]
    assert result.estimate == estimate_curve(
        _intervals(trails),
        [p[0].activity_ref for p in trails],
        origin_selection(),
        DEFAULTS,
    )
    assert result.data_available_at == at(27, 9)
    assert result.last_retained_end == at(27, 9)
    assert result.lower_bound == at(4, 23, month=2)


def _with_heart_rate(recorded: ActivityRecording) -> ActivityRecording:
    """Une FC en rampe de 100 à 160 bpm sur la durée de la position, un échantillon par
    seconde entière, gardé si ``t % 31 < 20`` : des trous de 12 s, plus longs que les
    10 s qui relient deux échantillons."""
    assert recorded.position is not None
    duration = recorded.position.time_s[-1]
    times = tuple(float(t) for t in range(int(duration) + 1) if t % 31 < 20)
    return dataclasses.replace(
        recorded,
        heart_rate=HeartRateChannel(
            times, tuple(100.0 + 60.0 * t / duration for t in times)
        ),
    )


def test_the_rule_passes_its_parameters_to_the_intervals() -> None:
    """D1 : le profil, le décalage et la couverture de FC, le plafond de la sélection
    vont aux intervalles ; un seul revenu à son défaut change l'estimation."""
    pairs: list[Pair] = []
    for item, recorded in _season():
        assert recorded is not None
        pairs.append((item, _with_heart_rate(recorded)))
    profile = ParameterSet(
        PROFILE_PARAMETER_SPECS, {"grid_step_m": 25.0, "smoothing_window_m": 100.0}
    )
    parameters = ParameterSet(
        CURVE_ESTIMATION_PARAMETER_SPECS, {"hr_lag_s": 0.0, "hr_min_coverage": 0.5}
    )
    chosen = origin_selection(max_elapsed_s=1800.0)
    result = estimate_at_origin(
        corpus(pairs), "x", ORIGIN, 56, chosen, parameters, profile
    )
    trails = pairs[:8]
    refs = [p[0].activity_ref for p in trails]

    def expected(
        grid: ParameterSet, hr_lag_s: float, hr_min_coverage: float
    ) -> CurveEstimate:
        return estimate_curve(
            _intervals(
                trails,
                grid,
                hr_lag_s=hr_lag_s,
                hr_min_coverage=hr_min_coverage,
                max_elapsed_s=1800.0,
            ),
            refs,
            chosen,
            parameters,
        )

    assert result.estimate == expected(profile, 0.0, 0.5)
    assert result.estimate != expected(PROFILE, 0.0, 0.5)
    assert result.estimate != expected(profile, 60.0, 0.5)
    assert result.estimate != expected(profile, 0.0, 0.8)


def test_a_finished_activity_after_the_origin_changes_nothing() -> None:
    pairs = _season()
    without = rule(corpus(pairs[:8]))
    with_it = rule(corpus(pairs))
    assert with_it.estimate == without.estimate
    assert with_it.activity_fates == without.activity_fates
    assert len(with_it.inspections) == len(without.inspections) + 1


def test_no_candidate_is_an_absence_with_a_diagnostic() -> None:
    result = rule(corpus(_season()), window=1, origin=at(19, 23))
    assert result.outcome is OriginOutcome.ABSENT
    assert result.absence_reason == NO_CANDIDATE
    assert result.estimate is None
    assert result.rows == ()
    assert result.data_available_at is None
    assert result.last_retained_end is None
    assert len(result.inspections) == 9


def test_retained_activities_without_a_bin_are_an_absence() -> None:
    """T11 : le diagnostic survit sans courbe."""
    result = rule(corpus(_season()), chosen=origin_selection(min_duration_s=99999.0))
    assert result.outcome is OriginOutcome.ABSENT
    assert result.absence_reason is not None
    assert result.absence_reason.startswith("Aucune tranche estimée")
    assert [f.exclusion for f in result.activity_fates] == [ActivityExclusion.SHORT] * 8
    assert result.data_available_at == at(27, 9)
    assert result.last_retained_end is None


def test_the_available_instant_is_the_latest_candidate() -> None:
    """T09 : la disponibilité porte sur les candidates, la dernière retenue sur les
    retenues."""
    short = activity_pair("court", at(30, 8), index_elapsed_s=None, recording_s=300.0)
    result = rule(
        corpus([*_season(), short]), chosen=origin_selection(min_duration_s=600.0)
    )
    assert result.data_available_at == at(30, 8, 5)
    assert result.last_retained_end == at(27, 9)
    last = result.activity_fates[-1]
    assert (last.activity_ref, last.exclusion, last.contributes) == (
        "court",
        ActivityExclusion.SHORT,
        False,
    )


def test_a_one_sided_support_is_a_curve_not_projectable() -> None:
    pairs = [
        activity_pair(
            f"m{k}",
            at(20 + k, 8),
            index_elapsed_s=None,
            recording_s=3600.0,
            descent=False,
        )
        for k in range(6)
    ]
    result = rule(corpus(pairs))
    assert result.outcome is OriginOutcome.NOT_PROJECTABLE
    assert result.support_error is not None
    assert "négative" in result.support_error
    assert result.estimate is not None
    assert result.estimate.level is None
    assert result.rows


def test_the_rule_refuses_another_athlete() -> None:
    with pytest.raises(ContractError, match="corpus est celui de 'x'"):
        rule(corpus(_season()), athlete="y")


def test_the_rule_refuses_a_dated_selection() -> None:
    chosen = selection(date_from=date(2024, 3, 1), date_to=date(2024, 3, 31))
    with pytest.raises(ContractError, match="ne prend pas de dates"):
        rule(corpus(_season()), chosen=chosen)


def test_the_history_is_in_the_result() -> None:
    result = rule(corpus(_season()), window="all")
    assert result.history == OriginHistory(0, 8, 0, 8)
    assert result.lower_bound is None
    for inspection in result.inspections[:8]:
        assert inspection.decision is TemporalDecision.CANDIDATE
        assert inspection.end.method is EndMethod.INFERRED


def test_the_history_follows_the_index_not_the_rule() -> None:
    """T01, A1 : la règle exclut l'activité, l'historique la compte finie."""
    pair = activity_pair("a", at(31, 21, 40), index_elapsed_s=600.0, recording_s=2400.0)
    result = rule(corpus([pair]))
    assert result.inspections[0].decision is TemporalDecision.AFTER_ORIGIN
    assert result.history == OriginHistory(1, 0, 1, 0)


def test_the_verdict_and_the_support_follow_the_diagnostics_threshold() -> None:
    season = corpus(_season())
    ten = rule(season)
    five = rule(season, support_threshold_min=5.0)
    day = rule(season, support_threshold_min=1440.0)
    assert ten.estimate is not None
    assert five.estimate is not None
    assert day.estimate is not None
    assert ten.outcome is OriginOutcome.PROJECTABLE
    assert ten.estimate.support_grade_range == (-0.0375, 0.2125)
    assert five.outcome is OriginOutcome.PROJECTABLE
    assert five.estimate.support_grade_range == (-0.175, 0.2125)
    assert five.support_threshold_min == 5.0
    assert day.outcome is OriginOutcome.NOT_PROJECTABLE
    assert day.support_error is not None
    assert "La tranche centrale de pente -3.75 % n'a que" in day.support_error
    assert day.estimate.support_grade_range is None
    assert day.estimate.level is None
    assert [b.speed_ms for b in day.estimate.bins] == [
        b.speed_ms for b in ten.estimate.bins
    ]


def test_a_sub_second_disagreement_crosses_the_origin() -> None:
    """T08 : aucune tolérance, pas de seconde de grâce."""
    start = ORIGIN - timedelta(seconds=600)
    found = inspected(
        [
            activity_pair("t", start, index_elapsed_s=599.5, recording_s=600.25),
            activity_pair("e", start, index_elapsed_s=599.5, recording_s=599.75),
        ]
    )
    assert found["e"].decision is TemporalDecision.CANDIDATE
    assert found["t"].decision is TemporalDecision.AFTER_ORIGIN
    assert found["t"].end.safe_end == ORIGIN + timedelta(seconds=0.25)
    assert found["t"].end.disagreement_s == 0.75


def test_two_corpora_with_the_same_references_do_not_mix() -> None:
    """PG2 : deux athlètes aux mêmes références, chacun son corpus."""
    first = corpus(_season())
    other = corpus(_season(4800.0), athlete="y")
    before = rule(first)
    theirs = rule(other, athlete="y")
    assert rule(first).estimate == before.estimate
    assert theirs.estimate != before.estimate
    assert [i.end.activity_ref for i in theirs.candidates] == [
        f"s{k}" for k in range(8)
    ]


@pytest.mark.parametrize("threshold", [-1.0, 1441.0, math.nan])
def test_the_rule_refuses_an_invalid_threshold_without_candidate(
    threshold: float,
) -> None:
    with pytest.raises(ContractError, match="support_threshold_min"):
        rule(
            corpus(_season()),
            window=1,
            origin=at(19, 23),
            support_threshold_min=threshold,
        )


@pytest.mark.parametrize("changes", [{"date_to": None}, {"date_from": None}])
def test_a_selection_has_both_dates_or_none(changes: dict[str, Any]) -> None:
    with pytest.raises(ContractError, match="présentes ensemble ou absentes ensemble"):
        selection(**changes)


def test_the_range_selection_wants_dates() -> None:
    index = ActivityIndex((), (SOURCE,))
    with pytest.raises(ContractError, match="une plage de dates est requise"):
        select_candidates(index, origin_selection())


# --- Le compagnon -------------------------------------------------------------------


LINE_KEYS = [
    "activity_ref",
    "decision",
    "method",
    "index_start",
    "index_end",
    "recording_start",
    "recording_end",
    "safe_end",
    "recording_sha256",
    "fate",
    "contributes",
]
"""Les onze clés d'une ligne, recopiées du § 6.5 du brief."""


def test_the_retained_start_days_are_local_days() -> None:
    """Le départ de ``a``, le 20 à 00:30 à son heure locale, est le 19 en UTC."""
    local = datetime(2024, 3, 20, 0, 30, tzinfo=timezone(timedelta(hours=2)))
    first = activity_pair("a", local, index_elapsed_s=None, recording_s=3600.0)
    season = corpus([first, *_season()[1:8]])
    result = rule(season)
    assert retained_start_days(result, season) == (date(2024, 3, 20), date(2024, 3, 27))


def _lines(document: dict[str, object]) -> list[dict[str, object]]:
    lines = document["activities"]
    assert isinstance(lines, list)
    return lines


def test_the_origin_document() -> None:
    season = corpus(_season())
    document = origin_document(rule(season), season)
    assert list(document) == [
        "origin",
        "window",
        "lower_bound",
        "outcome",
        "index_sha256",
        "data_available_at",
        "last_retained_end",
        "history",
        "activities",
    ]
    assert document["origin"] == "2024-03-31T22:00:00+00:00"
    assert document["window"] == 56
    assert document["lower_bound"] == "2024-02-04T23:00:00+00:00"
    assert document["outcome"] == "courbe projetable"
    assert document["index_sha256"] == "b" * 64
    assert document["data_available_at"] == "2024-03-27T09:00:00+00:00"
    assert document["last_retained_end"] == "2024-03-27T09:00:00+00:00"
    assert document["history"] == {
        "foot_index_finished": 0,
        "foot_without_index_elapsed": 8,
        "selected_index_finished": 0,
        "selected_without_index_elapsed": 8,
    }
    lines = _lines(document)
    assert [line["activity_ref"] for line in lines] == [
        *(f"s{k}" for k in range(8)),
        "apres",
    ]
    assert list(lines[0]) == LINE_KEYS
    assert lines[0] == {
        "activity_ref": "s0",
        "decision": "candidate",
        "method": "fin inférée",
        "index_start": "2024-03-20T08:00:00+00:00",
        "index_end": None,
        "recording_start": "2024-03-20T08:00:00+00:00",
        "recording_end": "2024-03-20T09:00:00+00:00",
        "safe_end": "2024-03-20T09:00:00+00:00",
        "recording_sha256": SHA,
        "fate": "retenue",
        "contributes": True,
    }
    assert lines[-1] == {
        "activity_ref": "apres",
        "decision": "finie à l'origine ou après",
        "method": "index seul",
        "index_start": "2024-04-02T08:00:00+00:00",
        "index_end": "2024-04-02T09:00:00+00:00",
        "recording_start": None,
        "recording_end": None,
        "safe_end": None,
        "recording_sha256": None,
        "fate": None,
        "contributes": False,
    }


def test_a_read_recording_is_written_for_a_non_candidate() -> None:
    """Choix 33 : la méthode décide, pas la décision. ``v`` (sans écoulé, finie avant la
    borne basse) et ``a`` (T01) ont lu leur enregistrement : leur ligne écrit sa
    fin sûre et son empreinte."""
    crossing = activity_pair(
        "a", at(31, 21, 40), index_elapsed_s=600.0, recording_s=2400.0
    )
    old = activity_pair(
        "v", at(1, 8, month=2), index_elapsed_s=None, recording_s=3600.0
    )
    season = corpus([old, *_season(), crossing])
    lines = _lines(origin_document(rule(season), season))
    assert [line["activity_ref"] for line in lines] == [
        "v",
        *(f"s{k}" for k in range(8)),
        "a",
        "apres",
    ]
    assert lines[0] == {
        "activity_ref": "v",
        "decision": "finie avant la fenêtre",
        "method": "fin inférée",
        "index_start": "2024-02-01T08:00:00+00:00",
        "index_end": None,
        "recording_start": "2024-02-01T08:00:00+00:00",
        "recording_end": "2024-02-01T09:00:00+00:00",
        "safe_end": "2024-02-01T09:00:00+00:00",
        "recording_sha256": SHA,
        "fate": None,
        "contributes": False,
    }
    assert lines[-2] == {
        "activity_ref": "a",
        "decision": "finie à l'origine ou après",
        "method": "index et enregistrement",
        "index_start": "2024-03-31T21:40:00+00:00",
        "index_end": "2024-03-31T21:50:00+00:00",
        "recording_start": "2024-03-31T21:40:00+00:00",
        "recording_end": "2024-03-31T22:20:00+00:00",
        "safe_end": "2024-03-31T22:20:00+00:00",
        "recording_sha256": SHA,
        "fate": None,
        "contributes": False,
    }
