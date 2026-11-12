"""Le rapport D15 du mode glissant et le rapport de comparaison (OG-2, § 6.9 du brief
OG-2).

Les valeurs littérales (``mde``, l'IC95, ``q_usage`` commun, les contributeurs de B3)
viennent de l'oracle de la conception ; les ensembles se calculent depuis des
DÉCLARATIONS construites à la main, aux parts choisies. Puis la commande, sur le monde
de ``test_og2_rolling`` dont les trails commencent le 2026-06-03 : sous 4 et 28 jours,
des performances aux trois statuts ; « chaque champ lu » et les rapports."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from fixtures.backtest_world import ATHLETE, COMMIT, run_world
from mountain_perf import cli
from mountain_perf.backtest.codec import decode_document
from mountain_perf.backtest.report import (
    ClockRole,
    Contributors,
    aggregate_table,
    command_sets,
    common_usage_target,
    comparison_conclusion,
    contributor_means,
    is_beyond,
    is_covered,
    minimum_detectable_effect,
    pair_beyond,
    paired_difference,
    rolling_scored_performances,
    scored_performances,
    window_sets,
)
from mountain_perf.backtest.rolling import platform_label
from mountain_perf.backtest.student_t import student_t_quantile
from mountain_perf.config import data_dir
from mountain_perf.estimation.curve import CURVE_ESTIMATION_PARAMETER_SPECS
from mountain_perf.gpx import PROFILE_PARAMETER_SPECS
from mountain_perf.schemas import (
    CALIBRATED_MODELS,
    AbsentCurve,
    CalibrationTerms,
    CurveStatus,
    FrozenCurve,
    ModelKind,
    ParameterSet,
    RollingDeclaration,
    RollingPerformance,
    RollingRule,
    Scenario,
    ShareScope,
    ShareUnavailability,
)
from test_og2_format6 import absent_performance, no_read_performance, rolling
from test_og2_rolling import (
    activities,
    build_world,
    declarations,
    events,
    fix_world,
    registry,
)
from test_og2_rolling import rolling as rolling_command

S = 0.1
MARKER = 0.5
CSV_SHA = "0123456789ab" + "d" * 52
DAYS = [date(2026, 6, 3) + timedelta(days=k) for k in range(4)]


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch) -> None:
    fix_world(monkeypatch)


def share(value: float) -> RollingPerformance:
    return RollingPerformance(
        CurveStatus.CURVE,
        "a" * 64,
        CSV_SHA,
        f"og2.csv#{CSV_SHA[:12]}",
        value,
        ShareScope.USAGE,
        None,
    )


def declared(*entries: RollingPerformance) -> RollingDeclaration:
    return rolling(performances=entries, covered_threshold=S, beyond_marker=MARKER)


# --- Les frontières et les ensembles --------------------------------------------------


def test_a_share_at_s_is_covered() -> None:
    assert is_covered(S, S)
    assert not is_covered(math.nextafter(S, 1.0), S)
    sets = window_sets(DAYS[:2], declared(share(S), share(math.nextafter(S, 1.0))))
    assert sets.covered == (DAYS[0],)


def test_a_share_at_the_marker_is_not_beyond() -> None:
    assert not is_beyond(MARKER, MARKER)
    assert is_beyond(math.nextafter(MARKER, 1.0), MARKER)
    sets = window_sets(
        DAYS[:2], declared(share(MARKER), share(math.nextafter(MARKER, 1.0)))
    )
    assert sets.beyond == (DAYS[1],)


def test_window_sets_count_unavailable_shares_and_no_curve() -> None:
    multi = replace(
        share(0.2),
        out_of_support_share=None,
        share_scope=None,
        share_unavailability=ShareUnavailability.MULTI_OUTING_DAY,
    )
    sets = window_sets(
        DAYS, declared(share(0.05), multi, absent_performance(), no_read_performance())
    )
    assert sets.covered == (DAYS[0],)
    assert sets.beyond == ()
    assert sets.unavailable == (("no_curve", 2), ("multi_outing_day", 1))
    assert sets.no_curve == (("absent", 1), ("no_read_support", 1))


def test_the_command_sets_are_computed_not_deduced() -> None:
    """Une performance couverte (part = s) sous toutes ; une à s + 1 ulp sous 28 jours,
    couverte ailleurs ; une au-delà du repère sous 28 jours seulement ; une sans courbe
    sous 28 jours, hors du commun : le support n'est pas monotone, le commun se
    calcule."""
    w28 = declared(
        share(S), share(math.nextafter(S, 1.0)), share(0.7), absent_performance()
    )
    w56 = declared(share(S), share(0.05), share(0.3), share(0.2))
    everything = declared(share(0.01), share(S), share(0.3), share(0.2))
    sets = command_sets(DAYS, [w28, w56, everything])
    assert sets.common == tuple(DAYS[:3])
    assert sets.covered_under_all == (DAYS[0],)
    assert sets.beyond == ((DAYS[2],), (), ())


def test_beyond_without_curve_under_all_leaves_n() -> None:
    """Une performance au-delà du repère sous 28 jours et sans courbe sous tout le
    passé sort de ``n`` dans leur paire ; elle reste dans la paire avec 56 jours."""
    w28 = declared(share(0.7), share(0.6), share(0.05), share(0.05))
    w56 = declared(share(0.3), share(0.3), share(0.05), share(0.05))
    everything = declared(
        absent_performance(), share(0.2), share(0.05), no_read_performance()
    )
    windows = [w28, w56, everything]
    assert window_sets(DAYS, w28).beyond == (DAYS[0], DAYS[1])
    assert pair_beyond(DAYS, windows, 0, 2) == (DAYS[1],)
    assert pair_beyond(DAYS, windows, 0, 1) == (DAYS[0], DAYS[1])


# --- L'issue probable, Student --------------------------------------------------------


def test_the_table_quantiles_by_hand() -> None:
    assert round(student_t_quantile(0.975, 10), 6) == 2.228139
    assert round(student_t_quantile(0.8, 10), 6) == 0.879058


def test_mde_by_hand() -> None:
    """``mde`` ≈ 0,0237 à n = 11 et 0,0151 à n = 24 (t lus à n − 1)."""
    eleven = minimum_detectable_effect(11)
    assert eleven is not None
    assert round(eleven, 4) == 0.0237
    twenty_four = minimum_detectable_effect(24)
    assert twenty_four is not None
    assert round(twenty_four, 4) == 0.0151
    assert minimum_detectable_effect(1) is None
    assert minimum_detectable_effect(0) is None


def _eleven_differences() -> list[float]:
    """Onze différences de moyenne −0,010 et d'écart-type 0,0253 (``n − 1``)."""
    z = [float(k) for k in range(-5, 6)]
    spread = math.sqrt(math.fsum(v * v for v in z) / 10)
    return [-0.010 + 0.0253 * v / spread for v in z]


