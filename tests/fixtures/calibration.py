"""Monde synthétique du calage (M4c-1) — § 7.1 du brief M4c-1.

Objets construits directement, sans GPX ni appariement : le calage ne lit que les temps
des segments admis et les projections non calées (``0010`` D9.2).

- :func:`clock_times` : les onze temps d'un segment, **distincts** d'une horloge à
  l'autre (écoulé ``e`` ; ``M θc = e·(0,79 + 0,01·c)`` ;
  ``(M+U) θc = e·(0,89 + 0,01·c)``), ou nuls sous les cinq ``M θ`` ;
- :class:`OutingSpec` : une sortie — jour, départ et durée, étiquette, référence,
  segments (classe, écoulé), et pour chaque modèle non calé ses rapports ``p_i / e_i``
  par scénario ; :class:`WorldSpec` : un monde, ses sorties, ses sorties non scorées et
  ses jours évalués ;
- :data:`WORLDS` : les quatre mondes du § 7.1 par leur nom ;
- :func:`world_performances`, :func:`world_scores` : les ``Performance`` et les scores
  non calés (``score_outing``) d'un monde ;
- :func:`close` : la tolérance ``1e−12·max(1, |x|)`` du § 7.0.

Utilisées par ``tests/test_backtest_calibration.py`` et par le calcul des valeurs du
§ 7.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from fixtures.outings import PARIS_SUMMER, outing_at, source
from mountain_perf.backtest import score_outing, score_scenario
from mountain_perf.schemas import (
    CLOCKS,
    AdmittedSegment,
    ModelForecast,
    ModelKind,
    ObservedPoint,
    OutingLabel,
    OutingObservation,
    OutingScores,
    ParameterSet,
    Performance,
    RegimeClass,
    Scenario,
    TargetMember,
    Unavailability,
)

RELATIVE_TOLERANCE = 1e-12
"""La tolérance du § 7.0 : ``1e−12·max(1, |x|)``, ``x`` la valeur attendue."""


def close(actual: float | None, expected: float | None) -> bool:
    """``actual`` vaut ``expected`` à ``1e−12·max(1, |expected|)`` près ; deux absences
    sont égales."""
    if actual is None or expected is None:
        return actual is None and expected is None
    return abs(actual - expected) <= RELATIVE_TOLERANCE * max(1.0, abs(expected))


SEGMENT_M = 100.0
"""Le segment ``k`` a pour bornes ``[100·k ; 100·(k + 1)]`` (nominales, effectives et
réalisées)."""

GENERATED_AT = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
"""L'instant fixe des prévisions du monde."""

A, F, D, X = "ascent", "flat", "descent", "mixed"
UNSCALED = (
    ModelKind.V0_RAW,
    ModelKind.CONSTANT_SPEED,
    ModelKind.NAISMITH,
    ModelKind.TOBLER,
)
"""Les quatre modèles non calés d'une sortie scorée."""


def clock_times(elapsed: float, *, zero_moving: bool = False) -> tuple[float, ...]:
    """Les onze temps d'un segment d'écoulé ``elapsed`` : ``M θc = e·(0,79 + 0,01·c)``
    et ``(M+U) θc = e·(0,89 + 0,01·c)`` pour ``c = 1…5`` ; ``zero_moving`` : nuls sous
    les cinq ``M θ``."""
    moving = tuple(
        0.0 if zero_moving else elapsed * (0.79 + 0.01 * c) for c in range(1, 6)
    )
    moving_or_undetermined = tuple(elapsed * (0.89 + 0.01 * c) for c in range(1, 6))
    return (elapsed, *moving, *moving_or_undetermined)


Ratios = Mapping[ModelKind, tuple[float, ...]]
"""Pour chaque modèle non calé, le rapport ``p_i / e_i`` de chaque segment ; ``nan``
écrit une projection absente (``None``)."""


