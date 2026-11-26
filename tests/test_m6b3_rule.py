"""La règle en couches à l'origine (M6b-3, § 8.2 du brief, ``docs/decisions/0025``) :
R1 à R10, par ``estimate_at_origin`` et un fournisseur d'intervalles.

Le corpus R : les lignes de N2 (le plat, ``k = 17`` ; la montée, ``k = 25``), plus, pour
chaque activité, une descente (``k = 13``, centre −0,0875 ; 2 m/s au niveau 0, 2,2 m/s
pour C), 1 000 s de temps M chacune ; des intervalles de 50 m aux pentes −0,0875, 0,0125
et 0,2125. Les fins se posent par rapport à l'origine : A et B avant la borne basse de
56 jours, C après ; trois poids égaux (3 000 s), donc le ``Δ`` de N2."""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from mountain_perf.estimation.curve import (
    LAYERED_METHOD,
    METHOD,
    BinValue,
    CurveSelection,
    _pace_model,
    _predicted_s,
    curve_file_rows,
    rank_quantile,
)
from mountain_perf.estimation.decision import (
    LAYERED,
    LAYERED_KAPPA,
    LAYERED_LEVEL_DAYS,
    PARIS,
)
from mountain_perf.estimation.intervals import (
    ActivityIntervals,
    CurveInterval,
    TraceRefusal,
)
from mountain_perf.estimation.levels import fit_joint_levels, level_shift
from mountain_perf.estimation.origin import (
    FEW_ACTIVITIES,
    NO_RECENT,
    CurveCorpus,
    LevelLayer,
    OriginEstimate,
    OriginOutcome,
    OriginWindow,
    estimate_at_origin,
    origin_absence_document,
    origin_companion,
    window_lower_bound,
)
from mountain_perf.validation import ContractError
from test_estimation_curve import DEFAULTS, activity, interval
from test_og1_origin import PROFILE, activity_pair, corpus, origin_selection

DESCENT, FLAT, CLIMB, STEEP = -0.0875, 0.0125, 0.2125, 0.1125
ORIGIN = datetime(2024, 4, 1, tzinfo=PARIS).astimezone(UTC)
"""00:00 à Paris le lundi 2024-04-01, au lendemain du passage à l'heure d'été."""
AUTUMN = datetime(2024, 10, 28, tzinfo=PARIS).astimezone(UTC)
"""00:00 à Paris le lundi 2024-10-28, au lendemain du passage à l'heure d'hiver."""

Spec = Mapping[float, tuple[float, float]]

R: dict[str, Spec] = {
    "A": {DESCENT: (2000.0, 1000.0), FLAT: (3000.0, 1000.0), CLIMB: (1000.0, 1000.0)},
    "B": {DESCENT: (2000.0, 1000.0), FLAT: (6000.0, 2000.0)},
    "C": {DESCENT: (2200.0, 1000.0), FLAT: (3300.0, 1000.0), CLIMB: (1100.0, 1000.0)},
}
R_BIS: dict[str, Spec] = {
    "A": {**R["A"], STEEP: (100.0, 100.0)},
    "B": R["B"],
    "C": {**R["C"], STEEP: (100.0, 50.0)},
}
ESTIMATOR = (
    "mperf curve --at (OG-1) : règle à l'origine, en couches (forme 365 jours, niveau "
    "56 jours, κ = 0,5) ; intervalles de la grille du profil, temps M θc, tranches "
    "variables, valeur somme"
)


def cells(spec: Spec) -> list[CurveInterval]:
    """Des intervalles de 50 m, chaque pente à sa longueur et à son temps M."""
    found: list[CurveInterval] = []
    for grade, (length_m, moving_s) in spec.items():
        count = round(length_m / 50.0)
        found += [interval(grade, 50.0, moving_s / count) for _ in range(count)]
    return found


