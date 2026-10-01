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
"""Les nombres du SVG, comparés à 0,1 près : un écart de libm entre Windows et la CI
ne doit pas faire échouer le test ; le texte autour, lui, est comparé exactement."""

TOLERANCE = 0.1


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
    committed_numbers = [float(n) for n in NUMBER.findall(committed)]
    fresh_numbers = [float(n) for n in NUMBER.findall(fresh)]
    assert len(committed_numbers) == len(fresh_numbers), stale
    drift = [
        (a, b)
        for a, b in zip(committed_numbers, fresh_numbers, strict=True)
        if abs(a - b) > TOLERANCE
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
