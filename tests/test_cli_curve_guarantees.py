"""Les garanties de la commande de la courbe (M6b, ``docs/decisions/0017``) que la
relecture de la PR #37 a trouvées sans test : un ``interim/`` qui ne se relit pas, un
type de ``--types`` à espace, les refus de l'état git, les tranches de 10 min pile,
l'ordre des dernières lignes, les exports dits au compagnon.

Par ``main([...])`` sur l'``interim/`` synthétique de ``tests/fixtures/processed.py``
(``a1`` à pied avec FC, ``a3`` à pied sans altitude, donc « sans trace ») ; l'état
git est fixé, sauf dans les tests qui le changent. La commande ne se lance jamais sur le
vrai dossier des données."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from typing import Any

import pytest

import mountain_perf.estimation.intervals as intervals_module
from fixtures.processed import COMMIT, write_interim
from mountain_perf import gitstate
from mountain_perf.cli import main
from mountain_perf.config import data_dir
from mountain_perf.estimation.intervals import TraceRefusal
from mountain_perf.gitstate import GitFailure, GitState, GitStateError
from mountain_perf.ingest.interim import read_recording, write_activities
from mountain_perf.schemas import ActivityIndex, ActivityRecording
from test_estimation_curve import GRADES, uniform
from test_ingest_interim import INDEX_SOURCE, LATER_INDEX, REPORT

WINDOW = ["--from", "2024-03-01", "--to", "2024-03-31", "--athlete", "x"]
COMMAND = "curve"
ACTIVITIES = ("interim", "activities")


@pytest.fixture(autouse=True)
def clean_clone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un clone propre au commit des fixtures."""
    monkeypatch.setattr(
        gitstate, "git_state", lambda directory: GitState(COMMIT, False)
    )


def run(capsys: pytest.CaptureFixture[str], *options: str) -> tuple[int, str, str]:
    code = main([COMMAND, "saison", *WINDOW, *options])
    out, err = capsys.readouterr()
    return code, out, err


def reference_exists() -> bool:
    return (data_dir() / "reference").exists()


# --- Un interim/ qui ne se relit pas ------------------------------------------------


def test_an_index_of_another_format_is_an_error_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """L'index écrit au format 1 (un ``interim/`` d'avant AN2-0, non régénéré) : la
    ``CodecError`` devient « Erreur : index d'interim/ : … », code 1, sans trace."""
    write_interim(data_dir())
    path = data_dir().joinpath(*ACTIVITIES, "index.json")
    document = json.loads(path.read_bytes().decode("utf-8"))
    document["format"] = 1
    path.write_bytes(json.dumps(document).encode("utf-8"))
    code, out, err = run(capsys)
    assert code == 1
    assert out == ""
    assert err == (
        "Erreur : index d'interim/ : document au format 1, 2 attendu ; relancer "
        "`mperf ingest`.\n"
    )
    assert not reference_exists()


def test_a_damaged_recording_is_an_error_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Un enregistrement tronqué : « Erreur : activité a1 : … ; relancer `mperf
    ingest`. », code 1, sans trace."""
    write_interim(data_dir())
    path = data_dir().joinpath(*ACTIVITIES, "recordings", "a1.json")
    path.write_bytes(path.read_bytes()[:100])
    code, _, err = run(capsys)
    assert code == 1
    assert err.startswith("Erreur : activité a1 : ")
    assert err.endswith("relancer `mperf ingest`.\n")
    assert not reference_exists()


def test_a_recording_a_contract_refuses_is_an_error_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Un enregistrement qui se décode, mais qu'un contrat refuse à la relecture (des
    instants qui ne croissent pas) : « Erreur : activité a1 : … ; relancer `mperf
    ingest`. », code 1, sans trace."""
    write_interim(data_dir())
    path = data_dir().joinpath(*ACTIVITIES, "recordings", "a1.json")
    original = path.read_bytes()
    assert b'"time_s":[1.0,2.0,' in original
    path.write_bytes(original.replace(b'"time_s":[1.0,2.0,', b'"time_s":[1.0,1.0,', 1))
    code, _, err = run(capsys)
    assert code == 1
    assert err.startswith(
        "Erreur : activité a1 : time_s doit être strictement croissante"
    )
    assert err.endswith(" ; relancer `mperf ingest`.\n")
    assert not reference_exists()


# --- Les refus avant toute lecture --------------------------------------------------


def test_a_type_with_a_space_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    """Un type de ``--types`` à espace en tête : refusé, jamais normalisé ; rien n'est
    écrit sous ``reference/``."""
    write_interim(data_dir())
    code, out, err = run(capsys, "--types", "trail_running, backcountry_skiing")
    assert code == 1
    assert out == ""
    assert err == (
        "Erreur : type de la source ' backcountry_skiing' : une espace en tête ou en "
        "fin.\n"
    )
    assert not reference_exists()


