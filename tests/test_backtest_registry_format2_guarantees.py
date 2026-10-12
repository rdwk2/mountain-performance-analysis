"""Garanties du registre au format 2 tenues par des tests (correctifs de la PR #23,
M4c-2 ; relecture C et balayage de mutation de la conception).

- **L'accord durci vaut pour toute ligne, de tout format** (brief M4c-2, § 3,
  décisions 3 et 4 ; ``LIRE_DABORD_M4C-2.md``, point 4) : une ligne du format 1 dont
  une sortie scorée omet un modèle déclaré, ou qui n'a pas de référence D8 pour un
  parcours de répétabilité, est refusée.
- **Chaque document se relit au format de l'événement qui le cite** (précision de D14,
  M4c-2) : une ligne du format 2 qui cite un document du format 1, au contenu valable,
  est refusée.
- ``DOCUMENT_FIRST_FORMAT`` est en lecture seule (§ 6.1, ``MappingProxyType``).
- **Les contrôles se font dans l'ordre des listes** (§ 6) : sur une entrée qui viole
  deux contrôles voisins, le message est celui du premier — ``decode_document`` (le
  format avant le contrat), ``_check_reference_days`` (un jour omis avant un jour en
  trop ; les jours avant les jours multi-sorties), ``OutingOutcome`` (les modèles
  distincts, puis le type des scores, puis la même observation).

Les registres s'écrivent par le code du jour puis se récrivent par les aides de
``test_backtest_registry_format2.py`` (test 1 du brief).
"""

import re
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import cast

import pytest

from fixtures.registry import (
    OUTINGS,
    REFERENCE_R1,
    d8_reference,
    not_calibrated,
    outcome,
    outcomes,
    v0_of,
)
from fixtures.repeatability import DEUX_JOURS
from mountain_perf.backtest import (
    DOCUMENT_FIRST_FORMAT,
    DOCUMENT_SUFFIX,
    DOCUMENTS_DIR,
    CodecError,
    RegistryError,
    append_result,
    content_hash,
    decode_document,
    read_registry,
    verify_registry,
)
from mountain_perf.schemas import (
    CalibratedScenarioScores,
    ContractError,
    Exclusion,
    ModelKind,
    OutingObservation,
    OutingOutcome,
    RegistryEvent,
)
from test_backtest_registry_format2 import (
    CANDIDATE,
    V0_RAW,
    _declared,
    _multi_day,
    _registry,
    _rewrite,
    _to_format_1,
)

Q20_ID, Q27_ID, _ = (outing.outing_id for outing in OUTINGS)
SOURCE = REFERENCE_R1.artifact.source


# ---------------------------------------------------------------------------
# L'accord durci, pour une ligne du format 1 (décisions 3 et 4)
# ---------------------------------------------------------------------------


def _with_candidate(item: OutingOutcome) -> OutingOutcome:
    """``item``, scoré aussi par le candidat (des ``OutingScores``, comme v0 brut)."""
    return OutingOutcome(
        item.outing_id,
        item.coverage,
        (item.scores[0], (ModelKind.CANDIDATE, v0_of(item.outing_id))),
    )


def test_format_1_line_lacking_a_declared_model_is_refused(tmp_path: Path) -> None:
    """Décision 3 : une ligne du format 1 dont une sortie scorée omet un modèle déclaré
    (le candidat) est refusée à la lecture, le modèle nommé."""
    root = _registry(
        tmp_path,
        models=(V0_RAW, CANDIDATE),
        outcomes_=tuple(_with_candidate(item) for item in outcomes()),
    )

    def without_candidate(event: RegistryEvent) -> RegistryEvent:
        if event.result is None:
            return event
        outings = tuple(
            replace(outing, models=outing.models[:1])
            if outing.outing_id == Q27_ID
            else outing
            for outing in event.result.outings
        )
        return replace(event, result=replace(event.result, outings=outings))

    _to_format_1(root, without_candidate)
    message = (
        "'q-2026-05-27', une sortie scorée l'est par chaque modèle déclaré "
        "(D0, D9.2) ; absent : candidate"
    )
    with pytest.raises(RegistryError, match=re.escape(message)):
        read_registry(root)


def test_format_1_line_without_d8_reference_is_refused(tmp_path: Path) -> None:
    """Décision 4 : une ligne du format 1 sans référence D8 pour un parcours de
    répétabilité est refusée à la vérification."""
    root = _registry(tmp_path)

    def without_references(event: RegistryEvent) -> RegistryEvent:
        if event.result is None:
            return event
        return replace(event, result=replace(event.result, references=()))

    _to_format_1(root, without_references)
    read_registry(root)
    with pytest.raises(
        RegistryError,
        match=re.escape("le parcours de répétabilité 'r1' n'a pas de référence D8"),
    ):
        verify_registry(root)


# ---------------------------------------------------------------------------
# Chaque document au format de l'événement qui le cite
# ---------------------------------------------------------------------------


