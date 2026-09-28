"""Contrats des métriques : valeurs, support, diagnostic, enveloppes, passages, cible
d'usage (M4b-1).

Protocole : ``docs/decisions/0010`` D5.4, D5.5, D7.1 à D7.5. Les métriques sont des
fonctions pures sur des vecteurs de nombres et de statuts
(``mountain_perf.backtest.metrics``) ; ces contrats portent leurs résultats. Le seuil
de D7.5 vit dans ``mountain_perf.backtest.metrics`` ; seules les tolérances, dont le
contrat a besoin, sont ici. L'assemblage sortie × scénario × horloge est le contrat de
M4b-2.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from mountain_perf.schemas.matching import RegimeClass
from mountain_perf.schemas.outing import Unavailability
from mountain_perf.validation import (
    ContractError,
    require_finite,
    require_immutable_sequence,
)

METRIC_RELATIVE_TOLERANCE = 1e-12
"""Tolérance relative ``τ`` de l'identité de ``0010`` D7.2 et de ``C_comp >= 0``
(brief M4b-1, § 3, choix 7).

Avec ``S = A + W + B + |C_comp|`` : ``|A − (W + B − C_comp)| <= τ·S`` et
``C_comp >= −τ·S`` ; même ``τ`` pour les invariances de D7.2. Mesuré en conception :
résidu au plus ``2,2e−16·S``, ``C_comp`` jusqu'à ``−7e−17·S``, sur des supports de 1 à
2 000 segments, ``t`` de ``1e−6`` à ``1e5`` s, ``|r|`` jusqu'à 30.
"""

WEIGHT_SUM_TOLERANCE = 1e-9
"""Tolérance de la somme des poids de ``K`` à 1 (``0010`` D7.4, ``Σ w_k = 1`` ; brief
M4b-1, § 3, choix 11).

