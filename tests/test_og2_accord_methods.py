"""La condition 3 bis de l'accord du format 6 (OG-2, choix C8 et C33), méthode par
méthode (constat C-2 de la relecture C du bloc 1) : une ligne du compagnon figé
réécrite à une autre méthode, cohérente partout sauf sur le contrôle visé, est
refusée. Le monde de ``test_og2_accord.py`` n'écrit que des lignes « fin inférée » :
ces contrôles n'y sont jamais pris en défaut."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import test_og2_accord as t
from mountain_perf.schemas import CalibrationTerm

Line = dict[str, Any]


def _rewrite(
    change: Callable[[Line, dict[str, Any]], None], decision: str
) -> t.Mutation:
    """Réécrit, dans le compagnon de Q20 (``k == 0``), la **première** ligne de décision
    ``decision`` par ``change(ligne, compagnon)``."""

    def mutate(k: int, document: dict[str, Any]) -> None:
        if k != 0:
            return
        lines = document["estimation"]["origin"]["activities"]
        line = next(x for x in lines if x["decision"] == decision)
        change(line, document)

    return mutate


AFTER = "finie à l'origine ou après"
CANDIDATE = "candidate"


def _indexed(document: dict[str, Any]) -> None:
    """L'historique, qui ne se vérifie pas, assez grand pour une ligne indexée de
    plus."""
    document["estimation"]["origin"]["history"]["selected_index_finished"] = 14


def _index_alone_without_index_end(line: Line, document: dict[str, Any]) -> None:
    line.update(
        decision="fin inconnue",
        method="index seul",
        index_end=None,
        recording_end=None,
        safe_end=None,
    )


def _index_alone_with_ends(line: Line, document: dict[str, Any]) -> None:
    line.update(
        method="index seul",
        index_end=line["recording_end"],
        recording_start=None,
        recording_sha256=None,
    )


def _index_alone_unread_with_start(line: Line, document: dict[str, Any]) -> None:
    line.update(
        method="index seul",
        index_end=line["recording_end"],
        recording_end=None,
        safe_end=None,
        recording_sha256=None,
    )


def _index_alone_undecided(line: Line, document: dict[str, Any]) -> None:
    line.update(
        method="index seul",
        index_end=line["safe_end"],
        recording_start=None,
        recording_end=None,
        safe_end=None,
        recording_sha256=None,
    )
    _indexed(document)


def _index_alone_read_without_start(line: Line, document: dict[str, Any]) -> None:
    line.update(
        method="index seul",
        index_end=line["safe_end"],
        recording_start=None,
        recording_end=None,
        safe_end=None,
    )
    _indexed(document)


def _index_alone_read_but_decided(line: Line, document: dict[str, Any]) -> None:
    line.update(
        method="index seul",
        index_end=line["recording_end"],
        recording_end=None,
        safe_end=None,
    )


def _both_without_digest(line: Line, document: dict[str, Any]) -> None:
    line.update(
        method="index et enregistrement",
        index_end=line["safe_end"],
        recording_sha256=None,
    )
    _indexed(document)


def _both_safe_end_not_latest(line: Line, document: dict[str, Any]) -> None:
    end = line["safe_end"]
    earlier = end.replace("09:00:00", "08:50:00")
    assert earlier != end
    line.update(method="index et enregistrement", index_end=earlier, safe_end=earlier)
    _indexed(document)


def _both_decided_by_index(line: Line, document: dict[str, Any]) -> None:
    line.update(method="index et enregistrement", index_end=line["recording_end"])


def _inferred_with_index_end(line: Line, document: dict[str, Any]) -> None:
    line.update(index_end=line["recording_end"])


def _unknown_end_with_ends(line: Line, document: dict[str, Any]) -> None:
    line.update(decision="fin inconnue", method="fin inconnue")


def _unknown_method(line: Line, document: dict[str, Any]) -> None:
    line.update(decision="fin inconnue", method="fin devinée")


CASES = [
    ("26a", _index_alone_without_index_end, AFTER),
    ("26b", _index_alone_with_ends, AFTER),
    ("26c", _index_alone_unread_with_start, AFTER),
    ("26d", _index_alone_undecided, "candidate"),
    ("26e", _index_alone_read_without_start, "candidate"),
    ("26f", _index_alone_read_but_decided, AFTER),
    ("26g", _both_without_digest, "candidate"),
    ("26h", _both_safe_end_not_latest, "candidate"),
    ("26i", _both_decided_by_index, AFTER),
    ("26j", _inferred_with_index_end, AFTER),
    ("26l", _unknown_end_with_ends, AFTER),
    ("26m", _unknown_method, AFTER),
]


@pytest.mark.parametrize(
    ("case", "change", "decision"), CASES, ids=[case[0] for case in CASES]
)
def test_a_line_of_another_method_is_refused(
    tmp_path: Path,
    case: str,
    change: Callable[[Line, dict[str, Any]], None],
    decision: str,
) -> None:
    t.refused(tmp_path, t.world(_rewrite(change, decision)), "condition 3 bis")


def test_terms_saying_another_status_are_refused(tmp_path: Path) -> None:
    """Condition 7 : le calage est « erreur du modèle » (un ``P_c`` absent), ses termes
    portent tous un ``P_c``."""

    def fill(document: Any) -> Any:
        sets = tuple(
            dataclasses.replace(
                item,
                terms=tuple(
                    CalibrationTerm(term.civil_date, term.observed_s, term.observed_s)
                    if term.forecast_s is None
                    else term
                    for term in item.terms
                ),
            )
            for item in document.sets
        )
        assert sets != document.sets
        return dataclasses.replace(document, sets=sets)

    t.refused(tmp_path, t.world(), "condition 7", broken=True, terms_change=fill)


def test_a_malformed_companion_is_a_registry_error(tmp_path: Path) -> None:
    """Un compagnon figé sans ``history`` : ``RegistryError`` (« mal formé »), pas une
    ``KeyError``."""

    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 0:
            del document["estimation"]["origin"]["history"]

    t.refused(tmp_path, t.world(mutate), "document de courbe mal formé")
