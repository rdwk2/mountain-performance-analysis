"""L'accord du format 6 (OG-2, § 6.6 du brief OG-2) : un registre glissant exact, puis
les réécritures d'A6 sur un compagnon figé, chacune avec ses empreintes recalculées.

Le registre exact a trois performances (accord de la conception) : ``Q20`` et ``Q27``
ont deux courbes distinctes, ``P03`` une absence. Le corpus : quatorze trails
synthétiques ``m06`` à ``m19``, un par jour de mai 2026 à 08:00 UTC, sans écoulé
d'index, d'une heure jusqu'au 12, d'une heure et douze minutes ensuite ; la fenêtre est
de 7 jours. Les
prévisions de v0 brut sont celles des cas de M4b-2, portées sur la courbe de leur
performance : l'accord ne recalcule aucun score."""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fixtures.registry import (
    ATHLETE,
    COMMIT,
    P03,
    Q20,
    Q27,
    V0_RAW,
    at,
    declaration,
    not_calibrated,
    outcome,
    outcomes,
    references,
    registry_root,
    v0_of,
)
from mountain_perf.backtest import content_hash, encode_document
from mountain_perf.backtest.calendar import origin
from mountain_perf.backtest.calibration import (
    calibrate,
    calibrated_scores,
    member_totals,
)
from mountain_perf.backtest.registry import (
    RegistryError,
    RollingDocuments,
    append_declaration,
    append_result,
    verify_registry,
)
from mountain_perf.estimation.origin import (
    estimate_at_origin,
    origin_absence_document,
    origin_companion,
)
from mountain_perf.model.curve_io import (
    curve_csv_support,
    curve_documents,
    freeze_companion,
    read_curve_documents,
)
from mountain_perf.model.engine import ENGINE_VERSION, PROJECTION_PARAMETER_SPECS
from mountain_perf.schemas import (
    CLOCKS,
    AbsentCurve,
    CalibratedOutingScores,
    CalibrationPopulation,
    CalibrationTerm,
    CalibrationTerms,
    CurveStatus,
    DeclaredModel,
    Exclusion,
    FrozenCurve,
    MetricValue,
    ModelKind,
    OutingOutcome,
    OutingScores,
    ParameterSet,
    RollingDeclaration,
    RollingPerformance,
    RollingRule,
    Scenario,
    ScenarioClockTerms,
    ShareScope,
    ShareUnavailability,
    Sport,
    Unavailability,
)
from test_estimation_curve import DEFAULTS
from test_og1_origin import PROFILE, activity_pair, corpus, origin_selection

WINDOW = 7
COMPARATOR = DeclaredModel(
    ModelKind.V0_RECALIBRATED,
    ENGINE_VERSION,
    ParameterSet(PROJECTION_PARAMETER_SPECS),
    "calage D9.2 par performance évaluée, scénario et horloge, sur C_j^eff",
)
READING = ParameterSet(PROJECTION_PARAMETER_SPECS)
OUTINGS = (Q20, Q27, P03)
Mutation = Callable[[int, dict[str, Any]], None]


def season() -> Any:
    pairs = [
        activity_pair(
            f"m{day:02d}",
            datetime(2026, 5, day, 8, tzinfo=UTC),
            index_elapsed_s=None,
            recording_s=3600.0 if day < 13 else 4320.0,
        )
        for day in range(6, 20)
    ]
    return corpus(pairs, athlete=ATHLETE)


def rule() -> RollingRule:
    return RollingRule(
        athlete_ref=ATHLETE,
        commit=COMMIT,
        window_days=WINDOW,
        source_activity_types=("trail_running",),
        min_duration_s=None,
        max_duration_s=None,
        max_elapsed_s=None,
        hr_center_bpm=None,
        value="somme",
        parameters={k: float(v) for k, v in DEFAULTS.values.items()},
        profile_parameters={k: float(v) for k, v in PROFILE.values.items()},
        diagnostic_support_threshold_min=10.0,
    )