def ended(ref: str, end: datetime, *, recording_end: datetime | None = None) -> Any:
    """Une activité dont la fin de l'index est ``end`` (une heure d'écoulé) ; son
    enregistrement finit à ``recording_end``, 10 minutes avant ``end`` par défaut."""
    start = end - timedelta(hours=1)
    last = end - timedelta(minutes=10) if recording_end is None else recording_end
    return activity_pair(
        ref,
        start,
        index_elapsed_s=3600.0,
        recording_s=(last - start).total_seconds(),
    )


def provider(
    table: Mapping[str, Spec],
    refused: frozenset[str] = frozenset(),
    *,
    raw: Mapping[str, ActivityIntervals] | None = None,
    elapsed: Mapping[str, float] | None = None,
) -> Any:
    """Le fournisseur des intervalles du corpus : ceux de ``table``, par référence,
    une heure d'écoulé sauf dans ``elapsed`` ; ceux de ``raw`` tels quels ; « sans
    trace » pour ``refused``."""

    def intervals_of(recording: Any, *_: Any, **__: Any) -> Any:
        ref = recording.activity_ref
        if ref in refused:
            return TraceRefusal.NO_TRACE
        if raw is not None and ref in raw:
            return raw[ref]
        seconds = 3600.0 if elapsed is None else elapsed.get(ref, 3600.0)
        result: ActivityIntervals = activity(ref, cells(table[ref]), seconds)
        return result

    return intervals_of


def run(
    ends: Mapping[str, Any],
    window: OriginWindow,
    *,
    origin: datetime = ORIGIN,
    table: Mapping[str, Spec] = R,
    refused: frozenset[str] = frozenset(),
    selection: CurveSelection | None = None,
    raw: Mapping[str, ActivityIntervals] | None = None,
    elapsed: Mapping[str, float] | None = None,
) -> tuple[OriginEstimate, CurveCorpus]:
    season = corpus(list(ends.values()))
    result = estimate_at_origin(
        season,
        "x",
        origin,
        window,
        origin_selection() if selection is None else selection,
        DEFAULTS,
        PROFILE,
        intervals_of=provider(table, refused, raw=raw, elapsed=elapsed),
    )
    return result, season


def season_r(origin: datetime = ORIGIN, *, c_days: int = 10) -> dict[str, Any]:
    """A et B finis 100 et 90 jours avant l'origine, C ``c_days`` jours avant."""
    return {
        "A": ended("A", origin - timedelta(days=100)),
        "B": ended("B", origin - timedelta(days=90)),
        "C": ended("C", origin - timedelta(days=c_days)),
    }


def _shift(result: OriginEstimate) -> float:
    layer = result.level_layer
    assert layer is not None
    assert layer.delta is not None
    return layer.delta


# --- R1, R2, R3, R10 : la correction ------------------------------------------------


def test_layered_is_the_365_curve_times_s() -> None:
    """R1 : mêmes candidates, retenues, comptes et support que sous 365 jours ; chaque
    vitesse multipliée par ``s``, le reste de chaque tranche inchangé."""
    year, _ = run(season_r(), 365)
    layered, _ = run(season_r(), LAYERED)
    assert year.estimate is not None
    assert layered.estimate is not None
    assert layered.candidates == year.candidates
    assert layered.lower_bound == year.lower_bound
    assert layered.estimate.activity_refs == year.estimate.activity_refs
    assert layered.estimate.counts == year.estimate.counts
    assert layered.estimate.support_grade_range == year.estimate.support_grade_range
    assert layered.estimate.activity_bins == year.estimate.activity_bins
    rows = year.estimate.activity_bins
    fit = fit_joint_levels(rows)
    shift = level_shift(fit.levels, [r.moving_s for r in rows], [False, False, True])
    assert shift is not None
    factor = math.exp(-0.5 * shift)
    assert len(layered.estimate.bins) == len(year.estimate.bins)
    for mine, base in zip(layered.estimate.bins, year.estimate.bins, strict=True):
        assert mine.speed_ms == pytest.approx(base.speed_ms * factor, rel=1e-12)
        assert dataclasses.replace(mine, speed_ms=base.speed_ms) == base


