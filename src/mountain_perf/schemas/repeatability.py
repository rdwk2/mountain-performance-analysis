"""Contrats de la référence prédictive de répétabilité d'un parcours (M4b-3).

Protocole : ``docs/decisions/0010`` D8 (et ses précisions de M4b-3), D0, D5.5, D7.2,
D7.5. Par parcours, sur les jours du jeu de répétabilité, sous chacune des onze
horloges : un gabarit ``y_uk = a_k + c_u`` appris sur les autres jours prédit le jour
retiré (pli), classe par classe ; ``F`` moyenne les scores des plis.

Aucun calcul ici : les producteurs vivent dans ``mountain_perf.backtest.repeatability``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from mountain_perf.schemas.clock import CLOCKS, Clock
from mountain_perf.schemas.common import SourceRef
from mountain_perf.schemas.matching import RegimeClass
from mountain_perf.schemas.metrics import MetricValue
from mountain_perf.schemas.outing import Performance, Unavailability
from mountain_perf.schemas.scoring import AdmittedSegment
from mountain_perf.validation import (
    ContractError,
    require_finite,
    require_immutable_sequence,
    require_in_range,
)

CERTIFICATION_TOLERANCE = 1e-8
"""Le seuil des quatre critères de certification de ``0010`` D8.3 : moyenne des
résidus par segment, par jour, somme des ``c_u`` (centrage) et incrément des ajustés
d'une itération à la suivante, chacun **strictement** sous ce seuil (choix 3 du brief
M4b-3)."""

MIN_CONTRIBUTING_SEGMENTS = 3
"""L'effectif de classe minimal pour qu'une valeur de régime contribue à ``F``
(``0010`` D7.5, D10.2, précision de D8.4) : une classe de moins de 3 segments dans
``S_j`` est « trop peu représentée » ; sa valeur reste publiée. Égal à
``UNDERREPRESENTED_BELOW`` de M4b-1 (vérifié par un test)."""

FIT_UNAVAILABILITY: frozenset[Unavailability] = frozenset(
    {
        Unavailability.INSUFFICIENT_SUPPORT,
        Unavailability.UNIDENTIFIED_REFERENCE,
        Unavailability.ZERO_TIME,
        Unavailability.NON_CONVERGENCE,
        Unavailability.MODEL_ERROR,
    }
)
"""Les cinq motifs qu'un ajustement d'un pli et d'une classe peut porter (``0010``
D8.2 à D8.4) : support insuffisant, référence non identifiée, temps nul,
non-convergence, erreur du modèle. Un ajustement « en échec » porte l'un des quatre
derniers ; ``insufficient_support`` n'est pas un échec (aucun segment vu)."""

_FAILED_WITHOUT_COMPONENT = frozenset(
    {Unavailability.INSUFFICIENT_SUPPORT, Unavailability.UNIDENTIFIED_REFERENCE}
)
"""Les motifs d'un ajustement sans composante ajustée."""

_FITTED = frozenset({None, Unavailability.NON_CONVERGENCE, Unavailability.MODEL_ERROR})
"""Les états d'un ajustement où ``two_way_fit`` a tourné."""

_CLASS_ORDER = tuple(RegimeClass)


def _require_effects(effects: tuple[tuple[int, float], ...], name: str) -> None:
    """Non vide, clés strictement croissantes, valeurs finies."""
    if not effects:
        raise ContractError(f"{name} ne doit pas être vide.")
    for (previous, _), (current, _) in pairwise(effects):
        if not previous < current:
            raise ContractError(
                f"les clés de {name} sont strictement croissantes, reçu {previous} "
                f"puis {current}."
            )
    for key, value in effects:
        require_finite(value, f"{name}[{key}]")


def _require_increasing_dates(dates: tuple[date, ...], name: str) -> None:
    for previous, current in pairwise(dates):
        if not previous < current:
            raise ContractError(
                f"{name} est strictement croissant, reçu {previous} puis {current}."
            )


