"""Les fichiers du registre (§ 6.3, § 7.2, § 7.3 et § 8.1, test 7, du brief M4b-4 ;
``0010`` D14).

La première ligne du journal au bit ; des lignes canoniques et chaînées ; un journal
coupé sur l'octet ``\\n`` seul ; huit documents nommés par leur empreinte, l'observation
partagée écrite une fois ; un document intact jamais réécrit ; une erreur du système de
fichiers qui remonte sans rien écrire.
"""

import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fixtures.registry import (
    REFERENCE_R1,
    at,
    d8_reference,
    declaration,
    outcomes,
    references,
    registry_root,
)
from fixtures.repeatability import DEUX_JOURS
from mountain_perf.backtest import (
    DOCUMENT_SUFFIX,
    DOCUMENTS_DIR,
    EVENTS_FILE,
    RegistryError,
    append_declaration,
    append_result,
    content_hash,
    load_outcomes,
    read_registry,
    verify_registry,
)
from mountain_perf.schemas import Exclusion
from test_backtest_registry import filled, journal_lines, snapshot

FIRST_LINE_SHA256 = "603f00f753f5ebd6626957b97c948addba4660c5ccb9cbba108b5dd274e37367"


def test_first_line_of_the_journal(tmp_path: Path) -> None:
    """§ 7.2 : la première ligne d'un registre où l'on a ajouté ``declaration()`` à
    ``at(0)`` : 5 474 octets et son ``sha256``."""
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    data = (root / EVENTS_FILE).read_bytes()
    assert data.endswith(b"\n")
    (line,) = journal_lines(root)
    assert len(line) == 5474
    assert content_hash(line) == FIRST_LINE_SHA256


def test_lines_are_canonical_and_chained(tmp_path: Path) -> None:
    """D14 : chaque ligne porte l'empreinte de la précédente ; le journal finit par
    ``\\n``."""
    root = filled(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(2))
    lines = journal_lines(root)
    events = read_registry(root).events
    assert len(lines) == len(events) == 3
    for previous, event in zip(lines, events[1:], strict=False):
        assert event.previous_hash == content_hash(previous)


def test_line_separators_inside_a_text_are_written_as_is(tmp_path: Path) -> None:
    """§ 6.3 : U+2028 et U+0085 s'écrivent tels quels ; le journal garde une ligne par
    événement, coupée sur l'octet ``\\n`` seul, et la relecture rend la déclaration."""
    root = registry_root(tmp_path)
    reason = "hors domaine\u2028VTT\u0085électrique"
    declared = declaration(exclusions=(Exclusion("velo-2026-05-27", reason),))
    append_declaration(root, declared, recorded_at=at(0))
    append_declaration(root, declaration(), recorded_at=at(1))
    data = (root / EVENTS_FILE).read_bytes()
    assert "\u2028".encode() in data
    assert "\u0085".encode() in data
    assert data.count(b"\n") == 2
    assert read_registry(root).events[0].declaration == declared


def test_eight_documents_named_by_their_hash(tmp_path: Path) -> None:
    """§ 7.3 : huit documents ; l'observation partagée de « Régimes » et de « Régimes
    sans référence » écrite une fois ; trois contrôles distincts, deux usages, une
    référence D8 ; pas d'usage pour ``p-2026-06-03``."""
    root = filled(tmp_path)
    paths = sorted((root / DOCUMENTS_DIR).iterdir())
    assert len(paths) == 8
    for path in paths:
        assert path.name == content_hash(path.read_bytes()) + DOCUMENT_SUFFIX
    result = read_registry(root).events[1].result
    assert result is not None
    q20, q27, p03 = result.outings
    assert q20.observation == p03.observation != q27.observation
    controls = {outing.models[0].control for outing in result.outings}
    usages = [outing.models[0].usage for outing in result.outings]
    assert len(controls) == 3
    assert usages[2] is None
    assert None not in usages[:2]
    cited = {q20.observation, q27.observation, *controls, *usages[:2]}
    cited.add(result.references[0].reference)
    assert {f"{sha}{DOCUMENT_SUFFIX}" for sha in cited} == {path.name for path in paths}


