"""Le fichier de courbe étendu (M6b, ``docs/decisions/0017``) : l'écriture d'une courbe
et de son compagnon, jamais réécrite ; la lecture de l'en-tête étendu et de l'ancien ;
les champs de M6b du compagnon ; la règle du support, appelée ; ``check_curve_rows``.

Les courbes sont inventées (règle 1)."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from mountain_perf.model.curve_io import (
    CURVE_PARAMETER_SPECS,
    EXTENDED_HEADER,
    CurveBin,
    CurveError,
    CurveFileRow,
    _select_support,
    check_curve_rows,
    read_curve,
    select_support,
    write_curve,
)
from mountain_perf.schemas import ContractError, CurveProvenance, ParameterSet, Sport

FIXTURES = Path(__file__).parent / "fixtures"

PROVENANCE = CurveProvenance(
    activity_count=7,
    hr_center_bpm=150.0,
    hr_width_bpm=10.0,
    date_from=date(2026, 1, 1),
    date_to=date(2026, 6, 30),
    source_activity_types=frozenset({"trail_running", "running"}),
    min_duration_s=1800.0,
    estimator="estimation synthétique, θc",
    generated_at=datetime(2026, 7, 1, 12, 0, 0, 123456, tzinfo=UTC),
    athlete_ref="x",
    max_duration_s=18000.0,
    max_elapsed_s=7200.0,
    hr_lag_s=60.0,
)

ROWS = (
    CurveFileRow("-12.5", 2.5, 128.25, 30.0, 2.25, 6, 0.125),
    CurveFileRow("-1.25", 3.0, None, 45.5, 2.75, 7, None),
    CurveFileRow("1.25", 2.75, 140.0, 60.0, 2.5, 7, 0.0625),
    CurveFileRow("13.75", 1.0, 150.5, 25.0, 0.875, 5, None),
)

ESTIMATION: dict[str, object] = {
    "value": "somme",
    "level": {"p10": -0.1, "p50": 0.0, "p90": 0.1},
}

COLUMN = {name: i for i, name in enumerate(EXTENDED_HEADER)}


def parameters() -> ParameterSet:
    return ParameterSet(CURVE_PARAMETER_SPECS)


def written(tmp_path: Path, rows: tuple[CurveFileRow, ...] = ROWS) -> Path:
    """Écrit la courbe de ``rows`` sous ``tmp_path`` et rend le chemin du CSV."""
    path = tmp_path / "courbe.csv"
    write_curve(path, rows, Sport.FOOT, PROVENANCE, ESTIMATION)
    return path


def companion(path: Path) -> Path:
    return path.with_name(f"{path.stem}.meta.json")


def data_cells(path: Path, line: int) -> list[str]:
    """Les cellules de la ligne de données ``line`` (1 pour la première)."""
    return path.read_bytes().decode("utf-8").split("\n")[line].split(",")


def replace_cell(path: Path, column: str, value: str) -> None:
    """Remplace la cellule ``column`` de la première ligne de données."""
    lines = path.read_bytes().decode("utf-8").split("\n")
    cells = lines[1].split(",")
    cells[COLUMN[column]] = value
    lines[1] = ",".join(cells)
    path.write_bytes("\n".join(lines).encode("utf-8"))


def rewrite_companion(path: Path, **changes: Any) -> None:
    meta_path = companion(path)
    meta = json.loads(meta_path.read_bytes().decode("utf-8"))
    meta.update(changes)
    meta_path.write_bytes(json.dumps(meta, ensure_ascii=False).encode("utf-8"))


# --- L'aller-retour et les fichiers --------------------------------------------------


def test_the_written_curve_reads_back(tmp_path: Path) -> None:
    """``read_curve`` relit la courbe écrite : ses quatre tranches, le nombre
    d'activités dans ``sample_count``, aucune dispersion, la provenance entière."""
    result = read_curve(written(tmp_path), parameters())
    curve = result.curve
    assert result.bin_count_read == 4
    assert curve.sport is Sport.FOOT
    assert tuple(curve.grade) == (-0.125, -0.0125, 0.0125, 0.1375)
    for speed, expected in zip(curve.speed_ms, (2.5, 3.0, 2.75, 1.0), strict=True):
        assert speed == pytest.approx(expected, rel=1e-15)
    assert tuple(curve.sample_count) == (6, 7, 7, 5)
    assert curve.dispersion_ms is None
    assert curve.estimation == PROVENANCE