def test_student_interval_by_hand() -> None:
    """11 performances de moyenne −0,010 et d'écart-type 0,0253 : IC95 [−0,027 ;
    +0,007], qui contient 0."""
    found = paired_difference([(0.0, d) for d in _eleven_differences()])
    assert found.count == 11
    assert found.mean is not None
    assert round(found.mean, 3) == -0.010
    assert found.interval is not None
    low, high = found.interval
    assert (round(low, 3), round(high, 3)) == (-0.027, 0.007)
    assert comparison_conclusion([found.interval]) is True


def test_paired_signs_and_small_samples() -> None:
    """B3 : ``k / n`` et les deux signes, sur les valeurs absolues ; un seul couple n'a
    pas d'IC95."""
    found = paired_difference([(0.2, 0.1), (0.1, -0.2), (0.3, 0.3)])
    assert (found.later_better, found.earlier_better, found.ties) == (1, 1, 1)
    single = paired_difference([(0.2, 0.1)])
    assert single.interval is None
    assert single.mean == pytest.approx(-0.1)
    assert paired_difference([]).count == 0


def test_the_conclusion() -> None:
    """Un IC95 qui contient 0 : la phrase ; un qui l'exclut : aucune ; une seule
    couverte sous toutes (aucun IC95) : « indisponible »."""
    assert comparison_conclusion([(-0.01, 0.02), (-0.03, 0.001)]) is True
    assert comparison_conclusion([(-0.01, 0.02), (0.001, 0.03)]) is False
    one = paired_difference([(0.05, 0.04)])
    assert comparison_conclusion([one.interval]) is None
    assert comparison_conclusion([]) is None


