"""Le modèle de la montée des tableaux de bord (AN4-2a, ``docs/decisions/0024``) : la
VAM à FC égale, en trois étages, pour les pages de la piste (AN4-2b, AN4-3).

1. **L'étage 1, la structure** (``structure.py``), sur toute l'histoire : l'effet de la
   FC (β), le déclin selon le D+ (``g``), l'altitude (λ), le régime (``rho``), lus
   dans la sortie ; entre sorties, un niveau qui suit le temps, l'effet de sortie et les
   résumés de sortie.
2. **L'étage 2, la Fenêtre** (``window_fit.py``) : le niveau et la tendance de la
   Fenêtre, β et ``g`` mêlés à ceux de l'histoire par un poids.
3. **L'étage 3, le jour** (``daily.py``) : le niveau des ``N`` derniers jours, lu à la
   dernière sortie, pente rétrécie, gelé après elle ; il ne lit que l'étage 1.

Et la sélection des montées (``selection.py``), les références (``references.py``),
la vitesse habituelle du niveau ``τ`` (``speed.py``), les états (``states.py``) et les
constantes (``parameters.py``).

**Conventions.**

- Tout est en logarithme naturel de la VAM en m/s (``y = ln(VAM)``) ; une différence
  de 0,01 vaut environ 1 %. Les pages convertissent.
- Le D+ et l'altitude en km dans le modèle : ``D = (preceding_ascent_m +
  profile_ascent_m / 2) / 1000``, ``A = moving_mean_elevation_m / 1000`` ; ``g``, λ et
  ``τ_g`` sont des pentes par 1 000 m.
- Les jours sont des ``date`` ; une durée en mois vaut ``jours / MONTH_DAYS`` ; les
  pentes en temps sont par mois.
- Le jour d'une sortie (une activité) est ``activity.start_time.date()``, le jour local
  de son départ ; toutes ses montées ont ce jour.
- Les intervalles sont à 95 % : la loi normale là où la variance est empruntée à
  l'étage 1 (étages 2 et 3), Student aux degrés de Bell-McCaffrey pour l'étage 1.
- Les objets rendus sont des ``dataclass(frozen=True)`` de nombres, de dates, de
  tuples et d'enums, jamais un tableau de numpy.
- Un état n'est pas une exception : une estimation impossible rend
  :class:`~mountain_perf.analyse.ascent.states.Unavailable` ;
  :class:`~mountain_perf.analyse.ascent.states.AscentError` (une ``ValueError``) ne
  dit qu'une entrée fautive.

**Ce dont dépend chaque étage** (pour le cache d'AN4-2b ; toutes les fonctions sont
pures, leur résultat ne dépend que de leurs arguments) : ``select_climbs``, de la
provenance des tables et des régimes ; ``references`` et ``fit_structure``, de la
sélection et de ``last_day`` ; ``habitual_speed``, des points, de la longueur et de
``end`` ; ``daily_level``, de l'étage 1, du jour, de ``N``, de ``τ`` et de la FC (jamais
de la Fenêtre) ; ``fit_window``, de l'étage 1, de la sélection et de la Fenêtre.

Python pur : ni numpy, ni scipy ; les matrices passent à ``analyse/inference/`` en
listes (``docs/decisions/0021``), ce qui demande l'extra ``analyse`` à l'exécution.
"""
