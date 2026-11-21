"""La relecture d'un résultat de Q2 (AN3-5, § 5 du brief) : les dossiers
d'estimation sous ``resultats/Q2/``, le dernier, et leur contenu (essais, flux,
autocorrélation, puissance nommée). Les dossiers sont écrits à la main sous
``tmp_path``, par les fonctions d'écriture du module (le format de ``mperf q2``) ; les
valeurs sont inventées. R11 relit un dossier écrit par la vraie commande sur le petit
monde de ``tests/fixtures/q2_run.py``."""

from __future__ import annotations

import contextlib
import csv
import dataclasses
import hashlib
import io
import json
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from fixtures.figure import tables_of
from mountain_perf.analyse.q2.results import (
    AUTOCORRELATION_COLUMNS,
    AUTOCORRELATION_FILE,
    BOOL_COLUMNS,
    FIGURE_HTML,
    FLOAT_COLUMNS,
    FLUX_COLUMNS,
    FLUX_FILE,
    INT_COLUMNS,
    POWER_COLUMNS,
    POWER_DIR,
    POWER_FILE,
    PROVENANCE_FILE,
    RESULTS_DIR,
    TRIALS_FILE,
    EstimationReading,
    Q2ResultsError,
    RegimeWarning,
    cell,
    csv_text,
    essais_csv,
    flux_summary,
    json_text,
    latest_estimation,
    read_estimation,
    stored_estimations,
    trial_columns,
)
from mountain_perf.analyse.q2.trials import TrialRow
from mountain_perf.analyse.results import TablesMatch
from mountain_perf.schemas.processed import ProcessedProvenance

TABLES = {"commit": "a" * 40, "inventees": True}
"""La valeur ``tables`` des dossiers inventés."""
POWER_NAME = "2026-01-01_eeeeeeeeeeee"
OLDER_POWER = "2025-12-30_ffffffffffff"
MESSAGE = "données insuffisantes pour juger un effet de 5 %/an"
BLAS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")


def _row(**changes: Any) -> TrialRow:
    """Une ligne d'essai inventée, l'essai principal par défaut."""
    values: dict[str, Any] = {
        "essai": "P",
        "indice": 0,
        "famille": "principale",
        "regime": "long_climb",
        "mesure": "M-P",
        "statut": "estime",
        "n_journees": 17,
        "n_montees": 23,
        "p": 4,
        "niveau": 0.95,
        "estimation_fraction": 0.237,
        "intervalle_fraction": (-0.062, math.inf),
        "inverse_fraction": 0.31,
        "intervalle_inverse_fraction": (0.01, 0.6),
        "k_contient_zero": False,
        "lecture": "non_tranche",
        "phrase": "les données ne tranchent pas",
        "phi": 7.36,
        "phi_a_la_borne_basse": False,
        "phi_a_la_borne_haute": True,
        "tirages_retires": 3,
    }
    values.update(changes)
    return TrialRow(**values)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def _estimation(
    data: Path,
    name: str,
    *,
    tables: object = TABLES,
    trials: str | None = None,
    extra: Mapping[str, object] | None = None,
    generated: str | None = None,
) -> Path:
    """Un dossier ``resultats/Q2/<name>/`` : ``provenance.json`` et ``essais.csv``
    (``trials`` : son texte ; une seule ligne principale par défaut)."""
    folder = data / RESULTS_DIR / name
    document: dict[str, object] = {
        "genere_le": name.split("_")[0] if generated is None else generated,
        "tables": tables,
        **(extra or {}),
    }
    _write(folder / PROVENANCE_FILE, json_text(document))
    _write(folder / TRIALS_FILE, essais_csv([_row()]) if trials is None else trials)
    return folder


def _regime(p_zero: float = 0.031, **changes: Any) -> dict[str, object]:
    entry: dict[str, object] = {
        "statut": "calculee",
        "a_zero": {
            "1": {"p_etabli": p_zero, "p_absence_effet_utile": 0.0},
            "2": {"p_etabli": 0.4, "p_absence_effet_utile": 0.0},
            "3": {"p_etabli": 0.5, "p_absence_effet_utile": 0.0},
            "4": {"p_etabli": 0.6, "p_absence_effet_utile": 0.0},
        },
        "seuils": [0.05, 0.01],
        "calibration": {"declenchee": False, "alpha": 0.05},
        "message": None,
    }
    entry.update(changes)
    return entry


POWER_ROWS: list[list[object]] = [
    ["long_climb", 1, 0.05, 3, 0, 0.7, 0.0, 0.1, 0.7, 0.0, 1.2, 0.9],
    ["long_climb", 4, 0.0, 3, 0, 0.1, 0.0, 0.1, 0.1, 0.0, 1.0, 0.011],
    ["long_climb", 4, 0.05, 3, 0, 0.6, 0.0, 0.1, 0.6, 0.0, 1.1, -0.007],
    ["ski_touring", 4, 0.05, 3, 0, 0.6, 0.0, 0.1, 0.6, 0.0, 1.1, 0.3],
]


