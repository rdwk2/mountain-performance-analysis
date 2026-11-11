"""La règle d'estimation à l'origine (OG-1, ``docs/decisions/0020``) : **la courbe à
l'origine ne lit que ce qui a fini avant l'origine.**

La chaîne, dans cet ordre :

1. **les fins** d'une activité (:func:`activity_end`) : celle de l'index, celle de
   l'enregistrement, et la fin sûre, la plus tardive des deux ;
2. **la sélection** (:func:`select_at_origin`) : une activité entre en entier ou pas du
   tout ;
3. **l'estimation** (:func:`estimate_at_origin`), celle de ``0017``, des candidates ;
4. **l'issue** : absence, courbe non projetable, ou courbe projetable.

Un noyau déterministe : sans horloge, sans git, sans fichier ni environnement.
L'appelant charge le corpus de l'athlète et l'atteste (:class:`CurveCorpus`).

Python pur : ni ``analyse/`` ni ``backtest/``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal, Protocol
from zoneinfo import ZoneInfo

from mountain_perf.estimation.curve import (
    SUPPORT_THRESHOLD_MIN,
    ActivityFate,
    CurveEstimate,
    CurveSelection,
    NoCurve,
    curve_file_rows,
    estimate_curve_outcome,
)
from mountain_perf.estimation.intervals import (
    ActivityIntervals,
    TraceRefusal,
    activity_intervals,
)
from mountain_perf.ingest.types import SOURCE_TYPE_SPORTS
from mountain_perf.model.curve_io import CurveFileRow, check_curve_rows
from mountain_perf.schemas import (
    SUPPORT_THRESHOLD_RANGE_MIN,
    ActivityIndex,
    ActivityRecording,
    IndexedActivity,
    ParameterSet,
    Sport,
)
from mountain_perf.validation import (
    ContractError,
    require_aware,
    require_finite,
    require_in_range,
    require_non_empty,
)

PARIS: Final = ZoneInfo("Europe/Paris")
"""Le fuseau des origines et des bornes de la fenêtre (``0010`` D0, D2.5)."""

_HEXADECIMAL: Final = frozenset("0123456789abcdef")
_SHA256_LENGTH: Final = 64


class EndMethod(StrEnum):
    """D'où vient la fin sûre d'une activité."""

    BOTH = "index et enregistrement"
    INFERRED = "fin inférée"
    INDEX_ONLY = "index seul"
    UNKNOWN = "fin inconnue"


@dataclass(frozen=True)
class ActivityEnd:
    """Les fins d'une activité, instants en UTC : une convention conservatrice de fin
    connue, pas une certification de la fin physique.

    - ``activity_ref`` — sans unité — l'activité ;
    - ``index_start``, ``index_end`` — instants — le départ de l'index, et ce départ
      plus l'écoulé de l'index (``None`` sans écoulé) ;
    - ``recording_start``, ``recording_end`` — instants — le départ et la fin de
      l'enregistrement (``None`` sans enregistrement) ;
    - ``safe_end`` — instant — la plus tardive des deux fins, ``None`` sans aucune ;
    - ``method`` — sans unité — celles qui sont présentes.
    """

    activity_ref: str
    index_start: datetime
    index_end: datetime | None
    recording_start: datetime | None
    recording_end: datetime | None
    safe_end: datetime | None
    method: EndMethod

    @property
    def disagreement_s(self) -> float | None:
        """La fin de l'enregistrement moins celle de l'index, en secondes ; ``None``
        sans les deux."""
        if self.index_end is None or self.recording_end is None:
            return None
        return (self.recording_end - self.index_end).total_seconds()


def recording_end(recording: ActivityRecording) -> datetime | None:
    """La fin d'un enregistrement : son départ décalé du plus grand de ses instants —
    le dernier échantillon de chacun de ses canaux, le départ de chaque session et, si
    elle a un écoulé, sa fin, chaque événement du chronomètre. Jamais la somme des
    écoulés : des sessions peuvent être disjointes ou se recouvrir. ``None`` sans aucun
    instant."""
    channels = (
        recording.position,
        recording.elevation,
        recording.distance,
        recording.heart_rate,
        recording.speed,
        recording.temperature,
    )
    offsets = [channel.time_s[-1] for channel in channels if channel is not None]
    for session in recording.sessions:
        offsets.append(session.start_s)
        if session.elapsed_duration_s is not None:
            offsets.append(session.start_s + session.elapsed_duration_s)
    offsets.extend(event.time_s for event in recording.timer_events)
    if not offsets:
        return None
    return recording.start_time + timedelta(seconds=max(offsets))


def activity_end(
    entry: IndexedActivity, recording: ActivityRecording | None
) -> ActivityEnd:
    """Les fins de l'activité ``entry``, avec son enregistrement s'il est donné ; celui
    d'une autre activité lève ``ContractError``."""
    if recording is not None and recording.activity_ref != entry.activity_ref:
        raise ContractError(
            f"activity_end : l'enregistrement {recording.activity_ref} n'est pas celui "
            f"de l'activité {entry.activity_ref}."
        )
    index_start = entry.start_time.astimezone(UTC)
    index_end = (
        None
        if entry.elapsed_duration_s is None
        else index_start + timedelta(seconds=entry.elapsed_duration_s)
    )
    watch_end = None if recording is None else recording_end(recording)
    ends = [end for end in (index_end, watch_end) if end is not None]
    if index_end is not None:
        method = EndMethod.BOTH if watch_end is not None else EndMethod.INDEX_ONLY
    else:
        method = EndMethod.INFERRED if watch_end is not None else EndMethod.UNKNOWN
    return ActivityEnd(
        activity_ref=entry.activity_ref,
        index_start=index_start,
        index_end=index_end,
        recording_start=None if recording is None else recording.start_time,
        recording_end=watch_end,
        safe_end=max(ends) if ends else None,
        method=method,
    )


