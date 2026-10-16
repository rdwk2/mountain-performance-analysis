"""Valeurs attendues de l'admission sur le monde de M4b-5 (M4c-3 ; ``0010`` D10.2 à
D10.6) : dix expériences de ``fixtures.effects`` sur ``fixtures.backtest_world``, et,
pour chacune, ce que publie son document d'admission.

Provenance. Les valeurs viennent de l'oracle indépendant de la conception de M4c-3
(``oracle_m4c3.py``, hors du dépôt), qui recalcule en mpmath à 50 chiffres, depuis la
préparation de l'expérience (observations, domaines, performances, courbe), sa
DÉCLARATION (exclusions d'admission, références figées, ``K`` déclarés) et les
prévisions **non calées** publiées : le calage de (0) et de (1), l'évaluation de chaque
performance, les agrégats, les garde-fous, le verdict et les réserves. Il n'importe ni
n'appelle le code de la règle (``admit``, ``assess_performances``, ``metric_value``,
``frozen_references``, ``reference_documents``, le calage, ``usage_target``,
``backtest/metrics.py``), et applique les arbitrages du coordinateur du 2026-10-14
(``q_usage`` au seuil fixe sans motif de la locale ; un échec calculable publié sous un
garde-fou indisponible ; le motif d'observation d'une métrique d'un modèle au calage en
échec ; le D+/km absent d'un jour de plusieurs sorties). Chaque nombre est recopié de sa
sortie (``valeurs_monde.json``), au double le plus proche de sa valeur à 50 chiffres ;
les réserves, de sa sortie texte. Aucune valeur n'est tirée du code testé. Les effectifs
des valeurs indisponibles, que l'oracle relève sans les vérifier, ne sont pas ici.

Tolérance. Énumérations, entiers et jours se comparent exactement ; les nombres à
``rel = 1e−9`` (``REL_TOLERANCE``), ``abs = 1e−12`` près de 0 (``ABS_TOLERANCE``) : un
dommage moyen de ``1e−52`` à 50 chiffres est un résidu d'arrondi de l'ordre de
``1e−16`` en double, sous ``abs``.

Aucune donnée réelle : le monde et les effets sont inventés.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from fixtures.effects import Broken, Descent, Identity, Scale
from mountain_perf.backtest import CandidateEffect
from mountain_perf.schemas import (
    CLOCKS,
    Clock,
    DeclaredUsageTarget,
    ExperimentMetric,
    TargetMember,
)
from mountain_perf.schemas.admission import (
    AdmissionReserve,
    AdmissionVerdict,
    FailedCheck,
    FailedCondition,
    GuardStatus,
    ReviewCause,
    ReviewReason,
    ThresholdSource,
)

REL_TOLERANCE = 1e-9
"""La tolérance relative des nombres."""
ABS_TOLERANCE = 1e-12
"""La tolérance absolue des nombres, près de 0."""

ELAPSED = CLOCKS[0]
"""L'écoulé."""
MOVING_2 = CLOCKS[3]
"""Le temps en mouvement de la convention 2 (``moving_2``)."""

J14, J25, J27 = date(2026, 6, 14), date(2026, 6, 25), date(2026, 6, 27)
"""Les jours évaluables du monde."""

K_PREFIX = DeclaredUsageTarget("a", (TargetMember(0, False),), (1.0,))
"""Un ``K`` du parcours ``a`` en préfixe : son premier lieu nommé seul, sans l'arrivée
(décision E4 : l'arrivée est optionnelle)."""

ADMISSION_EXCLUSION = "exclusion synthétique"
"""Le motif des exclusions d'admission des expériences, avant son préfixe."""


@dataclass(frozen=True)
class Experiment:
    """Une expérience du monde : l'effet, la cible et son horloge, les sorties exclues
    de l'admission (motif ``ADMISSION_EXCLUSION``), et ``K`` (cible ``q_usage``)."""

    effect: CandidateEffect
    target: ExperimentMetric
    clock: Clock
    exclusions: tuple[str, ...] = ()
    usage_targets: tuple[DeclaredUsageTarget, ...] = ()


@dataclass(frozen=True)
class DayValues:
    """Une performance évaluable : ``G_j``, ``δ_j``, la source de ``F_j``, et l'effort
    libre ``exp(−β)`` de (0) et de (1) sous l'horloge déclarée — absent : pas calé."""

    gain: float | None
    threshold: float
    source: ThresholdSource
    base_effort: float | None
    candidate_effort: float | None


