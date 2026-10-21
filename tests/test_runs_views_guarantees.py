"""Garanties de M5-1 sans test à la tête de la PR #33 (relecture de la PR : la C et
la conception) : ce que ``project_route`` publie du GPX lu ; le D+ total de la synthèse
de ``mperf project`` ; le singulier « 1 lieu résolu » ; les moyennes d'un tronçon de
moins d'une seconde ; une heure de départ qui n'existe pas ; les objets gelés ; l'export
de l'interface, qui a le texte de ``mperf project --csv`` aux fins de ligne près.

La synthèse est l'oracle de la commande comme de la page (§ 6.6 du brief) : ces tests
écrivent les attendus en dur, ou les lisent sur le profil construit à part, jamais sur
le texte qu'ils vérifient.
"""

import io
import subprocess
import sys
from dataclasses import replace
from datetime import date, datetime, time
from pathlib import Path

import pytest

from fixtures.curves import SUPPORT_CURVE
from fixtures.projection import CURVE_REF, ENDPOINTS, REFUGE, SIX_INTERVAL_PROFILE
from mountain_perf.controls import ParameterControl, changed_values, parameter_controls
from mountain_perf.gpx import (
    PROFILE_PARAMETER_DISPLAYS,
    PROFILE_PARAMETER_SPECS,
    build_profile_with_diagnostics,
    read_gpx,
)
from mountain_perf.model import (
    PROJECTION_PARAMETER_DISPLAYS,
    PROJECTION_PARAMETER_SPECS,
    project,
)
from mountain_perf.model.export import write_passages_csv
from mountain_perf.model.views import CIVIL_ZONE, PassageRow, civil_start, passage_rows
from mountain_perf.reports import projection_summary_lines
from mountain_perf.runs import RouteProjection, project_route
from mountain_perf.schemas import NamedPoint, ParameterSet, ResolvedPoint
from mountain_perf.units import format_count

FIXTURES = Path(__file__).parent / "fixtures"
GPX = FIXTURES / "mini_11.gpx"
CURVE = FIXTURES / "courbe_synthetique.csv"
MPERF = "import sys; from mountain_perf.cli import main; sys.exit(main(sys.argv[1:]))"

LATITUDE_STEP = 0.00089932036372
"""Environ 100 m le long du méridien 6° E, comme ``mini_11.gpx``."""


def _meridian_gpx(path: Path, elevations: list[float], waypoint_index: int) -> Path:
    """Un GPX synthétique le long du méridien 6° E, un point tous les 100 m environ, et
    un seul lieu nommé, posé sur le point ``waypoint_index``."""
    points = "\n".join(
        f'    <trkpt lat="{45 + i * LATITUDE_STEP:.14f}" lon="6"><ele>{z}</ele></trkpt>'
        for i, z in enumerate(elevations)
    )
    waypoint = (
        f'  <wpt lat="{45 + waypoint_index * LATITUDE_STEP:.14f}" lon="6">'
        f"<ele>{elevations[waypoint_index]}</ele><name>Col</name></wpt>"
    )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="synthetic-tests" '
        'xmlns="http://www.topografix.com/GPX/1/1">\n'
        f"{waypoint}\n"
        "  <trk><name>Montée régulière</name><trkseg>\n"
        f"{points}\n"
        "  </trkseg></trk>\n</gpx>\n",
        encoding="utf-8",
    )
    return path


def _climbing_route(tmp_path: Path) -> Path:
    """Onze points qui montent de 10 m chaque fois : le dernier intervalle de la grille
    monte encore, et un seul lieu est résolu, au milieu."""
    return _meridian_gpx(
        tmp_path / "montee.gpx", [1500.0 + 10.0 * i for i in range(11)], 5
    )


def test_the_route_projection_carries_the_gpx_it_read() -> None:
    run = project_route(GPX, CURVE, {}, {})
    read = read_gpx(GPX)
    assert run.read.point_count_read == read.point_count_read
    assert run.read.segment_count == read.segment_count
    assert run.read.route.name == read.route.name
    assert run.read.route.named_points == read.route.named_points
    assert tuple(run.read.route.elevation_m) == tuple(read.route.elevation_m)
    assert run.read.route.source.content_hash == read.route.source.content_hash


