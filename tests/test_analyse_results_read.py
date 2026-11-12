"""La relecture des résultats de Q1 (AN2-3, annexe C.3 du brief) : la dernière figure,
ce qu'elle dit des tables actuelles, les dossiers illisibles. Python pur : ces tests
tournent sans extra."""

from __future__ import annotations

import dataclasses
import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from fixtures.recovery_world import base_tables
from mountain_perf.analyse.results import (
    FIGURE_FILE,
    PROVENANCE_FILE,
    RESULTS_DIR,
    TablesMatch,
    latest_result,
    read_figure,
    stored_results,
)
from mountain_perf.schemas.processed import ProcessedProvenance

OTHER_TABLES = {"commit": "autre"}
"""La provenance de tables qui ne sont pas les actuelles."""


@pytest.fixture(scope="module")
def current(tmp_path_factory: pytest.TempPathFactory) -> ProcessedProvenance:
    return base_tables(tmp_path_factory.mktemp("base")).provenance


def _json(provenance: ProcessedProvenance) -> object:
    """La provenance écrite comme ``provenance.json`` l'écrit."""
    return json.loads(json.dumps(dataclasses.asdict(provenance)))


def _write(
    data_dir: Path,
    name: str,
    *,
    tables: object = OTHER_TABLES,
    generated: str | None = None,
    raw: bytes | None = None,
    figure: str | None = "<html>figure</html>",
    written_ns: int | None = None,
) -> Path:
    """Un dossier ``resultats/Q1/<name>/`` : ``provenance.json`` (``raw``, ou
    ``genere_le`` — par défaut le préfixe du nom — et ``tables``), ``figure.html`` au
    choix, la date de modification de ``provenance.json`` posée au besoin."""
    folder = data_dir / RESULTS_DIR / name
    folder.mkdir(parents=True)
    if raw is None:
        document = {
            "genere_le": name.split("_")[0] if generated is None else generated,
            "tables": tables,
        }
        raw = json.dumps(document).encode("utf-8")
    (folder / PROVENANCE_FILE).write_bytes(raw)
    if figure is not None:
        (folder / FIGURE_FILE).write_text(figure, encoding="utf-8")
    if written_ns is not None:
        os.utime(folder / PROVENANCE_FILE, ns=(written_ns, written_ns))
    return folder


def test_no_folder_no_result(tmp_path: Path, current: ProcessedProvenance) -> None:
    assert latest_result(tmp_path, current) is None
    assert stored_results(tmp_path) == ((), 0)
    (tmp_path / RESULTS_DIR).mkdir(parents=True)
    assert latest_result(tmp_path, current) is None
    assert stored_results(tmp_path) == ((), 0)


def test_the_temporary_folders_are_ignored(
    tmp_path: Path, current: ProcessedProvenance
) -> None:
    _write(
        tmp_path,
        ".2000-01-09_aaaaaaaaaaaa.nouveau",
        tables=_json(current),
        generated="2000-01-09",
    )
    _write(tmp_path, "2000-01-02_bbbbbbbbbbbb")
    latest = latest_result(tmp_path, current)
    assert latest is not None
    assert latest.result.folder.name == "2000-01-02_bbbbbbbbbbbb"
    assert latest.match is TablesMatch.DIFFERENT
    assert latest.unreadable == 0


def test_the_result_of_the_current_tables_wins_over_a_later_one(
    tmp_path: Path, current: ProcessedProvenance
) -> None:
    _write(tmp_path, "2000-01-02_aaaaaaaaaaaa", tables=_json(current))
    _write(tmp_path, "2000-01-05_bbbbbbbbbbbb")
    latest = latest_result(tmp_path, current)
    assert latest is not None
    assert latest.result.folder.name == "2000-01-02_aaaaaaaaaaaa"
    assert latest.match is TablesMatch.SAME


def test_without_the_current_tables_the_latest_date(
    tmp_path: Path, current: ProcessedProvenance
) -> None:
    _write(tmp_path, "2000-01-05_aaaaaaaaaaaa")
    _write(tmp_path, "2000-01-02_bbbbbbbbbbbb")
    latest = latest_result(tmp_path, current)
    assert latest is not None
    assert latest.result.folder.name == "2000-01-05_aaaaaaaaaaaa"
    assert latest.match is TablesMatch.DIFFERENT


def test_on_the_same_day_the_later_written_wins(
    tmp_path: Path, current: ProcessedProvenance
) -> None:
    _write(tmp_path, "2000-01-05_ffffffffffff", written_ns=1_000_000_000)
    _write(tmp_path, "2000-01-05_000000000000", written_ns=2_000_000_000)
    latest = latest_result(tmp_path, current)
    assert latest is not None
    assert latest.result.folder.name == "2000-01-05_000000000000"