def _require_sha256(value: str, name: str) -> None:
    if len(value) != _SHA256_LENGTH or not set(value) <= _HEXADECIMAL:
        raise ContractError(f"{name} : une empreinte SHA-256 en hexadécimal attendue.")


@dataclass(frozen=True)
class CurveCorpus:
    """Le corpus d'un athlète, attesté une fois, à la frontière de chargement.

    - ``athlete_ref`` — sans unité — le pseudonyme de l'athlète, non vide ;
    - ``index`` — sans unité — son index ;
    - ``index_sha256`` — sans unité — l'empreinte de l'index lu ;
    - ``recordings`` — sans unité — les enregistrements chargés, par référence ;
    - ``recording_sha256`` — sans unité — l'empreinte de chacun, par référence.

    Contrôlé à la construction (``ContractError``) ; les deux dictionnaires sont copiés
    puis rangés en lecture seule : modifier ensuite ceux de l'appelant ne change rien.

    Limite : une erreur d'étiquette humaine (le corpus d'un autre athlète sous ce nom)
    reste indétectable ; le format d'``interim/`` ne porte pas d'athlète.
    """

    athlete_ref: str
    index: ActivityIndex
    index_sha256: str
    recordings: Mapping[str, ActivityRecording]
    recording_sha256: Mapping[str, str]

    def __post_init__(self) -> None:
        require_non_empty(self.athlete_ref, "athlete_ref")
        _require_sha256(self.index_sha256, "index_sha256")
        entries = {entry.activity_ref: entry for entry in self.index.entries}
        for key, recording in self.recordings.items():
            if recording.activity_ref != key:
                raise ContractError(
                    f"recordings : la clé {key} porte l'enregistrement de "
                    f"{recording.activity_ref}."
                )
            if key not in entries:
                raise ContractError(f"recordings : {key} n'est pas à l'index.")
            if not entries[key].has_recording:
                raise ContractError(
                    f"recordings : l'index dit que {key} n'a pas d'enregistrement."
                )
        if set(self.recording_sha256) != set(self.recordings):
            raise ContractError(
                "recording_sha256 : une empreinte par enregistrement, et seulement."
            )
        for key, digest in self.recording_sha256.items():
            _require_sha256(digest, f"recording_sha256[{key}]")
        object.__setattr__(self, "recordings", MappingProxyType(dict(self.recordings)))
        object.__setattr__(
            self, "recording_sha256", MappingProxyType(dict(self.recording_sha256))
        )


ALL_PAST: Final = "all"
"""La fenêtre « tout le passé », sans date fictive."""

type OriginWindow = int | Literal["all"]
"""Une fenêtre : un nombre entier de jours civils, au moins 1, ou :data:`ALL_PAST`."""

DEFAULT_WINDOW_DAYS: Final = 56
"""La fenêtre par défaut, en jours : un choix d'usage, pas un résultat du backtest."""

COLD_START_ACTIVITIES: Final = 20
"""Sous ce nombre de sorties à pied, l'avertissement du démarrage à froid : un repère
indicatif, pas un seuil de validité."""