@dataclass(frozen=True)
class TwoWayFit:
    """L'ajustement additif ``y_uk = a_k + c_u`` d'une composante connexe (``0010``
    D8.1 à D8.3).

    Champs
    ------
    - ``segment_effects`` — log-secondes — les ``(k, a_k)``.
    - ``day_effects`` — log-secondes — les ``(u, c_u)`` ; ``u`` est le rang que
      l'appelant donne au jour.
    - ``iterations`` — sans unité — le nombre d'itérations faites.
    - ``residuals`` — log-secondes — les critères de D8.3 à la dernière itération,
      dans cet ordre : moyenne de résidus par segment (maximum des valeurs absolues),
      par jour (idem), ``|Σ c_u|``, incrément maximal des ajustés.
    - ``certified`` — sans unité — les quatre critères sont sous le seuil.

    Invariants
    ----------
    - les trois séquences sont des tuples ; ``iterations >= 1`` ;
    - ``segment_effects`` et ``day_effects`` non vides, clés strictement croissantes,
      valeurs finies ;
    - ``residuals`` a quatre valeurs, chacune ``>= 0`` et non ``nan`` ; finie, sauf
      ``residuals[3]``, qui peut valoir ``inf`` quand ``iterations == 1`` (pas
      d'incrément à la première itération) ;
    - ``certified`` **si et seulement si** les quatre valeurs sont
      ``< CERTIFICATION_TOLERANCE``.

    Producteur
    ----------
    ``two_way_fit`` (``mountain_perf.backtest.repeatability``).

    Consommateurs
    -------------
    ``repeatability_reference`` (``mountain_perf.backtest.repeatability``).

    Non promis
    ----------
    La certification borne les équations normales et la stabilité de l'itération, pas
    l'erreur sur ``a_k`` ni sur une prévision (précision de D8.3) ; non certifié,
    l'ajustement publie le dernier état, sans valeur de preuve.
    """

    segment_effects: tuple[tuple[int, float], ...]
    day_effects: tuple[tuple[int, float], ...]
    iterations: int
    residuals: tuple[float, float, float, float]
    certified: bool

    def __post_init__(self) -> None:
        for name in ("segment_effects", "day_effects", "residuals"):
            require_immutable_sequence(getattr(self, name), name)
        if self.iterations < 1:
            raise ContractError(f"iterations doit être >= 1, reçu {self.iterations}.")
        _require_effects(self.segment_effects, "segment_effects")
        _require_effects(self.day_effects, "day_effects")
        self._check_residuals()
        self._check_certification()

    def _check_residuals(self) -> None:
        if len(self.residuals) != 4:
            raise ContractError(
                f"residuals porte les quatre critères de D8.3, reçu "
                f"{len(self.residuals)} valeurs."
            )
        for i, value in enumerate(self.residuals):
            if math.isnan(value) or value < 0:
                raise ContractError(f"residuals[{i}] doit être >= 0, reçu {value}.")
            first_increment = i == 3 and self.iterations == 1
            if math.isinf(value) and not first_increment:
                raise ContractError(
                    f"residuals[{i}] doit être fini (seul l'incrément de la première "
                    f"itération vaut inf), reçu {value} à l'itération "
                    f"{self.iterations}."
                )

    def _check_certification(self) -> None:
        below = all(value < CERTIFICATION_TOLERANCE for value in self.residuals)
        if self.certified != below:
            raise ContractError(
                "certified si et seulement si les quatre critères sont sous "
                f"{CERTIFICATION_TOLERANCE} (D8.3), reçu certified={self.certified}, "
                f"residuals={self.residuals}."
            )


