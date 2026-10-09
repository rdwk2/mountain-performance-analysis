# ROADMAP

> **La carte, volontairement grossière.** Le détail d'un jalon s'écrit juste avant
> de l'attaquer — écrire le détail du jalon 7 aujourd'hui, c'est du travail jeté.
> Les idées qui arrivent en cours de route vont dans `BACKLOG.md`, pas ici.

Deux pistes partagent ce dépôt et sa méthode : le **moteur de prédiction** (jalons
`M<n>`, ci-dessous) et la **piste analyse** (jalons `AN<n>`, en fin de fichier), qui
analyse les données d'entraînement, de récupération et de sommeil de l'athlète.

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
L'autre moitié de la tranche verticale. Parallélisable avec M6a. **Partagé avec la
piste analyse** : elle écrit l'ingestion, le moteur estime la courbe.

- **À la piste analyse** (AN1, puis à la demande) :
  - acquisition : reprendre le script d'export de l'ancien projet (placé dans
    `legacy/`, ne pas le réécrire depuis zéro) → `raw/`, immuable, reprise après
    coupure ; elle attend la première mise à jour des données ;
  - ingestion : `raw/` → contrats → `interim/`, dans `src/mountain_perf/ingest/`, aux
    conventions du moteur (m/s, distance de `gpx/geo.py`, profil de
    `gpx/profile.py`) ; les séries d'activité viennent des FIT, à pleine résolution
    (`docs/decisions/0013`) ;
  - les détecteurs de qualité (`QualityFlag`, écrêtage des pics).
- **Au moteur** :
  - **estimation robuste de la courbe**, sur les positions à pleine résolution et avec
    la chaîne du profil : binning par pente, filtrage par bande de FC, traitement des
    valeurs aberrantes, et surtout **une mesure de dispersion** (elle servira aux
    intervalles en M8) ;
  - la courbe personnelle remplace la courbe figée ; le backtest dit de combien on
    gagne.
- Le moteur lit `interim/` par ses contrats, jamais `processed/`, qui appartient à la
  piste analyse.

**Fini quand** : `mperf curve --hr-center <bpm>` régénère une courbe depuis les
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
  (L'écart entre roulant et raide est à mesurer : sous-classes de descente du rapport
  D15, et question Q4 de la piste analyse.)
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
L'estimation de la courbe (M6b) attend l'ingestion des activités, écrite par la piste
analyse en AN1.

```
AN0 → AN1 → AN2 → AN3 …
       └── interim/ ──→ M6b (courbe)
```

M7 attend aussi AN2, qui ingère les nuits et les jours (sommeil, Body Battery).

---

## Hors périmètre pour l'instant

Noté ici pour que ce soit clair que ce n'est pas oublié, mais volontairement écarté :

- VTT et ski de randonnée **pour le moteur** (le modèle allure↔pente ne se transpose
  pas tel quel) ; la piste analyse les étudie
- déploiement en ligne et gestion des données d'autres utilisateurs (la piste analyse
  vise un usage local par un autre athlète, sur ses propres données : un athlète, un
  `MPA_DATA_DIR`)
- planification d'entraînement

Ces sujets vivent dans `BACKLOG.md`.

---

## La piste analyse (AN)

Décidée le 2026-10-06. Même dépôt, même méthode (brief relu, mode plan, PR relue),
jalons `AN<n>`. Sa méthode est dans `docs/analyse/CHARTE.md`, ses questions dans
`docs/analyse/QUESTIONS.md`. Deux principes la gouvernent en plus des trois du
moteur :

- **Pour tout athlète.** Rien de propre à un athlète ni à sa montre dans le code : les
  seuils personnels se calculent depuis ses données ou se déclarent dans sa
  configuration.
- **Permanent.** Une question livre une commande ou une page qui se recalcule à
  chaque mise à jour des données, pas un rapport unique.

Elle partage avec le moteur l'ingestion et `interim/` (M6b). Elle a en propre
`processed/` (les tables d'analyse), ses résultats, et ses dépendances, déclarées à
part du cœur (`docs/decisions/0011`).

### AN0 — Cadrage
Examen des données (hors du dépôt), questions, charte, bibliothèques, et cette
documentation.

**Fini quand** : la PR de documentation est fusionnée et le brief d'AN1 est écrit.

---

### AN1 — Activités et montées
- avant le code : le codec rendu commun, dans une PR à part, avec l'accord du moteur
  (`docs/decisions/0013`, point 4)
- ingestion des activités : index de l'export et séries des FIT, contrats et lecteur
  d'`interim/` sans dépendance (`docs/decisions/0013`)
- vues `Activity` et `TrackPointStream` pour M6b, et table des types de la source vers
  `Sport`, relue par le moteur
- tables `activités` et `montées` de `processed/`, avec une définition de la montée
  dont on contrôle la stabilité
- figure descriptive de Q1 : la vitesse ascensionnelle à pente, durée et altitude
  comparables

**Fini quand** : une commande régénère `interim/` et `processed/` depuis `raw/`, les
vues du moteur se calculent depuis `interim/`, et la figure de Q1 se recalcule.

---

### AN2 — Données journalières et tableau de bord
- ingestion des nuits et des jours (sommeil, HRV, FC de repos, indicateurs de Garmin)
- tableau de bord du suivi de la récupération

---

### AN3 et suivants — Une question par jalon
Une question, ou deux très proches, par jalon, numéroté à son ouverture. Ordre prévu :
Q2, Q3, Q4 ; les suivantes se choisissent à l'ouverture de chaque jalon. Chaque
question a son plan d'analyse, relu avant le code (charte).
