"""Le rapport du mode glissant (OG-UI, § 6.3 bis du brief) : l'issue probable comptée
sur les paires, la ligne de calage, D3 et D6 sur une performance sans courbe, le tableau
« performances », l'étiquette « activités », un instant hors du domaine des dates au
registre.

Les mondes et les aides de ``tests/test_og2_rolling.py``,
``tests/test_og2_evaluation.py`` et ``tests/test_og2_accord.py``, importés ; une
fixture ``autouse`` ne suit pas l'import : celle-ci appelle ``fix_world`` et
``freeze_reads``. Le mode déclaré est tenu par les
tests existants (``tests/test_cli_backtest.py`` et suivants), inchangés."""

from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path
from typing import Any

import pytest

import test_og2_accord as accord
from fixtures.registry import registry_root
from mountain_perf import cli
from mountain_perf.backtest.registry import RegistryError, _moment, read_registry
from mountain_perf.backtest.report import (
    ClockRole,
    ReportMetric,
    command_sets,
    paired_difference,
    performance_values,
    rolling_scored_performances,
)
from mountain_perf.backtest.rolling import RollingSettings, run_rolling
from mountain_perf.estimation.origin import ALL_PAST
from mountain_perf.schemas import CALIBRATED_MODELS, ModelKind, Scenario
from test_og2_evaluation import RECORDED_AT
from test_og2_rolling import activities, build_world, fix_world, freeze_reads, prepare

OUTCOME_3 = (
    "issue        Plus petit écart de |L| détectable à 80 % (test t apparié bilatéral "
    "à 5 %, écart-type 0,0253 des différences mesuré chez rdw, 56 − 28 jours, n = 11) "
    ": 0.078 avec 3 performances couvertes sous tous les W et lues en usage (v0 brut, "
    "écoulé). Le banc mesure, à support égal, des écarts de 0,013 au plus."
)
"""``mde(3) = (t₀,₉₇₅(2) + t₀,₈₀(2)) × 0,0253 / √3 = (4,3027 + 1,0607) × 0,0253 / 1,7321
= 0,0783``, calculée à la main (le brief, § 6.3 bis)."""


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch) -> None:
    fix_world(monkeypatch)
    freeze_reads(monkeypatch)


def _runs(tmp_path: Path, **settings: float) -> tuple[Any, Any]:
    manifest = build_world(tmp_path)
    chosen = RollingSettings(settings.get("s", 0.1), 0.5, 10.0, 60.0)
    preparation = prepare(manifest, [28, 56, ALL_PAST], chosen)
    runs = run_rolling(preparation, tmp_path / "glissant", recorded_at=RECORDED_AT)
    return runs, preparation


def _view(tmp_path: Path, pairs: Any = None) -> Any:
    manifest = build_world(tmp_path, pairs)
    preparation = prepare(manifest, [28])
    (run,) = run_rolling(preparation, tmp_path / "glissant", recorded_at=RECORDED_AT)
    return cli._rolling_view(run.evaluation, preparation.common.manifest)


# --- L'issue probable -----------------------------------------------------------------


def test_the_probable_outcome_counts_the_pairs(tmp_path: Path) -> None:
    runs, preparation = _runs(tmp_path)
    text = cli._comparison_report(runs, preparation.common.manifest)
    assert (
        "             couvertes sous toutes 4 : 2026-06-04, 2026-06-08, 2026-06-15, "
        "2026-06-25"
    ) in text
    assert OUTCOME_3 in text
    issue = text.index(OUTCOME_3)
    assert text[issue - 1].startswith("             au-delà du repère sous ")
    assert text[issue + 1].startswith("paires       ")


