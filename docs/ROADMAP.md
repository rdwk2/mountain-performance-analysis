# ROADMAP

> **La carte, volontairement grossière.** Le détail d'un jalon s'écrit juste avant
> de l'attaquer — écrire le détail du jalon 7 aujourd'hui, c'est du travail jeté.
> Les idées qui arrivent en cours de route vont dans `BACKLOG.md`, pas ici.

---

## Les trois principes qui gouvernent l'ordre

**1. Tranches verticales, pas couches horizontales.**
On ne fait pas « toute l'ingestion », puis « tout le modèle », puis « toute la viz ».
On fait un chemin fin de bout en bout, puis on l'épaissit. À chaque palier, quelque
chose marche et s'utilise.

**2. Les contrats avant les briques.**
Les schémas qui circulent entre les briques sont définis avant d'implémenter les
briques. C'est ce qui permet de remplacer une brique sans tout casser, et de
travailler sur deux briques en parallèle.

**3. La mesure avant les paramètres.**
Le harnais de backtest existe **avant** qu'on ajoute des effets au modèle. Un
paramètre qui ne fait pas baisser l'erreur mesurée ne rentre pas — ou rentre avec
une justification écrite.

---

## Jalons

### M0 — Fondations
Le socle technique. Aucune logique métier.

- `pyproject.toml`, gestion d'environnement, structure `src/` + `tests/`
- `ruff` + `mypy` (strict sur `src/`) + `pytest`
- un `justfile` avec la commande unique `just check`
- CI GitHub Actions qui lance `just check` sur une machine vierge
- `.env.example` avec `MPA_DATA_DIR`, `.gitignore` qui exclut toute donnée

**Fini quand** : `just check` est vert sur un clone frais, la CI est verte, et le
repo ne contient aucune donnée personnelle.

---

### M1 — Contrats de données
Les schémas typés, sans aucune entrée/sortie.

- `Activity`, `TrackPointStream`, `PaceCurve`, `Route`, `Projection`, `Split`,
  `ReferencePerformance`
- validation (unités, plages, monotonie des cumuls)
- un dictionnaire de données dans `docs/`

**Fini quand** : les schémas sont typés, validés, testés sur des données
synthétiques, et documentés. Rien ne lit encore de fichier.

*Note : le contenu de `ReferencePerformance` dépend un peu de la métrique choisie
en M4. Le prévoir extensible plutôt que chercher à le figer maintenant.*

---

### M2 — GPX → profil
La moitié « tracé » de la tranche verticale.

- lecture GPX, nettoyage et lissage de l'altitude
- rééchantillonnage sur une grille à pas fixe (~50 m)
- pente par pas, cumuls D+/D−, détection des descentes (pour la « profondeur »)

**Fini quand** : une commande donne distance, D+, D−, profil, sur un GPX ; tests
d'invariants (D+ de la grille ≈ D+ du GPX, monotonie de la distance cumulée,
stabilité au changement de densité d'échantillonnage).

**Piège connu** : le lissage de l'altitude change le D+ total de plusieurs
centaines de mètres. Le paramètre de lissage doit être explicite et documenté,
pas enfoui.

---

### M3 — Moteur de projection v0
Le modèle le plus simple qui marche de bout en bout.

- courbe allure↔pente **figée** (reprise de l'ancien projet, cf. `MODELE_V1.md`)
- `v = pace(pente) × effort`. **Zéro fatigue, zéro altitude, zéro chaleur.**
- sortie : tableau de temps de passage (CSV/JSON)

**Fini quand** : `mperf project route.gpx --curve courbe.csv --effort 0.92` sort un tableau de passages.
C'est déjà un outil utilisable.

---

### M4 — Backtest ⭐
Le jalon qui transforme le projet. À partir d'ici, tout changement est mesurable.

- **Première tâche du jalon : choisir la métrique d'erreur**, avec les données
  sous les yeux. Candidats à départager :
  - erreur absolue moyenne sur le temps cumulé à chaque point de passage
  - erreur en % sur le temps total
  - erreur par type de segment (montée / descente raide / descente roulante / plat)
  - erreur en fonction de l'avancement dans la course (est-ce qu'on dérive ?)

  Le choix se justifie par l'usage : c'est pour planifier une course, donc
  l'erreur tardive coûte plus cher que l'erreur précoce.

- **baselines à battre** (sinon on ne sait pas si le modèle sert à quelque chose) :
  vitesse constante, règle de Naismith, fonction de Tobler
