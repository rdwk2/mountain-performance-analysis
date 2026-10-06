"""L'extrait du README est la synthèse réelle de ``mperf backtest`` (§ 7.5 et § 8.1,
test 10, du brief M4b-5).

Le bloc ```` ```text ```` qui suit le bloc ```` ```bash ```` ``just backtest
courbe.csv`` est une suite contiguë d'au moins dix lignes de la synthèse sur le monde
synthétique du § 7.1 (aides ``_blocks`` et ``README`` de ``test_readme_examples.py``).
Contre-épreuve : un README dont une ligne intérieure de l'extrait est retirée échoue.
"""

from pathlib import Path

import pytest

from fixtures.backtest_world import write_world
from test_cli_backtest import backtest, contiguous, lines_of
from test_readme_examples import README, _blocks

COMMAND = "just backtest courbe.csv"


def readme_excerpt(path: Path) -> list[str]:
    """Le bloc ``text`` qui suit le bloc ``bash`` de ``just backtest courbe.csv``."""
    blocks = _blocks(path.read_text(encoding="utf-8").splitlines())
    (index,) = [
        i
        for i, block in enumerate(blocks)
        if block.info == "bash" and block.body == (COMMAND,)
    ]
    following = blocks[index + 1 : index + 2]
    assert following, "le bloc just backtest n'est suivi d'aucun bloc"
    assert following[0].info == "text"
    return list(following[0].body)


@pytest.fixture(scope="module")
def synthesis(tmp_path_factory: pytest.TempPathFactory) -> list[str]:
    """La synthèse de la commande sur le monde."""
    root = tmp_path_factory.mktemp("readme")
    data = root / "donnees"
    data.mkdir()
    with pytest.MonkeyPatch.context() as monkeypatch:
        outcome = backtest(monkeypatch, data, write_world(root / "monde"))
    assert outcome.code == 0, outcome.err
    return lines_of(outcome.out)


def test_readme_excerpt_is_the_real_synthesis(synthesis: list[str]) -> None:
    """§ 7.5 : l'extrait suit la synthèse ligne pour ligne, sur au moins dix
    lignes."""
    excerpt = readme_excerpt(README)
    assert len(excerpt) >= 10
    assert contiguous(excerpt, synthesis)


def test_an_interior_line_removed_from_the_excerpt_fails(
    synthesis: list[str], tmp_path: Path
) -> None:
    """Contre-épreuve : une ligne intérieure retirée de l'extrait le rend non
    contigu."""
    lines = README.read_text(encoding="utf-8").splitlines()
    excerpt = readme_excerpt(README)
    target = excerpt[len(excerpt) // 2]
    assert lines.count(target) == 1
    lines.remove(target)
    modified = tmp_path / "README.md"
    modified.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    assert not contiguous(readme_excerpt(modified), synthesis)
