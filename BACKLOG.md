# BACKLOG

> Une ligne par idée. On n'implémente rien depuis ce fichier : on y pioche au
> moment de planifier le jalon suivant, et l'idée retenue devient une issue.
> Ajouter en bas. Barrer et dater quand c'est fait.

Format : `- [ ] (jalon visé) idée — pourquoi`

---

## Modèle

*(repris du `NOTES_MODELE.md` de l'ancien projet — c'était déjà une bonne liste)*

- [ ] (M6a) Calibrer les paramètres de fatigue sur des passages réels au lieu de les deviner à la main
- [ ] (M8) Deux courbes de descente : roulant / faux-plat vs raide — la faiblesse est spécifiquement sur le roulant (−37 % vs −23 %)
- [ ] (M7) Chaleur basée sur la température réelle de l'activité au lieu du forfait horaire
- [ ] (M7) Acclimatation à la chaleur comme modulateur (métrique Garmin disponible)
- [ ] (M6a) Fatigue cumulée en D+ encaissé (quads), en plus de la fraction de course
- [ ] (M7) Dette de sommeil réelle (Body Battery / heures de sommeil) au lieu du forfait nuit
- [ ] (M6b) Recalibrer la courbe après chaque bloc d'entraînement, et par saison
- [ ] (M4) Valider la prédiction contre une course réelle le jour J → boucle de correction
- [ ] (M6a) Effet d'altitude affiné par tranche d'altitude réelle plutôt qu'un seuil unique
- [ ] (M8) Fourchettes P50/P80 dérivées des données au lieu de trois jeux de paramètres à la main
- [ ] (M8) Vérifier la calibration de l'intervalle : ~80 % des temps réels dans le P80, sinon l'intervalle ment
- [ ] Effet de la technicité du terrain (non capturé par la pente seule) — commencer par regarder si le résidu du backtest corrèle avec quelque chose de mesurable
- [ ] Sensibilité du modèle : quel paramètre bouge le plus le temps final ? Utile pour savoir où investir
- [ ] (M6a) Remplacer le facteur d'arrêts global par un temps d'arrêt par point de passage — le contrat arrivée/départ rend le multiplicateur global inapplicable tel quel
- [ ] (M6a) Distinguer la fatigue subie de la gestion choisie — effort est aujourd'hui constant sur toute la course, ce qui suppose une stratégie plate
- [ ] (M8) Tester « descente courue vs marchée » comme variable explicative du résidu — distinct de « roulant vs raide », les deux se croisent
- [ ] (M4) Attention à l'autocorrélation des erreurs sur temps cumulés au moment de choisir la métrique : une erreur précoce est comptée dans tous les cumuls suivants
- [ ] (M3) Définir l'extrapolation de la courbe hors de sa plage de pentes observées
- [ ] (M6b/M7) Grit et Flow (dynamique VTT Garmin) comme covariables explicatives du résidu — mesurables a posteriori, non projetables sur un tracé neuf
- [ ] (M7) Projection franchissant un changement d'heure : utc_offset_s est figé au départ, les effets d'heure dérivent d'une heure après la bascule — décider si ça compte quand le consommateur existera
- [ ] (M7) Projection.start_time : quel instant désigne-t-il quand passages[0].arrival_s ≠ 0 — t = 0 ou passages[0].departure_s ? Indifférent en M3, à trancher avant les effets d'heure
- [x] ~~(prochain passage sur model/pace, ou dès qu'il fait rougir une CI) Test de propriété instable : test_pace_varies_at_the_local_slope_on_each_side (tests/test_model_pace.py) — sa borne relative 1e−9 est trop serrée pour une pente extrême. Contre-exemple d'Hypothesis : grade = (−1.453125, −1.4375, 1.0), speed_ms = (1.0, 0.00390625, 1.0), epsilon = 1e−9 ; écart 1,6320001350e−5 pour une borne 1,6320001016e−5. Probablement l'échec intermittent de CI vu à la PR #8.~~ — fait le 2026-09-28 : PR M4b-0 (second contre-exemple : PR #12 ; le pas est mesuré sur l'abscisse évaluée)

## Données et ingestion

