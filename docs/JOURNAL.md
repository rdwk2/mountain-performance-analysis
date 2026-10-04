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

### 2026-10-04 · M4b-4 — Backtest : registre des expériences
Registre D14 en bibliothèque (aucune commande) : contrats de la déclaration complète
(dont la partie « expérience » que M4c remplira, son scénario et sa date d'analyse), du
résultat, de l'échec, du journal et du comptage des essais (`schemas/registry.py`) ;
écriture canonique des contrats en JSON d'après leurs annotations, stricte (écrit, donc
relu : types voisins et textes non UTF-8 refusés à l'écriture comme à la relecture), et
documents `{type, format, data}` (`backtest/codec.py`) ; registre sur disque — journal
`evenements.jsonl` chaîné par empreintes, documents nommés par leur `sha256`, verrou,
relecture et vérification, ajout qui contrôle tout avant d'écrire, lecture des documents,
comptage des essais, `declared_performance`, `curve_artifacts` (`backtest/registry.py`).
Précisions de `0010` D14 et D2.6 ajoutées, mot pour mot. Valeurs du § 7 reproduites du
premier coup : `SAMPLE` au bit, première ligne du journal (5 474 octets, `5c6dedde…`),
huit documents, `TrialCounts`, empreinte de forme des 44 contrats stockés (`4e2f2b55…`).
113 contre-épreuves jouées une à une (110 du § 8.2, trois de `Declaration.artifacts`),
contrats actifs puis, hors règles de contrat, neutralisés : toutes rouges ; deux écarts au
tableau du brief signalés dans la PR (« ligne écrite avant les documents » placée après le
contrôle des documents présents ne rougit que le test 7 — la variante placée au début de
l'étape 7 rougit les tests 7 et 9 ; « avant-dernière empreinte », contrats neutralisés,
rougit les tests 7 et 11, le test 10 échouant déjà sous la seule neutralisation).
Conclusion : `just check` vert (3 524 tests, contre 3 163). Environ 7 800 lignes, dont
1 024 de dictionnaire régénéré, 3 000 de code et 3 750 de tests. Rangé dans
`src/mountain_perf/schemas/registry.py`, `src/mountain_perf/backtest/codec.py`,
`src/mountain_perf/backtest/registry.py`, `tests/fixtures/registry.py`,
`tests/test_schemas_registry.py`, `tests/test_backtest_codec*.py`,
`tests/test_backtest_registry*.py`, `0010` D14 et D2.6 ; branche `m4b/registre`.
Correctifs de la relecture (deux relectures C et le balayage de mutation de la conception),
sans changement de `src/` : trente-deux règles écrites reçoivent un test — la première de
deux traces nommée par le contrôle, les jours à deux sorties (sort de chaque sortie, jour
d'une référence D8 sur deux parcours, origine avant la première sortie), la forme
canonique jugée sur la réécriture de l'objet relu, les noms prescrits sur disque et les
modèles qui recopient la courbe, les messages sans chemin absolu, neuf ordres de contrôle,
l'écriture d'un document par un temporaire, le document altéré laissé tel quel, les
corrections de déclarations seules, deux effets de même nom, l'ordre des références D8,
l'instant d'un échec, le poids nul, un résultat aux documents neufs, les liens relus, les
données non textes relues, un entier hors du domaine des flottants, et les points soumis 6
à 8 du plan (réponse hors bornes, verrou effacé à la main, messages de `load_outcomes`) ;
3 556 tests. Deux lignes de backlog.

### 2026-10-02 · M4b-3 — Backtest : référence prédictive de répétabilité
Référence D8 d'un parcours sous les onze horloges, en bibliothèque (aucune commande) :
contrats (`TwoWayFit`, `RepeatabilityDay`, `ClassFit`, `ClassScore`, `FoldScores`,
`ClockReference`, `RepeatabilityReference`), `two_way_fit` (moyennes alternées
certifiées par D8.3, Python pur), `contraction_rate` (`μ₂` par Jacobi),
`repeatability_reference` (plis, quatre classes, cellules nulles, `|L|` strict, temps
nul du jour retiré propagé sur `S_j`, `F` par moyenne des plis). Précisions de D8.1 à
D8.4 ajoutées à `0010`, mot pour mot. Test des exemples du README contre les sorties
réelles de `mperf` (quatre exemples, verts sur le README de `main`). Seize cas
synthétiques : les 555 valeurs de l'oracle reproduites (écart maximal 4,3e−8, plan
Lent), itérations exactes. 55 contre-épreuves jouées une à une, contrats actifs puis
neutralisés : toutes rouges ; deux écarts signalés dans la PR (« limite exclue » ne
rougit pas le test 5 ; « prévision non finie gardée » rougit par la `ContractError` de
`MetricValue`, pas par une valeur).
Conclusion : `just check` vert (3 125 tests, contre 2 800). Environ 6 000 lignes, dont
1 334 de valeurs d'oracle recopiées par script. Rangé dans
`src/mountain_perf/schemas/repeatability.py`, `src/mountain_perf/backtest/repeatability.py`,
`tests/fixtures/repeatability*.py`, `tests/test_*repeatability*.py`,
`tests/test_readme_examples.py`, `0010` D8 ; branche `m4b/repetabilite`.
Correctifs de la relecture (deux relectures C et le balayage de mutation de la conception) :
le contrat de `ClassFit` vérifie que `residuals` est un tuple (§ 6.1) ; quinze règles
écrites reçoivent un test (bords ancrés de fin, critères après le centrage, constantes,
résidus publiés, ordre des préconditions, horloges distinctes, jours multi-sorties triés,
référence publiée, mixte contributif, composantes entremêlées, bord ancré de départ,
prévisions sous une seconde, limite de Jacobi, une itération, indépendance du jour retiré).

### 2026-10-02 · docs — Figure de la chaîne dans le README
Mission documentaire hors jalons. `scripts/readme_figure.py` écrit un tracé GPX
inventé (montée 3,5 km vers « Col », descente 3,2 km vers « Refuge », plat jusqu'à
8 km, pentes ≤ 15 %) et une trace synthétique (vitesse de la courbe ×1.10 au-dessus
de +5 %, ×0.85 sous −5 %, sans arrêt) dans un dossier temporaire, puis exécute la
chaîne de `main` comme `mperf match --curve` ; `render_svg`, pure, dessine le
résultat. Valeurs (usage, horloge écoulé) : v0 1:10:30, réalisé 1:10:38, écart
−8 s (−0.2 %) ; `L` −0.002, `A` 0.108, `B` 0.108, `E_R` montée +0.094, descente
−0.159 ; `C_comp` ≈ 0.004 (régimes homogènes), remplacé dans l'encadré par `A` et
`B`. Contre-épreuves : facteur 1.10 → 1.12 sans régénérer, image retirée du README,
chemin absolu dans le SVG — chacune rougit son test.
Conclusion : `just check` vert (2 800 tests). Script de 708 lignes, presque tout du
dessin. Rangé dans `scripts/readme_figure.py`, `docs/img/chaine.svg`, `justfile`
(`just figure`), `tests/test_readme_figure.py`, `README.md`, branche `docs/figure`.

### 2026-10-01 · docs — README à jour
Mission documentaire hors jalons, plan approuvé avec sept précisions. Le README
décrit l'état réel : ce qu'est le projet, « Pourquoi » court (livré : v0 sans
dégradation ; prévu : dégradation et profondeur de descente, M6a), installation
(`uv sync --locked`, `just check`), `mperf profile`, `project` et `match` avec
leurs options et défauts, un exemple exécuté depuis la racine sur les fixtures
synthétiques (`match --curve` en extrait marqué), liens vers ROADMAP, JOURNAL,
BACKLOG et les dix décisions. Sorties du README rejouées et comparées, liens,
options et défauts vérifiés contre `cli.py` et les `ParameterSpec`, aucune fuite.
Trois écarts relevés hors périmètre, non corrigés : `CLAUDE.md` omet
`mperf project` et cite `just backtest`, absent du `justfile` ; la commande de fin
du M3 dans `ROADMAP.md` n'a pas `--curve`.
Conclusion : `just check` vert, 2 796 tests. Rangé dans `README.md`, branche
`docs/readme`.

### 2026-10-01 · M4b-2 — Backtest : scores de v0 brut sur une sortie
Brief M4b-2 rév. 2, sept précisions de la relecture du plan (P1 à P7). Adaptateur du
moteur M3 : `ProjectedTimeline` (cumul par `accumulate`, `time_at` au corps de
`_time_at`, précondition `[0 ; L]`), `project` réécrit dessus au bit (contre une copie
figée des formules de M3). Contrats à trois étages (`schemas/scoring.py`) :
observation d'une sortie sous les onze horloges, prévision d'un modèle dans un
scénario, scores par scénario et horloge. `observe_outing`, `usage_forecast`,
`control_forecast`, `score_scenario` (fonctions de M4b-1, diagnostic de D5.5,
enveloppes sur les dix sommes), `score_outing`, `report_clocks`, `v0_scores` ;
`mperf match --curve` et `--no-reference` (sections 11 à 13).
Conclusion : `just check` vert, 2 777 tests (2 365 avant). Valeurs du § 7.3
reproduites à `1e−9` relatif sur les treize cas, sans écart ; textes du § 7.5 au
caractère près ; sans `--curve`, sortie de `main` octet pour octet. Contre-épreuves :
les 38 mutations du § 8.2, les 4 de la précision 2 et 9 rejeux contrat neutralisé,
toutes rouges sur le test désigné (l'échange de `a` et `b` arrêté par la précondition
de M4b-1 sur onze cas, par une valeur sur Arrivée hors préfixe). La campagne a trouvé
un test 6 trop faible (écart d'arrivée comparé à lui-même), corrigé. Écart au brief :
le test de réemploi de M4b-1 interdisait l'import de `backtest/metrics.py` que le § 6
prescrit ; élargi à `backtest/scoring.py`, avec l'accord de rdw, dans un commit à part.
Rangé dans `src/mountain_perf/model/engine.py`, `src/mountain_perf/schemas/scoring.py`,
`src/mountain_perf/backtest/scoring.py`, `src/mountain_perf/cli.py`,
`tests/test_model_timeline.py`, `tests/test_schemas_scoring.py`,
`tests/test_backtest_scoring_*.py`, `tests/test_cli_match_scores.py`,
`tests/fixtures/scoring.py`, `tests/fixtures/scoring_values.py`,
`tests/fixtures/scores_*.txt`, `BACKLOG.md` (six lignes), branche `m4b/scores-v0`.
Après la double relecture de la PR #15 et le balayage mécanique des modules touchés,
sept correctifs de tests (R1 à R7, `CORRECTIFS_PR-15.md`) tiennent des règles écrites
qu'aucun test ne tenait (portée de l'erreur du modèle sur toutes les classes,
`ProjectedTimeline` gelée, ordre à abscisse égale, deux limites de contrat, mise en
forme du § 6.7, noms importés) ; aucun changement de `src/`, `just check` vert,
2 796 tests.

### 2026-09-28 · M4b-1 — Backtest : métriques D7, définitions
Les métriques de `0010` D7 en fonctions pures sur des vecteurs et des statuts (brief
M4b-1 rév. 2, cinq précisions de la relecture du plan). Contrats `MetricValue`,
`ClassMetrics`, `SupportMetrics`, `PositiveTimeDiagnostic`, `LogRatioEnvelope`,
`PassageErrors`, `TargetMember`, `UsageTarget`. Fonctions `support_metrics` et
`positive_time_diagnostic` (un seul code, motifs « l'observation avant le modèle »),
`log_ratio_envelope`, `passage_errors`, `default_targets` (une seule arrivée, en
dernier) et `usage_target`. Écritures imposées : `log_ratio`, `math.fsum`,
`time_weighted_deviation`, `compensation`. Toutes les valeurs du § 7 sont reproduites,
les égalités `==` au bit. Cinq précisions ajoutées à `0010` (D5.5, D7.1 à D7.4), sur
des lignes neuves.
Conclusion : `just check` vert, 2 353 tests. Contre-épreuves : 70 mutations sur 71
rougissent sur le test que le brief désigne ; `sum` au lieu de `math.fsum` est
équivalente (§ 7.8). `C_comp = W + B − A` n'est vue que par le réemploi au bit.
Rangé dans `src/mountain_perf/schemas/metrics.py`,
`src/mountain_perf/backtest/metrics.py`, `tests/test_schemas_metrics.py`,
`tests/test_backtest_metrics_*.py`, `tests/fixtures/metrics.py`, `tests/strategies.py`,
`docs/decisions/0010-protocole-de-backtest.md` et `BACKLOG.md` (une ligne cochée, deux
ajoutées), branche `m4b/metriques-definitions`.
Après la double relecture de la PR #14 et le balayage mécanique des deux
`metrics.py`, neuf correctifs de tests (R1 à R9, `CORRECTIFS_PR-14.md`) tiennent des
règles qu'aucun test de valeur ne tenait (sélection du diagnostic, `E_R − L` et `L`
au bit, premier motif, arrivée en dernier, imports relatifs, valeurs limites), sans
changer `src/` : 2 365 tests.

### 2026-09-28 · M4b-0 — Hygiène : test instable, sortie console
PR d'hygiène avant les métriques M4b (brief M4b-0 rév. 1). Test instable
`test_pace_varies_at_the_local_slope_on_each_side` : le défaut était le pas de
référence, pas la tolérance — `edge ± ε` est arrondi et la pente locale
(K ≈ 16 000 s/m) multiplie cet arrondi au-delà de la marge absolue de `1e-12` ; le
pas est désormais mesuré sur l'abscisse évaluée (`abs(at − edge)`), marges
inchangées, et les deux contre-exemples connus (PR #11, PR #12) sont des `@example`.
`mperf` : `stdout` et `stderr` reconfigurés en UTF-8 en tête de `main`, avant la
lecture des arguments, en gardant le gestionnaire d'erreurs de chaque flux ; seuls
les `io.TextIOWrapper` sont touchés ; quatre tests de sortie sous un flux cp1252.
Les onze contre-épreuves du § 5 rougissent là où le brief l'annonce ; témoin
Windows (`cmd /c` redirigé, `PYTHONIOENCODING` retiré) : `main` rend 1 avec
`UnicodeEncodeError`, la branche rend 0 avec `→` et `D−` lisibles.
Conclusion : `just check` vert, 2 033 tests. Rangé dans `tests/test_model_pace.py`,
`src/mountain_perf/cli.py`, `tests/test_cli_profile.py`, `BACKLOG.md` (trois lignes
barrées), branche `m4b/hygiene`.

### 2026-09-27 · M4a-3 — Backtest : passages et événements
Cinquième et dernière PR du lot M4a (brief M4a-3 rév. 1, `0010` D4.12 ; `0010`
inchangé). Six types de plus au dictionnaire (`PassageRole`, `PassageStatus`,
`EpisodeOutcome`, `PassageObservation`, `EpisodeAttribution`, `PassageMatchResult`)
et la table unique `PASSAGE_STATUS_UNAVAILABILITY` ; mot-clé `end_position` de
`crossing_candidates` (borne haute stricte, arrêt anticipé, `None` inchangé) ;
`backtest/passages.py` : huit prédicats, rattachement à la grille nominale,
recherche d'une occurrence encadrée, reprise d'un point de score (fenêtre jusqu'au
premier point daté après `k`), association arrêt → passage sous `θ_c` (médiane
lissée, 1 s puis 1 m), événements, chronologie (départ et arrivée hors chronologie),
maintien dans le préfixe, `observe_passages` ; `mperf match`, section 10. Précisions
de la relecture du plan intégrées (P1 à P5 : invariants du départ et de
`passage_index`, ligne cp1252 de la section Backtest, table testée valeur par
valeur, réemploi vérifié par l'arbre syntaxique, `time_distance_s` au commit 3).
Les 26 lignes du § 7.3.1 et la section 10 des sept paires reproduites dès le premier
essai, sans tolérance élargie. 61 contre-épreuves par mutation (chaque ligne du § 8,
chaque variante), une à la fois, cache de bytecode vidé, toutes rougies, arbre
restauré et vérifié par empreinte ; deux notes : la médiane brute ne s'écrit qu'au
point d'appel (`episode_median` n'a pas la trace), où seul le test de réemploi la
rougit ; `outside_prefix → absent` est d'abord arrêtée à la collecte des tests de
contrat, puis rougit dans le corps de Passages. `mperf match` 1,03 s sur Final hors
préfixe (1 944 enregistrements), démarrage compris ; `observe_passages` 0,3 ms.
Conclusion : `just check` vert avant chacun des six commits, 2 015 tests (+308).
Contrôle des dix-neuf paires réelles à faire par rdw avant la fusion (§ 11). Trois
lignes au backlog (§ 9), et le déclencheur de la ligne cp1252 réécrit.
Correctifs de la PR après la double relecture et le balayage mécanique (R1 à R10,
tests seulement, `src/` inchangé) : motifs et pluriel de la section 10, chronologie à
trois enveloppes, Chronologie miroir, `ε` et `r_c` hors défauts, lieu d'arrivée hors
chronologie, réemploi fermé, longueur au bit près, occurrence et épisode publiés
entiers, arrivée négative refusée ; une contre-épreuve par correctif, cache de
bytecode vidé, toutes rougies dans le corps du test visé ; 2 029 tests (+14).
Rangé dans `src/mountain_perf/schemas/matching.py`, `backtest/passages.py`,
`backtest/matching.py`, `cli.py`, `tests/`, branche `m4a/passages`.

### 2026-09-27 · M4a-2c — Horloges : égalités de seuil ; tests des segments
Quatrième des cinq PR du lot M4a (brief M4a-2c rév. 2, `0010` D5.2 : une précision,
rien d'autre). Partie A : `qualify` compare aux seuils d'horloge en réels — une mesure
est égale à son seuil si `|x − s| ≤ τ·s` et le dépasse si `x − s > τ·s`,
`τ = CLOCK_THRESHOLD_RELATIVE_TOLERANCE = 1e−6` —, par un seul prédicat privé que
reprend l'économie de `window_measures` ; `confirm` inchangé. Tableau de `qualify`
réécrit (neuf lignes à `τ/2` et `2τ` des seuils dyadiques), `τ` épinglé, trois
fixtures qui atteignent les seuils exactement à travers le lissage et
l'interpolation (marche de 1,0 m sur 1 234,4 m, marche de 1,5 m, pas de 0,15 m/s) :
quinze totaux exacts reproduits dès le premier essai, intervalles 136 et 162
immobiles sous `θ_c`. Partie B : cinq tests des segments (G1 à G5), lacunes d'un
essai de mutation mécanique de `segments.py`, qui ne change pas.
Effet sur les traces réelles, chiffré en conception et **confirmé** par le contrôle
réel de rdw (12 paires conformes) : Queyras, `M` 64 720 → 64 684 s sous `θ2`, `θ4`,
`θ5` ; `Q_1_2` et `Q_1_4`, 1 s de `M` passe en `U` ; aucun changement ailleurs.
11 contre-épreuves par mutation, une à la fois, toutes rougies, arbre restauré et
vérifié par empreinte ; l'économie restée stricte est arrêtée par `ValueError` (marche
de 1,5 m, pas de 0,15 m/s). Correctifs de la PR après deux relectures et le
balayage mécanique de `clocks.py` (R1 à R6, tests seulement, `src/` inchangé) : G5
sur trois paramètres, G4 sur les deux coordonnées, G2 sous 0,5 m, `confirm` sans
tolérance près de `c`, frontière `τ·s` incluse, six lacunes des fonctions internes
de `clocks.py` (K1 à K6) ; une contre-épreuve par correctif, cache de bytecode vidé,
toutes rougies dans le corps du test visé. 1 707 tests (+23). Trois lignes au backlog
(§ 9 du brief, et `qualify` face à une mesure non finie).

### 2026-09-25 · M4a-2b — Backtest : appariement, segments et couverture
Troisième des quatre PR du lot M4a (brief M4a-2b rév. 2, `0010` D3, D4.2, D4.3,
D4.9 à D4.11, D5.4, D6, D13 ; `0010` inchangé). Huit types de plus au dictionnaire
(`SegmentExclusion`, `Regime`, `RegimeClass`, `ScoreSegmentObservation`, `Coverage`,
`AdmittedTotals`, `SensitivityConfiguration`, `MatchResult`) ; `gap_between` extraite
de `_same_event` sans changement de comportement ; `backtest/segments.py` : quatre
prédicats de seuil, `fine_overlaps` (public, pour le diagnostic roulante / raide de
M4b), régimes et classes, chemin réalisé, `rho`, `H_1`, `H_2`, `observe_segment`,
couverture, préfixe comparable, dernier passage, totaux du support admis, `θ_bas`,
`θ_haut`, `I_sens,A` et `match_trace` ; `backtest/sensitivity.py` (19 configurations
déclarées) ; `mperf match`, sections 5 à 9. Précisions de la relecture du plan
intégrées (tolérances de la propriété 1 et ses jumeaux sans écart latéral,
« non daté » au préfixe, ligne `rho` au backlog).
Les 33 lignes du § 7.2b reproduites à `1e−6` dès le premier essai, sans tolérance
élargie (segments, couverture, préfixe, horloges des huit lignes qui les donnent).
26 contre-épreuves par mutation (au moins une par règle des §§ 5b.4 à 5b.7, trois de
jonction sur le code de M4a-2a, une sur les épisodes de `mperf match`), toutes
rougies, arbre restauré et vérifié par empreinte ; huit sont arrêtées par un contrat
(`ContractError`) avant la comparaison de valeurs. `match_trace` : 32 ms sur Fenêtre
(1 141 enregistrements), 0,62 s sur 5 570 (surtout `H_1`, une projection restreinte
par enregistrement intérieur) ; `mperf match` 1,0 s sur Fenêtre, démarrage compris
(0,9 s). Deux lignes au backlog (§ 9, et `rho` refusé par le lint).
Conclusion : `just check` vert avant chacun des huit commits, 1 679 tests à la fin.
Contrôle sur les douze paires réelles à faire par rdw avant la fusion (§ 11).
Rangé dans `src/mountain_perf/schemas/matching.py`, `backtest/segments.py`,
`backtest/sensitivity.py`, `cli.py`, `tests/`, branche `m4a/appariement-segments`.

### 2026-09-24 · M4a-2a — Backtest : appariement, points de score
Deuxième des quatre PR du lot M4a (brief M4a-2a rév. 2, `0010` D4.1 à D4.9 ; note
datée du découpage ajoutée à la fin de D16). Contrats `PointStatus` et
`ScorePointObservation` (deux types de plus au dictionnaire) ; géométrie de référence
(polyligne dédoublonnée de `0008`, position exacte aux sommets, plan local ancré,
repère, tangente indéfinie, projection restreinte et égalité de l'ancrage) ;
paramètres `Δ`, `ε`, `r_c`, grille de score et onze prédicats de seuil nommés ;
positions fractionnaires, franchissements, regroupement en événements, extrémités et
`match_points` ; `mperf match` (sections 1 à 4) avec une paire de GPX commitée.
Écart décidé à la relecture du plan : `anchor_projection` et `ANCHOR_TIE_M` vivent
dans `backtest/geometry.py`, pour éviter un import circulaire.
Les 33 lignes du § 7.2a reproduites à `1e−6` dès le premier essai, sans tolérance
élargie ; trois fixtures de session (S01 à S03) pour les règles qu'aucune ligne ne
distinguait. 35 contre-épreuves par mutation (une au moins par règle des §§ 5a.6 et
5a.7), toutes rougies, arbre restauré et vérifié par empreinte ; trois mutations
équivalentes (début du balayage, arrêt de la fenêtre, `j > π_cur` à l'arrivée),
consignées. `match_points` : 7,5 ms sur Fenêtre (1 141 enregistrements), 29 ms sur
5 570 ; `mperf match` 0,9 s, démarrage compris. Deux lignes du § 9 au backlog, plus
deux constats (sortie cp1252 de `mperf` redirigée, `ℓ` refusé par le lint).
Conclusion : `just check` vert avant chacun des six commits, 1 193 tests à la fin.
Contrôle sur les douze paires réelles à faire par rdw avant la fusion (§ 11).
Rangé dans `src/mountain_perf/{schemas,backtest}/matching.py`,
`backtest/geometry.py`, `cli.py`, `tests/`, branche `m4a/appariement-points`.

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
Correctifs de relecture : tests P1 à P10, message d'erreur du manifeste (P11) ;
959 tests.
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
