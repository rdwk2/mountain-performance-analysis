"""Les normales de la table ``jours`` (AN2-2, ``docs/decisions/0019``) : la normale
de chaque jour d'une suite, sa plage et ses segments, les ruptures de rang et de
version, les jours incertains et la normale à cheval.

**Les suites.** Chaque fonction prend des suites alignées sur des jours **consécutifs**
du calendrier, une entrée par ligne de ``jours`` : l'indice ``i`` est le jour ``i`` de
la table, le premier jour est l'indice 0, et « le jour t − k » est l'indice ``t − k``
s'il est positif ou nul. Aucune ne prend les jours eux-mêmes : l'appelant (la table, qui
a une
ligne par jour du premier au dernier document, ``absent`` comprise) promet qu'ils se
suivent. Aucune ne lit ``interim/`` ; les valeurs et leur admission viennent de la
table (``AdmissionRefusal``), qui les décide ; ici, une valeur admise entre dans les
normales, une autre jamais.

**La normale du jour t** : la fenêtre est faite des jours
``[t − window_days, t − 1]``, **bornes comprises**, présents dans la suite (au début
de la table, elle est plus courte) ; **le jour t n'en est jamais**. Les jours admis de
la fenêtre se comptent (``admitted_days``) : aucun, pas de normale, motif
``no_admitted_day`` ; au moins un et **strictement moins** que ``min_admitted_days``,
motif ``too_few_admitted_days`` (``min_admitted_days`` jours suffisent). Sinon, sur
les valeurs admises de la fenêtre (en log pour la HRV, ``math.log``) : la médiane
(``statistics.median``) ; la MAD, médiane des écarts absolus à la médiane ;
s = max(``mad_factor`` × MAD ; plancher), le plancher étant la résolution déclarée de
la mesure, et pour la HRV ln(1 + r / m), r sa résolution en ms et m = exp(médiane du
log). La normale est dans l'unité de la mesure (pour la HRV, m) ; la plage est
médiane ∓ ``range_k`` × s (pour la HRV, exp(médiane du log ∓ ``range_k`` × s), en ms,
dissymétrique) ; la dispersion est s (pour la HRV, aucune en ms : la médiane et le s
du log, à part).

**Les segments** : le segment du jour t est le nombre de lignes avant t dont la normale
est absente ; deux lignes à normale présente ont le même segment si et seulement si
aucune normale absente ne les sépare. Une rupture ne coupe pas les segments.

**Les ruptures et les avertissements** (un écart à la rupture d'office de la charte,
§ 11, pour la normale de ``jours`` seulement) : **une rupture n'exclut rien** ; elle
se marque, et la normale continue à travers elle.

- rupture de rang au jour R : R porte des rangs, et l'un d'eux manque aux rangs du
  dernier jour avant R qui en porte ; aucune au premier jour qui en porte ; elle vaut
  pour les six mesures (le retour à une montre déjà vue en est une) ;
- rupture de version de la mesure au jour R : R porte une version de la famille de la
  mesure, différente de celle du dernier jour avant R qui en porte une ; aucune à la
  première ;
- la rupture de la mesure au jour R : l'une ou l'autre ;
- jour incertain (commun aux mesures) : un jour à au moins deux rangs ; ou un jour sans
  rang situé entre le dernier jour à rangs avant lui et un jour R suivant de rupture de
  rang, sans jour à rangs entre eux (l'intervalle incertain d'un changement de
  montre) ; un jour sans rang ne se sait incertain qu'au vu du jour à rangs qui le
  suit ;
- normale à cheval au jour t : une rupture de la mesure à un jour de
  ``[t − window_days + 1, t − 1]`` (le premier jour de la fenêtre exclu : une fenêtre
  qui commence à la rupture ne mêle rien), ou un jour incertain dans
  ``[t − window_days, t − 1]``, bornes comprises.

**Le coût** : linéaire en la longueur de la suite fois la fenêtre (une fenêtre triée
glisse d'un jour à l'autre, un jour entre et un jour sort ; la médiane et la MAD se
lisent sur elle en un temps linéaire en la fenêtre) ; les ruptures, les jours
incertains, les segments et la normale à cheval sont linéaires en la suite.

Les paramètres sont déclarés ici (``NORMAL_PARAMETER_SPECS``), communs à tous les
athlètes, portés par la provenance sous ``normal.<nom>`` (la table les préfixe). Python
pur : la bibliothèque standard et ``mountain_perf.schemas``.
"""

