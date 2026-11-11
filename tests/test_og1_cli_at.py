"""La commande de la courbe à l'origine (OG-1, ``docs/decisions/0020``) et le chargement
attesté du corpus, sur l'``interim/`` synthétique de ``tests/fixtures/processed.py``
(``a1`` à pied le 2024-03-09, retenue ; ``a2`` ski de randonnée le 2024-03-10 ; ``a3`` à
pied sans altitude le 2024-03-11, « sans trace » ; ``a4`` golf sans enregistrement).

La commande ne se lance jamais sur le vrai dossier des données : elle se teste par
``main([...])``. L'horloge et l'état git sont fixés."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fixtures.processed import COMMIT, write_interim
from mountain_perf import cli, gitstate
from mountain_perf.backtest.calendar import origin as calendar_origin
from mountain_perf.cli import main
from mountain_perf.config import data_dir
from mountain_perf.estimation.origin import check_origin, window_lower_bound
from mountain_perf.gitstate import GitState
from mountain_perf.ingest.interim import (
    InterimError,
    read_index,
    read_recording,
    write_activities,
)
from mountain_perf.model.curve_io import CurveError
from mountain_perf.runs import load_curve_corpus
from mountain_perf.validation import ContractError
from test_cli_curve_guarantees import write_interim_with_a_later_export
from test_ingest_interim import REPORT

NOW = datetime(2024, 4, 1, 12, tzinfo=UTC)
ORIGIN_0325 = datetime(2024, 3, 17, 23, tzinfo=UTC)
"""L'origine du jour 2024-03-25."""
AT = ["--at", "2024-03-25", "--athlete", "x"]
RANGE = ["--from", "2024-03-01", "--to", "2024-03-31", "--athlete", "x"]
TRAIL = frozenset({"trail_running"})
EXPORTS = ["2024-04-01T10:00:00+00:00", "2026-01-01T00:00:00+00:00"]


