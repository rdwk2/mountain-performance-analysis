"""Relecture du registre (§ 6.3, § 7.4 et § 8.1, test 8, du brief M4b-4 ; ``0010``
D14).

Chaque refus de relecture du § 7.4, en ``RegistryError`` de type exact et son message ;
chaque ordre prescrit, par une entrée qui viole deux règles à la fois ; et les refus
que seule la vérification voit (``read_registry`` passe, ``verify_registry`` refuse).
"""

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from fixtures.registry import (
    CALIBRATED_MODELS,
    at,
    declaration,
    experiment,
    not_calibrated,
    outcomes,
    references,
    registry_root,
    v0_of,
)
from mountain_perf.backtest import (
    DOCUMENT_SUFFIX,
    DOCUMENTS_DIR,
    EVENTS_FILE,
    RegistryError,
    append_declaration,
    append_failure,
    append_result,
    content_hash,
    load_outcomes,
    read_registry,
    verify_registry,
)
from mountain_perf.schemas import Failure, FailureKind, ModelKind, RegistryEvent, Result
from test_backtest_registry import (
    filled,
    journal_lines,
    line_bytes,
    read_line,
    rewrite_last,
    snapshot,
)

TRUNCATED = (
    "evenements.jsonl, ligne 2 : ligne tronquée (sans fin de ligne) : un ajout a été "
    "interrompu. Si aucun ajout n'est en cours, retirer cette ligne incomplète à la "
    "main"
)


def _refused(root: Path, pattern: str) -> None:
    with pytest.raises(RegistryError, match=pattern):
        read_registry(root)


def _write_journal(root: Path, data: bytes) -> None:
    (root / EVENTS_FILE).write_bytes(data)


def _result(event: RegistryEvent) -> Result:
    assert event.result is not None
    return event.result


def _with_result(event: RegistryEvent, result: Result) -> RegistryEvent:
    return replace(event, result=result)


# ---------------------------------------------------------------------------
# Dossier et journal
# ---------------------------------------------------------------------------


def test_missing_root(tmp_path: Path) -> None:
    """§ 6.3, étape 1 : pas de dossier, pas de registre."""
    _refused(registry_root(tmp_path), re.escape("registre introuvable"))


def test_root_without_journal_is_an_empty_registry(tmp_path: Path) -> None:
    root = registry_root(tmp_path)
    root.mkdir()
    assert read_registry(root).events == ()
    _write_journal(root, b"")
    assert read_registry(root).events == ()


@pytest.mark.parametrize("cut", ["one-byte", "twenty-bytes-into-line-2"])
def test_truncated_journal(tmp_path: Path, cut: str) -> None:
    """§ 6.3, étape 2 : un journal qui ne finit pas par ``\\n`` est refusé, à la
    relecture comme à l'ajout, et le message dit quoi faire ; l'ajout n'écrit rien."""
    root = filled(tmp_path)
    data = (root / EVENTS_FILE).read_bytes()
    first = data.index(b"\n") + 1
    _write_journal(root, data[:-1] if cut == "one-byte" else data[: first + 20])
    _refused(root, re.escape(TRUNCATED))
    before = snapshot(root)
    with pytest.raises(RegistryError, match=re.escape(TRUNCATED)):
        append_failure(root, 1, Failure(FailureKind.TECHNICAL, "plantage"))
    assert snapshot(root) == before


def test_unreadable_json_line(tmp_path: Path) -> None:
    root = filled(tmp_path)
    first = journal_lines(root)[0]
    _write_journal(root, first + b"\n{\n")
    _refused(root, re.escape("evenements.jsonl, ligne 2 : JSON illisible"))


def test_crlf_journal_is_not_canonical(tmp_path: Path) -> None:
    """§ 6.3 : les lignes sont coupées sur ``\\n`` seul ; une fin de ligne CRLF reste
    visible et fait refuser la ligne 1."""
    root = filled(tmp_path)
    _write_journal(root, (root / EVENTS_FILE).read_bytes().replace(b"\n", b"\r\n"))
    _refused(root, re.escape("evenements.jsonl, ligne 1 : écriture non canonique"))


def test_line_with_missing_fields(tmp_path: Path) -> None:
    root = filled(tmp_path)
    first = journal_lines(root)[0]
    _write_journal(root, first + b'\n{"number":2}\n')
    _refused(
        root,
        re.escape("evenements.jsonl, ligne 2 : ")
        + ".*"
        + re.escape("champs manquants de RegistryEvent"),
    )


