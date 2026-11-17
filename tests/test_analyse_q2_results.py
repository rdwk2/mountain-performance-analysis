"""Les résultats de Q2 (AN3-3b, ``docs/decisions/0023``, § 10) : ``flux.csv`` (C3,
C13, la grille, les mois vides, les périodes), les dossiers de résultats (nom,
écriture temporaire, refus) et la relecture du dernier résultat de puissance. Sur des
tables inventées."""

from __future__ import annotations

import dataclasses
import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from fixtures.processed import COMMIT
from fixtures.q2_world import at, q2_activity, q2_climb, q2_tables
from mountain_perf.analyse.athlete import Periods
from mountain_perf.analyse.q2 import results
from mountain_perf.analyse.q2.data import Q2Data, q2_data
from mountain_perf.analyse.q2.model import Measure, ModelSpec, model_spec
from mountain_perf.analyse.q2.parameters import Q2_PARAMETER_SPECS, Q2_REGIMES
from mountain_perf.analyse.q2.power import (
    PowerResult,
    RegimePower,
    alpha_grid,
    power_grids,
)
from mountain_perf.analyse.q2.results import (
    FLUX_COLUMNS,
    POWER_DIR,
    Q2ResultsError,
    flux_csv,
    flux_rows,
    latest_power,
    write_folder,
    write_power_results,
)
from mountain_perf.analyse.tables import Tables
from mountain_perf.schemas import ParameterSet
from mountain_perf.schemas.processed import ClimbRegime, ProcessedProvenance
from test_analyse_q2_data import c3_tables

LONG = ClimbRegime.LONG_CLIMB
DEFAULTS = ParameterSet(Q2_PARAMETER_SPECS)


def _specs(
    data: Q2Data, parameters: ParameterSet = DEFAULTS
) -> dict[tuple[ClimbRegime, Measure], ModelSpec]:
    return {
        (r, m): model_spec(data.days[r], m, r, parameters)
        for r in Q2_REGIMES
        for m in Measure
    }


def _flux(tables: Tables, periods: Periods | None = None) -> str:
    data = q2_data(tables, periods, DEFAULTS)
    return flux_csv(data, _specs(data))


# --- C3 -----------------------------------------------------------------------------

