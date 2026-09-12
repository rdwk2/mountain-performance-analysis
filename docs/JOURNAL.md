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
