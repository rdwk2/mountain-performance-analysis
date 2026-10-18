"""Les fourchettes au rapport (``0010`` D11 et D15, leurs précisions de M4d-2) :
garantie de ``scored_performances`` que la batterie jointe n'exerçait pas (relecture C
de la PR M4d-2) — chaque performance porte les fourchettes **de sa sortie**. Monde de
M4b-5 (``fixtures.backtest_world``) ; aucune donnée réelle.
"""

from pathlib import Path

import pytest

from fixtures.backtest_world import run_world
from mountain_perf.backtest import BacktestRun, scored_performances


@pytest.fixture(scope="module")
def world_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, BacktestRun]:
    root = tmp_path_factory.mktemp("monde")
    return root, run_world(root)


def test_each_performance_carries_the_bands_of_its_own_outing(
    world_run: tuple[Path, BacktestRun],
) -> None:
    """``scored_performances`` attache à chaque performance d'une sortie scorée avec
    usage les fourchettes **de cette sortie** (pas celles d'une autre), et n'en attache
    à aucune autre."""
    _, run = world_run
    own = {
        declared.performance.civil_date: declared.performance.outings[0].outing_id
        for declared in run.preparation.declaration.performances
        if not declared.performance.is_multi_outing
    }
    entries = scored_performances(run)
    carried = [entry for entry in entries if entry.bands is not None]
    for entry in carried:
        assert entry.bands is not None
        assert entry.bands.outing_id == own[entry.civil_date]
    expected = [
        entry
        for entry in entries
        if entry.missing is None
        and entry.scores is not None
        and entry.scores.usage is not None
    ]
    assert carried == expected
    assert len(carried) >= 2
