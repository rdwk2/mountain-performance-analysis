"""La correspondance des sorties aux activités (OG-2, § 6.3, D-OG2-6), à ses bornes
(relecture C du bloc 1, mutation 4) ; les aides sont celles de
``test_og2_correspondence.py``."""

from __future__ import annotations

from datetime import datetime

import pytest

from mountain_perf.estimation.origin import ActivityEnd, EndMethod
from test_og2_correspondence import (
    DAY_END,
    DAY_START,
    NIGHT_END,
    NIGHT_START,
    ORIGIN,
    activity,
    check,
    outing,
    paris,
    refusal,
    trace,
)


def test_the_recording_may_start_before_the_index() -> None:
    """L'intervalle d'une activité part du plus tôt de ``index_start`` et de
    ``recording_start`` : l'enregistrement part à 08:00, l'index à 08:05 ; la trace
    de 08:00 est couverte."""
    late_index = ActivityEnd(
        "A", paris(5, 8, 5), DAY_END, DAY_START, DAY_END, DAY_END, EndMethod.BOTH
    )
    check(outing(DAY_START, DAY_END, ("A",)), trace(DAY_START, DAY_END), [late_index])


def test_a_tie_names_the_first_activity() -> None:
    """« la première dans l'ordre en cas d'égalité » : A et B finissent toutes deux
    à 00:01, après l'origine ; la sortie, avant."""
    message = refusal(
        outing(NIGHT_START, NIGHT_END, ("A", "B")),
        trace(NIGHT_START, NIGHT_END),
        [
            activity("A", NIGHT_START, paris(13, 0, 1)),
            activity("B", paris(12, 23, 40), paris(13, 0, 1)),
        ],
    )
    assert "la fin sûre de l'activité A (" in message


def test_one_shared_instant_is_enough_for_control_1() -> None:
    """Contrôle 1, bornes comprises : A finit à l'instant du premier point, C part à
    l'instant du dernier ; B couvre la sortie."""
    check(
        outing(DAY_START, DAY_END, ("A", "B", "C")),
        trace(DAY_START, DAY_END),
        [
            activity("A", paris(5, 7, 0), DAY_START),
            activity("B", DAY_START, DAY_END),
            activity("C", DAY_END, paris(5, 11, 0)),
        ],
    )


@pytest.mark.parametrize(
    ("outing_end", "safe_end"),
    [
        (paris(13, 0, 0), paris(12, 23, 59, 50)),
        (paris(12, 23, 59, 50), paris(13, 0, 0)),
    ],
    ids=["fin-du-manifeste-a-l-origine", "fin-sure-a-l-origine"],
)
def test_an_end_at_the_origin_is_after_it(
    outing_end: datetime, safe_end: datetime
) -> None:
    """Contrôle 3, comparaisons strictes des deux côtés (comme ``available_at_origin``
    et la règle F) : une fin **égale** à l'origine est « à l'origine ou après »."""
    start = paris(12, 23, 0)
    message = refusal(
        outing(start, outing_end, ("A",)),
        trace(start, outing_end),
        [activity("A", start, safe_end)],
    )
    assert "ne sont pas du même côté" in message


def test_an_infinite_tolerance_is_refused() -> None:
    sortie = outing(DAY_START, DAY_END, ("A",))
    assert refusal(sortie, None, [], tolerance_s=float("inf")) == (
        "tolerance_s : un nombre fini >= 0 attendu, reçu inf."
    )


def test_a_zero_tolerance_covers_exactly() -> None:
    sortie = outing(DAY_START, DAY_END, ("A", "B"))
    exact = [
        activity("A", DAY_START, paris(5, 9, 0)),
        activity("B", paris(5, 9, 0), DAY_END),
    ]
    check(sortie, trace(DAY_START, DAY_END), exact, tolerance_s=0.0)
    gap = [
        activity("A", DAY_START, paris(5, 8, 59, 55)),
        activity("B", paris(5, 9, 0, 5), DAY_END),
    ]
    assert "à 2026-06-05T07:00:00+00:00" in refusal(
        sortie, trace(DAY_START, DAY_END), gap, tolerance_s=0.0
    )


def test_a_boolean_tolerance_is_taken_as_one_second() -> None:
    """Constat de comportement : ``True`` passe pour 1 s (aucun refus de type)."""
    sortie = outing(DAY_START, DAY_END, ("A",))
    check(
        sortie,
        trace(DAY_START, DAY_END),
        [activity("A", DAY_START, DAY_END)],
        tolerance_s=True,
    )


def test_activities_in_another_order_are_refused() -> None:
    sortie = outing(DAY_START, DAY_END, ("A", "B"))
    swapped = [
        activity("B", paris(5, 9, 0), DAY_END),
        activity("A", DAY_START, paris(5, 9, 0)),
    ]
    assert refusal(sortie, trace(DAY_START, DAY_END), swapped) == (
        "activities : celles de la sortie s1 attendues."
    )


def test_unsorted_origins_name_the_first_given() -> None:
    """Constat de comportement : la docstring dit les origines « triées », rien ne le
    vérifie ; deux origines en défaut, données dans l'ordre inverse : le message nomme
    la plus tardive."""
    later = paris(14, 0, 0)
    arguments = (
        outing(NIGHT_START, NIGHT_END, ("A",)),
        trace(NIGHT_START, NIGHT_END),
        [activity("A", NIGHT_START, paris(14, 0, 30))],
    )
    assert "2026-06-12T22:00:00+00:00" in refusal(*arguments, origins=(ORIGIN, later))
    assert "2026-06-13T22:00:00+00:00" in refusal(*arguments, origins=(later, ORIGIN))
