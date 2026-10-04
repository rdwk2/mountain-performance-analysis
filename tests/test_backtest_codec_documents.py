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
    OutingObservation,
    RepeatabilityReference,
    ScenarioScores,
)

OBSERVATION = scoring.scores("Régimes").observation
DOCUMENT = encode_document(OBSERVATION)


def _refused(data: bytes, fragment: str) -> None:
    with pytest.raises(CodecError, match=re.escape(fragment)):
        decode_document(data, OutingObservation)


def test_document_types_are_exact() -> None:
    """D14 : observations, scores avec leurs prévisions, références D8."""
    assert (OutingObservation, ScenarioScores, RepeatabilityReference) == DOCUMENT_TYPES


def test_document_envelope_comes_first() -> None:
    assert DOCUMENT.startswith(b'{"type":"OutingObservation","format":1,"data":{')


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
    _refused(DOCUMENT.replace(b'"format":1', b'"format":2', 1), "document au format 2")


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
    """§ 6.2, ``decode_document`` : le type se vérifie avant le format."""
    with pytest.raises(
        CodecError,
        match=re.escape(
            "document de type 'OutingObservation', 'ScenarioScores' attendu"
        ),
    ):
        decode_document(
            DOCUMENT.replace(b'"format":1', b'"format":2', 1), ScenarioScores
        )
