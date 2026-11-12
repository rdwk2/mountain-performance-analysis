"""Garanties d'OG-1b que la suite ne tenait pas (balayage mutmut de la PR #43) : la
lecture du compagnon depuis ses octets ramène le ``"\\r"`` seul à ``"\\n"`` comme le
faisait la lecture en texte, et refuse un ``generated_at`` à ``null`` sans instant à
part par le message d'aujourd'hui (§ 6.3 du brief, étape 2 et table, ligne 1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mountain_perf.model.curve_io import (
    CURVE_PARAMETER_SPECS,
    CurveError,
    read_curve_documents,
)
from mountain_perf.schemas import ParameterSet

FIXTURES = Path(__file__).resolve().parent / "fixtures"
P = ParameterSet(CURVE_PARAMETER_SPECS)


def _documents() -> tuple[bytes, dict[str, Any]]:
    csv = (FIXTURES / "courbe_synthetique.csv").read_bytes()
    meta = json.loads(
        (FIXTURES / "courbe_synthetique.meta.json").read_text(encoding="utf-8")
    )
    return csv, meta


def test_un_compagnon_a_retours_chariot_seuls_se_lit_comme_en_texte(
    tmp_path: Path,
) -> None:
    """Fins de ligne ``"\\r"`` seules, JSON cassé après le premier retour : la position
    citée par « JSON illisible » est celle d'une lecture en texte du même fichier."""
    csv, meta = _documents()
    text = json.dumps(meta, indent=2).replace("\n", "\r")
    broken = text.replace('"sport"', '"sport" "x"', 1)
    (tmp_path / "k.meta.json").write_bytes(broken.encode("utf-8"))
    with pytest.raises(json.JSONDecodeError) as reference:
        json.loads((tmp_path / "k.meta.json").read_text(encoding="utf-8"))
    with pytest.raises(CurveError) as error:
        read_curve_documents(csv, broken.encode("utf-8"), "k.csv", P)
    assert str(error.value) == f"k.meta.json : JSON illisible ({reference.value})."


def test_generated_at_null_sans_instant_le_refus_d_aujourd_hui() -> None:
    """Clé ``generated_at`` à ``null``, pas d'instant à part : le message
    d'aujourd'hui."""
    csv, meta = _documents()
    meta["generated_at"] = None
    with pytest.raises(CurveError) as error:
        read_curve_documents(csv, json.dumps(meta).encode("utf-8"), "k.csv", P)
    assert str(error.value) == (
        "k.meta.json : champ « generated_at » attendu comme texte non vide, reçu None."
    )