def test_layered_n2() -> None:
    """R2 : le ``Δ`` de N2, ``s``, les comptes, la convergence, 12 tours."""
    result, _ = run(season_r(), LAYERED)
    layer = result.level_layer
    assert layer is not None
    assert layer.delta == pytest.approx(-0.0635401199, abs=1e-9)
    assert layer.speed_factor == pytest.approx(1.0322801155, rel=1e-9)
    assert (layer.fit_count, layer.recent_count) == (3, 1)
    assert (layer.iterations, layer.converged) == (12, True)
    assert layer.no_correction_reason is None
    assert (layer.level_window_days, layer.kappa) == (LAYERED_LEVEL_DAYS, LAYERED_KAPPA)


def test_layered_is_not_the_curve_level() -> None:
    """R3 : la moyenne pesée des ``λ_j`` sous la courbe de 365 jours (le niveau de
    ``0017``, P4.2) donnerait −0,0608768755 ; la règle rend −0,0635401199."""
    year, _ = run(season_r(), 365)
    assert year.estimate is not None
    model = _pace_model(year.estimate.bins, 10.0)
    assert model is not None
    levels = []
    for ref in ("A", "B", "C"):
        moving = cells(R[ref])
        total = math.fsum(i.moving_s for i in moving)
        levels.append((total, math.log(total / _predicted_s(model, moving))))

    def mean(chosen: list[tuple[float, float]]) -> float:
        return math.fsum(t * v for t, v in chosen) / math.fsum(t for t, _ in chosen)

    under_curve = mean(levels[2:]) - mean(levels)
    assert under_curve == pytest.approx(-0.0608768755, abs=1e-9)
    layered, _ = run(season_r(), LAYERED)
    assert _shift(layered) == pytest.approx(-0.0635401199, abs=1e-9)


def test_every_moving_bin_enters_the_fit() -> None:
    """R10 : la montée de 10 à 12,5 %, sous le seuil de support (150 s), hors de la
    forme du modèle : le support s'arrête au plat, l'ajustement lit les quatre
    tranches."""
    result, _ = run(season_r(), LAYERED, table=R_BIS)
    assert result.estimate is not None
    assert result.estimate.support_grade_range == (DESCENT, FLAT)
    assert [r.moving_s for r in result.estimate.activity_bins] == pytest.approx(
        [3100.0, 3000.0, 3050.0], rel=1e-12
    )
    layer = result.level_layer
    assert layer is not None
    assert layer.delta == pytest.approx(-0.0705553607, abs=1e-9)
    assert layer.speed_factor == pytest.approx(1.0359073200, rel=1e-9)
    assert layer.iterations == 12


MEDIAN = origin_selection(value=BinValue.MEDIAN)


def test_layered_under_the_median() -> None:
    """R1 sous « médiane », sur R bis : la courbe en couches est celle de 365 jours
    × s ; l'ajustement ne lit pas la valeur de la sélection, le ``Δ`` est celui de
    « somme », à l'octet."""
    year, _ = run(season_r(), 365, table=R_BIS, selection=MEDIAN)
    layered, _ = run(season_r(), LAYERED, table=R_BIS, selection=MEDIAN)
    pooled, _ = run(season_r(), LAYERED, table=R_BIS)
    assert year.estimate is not None
    assert layered.estimate is not None
    assert layered.candidates == year.candidates
    assert layered.estimate.counts == year.estimate.counts
    assert layered.estimate.support_grade_range == year.estimate.support_grade_range
    assert layered.estimate.activity_bins == year.estimate.activity_bins
    assert _shift(layered) == _shift(pooled)
    assert _shift(layered) == pytest.approx(-0.0705553607, abs=1e-9)
    factor = math.exp(-LAYERED_KAPPA * _shift(layered))
    assert len(layered.estimate.bins) == len(year.estimate.bins)
    for mine, base in zip(layered.estimate.bins, year.estimate.bins, strict=True):
        assert mine.speed_ms == pytest.approx(base.speed_ms * factor, rel=1e-12)
        assert dataclasses.replace(mine, speed_ms=base.speed_ms) == base


