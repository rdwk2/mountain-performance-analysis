"""Ingestion des exports Garmin, ``raw/garmin/`` → ``interim/activities/`` (AN1-1,
AN2-0, ``docs/decisions/0013``) et ``interim/days/`` (AN2-1).

Modules : ``types`` (la table des types de la source), ``index`` (le lecteur de
l'index), ``fit`` (le lecteur FIT, seul importeur de fitdecode, extra ``ingest``),
``views`` (les vues ``Activity`` et ``TrackPointStream`` du moteur), ``families`` (la
lecture d'un fichier d'une famille journalière), ``days`` (les jours de tous les
exports : export de référence, emprunts, écarts, Training Status, rapport),
``day_views`` (les vues des jours, M7 et la piste), ``interim`` (l'écriture et la
relecture des documents d'``interim/``), ``export`` (l'ingestion des exports, extra
``ingest``).

Le paquet n'importe rien : ``interim/`` se relit et les vues se calculent sans
fitdecode (``docs/decisions/0011``) ; seuls ``fit`` et ``export`` le demandent.
"""
