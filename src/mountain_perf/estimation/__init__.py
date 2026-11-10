"""L'estimation de la courbe personnelle allure ↔ pente depuis ``interim/`` (M6b,
``docs/decisions/0017``) : les intervalles d'une activité (``intervals``),
l'estimation d'une courbe (``curve``) et la règle à l'origine (``origin``, OG-1,
``docs/decisions/0020``).

Le moteur lit ``interim/`` par ses vues, jamais ``processed/``. Ce paquet n'importe ni
``mountain_perf.analyse`` ni ``mountain_perf.backtest``.
"""
