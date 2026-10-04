"""Les aides du registre (§ 6.4, § 7.2 et § 8.1, test 12, du brief M4b-4 ; ``0010``
D2.5, D2.6 ; décision 2).

``curve_artifacts`` : le CSV et son compagnon, disponibles à l'instant d'estimation de
la provenance, entrées de prévision. ``declared_performance`` : l'origine ``o_j``,
00:00 à Paris du jour ``J − 7``.
"""

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fixtures import scoring
from fixtures.registry import CURVE_PATH, RETRIEVED_AT, curve, declaration, performances
from mountain_perf.backtest import CURVE_METADATA_KIND, curve_artifacts
from mountain_perf.schemas import ArtifactRef, ArtifactRole, SourceRef

GENERATED_AT = datetime(2026, 2, 1, 11, 0, tzinfo=UTC)
CSV_SHA256 = "6767dd38064dd789547329f9b46bb6c46d3e54b1593daa38f575614cb4744f06"
META_SHA256 = "37e6a68850630cdd6b6a5f6946e0b85a0a507e1446d62b987d60ab023af3471b"


def test_curve_artifacts_of_the_committed_curve() -> None:
    """Décision 2, D2.6 : le CSV lu et son compagnon, leurs empreintes, disponibles à
    ``generated_at`` de la provenance, entrées de prévision."""
    read = scoring.curve_read()
    csv, meta = curve_artifacts(CURVE_PATH, read, retrieved_at=RETRIEVED_AT)
    assert csv == ArtifactRef(read.source, GENERATED_AT, ArtifactRole.FORECAST_INPUT)
    assert (csv.source.kind, csv.source.identifier, csv.source.content_hash) == (
        "csv",
        "courbe_synthetique.csv",
        CSV_SHA256,
    )
    assert CURVE_METADATA_KIND == "json"
    assert meta == ArtifactRef(
        SourceRef("json", "courbe_synthetique.meta.json", META_SHA256, RETRIEVED_AT),
        GENERATED_AT,
        ArtifactRole.FORECAST_INPUT,
    )


def test_curve_of_the_declaration() -> None:
    """§ 7.2 : la courbe déclarée et sa référence."""
    csv, meta = curve()
    assert csv.source == SourceRef(
        "csv", "courbe_synthetique.csv", CSV_SHA256, RETRIEVED_AT
    )
    assert declaration().curve_ref == "courbe_synthetique.csv#6767dd38064d"
    assert (csv.available_at, meta.available_at) == (GENERATED_AT, GENERATED_AT)


def test_companion_read_now_by_default() -> None:
    before = datetime.now(UTC)
    _, meta = curve_artifacts(CURVE_PATH, scoring.curve_read())
    after = datetime.now(UTC)
    assert before <= meta.source.retrieved_at <= after
    assert meta.available_at == GENERATED_AT


def test_curve_artifacts_of_another_file_is_refused(tmp_path: Path) -> None:
    """Précondition : la lecture est celle du fichier nommé."""
    with pytest.raises(
        ValueError,
        match=re.escape(
            "curve_artifacts : la lecture est celle de « courbe_synthetique.csv », pas "
            "de « autre.csv »"
        ),
    ) as raised:
        curve_artifacts(tmp_path / "autre.csv", scoring.curve_read())
    assert raised.type is ValueError


def test_declared_performance_origins() -> None:
    """D2.5 : 00:00 à Paris du jour ``J − 7``, heure d'été."""
    assert [declared.origin for declared in performances()] == [
        datetime(2026, 5, 12, 22, 0, tzinfo=UTC),
        datetime(2026, 5, 19, 22, 0, tzinfo=UTC),
        datetime(2026, 5, 26, 22, 0, tzinfo=UTC),
    ]