def _power(
    data: Path,
    name: str = POWER_NAME,
    *,
    regimes: Mapping[str, object] | None = None,
    rows: list[list[object]] | None = None,
    document: object = None,
    power_csv: bool = True,
) -> str:
    """Un dossier ``resultats/Q2/puissance/<name>/`` ; rend le SHA-256 des octets de
    son ``provenance.json``."""
    folder = data / POWER_DIR / name
    if document is None:
        document = {
            "genere_le": name.split("_")[0],
            "tables": TABLES,
            "parametres": {"delta": 0.05, "alpha": 0.05},
            "regimes": {"long_climb": _regime()} if regimes is None else regimes,
        }
    _write(folder / PROVENANCE_FILE, json_text(document))
    if power_csv:
        _write(
            folder / POWER_FILE,
            csv_text(POWER_COLUMNS, POWER_ROWS if rows is None else rows),
        )
    return hashlib.sha256((folder / PROVENANCE_FILE).read_bytes()).hexdigest()


def _named(digest: str, name: str = POWER_NAME) -> dict[str, object]:
    return {"puissance": {"dossier": name, "empreinte": digest}}


def _read(data: Path, folder: Path) -> EstimationReading:
    estimations, _ = stored_estimations(data)
    (stored,) = [e for e in estimations if e.folder == folder]
    return read_estimation(data, stored)


# --- R1 à R4 : les dossiers -------------------------------------------------------


def test_r1_only_result_names_are_read_and_counted(tmp_path: Path) -> None:
    root = tmp_path / RESULTS_DIR
    _power(tmp_path)
    (root / ".2026-01-04_cccccccccccc.nouveau").mkdir(parents=True)
    _estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa")
    _estimation(tmp_path, "2026-01-03_bbbbbbbbbbbb")
    missing = _estimation(tmp_path, "2026-01-05_dddddddddddd")
    (missing / TRIALS_FILE).unlink()
    (root / "notes").mkdir()
    (root / "lisez-moi.txt").write_text("x", encoding="utf-8")
    estimations, unreadable = stored_estimations(tmp_path)
    assert [e.folder.name for e in estimations] == [
        "2026-01-02_aaaaaaaaaaaa",
        "2026-01-03_bbbbbbbbbbbb",
    ]
    assert unreadable == 1
    latest = latest_estimation(tmp_path, None)
    assert latest is not None
    assert latest.estimation.folder.name == "2026-01-03_bbbbbbbbbbbb"
    assert latest.match is TablesMatch.UNKNOWN
    assert latest.unreadable == 1
    assert latest.estimation.document["tables"] == TABLES


def test_r1_two_unreadable_and_names_that_are_not_result_names(tmp_path: Path) -> None:
    """Le compte des illisibles s'additionne (deux dossiers, compte 2) ; un nom qui
    commence comme un nom de résultat sans en être un (``… - copie``, lisible par
    ailleurs) et un fichier au nom de résultat sont ignorés, sans être comptés :
    ``RESULT_NAME.fullmatch``, des dossiers seulement."""
    root = tmp_path / RESULTS_DIR
    _estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa")
    _estimation(tmp_path, "2026-01-03_bbbbbbbbbbbb")
    _no_trials(_estimation(tmp_path, "2026-01-04_cccccccccccc"))
    _not_json(_estimation(tmp_path, "2026-01-05_dddddddddddd"))
    _estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa - copie")
    (root / "2026-01-06_aaaaaaaaaaaa").write_text("x", encoding="utf-8")
    estimations, unreadable = stored_estimations(tmp_path)
    assert [e.folder.name for e in estimations] == [
        "2026-01-02_aaaaaaaaaaaa",
        "2026-01-03_bbbbbbbbbbbb",
    ]
    assert unreadable == 2
    latest = latest_estimation(tmp_path, None)
    assert latest is not None
    assert latest.unreadable == 2


def test_r1_without_results_dir_nothing(tmp_path: Path) -> None:
    assert stored_estimations(tmp_path) == ((), 0)
    assert latest_estimation(tmp_path, None) is None


def _warnings(data: Path, folder: Path) -> tuple[RegimeWarning, ...]:
    power = _read(data, folder).power
    assert power is not None
    return power


def _as_json(provenance: ProcessedProvenance) -> object:
    return json.loads(json.dumps(dataclasses.asdict(provenance)))


def test_r2_the_rule_of_q1(tmp_path: Path) -> None:
    current = tables_of([], []).provenance
    _estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa", tables=_as_json(current))
    _estimation(tmp_path, "2026-01-03_bbbbbbbbbbbb")
    unknown = latest_estimation(tmp_path, None)
    assert unknown is not None
    assert unknown.match is TablesMatch.UNKNOWN
    assert unknown.estimation.folder.name == "2026-01-03_bbbbbbbbbbbb"
    same = latest_estimation(tmp_path, current)
    assert same is not None
    assert same.match is TablesMatch.SAME
    assert same.estimation.folder.name == "2026-01-02_aaaaaaaaaaaa"
    other = dataclasses.replace(current, commit="b" * 40)
    different = latest_estimation(tmp_path, other)
    assert different is not None
    assert different.match is TablesMatch.DIFFERENT
    assert different.estimation.folder.name == "2026-01-03_bbbbbbbbbbbb"