@dataclass(frozen=True)
class RepeatabilityDay:
    """Un jour du jeu de répétabilité d'un parcours, et ses segments admis (``0010``
    D0, D8.1).

    Champs
    ------
    - ``performance`` — sans unité — le jour (date civile, sorties).
    - ``reference`` — sans unité — la référence du parcours, celle dont la grille de
      score a donné les segments.
    - ``segments`` — sans unité — les segments admis de la sortie du jour
      (``OutingObservation.segments`` de M4b-2), sous les onze horloges ; ``None``
      pour un jour multi-sorties.

    Invariants
    ----------
    - ``performance`` est une ``Performance``, ``reference`` un ``SourceRef`` ;
    - ``segments`` absent **si et seulement si** ``performance.is_multi_outing`` ;
    - présent : un tuple (vide permis), d'indices strictement croissants.

    Producteur
    ----------
    L'appelant (M4b-5, depuis l'observation de la sortie du jour par
    ``observe_outing`` contre la référence du parcours).

    Consommateurs
    -------------
    ``repeatability_reference`` (``mountain_perf.backtest.repeatability``).

    Non promis
    ----------
    Le contrat ne vérifie pas que les segments viennent de ``reference`` ni leur
    cohérence d'un jour à l'autre : ``repeatability_reference`` vérifie la seconde
    (préconditions).
    """

    performance: Performance
    reference: SourceRef
    segments: tuple[AdmittedSegment, ...] | None

    def __post_init__(self) -> None:
        if not isinstance(self.performance, Performance):
            raise ContractError(
                f"performance doit être une Performance, reçu {self.performance!r}."
            )
        if not isinstance(self.reference, SourceRef):
            raise ContractError(
                f"reference doit être un SourceRef, reçu {self.reference!r}."
            )
        multi = self.performance.is_multi_outing
        if (self.segments is None) != multi:
            raise ContractError(
                "segments est absent si et seulement si le jour est multi-sorties, "
                f"reçu segments={'absent' if self.segments is None else 'présent'}, "
                f"is_multi_outing={multi}."
            )
        if self.segments is not None:
            require_immutable_sequence(self.segments, "segments")
            for previous, current in pairwise(self.segments):
                if not previous.index < current.index:
                    raise ContractError(
                        "les index des segments sont strictement croissants, reçu "
                        f"{previous.index} puis {current.index}."
                    )