@dataclass(frozen=True)
class GuardValues:
    """Un garde-fou de métrique : son état, ``H̄`` (absent : une valeur manque) et
    ``η̄``."""

    status: GuardStatus
    mean_harm: float | None
    mean_threshold: float | None


@dataclass(frozen=True)
class AdmissionValues:
    """Ce que publie le document d'admission : ``n``, le verdict, ``Ḡ``, ``δ̄``, les
    succès, les succès exigés, la moyenne des gains contre v0 brut, chaque performance
    évaluable, les causes de « à revoir », les conditions qui échouent, les garde-fous,
    l'état du garde-fou des passages, et les réserves."""

    evaluable: int
    verdict: AdmissionVerdict
    mean_gain: float | None
    mean_threshold: float
    positive: int
    required: int
    mean_raw_gain: float | None
    days: Mapping[date, DayValues]
    review: tuple[ReviewReason, ...]
    failures: tuple[FailedCheck, ...]
    guards: Mapping[ExperimentMetric, GuardValues]
    passages: GuardStatus
    reserves: tuple[AdmissionReserve, ...]


EXPERIMENTS: Mapping[str, Experiment] = {
    "Identity/descent_level/elapsed": Experiment(
        Identity(), ExperimentMetric.DESCENT_LEVEL, ELAPSED
    ),
    "Descent/descent_level/elapsed": Experiment(
        Descent(), ExperimentMetric.DESCENT_LEVEL, ELAPSED
    ),
    "Descent/usage/elapsed": Experiment(Descent(), ExperimentMetric.USAGE, ELAPSED),
    "Descent/usage/elapsed/K_prefixe": Experiment(
        Descent(), ExperimentMetric.USAGE, ELAPSED, usage_targets=(K_PREFIX,)
    ),
    "Descent/descent_level/elapsed/exclusion": Experiment(
        Descent(),
        ExperimentMetric.DESCENT_LEVEL,
        ELAPSED,
        exclusions=("b-2026-06-25",),
    ),
    "Descent/descent_level/elapsed/exclusion_membre": Experiment(
        Descent(),
        ExperimentMetric.DESCENT_LEVEL,
        ELAPSED,
        exclusions=("a-2026-06-10",),
    ),
    "Descent/usage/moving_2": Experiment(Descent(), ExperimentMetric.USAGE, MOVING_2),
    "Broken/descent_level/elapsed": Experiment(
        Broken(), ExperimentMetric.DESCENT_LEVEL, ELAPSED
    ),
    "Broken/usage/moving_2": Experiment(Broken(), ExperimentMetric.USAGE, MOVING_2),
    "Scale(0.4)/descent_level/elapsed/sature": Experiment(
        Scale(0.4), ExperimentMetric.DESCENT_LEVEL, ELAPSED
    ),
}
"""Les expériences, nommées comme dans la sortie de l'oracle : effet, cible, horloge,
puis la variante — ``K_prefixe`` (``K_PREFIX``), ``exclusion`` (une sortie
évaluable), ``exclusion_membre`` (un jour de répétabilité, membre du calage des jours
suivants), ``sature`` (l'effort de (1) hors de ``EFFORT_BOUNDS``).
``Descent/usage/moving_2`` publie l'échec d'un garde-fou indisponible
(``ascent_level``, le 25 juin) ; ``Broken/usage/moving_2``, des métriques du candidat,
au calage en erreur, au motif de l'observation (temps nul)."""