def _sha(value: object) -> str:
    return content_hash(encode_document(value, 6))


@dataclasses.dataclass
class World:
    curves: list[FrozenCurve | AbsentCurve]
    entries: list[RollingPerformance]
    refs: list[str | None]


def world(mutate: Mutation | None = None) -> World:
    """Les documents de courbe des trois performances, chacun relu de ses octets ;
    ``mutate(k, compagnon)`` réécrit le compagnon figé (ou le document d'absence) de la
    performance ``k`` avant son figement."""
    found = World([], [], [])
    corpus_ = season()
    for k, outing in enumerate(OUTINGS):
        moment = origin(outing.start_time.date())
        result = estimate_at_origin(
            corpus_,
            ATHLETE,
            moment,
            WINDOW,
            origin_selection(),
            DEFAULTS,
            PROFILE,
        )
        if result.estimate is None:
            document = json.loads(origin_absence_document(result, corpus_))
            if mutate is not None:
                mutate(k, document)
            absent = AbsentCurve(json.dumps(document, ensure_ascii=False, indent=2))
            found.curves.append(absent)
            found.entries.append(
                RollingPerformance(
                    CurveStatus.ABSENT,
                    _sha(absent),
                    None,
                    None,
                    None,
                    None,
                    ShareUnavailability.NO_CURVE,
                )
            )
            found.refs.append(None)
            continue
        provenance, estimation = origin_companion(
            result,
            corpus_,
            origin_selection(),
            DEFAULTS,
            PROFILE,
            commit=COMMIT,
            generated_at=at(0),
        )
        documents = curve_documents(result.rows, Sport.FOOT, provenance, estimation)
        companion = json.loads(freeze_companion(documents.companion))
        if mutate is not None:
            mutate(k, companion)
        frozen = FrozenCurve(
            documents.csv.decode("utf-8"),
            json.dumps(companion, ensure_ascii=False, indent=2) + "\n",
        )
        name = f"og2-{outing.start_time.date().isoformat()}-w{WINDOW}.csv"
        read = read_curve_documents(
            documents.csv,
            frozen.companion.encode("utf-8"),
            name,
            READING,
            generated_at=at(0),
        )
        unreadable = curve_csv_support(documents.csv, 10.0)[1] is not None
        status = CurveStatus.NO_READ_SUPPORT if unreadable else CurveStatus.CURVE
        found.curves.append(frozen)
        found.entries.append(
            RollingPerformance(
                status,
                _sha(frozen),
                frozen.csv_sha256,
                read.curve_ref,
                0.2 if status is CurveStatus.CURVE else None,
                ShareScope.USAGE if status is CurveStatus.CURVE else None,
                None if status is CurveStatus.CURVE else ShareUnavailability.NO_CURVE,
            )
        )
        found.refs.append(read.curve_ref)
    return found


def rolling_declaration(built: World) -> Any:
    return declaration(
        models=(V0_RAW, COMPARATOR),
        curve_ref=None,
        curve=None,
        curve_metadata=None,
        rolling=RollingDeclaration(
            rule=_sha(rule()),
            window_days=WINDOW,
            command_windows=(WINDOW,),
            covered_threshold=0.1,
            beyond_marker=0.5,
            coverage_tolerance_s=60.0,
            index_sha256="b" * 64,
            platform="plateforme de test",
            performances=tuple(built.entries),
        ),
    )


def _on_curve(scores: OutingScores, curve_ref: str) -> OutingScores:
    def moved(scenario: Any) -> Any:
        if scenario is None:
            return None
        forecast = dataclasses.replace(scenario.forecast, curve_ref=curve_ref)
        return dataclasses.replace(scenario, forecast=forecast)

    return dataclasses.replace(
        scores, control=moved(scores.control), usage=moved(scores.usage)
    )


