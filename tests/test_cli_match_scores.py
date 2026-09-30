"""``mperf match --curve`` et ``--no-reference``, sections 11 à 13 (§ 6.7, § 7.5 et
§ 8.1, test 12, du brief M4b-2 ; ``0010`` D3, D5.4, D5.5, D7 ; décisions 4 à 6).

Les textes attendus du § 7.5 sont recopiés tels quels dans des fichiers de référence
de ``tests/fixtures/`` : ``scores_appariement.txt`` (106 lignes, la paire commitée),
``scores_appariement_sans_reference.txt`` (27 lignes, la trace seule avec
``--no-reference``), ``scores_passages_blocs.txt`` et ``scores_m05_ancre_blocs.txt``
(les blocs ``C_k`` et ``K`` de Passages et de M05 ancré, contigus). Sans ``--curve``,
la sortie est celle de ``main`` : les tests de ``mperf match`` existants restent tels
quels.
"""

import io
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from fixtures import passages as p
from fixtures.matching import MATCH_REFERENCE_GPX, MATCH_TRACE_GPX, MatchCase
from fixtures.segments import named_gpx_texts
from mountain_perf.cli import NO_REFERENCE_ERROR, main

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = FIXTURES / MATCH_REFERENCE_GPX
TRACE = FIXTURES / MATCH_TRACE_GPX
CURVE = FIXTURES / "courbe_synthetique.csv"
INDENT = " " * 13
LAST_OF_SECTION_TEN = f"{INDENT}épisodes θ_c : "


def _expected(name: str) -> list[str]:
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


def _run(capsys: pytest.CaptureFixture[str], *args: str | Path) -> list[str]:
    code = main(["match", *(str(a) for a in args)])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    return captured.out.splitlines()


def _pair(tmp_path: Path, case: Callable[[], MatchCase]) -> tuple[Path, Path]:
    reference_text, trace_text = named_gpx_texts(case())
    reference, trace = tmp_path / "reference.gpx", tmp_path / "trace.gpx"
    reference.write_text(reference_text, encoding="utf-8")
    trace.write_text(trace_text, encoding="utf-8")
    return reference, trace


def _contiguous(lines: list[str], block: list[str]) -> bool:
    return any(
        lines[i : i + len(block)] == block for i in range(len(lines) - len(block) + 1)
    )


# ---------------------------------------------------------------------------
# Sans --curve : la sortie de main
# ---------------------------------------------------------------------------


