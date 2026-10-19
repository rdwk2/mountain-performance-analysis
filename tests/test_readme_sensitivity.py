"""L'extrait du README est la synthèse réelle de ``mperf backtest … --sensitivity``
(brief M4d-3 ; précision de D15, M4d-3).

Le bloc ```` ```text ```` qui suit le bloc ```` ```bash ```` ``just backtest courbe.csv
--sensitivity`` est une suite contiguë d'au moins dix lignes de la sortie de la
commande sur le monde synthétique, prise dans la synthèse de la sensibilité (aides
``_blocks`` et ``README`` de ``test_readme_examples.py`` ; la commande est celle de
``test_cli_sensitivity.py``, exécutée une fois par session). Contre-épreuve : un
README dont une ligne intérieure de l'extrait est retirée échoue.
"""

from pathlib import Path

import pytest

from test_cli_backtest import contiguous, lines_of
from test_cli_sensitivity import sensitivity_command
from test_readme_examples import README, _blocks

COMMAND = "just backtest courbe.csv --sensitivity"


def readme_excerpt(path: Path) -> list[str]:
    """Le bloc ``text`` qui suit le bloc ``bash`` de ``just backtest courbe.csv
    --sensitivity``."""
    blocks = _blocks(path.read_text(encoding="utf-8").splitlines())
    (index,) = [
        i
        for i, block in enumerate(blocks)
        if block.info == "bash" and block.body == (COMMAND,)
    ]
    following = blocks[index + 1 : index + 2]
    assert following, "le bloc just backtest --sensitivity n'est suivi d'aucun bloc"
    assert following[0].info == "text"
    return list(following[0].body)


@pytest.fixture(scope="module")
def output(tmp_path_factory: pytest.TempPathFactory) -> list[str]:
    """La sortie de la commande sur le monde, ligne par ligne."""
    outcome = sensitivity_command(tmp_path_factory)
    assert outcome.code == 0, outcome.err
    return lines_of(outcome.out)


def test_readme_excerpt_is_the_real_synthesis(output: list[str]) -> None:
    """Précision de D15 (M4d-3) : l'extrait suit la sortie ligne pour ligne, sur au
    moins dix lignes, une fois, dans la synthèse de la sensibilité (après la ligne de
    sa DÉCLARATION)."""
    excerpt = readme_excerpt(README)
    assert len(excerpt) >= 10
    (start,) = contiguous(excerpt, output)
    declared = [
        i
        for i, line in enumerate(output)
        if line.startswith("sensibilité  déclaration")
    ]
    assert declared
    assert start > declared[0]


def test_an_interior_line_removed_from_the_excerpt_fails(
    output: list[str], tmp_path: Path
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
    assert not contiguous(readme_excerpt(modified), output)
