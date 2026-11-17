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
from fixtures.q2_world import at, q2_activity, q2_climb, q2_tables, small_world
from mountain_perf.analyse.athlete import Periods
from mountain_perf.analyse.inference.base import child_rng, order_quantile
from mountain_perf.analyse.q2 import results
from mountain_perf.analyse.q2.data import Q2Data, q2_data
from mountain_perf.analyse.q2.figure import (
    Q2Figure,
    partial_date_residuals,
    q2_figure_data,
)
from mountain_perf.analyse.q2.model import (
    Measure,
    ModelSpec,
    build_design,
    fit_direct,
    model_spec,
    stage_one,
)
from mountain_perf.analyse.q2.parameters import (
    Q2_PARAMETER_SPECS,
    Q2_REGIMES,
    Q2_ROOT_SEED,
)
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
    StoredPower,
    append_trials,
    check_trials,
    figure_csv,
    flux_csv,
    flux_rows,
    latest_power,
    write_estimation_results,
    write_folder,
    write_power_results,
)
from mountain_perf.analyse.q2.trials import NOT_DONE, Q2Estimation, TrialRow
from mountain_perf.analyse.tables import Tables
from mountain_perf.codec import content_hash
from mountain_perf.schemas import ParameterSet
from mountain_perf.schemas.processed import ClimbRegime, ProcessedProvenance
from test_analyse_q2_data import c3_tables

LONG = ClimbRegime.LONG_CLIMB
EXACT = 1e-12
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


# --- C16 : le journal chaîné ------------------------------------------------------


def _trial(name: str, value: float) -> TrialRow:
    return TrialRow(
        essai=name,
        indice=0,
        famille="principale",
        regime="long_climb",
        mesure="M-P",
        statut="estime",
        estimation_fraction=value,
        intervalle_fraction=(value - 0.01, value + 0.01),
    )


def _journal(data_dir: Path) -> Path:
    return data_dir / results.JOURNAL


def test_c16_the_chained_journal(tmp_path: Path) -> None:
    """C16 : deux exécutions de deux lignes ; la ligne 1 a ``precedente = null``, la
    ligne ``k`` l'empreinte des octets de la ligne ``k − 1`` sans ``\\n``."""
    append_trials(tmp_path, "e1", COMMIT, [_trial("P", 0.01), _trial("S1", 0.02)])
    append_trials(tmp_path, "e2", COMMIT, [_trial("P", 0.03), _trial("S1", 0.04)])
    lines = _journal(tmp_path).read_bytes().split(b"\n")
    assert lines[-1] == b""
    lines = lines[:-1]
    assert len(lines) == 4
    records = [json.loads(line) for line in lines]
    assert records[0]["precedente"] is None
    for k in range(1, 4):
        assert records[k]["precedente"] == content_hash(lines[k - 1])
    assert list(records[0]) == [
        "question",
        "execution",
        "commit",
        "essai",
        "precedente",
    ]
    assert records[2]["execution"] == "e2"
    assert records[0]["essai"]["intervalle_fraction"] == [0.0, 0.02]
    assert list(records[0]["essai"])[:3] == ["essai", "indice", "famille"]


def test_c16_a_changed_line_breaks_the_chain(tmp_path: Path) -> None:
    """Un chiffre de la ligne 2 changé (elle se décode encore) : l'ajout suivant lève
    à la ligne 3, et le fichier reste identique à l'octet."""
    append_trials(tmp_path, "e1", COMMIT, [_trial("P", 0.01), _trial("S1", 0.02)])
    append_trials(tmp_path, "e2", COMMIT, [_trial("P", 0.03), _trial("S1", 0.04)])
    path = _journal(tmp_path)
    lines = path.read_bytes().split(b"\n")
    assert b"0.02" in lines[1]
    lines[1] = lines[1].replace(b"0.02", b"0.07", 1)
    path.write_bytes(b"\n".join(lines))
    before = path.read_bytes()
    with pytest.raises(Q2ResultsError) as error:
        append_trials(tmp_path, "e3", COMMIT, [_trial("P", 0.05)])
    assert str(error.value) == (
        "essais.jsonl, ligne 3 : la chaîne est rompue ; rien n'est écrit"
    )
    assert path.read_bytes() == before


def test_c16_a_removed_line_breaks_the_chain(tmp_path: Path) -> None:
    append_trials(tmp_path, "e1", COMMIT, [_trial("P", 0.01), _trial("S1", 0.02)])
    append_trials(tmp_path, "e2", COMMIT, [_trial("P", 0.03), _trial("S1", 0.04)])
    path = _journal(tmp_path)
    lines = path.read_bytes().split(b"\n")
    path.write_bytes(b"\n".join([lines[0], *lines[2:]]))
    with pytest.raises(Q2ResultsError, match="ligne 2 : la chaîne est rompue"):
        check_trials(tmp_path)


def test_c16_the_last_line_is_not_seen_by_the_chain(tmp_path: Path) -> None:
    """La limite dite : la dernière ligne retouchée ne se voit pas par la chaîne."""
    append_trials(tmp_path, "e1", COMMIT, [_trial("P", 0.01), _trial("S1", 0.02)])
    path = _journal(tmp_path)
    first, last, end = path.read_bytes().split(b"\n")
    path.write_bytes(b"\n".join([first, last.replace(b"0.02", b"0.09"), end]))
    assert check_trials(tmp_path) is not None


# --- C24 et la figure ---------------------------------------------------------------


