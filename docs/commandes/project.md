# `mperf project` — les temps de passage

Projette des temps de passage sur un GPX, avec le moteur v0
([`0009`](../decisions/0009-moteur-projection-v0.md)).

```bash
uv run mperf project tests/fixtures/mini_11.gpx --curve tests/fixtures/courbe_synthetique.csv
```

```text
fichier      mini_11.gpx   sha256 7fdb9d12…
courbe       courbe_synthetique.csv   sha256 6767dd38…
             3 activités, 2026-01-01 → 2026-01-31
grille       1 000 m, 21 points, pas 50 m
lissage      150 m demandé → 150 m effectif (3 points)
support      9 tranches lues, 5 retenues (>= 10 min), plage −20 % … +20 %
             pentes rencontrées : −10 % … +10 %
             hors support : 0 % de la distance, 0 % du temps
effort       1.00
durée        0:08:30   (D+ 44 m / D− 44 m)
passages     4   (2 lieux résolus, départ et arrivée synthétisés)
      0 m   Départ                 0:00:00
      0 m   Départ                 0:00:00
    500 m   Col                    0:05:14
  1 000 m   Arrivée                0:08:30
```

Le départ et l'arrivée sont toujours synthétisés, même quand le GPX porte déjà un
lieu à ces abscisses : d'où deux lignes « Départ » à 0 m, le départ synthétisé
puis le lieu nommé de `mini_11.gpx` (docstring de `project` dans
[`model/engine.py`](../../src/mountain_perf/model/engine.py), test
`test_start_and_finish_are_synthesised_even_over_a_named_place` de
[`tests/test_model_engine.py`](../../tests/test_model_engine.py)).

| Option | Rôle | Défaut |
|---|---|---|
| `--curve fichier.csv` | courbe allure↔pente, avec son compagnon `<nom>.meta.json` à côté ; `--curve` ou `--at`, obligatoire | — |
| `--at AAAA-MM-JJ` | le jour de la course : la courbe à l'origine (`0020`), calculée en mémoire depuis `MPA_DATA_DIR/interim/activities/`, rien n'est écrit ; au-delà d'aujourd'hui + 7 jours, l'origine est bornée à aujourd'hui ; la sortie commence par les lignes de l'origine et dit ses avertissements ; exclut `--curve` | — |
| `--window W` | avec `--at` : la fenêtre de la courbe, en jours ou `all` | 56 |
| `--effort F` | facteur multiplicatif sur la vitesse ; 1 = la référence des activités qui ont construit la courbe | 1.0 |
| `--min-support-min F` | données minimales par tranche de pente pour la retenir (min) ; 0 = aucun filtre | 10 |
| `--step-m`, `--smoothing-m`, `--max-offset-m`, `--min-separation-m` | comme pour [`profile`](profile.md) | |
| `--csv` | le tableau des passages sur stdout, durées en secondes | — |

Colonnes du CSV : `name`, `distance_m`, `elevation_m`, `arrival_s`,
`departure_s`, `moving_time_s`, puis `segment_duration_s`, `segment_distance_m`,
`segment_ascent_m`, `segment_descent_m`, qui décrivent le tronçon **qui précède**
le passage (vides sur la première ligne).

Sur un préparé de `MPA_DATA_DIR/routes/`, la recette `just project` prend son nom puis
les options : `just project course.gpx --at 2026-06-20` (`--window 28` ou `all` après la
date). C'est une commande de l'humain : le hook la refuse aux sessions Claude Code (règle 1
de [`CLAUDE.md`](../../CLAUDE.md)).
