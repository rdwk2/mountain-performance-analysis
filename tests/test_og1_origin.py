"""La règle à l'origine (OG-1, ``docs/decisions/0020``) : les fins d'une activité, le
corpus, la sélection à l'origine, l'historique, l'estimation et ses trois issues, le
compagnon. Jours, heures et activités inventés (règle 1) ; les cas T01 à T23 sont ceux
de la passe experte."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

import pytest

from fixtures.montees import FLAT, climb_at
from fixtures.montees import recording as montee
from mountain_perf.estimation.origin import (
    CurveCorpus,
    EndMethod,
    activity_end,
    recording_end,
)
from mountain_perf.schemas import (
    ActivityIndex,
    ActivityRecording,
    HeartRateChannel,
    IndexedActivity,
    PositionChannel,
    RecordingSession,
    TimerEvent,
    TimerEventType,
)
from mountain_perf.validation import ContractError
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
