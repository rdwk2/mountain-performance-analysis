"""Tests des contrats du backtest : sorties, artefacts, rétention, performance.

Un test par invariant du § 4.1 du brief M4a-1 (``0010`` D0, D2), chacun violant cet
invariant seul.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fixtures.outings import (
    ATHLETE,
    END,
    OUTING,
    PARIS_SUMMER,
    PREPARED,
    RECORD,
    START,
    TRACE_ARTIFACT,
    outing_at,
)
from mountain_perf.schemas import (
    ARTIFACT_ROLE_DESCRIPTIONS,
    DATA_SET_DESCRIPTIONS,
    OUTING_LABEL_DESCRIPTIONS,
    REFERENCE_KIND_DESCRIPTIONS,
    UNAVAILABILITY_DESCRIPTIONS,
    ArtifactRef,
    ArtifactRole,
    ContractError,
    DataSet,
    Outing,
    OutingLabel,
    Performance,
    ReferenceKind,
    RetentionDecision,
    RouteReference,
    Unavailability,
)
from strategies import (
    artifact_refs,
    blank_texts,
    naive_datetimes,
    non_finite_floats,
    outings,
    performances,
    route_references,
)

# ---------------------------------------------------------------------------
# Énumérations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("enum", "descriptions"),
    [
        (OutingLabel, OUTING_LABEL_DESCRIPTIONS),
        (DataSet, DATA_SET_DESCRIPTIONS),
        (ReferenceKind, REFERENCE_KIND_DESCRIPTIONS),
        (ArtifactRole, ARTIFACT_ROLE_DESCRIPTIONS),
        (Unavailability, UNAVAILABILITY_DESCRIPTIONS),
    ],
)
def test_every_member_is_described(enum: Any, descriptions: Any) -> None:
    assert set(descriptions) == set(enum)
    assert all(text.strip() for text in descriptions.values())


def test_unavailability_lists_the_twelve_statuses_of_0010_d0() -> None:
    french = [text.split(" — ")[0] for text in UNAVAILABILITY_DESCRIPTIONS.values()]
    assert french == [
        "absent",
        "ambigu",
        "tangente indéfinie",
        "trou",
        "écart intérieur",
        "support insuffisant",
        "temps nul",
        "référence non identifiée",
        "non-convergence",
        "erreur du modèle",
        "non calé",
        "jour multi-sorties",
    ]


# ---------------------------------------------------------------------------
# ArtifactRef, RouteReference
# ---------------------------------------------------------------------------


@given(artifact_refs())
def test_valid_artifact_refs_build(artifact: ArtifactRef) -> None:
    assert artifact.available_at.tzinfo is UTC


@given(naive_datetimes())
def test_artifact_naive_available_at_is_refused(instant: datetime) -> None:
    with pytest.raises(ContractError, match="available_at"):
        replace(TRACE_ARTIFACT, available_at=instant)


def test_artifact_available_at_is_normalized_to_utc() -> None:
    assert TRACE_ARTIFACT.available_at == END
    assert TRACE_ARTIFACT.available_at.tzinfo is UTC
    assert TRACE_ARTIFACT.available_at.hour == 8


@given(route_references())
def test_valid_route_references_build(reference: RouteReference) -> None:
    assert reference.artifact.role is ArtifactRole.FORECAST_INPUT


def test_route_reference_must_be_a_forecast_input() -> None:
    """Un tracé de référence est une entrée de prévision (``0010`` D2.6)."""
    with pytest.raises(ContractError, match="FORECAST_INPUT"):
        replace(PREPARED, artifact=TRACE_ARTIFACT)


# ---------------------------------------------------------------------------
# Outing
# ---------------------------------------------------------------------------


@given(outings())
def test_valid_outings_build(outing: Outing) -> None:
    assert outing.start_time < outing.end_time
    assert outing.elapsed_s > 0


def test_outing_elapsed_s() -> None:
    assert OUTING.elapsed_s == 7200.0


@pytest.mark.parametrize("name", ["outing_id", "athlete_ref"])
@given(value=blank_texts())
def test_outing_blank_identifier_is_refused(name: str, value: str) -> None:
    changes: dict[str, Any] = {name: value}
    if name == "athlete_ref":
        changes["external_records"] = ()
    with pytest.raises(ContractError, match=name):
        replace(OUTING, **changes)


@pytest.mark.parametrize("name", ["start_time", "end_time"])
@given(instant=naive_datetimes())
def test_outing_naive_instant_is_refused(name: str, instant: datetime) -> None:
    changes: dict[str, Any] = {name: instant}
    with pytest.raises(ContractError, match=name):
        replace(OUTING, **changes)


def test_outing_instants_are_normalized_to_utc() -> None:
    assert OUTING.start_time.tzinfo is UTC
    assert OUTING.end_time.tzinfo is UTC
    assert OUTING.start_time == START
    assert OUTING.start_time.hour == 6


@pytest.mark.parametrize("delta_s", [0, -1])
def test_outing_start_must_precede_end(delta_s: int) -> None:
    with pytest.raises(ContractError, match="précéder"):
        replace(OUTING, end_time=START + timedelta(seconds=delta_s))


@pytest.mark.parametrize("name", ["traces", "duplicates", "external_records"])
def test_outing_mutable_sequences_are_refused(name: str) -> None:
    changes: dict[str, Any] = {name: list(getattr(OUTING, name))}
    with pytest.raises(ContractError, match=rf"{name}.*tuple"):
        replace(OUTING, **changes)


@pytest.mark.parametrize("name", ["traces", "duplicates"])
def test_outing_observations_must_be_evaluation_observations(name: str) -> None:
    changes: dict[str, Any] = {name: (PREPARED.artifact,)}
    with pytest.raises(ContractError, match=rf"{name}\[0\]\.role"):
        replace(OUTING, **changes)


def test_outing_duplicates_require_traces() -> None:
    with pytest.raises(ContractError, match="duplicates non vide"):
        replace(OUTING, traces=())


def test_outing_untraced_is_valid() -> None:
    untraced = replace(OUTING, traces=(), duplicates=())
    assert untraced.traces == ()


@pytest.mark.parametrize("name", ["route_id", "variant"])
@given(value=blank_texts())
def test_outing_blank_route_texts_are_refused(name: str, value: str) -> None:
    changes: dict[str, Any] = {name: value}
    with pytest.raises(ContractError, match=name):
        replace(OUTING, **changes)


@pytest.mark.parametrize("name", ["route_id", "variant"])
def test_outing_route_texts_are_optional(name: str) -> None:
    changes: dict[str, Any] = {name: None}
    assert getattr(replace(OUTING, **changes), name) is None


def test_outing_mutable_portion_is_refused() -> None:
    portion: Any = [0.0, 5000.0]
    with pytest.raises(ContractError, match=r"declared_portion_m.*tuple"):
        replace(OUTING, declared_portion_m=portion)


def test_outing_portion_must_be_a_pair() -> None:
    portion: Any = (0.0, 1.0, 2.0)
    with pytest.raises(ContractError, match="couple"):
        replace(OUTING, declared_portion_m=portion)


@pytest.mark.parametrize("index", [0, 1])
@given(value=non_finite_floats())
def test_outing_non_finite_portion_is_refused(index: int, value: float) -> None:
    portion = [100.0, 5000.0]
    portion[index] = value
    with pytest.raises(ContractError, match=rf"declared_portion_m\[{index}\].*fini"):
        replace(OUTING, declared_portion_m=(portion[0], portion[1]))


@pytest.mark.parametrize(
    "portion", [(-1.0, 5000.0), (100.0, 100.0), (200.0, 100.0)], ids=str
)
def test_outing_portion_must_be_ordered_from_zero(
    portion: tuple[float, float],
) -> None:
    with pytest.raises(ContractError, match="0 <= a < b"):
        replace(OUTING, declared_portion_m=portion)


def test_outing_portion_may_start_at_zero_and_is_optional() -> None:
    assert replace(OUTING, declared_portion_m=(0.0, 0.5)).declared_portion_m
    assert replace(OUTING, declared_portion_m=None).declared_portion_m is None


def test_outing_external_record_of_another_athlete_is_refused() -> None:
    """Un relevé d'un autre athlète n'appartient pas à la sortie (``0010`` D2.6)."""
    other = replace(RECORD, athlete_ref="athlete-2")
    with pytest.raises(ContractError, match=r"external_records\[0\]\.athlete_ref"):
        replace(OUTING, external_records=(other,))


def test_outing_optional_declarations_default_to_none() -> None:
    minimal = outing_at("x", START, 60.0)
    assert minimal.traces == minimal.duplicates == ()
    assert minimal.external_records == ()
    assert minimal.reference is None
    assert minimal.dataset is None
    assert minimal.declared_portion_m is None


# ---------------------------------------------------------------------------
# RetentionDecision
# ---------------------------------------------------------------------------

DECISION = RetentionDecision(
    outing=OUTING,
    civil_date=date(2026, 6, 7),
    rank=1,
    cumulative_elapsed_s=7200.0,
    retained=True,
)


@pytest.mark.parametrize("rank", [0, -1])
def test_retention_rank_starts_at_one(rank: int) -> None:
    with pytest.raises(ContractError, match="rank"):
        replace(DECISION, rank=rank)


@given(non_finite_floats())
def test_retention_non_finite_cumulative_is_refused(value: float) -> None:
    with pytest.raises(ContractError, match="cumulative_elapsed_s doit être fini"):
        replace(DECISION, cumulative_elapsed_s=value)


def test_retention_cumulative_cannot_be_below_the_outing_elapsed() -> None:
    with pytest.raises(ContractError, match="cumulative_elapsed_s"):
        replace(DECISION, cumulative_elapsed_s=7200.0 - 1e-5)


def test_retention_cumulative_tolerates_rounding() -> None:
    assert replace(DECISION, cumulative_elapsed_s=7200.0 - 1e-7).rank == 1


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

LATER = outing_at(
    "p1-apres-midi", datetime(2026, 6, 7, 14, 0, tzinfo=PARIS_SUMMER), 3600
)


@given(performances())
def test_valid_performances_build(performance: Performance) -> None:
    assert performance.is_multi_outing == (len(performance.outings) > 1)


def test_performance_requires_an_outing() -> None:
    with pytest.raises(ContractError, match="au moins 1"):
        Performance(civil_date=date(2026, 6, 7), outings=())


def test_performance_mutable_outings_are_refused() -> None:
    items: Any = [OUTING]
    with pytest.raises(ContractError, match=r"outings.*tuple"):
        Performance(civil_date=date(2026, 6, 7), outings=items)


def test_performance_outing_ids_are_distinct() -> None:
    twin = replace(LATER, outing_id=OUTING.outing_id)
    with pytest.raises(ContractError, match="identifiants distincts"):
        Performance(civil_date=date(2026, 6, 7), outings=(OUTING, twin))


def test_performance_has_a_single_athlete() -> None:
    other = replace(LATER, athlete_ref="athlete-2")
    with pytest.raises(ContractError, match="un seul athlete_ref"):
        Performance(civil_date=date(2026, 6, 7), outings=(OUTING, other))


def test_performance_outings_are_ordered_by_start() -> None:
    with pytest.raises(ContractError, match="ordonné"):
        Performance(civil_date=date(2026, 6, 7), outings=(LATER, OUTING))


def test_performance_ties_on_start_are_ordered_by_id() -> None:
    a = outing_at("a", START, 60)
    b = outing_at("b", START, 60)
    assert Performance(civil_date=date(2026, 6, 7), outings=(a, b)).is_multi_outing
    with pytest.raises(ContractError, match="ordonné"):
        Performance(civil_date=date(2026, 6, 7), outings=(b, a))


def test_performance_properties() -> None:
    long_morning = replace(OUTING, end_time=datetime(2026, 6, 7, 20, 0, tzinfo=UTC))
    performance = Performance(
        civil_date=date(2026, 6, 7), outings=(long_morning, LATER)
    )
    assert performance.athlete_ref == ATHLETE
    assert performance.is_multi_outing
    assert performance.end_time == datetime(2026, 6, 7, 20, 0, tzinfo=UTC)
    single = Performance(civil_date=date(2026, 6, 7), outings=(OUTING,))
    assert not single.is_multi_outing
    assert single.end_time == END


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        ((OutingLabel.TRAINING, OutingLabel.RACE), False),
        ((OutingLabel.TRAINING, None), False),
        ((OutingLabel.TRAINING, OutingLabel.TRAINING), True),
    ],
    ids=["entrainement-course", "entrainement-absente", "Y02"],
)
def test_all_training_is_the_historical_label_rule(
    labels: tuple[OutingLabel | None, OutingLabel | None], expected: bool
) -> None:
    """``0010`` D2.4 : une étiquette manquante ne vaut pas entraînement ; une course
    exclut la performance entière."""
    first = replace(OUTING, label=labels[0])
    second = replace(LATER, label=labels[1])
    performance = Performance(civil_date=date(2026, 6, 7), outings=(first, second))
    assert performance.all_training is expected


@given(st.sampled_from(OutingLabel))
def test_single_outing_all_training_follows_its_label(label: OutingLabel) -> None:
    performance = Performance(
        civil_date=date(2026, 6, 7), outings=(replace(OUTING, label=label),)
    )
    assert performance.all_training is (label is OutingLabel.TRAINING)
