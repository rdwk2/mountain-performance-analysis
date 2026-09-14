"""Fixtures fixes de la performance — synthétiques, inventées, à valeurs rondes.

- ``FIVE_BIN_CURVE`` : une ``PaceCurve`` à cinq tranches, de −40 % à +40 % par pas de
  20 %, figée « à la main » (``activity_count = 0``, pas de filtre).

Utilisées par ``tests/test_schemas_curve.py``.
"""

from datetime import UTC, date, datetime

from mountain_perf.schemas import CurveProvenance, PaceCurve, SourceRef, Sport

GENERATED_AT = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)

CURVE_SOURCE = SourceRef(
    kind="csv",
    identifier="courbe.csv",
    content_hash="0" * 64,
    retrieved_at=GENERATED_AT,
)

MANUAL_PROVENANCE = CurveProvenance(
    activity_count=0,
    hr_center_bpm=None,
    hr_width_bpm=None,
    date_from=date(2026, 1, 1),
    date_to=date(2026, 6, 30),
    source_activity_types=frozenset(),
    min_duration_s=None,
    estimator="saisie manuelle",
    generated_at=GENERATED_AT,
)

FIVE_BIN_CURVE = PaceCurve(
    sport=Sport.FOOT,
    grade=(-0.4, -0.2, 0.0, 0.2, 0.4),
    speed_ms=(2.0, 3.0, 3.0, 1.5, 0.75),
    sample_count=(10, 40, 100, 40, 10),
    dispersion_ms=(0.5, 0.5, 0.25, 0.25, 0.25),
    estimation=MANUAL_PROVENANCE,
    source=CURVE_SOURCE,
)
