"""Objets de contrat du backtest (M4a) — synthétiques, inventés, à valeurs rondes.

- ``OUTING`` : une sortie tracée complète — préparé, doublon, portion, jeu, étiquette,
  relevé externe — du 2026-06-07, de 08:00 à 10:00 à Paris (heure d'été).
- ``outing_at`` : une sortie minimale à un départ et une durée donnés, pour la
  rétention et le domaine.
- ``PARIS_SUMMER`` : le décalage fixe UTC+2 de l'heure d'été ; il construit des
  instants à Paris **sans dépendre de tzdata**.

Utilisées par ``tests/test_schemas_outing.py`` et ``tests/test_backtest_outings.py``.
"""

from datetime import UTC, date, datetime, timedelta, timezone

from mountain_perf.schemas import (
    ArtifactRef,
    ArtifactRole,
    DataSet,
    ObservedPassage,
    Outing,
    OutingLabel,
    ReferenceKind,
    ReferencePerformance,
    RouteReference,
    SourceRef,
    Sport,
    TimingConvention,
)

PARIS_SUMMER = timezone(timedelta(hours=2))
RETRIEVED_AT = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
ATHLETE = "athlete-1"


def source(kind: str, identifier: str, digit: str) -> SourceRef:
    """Provenance inventée : l'empreinte est un chiffre répété 64 fois."""
    return SourceRef(
        kind=kind,
        identifier=identifier,
        content_hash=digit * 64,
        retrieved_at=RETRIEVED_AT,
    )


START = datetime(2026, 6, 7, 8, 0, tzinfo=PARIS_SUMMER)
END = datetime(2026, 6, 7, 10, 0, tzinfo=PARIS_SUMMER)

TRACE_ARTIFACT = ArtifactRef(
    source("gpx", "jour3.gpx", "1"), END, ArtifactRole.EVALUATION_OBSERVATION
)
DUPLICATE_ARTIFACT = ArtifactRef(
    source("fit", "jour3.fit", "2"), END, ArtifactRole.EVALUATION_OBSERVATION
)
PREPARED = RouteReference(
    kind=ReferenceKind.PREPARED,
    artifact=ArtifactRef(
        source("gpx", "prepare.gpx", "3"),
        datetime(2026, 5, 24, 20, 0, tzinfo=PARIS_SUMMER),
        ArtifactRole.FORECAST_INPUT,
    ),
)
RECORD = ReferencePerformance(
    athlete_ref=ATHLETE,
    event_name="Relevé inventé",
    date=date(2026, 6, 7),
    passages=(
        ObservedPassage("Départ", 0.0, 0.0, TimingConvention.DEPARTURE),
        ObservedPassage("Col", 3600.0, None, TimingConvention.UNKNOWN),
    ),
    source=source("manifest", "manifeste.json", "4"),
)

OUTING = Outing(
    outing_id="p1-2026-06-07",
    athlete_ref=ATHLETE,
    sport=Sport.FOOT,
    start_time=START,
    end_time=END,
    traces=(TRACE_ARTIFACT,),
    duplicates=(DUPLICATE_ARTIFACT,),
    route_id="p1",
    variant="courte",
    declared_portion_m=(0.0, 5000.0),
    reference=PREPARED,
    dataset=DataSet.REPEATABILITY,
    label=OutingLabel.TRAINING,
    external_records=(RECORD,),
)


def outing_at(
    outing_id: str,
    start_time: datetime,
    duration_s: float,
    *,
    sport: Sport = Sport.FOOT,
    label: OutingLabel | None = OutingLabel.TRAINING,
    athlete_ref: str = ATHLETE,
) -> Outing:
    """Sortie non tracée minimale : départ, durée, sport et étiquette."""
    return Outing(
        outing_id=outing_id,
        athlete_ref=athlete_ref,
        sport=sport,
        start_time=start_time,
        end_time=start_time + timedelta(seconds=duration_s),
        label=label,
    )
