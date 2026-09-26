"""``mperf match``, sections 5 à 9 (§ 5b.11 et § 8.2b, test 7, du brief M4a-2b).

Paires de GPX synthétiques : la paire commitée de M4a-2a (X01 à 10 s), puis Passages,
rho bas, Hors ε, T05, Arrêt et Arrêt hors support écrites dans ``tmp_path`` par la
convention du § 7.0 (coordonnées en ``repr`` exact, instants entiers). Attendus
calculés en conception ; les tests de M4a-2a (``test_cli_match.py``) restent tels
quels.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from fixtures import matching as m
from fixtures import segments as s
from fixtures.matching import MATCH_REFERENCE_GPX, MATCH_TRACE_GPX, MatchCase
from mountain_perf.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def _report(capsys: pytest.CaptureFixture[str], reference: Path, trace: Path) -> str:
    code = main(["match", str(reference), str(trace)])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    return captured.out


def _pair_report(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    case: Callable[[], MatchCase],
) -> str:
    reference_text, trace_text = s.named_gpx_texts(case())
    reference, trace = tmp_path / "reference.gpx", tmp_path / "trace.gpx"
    reference.write_text(reference_text, encoding="utf-8")
    trace.write_text(trace_text, encoding="utf-8")
    return _report(capsys, reference, trace)


def _clock_lines(trace: str, admitted: str) -> list[str]:
    """Les cinq lignes d'horloges quand les cinq conventions sont égales."""
    return [
        f"             θ{k}  trace {trace}   admis {admitted}\n" for k in range(1, 6)
    ]