NO_CANDIDATE: Final = (
    "aucune activité candidate : aucun enregistrement des types demandés ne finit dans "
    "la fenêtre."
)
"""La raison d'une absence sans candidate."""


def check_origin(origin: datetime) -> datetime:
    """``origin`` en UTC, après contrôle : un instant à fuseau, minuit à Paris
    (``ContractError`` sinon)."""
    require_aware(origin, "origin")
    local = origin.astimezone(PARIS)
    if (local.hour, local.minute, local.second, local.microsecond) != (0, 0, 0, 0):
        raise ContractError(
            f"origin : 00:00 à Paris attendu, reçu {local.isoformat()} à Paris."
        )
    return origin.astimezone(UTC)


def check_window(window: object) -> None:
    """``window`` : un ``int`` d'au moins 1, non booléen, ou la chaîne ``"all"``
    (``ContractError`` sinon)."""
    if window == ALL_PAST:
        return
    if not isinstance(window, int) or isinstance(window, bool) or window < 1:
        raise ContractError(
            "window : un nombre entier de jours, au moins 1, ou 'all' ; reçu "
            f"{window!r}."
        )


def window_lower_bound(origin: datetime, window: OriginWindow) -> datetime | None:
    """La borne basse de la fenêtre, en UTC : 00:00 à Paris du jour civil de l'origine
    moins ``window`` jours (pas ``window`` × 24 h : la fenêtre traverse les changements
    d'heure) ; ``None`` pour :data:`ALL_PAST`, sans contrôler l'origine."""
    check_window(window)
    if isinstance(window, str):
        return None
    moment = check_origin(origin)
    try:
        day = moment.astimezone(PARIS).date() - timedelta(days=window)
        return datetime(day.year, day.month, day.day, tzinfo=PARIS).astimezone(UTC)
    except OverflowError as error:
        raise ContractError(
            f"window : {window} jours sortent du calendrier depuis l'origine."
        ) from error


class TemporalDecision(StrEnum):
    """Ce que la règle décide d'une activité inspectée."""

    CANDIDATE = "candidate"
    AFTER_ORIGIN = "finie à l'origine ou après"
    BEFORE_WINDOW = "finie avant la fenêtre"
    UNKNOWN_END = "fin inconnue"


@dataclass(frozen=True)
class Inspection:
    """Une activité inspectée par la règle.

    - ``end`` — ses fins ;
    - ``decision`` — la décision ;
    - ``recording_sha256`` — sans unité — l'empreinte de l'enregistrement lu, ``None``
      quand la décision s'est prise sur l'index seul : ``end`` ne porte alors que
      l'index et son ``safe_end``, la fin de l'index, n'est qu'une borne basse de la
      fin sûre.
    """

    end: ActivityEnd
    decision: TemporalDecision
    recording_sha256: str | None


def _inspect(
    entry: IndexedActivity,
    corpus: CurveCorpus,
    origin: datetime,
    lower_bound: datetime | None,
) -> Inspection:
    """La décision de la règle sur ``entry``. L'index décide seul quand sa fin suffit :
    ces décisions ne dépendent pas des enregistrements chargés en plus."""
    from_index = activity_end(entry, None)
    index_end = from_index.index_end
    if index_end is not None:
        if index_end >= origin:
            return Inspection(from_index, TemporalDecision.AFTER_ORIGIN, None)
        if lower_bound is not None and index_end < lower_bound:
            return Inspection(from_index, TemporalDecision.BEFORE_WINDOW, None)
    recording = corpus.recordings.get(entry.activity_ref)
    if recording is None:
        raise ContractError(
            f"corpus incomplet : l'enregistrement de {entry.activity_ref} manque."
        )
    end = activity_end(entry, recording)
    digest = corpus.recording_sha256[entry.activity_ref]
    safe_end = end.safe_end
    if safe_end is None:
        decision = TemporalDecision.UNKNOWN_END
    elif safe_end >= origin:
        decision = TemporalDecision.AFTER_ORIGIN
    elif lower_bound is not None and safe_end < lower_bound:
        decision = TemporalDecision.BEFORE_WINDOW
    else:
        decision = TemporalDecision.CANDIDATE
    return Inspection(end, decision, digest)