def test_the_two_files(tmp_path: Path) -> None:
    """Fins de ligne ``\\n`` ; l'en-tête étendu ; une FC et une forme absentes écrites
    vides ; le compagnon porte l'estimateur, l'estimation donnée et les types triés."""
    path = written(tmp_path)
    csv_bytes = path.read_bytes()
    meta_bytes = companion(path).read_bytes()
    assert b"\r\n" not in csv_bytes
    assert b"\r\n" not in meta_bytes
    assert csv_bytes.decode("utf-8").split("\n")[0] == ",".join(EXTENDED_HEADER)
    second = data_cells(path, 2)
    assert second[COLUMN["hr"]] == ""
    assert second[COLUMN["shape_iqr"]] == ""
    meta = json.loads(meta_bytes.decode("utf-8"))
    assert meta["estimator"] == "estimation synthétique, θc"
    assert meta["estimation"] == ESTIMATION
    assert meta["source_activity_types"] == ["running", "trail_running"]


def test_the_shape_is_written_as_is(tmp_path: Path) -> None:
    """La forme est un logarithme sans unité, jamais convertie comme une vitesse
    (``0017``, P4.4) ; relue, elle n'est pas une dispersion."""
    path = written(tmp_path)
    first = data_cells(path, 1)
    assert first[COLUMN["shape_iqr"]] == repr(0.125)
    assert first[COLUMN["kmh"]] == repr(2.5 * 3.6)
    assert first[COLUMN["kmh_elapsed"]] == repr(2.25 * 3.6)
    assert first[COLUMN["activities"]] == "6"
    assert first[COLUMN["grade_pct"]] == "-12.5"
    assert read_curve(path, parameters()).curve.dispersion_ms is None


# --- Jamais réécrite ----------------------------------------------------------------


def test_a_curve_is_never_rewritten(tmp_path: Path) -> None:
    """Une seconde écriture au même chemin est refusée, les deux fichiers inchangés à
    l'octet."""
    path = written(tmp_path)
    before = (path.read_bytes(), companion(path).read_bytes())
    with pytest.raises(CurveError, match="jamais réécrite"):
        written(tmp_path)
    assert (path.read_bytes(), companion(path).read_bytes()) == before


def test_a_lone_companion_is_enough_to_refuse(tmp_path: Path) -> None:
    """Un compagnon seul déjà là : refusé, il est nommé, aucun CSV écrit."""
    (tmp_path / "courbe.meta.json").write_bytes(b"{}")
    with pytest.raises(CurveError, match=r"courbe\.meta\.json"):
        written(tmp_path)
    assert not (tmp_path / "courbe.csv").exists()


