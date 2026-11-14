"""Les sources de courbe de ``runs.py`` (OG-UI, § 6.2 du brief) : l'origine d'une
course, les corpus, la courbe en mémoire, la courbe à l'origine et celle d'une plage,
le jour et la part hors support d'une sortie.

Le monde ``interim/`` de ``tests/fixtures/processed.py``, recalé par ``realign`` de
``tests/test_og1_cli_at.py`` : ``a1`` à pied le 2024-03-09, retenue ; ``a2`` ski de
randonnée le 2024-03-10 ; ``a3`` à pied sans altitude le 2024-03-11, « sans trace » ;
``a4`` golf sans enregistrement. L'oracle : ``mperf curve``, lancée par ``main`` avec
l'horloge et l'état git fixés, sur la même origine et la même fenêtre, ou la même
plage."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from fixtures.matching import MATCH_REFERENCE_GPX, MATCH_TRACE_GPX
from fixtures.processed import COMMIT, write_interim
from mountain_perf import cli, gitstate
from mountain_perf.backtest.rolling import rolling_selection
from mountain_perf.cli import main
from mountain_perf.config import data_dir
from mountain_perf.estimation.intervals import activity_intervals
from mountain_perf.estimation.origin import OriginWindow, intervals_cache
from mountain_perf.gitstate import GitState
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS, build_profile, read_gpx
from mountain_perf.model import PROJECTION_PARAMETER_SPECS
from mountain_perf.model.curve_io import CurveError, freeze_companion
from mountain_perf.model.engine import portion_out_of_support_time_share
from mountain_perf.reports import range_curve_lines
from mountain_perf.runs import (
    FOLDER_ATHLETE,
    RANGE_NO_CANDIDATE,
    CourseOrigin,
    CurveBytes,
    check_outing,
    course_origin,
    curve_selection,
    index_digest,
    load_athlete_corpus,
    load_range_corpus,
    match_outing,
    origin_curve,
    outing_day,
    outing_support_share,
    project_route,
    range_curve,
)
from mountain_perf.schemas import ParameterSet
from mountain_perf.validation import ContractError
from test_og1_cli_at import activities, damage, realign
from test_ogui_cli import write_not_projectable

NOW = datetime(2024, 4, 1, 12, tzinfo=UTC)
TODAY = date(2024, 4, 1)
FIXTURES = Path(__file__).parent / "fixtures"
ROUTE = FIXTURES / "mini_11.gpx"
REFERENCE = FIXTURES / MATCH_REFERENCE_GPX
TRACE = FIXTURES / MATCH_TRACE_GPX
TRAIL = frozenset({"trail_running"})
INSTANTS = frozenset({"retrieved_at", "generated_at"})


@pytest.fixture(autouse=True)
def fixed_world(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un clone propre au commit des fixtures, l'horloge de la commande à
    :data:`NOW` (comme ``tests/test_og1_cli_at.py``)."""
    monkeypatch.setattr(
        gitstate, "git_state", lambda directory: GitState(COMMIT, False)
    )
    monkeypatch.setattr(cli, "_now", lambda: NOW)


def write_aligned() -> Path:
    folder = data_dir()
    write_interim(folder)
    realign(folder)
    return folder


def curve_command(
    capsys: pytest.CaptureFixture[str], name: str, *options: str
) -> tuple[int, str, str]:
    code = main(["curve", name, *options])
    out, err = capsys.readouterr()
    return code, out, err


def written(name: str) -> tuple[bytes, bytes]:
    reference = data_dir() / "reference"
    return (
        (reference / f"{name}.csv").read_bytes(),
        (reference / f"{name}.meta.json").read_bytes(),
    )


def _origin_0325(window: OriginWindow = 56) -> Any:
    folder = write_aligned()
    corpus = load_athlete_corpus(folder, TRAIL)
    return origin_curve(
        corpus, course_origin(date(2024, 3, 25), TODAY), window, generated_at=NOW
    )


# --- L'origine d'une course -----------------------------------------------------------


