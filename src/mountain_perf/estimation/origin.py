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

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from zoneinfo import ZoneInfo

from mountain_perf.schemas import ActivityIndex, ActivityRecording, IndexedActivity
from mountain_perf.validation import ContractError, require_non_empty

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
