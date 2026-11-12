"""Les exemples du README sont les sorties réelles de ``mperf`` (§ 6.5 et § 8.1,
test 9, du brief M4b-3 ; règle de rdw du 2026-10-01).

Le ``README.md`` et les pages ``profile.md``, ``project.md`` et ``match.md`` de
``docs/commandes/`` (refonte du README) recopient au caractère près les sorties de
``mperf profile``, ``project``, ``match`` et ``match --curve`` sur les fixtures ; toute
PR qui change ces sorties ou les options de ``mperf`` met ces exemples à jour, rejoués.
Ce test lit ces fichiers sans les modifier :

- un **exemple** est un bloc ```` ```bash ```` dont l'unique ligne commence par
  ``uv run mperf `` ; le bloc clôturé suivant doit être un bloc ```` ```text ```` ;
- l'exemple est un **extrait** si le premier paragraphe non vide entre les deux blocs
  commence par « Extrait », sinon il est **complet** ;
- la commande s'exécute par ``mountain_perf.cli.main`` (les mots qui suivent
  ``uv run mperf``, découpés par ``shlex.split``), depuis la racine du dépôt ; code de
  retour 0 ;
- complet : les lignes de la sortie égalent celles du bloc ; extrait : les lignes du
  bloc forment une suite contiguë des lignes de la sortie.

Un exemple retiré ou ajouté à l'un de ces fichiers fait rougir le test du compte, qui
sera mis à jour avec lui ; un exemple écrit dans une autre page de la documentation
fait rougir le test qui les cherche. Contre-épreuves dans ce fichier : une page
modifiée, lue dans un répertoire temporaire, échoue. Une ligne retirée en tête ou en
fin d'extrait laisse une suite contiguë de la sortie : elle passe, par construction.
"""

import shlex
from dataclasses import dataclass
from pathlib import Path

import pytest

from mountain_perf.cli import main

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
COMMANDS = ROOT / "docs" / "commandes"
DOCUMENTS = (
    README,
    COMMANDS / "profile.md",
    COMMANDS / "project.md",
    COMMANDS / "match.md",
)
"""Les fichiers dont les exemples sont rejoués, dans l'ordre (refonte du README)."""
PREFIX = "uv run mperf "


@dataclass(frozen=True)
class Example:
    """Un exemple du README : la commande, ses arguments, le bloc attendu."""

    command: str
    arguments: tuple[str, ...]
    expected: tuple[str, ...]
    excerpt: bool


@dataclass(frozen=True)
class _Block:
    info: str
    body: tuple[str, ...]
    start: int
    end: int


def _blocks(lines: list[str]) -> list[_Block]:
    """Les blocs clôturés : langue, lignes, rang de l'ouverture et de la clôture."""
    blocks: list[_Block] = []
    opening: int | None = None
    for i, line in enumerate(lines):
        if not line.startswith("```"):
            continue
        if opening is None:
            opening = i
        else:
            info = lines[opening][3:].strip()
            blocks.append(_Block(info, tuple(lines[opening + 1 : i]), opening, i))
            opening = None
    return blocks