# --- q_usage commun -------------------------------------------------------------------


def test_common_usage_target_by_hand() -> None:
    """``T`` = 100 s, ``P₂₈`` = 110 s, ``P_all`` = 105 s : commun 10 / 105, propre
    10 / 110."""
    assert common_usage_target([110.0], [100.0], [105.0]) == 0.09523809523809523
    assert common_usage_target([110.0], [100.0], [110.0]) == 0.09090909090909091


# --- Les contributeurs ----------------------------------------------------------------


def _b3_terms() -> list[tuple[date, float, float | None]]:
    days = [date(2026, 5, 1) + timedelta(days=k) for k in range(9)]
    logs = [0.022] * 3 + [0.102] * 6
    return [(d, 1000.0 * math.exp(x), 1000.0) for d, x in zip(days, logs, strict=True)]


def _outings(
    terms: list[tuple[date, float, float | None]], empty: int | None = None
) -> list[tuple[date, list[tuple[str, tuple[str, ...]]]]]:
    return [
        (d, [(f"s{k}", () if k == empty else (f"t{k}",))])
        for k, (d, _, _) in enumerate(terms)
    ]


def test_contributors_by_hand() -> None:
    """B3 (28 jours) : +0,022 sur 3 contributeurs, +0,102 sur les 6 autres."""
    terms = _b3_terms()
    found = contributor_means(terms, _outings(terms), frozenset({"t0", "t1", "t2"}))
    assert (found.contributors, found.members) == (3, 9)
    assert found.contributing_mean == pytest.approx(0.022, abs=1e-12)
    assert found.other_mean == pytest.approx(0.102, abs=1e-12)
    assert found.unmatched == ()


def test_contributors_unavailable_without_refs() -> None:
    """Un membre sans ``activity_refs`` : indisponible, jamais les moyennes des seuls
    membres renseignés."""
    terms = _b3_terms()
    found = contributor_means(terms, _outings(terms, empty=4), frozenset({"t0"}))
    assert found.unmatched == ("s4",)
    assert found.contributing_mean is None
    assert found.other_mean is None


def test_no_contributor_gives_a_dash() -> None:
    terms = _b3_terms()
    found = contributor_means(terms, _outings(terms), frozenset())
    assert found.contributors == 0
    assert found.contributing_mean is None
    assert found.other_mean is not None
    assert cli._contributors_text(found) == (
        "contributeurs 0/9 ; ln(T/P) moyen — sur les contributeurs, +0.075 sur les "
        "autres"
    )
    b3 = Contributors(3, 9, 0.022, 0.102, ())
    assert cli._contributors_text(b3) == (
        "contributeurs 3/9 ; ln(T/P) moyen +0.022 sur les contributeurs, +0.102 sur "
        "les autres"
    )
    every = contributor_means(
        terms, _outings(terms), frozenset(f"t{k}" for k in range(9))
    )
    assert every.other_mean is None


# --- La commande : chaque champ lu, les rapports --------------------------------------


def _report(name: str) -> str:
    return (data_dir() / "rapports" / name).read_text(encoding="utf-8")


