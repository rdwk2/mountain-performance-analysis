"""``mperf tables`` (AN1-2b, ``docs/decisions/0014``) : ``MPA_DATA_DIR/interim`` →
``MPA_DATA_DIR/processed``, sur l'``interim/`` synthétique de
``tests/fixtures/processed.py``. Le dossier des données est celui que ``conftest.py``
pose pour chaque test, jamais celui de ``.env``."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

import mountain_perf.analyse
import mountain_perf.analyse.tables
from fixtures.processed import write_interim
from mountain_perf.analyse.athlete import DEFAULT_SETTINGS
from mountain_perf.analyse.tables import build_tables
from mountain_perf.cli import main
from mountain_perf.config import data_dir
from mountain_perf.schemas import ContractError


def test_cli_tables_writes_both_tables_and_says_what_it_wrote(
    capsys: pytest.CaptureFixture[str],
) -> None:
    pytest.importorskip("pyarrow")
    from mountain_perf.analyse.parquet import read_tables

    folder = data_dir()
    write_interim(folder)
    assert main(["tables"]) == 0
    tables = build_tables(folder, DEFAULT_SETTINGS)
    assert read_tables(folder) == tables
    assert capsys.readouterr().out.splitlines() == [
        "Activités : 4",
        "Montées : 3",
        "  short_climb : 1",
        "  intermediate : 0",
        "  long_climb : 1",
        "  ski_touring : 1",
        "  short_ski_touring : 0",
        "  other_sport : 0",
        "Montées marquées : 1",
        "Montées instables : 0",
        f"Empreinte d'interim/ : {tables.provenance.interim_sha256}",
        "-> activites.parquet, montees.parquet",
    ]


def test_cli_tables_reads_the_declarations_of_the_athlete() -> None:
    pytest.importorskip("pyarrow")
    from mountain_perf.analyse.parquet import read_tables

    folder = data_dir()
    write_interim(folder)
    (folder / "athlete.toml").write_text(
        "[analyse]\nreference_vertical_speed_m_per_h = 300\n", encoding="utf-8"
    )
    assert main(["tables"]) == 0
    provenance = read_tables(folder).provenance
    assert provenance.reference_vertical_speed_declared is True
    assert provenance.reference_vertical_speed_ms == pytest.approx(300 / 3600)


@pytest.mark.parametrize(
    ("athlete", "message"),
    [
        (None, "Erreur : "),
        ("[analyse]\nvref = 1\n", "Erreur : [analyse] : clés inconnues"),
    ],
)
def test_cli_tables_errors(
    capsys: pytest.CaptureFixture[str], athlete: str | None, message: str
) -> None:
    """Sans ``interim/`` (premier cas), ou avec un ``athlete.toml`` refusé : un
    message, code 1, et rien d'écrit sous ``processed/``."""
    pytest.importorskip("pyarrow")
    folder = data_dir()
    if athlete is not None:
        write_interim(folder)
        (folder / "athlete.toml").write_text(athlete, encoding="utf-8")
    assert main(["tables"]) == 1
    assert capsys.readouterr().err.startswith(message)
    assert not (folder / "processed").exists()


def test_cli_tables_without_the_extra_says_how_to_install(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """pyarrow absent (``None`` dans ``sys.modules`` : son import échoue) : un message,
    code 1, sans rien lire. L'attribut ``parquet`` du paquet est posé, comme pour
    ``mperf ingest`` (``tests/test_ingest_imports.py``), pour que l'import du
    sous-module soit refait quels que soient les tests lancés avant celui-ci."""
    monkeypatch.delitem(sys.modules, "mountain_perf.analyse.parquet", raising=False)
    monkeypatch.setattr(
        mountain_perf.analyse,
        "parquet",
        types.ModuleType("mountain_perf.analyse.parquet"),
        raising=False,
    )
    monkeypatch.setitem(sys.modules, "pyarrow", None)
    write_interim(data_dir())
    assert main(["tables"]) == 1
    assert capsys.readouterr().err == (
        "Erreur : l'écriture des tables demande l'extra analyse. Installer : "
        "uv sync --extra analyse\n"
    )
    assert not (data_dir() / "processed").exists()


def test_cli_tables_does_not_hide_another_missing_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "mountain_perf.analyse.parquet", None)
    with pytest.raises(ModuleNotFoundError):
        main(["tables"])


def test_mperf_help_lists_the_tables_subcommand(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    with pytest.raises(SystemExit) as stop:
        main(["--help"])
    assert stop.value.code == 0
    assert (
        "Écrire les tables de MPA_DATA_DIR/processed depuis interim (AN1-2b)"
        in capsys.readouterr().out
    )


def test_the_tables_are_not_written_into_tmp_path(tmp_path: Path) -> None:
    """Le dossier des données de ``conftest.py`` n'est pas ``tmp_path`` : la commande
    n'écrit que sous ``MPA_DATA_DIR``."""
    pytest.importorskip("pyarrow")
    write_interim(data_dir())
    assert main(["tables"]) == 0
    assert list(tmp_path.iterdir()) == []


def test_cli_tables_names_the_activity_that_breaks_a_contract(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("pyarrow")

    def broken(*args: object, **kwargs: object) -> None:
        raise ContractError("contrat violé")

    monkeypatch.setattr(mountain_perf.analyse.tables, "_track_summary", broken)
    write_interim(data_dir())
    assert main(["tables"]) == 1
    assert capsys.readouterr().err == "Erreur : activité a1 : contrat violé\n"
    assert not (data_dir() / "processed").exists()


def test_cli_tables_names_a_document_that_does_not_read_back(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Un enregistrement d'``interim/`` d'un autre format : « Erreur : », l'activité
    nommée, code 1, rien d'écrit sous ``processed/``."""
    pytest.importorskip("pyarrow")
    folder = data_dir()
    write_interim(folder)
    path = folder / "interim" / "activities" / "recordings" / "a2.json"
    path.write_bytes(path.read_bytes().replace(b'"format":1', b'"format":9', 1))
    assert main(["tables"]) == 1
    assert capsys.readouterr().err == (
        "Erreur : activité a2 : document au format 9, 1 attendu\n"
    )
    assert not (folder / "processed").exists()