@pytest.mark.parametrize(
    ("today", "day", "effective", "bounded", "origin_day", "origin"),
    [
        (
            date(2026, 11, 12),
            date(2026, 11, 19),
            date(2026, 11, 19),
            False,
            date(2026, 11, 12),
            datetime(2026, 11, 11, 23, tzinfo=UTC),
        ),
        (
            date(2026, 11, 12),
            date(2026, 11, 20),
            date(2026, 11, 19),
            True,
            date(2026, 11, 12),
            datetime(2026, 11, 11, 23, tzinfo=UTC),
        ),
        (
            date(2026, 11, 12),
            date(2026, 12, 6),
            date(2026, 11, 19),
            True,
            date(2026, 11, 12),
            datetime(2026, 11, 11, 23, tzinfo=UTC),
        ),
        (
            date(2026, 11, 12),
            date(2026, 11, 12),
            date(2026, 11, 12),
            False,
            date(2026, 11, 5),
            datetime(2026, 11, 4, 23, tzinfo=UTC),
        ),
        (
            date(2026, 11, 12),
            date(2026, 6, 1),
            date(2026, 6, 1),
            False,
            date(2026, 5, 25),
            datetime(2026, 5, 24, 22, tzinfo=UTC),
        ),
        (
            date(2026, 3, 30),
            date(2026, 4, 6),
            date(2026, 4, 6),
            False,
            date(2026, 3, 30),
            datetime(2026, 3, 29, 22, tzinfo=UTC),
        ),
        (
            date(2026, 3, 25),
            date(2026, 4, 5),
            date(2026, 4, 1),
            True,
            date(2026, 3, 25),
            datetime(2026, 3, 24, 23, tzinfo=UTC),
        ),
    ],
    ids=[
        "T+7",
        "T+8-bornee",
        "loin-bornee",
        "aujourd-hui",
        "passe-ete",
        "changement-d-heure",
        "bornee-autour-du-changement",
    ],
)
def test_course_origin_by_hand(
    today: date,
    day: date,
    effective: date,
    bounded: bool,
    origin_day: date,
    origin: datetime,
) -> None:
    """La table du § 6.2 (b), calculée à la main."""
    assert course_origin(day, today) == CourseOrigin(
        day, effective, origin_day, origin, bounded
    )


def test_course_origin_reads_every_field() -> None:
    found = course_origin(date(2026, 12, 6), date(2026, 11, 12))
    assert found.day == date(2026, 12, 6)
    assert found.effective_day == date(2026, 11, 19)
    assert found.origin_day == date(2026, 11, 12)
    assert found.origin == datetime(2026, 11, 11, 23, tzinfo=UTC)
    assert found.origin.utcoffset() is not None
    assert found.bounded is True


# --- Les corpus -----------------------------------------------------------------------


def test_the_athlete_corpus() -> None:
    folder = write_aligned()
    corpus = load_athlete_corpus(folder, TRAIL)
    assert sorted(corpus.recordings) == ["a1", "a3"]
    assert corpus.athlete_ref == FOLDER_ATHLETE == "athlète du dossier"
    assert corpus.index_sha256 == index_digest(folder)
    assert [e.activity_ref for e in corpus.index.entries] == ["a1", "a2", "a3", "a4"]


def test_a_damaged_recording_stops_the_athlete_corpus() -> None:
    folder = write_aligned()
    damage(activities("recordings", "a3.json"))
    with pytest.raises(CurveError) as raised:
        load_athlete_corpus(folder, TRAIL)
    assert str(raised.value).startswith("activité a3 : ")
    assert str(raised.value).endswith(" ; relancer `mperf ingest`.")


def test_a_damaged_index_stops_the_digest() -> None:
    folder = write_aligned()
    damage(activities("index.json"))
    with pytest.raises(CurveError) as raised:
        index_digest(folder)
    assert str(raised.value).startswith("index d'interim/ : ")


