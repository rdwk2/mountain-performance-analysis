# JOURNAL

> Trace chronologique de ce qui a été fait, pour ne pas se re-raconter.
> **Une entrée par session de travail**, ajoutée en haut : date · ce qui a été fait ·
> la conclusion · où c'est rangé.
> Le détail vit dans le code et les livrables ; ici c'est l'index.
> Les décisions structurantes ont leur propre fichier dans `decisions/`.

Format :

```
### AAAA-MM-JJ · Titre court
Ce qui a été fait. Ce qu'on en conclut. Où c'est rangé.
Backtest (à partir de M4) : métrique avant → après.
```

---

### 2026-09-24 · M4a-1 — Backtest : données et horloges
Première des trois PR du lot M4a (brief M4a-1 rév. 2, `0010`). `0010` commité octet
pour octet (SHA-256 `e020c47a…ffbe2e` vérifié avant la copie et sur le commit) ;
dix-neuf lignes « Backtest (0010) » au backlog. Contrats `outing`, `trace`, `clock`
(18 types au dictionnaire) ; `read_trace` (tronçons et fichiers concaténés, même
instant écarté et compté, instant décroissant refusé) ; séries dérivées (blocs,
lissage par bloc, `d_r`) ; calendrier de Paris et origine `o_j` avec `tzdata` sous
Windows (décision rdw du 2026-09-23) ; `load_manifest` (refus d'athlète avant toute
ouverture de fichier, trace refusée conservée pour la règle des 4 h, emplacements par
empreinte) ; sorties retenues, domaine, performances ; horloges M/S/U sous les cinq
conventions, cumulés, totaux, épisodes.
Quatre précisions de relecture intégrées : doublon sans extension → `kind`
`"unknown"`, `sha256` déclaré comparé sans tenir compte de la casse,
`clock_duration_s` refuse `start_s > end_s`, ligne `trace_reader.py` dans
`CLAUDE.md`. Toutes les valeurs du § 7.1 reproduites à leur tolérance, sans
tolérance élargie, dès le premier essai du prototype. Six contre-épreuves par mutation
exécutées et restaurées par empreinte : `>= c` → `> c`, rétention `<=`, diamètre sur
les seules bornes, lissage à travers les trous, `v_z` signée — chacune rougit le test
attendu ; seuil d'économie au minimum des conventions — `qualify` lève dès la
collecte. Partition d'une trace synthétique de 77 000 enregistrements : 4,6 s.
Contrats existants, défauts de `0008` et lignes existantes du backlog inchangés ;
aucune donnée personnelle, toutes les fixtures inventées.
Conclusion : `just check` vert avant chacun des huit commits, 939 tests à la fin.
Rangé dans `src/mountain_perf/schemas/{outing,trace,clock}.py`,
`src/mountain_perf/gpx/trace_reader.py`, `src/mountain_perf/backtest/`,
`tests/test_{schemas_outing,schemas_trace,schemas_clock,gpx_trace_reader}.py`,
`tests/test_backtest_*.py`, `tests/fixtures/{outings,traces}.py`,
`tests/fixtures/trace_troncons.gpx`, `tests/fixtures/manifeste/`,
`docs/decisions/0010`, branche `m4a/donnees-horloges`.

