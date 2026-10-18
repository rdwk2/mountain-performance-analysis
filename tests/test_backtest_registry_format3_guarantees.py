"""Garanties du registre au format 3 (M4c-3, ``backtest/registry.py``) que les tests
joints ne tenaient pas — correctifs de la relecture de la PR #25 (relecture C).

- ``_agree`` et ``_agree_documents`` : les contrôles de M4c-3, dans l'ordre (§ 6.3) ;
- ``_upgraded`` : une ligne du format 2 qui porte ``reference_documents``, même
  ``null``, est refusée par le message prescrit ;
- E6 : le RÉSULTAT publie les documents D8 figés, chacun à son empreinte figée ; un
  document de plus, d'un parcours que l'expérience ne fige pas, n'est pas refusé ;
- des formes qu'un registre réel peut produire, suivies d'une exécution de
  ``just backtest`` au format 3.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from fixtures.registry import (
    CALIBRATED_MODELS,
    at,
    declaration,
    references,
    registry_root,
)
from mountain_perf.backtest import (
    EVENTS_FILE,
    RegistryError,
    append_declaration,
    append_failure,
    append_result,
    count_trials,
    read_registry,
    verify_registry,
)
from mountain_perf.schemas import (
    ExperimentMetric,
    Failure,
    FailureKind,
    ModelKind,
    RepeatabilityRecord,
)
from test_backtest_registry_format2 import _outcomes, _registry, _to_format
from test_backtest_registry_format3 import (
    _admission,
    _experiment_declaration,
    _experiment_outcomes,
    _journal,
)

AGREEMENT = "un RÉSULTAT cite un document d'admission si et seulement si"


def test_agree_admission_iff_experiment_before_pre_format_3(tmp_path: Path) -> None:
    """``_agree``, dans l'ordre : « admission si et seulement si expérience » avant
    « une expérience déclarée avant le format 3 » — un RÉSULTAT sans admission à une
    expérience du format 2."""
    root = registry_root(tmp_path)
    append_declaration(root, _experiment_declaration(), recorded_at=at(0))

    def at_format_2(data: dict[str, Any]) -> None:
        data["format_version"] = 2
        data["declaration"]["experiment"].pop("reference_documents")
        data["declaration"].pop("sensitivity")

    _journal(root, at_format_2)
    with pytest.raises(RegistryError, match=re.escape(AGREEMENT)):
        append_result(
            root, 1, _experiment_outcomes(), references=references(), recorded_at=at(1)
        )


def test_agree_admission_iff_experiment_before_e6(tmp_path: Path) -> None:
    """``_agree``, dans l'ordre : « admission si et seulement si expérience » avant E6 —
    un RÉSULTAT sans admission à une expérience qui fige un autre document D8."""
    root = registry_root(tmp_path)
    frozen = (RepeatabilityRecord("r1", "d" * 64),)
    append_declaration(
        root, _experiment_declaration(reference_documents=frozen), recorded_at=at(0)
    )
    with pytest.raises(RegistryError, match=re.escape(AGREEMENT)):
        append_result(
            root, 1, _experiment_outcomes(), references=references(), recorded_at=at(1)
        )


def test_agree_documents_admission_before_missing_d8(tmp_path: Path) -> None:
    """``_agree_documents``, dans l'ordre : le décodage de l'admission (cible, horloge)
    avant « chaque parcours de répétabilité a sa référence D8 »."""
    root = registry_root(tmp_path)
    append_declaration(
        root,
        _experiment_declaration(frozen_references=(), reference_documents=()),
        recorded_at=at(0),
    )
    with pytest.raises(
        RegistryError, match=re.escape("l'admission porte une autre cible")
    ):
        append_result(
            root,
            1,
            _experiment_outcomes(),
            references=(),
            admission=_admission(target=ExperimentMetric.ASCENT_LEVEL),
            recorded_at=at(1),
        )
    assert len(read_registry(root).events) == 1


def test_format_2_experiment_carrying_null_reference_documents(tmp_path: Path) -> None:
    """Précision de D14 (M4c-3), § 6.3 : une ligne d'un format antérieur au 3 qui porte
    ``reference_documents``, **même** ``null``, est refusée par le message prescrit, pas
    par « écriture non canonique »."""
    root = registry_root(tmp_path)
    append_declaration(root, _experiment_declaration(), recorded_at=at(0))

    def at_format_2_null(data: dict[str, Any]) -> None:
        data["format_version"] = 2
        data["declaration"]["experiment"]["reference_documents"] = None
        data["declaration"].pop("sensitivity")

    _journal(root, at_format_2_null)
    with pytest.raises(
        RegistryError,
        match=re.escape(
            "evenements.jsonl, ligne 1 : experiment : champ inconnu au format 2 : "
            "'reference_documents'"
        ),
    ):
        read_registry(root)


def test_a_published_d8_document_beyond_the_frozen_ones(tmp_path: Path) -> None:
    """E6, précision de D10.1 : le RÉSULTAT publie les documents D8 figés, chacun à son
    empreinte figée ; une expérience qui n'en fige aucun (sans référence figée) reçoit
    un RÉSULTAT qui publie celui de ``r1``, que le jeu de répétabilité exige."""
    root = registry_root(tmp_path)
    append_declaration(
        root,
        _experiment_declaration(frozen_references=(), reference_documents=()),
        recorded_at=at(0),
    )
    append_result(
        root,
        1,
        _experiment_outcomes(),
        references=references(),
        admission=_admission(),
        recorded_at=at(1),
    )
    result = verify_registry(root).events[1].result
    assert result is not None
    assert [record.route_id for record in result.references] == ["r1"]


def test_real_shapes_then_a_format_3_backtest(tmp_path: Path) -> None:
    """Des formes qu'un registre réel peut produire — une DÉCLARATION sans réponse, un
    ÉCHEC entre deux exécutions, au format 2 —, puis une exécution de ``just backtest``
    au format courant (3 ; 4 depuis M4d-2 — DÉCLARATION et RÉSULTAT sans expérience) :
    le journal entier se vérifie, les lignes anciennes restent à l'octet."""
    v0_raw, v0_recalibrated, _ = CALIBRATED_MODELS
    models = (v0_raw, v0_recalibrated)
    root = _registry(
        tmp_path, models=models, outcomes_=_outcomes(ModelKind.V0_RECALIBRATED)
    )
    append_declaration(root, declaration(models=models), recorded_at=at(2))
    append_declaration(root, declaration(models=models), recorded_at=at(3))
    append_failure(
        root, 4, Failure(FailureKind.TECHNICAL, "OSError : disque"), recorded_at=at(4)
    )
    _to_format(root, 2)
    before = (root / EVENTS_FILE).read_bytes()
    append_declaration(root, declaration(models=models), recorded_at=at(5))
    append_result(
        root,
        6,
        _outcomes(ModelKind.V0_RECALIBRATED),
        references=references(),
        recorded_at=at(6),
    )
    log = verify_registry(root)
    assert [e.format_version for e in log.events] == [2, 2, 2, 2, 2, 5, 5]
    after = (root / EVENTS_FILE).read_bytes()
    assert after.startswith(before)
    lines = after.split(b"\n")
    assert b'"admission":null' in lines[-2]
    assert b'"experiment":null' in lines[-3]
    assert count_trials(log).declarations == 4