@dataclass(frozen=True)
class ClassFit:
    """L'ajustement d'un pli et d'une classe (``0010`` D8.2, D8.3).

    Champs
    ------
    - ``regime_class`` — sans unité — la classe.
    - ``unavailability`` — sans unité — ``None`` : ajustement certifié, prévisions
      disponibles sur ``S_jR`` ; sinon le motif.
    - ``left_count`` — sans unité — le nombre de cellules du jour retiré dans la
      classe.
    - ``seen_count`` — sans unité — ``|S_jR|``, celles qu'au moins un jour
      d'apprentissage observe.
    - ``training_days``, ``training_segments``, ``training_cells`` — sans unité — les
      effectifs de la composante ajustée (``0`` sans composante).
    - ``zero_cells`` — sans unité — les cellules nulles de la composante,
      ``(date du jour, k)``, triées.
    - ``iterations`` — sans unité — celles de ``two_way_fit``, quand il a tourné.
    - ``residuals`` — log-secondes — ceux de ``two_way_fit``, quand il a tourné.
    - ``contraction`` — sans unité — ``μ₂`` de la composante.
    - ``contraction_unavailability`` — sans unité — ``non_convergence`` quand le calcul
      de ``μ₂`` n'est pas certifié.

    « Avec composante » : ``unavailability`` n'est ni ``insufficient_support`` ni
    ``unidentified_reference``.

    Invariants
    ----------
    - ``zero_cells`` et ``residuals`` (présent) sont des tuples ;
      ``unavailability`` absent ou dans ``FIT_UNAVAILABILITY`` ;
    - ``0 <= seen_count <= left_count`` ;
    - ``insufficient_support`` **si et seulement si** ``seen_count == 0`` ;
    - avec composante : ``training_days >= 1``, ``training_segments >= 1``,
      ``training_cells >= max(training_days, training_segments)`` ; sans composante :
      les trois effectifs nuls et ``zero_cells`` vide ;
    - ``zero_time`` **si et seulement si** ``zero_cells`` non vide ;
    - ``iterations`` et ``residuals`` présents **si et seulement si**
      ``unavailability`` est ``None``, ``non_convergence`` ou ``model_error`` ;
      ``iterations >= 1`` ;
    - ``contraction`` présente ⇒ avec composante, et dans ``[0 ; 1]`` ;
      ``contraction_unavailability`` absent ou ``non_convergence`` ; avec composante,
      **exactement un** de ``contraction`` et ``contraction_unavailability`` ; sans
      composante, ni l'un ni l'autre ;
    - ``training_days == 1`` ⇒ ``contraction`` absente ou ``0.0``.

    Producteur
    ----------
    ``repeatability_reference`` (``mountain_perf.backtest.repeatability``).

    Consommateurs
    -------------
    Le rapport D15 (M4b-5) ; les seuils d'admission (M4c).

    Non promis
    ----------
    ``μ₂`` est publié pour toute composante, motif ``temps nul`` compris (il ne dépend
    que du plan) ; il ne change aucun statut et ne mesure pas l'incertitude de ``F``.
    """

    regime_class: RegimeClass
    unavailability: Unavailability | None
    left_count: int
    seen_count: int
    training_days: int
    training_segments: int
    training_cells: int
    zero_cells: tuple[tuple[date, int], ...]
    iterations: int | None
    residuals: tuple[float, float, float, float] | None
    contraction: float | None
    contraction_unavailability: Unavailability | None

    def __post_init__(self) -> None:
        require_immutable_sequence(self.zero_cells, "zero_cells")
        if self.residuals is not None:
            require_immutable_sequence(self.residuals, "residuals")
        motif = self.unavailability
        if motif is not None and motif not in FIT_UNAVAILABILITY:
            raise ContractError(f"motif d'ajustement hors de la liste : {motif}.")
        if not 0 <= self.seen_count <= self.left_count:
            raise ContractError(
                f"0 <= seen_count ({self.seen_count}) <= left_count "
                f"({self.left_count}) attendu."
            )
        self._check_insufficient_support()
        self._check_component()
        self._check_zero_cells()
        self._check_iterations()
        self._check_contraction()

    def _has_component(self) -> bool:
        return self.unavailability not in _FAILED_WITHOUT_COMPONENT

    def _check_insufficient_support(self) -> None:
        insufficient = self.unavailability is Unavailability.INSUFFICIENT_SUPPORT
        if insufficient != (self.seen_count == 0):
            raise ContractError(
                "insufficient_support si et seulement si aucun segment du jour retiré "
                f"n'est vu (D8.2), reçu {self.unavailability} avec seen_count="
                f"{self.seen_count}."
            )

    def _check_component(self) -> None:
        days, segments, cells = (
            self.training_days,
            self.training_segments,
            self.training_cells,
        )
        if self._has_component():
            if days < 1 or segments < 1 or cells < max(days, segments):
                raise ContractError(
                    "une composante ajustée a au moins un jour, un segment et "
                    f"max(jours, segments) cellules, reçu {days} jours, {segments} "
                    f"segments, {cells} cellules."
                )
        elif (days, segments, cells) != (0, 0, 0) or self.zero_cells:
            raise ContractError(
                f"sans composante ({self.unavailability}), effectifs nuls et aucune "
                f"cellule nulle, reçu {days} jours, {segments} segments, {cells} "
                f"cellules, zero_cells={self.zero_cells}."
            )

    def _check_zero_cells(self) -> None:
        zero_time = self.unavailability is Unavailability.ZERO_TIME
        if zero_time != bool(self.zero_cells):
            raise ContractError(
                "zero_time si et seulement si des cellules nulles sont publiées "
                f"(D8.3), reçu {self.unavailability} avec zero_cells="
                f"{self.zero_cells}."
            )

    def _check_iterations(self) -> None:
        fitted = self.unavailability in _FITTED
        for name in ("iterations", "residuals"):
            present = getattr(self, name) is not None
            if present != fitted:
                raise ContractError(
                    f"{name} est présent si et seulement si two_way_fit a tourné "
                    f"(motif absent, non_convergence ou model_error), reçu "
                    f"{self.unavailability} avec {name}={getattr(self, name)}."
                )
        if self.iterations is not None and self.iterations < 1:
            raise ContractError(f"iterations doit être >= 1, reçu {self.iterations}.")

    def _check_contraction(self) -> None:
        contraction = self.contraction
        unavailable = self.contraction_unavailability
        if (
            unavailable is not None
            and unavailable is not Unavailability.NON_CONVERGENCE
        ):
            raise ContractError(
                "contraction_unavailability est absent ou non_convergence, reçu "
                f"{unavailable}."
            )
        if contraction is not None:
            require_in_range(contraction, 0.0, 1.0, "contraction")
        if self._has_component():
            if (contraction is None) == (unavailable is None):
                raise ContractError(
                    "avec composante, exactement un de contraction et "
                    f"contraction_unavailability, reçu {contraction} et {unavailable}."
                )
        elif contraction is not None or unavailable is not None:
            raise ContractError(
                f"sans composante ({self.unavailability}), ni contraction ni "
                f"contraction_unavailability, reçu {contraction} et {unavailable}."
            )
        if self.training_days == 1 and contraction not in (None, 0.0):
            raise ContractError(
                f"μ₂ vaut 0 pour un seul jour d'apprentissage, reçu {contraction}."
            )


