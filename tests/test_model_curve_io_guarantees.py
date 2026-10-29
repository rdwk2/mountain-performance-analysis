"""Les garanties de l'écriture d'une courbe estimée (M6b, ``docs/decisions/0017`` ;
§ 6.2 du brief M6b-1) que la relecture de la PR #37 a trouvées sans test : l'ordre
d'écriture des deux fichiers, le refus d'écraser à l'écriture même, le texte du
compagnon et les cellules du CSV, les bornes du fichier étendu à la lecture.

Les courbes sont inventées (règle 1) ; les valeurs attendues sont recopiées du brief,
pas des constantes qu'elles éprouvent."""

from __future__ import annotations

import csv
import dataclasses
import json
import math
from pathlib import Path
from typing import Any

import pytest

from mountain_perf.estimation.curve import curve_file_rows
from mountain_perf.model.curve_io import CurveFileRow, read_curve, write_curve
from mountain_perf.schemas import Sport
from test_estimation_curve import GRADES, activity, estimate, interval
from test_model_curve_io_extended import (
    COLUMN,
    ESTIMATION,
    PROVENANCE,
    ROWS,
    companion,
    data_cells,
    parameters,
    replace_cell,
    written,
)

BRIEF_KEYS = [
    "sport",
    "activity_count",
    "hr_center_bpm",
    "hr_width_bpm",
    "hr_lag_s",
    "date_from",
    "date_to",
    "source_activity_types",
    "min_duration_s",
    "max_duration_s",
    "max_elapsed_s",
    "athlete_ref",
    "estimator",
    "generated_at",
    "estimation",
]
"""L'ordre des clés du compagnon, recopié du § 6.2 du brief."""


def fail_on(monkeypatch: pytest.MonkeyPatch, suffix: str, error: BaseException) -> None:
    """``Path.open`` lève ``error`` pour un fichier dont le nom finit par ``suffix``."""
    original = Path.open

    def opened(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.name.endswith(suffix):
            raise error
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)


# --- L'ordre d'écriture et le refus d'écraser ---------------------------------------


