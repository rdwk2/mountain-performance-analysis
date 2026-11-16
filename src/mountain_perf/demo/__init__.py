"""Les profils de démo (M5-3, ``docs/decisions/0022``) : cinq personnages inventés,
construits à la demande sous ``demo/<personnage>/`` à la racine du dépôt (ignoré par
git), sur lesquels l'interface et les commandes de lecture s'essaient sans rien du réel.

Le générateur n'écrit que des entrées brutes (un export Garmin, des GPX, un journal) ;
``interim/``, ``processed/``, ``resultats/Q1/`` et la courbe de ``reference/`` viennent
des vraies commandes. Les modules :

- ``constantes`` : tous les nombres inventés du générateur ;
- ``personnages`` : la courbe vraie, la spécificité, les personnages, les temps vrais ;
- ``parcours`` : le repère plan, les tronçons, les six parcours ;
- ``gpx`` : les GPX préparés et la trace témoin ;
- ``fit`` : l'écrivain FIT propre au générateur ;
- ``sorties`` : la simulation d'une sortie, le calendrier, l'export Garmin ;
- ``jours`` : les onze familles journalières et le journal ;
- ``construction`` : les entrées, la construction par les vraies commandes, la marque,
  l'interface.

Bibliothèque standard seule, avec ``mountain_perf`` (la racine du dépôt),
``mountain_perf.validation`` et ``mountain_perf.schemas.days`` (``WAKING_CONTEXT``) ;
le générateur ne lit jamais l'horloge.
"""
