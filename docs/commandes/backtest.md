# `just backtest` — le backtest enregistré des cinq modèles

Le backtest compare v0 à quatre autres modèles : v0 + effort recalé, et trois
modèles de référence — vitesse constante, Naismith, Tobler —, chacun calé sur les
entraînements terminés avant l'origine de la performance évaluée, à 00:00 sept jours
avant son jour ([`0010`](../decisions/0010-protocole-de-backtest.md), D2.5 et D9).
Un effet n'entrera dans le modèle que s'il fait baisser l'erreur mesurée, ou avec une
justification écrite : la règle d'admission (D10) compare le modèle avec et sans
l'effet, performance par performance, sur une cible déclarée d'avance, et vérifie que
le reste de l'erreur ne se dégrade pas au-delà de tolérances fixées d'avance (les
garde-fous). Son verdict reste exploratoire, jamais une preuve.

`just backtest <courbe.csv>` lance `mperf backtest` sur le manifeste
`MPA_DATA_DIR/reference/manifeste.json` et la courbe nommée, du même dossier
([`0010`](../decisions/0010-protocole-de-backtest.md), D9, D14 et D15) : sorties
retenues, domaine et performances ; appariement et scores de chaque sortie sous cinq
modèles — v0 brut, v0 + effort recalé, vitesse constante, Naismith et Tobler, les quatre
derniers calés sur les entraînements terminés avant l'origine de chaque performance ;
référence de répétabilité (D8) de chaque parcours du jeu de répétabilité ; au rapport
complet seulement, le diagnostic de longue course (D12) de chaque sortie scorée et, pour une
sortie à référence, ses fourchettes (D11), que le registre garde aussi. Une sortie
peut être déclarée au manifeste dans un jeu (répétabilité, développement ou
confirmation, D2.3) ; les agrégats se publient jeu par jeu, et une performance sans
jeu n'entre dans aucun. L'exécution est enregistrée dans
`MPA_DATA_DIR/registre/` (une DÉCLARATION avant le calcul, dont l'empreinte s'affiche
aussitôt, puis un RÉSULTAT ou un ÉCHEC) ; le rapport complet est écrit dans
`MPA_DATA_DIR/rapports/backtest-<n° du RÉSULTAT>.txt`, jamais réécrit. La synthèse
s'affiche avec le sceau du registre, l'empreinte de sa dernière ligne : l'entrée du
[`JOURNAL`](../JOURNAL.md) d'une exécution réelle recopie ce sceau et, au plus, les
agrégats par jeu, jamais la synthèse par sortie, qui date et nomme les sorties (règle 1
de [`CLAUDE.md`](../../CLAUDE.md)). Le code exécuté doit être celui d'un clone git, installé
par `uv sync` : la commande refuse un clone dont un fichier suivi est modifié, et
enregistre le commit du code exécuté. Le manifeste décrit chaque sortie (`0010` D2.6 ;
lecture : [`backtest/manifest.py`](../../src/mountain_perf/backtest/manifest.py)) ; exemples
synthétiques : [`tests/fixtures/manifeste/`](../../tests/fixtures/manifeste/README.md), et le
monde de [`tests/fixtures/backtest_world.py`](../../tests/fixtures/backtest_world.py),
exécutable de bout en bout.

```bash
just backtest courbe.csv
```

Extrait de la synthèse, sur le monde synthétique des tests
(`tests/fixtures/backtest_world.py`) : le calage de chaque performance (effort de v0,
facteur de chaque baseline), puis, jeu par jeu, les agrégats d'usage sous l'écoulé des
cinq modèles, à poids égal par performance, et `|L|` sur les performances où les cinq
ont une valeur. Aucun entraînement n'est terminé avant l'origine des cinq premières
performances, sept jours avant chacune : leur `C_j` est vide, et les modèles calés n'y
ont pas de valeur (« non calé », « — (0) »).

