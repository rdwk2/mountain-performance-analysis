"""L'enchaînement et les textes de ``mperf project`` en bibliothèque (§ 6.5 à 6.7 du
brief M5-1) : ``project_route``, ``grid_lines``, ``projection_summary_lines``,
``passage_lines`` et les trois formats déplacés de ``cli.py``.

Le test du câblage dit que la commande et la page montrent le même texte, pas que ce
texte est juste : depuis M5-1 la commande imprime ces fonctions. L'oracle du texte reste
ce qui l'écrit en dur et ne change pas : les blocs du README
(``test_readme_examples.py``), ``test_cli_project.py`` et ``test_cli_profile.py``.
"""

import math
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from mountain_perf.gpx import (
    PROFILE_PARAMETER_SPECS,
    GpxError,
    build_profile_with_diagnostics,
    read_gpx,
)
from mountain_perf.model import (
    PROJECTION_PARAMETER_SPECS,
    project_with_diagnostics,
    read_curve,
    route_endpoints,
)
from mountain_perf.reports import grid_lines, passage_lines, projection_summary_lines
from mountain_perf.runs import project_route
from mountain_perf.schemas import ParameterSet
from mountain_perf.units import format_count, format_grade, format_share
from mountain_perf.validation import ContractError

FIXTURES = Path(__file__).parent / "fixtures"
GPX = FIXTURES / "mini_11.gpx"
CURVE = FIXTURES / "courbe_synthetique.csv"

MPERF = "import sys; from mountain_perf.cli import main; sys.exit(main(sys.argv[1:]))"
"""La commande ``mperf``, lancée dans un processus neuf (``cli.py`` n'a pas de garde
``__main__``)."""


def _mperf(*args: str) -> list[str]:
    """Les lignes de la sortie standard de ``mperf args``, dans un processus neuf."""
    out = subprocess.run(
        [sys.executable, "-c", MPERF, *args],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    return out.stdout.splitlines()


# ---------------------------------------------------------------------------
# project_route : l'enchaînement de mperf project
# ---------------------------------------------------------------------------


def test_project_route_equals_the_previous_chain() -> None:
    """L'enchaînement d'avant M5-1, écrit ici avec les fonctions du moteur."""
    profile_values = {"grid_step_m": 25}
    projection_values = {"effort": 0.9}
    grid = ParameterSet(PROFILE_PARAMETER_SPECS, profile_values)
    model = ParameterSet(PROJECTION_PARAMETER_SPECS, projection_values)
    read = read_gpx(GPX)
    built = build_profile_with_diagnostics(read.route, grid)
    curve = read_curve(CURVE, model)
    projection, diagnostics = project_with_diagnostics(
        built.profile,
        curve.curve,
        model,
        curve_ref=curve.curve_ref,
        endpoints=route_endpoints(read.route),
    )

    run = project_route(GPX, CURVE, profile_values, projection_values)

    # Hors generated_at, et hors l'instant de lecture des fichiers (retrieved_at de
    # leur SourceRef), propre à chaque lecture.
    assert run.projection.passages == projection.passages
    assert run.projection.segments == projection.segments
    assert dict(run.projection.parameters.values) == dict(model.values)
    assert run.projection.curve_ref == projection.curve_ref
    assert run.diagnostics == diagnostics


def _unreadable_gpx(tmp_path: Path) -> Path:
    path = tmp_path / "illisible.gpx"
    path.write_bytes(b"pas du XML")
    return path


def _unreadable_curve(tmp_path: Path) -> Path:
    path = tmp_path / "courbe_fausse.csv"
    path.write_bytes(b"pas,une,courbe\n")
    shutil.copy(CURVE.with_suffix(".meta.json"), tmp_path / "courbe_fausse.meta.json")
    return path


def test_the_gpx_is_read_before_the_curve(tmp_path: Path) -> None:
    with pytest.raises(GpxError):
        project_route(_unreadable_gpx(tmp_path), _unreadable_curve(tmp_path), {}, {})


def test_the_parameters_are_checked_before_the_gpx(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="grid_step_m"):
        project_route(_unreadable_gpx(tmp_path), CURVE, {"grid_step_m": 0}, {})


# ---------------------------------------------------------------------------
# Le câblage : la commande imprime ces fonctions
# ---------------------------------------------------------------------------


def test_projection_lines_are_the_command_output() -> None:
    run = project_route(GPX, CURVE, {}, {})
    expected = [*projection_summary_lines(run), *passage_lines(run.projection)]
    assert _mperf("project", str(GPX), "--curve", str(CURVE)) == expected


def test_grid_lines_are_those_of_mperf_profile() -> None:
    run = project_route(GPX, CURVE, {}, {})
    output = _mperf("profile", str(GPX))
    shown = [line for line in output if line.startswith(("grille ", "lissage "))]
    assert shown == list(grid_lines(run.built))


# ---------------------------------------------------------------------------
# Les trois formats déplacés de cli.py
# ---------------------------------------------------------------------------


def test_format_count() -> None:
    assert format_count(12345.6) == "12 346"


@pytest.mark.parametrize(("grade", "text"), [(0.4549, "+45 %"), (-0.4, "−40 %")])
def test_format_grade(grade: float, text: str) -> None:
    assert format_grade(grade) == text


def test_format_share_rounds_half_to_even() -> None:
    assert format_share(0.125) == "12 %"


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("formatted", [format_count, format_grade, format_share])
def test_formats_show_a_dash_on_a_non_finite_input(
    formatted: Callable[[float], str], value: float
) -> None:
    assert formatted(value) == "—"
