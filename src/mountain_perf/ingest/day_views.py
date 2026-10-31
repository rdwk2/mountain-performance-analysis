"""Les vues des jours (AN2-1) : ce que M7 et la piste lisent d'``interim/days/``,
calculé à la lecture, jamais écrit.

Entrées : les ``DayRecord`` triés par jour, sans doublon (``read_days``), et le
``TrainingStatusHistory`` (``read_training_status``). Les objets
rendus sont des dataclasses gelées de ce module ; leurs énumérations
(``NightState``, ``NightFlag``, ``RestingHrStatus``, ``SeriesKind``, ``ViewAbsence``)
sont dans ``mountain_perf.schemas``.

**Règle commune** (vues prises à un instant ``t`` : ``sleep_within`` à sa borne
``end``, ``body_battery_at``, ``night_before``, ``training_status_at``,
``readiness_at``, ``resting_hr_at``, ``series_between`` à sa borne ``end``) : la vue
ne rend que ce dont l'instant propre est **au plus tard** ``t`` ; avec
``strict=True``, **strictement avant** ``t`` (``strict`` faux par défaut), pour tout ce
qu'elle lit (nuits, segments, points, entrées, jours, blocs). Les instants des contrats
sont à la microseconde : avec ``strict`` à ``t``, une vue rend les mêmes objets que
sans ``strict`` à ``t`` − 1 µs (seuls changent ce qui se mesure depuis ``t`` : âges,
écarts, borne ``end``, couverture). Jamais une valeur postérieure recopiée vers
l'arrière. Instants propres :

- d'une nuit et d'une sieste, leur fin ; tout ce que la nuit porte (fenêtre, durées,
  segments, séries) n'existe qu'une fois la nuit finie : une nuit finie après ``t``
  ne compte pas, ni sa fenêtre ni ses points ; **une nuit rendue** (``night_before``,
  les épisodes de ``sleep_within``) est la nuit telle que connue à ``t`` : ses séries
  coupées aux points d'instant au plus tard ``t`` et ses segments à ceux finis au plus
  tard ``t`` (``strict`` : strictement avant ``t``, pour les points des séries comme
  pour les segments) ; un point ou un segment hors de sa fenêtre et après ``t`` n'est
  pas rendu ;
- d'un point de série, son instant : si Garmin date un point agrégé par le début de son
  intervalle, ce que le point résume court jusqu'à un pas après son instant, et
  ``strict`` à ``t`` laisse donc passer des mesures jusqu'à un pas après ``t`` ; d'une
  entrée de Training Readiness, son horodatage ;
- d'une grandeur ``day`` (la FC de repos), la fin de la fenêtre de son jour : le plus
  tard de son début + 24 h et de sa fin des données (``data_end``), lue dans le seul
  document du jour, jamais dans celui du lendemain. Un jour de 25 h complet finit au
  minuit local qui suit ; un jour de 23 h, à début + 24 h, une heure après sa vraie fin
  (prudent) ; le jour du passage à l'heure d'hiver, si ses données finissent au plus
  tard à début + 24 h (jour tronqué, ou fenêtre écrite sur 24 h à un seul décalage), à
  début + 24 h : au plus une heure avant son minuit local, ses données, elles,
  finissant avant ; si elles finissent entre début + 24 h et ce minuit, à leur fin ;
- d'un bloc de Training Status, son ``proper_instant`` (calculé à l'ingestion) ; un
  bloc sans instant propre n'est jamais rendu. **Seule exception, en instants
  propres** (les points agrégés à part, ci-dessus), à « la vue à ``t`` ne dépend
  d'aucune donnée d'après ``t`` » : l'instant propre d'un bloc sans horodatage ni
  fenêtre de son jour D est le début de la fenêtre de D + 1 si D + 1 a une fenêtre
  (un document de D + 1 ``empty`` n'en a pas), sinon le minuit qui suit D au décalage
  du fichier choisi ; selon que D + 1 a une fenêtre, il bouge de l'écart entre les
  deux décalages (une heure au changement d'heure), et ``training_status_at`` avec
  lui.

``night_assessment``, ``resting_hr_on`` et ``readiness_on_waking`` se prennent sur un
jour, pas à un instant ; ``nights_after`` est **hors de la règle commune** (analyse
rétrospective).

**Entrées contrôlées** : instants *aware* ; ``days`` trié par ``day``, sans doublon ;
``day`` une date ; seuils sans valeur par défaut, nombres finis dans leur domaine
(durées ``>= 0``, pas ``> 0``, fractions dans ``[0, 1]``, comptes entiers ``>= 1``),
unités dans les noms ; sinon ``ValueError``, dont le message commence par le nom de
l'argument. Chaque vue dit, pour chaque seuil, si la borne est comprise. Les seuils se
comparent en secondes (flottants), jamais convertis en ``timedelta`` (qui arrondirait
à la microseconde).

À égalité d'instant propre, la vue rend le dernier dans l'ordre des documents (jour,
puis rang), sauf le dédoublonnage des points d'une série (``body_battery_at``,
``series_between``) : le point du fichier du jour le plus ancien.

Sans dépendance : la bibliothèque standard et ``mountain_perf.schemas`` ; ni
fitdecode, ni la lecture des familles, ni l'ingestion des jours.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from mountain_perf.schemas import (
    WAKING_CONTEXT,
    AltitudeAcclimationBlock,
    BodyBatterySeries,
    BodyBatteryStatus,
    DayRecord,
    DayState,
    HeartRateSeries,
    HeatAcclimationBlock,
    HrvSeries,
    LoadBalanceBlock,
    Nap,
    Night,
    NightFlag,
    NightSeries,
    NightState,
    ReadinessEntry,
    RespirationSeries,
    RestingHrStatus,
    RestlessMomentsSeries,
    SeriesKind,
    SleepStage,
    SourceRef,
    SpO2Series,
    StressSeries,
    TrainingStatusBlock,
    TrainingStatusHistory,
    TrainingStatusKind,
    ViewAbsence,
    Vo2MaxBlock,
)

type StatusBlock = (
    TrainingStatusBlock
    | LoadBalanceBlock
    | Vo2MaxBlock
    | HeatAcclimationBlock
    | AltitudeAcclimationBlock
)
"""Un bloc de Training Status, de l'une des cinq sortes."""

type DaySeriesItem = (
    HeartRateSeries
    | StressSeries
    | BodyBatterySeries
    | RespirationSeries
    | SpO2Series
    | HrvSeries
    | RestlessMomentsSeries
)
"""Une série d'un jour ou d'une nuit."""

_DAY_S = 86400.0
_HALF_DAY_S = 43200.0
_RESULTANT_GUARD = 1e-12
"""La garde de la moyenne circulaire : une résultante, rapportée au nombre de nuits, au
plus égale à elle n'a pas de direction (le bruit d'arrondi, pas un seuil)."""

_DAY = timedelta(days=1)
_MICRO = timedelta(microseconds=1)
_SLEEP_STAGES = (SleepStage.DEEP, SleepStage.LIGHT, SleepStage.REM)


