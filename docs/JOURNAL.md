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