def test_committed_pair_sections_five_to_nine(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """X01 à 10 s : 3 segments admis sur 3, ancrage 50 m, couverture 90,57 %, écoulé
    admis 0:05:20, préfixe 3 / 505 / 0:05:20, horloges 0:04:20 / 0 / 0:01:00 partout,
    ``I_sens,A`` [0:04:20 ; 0:05:20], aucun épisode."""
    out = _report(capsys, FIXTURES / MATCH_REFERENCE_GPX, FIXTURES / MATCH_TRACE_GPX)
    assert "départ       ancré — b_0 25.00 m, durée avant départ 0:00:00\n" in out
    assert "             ambigus : aucun\n" in out
    expected = [
        "segments     3 admis sur 3\n",
        "             borne non observée 0 (0.00 m), trou 0 (0.00 m)\n",
        "             rapport de longueur 0 (0.00 m), écart intérieur 0 (0.00 m)\n",
        "             ancrage exclu 50.00 m\n",
        "couverture   90.57 % — montée non évalué, plat 90.57 %, descente non évalué\n",
        "             écoulé admis 0:05:20\n",
        "             temps exclus : trou 0:00:00, rapport de longueur 0:00:00, "
        "écart intérieur 0:00:00\n",
        "             durées inconnues : 0 segment\n",
        "préfixe      3 segments, b_m 505.00 m, t*_m 0:05:20, dernier passage aucun\n",
        *_clock_lines("0:04:20 / 0:00:00 / 0:01:00", "0:04:20 / 0:00:00 / 0:01:00"),
        "             θ_bas θ1, θ_haut θ1, I_sens,A [0:04:20 ; 0:05:20]\n",
        "épisodes     sous θ_c : 0 épisode, 0:00:00\n",
    ]
    for line in expected:
        assert line in out
    assert out.index("ambigus") < out.index("segments     ")
    assert out.index("segments     ") < out.index("épisodes     ")


def test_passages_last_passage_and_unknown_durations(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Passages : dernier passage C, préfixe 2 / 500 ; trois segments borne non
    observée sur 510 m, trois durées inconnues."""
    out = _pair_report(capsys, tmp_path, s.passages)
    assert "segments     2 admis sur 5\n" in out
    assert "borne non observée 3 (510.00 m)" in out
    assert "             durées inconnues : 3 segments\n" in out
    assert (
        "préfixe      2 segments, b_m 500.00 m, t*_m 0:05:25, dernier passage C\n"
    ) in out


def test_low_ratio_is_a_length_ratio_exclusion(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """rho bas : 2 segments admis sur 3, un rapport de longueur de 250 m, temps exclu
    0:01:05, couverture 65,75 %, écoulé admis 0:04:00."""
    out = _pair_report(capsys, tmp_path, s.low_ratio)
    assert "segments     2 admis sur 3\n" in out
    assert "rapport de longueur 1 (250.00 m)" in out
    assert "temps exclus : trou 0:00:00, rapport de longueur 0:01:05," in out
    assert "couverture   65.75 % — montée non évalué, plat 65.75 %" in out
    assert "             écoulé admis 0:04:00\n" in out


def test_out_of_tolerance_has_no_admitted_segment(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Hors ε : aucun segment admis en section 8 ; préfixe 0, 0.00, non daté, aucun."""
    out = _pair_report(capsys, tmp_path, m.out_of_tolerance)
    assert "             θ_bas, θ_haut, I_sens,A : aucun segment admis\n" in out
    assert (
        "préfixe      0 segment, b_m 0.00 m, t*_m non daté, dernier passage aucun\n"
    ) in out


def test_t05_gap_exclusion_and_clocks(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """T05 : un segment trou de 250 m, temps exclu 0:04:10, couverture 50,98 %,
    écoulé admis 0:04:20 ; trace 0:07:11 / 0 / 0:01:19 et support admis
    0:04:03 / 0 / 0:00:17 sous chaque convention ; ``I_sens,A`` [0:04:03 ; 0:04:20]."""
    out = _pair_report(capsys, tmp_path, m.t05)
    assert "segments     2 admis sur 3\n" in out
    assert "trou 1 (250.00 m)" in out
    assert "temps exclus : trou 0:04:10," in out
    assert "couverture   50.98 %" in out
    assert "             écoulé admis 0:04:20\n" in out
    for line in _clock_lines(
        "0:07:11 / 0:00:00 / 0:01:19", "0:04:03 / 0:00:00 / 0:00:17"
    ):
        assert line in out
    assert "I_sens,A [0:04:03 ; 0:04:20]\n" in out


def test_stop_extremes_and_episodes_under_the_central_convention(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Arrêt : ``θ_bas`` θ3, ``θ_haut`` θ5, ``I_sens,A`` [0:08:17 ; 0:10:17] ; un
    épisode sous ``θ_c``, 0:01:24 (sous θ1, on lirait 0:01:22)."""
    out = _pair_report(capsys, tmp_path, s.stop)
    assert "             θ_bas θ3, θ_haut θ5, I_sens,A [0:08:17 ; 0:10:17]\n" in out
    assert "épisodes     sous θ_c : 1 épisode, 0:01:24\n" in out


def test_stop_off_support_is_counted_on_the_trace(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Arrêt hors support : 3 segments admis sur 4, un écart intérieur de 250 m, temps
    exclu 0:05:43, couverture 67,11 %, écoulé admis 0:05:40, préfixe 0 / 0.00 /
    0:00:00 ; sous θ1, trace 0:08:47 / 0:02:02 / 0:00:34 et support admis
    0:05:23 / 0 / 0:00:17 ; ``I_sens,A`` [0:05:23 ; 0:05:40] ; l'arrêt est hors du
    support, mais l'épisode est compté sur la trace : 1, 0:02:04."""
    out = _pair_report(capsys, tmp_path, s.stop_off_support)
    assert "segments     3 admis sur 4\n" in out
    assert "écart intérieur 1 (250.00 m)" in out
    assert "écart intérieur 0:05:43\n" in out
    assert "couverture   67.11 %" in out
    assert "             écoulé admis 0:05:40\n" in out
    assert (
        "préfixe      0 segment, b_m 0.00 m, t*_m 0:00:00, dernier passage aucun" in out
    )
    assert (
        "             θ1  trace 0:08:47 / 0:02:02 / 0:00:34   "
        "admis 0:05:23 / 0:00:00 / 0:00:17\n"
    ) in out
    assert "             θ_bas θ1, θ_haut θ1, I_sens,A [0:05:23 ; 0:05:40]\n" in out
    assert "épisodes     sous θ_c : 1 épisode, 0:02:04\n" in out


def test_two_stops_episodes_are_counted_under_the_central_convention(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """R1 (correctifs de la PR #10) : Deux arrêts, aux paramètres par défaut. Deux
    épisodes sous ``θ_c`` (0:03:24), un seul sous θ1 : c'est la seule paire où le
    **nombre** d'épisodes distingue la convention. Les segments ne sont pas ceux de
    la ligne du § 7.2b (``Δ = 100``) ; les épisodes ne dépendent pas de ``Δ``."""
    out = _pair_report(capsys, tmp_path, s.two_stops)
    assert "épisodes     sous θ_c : 2 épisodes, 0:03:24\n" in out
