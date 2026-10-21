"""Les résultats de Q1 (``mountain_perf.analyse.results``, AN1-2c, charte § 10,
``docs/decisions/0015``) : le dossier ``<date>_<empreinte>/``, jamais réécrit, ses
quatre fichiers et leur contenu, sur une figure de lignes écrites à la main."""

from __future__ import annotations

import codecs
import csv
import dataclasses
import hashlib
import io
import json
import re
from datetime import date
from pathlib import Path, PureWindowsPath
from typing import Any

import pytest

from fixtures.figure import (
    activity,
    climb,
    same_in_every_variant,
    start,
    tables_of,
    variant,
    without_track,
)
from fixtures.processed import COMMIT
from mountain_perf.analyse import results as results_module
from mountain_perf.analyse.q1 import Q1_PARAMETER_SPECS, Q1Figure, View, q1_figure
from mountain_perf.analyse.results import (
    COMMAND,
    FIGURE_FILE,
    FLUX_COLUMNS,
    FLUX_FILE,
    POINT_COLUMNS,
    POINTS_FILE,
    PROVENANCE_FILE,
    RESULTS_DIR,
    ResultsError,
    flux_csv,
    points_csv,
    provenance,
    write_results,
)
from mountain_perf.analyse.stability import VARIANTS
from mountain_perf.schemas import ParameterSet
from mountain_perf.schemas.processed import (
    AltitudeStratum,
    ClimbFlag,
    ClimbRegime,
    GradeStratum,
)

HTML = "<!DOCTYPE html>\n<p>figure synthétique — é</p>\n"
DAY = date(2026, 10, 19)
CODE_COMMIT = "f" * 40


@pytest.fixture
def figure() -> Q1Figure:
    """Cinq activités, une montée chacune, plus une montée marquée et une montée
    raide d'une sixième activité : des points des deux vues, une facette cachée, un
    drapeau au flux."""
    activities = [activity(f"w{i}", start(i)) for i in range(6)]
    climbs = [climb(f"w{i}", start(i), 600, 2400, 300, 1800) for i in range(5)]
    climbs += [
        climb("w5", start(5), 600, 1200, 100, 400, flags=(ClimbFlag.SPIKE,)),
        climb("w5", start(5), 1300, 1900, 150, 600, grade=GradeStratum.STEEP),
    ]
    variants = same_in_every_variant(climbs)
    return q1_figure(tables_of(activities, climbs, variants))


def _write(data_dir: Path, figure: Q1Figure, day: date = DAY) -> Path:
    return write_results(
        data_dir,
        figure,
        HTML,
        commit=CODE_COMMIT,
        package_version="0.0.1",
        generated_on=day,
    )


def _rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


# --- le dossier -----------------------------------------------------------------


def test_the_folder_name_is_the_date_and_the_digest(
    tmp_path: Path, figure: Q1Figure
) -> None:
    written = _write(tmp_path, figure)
    assert written.parent == tmp_path / RESULTS_DIR
    assert Path("resultats") / "Q1" == RESULTS_DIR
    day, digest = written.name.split("_")
    assert day == "2026-10-19"
    assert re.fullmatch(r"[0-9a-f]{12}", digest)
    document = json.loads((written / PROVENANCE_FILE).read_text(encoding="utf-8"))
    del document["genere_le"]
    undated = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert hashlib.sha256(undated.encode("utf-8")).hexdigest()[:12] == digest


def test_the_four_files_and_nothing_else(tmp_path: Path, figure: Q1Figure) -> None:
    written = _write(tmp_path, figure)
    assert sorted(p.name for p in written.iterdir()) == sorted(
        [FIGURE_FILE, POINTS_FILE, FLUX_FILE, PROVENANCE_FILE]
    )
    assert sorted(p.name for p in written.parent.iterdir()) == [written.name]
    assert (written / FIGURE_FILE).read_text(encoding="utf-8") == HTML