def test_the_range_corpus() -> None:
    folder = write_aligned()
    corpus = load_range_corpus(
        folder, "x", curve_selection(date(2024, 3, 1), date(2024, 3, 31))
    )
    assert sorted(corpus.recordings) == ["a1", "a3"]
    assert corpus.athlete_ref == "x"


# --- Un athlète vide (C12) ------------------------------------------------------------


def test_load_range_corpus_refuses_no_candidate_before_the_athlete() -> None:
    folder = write_aligned()
    with pytest.raises(CurveError) as raised:
        load_range_corpus(
            folder, "", curve_selection(date(2025, 1, 1), date(2025, 12, 31))
        )
    assert str(raised.value) == RANGE_NO_CANDIDATE


def test_curve_range_with_an_empty_athlete_without_candidate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_aligned()
    code, out, err = curve_command(
        capsys, "s", "--from", "2025-01-01", "--to", "2025-12-31", "--athlete", ""
    )
    assert code == 1
    assert out == ""
    assert err == (
        "Erreur : aucune activité candidate : aucun enregistrement des types "
        "demandés dans la fenêtre.\n"
    )


def test_curve_range_with_an_empty_athlete_and_a_candidate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_aligned()
    code, out, err = curve_command(
        capsys, "s", "--from", "2024-03-11", "--to", "2024-03-11", "--athlete", ""
    )
    assert code == 1
    assert out == ""
    assert err == "Erreur : athlete_ref ne doit pas être vide.\n"


# --- L'oracle général, à l'origine ----------------------------------------------------


def test_origin_curve_is_the_curve_of_mperf_curve_at(
    capsys: pytest.CaptureFixture[str],
) -> None:
    found = _origin_0325()
    assert found.course == course_origin(date(2024, 3, 25), TODAY)
    assert found.window == 56
    assert found.result.estimate is not None
    assert found.result.athlete_ref == FOLDER_ATHLETE
    curve = found.curve
    assert curve is not None
    assert curve.name == "origine-2024-03-25-w56.csv"
    assert curve.generated_at == NOW
    code, _, _ = curve_command(
        capsys,
        "origine-2024-03-25-w56",
        "--at",
        "2024-03-25",
        "--athlete",
        FOLDER_ATHLETE,
    )
    assert code == 0
    csv, companion = written("origine-2024-03-25-w56")
    assert curve.csv == csv
    assert curve.companion == freeze_companion(companion)


def test_origin_curve_with_seven_days_is_an_absence() -> None:
    found = _origin_0325(7)
    assert found.curve is None
    assert found.result.estimate is None
    assert found.result.absence_reason is not None
    assert found.window == 7


def test_origin_curve_all_the_past_is_named_all() -> None:
    found = _origin_0325("all")
    assert found.curve is not None
    assert found.curve.name == "origine-2024-03-25-all.csv"


# --- L'oracle général, sur une plage --------------------------------------------------