@dataclass(frozen=True)
class OutingSpec:
    """Une sortie du monde.

    ``day`` et ``hour`` : départ à Paris (UTC+2), ``duration_h`` heures ;
    ``segments`` : ``(classe, écoulé)`` ; ``zero_moving`` : temps nuls sous les
    ``M θ`` ; ``usage`` et ``control`` : les rapports de chaque modèle par segment ;
    ``usage`` vide : sortie sans référence."""

    outing_id: str
    day: str
    label: OutingLabel | None
    segments: tuple[tuple[str, float], ...]
    control: Ratios
    usage: Ratios = field(default_factory=dict)
    hour: int = 9
    duration_h: float = 1.0
    zero_moving: bool = False


@dataclass(frozen=True)
class WorldSpec:
    """Un monde : ses sorties, celles qui ne sont pas scorées (présentes dans les
    performances, absentes des scores), et les jours évalués dont le brief publie les
    valeurs."""

    outings: tuple[OutingSpec, ...]
    unscored: frozenset[str]
    evaluated: tuple[str, ...]


def _same(ratio: float, n: int) -> tuple[float, ...]:
    return (ratio,) * n


def _ratios(
    n: int, v0: float, constant: float, naismith: float, tobler: float
) -> dict[ModelKind, tuple[float, ...]]:
    """Des rapports égaux sur les ``n`` segments, un par modèle."""
    return {
        ModelKind.V0_RAW: _same(v0, n),
        ModelKind.CONSTANT_SPEED: _same(constant, n),
        ModelKind.NAISMITH: _same(naismith, n),
        ModelKind.TOBLER: _same(tobler, n),
    }


TRAINING, RACE = OutingLabel.TRAINING, OutingLabel.RACE
NAN = math.nan