from __future__ import annotations

import heapq
import math
import statistics
from bisect import bisect_left, insort
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import accumulate, pairwise
from types import MappingProxyType

from mountain_perf.schemas.parameters import ParameterSet, ParameterSpec
from mountain_perf.schemas.processed import NormalAbsence

NORMAL_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        name="window_days",
        unit="d",
        default=28.0,
        minimum=1.0,
        maximum=365.0,
        description=(
            "Jours de la fenêtre de la normale du jour t : [t − window_days, t − "
            "1], bornes comprises, le jour t exclu. Un compte, entier."
        ),
    ),
    ParameterSpec(
        name="min_admitted_days",
        unit="d",
        default=14.0,
        minimum=1.0,
        maximum=365.0,
        description=(
            "Jours admis de la fenêtre sans lesquels la normale manque : "
            "strictement moins, pas de normale ; autant suffisent. Un compte, "
            "entier."
        ),
    ),
    ParameterSpec(
        name="mad_factor",
        unit=None,
        default=1.4826,
        minimum=0.0,
        maximum=10.0,
        description=(
            "Facteur de la MAD dans la dispersion s = max(mad_factor × MAD ; plancher)."
        ),
    ),
    ParameterSpec(
        name="range_k",
        unit=None,
        default=1.0,
        minimum=0.0,
        maximum=10.0,
        description=(
            "Demi-largeur de la plage, en dispersions : médiane ∓ range_k × s "
            "(pour la HRV, dans le log)."
        ),
    ),
    ParameterSpec(
        name="exclude_altitude_stay",
        unit=None,
        default=1.0,
        minimum=0.0,
        maximum=1.0,
        description=(
            "1 : un jour de séjour en altitude au journal n'est admis dans aucune "
            "normale ; 0 : il l'est. Un interrupteur, entier."
        ),
    ),
    ParameterSpec(
        name="hrv_resolution_ms",
        unit="ms",
        default=1.0,
        minimum=0.001,
        maximum=100.0,
        description=(
            "Résolution déclarée de la HRV de la nuit ; son plancher, dans le log "
            ": ln(1 + r / m), m l'exponentielle de la médiane du log."
        ),
    ),
    ParameterSpec(
        name="resting_hr_resolution_bpm",
        unit="bpm",
        default=1.0,
        minimum=0.001,
        maximum=100.0,
        description=(
            "Résolution déclarée de la FC de repos, plancher de sa dispersion."
        ),
    ),
    ParameterSpec(
        name="measured_sleep_resolution_s",
        unit="s",
        default=60.0,
        minimum=0.001,
        maximum=3600.0,
        description=(
            "Résolution déclarée du sommeil mesuré, plancher de sa dispersion."
        ),
    ),
    ParameterSpec(
        name="night_stress_resolution",
        unit=None,
        default=1.0,
        minimum=0.001,
        maximum=100.0,
        description=(
            "Résolution déclarée du stress de la nuit, plancher de sa dispersion."
        ),
    ),
    ParameterSpec(
        name="night_respiration_resolution_breaths_per_min",
        unit="/min",
        default=1.0,
        minimum=0.001,
        maximum=100.0,
        description=(
            "Résolution déclarée de la respiration de la nuit, plancher de sa "
            "dispersion."
        ),
    ),
    ParameterSpec(
        name="night_spo2_resolution_percent",
        unit="%",
        default=1.0,
        minimum=0.001,
        maximum=100.0,
        description=(
            "Résolution déclarée de la SpO2 de la nuit, plancher de sa dispersion."
        ),
    ),
)
"""Les paramètres des normales. La provenance les porte sous ``normal.<nom>``. Bornes
comprises : un compte de jours dans ``[1, 365]`` ; le facteur et ``range_k`` dans
``[0, 10]`` ; l'interrupteur dans ``[0, 1]`` ; une résolution, un pas strictement
positif de la source, dans ``[0,001 ; 100]`` de son unité (``[0,001 ; 3600]`` s pour le
sommeil
mesuré).
"""

