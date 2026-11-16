# 0022 — Profils de démo

- **Date** : 2026-11-15
- **Statut** : acceptée

## Contexte

Le dépôt est public, et l'interface (`0016`) ne montre rien sans un dossier de données réel :
celui qui clone le dépôt n'a pas de quoi l'essayer. `0001` met les données hors du dépôt, et
la règle 1 de `CLAUDE.md` n'y admet que des fixtures synthétiques minuscules (M5-3).

## Options envisagées

**A. Des personnages inventés, construits à la demande** dans `demo/<personnage>/`, ignoré
par git, par les vraies commandes depuis des entrées brutes synthétiques.

**B. Des données de démo commitées** : des dizaines de Mo, des dates fixes, et la page vide
par défaut une fois ces dates passées.

**C. Une horloge forcée** par une variable d'environnement, pour garder des dates fixes : un
interrupteur caché dans le chemin réel.

**D. Un mode « démo » ou un sélecteur de dossier dans l'interface** : une logique de plus dans
`ui/`, contraire à « un athlète, un `MPA_DATA_DIR` ».

**E. Écrire `interim/` directement**, sans export ni ingestion : plus rapide, mais lié aux
contrats de la piste analyse.

## Décision

A : cinq personnages inventés (un débutant, quatre traileurs de même base entraînés
différemment), construits par `mperf demo <personnage>` (`just demo` lance aussi
l'interface), calés sur le jour de la construction.

## Pourquoi

- Le générateur n'écrit que des **entrées brutes** (un export Garmin, des GPX, un journal) ;
  `interim/`, `processed/`, `resultats/` et la courbe de `reference/` sont écrits par les
  **vraies commandes** : un contrat qui change est suivi par la démo sans retouche, et ses
  tests rougissent dans la PR qui le change.
- Les nombres (courbes, parcours, plans, jours) sont inventés et ronds, ou d'ordre de grandeur
  courant, écrits dans `mountain_perf/demo/constantes.py` ; jamais tirés des données de l'athlète (ni valeur, ni loi, ni ordre de grandeur)
  ni d'un jeu externe ; le lieu est fictif. Le générateur est déterministe pour un même (personnage, jour).
- `0001` protège les données **personnelles** par une frontière physique. `demo/` n'en
  contient aucune : rien n'y vient du réel, et un dossier de démo ne reçoit que de l'inventé :
  une trace réelle (une sortie, un préparé) va dans le dossier des données (`MPA_DATA_DIR`), hors
  du dépôt, que le hook protège, et jamais dans `demo/`, que `/demo/` ne garde que des commits ;
  rien n'y est commité (`/demo/` dans `.gitignore`), et les entrées générées se
  reconstruisent à l'octet (ce qu'écrivent les commandes porte son instant). Les fixtures
  restent la seule donnée commitée.
- Gardes : la commande ne lit jamais `MPA_DATA_DIR` pour décider où écrire ; elle n'écrit
  que dans un dossier absent, marque le dossier en dernier (`demo.json`), et ne supprime
  rien. Le hook refuse `just demo` et `mperf demo` aux sessions Claude Code.

## Conséquences

Les nombres de la démo illustrent la chaîne ; ils ne mesurent pas le modèle, et aucun ne va au
`JOURNAL` comme résultat. Un dossier vieillit : il se régénère en le supprimant. Les tests
construisent une version réduite de chaque personnage, ce qui allonge la suite de quelques
minutes. `journal.csv`, tenu à la main et jamais écrit par la bibliothèque (`0019`), l'est ici
par `mperf demo`, dans le seul dossier de démo.
