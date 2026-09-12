# mountain-performance-analysis

Analyse de données de sport de montagne et modélisation de la performance.

**Premier outil (v1)** : projeter les temps de passage sur un tracé GPX à partir de
la courbe allure↔pente personnelle de l'athlète, et valider ces projections contre
des performances réelles.

Python. Usage personnel d'abord, projet portfolio ensuite. Le repo sera rendu public.

---

## Règles dures — non négociables

1. **Aucune donnée personnelle dans le repo.**
   Pas de JSON/FIT Garmin, pas de CSV d'activités, pas de GPX de courses, pas
   d'identifiants, pas de tokens. Tout ça vit hors du repo, dans le dossier pointé
   par la variable d'environnement `MPA_DATA_DIR`.
   Les tests n'utilisent **que** les fixtures synthétiques de `tests/fixtures/`,
   qui sont minuscules, inventées, et commitées.

2. **`just check` doit être vert avant tout commit.**
   Si tu n'arrives pas à le rendre vert, tu t'arrêtes et tu le dis. Tu ne
   contournes pas (pas de `# type: ignore` posé pour faire taire, pas de test
   désactivé) sans le signaler explicitement et en donner la raison.

3. **Tu ne fais que ce qui est demandé.**
   Toute autre idée, amélioration, refactoring ou bug repéré en passant va dans
   `BACKLOG.md` — une ligne, et rien d'autre. Tu ne l'implémentes pas.

4. **Toute logique de calcul a un test.** Un calcul sans test n'est pas fini.
   Pour la modélisation, privilégier les **tests de propriété** (invariants,
   monotonie, comportement aux limites) aux seuls tests par l'exemple.

5. **Pas de nouvelle dépendance sans accord.**
   Tu la proposes, avec la raison et ce que ça coûterait de s'en passer, et tu
   attends. Une dépendance ajoutée en douce est un bug.

6. **`data/raw/` est immuable.**
   On ne modifie jamais un fichier brut. Tout ce qui est en aval doit être
   entièrement régénérable à partir de `raw/`. Si un parsing est faux, on
   re-parse — on ne re-télécharge pas.

7. **Pas de logique métier dans l'interface, ni dans un notebook.**
   L'UI et les notebooks appellent la bibliothèque. S'ils calculent quelque chose,
   c'est que ça manque dans `src/`.

8. **Jamais de commit direct sur `main`.**
   Une tâche = une branche (`<jalon>/<sujet>`, ex. `m2/gpx-profil`) = une pull
   request. La PR est le moment de revue : c'est là que le diff se relit, avec la
   CI verte à côté. Messages de commit préfixés : `feat:` `fix:` `docs:` `test:`
   `refactor:` `build:` `ci:`.

---

## Ce qui appartient à l'humain

Ces décisions ne sont **jamais** prises sans accord explicite. Si l'une se présente
en cours de tâche, tu t'arrêtes et tu demandes :

- l'**architecture** : quelles briques existent, quels contrats entre elles
- le **modèle mathématique** : les équations, les hypothèses et leur justification
- la **métrique d'erreur** et le **protocole de validation** (dont le découpage
  entraînement / test)
- tout ce qui touche aux **données personnelles** de l'athlète

⚠️ **Fuite de données** : calibrer des paramètres sur une course puis rapporter
l'erreur sur cette même course ne veut rien dire. Tout backtest doit expliciter
sur quoi il a été calibré et sur quoi il est évalué. Si une tâche te conduit à
mélanger les deux, tu t'arrêtes et tu le signales.

---

## Méthode de travail

- **Mode plan avant toute tâche non triviale.** Tu proposes le plan, j'y réponds,
  et seulement ensuite tu écris du code.
- **Une tâche = un périmètre borné + un critère d'acceptation vérifiable.**
  Si le critère d'acceptation n'est pas clair, tu le demandes avant de commencer.
- **Petits commits, un concept chacun.** Si un diff dépasse ~300 lignes, c'est
  probablement que la tâche était mal découpée : signale-le.
- **Jamais de fin de session sur du cassé non commité.**
- **Une entrée dans `docs/JOURNAL.md`** à la fin de chaque session de travail :
  date, ce qui a été fait, la conclusion, où c'est rangé.
- **Une décision structurante = un fichier dans `docs/decisions/`** (voir le
  template `0000-template.md`).

---

## Commandes

```bash
just check      # lint + types + tests  ← LA commande. Vert = le projet va bien.
just test       # pytest seul
just lint       # ruff
just fmt        # formatage
just backtest   # (à partir de M4) erreur du modèle sur le jeu de référence
```

---

## Structure

```
src/mountain_perf/     le code de la bibliothèque
  schemas.py           les contrats de données (M1)
  gpx/                 lecture GPX, profil, grille de pente (M2)
  model/               le moteur de projection (M3, puis M6a, M7)
  backtest/            évaluation contre des performances réelles (M4)
  ingest/              acquisition et normalisation Garmin (M6b)
  ui/                  interface — appelle la bibliothèque, ne calcule rien (M5)
  cli.py
tests/
  fixtures/            données synthétiques minuscules, commitées
docs/                  ROADMAP, JOURNAL, PIEGES_DATA, MODELE_V1, decisions/
notebooks/             exploration uniquement, jamais de logique
```

Les données réelles vivent **hors du repo**, sous `MPA_DATA_DIR` :

```
$MPA_DATA_DIR/
  raw/          export Garmin brut — IMMUABLE
  interim/      parsé et normalisé — régénérable depuis raw/
  processed/    prêt à l'analyse — régénérable
  routes/       GPX personnels
  reference/    performances réelles (jeu de backtest)
```

---

## Conventions

- Python 3.12+, annotations de type partout, `mypy` en mode strict sur `src/`
- `ruff` pour le lint et le formatage
- Noms de domaine en anglais dans le code (`grade`, `pace`, `ascent`), commentaires
  et documentation en français
- **Unités** : la vitesse circule en **m/s** partout dans le code. `min/km` et
  `VAM` sont des formats d'**affichage**, jamais de stockage — voir
  `docs/decisions/0002-unites.md`, qui explique pourquoi (min/km diverge en montée
  raide et casse les produits du modèle).
- Unités **explicites dans les noms** : `distance_m`, `speed_ms`, `duration_s`,
  `elevation_m`, `vam_mh`, `grade` (fraction, pas pourcentage). Une variable
  d'unité ambiguë est un bug en attente.
- Les conversions se font **aux frontières** (lecture de fichier, affichage),
  jamais au milieu d'un calcul.
- Les paramètres du modèle sont **déclaratifs** (un schéma, pas des constantes
  éparpillées) : l'interface génère ses contrôles à partir de ce schéma.

---

## Avant de toucher aux données Garmin

Lis **`docs/PIEGES_DATA.md`**. Il liste des pièges déjà rencontrés et déjà payés
sur la version précédente du projet. Les redécouvrir coûterait plusieurs heures
chacun.
