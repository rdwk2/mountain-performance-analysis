"""Contrats de la courbe allure↔pente : vitesse = f(pente), et sa provenance."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from mountain_perf.schemas.common import (
    GRADE_RANGE,
    HEART_RATE_RANGE_BPM,
    SourceRef,
    Sport,
)
from mountain_perf.validation import (
    ContractError,
    require_all_finite,
    require_all_in_range,
    require_aware,
    require_finite,
    require_immutable_sequence,
    require_in_range,
    require_increasing,
    require_min_length,
    require_non_empty,
    require_same_length,
)


@dataclass(frozen=True)
class CurveProvenance:
    """Comment une courbe a été estimée : sur quelles activités, avec quels filtres.

    Champs
    ------
    - ``activity_count`` — sans unité — nombre d'activités ayant servi, ``>= 0``.
    - ``hr_center_bpm`` — battements par minute — centre de la fenêtre de FC retenue,
      ``[20, 250]``, si un filtre de FC a été appliqué.
    - ``hr_width_bpm`` — battements par minute — largeur de cette fenêtre, ``> 0``.
    - ``date_from``, ``date_to`` — dates civiles — fenêtre des activités retenues.
    - ``source_activity_types`` — sans unité — types d'activité de la source retenus
      (``Activity.source_activity_type``).
    - ``min_duration_s`` — secondes — durée minimale d'une activité retenue, ``>= 0``.
    - ``estimator`` — sans unité — nom libre de la méthode d'estimation.
    - ``generated_at`` — instant — moment de l'estimation, *aware*, stocké en UTC.

    Invariants
    ----------
    - ``activity_count >= 0`` ;
    - ``hr_center_bpm`` et ``hr_width_bpm`` présents ensemble ou absents ensemble ;
      finis ; centre dans ``[20, 250]``, largeur ``> 0`` ;
    - ``date_from <= date_to`` ;
    - ``min_duration_s`` fini et ``>= 0`` si présent ;
    - ``estimator`` non vide ;
    - ``generated_at`` *aware*, normalisé en UTC.

    **Pourquoi la provenance est un champ et non un commentaire** : il y aura plusieurs
    courbes pour un même sport — course, randonnée, fin de saison, FC 150. Marcher les
    descentes au lieu de les courir ne change pas l'échelle de la courbe, ça change sa
    **forme**, et appliquer la mauvaise courbe ne lève aucune erreur.

    Producteur
    ----------
    L'estimation de courbe (M6b) ; une saisie manuelle pour la courbe figée du M3.

    Consommateurs
    -------------
    Le choix explicite de la courbe dans un scénario ; le backtest (M4), qui doit dire
    sur quoi la courbe a été calibrée.

    Non promis
    ----------
    - un ``source_activity_types`` **vide signifie « aucun filtre »**, pas « aucune
      activité » ;
    - ``activity_count = 0`` est légitime : courbe figée du M3, issue d'un CSV et non
      d'activités ;
    - ``date_from`` et ``date_to`` sont des **dates civiles sans fuseau** ; la borne
      incluse ou exclue n'est pas fixée ici ;
    - ``estimator`` est une chaîne libre en M1 : aucun code ne doit s'y brancher ;
    - rien n'est vérifié contre les activités elles-mêmes.
    """

    activity_count: int
    hr_center_bpm: float | None
    hr_width_bpm: float | None
    date_from: date
    date_to: date
    source_activity_types: frozenset[str]
    min_duration_s: float | None
    estimator: str
    generated_at: datetime

    def __post_init__(self) -> None:
        if self.activity_count < 0:
            raise ContractError(
                f"activity_count doit être >= 0, reçu {self.activity_count}."
            )
        if (self.hr_center_bpm is None) != (self.hr_width_bpm is None):
            raise ContractError(
                "hr_center_bpm et hr_width_bpm doivent être présents ensemble "
                "ou absents ensemble."
            )
        if self.hr_center_bpm is not None:
            require_finite(self.hr_center_bpm, "hr_center_bpm")
            require_in_range(self.hr_center_bpm, *HEART_RATE_RANGE_BPM, "hr_center_bpm")
        if self.hr_width_bpm is not None:
            require_finite(self.hr_width_bpm, "hr_width_bpm")
            if self.hr_width_bpm <= 0:
                raise ContractError(
                    f"hr_width_bpm doit être > 0, reçu {self.hr_width_bpm}."
                )
        if self.date_from > self.date_to:
            raise ContractError(
                f"date_from ({self.date_from}) doit être <= date_to ({self.date_to})."
            )
        if self.min_duration_s is not None:
            require_finite(self.min_duration_s, "min_duration_s")
            if self.min_duration_s < 0:
                raise ContractError(
                    f"min_duration_s doit être >= 0, reçu {self.min_duration_s}."
                )
        require_non_empty(self.estimator, "estimator")
        require_aware(self.generated_at, "generated_at")
        object.__setattr__(self, "generated_at", self.generated_at.astimezone(UTC))


@dataclass(frozen=True)
class PaceCurve:
    """Courbe vitesse horizontale = f(pente), par tranches de pente.

    Tableaux parallèles : la tranche ``i`` est centrée sur ``grade[i]``, de vitesse
    ``speed_ms[i]``, estimée sur ``sample_count[i]`` points.

    Champs
    ------
    - ``sport`` — sans unité — famille de modèle ; sert à interdire les croisements
      absurdes, **pas** à choisir la courbe.
    - ``grade`` — fraction — centres de tranches, ``[-2, 2]``,
      ``Δaltitude / distance horizontale`` ; jamais un pourcentage.
    - ``speed_ms`` — m/s — vitesse horizontale de chaque tranche, ``> 0``.
    - ``sample_count`` — sans unité — points ayant servi à chaque tranche, ``>= 0``.
    - ``dispersion_ms`` — m/s — dispersion de la vitesse dans la tranche, ``>= 0``,
      si estimée.
    - ``estimation`` — sans unité — provenance de l'estimation.
    - ``source`` — sans unité — fichier d'origine, si la courbe en vient (CSV du M3).

    Invariants
    ----------
    - tableaux en tuples, de même longueur, au moins 2 tranches ;
    - flottants finis ;
    - ``grade`` strictement croissant et dans ``[-2, 2]`` ;
    - ``speed_ms > 0`` ; ``sample_count >= 0`` ; ``dispersion_ms >= 0`` si présente.

    ``sample_count`` dit **où la courbe est soutenue par des données** et où elle n'est
    qu'une interpolation : indispensable au M8 pour la dispersion, et pour savoir
    jusqu'où on a le droit de croire les pentes extrêmes.

    Producteur
    ----------
    L'estimation de courbe (M6b) ; la lecture d'un CSV figé (M3).

    Consommateurs
    -------------
    Le moteur de projection (M3), choisie **explicitement** dans le scénario.

    Non promis
    ----------
    - **l'interpolation entre deux tranches** : c'est du M3 ;
    - **l'extrapolation hors de la plage observée** : que vaut la vitesse à −60 % si la
      courbe s'arrête à −40 % ? Non décidé ici, et une interpolation naïve y est
      généralement absurde (ligne de ``BACKLOG.md``, M3) ;
    - l'espacement régulier des tranches ;
    - ``Sport`` ne choisit pas la courbe : plusieurs courbes coexistent pour un sport ;
    - les tableaux ne sont pas copiés ; ils sont exigés immuables.
    """

    sport: Sport
    grade: Sequence[float]
    speed_ms: Sequence[float]
    sample_count: Sequence[int]
    dispersion_ms: Sequence[float] | None
    estimation: CurveProvenance
    source: SourceRef | None

    def __post_init__(self) -> None:
        require_immutable_sequence(self.grade, "grade")
        require_immutable_sequence(self.speed_ms, "speed_ms")
        require_immutable_sequence(self.sample_count, "sample_count")
        arrays: dict[str, Sequence[object]] = {
            "grade": self.grade,
            "speed_ms": self.speed_ms,
            "sample_count": self.sample_count,
        }
        if self.dispersion_ms is not None:
            require_immutable_sequence(self.dispersion_ms, "dispersion_ms")
            arrays["dispersion_ms"] = self.dispersion_ms
        require_same_length(**arrays)
        require_min_length(self.grade, 2, "grade")
        require_all_finite(self.grade, "grade")
        require_all_finite(self.speed_ms, "speed_ms")
        require_all_in_range(self.grade, *GRADE_RANGE, "grade")
        require_increasing(self.grade, "grade", strict=True)
        for i, speed in enumerate(self.speed_ms):
            if speed <= 0:
                raise ContractError(f"speed_ms[{i}] doit être > 0, reçu {speed}.")
        for i, count in enumerate(self.sample_count):
            if count < 0:
                raise ContractError(f"sample_count[{i}] doit être >= 0, reçu {count}.")
        if self.dispersion_ms is not None:
            require_all_finite(self.dispersion_ms, "dispersion_ms")
            require_all_in_range(self.dispersion_ms, 0.0, float("inf"), "dispersion_ms")