def test_layered_level_quantiles_under_the_median() -> None:
    """R7 sous « médiane », sur R bis : les quantiles en couches sont ceux de 365 jours
    − κΔ."""
    year, _ = run(season_r(), 365, table=R_BIS, selection=MEDIAN)
    layered, _ = run(season_r(), LAYERED, table=R_BIS, selection=MEDIAN)
    assert year.estimate is not None
    assert layered.estimate is not None
    base, mine = year.estimate.level, layered.estimate.level
    assert base is not None
    assert mine is not None
    shift = LAYERED_KAPPA * _shift(layered)
    assert [mine.p10, mine.p50, mine.p90] == pytest.approx(
        [base.p10 - shift, base.p50 - shift, base.p90 - shift], abs=1e-12
    )
    assert mine.count == base.count


def test_the_median_threshold_is_crossed_in_r_bis() -> None:
    """Sous « médiane », la cellule raide de C (50 s) est sous le seuil de la médiane
    (60 s) ; elle entre pourtant dans l'ajustement."""
    assert DEFAULTS["median_min_moving_s"] == 60.0
    layered, _ = run(season_r(), LAYERED, table=R_BIS, selection=MEDIAN)
    assert layered.estimate is not None
    c = layered.estimate.activity_bins[2]
    assert c.activity_ref == "C"
    assert min(t for _, _, t in c.bins) == pytest.approx(50.0)
    assert _shift(layered) == pytest.approx(-0.0705553607, abs=1e-9)


# --- R4 : récente, la règle de 56 jours ---------------------------------------------


def _recent(result: OriginEstimate) -> int:
    layer = result.level_layer
    assert layer is not None
    return layer.recent_count


def test_recent_is_the_56_day_rule() -> None:
    """R4 : une fin à ``b₅₆`` est récente, une microseconde avant non ; une activité
    dont la fin de l'index est avant ``b₅₆`` et l'enregistrement après n'est pas
    récente (l'index décide d'abord) ; ``b₅₆`` est 00:00 à Paris, au lendemain des deux
    changements d'heure."""
    bound = window_lower_bound(ORIGIN, LAYERED_LEVEL_DAYS)
    assert bound == datetime(2024, 2, 5, tzinfo=PARIS).astimezone(UTC)
    at_bound = {**season_r(), "C": ended("C", bound, recording_end=bound)}
    result, _ = run(at_bound, LAYERED)
    assert _recent(result) == 1
    assert result.level_layer is not None
    assert result.level_layer.level_lower_bound == bound
    before = bound - timedelta(microseconds=1)
    just_before = {**season_r(), "C": ended("C", before, recording_end=before)}
    result, _ = run(just_before, LAYERED)
    assert _recent(result) == 0
    late_watch = {
        **season_r(),
        "C": ended(
            "C", bound - timedelta(minutes=30), recording_end=bound + timedelta(hours=1)
        ),
    }
    result, _ = run(late_watch, LAYERED)
    assert any(i.end.activity_ref == "C" for i in result.candidates)
    assert result.estimate is not None
    assert "C" in result.estimate.activity_refs
    assert _recent(result) == 0

    def paris(
        year: int, month: int, day: int, hour: int = 0, minute: int = 0
    ) -> datetime:
        return datetime(year, month, day, hour, minute, tzinfo=PARIS).astimezone(UTC)

    # Des fins à 23:30 et 00:30 à Paris autour de b₅₆ : 24 × 56 h depuis l'origine en
    # UTC tomberaient une heure à côté.
    for origin, day, fins in (
        (ORIGIN, paris(2024, 2, 5), ((paris(2024, 2, 4, 23, 30), 0),)),
        (ORIGIN, paris(2024, 2, 5), ((paris(2024, 2, 5, 0, 30), 1),)),
        (AUTUMN, paris(2024, 9, 2), ((paris(2024, 9, 1, 23, 30), 0),)),
        (AUTUMN, paris(2024, 9, 2), ((paris(2024, 9, 2, 0, 30), 1),)),
    ):
        assert window_lower_bound(origin, LAYERED_LEVEL_DAYS) == day
        for end, expected in fins:
            ends = {**season_r(origin), "C": ended("C", end, recording_end=end)}
            result, _ = run(ends, LAYERED, origin=origin)
            assert _recent(result) == expected, (origin, end)


