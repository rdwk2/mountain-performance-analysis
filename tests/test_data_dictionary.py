"""Le dictionnaire de données commité est exactement celui que produit le code."""

import dataclasses
from enum import Enum
from pathlib import Path
from typing import Any

import pytest

from mountain_perf.schemas._dictionary import (
    DOCUMENTED_TYPES,
    ENUM_DESCRIPTIONS,
    RUBRICS,
    render,
    rubric_headings,
)

DICTIONARY = Path(__file__).resolve().parent.parent / "docs" / "DICTIONNAIRE_DONNEES.md"


def test_committed_dictionary_is_up_to_date() -> None:
    # Comparaison ligne à ligne : insensible à un éventuel CRLF de la copie de travail.
    committed = DICTIONARY.read_text(encoding="utf-8").splitlines()
    assert committed == render().splitlines(), (
        "docs/DICTIONNAIRE_DONNEES.md est périmé : lancer `just dictionary`."
    )


def test_render_is_deterministic_and_lf_only() -> None:
    text = render()
    assert text == render()
    assert "\r" not in text


@pytest.mark.parametrize("cls", DOCUMENTED_TYPES, ids=lambda cls: cls.__name__)
def test_every_type_documents_the_five_rubrics_in_order(cls: type) -> None:
    assert rubric_headings(cls) == RUBRICS


@pytest.mark.parametrize("cls", DOCUMENTED_TYPES, ids=lambda cls: cls.__name__)
def test_every_type_is_a_frozen_dataclass_or_a_described_enum(cls: type) -> None:
    if issubclass(cls, Enum):
        assert cls in ENUM_DESCRIPTIONS
    else:
        assert dataclasses.is_dataclass(cls)
        params: Any = vars(cls)["__dataclass_params__"]
        assert params.frozen


def test_annotations_are_rendered_from_source_strings() -> None:
    assert "| `distance_m` | `Sequence[float]` |" in render()
    assert "| `quality_flags` | `frozenset[QualityFlag]` | `frozenset()` |" in render()
