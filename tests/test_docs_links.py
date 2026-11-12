"""Les liens relatifs de la documentation mènent à un fichier ou à un dossier qui existe
(refonte du README).

Les fichiers lus : ``README.md``, ``CONTRIBUTING.md`` et chaque ``docs/**/*.md`` sauf
``docs/DICTIONNAIRE_DONNEES.md`` (généré). Un lien est la cible d'un ``](cible)`` hors
d'un bloc clôturé ; il est relatif s'il ne commence ni par un schéma (``https:``…) ni
par ``#`` ; sa partie avant ``#`` se résout depuis le dossier du fichier.
Contre-épreuve dans ce fichier : un lien cassé, écrit dans un répertoire temporaire, est
rapporté ; un lien dans un bloc clôturé, un lien externe et une ancre ne le sont pas.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED = ROOT / "docs" / "DICTIONNAIRE_DONNEES.md"
LINK = re.compile(r"\]\(([^)\s]+)\)")
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:")


def documents() -> list[Path]:
    """``README.md``, ``CONTRIBUTING.md``, puis chaque ``docs/**/*.md`` sauf le
    dictionnaire généré."""
    pages = sorted(path for path in (ROOT / "docs").rglob("*.md") if path != GENERATED)
    return [ROOT / "README.md", ROOT / "CONTRIBUTING.md", *pages]


def relative_links(path: Path) -> list[tuple[int, str]]:
    """Les liens relatifs d'un fichier, hors des blocs clôturés : (ligne, cible)."""
    links: list[tuple[int, str]] = []
    fenced = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        for target in LINK.findall(line):
            if SCHEME.match(target) or target.startswith("#"):
                continue
            links.append((number, target))
    return links


def broken_links(path: Path) -> list[str]:
    """Les liens relatifs qui ne mènent à rien : ``fichier:ligne: cible``."""
    return [
        f"{path.name}:{number}: {target}"
        for number, target in relative_links(path)
        if not (path.parent / target.partition("#")[0]).exists()
    ]


def test_every_relative_link_leads_somewhere() -> None:
    pages = documents()
    seen = sum(len(relative_links(path)) for path in pages)
    assert seen >= 130
    assert [link for path in pages for link in broken_links(path)] == []


def test_a_broken_link_is_reported(tmp_path: Path) -> None:
    """Contre-épreuve : seul le lien cassé hors d'un bloc est rapporté."""
    (tmp_path / "la.md").write_bytes(b"")
    page = tmp_path / "page.md"
    text = (
        "[a](absent.md) [b](la.md#section) [c](https://example.org) [d](#ancre)\n"
        "\n"
        "```text\n"
        "[e](absent-dans-un-bloc.md)\n"
        "```\n"
    )
    page.write_bytes(text.encode("utf-8"))
    assert broken_links(page) == ["page.md:1: absent.md"]