# --- R5, R6 : sans correction, toutes récentes ----------------------------------------


def _same_as_the_year(layered: OriginEstimate, year: OriginEstimate) -> None:
    """La courbe en couches est celle de 365 jours, estimation et lignes."""
    assert year.estimate is not None
    assert layered.estimate == year.estimate
    assert layered.rows == year.rows == curve_file_rows(year.estimate)


def _kept_constants(layer: LevelLayer) -> None:
    """Sans correction, la couche garde sa fenêtre, son κ et sa borne basse."""
    assert layer.level_window_days == 56
    assert layer.kappa == 0.5
    assert layer.level_lower_bound == window_lower_bound(ORIGIN, 56)


def test_no_correction() -> None:
    """R5 : une activité seule ; aucune récente ; une candidate récente hors de
    l'ajustement (sans trace) : pas de correction, la courbe de 365 jours ; la couche
    garde sa fenêtre, son κ et sa borne."""
    one = {"A": season_r()["A"]}
    layered, _ = run(one, LAYERED)
    year, _ = run(one, 365)
    layer = layered.level_layer
    assert layer is not None
    assert (layer.no_correction_reason, layer.speed_factor) == (FEW_ACTIVITIES, 1.0)
    assert (layer.delta, layer.iterations, layer.converged) == (None, None, None)
    assert (layer.fit_count, layer.recent_count) == (1, 0)
    _kept_constants(layer)
    _same_as_the_year(layered, year)
    old = season_r(c_days=80)
    layered, _ = run(old, LAYERED)
    year, _ = run(old, 365)
    layer = layered.level_layer
    assert layer is not None
    assert (layer.no_correction_reason, layer.speed_factor) == (NO_RECENT, 1.0)
    assert (layer.fit_count, layer.recent_count) == (3, 0)
    _kept_constants(layer)
    _same_as_the_year(layered, year)
    refused = frozenset({"C"})
    layered, _ = run(season_r(), LAYERED, refused=refused)
    year, _ = run(season_r(), 365, refused=refused)
    layer = layered.level_layer
    assert layer is not None
    assert (layer.no_correction_reason, layer.speed_factor) == (NO_RECENT, 1.0)
    assert (layer.fit_count, layer.recent_count) == (2, 0)
    assert any(i.end.activity_ref == "C" for i in layered.candidates)
    _same_as_the_year(layered, year)


def _with_d() -> dict[str, Any]:
    """Le corpus R et D, finie 5 jours avant l'origine."""
    return {**season_r(), "D": ended("D", ORIGIN - timedelta(days=5))}


def _out_of_the_fit(result: OriginEstimate) -> None:
    """D hors de l'ajustement : les trois de R, une récente (C), le ``Δ`` de R2."""
    assert result.estimate is not None
    assert "D" not in result.estimate.activity_refs
    assert [r.activity_ref for r in result.estimate.activity_bins] == ["A", "B", "C"]
    layer = result.level_layer
    assert layer is not None
    assert (layer.fit_count, layer.recent_count) == (3, 1)
    assert layer.delta == pytest.approx(-0.0635401199, abs=1e-9)


def test_an_activity_without_retained_interval_is_out_of_the_fit() -> None:
    """D, récente, n'a que des intervalles aberrants (10 m/s au plat et à la montée) :
    écartée « aucun intervalle retenu », hors de l'ajustement."""
    aberrant = activity(
        "D",
        [interval(FLAT, 50.0, 5.0) for _ in range(40)]
        + [interval(CLIMB, 50.0, 5.0) for _ in range(20)],
    )
    result, _ = run(_with_d(), LAYERED, raw={"D": aberrant})
    assert any(i.end.activity_ref == "D" for i in result.candidates)
    _out_of_the_fit(result)


