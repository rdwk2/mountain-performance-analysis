"""Le seuil des diagnostics d'une estimation (OG-1, ``docs/decisions/0020``,
décision R) : l'estimation calcule son niveau, sa forme et son verdict au seuil qu'on
lui donne et l'écrit au compagnon ; une lecture garde le sien, un filtre sans recalcul.

Les courbes et l'``interim/`` sont inventés (règle 1) ; la commande ne se lance jamais
sur le vrai dossier des données : elle se teste par ``main([...])``."""

from __future__ import annotations

import dataclasses
import json
import math
from datetime import UTC, date, datetime
from itertools import product
from pathlib import Path
from typing import Any

import pytest

from fixtures.processed import COMMIT, write_interim
from mountain_perf import gitstate
from mountain_perf.cli import main
from mountain_perf.config import data_dir
from mountain_perf.estimation.curve import (
    SUPPORT_THRESHOLD_MIN,
    CurveEstimate,
    estimate_curve,
)
from mountain_perf.estimation.intervals import ActivityIntervals
from mountain_perf.gitstate import GitState
from mountain_perf.model import PROJECTION_PARAMETER_SPECS
from mountain_perf.model.curve_io import (
    CURVE_PARAMETER_SPECS,
    DEFAULT_SUPPORT_THRESHOLD_MIN,
    read_curve,
    write_curve,
)
from mountain_perf.runs import project_route
from mountain_perf.schemas import (
    SUPPORT_THRESHOLD_RANGE_MIN,
    ContractError,
    CurveProvenance,
    ParameterSet,
    Sport,
)
from test_estimation_curve import DEFAULTS, GRADES, selection, uniform
from test_model_curve_io_extended import ROWS

FIXTURES = Path(__file__).parent / "fixtures"
GPX = FIXTURES / "mini_11.gpx"
COMPANION = FIXTURES / "courbe_synthetique.meta.json"

PROVENANCE = CurveProvenance(
    activity_count=1,
    hr_center_bpm=None,
    hr_width_bpm=None,
    date_from=date(2026, 1, 1),
    date_to=date(2026, 1, 31),
    source_activity_types=frozenset({"trail_running"}),
    min_duration_s=None,
    estimator="estimation synthétique",
    generated_at=datetime(2026, 2, 1, tzinfo=UTC),
)

SEVEN = """grade_pct,kmh,hr,vam_mh,time_min
-10.0,9.0,135,0,60.0
0.0,10.8,140,0,120.0
10.0,5.4,150,540,90.0
20.0,4.0,155,800,30.0
30.0,3.0,160,900,7.0
"""
"""Une courbe à l'ancien en-tête, dont la tranche de +30 % n'a que 7 min."""

WINDOW = ["--from", "2024-03-01", "--to", "2024-03-31", "--athlete", "x"]


@pytest.fixture
def clean_clone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un clone propre au commit des fixtures."""
    monkeypatch.setattr(
        gitstate, "git_state", lambda directory: GitState(COMMIT, False)
    )


def curve_files(folder: Path, text: str, **keys: Any) -> Path:
    """``courbe.csv`` de texte ``text`` sous ``folder``, et le compagnon de la fixture
    changé de ``keys`` ; rend le chemin du CSV."""
    meta = json.loads(COMPANION.read_bytes().decode("utf-8"))
    meta.update(keys)
    (folder / "courbe.meta.json").write_bytes(json.dumps(meta).encode("utf-8"))
    path = folder / "courbe.csv"
    path.write_bytes(text.encode("utf-8"))
    return path


def at(threshold_min: float) -> ParameterSet:
    """Les paramètres d'une lecture au seuil ``threshold_min``."""
    return ParameterSet(CURVE_PARAMETER_SPECS, {"curve_min_support_min": threshold_min})


def _edge_case() -> list[ActivityIntervals]:
    """Cinq activités à 2 m/s sur les pentes basses, et la plus raide portée par une
    seule, à 1 m/s pendant 420 s : sa tranche a 7 min."""
    outings = [uniform(f"u{k}", 2.0, GRADES[:-1]) for k in range(5)]
    outings.append(uniform("e", 1.0, GRADES[-1:], 420.0))
    return outings


def _estimated(outings: list[ActivityIntervals], **options: float) -> CurveEstimate:
    refs = [outing.activity_ref for outing in outings]
    return estimate_curve(outings, refs, selection(), DEFAULTS, **options)


def _companion(name: str = "saison") -> dict[str, Any]:
    path = data_dir() / "reference" / f"{name}.meta.json"
    loaded: dict[str, Any] = json.loads(path.read_bytes().decode("utf-8"))
    return loaded


