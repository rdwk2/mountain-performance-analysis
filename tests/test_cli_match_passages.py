"""``mperf match``, section 10 (§ 6.10 et § 8.3, test 7, du brief M4a-3).

Paires de GPX synthétiques écrites dans ``tmp_path`` par ``named_gpx_texts``
(coordonnées en ``repr`` exact, instants entiers) : Passages, Égalité, Chronologie,
M05 ancré, Passages (M4a-2b), Arrêt à 35 m ; et la paire commitée de M4a-2a, sans
lieu nommé. La section 10 est la dernière du rapport : ses lignes sont comparées
**au texte près**, de la ligne ``passages`` à la fin. Aucun instant publié n'est à
moins de 0,1 s d'une demi-seconde (§ 7.0). Les tests de ``test_cli_match.py`` et
``test_cli_match_segments.py`` restent tels quels.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from fixtures import passages as p
from fixtures.matching import MATCH_REFERENCE_GPX, MATCH_TRACE_GPX, MatchCase
from fixtures.segments import named_gpx_texts
from mountain_perf.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
INDENT = " " * 13


def _section_ten(out: str) -> list[str]:
    """Les lignes de la section 10, qui suit la section 9 et finit le rapport."""
    assert out.index("épisodes     sous θ_c") < out.index("passages     ")
    return out[out.index("passages     ") :].splitlines()


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
    reference_text, trace_text = named_gpx_texts(case())
    reference, trace = tmp_path / "reference.gpx", tmp_path / "trace.gpx"
    reference.write_text(reference_text, encoding="utf-8")
    trace.write_text(trace_text, encoding="utf-8")
    return _report(capsys, reference, trace)


EXPECTED: dict[str, tuple[Callable[[], MatchCase], list[str]]] = {
    "Passages": (
        p.passages,
        [
            "passages     3 occurrences — trouvé 2, ancré 0, ambigu 0, absent 0, "
            "hors ε 0, tangente indéfinie 0, hors préfixe 1 ; comparables 2",
            f"{INDENT}B — 250.40 m, intermédiaire, trouvé, t* 0:04:10, arrivée "
            "0:04:10, départ 0:04:10, S 0:00:00, 0 épisode ; comparable",
            f"{INDENT}A — 375.00 m, intermédiaire, trouvé, t* 0:06:15, arrivée "
            "0:06:15, départ 0:08:08, S 0:01:36, 1 épisode ; comparable",
            f"{INDENT}C — 900.00 m, intermédiaire, hors préfixe ; indisponible "
            "(support insuffisant)",
            f"{INDENT}épisodes θ_c : attribués 1, sans candidate 0, non attribués 0",
        ],
    ),
    "Égalité": (
        p.tie,
        [
            "passages     2 occurrences — trouvé 2, ancré 0, ambigu 0, absent 0, "
            "hors ε 0, tangente indéfinie 0, hors préfixe 0 ; comparables 2",
            f"{INDENT}E1 — 370.30 m, intermédiaire, trouvé, t* 0:06:10, arrivée "
            "0:06:10, départ 0:06:10, S 0:00:00, 0 épisode ; comparable",
            f"{INDENT}E2 — 389.70 m, intermédiaire, trouvé, t* 0:08:30, arrivée "
            "0:08:30, départ 0:08:30, S 0:00:00, 0 épisode ; comparable",
            f"{INDENT}épisodes θ_c : attribués 0, sans candidate 0, non attribués 1",
            f"{INDENT}non attribué [0:06:32 ; 0:08:08]",
        ],
    ),
    "Chronologie": (
        p.chronology,
        [
            "passages     2 occurrences — trouvé 0, ancré 0, ambigu 2, absent 0, "
            "hors ε 0, tangente indéfinie 0, hors préfixe 0 ; comparables 0",
            f"{INDENT}W1 — 375.50 m, intermédiaire, ambigu (chronologie), t* 0:07:05, "
            "arrivée 0:06:27, départ 0:10:02, S 0:03:35, 1 épisode ; indisponible "
            "(ambigu)",
            f"{INDENT}W2 — 378.50 m, intermédiaire, ambigu (chronologie), t* 0:09:35, "
            "arrivée 0:09:35, départ 0:09:35, S 0:00:00, 0 épisode ; indisponible "
            "(ambigu)",
            f"{INDENT}épisodes θ_c : attribués 1, sans candidate 0, non attribués 0",
        ],
    ),
    "M05 ancré": (
        p.m05_anchored,
        [
            "passages     5 occurrences — trouvé 1, ancré 2, ambigu 0, absent 0, "
            "hors ε 0, tangente indéfinie 0, hors préfixe 2 ; comparables 2",
            f"{INDENT}Départ — 0.00 m, départ, ancré, t* 0:00:00, arrivée 0:00:00, "
            "départ 0:00:00, S 0:00:00, 0 épisode ; non cible",
            f"{INDENT}Avant — 8.00 m, intermédiaire, hors préfixe ; indisponible "
            "(support insuffisant)",
            f"{INDENT}Juste après — 12.70 m, intermédiaire, trouvé, t* 0:00:01, "
            "arrivée 0:00:01, départ 0:00:01, S 0:00:00, 0 épisode ; comparable",
            f"{INDENT}Presque — 1005.00 m, intermédiaire, hors préfixe ; indisponible "
            "(support insuffisant)",
            f"{INDENT}Fin — 1010.00 m, arrivée, ancré, t* 0:16:32, arrivée 0:16:32, "
            "départ 0:16:32, S 0:00:00, 0 épisode ; comparable",
            f"{INDENT}épisodes θ_c : attribués 0, sans candidate 0, non attribués 0",
        ],
    ),
    "Passages (M4a-2b)": (
        p.passages_m4a2b,
        [
            "passages     4 occurrences — trouvé 2, ancré 0, ambigu 0, absent 0, "
            "hors ε 0, tangente indéfinie 0, hors préfixe 2 ; comparables 2",
            f"{INDENT}A — 5.00 m, intermédiaire, hors préfixe ; indisponible "
            "(support insuffisant)",
            f"{INDENT}B — 300.00 m, intermédiaire, trouvé, t* 0:03:12, arrivée "
            "0:03:12, départ 0:03:12, S 0:00:00, 0 épisode ; comparable",
            f"{INDENT}C — 480.00 m, intermédiaire, trouvé, t* 0:05:12, arrivée "
            "0:05:12, départ 0:05:12, S 0:00:00, 0 épisode ; comparable",
            f"{INDENT}D — 700.00 m, intermédiaire, hors préfixe ; indisponible "
            "(support insuffisant)",
            f"{INDENT}épisodes θ_c : attribués 0, sans candidate 0, non attribués 0",
        ],
    ),
    "Arrêt à 35 m": (
        p.stop_at_35_m,
        [
            "passages     1 occurrence — trouvé 1, ancré 0, ambigu 0, absent 0, "
            "hors ε 0, tangente indéfinie 0, hors préfixe 0 ; comparables 1",
            f"{INDENT}Z — 345.00 m, intermédiaire, trouvé, t* 0:05:45, arrivée "
            "0:05:45, départ 0:05:45, S 0:00:00, 0 épisode ; comparable",
            f"{INDENT}épisodes θ_c : attribués 0, sans candidate 1, non attribués 0",
        ],
    ),
    "Coin coupé": (
        p.cut_corner,
        [
            "passages     1 occurrence — trouvé 0, ancré 0, ambigu 0, absent 1, "
            "hors ε 0, tangente indéfinie 0, hors préfixe 0 ; comparables 0",
            f"{INDENT}W — 766.00 m, intermédiaire, absent ; indisponible (absent)",
            f"{INDENT}épisodes θ_c : attribués 0, sans candidate 0, non attribués 0",
        ],
    ),
    "Hors ε": (
        p.out_of_tolerance,
        [
            "passages     1 occurrence — trouvé 0, ancré 0, ambigu 0, absent 0, "
            "hors ε 1, tangente indéfinie 0, hors préfixe 0 ; comparables 0",
            f"{INDENT}H — 375.50 m, intermédiaire, hors ε ; indisponible (absent)",
            f"{INDENT}épisodes θ_c : attribués 0, sans candidate 0, non attribués 0",
        ],
    ),
    "Aller-retour": (
        p.out_and_back,
        [
            "passages     3 occurrences — trouvé 2, ancré 0, ambigu 0, absent 0, "
            "hors ε 0, tangente indéfinie 1, hors préfixe 0 ; comparables 2",
            f"{INDENT}M — 300.00 m, intermédiaire, trouvé, t* 0:05:00, arrivée "
            "0:05:00, départ 0:05:00, S 0:00:00, 0 épisode ; comparable",
            f"{INDENT}T — 620.00 m, intermédiaire, tangente indéfinie ; indisponible "
            "(tangente indéfinie)",
            f"{INDENT}M — 940.00 m, intermédiaire, trouvé, t* 0:17:40, arrivée "
            "0:15:47, départ 0:17:40, S 0:01:36, 1 épisode ; comparable",
            f"{INDENT}épisodes θ_c : attribués 1, sans candidate 0, non attribués 0",
        ],
    ),
}
"""Section 10 attendue, au texte près : l'exemple du § 6.10 (Passages), les lignes
du § 8.3, test 7, et, par R1 des correctifs de la PR #12, les motifs ``absent`` et
``tangente indéfinie`` et le compte ``hors ε`` (Coin coupé, Hors ε, Aller-retour)."""


@pytest.mark.parametrize("pair", EXPECTED, ids=EXPECTED.keys())
def test_section_ten_of_a_pair(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, pair: str
) -> None:
    """Comptes par statut final, une ligne par occurrence dans l'ordre des passages,
    la ligne des épisodes, une ligne par épisode non attribué ; les épisodes sans
    candidate sont comptés, pas listés (Arrêt à 35 m)."""
    case, lines = EXPECTED[pair]
    assert _section_ten(_pair_report(capsys, tmp_path, case)) == lines


def test_section_ten_of_the_committed_pair(capsys: pytest.CaptureFixture[str]) -> None:
    """La paire commitée de M4a-2a n'a aucun lieu nommé : libellés invariables à
    zéro."""
    out = _report(capsys, FIXTURES / MATCH_REFERENCE_GPX, FIXTURES / MATCH_TRACE_GPX)
    assert _section_ten(out) == [
        "passages     0 occurrence — trouvé 0, ancré 0, ambigu 0, absent 0, hors ε 0, "
        "tangente indéfinie 0, hors préfixe 0 ; comparables 0",
        f"{INDENT}épisodes θ_c : attribués 0, sans candidate 0, non attribués 0",
    ]