# --- Monde : population, exclusions, retraits, erreurs du modèle, bornes de l'origine
MONDE = WorldSpec(
    outings=(
        # A : un membre à référence, rapports variables d'un segment à l'autre.
        OutingSpec(
            "a-0601",
            "2026-06-01",
            TRAINING,
            ((A, 600.0), (D, 300.0), (F, 200.0)),
            control={
                ModelKind.V0_RAW: (0.95, 1.10, 1.02),
                ModelKind.CONSTANT_SPEED: (0.50, 1.60, 1.00),
                ModelKind.NAISMITH: (1.30, 1.70, 1.40),
                ModelKind.TOBLER: (1.20, 1.15, 1.35),
            },
            usage={
                ModelKind.V0_RAW: (0.90, 1.05, 1.00),
                ModelKind.CONSTANT_SPEED: (0.55, 1.50, 0.95),
                ModelKind.NAISMITH: (1.25, 1.65, 1.45),
                ModelKind.TOBLER: (1.10, 1.20, 1.30),
            },
        ),
        # B : un membre de deux sorties ; b2 sans référence (contrôle seul).
        OutingSpec(
            "b1-0602",
            "2026-06-02",
            TRAINING,
            ((A, 400.0), (D, 250.0)),
            control=_ratios(2, 0.85, 0.70, 1.50, 1.25),
            usage=_ratios(2, 0.88, 0.72, 1.45, 1.20),
        ),
        OutingSpec(
            "b2-0602",
            "2026-06-02",
            TRAINING,
            ((F, 900.0),),
            control=_ratios(1, 1.20, 1.10, 1.05, 1.00),
            hour=13,
        ),
        # C : une course, exclue en entier.
        OutingSpec(
            "c-0603",
            "2026-06-03",
            RACE,
            ((A, 500.0),),
            control=_ratios(1, 0.5, 0.5, 0.5, 0.5),
            usage=_ratios(1, 0.5, 0.5, 0.5, 0.5),
        ),
        # D : entraînement et sortie sans étiquette, exclue (étiquette manquante).
        OutingSpec(
            "d1-0604",
            "2026-06-04",
            TRAINING,
            ((A, 500.0),),
            control=_ratios(1, 0.5, 0.5, 0.5, 0.5),
            usage=_ratios(1, 0.5, 0.5, 0.5, 0.5),
        ),
        OutingSpec(
            "d2-0604",
            "2026-06-04",
            None,
            ((A, 500.0),),
            control=_ratios(1, 0.5, 0.5, 0.5, 0.5),
            hour=13,
        ),
        # E : course et sortie sans étiquette : la course passe avant.
        OutingSpec(
            "e1-0605",
            "2026-06-05",
            None,
            ((A, 500.0),),
            control=_ratios(1, 0.5, 0.5, 0.5, 0.5),
        ),
        OutingSpec(
            "e2-0605",
            "2026-06-05",
            RACE,
            ((A, 500.0),),
            control=_ratios(1, 0.5, 0.5, 0.5, 0.5),
            hour=13,
        ),
        # F : un entraînement non scoré : retiré, support vide.
        OutingSpec(
            "f-0606",
            "2026-06-06",
            TRAINING,
            ((A, 500.0),),
            control=_ratios(1, 0.5, 0.5, 0.5, 0.5),
            usage=_ratios(1, 0.5, 0.5, 0.5, 0.5),
        ),
        # G : sans référence (retiré en usage) ; Naismith invalide en contrôle.
        OutingSpec(
            "g-0607",
            "2026-06-07",
            TRAINING,
            ((A, 700.0), (D, 350.0)),
            control={
                **_ratios(2, 1.05, 0.80, 1.35, 1.15),
                ModelKind.NAISMITH: (1.35, NAN),
            },
        ),
        # H : temps nuls sous les M θ (retiré sous ces horloges) ; Naismith invalide en
        # usage — l'observation passe avant le modèle.
        OutingSpec(
            "h-0608",
            "2026-06-08",
            TRAINING,
            ((A, 450.0), (F, 150.0)),
            control=_ratios(2, 0.92, 0.75, 1.40, 1.18),
            usage={
                **_ratios(2, 0.93, 0.74, 1.42, 1.17),
                ModelKind.NAISMITH: (-0.1, 1.42),
            },
            zero_moving=True,
        ),
        # I : scorée sans segment admis : retirée, support vide.
        OutingSpec(
            "i-0609",
            "2026-06-09",
            TRAINING,
            (),
            control=_ratios(0, 1.0, 1.0, 1.0, 1.0),
            usage=_ratios(0, 1.0, 1.0, 1.0, 1.0),
        ),
        # K : partie le 10 à 23 h, finie le 11 à 0 h 30.
        OutingSpec(
            "k-0610",
            "2026-06-10",
            TRAINING,
            ((D, 800.0),),
            control=_ratios(1, 1.08, 0.90, 1.30, 1.12),
            usage=_ratios(1, 1.07, 0.91, 1.31, 1.11),
            hour=23,
            duration_h=1.5,
        ),
        # M : partie le 11 à 23 h, finie le 12 à 0 h pile.
        OutingSpec(
            "m-0611",
            "2026-06-11",
            TRAINING,
            ((A, 650.0),),
            control=_ratios(1, 0.97, 0.78, 1.33, 1.16),
            usage=_ratios(1, 0.96, 0.79, 1.34, 1.15),
            hour=23,
        ),
        # N : deux entraînements le 12 juin ; le second finit le 13 à 0 h 30, après
        # l'origine du 20 juin (13 juin, 0 h) : la performance n'est terminée qu'à la
        # fin de sa dernière sortie.
        OutingSpec(
            "n1-0612",
            "2026-06-12",
            TRAINING,
            ((A, 300.0),),
            control=_ratios(1, 1.0, 0.8, 1.3, 1.1),
            usage=_ratios(1, 1.0, 0.8, 1.3, 1.1),
        ),
        OutingSpec(
            "n2-0612",
            "2026-06-12",
            TRAINING,
            ((D, 300.0),),
            control=_ratios(1, 1.0, 0.8, 1.3, 1.1),
            usage=_ratios(1, 1.0, 0.8, 1.3, 1.1),
            hour=23,
            duration_h=1.5,
        ),
        # Jours évalués.
        OutingSpec(
            "j0-0530",
            "2026-05-30",
            TRAINING,
            ((A, 300.0), (D, 200.0)),
            control=_ratios(2, 1.0, 0.8, 1.3, 1.1),
            usage=_ratios(2, 1.0, 0.8, 1.3, 1.1),
        ),
        OutingSpec(
            "j1-0616",
            "2026-06-16",
            TRAINING,
            ((A, 500.0), (D, 300.0), (F, 100.0), (X, 120.0)),
            control={
                ModelKind.V0_RAW: (0.97, 1.08, 1.01, 0.99),
                ModelKind.CONSTANT_SPEED: (0.60, 1.40, 1.05, 0.90),
                ModelKind.NAISMITH: (1.20, 1.60, 1.30, 1.25),
                ModelKind.TOBLER: (1.10, 1.25, 1.20, 1.15),
            },
            usage={
                ModelKind.V0_RAW: (0.96, 1.07, 1.02, 0.98),
                ModelKind.CONSTANT_SPEED: (0.62, 1.38, 1.04, 0.91),
                ModelKind.NAISMITH: (1.22, 1.58, 1.31, 1.24),
                ModelKind.TOBLER: (1.11, 1.24, 1.21, 1.14),
            },
        ),
        OutingSpec(
            "j2-0617",
            "2026-06-17",
            TRAINING,
            ((A, 400.0), (D, 400.0)),
            control=_ratios(2, 1.02, 0.85, 1.28, 1.13),
        ),
        OutingSpec(
            "j3a-0618",
            "2026-06-18",
            TRAINING,
            ((A, 350.0),),
            control=_ratios(1, 0.98, 0.82, 1.27, 1.14),
            usage=_ratios(1, 0.99, 0.83, 1.26, 1.13),
        ),
        OutingSpec(
            "j3b-0618",
            "2026-06-18",
            TRAINING,
            ((D, 250.0),),
            control=_ratios(1, 1.04, 0.88, 1.29, 1.12),
            hour=13,
        ),
        OutingSpec(
            "j3c-0618",
            "2026-06-18",
            TRAINING,
            ((F, 100.0),),
            control=_ratios(1, 1.0, 1.0, 1.0, 1.0),
            hour=16,
        ),
        OutingSpec(
            "j4-0619",
            "2026-06-19",
            TRAINING,
            ((A, 450.0), (D, 300.0)),
            control=_ratios(2, 1.01, 0.84, 1.29, 1.14),
            usage=_ratios(2, 1.00, 0.83, 1.30, 1.13),
        ),
        OutingSpec(
            "j5-0620",
            "2026-06-20",
            TRAINING,
            ((A, 450.0), (D, 300.0)),
            control=_ratios(2, 1.01, 0.84, 1.29, 1.14),
            usage=_ratios(2, 1.00, 0.83, 1.30, 1.13),
        ),
    ),
    unscored=frozenset({"f-0606", "j3c-0618"}),
    evaluated=(
        "2026-05-30",
        "2026-06-16",
        "2026-06-17",
        "2026-06-18",
        "2026-06-19",
        "2026-06-20",
    ),
)