def _run_three_statuses(root: Path) -> None:
    """Le monde aux trails à partir du 2026-06-03, sous 4 et 28 jours, le seuil des
    diagnostics à 5 min : sous 28 jours, des absences, des « aucun support au seuil de
    lecture » et des courbes."""
    manifest = build_world(root, activities(first=date(2026, 6, 3)))
    outcome = rolling_command(manifest, "4,28", "--rule-support-threshold", "5")
    assert outcome.code == 0, outcome.err


def _stored(sha: str) -> bytes:
    return (registry() / "documents" / f"{sha}.json").read_bytes()


def test_every_field_is_read(tmp_path: Path) -> None:
    """Chaque champ de ``RollingRule``, ``RollingDeclaration``, ``RollingPerformance``,
    ``RollingResult``, ``CalibrationTerms`` et du document d'absence, relus de
    l'exécution, les deux statuts « sans courbe » compris."""
    _run_three_statuses(tmp_path)
    found = declarations()
    results = [e.result for e in events() if e.result is not None]
    assert len(found) == len(results) == 2
    last = found[1].rolling
    assert last is not None
    assert {e.status for e in last.performances} == set(CurveStatus)
    index = (data_dir() / "interim" / "activities" / "index.json").read_bytes()
    for declaration, result, window in zip(found, results, (4, 28), strict=True):
        roll = declaration.rolling
        assert roll is not None
        rule = decode_document(_stored(roll.rule), RollingRule)
        assert rule == RollingRule(
            ATHLETE,
            COMMIT,
            window,
            ("trail_running",),
            None,
            None,
            None,
            None,
            "somme",
            dict(ParameterSet(CURVE_ESTIMATION_PARAMETER_SPECS).values),
            dict(ParameterSet(PROFILE_PARAMETER_SPECS).values),
            5.0,
        )
        assert roll.window_days == window
        assert roll.command_windows == (4, 28)
        assert (roll.covered_threshold, roll.beyond_marker) == (0.1, 0.5)
        assert roll.coverage_tolerance_s == 60.0
        assert roll.index_sha256 == hashlib.sha256(index).hexdigest()
        assert roll.platform == platform_label()
        assert result is not None
        published = result.rolling
        assert published is not None
        assert published.rule == roll.rule
        assert published.curves == tuple(e.document for e in roll.performances)
        items = zip(
            declaration.performances,
            roll.performances,
            published.calibration_terms,
            strict=True,
        )
        for item, entry, terms_sha in items:
            day = item.performance.civil_date
            if entry.status is CurveStatus.ABSENT:
                absent = decode_document(_stored(entry.document), AbsentCurve)
                absence = json.loads(absent.document)
                assert absence["athlete_ref"] == ATHLETE
                assert absence["outcome"] == "absence"
                assert absence["absence_reason"]
                assert absence["support_threshold_min"] == 5.0
                assert absence["origin"]["window"] == window
                assert absence["origin"]["outcome"] == "absence"
                assert (entry.curve_sha256, entry.curve_ref) == (None, None)
            else:
                frozen = decode_document(_stored(entry.document), FrozenCurve)
                companion = json.loads(frozen.companion)
                assert "generated_at" not in companion
                assert "commit" not in companion["estimation"]
                assert entry.curve_sha256 == frozen.csv_sha256
                assert entry.curve_ref == (
                    f"og2-{day.isoformat()}-w{window}.csv#{frozen.csv_sha256[:12]}"
                )
            if entry.status is CurveStatus.CURVE:
                assert entry.share_unavailability is None
                assert entry.out_of_support_share is not None
                assert entry.share_scope is ShareScope.USAGE
            else:
                assert entry.out_of_support_share is None
                assert entry.share_scope is None
                assert entry.share_unavailability is ShareUnavailability.NO_CURVE
            assert (terms_sha is not None) == (entry.status is CurveStatus.CURVE)
            if terms_sha is None:
                continue
            terms = decode_document(_stored(terms_sha), CalibrationTerms)
            assert terms.model is ModelKind.V0_RECALIBRATED
            for item_terms in terms.sets:
                for term in item_terms.terms:
                    assert term.civil_date < day
                    assert term.observed_s > 0
                    assert term.forecast_s is None or term.forecast_s > 0


