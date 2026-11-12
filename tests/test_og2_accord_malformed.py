"""L'accord du format 6 devant des documents mal formés et des instants sans fuseau
(OG-2, correctifs de la PR #44 ; C-4 et C-5 de la relecture C du bloc 1) : tout refus
est une ``RegistryError`` qui dit pourquoi, et le verdict ne dépend pas du fuseau de
la machine qui relit."""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

import test_og2_accord as t
from fixtures.registry import COMMIT
from mountain_perf.backtest import encode_document
from mountain_perf.backtest import registry as registry_module
from mountain_perf.backtest.registry import RegistryError, verify_registry
from mountain_perf.model.curve_io import CurveError
from mountain_perf.schemas import AbsentCurve, FrozenCurve, RollingDeclaration

PARIS = ZoneInfo("Europe/Paris")
INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")


# --- Les instants (C-4) ---------------------------------------------------------------


def test_an_instant_without_time_zone_is_refused() -> None:
    """Un instant naïf serait lu à l'heure de la machine qui relit (``astimezone``) :
    refusé, quelle que soit la machine."""
    with pytest.raises(
        RegistryError, match="instant sans fuseau '2026-05-12T22:00:00'"
    ):
        registry_module._moment("2026-05-12T22:00:00", "")


@pytest.mark.parametrize(
    "text", ["2026-05-12T20:00:00+00:00", "2026-05-12T22:00:00+02:00"]
)
def test_an_instant_with_time_zone_is_read_in_utc(text: str) -> None:
    assert registry_module._moment(text, "") == datetime(2026, 5, 12, 20, tzinfo=UTC)
    moment = registry_module._moment(text, "")
    assert moment is not None
    assert moment.utcoffset() == timedelta(0)
    assert moment.tzinfo is UTC or moment.tzinfo == UTC


def _paris_wall_clock(value: Any) -> Any:
    """Les instants UTC d'une section réécrits à l'heure de Paris, sans fuseau."""
    if isinstance(value, str) and INSTANT.match(value):
        moment = datetime.fromisoformat(value).astimezone(PARIS)
        return moment.replace(tzinfo=None).isoformat()
    if isinstance(value, dict):
        return {k: _paris_wall_clock(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_paris_wall_clock(v) for v in value]
    return value


def test_a_companion_without_time_zones_is_refused(tmp_path: Path) -> None:
    """La section ``origin`` du compagnon de Q20 réécrite à l'heure de Paris sans
    fuseau : sur la tête de la PR, acceptée sur une machine à l'heure de Paris et
    refusée ailleurs ; refusée partout désormais."""

    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 0:
            section = document["estimation"]["origin"]
            document["estimation"]["origin"] = _paris_wall_clock(section)
            assert "+00:00" not in json.dumps(document["estimation"]["origin"])

    with pytest.raises(RegistryError, match="instant sans fuseau"):
        verify_registry(t.append_all(tmp_path, t.world(mutate)))


# --- Les documents mal formés (C-5) ---------------------------------------------------


def test_a_named_refusal_is_not_called_malformed(tmp_path: Path) -> None:
    """Le refus « mal formé » ne recouvre pas les refus nommés que lève la lecture d'un
    document bien formé : un compagnon figé qui porte un commit est refusé par la
    condition 1, avec son propre message."""

    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 0:
            document["estimation"]["commit"] = COMMIT

    with pytest.raises(RegistryError) as error:
        t.append_all(tmp_path, t.world(mutate))
    assert "condition 1" in str(error.value)
    assert "mal formé" not in str(error.value)


def _stored(built: Any) -> dict[str, bytes]:
    stored = {t._sha(t.rule()): encode_document(t.rule(), 6)}
    for curve in built.curves:
        stored[t._sha(curve)] = encode_document(curve, 6)
    return stored


def _agree(built: Any, declaration: Any) -> None:
    rolling = declaration.rolling
    assert isinstance(rolling, RollingDeclaration)
    registry_module._agree_rolling_documents(
        declaration, rolling, _stored(built).__getitem__, "", "", 6
    )


def test_an_absence_document_that_is_not_json_is_refused() -> None:
    built = t.world()
    absent = AbsentCurve("pas du JSON")
    entry = dataclasses.replace(built.entries[2], document=t._sha(absent))
    built = dataclasses.replace(
        built, curves=[*built.curves[:2], absent], entries=[*built.entries[:2], entry]
    )
    with pytest.raises(RegistryError, match=r"mal formé.*condition 1") as error:
        _agree(built, t.rolling_declaration(built))
    assert isinstance(error.value.__cause__, json.JSONDecodeError)


def test_a_frozen_csv_that_is_not_a_curve_is_refused() -> None:
    built = t.world()
    frozen = built.curves[0]
    assert isinstance(frozen, FrozenCurve)
    broken = FrozenCurve("ceci n'est pas une courbe\n", frozen.companion)
    entry = dataclasses.replace(
        built.entries[0],
        document=t._sha(broken),
        curve_sha256=broken.csv_sha256,
        curve_ref=f"og2.csv#{broken.csv_sha256[:12]}",
    )
    built = dataclasses.replace(
        built, curves=[broken, *built.curves[1:]], entries=[entry, *built.entries[1:]]
    )
    with pytest.raises(RegistryError, match=r"mal formé.*condition 1") as error:
        _agree(built, t.rolling_declaration(built))
    assert isinstance(error.value.__cause__, CurveError)


def test_a_rolling_declaration_without_v0_raw_is_refused() -> None:
    """Le contrat admet une DÉCLARATION glissante sans v0 brut (des modèles non vides,
    distincts) ; l'accord la refuse en le disant : le seuil de lecture relit le support
    sous v0 brut."""
    built = t.world()
    declaration = dataclasses.replace(
        t.rolling_declaration(built), models=(t.COMPARATOR,)
    )
    with pytest.raises(RegistryError, match="ne déclare pas v0 brut"):
        _agree(built, declaration)