def test_the_outcome_n_equals_the_n_of_the_pairs(tmp_path: Path) -> None:
    """Le ``n`` de l'issue égale celui de ``|L|`` de chaque paire « couvertes sous
    toutes » (ici : chaque performance lue sous un W l'est sous tous), et la seconde
    voie le recompte par ``paired_difference``."""
    runs, preparation = _runs(tmp_path)
    text = cli._comparison_report(runs, preparation.common.manifest)
    counts = [
        text[k + 1]
        for k, line in enumerate(text)
        if line.startswith("             couvertes sous toutes (")
    ]
    assert len(counts) == 3
    assert all(line.startswith("               |L| : n 3, ") for line in counts)
    declarations = [run.evaluation.window.declaration for run in runs]
    days = [d.performance.civil_date for d in declarations[0].performances]
    rollings = [d.rolling for d in declarations if d.rolling is not None]
    sets = command_sets(days, rollings)

    def level(k: int, day: date) -> Any:
        evaluation = runs[k].evaluation
        found = {
            e.civil_date: e
            for e in rolling_scored_performances(
                evaluation.window.declaration,
                evaluation.outings,
                [
                    (i.traced.outing.outing_id, i.traced.match)
                    for i in evaluation.no_curve
                ],
                evaluation.calibration,
                evaluation.bands,
            )
        }
        return performance_values(
            found[day], Scenario.USAGE, ClockRole.ELAPSED, ModelKind.V0_RAW
        )[(ReportMetric.ABS_LEVEL, None)]

    couples = [
        (level(0, d), level(1, d))
        for d in sets.covered_under_all
        if not isinstance(level(0, d), str) and not isinstance(level(1, d), str)
    ]
    assert paired_difference(couples).count == 3


def test_the_outcome_below_two(tmp_path: Path) -> None:
    """Au seuil ``s`` de 0,05, une seule couverte sous toutes, sans référence : ``n``
    vaut 0."""
    runs, preparation = _runs(tmp_path, s=0.05)
    text = cli._comparison_report(runs, preparation.common.manifest)
    assert "             couvertes sous toutes 1 : 2026-06-15" in text
    assert "issue        Issue probable : indisponible (n < 2)." in text


# --- La ligne de calage ---------------------------------------------------------------


def _calibration(view: Any, day: str) -> str:
    lines = cli._rolling_calibration_lines(view)
    (line,) = [line for line in lines if line.startswith(f"             {day}  ")]
    return line


def test_the_calibration_title(tmp_path: Path) -> None:
    lines = cli._rolling_calibration_lines(_view(tmp_path))
    assert lines[0] == (
        "calage       0010 D9.2 sur C_j (entraînements terminés avant o_j) ; écoulé, "
        "usage (contrôle sans référence) ; e : effort de v0, a : facteur ; calage (a) "
        "avec κ_j"
    )


def test_the_calibration_line_notes_a_multi_outing_day(tmp_path: Path) -> None:
    line = _calibration(_view(tmp_path), "2026-06-12")
    assert line.endswith(" (jour multi-sorties, a-2026-06-12)")


def test_the_calibration_line_notes_control(tmp_path: Path) -> None:
    view = _view(tmp_path)
    assert _calibration(view, "2026-06-15").endswith(" (contrôle)")
    assert not _calibration(view, "2026-06-25").endswith(")")


def _without_a_member(view: Any, day: date) -> tuple[Any, int]:
    """La vue où la population du comparateur, sur la première sortie du jour ``day``
    et sous l'écoulé, perd un membre ; rend aussi la taille de cette population."""
    calibration = list(view.calibration)
    k = next(i for i, p in enumerate(calibration) if p.population.civil_date == day)
    performance = calibration[k]
    first = performance.outings[0].outing_id
    comparator = CALIBRATED_MODELS[0]
    size = 0
    outings = []
    for entry in performance.outings:
        if entry.outing_id == first and entry.control.model is comparator:
            scenario = entry.usage
            elapsed = scenario.clocks[0]
            population = elapsed.calibration.population
            size = len(population) - 1
            changed = dataclasses.replace(
                elapsed,
                calibration=dataclasses.replace(
                    elapsed.calibration, population=population[:-1]
                ),
            )
            entry = dataclasses.replace(
                entry,
                usage=dataclasses.replace(
                    scenario, clocks=(changed, *scenario.clocks[1:])
                ),
            )
        outings.append(entry)
    calibration[k] = dataclasses.replace(performance, outings=tuple(outings))
    return dataclasses.replace(view, calibration=tuple(calibration)), size


