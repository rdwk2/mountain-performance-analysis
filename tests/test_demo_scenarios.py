"""Les scénarios des profils de démo sur la chaîne réelle (M5-3, § 6.4 (b) du brief) :
la version réduite de chaque personnage (``tests/demo_world.py``), la course à deux
parties le jour T0 + 21, aujourd'hui = T0. Une valeur du logiciel (une part hors
support) ne se compare qu'au repère ; les textes et les comptes sont ceux du brief."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from demo_world import T0, DemoBuild, built
from mountain_perf import cli
from mountain_perf.cli import main
from mountain_perf.config import DATA_DIR_ENV_VAR
from mountain_perf.demo.constantes import CHARACTER_NAMES
from mountain_perf.estimation.origin import (
    OriginOutcome,
    cold_start_warning,
)
from mountain_perf.model import PROJECTION_PARAMETER_SPECS, read_curve
from mountain_perf.reports import curve_warnings
from mountain_perf.runs import (
    OriginCurve,
    course_origin,
    curve_selection,
    load_athlete_corpus,
    origin_curve,
    project_route,
)
from mountain_perf.schemas import ParameterSet

pytest.importorskip("fitdecode")

NOW = datetime(2026, 11, 13, 12, tzinfo=UTC)
RACE = date(2026, 12, 4)
BEYOND = ("debutant", "rouleur", "moyen")
"""Les personnages dont la part hors support projetée dépasse le repère (D3)."""
WARNINGS = {"debutant": 2, "polyvalente": 0, "grimpeur": 0, "rouleur": 1, "moyen": 1}
"""Le nombre d'avertissements de la courbe à l'origine de la course (§ 6.4 (b) 4)."""
COLD_12 = "moins de 20 sorties à pied passées (12) : "
SUPPORT = " du temps prévu hors du support de la courbe : au-delà de 50 %"
BOUNDED = (
    "course le 2026-12-04 : au-delà de 7 jours, origine bornée à aujourd'hui (celle "
    "d'une course le 2026-11-20) ; ce n'est pas la courbe que le backtest prendrait "
    "pour cette course"
)


def _build(name: str, factory: pytest.TempPathFactory) -> DemoBuild:
    return built(name, factory)


def _curve(folder: Path, day: date) -> OriginCurve:
    corpus = load_athlete_corpus(folder, curve_selection().source_activity_types)
    return origin_curve(corpus, course_origin(day, T0), 56, generated_at=NOW)


def test_the_two_part_race_is_bounded() -> None:
    course = course_origin(T0 + timedelta(days=21), T0)
    assert course.day == RACE
    assert course.bounded
    assert course.origin == datetime(2026, 11, 12, 23, tzinfo=UTC)


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_curve_warnings(name: str, tmp_path_factory: pytest.TempPathFactory) -> None:
    """Points 2 à 4 : la courbe à l'origine existe et se projette ; la part hors
    support de ``deux_parties`` est du bon côté du repère ; les avertissements."""
    build = _build(name, tmp_path_factory)
    found = _curve(build.folder, RACE)
    assert found.curve is not None
    assert found.result.outcome is OriginOutcome.PROJECTABLE
    run = project_route(
        build.folder / "routes" / "deux_parties.gpx", found.curve, {}, {}
    )
    share = run.diagnostics.out_of_support_time_share
    if name in BEYOND:
        assert share > 0.5
    else:
        assert share <= 0.5
    warnings = curve_warnings(found.result.history, share)
    assert len(warnings) == WARNINGS[name]
    if name == "debutant":
        assert warnings[0].startswith(COLD_12)
    if warnings:
        assert SUPPORT in warnings[-1]


def test_the_beginner_at_the_default_day(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Point 5 : au jour par défaut (origine T0 − 7), le débutant a dix sorties finies
    avant le 2026-11-06."""
    found = _curve(_build("debutant", tmp_path_factory).folder, T0)
    warning = cold_start_warning(found.result.history)
    assert warning is not None
    assert warning.startswith("moins de 20 sorties à pied passées (10) : ")


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_the_range_curve(name: str, tmp_path_factory: pytest.TempPathFactory) -> None:
    """Point 6 : ``reference/plage.csv`` et son compagnon, projetables."""
    reference = _build(name, tmp_path_factory).folder / "reference"
    assert (reference / "plage.meta.json").exists()
    read = read_curve(reference / "plage.csv", ParameterSet(PROJECTION_PARAMETER_SPECS))
    assert read.bin_count_kept > 0


@pytest.mark.parametrize("name", CHARACTER_NAMES)
def test_the_projection_command(
    name: str,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Point 7 : ``mperf project … --at 2026-12-04`` sur le dossier, l'horloge des
    commandes à T0 12:00 UTC : la ligne bornée d'abord, un avertissement par
    avertissement du point 4."""
    folder = _build(name, tmp_path_factory).folder
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(folder))
    monkeypatch.setattr(cli, "_now", lambda: NOW)
    route = folder / "routes" / "deux_parties.gpx"
    assert main(["project", str(route), "--at", "2026-12-04"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == BOUNDED
    warnings = [line for line in lines if line.startswith("avertissement : ")]
    assert len(warnings) == WARNINGS[name]