# --- Le champ de la provenance ------------------------------------------------------


def test_the_diagnostic_threshold_is_not_said_by_default() -> None:
    assert PROVENANCE.diagnostic_support_threshold_min is None


def _provenance(threshold_min: float) -> CurveProvenance:
    return dataclasses.replace(
        PROVENANCE, diagnostic_support_threshold_min=threshold_min
    )


@pytest.mark.parametrize("threshold", [0.0, 5.0, 10.0, 1440.0])
def test_a_threshold_in_the_guardrails_is_kept(threshold: float) -> None:
    assert _provenance(threshold).diagnostic_support_threshold_min == threshold


@pytest.mark.parametrize("threshold", [-1.0, 1440.5, math.nan, math.inf])
def test_a_threshold_outside_the_guardrails_is_refused(threshold: float) -> None:
    with pytest.raises(ContractError, match="diagnostic_support_threshold_min"):
        _provenance(threshold)


def test_the_guardrails_are_those_of_the_reading_parameter() -> None:
    spec = CURVE_PARAMETER_SPECS[0]
    assert spec.name == "curve_min_support_min"
    assert (spec.minimum, spec.maximum) == SUPPORT_THRESHOLD_RANGE_MIN
    assert SUPPORT_THRESHOLD_RANGE_MIN == (0.0, 1440.0)
    assert (
        spec.default == DEFAULT_SUPPORT_THRESHOLD_MIN == SUPPORT_THRESHOLD_MIN == 10.0
    )


# --- Le compagnon, écrit et relu ----------------------------------------------------


def test_the_diagnostic_threshold_is_written_and_read_back(tmp_path: Path) -> None:
    path = tmp_path / "courbe.csv"
    provenance = _provenance(5.0)
    write_curve(path, ROWS, Sport.FOOT, provenance, {"value": "somme"})
    meta = json.loads((tmp_path / "courbe.meta.json").read_bytes().decode("utf-8"))
    assert meta["diagnostic_support_threshold_min"] == 5.0
    assert read_curve(path, at(0)).curve.estimation == provenance


def test_an_old_curve_says_no_diagnostic_threshold(tmp_path: Path) -> None:
    result = read_curve(curve_files(tmp_path, SEVEN), at(10))
    assert result.curve.estimation.diagnostic_support_threshold_min is None


def test_a_null_diagnostic_threshold_is_none(tmp_path: Path) -> None:
    path = curve_files(tmp_path, SEVEN, diagnostic_support_threshold_min=None)
    assert (
        read_curve(path, at(10)).curve.estimation.diagnostic_support_threshold_min
        is None
    )


@pytest.mark.parametrize(
    ("reading", "kept", "diagnostics"),
    [
        (reading, kept, diagnostics)
        for (reading, kept), diagnostics in product(
            ((5.0, 5), (10.0, 4), (0.0, 5)), (None, 5.0, 10.0, 20.0)
        )
    ],
)
def test_the_reading_threshold_is_a_filter_whatever_the_diagnostics(
    tmp_path: Path, reading: float, kept: int, diagnostics: float | None
) -> None:
    """La lecture filtre à son seuil, quel que soit celui des diagnostics, jamais un
    refus ; celui des diagnostics est relu tel quel."""
    path = curve_files(tmp_path, SEVEN, diagnostic_support_threshold_min=diagnostics)
    result = read_curve(path, at(reading))
    assert result.bin_count_kept == kept
    assert result.curve.estimation.diagnostic_support_threshold_min == diagnostics


# --- L'estimation au seuil donné ----------------------------------------------------


def test_the_level_follows_the_threshold() -> None:
    """Par défaut = 10 explicite ; à 5 min, mêmes tranches, et la tranche de 7 min
    entre au support : l'activité qui la porte n'a plus de niveau prolongé."""
    outings = _edge_case()
    default = _estimated(outings)
    at_ten = _estimated(outings, support_threshold_min=10.0)
    at_five = _estimated(outings, support_threshold_min=5.0)
    assert default == at_ten
    assert at_five.bins[0].speed_ms == at_ten.bins[0].speed_ms
    assert [b.speed_ms for b in at_five.bins] == [b.speed_ms for b in at_ten.bins]
    assert at_five.level is not None
    assert at_ten.level is not None
    assert at_five.level.p90 == 0.0
    assert at_ten.level.p90 != 0.0