# --- Saturation : effort borné de v0, à la borne, sous elle, au-dessus d'elle.
SATURATION = WorldSpec(
    outings=(
        # Écoulé : T/P = 2 exactement pour v0 (p = e/2), donc exp(−β) = 0,5.
        OutingSpec(
            "s1-0701",
            "2026-07-01",
            TRAINING,
            ((A, 400.0), (D, 200.0)),
            control=_ratios(2, 0.5, 0.9, 1.4, 1.2),
            usage=_ratios(2, 0.5, 0.9, 1.4, 1.2),
        ),
        OutingSpec(
            "s2-0710",
            "2026-07-10",
            TRAINING,
            ((A, 300.0), (F, 300.0)),
            control=_ratios(2, 1.0 / 3.0, 0.8, 1.3, 1.1),
            usage=_ratios(2, 1.0 / 3.0, 0.8, 1.3, 1.1),
        ),
        OutingSpec(
            "s3-0719",
            "2026-07-19",
            TRAINING,
            ((D, 500.0),),
            control=_ratios(1, 200.0, 1.1, 1.5, 1.3),
            usage=_ratios(1, 200.0, 1.1, 1.5, 1.3),
        ),
        OutingSpec(
            "t1-0709",
            "2026-07-09",
            TRAINING,
            ((A, 300.0), (D, 200.0)),
            control=_ratios(2, 0.6, 0.9, 1.3, 1.1),
            usage=_ratios(2, 0.6, 0.9, 1.3, 1.1),
        ),
        OutingSpec(
            "t2-0718",
            "2026-07-18",
            TRAINING,
            ((A, 300.0), (D, 200.0)),
            control=_ratios(2, 0.6, 0.9, 1.3, 1.1),
            usage=_ratios(2, 0.6, 0.9, 1.3, 1.1),
        ),
        OutingSpec(
            "t3-0727",
            "2026-07-27",
            TRAINING,
            ((A, 300.0), (D, 200.0)),
            control=_ratios(2, 0.6, 0.9, 1.3, 1.1),
            usage=_ratios(2, 0.6, 0.9, 1.3, 1.1),
        ),
    ),
    unscored=frozenset(),
    evaluated=("2026-07-09", "2026-07-18", "2026-07-27"),
)

