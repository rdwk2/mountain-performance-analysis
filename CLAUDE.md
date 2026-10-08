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
   Titre de PR : `M<n> — <nom du jalon>` (ex. `M1 — Contrats de données`). Avec
   « Squash and merge », ce titre devient le message du commit sur `main` : la
   liste des PR est donc la table des matières du projet.

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
just dictionary # régénère docs/DICTIONNAIRE_DONNEES.md depuis les docstrings
just backtest courbe.csv  # backtest enregistré de v0 brut, rapport D15 (M4b-5) ; MPA_DATA_DIR/reference/
uv run mperf profile tests/fixtures/mini_11.gpx  # compte-rendu GPX (M2), --csv pour la grille
uv run mperf project tests/fixtures/mini_11.gpx --curve tests/fixtures/courbe_synthetique.csv  # temps de passage (M3)
uv run mperf match tests/fixtures/appariement_reference.gpx tests/fixtures/appariement_trace_x01.gpx  # points de score (M4a-2a)
# mperf match, sections 5 à 9 (M4a-2b) : segments, couverture, préfixe, horloges, épisodes
# mperf match, section 10 (M4a-3) : passages nommés, événements, attribution des arrêts
uv run mperf match tests/fixtures/appariement_reference.gpx tests/fixtures/appariement_trace_x01.gpx --curve tests/fixtures/courbe_synthetique.csv  # scores de v0 brut, sections 11 à 13 (M4b-2)
```

---

## Structure

```
src/mountain_perf/     le code de la bibliothèque
  validation.py        vérifications partagées des contrats, ContractError (M1)
  schemas/             les contrats de données (M1) — aucune E/S, aucun algorithme
    common.py          Sport, QualityFlag, SourceRef, plages physiques
    parameters.py      ParameterSpec, ParameterSet
    route.py           PointKind, NamedPoint, Route, ResolvedPoint, RouteProfile
    activity.py        Activity, TrackPointStream (M1b)
    curve.py           PaceCurve, CurveProvenance (M1b)
    projection.py      Passage, Segment, Projection (M1b)
    reference.py       TimingConvention, ObservedPassage, ReferencePerformance (M1b)
    outing.py          sorties, artefacts, rétention, performance, statuts (M4a)
    trace.py           RecordedTrace, trace réalisée lue sans rien de dérivé (M4a)
    clock.py           conventions, horloges, partition M/S/U, totaux, épisodes (M4a)
    matching.py        PointStatus, ScorePointObservation : points de score (M4a-2a) ;
                       segments, Coverage, AdmittedTotals, MatchResult (M4a-2b) ;
                       PassageObservation, EpisodeAttribution, PassageMatchResult (M4a-3)
    metrics.py         MetricValue, ClassMetrics, SupportMetrics, PositiveTimeDiagnostic,
                       LogRatioEnvelope, PassageErrors, TargetMember, UsageTarget (M4b-1)
    scoring.py         Scenario, AdmittedSegment, ObservedPoint, OutingObservation,
                       ModelForecast, ClockScores, ScenarioScores, OutingScores :
                       observation, prévision, scores d'une sortie (M4b-2)
    repeatability.py   TwoWayFit, RepeatabilityDay, ClassFit, ClassScore, FoldScores,
                       ClockReference, RepeatabilityReference : référence de
                       répétabilité (M4b-3)
    registry.py        EventKind, Declaration, Result, Failure, RegistryEvent,
                       RegistryLog, TrialCounts… : registre des expériences (M4b-4)
    calibration.py     ModelKind, CalibrationPopulation, ModelCalibration,
                       CalibratedScenarioScores, CalibratedPerformance… : calage des
                       modèles de référence (M4c-1)
    _dictionary.py     rendu du dictionnaire de données depuis les docstrings
  gpx/                 lecture GPX, profil, grille de pente (M2)
    geo.py             haversine 2D, polyligne dédoublonnée, projection point-segment
    reader.py          read_gpx, GpxReadResult, GpxError
    trace_reader.py    read_trace, TraceError : trace réalisée horodatée (M4a)
    profile.py         paramètres, grille, lissage, passages et diagnostics de calcul
  model/               le moteur de projection (M3, puis M6a, M7) ; ProjectedTimeline,
                       la chronologie projetée d'un profil (M4b-2)
    baselines.py       vitesse constante, Naismith, Tobler : allures et chronologies
                       des baselines de 0010 D9.1 (M4c-1)
  backtest/            évaluation contre des performances réelles (M4)
    calendar.py        jour civil à Paris, origine o_j, disponibilité (M4a)
    manifest.py        load_manifest, ManifestReadResult, ManifestError (M4a)
    outings.py         sorties retenues, domaine, performances (M4a)
    series.py          trous, blocs, lissage par bloc, d_r (M4a)
    clocks.py          fenêtres, qualification, confirmation, horloges cumulées (M4a)
    geometry.py        géométrie de référence, plan local, repère, projection (M4a-2a)
    matching.py        grille de score, prédicats, franchissements, match_points (M4a-2a)
    segments.py        régimes, admissibilité, couverture, préfixe, totaux admis, match_trace (M4a-2b)
    passages.py        rattachement, recherche, association, chronologie, maintien, observe_passages (M4a-3)
    sensitivity.py     les 19 configurations de sensibilité, déclarées (M4a-2b)
    metrics.py         seuil, prédicats, métriques du support, diagnostic, enveloppes, C_k,
                       K par défaut, q_usage : métriques D7, fonctions pures (M4b-1)
    scoring.py         observe_outing, usage_forecast, control_forecast, score_scenario,
                       score_outing, report_clocks, v0_scores : scores de v0 brut (M4b-2) ;
                       clock_scores, realized_profile (M4c-1)
    repeatability.py   two_way_fit, contraction_rate, repeatability_reference : référence
                       D8 d'un parcours (M4b-3)
    codec.py           écriture canonique des contrats en JSON, documents (M4b-4)
    registry.py        journal, documents, ajout, relecture, comptage des essais (M4b-4)
    execution.py       git, domaine, déclaration, exécution enregistrée de just backtest (M4b-5)
    report.py          valeurs du rapport D15, fonctions pures (M4b-5)
    calibration.py     baseline_scores, calibration_population, calibrate,
                       calibrated_scores, calibrate_performances : calage D9 (M4c-1)
  ingest/              acquisition et normalisation Garmin (M6b)
  ui/                  interface — appelle la bibliothèque, ne calcule rien (M5)
  cli.py               mperf profile <fichier.gpx>, compte-rendu ou CSV sur stdout ;
                       mperf match <référence.gpx> <trace.gpx>, points de score (M4a-2a),
                       segments, couverture et horloges (M4a-2b), passages (M4a-3) ;
                       --curve, --no-reference : scores de v0 brut (M4b-2) ;
                       mperf backtest <manifeste.json> --curve : backtest enregistré, rapport D15 (M4b-5)
