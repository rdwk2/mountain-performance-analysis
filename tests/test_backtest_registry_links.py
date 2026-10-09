"""Liens et corrections par l'API (§ 6.3, § 7.4 et § 8.1, test 10, du brief M4b-4 ;
``0010`` D14 ; décision 4).

Une déclaration reçoit au plus une réponse qui n'en corrige pas une autre ; une
correction est un événement neuf du même type, qui nomme l'événement corrigé et son
motif ; un événement est corrigé au plus une fois. Chaque refus : rien n'est écrit.
"""

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from fixtures.registry import at, declaration, outcomes, references, registry_root
from mountain_perf.backtest import (
    RegistryError,
    append_declaration,
    append_failure,
    append_result,
    load_outcomes,
    read_registry,
)
from mountain_perf.schemas import Failure, FailureKind
from test_backtest_registry import filled, snapshot

FAILURE = Failure(FailureKind.TECHNICAL, "trace illisible")


def _refused(root: Path, fragment: str, append: Callable[[], object]) -> None:
    before = snapshot(root)
    with pytest.raises(RegistryError, match=re.escape(fragment)):
        append()
    assert snapshot(root) == before


def test_second_answer_is_refused(tmp_path: Path) -> None:
    """Décision 4 : une seconde réponse à une déclaration est une correction."""
    root = filled(tmp_path)
    _refused(
        root,
        "evenements.jsonl : la déclaration 1 a déjà une réponse",
        lambda: append_result(root, 1, outcomes(), recorded_at=at(2)),
    )


def test_failure_answering_a_result_is_refused(tmp_path: Path) -> None:
    """D14 : un ÉCHEC répond à une DÉCLARATION."""
    root = filled(tmp_path)
    _refused(
        root,
        "evenements.jsonl : l'événement 3 répond à l'événement 2, qui n'est pas une "
        "déclaration",
        lambda: append_failure(root, 2, FAILURE, recorded_at=at(2)),
    )


def test_failure_answering_itself_is_refused(tmp_path: Path) -> None:
    root = filled(tmp_path)
    _refused(
        root,
        "ajout refusé : answers (3) nomme une déclaration qui précède l'événement 3",
        lambda: append_failure(root, 3, FAILURE, recorded_at=at(2)),
    )


def test_failure_correcting_a_result_is_refused(tmp_path: Path) -> None:
    """Décision 4 : une correction est un événement du même type."""
    root = filled(tmp_path)
    _refused(
        root,
        "corrige l'événement 2 (result) : une correction vise un événement du même "
        "type",
        lambda: append_failure(
            root, 1, FAILURE, recorded_at=at(2), corrects=2, correction_reason="r"
        ),
    )


def test_result_correcting_the_result(tmp_path: Path) -> None:
    """Décision 4 : la correction est la réponse en vigueur ; l'événement corrigé ne
    l'est plus. Une seconde correction du même événement, ou une correction sans
    motif, est refusée."""
    root = filled(tmp_path)
    event = append_result(
        root,
        1,
        outcomes(),
        references=references(),
        recorded_at=at(2),
        corrects=2,
        correction_reason="erreur de saisie",
    )
    log = read_registry(root)
    assert event.number == 3
    assert log.answer(1) == event
    assert not log.in_force(2)
    assert log.corrected_by(2) == 3
    _refused(
        root,
        "evenements.jsonl : l'événement 2 est déjà corrigé (événement 3)",
        lambda: append_result(
            root,
            1,
            outcomes(),
            recorded_at=at(3),
            corrects=2,
            correction_reason="encore",
        ),
    )
    _refused(
        root,
        "ajout refusé : correction_reason est présent si et seulement si corrects "
        "l'est",
        lambda: append_result(root, 1, outcomes(), recorded_at=at(3), corrects=3),
    )


def test_failure_added_and_read_back(tmp_path: Path) -> None:
    """D14 : un ÉCHEC (non-évaluabilité) répond à la déclaration ; ce n'est pas un
    résultat, il n'a pas de sorties scorées."""
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    failure = Failure(FailureKind.NOT_EVALUABLE, "aucune performance évaluable")
    event = append_failure(root, 1, failure, recorded_at=at(1))
    log = read_registry(root)
    assert log.events[1] == event
    assert event.failure == failure
    assert log.answer(1) == event
    with pytest.raises(
        RegistryError, match=re.escape("l'événement 2 n'est pas un résultat")
    ):
        load_outcomes(root, log, 2)


# ---------------------------------------------------------------------------
# Correctifs de la relecture de la PR #19
# ---------------------------------------------------------------------------


def test_failure_keeps_the_given_instant(tmp_path: Path) -> None:
    """§ 6.3, étape 4 : l'instant donné à ``append_failure`` est celui de l'ÉCHEC écrit
    et relu."""
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    event = append_failure(root, 1, FAILURE, recorded_at=at(1))
    assert event.recorded_at == at(1)
    assert read_registry(root).event(2) == event


def test_result_answering_a_result_is_refused(tmp_path: Path) -> None:
    """§ 6.3, étapes 5 et 6 : le journal augmenté se contrôle avant l'accord ; un
    RÉSULTAT qui répond à un résultat est une ``RegistryError``, pas une erreur
    interne."""
    root = filled(tmp_path)
    _refused(
        root,
        "evenements.jsonl : l'événement 3 répond à l'événement 2, qui n'est pas une "
        "déclaration",
        lambda: append_result(root, 2, outcomes(), recorded_at=at(2)),
    )


def test_answer_out_of_bounds_is_none(tmp_path: Path) -> None:
    """Point soumis 6 du plan : ``answer(n)`` rend ``None`` pour un numéro sans réponse
    en vigueur, hors bornes compris."""
    log = read_registry(filled(tmp_path))
    assert log.answer(0) is None
    assert log.answer(3) is None
