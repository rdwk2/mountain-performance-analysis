"""Ajout et relecture du registre (§ 6.3, § 7.3 et § 8.1, test 6, du brief M4b-4 ;
``0010`` D14).

Le registre rempli du § 7.3 : la déclaration de v0 brut à ``at(0)``, puis son résultat
à ``at(1)``, relus par ``read_registry`` et ``verify_registry`` ; ses événements, ses
sorties scorées et ses références relues depuis les documents.

Ce fichier porte aussi les aides des autres tests du registre (registre rempli, état
des fichiers, réécriture d'une ligne).
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fixtures.registry import (
    at,
    declaration,
    outcomes,
    references,
    registry_root,
)
from fixtures.repeatability import case_reference
from mountain_perf.backtest import (
    DOCUMENTS_DIR,
    EVENTS_FILE,
    LOCK_FILE,
    append_declaration,
    append_result,
    canonical_bytes,
    content_hash,
    decode_contract,
    encode_contract,
    load_outcomes,
    load_references,
    read_registry,
    verify_registry,
)
from mountain_perf.schemas import EventKind, RegistryEvent

# ---------------------------------------------------------------------------
# Aides partagées
# ---------------------------------------------------------------------------


def filled(tmp_path: Path) -> Path:
    """Le registre du § 7.3 : ``declaration()`` à ``at(0)``, puis son résultat à
    ``at(1)``."""
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    append_result(root, 1, outcomes(), references=references(), recorded_at=at(1))
    return root


@dataclass(frozen=True)
class Snapshot:
    """L'état des fichiers d'un registre : journal, noms des documents, verrou."""

    journal: bytes
    documents: frozenset[str]
    locked: bool


def snapshot(root: Path) -> Snapshot:
    journal = root / EVENTS_FILE
    documents = root / DOCUMENTS_DIR
    return Snapshot(
        journal.read_bytes() if journal.is_file() else b"",
        frozenset(path.name for path in documents.iterdir())
        if documents.is_dir()
        else frozenset(),
        (root / LOCK_FILE).exists(),
    )


def journal_lines(root: Path) -> list[bytes]:
    """Les lignes du journal, coupées sur ``\\n`` (le journal finit par ``\\n``)."""
    data = (root / EVENTS_FILE).read_bytes()
    assert data.endswith(b"\n")
    return data.split(b"\n")[:-1]


def line_bytes(event: RegistryEvent) -> bytes:
    return canonical_bytes(encode_contract(event))


def read_line(line: bytes) -> RegistryEvent:
    return decode_contract(RegistryEvent, json.loads(line))


def rewrite_last(root: Path, change: Callable[[RegistryEvent], RegistryEvent]) -> None:
    """Réécrit la dernière ligne, en écriture canonique : la chaîne reste juste (la
    dernière ligne n'est protégée par aucune empreinte, § 6.3)."""
    lines = journal_lines(root)
    lines[-1] = line_bytes(change(read_line(lines[-1])))
    (root / EVENTS_FILE).write_bytes(b"".join(line + b"\n" for line in lines))


# ---------------------------------------------------------------------------
# Le registre rempli
# ---------------------------------------------------------------------------


def test_first_declaration_event(tmp_path: Path) -> None:
    """D14 : l'événement rendu par ``append_declaration`` est celui que l'on relit,
    numéro 1, sans empreinte précédente, à l'instant donné."""
    root = registry_root(tmp_path)
    event = append_declaration(root, declaration(), recorded_at=at(0))
    assert (event.number, event.kind, event.previous_hash) == (
        1,
        EventKind.DECLARATION,
        None,
    )
    assert event.recorded_at == at(0)
    assert read_registry(root).events == (event,)


def test_filled_registry_lines(tmp_path: Path) -> None:
    """§ 7.3 : deux lignes, chacune l'écriture canonique de son événement, chaînées."""
    root = filled(tmp_path)
    log = read_registry(root)
    lines = journal_lines(root)
    assert [line_bytes(event) for event in log.events] == lines
    assert [event.number for event in log.events] == [1, 2]
    assert [event.kind for event in log.events] == [
        EventKind.DECLARATION,
        EventKind.RESULT,
    ]
    assert [event.previous_hash for event in log.events] == [
        None,
        content_hash(lines[0]),
    ]
    assert log.events[1].answers == 1


def test_appended_events_are_the_ones_read_back(tmp_path: Path) -> None:
    root = registry_root(tmp_path)
    first = append_declaration(root, declaration(), recorded_at=at(0))
    second = append_result(
        root, 1, outcomes(), references=references(), recorded_at=at(1)
    )
    assert read_registry(root).events == (first, second)
    assert first.declaration == declaration()


def test_filled_registry_reads_back_its_documents(tmp_path: Path) -> None:
    """D14 : les prévisions conservées, et les références D8, se relisent."""
    root = filled(tmp_path)
    log = read_registry(root)
    assert verify_registry(root) == log
    assert load_outcomes(root, log, 2) == outcomes()
    assert load_references(root, log, 2) == references()
    assert log.answer(1) == log.event(2)


# ---------------------------------------------------------------------------
# Correctifs de la relecture de la PR #19
# ---------------------------------------------------------------------------


def test_d8_references_keep_the_caller_order(tmp_path: Path) -> None:
    """§ 6.3, étape 0 : les références D8 sont citées dans l'ordre de l'appelant, et
    relues dans cet ordre."""
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    pairs = (references()[0], ("r2", case_reference("Vide")))
    event = append_result(root, 1, outcomes(), references=pairs, recorded_at=at(1))
    assert event.result is not None
    assert [record.route_id for record in event.result.references] == ["r1", "r2"]
    assert load_references(root, read_registry(root), 2) == pairs
