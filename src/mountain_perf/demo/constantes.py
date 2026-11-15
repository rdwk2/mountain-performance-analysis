"""Les constantes des profils de démo (M5-3) : inventées et rondes, ou d'ordre de
grandeur courant ; jamais tirées des données de l'athlète (ni valeur, ni loi, ni ordre
de grandeur) ni d'un jeu externe (règle 1 de `CLAUDE.md`, `docs/decisions/0022`).

Les vitesses sont écrites en km/h, des nombres ronds à la frontière (``0002`` le permet
aux entrées) ; ``personnages.true_speed_ms`` est la seule conversion en m/s. Les pentes
sont des fractions (0,30 = 30 %), positives en montée ; les longueurs et les altitudes
en mètres. Aucun nombre d'un format (FIT, gabarits Garmin) n'est ici : ils vivent,
nommés, dans le module qui écrit ce format.
"""

from typing import Final

# --- Le lieu (D5) ---------------------------------------------------------------------

ORIGIN_LAT_DEG: Final = 0.0
"""La latitude de l'origine du repère plan : l'équateur, en plein océan."""

ORIGIN_LON_DEG: Final = -140.0
"""La longitude de l'origine du repère plan, loin de tout lieu habité ou connu."""

# --- La courbe de base (D1) et la spécificité (D2) ------------------------------------

BASE_KNOTS: Final[tuple[tuple[float, float], ...]] = (
    (-0.40, 3.0),
    (-0.30, 4.5),
    (-0.20, 6.5),
    (-0.10, 10.0),
    (0.0, 9.0),
    (0.10, 6.0),
    (0.20, 4.0),
    (0.30, 3.0),
    (0.40, 2.4),
)
"""Les nœuds de la courbe de base : la pente et la vitesse horizontale en km/h, de −40 %
à +40 %, maximum à −10 %."""

STEEP_FROM: Final = 0.10
"""En deçà de cette pente (en valeur absolue), le facteur du roulant seul."""

STEEP_FULL: Final = 0.20
"""Au-delà de cette pente (en valeur absolue), le facteur du raide seul."""

# --- Les personnages ------------------------------------------------------------------

CHARACTER_NAMES: Final = ("debutant", "polyvalente", "grimpeur", "rouleur", "moyen")
"""Les noms de dossier des cinq personnages, dans l'ordre de leurs rangs."""

TRAIL_CYCLE_DAYS: Final = 7
"""La longueur du cycle d'entraînement d'un traileur, en jours."""

TRAIL_OUTING_DAYS: Final = (0, 2, 4, 5)
"""Les restes, modulo le cycle, des jours de sortie d'un traileur."""

TRAIL_HISTORY_DAYS: Final = 119
"""L'historique d'un traileur, en jours (17 semaines)."""

BEGINNER_CYCLE_DAYS: Final = 3
"""Le cycle du débutant : une sortie tous les trois jours."""

BEGINNER_OUTING_DAYS: Final = (0,)
"""Les restes, modulo son cycle, des jours de sortie du débutant."""

BEGINNER_HISTORY_DAYS: Final = 35
"""L'historique du débutant, en jours (5 semaines)."""

CHARACTER_TABLE: Final[
    tuple[
        tuple[
            str,
            str,
            int,
            float,
            float,
            int,
            tuple[int, ...],
            int,
            tuple[tuple[str, int], ...],
            str,
        ],
        ...,
    ]
] = (
    (
        "debutant",
        "débutant",
        11,
        0.75,
        0.75,
        BEGINNER_HISTORY_DAYS,
        BEGINNER_OUTING_DAYS,
        BEGINNER_CYCLE_DAYS,
        (("boucle_douce", 1),),
        "boucle_douce",
    ),
    (
        "polyvalente",
        "polyvalente",
        12,
        1.1,
        1.1,
        TRAIL_HISTORY_DAYS,
        TRAIL_OUTING_DAYS,
        TRAIL_CYCLE_DAYS,
        (
            ("boucle_raide", 1),
            ("boucle_roulante", 2),
            ("boucle_raide", 1),
            ("boucle_moyenne", 2),
        ),
        "boucle_raide",
    ),
    (
        "grimpeur",
        "grimpeur",
        13,
        1.1,
        0.9,
        TRAIL_HISTORY_DAYS,
        TRAIL_OUTING_DAYS,
        TRAIL_CYCLE_DAYS,
        (
            ("boucle_raide", 1),
            ("boucle_raide", 1),
            ("boucle_moyenne", 1),
            ("boucle_raide", 2),
        ),
        "boucle_raide",
    ),
    (
        "rouleur",
        "rouleur",
        14,
        0.9,
        1.1,
        TRAIL_HISTORY_DAYS,
        TRAIL_OUTING_DAYS,
        TRAIL_CYCLE_DAYS,
        (
            ("boucle_roulante", 2),
            ("boucle_roulante", 1),
            ("boucle_roulante", 2),
            ("boucle_douce", 1),
        ),
        "boucle_roulante",
    ),
    (
        "moyen",
        "moyen",
        15,
        1.0,
        1.0,
        TRAIL_HISTORY_DAYS,
        TRAIL_OUTING_DAYS,
        TRAIL_CYCLE_DAYS,
        (
            ("boucle_moyenne", 2),
            ("boucle_moyenne", 2),
            ("boucle_moyenne", 1),
            ("boucle_roulante", 1),
        ),
        "boucle_moyenne",
    ),
)
"""Les personnages, dans l'ordre des rangs : nom de dossier, nom affiché, graine,
``F_raide``, ``F_roulant``, historique en jours, jours de sortie (restes modulo le
cycle), cycle en jours, la suite des sorties d'un cycle (boucle, tours), boucle
témoin."""

