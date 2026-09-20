"""Moteur de projection v0 : d'un ``RouteProfile`` à une ``Projection``.

Sur chaque intervalle de la grille la pente est constante, donc la vitesse aussi :

::

    durée_i = Δd_i × p(pente_i) / effort

Le temps cumulé à une abscisse ``x`` intérieure à l'intervalle ``i`` est le temps
cumulé au début de l'intervalle plus ``(x − d_i) × p(pente_i) / effort``. Sous le
modèle c'est **exact**, pas une approximation.

Ce que le moteur ne fait pas, et qui n'est pas un oubli : aucune fatigue, aucun
effet d'altitude, de chaleur ou de nuit, aucun modèle d'arrêts — ce sont les jalons
M6a et M7. En M3, ``arrival_s == departure_s`` partout, et ``start_time`` est
absent. Ce n'est pas non plus un modèle validé : la mesure de son erreur est le M4.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import accumulate
from typing import Final

from mountain_perf.model.curve_io import CURVE_PARAMETER_SPECS
from mountain_perf.model.pace import PaceModel
from mountain_perf.schemas import (
    NamedPoint,
    PaceCurve,
    ParameterSet,
    ParameterSpec,
    Passage,
    PointKind,
    Projection,
    ResolvedPoint,
    Route,
    RouteProfile,
)

ENGINE_VERSION: Final = "projection-v0"
"""Version du moteur, recopiée dans chaque ``Projection`` qu'il produit."""

MODEL_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        name="effort",
        unit=None,
        default=1.0,
        minimum=0.5,
        maximum=1.5,
        description=(
            "Facteur multiplicatif sur la vitesse, sans dépendance à la pente. "
            "1 désigne la référence empirique des activités qui ont construit la "
            "courbe ; la plage d'usage utile est 0,7–1,2."
        ),
    ),
)
"""Paramètres du modèle lui-même.

Les bornes sont plus larges que l'usage utile pour ne pas transformer une
exploration en erreur de contrat.
"""

PROJECTION_PARAMETER_SPECS: tuple[ParameterSpec, ...] = (
    MODEL_PARAMETER_SPECS + CURVE_PARAMETER_SPECS
)
"""Tout ce dont une projection dépend, hors paramètres de grille.

Ceux de la grille sont déjà dans ``profile.build_parameters`` : une projection
porte donc l'échelle qui l'a produite, ce que le biais d'échelle de D6 exige.
"""


@dataclass(frozen=True)
class ProjectionDiagnostics:
    """Ce que la projection a rencontré, et ce qu'elle a dû prolonger.

    Sans les deux fractions hors support, on ne sait pas si le prolongement a pesé
    sur le résultat — et le prolongement est la partie du modèle qui n'est adossée
    à aucune mesure.
    """

    out_of_support_distance_m: float
    out_of_support_time_s: float
    grade_min: float
    grade_max: float


def route_endpoints(route: Route) -> tuple[NamedPoint, NamedPoint]:
    """Départ et arrivée d'un tracé, fabriqués à partir de ses extrémités.

    ``RouteProfile`` ne porte **aucune coordonnée** : la décision ``0004`` sépare
    volontairement le lieu, qui vient du fichier, et sa résolution sur le profil. Le
    moteur ne peut donc pas inventer la latitude et la longitude de ses deux
    passages synthétisés, et ``(0, 0)`` passerait la validation en affirmant un lieu
    faux — au large du Ghana. Elles viennent donc d'ici, du ``Route`` lu.

    **Poser ``kind`` ici n'est pas une inférence.** La décision ``0004`` interdit de
    deviner la nature d'un lieu **lu dans un fichier** ; le départ et l'arrivée, eux,
    sont fabriqués par le programme, qui sait ce qu'ils sont.
    """
    return (
        NamedPoint(
            name="Départ",
            latitude_deg=route.latitude_deg[0],
            longitude_deg=route.longitude_deg[0],
            elevation_m=route.elevation_m[0],
            kind=PointKind.START,
        ),
        NamedPoint(
            name="Arrivée",
            latitude_deg=route.latitude_deg[-1],
            longitude_deg=route.longitude_deg[-1],
            elevation_m=route.elevation_m[-1],
            kind=PointKind.FINISH,
        ),
    )


