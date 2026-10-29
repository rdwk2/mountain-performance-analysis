"""La commande de l'estimation de la courbe (M6b, ``docs/decisions/0017``) :
``MPA_DATA_DIR/interim`` → ``MPA_DATA_DIR/reference/<nom>.csv`` et son compagnon, sur
l'``interim/`` synthétique de ``tests/fixtures/processed.py`` (``a1`` à pied avec FC,
``a3`` à pied sans altitude). Le dossier des données est celui que ``conftest.py`` pose
pour chaque test ; l'état git du paquet est fixé, sauf dans le test qui le change. La
commande ne se lance jamais sur le vrai dossier des données : elle se teste par
``main([...])``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fixtures.processed import COMMIT, write_interim
from mountain_perf import gitstate
from mountain_perf.cli import CURVE_MODIFIED_TREE_ERROR, main
from mountain_perf.config import data_dir
from mountain_perf.gitstate import GitState
from mountain_perf.model.curve_io import EXTENDED_HEADER

WINDOW = ["--from", "2024-03-01", "--to", "2024-03-31", "--athlete", "x"]
COMMAND = "curve"


@pytest.fixture(autouse=True)
def clean_clone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un clone propre au commit des fixtures."""
    monkeypatch.setattr(
        gitstate, "git_state", lambda directory: GitState(COMMIT, False)
    )


def reference() -> Path:
    return data_dir() / "reference"


def listing() -> list[str] | None:
    folder = reference()
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else None


def companion(name: str = "saison") -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (reference() / f"{name}.meta.json").read_bytes().decode("utf-8")
    )
    return loaded


def run(capsys: pytest.CaptureFixture[str], *options: str) -> tuple[int, str, str]:
    code = main([COMMAND, "saison", *WINDOW, *options])
    out, err = capsys.readouterr()
    return code, out, err


def test_the_curve_is_written(capsys: pytest.CaptureFixture[str]) -> None:
    """La courbe et son compagnon, et le résumé ligne pour ligne ; l'entrée et
    l'enregistrement de ``a1`` viennent de deux exports, tous deux dits."""
    write_interim(data_dir())
    code, out, _ = run(capsys)
    assert code == 0
    assert out.splitlines() == [
        "activités retenues : 1 sur 2 candidates ; tranches : 13, dont 4 d'au moins "
        "10 min",
        "  activités écartées, sans trace : 1",
        "  activités avec un niveau : 1 ; écoulé / M : 1.0087",
        "-> reference/saison.csv et reference/saison.meta.json",
    ]
    assert listing() == ["saison.csv", "saison.meta.json"]
    csv_text = (reference() / "saison.csv").read_bytes().decode("utf-8")
    assert csv_text.split("\n")[0] == ",".join(EXTENDED_HEADER)
    meta = companion()
    assert meta["athlete_ref"] == "x"
    assert meta["activity_count"] == 1
    assert meta["source_activity_types"] == ["trail_running"]
    assert (meta["date_from"], meta["date_to"]) == ("2024-03-01", "2024-03-31")
    assert meta["hr_center_bpm"] is None
    assert meta["hr_lag_s"] is None
    estimation = meta["estimation"]
    assert estimation["commit"] == COMMIT
    assert estimation["value"] == "somme"
    assert estimation["excluded_activities"] == {"sans trace": 1}
    assert estimation["projectable"] is True
    assert estimation["exports_retrieved_at"] == [
        "2024-04-01T10:00:00+00:00",
        "2026-01-01T00:00:00+00:00",
    ]