def _scaled(scores: OutingScores, factor: float, *, broken: bool = False) -> Any:
    def scaled(scenario: Any) -> Any:
        if scenario is None:
            return None
        values = tuple(p * factor for p in scenario.forecast.segment_s)
        if broken:
            values = (None, *values[1:])
        forecast = dataclasses.replace(scenario.forecast, segment_s=values)
        return dataclasses.replace(scenario, forecast=forecast)

    return dataclasses.replace(
        scores, control=scaled(scores.control), usage=scaled(scores.usage)
    )


def _comparator(
    outing_id: str, scores: OutingScores, member: OutingScores | None
) -> tuple[CalibratedOutingScores, CalibrationTerms]:
    """Les scores du comparateur sur la sortie, calés sur ``member`` (le jour de Q20),
    et ses termes, ceux de ``member_totals`` (E6)."""
    day = Q27.start_time.date() if member is not None else Q20.start_time.date()
    if member is None:
        calibrated = not_calibrated(outing_id, ModelKind.V0_RECALIBRATED, scores)
        sets = tuple(
            ScenarioClockTerms(s, clock, ())
            for s in (Scenario.CONTROL, Scenario.USAGE)
            for clock in CLOCKS
        )
        order = tuple(Scenario)
        sets = tuple(sorted(sets, key=lambda t: order.index(t.scenario)))
        return calibrated, CalibrationTerms(ModelKind.V0_RECALIBRATED, sets)
    member_day = Q20.start_time.date()
    population = CalibrationPopulation(day, origin(day), (member_day,), ())
    members = {member_day: (member,)}
    scenarios: dict[Scenario, Any] = {}
    sets_by: dict[Scenario, list[ScenarioClockTerms]] = {}
    for scenario, unscaled in (
        (Scenario.CONTROL, scores.control),
        (Scenario.USAGE, scores.usage),
    ):
        if unscaled is None:
            continue
        calibrations = tuple(
            calibrate(population, ModelKind.V0_RECALIBRATED, scenario, i, members)
            for i in range(len(CLOCKS))
        )
        usage = scores.usage
        base = usage.forecast if scenario is Scenario.USAGE and usage else None
        scenarios[scenario] = calibrated_scores(
            scores.observation, unscaled.forecast, calibrations, base=base
        )
        entries = []
        for i, calibration in enumerate(calibrations):
            terms = []
            for day_ in calibration.population:
                totals = member_totals(members[day_], scenario, i)
                assert not isinstance(totals, Unavailability)
                terms.append(CalibrationTerm(day_, totals[0], totals[1]))
            entries.append(ScenarioClockTerms(scenario, CLOCKS[i], tuple(terms)))
        sets_by[scenario] = entries
    calibrated = CalibratedOutingScores(
        outing_id,
        scores.observation,
        scenarios[Scenario.CONTROL],
        scenarios.get(Scenario.USAGE),
    )
    present = [s for s in Scenario if s in sets_by]
    sets = tuple(item for s in present for item in sets_by[s])
    return calibrated, CalibrationTerms(ModelKind.V0_RECALIBRATED, sets)


def result_documents(
    built: World,
    *,
    member_factor: float = 1.5,
    broken: bool = False,
    terms_change: Callable[[CalibrationTerms], CalibrationTerms] | None = None,
) -> tuple[tuple[OutingOutcome, ...], RollingDocuments]:
    """Les sorties scorées (Q20 et Q27, par v0 brut et le comparateur ; P03, sans
    courbe, non scorée) et les documents glissants du RÉSULTAT."""
    found: list[OutingOutcome] = []
    terms: list[CalibrationTerms | None] = []
    q20_v0: OutingScores | None = None
    for k, outing in enumerate(OUTINGS[:2]):
        curve_ref = built.refs[k]
        assert curve_ref is not None
        v0 = _on_curve(v0_of(outing.outing_id), curve_ref)
        member = None
        if k == 1:
            assert q20_v0 is not None
            member = _scaled(_on_curve(q20_v0, curve_ref), member_factor, broken=broken)
        calibrated, document = _comparator(outing.outing_id, v0, member)
        if k == 1 and terms_change is not None:
            document = terms_change(document)
        base = outcome(outing.outing_id)
        found.append(
            OutingOutcome(
                outing.outing_id,
                base.coverage,
                ((ModelKind.V0_RAW, v0), (ModelKind.V0_RECALIBRATED, calibrated)),
            )
        )
        terms.append(document)
        if k == 0:
            q20_v0 = v0_of(outing.outing_id)
    terms.append(None)
    return tuple(found), RollingDocuments(rule(), tuple(built.curves), tuple(terms))