C3_FLUX = """\
regime,mesure,periode,mois,etape,motif,journees,montees,valeur
long_climb,commun,toutes,2025-04,1,appareil_non_principal,1,1,
long_climb,commun,toutes,2025-04,1,plusieurs_sessions,1,1,
long_climb,commun,toutes,2025-04,1,jour_exclu_du_journal,1,1,
long_climb,commun,toutes,2025-04,2,hors_regimes,0,0,
long_climb,commun,toutes,2025-04,2,drapeau_exclu,1,2,
long_climb,commun,toutes,2025-04,2,vitesse_absente,0,0,
long_climb,commun,toutes,2025-04,2,cote_sous_gain_minimal,0,0,
long_climb,commun,toutes,2025-04,3,fc_indefinie,1,1,
long_climb,commun,toutes,2025-04,4,journee_reunie,1,4,
long_climb,M-P,toutes,2025-04,5,fc_repos_non_valide,0,0,
long_climb,M-P,toutes,2025-04,5,normale_absente,0,0,
long_climb,M-P,toutes,2025-04,5,a_cheval,0,0,
long_climb,M-P,toutes,2025-04,5,jour_incertain,0,0,
long_climb,M-P,toutes,2025-04,5,fc_repos_apres_sortie,0,0,
long_climb,M-P,toutes,2025-04,retenues,,2,5,
long_climb,M-P,toutes,,hors_mouvement,,2,5,0.0
long_climb,M-S,toutes,2025-04,5,fc_repos_non_valide,0,0,
long_climb,M-S,toutes,2025-04,5,normale_absente,0,0,
long_climb,M-S,toutes,2025-04,5,a_cheval,0,0,
long_climb,M-S,toutes,2025-04,5,jour_incertain,0,0,
long_climb,M-S,toutes,2025-04,5,fc_repos_apres_sortie,0,0,
long_climb,M-S,toutes,2025-04,6,ms_normale_absente,1,1,
long_climb,M-S,toutes,2025-04,6,ms_a_cheval,0,0,
long_climb,M-S,toutes,2025-04,6,ms_jour_incertain,0,0,
long_climb,M-S,toutes,2025-04,6,ms_reserve_non_positive,0,0,
long_climb,M-S,toutes,2025-04,retenues,,1,4,
short_climb,commun,toutes,2025-04,1,appareil_non_principal,0,0,
short_climb,commun,toutes,2025-04,1,plusieurs_sessions,0,0,
short_climb,commun,toutes,2025-04,1,jour_exclu_du_journal,0,0,
short_climb,commun,toutes,2025-04,2,hors_regimes,0,0,
short_climb,commun,toutes,2025-04,2,drapeau_exclu,0,0,
short_climb,commun,toutes,2025-04,2,vitesse_absente,0,0,
short_climb,commun,toutes,2025-04,2,cote_sous_gain_minimal,1,1,
short_climb,commun,toutes,2025-04,3,fc_indefinie,0,0,
short_climb,commun,toutes,2025-04,4,journee_reunie,0,0,
short_climb,M-P,toutes,2025-04,5,fc_repos_non_valide,0,0,
short_climb,M-P,toutes,2025-04,5,normale_absente,0,0,
short_climb,M-P,toutes,2025-04,5,a_cheval,0,0,
short_climb,M-P,toutes,2025-04,5,jour_incertain,0,0,
short_climb,M-P,toutes,2025-04,5,fc_repos_apres_sortie,0,0,
short_climb,M-P,toutes,2025-04,retenues,,1,1,
short_climb,M-P,toutes,,hors_mouvement,,1,1,0.0
short_climb,M-S,toutes,2025-04,5,fc_repos_non_valide,0,0,
short_climb,M-S,toutes,2025-04,5,normale_absente,0,0,
short_climb,M-S,toutes,2025-04,5,a_cheval,0,0,
short_climb,M-S,toutes,2025-04,5,jour_incertain,0,0,
short_climb,M-S,toutes,2025-04,5,fc_repos_apres_sortie,0,0,
short_climb,M-S,toutes,2025-04,6,ms_normale_absente,0,0,
short_climb,M-S,toutes,2025-04,6,ms_a_cheval,0,0,
short_climb,M-S,toutes,2025-04,6,ms_jour_incertain,0,0,
short_climb,M-S,toutes,2025-04,6,ms_reserve_non_positive,0,0,
short_climb,M-S,toutes,2025-04,retenues,,1,1,
ski_touring,commun,toutes,2025-04,1,appareil_non_principal,0,0,
ski_touring,commun,toutes,2025-04,1,plusieurs_sessions,0,0,
ski_touring,commun,toutes,2025-04,1,jour_exclu_du_journal,0,0,
ski_touring,commun,toutes,2025-04,2,hors_regimes,0,0,
ski_touring,commun,toutes,2025-04,2,drapeau_exclu,0,0,
ski_touring,commun,toutes,2025-04,2,vitesse_absente,0,0,
ski_touring,commun,toutes,2025-04,2,cote_sous_gain_minimal,0,0,
ski_touring,commun,toutes,2025-04,3,fc_indefinie,0,0,
ski_touring,commun,toutes,2025-04,4,journee_reunie,0,0,
ski_touring,M-P,toutes,2025-04,5,fc_repos_non_valide,0,0,
ski_touring,M-P,toutes,2025-04,5,normale_absente,0,0,
ski_touring,M-P,toutes,2025-04,5,a_cheval,0,0,
ski_touring,M-P,toutes,2025-04,5,jour_incertain,0,0,
ski_touring,M-P,toutes,2025-04,5,fc_repos_apres_sortie,0,0,
ski_touring,M-P,toutes,2025-04,retenues,,0,0,
ski_touring,M-P,toutes,,hors_mouvement,,0,0,
ski_touring,M-S,toutes,2025-04,5,fc_repos_non_valide,0,0,
ski_touring,M-S,toutes,2025-04,5,normale_absente,0,0,
ski_touring,M-S,toutes,2025-04,5,a_cheval,0,0,
ski_touring,M-S,toutes,2025-04,5,jour_incertain,0,0,
ski_touring,M-S,toutes,2025-04,5,fc_repos_apres_sortie,0,0,
ski_touring,M-S,toutes,2025-04,6,ms_normale_absente,0,0,
ski_touring,M-S,toutes,2025-04,6,ms_a_cheval,0,0,
ski_touring,M-S,toutes,2025-04,6,ms_jour_incertain,0,0,
ski_touring,M-S,toutes,2025-04,6,ms_reserve_non_positive,0,0,
ski_touring,M-S,toutes,2025-04,retenues,,0,0,
intermediate,commun,toutes,2025-04,1,appareil_non_principal,0,0,
intermediate,commun,toutes,2025-04,1,plusieurs_sessions,0,0,
intermediate,commun,toutes,2025-04,1,jour_exclu_du_journal,0,0,
intermediate,commun,toutes,2025-04,2,hors_regimes,1,1,
"""