def test_without_a_filter_neither_width_nor_lag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Sans filtre de FC, ni largeur ni décalage, malgré les défauts de la commande
    (``0017``, P5.4) ; la méthode identifiable dans le compagnon."""
    write_interim(data_dir())
    assert run(capsys)[0] == 0
    meta = companion()
    assert (meta["hr_center_bpm"], meta["hr_width_bpm"], meta["hr_lag_s"]) == (
        None,
        None,
        None,
    )
    estimation = meta["estimation"]
    assert estimation["heart_rate_integration"] == "exacte, pas coupés au prorata"
    assert estimation["heart_rate_max_step_s"] == 10.0
    assert estimation["clock_convention"] == "θc"
    assert estimation["level_kind"] == "diagnostic d'ajustement, en échantillon"
    assert estimation["parameters"]["hr_min_coverage"] == 0.8


def test_the_options(capsys: pytest.CaptureFixture[str]) -> None:
    """Les durées en minutes à la ligne de commande, en secondes dans la provenance."""
    write_interim(data_dir())
    code, _, _ = run(
        capsys,
        "--hr-center",
        "140",
        "--hr-lag",
        "30",
        "--min-duration-min",
        "1",
        "--max-duration-min",
        "600",
        "--max-elapsed-min",
        "100",
        "--value",
        "b",
        "--types",
        "trail_running,backcountry_skiing",
    )
    assert code == 0
    meta = companion()
    assert (meta["hr_center_bpm"], meta["hr_width_bpm"], meta["hr_lag_s"]) == (
        140.0,
        10.0,
        30.0,
    )
    assert (meta["min_duration_s"], meta["max_duration_s"], meta["max_elapsed_s"]) == (
        60.0,
        36000.0,
        6000.0,
    )
    assert meta["source_activity_types"] == ["backcountry_skiing", "trail_running"]
    assert meta["estimation"]["value"] == "médiane"
    assert meta["estimation"]["parameters"]["hr_lag_s"] == 30.0


def test_the_ceiling(capsys: pytest.CaptureFixture[str]) -> None:
    """Plafonnée à 10 min, la courbe synthétique n'est pas projetable : elle s'écrit,
    et la commande le dit (``0017``, P2.4, P3.7)."""
    write_interim(data_dir())
    code, out, _ = run(capsys, "--max-elapsed-min", "10")
    assert code == 0
    lines = out.splitlines()
    assert lines[:5] == [
        "activités retenues : 1 sur 2 candidates ; tranches : 6, dont 0 d'au moins "
        "10 min",
        "  activités écartées, sans trace : 1",
        "  intervalles écartés, au-delà du plafond : 73",
        "  intervalles coupés au plafond : 1",
        "  activités avec un niveau : 0 ; écoulé / M : 1.0292",
    ]
    assert any(
        "Courbe non projetable par read_curve : La tranche centrale" in line
        for line in lines[5:]
    )
    estimation = companion()["estimation"]
    assert estimation["projectable"] is False
    assert estimation["support_error"].startswith("La tranche centrale")
    counts = estimation["counts"]
    assert counts["truncated"] == 1
    assert counts["elapsed_s"] == pytest.approx(600, abs=1e-6)
    assert counts["after_ceiling_s"] == pytest.approx(3326, abs=1e-9)


# --- Les refus ----------------------------------------------------------------------


def refused(
    capsys: pytest.CaptureFixture[str], arguments: list[str], message: str
) -> str:
    """La commande refuse : code 1, « Erreur : … » qui contient ``message``,
    ``reference/`` inchangé."""
    before = listing()
    code = main(arguments)
    _, err = capsys.readouterr()
    assert code == 1
    assert err.startswith("Erreur : ")
    assert message in err
    assert listing() == before
    return err


def test_a_modified_tree_is_refused(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une courbe dit le commit qui l'a estimée."""
    write_interim(data_dir())
    monkeypatch.setattr(gitstate, "git_state", lambda directory: GitState(COMMIT, True))
    err = refused(capsys, [COMMAND, "saison", *WINDOW], CURVE_MODIFIED_TREE_ERROR)
    assert err == CURVE_MODIFIED_TREE_ERROR + "\n"
    assert listing() is None


@pytest.mark.parametrize("existing", ["saison.csv", "saison.meta.json"])
def test_an_existing_curve_is_refused_before_reading(
    capsys: pytest.CaptureFixture[str], existing: str
) -> None:
    """Sans ``interim/`` : le refus vient avant toute lecture."""
    reference().mkdir(parents=True)
    (reference() / existing).write_bytes(b"")
    refused(capsys, [COMMAND, "saison", *WINDOW], f"{existing} existe déjà")


@pytest.mark.parametrize("name", ["x.csv", "x.CSV", "a/b", ".x", "a b", "é"])
def test_an_invalid_name_is_refused(
    capsys: pytest.CaptureFixture[str], name: str
) -> None:
    write_interim(data_dir())
    refused(capsys, [COMMAND, name, *WINDOW], "nom de courbe invalide")


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (["--hr-width", "10"], "demandent --hr-center"),
        (["--hr-lag", "10"], "demandent --hr-center"),
        (["--hr-center", "10"], "hr_center_bpm"),
        (["--hr-center", "150", "--hr-width", "0"], "hr_width_bpm"),
        (["--min-duration-min", "60", "--max-duration-min", "30"], "max_duration_s"),
        (["--types", ""], "source_activity_types"),
    ],
)
def test_invalid_options_are_refused(
    capsys: pytest.CaptureFixture[str], options: list[str], message: str
) -> None:
    write_interim(data_dir())
    refused(capsys, [COMMAND, "saison", *WINDOW, *options], message)


def test_a_window_without_candidates_is_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_interim(data_dir())
    window = ["--from", "2025-01-01", "--to", "2025-12-31", "--athlete", "x"]
    refused(capsys, [COMMAND, "saison", *window], "aucune activité candidate")


def test_without_interim_the_command_is_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    refused(capsys, [COMMAND, "saison", *WINDOW], "")


def test_the_help_names_the_eleven_options(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    with pytest.raises(SystemExit) as stopped:
        main([COMMAND, "--help"])
    assert stopped.value.code == 0
    out = capsys.readouterr().out
    for option in (
        "--from",
        "--to",
        "--athlete",
        "--types",
        "--min-duration-min",
        "--max-duration-min",
        "--max-elapsed-min",
        "--hr-center",
        "--hr-width",
        "--hr-lag",
        "--value",
    ):
        assert option in out
    assert data_dir() != tmp_path