def test_an_activity_too_short_is_out_of_the_fit() -> None:
    """D, récente, de 10 minutes sous une durée minimale de 30 minutes : écartée
    « courte » ; ses intervalles (le plat à 4 m/s) n'entrent pas dans l'ajustement."""
    table = {**R, "D": {FLAT: (2000.0, 500.0), CLIMB: (500.0, 100.0)}}
    result, _ = run(
        _with_d(),
        LAYERED,
        table=table,
        selection=origin_selection(min_duration_s=1800.0),
        elapsed={"D": 600.0},
    )
    _out_of_the_fit(result)


def test_a_correction_without_level_quantiles() -> None:
    """Le corpus R sans les descentes : sans tranche négative, une courbe non
    projetable, sans quantiles de niveau ; la correction s'applique (le ``s`` de R2)."""
    table = {
        ref: {g: v for g, v in spec.items() if g != DESCENT} for ref, spec in R.items()
    }
    year, _ = run(season_r(), 365, table=table)
    layered, _ = run(season_r(), LAYERED, table=table)
    assert layered.outcome is OriginOutcome.NOT_PROJECTABLE
    assert year.estimate is not None
    assert layered.estimate is not None
    assert year.estimate.level is None
    assert layered.estimate.level is None
    layer = layered.level_layer
    assert layer is not None
    assert layer.speed_factor == pytest.approx(1.0322801155, rel=1e-9)
    assert len(layered.estimate.bins) == len(year.estimate.bins)
    for mine, base in zip(layered.estimate.bins, year.estimate.bins, strict=True):
        assert mine.speed_ms == pytest.approx(
            base.speed_ms * layer.speed_factor, rel=1e-12
        )


def test_all_recent() -> None:
    """R6 : toutes récentes : ``Δ = 0.0``, ``s = 1.0``, l'ajustement fait."""
    recent = {
        ref: ended(ref, ORIGIN - timedelta(days=days))
        for ref, days in (("A", 30), ("B", 20), ("C", 10))
    }
    layered, _ = run(recent, LAYERED)
    year, _ = run(recent, 365)
    layer = layered.level_layer
    assert layer is not None
    assert layer.delta == 0.0
    assert layer.speed_factor == 1.0
    assert layer.iterations is not None
    assert layer.converged is True
    assert layer.no_correction_reason is None
    _same_as_the_year(layered, year)


# --- R7 : les quantiles du niveau ---------------------------------------------------


def test_layered_level_quantiles() -> None:
    """R7 : les quantiles en couches sont ceux de 365 jours − κΔ, et ceux des ``λ_j``
    recalculés sous la courbe corrigée."""
    year, _ = run(season_r(), 365)
    layered, _ = run(season_r(), LAYERED)
    assert year.estimate is not None
    assert layered.estimate is not None
    base, mine = year.estimate.level, layered.estimate.level
    assert base is not None
    assert mine is not None
    shift = LAYERED_KAPPA * _shift(layered)
    assert [mine.p10, mine.p50, mine.p90] == pytest.approx(
        [base.p10 - shift, base.p50 - shift, base.p90 - shift], abs=1e-12
    )
    assert mine.count == base.count
    model = _pace_model(layered.estimate.bins, 10.0)
    assert model is not None
    levels = []
    for ref in ("A", "B", "C"):
        moving = cells(R[ref])
        total = math.fsum(i.moving_s for i in moving)
        levels.append(math.log(total / _predicted_s(model, moving)))
    recomputed = [rank_quantile(levels, n, d) for n, d in ((1, 10), (1, 2), (9, 10))]
    assert [mine.p10, mine.p50, mine.p90] == pytest.approx(recomputed, abs=1e-9)


# --- R8, R9 : le compagnon ----------------------------------------------------------


def _companion(result: OriginEstimate, season: CurveCorpus) -> Any:
    return origin_companion(
        result,
        season,
        origin_selection(),
        DEFAULTS,
        PROFILE,
        commit="c" * 40,
        generated_at=datetime(2024, 4, 2, tzinfo=UTC),
    )