@dataclass(frozen=True)
class ClassScore:
    """Les scores d'une classe pour le jour retiré (``0010`` D8.4, D5.5, D7.2, D7.5).

    Champs
    ------
    - ``regime_class`` — sans unité — la classe.
    - ``segment_count`` — sans unité — ``|S_jR|``.
    - ``log_ratio`` — sans unité — ``E_R`` du jour retiré, **signé**.
    - ``dispersion`` — sans unité — ``D_R`` du jour retiré.
    - ``contributes`` — sans unité — la valeur entre dans ``F``.

    Invariants
    ----------
    - ``segment_count >= 0`` ; ``log_ratio.count == dispersion.count ==
      segment_count`` ;
    - les deux valeurs présentes, ou les deux absentes avec le même motif ;
    - ``segment_count == 0`` ⇒ motif ``insufficient_support`` ;
    - ``dispersion`` présente : ``>= 0``, et ``== 0.0`` si ``segment_count == 1`` ;
    - ``contributes`` **si et seulement si** ``log_ratio`` présent et
      ``segment_count >= MIN_CONTRIBUTING_SEGMENTS``.

    Producteur
    ----------
    ``repeatability_reference`` (``mountain_perf.backtest.repeatability``).

    Consommateurs
    -------------
    Le rapport (M4b-5) ; les seuils d'admission (M4c).

    Non promis
    ----------
    Une valeur absente ne dit pas à elle seule si sa cause est le jour retiré (temps
    nul sur ``S_j``) ou l'ajustement : le ``ClassFit`` de même rang le dit ;
    ``contributes`` ne fait pas de la classe une cible ni un garde-fou de la
    performance (D7.5, D10.2).
    """

    regime_class: RegimeClass
    segment_count: int
    log_ratio: MetricValue
    dispersion: MetricValue
    contributes: bool

    def __post_init__(self) -> None:
        if self.segment_count < 0:
            raise ContractError(
                f"segment_count doit être >= 0, reçu {self.segment_count}."
            )
        for name in ("log_ratio", "dispersion"):
            value: MetricValue = getattr(self, name)
            if value.count != self.segment_count:
                raise ContractError(
                    f"{name}.count ({value.count}) doit valoir segment_count "
                    f"({self.segment_count})."
                )
        if self.log_ratio.unavailability != self.dispersion.unavailability:
            raise ContractError(
                "log_ratio et dispersion sont présents, ou absents avec le même "
                f"motif, reçu {self.log_ratio.unavailability} et "
                f"{self.dispersion.unavailability}."
            )
        motif = self.log_ratio.unavailability
        if self.segment_count == 0 and motif is not Unavailability.INSUFFICIENT_SUPPORT:
            raise ContractError(
                "une classe sans segment vu porte le motif insufficient_support, reçu "
                f"{motif}."
            )
        dispersion = self.dispersion.value
        if dispersion is not None:
            if dispersion < 0:
                raise ContractError(f"dispersion doit être >= 0, reçu {dispersion}.")
            if self.segment_count == 1 and dispersion != 0.0:
                raise ContractError(
                    "D_R vaut 0 exactement pour une classe d'un seul segment (D7.2), "
                    f"reçu {dispersion!r}."
                )
        self._check_contribution()

    def _check_contribution(self) -> None:
        expected = (
            self.log_ratio.available and self.segment_count >= MIN_CONTRIBUTING_SEGMENTS
        )
        if self.contributes != expected:
            raise ContractError(
                "contributes si et seulement si la valeur est présente et la classe a "
                f"au moins {MIN_CONTRIBUTING_SEGMENTS} segments (D7.5, précision de "
                f"D8.4), reçu contributes={self.contributes}, segment_count="
                f"{self.segment_count}, motif {self.log_ratio.unavailability}."
            )