```text
calage       0010 D9.2 sur C_j (entraînements terminés avant o_j) ; écoulé, usage (contrôle sans référence) ; e : effort de v0, a : facteur
             jour        C_j  C_j^eff  v0 + effort recalé  vitesse constante   Naismith            Tobler
             2026-06-03  0    0        non calé            non calé            non calé            non calé
             2026-06-04  0    0        non calé            non calé            non calé            non calé
             2026-06-06  0    0        non calé            non calé            non calé            non calé
             2026-06-08  0    0        non calé            non calé            non calé            non calé
             2026-06-10  0    0        non calé            non calé            non calé            non calé
             2026-06-12  2    2        e 1.032806          a 0.529643          a 0.517033          a 0.578027 (jour multi-sorties, a-2026-06-12)
             2026-06-14  3    3        e 0.994408          a 0.557052          a 0.540004          a 0.599883
             2026-06-15  3    3        e 1.005992          a 0.546608          a 0.532632          a 0.593522 (contrôle)
             2026-06-16  4    —        non scorée
             2026-06-20  6    —        non scorée
             2026-06-25  8    6        e 1.022058          a 0.540342          a 0.521925          a 0.586222
             2026-06-27  8    6        e 1.022058          a 0.540342          a 0.521925          a 0.586222
agrégats     usage, écoulé ; moyenne à poids égal par performance (effectif) ; |L| commun : performances où les cinq modèles ont une valeur ; détail et motifs : rapport complet
             répétabilité    v0 brut             v0 + effort recalé  vitesse constante   Naismith            Tobler
             L               +0.025018 (5)       — (0)               — (0)               — (0)               — (0)
             |L|             0.057571 (5)        — (0)               — (0)               — (0)               — (0)
             max |C_k|       132.4 (5)           — (0)               — (0)               — (0)               — (0)
             q_usage         0.059984 (4)        — (0)               — (0)               — (0)               — (0)
             |L| commun      — (0)               — (0)               — (0)               — (0)               — (0)
             développement   v0 brut             v0 + effort recalé  vitesse constante   Naismith            Tobler
             L               +0.132283 (1)       +0.137890 (1)       +0.112756 (1)       +0.126724 (1)       +0.139436 (1)
             |L|             0.132283 (1)        0.137890 (1)        0.112756 (1)        0.126724 (1)        0.139436 (1)
             max |C_k|       301.6 (1)           315.2 (1)           292.2 (1)           287.7 (1)           319.0 (1)
             q_usage         0.136219 (1)        0.141843 (1)        0.120012 (1)        0.144985 (1)        0.121469 (1)
             |L| commun      0.132283 (1)        0.137890 (1)        0.112756 (1)        0.126724 (1)        0.139436 (1)
             confirmation    v0 brut             v0 + effort recalé  vitesse constante   Naismith            Tobler
             L               +0.085392 (2)       +0.063574 (2)       +0.073070 (2)       +0.062541 (2)       +0.067179 (2)
             |L|             0.085392 (2)        0.063574 (2)        0.073070 (2)        0.062541 (2)        0.067179 (2)
             max |C_k|       177.4 (2)           132.8 (2)           225.2 (2)           192.1 (2)           151.0 (2)
             q_usage         0.088736 (2)        0.067154 (2)        0.091030 (2)        0.073195 (2)        0.066100 (2)
             |L| commun      0.085392 (2)        0.063574 (2)        0.073070 (2)        0.062541 (2)        0.067179 (2)
```

Avec `--sensitivity`, la commande enchaîne, après le rapport de l'exécution centrale, la
sensibilité de [`0010`](../decisions/0010-protocole-de-backtest.md), D13 : la même
déclaration rejouée sous dix-neuf configurations — les neuf paires (Δ, ε) sous l'écoulé,
et la paire centrale (250 m, 30 m) sous les dix horloges de mouvement —, chacune comparée
au comparateur (250 m, 30 m, écoulé) sur trois axes : la disponibilité de chaque valeur,
son support effectif, sa valeur. Neuf appariements au lieu d'un : elle dure plusieurs
fois l'exécution centrale. Elle s'enregistre en une DÉCLARATION de sensibilité, qui
nomme la déclaration centrale qu'elle qualifie, puis un RÉSULTAT ou un ÉCHEC, et ne
compte pas comme un essai de plus (D14). Le rapport
`MPA_DATA_DIR/rapports/sensibilite-<n° du RÉSULTAT>.txt` donne, par configuration, les
agrégats d'usage sous son horloge, les trois axes par modèle, `L` de v0 brut performance
par performance, les fourchettes de sa paire sous l'écoulé et la dérive de v0 brut. La
sensibilité est rapportée, jamais utilisée pour choisir. Extrait de sa synthèse sur le
monde synthétique : pour v0 brut, les valeurs comparées, perdues, gagnées, de support
changé et changées, configuration par configuration.