def test_layered_companion() -> None:
    """R8 : la fenêtre « layered », la section ``level_layer`` juste après
    ``lower_bound``, ses dix clés dans l'ordre, la méthode et l'estimateur ; une absence
    sous ``layered`` porte ``"level_layer": null``."""
    result, season = run(season_r(), LAYERED)
    provenance, document = _companion(result, season)
    origin = document["origin"]
    assert list(origin)[:5] == [
        "origin",
        "window",
        "lower_bound",
        "level_layer",
        "outcome",
    ]
    assert origin["window"] == "layered"
    layer = origin["level_layer"]
    assert list(layer) == [
        "level_window_days",
        "level_lower_bound",
        "kappa",
        "fit_count",
        "recent_count",
        "delta",
        "speed_factor",
        "iterations",
        "converged",
        "no_correction_reason",
    ]
    bound = window_lower_bound(ORIGIN, LAYERED_LEVEL_DAYS)
    assert bound is not None
    assert layer["level_lower_bound"] == bound.isoformat()
    assert (layer["level_window_days"], layer["kappa"]) == (56, 0.5)
    assert layer["delta"] == pytest.approx(-0.0635401199, abs=1e-9)
    assert document["method"] == LAYERED_METHOD
    assert provenance.estimator == ESTIMATOR
    json.dumps(document, allow_nan=False)
    late = {ref: ended(ref, ORIGIN + timedelta(days=2)) for ref in ("A", "B")}
    absent, season = run(late, LAYERED)
    assert absent.estimate is None
    assert absent.level_layer is None
    section = json.loads(origin_absence_document(absent, season))["origin"]
    assert list(section)[:4] == ["origin", "window", "lower_bound", "level_layer"]
    assert section["level_layer"] is None


@pytest.mark.parametrize(
    ("window", "label"),
    [(28, "28 jours"), (56, "56 jours"), (365, "365 jours"), ("all", "all")],
)
def test_windows_are_unchanged(window: OriginWindow, label: str) -> None:
    """R9 : sous une fenêtre, ni ``level_layer`` ni texte neuf."""
    result, season = run(season_r(), window)
    assert result.level_layer is None
    provenance, document = _companion(result, season)
    assert "level_layer" not in document["origin"]
    assert document["method"] == METHOD
    assert provenance.estimator == (
        f"mperf curve --at (OG-1) : règle à l'origine, fenêtre {label} ; intervalles "
        "de la grille du profil, temps M θc, tranches variables, valeur somme"
    )


# --- Les invariants de LevelLayer -----------------------------------------------------


def _layer(**changes: Any) -> LevelLayer:
    fields: dict[str, Any] = {
        "level_window_days": 56,
        "kappa": 0.5,
        "level_lower_bound": window_lower_bound(ORIGIN, 56),
        "fit_count": 3,
        "recent_count": 1,
        "delta": -0.0635401199,
        "speed_factor": 1.0322801155,
        "iterations": 12,
        "converged": True,
        "no_correction_reason": None,
    }
    fields.update(changes)
    return LevelLayer(**fields)


WITHOUT: dict[str, Any] = {"delta": None, "iterations": None, "converged": None}


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"delta": None}, "absents si et seulement si"),
        (
            {**WITHOUT, "no_correction_reason": NO_RECENT, "speed_factor": 1.03},
            "sans correction, le facteur vaut 1",
        ),
        ({"recent_count": 4}, "recent_count <= fit_count"),
    ],
    ids=["delta-sans-raison", "facteur-sans-delta", "recentes-au-dela"],
)
def test_level_layer_invariants(changes: dict[str, Any], fragment: str) -> None:
    _layer()
    _layer(**WITHOUT, no_correction_reason=NO_RECENT, speed_factor=1.0)
    with pytest.raises(ContractError, match=fragment):
        _layer(**changes)


def test_level_layer_is_frozen() -> None:
    layer = _layer()
    with pytest.raises(dataclasses.FrozenInstanceError):
        layer.kappa = 1.0  # type: ignore[misc]