@dataclass(frozen=True)
class FoldScores:
    """Un pli sous une horloge : ajustements, prévisions et scores du jour retiré
    (``0010`` D8.2 à D8.4, D5.5).

    Champs
    ------
    - ``day`` — date civile — le jour retiré.
    - ``support_count`` — sans unité — ``|S_j|``.
    - ``predicted_count`` — sans unité — ``|P_j|``.
    - ``fits`` — sans unité — les ajustements des quatre classes, dans l'ordre de
      ``RegimeClass``.
    - ``forecast_s`` — secondes — les ``(k, p_jk)`` sur ``P_j``.
    - ``level`` — sans unité — ``L`` du jour retiré, **signé**.
    - ``classes`` — sans unité — les scores des quatre classes, dans l'ordre de
      ``RegimeClass``.

    Invariants
    ----------
    - ``fits``, ``forecast_s``, ``classes`` sont des tuples ; clés de ``forecast_s``
      strictement croissantes, prévisions finies et ``> 0`` ;
    - ``len(forecast_s) == predicted_count`` ;
    - ``fits`` et ``classes`` : les quatre classes, dans l'ordre de ``RegimeClass`` ;
    - ``support_count == Σ seen_count`` des quatre ``fits`` ;
    - ``predicted_count == Σ seen_count`` des ``fits`` sans motif ;
    - ``classes[i].segment_count == fits[i].seen_count`` ;
      ``level.count == support_count`` ;
    - ``level`` présent ⇒ ``predicted_count == support_count`` (``|L|`` strict).

    Producteur
    ----------
    ``repeatability_reference`` (``mountain_perf.backtest.repeatability``).

    Consommateurs
    -------------
    Le rapport (M4b-5) ; les seuils d'admission (M4c).

    Non promis
    ----------
    ``level`` absent ne porte qu'un motif, le premier dans l'ordre de
    ``repeatability_reference`` (support vide, total nul, première classe en échec) :
    les autres causes sont dans ``fits`` ; ``forecast_s`` ne couvre que ``P_j``, sans
    prévision pour une classe en échec ; le contrat ne recalcule ni ``L`` ni les
    scores de classe.
    """

    day: date
    support_count: int
    predicted_count: int
    fits: tuple[ClassFit, ...]
    forecast_s: tuple[tuple[int, float], ...]
    level: MetricValue
    classes: tuple[ClassScore, ...]

    def __post_init__(self) -> None:
        for name in ("fits", "forecast_s", "classes"):
            require_immutable_sequence(getattr(self, name), name)
        for previous, current in pairwise(self.forecast_s):
            if not previous[0] < current[0]:
                raise ContractError(
                    "les clés de forecast_s sont strictement croissantes, reçu "
                    f"{previous[0]} puis {current[0]}."
                )
        self._check_forecast_values()
        self._check_forecast_count()
        for name in ("fits", "classes"):
            order = tuple(item.regime_class for item in getattr(self, name))
            if order != _CLASS_ORDER:
                raise ContractError(
                    f"{name} porte les quatre classes montée, plat, descente, mixte, "
                    f"dans cet ordre, reçu {[str(regime) for regime in order]}."
                )
        self._check_counts()
        for i, (fit, score) in enumerate(zip(self.fits, self.classes, strict=True)):
            if score.segment_count != fit.seen_count:
                raise ContractError(
                    f"classes[{i}].segment_count ({score.segment_count}) doit valoir "
                    f"fits[{i}].seen_count ({fit.seen_count})."
                )
        if self.level.count != self.support_count:
            raise ContractError(
                f"level.count ({self.level.count}) doit valoir support_count "
                f"({self.support_count})."
            )
        self._check_strict_level()

    def _check_forecast_values(self) -> None:
        for k, forecast_s in self.forecast_s:
            if not (math.isfinite(forecast_s) and forecast_s > 0):
                raise ContractError(
                    f"la prévision du segment {k} doit être finie et > 0 (erreur du "
                    f"modèle, D8.3), reçu {forecast_s}."
                )

    def _check_forecast_count(self) -> None:
        if len(self.forecast_s) != self.predicted_count:
            raise ContractError(
                f"forecast_s porte une prévision par segment prévu "
                f"({self.predicted_count}), reçu {len(self.forecast_s)}."
            )

    def _check_counts(self) -> None:
        support = sum(fit.seen_count for fit in self.fits)
        if self.support_count != support:
            raise ContractError(
                f"support_count ({self.support_count}) doit valoir la somme des "
                f"seen_count ({support})."
            )
        predicted = sum(
            fit.seen_count for fit in self.fits if fit.unavailability is None
        )
        if self.predicted_count != predicted:
            raise ContractError(
                f"predicted_count ({self.predicted_count}) doit valoir la somme des "
                f"seen_count des ajustements sans motif ({predicted})."
            )

    def _check_strict_level(self) -> None:
        if self.level.available and self.predicted_count != self.support_count:
            raise ContractError(
                "L présent exige P_j = S_j (|L| strict, décision 5 du brief M4b-3), "
                f"reçu {self.predicted_count} prévus sur {self.support_count}."
            )