# ---------------------------------------------------------------------------
# Les contrôles des entrées
# ---------------------------------------------------------------------------


def _check_days(days: Sequence[DayRecord]) -> None:
    for i in range(1, len(days)):
        if not days[i - 1].day < days[i].day:
            raise ValueError(
                f"days doit être trié par jour, sans doublon : rangs {i - 1} et {i} "
                f"({days[i - 1].day.isoformat()}, {days[i].day.isoformat()})."
            )


def _check_instant(value: Any, name: str) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(
            f"{name} doit être un instant aware (avec son décalage), reçu {value!r}."
        )


def _check_strict(value: Any) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"strict doit être un booléen, reçu {value!r}.")


def _check_day(value: Any, name: str) -> None:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError(
            f"{name} doit être une date (un jour de Garmin), reçu {value!r}."
        )


def _check_number(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} doit être un nombre, reçu {value!r}.")
    if not math.isfinite(value):
        raise ValueError(f"{name} doit être fini, reçu {value!r}.")


def _check_fraction(value: Any, name: str) -> None:
    _check_number(value, name)
    if not 0 <= value <= 1:
        raise ValueError(f"{name} doit être dans [0, 1], reçu {value!r}.")


def _check_duration(value: Any, name: str) -> None:
    _check_number(value, name)
    if not value >= 0:
        raise ValueError(f"{name} doit être >= 0 (secondes), reçu {value!r}.")


def _check_step(value: Any, name: str) -> None:
    _check_number(value, name)
    if not value > 0:
        raise ValueError(f"{name} doit être > 0 (secondes), reçu {value!r}.")


def _check_count(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} doit être un entier, reçu {value!r}.")
    if value < 1:
        raise ValueError(f"{name} doit être >= 1, reçu {value!r}.")


# ---------------------------------------------------------------------------
# Les instants propres, la nuit connue à un instant
# ---------------------------------------------------------------------------


def _visible(proper: datetime, t: datetime, strict: bool) -> bool:
    """L'instant propre ``proper`` est connu à ``t`` : au plus tard ``t``, ou
    strictement avant avec ``strict``."""
    return proper < t if strict else proper <= t


def _day_end(record: DayRecord) -> datetime | None:
    """La fin de la fenêtre d'un jour : le plus tard de son début + 24 h et de sa fin
    des données ; jamais lue dans un autre document."""
    if record.window_start is None or record.data_end is None:
        return None
    return max(record.window_start + _DAY, record.data_end)


def _at(origin: datetime, seconds: float) -> datetime:
    return origin + timedelta(seconds=seconds)


def _cut[S: DaySeriesItem](
    series: S | None, origin: datetime, t: datetime, strict: bool
) -> S | None:
    """La série coupée à ses points connus à ``t`` ; absente sans point connu."""
    if series is None:
        return None
    keep = [_visible(_at(origin, time), t, strict) for time in series.time_s]
    if all(keep):
        return series
    if not any(keep):
        return None
    changes: dict[str, Any] = {
        item.name: tuple(
            value
            for value, kept in zip(getattr(series, item.name), keep, strict=True)
            if kept
        )
        for item in dataclasses.fields(series)
        if item.name != "source"
    }
    return dataclasses.replace(series, **changes)


def _known(night: Night, t: datetime, strict: bool) -> Night:
    """La nuit telle que connue à ``t`` : ses séries et ses segments coupés à ``t``."""
    start = night.start
    series = night.series
    known_series = NightSeries(
        heart_rate=_cut(series.heart_rate, start, t, strict),
        stress=_cut(series.stress, start, t, strict),
        body_battery=_cut(series.body_battery, start, t, strict),
        hrv=_cut(series.hrv, start, t, strict),
        respiration=_cut(series.respiration, start, t, strict),
        spo2=_cut(series.spo2, start, t, strict),
        restless_moments=_cut(series.restless_moments, start, t, strict),
    )
    segments = tuple(
        segment
        for segment in night.segments
        if _visible(_at(start, segment.end_s), t, strict)
    )
    if known_series == series and segments == night.segments:
        return night
    return dataclasses.replace(night, series=known_series, segments=segments)


# ---------------------------------------------------------------------------
# sleep_within
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SleepEpisode:
    """Un épisode de sommeil entier rendu par ``sleep_within`` : la nuit principale ou
    une sieste d'un jour (``day``, le jour du document qui la porte)."""

    day: date
    episode: Night | Nap

    @property
    def start(self) -> datetime:
        """Le début de l'épisode."""
        return self.episode.start

    @property
    def end(self) -> datetime:
        """La fin de l'épisode, son instant propre."""
        return self.episode.end


@dataclass(frozen=True)
class SleepWithin:
    """Ce que rend ``sleep_within`` : les épisodes entiers retenus (triés par début),
    le sommeil en secondes et la couverture (fraction), chacun absent avec son motif.

    Des deux champs de chaque paire, la vue en remplit exactement un : ``sleep_s`` ou
    ``sleep_absence`` ; ``coverage_fraction`` ou ``coverage_absence``."""

    start: datetime
    end: datetime
    episodes: tuple[SleepEpisode, ...]
    sleep_s: float | None
    sleep_absence: ViewAbsence | None
    coverage_fraction: float | None
    coverage_absence: ViewAbsence | None