def test_a_git_failure_is_an_error_message(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    write_interim(data_dir())

    def failing(directory: Any) -> GitState:
        raise GitStateError(GitFailure.GIT_MISSING)

    monkeypatch.setattr(gitstate, "git_state", failing)
    code, _, err = run(capsys)
    assert code == 1
    assert err == "Erreur : git introuvable\n"
    assert not reference_exists()


def test_a_modified_tree_is_refused_before_reading_interim(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sans ``interim/`` : le refus de l'arbre modifié vient avant toute lecture. Le
    message est recopié du brief (§ 6.5)."""
    monkeypatch.setattr(gitstate, "git_state", lambda directory: GitState(COMMIT, True))
    code, _, err = run(capsys)
    assert code == 1
    assert err == (
        "Erreur : le code exécuté a des fichiers suivis modifiés ; une courbe dit le "
        "commit qui l'a estimée (committer ou annuler les modifications).\n"
    )
    assert not reference_exists()


# --- Le résumé ----------------------------------------------------------------------


def test_ten_minutes_exactly_count_as_ten_minutes(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cinq tranches de 600 s de temps M exactement : « dont 5 d'au moins 10 min »
    (le temps qui porte la valeur **atteint** 600 s)."""
    write_interim(data_dir())

    def crafted(recording: Any, profile: Any, **options: Any) -> Any:
        if recording.activity_ref == "a1":
            return uniform("a1", 2.0, GRADES, 600.0)
        return TraceRefusal.NO_TRACE

    monkeypatch.setattr(intervals_module, "activity_intervals", crafted)
    code, out, _ = run(capsys)
    assert code == 0
    assert out.splitlines()[0] == (
        "activités retenues : 1 sur 2 candidates ; tranches : 5, dont 5 d'au moins "
        "10 min"
    )


def test_the_non_projectable_line_comes_before_the_files(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Plafonnée à 10 min, la courbe n'est pas projetable : l'avant-dernière ligne le
    dit, la dernière nomme les fichiers."""
    write_interim(data_dir())
    code, out, _ = run(capsys, "--max-elapsed-min", "10")
    assert code == 0
    lines = out.splitlines()
    assert lines[-2].startswith("Courbe non projetable par read_curve : ")
    assert lines[-1] == "-> reference/saison.csv et reference/saison.meta.json"


# --- Les exports dits au compagnon --------------------------------------------------


def write_interim_with_a_later_export() -> ActivityIndex:
    """L'``interim/`` des fixtures, réécrit : l'entrée de ``a3`` vient d'un export plus
    tardif, et son enregistrement d'un export d'un autre instant encore. ``a3`` reste
    sans trace : une candidate non retenue."""
    index = write_interim(data_dir())
    recordings: list[ActivityRecording] = []
    for ref in ("a1", "a2", "a3"):
        recording = read_recording(data_dir(), ref)
        if ref == "a3":
            recording = dataclasses.replace(
                recording,
                source=dataclasses.replace(
                    recording.source, retrieved_at=datetime(2025, 6, 1, tzinfo=UTC)
                ),
            )
        recordings.append(recording)
    entries = tuple(
        dataclasses.replace(entry, source=LATER_INDEX)
        if entry.activity_ref == "a3"
        else entry
        for entry in index.entries
    )
    later = ActivityIndex(entries, (INDEX_SOURCE, LATER_INDEX))
    write_activities(data_dir(), later, recordings, REPORT)
    return later


def test_the_exports_are_those_of_the_retained_candidates_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Les instants d'acquisition au compagnon sont ceux de l'entrée et de
    l'enregistrement des **seules** candidates retenues (§ 6.5, point 10) : ceux de
    ``a3``, candidate sans trace, n'y figurent pas."""
    index = write_interim_with_a_later_export()
    a3 = next(entry for entry in index.entries if entry.activity_ref == "a3")
    assert a3.source.retrieved_at == datetime(2024, 5, 1, 10, tzinfo=UTC)
    code, out, _ = run(capsys)
    assert code == 0
    assert out.splitlines()[:2] == [
        "activités retenues : 1 sur 2 candidates ; tranches : 13, dont 4 d'au moins "
        "10 min",
        "  activités écartées, sans trace : 1",
    ]
    meta = json.loads(
        (data_dir() / "reference" / "saison.meta.json").read_bytes().decode("utf-8")
    )
    assert meta["estimation"]["exports_retrieved_at"] == [
        "2024-04-01T10:00:00+00:00",
        "2026-01-01T00:00:00+00:00",
    ]