@dataclass(frozen=True)
class ClockReference:
    """La référence sous une horloge : les plis et les ``F`` (``0010`` D8.4).

    Champs
    ------
    - ``clock`` — sans unité — l'horloge des temps.
    - ``folds`` — sans unité — les plis, dans l'ordre des jours.
    - ``level`` — sans unité — ``F_|L|``.
    - ``log_ratios`` — sans unité — les ``F_|E_R|`` des quatre classes, dans l'ordre de
      ``RegimeClass``.
    - ``dispersions`` — sans unité — les ``F_D_R`` des quatre classes, dans le même
      ordre.

    Invariants
    ----------
    - ``folds``, ``log_ratios``, ``dispersions`` sont des tuples ; quatre
      ``log_ratios``, quatre ``dispersions`` ;
    - chaque ``F`` (le niveau et les huit valeurs de classe) : absent ⇒ motif
      ``insufficient_support`` et effectif ``<= 1`` ; présent ⇒ effectif ``>= 2`` et
      valeur ``>= 0`` ;
    - ``level.count`` = le nombre de plis dont ``level`` est présent ;
    - ``log_ratios[i].count == dispersions[i].count`` = le nombre de plis où
      ``classes[i].contributes``.

    Producteur
    ----------
    ``repeatability_reference`` (``mountain_perf.backtest.repeatability``).

    Consommateurs
    -------------
    Le rapport (M4b-5) ; les seuils de D10.3 et D10.4 (M4c).

    Non promis
    ----------
    Un ``F`` absent ne dit pas pourquoi chaque jour manque : les causes sont dans les
    plis.
    """

    clock: Clock
    folds: tuple[FoldScores, ...]
    level: MetricValue
    log_ratios: tuple[MetricValue, ...]
    dispersions: tuple[MetricValue, ...]

    def __post_init__(self) -> None:
        for name in ("folds", "log_ratios", "dispersions"):
            require_immutable_sequence(getattr(self, name), name)
        for name in ("log_ratios", "dispersions"):
            values: tuple[MetricValue, ...] = getattr(self, name)
            if len(values) != len(RegimeClass):
                raise ContractError(
                    f"{name} porte une valeur par classe ({len(RegimeClass)}), reçu "
                    f"{len(values)}."
                )
        self._check_f_values()
        self._check_f_counts()

    def _check_f_values(self) -> None:
        for value in (self.level, *self.log_ratios, *self.dispersions):
            if value.value is None:
                if (
                    value.unavailability is not Unavailability.INSUFFICIENT_SUPPORT
                    or value.count > 1
                ):
                    raise ContractError(
                        "un F absent porte insufficient_support et un effectif <= 1 "
                        f"(D8.4), reçu {value.unavailability} d'effectif {value.count}."
                    )
            elif value.count < 2 or value.value < 0:
                raise ContractError(
                    "un F présent a un effectif >= 2 et une valeur >= 0 (D8.4), reçu "
                    f"{value.value} d'effectif {value.count}."
                )

    def _check_f_counts(self) -> None:
        levels = sum(fold.level.available for fold in self.folds)
        if self.level.count != levels:
            raise ContractError(
                f"level.count ({self.level.count}) doit valoir le nombre de plis où L "
                f"est présent ({levels})."
            )
        for i in range(len(RegimeClass)):
            contributing = sum(fold.classes[i].contributes for fold in self.folds)
            counts = (self.log_ratios[i].count, self.dispersions[i].count)
            if counts != (contributing, contributing):
                raise ContractError(
                    f"les effectifs des F de la classe {i} ({counts}) doivent valoir "
                    f"le nombre de plis où elle contribue ({contributing})."
                )