def test_modified_line_breaks_the_chain(tmp_path: Path) -> None:
    """D14 : la ligne suivante porte l'empreinte de la ligne modifiée."""
    root = filled(tmp_path)
    data = (root / EVENTS_FILE).read_bytes()
    assert data.count(b'"commit":"0') == 1
    _write_journal(root, data.replace(b'"commit":"0', b'"commit":"f'))
    _refused(
        root,
        re.escape(
            "evenements.jsonl, ligne 2 : l'empreinte de la ligne précédente ne "
            "correspond pas"
        ),
    )


def test_line_written_with_spaces_is_not_canonical(tmp_path: Path) -> None:
    root = filled(tmp_path)
    first, second = journal_lines(root)
    spaced = json.dumps(json.loads(second), ensure_ascii=False).encode()
    _write_journal(root, first + b"\n" + spaced + b"\n")
    _refused(root, re.escape("evenements.jsonl, ligne 2 : écriture non canonique"))


def test_line_with_another_number(tmp_path: Path) -> None:
    root = filled(tmp_path)
    rewrite_last(root, lambda event: replace(event, number=3))
    _refused(root, re.escape("evenements.jsonl, ligne 2 : porte le numéro 3"))


def test_line_with_an_escaped_lone_surrogate(tmp_path: Path) -> None:
    """§ 6.2 : un texte écrit en échappement JSON ``\\udcff`` ne s'encode pas en UTF-8 ;
    la relecture le refuse, chemin compris."""
    root = filled(tmp_path)
    data = (root / EVENTS_FILE).read_bytes()
    assert data.count(b"hors domaine : VTT") == 1
    _write_journal(
        root, data.replace(b"hors domaine : VTT", b"hors domaine \\udcff VTT")
    )
    _refused(
        root,
        re.escape(
            "evenements.jsonl, ligne 1 : declaration.exclusions[0].reason : un texte "
            "doit s'encoder en UTF-8"
        ),
    )


# ---------------------------------------------------------------------------
# Documents et accord sans documents
# ---------------------------------------------------------------------------


def test_altered_then_missing_document(tmp_path: Path) -> None:
    """§ 6.3, étape 5 : chaque document cité est présent et intact."""
    root = filled(tmp_path)
    result = _result(read_registry(root).events[1])
    usage = result.outings[1].models[0].usage
    assert usage is not None
    name = f"{DOCUMENTS_DIR}/{usage}{DOCUMENT_SUFFIX}"
    path = root / name
    data = path.read_bytes()
    assert data.count(b'"format":2') == 1
    path.write_bytes(data.replace(b'"format":2', b'"format":2 '))
    _refused(root, re.escape(f"{name} : document altéré"))
    path.unlink()
    _refused(root, re.escape(f"{name} : document introuvable"))


def test_declared_outing_without_fate(tmp_path: Path) -> None:
    """D0 : chaque sortie déclarée a un sort, vérifié aussi à la relecture."""
    root = filled(tmp_path)

    def drop_p03(event: RegistryEvent) -> RegistryEvent:
        result = _result(event)
        return _with_result(event, replace(result, outings=result.outings[:2]))

    rewrite_last(root, drop_p03)
    _refused(
        root,
        re.escape(
            "evenements.jsonl, ligne 2 : la sortie déclarée 'p-2026-06-03' n'est ni "
            "scorée ni écartée avec un motif"
        ),
    )


# ---------------------------------------------------------------------------
# Vérification : read_registry passe, verify_registry refuse
# ---------------------------------------------------------------------------


def _verify_refused(root: Path, pattern: str) -> None:
    read_registry(root)
    with pytest.raises(RegistryError, match=pattern):
        verify_registry(root)


def test_control_replaced_by_an_observation(tmp_path: Path) -> None:
    """§ 6.3 : ``verify_registry`` décode chaque document sous son type."""
    root = filled(tmp_path)

    def swap(event: RegistryEvent) -> RegistryEvent:
        result = _result(event)
        q20 = result.outings[0]
        model = replace(q20.models[0], control=q20.observation)
        q20 = replace(q20, models=(model,))
        return _with_result(event, replace(result, outings=(q20, *result.outings[1:])))

    rewrite_last(root, swap)
    _verify_refused(root, re.escape("'ScenarioScores' attendu"))


