"""La correspondance d'une sortie et des activités déclarées (OG-2, § 6.3 du brief
OG-2) : ``Outing.activity_refs``, le manifeste, ``check_correspondence``.

Cas de la table du brief (A7 de l'expert, la table de D-OG2-6) : sauf mention, tolérance
60 s, une origine ``o`` = 2026-06-13 00:00 à Paris (= 2026-06-12 22:00 UTC) ; heures de
Paris ; traces au pas de 10 s. Les messages en dur viennent de l'oracle de la
conception. Les instants sont à fuseau : les tests ne dépendent pas du fuseau local."""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from fixtures.traces import TRACE_SOURCE
from mountain_perf.backtest.correspondence import check_correspondence
from mountain_perf.backtest.manifest import ManifestError, load_manifest
from mountain_perf.estimation.origin import ActivityEnd, EndMethod
from mountain_perf.schemas import Outing, RecordedTrace, Sport
from mountain_perf.validation import ContractError

PARIS = ZoneInfo("Europe/Paris")
ORIGIN = datetime(2026, 6, 13, tzinfo=PARIS)


def paris(day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 6, day, hour, minute, second, tzinfo=PARIS)


def trace(
    start: datetime, end: datetime, gaps: tuple[tuple[datetime, datetime], ...] = ()
) -> RecordedTrace:
    """Une trace au pas de 10 s de ``start`` à ``end``, sans point dans les trous."""
    total = int((end - start).total_seconds())
    times = [
        float(t)
        for t in range(0, total + 1, 10)
        if not any(a <= start + timedelta(seconds=t) <= b for a, b in gaps)
    ]
    n = len(times)
    return RecordedTrace(
        start_time=start,
        time_s=tuple(times),
        latitude_deg=tuple(45.0 + i * 1e-5 for i in range(n)),
        longitude_deg=(6.0,) * n,
        elevation_m=(1000.0,) * n,
        sources=(TRACE_SOURCE,),
        dropped_same_instant_count=0,
    )


def outing(
    start: datetime, end: datetime, refs: tuple[str, ...], identifier: str = "s1"
) -> Outing:
    return Outing(
        outing_id=identifier,
        athlete_ref="x",
        sport=Sport.FOOT,
        start_time=start,
        end_time=end,
        activity_refs=refs,
    )


def activity(ref: str, start: datetime, end: datetime | None) -> ActivityEnd:
    """Une activité de l'index et de son enregistrement, alignés ; ``end`` ``None`` :
    ni écoulé à l'index, ni enregistrement (fin inconnue)."""
    if end is None:
        return ActivityEnd(ref, start, None, None, None, None, EndMethod.UNKNOWN)
    return ActivityEnd(ref, start, end, start, end, end, EndMethod.BOTH)


def check(
    sortie: Outing,
    recorded: RecordedTrace | None,
    activities: list[ActivityEnd],
    origins: tuple[datetime, ...] = (ORIGIN,),
    tolerance_s: float = 60.0,
) -> None:
    check_correspondence(sortie, recorded, activities, origins, tolerance_s)


def refusal(*args: object, **kwargs: object) -> str:
    with pytest.raises(ContractError) as error:
        check(*args, **kwargs)  # type: ignore[arg-type]
    return str(error.value)


# --- La nuit (A7) ----------------------------------------------------------------


NIGHT_START, NIGHT_END = paris(12, 23, 35), paris(12, 23, 49, 30)


def test_the_night_is_refused_by_control_3() -> None:
    message = refusal(
        outing(NIGHT_START, NIGHT_END, ("A",)),
        trace(NIGHT_START, NIGHT_END),
        [activity("A", NIGHT_START, paris(13, 0, 5))],
    )
    assert message == (
        "sortie s1 : à l'origine 2026-06-12T22:00:00+00:00, la fin du manifeste "
        "(2026-06-12T21:49:30+00:00) et la fin sûre de l'activité A "
        "(2026-06-12T22:05:00+00:00) ne sont pas du même côté."
    )


def test_the_night_ended_before_the_origin_is_admitted() -> None:
    check(
        outing(NIGHT_START, NIGHT_END, ("A",)),
        trace(NIGHT_START, NIGHT_END),
        [activity("A", NIGHT_START, paris(12, 23, 49, 40))],
    )


def test_an_origin_of_no_performance_refuses_nothing() -> None:
    check(
        outing(NIGHT_START, NIGHT_END, ("A",)),
        trace(NIGHT_START, NIGHT_END),
        [activity("A", NIGHT_START, paris(13, 0, 5))],
        origins=(),
    )