- **découpage entraînement / test explicite** — voir `CLAUDE.md`, section fuite de données
- `just backtest` → tableau d'erreurs par scénario

**Fini quand** : `just backtest` tourne, la métrique est documentée dans un
decision record, et on connaît l'erreur du moteur v0 contre les baselines.

---

### M5 — Interface v0 (moche, utile)
Volontairement laide. Le but est d'avoir l'outil sous la main tous les jours, et
de vérifier que l'API du moteur est utilisable.

- charger un GPX, choisir une courbe, régler les paramètres, voir profil + tableau
- export CSV

**Point de conception qui rend la suite gratuite** : l'interface **génère ses
contrôles à partir du schéma de paramètres du moteur**. Chaque effet ajouté plus
tard apparaît tout seul, sans toucher au code de l'UI.

**Fini quand** : tu l'utilises pour une vraie sortie sans passer par la ligne de
commande.

---

### M6a — Effets géométriques ∥
Ne dépendent que du GPX et du jeu de backtest. Parallélisable avec M6b.

Un effet = une branche = une comparaison de backtest avant/après :

1. fade en montée (fatigue qui monte en 2ᵉ moitié)
2. fatigue en descente par **profondeur** de la descente en cours
3. facteur d'arrêts (temps écoulé vs temps de mouvement)
4. pénalité d'altitude

**Fini quand** : chaque effet a son avant/après chiffré dans le JOURNAL, et ceux
qui n'améliorent rien sont soit retirés, soit conservés avec une raison écrite.

---

### M6b — Ingestion Garmin + courbe personnelle ∥
L'autre moitié de la tranche verticale. Parallélisable avec M6a.

- acquisition : reprendre le script d'export de l'ancien projet (placé dans
  `legacy/`, ne pas le réécrire depuis zéro) → `raw/`, immuable, reprise après coupure
- parsing des streams → schémas M1 → `interim/` puis `processed/`
- **estimation robuste de la courbe** : binning par pente, filtrage par bande de FC,
  traitement des valeurs aberrantes, et surtout **une mesure de dispersion**
  (elle servira aux intervalles en M8)
- la courbe personnelle remplace la courbe figée ; le backtest dit de combien on gagne

**Fini quand** : `mperf curve --hr-center 150` régénère une courbe depuis les
données brutes, et le backtest mesure l'effet du changement de courbe.

**Test de non-régression offert** : la nouvelle implémentation doit retrouver
approximativement les courbes de l'ancien projet sur les mêmes entrées.

---

### M7 — Effets physiologiques et environnementaux
Nécessite M6b.

- chaleur basée sur la **température réelle** de chaque activité, pas sur un
  forfait horaire
- acclimatation à la chaleur comme modulateur
- dette de sommeil réelle (Body Battery / heures de sommeil) au lieu du forfait nuit
- éventuellement : état de forme au moment de la course

Même discipline qu'en M6a : un effet, une mesure, une décision.

---

### M8 — Incertitude et spécialisation du modèle
Le jalon « maths ».

- **fourchettes P50 / P80** dérivées des données : la dispersion de la courbe
  allure↔pente et l'erreur résiduelle mesurée au backtest donnent des quantiles.
  On remplace « j'ai bidouillé trois scénarios » par un intervalle calibré.
- **deux courbes de descente** : roulant / faux-plat descendant vs raide.
  (Faiblesse déjà chiffrée sur l'athlète : −37 % sur le roulant vs −23 % sur le raide.)
- vérifier la **calibration** de l'intervalle : sur N courses, ~80 % des temps
  réels doivent tomber dans l'intervalle P80. Sinon l'intervalle ment.

---

### M9 — Interface v1 et vitrine
- refonte de l'UI maintenant que le moteur est stable
- README avec captures, schéma d'architecture, résultats du backtest
- une page « comment marche le modèle » lisible par quelqu'un qui n'est pas du domaine

---

## Dépendances

```
M0 → M1 → M2 → M3 → M4 → M5
                         ├── M6a ──┐
                         └── M6b ──┴── M7 → M8 → M9
```

M6a et M6b sont indépendants l'un de l'autre : rien de l'un ne bloque l'autre.

---

## Hors périmètre pour l'instant

Noté ici pour que ce soit clair que ce n'est pas oublié, mais volontairement écarté :

- VTT et ski de randonnée (le modèle allure↔pente ne se transpose pas tel quel)
- corrélations santé (HRV, sommeil) × entraînement
- déploiement en ligne et gestion des données d'autres utilisateurs
- planification d'entraînement

Ces sujets vivent dans `BACKLOG.md`.