def select_at_origin(
    corpus: CurveCorpus,
    origin: datetime,
    window: OriginWindow,
    activity_types: frozenset[str],
) -> tuple[Inspection, ...]:
    """Les décisions de la règle, dans l'ordre de l'index, sur les entrées des types
    choisis qui ont un enregistrement. Une activité est candidate si sa fin sûre est
    avant l'origine et sa fin basse (celle de l'index, à défaut d'écoulé la fin sûre) à
    la borne basse ou après ; comparaisons strictes, aucune tolérance."""
    moment = check_origin(origin)
    lower_bound = window_lower_bound(moment, window)
    if not activity_types:
        raise ContractError("activity_types : au moins un type.")
    return tuple(
        _inspect(entry, corpus, moment, lower_bound)
        for entry in corpus.index.entries
        if entry.has_recording and entry.source_activity_type in activity_types
    )


@dataclass(frozen=True)
class OriginHistory:
    """L'historique à l'origine, **selon l'index seul**, sans fenêtre : les sorties
    finies avant l'origine (départ + écoulé de l'index) et celles parties avant
    l'origine sans écoulé à l'index, à pied et des types choisis.

    Ces comptes ne sont pas les décisions de la règle : une sortie sans écoulé à l'index
    y est souvent candidate (fin inférée) ; une sortie que l'index fait finir avant
    l'origine et la montre après compte « finie » ici, et la règle l'exclut (T01).
    """

    foot_index_finished: int
    foot_without_index_elapsed: int
    selected_index_finished: int
    selected_without_index_elapsed: int


def origin_history(
    index: ActivityIndex, origin: datetime, activity_types: frozenset[str]
) -> OriginHistory:
    """L'historique de ``index`` à ``origin``, sur **toutes** les entrées parties avant
    l'origine, avec ou sans enregistrement."""
    moment = check_origin(origin)
    finished: list[IndexedActivity] = []
    without_elapsed: list[IndexedActivity] = []
    for entry in index.entries:
        if entry.start_time >= moment:
            continue
        if entry.elapsed_duration_s is None:
            without_elapsed.append(entry)
        elif entry.start_time + timedelta(seconds=entry.elapsed_duration_s) < moment:
            finished.append(entry)

    def on_foot(entries: list[IndexedActivity]) -> int:
        return sum(
            1
            for e in entries
            if SOURCE_TYPE_SPORTS.get(e.source_activity_type) is Sport.FOOT
        )

    def selected(entries: list[IndexedActivity]) -> int:
        return sum(1 for e in entries if e.source_activity_type in activity_types)

    return OriginHistory(
        on_foot(finished),
        on_foot(without_elapsed),
        selected(finished),
        selected(without_elapsed),
    )


def cold_start_warning(history: OriginHistory) -> str | None:
    """L'avertissement du démarrage à froid, ``None`` à :data:`COLD_START_ACTIVITIES`
    sorties à pied ou plus."""
    known = history.foot_index_finished
    if known >= COLD_START_ACTIVITIES:
        return None
    unknown = history.foot_without_index_elapsed
    if unknown:
        return (
            f"moins de {COLD_START_ACTIVITIES} sorties passées confirmées dans "
            f"l'historique fourni ({known}, et {unknown} sans écoulé à l'index) ; "
            "historique incomplet"
        )
    return (
        f"moins de {COLD_START_ACTIVITIES} sorties à pied passées ({known}) : repère "
        "indicatif, la courbe d'un athlète ne bat celle d'une population qu'au-delà "
        "d'une vingtaine"
    )


class OriginOutcome(StrEnum):
    """Les trois issues de la règle."""

    ABSENT = "absence"
    NOT_PROJECTABLE = "courbe non projetable"
    PROJECTABLE = "courbe projetable"


