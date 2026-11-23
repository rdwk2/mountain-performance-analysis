"""La Fenêtre des pages de la piste analyse (AN4-1, ``docs/decisions/0019``, section
AN4-1) : des jours consécutifs, choisis parmi 28, 56 ou 90 jours, tout l'historique ou
une plage de dates, ancrés au dernier jour des données.

L'étendue des données va du plus ancien au plus récent des jours de la table ``jours``
et des jours locaux du départ des montées ; son dernier jour est l'ancre, commune à
toutes les pages. L'interface choisit la Fenêtre ; ses bornes se calculent ici (règle 7
de ``CLAUDE.md``).

Python pur : ce module ne demande aucun extra.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from mountain_perf.schemas.processed import ClimbRow, DayRow

DEFAULT_DAYS: Final = 56
"""La Fenêtre par défaut : les 56 jours qui finissent à l'ancre."""

_INSTANT: Final = "Un jour (date) est attendu, pas un instant (datetime)."


@dataclass(frozen=True)
class Window:
    """Des jours consécutifs, ses deux bornes comprises."""

    first: date
    last: date

    def __post_init__(self) -> None:
        if self.first > self.last:
            raise ValueError(
                "Le premier jour de la fenêtre vient après le dernier : "
                f"{self.first.isoformat()} puis {self.last.isoformat()}."
            )

    def __contains__(self, day: object) -> bool:
        """``first <= day <= last`` pour une ``date`` ; un ``datetime`` lève
        ``TypeError`` (un instant passé pour un jour) ; toute autre valeur : faux."""
        if isinstance(day, datetime):
            raise TypeError(_INSTANT)
        if isinstance(day, date):
            return self.first <= day <= self.last
        return False

    @property
    def days(self) -> int:
        """Le nombre de jours de la fenêtre, ses deux bornes comprises."""
        return (self.last - self.first).days + 1


class WindowChoice(StrEnum):
    """Les choix de la Fenêtre, dans l'ordre du contrôle."""

    DAYS_28 = "28"
    DAYS_56 = "56"
    DAYS_90 = "90"
    ALL = "tout"
    RANGE = "plage"


DEFAULT_CHOICE: Final = WindowChoice.DAYS_56
"""Le choix par défaut : 56 jours."""

_CHOICE_DAYS: Mapping[WindowChoice, int] = MappingProxyType(
    {WindowChoice.DAYS_28: 28, WindowChoice.DAYS_56: 56, WindowChoice.DAYS_90: 90}
)


def data_span(days: Iterable[DayRow], climbs: Iterable[ClimbRow]) -> Window | None:
    """L'étendue des données : du plus ancien au plus récent des jours de ``days`` et
    des jours locaux du départ des montées (le jour au décalage que porte l'instant,
    jamais le jour UTC) ; ``None`` si les deux sont vides."""
    found = [row.day for row in days]
    found += [climb.local_start_time.date() for climb in climbs]
    if not found:
        return None
    return Window(min(found), max(found))


def last_days(span: Window, n: int) -> Window:
    """Les ``n`` jours qui finissent à ``span.last``, l'ancre comprise, sans remonter
    avant ``span.first`` ; ``ValueError`` si ``n < 1``."""
    if n < 1:
        raise ValueError(f"Une fenêtre a au moins un jour, reçu {n}.")
    return Window(max(span.first, span.last - timedelta(days=n - 1)), span.last)


def date_range(span: Window, first: date, last: date) -> Window | None:
    """La plage ``[first, last]``, ses deux jours compris, ramenée à ``span`` ;
    ``None`` si elle est vide (le premier jour après le second, ou hors des données)."""
    start, end = max(first, span.first), min(last, span.last)
    if start > end:
        return None
    return Window(start, end)


def chosen_window(
    span: Window,
    choice: WindowChoice,
    first: date | None = None,
    last: date | None = None,
) -> Window | None:
    """La Fenêtre de ``choice`` sur ``span`` : les 28, 56 ou 90 derniers jours, toute
    l'étendue, ou la plage ``[first, last]`` (``ValueError`` s'il manque une de ses
    dates) ; les autres choix ignorent ``first`` et ``last``. ``None`` : une plage
    vide."""
    if choice is WindowChoice.ALL:
        return span
    if choice is WindowChoice.RANGE:
        if first is None or last is None:
            raise ValueError("Une plage demande ses deux jours.")
        return date_range(span, first, last)
    return last_days(span, _CHOICE_DAYS[choice])


def within[T](
    items: Iterable[T], window: Window, day: Callable[[T], date]
) -> tuple[T, ...]:
    """Les éléments dont ``day(élément)`` est dans ``window``, dans leur ordre."""
    return tuple(item for item in items if day(item) in window)