def test_the_calibration_line_reads_the_comparator_population(tmp_path: Path) -> None:
    view, size = _without_a_member(_view(tmp_path), date(2026, 6, 25))
    columns = _calibration(view, "2026-06-25").split()
    assert columns[1] == "8"
    assert columns[2] == str(size) == "5"


# --- D3, D6 et le tableau « performances » sans courbe --------------------------------


NO_CURVE = [
    "a-2026-06-03",
    "a-2026-06-06",
    "a-2026-06-10",
    "b-2026-06-04",
    "b-2026-06-08",
]


def _no_curve_view(tmp_path: Path) -> Any:
    view = _view(tmp_path, activities(first=date(2026, 5, 28)))
    found = sorted(i.traced.outing.outing_id for i in view.evaluation.no_curve)
    assert found == NO_CURVE
    return view


def _section(lines: list[str], title: str) -> list[str]:
    start = next(k for k, line in enumerate(lines) if line.startswith(title))
    end = next(k for k in range(start + 1, len(lines)) if lines[k][:1] != " ")
    return lines[start:end]


def test_descents_say_unavailable_without_curve(tmp_path: Path) -> None:
    view = _no_curve_view(tmp_path)
    section = _section(cli._rolling_report_body(view, 0.25), "descentes")
    expected = [
        f"             {outing_id} — 0010 D6 : indisponible (sans courbe)"
        for outing_id in NO_CURVE
    ]
    assert section[-len(expected) - 1 : -1] == expected
    assert section[-1] == cli._descent_lines(view, 0.25)[-1]
    assert section[-1].startswith("             total : ")


def test_geometry_lists_the_outings_without_curve(tmp_path: Path) -> None:
    view = _no_curve_view(tmp_path)
    section = _section(cli._rolling_report_body(view, 0.25), "géométrie")
    tail = section[-len(NO_CURVE) :]
    assert [line.split()[0] for line in tail] == NO_CURVE
    assert all(line.endswith("sans courbe") for line in tail)
    assert all(line.startswith("             ") for line in tail)


def test_the_performances_table_shows_the_coverage_without_curve(
    tmp_path: Path,
) -> None:
    view = _no_curve_view(tmp_path)
    lines = cli._rolling_outing_lines(view)
    assert not any("non scorée : sans courbe" in line for line in lines)
    for item in view.evaluation.no_curve:
        coverage = item.traced.match.coverage
        share = cli._coverage_percent(coverage.fraction)
        prefix = f"{coverage.prefix_end_m / 1000:.2f} km"
        (line,) = [
            line for line in lines if f" {item.traced.outing.outing_id} " in line
        ]
        assert line.endswith(f"{share:<12}{prefix:<11}{'sans courbe':<12}sans courbe")


def test_the_activities_label(tmp_path: Path) -> None:
    view = _view(tmp_path)
    line = cli._unmatched_line(view.preparation.declaration)
    assert line.startswith("activités    sorties sans correspondance : 14 (")


# --- Un instant hors du domaine des dates ---------------------------------------------


@pytest.mark.parametrize(
    "text", ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"]
)
def test_an_instant_out_of_the_date_domain_is_a_registry_error(text: str) -> None:
    with pytest.raises(RegistryError) as raised:
        _moment(text, "compagnon : ")
    assert str(raised.value) == (
        f"compagnon : instant hors du domaine des dates {text!r}"
    )


def test_append_result_refuses_an_origin_out_of_the_date_domain(
    tmp_path: Path,
) -> None:
    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 0:
            document["estimation"]["origin"]["origin"] = "0001-01-01T00:00:00+01:00"

    built = accord.world(mutate)
    with pytest.raises(RegistryError) as raised:
        accord.append_all(tmp_path, built)
    assert "instant hors du domaine des dates '0001-01-01T00:00:00+01:00'" in str(
        raised.value
    )
    assert len(read_registry(registry_root(tmp_path)).events) == 1