def test_a_walk_aligned_is_admitted() -> None:
    """Le type de l'activité n'entre pas dans les contrôles."""
    start, end = paris(5, 8, 0), paris(5, 9, 0)
    check(outing(start, end, ("M",)), trace(start, end), [activity("M", start, end)])


# --- La montre relancée, les trois fichiers ------------------------------------------


DAY_START, DAY_END = paris(5, 8, 0), paris(5, 10, 0)
RELAUNCH = ((paris(5, 8, 50, 1), paris(5, 8, 52, 59)),)


def test_the_relaunched_watch_with_both_files_is_admitted() -> None:
    check(
        outing(DAY_START, DAY_END, ("A", "B")),
        trace(DAY_START, DAY_END, RELAUNCH),
        [
            activity("A", DAY_START, paris(5, 8, 50)),
            activity("B", paris(5, 8, 53), paris(5, 10, 0, 5)),
        ],
    )


def test_the_relaunched_watch_with_the_first_file_only_is_refused() -> None:
    message = refusal(
        outing(DAY_START, DAY_END, ("A",)),
        trace(DAY_START, DAY_END, RELAUNCH),
        [activity("A", DAY_START, paris(5, 8, 50))],
    )
    assert message == (
        "sortie s1 : à 2026-06-05T06:53:00+00:00, la trace n'est dans aucune "
        "activité déclarée, à 60 s près."
    )


def test_three_files_with_the_middle_one_forgotten_are_refused() -> None:
    """08:41:00 à Paris est encore couvert : la borne est incluse."""
    message = refusal(
        outing(DAY_START, DAY_END, ("A", "C")),
        trace(DAY_START, DAY_END),
        [
            activity("A", DAY_START, paris(5, 8, 40)),
            activity("C", paris(5, 9, 21), paris(5, 10, 0, 5)),
        ],
    )
    assert message == (
        "sortie s1 : à 2026-06-05T06:41:10+00:00, la trace n'est dans aucune "
        "activité déclarée, à 60 s près."
    )


def test_the_three_files_together_are_admitted() -> None:
    check(
        outing(DAY_START, DAY_END, ("A", "B", "C")),
        trace(DAY_START, DAY_END),
        [
            activity("A", DAY_START, paris(5, 8, 40)),
            activity("B", paris(5, 8, 41), paris(5, 9, 20)),
            activity("C", paris(5, 9, 21), paris(5, 10, 0, 5)),
        ],
    )


def test_the_tolerance_widens_both_sides() -> None:
    """A finit à 08:50, B part à 08:52 : de 08:50:10 à 08:51:00, la fin élargie de A
    couvre ; de 08:51:10 à 08:51:50, le départ élargi de B. Sans l'un des deux côtés,
    un point reste découvert."""
    activities = [
        activity("A", DAY_START, paris(5, 8, 50)),
        activity("B", paris(5, 8, 52), DAY_END),
    ]
    sortie = outing(DAY_START, DAY_END, ("A", "B"))
    check(sortie, trace(DAY_START, DAY_END), activities)
    message = refusal(sortie, trace(DAY_START, DAY_END), activities, tolerance_s=30.0)
    assert message == (
        "sortie s1 : à 2026-06-05T06:50:40+00:00, la trace n'est dans aucune "
        "activité déclarée, à 30 s près."
    )


# --- Le recouvrement et la fin ------------------------------------------------------


def test_a_wrong_reference_is_refused_by_control_1() -> None:
    message = refusal(
        outing(DAY_START, DAY_END, ("B",)),
        trace(DAY_START, DAY_END),
        [activity("B", paris(4, 8, 0), paris(4, 10, 0))],
    )
    assert message == (
        "sortie s1 : l'activité B (2026-06-04T06:00:00+00:00 – "
        "2026-06-04T08:00:00+00:00) ne recouvre pas la sortie "
        "(2026-06-05T06:00:00+00:00 – 2026-06-05T08:00:00+00:00)."
    )


def test_an_unknown_end_is_refused_by_control_1() -> None:
    message = refusal(
        outing(DAY_START, DAY_END, ("C",)),
        trace(DAY_START, DAY_END),
        [activity("C", DAY_START, None)],
    )
    assert message == (
        "sortie s1 : l'activité C n'a pas de fin connue ; sa correspondance ne se "
        "vérifie pas."
    )


