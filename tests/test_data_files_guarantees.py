"""Garanties de ``add_file`` et ``list_curves`` sans test à la tête de la PR #33
(relecture de la PR) : l'ajout dans un dossier ``routes/`` ou ``sorties/`` déjà
peuplé — le cas du réel ; la création exclusive pour une sortie ; « rien n'est réécrit »
quelle que soit l'horloge ; tous les noms réservés par Windows ; un compagnon qui est un
dossier ; « sans cause chaînée » (``from None``).
"""

import os
import tempfile
from pathlib import Path

import pytest

from mountain_perf.config import data_dir
from mountain_perf.data_files import (
    AddFileError,
    AddOutcome,
    FileKind,
    add_file,
    list_curves,
)

FIXTURES = Path(__file__).parent / "fixtures"
ROUTE = FIXTURES / "mini_11.gpx"
TRACE = FIXTURES / "appariement_trace_x01.gpx"
CURVE = FIXTURES / "courbe_synthetique.csv"
OLD_NS = 1_000_000_000_000_000_000
"""Une date de modification ancienne (2001-09-09), en nanosecondes."""


@pytest.fixture(autouse=True)
def system_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Le dossier temporaire du système, redirigé vers un sous-dossier dédié."""
    systeme = tmp_path / "systeme"
    systeme.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(systeme))
    return systeme


def _tree(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


@pytest.mark.parametrize(
    ("kind", "folder", "bad"),
    [
        (FileKind.ROUTE, "routes", b"<gpx>pas du XML"),
        (FileKind.OUTING, "sorties", ROUTE.read_bytes()),
    ],
    ids=["prepare", "sortie"],
)
def test_the_kind_folder_already_exists(
    kind: FileKind, folder: str, bad: bytes
) -> None:
    """Le cas courant du réel : le dossier de la sorte existe déjà, avec d'autres
    fichiers. Un refus de contenu n'y écrit rien ; un ajout valide y écrit le
    fichier, et lui seul."""
    (data_dir() / folder).mkdir()
    (data_dir() / folder / "deja_la.gpx").write_bytes(ROUTE.read_bytes())
    before = _tree(data_dir())
    with pytest.raises(AddFileError):
        add_file(data_dir(), kind, "refuse.gpx", bad)
    assert _tree(data_dir()) == before
    outcome = add_file(data_dir(), kind, "accepte.gpx", TRACE.read_bytes())
    assert outcome is AddOutcome.ADDED
    assert _tree(data_dir()) == sorted([*before, f"{folder}/accepte.gpx"])
    assert (data_dir() / folder / "accepte.gpx").read_bytes() == TRACE.read_bytes()


def test_creation_is_exclusive_for_an_outing_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    appeared = b"apparu pendant la verification"

    def reader_that_races(paths: list[Path]) -> None:
        (data_dir() / "sorties").mkdir()
        (data_dir() / "sorties" / paths[0].name).write_bytes(appeared)

    monkeypatch.setattr("mountain_perf.data_files.read_trace", reader_that_races)
    with pytest.raises(AddFileError, match="pendant l'ajout") as error:
        add_file(data_dir(), FileKind.OUTING, "trace.gpx", TRACE.read_bytes())
    assert (data_dir() / "sorties" / "trace.gpx").read_bytes() == appeared
    assert error.value.__suppress_context__


def test_already_present_rewrites_nothing_whatever_the_clock() -> None:
    """La date de modification posée loin dans le passé : une réécriture se voit,
    quelle que soit la résolution de l'horloge du système de fichiers."""
    add_file(data_dir(), FileKind.ROUTE, "mini_11.gpx", ROUTE.read_bytes())
    target = data_dir() / "routes" / "mini_11.gpx"
    os.utime(target, ns=(OLD_NS, OLD_NS))
    outcome = add_file(data_dir(), FileKind.ROUTE, "mini_11.gpx", ROUTE.read_bytes())
    assert outcome is AddOutcome.ALREADY_PRESENT
    assert target.stat().st_mtime_ns == OLD_NS


def test_another_content_under_the_same_name_writes_nothing() -> None:
    add_file(data_dir(), FileKind.ROUTE, "mini_11.gpx", ROUTE.read_bytes())
    before = _tree(data_dir())
    with pytest.raises(AddFileError, match="avec un autre contenu"):
        add_file(data_dir(), FileKind.ROUTE, "mini_11.gpx", TRACE.read_bytes())
    assert _tree(data_dir()) == before


RESERVED = [
    "con",
    "prn",
    "aux",
    "nul",
    *[f"com{i}" for i in range(1, 10)],
    *[f"lpt{i}" for i in range(1, 10)],
]


@pytest.mark.parametrize("stem", RESERVED)
def test_every_reserved_device_name_is_refused(stem: str) -> None:
    with pytest.raises(AddFileError, match="Nom réservé par Windows"):
        add_file(data_dir(), FileKind.ROUTE, f"{stem.upper()}.gpx", ROUTE.read_bytes())
    assert _tree(data_dir()) == []


def test_a_companion_that_is_a_folder_is_no_companion() -> None:
    reference = data_dir() / "reference"
    reference.mkdir()
    (reference / "a.csv").write_bytes(CURVE.read_bytes())
    (reference / "a.meta.json").mkdir()
    assert list_curves(data_dir()) == ()


def test_a_refused_content_has_no_chained_cause() -> None:
    """« Sans cause chaînée » (``from None``, § 6.4 du brief) : ni cause explicite, ni
    contexte affiché."""
    with pytest.raises(AddFileError) as error:
        add_file(data_dir(), FileKind.ROUTE, "illisible.gpx", b"pas du XML")
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__