def test_format_2_line_citing_a_format_1_document_is_refused(tmp_path: Path) -> None:
    """Précision de D14 (M4c-2) : la référence D8 d'une ligne du format 2 récrite en
    document du format 1, au contenu valable, est refusée à la vérification."""
    root = _registry(tmp_path)
    log = read_registry(root)
    result = log.events[1].result
    assert result is not None
    sha = result.references[0].reference
    path = root / DOCUMENTS_DIR / f"{sha}{DOCUMENT_SUFFIX}"
    data = path.read_bytes()
    head = re.match(rb'\{"type":"[A-Za-z]+","format":2,', data)
    assert head is not None
    older = head.group(0).replace(b'"format":2,', b'"format":1,') + data[head.end() :]
    renamed = content_hash(older)
    (root / DOCUMENTS_DIR / f"{renamed}{DOCUMENT_SUFFIX}").write_bytes(older)

    def citing_it(event: RegistryEvent) -> RegistryEvent:
        if event.result is None:
            return event
        records = tuple(
            replace(record, reference=renamed) for record in event.result.references
        )
        return replace(event, result=replace(event.result, references=records))

    _rewrite(root, citing_it)
    read_registry(root)
    with pytest.raises(
        RegistryError, match=re.escape("document au format 1, 2 attendu")
    ):
        verify_registry(root)


def test_document_first_format_is_read_only() -> None:
    """§ 6.1 : ``DOCUMENT_FIRST_FORMAT`` est une vue en lecture seule
    (``types.MappingProxyType``) : le premier format d'un type ne s'écrit pas en
    cours d'exécution."""
    assert isinstance(DOCUMENT_FIRST_FORMAT, MappingProxyType)
    writable = cast(dict[type, int], DOCUMENT_FIRST_FORMAT)
    with pytest.raises(TypeError):
        writable[CalibratedScenarioScores] = 1
    assert DOCUMENT_FIRST_FORMAT[CalibratedScenarioScores] == 2


# ---------------------------------------------------------------------------
# L'ordre des contrôles (§ 6, « dans l'ordre des listes »)
# ---------------------------------------------------------------------------


def test_format_is_checked_before_the_contract() -> None:
    """§ 6.1, ``decode_document`` : le format de l'enveloppe se contrôle avant le
    contrat — un document au mauvais format et au contenu invalide est refusé pour
    son format."""
    data = b'{"type":"OutingObservation","format":1,"data":{}}'
    with pytest.raises(CodecError, match=re.escape("document au format 1, 2 attendu")):
        decode_document(data, OutingObservation, 2)


def test_omitted_day_is_named_before_an_extra_one(tmp_path: Path) -> None:
    """§ 6.1, ``_check_reference_days`` : chaque jour attendu absent avant chaque jour
    présent non attendu — la référence porte le 20 mai, dont la sortie n'est pas
    scorée, et omet le 27, scoré."""
    root = _declared(tmp_path)
    with pytest.raises(
        RegistryError,
        match=re.escape(
            "ajout refusé : la référence de 'r1' omet le jour 2026-05-27 du jeu de "
            "répétabilité"
        ),
    ):
        append_result(
            root,
            1,
            outcomes()[1:],
            unscored=(Exclusion(Q20_ID, "trace illisible"),),
            references=(("r1", d8_reference(SOURCE, [DEUX_JOURS[0]])),),
        )


def test_days_are_checked_before_multi_outing_days(tmp_path: Path) -> None:
    """§ 6.1, ``_check_reference_days`` : les jours, puis les jours multi-sorties — une
    référence vide omet le 27 mai (un jour) et le 20 mai (multi-sorties) ; le jour est
    nommé."""
    root = _declared(tmp_path, performances=_multi_day())
    with pytest.raises(
        RegistryError,
        match=re.escape(
            "ajout refusé : la référence de 'r1' omet le jour 2026-05-27 du jeu de "
            "répétabilité"
        ),
    ):
        append_result(
            root,
            1,
            outcomes(),
            unscored=(Exclusion("q-2026-05-20-b", "trace illisible"),),
            references=(("r1", d8_reference(SOURCE, [])),),
        )


def test_distinct_models_before_the_type_of_scores() -> None:
    """§ 6.1, ``OutingOutcome`` : l'invariant neuf vient après celui des modèles
    distincts — v0 brut deux fois, la seconde avec des scores calés."""
    first = outcome(Q20_ID)
    calibrated = not_calibrated(Q20_ID, ModelKind.V0_RECALIBRATED, v0_of(Q20_ID))
    with pytest.raises(
        ContractError,
        match=re.escape(
            "les modèles d'une sortie sont distincts, reçu v0_raw deux fois."
        ),
    ):
        OutingOutcome(
            Q20_ID, first.coverage, (*first.scores, (ModelKind.V0_RAW, calibrated))
        )


def test_type_of_scores_before_the_same_observation() -> None:
    """§ 6.1, ``OutingOutcome`` : l'invariant neuf vient avant celui de la même
    observation — Naismith avec les ``OutingScores`` d'une autre sortie."""
    first = outcome(Q20_ID)
    with pytest.raises(
        ContractError,
        match=re.escape(
            "naismith est un modèle calé : ses scores sont des CalibratedOutingScores."
        ),
    ):
        OutingOutcome(
            Q20_ID, first.coverage, (*first.scores, (ModelKind.NAISMITH, v0_of(Q27_ID)))
        )