INTEGER_PARAMETERS: tuple[str, ...] = (
    "window_days",
    "min_admitted_days",
    "exclude_altitude_stay",
)
"""Les paramètres des normales qui sont des entiers : les deux comptes et
l'interrupteur (:func:`integer_parameter`).
"""


class NormalMeasure(StrEnum):
    """Une mesure des normales ; sa valeur est le préfixe de ses colonnes dans
    ``DayRow``, dans l'ordre des mesures de ``DayRow``.
    """

    HRV = "hrv"
    RESTING_HR = "resting_hr"
    MEASURED_SLEEP = "measured_sleep"
    NIGHT_STRESS = "night_stress"
    NIGHT_RESPIRATION = "night_respiration"
    NIGHT_SPO2 = "night_spo2"


class MeasureScale(StrEnum):
    """L'échelle où se calcule la normale d'une mesure : ``linear``, dans son unité ;
    ``log``, dans le log de son unité (la HRV seule).
    """

    LINEAR = "linear"
    LOG = "log"


@dataclass(frozen=True)
class MeasureSpec:
    """La déclaration d'une mesure des normales.

    - ``scale`` — l'échelle de la normale (``log`` pour la HRV seule) ;
    - ``resolution`` — le nom, dans ``NORMAL_PARAMETER_SPECS``, de sa résolution
      déclarée (le plancher de s) ;
    - ``version`` — le nom du champ d'``AlgorithmVersions`` (et de la colonne de
      ``DayRow``) de la famille de la mesure, dont un changement la rompt ; ``None``
      si aucune version ne la rompt ;
    - ``night`` — une mesure de nuit (l'admission lit l'état et les drapeaux de la
      nuit).
    """

    scale: MeasureScale
    resolution: str
    version: str | None
    night: bool


MEASURE_SPECS: Mapping[NormalMeasure, MeasureSpec] = MappingProxyType(
    {
        NormalMeasure.HRV: MeasureSpec(
            MeasureScale.LOG, "hrv_resolution_ms", None, True
        ),
        NormalMeasure.RESTING_HR: MeasureSpec(
            MeasureScale.LINEAR, "resting_hr_resolution_bpm", None, False
        ),
        NormalMeasure.MEASURED_SLEEP: MeasureSpec(
            MeasureScale.LINEAR, "measured_sleep_resolution_s", "sleep_version", True
        ),
        NormalMeasure.NIGHT_STRESS: MeasureSpec(
            MeasureScale.LINEAR, "night_stress_resolution", "sleep_version", True
        ),
        NormalMeasure.NIGHT_RESPIRATION: MeasureSpec(
            MeasureScale.LINEAR,
            "night_respiration_resolution_breaths_per_min",
            "respiration_version",
            True,
        ),
        NormalMeasure.NIGHT_SPO2: MeasureSpec(
            MeasureScale.LINEAR, "night_spo2_resolution_percent", None, True
        ),
    }
)
"""Les six mesures, dans l'ordre de ``NormalMeasure`` : la
version qui rompt une mesure est celle de sa famille, sans exception
(``sleep_version`` pour le sommeil mesuré et le stress de la nuit, champs de
``sleep`` ; ``respiration_version`` pour la respiration de la nuit ; aucune pour la HRV,
la FC de repos et la SpO2) ; ``sleep_respiration_version`` ne rompt aucune normale.
"""