@pytest.fixture(autouse=True)
def fixed_world(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un clone propre au commit des fixtures, l'horloge à :data:`NOW`."""
    monkeypatch.setattr(
        gitstate, "git_state", lambda directory: GitState(COMMIT, False)
    )
    monkeypatch.setattr(cli, "_now", lambda: NOW)


def realign(folder: Path) -> None:
    """Chaque enregistrement recalé sur le départ de son entrée : les enregistrements
    des fixtures partent le 2026-01-01, sous des entrées de 2024 (§ 7, piège 2)."""
    index = read_index(folder)
    recordings = [
        dataclasses.replace(
            read_recording(folder, item.activity_ref), start_time=item.start_time
        )
        for item in index.entries
        if item.has_recording
    ]
    write_activities(folder, index, recordings, REPORT)


def write_aligned(folder: Path) -> None:
    write_interim(folder)
    realign(folder)


def run(
    capsys: pytest.CaptureFixture[str], *options: str, name: str = "origine"
) -> tuple[int, str, str]:
    code = main(["curve", name, *options])
    out, err = capsys.readouterr()
    return code, out, err


def listing() -> list[str] | None:
    folder = data_dir() / "reference"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else None


def refused(
    capsys: pytest.CaptureFixture[str], options: list[str], message: str
) -> tuple[str, str]:
    """Code 1, « Erreur : … » qui contient ``message``, ``reference/`` inchangé ; rend
    les deux sorties."""
    before = listing()
    code, out, err = run(capsys, *options)
    assert code == 1
    assert err.startswith("Erreur : ")
    assert message in err
    assert listing() == before
    return out, err


def companion(name: str = "origine") -> dict[str, Any]:
    path = data_dir() / "reference" / f"{name}.meta.json"
    loaded: dict[str, Any] = json.loads(path.read_bytes().decode("utf-8"))
    return loaded


def activities(*parts: str) -> Path:
    return data_dir().joinpath("interim", "activities", *parts)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def damage(path: Path) -> None:
    path.write_bytes(path.read_bytes()[:100])


def instant(text: str) -> datetime:
    return datetime.fromisoformat(text)


# --- La courbe écrite ---------------------------------------------------------------


def test_the_curve_at_the_origin_is_written(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_aligned(data_dir())
    code, out, _ = run(capsys, *AT)
    assert code == 0
    lines = out.splitlines()
    assert len(lines) == 9
    assert lines[0] == (
        "jour 2024-03-25 : origine 2024-03-18 00:00 à Paris ; fenêtre 56 jours, fins "
        "depuis le 2024-01-22 00:00 à Paris"
    )
    assert lines[1] == (
        "activités inspectées : 2 (candidate 2, finie à l'origine ou après 0, finie "
        "avant la fenêtre 0, fin inconnue 0)"
    )
    assert lines[2].startswith("  dernières fins, à Paris : candidate 2024-03-11")
    assert "; retenue 2024-03-09" in lines[2]
    assert lines[3] == (
        "historique à l'origine, selon l'index : 2 sorties à pied finies (0 sans "
        "écoulé), 2 des types choisis (0 sans écoulé)"
    )
    assert lines[4].startswith(
        "avertissement : moins de 20 sorties à pied passées (2) : repère indicatif"
    )
    assert lines[5:] == [
        "activités retenues : 1 sur 2 candidates ; tranches : 13, dont 4 d'au moins "
        "10 min",
        "  activités écartées, sans trace : 1",
        "  activités avec un niveau : 1 ; écoulé / M : 1.0087",
        "-> reference/origine.csv et reference/origine.meta.json",
    ]
    assert listing() == ["origine.csv", "origine.meta.json"]


@pytest.mark.parametrize(
    "options",
    [[], ["--hr-center", "140", "--hr-lag", "0", "--max-elapsed-min", "30"]],
    ids=["defauts", "fc-decalage-plafond"],
)
def test_the_same_retained_activities_give_the_same_rows(
    capsys: pytest.CaptureFixture[str], options: list[str]
) -> None:
    """La plage et l'origine retiennent ``a1`` seule : les deux CSV sont identiques,
    octet pour octet."""
    write_aligned(data_dir())
    assert run(capsys, *RANGE, *options, name="plage")[0] == 0
    assert run(capsys, *AT, *options)[0] == 0
    reference = data_dir() / "reference"
    plage, origine = (reference / "plage.csv", reference / "origine.csv")
    assert plage.read_bytes() == origine.read_bytes()
    for key in ("hr_center_bpm", "hr_width_bpm", "hr_lag_s", "max_elapsed_s"):
        assert companion("plage")[key] == companion()[key]


def test_the_companion_at_the_origin(capsys: pytest.CaptureFixture[str]) -> None:
    write_aligned(data_dir())
    assert run(capsys, *AT)[0] == 0
    meta = companion()
    assert (meta["date_from"], meta["date_to"]) == ("2024-03-09", "2024-03-09")
    assert meta["generated_at"] == NOW.isoformat()
    assert meta["diagnostic_support_threshold_min"] == 10.0
    assert meta["estimator"].startswith(
        "mperf curve --at (OG-1) : règle à l'origine, fenêtre 56 jours ; "
    )
    estimation = meta["estimation"]
    assert estimation["mode"] == "origine"
    assert estimation["exports_retrieved_at"] == EXPORTS
    assert estimation["support_grade_range"] == [-0.0125, 0.0125]
    section = estimation["origin"]
    assert section["origin"] == ORIGIN_0325.isoformat()
    assert section["window"] == 56
    assert section["lower_bound"] == "2024-01-21T23:00:00+00:00"
    assert section["outcome"] == "courbe projetable"
    assert section["index_sha256"] == file_sha256(activities("index.json"))
    assert section["history"] == {
        "foot_index_finished": 2,
        "foot_without_index_elapsed": 0,
        "selected_index_finished": 2,
        "selected_without_index_elapsed": 0,
    }
    lines = section["activities"]
    assert [line["activity_ref"] for line in lines] == ["a1", "a3"]
    for line in lines:
        assert line["decision"] == "candidate"
        assert line["method"] == "index et enregistrement"
        ref = line["activity_ref"]
        assert line["recording_sha256"] == file_sha256(
            activities("recordings", f"{ref}.json")
        )
        assert instant(line["safe_end"]) == max(
            instant(line["index_end"]), instant(line["recording_end"])
        )
    assert [(line["fate"], line["contributes"]) for line in lines] == [
        ("retenue", True),
        ("sans trace", False),
    ]
    assert section["last_retained_end"] == lines[0]["safe_end"]
    assert section["data_available_at"] == lines[1]["safe_end"]


def test_the_exports_at_the_origin_are_those_of_the_retained_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """D2 : ni l'export de l'entrée de ``a3`` (2024-05-01), ni celui de son
    enregistrement (2025-06-01)."""
    write_interim_with_a_later_export()
    realign(data_dir())
    assert run(capsys, *AT)[0] == 0
    estimation = companion()["estimation"]
    assert [
        (line["activity_ref"], line["fate"])
        for line in estimation["origin"]["activities"]
    ] == [("a1", "retenue"), ("a3", "sans trace")]
    assert estimation["exports_retrieved_at"] == EXPORTS


def test_a_range_companion_says_its_mode(capsys: pytest.CaptureFixture[str]) -> None:
    write_aligned(data_dir())
    assert run(capsys, *RANGE)[0] == 0
    meta = companion()
    assert meta["estimation"]["mode"] == "plage"
    assert meta["estimation"]["origin"] is None
    assert meta["generated_at"] == NOW.isoformat()


def test_all_the_past(capsys: pytest.CaptureFixture[str]) -> None:
    write_aligned(data_dir())
    code, out, _ = run(capsys, *AT, "--window", "all")
    assert code == 0
    assert out.splitlines()[0] == (
        "jour 2024-03-25 : origine 2024-03-18 00:00 à Paris ; fenêtre tout le passé"
    )
    meta = companion()
    assert meta["estimation"]["origin"]["window"] == "all"
    assert meta["estimation"]["origin"]["lower_bound"] is None
    assert "fenêtre all ;" in meta["estimator"]


# --- Les absences -------------------------------------------------------------------


def test_a_one_day_window_retains_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    write_aligned(data_dir())
    out, err = refused(
        capsys,
        ["--at", "2024-03-19", "--window", "1", "--athlete", "x"],
        "aucune courbe à l'origine : ",
    )
    assert err.endswith("Rien n'est écrit.\n")
    assert out.splitlines()[1] == (
        "activités inspectées : 2 (candidate 1, finie à l'origine ou après 0, finie "
        "avant la fenêtre 1, fin inconnue 0)"
    )
    assert "; retenue aucune" in out


def test_without_candidate_nothing_is_written(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_aligned(data_dir())
    out, _ = refused(
        capsys,
        ["--at", "2024-03-10", "--athlete", "x"],
        "aucune courbe à l'origine : aucune activité candidate",
    )
    assert out.splitlines()[0].startswith(
        "jour 2024-03-10 : origine 2024-03-03 00:00 à Paris"
    )
    assert listing() is None


def test_other_types_select_other_activities(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_aligned(data_dir())
    code, out, _ = run(capsys, *AT, "--types", "backcountry_skiing")
    assert code == 0
    lines = out.splitlines()
    assert lines[1].startswith("activités inspectées : 1 (candidate 1, ")
    assert (
        "historique à l'origine, selon l'index : 2 sorties à pied finies (0 sans "
        "écoulé), 1 des types choisis (0 sans écoulé)"
    ) in lines
    assert lines[-2].startswith("Courbe non projetable par read_curve : ")
    estimation = companion()["estimation"]
    assert estimation["origin"]["outcome"] == "courbe non projetable"
    assert estimation["origin"]["history"] == {
        "foot_index_finished": 2,
        "foot_without_index_elapsed": 0,
        "selected_index_finished": 1,
        "selected_without_index_elapsed": 0,
    }
    assert estimation["projectable"] is False


# --- Les refus avant toute lecture --------------------------------------------------


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (
            ["--at", "2024-03-25", "--from", "2024-03-01", "--athlete", "x"],
            "--at exclut --from et --to",
        ),
        (
            ["--at", "2024-03-25", "--to", "2024-03-31", "--athlete", "x"],
            "--at exclut --from et --to",
        ),
        (
            ["--from", "2024-03-01", "--athlete", "x"],
            "--from et --to ensemble, ou --at.",
        ),
        (["--to", "2024-03-31", "--athlete", "x"], "--from et --to ensemble, ou --at."),
        (["--athlete", "x"], "--from et --to ensemble, ou --at."),
        ([*RANGE, "--window", "5"], "--window demande --at."),
    ],
)
def test_a_malformed_selection_is_refused_before_reading(
    capsys: pytest.CaptureFixture[str], options: list[str], message: str
) -> None:
    refused(capsys, options, message)


def test_the_name_is_checked_before_the_selection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, _, err = run(capsys, "--athlete", "x", name="x.csv")
    assert code == 1
    assert "nom de courbe invalide" in err


@pytest.mark.parametrize("value", ["0", "-3", "05", "+5", "x", "ALL", "1.5", " 5"])
def test_an_invalid_window_is_an_argument_error(
    capsys: pytest.CaptureFixture[str], value: str
) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["curve", "origine", *AT, "--window", value])
    assert stopped.value.code == 2
    assert "fenêtre invalide" in capsys.readouterr().err


def test_a_future_origin_is_refused_before_reading(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    just_before = ORIGIN_0325 - timedelta(microseconds=1)
    monkeypatch.setattr(cli, "_now", lambda: just_before)
    refused(capsys, AT, "l'origine du jour 2024-03-25 (2024-03-18 00:00 à Paris) est")


def test_the_origin_at_the_present_instant_is_allowed(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    write_aligned(data_dir())
    monkeypatch.setattr(cli, "_now", lambda: ORIGIN_0325)
    assert run(capsys, *AT)[0] == 0
    assert companion()["generated_at"] == ORIGIN_0325.isoformat()


@pytest.mark.parametrize("existing", ["origine.csv", "origine.meta.json"])
def test_an_existing_curve_is_refused_before_reading_at_the_origin(
    capsys: pytest.CaptureFixture[str], existing: str
) -> None:
    """Sans ``interim/`` : le refus vient avant toute lecture."""
    reference = data_dir() / "reference"
    reference.mkdir()
    (reference / existing).write_bytes(b"")
    refused(capsys, AT, f"{existing} existe déjà")


def test_the_help_names_at_and_window(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["curve", "--help"])
    assert stopped.value.code == 0
    out = capsys.readouterr().out
    for option in ("--at", "--window", "--from", "--to", "--min-support-min"):
        assert option in out


# --- Le chargement attesté du corpus ------------------------------------------------


def test_the_corpus_attests_the_files_it_read() -> None:
    write_aligned(data_dir())
    corpus = load_curve_corpus(data_dir(), "x", TRAIL, ORIGIN_0325, 56)
    assert corpus.athlete_ref == "x"
    assert corpus.index_sha256 == file_sha256(activities("index.json"))
    assert list(corpus.recordings) == ["a1", "a3"]
    for ref, digest in corpus.recording_sha256.items():
        assert digest == file_sha256(activities("recordings", f"{ref}.json"))


def test_an_activity_the_index_ends_after_the_origin_is_not_read() -> None:
    write_aligned(data_dir())
    damage(activities("recordings", "a3.json"))
    origin = datetime(2024, 3, 10, 23, tzinfo=UTC)
    corpus = load_curve_corpus(data_dir(), "x", TRAIL, origin, 56)
    assert list(corpus.recordings) == ["a1"]


def test_an_activity_the_index_ends_before_the_window_is_not_read() -> None:
    """F : ni lue ni son document abîmé relevé."""
    write_aligned(data_dir())
    origin = datetime(2029, 12, 31, 23, tzinfo=UTC)
    assert load_curve_corpus(data_dir(), "x", TRAIL, origin, "all").recordings
    damage(activities("recordings", "a1.json"))
    assert not load_curve_corpus(data_dir(), "x", TRAIL, origin, 56).recordings


def test_only_the_chosen_types_are_read() -> None:
    write_aligned(data_dir())
    types = frozenset({"backcountry_skiing"})
    corpus = load_curve_corpus(data_dir(), "x", types, ORIGIN_0325, 56)
    assert list(corpus.recordings) == ["a2"]


def test_a_damaged_recording_names_its_activity() -> None:
    write_aligned(data_dir())
    damage(activities("recordings", "a1.json"))
    with pytest.raises(CurveError, match=r"^activité a1 : .*relancer `mperf ingest`"):
        load_curve_corpus(data_dir(), "x", TRAIL, ORIGIN_0325, 56)


def test_a_damaged_index_is_a_curve_error() -> None:
    write_aligned(data_dir())
    damage(activities("index.json"))
    with pytest.raises(CurveError, match=r"^index d'interim/ : "):
        load_curve_corpus(data_dir(), "x", TRAIL, ORIGIN_0325, 56)


def test_a_missing_recording_stays_an_interim_error() -> None:
    write_aligned(data_dir())
    activities("recordings", "a3.json").unlink()
    with pytest.raises(InterimError, match=r"a3\.json manque"):
        load_curve_corpus(data_dir(), "x", TRAIL, ORIGIN_0325, 56)


def test_the_corpus_origin_is_midnight_in_paris() -> None:
    write_aligned(data_dir())
    late = ORIGIN_0325 + timedelta(hours=1)
    with pytest.raises(ContractError, match="00:00 à Paris"):
        load_curve_corpus(data_dir(), "x", TRAIL, late, 56)


@pytest.mark.parametrize(
    ("day", "origin", "lower"),
    [
        (
            date(2024, 4, 7),
            datetime(2024, 3, 30, 23, tzinfo=UTC),
            datetime(2024, 2, 3, 23, tzinfo=UTC),
        ),
        (
            date(2024, 11, 3),
            datetime(2024, 10, 26, 22, tzinfo=UTC),
            datetime(2024, 8, 31, 22, tzinfo=UTC),
        ),
    ],
)
def test_the_origin_of_a_day_across_the_clock_changes(
    day: date, origin: datetime, lower: datetime
) -> None:
    computed = calendar_origin(day)
    assert computed == origin
    assert check_origin(computed) == origin
    assert window_lower_bound(computed, 56) == lower


def test_the_rule_takes_the_diagnostics_threshold(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_aligned(data_dir())
    code, out, _ = run(capsys, *AT, "--min-support-min", "1440")
    assert code == 0
    assert "dont 0 d'au moins 1440 min" in out
    meta = companion()
    assert meta["diagnostic_support_threshold_min"] == 1440.0
    assert meta["estimation"]["origin"]["outcome"] == "courbe non projetable"
    assert meta["estimation"]["level"] is None