def test_an_untraced_outing_is_checked_on_its_two_instants() -> None:
    check(
        outing(DAY_START, DAY_END, ("A",)),
        None,
        [activity("A", paris(5, 7, 59, 30), paris(5, 10, 0, 20))],
    )


def test_an_outing_across_the_origin_is_admitted() -> None:
    """La sortie part avant ``o`` et finit après : sa fin et la fin sûre de son
    activité sont du même côté (après)."""
    start, end = paris(12, 23, 50), paris(13, 0, 10)
    check(
        outing(start, end, ("A",)),
        trace(start, end),
        [activity("A", start, paris(13, 0, 10, 5))],
    )


def test_the_latest_safe_end_is_named() -> None:
    message = refusal(
        outing(NIGHT_START, NIGHT_END, ("A", "B")),
        trace(NIGHT_START, NIGHT_END),
        [
            activity("A", NIGHT_START, paris(12, 23, 40)),
            activity("B", paris(12, 23, 40), paris(13, 0, 1)),
        ],
    )
    assert "la fin sûre de l'activité B (2026-06-12T22:01:00+00:00)" in message


def test_the_arguments_are_checked_first() -> None:
    sortie = outing(DAY_START, DAY_END, ("A",))
    assert refusal(sortie, None, [], tolerance_s=-1.0) == (
        "tolerance_s : un nombre fini >= 0 attendu, reçu -1.0."
    )
    assert refusal(sortie, None, [], tolerance_s=float("nan")) == (
        "tolerance_s : un nombre fini >= 0 attendu, reçu nan."
    )
    assert refusal(sortie, None, [activity("B", DAY_START, DAY_END)]) == (
        "activities : celles de la sortie s1 attendues."
    )


# --- Le contrat et le manifeste ---------------------------------------------------


def test_outing_activity_refs_are_distinct_texts() -> None:
    sortie = outing(DAY_START, DAY_END, ())
    assert sortie.activity_refs == ()
    with pytest.raises(ContractError, match=r"activity_refs : A en double\."):
        dataclasses.replace(sortie, activity_refs=("A", "A"))
    with pytest.raises(ContractError):
        dataclasses.replace(sortie, activity_refs=("",))


def _manifest(tmp_path: Path, outings: list[dict[str, object]]) -> Path:
    path = tmp_path / "manifeste.json"
    document = {
        "schema_version": 1,
        "athlete_ref": "x",
        "domain_start_date": "2026-06-01",
        "outings": outings,
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _untraced(identifier: str, refs: object, athlete: str = "x") -> dict[str, object]:
    entry: dict[str, object] = {
        "id": identifier,
        "sport": "foot",
        "athlete_ref": athlete,
        "start": "2026-06-05T08:00:00+02:00",
        "end": "2026-06-05T10:00:00+02:00",
    }
    if refs is not None:
        entry["activity_refs"] = refs
    return entry


def test_the_manifest_reads_activity_refs(tmp_path: Path) -> None:
    read = load_manifest(
        _manifest(tmp_path, [_untraced("s1", ["A", "B"]), _untraced("s2", None)])
    )
    assert [o.activity_refs for o in read.outings] == [("A", "B"), ()]


@pytest.mark.parametrize(
    ("outings", "message"),
    [
        (
            [_untraced("s1", ["A", "A"])],
            "sortie s1, clé activity_refs : activity_refs : A déclarée deux fois.",
        ),
        (
            [_untraced("s1", ["A"]), _untraced("s2", ["B", "A"])],
            "sortie s2, clé activity_refs : activity_refs : A est déjà déclarée par "
            "la sortie s1. Une activité n'appartient qu'à une sortie.",
        ),
        (
            [_untraced("s1", "A")],
            "sortie s1, clé activity_refs : liste JSON attendue.",
        ),
        (
            [_untraced("s1", [""])],
            "sortie s1, clé activity_refs : texte non vide attendu, reçu ''.",
        ),
    ],
)
def test_the_manifest_refuses_bad_activity_refs(
    tmp_path: Path, outings: list[dict[str, object]], message: str
) -> None:
    with pytest.raises(ManifestError) as error:
        load_manifest(_manifest(tmp_path, outings))
    assert str(error.value) == message


def test_an_outing_of_another_athlete_declares_nothing(tmp_path: Path) -> None:
    read = load_manifest(
        _manifest(
            tmp_path,
            [_untraced("s1", ["A"], athlete="y"), _untraced("s2", ["A"])],
        )
    )
    assert [o.outing_id for o in read.outings] == ["s2"]
    assert read.outings[0].activity_refs == ("A",)