```bash
just backtest courbe.csv --sensitivity
```

```text
             v0 brut                             valeurs comparées   perdues             gagnées             support changé      valeur changée
              1  Δ 100 m, ε 15 m, écoulé         72                  0                   0                   64                  59
              2  Δ 100 m, ε 30 m, écoulé         72                  0                   0                   64                  59
              3  Δ 100 m, ε 45 m, écoulé         72                  0                   0                   64                  59
              4  Δ 250 m, ε 15 m, écoulé         72                  0                   0                   0                   0
              5* Δ 250 m, ε 30 m, écoulé         72                  0                   0                   0                   0
              6  Δ 250 m, ε 45 m, écoulé         72                  0                   0                   0                   0
              7  Δ 500 m, ε 15 m, écoulé         72                  0                   0                   64                  47
              8  Δ 500 m, ε 30 m, écoulé         72                  0                   0                   64                  47
              9  Δ 500 m, ε 45 m, écoulé         72                  0                   0                   64                  47
             10  Δ 250 m, ε 30 m, M θ1           72                  30                  0                   35                  35
             11  Δ 250 m, ε 30 m, M θ2           72                  30                  0                   35                  35
             12  Δ 250 m, ε 30 m, M θ3           72                  30                  0                   35                  35
             13  Δ 250 m, ε 30 m, M θ4           72                  30                  0                   35                  35
             14  Δ 250 m, ε 30 m, M θ5           72                  30                  0                   35                  35
             15  Δ 250 m, ε 30 m, (M+U) θ1       72                  0                   0                   0                   5
             16  Δ 250 m, ε 30 m, (M+U) θ2       72                  0                   0                   0                   5
             17  Δ 250 m, ε 30 m, (M+U) θ3       72                  0                   0                   0                   5
             18  Δ 250 m, ε 30 m, (M+U) θ4       72                  0                   0                   0                   5
             19  Δ 250 m, ε 30 m, (M+U) θ5       72                  0                   0                   0                   5
             * comparateur
```

| Option de `mperf backtest` | Rôle | Défaut |
|---|---|---|
| `--curve courbe.csv` | courbe allure↔pente : une entrée déclarée de l'exécution ; `--curve` ou `--rolling`, l'un des deux | — |
| `--rolling W[,W…]` | le backtest glissant (`0010`, précision OG-2) : les fenêtres, en jours ou `all`, distinctes ; une DÉCLARATION par fenêtre, en un processus, et un rapport `comparaison-<n>.txt` dès deux fenêtres | — |
| `--covered-threshold S` | avec `--rolling`, obligatoire : une performance est couverte si sa part hors support est au plus `S` | — |
| `--coverage-tolerance SECONDES` | avec `--rolling`, obligatoire : la tolérance de la correspondance des `activity_refs` | — |
| `--beyond-marker PART` | avec `--rolling` : au-delà du repère, une part hors support plus grande que `PART` | 0.5 |
| `--rule-support-threshold MIN` | avec `--rolling` : le seuil de support des diagnostics de la règle à l'origine (`0020`) ; la lecture de chaque courbe garde le paramètre `curve_min_support_min` de v0 | 10 |
| `--descent-threshold F` | seuil des descentes roulantes et raides (diagnostic de `0010` D6), dans [0.60 ; 1] | 0.80 |
| `--sensitivity` | puis la sensibilité de `0010` D13, enregistrée, et son rapport `sensibilite-<n>.txt` | absente |

`just backtest-rolling <fenêtres> <options>` lance `mperf backtest --rolling` sur le
même manifeste, sans courbe déclarée : chaque performance est jugée avec la courbe
que la règle à l'origine ([`0020`](../decisions/0020-origine-glissante.md))
rend à son origine sur la fenêtre, lue dans `MPA_DATA_DIR/interim/activities/`
(`0010`, précision OG-2). Une DÉCLARATION et un rapport par fenêtre ; dès deux
fenêtres, le rapport `comparaison-<n>.txt`, qui n'est pas un événement du registre.
Le manifeste déclare, par sortie, ses `activity_refs`.

```bash
just backtest-rolling 28,56,all --covered-threshold 0.1 --coverage-tolerance 60
```
