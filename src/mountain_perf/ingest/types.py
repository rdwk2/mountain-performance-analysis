"""La table des types de la source (``activityType.typeKey`` de Garmin) vers les
familles de modèle (``Sport``), relue par le moteur (``docs/decisions/0013``, point 2).

Seuls les types dont la famille de modèle est certaine y figurent : course, trail,
piste, tapis, marche (dont marche de promenade et marche rapide), randonnée, alpinisme
→ ``FOOT`` ; ski de randonnée → ``SKI_TOURING`` ; VTT → ``MTB``. Un type absent de la
table n'a pas de vue ``Activity`` : il reste dans l'index et se compte au rapport
d'ingestion (``ViewRefusal.NO_SPORT``), de sorte qu'un type courant oublié se voit au
premier export qui le porte. La table se bâtit sur les types de Garmin, pas sur les
sports d'un athlète.

Exclusions voulues :

- les activités virtuelles (``virtual_run``, ``virtual_ride``) : leurs positions sont
  celles d'un monde simulé ;
- les courses à obstacles (``obstacle_run``) : l'allure y dépend des obstacles, pas
  seulement de la pente ;
- les vélos à montée assistée ou de descente (``e_bike_mountain``,
  ``downhill_biking``) : l'assistance fait une part de la montée, ou la montée se fait
  par remontée mécanique ;
- le snowboard de randonnée (``backcountry_snowboarding``) : sa descente n'est pas celle
  du ski de randonnée, et aucune famille ne lui est certaine ;
- et tout autre type sans famille certaine (escalade, renforcement, ski de piste,
  multisport, vélo électrique…).

Les raquettes sont de la famille ``FOOT`` (avis du moteur), mais leur clé n'est
confirmée nulle part : elle s'ajoutera quand un export la portera, comme tout type
courant que la table ignore.
"""

from collections.abc import Mapping
from types import MappingProxyType

from mountain_perf.schemas import Sport

SOURCE_TYPE_SPORTS: Mapping[str, Sport] = MappingProxyType(
    {
        "running": Sport.FOOT,
        "street_running": Sport.FOOT,
        "trail_running": Sport.FOOT,
        "track_running": Sport.FOOT,
        "treadmill_running": Sport.FOOT,
        "walking": Sport.FOOT,
        "casual_walking": Sport.FOOT,
        "speed_walking": Sport.FOOT,
        "hiking": Sport.FOOT,
        "mountaineering": Sport.FOOT,
        "backcountry_skiing": Sport.SKI_TOURING,
        "mountain_biking": Sport.MTB,
    }
)
"""Type de la source → famille de modèle ; un type absent n'a pas de vue
``Activity``."""
