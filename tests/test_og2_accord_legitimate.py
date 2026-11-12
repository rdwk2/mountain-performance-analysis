"""L'accord du format 6 (OG-2, E6) dans l'autre sens : des registres légitimes que
l'accord ne refuse pas (une condition trop stricte les refuserait), et un cas où la
condition 3 bis est seule à refuser (relecture C du bloc 1, mutation 2). Le monde est
celui de ``test_og2_accord.py``."""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

import test_og2_accord as t
from fixtures.registry import (
    P03,
    Q20,
    Q27,
    V0_RAW,
    at,
    references,
    registry_root,
    v0_of,
)
from mountain_perf.backtest import declared_performance
from mountain_perf.backtest.registry import (
    append_declaration,
    append_result,
    verify_registry,
)
from mountain_perf.schemas import (
    ArtifactRef,
    CurveStatus,
    Outing,
    Performance,
)


def _window(window: int, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, Any, Any]:
    """La DÉCLARATION, les sorties scorées et les documents glissants du monde sous
    ``window`` jours ; une performance ``curve`` non scorée reçoit des termes vides
    (non calée), comme le veut la condition 2 sans documents."""
    monkeypatch.setattr(t, "WINDOW", window)
    built = t.world()
    declaration = t.rolling_declaration(built)
    scored, documents = t.result_documents(built)
    terms = list(documents.calibration_terms)
    for k, entry in enumerate(built.entries):
        if entry.status is CurveStatus.CURVE and terms[k] is None:
            ref = built.refs[k]
            assert ref is not None
            _, empty = t._comparator(
                t.OUTINGS[k].outing_id,
                t._on_curve(v0_of(t.OUTINGS[k].outing_id), ref),
                None,
            )
            terms[k] = empty
    documents = dataclasses.replace(documents, calibration_terms=tuple(terms))
    return built, declaration, scored, documents


def test_absent_under_one_window_curve_under_another_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deux DÉCLARATIONS d'une même commande (7 et 28 jours, chacune nomme l'autre) :
    P03 sans courbe sous 7 jours, avec une courbe sous 28."""
    built7, declaration7, scored7, documents7 = _window(7, monkeypatch)
    built28, declaration28, scored28, documents28 = _window(28, monkeypatch)
    assert built7.entries[2].status is CurveStatus.ABSENT
    assert built28.entries[2].status is CurveStatus.CURVE
    root = registry_root(tmp_path)
    for number, declaration, scored, documents in (
        (1, declaration7, scored7, documents7),
        (3, declaration28, scored28, documents28),
    ):
        rolling = dataclasses.replace(declaration.rolling, command_windows=(7, 28))
        append_declaration(
            root,
            dataclasses.replace(declaration, rolling=rolling),
            recorded_at=at(number),
        )
        append_result(
            root,
            number,
            scored,
            unscored=t.UNSCORED,
            references=references(),
            rolling=documents,
            recorded_at=at(number + 1),
        )
    log = verify_registry(root)
    assert len(log.events) == 4


def test_an_outing_over_several_days_is_accepted(tmp_path: Path) -> None:
    """P03, non tracée au RÉSULTAT, déclarée sur 50 heures (trois jours civils)."""
    long = Outing(
        outing_id=P03.outing_id,
        athlete_ref=P03.athlete_ref,
        sport=P03.sport,
        start_time=P03.start_time,
        end_time=P03.start_time + timedelta(hours=50),
        traces=tuple(
            ArtifactRef(a.source, P03.start_time + timedelta(hours=50), a.role)
            for a in P03.traces
        ),
        route_id=P03.route_id,
        reference=P03.reference,
        dataset=P03.dataset,
        label=P03.label,
    )
    performances = tuple(
        declared_performance(Performance(o.start_time.date(), (o,)))
        for o in (Q20, Q27, long)
    )
    built = t.world()
    declaration = dataclasses.replace(
        t.rolling_declaration(built), performances=performances
    )
    root = registry_root(tmp_path)
    append_declaration(root, declaration, recorded_at=at(0))
    scored, documents = t.result_documents(built)
    append_result(
        root,
        1,
        scored,
        unscored=t.UNSCORED,
        references=references(),
        rolling=documents,
        recorded_at=at(1),
    )
    verify_registry(root)
    assert V0_RAW in declaration.models


def test_a_non_candidate_swapped_to_another_non_candidate_is_refused(
    tmp_path: Path,
) -> None:
    """Condition 3 bis seule : une ligne « finie à l'origine ou après » réécrite « finie
    avant la fenêtre » (deux non-candidates : aucun compte ne bouge)."""

    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 0:
            lines = document["estimation"]["origin"]["activities"]
            line = next(
                x for x in lines if x["decision"] == "finie à l'origine ou après"
            )
            line["decision"] = "finie avant la fenêtre"

    t.refused(tmp_path, t.world(mutate), "condition 3 bis")
