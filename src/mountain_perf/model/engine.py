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
from dataclasses import dataclass, field
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
from mountain_perf.validation import (
    ContractError,
    require_all_finite,
    require_immutable_sequence,
    require_increasing,
    require_min_length,
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

    Champs
    ------
    - ``out_of_support_distance_m`` — mètres — distance parcourue hors du support
      de la courbe, ``>= 0``.
    - ``out_of_support_time_s`` — secondes — temps correspondant, ``>= 0``.
    - ``out_of_support_distance_share``, ``out_of_support_time_share`` — fractions
      dans ``[0, 1]`` — les deux précédentes rapportées au total du tracé.
    - ``grade_min``, ``grade_max`` — fractions — pentes extrêmes rencontrées.

    Sans les deux fractions, on ne sait pas si le prolongement a pesé sur le
    résultat — et le prolongement est la partie du modèle qui n'est adossée à
    aucune mesure.

    **Les fractions sont stockées, pas leurs dénominateurs.** Porter la longueur et
    la durée totales dupliquerait ``profile.distance_m[-1]`` et
    ``passages[-1].arrival_s``, que l'appelant a déjà : c'est exactement ce que la
    décision ``0007`` proscrit. Le quotient, lui, n'existe nulle part ailleurs, et
    le laisser à l'appelant reviendrait à calculer dans l'interface (règle 7 de
    ``CLAUDE.md``). ``project_with_diagnostics`` a les totaux au moment du calcul.

    Non promis
    ----------
    Une fraction nulle ne distingue pas « rien hors support » d'un tracé de
    longueur ou de durée nulle — que le M2 ne produit pas.
    """

    out_of_support_distance_m: float
    out_of_support_time_s: float
    out_of_support_distance_share: float
    out_of_support_time_share: float
    grade_min: float
    grade_max: float


def _share(part: float, whole: float) -> float:
    """Fraction ``part / whole``, ``0`` pour un total nul.

    Un profil produit par le M2 a toujours une longueur et une durée strictement
    positives ; « aucune distance, donc aucune part » vaut mieux qu'une division
    par zéro pour un profil qui n'en aurait pas.
    """
    return part / whole if whole > 0 else 0.0


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


@dataclass(frozen=True)
class ProjectedTimeline:
    """La chronologie projetée d'un profil : le cumul ``P(s)`` à toute abscisse de
    ``[0 ; L]`` (``0010`` D16, « accès aux temps fins et aux cumuls v0 aux abscisses
    exactes »).

    Générique : une allure par intervalle de la grille, quelle qu'en soit l'origine —
    v0 par :func:`projected_timeline`, les baselines de M4c (D9.1) par la classe
    elle-même.

    Champs
    ------
    - ``grid_m`` — mètres — la grille fine du profil (``distance_m``).
    - ``pace_s_per_m`` — secondes par mètre — une allure par intervalle
      ``[g_i ; g_{i+1}]``.
    - ``cumulative_s`` — secondes — le cumul à chaque nœud, **calculé** à la
      construction, jamais passé : ``accumulate`` des ``l_i · a_i`` avec
      ``l_i = g_{i+1} − g_i``, les mêmes opérations, dans le même ordre, que
      ``project_with_diagnostics`` de M3.

    Propriété calculée (jamais stockée) : ``length_m``.

    Invariants
    ----------
    - ``grid_m`` et ``pace_s_per_m`` sont des tuples ;
    - ``grid_m`` : au moins deux valeurs, finies, strictement croissantes,
      ``grid_m[0] == 0`` ;
    - ``len(pace_s_per_m) == len(grid_m) − 1``, allures finies et ``> 0``.

    Non promis
    ----------
    - une allure non finie ou ``<= 0`` est refusée à la construction : une baseline
      qui en produirait lèverait au lieu d'un statut « erreur du modèle » (D7.1) ;
    - :meth:`time_at` ne prolonge pas au-delà de ``L``.
    """

    grid_m: tuple[float, ...]
    pace_s_per_m: tuple[float, ...]
    cumulative_s: tuple[float, ...] = field(init=False)

    def __post_init__(self) -> None:
        require_immutable_sequence(self.grid_m, "grid_m")
        require_immutable_sequence(self.pace_s_per_m, "pace_s_per_m")
        require_min_length(self.grid_m, 2, "grid_m")
        require_all_finite(self.grid_m, "grid_m")
        if self.grid_m[0] != 0:
            raise ContractError(f"grid_m[0] doit valoir 0, reçu {self.grid_m[0]}.")
        require_increasing(self.grid_m, "grid_m", strict=True)
        if len(self.pace_s_per_m) != len(self.grid_m) - 1:
            raise ContractError(
                f"pace_s_per_m doit porter {len(self.grid_m) - 1} allures (une par "
                f"intervalle), reçu {len(self.pace_s_per_m)}."
            )
        require_all_finite(self.pace_s_per_m, "pace_s_per_m")
        for i, pace in enumerate(self.pace_s_per_m):
            if pace <= 0:
                raise ContractError(f"pace_s_per_m[{i}] doit être > 0, reçu {pace}.")
        grid_m = self.grid_m
        lengths_m = tuple(grid_m[i + 1] - grid_m[i] for i in range(len(grid_m) - 1))
        cumulative_s = tuple(
            accumulate(
                (
                    length_m * pace
                    for length_m, pace in zip(lengths_m, self.pace_s_per_m, strict=True)
                ),
                initial=0.0,
            )
        )
        object.__setattr__(self, "cumulative_s", cumulative_s)

    @property
    def length_m(self) -> float:
        """``L`` (m) : ``grid_m[-1]``."""
        return self.grid_m[-1]

    def time_at(self, at_m: float) -> float:
        """Le cumul ``P(at_m)`` (s), exact aux points de la grille.

        Fonction **pure de l'abscisse** : deux passages de même abscisse en reçoivent
        le même bit, et le dernier passage reçoit exactement le cumul final — ce que
        ``Projection`` exige en égalité stricte. Le corps est celui de ``_time_at`` de
        M3, inchangé ; les deux retours aux nœuds rendent les bits de la formule et
        restent pour la lisibilité.

        Précondition : ``0 <= at_m <= L``, sinon ``ValueError``.
        """
        if not 0 <= at_m <= self.length_m:
            raise ValueError(
                f"time_at : l'abscisse {at_m} doit être dans [0 ; {self.length_m}]."
            )
        grid_m, cumulative_s = self.grid_m, self.cumulative_s
        i = min(max(bisect_right(grid_m, at_m) - 1, 0), len(grid_m) - 2)
        if at_m == grid_m[i]:
            return cumulative_s[i]
        if at_m == grid_m[i + 1]:
            return cumulative_s[i + 1]
        return cumulative_s[i] + (at_m - grid_m[i]) * self.pace_s_per_m[i]


def projected_timeline(
    profile: RouteProfile, curve: PaceCurve, parameters: ParameterSet
) -> ProjectedTimeline:
    """La chronologie de v0 sur un profil : l'allure de la courbe à la pente de chaque
    intervalle, divisée par l'effort — les allures de M3, au bit."""
    model = PaceModel(curve)
    effort = parameters["effort"]
    return ProjectedTimeline(
        tuple(profile.distance_m),
        tuple(model.pace_s_per_m(g) / effort for g in profile.grade),
    )


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
    # Allure effective par intervalle : constante sur l'intervalle, donc le temps
    # y est linéaire en abscisse.
    timeline = projected_timeline(profile, curve, parameters)
    pace_s_per_m = timeline.pace_s_per_m
    cumulative_s = timeline.cumulative_s
    lengths_m = tuple(grid_m[i + 1] - grid_m[i] for i in range(len(grid_m) - 1))
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
            _still(point, timeline.time_at(point.distance_m))
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
    out_of_support_distance_m = sum(lengths_m[i] for i in extrapolated)
    out_of_support_time_s = sum(lengths_m[i] * pace_s_per_m[i] for i in extrapolated)
    diagnostics = ProjectionDiagnostics(
        out_of_support_distance_m=out_of_support_distance_m,
        out_of_support_time_s=out_of_support_time_s,
        # Les totaux sont ici, à portée : c'est le seul endroit où le quotient se
        # calcule sans redemander à l'appelant ce qu'il a déjà.
        out_of_support_distance_share=_share(out_of_support_distance_m, grid_m[-1]),
        out_of_support_time_share=_share(out_of_support_time_s, cumulative_s[-1]),
        grade_min=min(grade),
        grade_max=max(grade),
    )
    return projection, diagnostics