@pytest.mark.parametrize("threshold", [-1.0, 1441.0, math.nan])
def test_the_estimation_refuses_a_threshold_outside(threshold: float) -> None:
    with pytest.raises(ContractError, match="support_threshold_min"):
        _estimated(_edge_case(), support_threshold_min=threshold)


def test_the_support_range_follows_the_threshold() -> None:
    outings = _edge_case()
    assert _estimated(outings).support_grade_range == (GRADES[0], GRADES[-2])
    at_five = _estimated(outings, support_threshold_min=5.0)
    assert at_five.support_grade_range == (GRADES[0], GRADES[-1])


# --- La commande --------------------------------------------------------------------


@pytest.mark.usefixtures("clean_clone")
def test_mperf_curve_writes_ten_by_default() -> None:
    write_interim(data_dir())
    assert main(["curve", "saison", *WINDOW]) == 0
    assert _companion()["diagnostic_support_threshold_min"] == 10.0


@pytest.mark.usefixtures("clean_clone")
def test_mperf_curve_writes_the_given_threshold(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_interim(data_dir())
    assert main(["curve", "saison", *WINDOW, "--min-support-min", "5"]) == 0
    assert capsys.readouterr().out.splitlines()[0].endswith("d'au moins 5 min")
    assert _companion()["diagnostic_support_threshold_min"] == 5.0


@pytest.mark.usefixtures("clean_clone")
def test_mperf_curve_refuses_a_threshold_outside(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_interim(data_dir())
    assert main(["curve", "saison", *WINDOW, "--min-support-min", "-1"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("Erreur : ")
    assert "curve_min_support_min" in err
    assert not (data_dir() / "reference").exists()


@pytest.mark.usefixtures("clean_clone")
def test_mperf_curve_writes_the_support_range() -> None:
    write_interim(data_dir())
    assert main(["curve", "saison", *WINDOW]) == 0
    assert _companion()["estimation"]["support_grade_range"] == [-0.0125, 0.0125]


@pytest.mark.usefixtures("clean_clone")
def test_mperf_curve_at_a_whole_day_threshold(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Au seuil de 1 440 min, aucune tranche ne l'atteint : la courbe s'écrit, non
    projetable, sans niveau ni plage, et la commande compte à ce seuil."""
    write_interim(data_dir())
    assert main(["curve", "saison", *WINDOW, "--min-support-min", "1440"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == (
        "activités retenues : 1 sur 2 candidates ; tranches : 13, dont 0 d'au moins "
        "1440 min"
    )
    assert lines[2] == "  activités avec un niveau : 0 ; écoulé / M : 1.0087"
    assert lines[3].startswith(
        "Courbe non projetable par read_curve : La tranche centrale de pente -1.25 % "
        "n'a que"
    )
    meta = _companion()
    assert meta["diagnostic_support_threshold_min"] == 1440.0
    assert meta["estimation"]["projectable"] is False
    assert meta["estimation"]["level"] is None
    assert meta["estimation"]["support_grade_range"] is None


# --- Les lectures gardent leur seuil ------------------------------------------------


def test_mperf_project_reads_at_its_own_threshold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    curve = str(curve_files(tmp_path, SEVEN, diagnostic_support_threshold_min=5.0))
    assert main(["project", str(GPX), "--curve", curve]) == 0
    assert "5 tranches lues, 4 retenues (>= 10 min)" in capsys.readouterr().out
    options = ["--min-support-min", "5"]
    assert main(["project", str(GPX), "--curve", curve, *options]) == 0
    assert "5 tranches lues, 5 retenues (>= 5 min)" in capsys.readouterr().out


def test_the_projection_carries_its_threshold(tmp_path: Path) -> None:
    """La projection porte le seuil de sa lecture, pas celui des diagnostics."""
    curve = curve_files(tmp_path, SEVEN, diagnostic_support_threshold_min=20.0)
    values = {"effort": 0.9, "curve_min_support_min": 5.0}
    projected = project_route(GPX, curve, {}, values)
    carried = projected.projection.parameters.values
    assert dict(carried) == values
    assert set(carried) == {spec.name for spec in PROJECTION_PARAMETER_SPECS}


def test_the_projection_page_keeps_the_threshold_control() -> None:
    """Le curseur de la page Projection reste (décision R). Sauté sans l'extra
    ``tableau`` : ``test_ui_guarantees`` importe Streamlit dès son chargement."""
    pytest.importorskip("streamlit")
    from test_ui_guarantees import _page, _with_curve, _with_route

    _with_route()
    _with_curve()
    page = _page()
    assert not page.exception
    labels = [slider.label for slider in page.slider]
    assert "Effort" in labels
    assert "Support minimal d'une tranche (min)" in labels