def test_c3_the_whole_flux_file() -> None:
    """C3 : chaque motif à son premier compte ; ``drapeau_exclu`` des longues à 1
    journée et 2 montées ; tous les retraits jouent, donc l'étape 5 est à 0 et la
    journée du 5 avril revient ; aucune ligne pour mars."""
    assert _flux(c3_tables()) == C3_FLUX


# --- C13 ----------------------------------------------------------------------------

PARTS = (0.03, 0.14, 0.07, 0.22, 0.09, 0.31, 0.05, 0.18, 0.12, 0.26)


def test_c13_the_90th_percentile_of_the_off_moving_share() -> None:
    """C13 : la 9ᵉ des dix parts triées (statistique d'ordre) : 0,26."""
    activities, climbs = [], []
    for i, part in enumerate(PARTS):
        when = at(date(2025, 6, 1) + timedelta(days=i), 9)
        ref = f"h{i}"
        activities.append(q2_activity(ref, when))
        climbs.append(
            q2_climb(
                ref,
                when,
                moving_s=100.0 - 100.0 * part,
                stopped_s_by_convention=(100.0 * part,) * 5,
            )
        )
    rows = flux_rows(*_data_and_specs(q2_tables(activities, climbs)))
    (line,) = [r for r in rows if r[0] == "long_climb" and r[4] == "hors_mouvement"]
    assert line == [
        "long_climb",
        "M-P",
        "toutes",
        "",
        "hors_mouvement",
        "",
        10,
        10,
        0.26,
    ]


def _data_and_specs(
    tables: Tables, periods: Periods | None = None
) -> tuple[Q2Data, dict[tuple[ClimbRegime, Measure], ModelSpec]]:
    data = q2_data(tables, periods, DEFAULTS)
    return data, _specs(data)


# --- la grille ----------------------------------------------------------------------


def _two_month_world() -> Tables:
    jan = at(date(2025, 1, 15), 9)
    mar = at(date(2025, 3, 15), 9)
    return q2_tables(
        [q2_activity("j1", jan), q2_activity("m1", mar)],
        [q2_climb("j1", jan), q2_climb("m1", mar)],
    )


def test_an_empty_month_is_written_at_zero() -> None:
    rows = flux_rows(*_data_and_specs(_two_month_world()))
    months = sorted({str(r[3]) for r in rows if r[3]})
    assert months == ["2025-01", "2025-02", "2025-03"]
    february = [r for r in rows if r[3] == "2025-02"]
    assert february
    assert all(r[6] == 0 and r[7] == 0 for r in february)


