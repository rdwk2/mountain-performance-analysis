"""Courbe synthétique du M3, déjà réduite à son support — inventée, valeurs rondes.

C'est le support que ``read_curve`` retient de
``tests/fixtures/courbe_synthetique.csv`` au seuil de 10 minutes. Elle est
reconstruite ici à la main pour que les tests du modèle d'allure et du moteur ne
dépendent pas du lecteur : si la lecture casse, ce sont ses tests qui rougissent,
pas ceux du calcul.
"""

from datetime import UTC, date, datetime

from mountain_perf.schemas import CurveProvenance, PaceCurve, SourceRef, Sport

CURVE_SOURCE = SourceRef(
    kind="csv",
    identifier="courbe_synthetique.csv",
    content_hash="1" * 64,
    retrieved_at=datetime(2026, 2, 1, 11, 0, tzinfo=UTC),
)

PROVENANCE = CurveProvenance(
    activity_count=3,
    hr_center_bpm=None,
    hr_width_bpm=None,
    date_from=date(2026, 1, 1),
    date_to=date(2026, 1, 31),
    source_activity_types=frozenset({"trail_running"}),
    min_duration_s=0.0,
    estimator="fixture synthétique",
    generated_at=datetime(2026, 2, 1, 11, 0, tzinfo=UTC),
)

SUPPORT_CURVE = PaceCurve(
    sport=Sport.FOOT,
    grade=(-0.20, -0.10, 0.0, 0.10, 0.20),
    speed_ms=(2.0, 2.5, 3.0, 1.5, 1.0),
    sample_count=(1800, 3600, 7200, 5400, 2700),
    dispersion_ms=None,
    estimation=PROVENANCE,
    source=CURVE_SOURCE,
)
"""Support retenu : allures aux nœuds ``0,5 · 0,4 · 1/3 · 2/3 · 1`` s/m.

Vitesses verticales de bord, que le prolongement fige : ``C₋ = 2,0 × 0,20 = 0,4``
m/s en descente, ``C₊ = 1,0 × 0,20 = 0,2`` m/s en montée.
"""