def _union(
    intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """L'union d'intervalles, en intervalles disjoints triés."""
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _length_s(intervals: list[tuple[datetime, datetime]]) -> float:
    return sum((end - start) // _MICRO for start, end in intervals) / 1e6


def _intersection(
    a: list[tuple[datetime, datetime]], b: list[tuple[datetime, datetime]]
) -> list[tuple[datetime, datetime]]:
    out: list[tuple[datetime, datetime]] = []
    for a_start, a_end in a:
        for b_start, b_end in b:
            start, end = max(a_start, b_start), min(a_end, b_end)
            if start < end:
                out.append((start, end))
    return _union(out)


def _stage_intervals(
    night: Night, stages: tuple[SleepStage, ...]
) -> list[tuple[datetime, datetime]]:
    return [
        (_at(night.start, segment.start_s), _at(night.start, segment.end_s))
        for segment in night.segments
        if segment.stage in stages
    ]


def _episode_sleep(episode: Night | Nap) -> float | None:
    return episode.measured_sleep_s if isinstance(episode, Night) else episode.sleep_s


def _groups(episodes: list[SleepEpisode]) -> list[list[SleepEpisode]]:
    """Les groupes d'épisodes qui se recouvrent (intersection de durée non nulle)."""
    groups: list[list[SleepEpisode]] = []
    group_end: datetime | None = None
    for episode in episodes:
        if groups and group_end is not None and episode.start < group_end:
            groups[-1].append(episode)
            group_end = max(group_end, episode.end)
        else:
            groups.append([episode])
            group_end = episode.end
    return groups


def sleep_within(
    days: Sequence[DayRecord], start: datetime, end: datetime, *, strict: bool = False
) -> SleepWithin:
    """Le sommeil des épisodes entiers (nuits principales et siestes) **finis au plus
    tard à** ``end`` (``strict`` : strictement avant ``end``) qui **recoupent**
    ``[start, end]`` (fin de l'épisode au plus tôt ``start`` : la borne ``start`` est
    comprise), non coupés aux bornes.

    Deux conséquences, voulues : **le total peut compter du sommeil d'avant ``start``
    (une nuit commencée avant, finie dedans) ; un épisode presque entièrement dans
    [``start``, ``end``] mais fini après ``end`` n'est pas compté.**

    Chaque nuit rendue, et lue par le calcul, est **la nuit telle que connue à**
    ``end`` : ses séries coupées aux points d'instant au plus tard ``end`` et ses
    segments à ceux finis au plus tard ``end`` (``strict`` : strictement avant ``end``,
    pour les points comme pour les segments) ; un point ou un segment hors de sa fenêtre
    et après ``end`` n'est ni rendu ni compté. L'instant propre d'un point est son
    instant : un point agrégé que Garmin daterait par le début de son intervalle résume
    des mesures jusqu'à un pas après lui, donc, avec ``strict``, jusqu'à un pas après
    ``end``.

    Le sommeil d'une nuit est son sommeil mesuré (``Night.measured_sleep_s`` : profond
    + léger, plus le paradoxal s'il est détecté) ; celui d'une sieste, sa durée de
    sommeil selon Garmin (``Nap.sleep_s``). Les épisodes se rangent en groupes qui se
    recouvrent (intersection de durée non nulle ; deux épisodes qui se touchent ne se
    recouvrent pas) :

    - un épisode seul compte son sommeil ; leur somme fait le total ;
    - un groupe de plusieurs épisodes compte l'union, sur les segments de sommeil de
      ses nuits (profond, léger, paradoxal) et les fenêtres de ses siestes, **bornée
      par la somme** de leurs sommeils (le plus petit des deux).

    La couverture est la part de l'union des fenêtres des épisodes rendus qui n'est pas
    « non mesurable » : le non mesurable d'une nuit seule est son résumé
    (``Night.unmeasurable_s``) ; celui d'un groupe, l'union des segments
    ``unmeasurable`` de ses nuits dans l'union de ses fenêtres ; une fraction négative
    (un non mesurable de la source plus long que la nuit) est ramenée à 0.

    Motifs d'absence, le premier rencontré dans l'ordre des groupes : aucun épisode
    (``no_episode``, sommeil et couverture) ; une nuit d'un groupe de plusieurs
    épisodes sans segments (``no_segments``, sommeil et couverture) ; une nuit sans
    sommeil mesuré (``no_measured_sleep``, sommeil) ; une nuit seule sans non mesurable
    (``no_unmeasurable``, couverture). ``end`` doit valoir au moins ``start``.
    """
    _check_days(days)
    _check_instant(start, "start")
    _check_instant(end, "end")
    _check_strict(strict)
    if end < start:
        raise ValueError(f"end doit valoir au moins start, reçu {start!r}, {end!r}.")
    found: list[SleepEpisode] = []
    for record in days:
        candidates: list[Night | Nap] = [*record.naps]
        if record.night is not None:
            candidates.insert(0, record.night)
        for episode in candidates:
            if _visible(episode.end, end, strict) and episode.end >= start:
                if isinstance(episode, Night):
                    episode = _known(episode, end, strict)
                found.append(SleepEpisode(record.day, episode))
    episodes = sorted(found, key=lambda item: item.start)
    if not episodes:
        absent = ViewAbsence.NO_EPISODE
        return SleepWithin(start, end, (), None, absent, None, absent)
    sleep_absence: ViewAbsence | None = None
    coverage_absence: ViewAbsence | None = None
    total_sleep_s = 0.0
    window_s = 0.0
    unmeasured_s = 0.0
    for group in _groups(episodes):
        nights = [item.episode for item in group if isinstance(item.episode, Night)]
        windows = _union([(item.start, item.end) for item in group])
        window_s += _length_s(windows)
        if len(group) > 1 and any(not night.segments for night in nights):
            sleep_absence = sleep_absence or ViewAbsence.NO_SEGMENTS
            coverage_absence = coverage_absence or ViewAbsence.NO_SEGMENTS
            continue
        sleeps = [_episode_sleep(item.episode) for item in group]
        if any(value is None for value in sleeps):
            sleep_absence = sleep_absence or ViewAbsence.NO_MEASURED_SLEEP
        else:
            total = sum(value for value in sleeps if value is not None)
            if len(group) > 1:
                union = _union(
                    [
                        interval
                        for night in nights
                        for interval in _stage_intervals(night, _SLEEP_STAGES)
                    ]
                    + [
                        (item.start, item.end)
                        for item in group
                        if isinstance(item.episode, Nap)
                    ]
                )
                total = min(total, _length_s(union))
            total_sleep_s += total
        if len(group) == 1:
            episode = group[0].episode
            if isinstance(episode, Night):
                if episode.unmeasurable_s is None:
                    coverage_absence = coverage_absence or ViewAbsence.NO_UNMEASURABLE
                else:
                    unmeasured_s += episode.unmeasurable_s
        else:
            unmeasurable = _union(
                [
                    interval
                    for night in nights
                    for interval in _stage_intervals(night, (SleepStage.UNMEASURABLE,))
                ]
            )
            unmeasured_s += _length_s(_intersection(unmeasurable, windows))
    sleep_s = None if sleep_absence is not None else total_sleep_s
    coverage: float | None = None
    if coverage_absence is None:
        coverage = (
            0.0 if window_s <= 0 else max(0.0, (window_s - unmeasured_s) / window_s)
        )
    return SleepWithin(
        start,
        end,
        tuple(episodes),
        sleep_s,
        sleep_absence,
        coverage,
        coverage_absence,
    )


# ---------------------------------------------------------------------------
# body_battery_at, night_before, nights_after
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BodyBatteryReading:
    """Ce que rend ``body_battery_at`` : le dernier point de la série fusionnée (son
    instant, son niveau, son statut, s'il vient de la nuit, le jour du fichier qui le
    porte, son âge en secondes, sa provenance), ou le motif de son absence.

    ``absence`` est rempli si et seulement si les autres champs sont absents."""

    point_instant: datetime | None
    level: int | None
    status: BodyBatteryStatus | None
    from_night: bool | None
    day: date | None
    age_s: float | None
    source: SourceRef | None
    absence: ViewAbsence | None


def body_battery_at(
    days: Sequence[DayRecord], instant: datetime, *, strict: bool = False
) -> BodyBatteryReading:
    """Le dernier point de Body Battery au plus tard à ``instant`` (``strict`` :
    strictement avant), sur **une série fusionnée** :

    - les points de la série de la nuit (``NightSeries.body_battery``, sans statut) qui
      tombent **dans la fenêtre de leur nuit, fermée à ses deux bornes** ;
    - les points de la série de la journée (``DaySeries.body_battery``, avec statut)
      **hors de toutes ces fenêtres** (un point du jour à la borne d'une nuit cède la
      place à celui de la nuit) ;
    - seules comptent les nuits **finies au plus tard à** ``instant`` (``strict`` :
      avant) : une nuit en cours à ``instant`` n'a ni fenêtre ni points, et la série
      de la journée vaut à sa place ;
    - deux points au même instant (le recouvrement d'une heure de deux fenêtres de jour
      au changement d'heure ; deux nuits qui se recouvrent) : **le point du fichier du
      jour le plus ancien** est gardé.

    Rend l'instant du point, son niveau, son statut (``None`` pour un point de la
    nuit), s'il vient de la nuit, le jour du fichier, son âge (``instant`` − instant du
    point, en secondes) et sa provenance ; aucun point : absent, motif ``no_point``.
    Rien n'est interpolé : un trou de la série (le trou d'une heure de deux fenêtres de
    jour à l'automne) vieillit le dernier point.

    L'instant propre d'un point est son instant, avec ou sans ``strict`` : si Garmin
    date un point agrégé par le début de son intervalle, ce qu'il résume court jusqu'à
    un pas après lui, et ``strict`` laisse donc passer des mesures jusqu'à un pas après
    ``instant``.
    """
    _check_days(days)
    _check_instant(instant, "instant")
    _check_strict(strict)
    nights = [
        (record.day, record.night)
        for record in days
        if record.night is not None and _visible(record.night.end, instant, strict)
    ]
    windows = [(night.start, night.end) for _, night in nights]
    best: tuple[datetime, int, BodyBatteryReading] | None = None

    def offer(point: datetime, rank: int, reading: BodyBatteryReading) -> None:
        nonlocal best
        if not _visible(point, instant, strict):
            return
        if best is None or point > best[0] or (point == best[0] and rank < best[1]):
            best = (point, rank, reading)

    ranks = {record.day: rank for rank, record in enumerate(days)}
    for day, night in nights:
        series = night.series.body_battery
        if series is None:
            continue
        for time, level in zip(series.time_s, series.level, strict=True):
            point = _at(night.start, time)
            if night.start <= point <= night.end:
                offer(
                    point,
                    ranks[day],
                    BodyBatteryReading(
                        point, level, None, True, day, None, series.source, None
                    ),
                )
    for record in days:
        series = record.series.body_battery
        if series is None or record.window_start is None:
            continue
        for time, level, status in zip(
            series.time_s, series.level, series.status, strict=True
        ):
            point = _at(record.window_start, time)
            if any(start <= point <= end for start, end in windows):
                continue
            offer(
                point,
                ranks[record.day],
                BodyBatteryReading(
                    point, level, status, False, record.day, None, series.source, None
                ),
            )
    if best is None:
        return BodyBatteryReading(
            None, None, None, None, None, None, None, ViewAbsence.NO_POINT
        )
    point, _, reading = best
    return dataclasses.replace(reading, age_s=(instant - point).total_seconds())


@dataclass(frozen=True)
class NightBefore:
    """Ce que rend ``night_before`` : la nuit, son jour (celui du réveil), l'écart
    (``instant`` − fin de la nuit, en secondes, ``>= 0``), ou le motif de son
    absence."""

    day: date | None
    night: Night | None
    gap_s: float | None
    absence: ViewAbsence | None


def night_before(
    days: Sequence[DayRecord], instant: datetime, *, strict: bool = False
) -> NightBefore:
    """La dernière nuit principale **finie au plus tard à** ``instant`` (une nuit
    finie à l'instant même entre ; ``strict`` : finie strictement avant), son jour et
    l'écart ``instant`` − fin, en secondes. La dernière : la plus grande fin ; à fins
    égales, la dernière dans l'ordre des jours. Aucune : absente, motif
    ``no_night_before``.

    La nuit rendue est **la nuit telle que connue à** ``instant`` : ses séries coupées
    aux points d'instant au plus tard ``instant`` et ses segments à ceux finis au plus
    tard ``instant`` (``strict`` : strictement avant ``instant``, pour les points comme
    pour les segments) ; un point ou un segment hors de sa fenêtre et après ``instant``
    n'est pas rendu. Fenêtre, durées et résumés sont ceux de la nuit (son instant propre
    est sa fin). L'instant propre d'un point est son instant : un point agrégé que
    Garmin daterait par le début de son intervalle résume des mesures jusqu'à un pas
    après lui, donc, avec ``strict``, jusqu'à un pas après ``instant``.
    """
    _check_days(days)
    _check_instant(instant, "instant")
    _check_strict(strict)
    chosen: DayRecord | None = None
    for record in days:
        night = record.night
        if night is None or not _visible(night.end, instant, strict):
            continue
        if chosen is None or chosen.night is None or night.end >= chosen.night.end:
            chosen = record
    if chosen is None or chosen.night is None:
        return NightBefore(None, None, None, ViewAbsence.NO_NIGHT_BEFORE)
    night = _known(chosen.night, instant, strict)
    return NightBefore(chosen.day, night, (instant - night.end).total_seconds(), None)


@dataclass(frozen=True)
class NightAfter:
    """Une nuit rendue par ``nights_after`` : son jour (celui du réveil), la nuit, et
    le délai de sa fin après ``after`` (secondes, ``> 0``)."""

    day: date
    night: Night
    delay_s: float


def nights_after(
    days: Sequence[DayRecord], after: datetime, count: int
) -> tuple[NightAfter, ...]:
    """Les ``count`` premières nuits principales **finies strictement après**
    ``after``, dans l'ordre de leur fin (à fins égales, l'ordre des jours) ; moins
    s'il n'y en a pas assez, aucune s'il n'y en a pas.

    **Hors de la règle commune**, à dessein : cette vue lit ce qui suit ``after``.
    C'est une vue d'**analyse rétrospective** (la piste : ce qui suit un événement),
    **jamais de prévision** : aucune vue prise à un instant ne doit l'appeler, et le
    moteur ne la lit pas. Une nuit finie à ``after`` même n'en est pas (elle est à
    ``night_before``).
    """
    _check_days(days)
    _check_instant(after, "after")
    _check_count(count, "count")
    found = [
        NightAfter(record.day, record.night, (record.night.end - after).total_seconds())
        for record in days
        if record.night is not None and record.night.end > after
    ]
    found.sort(key=lambda item: item.night.end)
    return tuple(found[:count])


# ---------------------------------------------------------------------------
# training_status_at, readiness_at
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StatusReading:
    """Ce que rend ``training_status_at`` : la sorte, le dernier bloc et son âge
    (``instant`` − instant propre du bloc, en secondes), ou le motif de son absence."""

    kind: TrainingStatusKind
    block: StatusBlock | None
    age_s: float | None
    absence: ViewAbsence | None


def _suite(history: TrainingStatusHistory, kind: TrainingStatusKind) -> Sequence[Any]:
    return {
        TrainingStatusKind.STATUS: history.statuses,
        TrainingStatusKind.LOAD_BALANCE: history.load_balances,
        TrainingStatusKind.VO2_MAX: history.vo2_max,
        TrainingStatusKind.HEAT_ACCLIMATION: history.heat_acclimation,
        TrainingStatusKind.ALTITUDE_ACCLIMATION: history.altitude_acclimation,
    }[kind]


def training_status_at(
    history: TrainingStatusHistory,
    kind: TrainingStatusKind,
    instant: datetime,
    *,
    strict: bool = False,
) -> StatusReading:
    """Le dernier bloc de Training Status de la sorte ``kind`` dont l'instant propre
    (``proper_instant``, calculé à l'ingestion : l'horodatage du statut ; sinon la fin
    de la fenêtre du jour de sa date propre, celle des grandeurs ``day`` ; sans fenêtre
    de ce jour, le début de la fenêtre du lendemain si ce lendemain a une fenêtre ;
    sinon le minuit local qui suit sa date, au décalage du jour du fichier choisi) est
    **au plus tard** ``instant`` (``strict`` : strictement avant), et son âge en
    secondes. Le seul instant propre qui lit un autre jour : celui d'un bloc sans
    horodatage ni fenêtre de son jour ; la vue dépend alors de ce que le lendemain a
    une fenêtre (de l'écart des deux décalages, une heure au changement d'heure).

    **Un bloc sans instant propre n'est jamais rendu** ; un bloc sans horodatage daté
    de D, avec ``instant`` au matin de D, ne l'est pas (son instant propre est la fin
    du jour D). Le dernier : le plus grand instant propre ; à instants égaux, le
    dernier de la suite (la date propre la plus récente). Aucun : absent, motif
    ``no_block``.
    """
    if not isinstance(kind, TrainingStatusKind):
        raise ValueError(f"kind doit être un TrainingStatusKind, reçu {kind!r}.")
    _check_instant(instant, "instant")
    _check_strict(strict)
    chosen: StatusBlock | None = None
    for block in _suite(history, kind):
        proper = block.proper_instant
        if proper is None or not _visible(proper, instant, strict):
            continue
        if (
            chosen is None
            or chosen.proper_instant is None
            or proper >= chosen.proper_instant
        ):
            chosen = block
    if chosen is None or chosen.proper_instant is None:
        return StatusReading(kind, None, None, ViewAbsence.NO_BLOCK)
    return StatusReading(
        kind, chosen, (instant - chosen.proper_instant).total_seconds(), None
    )


@dataclass(frozen=True)
class ReadinessReading:
    """Ce que rend ``readiness_at`` : la dernière entrée, le jour du document qui la
    porte, son âge (``instant`` − horodatage, en secondes), ou le motif de son
    absence."""

    day: date | None
    entry: ReadinessEntry | None
    age_s: float | None
    absence: ViewAbsence | None


def readiness_at(
    days: Sequence[DayRecord], instant: datetime, *, strict: bool = False
) -> ReadinessReading:
    """La dernière entrée de Training Readiness d'horodatage **au plus tard**
    ``instant`` (``strict`` : strictement avant ; Q9 l'appelle au départ avec
    ``strict`` vrai), tous contextes confondus, et son âge en secondes. La dernière :
    le plus grand horodatage ; à horodatages égaux, la dernière dans l'ordre des
    jours puis des entrées. Aucune : absente, motif
    ``no_entry``.
    """
    _check_days(days)
    _check_instant(instant, "instant")
    _check_strict(strict)
    chosen: tuple[date, ReadinessEntry] | None = None
    for record in days:
        for entry in record.readiness:
            if not _visible(entry.instant, instant, strict):
                continue
            if chosen is None or entry.instant >= chosen[1].instant:
                chosen = (record.day, entry)
    if chosen is None:
        return ReadinessReading(None, None, None, ViewAbsence.NO_ENTRY)
    day, entry = chosen
    return ReadinessReading(day, entry, (instant - entry.instant).total_seconds(), None)


# ---------------------------------------------------------------------------
# night_assessment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NightAssessment:
    """Ce que rend ``night_assessment`` pour un jour : l'état de sa nuit, ses deux
    drapeaux (chacun vrai, faux, ou inconnu avec son motif), et les grandeurs qui les
    décident.

    - ``measured_sleep_s`` — secondes — le sommeil mesuré de la nuit ;
    - ``unmeasured_fraction`` — fraction — non mesurable / (fin − début) ;
    - ``midpoint_s`` — secondes depuis minuit — le milieu de la nuit en heure locale de
      la source (milieu des deux heures murales de ses bornes) ;
    - ``usual_midpoint_s`` — secondes depuis minuit, dans ``[0, 86400)`` — le milieu
      habituel (moyenne circulaire ; minuit vaut 0, jamais 86 400), absent sans nuit
      admise ou si leurs milieux n'ont pas de moyenne circulaire ; ``usual_nights`` —
      les nuits qui y entrent ;
    - ``midpoint_distance_s`` — secondes, dans ``[0, 43200]`` — l'écart circulaire
      entre les deux milieux."""

    day: date
    state: NightState
    short: bool | None
    short_absence: ViewAbsence | None
    shifted: bool | None
    shifted_absence: ViewAbsence | None
    measured_sleep_s: float | None
    unmeasured_fraction: float | None
    midpoint_s: float | None
    usual_midpoint_s: float | None
    usual_nights: int
    midpoint_distance_s: float | None

    @property
    def flags(self) -> tuple[NightFlag, ...]:
        """Les drapeaux posés (vrais), dans l'ordre de ``NightFlag``."""
        posed = {NightFlag.SHORT: self.short, NightFlag.SHIFTED: self.shifted}
        return tuple(flag for flag in NightFlag if posed[flag] is True)


def _record(days: Sequence[DayRecord], day: date) -> DayRecord | None:
    for record in days:
        if record.day == day:
            return record
    return None


def _unmeasured_fraction(night: Night) -> float | None:
    if night.unmeasurable_s is None:
        return None
    return night.unmeasurable_s / (night.end - night.start).total_seconds()


def _night_state(record: DayRecord, max_unmeasured_fraction: float) -> NightState:
    night = record.night
    if night is None:
        return NightState.MISSING
    if night.from_device is False:
        return NightState.DECLARED
    late = record.data_end is not None and night.end > record.data_end
    if late or night.window_confirmed is False:
        return NightState.IN_PROGRESS
    fraction = _unmeasured_fraction(night)
    if fraction is None or fraction > max_unmeasured_fraction:
        return NightState.PARTIAL
    return NightState.COMPLETE


def _midpoint_s(night: Night) -> float:
    """Le milieu des deux heures murales des bornes de la nuit, en secondes depuis
    minuit (heure locale de la source)."""
    start = night.start.replace(tzinfo=None)
    end = night.end.replace(tzinfo=None)
    middle = start + (end - start) / 2
    since = middle - datetime(middle.year, middle.month, middle.day)
    return since / _MICRO / 1e6


def _circular_mean_s(midpoints: list[float]) -> float | None:
    """La moyenne circulaire de milieux sur 24 h, dans ``[0, 86400)`` ; ``None`` si la
    résultante est nulle à la garde numérique près."""
    angles = [2 * math.pi * value / _DAY_S for value in midpoints]
    cos_sum = sum(math.cos(angle) for angle in angles)
    sin_sum = sum(math.sin(angle) for angle in angles)
    if math.hypot(cos_sum, sin_sum) / len(midpoints) <= _RESULTANT_GUARD:
        return None
    mean = math.atan2(sin_sum, cos_sum) / (2 * math.pi) * _DAY_S % _DAY_S
    return 0.0 if mean >= _DAY_S else mean


def _circular_distance_s(a: float, b: float) -> float:
    distance = abs(a - b) % _DAY_S
    return min(distance, _DAY_S - distance)


def night_assessment(
    days: Sequence[DayRecord],
    day: date,
    *,
    max_unmeasured_fraction: float,
    short_sleep_s: float,
    shift_s: float,
    usual_window_days: int,
    usual_min_nights: int,
) -> NightAssessment:
    """L'état de la nuit rattachée à ``day`` et ses drapeaux.

    **État, dans l'ordre de** ``NightState`` (le premier qui s'applique) :

    1. ``missing`` : pas de document pour ``day``, ou pas de nuit ;
    2. ``declared`` : la source ne la dit pas venue de la montre (``from_device`` faux ;
       inconnu n'est pas faux) ;
    3. ``in_progress`` : la nuit finit **strictement après** ``data_end`` du jour, ou
       la source ne dit pas sa fenêtre confirmée (``window_confirmed`` faux) ; sans
       ``data_end`` (jour ``empty``), seulement la seconde ;
    4. ``partial`` : la part non mesurable (``unmeasurable_s`` / (fin − début))
       **dépasse strictement** ``max_unmeasured_fraction`` (une part égale au seuil
       n'est pas partielle) ; un non mesurable absent : ``partial`` (la part n'est pas
       connue, la nuit n'est pas dite complète) ;
    5. ``complete``.

    **Drapeaux** (indépendants de l'état) :

    - ``short`` : sommeil mesuré **strictement sous** ``short_sleep_s`` (égal : pas
      courte) ; sommeil mesuré absent : inconnu, motif ``no_measured_sleep`` ;
    - ``shifted`` : écart circulaire entre le milieu de la nuit et le milieu habituel
      **strictement au-dessus de** ``shift_s`` (égal : pas décalée). Le milieu
      habituel est la **moyenne circulaire** (sur 24 h) des milieux, en heures locales
      de la source, des nuits ``complete`` et non ``short`` (sommeil mesuré
      connu, au moins ``short_sleep_s``) des jours ``[day − usual_window_days,
      day − 1]`` ; **inconnu** (motif ``below_usual_minimum``) s'il y en a strictement
      moins que ``usual_min_nights`` (``usual_min_nights`` nuits suffisent) ;
      **inconnu** aussi (motif ``dispersed_midpoints``) si leurs milieux n'ont pas de
      moyenne circulaire : résultante nulle à une **garde numérique** près (sa
      longueur rapportée au nombre de nuits au plus ``1e-12``, ``_RESULTANT_GUARD``),
      qui sépare zéro du bruit d'arrondi et n'est pas un seuil (des milieux également
      répartis sur 24 h). Le milieu habituel rendu (``usual_midpoint_s``) est dans
      ``[0, 86400)`` : minuit vaut 0, jamais 86 400.

    Pas de nuit : les deux drapeaux inconnus, motif ``no_night``. Motifs de ``shifted``,
    dans cet ordre : ``no_night``, ``below_usual_minimum``, ``dispersed_midpoints``.

    Seuils : ``max_unmeasured_fraction`` dans ``[0, 1]`` ; ``short_sleep_s`` et
    ``shift_s`` en secondes, ``>= 0`` ; ``usual_window_days`` et ``usual_min_nights``
    entiers ``>= 1`` ; tous finis, sans défaut.
    """
    _check_days(days)
    _check_day(day, "day")
    _check_fraction(max_unmeasured_fraction, "max_unmeasured_fraction")
    _check_duration(short_sleep_s, "short_sleep_s")
    _check_duration(shift_s, "shift_s")
    _check_count(usual_window_days, "usual_window_days")
    _check_count(usual_min_nights, "usual_min_nights")
    first = day - timedelta(days=usual_window_days)
    usual: list[float] = []
    for record in days:
        if not first <= record.day < day or record.night is None:
            continue
        measured = record.night.measured_sleep_s
        complete = _night_state(record, max_unmeasured_fraction) is NightState.COMPLETE
        if complete and measured is not None and measured >= short_sleep_s:
            usual.append(_midpoint_s(record.night))
    usual_midpoint = _circular_mean_s(usual) if usual else None
    own = _record(days, day)
    night = None if own is None else own.night
    if own is None or night is None:
        return NightAssessment(
            day=day,
            state=NightState.MISSING,
            short=None,
            short_absence=ViewAbsence.NO_NIGHT,
            shifted=None,
            shifted_absence=ViewAbsence.NO_NIGHT,
            measured_sleep_s=None,
            unmeasured_fraction=None,
            midpoint_s=None,
            usual_midpoint_s=usual_midpoint,
            usual_nights=len(usual),
            midpoint_distance_s=None,
        )
    measured = night.measured_sleep_s
    short = None if measured is None else measured < short_sleep_s
    midpoint = _midpoint_s(night)
    distance = (
        None
        if usual_midpoint is None
        else _circular_distance_s(midpoint, usual_midpoint)
    )
    shifted: bool | None = None
    shifted_absence: ViewAbsence | None = None
    if len(usual) < usual_min_nights:
        shifted_absence = ViewAbsence.BELOW_USUAL_MINIMUM
    elif distance is None:
        shifted_absence = ViewAbsence.DISPERSED_MIDPOINTS
    else:
        shifted = distance > shift_s
    return NightAssessment(
        day=day,
        state=_night_state(own, max_unmeasured_fraction),
        short=short,
        short_absence=None if short is not None else ViewAbsence.NO_MEASURED_SLEEP,
        shifted=shifted,
        shifted_absence=shifted_absence,
        measured_sleep_s=measured,
        unmeasured_fraction=_unmeasured_fraction(night),
        midpoint_s=midpoint,
        usual_midpoint_s=usual_midpoint,
        usual_nights=len(usual),
        midpoint_distance_s=distance,
    )


# ---------------------------------------------------------------------------
# La FC de repos, la Training Readiness du réveil
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RestingHrDay:
    """Ce que rend ``resting_hr_on`` : la FC de repos d'un jour (bpm ; absente quand le
    statut est ``absent``), son statut, et l'instant propre du jour (la fin de sa
    fenêtre : le plus tard de son début + 24 h et de sa fin des données ; absent sans
    fenêtre)."""

    day: date
    resting_hr_bpm: float | None
    status: RestingHrStatus
    proper_instant: datetime | None


def _resting_status(
    record: DayRecord | None, min_sleep_s: float, night: Night | None
) -> RestingHrStatus:
    if (
        record is None
        or record.resting_hr is None
        or record.state in (DayState.EMPTY, DayState.NO_MEASUREMENT)
    ):
        return RestingHrStatus.ABSENT
    if record.state is DayState.TRUNCATED:
        return RestingHrStatus.PROVISIONAL
    measured = None if night is None else night.measured_sleep_s
    if measured is None or measured < min_sleep_s:
        return RestingHrStatus.NO_NIGHT
    return RestingHrStatus.VALID


def resting_hr_on(
    days: Sequence[DayRecord], day: date, *, min_sleep_s: float
) -> RestingHrDay:
    """La FC de repos selon Garmin du jour ``day``, son statut et l'instant propre du
    jour (publique, pour un écart à une normale).

    **Statut, dans l'ordre de** ``RestingHrStatus`` (le premier qui s'applique) :

    1. ``absent`` : pas de document pour ``day``, valeur absente, ou jour ``empty`` ou
       ``no_measurement`` (même s'il porte une valeur : elle n'est pas rendue) ;
    2. ``provisional`` : jour ``truncated``, qu'il ait une nuit ou non ;
    3. ``no_night`` : pas de nuit rattachée au jour, ou son sommeil mesuré absent, ou
       **strictement sous** ``min_sleep_s`` (égal : la nuit suffit) ;
    4. ``valid``.

    Seuil : ``min_sleep_s`` en secondes, fini, ``>= 0``, sans défaut. L'instant propre
    est la fin de la fenêtre du jour : le plus tard de son début + 24 h et de sa fin des
    données, lue dans le seul document du jour (un jour de 25 h complet : le minuit
    local qui suit ; un jour tronqué : début + 24 h ; le jour du passage à l'heure
    d'hiver dont les données finissent au plus tard à début + 24 h : début + 24 h, au
    plus une heure avant son minuit local ; entre les deux : sa fin des données) ;
    absent sans fenêtre.
    """
    _check_days(days)
    _check_day(day, "day")
    _check_duration(min_sleep_s, "min_sleep_s")
    record = _record(days, day)
    status = _resting_status(
        record, min_sleep_s, None if record is None else record.night
    )
    value = (
        None
        if status is RestingHrStatus.ABSENT
        or record is None
        or record.resting_hr is None
        else record.resting_hr.resting_hr_bpm
    )
    proper = None if record is None else _day_end(record)
    return RestingHrDay(day, value, status, proper)


@dataclass(frozen=True)
class RestingHrReading:
    """Ce que rend ``resting_hr_at`` : la dernière FC de repos (bpm), son jour, son
    statut, l'instant propre du jour, son âge (``instant`` − instant propre, en
    secondes), ou le motif de son absence."""

    day: date | None
    resting_hr_bpm: float | None
    status: RestingHrStatus | None
    proper_instant: datetime | None
    age_s: float | None
    absence: ViewAbsence | None


def resting_hr_at(
    days: Sequence[DayRecord],
    instant: datetime,
    *,
    min_sleep_s: float,
    strict: bool = False,
) -> RestingHrReading:
    """La dernière FC de repos **de statut autre qu'** ``absent`` d'un jour dont la
    fenêtre finit **au plus tard à** ``instant`` (``strict`` : strictement avant), avec
    son jour, son statut et son âge (la forme que lit M7). La fin de la fenêtre est
    celle de ``resting_hr_on`` : le plus tard du début + 24 h et de la fin des données,
    jamais lue dans le document du lendemain ; avec ``strict`` au minuit local qui suit
    un jour de 25 h complet, ce jour n'est pas rendu.

    Le statut est celui de ``resting_hr_on`` (même seuil ``min_sleep_s``, même borne :
    sommeil mesuré **strictement sous** ``min_sleep_s`` → ``no_night``), à une
    différence près, pour la règle commune : une nuit finie après ``instant`` (ou à
    ``instant`` avec ``strict``) ne compte pas (``no_night``). La dernière : la plus
    grande fin de fenêtre ; à fins égales, le dernier jour. Aucune : absente, motif
    ``no_resting_hr``.
    """
    _check_days(days)
    _check_instant(instant, "instant")
    _check_duration(min_sleep_s, "min_sleep_s")
    _check_strict(strict)
    chosen: RestingHrReading | None = None
    for record in days:
        proper = _day_end(record)
        if proper is None or not _visible(proper, instant, strict):
            continue
        night = record.night
        if night is not None and not _visible(night.end, instant, strict):
            night = None
        status = _resting_status(record, min_sleep_s, night)
        if status is RestingHrStatus.ABSENT or record.resting_hr is None:
            continue
        if (
            chosen is None
            or chosen.proper_instant is None
            or proper >= chosen.proper_instant
        ):
            chosen = RestingHrReading(
                record.day,
                record.resting_hr.resting_hr_bpm,
                status,
                proper,
                (instant - proper).total_seconds(),
                None,
            )
    if chosen is None:
        return RestingHrReading(None, None, None, None, None, ViewAbsence.NO_RESTING_HR)
    return chosen


@dataclass(frozen=True)
class WakingReadiness:
    """Ce que rend ``readiness_on_waking`` : l'entrée « réveil » retenue, la fin de la
    nuit, ou le motif de son absence."""

    day: date
    entry: ReadinessEntry | None
    night_end: datetime | None
    absence: ViewAbsence | None


def readiness_on_waking(
    days: Sequence[DayRecord], day: date, *, tolerance_s: float
) -> WakingReadiness:
    """La Training Readiness du réveil du jour ``day`` : **la première** entrée du
    document de ``day`` de contexte « réveil » (``WAKING_CONTEXT``) dont l'instant est
    **au moins** la fin de la nuit moins ``tolerance_s`` (une entrée à exactement
    ``tolerance_s`` avant la fin entre ; une entrée après la fin aussi), et
    **strictement avant le début de la sieste suivante** (la première sieste du jour qui
    commence au plus tôt à la fin de la nuit ; sans elle, pas de borne).

    Pas de document ou pas de nuit : absente, motif ``no_night`` ; aucune entrée :
    absente, motif ``no_entry_after_night`` ; jamais de repli sur une autre entrée.

    Seuil : ``tolerance_s`` en secondes, fini, ``>= 0``, sans défaut ; comparé à
    fin de la nuit − instant de l'entrée, en secondes.
    """
    _check_days(days)
    _check_day(day, "day")
    _check_duration(tolerance_s, "tolerance_s")
    record = _record(days, day)
    if record is None or record.night is None:
        return WakingReadiness(day, None, None, ViewAbsence.NO_NIGHT)
    end = record.night.end
    following = [nap.start for nap in record.naps if nap.start >= end]
    bound = min(following) if following else None
    for entry in record.readiness:
        if entry.input_context != WAKING_CONTEXT:
            continue
        if (end - entry.instant).total_seconds() > tolerance_s:
            continue
        if bound is not None and not entry.instant < bound:
            continue
        return WakingReadiness(day, entry, end, None)
    return WakingReadiness(day, None, end, ViewAbsence.NO_ENTRY_AFTER_NIGHT)


# ---------------------------------------------------------------------------
# series_between
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeriesPoint:
    """Un point rendu par ``series_between`` : son instant, sa valeur dans l'unité de
    la série (``SERIES_KIND_DESCRIPTIONS`` ; absente quand le point porte un code), son
    code sentinelle, son statut (Body Battery de la journée), et le jour du fichier qui
    le porte."""

    instant: datetime
    value: float | None
    code: int | None
    status: BodyBatteryStatus | None
    day: date


@dataclass(frozen=True)
class SeriesWindow:
    """Ce que rend ``series_between`` : les points dédoublonnés de l'intervalle (vides
    si la série est absente), la couverture (fraction, toujours rendue), le nombre de
    points écartés comme doublons d'instant, et le motif d'absence."""

    kind: SeriesKind
    start: datetime
    end: datetime
    points: tuple[SeriesPoint, ...]
    coverage_fraction: float
    duplicates: int
    absence: ViewAbsence | None


_SERIES_FIELDS = {
    SeriesKind.DAY_HEART_RATE: "heart_rate",
    SeriesKind.DAY_STRESS: "stress",
    SeriesKind.DAY_BODY_BATTERY: "body_battery",
    SeriesKind.DAY_RESPIRATION: "respiration",
    SeriesKind.DAY_SPO2: "spo2",
    SeriesKind.NIGHT_HEART_RATE: "heart_rate",
    SeriesKind.NIGHT_STRESS: "stress",
    SeriesKind.NIGHT_BODY_BATTERY: "body_battery",
    SeriesKind.NIGHT_HRV: "hrv",
    SeriesKind.NIGHT_RESPIRATION: "respiration",
    SeriesKind.NIGHT_SPO2: "spo2",
    SeriesKind.NIGHT_RESTLESS_MOMENTS: "restless_moments",
}


def _series_points(
    series: DaySeriesItem, origin: datetime, day: date
) -> list[SeriesPoint]:
    """Les points d'une série, en instants, avec leur valeur, leur code, leur statut."""
    times = [_at(origin, time) for time in series.time_s]
    count = len(times)
    values: tuple[Any, ...]
    codes: tuple[int | None, ...] = (None,) * count
    statuses: tuple[BodyBatteryStatus | None, ...] = (None,) * count
    match series:
        case HeartRateSeries():
            values = series.heart_rate_bpm
        case StressSeries():
            values, codes = series.stress_level, series.code
        case BodyBatterySeries():
            values, statuses = series.level, series.status
        case RespirationSeries():
            values, codes = series.breaths_per_min, series.code
        case SpO2Series():
            values = series.spo2_percent
        case HrvSeries():
            values = series.hrv_ms
        case RestlessMomentsSeries():
            values = series.count
    return [
        SeriesPoint(instant, value, code, status, day)
        for instant, value, code, status in zip(
            times, values, codes, statuses, strict=True
        )
    ]


def series_between(
    days: Sequence[DayRecord],
    kind: SeriesKind,
    start: datetime,
    end: datetime,
    *,
    step_s: float,
    min_coverage_fraction: float,
    strict: bool = False,
) -> SeriesWindow:
    """Les points de la série ``kind`` (de la journée, ou de la nuit) d'instant dans
    ``[start, end]`` (``strict`` : ``[start, end)``), pris dans tous les documents,
    et sa couverture.

    - Une série de la nuit ne compte que si sa nuit est **finie au plus tard à**
      ``end`` (``strict`` : strictement avant ``end``, comme ses points) : la règle
      commune, à la borne ``end``.
    - L'instant propre d'un point est son instant : si Garmin date un point agrégé par
      le début de son intervalle, ce qu'il résume court jusqu'à un pas après lui, et
      ``strict`` laisse donc passer des mesures jusqu'à un pas après ``end``.
    - **Dédoublonnage par instant** : deux points au même instant (deux fichiers
      voisins, le recouvrement d'une heure au changement d'heure) : **le point du
      fichier du jour le plus ancien est gardé**, les autres sont comptés
      (``duplicates``) et écartés. Rien n'est interpolé ni comblé.
    - **Couverture** : la part de ``[start, end]`` sous l'union des ``[tᵢ, tᵢ +
      step_s)`` des points gardés (fraction ; un point avant ``start`` n'y entre pas).
    - Absente, points vides : aucun point (motif ``no_point``) ; sinon couverture
      **strictement sous** ``min_coverage_fraction`` (motif ``below_coverage`` ; une
      couverture égale au minimum suffit).

    Seuils : ``step_s`` en secondes, fini, ``> 0`` ; ``min_coverage_fraction`` dans
    ``[0, 1]`` ; sans défaut. ``end`` doit suivre ``start`` strictement.
    """
    _check_days(days)
    if not isinstance(kind, SeriesKind):
        raise ValueError(f"kind doit être un SeriesKind, reçu {kind!r}.")
    _check_instant(start, "start")
    _check_instant(end, "end")
    _check_step(step_s, "step_s")
    _check_fraction(min_coverage_fraction, "min_coverage_fraction")
    _check_strict(strict)
    if not end > start:
        raise ValueError(f"end doit suivre start, reçu {start!r}, {end!r}.")
    name = _SERIES_FIELDS[kind]
    night_kind = kind.value.startswith("night_")
    kept: dict[datetime, SeriesPoint] = {}
    duplicates = 0
    for record in days:
        series: DaySeriesItem | None
        if night_kind:
            night = record.night
            if night is None or not _visible(night.end, end, strict):
                continue
            series, origin = getattr(night.series, name), night.start
        else:
            if record.window_start is None:
                continue
            series, origin = getattr(record.series, name), record.window_start
        if series is None:
            continue
        for point in _series_points(series, origin, record.day):
            inside = start <= point.instant and (
                point.instant < end if strict else point.instant <= end
            )
            if not inside:
                continue
            if point.instant in kept:
                duplicates += 1
                continue
            kept[point.instant] = point
    points = tuple(sorted(kept.values(), key=lambda point: point.instant))
    length_s = (end - start).total_seconds()
    covered = 0.0
    reach = 0.0
    for point in points:
        begin = (point.instant - start).total_seconds()
        finish = min(begin + step_s, length_s)
        begin = max(begin, reach)
        if finish > begin:
            covered += finish - begin
            reach = finish
    coverage = covered / length_s
    if not points:
        return SeriesWindow(kind, start, end, (), 0.0, duplicates, ViewAbsence.NO_POINT)
    if coverage < min_coverage_fraction:
        return SeriesWindow(
            kind, start, end, (), coverage, duplicates, ViewAbsence.BELOW_COVERAGE
        )
    return SeriesWindow(kind, start, end, points, coverage, duplicates, None)