ORACLE: Mapping[str, AdmissionValues] = {
    "Identity/descent_level/elapsed": AdmissionValues(
        evaluable=3,
        verdict=AdmissionVerdict.REJECTED,
        mean_gain=0.0,
        mean_threshold=0.026502403822383624,
        positive=0,
        required=3,
        mean_raw_gain=0.01267621667909191,
        days={
            J14: DayValues(
                0.0,
                0.034753605733575436,
                ThresholdSource.LOCAL,
                0.9944081039918902,
                0.9944081039918902,
            ),
            J25: DayValues(
                0.0,
                0.01,
                ThresholdSource.LOCAL,
                1.022057875282595,
                1.022057875282595,
            ),
            J27: DayValues(
                0.0,
                0.034753605733575436,
                ThresholdSource.LOCAL,
                1.022057875282595,
                1.022057875282595,
            ),
        },
        review=(),
        failures=(
            FailedCheck(FailedCondition.MEAN_GAIN, None, ()),
            FailedCheck(FailedCondition.VOTE, None, ()),
        ),
        guards={
            ExperimentMetric.LEVEL: GuardValues(
                GuardStatus.SATISFIED, 0.0, 0.006366785649738754
            ),
            ExperimentMetric.ASCENT_LEVEL: GuardValues(
                GuardStatus.SATISFIED, 0.0, 0.005
            ),
            ExperimentMetric.FLAT_LEVEL: GuardValues(GuardStatus.SATISFIED, 0.0, 0.005),
            ExperimentMetric.ASCENT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 0.0, 0.005
            ),
            ExperimentMetric.FLAT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 0.0, 0.005
            ),
            ExperimentMetric.DESCENT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 0.0, 0.013994583331636662
            ),
        },
        passages=GuardStatus.SATISFIED,
        reserves=(AdmissionReserve.SENSITIVITY_REMAINING,),
    ),
    "Descent/descent_level/elapsed": AdmissionValues(
        evaluable=3,
        verdict=AdmissionVerdict.REJECTED,
        mean_gain=0.011191165071411834,
        mean_threshold=0.026502403822383624,
        positive=2,
        required=3,
        mean_raw_gain=0.023867381750503742,
        days={
            J14: DayValues(
                0.06892458433961701,
                0.034753605733575436,
                ThresholdSource.LOCAL,
                0.9944081039918902,
                0.9588280509813139,
            ),
            J25: DayValues(
                0.007822962000202143,
                0.01,
                ThresholdSource.LOCAL,
                1.022057875282595,
                0.9869859616639189,
            ),
            J27: DayValues(
                -0.04317405112558366,
                0.034753605733575436,
                ThresholdSource.LOCAL,
                1.022057875282595,
                0.9869859616639189,
            ),
        },
        review=(),
        failures=(
            FailedCheck(FailedCondition.MEAN_GAIN, None, ()),
            FailedCheck(FailedCondition.VOTE, None, ()),
            FailedCheck(FailedCondition.LOSS, None, (J27,)),
            FailedCheck(
                FailedCondition.GUARD, ExperimentMetric.ASCENT_LEVEL, (J14, J25, J27)
            ),
            FailedCheck(FailedCondition.GUARD, ExperimentMetric.FLAT_LEVEL, (J25,)),
            FailedCheck(FailedCondition.PASSAGES, None, (J14, J27)),
        ),
        guards={
            ExperimentMetric.LEVEL: GuardValues(
                GuardStatus.SATISFIED, 0.00029661521574523826, 0.006366785649738754
            ),
            ExperimentMetric.ASCENT_LEVEL: GuardValues(
                GuardStatus.VIOLATED, 0.035423698773493544, 0.005
            ),
            ExperimentMetric.FLAT_LEVEL: GuardValues(
                GuardStatus.VIOLATED, 0.03491758250113529, 0.005
            ),
            ExperimentMetric.ASCENT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 1.681973250066583e-16, 0.005
            ),
            ExperimentMetric.FLAT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 0.0, 0.005
            ),
            ExperimentMetric.DESCENT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 2.784129906346037e-53, 0.013994583331636662
            ),
        },
        passages=GuardStatus.VIOLATED,
        reserves=(AdmissionReserve.SENSITIVITY_REMAINING,),
    ),
    "Descent/usage/elapsed": AdmissionValues(
        evaluable=3,
        verdict=AdmissionVerdict.REJECTED,
        mean_gain=-0.003567299246426236,
        mean_threshold=0.01,
        positive=0,
        required=3,
        mean_raw_gain=0.009273985605933777,
        days={
            J14: DayValues(
                -0.00566872667203893,
                0.01,
                ThresholdSource.FIXED,
                0.9944081039918902,
                0.9588280509813139,
            ),
            J25: DayValues(
                -0.0008902416773335086,
                0.01,
                ThresholdSource.FIXED,
                1.022057875282595,
                0.9869859616639189,
            ),
            J27: DayValues(
                -0.004142929389906269,
                0.01,
                ThresholdSource.FIXED,
                1.022057875282595,
                0.9869859616639189,
            ),
        },
        review=(),
        failures=(
            FailedCheck(FailedCondition.MEAN_GAIN, None, ()),
            FailedCheck(FailedCondition.VOTE, None, ()),
            FailedCheck(
                FailedCondition.GUARD, ExperimentMetric.ASCENT_LEVEL, (J14, J25, J27)
            ),
            FailedCheck(FailedCondition.GUARD, ExperimentMetric.FLAT_LEVEL, (J25,)),
            FailedCheck(FailedCondition.GUARD, ExperimentMetric.DESCENT_LEVEL, (J27,)),
            FailedCheck(FailedCondition.PASSAGES, None, (J14, J27)),
        ),
        guards={
            ExperimentMetric.LEVEL: GuardValues(
                GuardStatus.SATISFIED, 0.00029661521574523826, 0.006366785649738754
            ),
            ExperimentMetric.ASCENT_LEVEL: GuardValues(
                GuardStatus.VIOLATED, 0.035423698773493544, 0.005
            ),
            ExperimentMetric.FLAT_LEVEL: GuardValues(
                GuardStatus.VIOLATED, 0.03491758250113529, 0.005
            ),
            ExperimentMetric.DESCENT_LEVEL: GuardValues(
                GuardStatus.VIOLATED, 0.014391350375194553, 0.010934294862286783
            ),
            ExperimentMetric.ASCENT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 1.681973250066583e-16, 0.005
            ),
            ExperimentMetric.FLAT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 0.0, 0.005
            ),
            ExperimentMetric.DESCENT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 2.784129906346037e-53, 0.013994583331636662
            ),
        },
        passages=GuardStatus.VIOLATED,
        reserves=(AdmissionReserve.SENSITIVITY_REMAINING,),
    ),
    "Descent/usage/elapsed/K_prefixe": AdmissionValues(
        evaluable=3,
        verdict=AdmissionVerdict.REJECTED,
        mean_gain=-0.02451081885464567,
        mean_threshold=0.01,
        positive=0,
        required=3,
        mean_raw_gain=-0.011669534002285658,
        days={
            J14: DayValues(
                -0.03710785575595308,
                0.01,
                ThresholdSource.FIXED,
                0.9944081039918902,
                0.9588280509813139,
            ),
            J25: DayValues(
                -0.0008902416773335086,
                0.01,
                ThresholdSource.FIXED,
                1.022057875282595,
                0.9869859616639189,
            ),
            J27: DayValues(
                -0.03553435913065043,
                0.01,
                ThresholdSource.FIXED,
                1.022057875282595,
                0.9869859616639189,
            ),
        },
        review=(),
        failures=(
            FailedCheck(FailedCondition.MEAN_GAIN, None, ()),
            FailedCheck(FailedCondition.VOTE, None, ()),
            FailedCheck(FailedCondition.LOSS, None, (J14, J27)),
            FailedCheck(
                FailedCondition.GUARD, ExperimentMetric.ASCENT_LEVEL, (J14, J25, J27)
            ),
            FailedCheck(FailedCondition.GUARD, ExperimentMetric.FLAT_LEVEL, (J25,)),
            FailedCheck(FailedCondition.GUARD, ExperimentMetric.DESCENT_LEVEL, (J27,)),
            FailedCheck(FailedCondition.PASSAGES, None, (J14, J27)),
        ),
        guards={
            ExperimentMetric.LEVEL: GuardValues(
                GuardStatus.SATISFIED, 0.00029661521574523826, 0.006366785649738754
            ),
            ExperimentMetric.ASCENT_LEVEL: GuardValues(
                GuardStatus.VIOLATED, 0.035423698773493544, 0.005
            ),
            ExperimentMetric.FLAT_LEVEL: GuardValues(
                GuardStatus.VIOLATED, 0.03491758250113529, 0.005
            ),
            ExperimentMetric.DESCENT_LEVEL: GuardValues(
                GuardStatus.VIOLATED, 0.014391350375194553, 0.010934294862286783
            ),
            ExperimentMetric.ASCENT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 1.681973250066583e-16, 0.005
            ),
            ExperimentMetric.FLAT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 0.0, 0.005
            ),
            ExperimentMetric.DESCENT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 2.784129906346037e-53, 0.013994583331636662
            ),
        },
        passages=GuardStatus.VIOLATED,
        reserves=(AdmissionReserve.SENSITIVITY_REMAINING,),
    ),
    "Descent/descent_level/elapsed/exclusion": AdmissionValues(
        evaluable=2,
        verdict=AdmissionVerdict.REJECTED,
        mean_gain=0.01287526660701668,
        mean_threshold=0.034753605733575436,
        positive=1,
        required=2,
        mean_raw_gain=0.020980531819078947,
        days={
            J14: DayValues(
                0.06892458433961701,
                0.034753605733575436,
                ThresholdSource.LOCAL,
                0.9944081039918902,
                0.9588280509813139,
            ),
            J27: DayValues(
                -0.04317405112558366,
                0.034753605733575436,
                ThresholdSource.LOCAL,
                1.022057875282595,
                0.9869859616639189,
            ),
        },
        review=(),
        failures=(
            FailedCheck(FailedCondition.MEAN_GAIN, None, ()),
            FailedCheck(FailedCondition.VOTE, None, ()),
            FailedCheck(FailedCondition.LOSS, None, (J27,)),
            FailedCheck(
                FailedCondition.GUARD, ExperimentMetric.ASCENT_LEVEL, (J14, J27)
            ),
            FailedCheck(FailedCondition.PASSAGES, None, (J14, J27)),
        ),
        guards={
            ExperimentMetric.LEVEL: GuardValues(
                GuardStatus.SATISFIED, 0.0, 0.00705017847460813
            ),
            ExperimentMetric.ASCENT_LEVEL: GuardValues(
                GuardStatus.VIOLATED, 0.035676756909672674, 0.005
            ),
            ExperimentMetric.FLAT_LEVEL: GuardValues(
                GuardStatus.NOT_EVALUABLE, None, None
            ),
            ExperimentMetric.ASCENT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 2.522959875099875e-16, 0.005
            ),
            ExperimentMetric.FLAT_DISPERSION: GuardValues(
                GuardStatus.NOT_EVALUABLE, None, None
            ),
            ExperimentMetric.DESCENT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 4.176194859519056e-53, 0.018491874997454992
            ),
        },
        passages=GuardStatus.VIOLATED,
        reserves=(AdmissionReserve.SENSITIVITY_REMAINING,),
    ),
    "Descent/descent_level/elapsed/exclusion_membre": AdmissionValues(
        evaluable=3,
        verdict=AdmissionVerdict.REJECTED,
        mean_gain=0.011191165071411834,
        mean_threshold=0.026502403822383624,
        positive=2,
        required=3,
        mean_raw_gain=0.023867381750503742,
        days={
            J14: DayValues(
                0.06892458433961701,
                0.034753605733575436,
                ThresholdSource.LOCAL,
                0.9944081039918902,
                0.9588280509813139,
            ),
            J25: DayValues(
                0.007822962000202143,
                0.01,
                ThresholdSource.LOCAL,
                1.022057875282595,
                0.9869859616639189,
            ),
            J27: DayValues(
                -0.04317405112558366,
                0.034753605733575436,
                ThresholdSource.LOCAL,
                1.022057875282595,
                0.9869859616639189,
            ),
        },
        review=(),
        failures=(
            FailedCheck(FailedCondition.MEAN_GAIN, None, ()),
            FailedCheck(FailedCondition.VOTE, None, ()),
            FailedCheck(FailedCondition.LOSS, None, (J27,)),
            FailedCheck(
                FailedCondition.GUARD, ExperimentMetric.ASCENT_LEVEL, (J14, J25, J27)
            ),
            FailedCheck(FailedCondition.GUARD, ExperimentMetric.FLAT_LEVEL, (J25,)),
            FailedCheck(FailedCondition.PASSAGES, None, (J14, J27)),
        ),
        guards={
            ExperimentMetric.LEVEL: GuardValues(
                GuardStatus.SATISFIED, 0.00029661521574523826, 0.006366785649738754
            ),
            ExperimentMetric.ASCENT_LEVEL: GuardValues(
                GuardStatus.VIOLATED, 0.035423698773493544, 0.005
            ),
            ExperimentMetric.FLAT_LEVEL: GuardValues(
                GuardStatus.VIOLATED, 0.03491758250113529, 0.005
            ),
            ExperimentMetric.ASCENT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 1.681973250066583e-16, 0.005
            ),
            ExperimentMetric.FLAT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 0.0, 0.005
            ),
            ExperimentMetric.DESCENT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 2.784129906346037e-53, 0.013994583331636662
            ),
        },
        passages=GuardStatus.VIOLATED,
        reserves=(AdmissionReserve.SENSITIVITY_REMAINING,),
    ),
    "Descent/usage/moving_2": AdmissionValues(
        evaluable=3,
        verdict=AdmissionVerdict.TO_REVIEW,
        mean_gain=-0.003567299246426236,
        mean_threshold=0.01,
        positive=0,
        required=3,
        mean_raw_gain=0.043656558077147925,
        days={
            J14: DayValues(
                -0.00566872667203893,
                0.01,
                ThresholdSource.FIXED,
                1.0321893277199572,
                0.9952574575453285,
            ),
            J25: DayValues(
                -0.0008902416773335086,
                0.01,
                ThresholdSource.FIXED,
                1.0547411221253826,
                1.0185476829671365,
            ),
            J27: DayValues(
                -0.004142929389906269,
                0.01,
                ThresholdSource.FIXED,
                1.0547411221253826,
                1.0185476829671365,
            ),
        },
        review=(
            ReviewReason(
                ReviewCause.GUARD_UNAVAILABLE, ExperimentMetric.ASCENT_LEVEL, (J14, J27)
            ),
            ReviewReason(
                ReviewCause.GUARD_UNAVAILABLE,
                ExperimentMetric.DESCENT_LEVEL,
                (J14, J27),
            ),
            ReviewReason(
                ReviewCause.GUARD_UNAVAILABLE,
                ExperimentMetric.ASCENT_DISPERSION,
                (J14, J27),
            ),
            ReviewReason(
                ReviewCause.GUARD_UNAVAILABLE,
                ExperimentMetric.DESCENT_DISPERSION,
                (J14, J27),
            ),
        ),
        failures=(
            FailedCheck(FailedCondition.MEAN_GAIN, None, ()),
            FailedCheck(FailedCondition.VOTE, None, ()),
            FailedCheck(FailedCondition.GUARD, ExperimentMetric.ASCENT_LEVEL, (J25,)),
            FailedCheck(FailedCondition.GUARD, ExperimentMetric.FLAT_LEVEL, (J25,)),
            FailedCheck(FailedCondition.PASSAGES, None, (J14, J27)),
        ),
        guards={
            ExperimentMetric.LEVEL: GuardValues(
                GuardStatus.SATISFIED, 0.00029661521574523826, 0.005
            ),
            ExperimentMetric.ASCENT_LEVEL: GuardValues(
                GuardStatus.UNAVAILABLE, None, 0.005
            ),
            ExperimentMetric.FLAT_LEVEL: GuardValues(
                GuardStatus.VIOLATED, 0.03491758250113529, 0.005
            ),
            ExperimentMetric.DESCENT_LEVEL: GuardValues(
                GuardStatus.UNAVAILABLE, None, 0.005
            ),
            ExperimentMetric.ASCENT_DISPERSION: GuardValues(
                GuardStatus.UNAVAILABLE, None, 0.005
            ),
            ExperimentMetric.FLAT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 3.1321461446392918e-52, 0.005
            ),
            ExperimentMetric.DESCENT_DISPERSION: GuardValues(
                GuardStatus.UNAVAILABLE, None, 0.005
            ),
        },
        passages=GuardStatus.VIOLATED,
        reserves=(AdmissionReserve.SENSITIVITY_REMAINING,),
    ),
    "Broken/descent_level/elapsed": AdmissionValues(
        evaluable=3,
        verdict=AdmissionVerdict.TO_REVIEW,
        mean_gain=None,
        mean_threshold=0.026502403822383624,
        positive=0,
        required=3,
        mean_raw_gain=None,
        days={
            J14: DayValues(
                None,
                0.034753605733575436,
                ThresholdSource.LOCAL,
                0.9944081039918902,
                None,
            ),
            J25: DayValues(
                None,
                0.01,
                ThresholdSource.LOCAL,
                1.022057875282595,
                None,
            ),
            J27: DayValues(
                None,
                0.034753605733575436,
                ThresholdSource.LOCAL,
                1.022057875282595,
                None,
            ),
        },
        review=(
            ReviewReason(ReviewCause.TARGET_UNAVAILABLE, None, (J14, J25, J27)),
            ReviewReason(
                ReviewCause.GUARD_UNAVAILABLE, ExperimentMetric.LEVEL, (J14, J25, J27)
            ),
            ReviewReason(
                ReviewCause.GUARD_UNAVAILABLE,
                ExperimentMetric.ASCENT_LEVEL,
                (J14, J25, J27),
            ),
            ReviewReason(
                ReviewCause.GUARD_UNAVAILABLE, ExperimentMetric.FLAT_LEVEL, (J25,)
            ),
            ReviewReason(
                ReviewCause.GUARD_UNAVAILABLE,
                ExperimentMetric.ASCENT_DISPERSION,
                (J14, J25, J27),
            ),
            ReviewReason(
                ReviewCause.GUARD_UNAVAILABLE, ExperimentMetric.FLAT_DISPERSION, (J25,)
            ),
            ReviewReason(
                ReviewCause.GUARD_UNAVAILABLE,
                ExperimentMetric.DESCENT_DISPERSION,
                (J14, J25, J27),
            ),
            ReviewReason(ReviewCause.PASSAGES_UNAVAILABLE, None, (J14, J25, J27)),
        ),
        failures=(),
        guards={
            ExperimentMetric.LEVEL: GuardValues(
                GuardStatus.UNAVAILABLE, None, 0.006366785649738754
            ),
            ExperimentMetric.ASCENT_LEVEL: GuardValues(
                GuardStatus.UNAVAILABLE, None, 0.005
            ),
            ExperimentMetric.FLAT_LEVEL: GuardValues(
                GuardStatus.UNAVAILABLE, None, 0.005
            ),
            ExperimentMetric.ASCENT_DISPERSION: GuardValues(
                GuardStatus.UNAVAILABLE, None, 0.005
            ),
            ExperimentMetric.FLAT_DISPERSION: GuardValues(
                GuardStatus.UNAVAILABLE, None, 0.005
            ),
            ExperimentMetric.DESCENT_DISPERSION: GuardValues(
                GuardStatus.UNAVAILABLE, None, 0.013994583331636662
            ),
        },
        passages=GuardStatus.UNAVAILABLE,
        reserves=(AdmissionReserve.SENSITIVITY_REMAINING,),
    ),
    "Broken/usage/moving_2": AdmissionValues(
        evaluable=3,
        verdict=AdmissionVerdict.TO_REVIEW,
        mean_gain=None,
        mean_threshold=0.01,
        positive=0,
        required=3,
        mean_raw_gain=None,
        days={
            J14: DayValues(
                None,
                0.01,
                ThresholdSource.FIXED,
                1.0321893277199572,
                None,
            ),
            J25: DayValues(
                None,
                0.01,
                ThresholdSource.FIXED,
                1.0547411221253826,
                None,
            ),
            J27: DayValues(
                None,
                0.01,
                ThresholdSource.FIXED,
                1.0547411221253826,
                None,
            ),
        },
        review=(
            ReviewReason(ReviewCause.TARGET_UNAVAILABLE, None, (J14, J25, J27)),
            ReviewReason(
                ReviewCause.GUARD_UNAVAILABLE, ExperimentMetric.LEVEL, (J14, J25, J27)
            ),
            ReviewReason(
                ReviewCause.GUARD_UNAVAILABLE,
                ExperimentMetric.ASCENT_LEVEL,
                (J14, J25, J27),
            ),
            ReviewReason(
                ReviewCause.GUARD_UNAVAILABLE, ExperimentMetric.FLAT_LEVEL, (J25,)
            ),
            ReviewReason(
                ReviewCause.GUARD_UNAVAILABLE,
                ExperimentMetric.DESCENT_LEVEL,
                (J14, J25, J27),
            ),
            ReviewReason(
                ReviewCause.GUARD_UNAVAILABLE,
                ExperimentMetric.ASCENT_DISPERSION,
                (J14, J25, J27),
            ),
            ReviewReason(
                ReviewCause.GUARD_UNAVAILABLE, ExperimentMetric.FLAT_DISPERSION, (J25,)
            ),
            ReviewReason(
                ReviewCause.GUARD_UNAVAILABLE,
                ExperimentMetric.DESCENT_DISPERSION,
                (J14, J25, J27),
            ),
            ReviewReason(ReviewCause.PASSAGES_UNAVAILABLE, None, (J14, J25, J27)),
        ),
        failures=(),
        guards={
            ExperimentMetric.LEVEL: GuardValues(GuardStatus.UNAVAILABLE, None, 0.005),
            ExperimentMetric.ASCENT_LEVEL: GuardValues(
                GuardStatus.UNAVAILABLE, None, 0.005
            ),
            ExperimentMetric.FLAT_LEVEL: GuardValues(
                GuardStatus.UNAVAILABLE, None, 0.005
            ),
            ExperimentMetric.DESCENT_LEVEL: GuardValues(
                GuardStatus.UNAVAILABLE, None, 0.005
            ),
            ExperimentMetric.ASCENT_DISPERSION: GuardValues(
                GuardStatus.UNAVAILABLE, None, 0.005
            ),
            ExperimentMetric.FLAT_DISPERSION: GuardValues(
                GuardStatus.UNAVAILABLE, None, 0.005
            ),
            ExperimentMetric.DESCENT_DISPERSION: GuardValues(
                GuardStatus.UNAVAILABLE, None, 0.005
            ),
        },
        passages=GuardStatus.UNAVAILABLE,
        reserves=(AdmissionReserve.SENSITIVITY_REMAINING,),
    ),
    "Scale(0.4)/descent_level/elapsed/sature": AdmissionValues(
        evaluable=3,
        verdict=AdmissionVerdict.REJECTED,
        mean_gain=-0.1048899616023252,
        mean_threshold=0.026502403822383624,
        positive=0,
        required=3,
        mean_raw_gain=-0.0922137449232333,
        days={
            J14: DayValues(
                -0.017553798592859042,
                0.034753605733575436,
                ThresholdSource.LOCAL,
                0.9944081039918902,
                0.3977632415967561,
            ),
            J25: DayValues(
                -0.12305953654416535,
                0.01,
                ThresholdSource.LOCAL,
                1.022057875282595,
                0.408823150113038,
            ),
            J27: DayValues(
                -0.1740565496699512,
                0.034753605733575436,
                ThresholdSource.LOCAL,
                1.022057875282595,
                0.408823150113038,
            ),
        },
        review=(),
        failures=(
            FailedCheck(FailedCondition.MEAN_GAIN, None, ()),
            FailedCheck(FailedCondition.VOTE, None, ()),
            FailedCheck(FailedCondition.LOSS, None, (J25, J27)),
            FailedCheck(FailedCondition.GUARD, ExperimentMetric.LEVEL, (J25, J27)),
            FailedCheck(FailedCondition.GUARD, ExperimentMetric.ASCENT_LEVEL, (J27,)),
            FailedCheck(FailedCondition.GUARD, ExperimentMetric.FLAT_LEVEL, (J25,)),
            FailedCheck(FailedCondition.PASSAGES, None, (J25, J27)),
        ),
        guards={
            ExperimentMetric.LEVEL: GuardValues(
                GuardStatus.VIOLATED, 0.049452063820724035, 0.006366785649738754
            ),
            ExperimentMetric.ASCENT_LEVEL: GuardValues(
                GuardStatus.VIOLATED, 0.016096653276038386, 0.005
            ),
            ExperimentMetric.FLAT_LEVEL: GuardValues(
                GuardStatus.VIOLATED, 0.08768249014998201, 0.005
            ),
            ExperimentMetric.ASCENT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 1.4668449071929738e-16, 0.005
            ),
            ExperimentMetric.FLAT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 1.0615745773106613e-15, 0.005
            ),
            ExperimentMetric.DESCENT_DISPERSION: GuardValues(
                GuardStatus.SATISFIED, 5.568259812692074e-53, 0.013994583331636662
            ),
        },
        passages=GuardStatus.VIOLATED,
        reserves=(
            AdmissionReserve.CANDIDATE_SATURATED,
            AdmissionReserve.SENSITIVITY_REMAINING,
        ),
    ),
}
"""Les valeurs de l'oracle, par expérience de ``EXPERIMENTS``."""
