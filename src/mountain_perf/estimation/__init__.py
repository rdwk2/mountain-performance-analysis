"""L'estimation de la courbe personnelle allure ↔ pente depuis ``interim/`` (M6b,
``docs/decisions/0017``) : les intervalles d'une activité (``intervals``) et
l'estimation d'une courbe (``curve``).

Le moteur lit ``interim/`` par ses vues, jamais ``processed/``. Ce paquet n'importe ni
``mountain_perf.analyse`` ni ``mountain_perf.backtest``.
"""