### 2026-09-20 · M3 — Moteur de projection v0
Tranche verticale fermée : `mperf project trace.gpx --curve courbe.csv` produit un
tableau de temps de passage. Lecture d'un CSV de courbe et de son compagnon
`<stem>.meta.json` obligatoire (`curve_io`), modèle d'allure à deux régimes
(`pace`), moteur du `RouteProfile` à la `Projection` avec diagnostics (`engine`),
`format_duration`, sous-commande `project` (rapport ou `--csv`). Décisions D2 à D8
consignées dans `docs/decisions/0009`.
Deux points tranchés en cours de route, hors brief révision 4 : `PaceCurve.sport`
n'avait aucune source — il devient une clé **obligatoire** du compagnon, valeurs
`foot`/`ski_touring`/`mtb`, inconnue refusée en nommant les valeurs admises ; et le
tableau du § 5.6 ne peut pas passer par un GPX — mesuré, `haversine_m` rend
599,999 999 999 7 m sur un méridien de sept points à 100 m, et des pentes à
0,100 000 000 000 3. L'écriture CSV est donc extraite dans `write_passages_csv`,
testée cellule par cellule sur le profil synthétique, le bout en bout restant sur
`mini_11.gpx`. Aucune tolérance du brief élargie.
Valeurs du § 5 reproduites : 540 s exact, 675 s exact à effort 0,8, 370/3 à
1,4e-14, 1250/3 exact, 200 m / 300 s hors support. Seul écart, signalé et non
absorbé : `p(−5 %)` tombe à 1 ulp de `11/30` (5,6e-17), qui n'est pas représentable
en binaire — les allures sont comparées à 1e-12 absolu, trois ordres de grandeur
sous la tolérance des temps du brief.
Deux contre-épreuves exécutées en copie restaurée par empreinte : remplacer la
règle 3 de sélection du support par un filtre plat `time_min >= seuil` fait rougir
trois tests (support retenu [−40 %, +40 %] au lieu de [−20 %, +20 %]) ; écrire
`arrival_s` dans `segment_duration_s` ne fait rougir que la dernière ligne du CSV,
exactement le mode d'échec que le § 5.6 annonce.
Contrats `schemas/` inchangés, aucune dépendance ajoutée, défauts `grid_step_m = 50`
et `smoothing_window_m = 150` inchangés, aucune ligne existante de `BACKLOG.md`
cochée. Aucun accès aux données personnelles : toutes les fixtures sont inventées.
Conclusion : `just check` vert avant chacun des six commits, 523 tests à la fin.
Rangé dans `src/mountain_perf/model/`, `src/mountain_perf/{units,cli}.py`,
`tests/{test_model_*,test_cli_project}.py`, `tests/fixtures/{courbe_synthetique.csv,
courbe_synthetique.meta.json,curves.py,projection.py}`, `docs/decisions/0009`,
branche `m3/moteur-projection`.

### 2026-09-19 · Calage GPX post-M2 — maintien des défauts provisoires
Exploration sur des parcours réels de reliefs différents : répétitions
d'activités et tracés préparés, pas fixé à 50 m, fenêtres de lissage demandées
de 0, 150 et 250 m. Comparaison de l'étendue du D+ entre activités et de l'écart
du préparé à leur médiane, avec tolérances définies avant les essais, complétée
par l'examen des profils. Calculs au M2 `fe07c4020cb356b59fe5f37ff05bcd3aee72cc58`.
Aucun réglage testé ne satisfait tous les groupes ; un lissage plus fort peut
rapprocher les totaux tout en effaçant de petites formes du relief.
Décision acceptée : conserver `grid_step_m = 50` et `smoothing_window_m = 150`
comme provisoires, et différer leur validation générale. Pas de référence
altimétrique terrain ni d'étude de sensibilité au pas ; ces observations
ne valident pas les temps de projection. La préparation M3 peut poursuivre
avec ce statut explicite. Aucun changement de code ou de défaut.
Détail conservé hors dépôt dans le dossier de conception :
`11_CALAGE_GPX_POST_M2.md`, `11_CALAGE_Q2.md` et `resultat/11_LISEZ_MOI.md`.
La ligne de suivi M2/M3 du backlog demeure ouverte pour la validation différée.

### 2026-09-17 · M2 — Couverture A1/A2 après arbitrage A
Reprise de la PR #5 à `873f9f10756008c076cd96d7edb568fd5d6700ec`, tête locale
et distante inchangée depuis la relecture C. Deux tests ajoutés uniquement dans
`tests/test_gpx_profile.py` : A1 vérifie le passage au seuil exact de 3 m sur le
montage équatorial prescrit ; A2 exige la grille exacte `(0.0, 50.0, 75.0)` pour
`L = 75.0`, `h = 50.0`, en conservant les tests de bornes existants.
Preuves ciblées exécutées séparément dans deux copies jetables : chaque nouveau
test passe sur le code non muté (1 test vert), puis échoue sous sa mutation.
M09 (`<=` → `<` au filtre maximal) donne zéro passage au lieu d'un ; M10
(`<` → `<=` au reste de grille) donne `(0.0, 75.0)` au lieu des trois points.
Chaque source a été restaurée à l'identique avant suppression de la copie.
Aucune autre campagne de mutations ; aucun changement permanent de calcul,
de contrat, de fixture partagée, de dépendance ou de décision.
Conclusion : `just check` vert avant chacun des deux commits, 425 puis 426 tests,
avec lint, formatage et mypy strict verts. Rangé dans `tests/test_gpx_profile.py`
et cette entrée, branche `m2/gpx-profil`, PR #5 ; revue GitHub finale et fusion
laissées à rdw selon l'arbitrage A.

