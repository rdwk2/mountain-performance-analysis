"""Garanties de la bibliothèque de la sensibilité (M4d-3, ``backtest/sensitivity.py``)
que les tests joints ne tenaient pas — correctifs de la relecture de la PR #32
(relecture C en deux passes).

- Ses imports (§ 6.0 du brief), lus sur l'arbre syntaxique : du projet, le package
  ``mountain_perf.schemas`` et cinq noms de ``mountain_perf.schemas.sensitivity``, aucun
  module de ``backtest/`` ; hors du projet, ``__future__``, ``collections.abc``,
  ``dataclasses``, ``datetime``, ``enum`` au plus ; ni ``open``.
- ``Side`` et ``SensitivityQualification`` : des dataclasses gelées (§ 6.2).
- ``SensitivityStatus`` : ses membres, leurs valeurs, leur ordre (§ 6.2).
"""

import ast
import dataclasses
from pathlib import Path

import pytest

from mountain_perf.backtest import (
    SensitivityQualification,
    SensitivityStatus,
    Side,
)
from mountain_perf.backtest import sensitivity as library

ALLOWED = {
    "__future__",
    "collections.abc",
    "dataclasses",
    "datetime",
    "enum",
    "mountain_perf.schemas",
    "mountain_perf.schemas.sensitivity",
}
"""Les modules que la bibliothèque peut importer (§ 6.0 du brief)."""
FROM_CONTRACTS = {
    "DOCUMENT_RESERVES",
    "METRIC_COMPONENTS",
    "common_set",
    "guards_lost",
    "sign_class",
}
"""Les noms qu'elle importe de ``mountain_perf.schemas.sensitivity``."""


def test_library_imports_what_the_brief_allows() -> None:
    """§ 6.0 du brief : la bibliothèque importe le package ``mountain_perf.schemas`` et
    cinq noms des contrats de la sensibilité, aucun module de ``backtest/`` ; hors du
    projet, ``__future__``, ``collections.abc``, ``dataclasses``, ``datetime``, ``enum``
    au plus. Fonctions pures, sans lecture ni écriture : ni ``open``."""
    tree = ast.parse(Path(library.__file__).read_text(encoding="utf-8"))
    modules: set[str] = set()
    contracts: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            assert node.module is not None
            modules.add(node.module)
            if node.module == "mountain_perf.schemas.sensitivity":
                contracts |= {alias.name for alias in node.names}
    assert modules <= ALLOWED
    assert {"mountain_perf.schemas", "mountain_perf.schemas.sensitivity"} <= modules
    assert contracts == FROM_CONTRACTS
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not names & {"open", "__import__", "exec", "eval"}


FROZEN: list[type] = [Side, SensitivityQualification]


@pytest.mark.parametrize("cls", FROZEN, ids=[cls.__name__ for cls in FROZEN])
def test_library_objects_are_frozen(cls: type) -> None:
    """§ 6.2 du brief : ``Side`` et ``SensitivityQualification`` sont des dataclasses
    gelées."""
    instance: object = object.__new__(cls)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, dataclasses.fields(cls)[0].name, None)


def test_sensitivity_status_members() -> None:
    """§ 6.2 du brief : ``SensitivityStatus``, dans cet ordre — ``REMAINING``,
    ``INCOMPLETE``, ``RESERVED``, ``DONE`` —, et leurs valeurs."""
    assert [(m.name, m.value) for m in SensitivityStatus] == [
        ("REMAINING", "central_sensitivity_remaining"),
        ("INCOMPLETE", "sensitivity_incomplete"),
        ("RESERVED", "sensitivity_reserved"),
        ("DONE", "sensitivity_done"),
    ]