tests/
  conftest.py          MPA_DATA_DIR sur un dossier temporaire neuf pour chaque test (M4c-1)
  strategies.py        stratégies Hypothesis des contrats, réutilisées par tous les jalons
  fixtures/            données synthétiques minuscules, commitées
scripts/               outillage du dépôt (ex. `just dictionary`), jamais de logique métier
docs/                  ROADMAP, JOURNAL, PIEGES_DATA, MODELE_V1, decisions/,
                       DICTIONNAIRE_DONNEES (généré — ne pas éditer à la main)
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
  registre/     registre des expériences (0010 D14), écrit par just backtest seul
  rapports/     rapports D15 de just backtest, jamais réécrits
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
  `elevation_m`, `vertical_speed_ms`, `grade` (fraction, pas pourcentage). Une
  variable d'unité ambiguë est un bug en attente.
- `vertical_speed_ms` est **signée** ; une seule grandeur pour la montée et la
  descente. « VAM » est une étiquette d'affichage, pas un nom de variable.
- `grade = Δaltitude / distance horizontale`, `speed_ms` est la vitesse
  horizontale ; cette convention doit être **identique** à la construction de la
  courbe (M6b) et à son application au GPX (M2/M3) — un mélange des deux crée un
  biais systématique qui croît avec la pente.
- Les conversions se font **aux frontières** (lecture de fichier, affichage),
  jamais au milieu d'un calcul.
- Les paramètres du modèle sont **déclaratifs** (un schéma, pas des constantes
  éparpillées) : l'interface génère ses contrôles à partir de ce schéma.

---

## Avant de toucher aux données Garmin

Lis **`docs/PIEGES_DATA.md`**. Il liste des pièges déjà rencontrés et déjà payés
sur la version précédente du projet. Les redécouvrir coûterait plusieurs heures
chacun.