def test_without_curve_nothing_follows_section_ten(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Décision 6 (Q7) : sans ``--curve``, les sections 1 à 10 seules — 28 lignes sur
    la paire commitée, la dernière celle des épisodes de la section 10."""
    lines = _run(capsys, REFERENCE, TRACE)
    assert len(lines) == 28
    assert lines[-1].startswith(LAST_OF_SECTION_TEN)
    assert not [line for line in lines if line.startswith("v0 brut")]


# ---------------------------------------------------------------------------
# --curve : les textes du § 7.5
# ---------------------------------------------------------------------------


def test_curve_on_the_committed_pair(capsys: pytest.CaptureFixture[str]) -> None:
    """§ 7.5 ; décisions 4 à 6 : les sections 1 à 10 de ``main``, puis les 106 lignes
    des sections 11 à 13 au caractère près — v0 brut, usage (enveloppes, métriques
    sous ``écoulé``, ``M θ_bas``, ``(M+U) θ_haut``, diagnostic de D5.5 sous les
    lignes principales, ``C_k``, ``K``, écart d'arrivée), contrôle."""
    without = _run(capsys, REFERENCE, TRACE)
    lines = _run(capsys, REFERENCE, TRACE, "--curve", CURVE)
    assert lines[:28] == without
    assert lines[28:] == _expected("scores_appariement.txt")


def test_no_reference_on_the_trace_alone(capsys: pytest.CaptureFixture[str]) -> None:
    """``0010`` D3 (sortie sans référence) ; décision 4 : la trace seule avec
    ``--no-reference`` — les sections 1 à 10 de ce cas, puis 27 lignes : pas d'usage,
    le scénario contrôle seul."""
    without = _run(capsys, TRACE, TRACE)
    lines = _run(capsys, TRACE, TRACE, "--curve", CURVE, "--no-reference")
    assert lines[: len(without)] == without
    assert lines[len(without) :] == _expected("scores_appariement_sans_reference.txt")


@pytest.mark.parametrize(
    ("case", "count", "blocks"),
    [
        (p.passages, 110, "scores_passages_blocs.txt"),
        (p.m05_anchored, 112, "scores_m05_ancre_blocs.txt"),
    ],
    ids=["Passages", "M05 ancré"],
)
def test_curve_on_cases_with_places(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    case: Callable[[], MatchCase],
    count: int,
    blocks: str,
) -> None:
    """§ 7.5 (D3 de la passe 1) ; ``0010`` D7.3, D7.4 : la sortie sans ``--curve``,
    puis 110 (Passages) ou 112 (M05 ancré) lignes contenant, contigus et au
    caractère près, les blocs ``C_k`` et ``K`` — lieux disponibles et indisponibles,
    ``poids —``, ``arrivée (Fin)``, écart d'arrivée."""
    reference, trace = _pair(tmp_path, case)
    without = _run(capsys, reference, trace)
    lines = _run(capsys, reference, trace, "--curve", CURVE)
    assert lines[: len(without)] == without
    extra = lines[len(without) :]
    assert len(extra) == count
    assert _contiguous(extra, _expected(blocks))


def test_zero_time_segment_is_named_by_its_index(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """``0010`` D5.5 ; § 6.7 (D4 du contre-calcul) : dans Passages, le segment 3 n'est
    pas admis ; la ligne ``temps nuls`` du diagnostic désigne le segment de temps nul
    par son indice (4), pas par son rang parmi les admis (3) — deux fois, en usage
    et en contrôle."""
    reference, trace = _pair(tmp_path, p.passages)
    lines = _run(capsys, reference, trace, "--curve", CURVE)
    zero = f"{INDENT}temps nuls      —                   k 4                 —"
    assert lines.count(zero) == 2
    assert not [line for line in lines if "k 3" in line]


def test_single_report_clock_without_admitted_segment(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Choix 12 : sans segment admis (Départ non daté), l'écoulé seul au rapport,
    avec la mention ``(aucun segment admis)``."""
    reference, trace = _pair(tmp_path, p.undated_departure)
    lines = _run(capsys, reference, trace, "--curve", CURVE)
    (line,) = [line for line in lines if "horloges du rapport" in line]
    assert line == (
        f"{INDENT}effort 1.00, moteur projection-v0 ; horloges du rapport : "
        "écoulé (aucun segment admis)"
    )


# ---------------------------------------------------------------------------
# --no-reference : contrôlé toujours ; erreurs de lecture
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("curve", [False, True], ids=["sans --curve", "--curve"])
def test_no_reference_refuses_two_different_files(
    capsys: pytest.CaptureFixture[str], curve: bool
) -> None:
    """``0010`` D3 ; § 6.7 (A1 de la passe 1) : avec ``--no-reference``, la référence
    doit être la trace elle-même, contrôlé avec ou sans ``--curve``, avant toute
    sortie — code 1, le message sur stderr, rien sur stdout."""
    extra = ["--curve", str(CURVE)] if curve else []
    code = main(["match", str(REFERENCE), str(TRACE), "--no-reference", *extra])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err == NO_REFERENCE_ERROR + "\n"
    assert NO_REFERENCE_ERROR == (
        "Erreur : --no-reference : la référence doit être la trace elle-même (0010 D3)."
    )


def test_no_reference_without_curve_is_sections_one_to_ten(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A1 de la passe 1 : le même fichier deux fois, ``--no-reference`` sans
    ``--curve`` — les sections 1 à 10 seules, inchangées, code 0."""
    assert _run(capsys, TRACE, TRACE, "--no-reference") == _run(capsys, TRACE, TRACE)


def test_missing_curve_is_an_input_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Décision 6 : une courbe illisible est une erreur d'entrée, comme pour
    ``mperf project`` — code 1, message sur stderr ; lue avant toute sortie."""
    code = main(
        ["match", str(REFERENCE), str(TRACE), "--curve", str(tmp_path / "x.csv")]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err.startswith("Erreur : ")
    assert "Traceback" not in captured.err


def test_scores_are_utf8_under_a_cp1252_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Comme les tests de M4b-0 : ``−``, ``θ``, ``—``, ``∞`` sous une sortie
    redirigée en cp1252 — pas d'``UnicodeEncodeError``."""
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)
    assert main(["match", str(REFERENCE), str(TRACE), "--curve", str(CURVE)]) == 0
    stream.flush()
    text = raw.getvalue().decode("utf-8")
    assert (
        f"{INDENT}L               −0.693147           −0.485508           −0.693147"
        in text
    )
    assert f"{INDENT}arrivée ancrée, L − b_K 25.00 m" in text