OUTING_START_HOUR: Final = 9
"""L'heure de départ de toutes les sorties, à Paris."""

# --- Les parcours ---------------------------------------------------------------------

LOOP_EAST_SHARE: Final = 0.3
"""Le côté est-ouest du rectangle d'une boucle, en part de sa longueur."""

LOOP_NORTH_SHARE: Final = 0.2
"""Le côté nord-sud du rectangle d'une boucle, en part de sa longueur."""

STEEP_PART: Final[tuple[tuple[float, float, float], ...]] = (
    (2_000.0, 0.30, 0.30),
    (1_000.0, -0.20, -0.20),
    (2_000.0, 0.35, 0.35),
    (2_000.0, -0.25, -0.25),
    (2_000.0, 0.25, 0.25),
    (1_000.0, 0.20, 0.20),
)
"""La partie raide des courses : (longueur, pente de début, pente de fin)."""

ROLLING_PART: Final[tuple[tuple[float, float, float], ...]] = (
    (4_000.0, -0.06, -0.06),
    (4_000.0, 0.04, 0.04),
    (4_000.0, -0.06, -0.06),
    (4_000.0, 0.04, 0.04),
    (4_000.0, -0.02, -0.02),
)
"""La partie roulante de la course à deux parties."""

STEEP_LOOP_UP: Final = 0.36
"""La pente tenue de la montée de la boucle raide."""

STEEP_LOOP_DOWN: Final = -0.28
"""La pente tenue de la descente de la boucle raide."""

STEEP_LOOP: Final[tuple[tuple[float, float, float], ...]] = (
    (400.0, 0.0, 0.0),
    (2_000.0, 0.0, STEEP_LOOP_UP),
    (500.0, STEEP_LOOP_UP, STEEP_LOOP_UP),
    (500.0, STEEP_LOOP_UP, 0.0),
    (300.0, 0.0, 0.0),
    (2_000.0, 0.0, STEEP_LOOP_DOWN),
    (500.0, STEEP_LOOP_DOWN, STEEP_LOOP_DOWN),
    (1_500.0, STEEP_LOOP_DOWN, 0.0),
    (300.0, 0.0, 0.0),
)
"""Les tronçons de la boucle raide."""

ROLLING_LOOP_GRADE: Final = 0.09
"""La pente tenue de la boucle roulante, en montée comme en descente."""

ROLLING_LOOP_WAVE: Final[tuple[tuple[float, float, float], ...]] = (
    (400.0, 0.0, ROLLING_LOOP_GRADE),
    (250.0, ROLLING_LOOP_GRADE, ROLLING_LOOP_GRADE),
    (400.0, ROLLING_LOOP_GRADE, 0.0),
    (300.0, 0.0, 0.0),
    (400.0, 0.0, -ROLLING_LOOP_GRADE),
    (250.0, -ROLLING_LOOP_GRADE, -ROLLING_LOOP_GRADE),
    (400.0, -ROLLING_LOOP_GRADE, 0.0),
    (300.0, 0.0, 0.0),
)
"""Une vague de la boucle roulante, parcourue trois fois."""

MEDIUM_LOOP_GRADE: Final = 0.14
"""La pente tenue de la boucle moyenne."""

MEDIUM_LOOP: Final[tuple[tuple[float, float, float], ...]] = (
    (600.0, 0.0, MEDIUM_LOOP_GRADE),
    (1_200.0, MEDIUM_LOOP_GRADE, MEDIUM_LOOP_GRADE),
    (600.0, MEDIUM_LOOP_GRADE, 0.0),
    (300.0, 0.0, 0.0),
    (600.0, 0.0, -MEDIUM_LOOP_GRADE),
    (1_200.0, -MEDIUM_LOOP_GRADE, -MEDIUM_LOOP_GRADE),
    (600.0, -MEDIUM_LOOP_GRADE, 0.0),
    (300.0, 0.0, 0.0),
)
"""Les tronçons de la boucle moyenne."""

GENTLE_LOOP_GRADE: Final = 0.065
"""La pente tenue de la boucle douce."""

