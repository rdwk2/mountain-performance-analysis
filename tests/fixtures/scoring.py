"""Fixtures synthétiques des scores de v0 brut (M4b-2) — les treize cas du § 7.2.

Convention du § 7.0 du brief M4b-2 : les constructeurs de M4a, **inchangés**, de
``fixtures.segments`` (Régimes, Régimes déviation) et de ``fixtures.passages`` (les
autres), passés par la chaîne de M4a — ``reference_profile``, la géométrie du cas,
``build_series``, ``clock_partition``, ``match_trace`` avec les paramètres du cas,
``observe_passages`` —, puis par ``v0_scores`` avec la courbe commitée
``courbe_synthetique.csv`` lue par ``read_curve`` aux paramètres de v0 brut et un
``generated_at`` fixe. « Régimes sans référence » est Régimes avec
``reference=None``. Ce module **appelle** les constructeurs de M4a, il ne les recopie
pas.

- :data:`SCORING_CASES` : les treize cas par leur nom du § 7.2 ;
- :func:`match_case`, :func:`curve_read`, :func:`trace_profile` : le cas, la courbe
  commitée et le profil de la trace (choix 4 du brief).

Utilisées par ``tests/test_model_timeline.py`` et les ``tests/test_*scoring*.py``.
"""

import functools
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fixtures import passages, segments
from fixtures.matching import MatchCase
from mountain_perf.backtest import trace_route
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS, build_profile
from mountain_perf.model import PROJECTION_PARAMETER_SPECS, CurveReadResult, read_curve
from mountain_perf.schemas import ParameterSet, RecordedTrace, RouteProfile

FIXTURES = Path(__file__).parent
CURVE_PATH = FIXTURES / "courbe_synthetique.csv"

GENERATED_AT = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
"""Le ``generated_at`` fixe des prévisions des tests (§ 7.0)."""


@dataclass(frozen=True)
class ScoringCase:
    """Un cas du § 7.2 : son constructeur de M4a, et s'il a une référence."""

    constructor: Callable[[], MatchCase]
    with_reference: bool = True


SCORING_CASES: dict[str, ScoringCase] = {
    "Régimes": ScoringCase(segments.regimes),
    "Régimes sans référence": ScoringCase(segments.regimes, with_reference=False),
    "Régimes déviation": ScoringCase(segments.regimes_deviation),
    "Passages": ScoringCase(passages.passages),
    "M05": ScoringCase(passages.m05),
    "M05 ancré": ScoringCase(passages.m05_anchored),
    "Arrivée hors préfixe": ScoringCase(passages.final_outside_prefix),
    "Chronologie": ScoringCase(passages.chronology),
    "Coin coupé": ScoringCase(passages.cut_corner),
    "Départ dans l'arrêt": ScoringCase(passages.departure_in_stop),
    "Départ non daté": ScoringCase(passages.undated_departure),
    "Deux arrêts": ScoringCase(passages.two_stops),
    "Aller-retour": ScoringCase(passages.out_and_back),
}
"""Les treize cas du § 7.2, dans l'ordre du tableau."""

CONSTRUCTED = tuple(name for name, case in SCORING_CASES.items() if case.with_reference)
"""Les douze cas construits (« Régimes sans référence » a la trace de Régimes)."""


@functools.cache
def match_case(name: str) -> MatchCase:
    """Le ``MatchCase`` d'un cas du § 7.2, construit une fois."""
    return SCORING_CASES[name].constructor()


@functools.cache
def curve_read() -> CurveReadResult:
    """La courbe commitée, lue aux paramètres de v0 brut (choix 5 du brief)."""
    return read_curve(CURVE_PATH, ParameterSet(PROJECTION_PARAMETER_SPECS))


def trace_profile(trace: RecordedTrace) -> RouteProfile:
    """Le profil de la trace réalisée (choix 4 du brief) :
    ``build_profile(trace_route(trace, trace.sources[0].identifier), …)`` aux défauts
    de ``0008``."""
    return build_profile(
        trace_route(trace, trace.sources[0].identifier),
        ParameterSet(PROFILE_PARAMETER_SPECS),
    )