@dataclass(frozen=True)
class MeasureNormal:
    """La normale d'une mesure à un jour, ce que la ligne de ``jours`` en porte.

    - ``normal`` — unité de la mesure — la médiane des valeurs admises de la fenêtre ;
      pour la HRV, exp(médiane du log), en ms ;
    - ``dispersion`` — unité de la mesure — s = max(``mad_factor`` × MAD ; plancher) ;
      ``None`` pour la HRV (sa plage est dissymétrique en ms) ;
    - ``log_median``, ``log_dispersion`` — sans unité — pour la HRV seule, la médiane
      et le s du log de ses valeurs en ms ; ``None`` pour les autres mesures ;
    - ``range_low``, ``range_high`` — unité de la mesure — la plage, médiane ∓
      ``range_k`` × s ; pour la HRV, exp(médiane du log ∓ ``range_k`` × s) ;
    - ``admitted_days`` — sans unité — les jours admis de la fenêtre ;
    - ``absence`` — sans unité — le motif d'une normale absente, ``None`` si elle est
      là ;
    - ``segment`` — sans unité — le nombre de lignes avant celle-ci dont la normale
      est absente ;
    - ``rupture`` — sans unité — une rupture de la mesure ce jour, de rang ou de
      version ;
    - ``straddles`` — sans unité — la normale est à cheval sur une rupture.

    Sans normale, ``normal``, ``dispersion``, ``log_median``, ``log_dispersion``,
    ``range_low`` et ``range_high`` sont tous ``None`` ; avec elle,
    ``range_low`` ≤ ``normal`` ≤ ``range_high``.
    """

    normal: float | None
    dispersion: float | None
    log_median: float | None
    log_dispersion: float | None
    range_low: float | None
    range_high: float | None
    admitted_days: int
    absence: NormalAbsence | None
    segment: int
    rupture: bool
    straddles: bool


def integer_parameter(parameters: ParameterSet, name: str) -> int:
    """La valeur du paramètre ``name`` de ``parameters``, un compte ou un interrupteur,
    convertie en entier : ``28.0`` donne 28 ; une valeur qui n'est pas entière
    (``27.5``) lève ``ValueError``, qui nomme le paramètre. ``KeyError`` si ``name``
    n'est pas déclaré dans ``parameters``. Les bornes sont celles de la spec (le jeu
    les a contrôlées) ; celles de l'interrupteur sont 0 et 1.
    """
    value = parameters[name]
    if not float(value).is_integer():
        raise ValueError(
            f"Le paramètre {name} doit être entier (un compte ou un interrupteur), "
            f"reçu {value!r}."
        )
    return int(value)


def _check_parameters(parameters: ParameterSet) -> None:
    if (
        not isinstance(parameters, ParameterSet)
        or parameters.specs != NORMAL_PARAMETER_SPECS
    ):
        raise ValueError(
            "parameters doit être un ParameterSet de NORMAL_PARAMETER_SPECS, reçu "
            f"{parameters!r}."
        )
    for name in INTEGER_PARAMETERS:
        integer_parameter(parameters, name)


def _check_lengths(**suites: Sequence[object]) -> None:
    if len({len(suite) for suite in suites.values()}) > 1:
        detail = ", ".join(f"{name}={len(suite)}" for name, suite in suites.items())
        raise ValueError(
            "Les suites doivent avoir la même longueur (un jour par entrée) : "
            f"{detail}."
        )


def rank_ruptures(ranks: Sequence[tuple[int, ...]]) -> tuple[bool, ...]:
    """Les ruptures de rang, jour par jour : au jour R, R porte des rangs et l'un
    d'eux manque aux rangs du **dernier jour avant R qui en porte** (les jours sans
    rang entre eux ne comptent pas) ; aucune au premier jour qui en porte, ni à un jour
    sans rang. Un rang de la veille qui disparaît n'en est pas une (rangs 1 et 2, puis
    2 seul) ; le retour à une montre déjà vue en est une (rangs 1, puis 2, puis 1 :
    ruptures au premier 2 et au retour du 1).

    ``ranks`` : un tuple de rangs (entiers d'au moins 1, strictement croissants) par
    jour
    consécutif ; ``ValueError`` sinon, qui nomme l'entrée.
    """
    ruptures: list[bool] = []
    previous: tuple[int, ...] = ()
    for i, day_ranks in enumerate(ranks):
        if not isinstance(day_ranks, tuple) or any(
            isinstance(rank, bool) or not isinstance(rank, int) or rank < 1
            for rank in day_ranks
        ):
            raise ValueError(
                f"ranks[{i}] doit être un tuple d'entiers >= 1, reçu {day_ranks!r}."
            )
        if any(b <= a for a, b in pairwise(day_ranks)):
            raise ValueError(
                f"ranks[{i}] doit être trié, strictement croissant, reçu {day_ranks!r}."
            )
        ruptures.append(bool(previous) and not set(day_ranks) <= set(previous))
        if day_ranks:
            previous = day_ranks
    return tuple(ruptures)


