"""La clé du cache de l'interface, ``tables_key`` (AN2-3, annexe C.5 du brief) : ici,
hors des tests de l'interface, qui n'ont pas le droit d'importer pyarrow."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pyarrow.parquet")

from fixtures.recovery_world import base_tables, world_tables, write_world
from mountain_perf.analyse.parquet import DAYS_FILE, PROCESSED_DIR, tables_key
from mountain_perf.analyse.tables import Tables


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> Tables:
    return base_tables(tmp_path_factory.mktemp("base"))


def test_a_table_without_provenance_gives_no_key(tmp_path: Path, base: Tables) -> None:
    write_world(tmp_path, world_tables(base))
    assert tables_key(tmp_path) is not None
    pq = pytest.importorskip("pyarrow.parquet")
    days = tmp_path / PROCESSED_DIR / DAYS_FILE
    table = pq.read_table(days)
    pq.write_table(table.replace_schema_metadata(None), days)
    assert tables_key(tmp_path) is None


def test_a_table_that_does_not_read_gives_no_key(tmp_path: Path, base: Tables) -> None:
    write_world(tmp_path, world_tables(base))
    days = tmp_path / PROCESSED_DIR / DAYS_FILE
    days.write_bytes(days.read_bytes()[:100])
    assert tables_key(tmp_path) is None
