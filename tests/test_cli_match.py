"""``mperf match`` (§ 5a.9 du brief M4a-2a) sur GPX synthétiques uniquement.

La paire commitée (§ 8, test 6) : référence ``(0,0)→(530,0)`` sans lieu nommé, et
X01 échantillonnée toutes les 10 s. Attendu calculé en conception : départ ancré en
``b_0 = 25,00`` m, durée avant départ ``0:00:00`` ; points 1 et 2 trouvés à 150 et
316,666667 s ; arrivée ancrée à ``0:05:20``, ``b_K = 505,00``, ``L − b_K = 25,00``.
"""

from pathlib import Path

import pytest

from fixtures.matching import (
    MATCH_REFERENCE_GPX,
    MATCH_TRACE_GPX,
    gpx_texts,
    t01_bis,
    x01_gpx_pair,
    x04,
)
from fixtures.traces import local_deg
from mountain_perf.backtest import (
    MATCHING_PARAMETER_SPECS,
    build_series,
    match_points,
    reference_geometry,
)
from mountain_perf.cli import main
from mountain_perf.gpx import read_gpx
from mountain_perf.gpx.trace_reader import read_trace
from mountain_perf.schemas import ParameterSet, PointStatus

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = FIXTURES / MATCH_REFERENCE_GPX
TRACE = FIXTURES / MATCH_TRACE_GPX


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    code = main(["match", *args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_committed_pair_is_written_by_the_convention() -> None:
    """Les deux fichiers sont exactement ceux que produit la convention du § 7.0
    (``local_deg``, coordonnées en ``repr``) : 33 enregistrements, UTC."""
    reference, trace = x01_gpx_pair()
    assert REFERENCE.read_text(encoding="utf-8").splitlines() == reference.splitlines()
    assert TRACE.read_text(encoding="utf-8").splitlines() == trace.splitlines()
    route = read_gpx(REFERENCE).route
    assert route.named_points == ()
    assert list(zip(route.latitude_deg, route.longitude_deg, strict=True)) == [
        local_deg(0.0, 0.0),
        local_deg(530.0, 0.0),
    ]
    records = read_trace([TRACE])
    assert records.time_s == tuple(10.0 * i for i in range(33))
    offset = records.start_time.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 0


def test_committed_pair_values_of_the_design() -> None:
    """Points 1 et 2 trouvés à 150 et 316,666667 s ; extrémités ancrées."""
    route = read_gpx(REFERENCE).route
    trace = read_trace([TRACE])
    points = match_points(
        reference_geometry(route),
        trace,
        build_series(trace),
        ParameterSet(MATCHING_PARAMETER_SPECS),
    )
    assert [p.status for p in points] == [
        PointStatus.ANCHORED,
        PointStatus.FOUND,
        PointStatus.FOUND,
        PointStatus.ANCHORED,
    ]
    assert points[0].effective_m == pytest.approx(25.0, abs=1e-6)
    assert points[1].time_s == pytest.approx(150.0, abs=1e-6)
    assert points[2].time_s == pytest.approx(316.666667, abs=1e-6)
    assert points[3].time_s == pytest.approx(320.0, abs=1e-6)
    assert points[3].effective_m == pytest.approx(505.0, abs=1e-6)


def test_report_on_the_committed_pair(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(capsys, str(REFERENCE), str(TRACE))
    assert code == 0
    assert err == ""
    assert "référence    appariement_reference.gpx   sha256 " in out
    assert "             L 530 m, D+/km 0 m/km" in out
    assert "trace        appariement_trace_x01.gpx" in out
    assert (
        "             33 enregistrements, 0 instant dupliqué écarté, "
        "écoulé 0:05:20, 1 bloc, 0 trou"
    ) in out
    assert "départ       ancré — b_0 25.00 m, durée avant départ 0:00:00" in out
    assert "arrivée      ancré — instant 0:05:20, b_K 505.00 m, L − b_K 25.00 m" in out
    assert "points       Δ 250 m, ε 30 m, r_c 15 m — 4 points" in out
    assert (
        "             trouvé 2, ancré 2, ambigu 0, absent 0, hors ε 0, "
        "tangente indéfinie 0"
    ) in out
    assert "             ambigus : aucun" in out


def test_options_change_the_grid_and_tolerance(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _ = _run(
        capsys, str(REFERENCE), str(TRACE), "--delta-m", "100", "--eps-m", "45"
    )
    assert code == 0
    assert "points       Δ 100 m, ε 45 m, r_c 15 m — 7 points" in out


def _write_pair(tmp_path: Path, texts: tuple[str, str]) -> tuple[str, str]:
    reference, trace = tmp_path / "reference.gpx", tmp_path / "trace.gpx"
    reference.write_text(texts[0], encoding="utf-8")
    trace.write_text(texts[1], encoding="utf-8")
    return str(reference), str(trace)


def test_ambiguous_points_are_listed(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """X04 : deux candidats séparés par un trou au point 1."""
    code, out, err = _run(capsys, *_write_pair(tmp_path, gpx_texts(x04())))
    assert code == 0
    assert err == ""
    assert "             ambigus : k = 1 (s_k = 250 m)" in out
    assert "trouvé 0, ancré 0, ambigu 1, absent 3" in out
    assert "départ       absent\n" in out
    assert "arrivée      absent\n" in out
    assert "2 blocs, 1 trou" in out


def test_found_ends_show_their_instants_without_anchoring_offset(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """T01-bis : départ trouvé après 10 s d'arrêt sur la ligne, arrivée trouvée à
    270 s ; ni l'un ni l'autre n'est ancré, donc pas de ``L − b_K``."""
    code, out, _ = _run(capsys, *_write_pair(tmp_path, gpx_texts(t01_bis())))
    assert code == 0
    assert "136 enregistrements" in out
    assert "départ       trouvé — b_0 0.00 m, durée avant départ 0:00:10\n" in out
    assert "arrivée      trouvé — instant 0:04:30, b_K 520.00 m\n" in out
    assert "trouvé 4, ancré 0" in out


def test_unreadable_trace_fails_without_traceback(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    broken = tmp_path / "cassee.gpx"
    broken.write_text("<gpx><trk><trkseg><trkpt lat=", encoding="utf-8")
    code, out, err = _run(capsys, str(REFERENCE), str(broken))
    assert code == 1
    assert out == ""
    assert err.startswith("Erreur : cassee.gpx : XML mal formé")
    assert "Traceback" not in err


def test_trace_without_time_fails_without_traceback(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Une trace sans ``<time>`` : ``GpxError``, code 1."""
    code, _, err = _run(
        capsys, *_write_pair(tmp_path, gpx_texts(x04(), trace_times=False))
    )
    assert code == 1
    assert "instant manquant" in err


def test_single_record_trace_is_a_trace_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    reference, trace = gpx_texts(x04())
    lines = trace.splitlines()
    single = "\n".join(
        line for line in lines if "<trkpt" not in line or "08:00:00Z" in line
    )
    code, _, err = _run(capsys, *_write_pair(tmp_path, (reference, single)))
    assert code == 1
    assert "au moins 2 enregistrements" in err


def test_out_of_range_option_is_a_contract_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, _, err = _run(capsys, str(REFERENCE), str(TRACE), "--eps-m", "0.5")
    assert code == 1
    assert "lateral_tolerance_m" in err


def test_missing_file_fails_without_traceback(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, _, err = _run(capsys, str(REFERENCE), str(tmp_path / "absente.gpx"))
    assert code == 1
    assert err.startswith("Erreur : ")


def test_missing_argument_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["match", str(REFERENCE)])
    assert exit_info.value.code == 2
    assert "usage" in capsys.readouterr().err
