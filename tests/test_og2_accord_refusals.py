"""Garanties de l'accord du format 6 (OG-2, E6) que la suite de la PR #44 ne tenait
pas : chaque refus nommé de l'accord tenu par un cas, vert sur un registre juste et
rouge si le refus est neutralisé (relecture C du bloc 1, mutation 2). Le monde est
celui de ``test_og2_accord.py``."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

import test_og2_accord as t
from fixtures.registry import COMMIT
from mountain_perf.backtest import encode_document
from mountain_perf.backtest import registry as registry_module
from mountain_perf.backtest.registry import RegistryError
from mountain_perf.schemas import (
    CurveStatus,
    FrozenCurve,
    Scenario,
    ShareUnavailability,
)


def _line(document: dict[str, Any], decision: str) -> dict[str, Any]:
    lines = document["estimation"]["origin"]["activities"]
    found: dict[str, Any] = next(x for x in lines if x["decision"] == decision)
    return found


def test_rule_of_another_commit_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Condition R : le document de règle porte un autre commit que la DÉCLARATION."""
    other = dataclasses.replace(t.rule(), commit="f" * 40)
    monkeypatch.setattr(t, "rule", lambda: other)
    t.refused(tmp_path, t.world(), "condition R")


def test_rule_of_another_window_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Condition R : le document de règle porte une autre fenêtre (28) que la
    DÉCLARATION (7)."""
    other = dataclasses.replace(t.rule(), window_days=28)
    monkeypatch.setattr(t, "rule", lambda: other)
    t.refused(tmp_path, t.world(), "condition R")


def test_frozen_companion_with_a_commit_is_refused(tmp_path: Path) -> None:
    """Condition 1 : le compagnon figé porte ``estimation.commit``."""

    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 0:
            document["estimation"]["commit"] = COMMIT

    t.refused(tmp_path, t.world(mutate), "condition 1")


def test_frozen_csv_other_than_declared_is_refused(tmp_path: Path) -> None:
    """Condition 1 : le CSV figé publié n'est pas celui dont la DÉCLARATION fixe
    l'empreinte (``curve_sha256``) ; le document de courbe, lui, est bien celui qu'elle
    nomme (``document``). Un chiffre d'une allure changé : mêmes tranches, même
    support."""
    built = t.world()
    frozen = built.curves[0]
    assert isinstance(frozen, FrozenCurve)
    changed = FrozenCurve(
        frozen.csv.replace("2.048198994060693", "2.048198994060694", 1),
        frozen.companion,
    )
    assert changed.csv != frozen.csv
    entry = dataclasses.replace(built.entries[0], document=t._sha(changed))
    lying = dataclasses.replace(
        built,
        curves=[changed, *built.curves[1:]],
        entries=[entry, *built.entries[1:]],
    )
    t.refused(tmp_path, lying, "condition 1")


def test_another_window_in_the_companion_is_refused(tmp_path: Path) -> None:
    """Condition 2 : la section ``origin`` du compagnon dit ``window`` 28 sous une
    DÉCLARATION de 7 jours ; la borne basse écrite reste celle de 7 jours."""

    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 0:
            document["estimation"]["origin"]["window"] = 28

    t.refused(tmp_path, t.world(mutate), "l'origine ou la fenêtre du document")


def test_a_non_candidate_with_a_fate_is_refused(tmp_path: Path) -> None:
    """Condition 3 : une ligne « finie à l'origine ou après » marquée « retenue » (sans
    contribuer)."""

    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 0:
            _line(document, "finie à l'origine ou après")["fate"] = "retenue"

    t.refused(tmp_path, t.world(mutate), "une non-candidate n'a pas de sort")


def test_another_data_available_at_is_refused(tmp_path: Path) -> None:
    """Condition 3 : ``data_available_at`` d'une seconde plus tard."""

    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 0:
            section = document["estimation"]["origin"]
            assert section["data_available_at"] == "2026-05-12T09:00:00+00:00"
            section["data_available_at"] = "2026-05-12T09:00:01+00:00"

    t.refused(tmp_path, t.world(mutate), "data_available_at ou last_retained_end")


@pytest.mark.parametrize("place", ["candidates", "retained", "activity_count"])
def test_another_count_is_refused(tmp_path: Path, place: str) -> None:
    """Condition 3 ter : un compte de plus que les lignes."""

    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 0:
            if place == "activity_count":
                document["activity_count"] += 1
            else:
                document["estimation"]["counts"][place] += 1

    t.refused(tmp_path, t.world(mutate), "condition 3 ter")


@pytest.mark.parametrize("place", ["projectable", "bins"])
def test_another_verdict_is_refused(tmp_path: Path, place: str) -> None:
    """Condition 5 bis : le compagnon se dit non projetable (ou perd une tranche) alors
    que son CSV a un support au seuil des diagnostics."""

    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 0:
            estimation = document["estimation"]
            if place == "projectable":
                estimation["projectable"] = False
                estimation["support_error"] = "support impossible"
            else:
                estimation["bins"] = estimation["bins"][:-1]

    t.refused(tmp_path, t.world(mutate), "condition 5 bis")


def test_no_read_support_with_a_readable_csv_is_refused() -> None:
    """Condition 5 bis, la lecture : le statut ``no_read_support`` sur une courbe que
    le seuil de lecture (10 min) relit. Appelé sur l'accord des documents de la
    DÉCLARATION seuls (le RÉSULTAT n'y entre pas)."""
    built = t.world()
    lying = dataclasses.replace(
        built.entries[0],
        status=CurveStatus.NO_READ_SUPPORT,
        out_of_support_share=None,
        share_scope=None,
        share_unavailability=ShareUnavailability.NO_CURVE,
    )
    declaration = t.rolling_declaration(
        dataclasses.replace(built, entries=[lying, *built.entries[1:]])
    )
    rolling = declaration.rolling
    assert rolling is not None
    stored = {t._sha(t.rule()): encode_document(t.rule(), 6)}
    for curve in built.curves:
        stored[t._sha(curve)] = encode_document(curve, 6)
    with pytest.raises(RegistryError, match="seuil de lecture"):
        registry_module._agree_rolling_documents(
            declaration, rolling, stored.__getitem__, "", "", 6
        )


def test_terms_without_a_scenario_are_refused(tmp_path: Path) -> None:
    """Condition 7 : les termes du comparateur sans le scénario d'usage, que son calage
    porte."""

    def drop_usage(document: Any) -> Any:
        sets = tuple(s for s in document.sets if s.scenario is not Scenario.USAGE)
        assert len(sets) < len(document.sets)
        return dataclasses.replace(document, sets=sets)

    t.refused(tmp_path, t.world(), "condition 7", terms_change=drop_usage)