def test_the_columns_and_the_order_of_the_rows() -> None:
    text = _flux(_two_month_world())
    assert text.splitlines()[0] == ",".join(FLUX_COLUMNS)
    rows = flux_rows(*_data_and_specs(_two_month_world()))
    long_mp = [r for r in rows if r[0] == "long_climb" and r[1] == "M-P"]
    assert [(r[3], r[4], r[5]) for r in long_mp[:7]] == [
        ("2025-01", "5", "fc_repos_non_valide"),
        ("2025-01", "5", "normale_absente"),
        ("2025-01", "5", "a_cheval"),
        ("2025-01", "5", "jour_incertain"),
        ("2025-01", "5", "fc_repos_apres_sortie"),
        ("2025-01", "retenues", ""),
        ("2025-02", "5", "fc_repos_non_valide"),
    ]
    assert long_mp[-1][4] == "hors_mouvement"
    assert [r[0] for r in rows][:: len(rows) - 1] == ["long_climb", "ski_touring"]


def test_a_month_cut_by_the_periods_is_written_once_per_period() -> None:
    """Février coupé par la découverte (10 au 20) : ``avant``, ``decouverte``,
    ``suite`` ; les périodes dans leur ordre, puis les mois."""
    periods = Periods(date(2025, 2, 10), date(2025, 2, 20))
    rows = flux_rows(*_data_and_specs(_two_month_world(), periods))
    keys = [
        (r[2], r[3])
        for r in rows
        if r[0] == "long_climb"
        and r[1] == "commun"
        and r[5] == "appareil_non_principal"
    ]
    assert keys == [
        ("avant", "2025-01"),
        ("avant", "2025-02"),
        ("decouverte", "2025-02"),
        ("suite", "2025-02"),
        ("suite", "2025-03"),
    ]
    off = [r for r in rows if r[0] == "long_climb" and r[4] == "hors_mouvement"]
    assert [r[2] for r in off] == ["avant", "decouverte", "suite"]
    assert [r[6] for r in off] == [1, 0, 1]
    assert off[1][8] is None


# --- les dossiers -------------------------------------------------------------------

FILES = {"a.csv": "x\n1\n"}
DOCUMENT: dict[str, object] = {"question": "Q2"}


def test_a_folder_is_named_by_its_date_and_fingerprint(tmp_path: Path) -> None:
    written = write_folder(tmp_path, POWER_DIR, FILES, DOCUMENT, date(2026, 11, 16))
    assert written.parent == tmp_path / POWER_DIR
    assert written.name.startswith("2026-11-16_")
    assert results.RESULT_NAME.fullmatch(written.name)
    assert sorted(p.name for p in written.iterdir()) == ["a.csv", "provenance.json"]
    document = json.loads((written / "provenance.json").read_text(encoding="utf-8"))
    assert document["genere_le"] == "2026-11-16"
    assert set(document["fichiers"]) == {"a.csv"}
    other = write_folder(tmp_path, POWER_DIR, FILES, DOCUMENT, date(2026, 11, 17))
    assert other.name.split("_")[1] == written.name.split("_")[1]


def test_an_existing_folder_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    written = write_folder(tmp_path, POWER_DIR, FILES, DOCUMENT, date(2026, 11, 16))
    before = {p: p.read_bytes() for p in written.iterdir()}
    with pytest.raises(Q2ResultsError, match="existe déjà : rien n'est réécrit"):
        write_folder(
            tmp_path, POWER_DIR, {"a.csv": "x\n1\n"}, DOCUMENT, date(2026, 11, 16)
        )
    assert {p: p.read_bytes() for p in written.iterdir()} == before


def test_a_failed_write_leaves_neither_folder_nor_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.write_text

    def fail_on_provenance(self: Path, *args: Any, **kwargs: Any) -> int:
        if self.name == "provenance.json":
            raise OSError("disque plein")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_on_provenance)
    with pytest.raises(OSError, match="disque plein"):
        write_folder(tmp_path, POWER_DIR, FILES, DOCUMENT, date(2026, 11, 16))
    assert list((tmp_path / POWER_DIR).iterdir()) == []