def test_r3_same_date_the_last_written_then_the_largest_name(tmp_path: Path) -> None:
    small = _estimation(tmp_path, "2026-01-03_aaaaaaaaaaaa")
    large = _estimation(tmp_path, "2026-01-03_bbbbbbbbbbbb")
    os.utime(large / PROVENANCE_FILE, ns=(1_000_000_000, 1_000_000_000))
    os.utime(small / PROVENANCE_FILE, ns=(2_000_000_000, 2_000_000_000))
    latest = latest_estimation(tmp_path, None)
    assert latest is not None
    assert latest.estimation.folder == small
    os.utime(small / PROVENANCE_FILE, ns=(1_000_000_000, 1_000_000_000))
    latest = latest_estimation(tmp_path, None)
    assert latest is not None
    assert latest.estimation.folder == large


def _no_provenance(folder: Path) -> None:
    (folder / PROVENANCE_FILE).unlink()


def _not_json(folder: Path) -> None:
    (folder / PROVENANCE_FILE).write_bytes(b"{pas du json")


def _not_utf8(folder: Path) -> None:
    (folder / PROVENANCE_FILE).write_bytes(b'{"tables": "\xff"}')


def _not_object(folder: Path) -> None:
    (folder / PROVENANCE_FILE).write_text("[1, 2]", encoding="utf-8")


def _no_tables(folder: Path) -> None:
    (folder / PROVENANCE_FILE).write_text(
        json.dumps({"genere_le": "2026-01-02"}), encoding="utf-8"
    )


def _other_date(folder: Path) -> None:
    (folder / PROVENANCE_FILE).write_text(
        json.dumps({"genere_le": "2026-01-09", "tables": TABLES}), encoding="utf-8"
    )


def _not_a_date(folder: Path) -> None:
    (folder / PROVENANCE_FILE).write_text(
        json.dumps({"genere_le": "02/01/2026", "tables": TABLES}), encoding="utf-8"
    )


def _no_trials(folder: Path) -> None:
    (folder / TRIALS_FILE).unlink()