def test_the_summary_gives_the_total_ascent_of_the_profile(tmp_path: Path) -> None:
    route = _climbing_route(tmp_path)
    profile = build_profile_with_diagnostics(
        read_gpx(route).route, ParameterSet(PROFILE_PARAMETER_SPECS, {})
    ).profile
    total = format_count(profile.cumulative_ascent_m[-1])
    # Le cas distingue le total de l'avant-dernier cumul : la route monte jusqu'au bout.
    assert total != format_count(profile.cumulative_ascent_m[-2])
    (duration_line,) = (
        line
        for line in projection_summary_lines(project_route(route, CURVE, {}, {}))
        if line.startswith("durée")
    )
    assert f"(D+ {total} m / " in duration_line


def test_one_resolved_place_is_written_in_the_singular(tmp_path: Path) -> None:
    lines = projection_summary_lines(
        project_route(_climbing_route(tmp_path), CURVE, {}, {})
    )
    assert lines[-1] == (
        "passages     3   (1 lieu résolu, départ et arrivée synthétisés)"
    )


def test_a_leg_shorter_than_a_second_still_has_its_means() -> None:
    source = NamedPoint(
        name="Source", latitude_deg=45.0, longitude_deg=6.0, elevation_m=1000.0
    )
    profile = replace(
        SIX_INTERVAL_PROFILE,
        resolved_points=(
            ResolvedPoint(
                point=REFUGE, distance_m=250.0, elevation_m=1000.0, offset_m=0.0
            ),
            ResolvedPoint(
                point=source, distance_m=250.5, elevation_m=1000.0, offset_m=0.0
            ),
        ),
    )
    projection = project(
        profile,
        SUPPORT_CURVE,
        ParameterSet(PROJECTION_PARAMETER_SPECS, {}),
        curve_ref=CURVE_REF,
        endpoints=ENDPOINTS,
    )
    (row,) = (row for row in passage_rows(projection) if row.name == "Source")
    assert row.segment is not None
    assert 0 < row.segment.duration_s <= 1
    assert row.speed_ms == row.segment.distance_m / row.segment.duration_s
    assert row.ascent_rate_ms == row.segment.ascent_m / row.segment.duration_s


def test_a_start_hour_that_does_not_exist_raises_nothing() -> None:
    """2 h 30 le jour du passage à l'heure d'été n'existe pas à Paris : l'heure est
    celle que ``zoneinfo`` lui donne, sans erreur (§ 6.8 du brief)."""
    start = civil_start(date(2026, 3, 29), time(2, 30))
    assert start == datetime(2026, 3, 29, 2, 30, tzinfo=CIVIL_ZONE)


@pytest.mark.parametrize("cls", [ParameterControl, RouteProjection, PassageRow])
def test_new_objects_are_frozen(cls: type) -> None:
    assert vars(cls)["__dataclass_params__"].frozen


def _interface_bytes() -> bytes:
    """Ce que la page met dans son bouton : le texte de ``write_passages_csv`` sur un
    ``io.StringIO``, encodé en UTF-8, les contrôles à leur défaut."""
    profile = parameter_controls(PROFILE_PARAMETER_SPECS, PROFILE_PARAMETER_DISPLAYS)
    projection = parameter_controls(
        PROJECTION_PARAMETER_SPECS, PROJECTION_PARAMETER_DISPLAYS
    )
    run = project_route(
        GPX,
        CURVE,
        changed_values(profile, {c.spec.name: c.default for c in profile}),
        changed_values(projection, {c.spec.name: c.default for c in projection}),
    )
    stream = io.StringIO()
    write_passages_csv(run.projection, stream)
    return stream.getvalue().encode("utf-8")


def test_the_interface_export_has_the_command_text_up_to_line_endings() -> None:
    """Les octets de ``mperf project --csv`` lus tels quels, sans décodage : le même
    texte que l'export de la page, en UTF-8, aux fins de ligne près (sous Windows, la
    commande écrit des CRLF, comme toute sortie texte de Python ; la page, des LF)."""
    command = subprocess.run(
        [
            sys.executable,
            "-c",
            MPERF,
            "project",
            str(GPX),
            "--curve",
            str(CURVE),
            "--csv",
        ],
        capture_output=True,
        check=True,
    ).stdout
    interface = _interface_bytes()
    assert b"\r" not in interface
    assert command.replace(b"\r\n", b"\n") == interface