def test_observation_of_another_outing(tmp_path: Path) -> None:
    """D7.1 : les scores se reconstruisent sur leur observation (effectifs)."""
    root = filled(tmp_path)

    def swap(event: RegistryEvent) -> RegistryEvent:
        result = _result(event)
        q20, q27, p03 = result.outings
        q20 = replace(q20, observation=q27.observation)
        return _with_result(event, replace(result, outings=(q20, q27, p03)))

    rewrite_last(root, swap)
    _verify_refused(root, re.escape("'q-2026-05-20', ") + ".*segments admis")


def test_controls_swapped_between_outings(tmp_path: Path) -> None:
    """D2.6, précision de D14 : un contrôle nomme la première trace déclarée de sa
    sortie ; même observation et mêmes effectifs ne suffisent pas."""
    root = filled(tmp_path)

    def swap(event: RegistryEvent) -> RegistryEvent:
        result = _result(event)
        q20, q27, p03 = result.outings
        q20_model = replace(q20.models[0], control=p03.models[0].control)
        p03_model = replace(p03.models[0], control=q20.models[0].control)
        outings = (
            replace(q20, models=(q20_model,)),
            q27,
            replace(p03, models=(p03_model,)),
        )
        return _with_result(event, replace(result, outings=outings))

    rewrite_last(root, swap)
    _verify_refused(
        root,
        re.escape(
            "evenements.jsonl, ligne 2 : 'q-2026-05-20', v0_raw, control : la "
            "prévision ne nomme pas la première trace déclarée de la sortie"
        ),
    )


# ---------------------------------------------------------------------------
# Ordres prescrits
# ---------------------------------------------------------------------------


def test_end_of_journal_before_any_line(tmp_path: Path) -> None:
    """§ 6.3 : la fin du journal se vérifie avant toute ligne."""
    root = filled(tmp_path)
    second = journal_lines(root)[1]
    _write_journal(root, b"{\n" + second[:-1])
    _refused(root, re.escape("evenements.jsonl, ligne 2 : ligne tronquée"))


def test_form_before_number(tmp_path: Path) -> None:
    """§ 6.3 : la forme canonique se vérifie avant le numéro."""
    root = filled(tmp_path)
    first, second = journal_lines(root)
    renumbered = line_bytes(replace(read_line(second), number=3))
    spaced = json.dumps(json.loads(renumbered), ensure_ascii=False).encode()
    _write_journal(root, first + b"\n" + spaced + b"\n")
    _refused(root, re.escape("evenements.jsonl, ligne 2 : écriture non canonique"))


def test_number_before_chain(tmp_path: Path) -> None:
    """§ 6.3 : le numéro se vérifie avant la chaîne des empreintes."""
    root = filled(tmp_path)
    wrong = content_hash(b"autre ligne")
    rewrite_last(root, lambda event: replace(event, number=3, previous_hash=wrong))
    _refused(root, re.escape("evenements.jsonl, ligne 2 : porte le numéro 3"))


def test_declaration_alone_reads_back(tmp_path: Path) -> None:
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    assert verify_registry(root) == read_registry(root)


# ---------------------------------------------------------------------------
# Correctifs de la relecture de la PR #19
# ---------------------------------------------------------------------------


def test_links_are_checked_at_reading(tmp_path: Path) -> None:
    """§ 6.3, relecture, étape 4 : les liens du journal relu ; leur ``ContractError``
    devient une ``RegistryError`` préfixée de « evenements.jsonl : »."""
    root = filled(tmp_path)
    rewrite_last(
        root,
        lambda event: replace(event, corrects=1, correction_reason="erreur de saisie"),
    )
    _refused(
        root,
        re.escape(
            "evenements.jsonl : l'événement 2 (result) corrige l'événement 1 "
            "(declaration)"
        ),
    )


def test_line_with_a_z_offset_is_not_canonical(tmp_path: Path) -> None:
    """§ 6.3, relecture : la forme canonique se juge sur la réécriture de l'événement
    relu, pas sur celle du JSON lu ; un instant écrit ``Z`` au lieu de ``+00:00`` (JSON
    canonique, lisible par ``fromisoformat``) est refusé."""
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    data = (root / EVENTS_FILE).read_bytes()
    assert data.count(b'+00:00"') > 1
    _write_journal(root, data.replace(b'+00:00"', b'Z"', 1))
    _refused(root, re.escape("evenements.jsonl, ligne 1 : écriture non canonique"))


