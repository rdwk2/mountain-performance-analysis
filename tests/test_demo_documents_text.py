"""Les documents des profils de démo (M5-3, § 6.6 du brief) : la recette, la ligne de
``.gitignore``, la page de la commande et le record, la ligne de ``CLAUDE.md``."""

from __future__ import annotations

import subprocess
from pathlib import Path

from mountain_perf.demo.constantes import CHARACTER_NAMES, DEMO_PORT_BASE

ROOT = Path(__file__).resolve().parent.parent
RECIPE = (
    "# Les profils de démo (M5-3, docs/decisions/0022) : construit demo/<personnage>/ "
    "(données\n"
    "# inventées, ignorées par git) s'il manque, puis lance l'interface dessus, port "
    "8511 + rang.\n"
    "# Personnages : debutant, polyvalente, grimpeur, rouleur, moyen. Refusée à Claude "
    "Code par\n"
    "# le hook.\n"
    "demo personnage:\n"
    "    uv run --extra ingest --extra analyse --extra tableau mperf demo "
    '"{{personnage}}" --interface\n'
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_recipe() -> None:
    assert _text(ROOT / "justfile").count(RECIPE) == 1


def test_the_gitignore_line() -> None:
    assert "/demo/" in _text(ROOT / ".gitignore").splitlines()


def _check_ignore(path: str) -> int:
    """Le code de ``git check-ignore`` : 0 ignoré, 1 non ignoré, 128 un échec."""
    return subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", path], cwd=ROOT, check=False
    ).returncode


def test_the_demo_folders_are_ignored_but_not_the_package() -> None:
    assert _check_ignore("demo/polyvalente/demo.json") == 0
    assert _check_ignore("src/mountain_perf/demo/constantes.py") == 1


def test_the_command_page_names_the_characters_and_their_ports() -> None:
    page = _text(ROOT / "docs" / "commandes" / "demo.md")
    assert (ROOT / "docs" / "decisions" / "0022-profils-de-demo.md").is_file()
    for rank, name in enumerate(CHARACTER_NAMES):
        assert f"| `{name}` | {DEMO_PORT_BASE + rank} | " in page, name


def test_the_claude_md_command_line() -> None:
    assert (
        "just demo polyvalente  # les profils de démo (M5-3) : construit "
        "demo/<personnage>/, puis l'interface dessus"
    ) in _text(ROOT / "CLAUDE.md").splitlines()