### 2026-09-17 · M2 — GPX → profil
Lecture GPX 1.0/1.1/sans namespace, dédoublonnage conservant le premier point,
distance haversine horizontale, grille puis lissage, résolution des lieux nommés
et commande `mperf profile` (texte/CSV). Reprise du plan en six commits avec les
corrections arbitrées du brief révision 5 : candidats lus sur `t`, diagnostics
issus de `profile.py`, erreurs numériques converties en `GpxError`.
Contrats M1 et dépendances inchangés ; aucun accès aux données personnelles.
Vérifications exécutées dans cette session : `just check` avant chaque commit ;
oracle 120 m et `40(1+√2)` m avec comparaison des altitudes ; subdivision avec
lissage à 1e-9 m ; décimation à 1 % ; résolution de la sucette, des lacets et de
l'aller-retour avant/après subdivision ; tests de propriété avec lieux proches.
La commande réelle sur `mini_11.gpx` affiche 1 000 m, 21 points, D+ 44 m lissé
et 50 m brut ; dernière cellule `grade` du CSV vide. `just dictionary` ne change
pas le dictionnaire. Pas de seuil modifié, de test désactivé ni de dérogation
Hypothesis. Les commits lecture, profil et résolution dépassent 300 lignes avec
leurs tests et fixtures (377, 500 et 376 lignes modifiées), signalé en session.
Conclusion : `just check` vert (424 tests). Rangé dans `src/mountain_perf/gpx/`,
`src/mountain_perf/cli.py`, `tests/test_gpx_*.py`, `tests/test_cli_profile.py`,
`tests/fixtures/mini_*.gpx`, `tests/fixtures/synthetic_routes.py`,
`docs/decisions/0008-geometrie-et-lissage.md`, branche `m2/gpx-profil`.
Les suites hors périmètre sont inscrites au backlog ; livraison en PR, sans fusion.

### 2026-09-14 · M1b — Contrats de la performance
Contrats du côté athlète et de la sortie, sans E/S ni algorithme de modélisation.
`Activity` (référence son flux, deux durées pour un résidu attribuable),
`TrackPointStream` (distance croissante au sens large, 1 point suffit),
`CurveProvenance`/`PaceCurve` (provenance et `sample_count` portés par la courbe),
`Passage`/`Segment`/`Projection` (segments en propriété, premier passage à 0 et
dernier en fin de profil, `departure[i] ≤ arrival[i+1]`, mouvement monotone et
borné par le temps écoulé), `TimingConvention`/`ObservedPassage`/`ReferencePerformance`
(convention par passage, `UNKNOWN` légitime). Décidé en cours de route : D+/D−/altitudes
de segment avec **altitude linéaire entre points de grille** (l'hypothèse de
`RouteProfile.grade`) ; invariant central sommé sur les arrêts **intérieurs** ; fixture
hors grille à 1 500 m comme seul oracle chiffré de l'interpolation. **Écart au brief** :
`utc_offset_s` n'est pas un champ mais une propriété lue sur le fuseau de
`start_time`, stocké dans son fuseau à décalage fixe — normaliser en UTC puis recouper
un champ parallèle n'était pas idempotent (`replace` levait). 0006 amendée, 0005 écrite.
`require_aware` renvoie désormais le décalage. Trois lignes de backlog.
Conclusion : `just check` vert (346 tests). `src/` ≈ 400 lignes hors docstrings, assumé comme
au M1a. Rangé dans `src/mountain_perf/schemas/{activity,curve,projection,reference}.py`,
`tests/`, `tests/fixtures/performance.py`, `docs/decisions/0005-…`, branche
`m1b/contrats-performance`.