def test_messages_start_with_the_path_in_the_registry(tmp_path: Path) -> None:
    """§ 6.3, règle 1 : les messages nomment les fichiers par leur chemin dans le
    registre, jamais par un chemin absolu — le message **commence** par ce chemin."""
    root = filled(tmp_path)
    data = (root / EVENTS_FILE).read_bytes()
    _write_journal(root, data[:-1])
    _refused(root, "^" + re.escape("evenements.jsonl, ligne 2 : ligne tronquée"))
    _write_journal(root, data)
    observation = _result(read_registry(root).events[1]).outings[0].observation
    name = f"documents/{observation}.json"
    (root / name).unlink()
    _refused(root, "^" + re.escape(f"{name} : document introuvable"))


def test_links_before_documents_at_reading(tmp_path: Path) -> None:
    """§ 6.3, relecture : les liens du journal (étape 4) se vérifient avant les
    documents des résultats (étape 5)."""
    root = filled(tmp_path)
    observation = _result(read_registry(root).events[1]).outings[0].observation
    (root / f"documents/{observation}.json").unlink()
    rewrite_last(
        root,
        lambda event: replace(event, corrects=1, correction_reason="erreur de saisie"),
    )
    _refused(
        root,
        re.escape("evenements.jsonl : l'événement 2 (result) corrige l'événement 1"),
    )


def test_agreement_before_documents_at_reading(tmp_path: Path) -> None:
    """§ 6.3, relecture, étape 5 : pour un résultat, l'accord sans documents se vérifie
    avant ses documents."""
    root = filled(tmp_path)
    control = _result(read_registry(root).events[1]).outings[0].models[0].control
    (root / f"documents/{control}.json").unlink()

    def drop_p03(event: RegistryEvent) -> RegistryEvent:
        result = _result(event)
        return _with_result(event, replace(result, outings=result.outings[:2]))

    rewrite_last(root, drop_p03)
    _refused(
        root,
        re.escape(
            "evenements.jsonl, ligne 2 : la sortie déclarée 'p-2026-06-03' n'est ni "
            "scorée ni écartée avec un motif"
        ),
    )


def test_load_outcomes_messages_name_the_line(tmp_path: Path) -> None:
    """Point soumis 8 du plan : ``load_outcomes`` relit les documents avec les messages
    de ``verify_registry``, préfixés de la ligne du résultat."""
    root = filled(tmp_path)

    def swap(event: RegistryEvent) -> RegistryEvent:
        result = _result(event)
        q20, q27, p03 = result.outings
        q20 = replace(q20, observation=q27.observation)
        return _with_result(event, replace(result, outings=(q20, q27, p03)))

    rewrite_last(root, swap)
    log = read_registry(root)
    with pytest.raises(
        RegistryError,
        match=re.escape("evenements.jsonl, ligne 2 : 'q-2026-05-20', ")
        + ".*segments admis",
    ):
        load_outcomes(root, log, 2)


def test_forecasts_are_checked_model_by_model(tmp_path: Path) -> None:
    """§ 6.3, accord par les documents : les prévisions d'une sortie se recoupent
    modèle par modèle — celles du premier avant le décodage des documents du second."""
    root = registry_root(tmp_path)
    declared = declaration(models=CALIBRATED_MODELS, experiment=experiment())
    append_declaration(root, declared, recorded_at=at(0))
    two_models = tuple(
        replace(
            o,
            scores=(
                *o.scores,
                (
                    ModelKind.V0_RECALIBRATED,
                    not_calibrated(
                        o.outing_id, ModelKind.V0_RECALIBRATED, v0_of(o.outing_id)
                    ),
                ),
                (ModelKind.CANDIDATE, v0_of(o.outing_id)),
            ),
        )
        for o in outcomes()
    )
    append_result(root, 1, two_models, references=references(), recorded_at=at(1))

    def swap(event: RegistryEvent) -> RegistryEvent:
        result = _result(event)
        q20, q27, p03 = result.outings
        v0_raw, recalibrated, candidate = q20.models
        v0_raw = replace(v0_raw, control=p03.models[0].control)
        recalibrated = replace(recalibrated, control=q20.observation)
        q20 = replace(q20, models=(v0_raw, recalibrated, candidate))
        return _with_result(event, replace(result, outings=(q20, q27, p03)))

    rewrite_last(root, swap)
    _verify_refused(
        root,
        re.escape(
            "evenements.jsonl, ligne 2 : 'q-2026-05-20', v0_raw, control : la "
            "prévision ne nomme pas la première trace déclarée de la sortie"
        ),
    )