- [ ] (M6b) Reprise après coupure et gestion du 429 Garmin (déjà résolu dans l'ancien script, à ne pas réinventer)
- [ ] Détecter et signaler les activités aberrantes (GPS perdu, pause oubliée, tapis)
- [ ] Températures : croiser météo de l'activité et capteur de la montre, voir lequel prédit le mieux
- [ ] Import de traces autres que Garmin (GPX/FIT génériques) pour ne pas être enfermé
- [ ] (M6b) Vérifier empiriquement si le `sumDistance` de Garmin est une distance 2D ou 3D : recalculer la distance depuis le flux de positions et comparer. Toute la convention de pente en dépend (cf. docs/decisions/0002-unites.md) — un écart passerait inaperçu et biaiserait le modèle d'autant plus que la pente est forte.
- [ ] (M4) Séparer physiquement $MPA_DATA_DIR/reference/ (soi, évaluable) et population/ (446 coureurs, non évaluable)
- [ ] Contrat pour les données de population, le jour où leur usage sera défini
- [ ] (M6b) FC : un flux Garmin porte des 0 sur les premiers points et des métadonnées où average_hr > max_hr — les invariants durs de M1b imposent de réparer ou d'écarter avant construction, et une valeur de QualityFlag sera à ajouter alors

## Outil et interface

- [ ] (M9) Comparer deux scénarios côte à côte sur le même tracé
- [ ] (M9) Export d'une table de marche imprimable (l'ancien projet produisait une fiche PDF utile en course)
- [ ] Points de ravitaillement / waypoints du GPX affichés dans le tableau de passages
- [ ] Plan hydrique et nutrition dérivé du temps par segment et de la température
- [ ] (M3/M5) Choisir le format d'affichage selon le régime : VAM en montée soutenue, min/km sur le plat et le roulant — le seuil de pente est un paramètre du modèle, pas une constante du formateur
- [ ] (M3) `format_duration(duration_s)` → `"1:23:45"` pour les tableaux de temps de passage
- [ ] (M5) Remplir PointKind, à la main ou semi-automatiquement — aucune inférence en M1
- [ ] (M2) Projeter un tracé à l'envers — ce n'est pas renverser la liste, D+ et D− s'échangent

## Long terme — hors périmètre actuel

- [ ] VTT : le modèle allure↔pente ne se transpose pas tel quel, il faut repartir des données
- [ ] Ski de randonnée : idem, plus la neige comme variable
- [ ] Corrélations données santé (HRV, sommeil, stress) × charge d'entraînement
- [ ] Déploiement en ligne : question ouverte de l'import et de la conservation des données d'autres utilisateurs
- [ ] Planification d'entraînement à partir du modèle
- [ ] (long terme) BERA : la section « qualité de la neige » est exploitable par extraction de texte ; le risque d'avalanche n'est pas la skiabilité

## Outillage et dépôt