def version_ruptures(versions: Sequence[int | None]) -> tuple[bool, ...]:
    """Les ruptures de version d'une famille, jour par jour : au jour R, R porte une
    version, **différente** de celle du **dernier jour avant R qui en porte une** (les
    jours sans version entre eux ne comptent pas) ; aucune à la première version, ni
    à un jour sans version.

    ``versions`` : une version (entier positif ou nul) ou ``None`` par jour consécutif ;
    ``ValueError`` sinon, qui nomme l'entrée.
    """
    ruptures: list[bool] = []
    previous: int | None = None
    for i, version in enumerate(versions):
        if version is not None and (
            isinstance(version, bool) or not isinstance(version, int) or version < 0
        ):
            raise ValueError(
                f"versions[{i}] doit être un entier >= 0 ou None, reçu {version!r}."
            )
        ruptures.append(
            version is not None and previous is not None and version != previous
        )
        if version is not None:
            previous = version
    return tuple(ruptures)


def uncertain_days(ranks: Sequence[tuple[int, ...]]) -> tuple[bool, ...]:
    """Les jours incertains (``DayRow.uncertain_device``, communs aux mesures) : un
    jour à **au moins deux** rangs (on ne sait pas quelle montre a mesuré) ; ou un jour
    sans rang situé entre le dernier jour à rangs avant lui et un jour R suivant de
    rupture de rang (:func:`rank_ruptures`), sans jour à rangs entre eux (l'intervalle
    incertain d'un changement de montre : des familles sans appareil peuvent y porter
    des valeurs).
    Un jour sans rang qui ne précède aucune rupture (le prochain jour à rangs n'en est
    pas une, ou il n'y en a pas) n'est pas incertain ; ni le jour R d'un seul rang, ni
    le dernier jour à rangs avant l'intervalle.

    Non promis : un jour sans rang n'est dit incertain qu'au vu du jour à rangs qui le
    suit ; son incertitude, et la normale à cheval qui en dépend
    (:func:`straddles`), peuvent donc tenir aux rangs de jours postérieurs (la table
    se recalcule en entier à chaque ``mperf tables``).

    ``ranks`` : comme :func:`rank_ruptures`.
    """
    ruptures = rank_ruptures(ranks)
    uncertain = [len(day_ranks) >= 2 for day_ranks in ranks]
    rupture_follows = False
    for i in range(len(ranks) - 1, -1, -1):
        if ranks[i]:
            rupture_follows = ruptures[i]
        elif rupture_follows:
            uncertain[i] = True
    return tuple(uncertain)


def straddles(
    ruptures: Sequence[bool], uncertain: Sequence[bool], parameters: ParameterSet
) -> tuple[bool, ...]:
    """La normale à cheval, jour par jour : au jour t, une
    rupture de la mesure à un jour de ``[t − window_days + 1, t − 1]`` (la fenêtre
    mêle l'avant et l'après ; une rupture au premier jour de la fenêtre, t −
    ``window_days``, n'en mêle rien), ou un jour incertain dans
    ``[t − window_days, t − 1]`` ; bornes comprises, le jour t jamais.

    ``ruptures`` : la rupture de la mesure (de rang ou de version) par jour
    consécutif ; ``uncertain`` : :func:`uncertain_days` ; ``parameters`` : un jeu de
    ``NORMAL_PARAMETER_SPECS``. ``ValueError`` sur des longueurs différentes, une
    entrée qui n'est pas un booléen ou un jeu d'autres paramètres.
    """
    _check_parameters(parameters)
    window = integer_parameter(parameters, "window_days")
    _check_lengths(ruptures=ruptures, uncertain=uncertain)
    for name, flags in (("ruptures", ruptures), ("uncertain", uncertain)):
        for i, flag in enumerate(flags):
            if not isinstance(flag, bool):
                raise ValueError(f"{name}[{i}] doit être un booléen, reçu {flag!r}.")
    rupture_sum = [0, *accumulate(int(flag) for flag in ruptures)]
    uncertain_sum = [0, *accumulate(int(flag) for flag in uncertain)]
    return tuple(
        rupture_sum[t] - rupture_sum[max(t - window + 1, 0)] > 0
        or uncertain_sum[t] - uncertain_sum[max(t - window, 0)] > 0
        for t in range(len(ruptures))
    )


