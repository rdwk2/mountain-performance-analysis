"""La figure commitée du README est celle que produit ``scripts/readme_figure.py``."""

import importlib.util
import re
import tempfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "readme_figure.py"
FIGURE = ROOT / "docs" / "img" / "chaine.svg"

NUMBER = re.compile(r"\d+(?:\.\d+)?")
"""Les nombres du SVG, comparés à une unité de leur dernière décimale affichée : un
écart de libm entre Windows et la CI ne doit pas faire échouer le test ; le texte
autour, lui, est comparé exactement."""


def _unit(number: str) -> float:
    """Une unité de la dernière décimale : ``0.108`` → 0,001, ``123.4`` → 0,1, un
    entier → 1."""
    _, _, decimals = number.partition(".")
    return 10.0 ** -len(decimals)


def _script() -> ModuleType:
    """Le script, chargé depuis son fichier : ``scripts/`` n'est pas un paquet."""
    spec = importlib.util.spec_from_file_location("readme_figure", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def regenerated() -> str:
    module = _script()
    svg: str = module.render_svg(module.run_chain().figure)
    return svg


def test_committed_figure_is_up_to_date(regenerated: str) -> None:
    stale = "docs/img/chaine.svg est périmé : lancer `just figure`."
    # Comparaison insensible à un éventuel CRLF de la copie de travail.
    committed = "\n".join(FIGURE.read_text(encoding="utf-8").splitlines())
    fresh = "\n".join(regenerated.splitlines())
    assert NUMBER.split(committed) == NUMBER.split(fresh), stale
    committed_numbers = NUMBER.findall(committed)
    fresh_numbers = NUMBER.findall(fresh)
    assert len(committed_numbers) == len(fresh_numbers), stale
    # La tolérance se lit sur le nombre commité ; la marge relative absorbe l'arrondi
    # binaire de la soustraction (0.109 − 0.108 n'est pas exactement 0.001).
    drift = [
        (a, b)
        for a, b in zip(committed_numbers, fresh_numbers, strict=True)
        if abs(float(a) - float(b)) > _unit(a) * (1 + 1e-9)
    ]
    assert not drift, f"{stale} Écarts : {drift[:5]}"


def test_render_is_deterministic_and_lf_only(regenerated: str) -> None:
    module = _script()
    data = module.run_chain().figure
    assert module.render_svg(data) == module.render_svg(data)
    assert "\r" not in regenerated


def test_figure_leaks_no_path(regenerated: str) -> None:
    for fragment in (tempfile.gettempdir(), str(ROOT), "Users", "Temp", ":\\"):
        assert fragment not in regenerated, fragment


def test_readme_shows_the_figure() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    image = re.search(r"!\[([^\]]+)\]\(docs/img/chaine\.svg\)", readme)
    assert image is not None, "README.md doit afficher docs/img/chaine.svg."
    assert image.group(1).strip()
    assert image.start() < readme.index("## Pourquoi")