def test_c24_the_partial_residuals_of_the_date() -> None:
    x = [[1.0, 0.0, 2.0], [1.0, 10.0, 1.0], [1.0, 20.0, 4.0]]
    y = [5.0, 4.0, 9.0]
    assert partial_date_residuals(x, y, [1.0, 0.1, 2.0], 0, 1) == pytest.approx(
        [1.0, 2.0, 1.0], rel=EXACT
    )


@pytest.fixture(scope="module")
def figure() -> Q2Figure:
    params = ParameterSet(Q2_PARAMETER_SPECS, {"bootstrap_draws": 9.0})
    data = q2_data(small_world(1), None, params)
    spec = model_spec(data.days[LONG], Measure.MP, LONG, params)
    units = spec.units()
    design = build_design(units, spec, stage_one(units, Measure.MP), params)
    built = q2_figure_data(
        fit_direct(design, params), params, child_rng(Q2_ROOT_SEED, 2, 0, 2)
    )
    assert built is not None
    return built


def test_the_figure_has_five_knots_and_a_provisional_last_section(
    figure: Q2Figure,
) -> None:
    t = [float((p.day - figure.points[0].day).days) for p in figure.points]
    assert figure.knots[0] == min(t)
    assert figure.knots[-1] == max(t)
    assert len(figure.knots) == 5
    assert figure.knots[3] == order_quantile(t, 0.75)
    first = figure.points[0].day
    for c in figure.curve:
        assert c.provisional is ((c.day - first).days > figure.knots[3])
        assert c.low <= c.estimate <= c.high
    assert len(figure.curve) == int(max(t)) + 1
    assert figure.draws == 9
    assert figure.key == (2, 0, 2)


def test_figure_csv(figure: Q2Figure) -> None:
    text = figure_csv(figure)
    lines = text.splitlines()
    assert lines[0] == "type,date,residu_partiel,estimation,bas,haut,provisoire"
    points = [line for line in lines if line.startswith("point,")]
    curve = [line for line in lines if line.startswith("courbe,")]
    assert len(points) == len(figure.points)
    assert len(curve) == len(figure.curve)
    assert lines[1].split(",")[3:] == ["", "", "", ""]
    assert curve[-1].endswith(",true")
    assert curve[0].endswith(",false")
    assert figure_csv(None) == lines[0] + "\n"


def test_the_figure_page_carries_the_legend_word_for_word(figure: Q2Figure) -> None:
    pytest.importorskip("plotly")
    from mountain_perf.analyse.plot import q2_figure_html

    page = q2_figure_html(figure)
    assert (
        "Résidus partiels de la date, montées longues ; courbe lissée et bande"
        " simultanée à 95 % ; descriptive, sans verdict ; la bande ignore la"
        " corrélation entre journées : sans doute trop étroite ; dernier tronçon"
        " provisoire."
    ) in page
    assert q2_figure_html(figure) == page
    empty = q2_figure_html(None)
    assert "Pas de figure : l&#x27;essai principal n&#x27;est pas estimé." in empty


# --- le dossier d'estimation ----------------------------------------------------------


def _estimation(data: Q2Data) -> Q2Estimation:
    return Q2Estimation(
        rows=(_trial("P", 0.01),),
        specs=_specs(data),
        principal=None,
        levels={"P": 0.95},
        bounds={},
        autocorrelation=(("long_climb", "M-P", 57, None, 0, None),),
    )


def _write_estimation(data_dir: Path, day: date) -> Path:
    data = q2_data(c3_tables(), None, DEFAULTS)
    power = StoredPower(
        data_dir / "puissance" / "2026-11-15_aaaaaaaaaaaa", "f" * 64, {}
    )
    return write_estimation_results(
        data_dir,
        _estimation(data),
        data,
        None,
        "<p>x</p>",
        c3_tables().provenance,
        DEFAULTS,
        power,
        commit=COMMIT,
        package_version="0.0.1",
        generated_on=day,
    )


def test_the_estimation_folder(tmp_path: Path) -> None:
    written = _write_estimation(tmp_path, date(2026, 11, 16))
    assert written.parent == tmp_path / "resultats" / "Q2"
    assert results.RESULT_NAME.fullmatch(written.name)
    assert sorted(p.name for p in written.iterdir()) == [
        "autocorrelation.csv",
        "essais.csv",
        "figure.csv",
        "figure.html",
        "flux.csv",
        "provenance.json",
    ]
    assert (written / "autocorrelation.csv").read_text(encoding="utf-8") == (
        "regime,mesure,de,a,paires,correlation\nlong_climb,M-P,57,,0,\n"
    )
    header = (written / "essais.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "intervalle_fraction_bas,intervalle_fraction_haut" in header
    document = json.loads((written / "provenance.json").read_text(encoding="utf-8"))
    assert document["commande"] == "mperf q2"
    assert document["puissance"] == {
        "dossier": "2026-11-15_aaaaaaaaaaaa",
        "empreinte": "f" * 64,
    }
    assert document["non_faites"] == list(NOT_DONE)
    assert document["figure"] is None
    other = _write_estimation(tmp_path, date(2026, 11, 17))
    assert other.name.split("_")[1] == written.name.split("_")[1]
    with pytest.raises(Q2ResultsError, match="existe déjà"):
        _write_estimation(tmp_path, date(2026, 11, 16))
    assert not any(p.name.startswith(".") for p in written.parent.iterdir())