# --- Retraits : tous les membres retirés en usage (non calé, retraits publiés).
RETRAITS = WorldSpec(
    outings=(
        OutingSpec(
            "r1-0801",
            "2026-08-01",
            TRAINING,
            ((A, 400.0),),
            control=_ratios(1, 1.0, 0.8, 1.3, 1.1),
            usage=_ratios(1, 1.0, 0.8, 1.3, 1.1),
        ),
        OutingSpec(
            "r2-0802",
            "2026-08-02",
            TRAINING,
            ((A, 400.0), (D, 300.0)),
            control=_ratios(2, 1.1, 0.85, 1.35, 1.15),
        ),
        OutingSpec(
            "r3-0810",
            "2026-08-10",
            TRAINING,
            ((A, 400.0), (D, 300.0)),
            control=_ratios(2, 1.0, 0.8, 1.3, 1.1),
            usage=_ratios(2, 1.0, 0.8, 1.3, 1.1),
        ),
    ),
    unscored=frozenset({"r1-0801"}),
    evaluated=("2026-08-10",),
)

# --- Erreur : Tobler sans prévision sur un membre (toutes ses projections absentes).
ERREUR = WorldSpec(
    outings=(
        OutingSpec(
            "x1-0901",
            "2026-09-01",
            TRAINING,
            ((A, 400.0), (D, 300.0)),
            control={
                **_ratios(2, 1.0, 0.8, 1.3, 1.1),
                ModelKind.TOBLER: (NAN, NAN),
            },
            usage={
                **_ratios(2, 1.0, 0.8, 1.3, 1.1),
                ModelKind.TOBLER: (NAN, NAN),
            },
        ),
        OutingSpec(
            "x2-0902",
            "2026-09-02",
            TRAINING,
            ((A, 400.0), (D, 300.0)),
            control=_ratios(2, 1.05, 0.82, 1.32, 1.12),
            usage=_ratios(2, 1.05, 0.82, 1.32, 1.12),
        ),
        OutingSpec(
            "x3-0910",
            "2026-09-10",
            TRAINING,
            ((A, 400.0), (D, 300.0)),
            control=_ratios(2, 1.0, 0.8, 1.3, 1.1),
            usage=_ratios(2, 1.0, 0.8, 1.3, 1.1),
        ),
    ),
    unscored=frozenset(),
    evaluated=("2026-09-10",),
)

WORLDS: Mapping[str, WorldSpec] = {
    "Monde": MONDE,
    "Saturation": SATURATION,
    "Retraits": RETRAITS,
    "Erreur": ERREUR,
}
"""Les quatre mondes du § 7.1, par leur nom."""


# ---------------------------------------------------------------------------
# Construction des objets (§ 7.1)
# ---------------------------------------------------------------------------

REFERENCE = source("gpx", "parcours.gpx", "7")
"""La référence de toutes les sorties à usage."""

TRACE = source("gpx", "trace.gpx", "8")
"""Le tracé de la trace, en contrôle."""


def _start(spec: OutingSpec) -> datetime:
    day = date.fromisoformat(spec.day)
    return datetime(day.year, day.month, day.day, spec.hour, 0, tzinfo=PARIS_SUMMER)


