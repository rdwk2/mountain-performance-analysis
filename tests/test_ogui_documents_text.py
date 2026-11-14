"""Les documents d'OG-UI (§ 6.6 du brief) : les sections de ``0016`` et de ``0020``, le
``BACKLOG``, la recette ``project``, la règle 1 de ``CLAUDE.md`` et les documents
d'usage."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent.parent
DECISIONS = ROOT / "docs" / "decisions"
COMMANDS = ROOT / "docs" / "commandes"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_0016_has_its_og_ui_section_at_the_end() -> None:
    text = _text(DECISIONS / "0016-interface-v0.md")
    start = text.index("## OG-UI — la courbe à l'origine sur les pages (")
    assert text.index("## AN2-3 — les pages de la piste") < start
    assert "## " not in text[start + 3 :]
    section = text[start:]
    assert "Une page de texte, « La fenêtre »" in section
    assert "un enregistrement illisible, de n'importe quelle date, l'arrête." in section


def test_0020_has_its_og_ui_section_after_og_2() -> None:
    text = _text(DECISIONS / "0020-origine-glissante.md")
    og2 = text.index("## Précision OG-2 — la décision écrite une fois")
    ogui = text.index("## Précision OG-UI — les pages et la commande (")
    consequences = text.index("## Conséquences")
    assert og2 < ogui < consequences
    assert (
        "*Aucune décision de la règle ne change ; aucun octet écrit par "
        "`mperf curve` ne change.*"
    ) in text[ogui:consequences]
    assert "(`candidate_intervals`)" in text[ogui:consequences]


def test_the_backlog_lines() -> None:
    lines = _text(ROOT / "BACKLOG.md").split("\n")
    (window,) = [
        line
        for line in lines
        if line.startswith("- [x] ~~(OG-UI) Avertir des sorties en bordure de fenêtre")
    ]
    assert window.endswith(
        "~~ — fait le 2026-11-13 : PR OG-UI (la page « La fenêtre », liée depuis les "
        "deux pages)"
    )
    (report,) = [
        line
        for line in lines
        if line.startswith("- [x] ~~(OG-UI) Le rapport D15 glissant, présentation")
    ]
    assert report.endswith(
        "~~ — fait le 2026-11-13 : PR OG-UI (§ 6.3 bis ; et l'issue probable comptée "
        "sur les paires)"
    )
    engine = next(
        k
        for k, line in enumerate(lines)
        if line.startswith(
            "- [ ] (moteur) `ProjectionDiagnostics.out_of_support_time_share`"
        )
    )
    assert lines[engine + 1].startswith("- [ ] (OG, `0010` D2.2) Pour une courbe de ")
    assert lines[engine + 2].startswith("- [ ] (OG) `Inspection` : une fin sûre ")
    assert lines[engine + 3].startswith(
        "- [ ] (OG-UI) Les réglages de la règle sur les pages "
    )


def test_the_project_recipe() -> None:
    text = _text(ROOT / "justfile")
    assert (
        "project route *options:\n"
        "    uv run mperf project \"{{env_var('MPA_DATA_DIR')}}/routes/{{route}}\" "
        "{{options}}\n"
    ) in text
    assert "# (routes/, sorties/, reference/, interim/ ; processed/" in text


def test_claude_md_names_the_reading_commands_in_rule_1() -> None:
    text = _text(ROOT / "CLAUDE.md")
    rule = text[text.index("1. **Aucune donnée") : text.index("2. **`just check`")]
    assert "`just project`, `mperf project … --at`," in rule


def test_the_usage_documents() -> None:
    ui = _text(COMMANDS / "ui.md")
    assert "Cinq pages : " in ui
    assert "- **La page « La fenêtre »** : " in ui
    project = _text(COMMANDS / "project.md")
    assert "| `--at AAAA-MM-JJ` | le jour de la course : " in project
    (curve,) = [line for line in project.split("\n") if line.startswith("| `--curve ")]
    assert "**obligatoire**" not in curve
    readme = _text(ROOT / "README.md")
    assert "Cinq pages :" in readme
    assert "| [`just project`](docs/commandes/project.md) | " in readme
    commands = _text(COMMANDS / "README.md")
    assert "- [`just project`](project.md) — " in commands


def test_the_data_folder_names_interim_for_the_pages() -> None:
    """« Le dossier des données » dit qu'``interim/activities/`` est lu par l'interface
    et par la projection avec ``--at`` (§ 6.6 (i) 1)."""
    flat = " ".join(_text(COMMANDS / "README.md").split())
    assert (
        "(`just ui` : `routes/`, `sorties/`, `reference/`, `interim/activities/`, "
        "`processed/` et `resultats/Q1/` lus ;"
    ) in flat
    assert (
        "écrits par l'ajout d'un fichier) et à la projection (`just " + "project` : "
        "`routes/` lu ; avec `--at`, `interim/activities/` aussi"
    ) in flat