Tolérance d'arrondi, pas règle de recevabilité : des poids calculés par programme
(fractions, renormalisations) somment à 1 à quelques ulps près, bien en deçà ; une
déclaration arrondie à la main (``(0.3333333, 0.3333333, 0.3333333)``, somme
``0.9999999``) est refusée plutôt que renormalisée en silence. Les poids déclarés
n'ont pas de producteur avant M4c ; la valeur se réexamine au brief qui les produira.
"""

_SUPPORT_MOTIFS = frozenset(
    {
        Unavailability.INSUFFICIENT_SUPPORT,
        Unavailability.ZERO_TIME,
        Unavailability.MODEL_ERROR,
    }
)
"""Les seuls motifs que produisent ``SupportMetrics`` et ``ClassMetrics``."""

_ENVELOPE_MOTIFS = frozenset({Unavailability.ZERO_TIME, Unavailability.MODEL_ERROR})


@dataclass(frozen=True)
class MetricValue:
    """Une valeur de métrique, ou son indisponibilité, avec son effectif (``0010`` D0,
    D7.5).

    Champs
    ------
    - ``value`` — unité de la métrique : sans unité pour les métriques logarithmiques
      et ``q_usage``, secondes pour ``C_k`` — la valeur.
    - ``unavailability`` — sans unité — le motif (``0010`` D0).
    - ``count`` — sans unité — l'effectif du support de la valeur, en segments ou en
      passages.

    Propriété calculée (jamais stockée) : ``available``.

    Invariants
    ----------
    - exactement un de ``value`` et ``unavailability`` est présent ;
    - ``value`` finie ;
    - ``count >= 0`` ;
    - ``value`` présente ⇒ ``count >= 1``.

    Producteur
    ----------
    Les fonctions de ``mountain_perf.backtest.metrics``.

    Consommateurs
    -------------
    Les contrats qui la portent (``ClassMetrics``, ``SupportMetrics``,
    ``PassageErrors``, ``UsageTarget``) et leurs consommateurs : l'assemblage (M4b-2),
    la référence D8 (M4b-3), le rapport (M4b-5), l'admission (M4c).

    Non promis
    ----------
    - le contrat ne dit pas de quel support il s'agit : c'est le contrat qui le porte ;
    - une valeur n'est jamais « zéro par défaut ».
    """

    value: float | None
    unavailability: Unavailability | None
    count: int

    def __post_init__(self) -> None:
        if (self.value is None) == (self.unavailability is None):
            raise ContractError(
                "exactement un de value et unavailability doit être présent, reçu "
                f"value={self.value}, unavailability={self.unavailability}."
            )
        if self.value is not None:
            require_finite(self.value, "value")
        if self.count < 0:
            raise ContractError(f"count doit être >= 0, reçu {self.count}.")
        if self.value is not None and self.count < 1:
            raise ContractError(
                f"une valeur présente a un effectif >= 1, reçu {self.count}."
            )

    @property
    def available(self) -> bool:
        """La valeur est présente (``value is not None``)."""
        return self.value is not None


def _motif(values: tuple[MetricValue, ...], names: str) -> Unavailability | None:
    """Le motif commun de ``values`` (``None`` : toutes présentes) ; refuse des motifs
    différents, ou un mélange de valeurs présentes et indisponibles."""
    motifs = {value.unavailability for value in values}
    if len(motifs) != 1:
        raise ContractError(
            f"{names} ont le même motif, ou sont toutes présentes, reçu "
            f"{[value.unavailability for value in values]}."
        )
    return next(iter(motifs))


@dataclass(frozen=True)
class ClassMetrics:
    """Les métriques d'une classe de régime sur le support (``0010`` D6, D7.2, D7.5).

    Champs
    ------
    - ``regime_class`` — sans unité — la classe.
    - ``segment_count`` — sans unité — ``n_R``, segments du support dans la classe.
    - ``underrepresented`` — sans unité — « trop peu représenté » (D7.5).
    - ``log_ratio`` — sans unité — ``E_R``.
    - ``dispersion`` — sans unité — ``D_R``.
    - ``shape`` — sans unité — ``E_R − L``, diagnostic de forme.

    Invariants
    ----------
    - ``segment_count >= 0`` ;
    - les trois valeurs ont ``count == segment_count``, le même motif, ou sont toutes
      trois présentes ;
    - motif parmi les motifs du support (``insufficient_support``, ``zero_time``,
      ``model_error``) ;
    - ``segment_count == 0`` ⇒ motif ``insufficient_support`` ;
    - ``underrepresented`` ⇒ ``segment_count >= 1`` ;
    - ``dispersion`` présente ⇒ ``dispersion.value >= 0`` ;
    - ``dispersion`` présente et ``segment_count == 1`` ⇒ ``dispersion.value == 0.0``
      **exactement** (D7.2).

    Producteur
    ----------
    ``support_metrics`` et ``positive_time_diagnostic``
    (``mountain_perf.backtest.metrics``).

    Consommateurs
    -------------
    ``SupportMetrics``, qui la porte, et ses consommateurs : l'assemblage (M4b-2), la
    référence D8 (M4b-3), le rapport (M4b-5), l'admission (M4c).

    Non promis
    ----------
    - le seuil de 3 n'est pas dans le contrat : le contrat ne vérifie pas que
      ``underrepresented`` correspond à l'effectif (tests du producteur) ;
    - ``E_R`` d'une classe « trop peu représentée » n'est ni une cible ni un garde-fou
      (D7.5) ;
    - mixte n'est jamais une cible (D6).
    """

    regime_class: RegimeClass
    segment_count: int
    underrepresented: bool
    log_ratio: MetricValue
    dispersion: MetricValue
    shape: MetricValue

    def __post_init__(self) -> None:
        if self.segment_count < 0:
            raise ContractError(
                f"segment_count doit être >= 0, reçu {self.segment_count}."
            )
        values = (self.log_ratio, self.dispersion, self.shape)
        for name, value in zip(
            ("log_ratio", "dispersion", "shape"), values, strict=True
        ):
            if value.count != self.segment_count:
                raise ContractError(
                    f"{name}.count ({value.count}) doit valoir segment_count "
                    f"({self.segment_count})."
                )
        motif = _motif(values, "log_ratio, dispersion et shape")
        if motif is not None and motif not in _SUPPORT_MOTIFS:
            raise ContractError(
                f"motif d'une classe hors des motifs du support : {motif}."
            )
        if self.segment_count == 0 and motif is not Unavailability.INSUFFICIENT_SUPPORT:
            raise ContractError(
                "une classe absente (segment_count == 0) porte le motif "
                f"insufficient_support, reçu {motif}."
            )
        if self.underrepresented and self.segment_count < 1:
            raise ContractError(
                "underrepresented exige segment_count >= 1 (une classe absente est "
                "« non évaluée »)."
            )
        dispersion = self.dispersion.value
        if dispersion is not None:
            if dispersion < 0:
                raise ContractError(f"dispersion doit être >= 0, reçu {dispersion}.")
            if self.segment_count == 1 and dispersion != 0.0:
                raise ContractError(
                    "D_R vaut 0 exactement pour une classe d'un seul segment "
                    f"(D7.2), reçu {dispersion!r}."
                )


_CLASS_ORDER = tuple(RegimeClass)


@dataclass(frozen=True)
class SupportMetrics:
    """Les métriques d'un support (``0010`` D7.1, D7.2, D5.5).

    Champs
    ------
    - ``segment_count`` — sans unité — ``n``, segments du support.
    - ``model_error`` — sans unité — sortie de modèle invalide sur le support (D7.1).
    - ``log_ratio`` — sans unité — ``L``.
    - ``dispersion`` — sans unité — ``A``.
    - ``within`` — sans unité — ``W``.
    - ``between`` — sans unité — ``B``.
    - ``compensation`` — sans unité — ``C_comp``.
    - ``classes`` — sans unité — les métriques de chaque classe de régime.

    Invariants
    ----------
    - ``classes`` est un tuple de quatre éléments, de ``regime_class`` montée, plat,
      descente, mixte, dans cet ordre ;
    - ``sum(segment_count des classes) == segment_count`` ;
    - ``log_ratio``, ``dispersion``, ``within``, ``between``, ``compensation`` ont
      ``count == segment_count`` ;
    - ``dispersion``, ``within``, ``between``, ``compensation`` ont le même motif, ou
      sont toutes présentes (« motif vectoriel ») ;
    - tous les motifs sont parmi les motifs du support (``insufficient_support``,
      ``zero_time``, ``model_error``) ;
    - ``segment_count == 0`` ⇐⇒ ``log_ratio`` et le motif vectoriel sont
      ``insufficient_support`` ; et alors ``model_error`` est faux ;
    - ``model_error`` ⇒ aucune valeur présente, ni du support ni des classes ;
    - non ``model_error`` ⇒ aucun motif ``model_error``, nulle part ;
    - ``log_ratio`` en ``zero_time`` ⇒ motif vectoriel ``zero_time`` ;
    - ``dispersion`` présente ⇒ ``log_ratio`` présente ;
    - pour chaque classe, son motif est ``insufficient_support`` si son effectif est
      nul, sinon le motif vectoriel ;
    - ``shape`` présente ⇒ ``shape.value == log_ratio.value (de la classe) −
      log_ratio.value (du support)`` exactement ;
    - valeurs vectorielles présentes : ``A``, ``W``, ``B`` ``>= 0`` ; avec
      ``S = A + W + B + |C_comp|`` : ``C_comp >= −τ·S`` et
      ``|A − (W + B − C_comp)| <= τ·S`` (``τ = METRIC_RELATIVE_TOLERANCE``).

    Producteur
    ----------
    ``support_metrics`` et ``positive_time_diagnostic``
    (``mountain_perf.backtest.metrics``).

    Consommateurs
    -------------
    L'assemblage (M4b-2), la référence D8 (M4b-3, scores du jour retiré), le rapport
    (M4b-5), l'admission (M4c).

    Non promis
    ----------
    - ni les ``r_i``, ni ``alpha_R``, ni les totaux ne sont publiés ;
    - l'identité ne sépare pas deux causes additives (D7.2) ;
    - le contrat ne connaît ni l'horloge, ni le scénario, ni le modèle : ils sont dans
      l'assemblage (M4b-2) ;
    - un ``SupportMetrics`` ne dit pas s'il porte le support principal ou le
      diagnostic : c'est ``PositiveTimeDiagnostic`` qui le dit ;
    - le résultat n'est pas promis hors du domaine du brief M4b-1 (§ 3, choix 12) :
      projections et temps observés positifs dans ``[1e−6 ; 1e12]`` ; au-delà, une
      valeur finie ``> 0`` peut faire sous-dépasser ou déborder un quotient ou une
      somme.
    """

    segment_count: int
    model_error: bool
    log_ratio: MetricValue
    dispersion: MetricValue
    within: MetricValue
    between: MetricValue
    compensation: MetricValue
    classes: tuple[ClassMetrics, ...]

    def __post_init__(self) -> None:
        self._check_classes()
        vector = self._check_counts_and_motifs()
        self._check_empty_and_flag(vector)
        self._check_class_motifs(vector)
        self._check_shapes()
        if vector is None:
            self._check_identity()

    def _vector(self) -> tuple[MetricValue, ...]:
        """``A``, ``W``, ``B``, ``C_comp`` : les valeurs du motif vectoriel."""
        return (self.dispersion, self.within, self.between, self.compensation)

    def _check_classes(self) -> None:
        require_immutable_sequence(self.classes, "classes")
        order = tuple(metrics.regime_class for metrics in self.classes)
        if order != _CLASS_ORDER:
            raise ContractError(
                "classes porte les quatre classes montée, plat, descente, mixte, dans "
                f"cet ordre, reçu {[str(regime) for regime in order]}."
            )
        total = sum(metrics.segment_count for metrics in self.classes)
        if total != self.segment_count:
            raise ContractError(
                f"la somme des segment_count des classes ({total}) doit valoir "
                f"segment_count ({self.segment_count})."
            )

    def _check_counts_and_motifs(self) -> Unavailability | None:
        names = ("log_ratio", "dispersion", "within", "between", "compensation")
        for name, value in zip(names, (self.log_ratio, *self._vector()), strict=True):
            if value.count != self.segment_count:
                raise ContractError(
                    f"{name}.count ({value.count}) doit valoir segment_count "
                    f"({self.segment_count})."
                )
        vector = _motif(self._vector(), "dispersion, within, between et compensation")
        for motif in (self.log_ratio.unavailability, vector):
            if motif is not None and motif not in _SUPPORT_MOTIFS:
                raise ContractError(f"motif hors des motifs du support : {motif}.")
        return vector

    def _check_empty_and_flag(self, vector: Unavailability | None) -> None:
        insufficient = Unavailability.INSUFFICIENT_SUPPORT
        empty = self.log_ratio.unavailability is insufficient and vector is insufficient
        if (self.segment_count == 0) != empty:
            raise ContractError(
                "segment_count == 0 si et seulement si log_ratio et le motif "
                "vectoriel sont insufficient_support, reçu "
                f"segment_count={self.segment_count}, "
                f"log_ratio={self.log_ratio.unavailability}, vectoriel={vector}."
            )
        if self.segment_count == 0 and self.model_error:
            raise ContractError("un support vide ne lève pas model_error.")
        values = (
            self.log_ratio,
            *self._vector(),
            *(
                value
                for metrics in self.classes
                for value in (metrics.log_ratio, metrics.dispersion, metrics.shape)
            ),
        )
        if self.model_error and any(value.available for value in values):
            raise ContractError(
                "model_error : aucune valeur présente, ni du support ni des classes."
            )
        if not self.model_error and any(
            value.unavailability is Unavailability.MODEL_ERROR for value in values
        ):
            raise ContractError("motif model_error sans le drapeau model_error.")
        if (
            self.log_ratio.unavailability is Unavailability.ZERO_TIME
            and vector is not Unavailability.ZERO_TIME
        ):
            raise ContractError(
                f"log_ratio en zero_time exige le motif vectoriel zero_time, reçu "
                f"{vector}."
            )
        if self.dispersion.available and not self.log_ratio.available:
            raise ContractError("dispersion présente exige log_ratio présente.")

    def _check_class_motifs(self, vector: Unavailability | None) -> None:
        for metrics in self.classes:
            expected = (
                Unavailability.INSUFFICIENT_SUPPORT
                if metrics.segment_count == 0
                else vector
            )
            if metrics.log_ratio.unavailability is not expected:
                raise ContractError(
                    f"la classe {metrics.regime_class} (effectif "
                    f"{metrics.segment_count}) porte le motif {expected}, reçu "
                    f"{metrics.log_ratio.unavailability}."
                )

    def _check_shapes(self) -> None:
        level = self.log_ratio.value
        for metrics in self.classes:
            shape, class_level = metrics.shape.value, metrics.log_ratio.value
            if shape is None:
                continue
            if level is None or class_level is None:
                raise ContractError(
                    f"shape de {metrics.regime_class} présente sans E_R ou sans L."
                )
            if shape != class_level - level:
                raise ContractError(
                    f"shape de {metrics.regime_class} ({shape!r}) doit valoir "
                    f"E_R − L ({class_level - level!r}) exactement."
                )

    def _check_identity(self) -> None:
        a, w, b, c = (value.value for value in self._vector())
        if a is None or w is None or b is None or c is None:
            raise ContractError("valeurs vectorielles présentes attendues.")
        for name, value in (("dispersion", a), ("within", w), ("between", b)):
            if value < 0:
                raise ContractError(f"{name} doit être >= 0, reçu {value}.")
        scale = math.fsum((a, w, b, abs(c)))
        bound = METRIC_RELATIVE_TOLERANCE * scale
        if c < -bound:
            raise ContractError(
                f"compensation doit être >= −τ·S ({-bound}), reçu {c} (D7.2)."
            )
        residual = math.fsum((a, -w, -b, c))
        if abs(residual) > bound:
            raise ContractError(
                f"A = W + B − C_comp doit tenir à τ·S ({bound}) près, écart {residual} "
                "(D7.2)."
            )


@dataclass(frozen=True)
class PositiveTimeDiagnostic:
    """Le diagnostic du sous-support à temps positifs (``0010`` D5.5).

    Champs
    ------
    - ``mask`` — sans unité — un booléen par segment du support principal, vrai si
      ``t_i > 0``.
    - ``metrics`` — sans unité — les métriques des segments de masque vrai.

    Invariants
    ----------
    - ``mask`` est un tuple de booléens ;
    - ``metrics.segment_count`` égale le nombre de vrais de ``mask`` ;
    - aucun motif ``zero_time`` dans ``metrics``.

    Producteur
    ----------
    ``positive_time_diagnostic`` (``mountain_perf.backtest.metrics``).

    Consommateurs
    -------------
    L'assemblage (M4b-2), le rapport (M4b-5).

    Non promis
    ----------
    - **ne remplace jamais le support principal**, ni pour une cible ni pour un
      garde-fou (D5.5) ;
    - le contrat ne vérifie pas le masque contre les temps (il ne les connaît pas).
    """

    mask: tuple[bool, ...]
    metrics: SupportMetrics

    def __post_init__(self) -> None:
        require_immutable_sequence(self.mask, "mask")
        for i, kept in enumerate(self.mask):
            if not isinstance(kept, bool):
                raise ContractError(
                    f"mask[{i}] doit être un booléen, reçu {type(kept).__name__}."
                )
        kept_count = sum(self.mask)
        if self.metrics.segment_count != kept_count:
            raise ContractError(
                f"metrics.segment_count ({self.metrics.segment_count}) doit valoir le "
                f"nombre de vrais de mask ({kept_count})."
            )
        metrics = self.metrics
        values = (
            metrics.log_ratio,
            metrics.dispersion,
            metrics.within,
            metrics.between,
            metrics.compensation,
            *(
                value
                for regime in metrics.classes
                for value in (regime.log_ratio, regime.dispersion, regime.shape)
            ),
        )
        if any(value.unavailability is Unavailability.ZERO_TIME for value in values):
            raise ContractError(
                "le sous-support à temps positifs ne porte aucun motif zero_time."
            )


@dataclass(frozen=True)
class LogRatioEnvelope:
    """L'intervalle de ``L`` pour un temps admissible dans ``[a ; b]`` (``0010`` D5.4).

    Champs
    ------
    - ``lower``, ``upper`` — sans unité — bornes de ``L``, ``ln(P/b)`` et ``ln(P/a)``.
    - ``min_abs`` — sans unité — ``min |L|`` sur l'intervalle.
    - ``unavailability`` — sans unité — le motif (``0010`` D0).

    Invariants
    ----------
    - motif absent ⇒ les trois valeurs présentes et finies ;
    - motif ``model_error`` ⇒ les trois absentes ;
    - motif ``zero_time`` ⇒ soit les trois absentes (``b = 0``), soit ``lower`` finie,
      ``upper == math.inf`` et ``min_abs`` finie (``a = 0 < b``) ;
    - aucun autre motif ;
    - valeurs présentes : ``lower <= upper``, ``min_abs >= 0``, et ``min_abs == 0`` si
      et seulement si ``lower <= 0 <= upper``.

    Producteur
    ----------
    ``log_ratio_envelope`` (``mountain_perf.backtest.metrics``).

    Consommateurs
    -------------
    M4b-2 (enveloppes de la performance et de chaque régime), le rapport (M4b-5).

    Non promis
    ----------
    - une enveloppe vaut **à ``P`` fixé** : elle ne borne pas les scores de modèles
      recalés différemment selon l'horloge (D5.4) ;
    - ``E_R`` et ``D_R`` aux horloges scénarios ne sont pas des bornes.
    """

    lower: float | None
    upper: float | None
    min_abs: float | None
    unavailability: Unavailability | None

    def __post_init__(self) -> None:
        motif = self.unavailability
        if motif is not None and motif not in _ENVELOPE_MOTIFS:
            raise ContractError(
                f"une enveloppe ne porte que zero_time ou model_error, reçu {motif}."
            )
        lower, upper, min_abs = self.lower, self.upper, self.min_abs
        present = [value is not None for value in (lower, upper, min_abs)]
        if not any(present):
            if motif is None:
                raise ContractError(
                    "une enveloppe sans motif a ses trois valeurs présentes."
                )
            return
        if lower is None or upper is None or min_abs is None:
            raise ContractError(
                "lower, upper et min_abs sont toutes présentes ou toutes absentes, "
                f"reçu {lower}, {upper}, {min_abs}."
            )
        if motif is Unavailability.MODEL_ERROR:
            raise ContractError("une enveloppe model_error n'a aucune valeur.")
        require_finite(lower, "lower")
        require_finite(min_abs, "min_abs")
        if motif is Unavailability.ZERO_TIME:
            if upper != math.inf:
                raise ContractError(
                    f"une enveloppe zero_time à valeurs a upper == inf, reçu {upper}."
                )
        else:
            require_finite(upper, "upper")
        if not lower <= upper:
            raise ContractError(f"lower ({lower}) doit être <= upper ({upper}).")
        if min_abs < 0:
            raise ContractError(f"min_abs doit être >= 0, reçu {min_abs}.")
        if (min_abs == 0) != (lower <= 0 <= upper):
            raise ContractError(
                "min_abs == 0 si et seulement si lower <= 0 <= upper, reçu "
                f"lower={lower}, upper={upper}, min_abs={min_abs}."
            )


@dataclass(frozen=True)
class PassageErrors:
    """Les erreurs aux passages (``0010`` D7.3).

    Champs
    ------
    - ``errors_s`` — secondes — ``C_k = P_k − T_k``, un par point donné, dans l'ordre
      donné.
    - ``model_error`` — sans unité — sortie de modèle invalide en l'un des points
      donnés.
    - ``max_abs_error_s``, ``max_error_s``, ``min_error_s`` — secondes —
      ``max |C_k|``, ``max C_k``, ``min C_k``.

    Invariants
    ----------
    - ``errors_s`` est un tuple ; chacun de ses éléments a ``count == 1`` ;
    - les trois agrégats ont le même motif et le même effectif, ou sont tous trois
      présents ;
    - leur effectif est le nombre d'erreurs présentes ou en ``model_error`` (points
      observés) ;
    - effectif nul ⇒ motif ``insufficient_support`` ;
    - effectif non nul : agrégats en ``model_error`` si et seulement si
      ``model_error`` ;
    - non ``model_error`` ⇒ aucune erreur en ``model_error`` ;
    - agrégats présents ⇒ égaux, exactement, à ``max(|c|)``, ``max(c)``, ``min(c)``
      sur les erreurs présentes ;
    - un ``C_k`` présent reste permis quand ``model_error`` est vrai (brief M4b-1,
      § 3, choix 7).

    Producteur
    ----------
    ``passage_errors`` (``mountain_perf.backtest.metrics``).

    Consommateurs
    -------------
    L'assemblage (M4b-2), le rapport (M4b-5).

    Non promis
    ----------
    - ni les abscisses, ni les noms des points : l'appelant tient l'ordre ;
    - l'ensemble des points (préfixe, origine exclue) est construit par l'appelant
      (M4b-2).
    """

    errors_s: tuple[MetricValue, ...]
    model_error: bool
    max_abs_error_s: MetricValue
    max_error_s: MetricValue
    min_error_s: MetricValue

    def __post_init__(self) -> None:
        require_immutable_sequence(self.errors_s, "errors_s")
        for k, error in enumerate(self.errors_s):
            if error.count != 1:
                raise ContractError(
                    f"errors_s[{k}].count doit valoir 1, reçu {error.count}."
                )
        aggregates = (self.max_abs_error_s, self.max_error_s, self.min_error_s)
        motif = _motif(aggregates, "max_abs_error_s, max_error_s et min_error_s")
        observed = sum(
            error.available or error.unavailability is Unavailability.MODEL_ERROR
            for error in self.errors_s
        )
        for name, aggregate in zip(
            ("max_abs_error_s", "max_error_s", "min_error_s"), aggregates, strict=True
        ):
            if aggregate.count != observed:
                raise ContractError(
                    f"{name}.count ({aggregate.count}) doit valoir le nombre de points "
                    f"observés ({observed})."
                )
        if observed == 0 and motif is not Unavailability.INSUFFICIENT_SUPPORT:
            raise ContractError(
                f"sans point observé, les agrégats sont insufficient_support, reçu "
                f"{motif}."
            )
        if observed > 0 and (motif is Unavailability.MODEL_ERROR) != self.model_error:
            raise ContractError(
                "avec des points observés, les agrégats sont model_error si et "
                f"seulement si model_error, reçu {motif} et {self.model_error}."
            )
        if not self.model_error and any(
            error.unavailability is Unavailability.MODEL_ERROR
            for error in self.errors_s
        ):
            raise ContractError("une erreur model_error exige le drapeau model_error.")
        if motif is None:
            self._check_aggregates()

    def _check_aggregates(self) -> None:
        present = [error.value for error in self.errors_s if error.value is not None]
        if not present:
            raise ContractError("agrégats présents sans aucune erreur présente.")
        expected = (
            ("max_abs_error_s", self.max_abs_error_s, max(abs(c) for c in present)),
            ("max_error_s", self.max_error_s, max(present)),
            ("min_error_s", self.min_error_s, min(present)),
        )
        for name, aggregate, wanted in expected:
            if aggregate.value != wanted:
                raise ContractError(
                    f"{name} ({aggregate.value}) doit valoir {wanted}, calculé sur les "
                    "erreurs présentes."
                )


@dataclass(frozen=True)
class TargetMember:
    """Un élément de l'ensemble ``K`` de la cible d'usage (``0010`` D7.4, D4.12).

    Champs
    ------
    - ``occurrence_index`` — sans unité — rang de l'occurrence dans la suite des rôles
      donnée à ``default_targets`` (celle de ``PassageMatchResult.passages``).
    - ``arrival`` — sans unité — l'élément est l'arrivée.

    Invariants
    ----------
    - ``occurrence_index`` absent ⇒ ``arrival`` ;
    - présent ⇒ ``>= 0``.

    Producteur
    ----------
    ``default_targets`` (``mountain_perf.backtest.metrics``).

    Consommateurs
    -------------
    M4b-2 (cumulés et statut de chaque élément), le rapport (M4b-5).

    Non promis
    ----------
    Un élément d'arrivée sans occurrence désigne l'arrivée de la grille de score
    (``b_K``).
    """

    occurrence_index: int | None
    arrival: bool

    def __post_init__(self) -> None:
        if self.occurrence_index is None:
            if not self.arrival:
                raise ContractError(
                    "un élément sans occurrence est l'arrivée de la grille : arrival "
                    "doit être vrai."
                )
        elif self.occurrence_index < 0:
            raise ContractError(
                f"occurrence_index doit être >= 0, reçu {self.occurrence_index}."
            )


@dataclass(frozen=True)
class UsageTarget:
    """La cible d'usage d'une performance (``0010`` D7.4).

    Champs
    ------
    - ``weights`` — sans unité — les ``w_k`` ; absents si les poids par défaut ne sont
      pas calculables.
    - ``q_usage`` — sans unité — la cible d'usage.
    - ``q_usage_prefix`` — sans unité — le diagnostic ``q_usage | préfixe``.
    - ``comparable`` — sans unité — un booléen par élément de ``K`` : passage
      comparable (garde-fou de D10.4).
    - ``model_error`` — sans unité — sortie de modèle invalide en l'un des éléments de
      ``K`` (``P_k`` ou ``P^(0)_k``).
    - ``arrival_anchor_gap_m`` — mètres — ``L − s'_K`` d'une arrivée ancrée.

    Propriétés calculées (jamais stockées) : ``target_count`` (``N``) et
    ``available_count`` (``n`` de « n passages sur N »).

    Invariants
    ----------
    - ``comparable`` est un tuple non vide ;
    - ``weights`` présents : tuple de longueur ``len(comparable)``, valeurs finies,
      ``>= 0``, de somme 1 à ``WEIGHT_SUM_TOLERANCE`` près ;
    - ``weights`` absents ⇒ ``model_error`` ;
    - ``q_usage.count == q_usage_prefix.count <= len(comparable)`` ;
    - ``q_usage`` présent ⇒ ``count == len(comparable)`` et ``value >= 0`` ;
    - ``q_usage_prefix`` présent ⇒ ``value >= 0`` ;
    - ``model_error`` ⇒ ``q_usage_prefix`` indisponible et ``q_usage`` indisponible ;
    - non ``model_error`` ⇒ aucun des deux n'a le motif ``model_error`` ;
    - le nombre de vrais de ``comparable`` est ``<= q_usage.count`` ;
    - ``arrival_anchor_gap_m`` présent ⇒ fini et ``>= 0``.

    Producteur
    ----------
    ``usage_target`` (``mountain_perf.backtest.metrics``).

    Consommateurs
    -------------
    L'assemblage (M4b-2), le rapport (M4b-5), l'admission (M4c).

    Non promis
    ----------
    - ``q_usage_prefix`` n'est **ni une cible ni un garde-fou** (D7.4) ;
    - le contrat ne connaît pas les éléments de ``K`` (l'appelant les tient) ;
    - il ne vérifie ni « départ exclu » ni « arrivée unique » (tests de
      ``default_targets``).
    """

    weights: tuple[float, ...] | None
    q_usage: MetricValue
    q_usage_prefix: MetricValue
    comparable: tuple[bool, ...]
    model_error: bool
    arrival_anchor_gap_m: float | None

    def __post_init__(self) -> None:
        require_immutable_sequence(self.comparable, "comparable")
        if not self.comparable:
            raise ContractError("comparable ne doit pas être vide : K est non vide.")
        self._check_weights()
        self._check_usage()
        gap_m = self.arrival_anchor_gap_m
        if gap_m is not None:
            require_finite(gap_m, "arrival_anchor_gap_m")
            if gap_m < 0:
                raise ContractError(
                    f"arrival_anchor_gap_m doit être >= 0, reçu {gap_m}."
                )

    @property
    def target_count(self) -> int:
        """``N``, nombre d'éléments de ``K`` (``len(comparable)``)."""
        return len(self.comparable)

    @property
    def available_count(self) -> int:
        """``n`` de « n passages sur N » : éléments disponibles (``q_usage.count``)."""
        return self.q_usage.count

    def _check_weights(self) -> None:
        weights = self.weights
        if weights is None:
            if not self.model_error:
                raise ContractError(
                    "weights absents : seuls des poids par défaut incalculables "
                    "(model_error) les rendent absents."
                )
            return
        require_immutable_sequence(weights, "weights")
        if len(weights) != len(self.comparable):
            raise ContractError(
                f"weights ({len(weights)}) et comparable ({len(self.comparable)}) "
                "ont la même longueur."
            )
        for k, weight in enumerate(weights):
            require_finite(weight, f"weights[{k}]")
            if weight < 0:
                raise ContractError(f"weights[{k}] doit être >= 0, reçu {weight}.")
        total = math.fsum(weights)
        if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
            raise ContractError(
                f"les poids somment à 1 à {WEIGHT_SUM_TOLERANCE} près, reçu {total}."
            )

    def _check_usage(self) -> None:
        usage, prefix = self.q_usage, self.q_usage_prefix
        target_count = len(self.comparable)
        if usage.count != prefix.count:
            raise ContractError(
                f"q_usage.count ({usage.count}) doit valoir q_usage_prefix.count "
                f"({prefix.count})."
            )
        if usage.count > target_count:
            raise ContractError(
                f"q_usage.count ({usage.count}) doit être <= len(comparable) "
                f"({target_count})."
            )
        if usage.value is not None:
            if usage.count != target_count:
                raise ContractError(
                    f"q_usage présent porte sur tout K : count ({usage.count}) doit "
                    f"valoir {target_count}."
                )
            if usage.value < 0:
                raise ContractError(f"q_usage doit être >= 0, reçu {usage.value}.")
        if prefix.value is not None and prefix.value < 0:
            raise ContractError(f"q_usage_prefix doit être >= 0, reçu {prefix.value}.")
        if self.model_error and (usage.available or prefix.available):
            raise ContractError(
                "model_error : q_usage et q_usage_prefix sont indisponibles."
            )
        if not self.model_error and Unavailability.MODEL_ERROR in (
            usage.unavailability,
            prefix.unavailability,
        ):
            raise ContractError("motif model_error sans le drapeau model_error.")
        comparable_count = sum(self.comparable)
        if comparable_count > usage.count:
            raise ContractError(
                f"{comparable_count} passages comparables pour {usage.count} éléments "
                "disponibles."
            )