UNSCORED = (Exclusion(P03.outing_id, "sortie non tracée"),)


def append_all(
    tmp_path: Path,
    built: World,
    **options: Any,
) -> Path:
    root = registry_root(tmp_path)
    append_declaration(root, rolling_declaration(built), recorded_at=at(0))
    scored, documents = result_documents(built, **options)
    append_result(
        root,
        1,
        scored,
        unscored=UNSCORED,
        references=references(),
        rolling=documents,
        recorded_at=at(1),
    )
    return root


def refused(tmp_path: Path, built: World, fragment: str, **options: Any) -> None:
    with pytest.raises(RegistryError) as error:
        append_all(tmp_path, built, **options)
    assert fragment in str(error.value), str(error.value)


# --- Le registre exact ---------------------------------------------------------------


def test_the_world_has_two_distinct_curves_and_an_absence() -> None:
    built = world()
    statuses = [entry.status for entry in built.entries]
    assert statuses == [CurveStatus.CURVE, CurveStatus.CURVE, CurveStatus.ABSENT]
    assert built.entries[0].curve_sha256 != built.entries[1].curve_sha256
    assert built.refs[0] != built.refs[1]


def test_the_exact_registry_is_accepted(tmp_path: Path) -> None:
    built = world()
    root = append_all(tmp_path, built)
    log = verify_registry(root)
    assert [event.format_version for event in log.events] == [6, 6]
    result = log.events[1].result
    assert result is not None
    assert result.rolling is not None
    assert result.rolling.curves == tuple(entry.document for entry in built.entries)


def test_a_forecast_on_another_performance_curve_is_refused(tmp_path: Path) -> None:
    """Condition 6 : les prévisions de chaque performance nomment sa courbe. Les deux
    performances ``curve`` échangent leurs courbes dans le RÉSULTAT (chacune nomme une
    courbe de la DÉCLARATION, mais pas la sienne) : refusé."""
    built = world()
    swapped = dataclasses.replace(built, refs=[built.refs[1], built.refs[0], None])
    refused(tmp_path, swapped, "courbe différente de la déclaration")


def test_the_comparator_is_calibrated_away_from_zero(tmp_path: Path) -> None:
    """La précondition du cas « β changé de 1e−9 » : ``|β| >= 0,01``, sinon, à
    ``τ·max(1, |β|)``, le changement serait accepté sans faute."""
    scored, _ = result_documents(world())
    calibrated = scored[1].scores[1][1]
    assert isinstance(calibrated, CalibratedOutingScores)
    assert calibrated.usage is not None
    beta = calibrated.usage.clocks[0].calibration.beta
    assert beta is not None
    assert abs(beta) >= 0.01


# --- Les réécritures d'A6 ------------------------------------------------------------


def _candidate(document: dict[str, Any]) -> dict[str, Any]:
    lines = document["estimation"]["origin"]["activities"]
    line: dict[str, Any] = next(x for x in lines if x["decision"] == "candidate")
    return line


def test_a_removed_candidate_is_refused(tmp_path: Path) -> None:
    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 0:
            line = _candidate(document)
            line["decision"] = "finie avant la fenêtre"
            line["fate"] = None
            line["contributes"] = False

    refused(tmp_path, world(mutate), "condition 3 bis")