def observation(spec: OutingSpec) -> OutingObservation:
    """L'observation d'une sortie : ses segments ``k = 0, 1…`` de 100 m, et pour ``K``
    la seule arrivée, en ``L`` (indisponible, motif ``absent``, sans segment)."""
    segments = tuple(
        AdmittedSegment(
            k,
            SEGMENT_M * k,
            SEGMENT_M * (k + 1),
            SEGMENT_M * k,
            SEGMENT_M * (k + 1),
            SEGMENT_M * k,
            SEGMENT_M * (k + 1),
            RegimeClass(regime),
            clock_times(elapsed, zero_moving=spec.zero_moving),
        )
        for k, (regime, elapsed) in enumerate(spec.segments)
    )
    length_m = SEGMENT_M * max(1, len(spec.segments))
    if segments:
        totals = tuple(
            math.fsum(segment.times_s[i] for segment in segments)
            for i in range(len(CLOCKS))
        )
        target = ObservedPoint(length_m, len(segments), None, None, totals)
    else:
        target = ObservedPoint(length_m, 0, None, Unavailability.ABSENT, None)
    return OutingObservation(
        reference_length_m=length_m,
        origin_m=0.0,
        origin_s=0.0,
        segments=segments,
        error_points=(),
        members=(TargetMember(None, True),),
        targets=(target,),
        arrival_anchor_gap_m=None,
    )


def _projection(ratio: float, elapsed: float) -> float | None:
    return None if math.isnan(ratio) else ratio * elapsed


def forecast(spec: OutingSpec, model: ModelKind, scenario: Scenario) -> ModelForecast:
    """La prévision non calée de ``model`` : ``p_i = rapport_i · e_i`` ; en usage, le
    cumulé de l'arrivée est la somme des ``p_i`` (absent si l'un l'est)."""
    ratios = (spec.usage if scenario is Scenario.USAGE else spec.control)[model]
    segment_s = tuple(
        _projection(ratio, elapsed)
        for ratio, (_, elapsed) in zip(ratios, spec.segments, strict=True)
    )
    target_s: tuple[float | None, ...] = ()
    if scenario is Scenario.USAGE:
        present = [p for p in segment_s if p is not None]
        total = math.fsum(present) if len(present) == len(segment_s) else None
        target_s = (total if segment_s else None,)
    return ModelForecast(
        scenario=scenario,
        source=REFERENCE if scenario is Scenario.USAGE else TRACE,
        curve_ref="courbe-du-monde",
        parameters=ParameterSet(()),
        engine_version="monde",
        generated_at=GENERATED_AT,
        segment_s=segment_s,
        point_s=(),
        target_s=target_s,
    )


def outing_scores(spec: OutingSpec, model: ModelKind) -> OutingScores:
    """Les scores non calés de ``model`` sur la sortie (``score_scenario``)."""
    obs = observation(spec)
    usage = None
    if spec.usage:
        usage = score_scenario(obs, forecast(spec, model, Scenario.USAGE))
    return score_outing(
        obs, score_scenario(obs, forecast(spec, model, Scenario.CONTROL)), usage
    )


def world_performances(world: WorldSpec) -> tuple[Performance, ...]:
    """Les performances du monde, une par jour, sorties dans l'ordre de leur départ."""
    by_day: dict[str, list[OutingSpec]] = {}
    for spec in world.outings:
        by_day.setdefault(spec.day, []).append(spec)
    performances = []
    for day in sorted(by_day):
        specs = sorted(by_day[day], key=lambda s: (_start(s), s.outing_id))
        outings = tuple(
            outing_at(
                s.outing_id,
                _start(s),
                s.duration_h * 3600.0,
                label=s.label,
            )
            for s in specs
        )
        performances.append(Performance(date.fromisoformat(day), outings))
    return tuple(performances)


def world_scores(world: WorldSpec) -> dict[str, dict[ModelKind, OutingScores]]:
    """Les scores non calés des sorties scorées du monde, sous les quatre modèles."""
    return {
        spec.outing_id: {model: outing_scores(spec, model) for model in UNSCALED}
        for spec in world.outings
        if spec.outing_id not in world.unscored
    }


def end_of(spec: OutingSpec) -> datetime:
    """L'instant de fin de la sortie."""
    return _start(spec) + timedelta(hours=spec.duration_h)