def test_the_companion_is_written_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le compagnon s'écrit d'abord : s'il échoue, aucun fichier, pas même le CSV."""
    fail_on(monkeypatch, ".meta.json", OSError("disque plein"))
    with pytest.raises(OSError, match="disque plein"):
        written(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_any_csv_failure_takes_the_companion_away(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """« Si l'écriture du CSV échoue (toute exception), le compagnon est retiré » : une
    ``RuntimeError``, pas seulement une ``OSError``."""
    fail_on(monkeypatch, ".csv", RuntimeError("panne"))
    with pytest.raises(RuntimeError, match="panne"):
        written(tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("existing", ["courbe.csv", "courbe.meta.json"])
def test_a_file_appearing_after_the_check_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: str
) -> None:
    """Le fichier apparaît entre le contrôle d'existence et l'écriture : l'ouverture en
    ``"xb"`` le refuse, il reste tel quel, et rien d'autre n'est laissé."""
    (tmp_path / existing).write_bytes(b"autre")
    monkeypatch.setattr(Path, "exists", lambda self: False)
    with pytest.raises(FileExistsError):
        written(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == [existing]
    assert (tmp_path / existing).read_bytes() == b"autre"


def test_a_non_finite_estimation_value_writes_nothing(tmp_path: Path) -> None:
    """Une valeur non finie du document de l'estimation : ``ValueError`` avant tout
    écrit."""
    path = tmp_path / "courbe.csv"
    with pytest.raises(ValueError, match="JSON compliant"):
        write_curve(path, ROWS, Sport.FOOT, PROVENANCE, {"level": {"p10": math.nan}})
    assert list(tmp_path.iterdir()) == []


# --- Le texte du compagnon ----------------------------------------------------------


def test_the_companion_text(tmp_path: Path) -> None:
    """Les clés dans l'ordre du § 6.2 ; « θc » en clair (``ensure_ascii=False``) ;
    ``indent=2`` ; un ``"\\n"`` final, un seul ; ``generated_at`` et les dates en
    ``isoformat()``."""
    raw = companion(written(tmp_path)).read_bytes()
    text = raw.decode("utf-8")
    assert list(json.loads(text)) == BRIEF_KEYS
    assert '"estimator": "estimation synthétique, θc",' in text
    assert text.startswith('{\n  "sport": "foot",\n  "activity_count": 7,\n')
    assert raw.endswith(b"\n}\n")
    assert not raw.endswith(b"\n\n")
    assert '\n  "generated_at": "2026-07-01T12:00:00.123456+00:00",\n' in text
    assert '\n  "date_from": "2026-01-01",\n' in text
    assert '\n  "date_to": "2026-06-30",\n' in text
    assert '\n  "estimation": {\n    "value": "somme",\n' in text


def test_the_types_are_sorted(tmp_path: Path) -> None:
    """Les types de la source triés, sur quatre types : deux ne tiendraient leur ordre
    que par hasard, selon ``PYTHONHASHSEED``."""
    types = frozenset({"trail_running", "hiking", "running", "backcountry_skiing"})
    provenance = dataclasses.replace(PROVENANCE, source_activity_types=types)
    path = tmp_path / "courbe.csv"
    write_curve(path, ROWS, Sport.FOOT, provenance, ESTIMATION)
    meta = json.loads(companion(path).read_bytes().decode("utf-8"))
    assert meta["source_activity_types"] == [
        "backcountry_skiing",
        "hiking",
        "running",
        "trail_running",
    ]


# --- Les cellules du CSV ------------------------------------------------------------


def test_the_csv_cells(tmp_path: Path) -> None:
    """``hr`` par ``repr`` (vide pour ``None``), ``vam_mh`` =
    ``repr(speed_ms × (grade_pct / 100) × 3600)``, ``time_min`` par ``repr``."""
    rows = (dataclasses.replace(ROWS[0], time_min=12.345), *ROWS[1:])
    path = written(tmp_path, rows)
    first = data_cells(path, 1)
    assert first[COLUMN["hr"]] == "128.25"
    assert first[COLUMN["vam_mh"]] == repr(2.5 * (-12.5 / 100) * 3600)
    assert first[COLUMN["time_min"]] == "12.345"
    assert data_cells(path, 2)[COLUMN["hr"]] == ""


def heart_rate_estimate_rows() -> tuple[CurveFileRow, ...]:
    """Les lignes d'une estimation de cinq activités, FC posée, vitesses différentes :
    des vitesses, des FC et des temps qui ne tombent pas juste."""
    outings = []
    for k in range(5):
        speed = 2.0 + 0.1 * k
        outings.append(
            activity(
                f"u{k}",
                [
                    interval(
                        g, 50.0, 50.0 / speed, heart_rate_bpm=130.0 + 3 * k + 10 * g
                    )
                    for g in GRADES
                    for _ in range(round(900 * speed / 50))
                ],
            )
        )
    return curve_file_rows(estimate(outings))


def test_the_csv_cells_of_an_estimate(tmp_path: Path) -> None:
    """Sur les lignes d'une estimation : chaque cellule ``vam_mh``, ``hr`` et
    ``time_min`` est le ``repr`` de la règle du § 6.2, à l'octet."""
    rows = heart_rate_estimate_rows()
    path = written(tmp_path, rows)
    with path.open(encoding="utf-8", newline="") as stream:
        cells = list(csv.DictReader(stream))
    assert len(cells) == len(rows)
    for cell, row in zip(cells, rows, strict=True):
        assert row.mean_hr_bpm is not None
        assert cell["vam_mh"] == repr(
            row.speed_ms * (float(row.grade_pct) / 100) * 3600
        )
        assert cell["hr"] == repr(row.mean_hr_bpm)
        assert cell["time_min"] == repr(row.time_min)


# --- Les bornes du fichier étendu à la lecture --------------------------------------


@pytest.mark.parametrize("value", ["0.01", "100.0"])
def test_the_elapsed_speed_bounds_are_read(tmp_path: Path, value: str) -> None:
    """La vitesse écoulée se lit à ses bornes, comprises : ``[0.01 ; 100.0]`` km/h
    (§ 6.2)."""
    path = written(tmp_path)
    replace_cell(path, "kmh_elapsed", value)
    assert read_curve(path, parameters()).bin_count_read == 4


def test_zero_activities_are_read(tmp_path: Path) -> None:
    """``activities`` se lit à 0 : un entier ``>= 0`` (§ 6.2) ; ``sample_count`` le
    reçoit."""
    path = written(tmp_path)
    replace_cell(path, "activities", "0")
    curve = read_curve(path, parameters()).curve
    assert tuple(curve.sample_count) == (0, 7, 7, 5)