@dataclass(frozen=True)
class OriginEstimate:
    """Ce que la règle rend pour une origine.

    - ``athlete_ref``, ``origin`` (UTC), ``window``, ``lower_bound`` (UTC, ``None`` pour
      tout le passé), ``activity_types`` — ce qui a été demandé ;
    - ``inspections`` — les décisions, dans l'ordre de l'index ;
    - ``outcome`` — l'issue ;
    - ``estimate`` — l'estimation, ``None`` en cas d'absence ;
    - ``rows`` — les lignes du fichier, vides en cas d'absence ;
    - ``support_error`` — le message d'un support impossible au seuil des diagnostics ;
    - ``absence_reason`` — la raison d'une absence ;
    - ``activity_fates`` — le sort des candidates ;
    - ``data_available_at`` — la plus tardive des fins sûres des candidates ;
    - ``last_retained_end`` — la plus tardive des fins sûres des retenues ;
    - ``history`` — l'historique, selon l'index ;
    - ``support_threshold_min`` — minutes — le seuil des diagnostics.
    """

    athlete_ref: str
    origin: datetime
    window: OriginWindow
    lower_bound: datetime | None
    activity_types: frozenset[str]
    inspections: tuple[Inspection, ...]
    outcome: OriginOutcome
    estimate: CurveEstimate | None
    rows: tuple[CurveFileRow, ...]
    support_error: str | None
    absence_reason: str | None
    activity_fates: tuple[ActivityFate, ...]
    data_available_at: datetime | None
    last_retained_end: datetime | None
    history: OriginHistory
    support_threshold_min: float

    @property
    def candidates(self) -> tuple[Inspection, ...]:
        """Les inspections candidates, dans l'ordre de l'index."""
        return tuple(
            inspection
            for inspection in self.inspections
            if inspection.decision is TemporalDecision.CANDIDATE
        )


class IntervalsOf(Protocol):
    """Ce qui rend les intervalles d'un enregistrement, à la signature
    d'``activity_intervals`` (OG-1b)."""

    def __call__(
        self,
        recording: ActivityRecording,
        profile_parameters: ParameterSet,
        /,
        *,
        hr_lag_s: float,
        hr_min_coverage: float,
        max_elapsed_s: float | None,
    ) -> ActivityIntervals | TraceRefusal: ...


def _latest_end(inspections: Iterable[Inspection]) -> datetime | None:
    """La plus tardive des fins sûres de ``inspections`` ; ``None`` sans aucune."""
    ends = [i.end.safe_end for i in inspections if i.end.safe_end is not None]
    return max(ends, default=None)


def estimate_at_origin(
    corpus: CurveCorpus,
    athlete_ref: str,
    origin: datetime,
    window: OriginWindow,
    selection: CurveSelection,
    parameters: ParameterSet,
    profile_parameters: ParameterSet,
    *,
    support_threshold_min: float = SUPPORT_THRESHOLD_MIN,
    intervals_of: IntervalsOf | None = None,
) -> OriginEstimate:
    """La règle à l'origine : **la seule fonction de la règle**. Rend la courbe en
    mémoire et n'écrit rien.

    Une entrée invalide (un seuil des diagnostics hors garde-fous compris, même sans
    candidate) ou un enregistrement manquant au corpus est une erreur
    (``ContractError``), pas une absence. Une ligne que ``read_curve`` refuserait lève
    ``CurveError`` (``0017``, P3.7). Dans cet ordre : les contrôles, la sélection,
    l'historique, les intervalles des candidates, l'estimation au seuil donné, l'issue
    au même seuil.

    ``intervals_of`` (OG-1b) : le fournisseur des intervalles, à la signature
    d':func:`activity_intervals`, appelé une fois par candidate avec les paramètres de
    la règle ; ``None`` : :func:`activity_intervals`. Un cache s'y pose (OG-2, OG-UI),
    avec sa propre clé (``0020``, « Conséquences »).
    """
    if athlete_ref != corpus.athlete_ref:
        raise ContractError(
            f"athlete_ref : la règle est demandée pour {athlete_ref!r}, le corpus est "
            f"celui de {corpus.athlete_ref!r}."
        )
    if selection.date_from is not None:
        raise ContractError(
            "selection : la règle à l'origine ne prend pas de dates (date_from et "
            "date_to à None)."
        )
    require_finite(support_threshold_min, "support_threshold_min")
    require_in_range(
        support_threshold_min, *SUPPORT_THRESHOLD_RANGE_MIN, "support_threshold_min"
    )
    moment = check_origin(origin)
    lower_bound = window_lower_bound(moment, window)
    types = selection.source_activity_types
    inspections = select_at_origin(corpus, moment, window, types)
    history = origin_history(corpus.index, moment, types)
    candidates = tuple(
        inspection
        for inspection in inspections
        if inspection.decision is TemporalDecision.CANDIDATE
    )
    available_at = _latest_end(candidates)

    def absence(
        reason: str,
        fates: tuple[ActivityFate, ...] = (),
        last_retained: datetime | None = None,
    ) -> OriginEstimate:
        return OriginEstimate(
            athlete_ref,
            moment,
            window,
            lower_bound,
            types,
            inspections,
            OriginOutcome.ABSENT,
            None,
            (),
            None,
            reason,
            fates,
            available_at,
            last_retained,
            history,
            support_threshold_min,
        )

    if not candidates:
        return absence(NO_CANDIDATE)
    refs = [inspection.end.activity_ref for inspection in candidates]
    # Le défaut se lit dans le module à l'appel, jamais à la définition (OG-1b, C2).
    provider = activity_intervals if intervals_of is None else intervals_of
    intervals = [
        provider(
            corpus.recordings[ref],
            profile_parameters,
            hr_lag_s=parameters["hr_lag_s"],
            hr_min_coverage=parameters["hr_min_coverage"],
            max_elapsed_s=selection.max_elapsed_s,
        )
        for ref in refs
    ]
    estimated = estimate_curve_outcome(
        intervals,
        refs,
        selection,
        parameters,
        support_threshold_min=support_threshold_min,
    )
    last_retained = _latest_end(
        inspection
        for inspection, fate in zip(candidates, estimated.activity_fates, strict=True)
        if fate.exclusion is None
    )
    if isinstance(estimated, NoCurve):
        return absence(estimated.reason, estimated.activity_fates, last_retained)
    rows = curve_file_rows(estimated)
    support_error = check_curve_rows(rows, support_threshold_min)
    return OriginEstimate(
        athlete_ref,
        moment,
        window,
        lower_bound,
        types,
        inspections,
        (
            OriginOutcome.PROJECTABLE
            if support_error is None
            else OriginOutcome.NOT_PROJECTABLE
        ),
        estimated,
        rows,
        support_error,
        None,
        estimated.activity_fates,
        available_at,
        last_retained,
        history,
        support_threshold_min,
    )