def readme_examples(path: Path) -> list[Example]:
    """Les exemples d'un README, dans l'ordre (§ 6.5 du brief M4b-3)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks = _blocks(lines)
    examples: list[Example] = []
    for block, following in zip(blocks, [*blocks[1:], None], strict=True):
        if not (
            block.info == "bash"
            and len(block.body) == 1
            and block.body[0].startswith(PREFIX)
        ):
            continue
        if following is None or following.info != "text":
            raise ValueError(
                f"l'exemple {block.body[0]!r} n'est pas suivi d'un bloc text"
            )
        between = lines[block.end + 1 : following.start]
        first = next((line for line in between if line.strip()), "")
        examples.append(
            Example(
                command=block.body[0],
                arguments=tuple(shlex.split(block.body[0])[3:]),
                expected=following.body,
                excerpt=first.startswith("Extrait"),
            )
        )
    return examples


def matches(example: Example, output: list[str]) -> bool:
    """Complet : lignes égales ; extrait : suite contiguë de la sortie."""
    expected = list(example.expected)
    if not example.excerpt:
        return output == expected
    n = len(expected)
    return any(output[i : i + n] == expected for i in range(len(output) - n + 1))


def _run(
    example: Example,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> list[str]:
    monkeypatch.chdir(ROOT)
    code = main(list(example.arguments))
    captured = capsys.readouterr()
    assert code == 0, captured.err
    return captured.out.splitlines()


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


CASES = [
    (document, example)
    for document in DOCUMENTS
    for example in readme_examples(document)
]
EXAMPLES = [example for _, example in CASES]


def test_each_document_has_its_examples() -> None:
    """Le README : ``project`` ; ``profile.md`` : ``profile`` ; ``project.md`` :
    ``project`` ; ``match.md`` : ``match``, puis ``match --curve``, seul extrait."""
    assert [
        (_relative(document), example.arguments[0], example.excerpt)
        for document, example in CASES
    ] == [
        ("README.md", "project", False),
        ("docs/commandes/profile.md", "profile", False),
        ("docs/commandes/project.md", "project", False),
        ("docs/commandes/match.md", "match", False),
        ("docs/commandes/match.md", "match", True),
    ]
    assert "--curve" in EXAMPLES[4].arguments


def _example_lines(path: Path) -> list[str]:
    """Les blocs ``bash`` d'une ligne qui commence par ``uv run mperf ``."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [
        block.body[0]
        for block in _blocks(lines)
        if block.info == "bash"
        and len(block.body) == 1
        and block.body[0].startswith(PREFIX)
    ]


def test_no_example_outside_the_documents() -> None:
    """Un exemple ``uv run mperf …`` n'est rejoué que dans ``DOCUMENTS`` : aucune autre
    page de la documentation n'en porte."""
    candidates = [ROOT / "CONTRIBUTING.md", *sorted((ROOT / "docs").rglob("*.md"))]
    read = [path for path in candidates if path not in DOCUMENTS]
    assert COMMANDS / "backtest.md" in read
    found = {_relative(path): _example_lines(path) for path in read}
    assert {name: lines for name, lines in found.items() if lines} == {}


@pytest.mark.parametrize(
    "index",
    range(len(EXAMPLES)),
    ids=[f"{_relative(d)}: {e.command[len(PREFIX) :]}" for d, e in CASES],
)
def test_readme_example_is_the_real_output(
    index: int, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    example = EXAMPLES[index]
    assert matches(example, _run(example, monkeypatch, capsys))


def _modified_examples(
    tmp_path: Path, document: Path, old: str, new: str
) -> list[Example]:
    """Les exemples d'une page modifiée, écrite dans ``tmp_path``."""
    text = document.read_text(encoding="utf-8")
    assert text.count(old) == 1
    path = tmp_path / document.name
    path.write_bytes(text.replace(old, new).encode("utf-8"))
    return readme_examples(path)


def test_a_changed_character_in_the_profile_block_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Contre-épreuve : un caractère changé dans le bloc de ``profile`` rougit."""
    original = EXAMPLES[1].expected[1]
    changed = original.replace("11 points", "12 points")
    assert changed != original
    example = _modified_examples(tmp_path, COMMANDS / "profile.md", original, changed)[
        0
    ]
    assert not matches(example, _run(example, monkeypatch, capsys))


def test_an_interior_line_removed_from_the_excerpt_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Contre-épreuve : une ligne **intérieure** retirée de l'extrait rougit."""
    excerpt = EXAMPLES[4].expected
    interior = len(excerpt) // 2
    block = "\n".join(excerpt)
    shortened = "\n".join(excerpt[:interior] + excerpt[interior + 1 :])
    example = _modified_examples(tmp_path, COMMANDS / "match.md", block, shortened)[1]
    assert len(example.expected) == len(excerpt) - 1
    assert not matches(example, _run(example, monkeypatch, capsys))
