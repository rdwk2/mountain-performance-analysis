"""Garanties d'OG-1b que la suite ne tenait pas (relecture C de la PR #43, C-1 et C-3 à
C-10) : la provenance d'un compagnon à plusieurs retenues (``activity_count``,
``date_from``, ``date_to``), la pureté d'``origin_companion`` contre l'horloge de la
commande et l'ordre de ses contrôles, ``CurveDocuments`` gelé, l'ordre des écritures et
des refus de ``write_curve``, l'ordre de lecture de ``read_curve_documents`` (le support
du CSV avant le compagnon, ``generated_at`` à sa place) et le ``"\r"`` seul. Valeurs en
dur ; ``_season()`` : ``s0`` à ``s7`` partis du 20 au 27 mars 2024, à 08:00 UTC
(inventés, règle 1)."""

from __future__ import annotations

import dataclasses
import json
import math
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from fixtures.processed import COMMIT
from mountain_perf import cli
from mountain_perf.estimation.origin import origin_companion
from mountain_perf.model.curve_io import (
    CURVE_PARAMETER_SPECS,
    CurveError,
    curve_documents,
    read_curve_documents,
    write_curve,
)
from mountain_perf.schemas import ParameterSet, Sport
from mountain_perf.validation import ContractError
from test_estimation_curve import DEFAULTS
from test_model_curve_io import CURVE, base_meta
from test_model_curve_io_extended import ESTIMATION, PROVENANCE, ROWS
from test_og1_cli_at import NOW
from test_og1_origin import PROFILE, _season, corpus, origin_selection, rule

P = ParameterSet(CURVE_PARAMETER_SPECS)


def companion_of(result: Any, season: Any) -> Any:
    return origin_companion(
        result,
        season,
        origin_selection(),
        DEFAULTS,
        PROFILE,
        commit=COMMIT,
        generated_at=NOW,
    )


def test_l_etendue_des_jours_de_depart_des_retenues() -> None:
    """C-1 : huit retenues, du 20 au 27 mars : ``date_from`` le plus ancien jour,
    ``date_to`` le plus récent."""
    season = corpus(_season())
    provenance, _ = companion_of(rule(season), season)
    assert (provenance.date_from, provenance.date_to) == (
        date(2024, 3, 20),
        date(2024, 3, 27),
    )


def test_le_nombre_d_activites_des_retenues() -> None:
    """C-1 : ``activity_count`` = le nombre de retenues (§ 6.2 (a)) : huit sur
    ``_season()``."""
    season = corpus(_season())
    provenance, _ = companion_of(rule(season), season)
    assert provenance.activity_count == 8


def test_origin_companion_ne_lit_pas_l_horloge_de_la_commande(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-3 : l'horloge de la commande vaut 2030 ; le compagnon garde l'instant donné."""
    monkeypatch.setattr(cli, "_now", lambda: datetime(2030, 1, 1, tzinfo=UTC))
    season = corpus(_season())
    provenance, _ = companion_of(rule(season), season)
    assert provenance.generated_at == NOW


def test_curve_documents_est_gele() -> None:
    """C-4 : ``@dataclass(frozen=True)`` (§ 6.2 (c))."""
    documents = curve_documents(ROWS, Sport.FOOT, PROVENANCE, ESTIMATION)
    with pytest.raises(dataclasses.FrozenInstanceError):
        documents.csv = b""  # type: ignore[misc]
    assert hash(documents) == hash(dataclasses.replace(documents))


def test_write_curve_refuse_d_abord_un_compagnon_existant(tmp_path: Path) -> None:
    """C-6 : le refus avant tout rendu, sur le second fichier aussi (K25)."""
    (tmp_path / "k.meta.json").write_bytes(b"deja")
    with pytest.raises(CurveError) as error:
        write_curve(
            tmp_path / "k.csv",
            ROWS,
            Sport.FOOT,
            PROVENANCE,
            {"level": {"p10": math.nan}},
        )
    assert str(error.value) == (
        "k.meta.json existe déjà : une courbe n'est jamais réécrite."
    )


def test_le_compagnon_s_ouvre_avant_le_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-5 : « le compagnon s'écrit avant le CSV » (``0017``, « Le fichier »)."""
    opened: list[str] = []
    original = Path.open

    def spy(self: Path, *args: Any, **kwargs: Any) -> Any:
        opened.append(self.name)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy)
    write_curve(tmp_path / "k.csv", ROWS, Sport.FOOT, PROVENANCE, ESTIMATION)
    assert opened == ["k.meta.json", "k.csv"]


def test_le_support_du_csv_avant_le_compagnon() -> None:
    """C-10 : le CSV d'abord, support compris (§ 6.3, étape 1) : un support impossible
    et pas de compagnon donnent l'erreur du support."""
    csv_bytes = (
        b"grade_pct,kmh,hr,vam_mh,time_min\n"
        b"1.25,9.0,140,112.5,30\n"
        b"3.75,8.0,145,300,30\n"
    )
    with pytest.raises(CurveError) as error:
        read_curve_documents(csv_bytes, None, "k.csv", P)
    assert str(error.value).startswith(
        "Le support doit encadrer le plat : aucune tranche de pente négative."
    )


def test_un_compagnon_a_retours_chariot_seuls() -> None:
    """C-8 : « ``"\\r\\n"``, puis ``"\\r"`` seul » (§ 6.3, étape 2) : un compagnon à
    fins de ligne ``"\\r"`` cassé à sa deuxième ligne donne le message que
    ``read_curve`` donnait de son fichier sur ``6a87b89`` (« line 2 column 3
    (char 4) »)."""
    lines = json.dumps(base_meta(), indent=2).split("\n")
    lines[1] = "  x"
    with pytest.raises(CurveError) as error:
        read_curve_documents(CURVE.read_bytes(), "\r".join(lines).encode(), "k.csv", P)
    assert str(error.value) == (
        "k.meta.json : JSON illisible (Expecting property name enclosed in double "
        "quotes: line 2 column 3 (char 4))."
    )


def test_generated_at_a_sa_place() -> None:
    """C-7 : « ``generated_at``, à sa place d'aujourd'hui (après ``estimator``) »
    (§ 6.3, étape 3) : un compagnon sans ``activity_count`` ni ``generated_at`` dit
    d'abord ``activity_count``."""
    meta = base_meta()
    del meta["activity_count"]
    del meta["generated_at"]
    with pytest.raises(CurveError) as error:
        read_curve_documents(CURVE.read_bytes(), json.dumps(meta).encode(), "k.csv", P)
    assert str(error.value) == "k.meta.json : champ « activity_count » manquant."


def test_l_absence_avant_l_athlete() -> None:
    """C-9 : l'ordre des contrôles d'``origin_companion`` (§ 6.2 (b), 1 puis 2)."""
    result = rule(corpus(_season()), origin=datetime(2024, 3, 19, 23, tzinfo=UTC))
    with pytest.raises(ContractError) as error:
        companion_of(result, corpus(_season(), athlete="y"))
    assert str(error.value) == "result : une absence n'a pas de compagnon."


def test_le_support_error_d_une_origine_non_projetable() -> None:
    """Le document porte le message de support du résultat (§ 6.2 (b), 7)."""
    season = corpus(_season())
    result = rule(season, origin=datetime(2024, 3, 24, 23, tzinfo=UTC))
    assert result.support_error is not None
    _, document = companion_of(result, season)
    assert document["support_error"] == result.support_error
    assert document["projectable"] is False