def retained_start_days(
    result: OriginEstimate, corpus: CurveCorpus
) -> tuple[date, date] | None:
    """Le plus ancien et le plus récent des jours civils **locaux** de départ des
    retenues (l'heure locale de l'index, ``0017``, P2.2) : l'étendue descriptive que la
    provenance porte à l'origine ; ``None`` sans retenue."""
    retained = {
        fate.activity_ref for fate in result.activity_fates if fate.exclusion is None
    }
    days = [
        entry.start_time.date()
        for entry in corpus.index.entries
        if entry.activity_ref in retained
    ]
    return (min(days), max(days)) if days else None


def _instant(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(UTC).isoformat()


def _activity_line(
    inspection: Inspection, fates: Mapping[str, ActivityFate]
) -> dict[str, object]:
    """La ligne d'une inspectée au compagnon. La méthode décide, pas la décision : une
    ligne décidée sur l'index seul n'a pas lu son enregistrement, et n'écrit ni fin sûre
    ni empreinte ; une non-candidate dont l'enregistrement a été lu les écrit."""
    end = inspection.end
    fate = fates.get(end.activity_ref)
    label: str | None = None
    if fate is not None:
        label = "retenue" if fate.exclusion is None else fate.exclusion.value
    return {
        "activity_ref": end.activity_ref,
        "decision": inspection.decision.value,
        "method": end.method.value,
        "index_start": _instant(end.index_start),
        "index_end": _instant(end.index_end),
        "recording_start": _instant(end.recording_start),
        "recording_end": _instant(end.recording_end),
        "safe_end": (
            None if end.method is EndMethod.INDEX_ONLY else _instant(end.safe_end)
        ),
        "recording_sha256": inspection.recording_sha256,
        "fate": label,
        "contributes": fate is not None and fate.contributes,
    }


def origin_document(result: OriginEstimate, corpus: CurveCorpus) -> dict[str, object]:
    """La section ``origin`` du document d'estimation d'une courbe à l'origine :
    l'origine, sa fenêtre, l'issue, l'empreinte de l'index, les dates, l'historique et
    une ligne par activité inspectée, dans l'ordre de l'index."""
    fates = {fate.activity_ref: fate for fate in result.activity_fates}
    history = result.history
    return {
        "origin": _instant(result.origin),
        "window": result.window,
        "lower_bound": _instant(result.lower_bound),
        "outcome": result.outcome.value,
        "index_sha256": corpus.index_sha256,
        "data_available_at": _instant(result.data_available_at),
        "last_retained_end": _instant(result.last_retained_end),
        "history": {
            "foot_index_finished": history.foot_index_finished,
            "foot_without_index_elapsed": history.foot_without_index_elapsed,
            "selected_index_finished": history.selected_index_finished,
            "selected_without_index_elapsed": history.selected_without_index_elapsed,
        },
        "activities": [
            _activity_line(inspection, fates) for inspection in result.inspections
        ],
    }