@dataclass(frozen=True)
class RepeatabilityReference:
    """La référence prédictive de répétabilité d'un parcours (``0010`` D8).

    Champs
    ------
    - ``reference`` — sans unité — la référence du parcours.
    - ``days`` — dates civiles — les jours éligibles, croissants.
    - ``multi_outing_days`` — dates civiles — les jours multi-sorties exclus,
      croissants.
    - ``single_contrast`` — sans unité — « un seul contraste » (précision de D8.4).
    - ``clocks`` — sans unité — la référence sous chaque horloge, dans l'ordre de
      ``CLOCKS``.

    Invariants
    ----------
    - ``days``, ``multi_outing_days`` et ``clocks`` sont des tuples ; ``days`` et
      ``multi_outing_days`` strictement croissants et disjoints ;
    - ``tuple(c.clock for c in clocks) == CLOCKS`` ;
    - pour chaque horloge, ``tuple(f.day for f in folds) == days`` ;
    - ``single_contrast`` ⇒ ``len(days) >= 2`` ;
    - pour chaque pli et chaque classe, ``fits[i].contraction`` est le même sous les
      onze horloges.

    Producteur
    ----------
    ``repeatability_reference`` (``mountain_perf.backtest.repeatability``).

    Consommateurs
    -------------
    Le rapport (M4b-5) ; les seuils d'admission (M4c).

    Non promis
    ----------
    Aucune valeur n'est agrégée sur plusieurs parcours ; le contrat ne recalcule ni
    ``F`` ni les plis.
    """

    reference: SourceRef
    days: tuple[date, ...]
    multi_outing_days: tuple[date, ...]
    single_contrast: bool
    clocks: tuple[ClockReference, ...]

    def __post_init__(self) -> None:
        for name in ("days", "multi_outing_days", "clocks"):
            require_immutable_sequence(getattr(self, name), name)
        _require_increasing_dates(self.days, "days")
        _require_increasing_dates(self.multi_outing_days, "multi_outing_days")
        common = set(self.days) & set(self.multi_outing_days)
        if common:
            raise ContractError(
                "days et multi_outing_days sont disjoints, reçu en commun "
                f"{sorted(common)}."
            )
        self._check_clock_order()
        self._check_fold_order()
        self._check_single_contrast()
        self._check_common_contraction()

    def _check_clock_order(self) -> None:
        if tuple(reference.clock for reference in self.clocks) != CLOCKS:
            raise ContractError(
                "clocks porte les onze horloges dans l'ordre de CLOCKS, reçu "
                f"{[reference.clock for reference in self.clocks]}."
            )

    def _check_fold_order(self) -> None:
        for reference in self.clocks:
            days = tuple(fold.day for fold in reference.folds)
            if days != self.days:
                raise ContractError(
                    f"les plis sous {reference.clock} sont les jours, dans l'ordre, "
                    f"reçu {days} pour {self.days}."
                )

    def _check_single_contrast(self) -> None:
        if self.single_contrast and len(self.days) < 2:
            raise ContractError(
                "« un seul contraste » exige au moins deux jours éligibles, reçu "
                f"{len(self.days)}."
            )

    def _check_common_contraction(self) -> None:
        for j, day in enumerate(self.days):
            for i in range(len(RegimeClass)):
                values = {
                    reference.folds[j].fits[i].contraction for reference in self.clocks
                }
                if len(values) > 1:
                    raise ContractError(
                        f"μ₂ du pli {day}, classe {i}, est le même sous les onze "
                        f"horloges (il ne dépend que du plan), reçu {values}."
                    )