def test_the_power_folder_without_estimable_regime(tmp_path: Path) -> None:
    data, specs = _data_and_specs(c3_tables())
    result = PowerResult(
        power_grids(DEFAULTS),
        tuple(
            RegimePower(r, None, None, "trop peu de journées", alpha_grid(r, DEFAULTS))
            for r in (LONG, ClimbRegime.SHORT_CLIMB)
        ),
    )
    tables = c3_tables()
    written = write_power_results(
        tmp_path,
        result,
        data,
        specs,
        tables.provenance,
        DEFAULTS,
        commit=COMMIT,
        package_version="0.0.1",
        generated_on=date(2026, 11, 16),
    )
    assert sorted(p.name for p in written.iterdir()) == [
        "flux.csv",
        "provenance.json",
        "puissance.csv",
    ]
    assert (written / "puissance.csv").read_text(encoding="utf-8").count("\n") == 1
    document = json.loads((written / "provenance.json").read_text(encoding="utf-8"))
    assert document["regimes"]["long_climb"] == {
        "statut": "non_estimable",
        "motif": "trop peu de journées",
    }
    assert document["commande"] == "mperf q2 puissance"
    assert document["graine"] == 20261115
    assert document["appareil_principal"] == {"fabricant": "garmin", "produit": 1}
    assert document["tables"] == json.loads(
        json.dumps(dataclasses.asdict(tables.provenance))
    )


# --- latest_power -------------------------------------------------------------------


def _power_folder(
    data_dir: Path,
    name: str,
    provenance: ProcessedProvenance,
    *,
    written_ns: int | None = None,
    alpha: float | None = 0.04,
) -> Path:
    folder = data_dir / POWER_DIR / name
    folder.mkdir(parents=True)
    document = {
        "tables": dataclasses.asdict(provenance),
        "genere_le": name.split("_")[0],
        "regimes": {
            "long_climb": {
                "calibration": {"declenchee": alpha is not None, "alpha": alpha}
            },
            "short_climb": {"statut": "non_estimable", "motif": "x"},
        },
    }
    (folder / "provenance.json").write_text(json.dumps(document), encoding="utf-8")
    if written_ns is not None:
        os.utime(folder / "provenance.json", ns=(written_ns, written_ns))
    return folder


def test_latest_power_reads_the_tables_and_the_most_recent(tmp_path: Path) -> None:
    provenance = c3_tables().provenance
    other = dataclasses.replace(provenance, climb_count=99)
    assert latest_power(tmp_path, provenance) is None
    _power_folder(tmp_path, "2026-11-15_aaaaaaaaaaaa", provenance)
    _power_folder(tmp_path, "2026-11-17_bbbbbbbbbbbb", other)
    _power_folder(tmp_path, "2026-11-16_cccccccccccc", provenance, alpha=None)
    (tmp_path / POWER_DIR / ".2026-11-18_dddddddddddd.nouveau").mkdir()
    _power_folder(tmp_path, "2026-11-19_pas-un-nom", provenance)
    stored = latest_power(tmp_path, provenance)
    assert stored is not None
    assert stored.folder.name == "2026-11-16_cccccccccccc"
    assert stored.levels["long_climb"].computed is True
    assert stored.levels["long_climb"].alpha is None
    assert stored.levels["short_climb"].computed is False
    assert len(stored.digest) == 64


def test_latest_power_at_equal_dates_takes_the_last_written(tmp_path: Path) -> None:
    """À date égale, le ``provenance.json`` écrit le plus tard, même si son nom est le
    plus petit."""
    provenance = c3_tables().provenance
    _power_folder(tmp_path, "2026-11-16_ffffffffffff", provenance, written_ns=10**18)
    _power_folder(
        tmp_path, "2026-11-16_000000000000", provenance, written_ns=2 * 10**18
    )
    stored = latest_power(tmp_path, provenance)
    assert stored is not None
    assert stored.folder.name == "2026-11-16_000000000000"