def test_a_recording_end_after_the_origin_is_refused(tmp_path: Path) -> None:
    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 0:
            line = _candidate(document)
            line["recording_end"] = "2026-05-13T08:00:00+00:00"

    refused(tmp_path, world(mutate), "condition 3 bis")


def test_a_lower_bound_moved_back_is_refused(tmp_path: Path) -> None:
    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 0:
            section = document["estimation"]["origin"]
            bound = datetime.fromisoformat(section["lower_bound"])
            section["lower_bound"] = (bound - timedelta(days=90)).isoformat()

    refused(tmp_path, world(mutate), "condition 2 bis")


def test_a_threshold_raised_with_a_projectable_verdict_is_refused(
    tmp_path: Path,
) -> None:
    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 0:
            document["diagnostic_support_threshold_min"] = 40.0
            document["estimation"]["projectable"] = True

    refused(tmp_path, world(mutate), "condition 2)")


def test_a_rewritten_history_is_accepted(tmp_path: Path) -> None:
    """L'historique ne se vérifie pas (3 ter) : aucune ligne n'a d'écoulé d'index,
    l'inégalité tient."""

    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 0:
            history = document["estimation"]["origin"]["history"]
            for key in history:
                history[key] = 3

    verify_registry(append_all(tmp_path, world(mutate)))


def test_a_non_candidate_marked_contributing_is_refused(tmp_path: Path) -> None:
    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 1:
            lines = document["estimation"]["origin"]["activities"]
            line = next(x for x in lines if x["decision"] == "finie avant la fenêtre")
            line["contributes"] = True

    refused(tmp_path, world(mutate), "condition 3)")


def test_another_recording_digest_is_refused(tmp_path: Path) -> None:
    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 1:
            lines = document["estimation"]["origin"]["activities"]
            line = next(x for x in lines if x["activity_ref"] == "m06")
            line["recording_sha256"] = "c" * 64

    refused(tmp_path, world(mutate), "condition 4)")


def test_an_absence_of_another_threshold_is_refused(tmp_path: Path) -> None:
    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 2:
            document["support_threshold_min"] = 5.0

    refused(tmp_path, world(mutate), "condition 2)")


def test_the_index_digest_is_the_declared_one(tmp_path: Path) -> None:
    def mutate(k: int, document: dict[str, Any]) -> None:
        if k == 2:
            document["origin"]["index_sha256"] = "e" * 64

    refused(tmp_path, world(mutate), "condition 4)")


# --- Le calage (condition 7) ---------------------------------------------------------


def _shift(document: CalibrationTerms, change: Callable[[float], float]) -> Any:
    first = document.sets[0]
    term = first.terms[0]
    moved = dataclasses.replace(term, observed_s=change(term.observed_s))
    sets = (
        dataclasses.replace(first, terms=(moved, *first.terms[1:])),
        *document.sets[1:],
    )
    return dataclasses.replace(document, sets=sets)


def test_a_beta_changed_by_1e_9_is_refused(tmp_path: Path) -> None:
    built = world()
    scored, _ = result_documents(built)
    calibrated = scored[1].scores[1][1]
    assert isinstance(calibrated, CalibratedOutingScores)
    beta = calibrated.control.clocks[0].calibration.beta
    assert beta is not None
    assert abs(beta) >= 0.01
    delta = 1e-9 * abs(beta)
    refused(
        tmp_path,
        built,
        "condition 7",
        terms_change=lambda document: _shift(document, lambda t: t * math.exp(delta)),
    )


def test_a_beta_changed_by_one_ulp_is_accepted(tmp_path: Path) -> None:
    built = world()
    verify_registry(
        append_all(
            tmp_path,
            built,
            terms_change=lambda document: _shift(
                document, lambda t: math.nextafter(t, math.inf)
            ),
        )
    )