def segments(absences: Sequence[NormalAbsence | None]) -> tuple[int, ...]:
    """Les segments, jour par jour : au jour t, le nombre de lignes **avant** t dont la
    normale est absente (le jour t lui-même ne compte pas) ; le premier jour est au
    segment 0, et le segment croît d'une unité après chaque normale absente.

    ``absences`` : le motif d'une normale absente, ou ``None``, par jour consécutif ;
    ``ValueError`` sur une autre entrée.
    """
    out: list[int] = []
    count = 0
    for i, absence in enumerate(absences):
        if absence is not None and not isinstance(absence, NormalAbsence):
            raise ValueError(
                f"absences[{i}] doit être un NormalAbsence ou None, reçu {absence!r}."
            )
        out.append(count)
        if absence is not None:
            count += 1
    return tuple(out)


def _check_entries(
    scale: MeasureScale, values: Sequence[float | None], admitted: Sequence[bool]
) -> None:
    for i, (value, flag) in enumerate(zip(values, admitted, strict=True)):
        if not isinstance(flag, bool):
            raise ValueError(f"admitted[{i}] doit être un booléen, reçu {flag!r}.")
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            raise ValueError(
                f"values[{i}] doit être un nombre fini ou None, reçu {value!r}."
            )
        if flag and value is None:
            raise ValueError(f"admitted[{i}] est vrai sans valeur (values[{i}]).")
        if flag and scale is MeasureScale.LOG and value is not None and value <= 0:
            raise ValueError(
                f"values[{i}] est admise sur l'échelle log : elle doit être > 0, reçu "
                f"{value!r}."
            )


def _mad(window: Sequence[float], median: float) -> float:
    """La médiane des écarts absolus à ``median`` d'une fenêtre triée : les écarts des
    deux moitiés, déjà triés, se fusionnent en un temps linéaire."""
    middle = bisect_left(window, median)
    below = [median - value for value in reversed(window[:middle])]
    above = [value - median for value in window[middle:]]
    return statistics.median(list(heapq.merge(below, above)))


def _statistics(
    window: Sequence[float],
    scale: MeasureScale,
    resolution: float,
    mad_factor: float,
    range_k: float,
) -> tuple[float, float | None, float | None, float | None, float, float]:
    """Normale, dispersion, médiane et dispersion du log, bornes de la plage."""
    median = statistics.median(window)
    mad = _mad(window, median)
    if scale is MeasureScale.LOG:
        center = math.exp(median)
        spread = max(mad_factor * mad, math.log1p(resolution / center))
        return (
            center,
            None,
            median,
            spread,
            math.exp(median - range_k * spread),
            math.exp(median + range_k * spread),
        )
    spread = max(mad_factor * mad, resolution)
    return (
        median,
        spread,
        None,
        None,
        median - range_k * spread,
        median + range_k * spread,
    )