@pytest.mark.parametrize(
    "spoil",
    [
        _no_provenance,
        _not_json,
        _not_utf8,
        _not_object,
        _no_tables,
        _other_date,
        _not_a_date,
        _no_trials,
    ],
)
def test_r4_each_cause_of_unreadable(tmp_path: Path, spoil: Any) -> None:
    spoil(_estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa"))
    assert stored_estimations(tmp_path) == ((), 1)
    assert latest_estimation(tmp_path, None) is None


# --- R5, R6, R12 : les cases d'essais.csv -------------------------------------------


def test_the_typed_columns_split_the_trial_columns() -> None:
    columns = trial_columns()
    typed = [*INT_COLUMNS, *FLOAT_COLUMNS, *BOOL_COLUMNS]
    assert len(INT_COLUMNS) == 6
    assert len(FLOAT_COLUMNS) == 14
    assert len(typed) == len(set(typed))
    assert set(typed) <= set(columns)
    text = set(columns) - set(typed)
    assert text == {
        "essai",
        "famille",
        "regime",
        "mesure",
        "statut",
        "motif",
        "retraits",
        "lecture",
        "phrase",
        "mention",
        "forme_fc",
    }


def _cells(**values: str) -> str:
    """``essais.csv`` d'une ligne : celle de ``_row()``, des cases remplacées."""
    columns = trial_columns()
    text = essais_csv([_row()])
    _, line = text.rstrip("\n").split("\n")
    (cells,) = list(csv.reader([line]))
    by_name = dict(zip(columns, cells, strict=True))
    by_name.update(values)
    return csv_text(columns, [[by_name[c] for c in columns]])


def test_r5_the_cells_and_their_types(tmp_path: Path) -> None:
    every_int = {c: "17" for c in INT_COLUMNS}
    every_float = {c: "0.237" for c in FLOAT_COLUMNS}
    every_bool = {c: "true" for c in BOOL_COLUMNS}
    trials = _cells(
        **{**every_int, **every_float, **every_bool, "motif": "", "indice": "3"}
    )
    folder = _estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa", trials=trials)
    (row,) = _read(tmp_path, folder).trials
    assert list(row) == list(trial_columns())
    for column in INT_COLUMNS:
        assert type(row[column]) is int, column
    assert row["n_journees"] == 17
    assert row["indice"] == 3
    for column in FLOAT_COLUMNS:
        assert type(row[column]) is float, column
        assert row[column] == 0.237
    for column in BOOL_COLUMNS:
        assert row[column] is True, column
    assert row["motif"] is None
    assert row["essai"] == "P"
    false = _estimation(
        tmp_path,
        "2026-01-03_aaaaaaaaaaaa",
        trials=_cells(holm_rejet="false", kappa="inf", tau2=""),
    )
    (row,) = _read(tmp_path, false).trials
    assert row["holm_rejet"] is False
    assert row["kappa"] == math.inf
    assert row["tau2"] is None


@pytest.mark.parametrize(
    ("column", "text"),
    [
        ("estimation_fraction", "abc"),
        ("n_journees", "17.5"),
        ("indice", "true"),
        ("holm_rejet", "oui"),
    ],
)
def test_r6_an_unreadable_cell_names_the_file_and_the_column(
    tmp_path: Path, column: str, text: str
) -> None:
    folder = _estimation(
        tmp_path, "2026-01-02_aaaaaaaaaaaa", trials=_cells(**{column: text})
    )
    with pytest.raises(Q2ResultsError) as raised:
        _read(tmp_path, folder)
    message = str(raised.value)
    assert "resultats/Q2/2026-01-02_aaaaaaaaaaaa/essais.csv" in message
    assert "ligne 2" in message
    assert column in message


def test_r12_a_cell_written_by_cell_inf_reads_back_inf(tmp_path: Path) -> None:
    folder = _estimation(
        tmp_path,
        "2026-01-02_aaaaaaaaaaaa",
        trials=_cells(intervalle_fraction_haut=cell(math.inf)),
    )
    (row,) = _read(tmp_path, folder).trials
    assert row["intervalle_fraction_haut"] == math.inf
    (row,) = _read(tmp_path, _estimation(tmp_path, "2026-01-03_aaaaaaaaaaaa")).trials
    assert row["intervalle_fraction_haut"] == math.inf


# --- R7 : le flux -------------------------------------------------------------------

FLUX_CASE = [
    [
        "long_climb",
        "commun",
        "suite",
        "2026-01",
        1,
        "appareil_non_principal",
        2,
        3,
        None,
    ],
    [
        "long_climb",
        "commun",
        "suite",
        "2026-02",
        1,
        "appareil_non_principal",
        1,
        1,
        None,
    ],
    ["long_climb", "M-P", "suite", "", "hors_mouvement", "", 0, 0, 0.25],
]


def _flux_rows(rows: list[list[object]]) -> list[dict[str, str]]:
    return [
        dict(zip(FLUX_COLUMNS, [cell(v) for v in row], strict=True)) for row in rows
    ]


EXPECTED_FLUX = (
    {
        "regime": "long_climb",
        "mesure": "commun",
        "periode": "suite",
        "etape": "1",
        "motif": "appareil_non_principal",
        "journees": 3,
        "montees": 4,
        "valeur": None,
    },
    {
        "regime": "long_climb",
        "mesure": "M-P",
        "periode": "suite",
        "etape": "hors_mouvement",
        "motif": "",
        "journees": 0,
        "montees": 0,
        "valeur": 0.25,
    },
)


def test_r7_the_flux_summed_over_the_months() -> None:
    summary = flux_summary(_flux_rows(FLUX_CASE))
    assert summary == EXPECTED_FLUX
    for line in summary:
        assert list(line) == [
            "regime",
            "mesure",
            "periode",
            "etape",
            "motif",
            "journees",
            "montees",
            "valeur",
        ]
        assert type(line["journees"]) is int
        assert type(line["montees"]) is int
    assert type(summary[1]["valeur"]) is float


def test_r7_two_off_moving_rows_are_not_summed() -> None:
    off = ["long_climb", "M-P", "suite", "", "hors_mouvement", "", 2, 5, 0.25]
    other = ["long_climb", "M-P", "suite", "", "hors_mouvement", "", 1, 4, 0.5]
    summary = flux_summary(_flux_rows([off, other]))
    assert [(s["journees"], s["montees"], s["valeur"]) for s in summary] == [
        (2, 5, 0.25),
        (1, 4, 0.5),
    ]


def test_r7_the_order_of_first_appearance() -> None:
    """Les lignes rendues suivent l'ordre de première apparition : une ligne
    ``hors_mouvement`` en premier reste première, et deux clés sommées gardent leur
    ordre du fichier (l'étape 2 avant l'étape 1), qui n'est pas l'ordre trié."""
    off = ["long_climb", "M-P", "suite", "", "hors_mouvement", "", 2, 5, 0.25]
    two = ["long_climb", "commun", "suite", "2026-01", 2, "trop_courte", 1, 2, None]
    one = ["long_climb", "commun", "suite", "2026-01", 1, "appareil", 3, 4, None]
    two_later = [*two[:3], "2026-02", *two[4:6], 5, 6, None]
    one_later = [*one[:3], "2026-02", *one[4:6], 7, 8, None]
    summary = flux_summary(_flux_rows([off, two, one, two_later, one_later]))
    assert [(s["etape"], s["motif"], s["journees"], s["montees"]) for s in summary] == [
        ("hors_mouvement", "", 2, 5),
        ("2", "trop_courte", 6, 8),
        ("1", "appareil", 10, 12),
    ]
    assert [s["valeur"] for s in summary] == [0.25, None, None]


def test_r7_the_flux_is_read_from_its_file(tmp_path: Path) -> None:
    folder = _estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa")
    _write(folder / FLUX_FILE, csv_text(FLUX_COLUMNS, FLUX_CASE))
    assert _read(tmp_path, folder).flux == EXPECTED_FLUX


# --- R8 à R10, R13 : la puissance ---------------------------------------------------


@pytest.mark.parametrize(
    ("regimes", "order"),
    [
        (
            {
                "ski_touring": _regime(0.02),
                "short_climb": {"statut": "non_estimable", "motif": "trop peu"},
                "long_climb": _regime(),
            },
            ["long_climb", "ski_touring"],
        ),
        (
            {"short_climb": _regime(0.02), "long_climb": _regime()},
            ["long_climb", "short_climb"],
        ),
    ],
)
def test_r8_the_named_power_is_read(
    tmp_path: Path, regimes: dict[str, object], order: list[str]
) -> None:
    long_climb = _regime(
        0.031,
        seuils=[0.05, 0.01],
        calibration={"declenchee": True, "alpha": 0.008},
        message=MESSAGE,
    )
    regimes = {**regimes, "long_climb": long_climb}
    digest = _power(tmp_path, OLDER_POWER, regimes=regimes)
    _power(tmp_path, POWER_NAME, regimes={"long_climb": _regime(0.9)})
    folder = _estimation(
        tmp_path, "2026-01-02_aaaaaaaaaaaa", extra=_named(digest, OLDER_POWER)
    )
    reading = _read(tmp_path, folder)
    assert reading.power_folder == OLDER_POWER
    assert reading.delta == 0.05
    assert reading.power is not None
    assert [w.regime for w in reading.power] == order
    first = reading.power[0]
    assert first == RegimeWarning("long_climb", 0.031, 0.05, MESSAGE, -0.007)
    second = reading.power[1]
    assert second.established_at_zero == 0.02
    assert second.message is None
    assert second.bias_at_delta is None


def test_r9_a_wrong_digest_or_a_missing_folder_reads_no_power(tmp_path: Path) -> None:
    digest = _power(tmp_path)
    wrong = _estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa", extra=_named("0" * 64))
    reading = _read(tmp_path, wrong)
    assert reading.power is None
    assert reading.power_folder == POWER_NAME
    assert reading.delta is None
    absent = _estimation(
        tmp_path,
        "2026-01-03_aaaaaaaaaaaa",
        extra=_named(digest, "2026-01-09_999999999999"),
    )
    reading = _read(tmp_path, absent)
    assert reading.power is None
    assert reading.power_folder == "2026-01-09_999999999999"
    unnamed = _estimation(tmp_path, "2026-01-04_aaaaaaaaaaaa")
    reading = _read(tmp_path, unnamed)
    assert reading.power_folder is None
    assert reading.power is None


def test_r9_a_named_folder_without_provenance_reads_no_power(tmp_path: Path) -> None:
    digest = _power(tmp_path)
    (tmp_path / POWER_DIR / POWER_NAME / PROVENANCE_FILE).unlink()
    folder = _estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa", extra=_named(digest))
    reading = _read(tmp_path, folder)
    assert reading.power is None
    assert reading.power_folder == POWER_NAME


def _valid_power_at(folder: Path) -> str:
    """Un ``provenance.json`` de puissance valide écrit dans ``folder`` ; rend son
    empreinte."""
    document = {
        "genere_le": "2026-01-01",
        "tables": TABLES,
        "parametres": {"delta": 0.05, "alpha": 0.05},
        "regimes": {"long_climb": _regime()},
    }
    _write(folder / PROVENANCE_FILE, json_text(document))
    return hashlib.sha256((folder / PROVENANCE_FILE).read_bytes()).hexdigest()


def _parent_name(data: Path) -> tuple[str, str]:
    name = "../2026-01-01_eeeeeeeeeeee"
    return name, _valid_power_at(data / RESULTS_DIR / "2026-01-01_eeeeeeeeeeee")


def _null_name(data: Path) -> tuple[str, str]:
    return "2026-01-01_eeee\u0000eeeeeeee", "0" * 64


def _absolute_name(data: Path) -> tuple[str, str]:
    folder = data / "ailleurs" / "2026-01-01_eeeeeeeeeeee"
    return str(folder), _valid_power_at(folder)


@pytest.mark.parametrize("name_of", [_parent_name, _null_name, _absolute_name])
def test_r17_a_power_name_that_is_not_a_result_name_reads_no_power(
    tmp_path: Path, name_of: Any
) -> None:
    """La garde du nom de puissance : un nom qui n'est pas un nom de résultat
    (``RESULT_NAME``) est traité comme une puissance absente ; la lecture reste sous
    ``resultats/Q2/puissance/`` (ni ``..``, ni chemin absolu, même vers une puissance
    valide à la bonne empreinte), et aucun nom ne fait sortir autre chose que
    ``Q2ResultsError`` (un caractère nul ne lève pas ``ValueError``)."""
    _power(tmp_path, OLDER_POWER)
    name, digest = name_of(tmp_path)
    folder = _estimation(
        tmp_path, "2026-01-02_aaaaaaaaaaaa", extra=_named(digest, name)
    )
    reading = _read(tmp_path, folder)
    assert reading.power is None
    assert reading.power_folder == name
    assert reading.delta is None


def test_r10_the_bias_of_scenario_4_at_delta_for_long_climbs_only(
    tmp_path: Path,
) -> None:
    digest = _power(
        tmp_path, regimes={"long_climb": _regime(), "ski_touring": _regime()}
    )
    folder = _estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa", extra=_named(digest))
    reading = _read(tmp_path, folder)
    assert reading.power is not None
    biases = {w.regime: w.bias_at_delta for w in reading.power}
    assert biases == {"long_climb": -0.007, "ski_touring": None}


def test_r10_an_empty_bias_cell_or_no_line_is_none(tmp_path: Path) -> None:
    empty = [["long_climb", 4, 0.05, 3, 0, 0.6, 0.0, 0.1, 0.6, 0.0, 1.1, None]]
    digest = _power(tmp_path, rows=empty)
    folder = _estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa", extra=_named(digest))
    (warning,) = _warnings(tmp_path, folder)
    assert warning.bias_at_delta is None
    other = "2026-01-01_aaaaaaaaaaaa"
    digest = _power(tmp_path, other, rows=[POWER_ROWS[1]])
    folder = _estimation(
        tmp_path, "2026-01-03_aaaaaaaaaaaa", extra=_named(digest, other)
    )
    (warning,) = _warnings(tmp_path, folder)
    assert warning.bias_at_delta is None


def test_r13_the_share_at_zero_is_read_at_key_1(tmp_path: Path) -> None:
    digest = _power(tmp_path, regimes={"long_climb": _regime(0.031)})
    folder = _estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa", extra=_named(digest))
    (warning,) = _warnings(tmp_path, folder)
    assert warning.established_at_zero == 0.031


# --- R14 à R16 : ce qui manque, ce qui est mal formé ----------------------------------


def test_r14_missing_files(tmp_path: Path) -> None:
    digest = _power(tmp_path, power_csv=False)
    folder = _estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa", extra=_named(digest))
    reading = _read(tmp_path, folder)
    assert reading.flux == ()
    assert reading.autocorrelation == ()
    assert reading.figure_html is None
    assert reading.period is None
    assert reading.bounds == {}
    assert reading.power is not None
    assert [w.bias_at_delta for w in reading.power] == [None]
    assert reading.power[0].established_at_zero == 0.031
    assert len(reading.trials) == 1


def test_r14_the_figure_period_and_bounds_are_read(tmp_path: Path) -> None:
    bounds = {
        "long_climb": {
            "statut": "declenchees",
            "journees_imputees": 3,
            "b_basse_fraction": 0.1,
            "b_haute_fraction": None,
        }
    }
    folder = _estimation(
        tmp_path,
        "2026-01-02_aaaaaaaaaaaa",
        extra={
            "periode": {"debut": "2025-03-01", "fin": "2025-12-31"},
            "bornes": bounds,
        },
    )
    _write(folder / FIGURE_HTML, "<p>Résidus é</p>")
    reading = _read(tmp_path, folder)
    assert reading.figure_html == "<p>Résidus é</p>"
    assert reading.period == {"debut": "2025-03-01", "fin": "2025-12-31"}
    assert reading.bounds == bounds


def _power_not_object(data: Path) -> dict[str, object]:
    return _named(_power(data, document=[1, 2]))


def _power_without_delta(data: Path) -> dict[str, object]:
    document = {"genere_le": "2026-01-01", "parametres": {}, "regimes": {}}
    return _named(_power(data, document=document))


def _regimes_not_object(data: Path) -> dict[str, object]:
    document = {"parametres": {"delta": 0.05}, "regimes": [1]}
    return _named(_power(data, document=document))


def _regime_not_object(data: Path) -> dict[str, object]:
    return _named(_power(data, regimes={"long_climb": "calculee"}))


def _a_zero_not_object(data: Path) -> dict[str, object]:
    return _named(_power(data, regimes={"long_climb": _regime(a_zero=[0.1])}))


def _seuils_empty(data: Path) -> dict[str, object]:
    return _named(_power(data, regimes={"long_climb": _regime(seuils=[])}))


def _parametres_not_object(data: Path) -> dict[str, object]:
    document = {"parametres": [0.05], "regimes": {}}
    return _named(_power(data, document=document))


def _named_not_object(data: Path) -> dict[str, object]:
    return {"puissance": "2026-01-01_eeeeeeeeeeee"}


def _bounds_not_object(data: Path) -> dict[str, object]:
    return {"bornes": ["declenchees"]}


def _bound_entry_not_object(data: Path) -> dict[str, object]:
    return {"bornes": {"long_climb": "declenchees"}}


def _period_not_dates(data: Path) -> dict[str, object]:
    return {"periode": {"debut": "01/03/2025", "fin": "2025-12-31"}}


def _power_csv_without_column(data: Path) -> dict[str, object]:
    digest = _power(data)
    _write(data / POWER_DIR / POWER_NAME / POWER_FILE, "regime,scenario\n")
    return _named(digest)


def _named_folder_not_text(data: Path) -> dict[str, object]:
    return {"puissance": {"dossier": 20260101, "empreinte": _power(data)}}


def _named_digest_not_text(data: Path) -> dict[str, object]:
    _power(data)
    return {"puissance": {"dossier": POWER_NAME, "empreinte": 0}}


def _p_etabli_text(data: Path) -> dict[str, object]:
    a_zero = {"1": {"p_etabli": "0.03", "p_absence_effet_utile": 0.0}}
    return _named(_power(data, regimes={"long_climb": _regime(a_zero=a_zero)}))


def _a_zero_1_not_object(data: Path) -> dict[str, object]:
    a_zero = {"1": [0.03, 0.0]}
    return _named(_power(data, regimes={"long_climb": _regime(a_zero=a_zero)}))


def _seuils_not_list(data: Path) -> dict[str, object]:
    return _named(_power(data, regimes={"long_climb": _regime(seuils=0.05)}))


@pytest.mark.parametrize(
    ("spoil", "file"),
    [
        (_power_not_object, "puissance/2026-01-01_eeeeeeeeeeee/provenance.json"),
        (_power_without_delta, "puissance/2026-01-01_eeeeeeeeeeee/provenance.json"),
        (_regimes_not_object, "puissance/2026-01-01_eeeeeeeeeeee/provenance.json"),
        (_regime_not_object, "puissance/2026-01-01_eeeeeeeeeeee/provenance.json"),
        (_a_zero_not_object, "puissance/2026-01-01_eeeeeeeeeeee/provenance.json"),
        (_seuils_empty, "puissance/2026-01-01_eeeeeeeeeeee/provenance.json"),
        (_parametres_not_object, "puissance/2026-01-01_eeeeeeeeeeee/provenance.json"),
        (_named_not_object, "2026-01-02_aaaaaaaaaaaa/provenance.json"),
        (_bounds_not_object, "2026-01-02_aaaaaaaaaaaa/provenance.json"),
        (_bound_entry_not_object, "2026-01-02_aaaaaaaaaaaa/provenance.json"),
        (_period_not_dates, "2026-01-02_aaaaaaaaaaaa/provenance.json"),
        (_power_csv_without_column, "puissance/2026-01-01_eeeeeeeeeeee/puissance.csv"),
        (_named_folder_not_text, "2026-01-02_aaaaaaaaaaaa/provenance.json"),
        (_named_digest_not_text, "2026-01-02_aaaaaaaaaaaa/provenance.json"),
        (_p_etabli_text, "puissance/2026-01-01_eeeeeeeeeeee/provenance.json"),
        (_a_zero_1_not_object, "puissance/2026-01-01_eeeeeeeeeeee/provenance.json"),
        (_seuils_not_list, "puissance/2026-01-01_eeeeeeeeeeee/provenance.json"),
    ],
)
def test_r15_a_malformed_json_or_csv_is_a_q2_results_error(
    tmp_path: Path, spoil: Any, file: str
) -> None:
    """Un JSON ou un CSV mal formé (dont un ``dossier`` ou une ``empreinte`` de
    puissance qui n'est pas un texte, un ``p_etabli`` écrit en texte, un
    ``a_zero["1"]`` qui n'est pas un objet, des ``seuils`` qui ne sont pas une liste)
    lève ``Q2ResultsError``, qui nomme le fichier, et aucune autre exception."""
    folder = _estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa", extra=spoil(tmp_path))
    with pytest.raises(Q2ResultsError) as raised:
        _read(tmp_path, folder)
    assert f"resultats/Q2/{file}" in str(raised.value)


@pytest.mark.parametrize(
    ("file", "text"),
    [
        (TRIALS_FILE, "essai,indice\nP,0\n"),
        (FLUX_FILE, "regime,mesure\nlong_climb,commun\n"),
        (AUTOCORRELATION_FILE, "regime\nlong_climb\n"),
        (AUTOCORRELATION_FILE, "regime,mesure,de,a,paires,correlation\nl,m,x,,1,\n"),
        (
            FLUX_FILE,
            csv_text(FLUX_COLUMNS, [["l", "c", "s", "m", 1, "x", "", 1, None]]),
        ),
        (FIGURE_HTML, b"\xff\xfe<p>"),
        pytest.param(TRIALS_FILE, None, id="case-trop-longue"),
    ],
)
def test_r15_a_malformed_csv_of_the_estimation_is_a_q2_results_error(
    tmp_path: Path, file: str, text: str | bytes | None
) -> None:
    """Un fichier mal formé de l'estimation lève ``Q2ResultsError``, qui le nomme ;
    dont une case de plus de 131 072 caractères (la limite par défaut de
    ``csv.field_size_limit``), que ``csv`` refuse par ``csv.Error``."""
    folder = _estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa")
    if text is None:
        text = _cells(phrase="x" * 131_073)
    if isinstance(text, bytes):
        (folder / file).write_bytes(text)
    else:
        _write(folder / file, text)
    with pytest.raises(Q2ResultsError) as raised:
        _read(tmp_path, folder)
    assert f"resultats/Q2/2026-01-02_aaaaaaaaaaaa/{file}" in str(raised.value)


TRIALS_LABEL = "resultats/Q2/2026-01-02_aaaaaaaaaaaa/essais.csv"


def _without(*dropped: str) -> str:
    """``essais.csv`` de ``_cells()``, sans les colonnes ``dropped``."""
    header, line = list(csv.reader(_cells().splitlines()))
    kept = [i for i, column in enumerate(header) if column not in dropped]
    return csv_text([header[i] for i in kept], [[line[i] for i in kept]])


def _short_line(folder: Path) -> None:
    _write(folder / TRIALS_FILE, ",".join(trial_columns()) + "\nP,0\n")


def _two_missing(folder: Path) -> None:
    _write(folder / TRIALS_FILE, _without("phrase", "statut"))


@pytest.mark.parametrize(
    ("spoil", "message"),
    [
        (_short_line, f"{TRIALS_LABEL}, ligne 2 : cases manquantes"),
        (_two_missing, f"{TRIALS_LABEL} : colonnes absentes : statut, phrase"),
    ],
)
def test_r15_the_exact_messages_of_a_malformed_csv(
    tmp_path: Path, spoil: Any, message: str
) -> None:
    """Les messages que promet le § 5.2, exacts : une ligne trop courte, la deuxième
    du fichier (« <fichier>, ligne 2 : cases manquantes », les lignes comptées depuis
    l'en-tête) ; deux colonnes manquantes (« <fichier> : colonnes absentes : … »,
    nommées dans l'ordre des colonnes attendues, séparées par une virgule)."""
    folder = _estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa")
    spoil(folder)
    with pytest.raises(Q2ResultsError) as raised:
        _read(tmp_path, folder)
    assert str(raised.value) == message


def test_r15_trials_that_are_not_utf8_name_the_file(tmp_path: Path) -> None:
    """Un ``essais.csv`` qui n'est pas de l'UTF-8 (un octet ``0xff``) lève
    ``Q2ResultsError``, qui le nomme."""
    folder = _estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa")
    (folder / TRIALS_FILE).write_bytes(_cells().encode("utf-8") + b"\xff\n")
    with pytest.raises(Q2ResultsError) as raised:
        _read(tmp_path, folder)
    assert TRIALS_LABEL in str(raised.value)


def test_r15_an_unreadable_b_of_the_power_csv_names_the_file(tmp_path: Path) -> None:
    """La case ``b_fraction_par_an`` de la ligne ``long_climb``, scénario 4, de
    ``puissance.csv`` qui ne se relit pas (``abc``) lève ``Q2ResultsError``, qui
    nomme ``puissance.csv``."""
    rows: list[list[object]] = [
        ["long_climb", 4, "abc", 3, 0, 0.6, 0.0, 0.1, 0.6, 0.0, 1.1, -0.007]
    ]
    digest = _power(tmp_path, rows=rows)
    folder = _estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa", extra=_named(digest))
    with pytest.raises(Q2ResultsError) as raised:
        _read(tmp_path, folder)
    assert f"resultats/Q2/puissance/{POWER_NAME}/puissance.csv" in str(raised.value)


def test_r16_the_autocorrelation(tmp_path: Path) -> None:
    folder = _estimation(tmp_path, "2026-01-02_aaaaaaaaaaaa")
    rows = [
        ["long_climb", "M-P", 1, 7, 12, 0.21],
        ["long_climb", "M-P", 8, None, 5, None],
    ]
    _write(folder / AUTOCORRELATION_FILE, csv_text(AUTOCORRELATION_COLUMNS, rows))
    first, last = _read(tmp_path, folder).autocorrelation
    assert first == {
        "regime": "long_climb",
        "mesure": "M-P",
        "de": 1,
        "a": 7,
        "paires": 12,
        "correlation": 0.21,
    }
    assert type(first["a"]) is int
    assert type(first["de"]) is int
    assert type(first["paires"]) is int
    assert last["a"] is None
    assert last["correlation"] is None


# --- R11 : de bout en bout ----------------------------------------------------------


@pytest.fixture(scope="module")
def written(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """``mperf q2 puissance`` puis ``mperf q2`` sur le petit monde, une fois pour le
    module (le mécanisme de ``tests/test_cli_q2.py``) ; rend le dossier des données."""
    for library in ("numpy", "scipy", "pyarrow", "plotly"):
        pytest.importorskip(library)
    from fixtures import q2_run
    from fixtures.processed import COMMIT
    from mountain_perf import cli, gitstate
    from mountain_perf.analyse.q2 import parameters, power
    from mountain_perf.cli import main
    from mountain_perf.gitstate import GitState

    folder = tmp_path_factory.mktemp("q2_relecture")
    q2_run.write_world(folder)
    with pytest.MonkeyPatch.context() as patch:
        for name in BLAS:
            patch.setenv(name, os.environ.get(name, "0"))
        patch.setenv("MPA_DATA_DIR", str(folder))
        patch.setattr(gitstate, "git_state", lambda d: GitState(COMMIT, False))
        patch.setattr(cli, "_today", lambda: q2_run.DAY)
        patch.setattr(parameters, "q2_parameters", q2_run.reduced_parameters)
        patch.setattr(power, "power_grids", q2_run.reduced_grids)
        with contextlib.redirect_stdout(io.StringIO()):
            assert main(["q2", "puissance"]) == 0
            assert main(["q2"]) == 0
    return folder


def test_r11_a_folder_written_by_mperf_q2_reads_back(written: Path) -> None:
    """Un dossier écrit par la vraie commande se relit sans erreur : 24 essais, la
    puissance lue, dont le ``RegimeWarning`` des montées longues et son biais à
    ``delta`` (non ``None``), la figure, le flux et l'autocorrélation."""
    latest = latest_estimation(written, None)
    assert latest is not None
    assert latest.unreadable == 0
    reading = read_estimation(written, latest.estimation)
    assert len(reading.trials) == 24
    assert [t["indice"] for t in reading.trials] == list(range(24))
    assert reading.trials[0]["essai"] == "P"
    assert reading.power is not None
    assert reading.power_folder is not None
    assert reading.delta == 0.05
    assert reading.figure_html is not None
    assert reading.flux
    assert reading.autocorrelation
    assert reading.autocorrelation[-1]["a"] is None
    assert all(type(r["de"]) is int for r in reading.autocorrelation)
    long_climb = [w for w in reading.power if w.regime == "long_climb"]
    assert len(long_climb) == 1
    assert long_climb[0].bias_at_delta is not None
