"""Les coutures de la règle à l'origine (OG-1b, ``docs/decisions/0020``, précision
OG-1b) : le fournisseur des intervalles, le compagnon en fonctions pures, la lecture
d'une courbe depuis ses octets. Jours, heures et activités inventés (règle 1) ; aucun
comportement ne change, les valeurs attendues sont écrites en dur."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from mountain_perf.estimation import origin as origin_module
from mountain_perf.estimation.curve import CURVE_ESTIMATION_PARAMETER_SPECS
from mountain_perf.estimation.intervals import (
    ActivityIntervals,
    TraceRefusal,
    activity_intervals,
)
from mountain_perf.estimation.origin import (
    NO_CANDIDATE,
    IntervalsOf,
    OriginOutcome,
    estimate_at_origin,
)
from mountain_perf.schemas import ActivityRecording, ParameterSet
from test_estimation_curve import DEFAULTS
from test_og1_origin import ORIGIN, PROFILE, _season, corpus, origin_selection, rule

NO_CANDIDATE_ORIGIN = datetime(2024, 3, 19, 23, tzinfo=UTC)
"""00:00 à Paris le 2024-03-20 : aucune candidate sur ``_season()``."""

Call = tuple[str, ParameterSet, dict[str, Any]]


def recorder(calls: list[Call]) -> IntervalsOf:
    """Un fournisseur qui note chaque appel, puis délègue à
    ``activity_intervals``."""

    def provider(
        recording: ActivityRecording, profile: ParameterSet, **options: Any
    ) -> ActivityIntervals | TraceRefusal:
        calls.append((recording.activity_ref, profile, dict(options)))
        return activity_intervals(recording, profile, **options)

    return provider


# --- Section 1 : le fournisseur des intervalles (commit 1) -------------------------


def test_un_fournisseur_recoit_les_candidates_et_les_parametres_de_la_regle() -> None:
    parameters = ParameterSet(
        CURVE_ESTIMATION_PARAMETER_SPECS, {"hr_lag_s": 30.0, "hr_min_coverage": 0.5}
    )
    chosen = origin_selection(max_elapsed_s=1800.0)
    calls: list[Call] = []
    result = estimate_at_origin(
        corpus(_season()),
        "x",
        ORIGIN,
        56,
        chosen,
        parameters,
        PROFILE,
        intervals_of=recorder(calls),
    )
    assert len(calls) == 8
    assert [ref for ref, _, _ in calls] == [f"s{k}" for k in range(8)]
    for _, profile, options in calls:
        assert profile is PROFILE
        assert options == {
            "hr_lag_s": 30.0,
            "hr_min_coverage": 0.5,
            "max_elapsed_s": 1800.0,
        }
    assert result.outcome is OriginOutcome.NOT_PROJECTABLE
    assert result == estimate_at_origin(
        corpus(_season()), "x", ORIGIN, 56, chosen, parameters, PROFILE
    )


def test_sans_fournisseur_activity_intervals_du_module_lu_a_l_appel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Call] = []
    monkeypatch.setattr(origin_module, "activity_intervals", recorder(calls))
    rule(corpus(_season()))
    assert len(calls) == 8


def test_un_fournisseur_remplace_activity_intervals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = rule(corpus(_season()))

    def forbidden(*args: Any, **options: Any) -> Any:
        raise AssertionError("activity_intervals du module appelée")

    monkeypatch.setattr(origin_module, "activity_intervals", forbidden)
    result = estimate_at_origin(
        corpus(_season()),
        "x",
        ORIGIN,
        56,
        origin_selection(),
        DEFAULTS,
        PROFILE,
        support_threshold_min=10.0,
        intervals_of=activity_intervals,
    )
    assert result == expected


def test_sans_candidate_le_fournisseur_n_est_pas_appele() -> None:
    calls: list[Call] = []
    result = estimate_at_origin(
        corpus(_season()),
        "x",
        NO_CANDIDATE_ORIGIN,
        56,
        origin_selection(),
        DEFAULTS,
        PROFILE,
        intervals_of=recorder(calls),
    )
    assert result.outcome is OriginOutcome.ABSENT
    assert result.absence_reason == NO_CANDIDATE
    assert calls == []
