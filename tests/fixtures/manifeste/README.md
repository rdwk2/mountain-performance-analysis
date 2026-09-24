# Manifeste synthétique (M4a-1)

Inventé de bout en bout, pour `tests/test_backtest_manifest.py` (brief M4a-1, § 4.5
et § 7.1). Trois sorties de l'athlète `athlete-1` :

- `p1-2026-06-07` — tracée (`gpx/p1/jour3.gpx`), avec un préparé
  (`gpx/p1/prepare.gpx`) et un doublon `gpx/p1/jour3.fit`, un fichier **texte** qui
  n'est pas du GPX : il est haché, jamais lu ;
- `p2-2026-06-10` — tracée en deux tronçons (`gpx/p2/matin_1.gpx`, `matin_2.gpx`,
  T28), sans référence, avec un relevé externe ;
- `velo-2026-06-07` — VTT, non tracée, instants déclarés.

`gpx/p2/prepare.gpx` porte le même nom que le préparé de p1 avec un autre contenu ;
seules des variantes du test le citent. Chaque cas d'erreur est une variante écrite
dans `tmp_path`, jamais ici.