def _time_at(
    grid_m: Sequence[float],
    cumulative_s: Sequence[float],
    pace_s_per_m: Sequence[float],
    at_m: float,
) -> float:
    """Temps cumulé à l'abscisse ``at_m``, exact aux points de la grille.

    Fonction **pure de l'abscisse** : deux passages de même abscisse en reçoivent
    le même bit, et le dernier passage reçoit exactement le cumul final — ce que
    ``Projection`` exige en égalité stricte.
    """
    i = min(max(bisect_right(grid_m, at_m) - 1, 0), len(grid_m) - 2)
    if at_m == grid_m[i]:
        return cumulative_s[i]
    if at_m == grid_m[i + 1]:
        return cumulative_s[i + 1]
    return cumulative_s[i] + (at_m - grid_m[i]) * pace_s_per_m[i]


def _still(point: ResolvedPoint, at_s: float) -> Passage:
    """Passage sans arrêt : en M3 le modèle ne connaît pas les arrêts."""
    return Passage(point=point, moving_time_s=at_s, arrival_s=at_s, departure_s=at_s)


def project(
    profile: RouteProfile,
    curve: PaceCurve,
    parameters: ParameterSet,
    *,
    curve_ref: str,
    endpoints: tuple[NamedPoint, NamedPoint],
    generated_at: datetime | None = None,
) -> Projection:
    """Temps de passage projetés sur un profil, pour une courbe et un effort.

    Les passages produits sont les ``resolved_points`` du profil, **plus** un
    passage de départ à l'abscisse 0 et un passage d'arrivée à la fin du profil,
    toujours synthétisés même si des lieux nommés y figurent déjà : sans eux les
    segments ne couvrent ni la tête ni la queue du parcours, et le contrat
    ``Projection`` les exige.

    ``endpoints`` vient de :func:`route_endpoints` : le moteur ne connaît pas la
    géométrie, il reçoit ce qui lui manque.
    """
    return project_with_diagnostics(
        profile,
        curve,
        parameters,
        curve_ref=curve_ref,
        endpoints=endpoints,
        generated_at=generated_at,
    )[0]


def project_with_diagnostics(
    profile: RouteProfile,
    curve: PaceCurve,
    parameters: ParameterSet,
    *,
    curve_ref: str,
    endpoints: tuple[NamedPoint, NamedPoint],
    generated_at: datetime | None = None,
) -> tuple[Projection, ProjectionDiagnostics]:
    """Même projection que :func:`project`, avec les diagnostics du calcul."""
    model = PaceModel(curve)
    grid_m = profile.distance_m
    elevation_m = profile.elevation_m
    grade = profile.grade
    effort = parameters["effort"]
    # Allure effective par intervalle : constante sur l'intervalle, donc le temps
    # y est linéaire en abscisse.
    pace_s_per_m = tuple(model.pace_s_per_m(g) / effort for g in grade)
    lengths_m = tuple(grid_m[i + 1] - grid_m[i] for i in range(len(grid_m) - 1))
    cumulative_s = tuple(
        accumulate(
            (
                length_m * pace
                for length_m, pace in zip(lengths_m, pace_s_per_m, strict=True)
            ),
            initial=0.0,
        )
    )
    start_point, finish_point = endpoints
    passages = (
        _still(
            ResolvedPoint(
                point=start_point,
                distance_m=grid_m[0],
                # Altitude lue sur le profil lissé, pas sur le fichier : c'est la
                # convention du M2, et les deux valeurs diffèrent légitimement.
                elevation_m=elevation_m[0],
                offset_m=0.0,
            ),
            cumulative_s[0],
        ),
        *(
            _still(
                point, _time_at(grid_m, cumulative_s, pace_s_per_m, point.distance_m)
            )
            for point in profile.resolved_points
        ),
        _still(
            ResolvedPoint(
                point=finish_point,
                distance_m=grid_m[-1],
                elevation_m=elevation_m[-1],
                offset_m=0.0,
            ),
            cumulative_s[-1],
        ),
    )
    projection = Projection(
        profile=profile,
        curve_ref=curve_ref,
        parameters=parameters,
        passages=passages,
        start_time=None,
        engine_version=ENGINE_VERSION,
        generated_at=datetime.now(UTC) if generated_at is None else generated_at,
    )
    extrapolated = [i for i, g in enumerate(grade) if model.is_extrapolated(g)]
    diagnostics = ProjectionDiagnostics(
        out_of_support_distance_m=sum(lengths_m[i] for i in extrapolated),
        out_of_support_time_s=sum(lengths_m[i] * pace_s_per_m[i] for i in extrapolated),
        grade_min=min(grade),
        grade_max=max(grade),
    )
    return projection, diagnostics