def test_range_curve_is_the_curve_of_mperf_curve_from_to(
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = write_aligned()
    corpus = load_athlete_corpus(folder, TRAIL)
    found = range_curve(corpus, date(2024, 3, 1), date(2024, 3, 31), generated_at=NOW)
    assert (found.date_from, found.date_to) == (date(2024, 3, 1), date(2024, 3, 31))
    assert found.estimate is not None
    assert found.estimate.activity_refs == ("a1",)
    assert found.absence_reason is None
    assert found.support_error is None
    curve = found.curve
    assert curve is not None
    assert curve.name == "plage-2024-03-01-2024-03-31.csv"
    code, _, _ = curve_command(
        capsys,
        "plage-2024-03-01-2024-03-31",
        "--from",
        "2024-03-01",
        "--to",
        "2024-03-31",
        "--athlete",
        FOLDER_ATHLETE,
    )
    assert code == 0
    csv, companion = written("plage-2024-03-01-2024-03-31")
    assert curve.csv == csv
    assert curve.companion == freeze_companion(companion)


def test_range_curve_without_candidate_is_an_absence() -> None:
    folder = write_aligned()
    corpus = load_athlete_corpus(folder, TRAIL)
    found = range_curve(corpus, date(2024, 1, 1), date(2024, 1, 31), generated_at=NOW)
    assert found.curve is None
    assert found.estimate is None
    assert found.support_error is None
    assert found.absence_reason == RANGE_NO_CANDIDATE


def test_range_without_bin_keeps_its_reason(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Le 2024-03-11, la seule ``a3``, sans trace : une absence qui n'est pas « aucune
    candidate » ; sa raison est celle que ``mperf curve --from --to`` imprime
    (§ 6.2 (f))."""
    folder = write_aligned()
    found = range_curve(
        load_athlete_corpus(folder, TRAIL),
        date(2024, 3, 11),
        date(2024, 3, 11),
        generated_at=NOW,
    )
    assert found.curve is None
    assert found.absence_reason is not None
    code, _, err = curve_command(
        capsys,
        "s",
        "--from",
        "2024-03-11",
        "--to",
        "2024-03-11",
        "--athlete",
        FOLDER_ATHLETE,
    )
    assert code == 1
    assert err == f"Erreur : {found.absence_reason}\n"


def test_range_curve_not_projectable_says_so(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Le monde non projetable de ``tests/test_ogui_cli.py`` (``a2`` seule retenue, la
    tranche centrale sous 10 min), sur la plage de mars : l'erreur de support est
    remplie, et la dernière ligne est celle que ``mperf curve --from --to`` imprime
    (§ 6.2 (f), § 8.2)."""
    write_not_projectable()
    found = range_curve(
        load_athlete_corpus(data_dir(), TRAIL),
        date(2024, 3, 1),
        date(2024, 3, 31),
        generated_at=NOW,
    )
    assert found.curve is not None
    assert found.support_error is not None
    lines = range_curve_lines(found)
    assert lines[-1] == f"Courbe non projetable par read_curve : {found.support_error}"
    code, out, _ = curve_command(
        capsys,
        "plage-2024-03-01-2024-03-31",
        "--from",
        "2024-03-01",
        "--to",
        "2024-03-31",
        "--athlete",
        FOLDER_ATHLETE,
    )
    assert code == 0
    printed = [
        line
        for line in out.splitlines()
        if line.startswith("Courbe non projetable par read_curve : ")
    ]
    assert printed == [lines[-1]]


def test_the_range_refuses_intervals_of_another_activity() -> None:
    """``range_curve``, par ``range_estimate``, passe par ``candidate_intervals``
    (§ 6.1 (b)) : a1 reçoit le refus d'a3 (sans trace), puis a3 les intervalles d'a1,
    refusés."""
    folder = write_aligned()
    corpus = load_athlete_corpus(folder, TRAIL)

    def provider(recording: Any, *args: Any, **kwargs: Any) -> Any:
        other = "a1" if recording.activity_ref == "a3" else "a3"
        return activity_intervals(corpus.recordings[other], *args, **kwargs)

    with pytest.raises(ContractError) as raised:
        range_curve(
            corpus,
            date(2024, 3, 1),
            date(2024, 3, 31),
            generated_at=NOW,
            intervals_of=provider,
        )
    assert str(raised.value) == "intervals_of : les intervalles de a1 rendus pour a3."


def test_the_range_goes_through_the_given_intervals_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deux plages qui partagent leurs candidates, sur le cache qu'on leur donne
    (§ 6.2 (f), § 6.4 (a)) : chaque activité calculée une fois."""
    calls: list[str] = []

    def spy(recording: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(recording.activity_ref)
        return activity_intervals(recording, *args, **kwargs)

    monkeypatch.setattr("mountain_perf.estimation.origin.activity_intervals", spy)
    corpus = load_athlete_corpus(write_aligned(), TRAIL)
    cache = intervals_cache(corpus)
    for date_from, date_to in (
        (date(2024, 3, 1), date(2024, 3, 31)),
        (date(2024, 3, 9), date(2024, 3, 11)),
    ):
        found = range_curve(
            corpus, date_from, date_to, generated_at=NOW, intervals_of=cache
        )
        assert found.estimate is not None
    assert sorted(calls) == ["a1", "a3"]


# --- La lecture -----------------------------------------------------------------------


def _memory_and_file(capsys: pytest.CaptureFixture[str]) -> tuple[CurveBytes, Path]:
    found = _origin_0325()
    assert found.curve is not None
    assert (
        curve_command(
            capsys,
            "origine-2024-03-25-w56",
            "--at",
            "2024-03-25",
            "--athlete",
            FOLDER_ATHLETE,
        )[0]
        == 0
    )
    return found.curve, data_dir() / "reference" / "origine-2024-03-25-w56.csv"


def test_the_memory_curve_projects_like_the_file(
    capsys: pytest.CaptureFixture[str],
) -> None:
    memory, path = _memory_and_file(capsys)
    kept = {}
    for threshold in (10.0, 1.0):
        values = {"curve_min_support_min": threshold}
        from_memory = project_route(ROUTE, memory, {}, values)
        from_file = project_route(ROUTE, path, {}, values)
        assert from_memory.curve.curve_ref == from_file.curve.curve_ref
        assert [p.arrival_s for p in from_memory.projection.passages] == [
            p.arrival_s for p in from_file.projection.passages
        ]
        assert from_memory.curve.bin_count_kept == from_file.curve.bin_count_kept
        kept[threshold] = from_memory.curve.bin_count_kept
    assert kept[1.0] > kept[10.0]


def _plain(value: object) -> object:
    """Un objet des contrats en structure simple, sans les instants pris à l'horloge
    (``retrieved_at``, ``generated_at``)."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return (
            type(value).__name__,
            tuple(
                (field.name, _plain(getattr(value, field.name)))
                for field in dataclasses.fields(value)
                if field.name not in INSTANTS
            ),
        )
    if isinstance(value, list | tuple):
        return tuple(_plain(item) for item in value)
    if isinstance(value, Mapping):
        return tuple(sorted((repr(k), _plain(v)) for k, v in value.items()))
    return value


def test_the_memory_curve_scores_like_the_file(
    capsys: pytest.CaptureFixture[str],
) -> None:
    memory, path = _memory_and_file(capsys)
    from_memory = check_outing(match_outing(REFERENCE, TRACE, memory, {}))
    from_file = check_outing(match_outing(REFERENCE, TRACE, path, {}))
    assert repr(_plain(from_memory.scores)) == repr(_plain(from_file.scores))
    assert from_memory.in_curve_window is from_file.in_curve_window


# --- La sélection ---------------------------------------------------------------------


def test_curve_selection_is_the_rolling_selection() -> None:
    assert curve_selection() == rolling_selection()
    dated = curve_selection(date(2024, 3, 1), date(2024, 3, 31))
    assert (dated.date_from, dated.date_to) == (date(2024, 3, 1), date(2024, 3, 31))


# --- La sortie ------------------------------------------------------------------------


def test_outing_day_is_the_paris_day(tmp_path: Path) -> None:
    assert outing_day(TRACE) == date(2026, 6, 1)
    text = TRACE.read_text(encoding="utf-8")
    assert "2026-06-01T08:0" in text
    late = tmp_path / "trace_tardive.gpx"
    late.write_text(
        text.replace("2026-06-01T08:0", "2026-05-31T22:3"), encoding="utf-8"
    )
    assert outing_day(late) == date(2026, 6, 1)


def test_outing_support_share(capsys: pytest.CaptureFixture[str]) -> None:
    memory, _ = _memory_and_file(capsys)
    match = match_outing(REFERENCE, TRACE, memory, {})
    assert match.curve is not None
    profile = build_profile(
        read_gpx(REFERENCE).route, ParameterSet(PROFILE_PARAMETER_SPECS)
    )
    expected = portion_out_of_support_time_share(
        profile, match.curve.curve, ParameterSet(PROJECTION_PARAMETER_SPECS), None
    )
    assert outing_support_share(match) == expected
    with pytest.raises(ValueError, match="pas de courbe"):
        outing_support_share(match_outing(REFERENCE, TRACE, None, {}))