GENTLE_LOOP_WAVE: Final[tuple[tuple[float, float, float], ...]] = (
    (300.0, 0.0, GENTLE_LOOP_GRADE),
    (300.0, GENTLE_LOOP_GRADE, GENTLE_LOOP_GRADE),
    (300.0, GENTLE_LOOP_GRADE, 0.0),
    (300.0, 0.0, 0.0),
    (300.0, 0.0, -GENTLE_LOOP_GRADE),
    (300.0, -GENTLE_LOOP_GRADE, -GENTLE_LOOP_GRADE),
    (300.0, -GENTLE_LOOP_GRADE, 0.0),
    (300.0, 0.0, 0.0),
)
"""Une vague de la boucle douce, parcourue trois fois."""

LOOP_WAVES: Final = 3
"""Le nombre de vagues des boucles roulante et douce."""

ROUTE_TABLE: Final[
    tuple[
        tuple[
            str,
            str,
            tuple[float, float],
            float,
            tuple[tuple[float, float, float], ...],
            tuple[tuple[str, float], ...],
        ],
        ...,
    ]
] = (
    (
        "deux_parties",
        "line",
        (0.0, 0.0),
        1_000.0,
        STEEP_PART + ROLLING_PART,
        (
            ("Départ", 0.0),
            ("Sommet 1", 2_000.0),
            ("Sommet 2", 5_000.0),
            ("Col", 10_000.0),
            ("Arrivée", 30_000.0),
        ),
    ),
    (
        "course_raide",
        "line",
        (0.0, 0.0),
        1_000.0,
        STEEP_PART,
        (
            ("Départ", 0.0),
            ("Sommet 1", 2_000.0),
            ("Sommet 2", 5_000.0),
            ("Arrivée", 10_000.0),
        ),
    ),
    (
        "boucle_raide",
        "loop",
        (0.0, 2_000.0),
        1_200.0,
        STEEP_LOOP,
        (("Sommet", 3_400.0),),
    ),
    (
        "boucle_roulante",
        "loop",
        (0.0, -4_000.0),
        1_100.0,
        ROLLING_LOOP_WAVE * LOOP_WAVES,
        (("Mi-parcours", 4_050.0),),
    ),
    (
        "boucle_moyenne",
        "loop",
        (-3_000.0, 2_000.0),
        1_150.0,
        MEDIUM_LOOP,
        (("Sommet", 2_400.0),),
    ),
    (
        "boucle_douce",
        "loop",
        (-3_000.0, -4_000.0),
        1_050.0,
        GENTLE_LOOP_WAVE * LOOP_WAVES,
        (("Mi-parcours", 3_600.0),),
    ),
)
"""Les six parcours, dans l'ordre de ``ROUTES`` : nom, forme, départ (x ; y) dans le
repère plan, altitude de départ, tronçons, lieux nommés (nom, distance depuis le
départ)."""

ROUTE_POINT_STEP_M: Final = 10.0
"""Le pas des points d'un GPX préparé, en mètres."""

# --- Les sorties ----------------------------------------------------------------------

OUTING_FACTOR_MIN: Final = 0.95
OUTING_FACTOR_SPAN: Final = 0.10
"""Le bruit du jour d'une sortie : un facteur de vitesse ``0,95 + 0,10 · u``."""

ALTITUDE_NOISE_M: Final = 0.4
"""L'amplitude du bruit d'altitude d'un enregistrement (±0,2 m)."""

HR_REST: Final = 95.0
"""La FC au départ et pendant l'arrêt, en bpm."""

HR_BASE: Final = 125.0
"""La FC cible en mouvement sur le plat, en bpm."""

HR_PER_GRADE: Final = 150.0
"""Ce que la pente positive ajoute à la FC cible, en bpm par unité de pente."""

HR_LAG_S: Final = 30.0
"""Le retard de la FC sur sa cible, en secondes."""

STOP_S: Final = 120
"""La durée de l'arrêt d'une sortie, en secondes, à mi-parcours du premier tour."""

STOP_EVERY: Final = 3
"""Une sortie sur trois s'arrête (``number % 3 == 0``)."""

REDUCED_HISTORY_DAYS: Final = 42
"""L'historique au plus de la version réduite, en jours (les traileurs ; le débutant,
plus court, est inchangé)."""

REDUCED_LAPS: Final = 1
"""Les tours d'une sortie de la version réduite."""

ID_BASE: Final = 1_000_000
"""La base des identifiants des activités : ``ID_BASE · (rang + 1) + numéro``."""

LOAD_PER_MINUTE: Final = 1.0
"""La charge selon Garmin d'une minute de sortie."""

ACQUISITION_HOUR: Final = 6
"""L'heure, à Paris, de l'instant d'acquisition de l'export, le jour T0."""

# --- La construction et la commande ---------------------------------------------------

DEMO_VERSION: Final = 1
"""La version du générateur, écrite dans la marque ``demo.json``."""

RACE_STEEP_DAYS: Final = 5
"""Le jour de la course raide, en jours après T0."""

RACE_TWO_PARTS_DAYS: Final = 21
"""Le jour de la course à deux parties, en jours après T0."""

DEMO_PORT_BASE: Final = 8511
"""Le port de l'interface d'un personnage : ``DEMO_PORT_BASE`` + son rang."""
