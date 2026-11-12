"""La courbe figée et la courbe absente (OG-2, § 6.4, C2, C3), à leurs bornes
(relecture C du bloc 1, mutation 6)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import test_og2_accord as t
from mountain_perf.estimation.origin import origin_absence_document
from mountain_perf.model.curve_io import freeze_companion, read_curve_documents
from mountain_perf.schemas import SourceRef
from test_og1_cli_at import NOW
from test_og1_origin import _season, corpus, rule
from test_og2_documents import NAME, READ, _documents


def test_null_keys_are_carried_and_removed() -> None:
    """Piège 8 : une clé à ``null`` compte comme portée ; le compagnon figé est celui
    d'un compagnon aux clés pleines, octet pour octet."""
    _, companion = _documents()
    reference = freeze_companion(companion)
    for change in ("generated_at", "commit"):
        document = json.loads(companion)
        if change == "generated_at":
            document["generated_at"] = None
        else:
            document["estimation"]["commit"] = None
        text = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        )
        assert freeze_companion(text) == reference


def _same_instant(value: Any) -> Any:
    """``value`` (une lecture de courbe), l'instant de lecture de ses sources
    (``retrieved_at``, l'horloge de la machine à la lecture) fixé : seul champ qui
    diffère légitimement entre deux lectures."""
    if isinstance(value, SourceRef):
        return dataclasses.replace(value, retrieved_at=NOW)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        changes = {
            f.name: _same_instant(getattr(value, f.name))
            for f in dataclasses.fields(value)
        }
        return dataclasses.replace(value, **changes)
    if isinstance(value, tuple):
        return tuple(_same_instant(item) for item in value)
    return value


def test_the_frozen_read_equals_the_plain_read_field_by_field() -> None:
    """Hors ``retrieved_at`` (l'instant de chaque lecture), champ par champ."""
    csv, companion = _documents()
    plain = _same_instant(read_curve_documents(csv, companion, NAME, READ))
    frozen = _same_instant(
        read_curve_documents(
            csv, freeze_companion(companion), NAME, READ, generated_at=NOW
        )
    )
    for field in dataclasses.fields(plain):
        assert getattr(frozen, field.name) == getattr(plain, field.name), field.name


def test_the_absence_document_has_the_keys_of_c3_only() -> None:
    season = corpus(_season())
    document = json.loads(origin_absence_document(rule(season, window=1), season))
    assert list(document) == [
        "athlete_ref",
        "outcome",
        "absence_reason",
        "support_threshold_min",
        "origin",
    ]
    assert list(document["origin"]) == [
        "origin",
        "window",
        "lower_bound",
        "outcome",
        "index_sha256",
        "data_available_at",
        "last_retained_end",
        "history",
        "activities",
    ]


def test_a_decision_changed_in_an_absence_is_refused(tmp_path: Path) -> None:
    """C3 : l'accord vérifie les décisions d'un document d'absence comme pour une
    courbe ; une ligne « finie avant la fenêtre » réécrite « finie à l'origine ou
    après »."""

    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 2:
            lines = document["origin"]["activities"]
            line = next(x for x in lines if x["decision"] == "finie avant la fenêtre")
            line["decision"] = "finie à l'origine ou après"

    t.refused(tmp_path, t.world(mutate), "condition 3 bis")
