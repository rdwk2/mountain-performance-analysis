"""La part sur une portion (OG-2, § 6.2) et ``_share`` de ``backtest/rolling.py``, à
leurs bornes (relecture C du bloc 1, mutation 5)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from hypothesis import given

from fixtures.curves import SUPPORT_CURVE
from fixtures.projection import SIX_INTERVAL_PROFILE
from mountain_perf.config import data_dir
from mountain_perf.model.engine import (
    ProjectedTimeline,
    portion_out_of_support_share,
    portion_out_of_support_time_share,
)
from mountain_perf.validation import ContractError
from test_og2_part import HAND, MIDDLE, _parameters, timelines
from test_og2_rolling import build_world, edit_manifest, fix_world, journal, rolling


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch) -> None:
    fix_world(monkeypatch)


@given(timelines())
def test_none_is_the_whole_profile(timeline: ProjectedTimeline) -> None:
    """``portion_m`` ``None`` et ``(0, longueur)`` : la même part, au bit."""
    n = len(timeline.pace_s_per_m)
    for flags in ((True,) * n, (False,) * n, tuple(i % 2 == 0 for i in range(n))):
        whole = (0.0, timeline.length_m)
        assert portion_out_of_support_share(timeline, flags, None) == (
            portion_out_of_support_share(timeline, flags, whole)
        )


def test_one_ulp_beyond_the_profile_is_refused() -> None:
    beyond = math.nextafter(400.0, math.inf)
    with pytest.raises(ContractError, match="portion_m"):
        portion_out_of_support_share(HAND, MIDDLE, (0.0, beyond))
    assert portion_out_of_support_share(HAND, MIDDLE, (0.0, 400.0)) == (
        portion_out_of_support_share(HAND, MIDDLE, None)
    )


def test_a_portion_inside_the_last_interval() -> None:
    """Une portion d'un seul intervalle partiel, dans le support : 0."""
    assert portion_out_of_support_share(HAND, MIDDLE, (310.0, 390.0)) == 0.0


def test_a_portion_longer_than_its_reference_writes_nothing(tmp_path: Path) -> None:
    """``_share`` : une portion déclarée au-delà du profil de la référence refuse
    toute l'exécution, avant tout écrit (registre, documents, rapports)."""
    manifest = build_world(tmp_path)
    edit_manifest(manifest, "a-2026-06-20", portion_m=[0.0, 1.0e7])
    outcome = rolling(manifest, "28")
    assert outcome.code == 1, outcome.err
    assert "dépasse la longueur du profil de sa référence" in outcome.err, outcome.err
    assert journal() == b""
    for folder in ("registre", "rapports"):
        path = data_dir() / folder
        assert not path.exists() or not any(path.iterdir()), folder


@pytest.mark.parametrize(
    ("portion", "share"), [((0.0, 200.0), 0.0), ((500.0, 600.0), 1.0), (None, 5 / 9)]
)
def test_the_time_share_reads_its_portion(
    portion: tuple[float, float] | None, share: float
) -> None:
    """``portion_out_of_support_time_share`` passe la portion au calcul : sur le profil
    des tests du moteur (les deux derniers intervalles hors support, 5/9 du temps), la
    tête (0 à 200 m) est dans le support et la queue (500 à 600 m) en dehors (balayage
    de la conception : la portion remplacée par ``None`` survivait)."""
    found = portion_out_of_support_time_share(
        SIX_INTERVAL_PROFILE, SUPPORT_CURVE, _parameters(), portion
    )
    assert found == pytest.approx(share, rel=1e-12, abs=0.0)
