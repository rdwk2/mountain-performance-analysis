"""Les documents d'OG-2 (§ 6.10 du brief OG-2) : les sections de ``0010`` et de
``0020``, à leur place ; les lignes du ``BACKLOG`` ; la recette glissante du
``justfile``. Aucune date n'est fixée : les sections portent celle de leur commit."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "docs" / "decisions"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _one(pattern: str) -> Path:
    (found,) = DECISIONS.glob(pattern)
    return found


def _section(text: str, title: str, following: str) -> str:
    """La section de titre ``title`` (sa date, quelle qu'elle soit), présente une seule
    fois et suivie, plus loin, de ``following``."""
    heading = re.compile(rf"^## {re.escape(title)} \(\d{{4}}-\d{{2}}-\d{{2}}\)$", re.M)
    matches = list(heading.finditer(text))
    assert len(matches) == 1, title
    start = matches[0].start()
    end = text.index(f"\n{following}\n", start)
    return text[start:end]


def test_the_section_of_0010_is_just_before_why() -> None:
    text = _text(_one("0010-*.md"))
    section = _section(text, "Précision OG-2 — le mode glissant", "## Pourquoi")
    assert "\n## " not in section[3:]
    for point in range(1, 14):
        assert f"\n{point}. **" in section, point
    assert "Le mode « courbe déclarée » ne change pas." in section
    assert (
        "jamais de dénominateur de repli (les poids publiés d'une cible "
        "« sans courbe »\n   restent ceux de la baseline elle-même ; rien ne les lit) ;"
    ) in section
    assert "`β = fsum(ln(T_c / P_c)) / n` à 1e−12 près" in section
    assert "56 jours est un choix d'usage (rdw, 2026-11-01)" in section
    assert "*Hypothèse, non mesurée*" in section


def test_the_section_of_0020_is_just_before_consequences() -> None:
    text = _text(_one("0020-*.md"))
    section = _section(
        text, "Précision OG-2 — la décision écrite une fois", "## Conséquences"
    )
    assert text.index("## Précision OG-1b") < text.index("## Précision OG-2")
    assert (
        "*Aucune décision de la règle ne change ; aucun octet écrit par `mperf curve` "
        "ne change.*"
    ) in section
    assert "vivent dans `estimation/decision.py`, écrites une fois" in section


BACKLOG_LINES = (
    "- [ ] (OG, admission en mode glissant) Un effet appris sur `C_j`",
    "- [ ] (OG) Une version de la règle qui survive à un changement de commit",
    "- [ ] (OG, mesure) Le calage (a) restreint aux membres dans la fenêtre",
    "- [ ] (OG) La sensibilité de D13 en mode glissant, refusée par OG-2",
    "- [ ] (OG) L'IC95 de la comparaison des fenêtres : Student",
    "- [ ] (OG) Les réglages de la règle en mode glissant",
    "- [ ] (OG) Les fourchettes des baselines d'une performance sans courbe",
    "- [ ] (OG) Le seuil de lecture réglable en mode glissant",
    "- [ ] (moteur) `ProjectionDiagnostics.out_of_support_time_share` peut valoir",
)


def test_the_backlog_lines_follow_the_og_lines_of_the_backtest() -> None:
    lines = _text(ROOT / "BACKLOG.md").split("\n")
    backtest = lines.index("## Backtest (0010)")
    anchor = next(
        k
        for k, line in enumerate(lines)
        if line.startswith("- [ ] (OG-UI) Avertir des sorties en bordure de fenêtre")
    )
    assert anchor > backtest
    for offset, start in enumerate(BACKLOG_LINES, start=1):
        assert lines[anchor + offset].startswith(start), start
    (m6a,) = [
        line
        for line in lines
        if line.startswith(
            "- [ ] (M6a, avant la première expérience sur la courbe neuve)"
        )
    ]
    assert m6a.endswith(
        "Réglé en mode glissant (OG-2) ; reste pour une courbe déclarée de "
        "`mperf curve`."
    )


def test_the_rolling_recipe() -> None:
    text = _text(ROOT / "justfile")
    recipe = (
        "# Le backtest glissant (OG-2, docs/decisions/0010, précision OG-2) : une "
        "DÉCLARATION par\n"
        "# fenêtre, en un processus ; refusé à Claude Code par le hook.\n"
        "backtest-rolling windows *options:\n"
        "    uv run mperf backtest \"{{env_var('MPA_DATA_DIR')}}/reference/"
        'manifeste.json" --rolling {{windows}} {{options}}\n'
    )
    assert text.count(recipe) == 1
    assert text.index("\nbacktest curve *options:\n") < text.index(recipe)