def test_the_same_inputs_give_the_same_digest(tmp_path: Path, figure: Q1Figure) -> None:
    """Un autre jour, mêmes tables, même code, mêmes paramètres : la même empreinte,
    une autre date, un autre dossier."""
    first = _write(tmp_path, figure)
    second = _write(tmp_path, figure, date(2026, 10, 20))
    assert first.name.split("_")[1] == second.name.split("_")[1]
    assert second.name.startswith("2026-10-20_")


@pytest.mark.parametrize(
    "change",
    [
        {"commit": "e" * 40},
        {"package_version": "0.0.2"},
        {"html": HTML + "<p>autre</p>\n"},
    ],
    ids=["commit", "version", "figure"],
)
def test_another_input_gives_another_digest(
    tmp_path: Path, figure: Q1Figure, change: dict[str, str]
) -> None:
    arguments = {"commit": CODE_COMMIT, "package_version": "0.0.1", "html": HTML}
    first = _write(tmp_path, figure)
    arguments.update(change)
    second = write_results(
        tmp_path,
        figure,
        arguments["html"],
        commit=arguments["commit"],
        package_version=arguments["package_version"],
        generated_on=DAY,
    )
    assert first.name != second.name


def test_other_parameters_give_another_digest(tmp_path: Path, figure: Q1Figure) -> None:
    changed = dataclasses.replace(
        figure,
        parameters=ParameterSet(Q1_PARAMETER_SPECS, {"min_facet_activities": 4}),
    )
    assert _write(tmp_path, figure).name != _write(tmp_path, changed).name


def test_an_existing_folder_is_never_rewritten(
    tmp_path: Path, figure: Q1Figure
) -> None:
    written = _write(tmp_path, figure)
    (written / FIGURE_FILE).write_text("modifiée à la main\n", encoding="utf-8")
    with pytest.raises(ResultsError) as raised:
        _write(tmp_path, figure)
    assert str(raised.value) == (
        f"resultats/Q1/{written.name}/ existe déjà : rien n'est réécrit"
    )
    assert (written / FIGURE_FILE).read_text(encoding="utf-8") == (
        "modifiée à la main\n"
    )
    assert sorted(p.name for p in written.parent.iterdir()) == [written.name]


def test_a_leftover_temporary_folder_is_replaced(
    tmp_path: Path, figure: Q1Figure
) -> None:
    """Les restes d'une écriture interrompue, sous le nom temporaire, sont
    supprimés avant l'écriture."""
    name = _write(tmp_path / "essai", figure).name
    leftover = tmp_path / RESULTS_DIR / f".{name}.nouveau"
    leftover.mkdir(parents=True)
    (leftover / "reste.txt").write_text("reste\n", encoding="utf-8")
    written = _write(tmp_path, figure)
    assert written.name == name
    assert not leftover.exists()
    assert not (written / "reste.txt").exists()


