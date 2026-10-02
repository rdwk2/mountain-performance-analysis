"""Les exemples du README sont les sorties réelles de ``mperf`` (§ 6.5 et § 8.1,
test 9, du brief M4b-3 ; règle de rdw du 2026-10-01).

Le ``README.md`` recopie au caractère près les sorties de ``mperf profile``,
``project``, ``match`` et ``match --curve`` sur les fixtures ; toute PR qui change ces
sorties ou les options de ``mperf`` met ces exemples à jour, rejoués. Ce test lit le
``README.md`` sans le modifier :

- un **exemple** est un bloc ```` ```bash ```` dont l'unique ligne commence par
  ``uv run mperf `` ; le bloc clôturé suivant doit être un bloc ```` ```text ```` ;
- l'exemple est un **extrait** si le premier paragraphe non vide entre les deux blocs
  commence par « Extrait », sinon il est **complet** ;
- la commande s'exécute par ``mountain_perf.cli.main`` (les mots qui suivent
  ``uv run mperf``, découpés par ``shlex.split``), depuis la racine du dépôt ; code de
  retour 0 ;
- complet : les lignes de la sortie égalent celles du bloc ; extrait : les lignes du
  bloc forment une suite contiguë des lignes de la sortie.

Un exemple retiré ou ajouté au README fait rougir le test du compte, qui sera mis à
jour avec lui. Contre-épreuves dans ce fichier : un ``README.md`` modifié, lu dans un
répertoire temporaire, échoue. Une ligne retirée en tête ou en fin d'extrait laisse
une suite contiguë de la sortie : elle passe, par construction.
"""

import shlex
from dataclasses import dataclass
from pathlib import Path

import pytest

from mountain_perf.cli import main

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
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


EXAMPLES = readme_examples(README)


def test_the_readme_has_four_examples() -> None:
    """``profile``, ``project``, ``match``, puis ``match --curve``, seul extrait."""
    assert [example.arguments[0] for example in EXAMPLES] == [
        "profile",
        "project",
        "match",
        "match",
    ]
    assert [example.excerpt for example in EXAMPLES] == [False, False, False, True]
    assert "--curve" in EXAMPLES[3].arguments


@pytest.mark.parametrize(
    "index", range(len(EXAMPLES)), ids=[e.command[len(PREFIX) :] for e in EXAMPLES]
)
def test_readme_example_is_the_real_output(
    index: int, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    example = EXAMPLES[index]
    assert matches(example, _run(example, monkeypatch, capsys))


def _modified_examples(tmp_path: Path, old: str, new: str) -> list[Example]:
    """Les exemples d'un ``README.md`` modifié, écrit dans ``tmp_path``."""
    text = README.read_text(encoding="utf-8")
    assert text.count(old) == 1
    path = tmp_path / "README.md"
    path.write_bytes(text.replace(old, new).encode("utf-8"))
    return readme_examples(path)


def test_a_changed_character_in_the_profile_block_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Contre-épreuve : un caractère changé dans le bloc de ``profile`` rougit."""
    original = EXAMPLES[0].expected[1]
    changed = original.replace("11 points", "12 points")
    assert changed != original
    example = _modified_examples(tmp_path, original, changed)[0]
    assert not matches(example, _run(example, monkeypatch, capsys))


def test_an_interior_line_removed_from_the_excerpt_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Contre-épreuve : une ligne **intérieure** retirée de l'extrait rougit."""
    excerpt = EXAMPLES[3].expected
    interior = len(excerpt) // 2
    block = "\n".join(excerpt)
    shortened = "\n".join(excerpt[:interior] + excerpt[interior + 1 :])
    example = _modified_examples(tmp_path, block, shortened)[3]
    assert len(example.expected) == len(excerpt) - 1
    assert not matches(example, _run(example, monkeypatch, capsys))