def test_recorded_at_defaults_to_now(tmp_path: Path) -> None:
    """D14 : sans ``recorded_at``, l'instant de l'ajout."""
    root = registry_root(tmp_path)
    before = datetime.now(UTC)
    event = append_declaration(root, declaration())
    after = datetime.now(UTC)
    assert before <= event.recorded_at <= after
    assert read_registry(root).events == (event,)


def test_intact_document_is_not_rewritten(tmp_path: Path) -> None:
    """§ 6.3, étape 7 : un document déjà présent et intact n'est pas réécrit."""
    root = filled(tmp_path)
    past = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    paths = sorted((root / DOCUMENTS_DIR).iterdir())
    for path in paths:
        os.utime(path, (past, past))
    append_result(
        root,
        1,
        outcomes(),
        references=references(),
        recorded_at=at(2),
        corrects=2,
        correction_reason="même résultat, réécrit",
    )
    assert sorted((root / DOCUMENTS_DIR).iterdir()) == paths
    assert all(path.stat().st_mtime == past for path in paths)


def test_documents_as_a_file_is_an_os_error(tmp_path: Path) -> None:
    """§ 6.3 : une erreur du système de fichiers remonte telle quelle ; le journal est
    inchangé et le verrou retiré."""
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    (root / DOCUMENTS_DIR).write_bytes(b"")
    before = snapshot(root)
    with pytest.raises(FileExistsError):
        append_result(root, 1, outcomes(), references=references(), recorded_at=at(1))
    after = snapshot(root)
    assert after.journal == before.journal
    assert not after.locked


# ---------------------------------------------------------------------------
# Correctifs de la relecture de la PR #19
# ---------------------------------------------------------------------------


def test_new_documents_in_a_registry_that_has_documents(tmp_path: Path) -> None:
    """§ 6.3, étape 7 : le dossier des documents est créé au besoin ; un résultat dont
    des documents sont neufs s'ajoute à un registre qui en a déjà."""
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    first, *others = outcomes()
    unscored = tuple(Exclusion(o.outing_id, "trace illisible") for o in others)
    # Q27 écartée : la référence de r1 n'a plus que le 2026-05-20 (M4c-2).
    alone = d8_reference(REFERENCE_R1.artifact.source, [DEUX_JOURS[0]])
    append_result(
        root,
        1,
        (first,),
        unscored=unscored,
        references=(("r1", alone),),
        recorded_at=at(1),
    )
    event = append_result(
        root,
        1,
        outcomes(),
        references=references(),
        recorded_at=at(2),
        corrects=2,
        correction_reason="erreur de saisie",
    )
    log = verify_registry(root)
    assert log.answer(1) == event
    assert load_outcomes(root, log, 3) == outcomes()


def test_registry_file_names_are_the_prescribed_ones(tmp_path: Path) -> None:
    """§ 6.3 : les noms sur disque sont prescrits — ``evenements.jsonl``,
    ``documents/<sha256>.json``, ``verrou`` ; les autres tests les écrivent avec les
    constantes du module."""
    root = filled(tmp_path)
    assert (root / "evenements.jsonl").is_file()
    assert (root / "documents").is_dir()
    names = [path.name for path in (root / "documents").iterdir()]
    assert len(names) == 8
    assert all(re.fullmatch(r"[0-9a-f]{64}\.json", name) for name in names)
    (root / "verrou").write_bytes(b"")
    with pytest.raises(RegistryError, match=re.escape("registre verrouillé")):
        append_declaration(root, declaration(), recorded_at=at(2))


def test_a_document_is_published_only_once_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§ 6.3, étape 7 : un document s'écrit dans un temporaire, ``flush``,
    ``os.fsync``, puis ``os.replace`` vers son nom ; une panne avant le remplacement ne
    laisse ni document sous son nom, ni ligne, ni verrou."""
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    journal = (root / EVENTS_FILE).read_bytes()

    def failing_fsync(descriptor: int) -> None:
        raise OSError(f"panne simulée ({descriptor})")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    with pytest.raises(OSError, match="panne simulée"):
        append_result(root, 1, outcomes(), references=references(), recorded_at=at(1))
    assert (root / EVENTS_FILE).read_bytes() == journal
    assert not list((root / DOCUMENTS_DIR).glob(f"*{DOCUMENT_SUFFIX}"))
    assert not (root / "verrou").exists()