def test_the_files_are_written_under_the_temporary_name(
    tmp_path: Path, figure: Q1Figure, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Les quatre fichiers s'écrivent sous ``.<nom>.nouveau/``, et le dossier n'existe
    pas encore sous son nom : un arrêt au milieu de l'écriture ne laisse jamais un
    dossier incomplet sous son nom final."""
    name = _write(tmp_path / "essai", figure).name
    target = tmp_path / RESULTS_DIR / name
    real = Path.write_text
    seen: list[tuple[str, bool]] = []

    def spy(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        seen.append((self.parent.name, target.exists()))
        return real(self, data, encoding, errors, newline)

    monkeypatch.setattr(Path, "write_text", spy)
    assert _write(tmp_path, figure) == target
    assert seen == [(f".{name}.nouveau", False)] * 4


@pytest.mark.parametrize("failing_call", [1, 2, 3, 4])
def test_a_failed_write_leaves_nothing(
    tmp_path: Path,
    figure: Q1Figure,
    monkeypatch: pytest.MonkeyPatch,
    failing_call: int,
) -> None:
    """L'écriture d'un des quatre fichiers échoue : ni le dossier, ni le dossier
    temporaire ne restent, et l'erreur se propage."""
    real = Path.write_text
    calls: list[str] = []

    def failing(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        calls.append(self.name)
        if len(calls) == failing_call:
            raise OSError("disque plein")
        return real(self, data, encoding, errors, newline)

    monkeypatch.setattr(Path, "write_text", failing)
    with pytest.raises(OSError, match="disque plein"):
        _write(tmp_path, figure)
    assert list((tmp_path / RESULTS_DIR).iterdir()) == []


def test_utf8_and_lf_are_asked_for_on_every_system(
    tmp_path: Path, figure: Q1Figure, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sous Windows, l'encodage par défaut n'est pas UTF-8 et ``\\n`` s'écrit
    ``\\r\\n`` : chacun des quatre fichiers demande UTF-8 et ``newline=""``, ce que
    les octets relus sous Linux (le test suivant) ne montrent pas."""
    real = Path.write_text
    asked: dict[str, tuple[str | None, str | None]] = {}

    def spy(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        asked[self.name] = (encoding, newline)
        return real(self, data, encoding, errors, newline)

    monkeypatch.setattr(Path, "write_text", spy)
    _write(tmp_path, figure)
    assert sorted(asked) == sorted(
        [FIGURE_FILE, POINTS_FILE, FLUX_FILE, PROVENANCE_FILE]
    )
    for name, (encoding, newline) in asked.items():
        assert encoding is not None, name
        assert codecs.lookup(encoding).name == "utf-8", name
        assert newline == "", name


def test_a_folder_that_cannot_be_created_raises_its_own_error(
    tmp_path: Path, figure: Q1Figure, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La création du dossier temporaire échoue : son erreur se propage telle quelle ;
    le nettoyage d'un dossier qui n'existe pas ne la remplace pas."""

    def refused(
        self: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        raise PermissionError("accès refusé")

    monkeypatch.setattr(Path, "mkdir", refused)
    with pytest.raises(PermissionError, match=r"^accès refusé$"):
        _write(tmp_path, figure)


def test_lf_and_utf8_everywhere(tmp_path: Path, figure: Q1Figure) -> None:
    written = _write(tmp_path, figure)
    for name in (FIGURE_FILE, POINTS_FILE, FLUX_FILE, PROVENANCE_FILE):
        raw = (written / name).read_bytes()
        assert b"\r" not in raw, name
        assert raw.endswith(b"\n"), name
        raw.decode("utf-8")


# --- provenance.json ------------------------------------------------------------


def test_the_provenance(tmp_path: Path, figure: Q1Figure) -> None:
    written = _write(tmp_path, figure)
    document = json.loads((written / PROVENANCE_FILE).read_text(encoding="utf-8"))
    assert sorted(document) == [
        "commande",
        "commit",
        "fichiers",
        "genere_le",
        "parametres_de_la_figure",
        "periode",
        "question",
        "tables",
        "version_du_paquet",
    ]
    assert document["question"] == "Q1"
    assert document["commande"] == COMMAND == "mperf q1"
    assert document["commit"] == CODE_COMMIT
    assert document["version_du_paquet"] == "0.0.1"
    assert document["genere_le"] == "2026-10-19"
    assert figure.period is not None
    assert document["periode"] == {
        "debut": figure.period[0].isoformat(),
        "fin": figure.period[1].isoformat(),
    }
    assert document["periode"]["debut"].endswith("+01:00")
    tables = document["tables"]
    assert tables["commit"] == COMMIT
    assert tables["interim_sha256"] == figure.provenance.interim_sha256
    assert tables["variant_climb_count"] == figure.provenance.variant_climb_count
    assert tables["parameters"] == [
        [name, value] for name, value in figure.provenance.parameters
    ]
    assert document["parametres_de_la_figure"] == dict(figure.parameters.values)
    for name in (FIGURE_FILE, POINTS_FILE, FLUX_FILE):
        digest = hashlib.sha256((written / name).read_bytes()).hexdigest()
        assert document["fichiers"][name] == digest
    assert sorted(document["fichiers"]) == sorted([FIGURE_FILE, POINTS_FILE, FLUX_FILE])


def test_the_provenance_of_a_figure_without_activity() -> None:
    empty = q1_figure(tables_of([], []))
    document = provenance(empty, {}, commit=CODE_COMMIT, package_version="0.0.1")
    assert document["periode"] is None
    assert document["fichiers"] == {}


def test_the_provenance_json_is_sorted_and_indented(
    tmp_path: Path, figure: Q1Figure
) -> None:
    text = (_write(tmp_path, figure) / PROVENANCE_FILE).read_text(encoding="utf-8")
    document = json.loads(text)
    assert text == (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )


def test_an_accent_in_the_provenance_is_written_as_is(
    tmp_path: Path, figure: Q1Figure
) -> None:
    """Un produit barométrique déclaré avec un accent (``athlete.toml``) : la
    provenance l'écrit tel quel, sans échappement, et l'empreinte du dossier est celle
    de ce texte."""
    tables = dataclasses.replace(
        figure.provenance, barometer_products=("fabricant:montre été",)
    )
    written = _write(tmp_path, dataclasses.replace(figure, provenance=tables))
    text = (written / PROVENANCE_FILE).read_text(encoding="utf-8")
    assert '"fabricant:montre été"' in text
    document = json.loads(text)
    del document["genere_le"]
    undated = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    digest = hashlib.sha256(undated.encode("utf-8")).hexdigest()[:12]
    assert written.name == f"{DAY.isoformat()}_{digest}"


# --- points.csv -----------------------------------------------------------------


def test_points_csv(figure: Q1Figure) -> None:
    rows = _rows(points_csv(figure))
    assert tuple(rows[0]) == POINT_COLUMNS
    assert len(rows) == 1 + len(figure.points)
    by_column = [dict(zip(POINT_COLUMNS, row, strict=True)) for row in rows[1:]]
    for point, row in zip(figure.points, by_column, strict=True):
        assert row["view"] == point.view.value
        assert row["panel"] == point.panel.value
        assert row["grade_stratum"] == point.grade_stratum.value
        assert row["altitude_stratum"] == point.altitude_stratum.value
        assert row["activity_ref"] == point.activity_ref
        assert row["start_time"] == point.start_time.isoformat()
        assert row["status"] == point.status.value
        assert row["climb_count"] == str(point.climb_count)
        assert float(row["moving_gain_m"]) == point.moving_gain_m
        assert float(row["moving_s"]) == point.moving_s
        assert point.vertical_speed_ms is not None
        assert float(row["vertical_speed_ms"]) == point.vertical_speed_ms
        assert float(row["vertical_speed_low_ms"]) == point.vertical_speed_low_ms
        assert float(row["vertical_speed_high_ms"]) == point.vertical_speed_high_ms
        s = point.stability
        if s is None:
            assert [row[c] for c in POINT_COLUMNS[-4:]] == ["", "", "", ""]
        else:
            assert float(row["found_fraction"]) == s.found_fraction
            assert float(row["min_kept_fraction"]) == s.min_kept_fraction
            assert row["max_relative_deviation"] == repr(s.max_relative_deviation)
            assert row["stable"] == ("true" if s.stable else "false")
    assert {row["view"] for row in by_column} == {v.value for v in View}
    assert {row["stable"] for row in by_column} == {"true", ""}


def test_points_csv_keeps_full_precision(figure: Q1Figure) -> None:
    """Les nombres s'écrivent par ``repr`` : ils se relisent à l'identique."""
    point = figure.points[0]
    assert point.vertical_speed_ms is not None
    row = _rows(points_csv(figure))[1]
    assert row[POINT_COLUMNS.index("vertical_speed_ms")] == repr(
        point.vertical_speed_ms
    )


def test_an_unstable_point_and_a_missing_deviation() -> None:
    """Un point jamais retrouvé : ``stable`` vaut ``false``, l'écart est vide."""
    activities = [activity("a", start(0))]
    climbs = [climb("a", start(0), 600, 2400, 300, 1800)]
    figure = q1_figure(tables_of(activities, climbs, []))
    (row,) = [
        dict(zip(POINT_COLUMNS, r, strict=True))
        for r in _rows(points_csv(figure))[1:]
        if r[0] == View.MAIN.value
    ]
    assert row["stable"] == "false"
    assert row["max_relative_deviation"] == ""
    assert row["found_fraction"] == "0.0"


# --- flux.csv -------------------------------------------------------------------


def test_flux_csv_columns() -> None:
    assert FLUX_COLUMNS[:7] == (
        "month",
        "panel",
        "activities",
        "with_track",
        "multisession_activities",
        "climbs",
        "flagged",
    )
    assert FLUX_COLUMNS[7 : 7 + len(ClimbFlag)] == tuple(
        f"flag_{flag.value}" for flag in ClimbFlag
    )
    assert FLUX_COLUMNS[7 + len(ClimbFlag) :] == (
        "multisession",
        "unstratified",
        "kept",
        "kept_unstable",
        "points",
        "points_hidden",
        "points_non_positive",
        "points_unstable",
        "stable_only_points",
        "stable_only_points_hidden",
        "stable_only_points_non_positive",
    )


def test_flux_csv(figure: Q1Figure) -> None:
    rows = _rows(flux_csv(figure))
    assert tuple(rows[0]) == FLUX_COLUMNS
    body = [dict(zip(FLUX_COLUMNS, row, strict=True)) for row in rows[1:]]
    months = [m.month for m in figure.month_activities]
    activity_rows = body[: len(months)]
    panel_rows = body[len(months) :]
    assert [r["month"] for r in activity_rows] == months
    assert {r["panel"] for r in activity_rows} == {""}
    for m, r in zip(figure.month_activities, activity_rows, strict=True):
        assert (r["activities"], r["with_track"], r["multisession_activities"]) == (
            str(m.activities),
            str(m.with_track),
            str(m.multisession),
        )
        assert all(r[c] == "" for c in FLUX_COLUMNS[5:])
    assert len(panel_rows) == len(figure.month_panels)
    for mp, r in zip(figure.month_panels, panel_rows, strict=True):
        assert (r["month"], r["panel"]) == (mp.month, mp.panel.value)
        assert all(r[c] == "" for c in FLUX_COLUMNS[2:5])
        assert r["climbs"] == str(mp.climbs)
        assert r["flagged"] == str(mp.flagged)
        for flag, count in mp.flags:
            assert r[f"flag_{flag.value}"] == str(count)
        for name in FLUX_COLUMNS[7 + len(ClimbFlag) :]:
            assert r[name] == str(getattr(mp, name)), name
    long = [r for r in panel_rows if r["panel"] == ClimbRegime.LONG_CLIMB.value]
    assert sum(int(r["flag_spike"]) for r in long) == 1
    assert sum(int(r["points_hidden"]) for r in long) == 1
    assert sum(int(r["kept"]) for r in long) == 6


# --- chaque colonne liée à une valeur distincte (relecture du prototype) --------


def _rich_figure() -> Q1Figure:
    """Une figure où, sommée sur les mois du panneau des montées longues, chaque
    colonne de ``flux.csv`` hors de celles des drapeaux (leur test suit) vaut un nombre
    non nul, différent de toutes les autres :
    41 montées, dont 7 marquées, 6 d'une activité à plusieurs sessions, 9 sans strate,
    19 gardées (dont 8 instables) ; 18 points (4 cachés, 5 au résumé non positif, 2
    instables) ; 10 points de la vue de sensibilité (3 cachés, 1 au résumé non
    positif). Le point modéré et bas de ``w5`` a une enveloppe ouverte et n'est couvert
    qu'en partie sous une variante, où il reste retrouvé."""
    activities = [activity(f"w{i}", start(i)) for i in range(9)]
    activities.append(activity("m", start(9), session_count=2))
    climbs = []
    for i in range(9):
        changes: dict[str, Any] = {}
        if i == 5:
            changes = {
                "moving_gain_m_by_convention": (310.0,) * 3 + (300.0,) * 2,
                "undetermined_s_by_convention": (0.0, 0.0, 0.0, 100.0, 200.0),
            }
        gain = 310.0 if i == 5 else 300.0 + 10 * i
        climbs.append(
            climb(f"w{i}", start(i), 600, 2400, gain, 1800, stable=i >= 3, **changes)
        )
    climbs.append(climb("w8", start(8), 2500, 2800, 40, 200))
    climbs += [
        climb(
            f"w{i}",
            start(i),
            3000,
            3300,
            60,
            200,
            grade=GradeStratum.STEEP,
            stable=i > 0,
        )
        for i in range(4)
    ]
    sinking: dict[str, Any] = {"moving_gain_m_by_convention": (-30.0,) * 5}
    climbs.append(
        climb("w4", start(4), 3000, 3600, 5, 600, grade=GradeStratum.STEEP, **sinking)
    )
    climbs += [
        climb(
            f"w{2 + j}",
            start(2 + j),
            3000,
            3600,
            5,
            600,
            altitude=AltitudeStratum.MID,
            stable=False,
            **sinking,
        )
        for j in range(4)
    ]
    climbs += [
        climb(f"w{i % 9}", start(i % 9), 3700, 3800, 20, 60, flags=(ClimbFlag.SPIKE,))
        for i in range(7)
    ]
    climbs += [
        climb(f"w{i % 9}", start(i % 9), 3900, 4000, 20, 60, altitude=None)
        for i in range(9)
    ]
    climbs += [
        climb("m", start(9), 100 + 300 * k, 300 + 300 * k, 30, 120) for k in range(6)
    ]
    first = VARIANTS[0].name
    rows = [
        r
        for r in same_in_every_variant(climbs)
        if r.activity_ref not in ("w0", "w1")
        and not (
            r.activity_ref == "w5" and r.variant == first and r.start_offset_s == 600
        )
    ]
    rows.append(variant("w5", first, 600, 2200, 310, 1800))
    return q1_figure(tables_of(activities, climbs, rows))


def test_each_flux_column_is_tied_to_a_distinct_value() -> None:
    figure = _rich_figure()
    body = list(csv.DictReader(io.StringIO(flux_csv(figure))))
    long = [r for r in body if r["panel"] == ClimbRegime.LONG_CLIMB.value]
    mine = [m for m in figure.month_panels if m.panel is ClimbRegime.LONG_CLIMB]
    counts = [c for c in FLUX_COLUMNS[5:] if not c.startswith("flag_")]
    totals = {c: sum(int(r[c]) for r in long) for c in counts}
    assert totals == {
        "climbs": 41,
        "flagged": 7,
        "multisession": 6,
        "unstratified": 9,
        "kept": 19,
        "kept_unstable": 8,
        "points": 18,
        "points_hidden": 4,
        "points_non_positive": 5,
        "points_unstable": 2,
        "stable_only_points": 10,
        "stable_only_points_hidden": 3,
        "stable_only_points_non_positive": 1,
    }
    assert totals == {c: sum(getattr(m, c) for m in mine) for c in counts}
    for flag in ClimbFlag:
        assert sum(int(r[f"flag_{flag.value}"]) for r in long) == sum(
            dict(m.flags)[flag] for m in mine
        )
    assert sum(int(r["flag_spike"]) for r in long) == 7
    activities = [r for r in body if r["panel"] == ""]
    assert sum(int(r["activities"]) for r in activities) == 10
    assert sum(int(r["multisession_activities"]) for r in activities) == 1


def test_each_flag_column_is_tied_to_its_flag() -> None:
    """Le drapeau de rang ``i`` (dans l'ordre de ``ClimbFlag``) marque ``i + 1``
    montées, seul ; deux montées ne sont pas marquées : chaque colonne ``flag_*`` a sa
    valeur, différente des autres, de ``flagged`` (28) et de ``climbs`` (30)."""
    assert len(ClimbFlag) == 7
    when = start(0)
    climbs = [climb("a", when, 100, 200, 30, 60), climb("a", when, 300, 400, 30, 60)]
    offset = 1000
    for i, flag in enumerate(ClimbFlag):
        for _ in range(i + 1):
            climbs.append(climb("a", when, offset, offset + 100, 30, 60, flags=(flag,)))
            offset += 200
    figure = q1_figure(tables_of([activity("a", when)], climbs))
    body = list(csv.DictReader(io.StringIO(flux_csv(figure))))
    (row,) = [r for r in body if r["panel"] == ClimbRegime.LONG_CLIMB.value]
    assert (row["climbs"], row["flagged"]) == ("30", "28")
    assert [row[f"flag_{flag.value}"] for flag in ClimbFlag] == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
    ]


def test_activities_and_with_track_differ() -> None:
    """Une activité avec vue, une autre enregistrée sans vue : 2 et 1."""
    activities = [
        activity("a", start(0)),
        activity("b", start(0).replace(day=5), **without_track()),
    ]
    (row,) = list(
        csv.DictReader(io.StringIO(flux_csv(q1_figure(tables_of(activities, [])))))
    )[:1]
    assert (row["activities"], row["with_track"]) == ("2", "1")


def test_each_point_column_is_tied_to_a_distinct_value() -> None:
    """Le point modéré et bas de ``w5`` : une enveloppe ouverte (le bas n'est pas le
    haut), une part des variantes où il est retrouvé qui n'est pas la plus petite part
    de son gain qui reste ; chaque colonne dit sa valeur."""
    figure = _rich_figure()
    rows = list(csv.DictReader(io.StringIO(points_csv(figure))))
    (row,) = [
        r
        for r in rows
        if r["view"] == View.MAIN.value
        and r["activity_ref"] == "w5"
        and r["grade_stratum"] == GradeStratum.MODERATE.value
        and r["altitude_stratum"] == AltitudeStratum.LOW.value
    ]
    (point,) = [
        p
        for p in figure.points
        if p.view is View.MAIN
        and p.activity_ref == "w5"
        and p.grade_stratum is GradeStratum.MODERATE
        and p.altitude_stratum is AltitudeStratum.LOW
    ]
    assert point.vertical_speed_low_ms is not None
    assert point.vertical_speed_high_ms is not None
    assert point.vertical_speed_low_ms < point.vertical_speed_high_ms
    assert float(row["vertical_speed_low_ms"]) == point.vertical_speed_low_ms
    assert float(row["vertical_speed_high_ms"]) == point.vertical_speed_high_ms
    assert point.stability is not None
    assert point.stability.found_fraction == 1.0
    assert point.stability.min_kept_fraction < 1.0
    assert float(row["found_fraction"]) == point.stability.found_fraction
    assert float(row["min_kept_fraction"]) == point.stability.min_kept_fraction


def test_the_three_speed_columns_of_a_point() -> None:
    """Un point dont le résumé θc est à l'intérieur de son enveloppe : 300 m en
    1 000 s sous θc (0,3 m/s) ; 300 m en 1 200 s et 310 m en 950 s sous deux autres
    conventions, les bornes. Chaque colonne de VAM dit sa valeur."""
    c = climb(
        "a",
        start(0),
        100,
        1300,
        300,
        1000,
        moving_gain_m_by_convention=(280.0, 300.0, 300.0, 300.0, 310.0),
        moving_s_by_convention=(1100.0, 1000.0, 1200.0, 1000.0, 950.0),
    )
    figure = q1_figure(tables_of([activity("a", start(0))], [c]))
    (row,) = [
        r
        for r in csv.DictReader(io.StringIO(points_csv(figure)))
        if r["view"] == View.MAIN.value
    ]
    assert float(row["vertical_speed_ms"]) == pytest.approx(0.3)
    assert float(row["vertical_speed_low_ms"]) == pytest.approx(0.25)
    assert float(row["vertical_speed_high_ms"]) == pytest.approx(310 / 950)


def test_the_refusal_names_the_folder_with_slashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, figure: Q1Figure
) -> None:
    """Sous Windows, ``RESULTS_DIR / nom`` s'écrirait avec des ``\\`` : le message
    dit ``resultats/Q1/<nom>/`` sur toutes les plateformes."""
    monkeypatch.setattr(
        results_module, "RESULTS_DIR", PureWindowsPath("resultats", "Q1")
    )
    written = _write(tmp_path, figure)
    with pytest.raises(ResultsError) as raised:
        _write(tmp_path, figure)
    assert str(raised.value) == (
        f"resultats/Q1/{written.name}/ existe déjà : rien n'est réécrit"
    )