def test_a_model_error_with_an_absent_forecast_is_accepted(tmp_path: Path) -> None:
    built = world()
    scored, documents = result_documents(built, broken=True)
    calibrated = scored[1].scores[1][1]
    assert isinstance(calibrated, CalibratedOutingScores)
    status = calibrated.control.clocks[0].calibration.unavailability
    assert status is Unavailability.MODEL_ERROR
    terms = documents.calibration_terms[1]
    assert terms is not None
    assert terms.sets[0].terms[0].forecast_s is None
    verify_registry(append_all(tmp_path, built, broken=True))


def test_terms_of_another_population_are_refused(tmp_path: Path) -> None:
    def other_day(document: CalibrationTerms) -> CalibrationTerms:
        first = document.sets[0]
        term = dataclasses.replace(first.terms[0], civil_date=date(2026, 5, 1))
        sets = (dataclasses.replace(first, terms=(term,)), *document.sets[1:])
        return dataclasses.replace(document, sets=sets)

    refused(tmp_path, world(), "condition 7", terms_change=other_day)


# --- Sans documents (conditions 1 à 4) ------------------------------------------------


def test_a_rolling_result_answers_a_rolling_declaration(tmp_path: Path) -> None:
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    _, documents = result_documents(world())
    with pytest.raises(RegistryError, match="un RÉSULTAT glissant répond"):
        append_result(root, 1, outcomes(), references=references(), rolling=documents)


def test_the_result_publishes_the_frozen_documents(tmp_path: Path) -> None:
    built = world()
    root = registry_root(tmp_path)
    append_declaration(root, rolling_declaration(built), recorded_at=at(0))
    scored, documents = result_documents(built)
    swapped = dataclasses.replace(
        documents,
        curves=(documents.curves[1], documents.curves[0], documents.curves[2]),
    )
    with pytest.raises(RegistryError, match="publie les documents que la DÉCLARATION"):
        append_result(
            root,
            1,
            scored,
            unscored=UNSCORED,
            references=references(),
            rolling=swapped,
        )


def test_without_curve_v0_does_not_score(tmp_path: Path) -> None:
    built = world()
    root = registry_root(tmp_path)
    append_declaration(root, rolling_declaration(built), recorded_at=at(0))
    scored, documents = result_documents(built)
    p03 = OutingOutcome(
        P03.outing_id,
        outcome(P03.outing_id).coverage,
        (
            (ModelKind.V0_RAW, v0_of(P03.outing_id)),
            (
                ModelKind.V0_RECALIBRATED,
                not_calibrated(
                    P03.outing_id, ModelKind.V0_RECALIBRATED, v0_of(P03.outing_id)
                ),
            ),
        ),
    )
    with pytest.raises(RegistryError, match="sans courbe, v0 brut et v0 \\+ effort"):
        append_result(
            root,
            1,
            (*scored, p03),
            references=references(),
            rolling=documents,
        )


def test_no_curve_outside_rolling_is_refused(tmp_path: Path) -> None:
    root = registry_root(tmp_path)
    append_declaration(root, declaration(), recorded_at=at(0))
    first = outcomes()[0]
    kind, scores = first.scores[0]
    assert isinstance(scores, OutingScores)
    assert scores.usage is not None
    clock = scores.usage.clocks[0]
    assert clock.usage_target is not None
    target = dataclasses.replace(
        clock.usage_target,
        q_usage=MetricValue(
            None, Unavailability.NO_CURVE, clock.usage_target.q_usage.count
        ),
    )
    usage = dataclasses.replace(
        scores.usage,
        clocks=(
            dataclasses.replace(clock, usage_target=target),
            *scores.usage.clocks[1:],
        ),
    )
    changed = dataclasses.replace(
        first, scores=((kind, dataclasses.replace(scores, usage=usage)),)
    )
    with pytest.raises(
        RegistryError, match="« sans courbe » n'existe qu'en mode glissant"
    ):
        append_result(root, 1, (changed, *outcomes()[1:]), references=references())