def test_the_order_does_not_depend_on_the_listing(
    tmp_path: Path, current: ProcessedProvenance, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("2000-01-05_ffffffffffff", "2000-01-05_000000000000"):
        _write(tmp_path, name, written_ns=1_000_000_000)
    names = ["2000-01-05_000000000000", "2000-01-05_ffffffffffff"]

    def check() -> None:
        latest = latest_result(tmp_path, current)
        assert latest is not None
        assert latest.result.folder.name == "2000-01-05_ffffffffffff"
        results, unreadable = stored_results(tmp_path)
        assert [result.folder.name for result in results] == names
        assert unreadable == 0

    check()
    listing = Path.iterdir

    def reversed_listing(self: Path) -> Iterator[Path]:
        return iter(sorted(listing(self), reverse=True))

    monkeypatch.setattr(Path, "iterdir", reversed_listing)
    assert [p.name for p in (tmp_path / RESULTS_DIR).iterdir()] == names[::-1]
    check()


def test_the_written_provenance_is_compared_as_json(
    tmp_path: Path, current: ProcessedProvenance
) -> None:
    assert dataclasses.asdict(current) != _json(current)
    _write(tmp_path, "2000-01-02_aaaaaaaaaaaa", tables=_json(current))
    latest = latest_result(tmp_path, current)
    assert latest is not None
    assert latest.match is TablesMatch.SAME


def test_a_provenance_from_before_an2_2_is_different(
    tmp_path: Path, current: ProcessedProvenance
) -> None:
    old = _json(current)
    assert isinstance(old, dict)
    for name in ("acquired_at", "day_count", "interim_days_sha256", "journal_sha256"):
        del old[name]
    _write(tmp_path, "2000-01-02_aaaaaaaaaaaa", tables=old)
    latest = latest_result(tmp_path, current)
    assert latest is not None
    assert latest.match is TablesMatch.DIFFERENT


def test_without_current_tables_the_comparison_is_unknown(
    tmp_path: Path, current: ProcessedProvenance
) -> None:
    _write(tmp_path, "2000-01-01_aaaaaaaaaaaa", tables=_json(current))
    _write(tmp_path, "2000-01-02_bbbbbbbbbbbb")
    latest = latest_result(tmp_path, None)
    assert latest is not None
    assert latest.match is TablesMatch.UNKNOWN
    assert latest.result.folder.name == "2000-01-02_bbbbbbbbbbbb"


@pytest.mark.parametrize(
    ("name", "raw"),
    [
        ("2000-01-06_cccccccccccc", b'{"genere_le": "2000-01-06", "tables"'),
        ("2000-01-06_cccccccccccc", b'{"tables": {}}'),
        ("2000-01-06_cccccccccccc", b'{"genere_le": "hier", "tables": {}}'),
        ("2000-01-06_cccccccccccc", b'{"genere_le": "2000-01-06"}'),
        ("2000-01-06_cccccccccccc", b'["2000-01-06", {}]'),
        ("2000-01-06_cccccccccccc", bytes.fromhex("fffe7b7d")),
        ("20000106_cccccccccccc", b'{"genere_le": 20000106, "tables": {}}'),
    ],
    ids=[
        "json-casse",
        "sans-genere-le",
        "hier",
        "sans-tables",
        "liste",
        "pas-utf8",
        "numerique",
    ],
)
def test_an_unreadable_provenance_is_counted_and_skipped(
    tmp_path: Path, current: ProcessedProvenance, name: str, raw: bytes
) -> None:
    _write(tmp_path, name, raw=raw)
    _write(tmp_path, "2000-01-02_bbbbbbbbbbbb")
    latest = latest_result(tmp_path, current)
    assert latest is not None
    assert latest.result.folder.name == "2000-01-02_bbbbbbbbbbbb"
    assert latest.unreadable == 1
    results, unreadable = stored_results(tmp_path)
    assert [result.folder.name for result in results] == ["2000-01-02_bbbbbbbbbbbb"]
    assert unreadable == 1


def test_a_folder_without_provenance_is_unreadable(tmp_path: Path) -> None:
    root = tmp_path / RESULTS_DIR
    (root / "2000-01-02_aaaaaaaaaaaa").mkdir(parents=True)
    (root / "fichier.txt").write_text("texte", encoding="utf-8")
    assert stored_results(tmp_path) == ((), 1)


def test_read_figure(tmp_path: Path, current: ProcessedProvenance) -> None:
    folder = _write(tmp_path, "2000-01-02_aaaaaaaaaaaa", figure="<p>é</p>")
    latest = latest_result(tmp_path, current)
    assert latest is not None
    assert read_figure(latest.result) == "<p>é</p>"
    (folder / FIGURE_FILE).unlink()
    assert read_figure(latest.result) is None


def test_a_date_that_is_not_the_prefix_is_unreadable(tmp_path: Path) -> None:
    _write(tmp_path, "2000-01-02_aaaaaaaaaaaa", generated="2030-01-02")
    assert stored_results(tmp_path) == ((), 1)
    compact = tmp_path / "compact"
    _write(compact, "20000106_aaaaaaaaaaaa", generated="20000106")
    assert stored_results(compact) == ((), 1)


def test_a_folder_with_only_the_temporary_prefix_is_read(tmp_path: Path) -> None:
    _write(tmp_path, ".2000-01-09_aaaaaaaaaaaa", generated="2000-01-09")
    _write(tmp_path, "2000-01-08_bbbbbbbbbbbb.nouveau", generated="2000-01-08")
    results, unreadable = stored_results(tmp_path)
    assert [result.folder.name for result in results] == [
        "2000-01-08_bbbbbbbbbbbb.nouveau"
    ]
    assert unreadable == 1


def test_a_provenance_without_tables_is_unreadable(tmp_path: Path) -> None:
    _write(tmp_path, "2000-01-09_aaaaaaaaaaaa", raw=b'{"genere_le": "2000-01-09"}')
    assert stored_results(tmp_path) == ((), 1)


# Correctifs de la PR AN2-3, lot 1 : les règles qu'aucun test ne tenait.

JANUARY_2026_NS = 1_767_225_600_000_000_000
"""Le 1er janvier 2026 à minuit UTC, en nanosecondes."""


def test_the_latest_of_two_current_results(
    tmp_path: Path, current: ProcessedProvenance
) -> None:
    """L5 : parmi deux résultats aux tables actuelles, le plus récent."""
    _write(tmp_path, "2000-01-02_aaaaaaaaaaaa", tables=_json(current))
    _write(tmp_path, "2000-01-05_bbbbbbbbbbbb", tables=_json(current))
    latest = latest_result(tmp_path, current)
    assert latest is not None
    assert latest.result.folder.name == "2000-01-05_bbbbbbbbbbbb"
    assert latest.match is TablesMatch.SAME


def test_the_whole_date_is_the_prefix_of_the_name(tmp_path: Path) -> None:
    """L3 : un dossier daté du 5 dont ``genere_le`` vaut le 6 est illisible ; un nom
    qui porte deux « _ » après la date, ``genere_le`` étant cette date, est lisible."""
    other_day = tmp_path / "jour"
    _write(other_day, "2000-01-05_aaaaaaaaaaaa", generated="2000-01-06")
    assert stored_results(other_day) == ((), 1)
    two_parts = tmp_path / "deux"
    _write(two_parts, "2000-01-05_aaaaaa_bbbbbb", generated="2000-01-05")
    results, unreadable = stored_results(two_parts)
    assert [result.folder.name for result in results] == ["2000-01-05_aaaaaa_bbbbbb"]
    assert unreadable == 0


def test_two_unreadable_folders_count_two(tmp_path: Path) -> None:
    """L3 : chaque dossier illisible compte."""
    _write(tmp_path, "2000-01-05_aaaaaaaaaaaa", generated="2030-01-05")
    _write(tmp_path, "2000-01-06_bbbbbbbbbbbb", raw=b"{")
    assert stored_results(tmp_path) == ((), 2)


def test_the_tie_is_decided_by_the_nanoseconds(
    tmp_path: Path, current: ProcessedProvenance
) -> None:
    """L5 : au même ``genere_le``, le ``provenance.json`` écrit le plus tard gagne,
    par ``st_mtime_ns`` : deux instants de 2026 distincts en nanosecondes, au même
    ``st_mtime``, le plus tardif portant le nom le plus petit."""
    earlier = (
        _write(tmp_path, "2000-01-05_ffffffffffff", written_ns=JANUARY_2026_NS)
        / PROVENANCE_FILE
    )
    later = (
        _write(tmp_path, "2000-01-05_000000000000", written_ns=JANUARY_2026_NS + 100)
        / PROVENANCE_FILE
    )
    assert earlier.stat().st_mtime == later.stat().st_mtime
    assert earlier.stat().st_mtime_ns < later.stat().st_mtime_ns
    latest = latest_result(tmp_path, current)
    assert latest is not None
    assert latest.result.folder.name == "2000-01-05_000000000000"


def test_the_figure_is_read_as_utf8(
    tmp_path: Path, current: ProcessedProvenance, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L8 : la figure se lit en UTF-8 même quand l'encodage par défaut de la machine
    ne l'est pas : ``Path.read_text`` sans encodage y lit du cp1252."""
    _write(tmp_path, "2000-01-02_aaaaaaaaaaaa", figure="<p>Récupération — été</p>")
    latest = latest_result(tmp_path, current)
    assert latest is not None
    read_text = Path.read_text

    def cp1252_by_default(
        self: Path, encoding: str | None = None, errors: str | None = None
    ) -> str:
        return read_text(self, encoding=encoding or "cp1252", errors=errors)

    monkeypatch.setattr(Path, "read_text", cp1252_by_default)
    assert read_figure(latest.result) == "<p>Récupération — été</p>"