def test_a_failing_csv_takes_its_companion_away(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si l'écriture du CSV échoue, le compagnon écrit avant lui est retiré et l'erreur
    remonte ; la tentative suivante réussit."""
    original = Path.open

    def opened(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.suffix == ".csv":
            raise OSError("disque plein")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(OSError, match="disque plein"):
        written(tmp_path)
    assert list(tmp_path.iterdir()) == []
    monkeypatch.undo()
    path = written(tmp_path)
    assert path.exists()
    assert companion(path).exists()


def test_an_unreadable_grade_writes_nothing(tmp_path: Path) -> None:
    """Une pente illisible sort avant tout écrit."""
    rows = (dataclasses.replace(ROWS[0], grade_pct="moins douze"), *ROWS[1:])
    with pytest.raises(ValueError, match="could not convert"):
        written(tmp_path, rows)
    assert list(tmp_path.iterdir()) == []


# --- La lecture des cellules étendues -----------------------------------------------


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("activities", "1.5", "activities"),
        ("activities", "-1", "activities"),
        ("activities", "", "activities"),
        ("kmh_elapsed", "0", "vitesse écoulée"),
        ("kmh_elapsed", "", "kmh_elapsed"),
        ("shape_iqr", "-0.01", "shape_iqr"),
        ("shape_iqr", "nan", "shape_iqr"),
        ("kmh", "", "kmh"),
    ],
)
def test_extended_cells_are_checked(
    tmp_path: Path, column: str, value: str, message: str
) -> None:
    """Chaque cellule étendue est contrôlée à la lecture ; seules ``hr`` et
    ``shape_iqr`` peuvent être vides."""
    path = written(tmp_path)
    replace_cell(path, column, value)
    with pytest.raises(CurveError, match=message):
        read_curve(path, parameters())


def test_the_old_header_is_read_as_before() -> None:
    """La courbe synthétique, à l'ancien en-tête, se lit ; ses quatre champs de M6b
    sont absents."""
    provenance = read_curve(
        FIXTURES / "courbe_synthetique.csv", parameters()
    ).curve.estimation
    assert provenance.athlete_ref is None
    assert provenance.max_duration_s is None
    assert provenance.max_elapsed_s is None
    assert provenance.hr_lag_s is None


def test_the_old_header_refuses_an_empty_heart_rate(tmp_path: Path) -> None:
    """Seul l'en-tête étendu permet une cellule ``hr`` vide."""
    lines = (FIXTURES / "courbe_synthetique.csv").read_bytes().decode().split("\n")
    cells = lines[1].split(",")
    cells[2] = ""
    lines[1] = ",".join(cells)
    path = tmp_path / "courbe.csv"
    path.write_bytes("\n".join(lines).encode("utf-8"))
    companion(path).write_bytes(
        (FIXTURES / "courbe_synthetique.meta.json").read_bytes()
    )
    with pytest.raises(CurveError, match="hr"):
        read_curve(path, parameters())


# --- Les champs de M6b du compagnon -------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [{"athlete_ref": ""}, {"athlete_ref": 3}, {"max_elapsed_s": "deux heures"}],
)
def test_unreadable_m6b_fields_are_curve_errors(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    path = written(tmp_path)
    rewrite_companion(path, **changes)
    with pytest.raises(CurveError):
        read_curve(path, parameters())


@pytest.mark.parametrize(
    "changes",
    [
        {"hr_center_bpm": None, "hr_width_bpm": None},
        {"max_duration_s": 1000.0},
    ],
)
def test_incoherent_m6b_fields_are_contract_errors(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    """Le décalage seul, sans filtre de FC ; une durée maximale sous la minimale."""
    path = written(tmp_path)
    rewrite_companion(path, **changes)
    with pytest.raises(ContractError):
        read_curve(path, parameters())


def test_null_m6b_fields_are_absent(tmp_path: Path) -> None:
    path = written(tmp_path)
    rewrite_companion(
        path, athlete_ref=None, max_duration_s=None, max_elapsed_s=None, hr_lag_s=None
    )
    provenance = read_curve(path, parameters()).curve.estimation
    assert provenance == dataclasses.replace(
        PROVENANCE,
        athlete_ref=None,
        max_duration_s=None,
        max_elapsed_s=None,
        hr_lag_s=None,
    )


# --- La règle du support et check_curve_rows ----------------------------------------


def test_the_support_rule_is_the_one_of_read_curve() -> None:
    """``select_support`` enveloppe la sélection de ``read_curve`` : appelée, ni alias
    ni copie."""
    assert select_support is not _select_support
    bins = [
        CurveBin(-0.2, 1.0, 5.0, 300),
        CurveBin(-0.1, 1.0, 30.0, 1800),
        CurveBin(0.1, 1.0, 30.0, 1800),
        CurveBin(0.2, 1.0, 5.0, 300),
    ]
    kept, discarded = select_support(bins, 10.0)
    assert (kept, discarded) == _select_support(bins, 10.0)
    assert [curve_bin.grade for curve_bin in kept] == [-0.1, 0.1]
    assert len(discarded) == 2


def test_check_curve_rows_says_what_read_curve_would_do() -> None:
    """``None`` pour une courbe projetable ; le message du support sinon."""
    assert check_curve_rows(ROWS, 10.0) is None
    message = check_curve_rows(ROWS, 50.0)
    assert message is not None
    assert "tranche centrale" in message


def test_an_unreadable_row_names_its_slice() -> None:
    """Une ligne que ``read_curve`` refuserait n'est pas écrite : l'erreur dit la
    tranche (``0017``, P3.7)."""
    rows = (dataclasses.replace(ROWS[0], speed_ms=500.0), *ROWS[1:])
    with pytest.raises(CurveError) as caught:
        check_curve_rows(rows, 10.0)
    assert str(caught.value).startswith(
        "La tranche -12.5 % serait illisible par read_curve, la courbe n'est pas "
        "écrite : ligne 2 : vitesse 1800.0 km/h"
    )


def test_the_slice_named_is_the_one_at_fault() -> None:
    """La tranche nommée est celle en cause, pas la première."""
    rows = (*ROWS[:2], dataclasses.replace(ROWS[2], speed_ms=500.0), ROWS[3])
    with pytest.raises(CurveError) as caught:
        check_curve_rows(rows, 10.0)
    assert str(caught.value).startswith("La tranche 1.25 %")
    assert "ligne 4 : vitesse" in str(caught.value)


def test_an_error_of_no_single_row_is_raised_as_is() -> None:
    """Une pente en double ne vient d'aucune ligne seule : l'erreur de lecture telle
    quelle."""
    rows = (ROWS[0], dataclasses.replace(ROWS[1], grade_pct="-12.5"), *ROWS[2:])
    with pytest.raises(CurveError) as caught:
        check_curve_rows(rows, 10.0)
    assert str(caught.value) == "Pente en double : -12.5 %."


@pytest.mark.parametrize(("time_min", "projectable"), [(9.999, False), (10.0, True)])
def test_the_central_slice_threshold(time_min: float, projectable: bool) -> None:
    rows = (ROWS[0], dataclasses.replace(ROWS[1], time_min=time_min), *ROWS[2:])
    message = check_curve_rows(rows, 10.0)
    if projectable:
        assert message is None
    else:
        assert message is not None
        assert "tranche centrale" in message


def test_no_positive_slice_is_a_support_message() -> None:
    message = check_curve_rows(ROWS[:2], 10.0)
    assert message is not None
    assert "aucune tranche de pente positive" in message