def test_the_reports_of_the_command(tmp_path: Path) -> None:
    """Le rapport D15 de chaque fenêtre et la comparaison : la provenance glissante et
    ses phrases fixes ; les ensembles par motif ; une performance sans courbe comptée
    à « sans courbe » dans les manquants de v0 ; sans tout le passé, ``q_usage`` commun
    indisponible."""
    _run_three_statuses(tmp_path)
    names = sorted(p.name for p in (data_dir() / "rapports").iterdir())
    assert names == ["backtest-0002.txt", "backtest-0004.txt", "comparaison-0004.txt"]
    text = _report("backtest-0004.txt")
    assert "mode glissant, fenêtre 28 jours ; document de règle sha256 " in text
    assert "seuils de support 5 min (règle), 10 min (lecture, paramètre de v0)" in text
    assert (
        "Sous le calage (a), le niveau du comparateur ne dépend pas de la fenêtre ; "
        "les fenêtres se comparent sur v0 brut."
    ) in text
    assert "56 jours est un choix d'usage (rdw, 2026-11-01)" in text
    assert (
        "Courbes de mperf curve --at, mesurées à l'horloge et à la pente du moteur "
        "(0017)."
    ) in text
    assert (
        "2026-06-03 fenêtre du 2026-04-29 au 2026-05-27 (Paris) ; sans courbe : "
        in text
    )
    assert (
        "sans courbe : aucun support au seuil de lecture ; sans courbe à la lecture "
        "(10 min) ; projetable au seuil des diagnostics (5 min)"
    ) in text
    assert "part indisponible : sans courbe 9 ; sans courbe : absence 5, " in text
    assert "aucun support au seuil de lecture 4" in text
    assert "contributeurs : indisponible, sorties sans correspondance : " in text
    assert "manquants     répétabilité 5 sans courbe, 1 jour multi-sorties" in text
    comparison = _report("comparaison-0004.txt")
    assert "Issue probable : indisponible (n < 2)." in comparison
    assert (
        "IC95 de Student ; une paire lue, sans correction de multiplicité."
        in comparison
    )
    assert (
        "q_usage à dénominateur commun : indisponible (tout le passé n'est pas exécuté)"
    ) in comparison
    assert "Pas de conclusion : IC95 indisponibles (n < 2)." in comparison
    assert "Hypothèse (E15), non mesurée ici" in comparison


def test_one_window_writes_no_comparison(tmp_path: Path) -> None:
    manifest = build_world(tmp_path, activities(first=date(2026, 6, 3)))
    outcome = rolling_command(manifest, "28", "--rule-support-threshold", "5")
    assert outcome.code == 0, outcome.err
    names = sorted(p.name for p in (data_dir() / "rapports").iterdir())
    assert names == ["backtest-0002.txt"]


def test_the_all_aggregates_equal_the_declared_mode(tmp_path: Path) -> None:
    """Les entrées du mode glissant, sur les scores d'une exécution en mode « courbe
    déclarée », sont celles du mode déclaré : les agrégats « toutes » sont les
    mêmes."""
    run = run_world(tmp_path)
    declared_entries = scored_performances(run)
    entries = rolling_scored_performances(
        run.preparation.declaration, run.outings, (), run.calibration, run.bands
    )
    assert entries == declared_entries
    for model in (ModelKind.V0_RAW, *CALIBRATED_MODELS):
        for scenario in Scenario:
            assert aggregate_table(
                entries, scenario, ClockRole.ELAPSED, model
            ) == aggregate_table(declared_entries, scenario, ClockRole.ELAPSED, model)