- [ ] Commiter un `.vscode/settings.json` minimal (`"files.eol": "\n"`) et ajuster le `.gitignore`, qui exclut aujourd'hui tout `.vscode/` — évite de recréer des fichiers CRLF à la main
- [x] ~~Activer la protection de la branche `main` : exiger une pull request, puis ajouter l'exigence de CI verte une fois que le workflow a tourné au moins une fois~~ — fait le 2026-09-12 : PR obligatoire, CI verte obligatoire, historique linéaire, zéro approbation requise
- [ ] Garde CI qui échoue si un fichier de données (`.gpx`, `.fit`, `.json` d'activité, `.csv`) apparaît hors de `tests/fixtures/` — la règle 1 vérifiée mécaniquement, pas par vigilance
- [ ] (M2/M6b) Aides `raw_dir()`, `interim_dir()`, `processed_dir()`, `routes_dir()`, `reference_dir()` dérivées de `config.data_dir()` quand un premier lecteur en aura besoin
- [ ] (M9) README — une section « Méthode » assumant l'usage de Claude Code : ce qui relève de mes décisions (architecture, modèle, métrique, protocole de validation), ce qui relève de l'implémentation assistée, et le fait que chaque PR est relue avant fusion. Renvoyer vers `docs/decisions/`
- [ ] (M9, optionnel) Signature SSH des commits pour les badges « Verified » — nécessitera de configurer la signature côté Claude Code aussi
- [ ] (M4/M6b) Hook `PreToolUse` refusant toute écriture dans le dossier de données, à poser au moment où `--add-dir` donnera accès à `mpa-data` (non versionné, donc sans filet git)
- [ ] (M6a) Envisager un worktree git quand M6a et M6b tourneront en parallèle
- [ ] (M6a) Écrire une skill pour la boucle « ajouter un effet → backtest → comparer → entrée de JOURNAL », après l'avoir faite deux fois à la main
- [ ] Tester le chemin `cached_property` de `_render_dataclass` — la branche existe depuis M1a mais n'est exercée par rien tant qu'aucune propriété n'est mémoïsée

- [ ] (M6b) Aligner la définition de `sample_count` : la lecture M3 y met des secondes de données, faute de comptage de points dans le CSV de courbe.
- [ ] (M6b) Réestimer la courbe avec **le même opérateur de pente** que le moteur — largeur `W` identique — pour supprimer le biais d'échelle de D6 (`docs/decisions/0009`).
- [ ] (M4) Le seuil de support de 10 min est un choix par défaut d'aujourd'hui : le bon critère serait le nombre d'activités contributrices et leur dispersion, absents du fichier de courbe.
- [ ] (M4) Vérifier que les temps de référence sont comparables aux **temps en mouvement** de la courbe : un arrêt compté dans un passage réel se lirait comme une baisse d'effort.
- [x] ~~Sortie console : `mperf` écrit `→` et `−`, absents de cp1252 ; depuis un terminal Windows non UTF-8 la commande lève `UnicodeEncodeError` après quelques lignes. Repéré au M3, présent depuis le M2.~~ — fait le 2026-09-28 : PR M4b-0
- [ ] `ParameterSpec.default` de `grid_step_m` vaut l'entier `50`, donc `grid_m[0]` est un `int 0` et le CSV écrit `0` au lieu de `0.0` — cosmétique, mais un mélange int/float dans un calcul est un piège en attente.

- [ ] (M5) Plage d'affichage des `ParameterSpec`, distincte des bornes de garde-fou — les bornes actuelles sont larges à dessein et feraient un curseur inutilisable.
- [ ] (M6b) Écrêtage des pics d'altitude et `QualityFlag` correspondant, au moment où les détecteurs existeront.
- [ ] (M6b) Mesurer le biais sphère / ellipsoïde selon l'azimut lors de la confrontation au `sumDistance` Garmin — il ne se simplifie dans `durée = distance / vitesse` que si les orientations des activités et du tracé se ressemblent.
- [ ] (M2/M3) Caler les défauts de `smoothing_window_m` et `grid_step_m` sur des fichiers réels — les valeurs livrées sont provisoires.
- [ ] (hors périmètre M2) Définir le traitement des tracés traversant l'antiméridien avant de généraliser la projection locale — la différence brute de longitude ne représente pas le raccord ±180°.

## Backtest (0010)

- [ ] (après M6b, ≥ 20 jours hors échantillon) Modèle d'erreur hiérarchique et score prédictif — seuil de réexamen, pas une garantie.
- [ ] (≥ 10 performances postérieures au figement) Test de confirmation d'un gain utile : blocs indépendants définis avant analyse, `S = Σ_b 1{G_b > δ*}`, égalités non-succès, `p = Σ_{s=S}^{B} binom(B, s) 2^{−B}` ; `δ*`, date d'analyse et gestion de plusieurs candidats fixés d'avance.
- [ ] (avant la première expérience déclarée, M6a) Réexaminer les seuils d'admission (critère « comparable », référence empruntée) ; après la première déclaration, toute modification est une nouvelle version.
- [ ] (M6b) Origine glissante 28 j, demi-vie 7 j, `n_eff` publié.
- [ ] (M6b) Définition commune du mouvement et même opérateur de pente à l'estimation et à l'application.
- [ ] (M6a) Valider le détecteur d'arrêts sur des épisodes arrêt / marche connus avant toute revendication de temps de mouvement calibré.
- [ ] (M6a+) Effort de course et affûtage : calibrables sur des courses seulement.
- [ ] (après M6b) Progression sur 28 j par régime, à comparer à l'origine glissante.
- [ ] (M6b+) Courbe par période et test des sorties de plat dans leur domaine ; lissage à noyau pondéré ; banc du traitement GPX (MNT ou concordance des répétitions).
- [ ] (M8) Fourchettes par régime ; loi complète et CRPS ; référence propre `F_usage`.
- [ ] (M4+) Lecture de `e^L` comme correction d'effort a posteriori : rétrospective, limitée au support comparé, invalide en présence d'arrêts additifs.
- [ ] (premier cas réel) Jours à plusieurs sorties : revoir la règle des 4 h et définir l'agrégation d'une performance multi-sorties (référence, étiquettes, durée, `K`, cellules répétées).
- [ ] (prochaine course avec relevés de ravitaillement) Confronter l'association arrêt → passage (médiane, départage à 1 s puis 1 m) aux relevés réels.
- [ ] (avant la première confirmation) Rôles des artefacts : revoir la séparation entrées de prévision / observations d'évaluation.
- [ ] (première cellule nulle réelle) Cellule de temps nul dans le gabarit de répétabilité.
- [ ] (premier préparé avec waypoint terminal) Arrivée unique dans `K`.
- [ ] (M4d) Dégénérescences de la dérive : `t_h <= 0`, variance nulle de `u`.
- [ ] (avant la première expérience ciblant q_usage ou un passage, M6a) Préfixe comparable court : un point non daté ou un segment non admis l'arrête ; mesuré en conception, `q_usage` complet n'existe que sur une minorité de sorties et le diagnostic de longue course de la seule course est vide.
- [ ] (avant la première expérience de l'effet arrêts, ou la première course évaluée) Longs arrêts de course hors support : `ρ` et `H` excluent les segments de ravitaillement (bruit GPS à l'arrêt, ravitaillement à l'écart du tracé).
- [ ] (M6a ou premier refactoring) Trois plans locaux de `0008` coexistent : `gpx/geo.py` (projection point-segment), `backtest/clocks.py` (fenêtres d'horloge), `backtest/geometry.py` (`to_local`). Les factoriser sur `to_local`, avec un test d'égalité bit pour bit avant et après.
- [ ] (M4d, avant l'exécution de la sensibilité) Temps de `match_points` sur une longue trace qui quitte le tracé (fenêtre qui s'élargit après chaque point non daté) : mesurer sur la course du Queyras, et n'optimiser que si les 19 configurations de D13 le rendent nécessaire.
- [x] ~~(M4b, avant `just backtest`) Sortie de `mperf` redirigée sous Windows : stdout en cp1252 refuse `→`, `−`, `Δ`, `ε` (`UnicodeEncodeError`, avec traceback) ; constaté en M4a-2a sur `mperf profile` et `mperf match`, invisible en console et sous pytest. Laissée hors de M4a-2b et de M4a-3 par décision de rdw.~~ — fait le 2026-09-28 : PR M4b-0
- [ ] (outillage) `ℓ` est refusé par les règles RUF001-003 : l'ajouter aux `allowed-confusables` de `pyproject.toml` si les docstrings d'appariement doivent écrire `ℓ*` plutôt que « écart latéral ».
- [ ] (tests) `local_deg` : longitude de base en paramètre, pour écrire des fixtures à cheval sur un méridien ou l'équateur (exactitude aux sommets, PR #9).
- [ ] (M4b, rapport) Diagnostic « descente roulante / raide » de `0010` D6, non calculé en M4a-2b : le calculer à partir de `fine_overlaps` (M4a-2b), sans modifier le contrat du segment, et écrire alors la précision de « même règle » pour les descentes pures qui ne sont ni roulantes ni raides à 80 % (13 à 18 % des segments de descente sur les quatre références, mesuré en conception ; roulante et raide ont chacune au moins 5 segments purs par référence).
- [ ] (outillage) `ρ` est refusé par les règles RUF001-003 : l'ajouter aux `allowed-confusables` de `pyproject.toml` si les docstrings de segments doivent écrire `ρ` plutôt que `rho`.
- [x] ~~(M4a-3, ou PR à part avant M4b) Horloges : égalités exactes des seuils de `qualify` (`backtest/clocks.py`). Sur des altitudes enregistrées au pas de 0,2 m, Δz sur 30 s est un multiple de 0,02 m et atteint exactement 30·z = 0,9 m (θ2, θ4, θ5) ; en flottant `0.9/30 > 0.03` et `30*0.03 < 0.9`, si bien qu'une égalité exacte est jugée mobile et que l'arrondi tranche les cas limites. Constaté sur une trace réelle au contrôle de M4a-2b (environ 0,05 % du temps de mouvement sous `θ_c`). Piste : comparaisons à tolérance, fixture à altitudes quantifiées.~~ — fait le 2026-09-27 : PR M4a-2c
- [ ] (M4b) θ_bas et θ_haut sont départagés au bit (convention_extremes). Les égalités en réels vues sur les douze paires (par exemple M + U de θ1, θ2 et θ5 quand S_A = 0) viennent des mêmes intervalles et sont égales au bit ; une égalité en réels entre ensembles d'intervalles différents serait tranchée par l'arrondi. Aucun cas constaté.
- [ ] (M4b, ou prochain passage sur clocks.py) qualify et une mesure non finie : une mesure NaN ne dépasse aucun seuil, donc qualify rend IMMOBILE si les diamètres sont NaN (main rendait INDETERMINATE). Inatteignable par clock_partition (RecordedTrace n'admet que des valeurs finies). Décider si qualify refuse un argument non fini ou le déclare non promis. Relevé à la relecture de la PR #11.
- [ ] (M4b, avant le manifeste réel, si un préparé à lieux nommés sert de référence) Passage absent à un virage serré : sur une épingle, le point de score qui précède le lieu peut être daté par un candidat postérieur au franchissement de la normale du lieu (événement de D4.7 daté par son dernier candidat), et le passage est absent (D4.12, recherche entre les deux points qui encadrent s_w). Constaté en M4a-3 sur une sortie Q1 contre le préparé à waypoints ; un passage de K indisponible rend q_usage indisponible (D7.4). Décider avec rdw s'il faut préciser D4.12.
- [x] ~~(M4b, construction de K) Deux lieux à moins de 1 m de L donnent deux occurrences de rôle arrivée, qui reprennent le même événement : K n'en garde qu'une (D4.12, arrivée unique).~~ — fait le 2026-09-28 : PR M4b-1 (default_targets, un seul élément d'arrivée)
- [ ] (M4b, premier épisode attribué sur une sortie réelle) Vérifier à la main la première attribution réelle arrêt → passage : aucune des dix-neuf paires du contrôle de M4a-3 n'en a (aucun épisode dans un préfixe comparable).
- [ ] (M4b-3 et rapport de M4b-5) Temps nul du dernier segment sous M_θ : sur des traces arrêtées à l'arrivée, le dernier segment admis tombe dans les 15 dernières secondes, où la fenêtre de D5.2 est invalide (état U) ; son temps est nul sous les cinq M_θ, si bien que D5.5 rend les quantités vectorielles indisponibles sous ces horloges (diagnostic du sous-support livré en M4b-1). Mesuré en conception sur les sept traces Q1 (segments de 22 à 29 m, 6 à 12 s). C'est aussi une cellule nulle de D8 (choix M02, « ajustement indisponible, temps nul ») : à relire au brief de M4b-3 ; la borne θ_bas du rapport est une M_θ.
- [ ] (M4b-4 ou M4c) Un K déclaré par une expérience n'est vérifié ni pour « départ exclu » ni pour « arrivée unique » (D7.4, « sous les mêmes règles ») : usage_target ne connaît pas les rôles ; à tenir dans le schéma de déclaration.
- [ ] (outillage) Imports relatifs : le test de réemploi de M4a-3 (test_backtest_passages_reuse.py) lit node.module sans node.level et ne voit pas un import relatif (celui de M4b-1 est corrigé) ; la règle ruff TID252 les interdirait dans src/. Relevé à la relecture de la PR #14.
- [ ] (M4b-5, rapport) Troisième horloge du rapport égale à l'écoulé : sur Q1, Infernet et Pas de l'Homme, aucun arrêt ne tombe sur le support admis, (M+U) θ_haut vaut l'écoulé et la colonne répète la première (mesuré en conception, M4b-2). Le signaler au rapport D15, ou non.
- [ ] (M4c, baselines) ProjectedTimeline refuse une allure non finie ou <= 0 : une baseline qui en produirait lèverait au lieu d'un statut « erreur du modèle » (0010 D7.1). À trancher au brief des baselines.
- [ ] (M4b-5, ou M4d avant la sensibilité) Coût de l'observation d'une sortie : clock_duration_s parcourt les intervalles depuis le début à chaque appel ; 18 s au Queyras sous dix horloges pour 304 segments admis (mesuré en conception, M4b-2), en plus des 57 s de l'appariement. N'optimiser que si just backtest ou la sensibilité le demandent.
- [ ] (M4c, déclaration de K ; ou précision de 0010 D7.4) Lieu de K entre 1 m et un départ ancré (b_0 = s'_0 <= ε) : son cumulé P_k = P(s_w) − P(b_0) est négatif ; hors préfixe, il rend q_usage indisponible (support insuffisant), mais le drapeau d'erreur du modèle de usage_target (M4b-1) porte sur tout K : q_usage | préfixe devient « erreur du modèle », poids absents. Cas synthétique M05 ancré (M4b-2) ; aucun cas réel.
- [ ] (M4b-5, rapport) Diagnostic de géométrie de 0010 D3 (usage − contrôle, v0 brut, mêmes courbe, horloge et support) : calculé ni en M4b-2 ni ailleurs ; à rattacher au rapport D15 ou à écarter explicitement (relevé par B, passe 1 de M4b-2).
- [ ] (M4b-4) Provenance d'une trace en plusieurs tronçons : la prévision de contrôle porte la source du profil de trace_route, qui ne garde que trace.sources[0] ; les tronçons suivants perdent leur provenance (relevé par B, passe 1 de M4b-2).