### 2026-09-13 · M1a — Contrats du tracé
Contrats du socle et du tracé, sans E/S ni algorithme. `validation.py` :
`ContractError` et vérifications génériques (dont `require_finite` sur tout flottant
et `require_immutable_sequence`, qui refuse une `list` plutôt que de la copier).
Paquet `schemas/` : `Sport`, `QualityFlag` (trois valeurs définies, aucun détecteur),
`SourceRef` (nom de fichier jamais chemin, sha256, instant normalisé UTC),
`ParameterSpec`/`ParameterSet` (complété par les défauts, table en lecture seule),
`NamedPoint`, `Route`, `ResolvedPoint`, `RouteProfile` — pente et cumuls D+/D− en
propriétés, un même lieu résolu deux fois autorisé et testé (fixture « sucette »,
Source traversée à 1 km et 5 km). Stratégies Hypothesis réutilisables dans
`tests/strategies.py`. Dictionnaire de données généré depuis les docstrings
(`just dictionary`), avec un test qui rougit si le fichier commité est périmé
(contre-épreuve faite) ; annotations rendues depuis les chaînes sources pour ne pas
dépendre de la version de Python. Membres d'enum décrits dans des `Mapping` voisins
(Python jette les docstrings de membres). Décisions 0003, 0004, 0006, 0007 ; 0005
laissée libre. mypy : racines `src`/`tests` explicites (`fixtures/routes.py` était vu
sous deux noms).
Conclusion : `just check` vert (178 tests). Code de `src/` ≈ 510 lignes hors
docstrings, au-dessus du seuil de 300 — signalé dans la PR. Rangé dans
`src/mountain_perf/{validation.py,schemas/}`, `tests/`, `scripts/`,
`docs/DICTIONNAIRE_DONNEES.md`, `docs/decisions/`, branche `m1a/contrats-trace`.

### 2026-09-13 · Ménage post-M0
Sans logique métier. Ruff : `allowed-confusables = × − ’ … –` avec un commentaire
qui dit pourquoi RUF001-003 restent actives (homoglyphes) ; le `×` du docstring
de `units` et le `−` d'un commentaire de `test_units`, retirés au M0 pour faire
passer le lint, sont remis. Contre-épreuve : une espace insécable dans une chaîne
est toujours refusée. `CLAUDE.md` règle 8 : convention de titre de PR
`M<n> — <nom du jalon>`. `BACKLOG.md` : cinq lignes ajoutées (README « Méthode »,
signature SSH, hook `PreToolUse` sur le dossier de données, worktree M6a/M6b,
skill de la boucle effet → backtest), protection de `main` cochée.
Vérifié : `.claude/settings.local.json` n'est pas suivi par git, rien à ignorer.
Environnement : le certificat intercepté se contourne avec `UV_SYSTEM_CERTS=1`
(drapeau `--system-certs`), désormais posée au niveau utilisateur — Claude
Desktop doit être relancé complètement pour la voir. Après déplacement du dossier
du projet, les lanceurs du `.venv` (`mypy.exe`) gardaient l'ancien chemin :
`uv sync --locked --reinstall` les régénère.
Conclusion : `just check` vert (32 tests) à chaque commit. Rangé dans
`pyproject.toml`, `CLAUDE.md`, `BACKLOG.md`, branche `chore/menage-post-m0`.

### 2026-09-12 · M0 — Fondations
Socle technique posé, sans logique métier : `pyproject.toml` en src-layout géré
par uv (Python 3.12+, aucune dépendance de calcul), ruff + mypy strict, `justfile`
(`check` = lint + types + tests, une commande par ligne pour qu'aucun échec ne
soit masqué), CI GitHub Actions qui installe uv et just puis lance `just check`
sur machine vierge. Module `config.data_dir()` qui lit `MPA_DATA_DIR` et échoue
avec la marche à suivre. Module `units` (m/s interne, conversions km/h et allure,
vitesse verticale signée, `format_pace`, `format_vam`) avec tests par l'exemple et
propriétés hypothesis. Règle posée : le calcul est strict, l'affichage ne plante
jamais.
Décision affinée en passant : `vam_mh` → `vertical_speed_ms` signée, convention
`grade = Δalt / distance horizontale` avec `speed_ms` horizontale (0002, CLAUDE.md).
Conclusion : `just check` vert (32 tests), mypy strict silencieux sur `src/`.
Rangé dans `src/mountain_perf/{config,units}.py`, `tests/`, `justfile`,
`.github/workflows/ci.yml`, branche `m0/fondations`.
