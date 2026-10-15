"""Documents du registre (§ 6.2 et § 8.1, test 4, du brief M4b-4 ; ``0010`` D14).

Un document est l'écriture canonique de ``{"type", "format", "data"}`` ; sa relecture
vérifie, dans l'ordre, le JSON en UTF-8, l'enveloppe, le type, le format, le contrat,
puis que la réécriture redonne les octets lus.
"""

import json
import re

import pytest

from fixtures import scoring
from fixtures.repeatability import case_reference
from mountain_perf.backtest import (
    DOCUMENT_TYPES,
    CodecError,
    canonical_bytes,
    decode_document,
    encode_document,
)
from mountain_perf.schemas import (
    REGISTRY_FORMAT_VERSION,
    Admission,
    CalibratedScenarioScores,
    OutingObservation,
    RepeatabilityReference,
    ScenarioScores,
)

OBSERVATION = scoring.scores("Régimes").observation
DOCUMENT = encode_document(OBSERVATION)
FORMAT = f'"format":{REGISTRY_FORMAT_VERSION}'.encode()


def _altered(data: bytes, old: bytes, new: bytes) -> bytes:
    """``data`` où ``old``, présent une fois, devient ``new`` : un remplacement qui ne
    trouverait rien ferait passer le test à vide (relecture C de la PR #24)."""
    assert data.count(old) == 1
    return data.replace(old, new)


def _refused(data: bytes, fragment: str) -> None:
    with pytest.raises(CodecError, match=re.escape(fragment)):
        decode_document(data, OutingObservation)


def test_document_types_are_exact() -> None:
    """D14 : observations, scores avec leurs prévisions, références D8 ; depuis le
    format 2, scores calés (M4c-2) ; depuis le format 3, document d'admission
    (M4c-3)."""
    assert (
        OutingObservation,
        ScenarioScores,
        RepeatabilityReference,
        CalibratedScenarioScores,
        Admission,
    ) == DOCUMENT_TYPES


def test_document_envelope_comes_first() -> None:
    assert DOCUMENT.startswith(b'{"type":"OutingObservation",' + FORMAT + b',"data":{')


def test_documents_read_back() -> None:
    scores = scoring.scores("Passages")
    reference = case_reference("Deux jours")
    assert decode_document(DOCUMENT, OutingObservation) == OBSERVATION
    assert decode_document(encode_document(scores.control), ScenarioScores) == (
        scores.control
    )
    assert (
        decode_document(encode_document(reference), RepeatabilityReference) == reference
    )


def test_document_of_another_type_is_refused() -> None:
    with pytest.raises(
        CodecError,
        match=re.escape(
            "document de type 'OutingObservation', 'ScenarioScores' attendu"
        ),
    ):
        decode_document(DOCUMENT, ScenarioScores)


def test_document_of_another_format_is_refused() -> None:
    _refused(
        _altered(DOCUMENT, FORMAT, b'"format":1'),
        f"document au format 1, {REGISTRY_FORMAT_VERSION} attendu",
    )


def test_document_envelope_is_exact() -> None:
    envelope = json.loads(DOCUMENT)
    extra = canonical_bytes({**envelope, "extra": 1})
    _refused(extra, "document : objet {type, format, data} attendu")
    _refused(b"[]", "document : objet {type, format, data} attendu")


def test_unreadable_document_is_refused() -> None:
    _refused(b"\xff" + DOCUMENT, "document illisible")
    _refused(DOCUMENT[:-1], "document illisible")


def test_non_canonical_document_is_refused() -> None:
    indented = json.dumps(json.loads(DOCUMENT), ensure_ascii=False, indent=2)
    _refused(indented.encode(), "document d'écriture non canonique")


def test_only_document_types_are_written() -> None:
    with pytest.raises(TypeError, match="OutingScores n'est pas un type de document"):
        encode_document(scoring.scores("Régimes"))


# ---------------------------------------------------------------------------
# Correctifs de la relecture de la PR #19
# ---------------------------------------------------------------------------


def test_document_with_a_z_offset_is_not_canonical() -> None:
    """§ 6.2 : la forme canonique se juge sur la réécriture du contrat relu, pas sur
    celle du JSON lu ; un instant écrit ``Z`` au lieu de ``+00:00`` (JSON canonique,
    lisible par ``fromisoformat``) est refusé."""
    scores = encode_document(scoring.scores("Régimes").control)
    assert scores.count(b'+00:00"') >= 1
    with pytest.raises(
        CodecError, match=re.escape("document d'écriture non canonique")
    ):
        decode_document(scores.replace(b'+00:00"', b'Z"', 1), ScenarioScores)


def test_type_is_checked_before_format() -> None:
    """§ 6.2, ``decode_document`` : le type se vérifie avant le format. Un document
    écrit au format 1 et relu au format du jour, sous un autre type, viole les deux
    contrôles (vérifié : sous son type, le format est refusé) ; le type est refusé
    d'abord (redressé en M4c-3 : depuis M4c-2, le remplacement de ``"format":1`` ne
    trouvait rien, et seul le type était faux)."""
    older = encode_document(OBSERVATION, 1)
    with pytest.raises(
        CodecError,
        match=re.escape(f"document au format 1, {REGISTRY_FORMAT_VERSION} attendu"),
    ):
        decode_document(older, OutingObservation)
    with pytest.raises(
        CodecError,
        match=re.escape(
            "document de type 'OutingObservation', 'ScenarioScores' attendu"
        ),
    ):
        decode_document(older, ScenarioScores)