def measure_normals(
    measure: NormalMeasure,
    values: Sequence[float | None],
    admitted: Sequence[bool],
    ranks: Sequence[tuple[int, ...]],
    versions: Sequence[int | None] | None,
    parameters: ParameterSet,
) -> tuple[MeasureNormal, ...]:
    """La normale de ``measure`` à chaque jour d'une suite, ses segments, ses ruptures
    et sa normale à cheval : un ``MeasureNormal`` par jour, dans l'ordre.

    La règle est celle du module : au jour t, les valeurs **admises** des jours
    ``[t − window_days, t − 1]`` (bornes comprises, le jour t exclu, plus courte au
    début de la table) ; aucune, motif ``no_admitted_day`` ; au moins une et
    strictement moins que ``min_admitted_days``, ``too_few_admitted_days`` ; sinon la
    médiane, s = max(``mad_factor`` × MAD ; plancher), la plage médiane ∓ ``range_k``
    × s, sur l'échelle de la mesure (``MEASURE_SPECS`` ; pour la HRV, en log, le
    plancher ln(1 + r / m) et la normale m = exp(médiane du log)). Une valeur non
    admise n'est jamais lue, et une rupture n'exclut rien ; la normale du jour t ne
    dépend que des valeurs et des admissions des jours avant t.

    Entrées, une par jour consécutif, de même longueur :

    - ``values`` — unité de la mesure — sa valeur du jour, ou ``None`` ; finie ;
    - ``admitted`` — la valeur entre dans les normales (décidé par la table) ; une
      valeur admise est présente, et strictement positive pour la HRV (son log) ;
    - ``ranks`` — les rangs d'appareil du jour (:func:`rank_ruptures`) ;
    - ``versions`` — la version de la famille de la mesure
      (la version que ``MEASURE_SPECS`` déclare pour la mesure) ou ``None`` par jour ;
      ``None`` à la place
      de la suite pour une mesure qu'aucune version ne rompt ;
    - ``parameters`` — un jeu de ``NORMAL_PARAMETER_SPECS``, ses comptes et son
      interrupteur entiers (:func:`integer_parameter`).

    ``ValueError``, qui nomme l'argument, sur toute entrée qui s'en écarte. Coût :
    linéaire en la longueur de la suite fois ``window_days``.

    Une fenêtre plus courte que le minimum (``window_days`` strictement sous
    ``min_admitted_days``) rend
    une normale toujours absente, de motif ``too_few_admitted_days`` (ou
    ``no_admitted_day`` sans jour admis), sans erreur : ``ParameterSet`` ne croise pas
    les paramètres, et la provenance dit le jeu qui l'a donnée.

    Non promis : des valeurs hors de toute plage physique (une HRV de 10³⁰⁰ ms) peuvent
    déborder ; la table n'en admet pas (la lecture des familles borne la HRV,
    ``HRV_RANGE_MS``).
    """
    if not isinstance(measure, NormalMeasure):
        raise ValueError(f"measure doit être un NormalMeasure, reçu {measure!r}.")
    _check_parameters(parameters)
    spec = MEASURE_SPECS[measure]
    if spec.version is None and versions is not None:
        raise ValueError(
            f"versions doit être None : aucune version ne rompt la mesure {measure}."
        )
    if spec.version is not None and versions is None:
        raise ValueError(
            f"versions manque : la version {spec.version} rompt la mesure {measure}."
        )
    if versions is None:
        _check_lengths(values=values, admitted=admitted, ranks=ranks)
    else:
        _check_lengths(values=values, admitted=admitted, ranks=ranks, versions=versions)
    _check_entries(spec.scale, values, admitted)
    rank_breaks = rank_ruptures(ranks)
    version_breaks = (
        (False,) * len(values) if versions is None else version_ruptures(versions)
    )
    ruptures = tuple(a or b for a, b in zip(rank_breaks, version_breaks, strict=True))
    astride = straddles(ruptures, uncertain_days(ranks), parameters)
    window_days = integer_parameter(parameters, "window_days")
    minimum = integer_parameter(parameters, "min_admitted_days")
    scaled = [
        None
        if not flag or value is None
        else math.log(value)
        if spec.scale is MeasureScale.LOG
        else float(value)
        for value, flag in zip(values, admitted, strict=True)
    ]
    window: list[float] = []
    computed: list[tuple[int, NormalAbsence | None, tuple[float | None, ...]]] = []
    for t, entering in enumerate(scaled):
        leaving = scaled[t - window_days - 1] if t - window_days - 1 >= 0 else None
        if leaving is not None:
            del window[bisect_left(window, leaving)]
        count = len(window)
        if count == 0:
            computed.append((count, NormalAbsence.NO_ADMITTED_DAY, (None,) * 6))
        elif count < minimum:
            computed.append((count, NormalAbsence.TOO_FEW_ADMITTED_DAYS, (None,) * 6))
        else:
            numbers = _statistics(
                window,
                spec.scale,
                parameters[spec.resolution],
                parameters["mad_factor"],
                parameters["range_k"],
            )
            computed.append((count, None, numbers))
        if entering is not None:
            insort(window, entering)
    segment_numbers = segments([absence for _, absence, _ in computed])
    return tuple(
        MeasureNormal(
            normal=numbers[0],
            dispersion=numbers[1],
            log_median=numbers[2],
            log_dispersion=numbers[3],
            range_low=numbers[4],
            range_high=numbers[5],
            admitted_days=count,
            absence=absence,
            segment=segment,
            rupture=rupture,
            straddles=straddling,
        )
        for (count, absence, numbers), segment, rupture, straddling in zip(
            computed, segment_numbers, ruptures, astride, strict=True
        )
    )
