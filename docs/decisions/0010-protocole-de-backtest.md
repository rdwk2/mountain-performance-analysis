# 0010 — Protocole de backtest et métrique d'erreur

- **Date** : 2026-09-23
- **Statut** : acceptée

## Contexte

Le M3 a fermé la tranche verticale : un GPX entre, des temps de passage sortent.
Rien ne dit encore si ces temps sont bons. Le M4 construit la mesure **avant**
tout effet ajouté au modèle (principe 3 de la ROADMAP) : un effet ne rentre que
s'il fait baisser une erreur mesurée, contre des références et sans fuite de
données.

Cinq contraintes pèsent sur tous les choix :

- **Peu de données.** Une poignée de parcours de montagne répétés sur quelques
  semaines, quelques sorties de développement, une course longue interrompue.
  Aucune analyse statistique confirmatoire n'est possible aujourd'hui ; toute
  règle de décision est exploratoire.
- **La courbe v0 a été estimée sur une partie de ces sorties** (fenêtre du
  2026-05-20 au 2026-06-26) et produite après coup : aucun score ne peut
  revendiquer l'information réellement disponible avant la sortie.
- **Les traces réalisées ne suivent jamais exactement le préparé** : variantes,
  raccourcis, lacets, départs et arrivées à quelques mètres de la ligne,
  enregistrement qui démarre avant le départ.
- **Les arrêts** : le temps de référence est l'écoulé ; la courbe est estimée sur
  du mouvement ; aucun détecteur d'arrêts n'est validé.
- **L'usage** : planifier une course, où une erreur tardive coûte plus cher qu'une
  erreur précoce, et où l'on sous-estime plus volontiers qu'on ne surestime.

Cette décision fixe le protocole complet (appariement, horloges, métriques,
référence de répétabilité, modèles de référence et calage, règle d'admission,
fourchettes, dérive, sensibilité, registre). Il est livré en quatre lots,
M4a à M4d (§ D16).

## Options envisagées

**Unité de comparaison.** *A.* Temps cumulés aux points de passage. *B.* Erreur
en % du temps total. *C.* **Segments de longueur fixe le long du préparé**,
retrouvés sur la trace dans l'ordre du parcours, plus les cumulés aux passages en
métrique d'usage.

**Métrique.** *A.* Erreur absolue moyenne des cumulés. *B.* Écart relatif signé
`(p − t)/t`. *C.* **Logarithme du rapport** `r = ln(p/t)`, agrégé en couches :
niveau global, biais par régime de pente, dispersion intra-régime.

**Arrêts.** *A.* Écoulé seul. *B.* Temps de mouvement seul, arrêts retirés par un
détecteur. *C.* **Les deux** : l'écoulé comme référence, dix horloges de
mouvement en sensibilité.

**Plancher d'erreur.** *A.* Écart-type des répétitions. *B.* **Référence
prédictive de répétabilité** : un gabarit appris sur les autres jours du même
parcours prédit le jour retiré.

**Calage des références.** *A.* Aucun calage. *B.* Calage sur tout le jeu.
*C.* **Un paramètre d'échelle par modèle**, appris sur les entraînements terminés
avant l'origine de la performance évaluée.

**Décision sur un effet.** *A.* Test statistique (signes, permutation).
*B.* **Règle exploratoire préspécifiée** : seuil d'amplitude par performance,
majorité, dommages bornés sur des garde-fous figés ; confirmation statistique
reportée à des données futures.

## Décision

Le protocole ci-dessous. Les sections D0 à D17 sont normatives ; les lots M4a à
M4d les implémentent (§ D16). Les passages marqués *(précision)* fixent un point
qu'une implémentation doit trancher et que la spécification laissait ouvert.

### D0 — Conventions

- `r = ln(p/t)` : **positif = projection trop lente**. Une valeur `x` se lit
  `exp(x)`, pas `1 + x`. Les dispersions sont descriptives, pas des écarts-types.
- **Sortie** : une activité enregistrée (un fichier, ou plusieurs tronçons d'un
  même enregistrement), avec un identifiant stable. Une sortie qui traverse minuit
  reste une sortie, datée du **jour civil de son départ** (Europe/Paris).
- **Sorties retenues d'un jour** : les sorties du jour sont ordonnées par instant
  de départ ; la première est retenue ; une suivante l'est seulement si la durée
  écoulée cumulée des sorties du jour jusqu'à sa fin, **tous sports confondus**,
  est `< 4 h` (1 h de plat puis 2 h 30 en montagne : les deux ; 1 h de plat puis
  3 h 30 : la première seule). Le domaine (D2.1) s'applique ensuite à chaque
  sortie retenue. Les sorties non retenues restent en diagnostic.
- **Performance** : les sorties retenues et dans le domaine d'un même jour. C'est
  l'unité statistique de **toutes** les décisions (plis, moyennes, votes,
  calage) ; la retirer retire toutes ses sorties ; elle est « terminée » quand
  toutes ses sorties le sont. Aucun raccord temporel n'est fabriqué entre deux
  sorties. **Cas pris en charge : une seule sortie par performance.** Une
  performance de deux sorties ou plus reçoit des diagnostics par sortie ; elle est
  `jour multi-sorties` : non évaluable pour l'admission (D10), exclue du gabarit
  (D8) ; au calage (D9), elle n'entre que si toutes ses sorties sont des
  entraînements (D2.4), avec ses totaux sommés sur la journée.
- **Parcours** : itinéraire répété, avec ses variantes.
- Instants en UTC dans les calculs ; dates civiles en Europe/Paris.
- **Indisponibilité.** Toute valeur non calculable porte un statut parmi :
  `absent`, `ambigu`, `tangente indéfinie`, `trou`, `écart intérieur`,
  `support insuffisant`, `temps nul`, `référence non identifiée`,
  `non-convergence`, `erreur du modèle`, `non calé`, `jour multi-sorties` — avec
  motif, effectif et support. Elle ne vaut jamais zéro, ni « parfait », ni « échec
  sportif ». Un contrôle obligatoire indisponible **ne vaut pas satisfaction**.

### D1 — Objet et périmètre

Mesurer l'erreur du moteur v0 et de modèles de référence, performance par
performance, et fournir une règle **exploratoire** d'admission des futurs effets.
Le M4 ne teste aucun effet réel : la règle d'admission est codée et éprouvée sur
cas synthétiques ; sa première utilisation est le M6a. Hors M4 : estimation de
courbe (M6b), modélisation de la forme ou de la progression, effets (M6a+),
confirmation statistique (données futures).

### D2 — Données

**D2.1 Domaine.** Trail à pied (`Sport.FOOT`), départ au plus tôt à la **date de
début du domaine** déclarée dans le manifeste (aujourd'hui 2026-05-20, premier
jour de la fenêtre de la courbe v0), profil de **D+/km ≥ 40** — D+ du profil lissé
de `0008` rapporté à sa longueur. Profil utilisé : le préparé ; à défaut, la trace
de référence désignée ; à défaut, la trace réalisée — source fixée par le
manifeste avant toute évaluation ; seuil inclusif. Les sorties de plat (≈ 14 D+/km
sur la série observée) forment un diagnostic « hors domaine », hors de tout score
principal ; les parcours de répétabilité mesurent 66 à 87 D+/km.
*(précision, M4b-5)* Le profil de domaine se lit comme un tracé (lecture GPX, profil lissé
de `0008` à ses paramètres par défaut) : le préparé, la trace de référence désignée ou, à
défaut, les fichiers de trace de la sortie, même refusés par la lecture des traces (un
fichier sans horodatage reste un tracé) ; une sortie en plusieurs fichiers a pour D+/km la
somme de leurs D+ sur la somme de leurs longueurs. Sans fichier, ou si l'un ne se lit pas
comme un tracé, le D+/km est inconnu, et la sortie hors domaine avec ce motif. Le motif
d'une sortie retenue hors du domaine est le premier, dans l'ordre : sport, date, D+/km
inconnu, D+/km sous le seuil. Une sortie du domaine dont la trace est refusée reste dans sa
performance, non scorée, avec le motif du refus.

**D2.2 Fenêtre de la courbe v0** : du 2026-05-20 00:00 au 2026-06-26 24:00
(Europe/Paris), les deux jours inclus. La courbe a été produite en septembre
2026 : **aucun score M4 ne peut revendiquer l'information disponible à J−7** ;
tous les scores de développement sont rétrospectifs.

**D2.3 Jeux**, déclarés sortie par sortie dans le manifeste :
- *répétabilité* : parcours répétés dans la fenêtre de la courbe. Les scores de
  v0 sur ces jours sont étiquetés **« apprentissage »** : la courbe les contient,
  et le retrait d'un jour dans le gabarit (D8) ne le retire pas de la courbe ;
- *développement* : après la fenêtre, déjà regardées ; résultats **indicatifs** ;
- *confirmation* : performances dont l'origine `o_j` (D2.5) est **postérieure à
  l'instant de figement de la déclaration du candidat** (D10.7), idéalement sur
  des itinéraires nouveaux.

**D2.4 Trois ensembles historiques**, déclarés séparément :
1. le **jeu de répétabilité**, pour la référence de D8 ;
2. l'**information à l'origine** `C_j` de la performance `j` : performances du
   domaine dont **toutes** les sorties retenues sont étiquetées **entraînement**
   (une étiquette manquante ne vaut pas entraînement ; une performance contenant
   une course est exclue **en entier**, motif publié), terminées (toutes leurs
   sorties) avant `o_j`. Les courses en sont exclues : l'effort de course est un
   effet futur, calibrable sur courses seulement. Sert au calage des modèles (D9)
   et des effets ;
3. le **réservoir des fourchettes** : identique à `C_j`, chaque résidu étiqueté
   dans ou hors fenêtre de la courbe (D11).

**D2.5 Origine et disponibilité.** `o_j` = 00:00 Europe/Paris du jour civil
`J − 7`. Une donnée est disponible à `o_j` si l'instant de **fin** de la sortie
qui la porte est strictement antérieur à `o_j`. Âge de la courbe rapporté au jour
`J` et à `o_j`. L'origine n'est jamais déplacée après coup.

**D2.6 Manifeste et provenance.** Un fichier sous `MPA_DATA_DIR` décrit chaque
sortie : identifiant, fichier(s), sport, instants de départ et de fin, parcours,
variante et portion déclarée, préparé ou **trace de référence désignée à
l'avance**, jeu, étiquette course / entraînement, relevés externes avec leur
convention **par passage** (`TimingConvention` de `reference.py`). Rang dans le
jour, statut « retenue », domaine et performance s'en déduisent (D0, D2.1). Une
sortie **ou un relevé externe** dont l'`athlete_ref` diffère de celui de la courbe
est refusé avant tout calcul. Chaque artefact utilisé porte une **empreinte**
(SHA-256), un **instant de disponibilité** et un **rôle** : **entrée de
prévision** (courbe, préparé ou trace de référence, paramètres, historique de
calage effectivement utilisé) ou **observation d'évaluation** (trace réalisée, fin
réelle, statut « retenue »). Une prévision n'est éligible à une confirmation à J−7
que si toutes ses **entrées** étaient disponibles à `o_j` ; les observations
d'évaluation, postérieures par nature, n'entrent pas dans ce test. Des fichiers
qui décrivent la même sortie (tronçons, doublons) sont réunis en une sortie par le
manifeste, jamais comptés deux fois.
*(précision, M4b-4)* La courbe est déclarée par l'exécution qui l'utilise, pas par le
manifeste : la DÉCLARATION (D14) porte le CSV et son compagnon de provenance, avec leurs
empreintes ; leur instant de disponibilité est l'instant d'estimation de la provenance
(`generated_at`), et leur rôle, entrée de prévision. Par exception, le manifeste est cité
par son empreinte seule, sans instant de disponibilité ni rôle : il décrit à la fois des
entrées et des observations.
*(précision, M4b-5)* La courbe ne porte pas d'athlète (ni son CSV, ni son compagnon de
provenance) : le refus d'une sortie ou d'un relevé d'un autre athlète se fait contre
l'athlète du manifeste, que la DÉCLARATION fige ; qu'une courbe soit celle de cet athlète
n'est vérifié par rien, jusqu'à ce que la courbe porte le sien (M6b).

### D3 — Scénarios

- **Usage** : projection sur le profil de référence (préparé ou trace de référence
  désignée), comparée à la trace réalisée.
- **Contrôle** : projection sur le profil de la trace réalisée elle-même
  (rétrospectif, non disponible à J−7) ; son écart à l'usage n'isole pas
  causalement une cause.
- *(précision)* **Sortie sans préparé ni trace de référence désignée** : elle n'a
  pas de scénario d'usage ; sa grille de score et son appariement (D4) portent sur
  le profil de sa propre trace, et seul le scénario contrôle est calculé.
- **Correspondance** : le segment `i` de la grille de score (D4.2) correspond,
  dans le scénario contrôle, à la portion de trace réalisée entre `t*_i` et
  `t*_{i+1}`, d'abscisses réalisées `d_r(π_i)` et `d_r(π_{i+1})`. Mêmes temps
  observés `t_i` dans les deux scénarios.
- **Partition commune** : les régimes des segments sont ceux du profil de
  référence, **dans les deux scénarios**. Un diagnostic séparé, classé selon le
  profil réalisé, peut être publié.
- **Diagnostic de géométrie** (usage − contrôle) : calculé avec **v0 brut**, sans
  aucun calage, mêmes courbe, horloge et support. Les modèles calés (D9) sont
  scorés dans chaque scénario avec leur propre calage ; l'écart de leurs scores
  entre scénarios n'est pas lu comme un effet de géométrie.
- *(précision, M4b-5)* Le diagnostic de géométrie d'une sortie à référence est
  `G = ln(ΣP_usage / ΣP_contrôle)`, sommes des prévisions de v0 brut sur son support
  admis, et `G_R` de même sur les segments de chaque classe : il ne dépend pas des temps
  observés, et vaut `L_usage − L_contrôle` sous toute horloge où les deux sont
  disponibles. Une prévision absente, non finie, nulle ou négative le rend indisponible
  (`erreur du modèle`) ; une classe sans segment, `support insuffisant`. Publié par sortie
  au rapport (D15) ; ni cible ni garde-fou.

### D4 — Appariement (M4a)

**D4.1 Profil de référence** : sortie de `build_profile` (M2) **inchangée**,
défauts `0008` (`h = 50 m`, moyenne glissante 150 m). Le backtest ne
rééchantillonne pas le profil. *(précision)* La géométrie horizontale du tracé de
référence accompagne le profil : polyligne dédoublonnée de `0008`, abscisses
haversine cumulées — celles dont la grille du profil est issue ; la position à
l'abscisse `s` s'obtient par interpolation linéaire en latitude et longitude sur
cette polyligne.

**D4.2 Grille de score**, distincte de la grille fine : `s_k = kΔ` pour
`kΔ < L`, plus `L` ; `Δ = 250 m` ; le dernier segment, plus court, est déclaré.
Les longueurs de segment sont toujours les longueurs exactes. **Bornes
effectives**, par sortie : `b_0 = s'_0` si le départ est ancré (D4.8), sinon 0 ;
`b_K = s'_K` si l'arrivée est ancrée, sinon `L` ; `b_k = s_k` ailleurs. **Toutes**
les quantités — longueurs, fractions de régime, projections, `ρ`, `H`, distances
admises, cumuls — utilisent les `b_k` ; le dénominateur de couverture reste `L`,
et les mètres omis aux extrémités sont exclus avec le motif `ancrage`. Un segment
est identifié par ses bornes : un segment de bord ancré n'est pas la même cellule
que le segment nominal.

**D4.3 Géométrie locale.** Coordonnées horizontales métriques dans le plan tangent
de `0008` (`x = R·Δλ·cos φ_A`, `y = R·Δφ`), ancré au point de score concerné pour
le franchissement et au début du segment pour le contrôle intérieur. Tangente
unitaire `τ` = corde entre les positions du profil à `s − 25` et `s + 25` m,
bornées à `[0 ; L]` (unilatérale aux bords) ; normale `n` = `τ` tourné de +90°.
Corde de longueur `< 1e−6` m : statut `tangente indéfinie`, jamais une normale non
finie propagée. Longueurs réalisées par haversine (`0008`).

**D4.4 Lecture de trace.** Instants strictement croissants : des enregistrements
de même instant sont réduits au premier ; un instant décroissant ou une valeur non
finie fait refuser la sortie (statut motivé). Plusieurs tronçons sont concaténés ;
leur raccord est un trou s'il dépasse 10 s. Aucun rééchantillonnage à 1 Hz.
**Bloc** = suite d'enregistrements sans trou. Positions et altitudes **brutes** et
**lissées** (moyenne centrée sur 5 enregistrements, tronquée aux bords de bloc,
jamais complétée par zéro) sont conservées sous des noms distincts ; les
enregistrements immobiles ne sont jamais supprimés. Abscisse réalisée `d_r` =
distance haversine cumulée des positions brutes ; position fractionnaire
`π = i + f`.

**D4.5 Franchissement intérieur.** Pour un point `Q` et les positions **brutes**
`P_i` : `h_i = (P_i − Q)·τ`. Franchissement orienté entre `i` et `i+1` si
`h_i ≤ 0 < h_{i+1}` et `t_{i+1} − t_i ≤ 10 s` ; `f = −h_i/(h_{i+1} − h_i)` ;
`t* = (1−f)t_i + f t_{i+1}` ; `ℓ* = ((1−f)P_i + fP_{i+1} − Q)·n` (**interpolation
signée**) ; candidat admissible si `|ℓ*| < ε = 30 m`.

**D4.6 Recherche ordonnée.** État du chercheur : `(π_cur, k_der)`, initialisé à
`(0, 0)`. Pour le point `k`, candidats de position `π > π_cur` (`π ≥ 0` pour
`k = 0`) et `d_r(π) ≤ d_r(π_cur) + 2,5·Δ·(k − k_der) + 300 m`, fenêtre tronquée à
la fin de la trace. Après un statut `trouvé` ou `ancré` : `π_cur ← π`,
`k_der ← k`. Après tout autre statut : état inchangé (la fenêtre s'élargit au
point suivant). Les instants retenus sont donc strictement croissants.

**D4.7 Regroupement et ambiguïté.** Les candidats admissibles, triés par `π`, sont
regroupés en **événements** : deux candidats consécutifs appartiennent au même
événement s'ils sont dans le **même bloc** et si tout le sous-chemin fermé qui les
relie — leurs deux points de franchissement interpolés et les enregistrements
bruts strictement entre eux — reste à `≤ r_c = 15 m` de `Q`. Les candidats de même
`π` sont confondus. Les candidats sont **tous** énumérés dans la fenêtre avant
toute décision, arrivée comprise. Un événement est daté par son **dernier**
candidat (convention départ, `0005`), sauf au point d'arrivée, daté par son
premier. Un événement : `trouvé`. Deux ou plus : `ambigu`, exclu et compté ;
jamais départagé par l'erreur d'un modèle. *(précision)* Au moins un
franchissement orienté dans la fenêtre, aucun admissible, pas d'ancrage : statut
`hors ε`, qui se comporte comme `absent` pour l'état du chercheur.

**D4.8 Extrémités.**
- **Départ** (`k = 0`) : règle D4.5. Une trace immobile sur la ligne est datée au
  dernier instant sur la ligne. Si **aucun candidat admissible** n'existe (jamais
  pour effacer une ambiguïté) et que le premier enregistrement vérifie
  `0 < h_0 ≤ ε` et `|ℓ_0| < ε` : **ancrage**, `t*_0 = t_0`, `b_0 = s'_0`, abscisse
  de la projection orthogonale de `P_0` sur le préparé restreint à
  `[0 ; min(2ε, L)]`.
- **Arrivée** (`k = K`) : candidats de la condition fermée `h_i ≤ 0 ≤ h_{i+1}`,
  `(h_i, h_{i+1}) ≠ (0, 0)`, avec les autres exigences de D4.5–D4.7 ; un seul
  événement → daté par son premier candidat. Si aucun candidat admissible et que
  le dernier enregistrement vérifie `−ε ≤ h_der < 0`, `|ℓ_der| < ε`, dans la
  fenêtre et avec `π > π_cur` : ancrage, `t*_K = t_der`, `b_K = s'_K`, projection
  sur `[max(0, L − 2ε) ; L]`.
- La projection d'ancrage doit être unique : si la distance minimale est atteinte
  à plusieurs abscisses (à 0,01 m près), statut `ambigu`. *(précision)* Les
  minima candidats sont les minima locaux de la distance le long de la polyligne
  restreinte, lus sur le paramètre de projection comme en `0008` ; deux minima
  d'abscisses distantes de plus de 0,01 m, de distances à moins de 0,01 m du
  minimum, rendent l'ancrage ambigu. Les écarts curvilignes sont vérifiés :
  `s'_0 ≤ ε` et `L − s'_K ≤ ε` ; sinon extrémité `absente`. Les bornes effectives
  doivent être strictement croissantes ; sinon l'extrémité est `absente`. Sans
  ancrage, `s' = s`.
- **Arrivée ancrée** : l'arrivée est observée en `b_K = s'_K` (statut
  `arrivée ancrée`, écart `L − s'_K ≤ ε` publié) ; projections lues en `s'_K`. Ce
  n'est jamais présenté comme l'arrivée originale en `L`. Au départ, de même, les
  cumuls observés et projetés partent de `(t*_0, b_0)`.
- Au-delà de `ε` : extrémité `absente`. Décalages et durée avant départ
  (`t*_0 − t_premier`) **publiés**.

**D4.9 Trous.** Aucun franchissement interpolé entre deux enregistrements séparés
de plus de 10 s (10 s autorisé, 10,001 s interdit). Un segment dont l'intérieur
contient un trou a le statut `trou` : son temps écoulé peut être rapporté, il
n'est pas scoré.

**D4.10 Admissibilité d'un segment** `[b_k ; b_{k+1}]` — toutes les conditions :
1. deux bornes `trouvées` ou `ancrées` ;
2. aucun trou à l'intérieur ;
3. `ρ = ℓ_réalisé / (b_{k+1} − b_k) ∈ [0,6 ; 1,6]`, bornes incluses, où
   `ℓ_réalisé` est la longueur du chemin : point de franchissement `k` → positions
   **lissées** des enregistrements strictement intérieurs → point de
   franchissement `k+1` (ou d'ancrage). *(précision)* Échec : motif
   `rapport de longueur` ;
4. **contrôle intérieur** : `H = max(H_1, H_2) ≤ ε`, avec `H_1` = plus grande
   distance d'une position lissée intérieure au préparé restreint à
   `[max(0, b_k − ε) ; min(L, b_{k+1} + ε)]` (**`H_1 = 0` si aucun enregistrement
   intérieur**), et `H_2` = plus grande distance, aux **segments** du chemin du
   point 3, des points du préparé suivants : sommets de la polyligne restreinte à
   `[b_k ; b_{k+1}]`, les deux bornes exactes, et les abscisses `b_k + 10n`
   intérieures. Échec : statut `écart intérieur`. Ce contrôle est **discret** : il
   ne garantit ni le tube entre échantillons, ni l'ordre intérieur des branches.

Aucun temps cumulé n'est reconstruit à travers une portion non admise.

**D4.11 Couverture publiée** : distance admise / longueur du profil, globale et
par régime — pour un régime `R`, numérateur = longueurs fines de `R` contenues
dans les segments admis, dénominateur = longueur fine de `R` sur `[0 ; L]`
(dénominateur nul → non évalué) ; temps écoulé admis ; distances et temps exclus
connus, **par motif** (dont `ancrage`) ; durées inconnues ; points `trouvés`,
`ancrés`, `ambigus`, `absents`, `hors ε`, `tangente indéfinie`. **Préfixe
comparable** : plus grand `m` tel que les segments `0…m−1` sont tous admis ;
publier son abscisse de fin `b_m`, son instant `t*_m` et le dernier passage nommé
qu'il contient (« aucun » s'il n'en contient pas — jamais de nom inventé).

**D4.12 Passages nommés et événements.**
- Waypoints du préparé, résolus sur le profil par `0008` (plusieurs occurrences
  possibles sur une boucle). Chaque occurrence `w` garde son abscisse exacte
  `s_w` ; elle n'est **pas** ajoutée à la grille de score.
- Observation : franchissement de la normale en `s_w` (D4.5–D4.8), cherché entre
  les franchissements des deux points de score qui encadrent `s_w`, sur le préfixe
  comparable seulement. Un waypoint à moins de 1 m d'un point de score réutilise
  le franchissement de ce point ; sa fenêtre d'association va alors du
  franchissement de `k − 1` à celui de `k + 1`.
- **Association arrêt → passage**, sous la convention centrale
  `θ_c = (0,10 ; 0,03 ; 60)` (D5). Pour un épisode d'arrêt confirmé `[a ; b]`,
  les occurrences candidates sont celles trouvées sur le préfixe dont `Q_w` est à
  moins de `ε` de la position lissée médiane de l'épisode (médiane coordonnée par
  coordonnée, dans le repère local, des positions lissées des enregistrements de
  l'épisode) et dont la fenêtre d'association chevauche `[a ; b]`. L'épisode est
  attribué à **une seule** occurrence : celle dont `t*_w` est la plus proche de
  `[a ; b]` (distance nulle si `t*_w ∈ [a ; b]`) — égalité jugée à 1 s près —,
  puis celle dont `Q_w` est la plus proche de la position médiane — égalité à 1 m
  près ; égalité persistante : épisode `non attribué`, publié.
- Événements : `arrivée_w = min(t*_w, a_premier)`,
  `départ_w = max(t*_w, b_dernier)` sur les épisodes attribués à `w` ; sans
  épisode, `arrivée_w = départ_w = t*_w`. La somme des durées `S` attribuées est
  publiée à part de l'enveloppe `départ − arrivée`. **Chronologie** vérifiée pour
  les occurrences successives du préfixe (arrivée finale comprise) :
  `arrivée_w ≤ départ_w ≤ arrivée_{w+1}` ; une violation rend les événements des
  deux occurrences `ambigus`. Jamais de durée de déplacement négative.
- **Maintien dans le préfixe** : un événement utilisé comme observation comparable
  doit appartenir à `[t*_0 ; t*_m]` et suivre l'origine (`t*_0 ≤ arrivée_w`). Si un
  épisode attribué fait sortir `arrivée_w` ou `départ_w` de cet intervalle, le
  passage est **indisponible** (motif `support insuffisant`) ; ses événements
  restent publiés en diagnostic. On ne tronque jamais l'épisode et on ne supprime
  jamais son attribution pour fabriquer un départ favorable. L'indisponibilité se
  propage à `C_k`, `q_usage`, au garde-fou des passages et à la dérive selon leurs
  règles.
- **Arrivée unique** : `K` contient une seule occurrence terminale ; un waypoint
  qui représente l'arrivée reprend l'événement d'arrivée, ancrage compris, sans
  second poids ni seconde cible en `L`. Les autres occurrences d'un même lieu sur
  une boucle restent distinctes.
- **Temps observés `T_k` des métriques** : départ aux passages nommés (`0005`) ;
  franchissement `t*` aux points de score ; à l'arrivée, premier franchissement ou
  `t*_K` ancré. Sous une autre horloge que l'écoulé, les instants passent par les
  fonctions cumulées de D5.3, depuis la même origine.
- **Relevés externes** : associés par nom puis par abscisse. L'observation
  principale est celle de la trace ; un relevé externe est un **diagnostic
  d'écart**. Un relevé `DEPARTURE` se compare au départ projeté, `ARRIVAL` à
  l'arrivée projetée ; `UNKNOWN` : hors comparaison principale, ou deux scénarios
  arrivée / départ déclarés avant résultat.
- Projection : cumul projeté calculé à `s_w` exact. Un futur arrêt projeté au
  passage `w` se place entre `arrivée_w` et `départ_w` : il appartient au passage,
  jamais aux deux intervalles voisins.

### D5 — Horloges (M4a)

**D5.1 Écoulé** : référence principale, et référence de l'effet « arrêts ». Durée
observée `E = t_dernier − t_premier`, trous compris.

**D5.2 Partition.** Intervalles élémentaires `I_i = [t_i ; t_{i+1})` entre
enregistrements consécutifs. Pour chacune des cinq conventions `θ = (h ; z ; c)` —
`(0,05 ; 0,015 ; 60)`, `(0,10 ; 0,03 ; 60)` (centrale), `(0,15 ; 0,045 ; 60)`,
`(0,10 ; 0,03 ; 30)`, `(0,10 ; 0,03 ; 90)` (m/s, m/s, s) — chaque intervalle
reçoit **un seul** état `M`, `S` ou `U` :
- intervalle de trou (`> 10 s`) : `U` ;
- sinon, **fenêtre exacte** `W_i = [m_i − 15 s ; m_i + 15 s]` centrée sur le
  milieu `m_i` de l'intervalle. Valide seulement si ses deux bornes sont dans le
  même bloc et si le lissage est complet (non tronqué) pour les enregistrements qui
  encadrent chaque borne et pour ceux qui sont strictement intérieurs.
  *(précision)* Les enregistrements qui encadrent une borne `β` sont
  `j⁻ = max{j : t_j ≤ β}` et `j⁺ = min{j : t_j ≥ β}`, confondus si `β` tombe sur
  un enregistrement. Valeurs aux bornes `X̃(m_i ± 15)`, `z̃(m_i ± 15)` :
  interpolation linéaire de la série **lissée** entre `j⁻` et `j⁺`. Alors
  `v_h = ‖X̃(m_i + 15) − X̃(m_i − 15)‖ / 30`,
  `v_z = |z̃(m_i + 15) − z̃(m_i − 15)| / 30` ; diamètre `D_h` et étendue `D_z`
  calculés sur les deux valeurs de borne **et** les valeurs lissées des
  enregistrements strictement intérieurs. *(précision)* Distances horizontales dans
  le plan local de `0008` ancré en `X̃(m_i − 15)` ;
- qualification : **mobile** si `v_h > h` ou `v_z > z` ; **immobile** si
  `v_h ≤ h`, `v_z ≤ z`, `D_h ≤ 30h` et `D_z ≤ 30z` ; **indéterminé** sinon, et
  pour toute fenêtre invalide. *(précision, M4a-2c)* Les comparaisons portent sur
  les valeurs réelles : une mesure qui ne diffère de son seuil que de l'erreur
  d'arrondi lui est égale — en flottant, `|x − s| ≤ 10⁻⁶·s`. Les altitudes
  enregistrées au pas de 0,2 m atteignent exactement `z` et `30z` (`Δz = 0,9` m en
  30 s sous `θ_c`) ;
- **confirmation** : une suite maximale d'intervalles consécutifs *immobiles* d'un
  même bloc dont la **durée** totale est `≥ c` passe entièrement à `S` ; plus
  courte, elle passe à `U`. *Mobile* → `M` ; *indéterminé* → `U`.
- Contrôle exact : `M_θ + S_θ + U_θ = E` pour chaque `θ`.

**D5.3 Horloges cumulées.** Fonctions `m_θ(t)`, `s_θ(t)`, `u_θ(t)` = temps cumulé
dans chaque état depuis `t_premier`, linéaires dans chaque intervalle. Temps d'un
segment sous l'horloge `M_θ` : `m_θ(t*_{k+1}) − m_θ(t*_k)` ; sous `M_θ + U_θ` :
idem avec `m_θ + u_θ` ; en écoulé : `t*_{k+1} − t*_k`. Additivité exacte sur tout
découpage.

**D5.4 Onze horloges** : écoulé, `M_θ` (5), `M_θ + U_θ` (5). Toutes calculées et
conservées.
- **Deux jeux de totaux**, publiés séparément : ceux de la **trace**
  (`E`, `M_θ`, `S_θ`, `U_θ`) et ceux du **support admis** (`E_A`, `M_{θ,A}`,
  `S_{θ,A}`, `U_{θ,A}`), sommés sur les intervalles `[t*_k ; t*_{k+1}]` des
  segments admis. Chaque identité porte sur un seul jeu :
  `E_A = M_{θ,A} + S_{θ,A} + U_{θ,A}` et
  `I_sens,A = [min_θ M_{θ,A} ; E_A − min_θ S_{θ,A}]`.
- Le rapport montre trois horloges : l'écoulé, et les deux **scénarios réalisant
  les extrêmes du total admis** — `θ_bas = argmin_θ M_{θ,A}` et
  `θ_haut = argmax_θ (M + U)_{θ,A}`, égalités départagées par l'ordre de la liste
  de D5.2 — appliqués à **tous** les segments de la performance. Jamais de maximum
  ou de minimum segment par segment.
- **Enveloppes** : pour un total projeté `P` et un temps admissible dans
  `[a ; b]`, `L ∈ [ln(P/b) ; ln(P/a)]`, `min |L| = 0` si l'intervalle contient
  zéro ; `a = 0 < P` donne une borne supérieure `+∞` et le statut `temps nul`. Pour
  un régime `R`, l'enveloppe se construit **sur le support de `R`** :
  `a_R = min_θ M_{R,θ}`, `b_R = max_θ (M + U)_{R,θ}`. Ces enveloppes valent **à `P`
  fixé** : elles ne bornent pas les scores de modèles recalés différemment selon
  l'horloge. Les `E_R` et `D_R` aux horloges scénarios sont des **scénarios**, pas
  des bornes.

**D5.5 Temps nuls.** Un segment de temps nul sous une horloge rend `r_i` indéfini :
les quantités vectorielles (`r`, `E_R`, `D_R`, `A`, `W`, `B`, `C_comp`) sont
`indisponibles` (`temps nul`) pour cette performance et cette horloge ; `L` reste
calculable si le total est positif. Un diagnostic sur le sous-support à temps
positifs peut être publié avec son masque ; il ne remplace jamais le support
principal.
*(précision, M4b-1)* Le diagnostic porte les mêmes métriques que le support
principal (D7.2), calculées sur les segments de temps positif, et publie son
masque ; l'erreur du modèle s'y juge sur le support principal.

### D6 — Régimes

Pente fine `g_h = (Z_{h+1} − Z_h)/(s_{h+1} − s_h)` sur la grille fine de `0008`
(longueurs réelles, pas toujours 50 m) : montée `g > 0,05`, plat
`−0,05 ≤ g ≤ 0,05`, descente `g < −0,05`. Fraction d'un segment de score `i`, sur
ses bornes effectives :
`f_iR = Σ_h |[b_i ; b_{i+1}] ∩ [s_h ; s_{h+1}]| · 1{R(g_h) = R} / (b_{i+1} − b_i)`.
Segment **pur** si `max_R f_iR ≥ 0,80` (inclus), sinon **mixte** — classe réelle
du score. Diagnostic seulement : descente roulante `−0,15 ≤ g < −0,05`, raide
`g < −0,15`, même règle. Le temps observé n'est jamais réparti selon ces
fractions. Régime absent = « non évalué ». Mixte, roulante et raide ne sont
**jamais** des cibles ni des garde-fous, ni des dimensions d'apprentissage
d'effets sans nouvelle préspécification.
*(précision, M4b-5)* « Même règle » pour les descentes : seul un segment de classe
descente reçoit une sous-classe — **roulante** si sa fraction roulante atteint le seuil,
**raide** si sa fraction raide l'atteint, sinon **non départagée** (comptée, jamais
scorée). Le seuil vaut 0,80, celui des segments purs ; une exécution peut en prendre un
autre dans `[0,60 ; 1]`, que sa synthèse et son rapport publient — un réglage du
diagnostic, sans effet sur les scores ni sur le registre (au-dessus de 0,5, un segment
n'est jamais roulant et raide à la fois ; les fractions se lisent sur la grille fine,
souvent par cinquièmes). Une sous-classe se mesure sur ses segments : `E_R` et `D_R` (D7.2), et
`E_R − L` contre le `L` de la performance ; moins de 3 segments, elle est trop peu
représentée (D7.5).

### D7 — Métriques (M4b)

**D7.1 Support.** Segments admis `i` (D4.10), déterminés par l'observation seule,
donc identiques pour tous les modèles comparés. Une sortie de modèle `p_i ≤ 0`,
non finie ou manquante sur ce support donne le statut `erreur du modèle` pour la
performance et ce modèle : **aucune exclusion** de la portion concernée.
*(précision, M4b-1)* Quand plusieurs statuts s'appliquent à une même valeur,
l'observation passe avant le modèle : support vide, régime absent, temps nul,
puis erreur du modèle. L'erreur du modèle est en outre signalée pour la
performance et le modèle.

**D7.2 Formules** (`p_i > 0`, `t_i > 0`, `T = Σ t_i`, `T_R = Σ_{i∈R} t_i`,
`α_R = T_R/T`) :
- `r_i = ln(p_i/t_i)` ; `L = ln(Σ p_i / Σ t_i)` ;
- `E_R = ln(Σ_{i∈R} p_i / T_R)` ; `D_R = Σ_{i∈R} t_i |r_i − E_R| / T_R` ;
- `A = Σ (t_i/T) |r_i − L|`, `W = Σ_R α_R D_R`, `B = Σ_R α_R |E_R − L|`,
  `C_comp = Σ_i (t_i/T) [ |r_i − E_{R(i)}| + |E_{R(i)} − L| − |r_i − L| ] ≥ 0`,
  d'où l'identité exacte `A = W + B − C_comp`, toutes classes non vides, mixte et
  régimes à un ou deux segments compris. Descriptive : `W` et `B` ne sont pas deux
  causes additives. `C_comp` se calcule par sa formule, jamais par `W + B − A`.
- Cas limites : support vide → `L`, `A`, `W`, `B`, `C_comp` indisponibles ; régime
  absent → `E_R`, `D_R` indisponibles (jamais `0/0`, jamais `α_R · NaN`) ; un seul
  segment dans `R` → `D_R = 0` exactement, sans valeur de preuve.
  *(précision, M4b-1)* Le support vide et le régime absent portent le statut
  `support insuffisant`, d'effectif nul ; le régime absent est le « non évalué »
  de D6.
- Diagnostic de forme `E_R − L`. Invariances : `D_R` ne change pas si l'on
  multiplie les `p_i` d'un régime par une constante ; `E_R − L` ne change pas sous
  une multiplication globale. D'où les garde-fous de niveau et de passages de D10.

**D7.3 Erreurs aux passages** (obligatoires) : `C_k = P_k − T_k` en secondes, temps
**cumulés** depuis l'origine commune `(t*_0, b_0)`, `T_k` défini en D4.12, aux
passages nommés et aux points de score du **préfixe comparable** seulement (ce ne
sont pas des sommes de segments admis). Publier `max_k |C_k|`, `max_k C_k`,
`min_k C_k` ; ensemble vide → indisponible.
*(précision, M4b-1)* L'origine `(t*_0, b_0)` n'est pas un point de l'ensemble
(`C_0 = 0` par construction). Un `C_k` indisponible est publié avec son motif.
Les agrégats portent sur les points observés : aucun point observé,
`support insuffisant` ; une sortie de modèle invalide en l'un des points donnés,
observé ou non, `erreur du modèle` ; sinon, les `C_k` des points observés.

**D7.4 Cible d'usage.**
`q_usage = Σ_{k∈K} w_k |P_k − T_k| / P_k^(0)`, avec `P^(0)` la projection du modèle
de base, fixée à l'origine et identique pour les modèles comparés. **Dans le
rapport**, hors expérience, `P^(0)` est la projection de **v0 brut** ; dans une
expérience d'admission, c'est la base `(0)`. Une arrivée ancrée est observée et
projetée en `b_K`, avec son statut. Conditions : `K` non vide, départ exclu,
`w_k ≥ 0`, `Σ w_k = 1`, `P_k^(0) > 0`.
- **Défaut** : `K` = tous les passages nommés du profil de référence, départ exclu,
  **plus l'arrivée** (sans waypoint, `K` = {arrivée}) ; **poids proportionnels au
  temps projeté**, `w_k = P_k^(0) / Σ_{k'} P_{k'}^(0)`, d'où
  `q_usage = Σ |P_k − T_k| / Σ P_k^(0)` (une erreur tardive pèse ses secondes).
- Un passage de `K` indisponible (hors du préfixe comparable, ambigu…) rend
  `q_usage` **indisponible** pour la performance, sans repondération. Le rapport
  peut publier le diagnostic **`q_usage | préfixe`**, restreint aux passages de `K`
  situés dans le préfixe comparable, poids renormalisés, avec la mention « n
  passages sur N » ; ce diagnostic n'est ni une cible ni un garde-fou, sauf
  déclaration explicite d'une expérience avant résultat.
  *(précision, M4b-1)* `q_usage` indisponible porte le motif du premier passage
  indisponible de `K` dans l'ordre des abscisses, avec pour effectif le nombre de
  passages disponibles. `q_usage | préfixe` porte sur les passages de `K`
  disponibles, poids renormalisés sur eux.
- Une expérience peut déclarer un autre `K` et d'autres poids avant résultat, sous
  les mêmes règles.
- **Passages comparables** (garde-fou de D10.4) : passages de `K` situés dans le
  préfixe comparable, avec `T > 0` et des événements maintenus dans le préfixe. La
  fin d'un préfixe interrompu n'est **pas** un passage.

**D7.5 Effectifs.** Segments et **jours** publiés par métrique. Un régime de moins
de 3 segments sur une performance est « trop peu représenté » : sa valeur reste
dans l'identité, mais ne sert ni de cible ni de garde-fou pour cette performance.

### D8 — Référence prédictive de répétabilité (M4b)

Par parcours, sur les jours du **jeu de répétabilité** seulement, et pour
**chacune des onze horloges**.

**D8.1 Modèle.** `y_uk = ln t_uk = a_k + c_{u,R(k)} + e_uk`. **Chaque cellule
observée a le même poids** : un jour partiel ou un segment terminal court ne sont
pas repondérés. **Cellules** = segments de bornes nominales : un segment de bord
ancré n'entre pas dans le gabarit et reste hors support. Une performance
`jour multi-sorties` en est exclue. Le problème se sépare par régime. Pour chaque
jour `j`, retrait de **toutes** ses lignes (pli).
*(précision, M4b-3)* Les jours sont les performances du jeu de répétabilité du
parcours, ordonnées par date ; une performance `jour multi-sorties` est exclue et
publiée comme telle. Une cellule `(u, k)` est un segment admis dont les bornes
effectives sont les bornes nominales, identifié par son indice `k` dans la grille
de score de la référence du parcours : tous les jours ont la même référence, et un
même indice y a les mêmes bornes nominales et, pour ses cellules, la même classe,
sinon l'entrée est refusée. Le problème se sépare en quatre sous-problèmes
indépendants, un par classe de D6 : montée, plat, descente et mixte.
*(précision, M4b-5)* Un jour dont la sortie n'est pas scorée (trace refusée ou absente)
n'entre pas dans la référence ; l'exécution publie cette sortie parmi ses sorties non
scorées. Un jour dont la sortie est scorée sans segment admis y entre, sans cellule.

**D8.2 Identification par pli et par régime.** Graphe biparti (jours
d'apprentissage × segments du régime observés). Contrainte de centrage
`Σ_{u∈A_R} c_{uR} = 0` sur la composante. Si les segments du jour retiré dans `R`
qui sont observés à l'apprentissage relèvent de **plusieurs** composantes : régime
`R` **indisponible** pour ce pli (`référence non identifiée`). Les segments du
jour retiré non observés à l'apprentissage sont hors support.
*(précision, M4b-3)* Pour le pli `j` et la classe `R`, `S_jR` désigne les segments
de `R` observés par le jour retiré et par au moins un jour d'apprentissage. `S_jR`
vide : la classe est indisponible pour ce pli (`support insuffisant`). Le graphe se
construit sur toutes les cellules d'apprentissage de `R`, nulles comprises. Si
`S_jR` rencontre plusieurs composantes : `référence non identifiée`. Sinon
l'ajustement porte sur la seule composante qui contient `S_jR`, avec toutes ses
cellules ; les autres composantes sont ignorées, et le centrage porte sur les jours
de cette composante.

**D8.3 Résolution et certification.** Résolution directe ou itérative. Résidus
`e_uk = y_uk − a_k − c_{uR}`. Certification exigée :
`max_k |moyenne_{u:(u,k)∈Ω} e_uk| < 1e−8`,
`max_{u,R} |moyenne_{k∈R:(u,k)∈Ω} e_uk| < 1e−8` (par jour **et** par régime),
contraintes de centrage à `1e−8` ; en itératif, en plus,
`max |Δ(a_k + c_{uR})| < 1e−8` entre deux itérations. Centrage avec report
`a_k ← a_k + m_R` quand `c ← c − m_R`. Limite d'itérations atteinte :
`non-convergence`, aucune contribution à `F`. Publier un diagnostic de
conditionnement. **Cellule nulle** : une cellule de temps nul requise dans un
ajustement rend cet ajustement (pli et régime) indisponible, motif `temps nul` ;
jamais de suppression de la cellule ni de remplacement par un epsilon.
*(précision, M4b-3)* La résolution est itérative, par moyennes alternées :
`c_u = 0` au départ ; à chaque itération, `a_k` reçoit la moyenne des `y_uk − c_u`
sur les jours qui observent `k`, puis `c_u` la moyenne des `y_uk − a_k` sur les
segments de `u`, puis `c_u ← c_u − m` et `a_k ← a_k + m`, où `m` est la moyenne des
`c_u`. Les critères sont évalués après ce centrage : les moyennes de résidus, la
**somme** des `c_u`, et l'incrément des ajustés `a_k + c_u` des cellules d'une
itération à la suivante (d'où au moins deux itérations). La limite est de 10 000
itérations, la dernière comprise. La certification contrôle les équations normales
et la stabilité de l'itération ; elle ne garantit pas une erreur de `1e−8` sur les
paramètres ni sur les prévisions, qu'un plan mal relié peut amplifier. Une cellule
nulle de la composante ajustée rend l'ajustement indisponible, que le jour retiré
observe ou non son segment. Une prévision `exp(a_k)` non finie ou nulle donne
`erreur du modèle` pour le pli et la classe. Le diagnostic de conditionnement est
`μ₂`, la seconde valeur propre de `S = D_j^(−1/2) N D_s^(−1) Nᵀ D_j^(−1/2)` sur la
composante ajustée (`N` : incidence jours × segments des cellules ; `D_j`, `D_s` :
leurs degrés), `0` pour un seul jour : c'est le facteur asymptotique de contraction
de l'erreur des moyennes alternées, `0` pour un plan complet, proche de `1` pour
des jours mal reliés. Il ne dépend que du plan d'observation et vaut pour les onze
horloges ; il ne mesure pas l'incertitude de `F` et ne change aucun statut. Un
calcul de `μ₂` non certifié le publie indisponible (`non-convergence`), jamais `0`.

**D8.4 Scores.** `p_jk = exp(a_k)` sur l'intersection des supports ; `|L|`,
`|E_R|`, `D_R` du jour retiré. `F_q` = moyenne sur les **jours où la métrique `q`
est calculable**, avec son propre effectif `m_q`. `m_q ≤ 1` → `F_q` indisponible ;
`m = 2` avec support commun non vide → mention « un seul contraste » ; un régime vu
par le seul jour retiré → indisponible.
*(précision, M4b-3)* `S_j` est l'union des `S_jR` ; `P_j` la partie de `S_j` que
prévoient les ajustements disponibles (certifiés, de prévisions finies et non
nulles). `|L|` du jour retiré : `S_j` vide, `support insuffisant` ; total observé
nul sur `S_j`, `temps nul` ; `P_j ≠ S_j`, indisponible, avec le motif de la
première classe en échec dans l'ordre montée, plat, descente, mixte ; sinon `L` sur
`S_j` (D5.5). `E_R` et `D_R` : aucun segment de `R` dans `S_j`,
`support insuffisant` ; un temps nul du jour retiré sur `S_j`, `temps nul` pour
toutes les classes de `S_j`, quel que soit le sort des ajustements (D5.5) ; classe
en échec, son motif ; sinon sur ses segments. Une valeur de régime ne contribue à
`F` que si sa classe a au moins 3 segments dans `S_j` (D7.5, D10.2) ; les valeurs
des classes trop peu représentées restent publiées. `F_q` est la moyenne
arithmétique, à poids égal par jour, des `|L|`, des `|E_R|` et des `D_R`
contributifs ; `m_q ≤ 1` donne `support insuffisant` (moins de deux jours
contributifs), les causes par jour restant publiées. « Un seul contraste » :
exactement deux jours éligibles ont au moins une cellule en commun avec un autre
jour éligible.

**D8.5 Nom.** « Référence prédictive de répétabilité », pas « plancher ». Les
références de niveau contiennent la progression de la période ; on ne les remplace
pas par une version détendancée.

### D9 — Modèles de référence et calage (M4c)

**D9.1 Modèles.** v0 brut (effort 1) ; v0 + effort recalé (**comparateur**) ;
vitesse constante ; Naismith (5 km/h + 1 h par 600 m de D+) ; Tobler
(`v = 6·exp(−3,5·|g + 0,05|)` km/h). Les baselines sont intégrées sur la grille
fine : distance horizontale, D+ du profil lissé, `g` sans unité, vitesses
converties en m/s, temps fins sommés au prorata de longueur sur les segments de
score. La vitesse nominale de la vitesse constante (1 m/s) est absorbée par le
facteur.

**D9.2 Règle de calage unique.** Pour la performance évaluée `j` et chaque modèle
`M`, pour chaque performance `c` de la population effective `C_j^eff`, totaux
`T_c` et `P_c^M` sur le **support admis de `c`**, dans la **même horloge** et le
**même scénario** que le score évalué ;
`β = moyenne_{c ∈ C_j^eff} ln(T_c / P_c^M)`.
- Baselines : facteur de temps `a = exp(β) > 0`, sans borne ; prédiction `a · P^M`.
- v0 : effort `e = e_0 · exp(−β)` pour `P` calculé à `e_0 = 1`, **contraint à
  `[0,5 ; 1,5]`** (`0009`) — minimiseur sur l'intervalle de l'objectif, convexe
  **en log-effort** ; saturation déclarée.
- **Population effective** `C_j^eff` : performances de `C_j` dont le support admis,
  dans l'horloge et le scénario demandés, est non vide avec `T_c > 0`. Totaux
  sommés d'abord sur la performance, puis `β` moyenné sur les performances. Une
  sortie de modèle invalide sur ce support donne `erreur du modèle`, jamais un
  retrait discret de la performance. Retraits et `|C_j^eff|` publiés.
- `C_j^eff` vide : statut `non calé` (v0 brut reste scoré).
- Le jour évalué n'entre jamais dans son propre calage.

**D9.3 Effets candidats** (M6a+) : paramètres ou règle d'estimation appris sur
`C_j` seulement, même information que le comparateur.

### D10 — Admission exploratoire d'un effet (M4c)

**D10.1 Déclaration** (avant tout résultat, enregistrée en D14) : cible unique
`q ∈ {|E_R|, D_R pour R ∈ {montée, plat, descente}, q_usage}` (`|L|` n'est pas une
cible) ; horloge (écoulé pour l'effet arrêts) ; performances évaluables et
exclusions ; base `(0)` = **v0 + effort recalé** ; candidat `(1)` = base + effet,
paramètres ou règle d'estimation ; `K` et poids si `q_usage` ; sources des seuils
et valeurs de référence figées.

**D10.2 Gains.** `G_j = q_j^(0) − q_j^(1)`, même support, poids égal par
performance. L'évaluabilité se décide sur **l'observation seule** : une
performance est évaluable pour `q` si son support observé permet de calculer `q`
et, pour une cible de régime, si ce régime compte au moins 3 segments. Une
`erreur du modèle` de `(0)` ou de `(1)` sur une performance évaluable rend le
verdict « à revoir » ; elle n'exclut jamais la performance. Une performance
`jour multi-sorties` n'est pas évaluable. `n` = performances évaluables,
**égalités `G_j = 0` comprises** (non-succès). `n = 0` : aucune décision.

**D10.3 Seuils par performance.** `δ_j = max(0,010 ; 0,25·F_j)` où `F_j` est, pour
la métrique et l'horloge déclarées :
1. la **référence locale** du parcours de `j` (D8) si elle existe ;
2. sinon, si `j` est **comparable**, la **référence empruntée** `F_emp` = moyenne à
   poids égal par parcours des références **disponibles pour cette métrique, cette
   horloge et cette configuration**, figée dans la déclaration avec ses donneurs,
   supports et `m_q`, et étiquetée « empruntée » ;
3. sinon — ou si aucun donneur n'est disponible — `F_j` indisponible et
   `δ_j = 0,010` (seuil fixe).

L'ordre local → emprunté → fixe ne s'inverse jamais. **Comparable** :
entraînement, dans le domaine, durée projetée `≤ 4 h` — projection par `(0)`, dans
la version et le scénario fixés par la déclaration (par v0 brut si `(0)` est
`non calé`, pour cette seule classification), sur **toute la portion déclarée** de
la sortie, jamais sur les seuls segments admis —, et D+/km du profil (au sens de
D2.1) dans `[50 ; 110]` (références de 66 à 87, bande élargie d'un quart de chaque
côté). Frontières inclusives. Pour `q_usage` : `δ_j = 0,010` pour toutes les
performances. Seuil de l'expérience `δ̄ = moyenne_j δ_j`. **Candidat provisoire**
si `Ḡ ≥ δ̄`, `#{G_j > 0} ≥ ⌈3n/4⌉` et `G_j ≥ −δ_j` pour tout `j`.

**D10.4 Garde-fous** — liste figée : `|L|` ; `|E_R|` et `D_R` pour
`R ∈ {montée, plat, descente}`, hors la cible ; passages.
- Métrique `k` : `H_jk = (q_jk^(1) − q_jk^(0))_+`, `η_jk = max(0,005 ; 0,10·F_jk)`
  (même règle de source que D10.3, seuil fixe `0,005` à défaut). Ensemble `J_k` =
  performances évaluables pour la cible **et** soumises au garde-fou `k` selon
  l'observation ; conditions `moyenne_{j∈J_k} H_jk ≤ moyenne_{j∈J_k} η_jk` et
  `H_jk ≤ 2η_jk` pour tout `j ∈ J_k`. Jamais de zéro pour une performance hors de
  `J_k`. Un garde-fou exigé mais non calculable rend le verdict « à revoir ».
- Passages : pour tout **passage comparable** (D7.4),
  `(|P^(1)_jk − T_jk| − |P^(0)_jk − T_jk|)_+ / T_jk ≤ 0,01`.
- **Obligatoires** : `|L|` sur toute performance évaluable ; le garde-fou des
  passages sur toute performance évaluable ayant au moins un passage comparable.
  Indisponibles là où ils sont exigés, ou garde-fou des passages applicable sur
  **aucune** performance évaluable → verdict « à revoir ».
- Un garde-fou de régime est exigé sur les performances où ce régime compte au
  moins 3 segments ; évaluable nulle part, il est rapporté « non évaluable » sans
  bloquer.

**D10.5 Comparaisons publiées** : contre la base `(0)` (décision) et contre v0
brut (information). Un candidat qui **reproduit les prédictions du comparateur** a
un gain nul. Quand l'effort du comparateur est saturé, un gain peut venir d'un
simple recalage de niveau que la borne interdisait au comparateur : le verdict
porte alors la réserve « comparateur saturé ».

**D10.6 Verdict à trois états** : **candidat provisoire exploratoire** /
**rejeté** / **à revoir**. Tant que la sensibilité complète (D13) n'a pas tourné :
« centrale, sensibilité restante ». Jamais une preuve.

**D10.7 Figement pour confirmation.** Candidat, paramètres ou règle d'estimation,
cible, horloge, exclusions, seuils et date d'analyse sont figés **ensemble** dans
une déclaration versionnée du registre. Une performance n'entre en confirmation
que si `o_j` est postérieure à l'instant de cette déclaration et si toutes les
entrées de sa prévision étaient disponibles à `o_j` (D2.6).

### D11 — Fourchettes, expérimental (M4d)

- Résidu de jour `Z_c = ln(T_c / P_c)` du **modèle évalué**, pour `c` dans le
  réservoir (D2.4), la prévision `P_c` étant celle que le modèle aurait faite à
  `o_c` (calage D9 compris). Horloge : écoulé ; événements : départs (`0005`).
  `n` = résidus disponibles.
- Quantiles empiriques de rang `⌈nq⌉` (indexés à partir de 1). `n = 0` :
  indisponible ; `n = 1` : plage ponctuelle, aucune couverture revendiquée.
- `α = 0,20` : `[P_k e^{Q_0,1(Z)} ; P_k e^{Q_0,9(Z)}]` ; médiane `P_k e^{Q_0,5(Z)}`
  (inférieure centrale si `n` pair) = nouvelle prévision, comparée à v0, jamais
  substituée.
- Score `IS_0,20(l, u ; T) = (u − l) + 10 (l − T)_+ + 10 (T − u)_+` en secondes,
  largeur publiée ; par performance `IS_j = Σ_k w_jk IS_jk` et
  `IS_j,norm = Σ_k w_jk IS_jk / P_jk^(0)` (dénominateur fixé à l'origine ; jamais
  `T`) ; agrégat à poids égal par jour. Poids par défaut : ceux de D7.4.
- Couverture `Σ_k w_k 1{l_k ≤ T_k ≤ u_k}` et « tous couverts » ; passages requis
  manquants ou `K` vide → indisponible. Les 80 % sont marginaux par passage, pas
  une couverture simultanée.
- Étiquette obligatoire **« plage de scénarios — calibration non disponible »**
  tant qu'aucune calibration indépendante n'existe. Les prévisions datées sont
  conservées au registre (D14), pas seulement leurs erreurs recalculées.
- Option « prudente » : lecture du quantile 2/3, qui correspond à la préférence
  « sous-estimer coûte deux fois plus que surestimer » ; affichage déclaré, ni
  réglage du moteur, ni modification de `q_usage`.

### D12 — Diagnostic de longue course (M4d)

- Séquence des passages nommés du **préfixe comparable**, de `(t*_0, b_0)` au
  dernier, `H`, événements de D4.12. Une course interrompue est diagnostiquée
  jusqu'au dernier passage du préfixe effectivement obtenu — jamais « course
  entière ». Si le préfixe ne contient aucun passage nommé, le diagnostic est
  indisponible (`support insuffisant`).
- Intervalles `h` départ → départ (`0005`) : `t_h = D_h − D_{h−1}`,
  `p_h = P_h − P_{h−1}`, `y_h = ln(t_h / p_h)` (**+ = plus long que prévu**, signe
  opposé à `C`) ; erreur locale `(t_h − p_h)/60` min ; déplacement `A_h − D_{h−1}`
  et arrêt `D_h − A_h` publiés à part ; fractions de régime. Un intervalle de
  projection nulle n'est pas admissible ; un temps observé `t_h ≤ 0` rend le
  diagnostic concerné indisponible, motif `temps nul`, sans retrait silencieux.
- Cumul brut `C_k` ; recentré `B_k = T_k − c·P_k`, `c = T_H/P_H`, rétrospectif,
  `B_H = 0` par construction.
- Pente de dérive : `y_h = a + b·u_h + Σ_{R≠R_0} γ_R f_hR + e_h`,
  `u_h = (P_{h−1} + p_h/2)/P_H`, `f_hR = p_hR / p_h` (fraction du **temps
  projeté**, calculée sur la grille fine), `R_0` = régime de plus grand temps
  projeté total (égalités : ordre montée, plat, descente) ; poids égaux par
  intervalle. **Espace des nuisances** : `Z` = base indépendante de l'espace
  engendré par la constante et les fractions `f_R, R ≠ R_0` (décomposition en
  valeurs singulières, tolérance relative `1e−10`). `M_Z = I − Z (ZᵀZ)⁻¹ Zᵀ`,
  `b = (uᵀ M_Z y)/(uᵀ M_Z u)`. **Identification** :
  `ρ_u = uᵀ M_Z u / Σ_h (u_h − ū)² > 1e−10` ; aucun intervalle ou
  `Σ_h (u_h − ū)² = 0` → pente non identifiable, contrôle repris à chaque retrait ;
  publier `ρ_u`, `uᵀ M_Z u`, le rang de `Z` et le nombre d'intervalles. `u` et `f`
  viennent de v0 et restent fixes entre modèles et horloges comparés.
- Retraits : on retire une ligne en gardant les `u`, `f` initiaux, on reconstruit
  la base et on revérifie l'identification ; seuls les ajustements identifiables
  entrent dans l'étendue, leur nombre est publié ; aucun → étendue indisponible.
  Une course = une performance.

### D13 — Sensibilité (M4d, paramètres posés en M4a)

Configurations : `Δ ∈ {100, 250, 500}` × `ε ∈ {15, 30, 45}` en écoulé (9), plus
`(Δ, ε) = (250, 30)` sous les dix horloges de mouvement (10), soit 19 ;
`r_c = 15 m` fixe. **Chaque configuration est une exécution complète du
protocole** : courbe et intégration fines fixes ; supports, paramètres calés (D9)
et référence (D8) recalculés dans la configuration ; supports, effectifs, gains,
statuts, dommages et verdicts publiés par configuration. Rapportée, **jamais**
utilisée pour choisir. Réserve explicite si le signe de la moyenne **ou** de gains
individuels change. Distinguer changement de support et changement de score ; `D`
n'est pas normalisé par `Δ`. Avant M4d, une décision M4c porte l'étiquette
« centrale, sensibilité restante ».

### D14 — Registre des expériences (M4b)

Événements **ajoutés, jamais réécrits**, liés entre eux :
- `DÉCLARATION`, **avant** le calcul des résultats de l'expérience (les références
  peuvent être préparées avant) : identifiant, date, commit, version du protocole
  et de la configuration (Δ, ε, `r_c`, horloges), `curve_ref`, manifeste et
  identifiants des données, origines, modèles et paramètres ou règles
  d'estimation, effet, cible, horloge, `K` et poids, seuils et références figées
  avec leur source, performances et leur jeu, exclusions, **empreintes, instants
  de disponibilité et rôles des artefacts** (D2.6) ;
- `RÉSULTAT` : scores par performance, supports, couvertures, gains, dommages,
  verdict et motif, **références des prévisions conservées** (projection datée par
  performance et modèle, passages, paramètres) ; ou `ÉCHEC` : erreur technique ou
  non-évaluabilité, avec motif.

Les prévisions de v0 brut sont conservées dès M4b, celles des modèles calés dès
M4c. Une erreur se corrige par un nouvel événement lié. Toute exécution de
`just backtest` est enregistrée, effet testé ou non. Stocké sous `MPA_DATA_DIR` ;
résumé dans `docs/JOURNAL.md`. Sert au comptage des essais.
*(précision, M4b-4)* Le registre est un journal, une ligne par événement en écriture
canonique, et des documents nommés par leur empreinte `sha256` : observations, scores avec
leurs prévisions, références D8. Chaque événement porte un numéro, son rang dans le
journal à partir de 1, et l'empreinte de la ligne précédente ; un RÉSULTAT ou un ÉCHEC
nomme la DÉCLARATION à laquelle il répond. Une DÉCLARATION fige ses performances telles
que le manifeste les décrit (sorties, fichiers, empreintes, instants de disponibilité,
rôles, jeux, étiquettes), leurs origines, la courbe et les modèles ; pour une expérience,
aussi son scénario (D9.2, D10.3) et sa date d'analyse (D10.7). Un RÉSULTAT rend compte de
chaque sortie de ces performances : scorée, ou non scorée avec son motif ; ses prévisions
nomment un fichier déclaré de leur sortie (la référence en usage, la première trace en
contrôle), recopient la version et les paramètres fixés de la déclaration, et sa courbe
pour les modèles qui projettent avec elle.
*(précision, M4b-4)* Une correction est un événement neuf du même type, qui nomme
l'événement corrigé et son motif ; un événement est corrigé au plus une fois, et une
déclaration reçoit au plus une réponse qui n'en corrige pas une autre. Toute modification
d'une déclaration est une DÉCLARATION neuve. Chaque DÉCLARATION compte pour un essai,
corrections comprises : la règle ne peut que surestimer le nombre d'essais. Les essais se
comptent par effet et par cible ; les exécutions sans effet testé, à part.
*(précision, M4b-5)* `just backtest` déclare le commit du code qu'il exécute et refuse,
avant tout écrit, un arbre de travail dont des fichiers suivis sont modifiés ; en M4b, il
déclare v0 brut seul (effort 1, paramètres par défaut), les onze horloges et
l'appariement par défaut. Une exception, ou une interruption au clavier (Ctrl-C), pendant
le calcul qui sépare la DÉCLARATION du RÉSULTAT devient un ÉCHEC technique, au motif sans
chemin de fichier — une interruption hors du calcul, pendant l'ajout d'un événement au
registre ou à l'instant qui le suit, est celle d'un processus tué ; une exécution sans
performance dans le domaine, un ÉCHEC « non évaluable ». La référence D8 d'un parcours
nomme le fichier de référence déclaré de chaque sortie du jeu de répétabilité de ce
parcours, à chacun des jours de la référence, jours multi-sorties compris (même
empreinte), ce que le registre vérifie.
*(précision, M4b-5)* L'empreinte `sha256` de la dernière ligne du journal scelle le
registre : `just backtest` la publie à chaque exécution — sa synthèse et son rapport, ou
son message d'erreur quand l'exécution finit en ÉCHEC ou que le rapport ne s'écrit pas —,
et le résumé d'exécution du `JOURNAL` la recopie ; une réécriture ou une suppression des
dernières lignes se voit alors contre l'historique git. Un processus tué (fenêtre fermée,
coupure) n'enregistre rien de plus : entre la DÉCLARATION et le RÉSULTAT, il laisse la
DÉCLARATION sans réponse, qui compte pour un essai ; après le RÉSULTAT, un RÉSULTAT sans
rapport ; dans les deux cas, l'empreinte de la dernière ligne n'est publiée nulle part.

### D15 — Rapport de `just backtest`

Par performance : jeu et étiquettes ; couverture (D4.11) ; horloges — totaux de la
trace et du support admis, **séparés** ; événements aux passages et épisodes non
attribués ; pour chaque modèle (v0 brut, v0 + effort, trois baselines) : `L`,
`E_R`, `D_R`, `E_R − L`, identité `A / W / B / C_comp`, `C_k`, `q_usage` par
défaut ; référence `F` du parcours avec `m` et `m_q` ; statuts d'indisponibilité.
Agrégats à poids égal par performance, **par métrique sur son propre ensemble et
effectif**, et **séparés** par jeu (répétabilité « apprentissage »,
développement, confirmation) — jamais un agrégat principal qui les mélange.
Provenance : courbe, âge au jour `J` et à `o_j`, « mouvement historique non
harmonisé », biais d'opérateur de pente (`0009`, D6), courbe postérieure aux
origines M4. Le rapport s'enrichit par lot : M4b livre les rubriques calculables
avec v0 brut, M4c les modèles calés et l'admission, M4d fourchettes, dérive et
sensibilité ; une rubrique d'un lot futur est « non implémentée dans ce lot »,
jamais une erreur du modèle ni un échec de calage.
*(précision, M4b-5)* Le rapport se calcule pendant l'exécution, sur ses objets en mémoire :
le registre ne garde pas tout ce qu'il publie (totaux de la trace, événements aux passages,
épisodes non attribués, fractions fines de D6), et un rapport passé ne se régénère pas
depuis lui. Il s'écrit en entier dans `MPA_DATA_DIR/rapports/backtest-<n° du RÉSULTAT>.txt`,
jamais réécrit ; sa synthèse s'affiche : provenance, numéros et sceau du registre, sorties
écartées, une ligne par sortie déclarée, agrégats d'usage sous l'écoulé, et pour chaque
parcours de répétabilité ses `F` à côté de la moyenne de v0 sur ses jours (supports
différents : `F` pli par pli, v0 sur le support admis de chaque jour). Un agrégat est la
moyenne arithmétique, à poids égal par performance, d'une métrique sur son propre effectif,
séparée par jeu : biais signés (`L`, `E_R − L`) et valeurs absolues (`|L|`, `|E_R|`,
`D_R`, `A`, `W`, `B`, `C_comp`, `max |C_k|`, `q_usage`), en usage et en contrôle, sous
l'écoulé, `M` sous le `θ_bas` et `M + U` sous le `θ_haut` de chaque performance (D5.4). Une
valeur de régime n'y entre que si sa classe a au moins 3 segments (D7.5) ; une valeur
manquante est comptée par motif — statut de D0, classe trop peu représentée, sortie non
scorée, sans référence, `jour multi-sorties` ; une performance de plusieurs sorties compte
dans le jeu de chacune. La courbe postérieure aux origines est comptée (performances dont
l'origine `o_j` ne suit pas strictement son instant de disponibilité). La référence de
répétabilité se publie entière, causes d'un `|L|` de pli indisponible comprises (aucun
diagnostic neuf) ; une troisième horloge égale à l'écoulé, faute d'arrêt confirmé sur le
support, se signale d'une ligne.

### D16 — Découpage

| Lot | Contenu | Relecture de PR |
|---|---|---|
| M4a | contrats (sortie, sorties retenues, performance, passage, manifeste, provenance, origines, statuts), lecture de trace, horloges D5 ; grilles et bornes effectives, appariement D4.4–D4.11, passages et événements D4.12, correspondance usage / contrôle, totaux sur support admis, paramètres de sensibilité | profonde, une par PR |
| M4b | métriques D7 dont `C_k` et `q_usage` (dénominateur v0 brut), référence D8, schéma de déclaration et registre D14 avec prévisions de v0 brut, `just backtest` v0, rapport D15 | profonde |
| M4c | modèles et calage D9, gains, garde-fous, admission D10, prévisions des modèles calés | profonde |
| M4d | fourchettes D11, dérive D12, exécution complète de la sensibilité D13 | bornée, avec examen mathématique explicite |

Chaque lot ne consomme que des objets des lots précédents. M4a est livré en
**trois PR** : (1) contrats des sorties, manifeste, lecture de trace, horloges ;
(2) appariement ; (3) passages et événements. La géométrie horizontale du tracé source accompagne le
profil M2 dans les objets d'appariement (M4a) ; la règle d'étiquette historique
(D2.4) est posée dans les contrats de M4a, appliquée en M4c ; l'accès aux temps
fins et aux cumuls v0 aux abscisses exactes est livré en M4b (adaptateur du moteur
M3) ; *(précision)* le schéma de déclaration est livré avec le registre, en M4b,
son seul producteur et premier consommateur.

> **Note du 2026-09-24 (M4a-2a) — découpage.** L'appariement (2) est livré en
> deux PR : M4a-2a, points de score (D4.1 à D4.3, grille et bornes effectives
> des extrémités de D4.2, D4.5 à D4.9 pour les franchissements) ; M4a-2b,
> segments et couverture (bornes effectives dans les segments, D4.9 pour les
> segments, D4.10, D4.11, D6, totaux du support admis de D5.4, D3, D13). M4a est
> donc livré en quatre PR. Aucune règle ne change.

### D17 — Reporté, avec déclencheur

Voir les lignes `(M4…)`, `(M6a)` et `(M6b)` ajoutées au `BACKLOG.md` avec cette
décision. Les principales : modèle d'erreur hiérarchique et score prédictif
(≥ 20 jours hors échantillon, après M6b) ; test de confirmation d'un gain utile par
blocs indépendants, égalités comptées comme non-succès (≥ 10 performances
postérieures au figement) ; réexamen des seuils d'admission (critère
« comparable », référence empruntée) avant la première expérience déclarée ;
origine glissante et pondération temporelle (M6b) ; définition commune du
mouvement et même opérateur de pente à l'estimation et à l'application (M6b) ;
validation du détecteur d'arrêts ; effort de course sur courses seulement ;
agrégation des jours à plusieurs sorties au premier cas réel ; limites connues
listées ci-dessous (Conséquences).

## Pourquoi

**Des segments plutôt que des cumulés.** Un cumulé est une somme : une erreur au
kilomètre 3 se retrouve dans tous les cumulés suivants, et vingt passages ne font
pas vingt observations. Le segment de longueur fixe le long du préparé, retrouvé
sur la trace par le franchissement d'une normale, donne des observations presque
indépendantes, comparables d'un jour à l'autre et d'un parcours à l'autre, sans
saisie manuelle de points. Les cumulés restent la métrique d'**usage** (`q_usage`,
`C_k`), parce que c'est ce que le coureur lit en course.

**Le logarithme du rapport.** Il est symétrique (projeter deux fois trop long ou
deux fois trop court coûte pareil), il s'agrège exactement en temps — `L` est le
logarithme du rapport des totaux, donc exactement `ln` de l'effort qui aurait
collé (`e* = e^L` ; signe corrigé en M4b-5) —, et il se décompose : niveau `L`, biais de forme `E_R − L`, dispersion
`D_R`. L'erreur en % du total (B) confond niveau et forme ; l'erreur absolue des
cumulés (A) porte l'autocorrélation décrite plus haut. `A = W + B − C_comp` est une
identité descriptive, pas une décomposition causale ; `C_comp` est calculé par sa
formule pour qu'un test de l'identité ne soit pas tautologique.

**L'appariement.** Une recherche par plus proche point confond les lacets, les
aller-retour et les boucles ; le franchissement orienté d'une normale, cherché
dans l'ordre et dans une fenêtre qui s'élargit, ne peut pas remonter le temps. Le
regroupement des candidats dans un rayon de 15 m récupère les arrêts sur la ligne
(sans lui, le point d'arrêt de chaque sortie d'un parcours de répétabilité serait
ambigu) ; au-delà, deux événements restent ambigus plutôt que d'être départagés
par l'erreur d'un modèle. Les ancrages aux extrémités évitent de perdre un départ
ou une arrivée pour quelques mètres (6 sorties sur 7 du principal parcours de
répétabilité en ont besoin), et les bornes effectives évitent de fabriquer une
fausse répétabilité en comparant des cellules de longueurs différentes. `ρ` seul
accepte une autre portion de même longueur : le contrôle intérieur `H` la
refuse.

**Deux horloges.** L'écoulé est ce qui compte en course et ce qui est
chronométré ; le mouvement isole le modèle de déplacement, mais son détecteur n'est
pas validé. Cinq conventions encadrent l'incertitude de la détection ; le rapport
montre les deux conventions qui réalisent les extrêmes du total admis, jamais un
extrême segment par segment, qui ne correspondrait à aucune convention.

**Une référence prédictive, pas un plancher.** L'écart-type de répétitions ne dit
pas ce qu'un modèle parfait atteindrait ; un gabarit appris sur les autres jours et
évalué sur le jour retiré, si. Il contient la progression de la période ; il est
nommé pour ce qu'il est.

**Un calage unique et sans fuite.** Un calage sur tout le jeu contient le jour
évalué ; un modèle calé et l'autre non ne se comparent pas. Un paramètre d'échelle
par modèle, appris sur les entraînements terminés avant l'origine, donne la même
information à tous. Les courses en sont exclues : l'effort de course est un effet,
et une course dans le calage d'entraînements décale le facteur d'environ 3 %.

**Une règle exploratoire.** Avec quelques performances, aucun test n'a de
puissance ; une valeur p fabriquée serait pire qu'aucune. La règle d'admission
exige un gain d'amplitude au moins un quart de la référence de répétabilité, une
majorité des trois quarts, aucun gain négatif au-delà du seuil, et des dommages
bornés sur des garde-fous fixés d'avance ; elle produit un « candidat provisoire »,
confirmé plus tard sur des données postérieures au figement. Le seuil emprunté
n'est appliqué qu'à des sorties du même genre (entraînement, ≤ 4 h, profil
voisin) ; un seuil laxiste remplirait la file de confirmation d'effets de l'ordre
du bruit.

**Pourquoi pas plus simple.** Chaque règle écrite ici a été confrontée à des
contre-exemples chiffrés et aux traces réelles avant d'être figée ; les versions
plus simples (plus proche point, extrêmes segment par segment, calage sur tout le
jeu, garde-fous moyennés avec des zéros, préfixe prolongé à travers une portion
inconnue) produisaient chacune un résultat faux sur un cas précis.

## Conséquences

**Ce que ça rend facile.** Un effet (M6a) s'ajoute, se déclare, se mesure et reçoit
un verdict sans nouvelle décision de méthode. Tout score dit sur quoi il repose :
support, couverture, statuts, provenance, âge de la courbe. Les indisponibilités
sont visibles au lieu de devenir des zéros.

**Ce que ça rend difficile.** Le protocole est long à implémenter (quatre lots) et
chaque règle a ses cas limites. Les scores actuels sont **rétrospectifs** et, pour
la répétabilité, des scores d'**apprentissage** ; rien n'est confirmé.

**Limites connues, mesurées avant écriture** (conception, calcul indépendant du
protocole sur les traces réelles) :
- **Le préfixe comparable est souvent court.** Un point non daté ou un segment non
  admis l'arrête : lacets rendant ambigu un point de score, variante de quelques
  dizaines de mètres, détour de la trace de référence. `q_usage` complet et les
  garde-fous de passages n'existent aujourd'hui que sur une minorité de sorties ;
  le diagnostic de longue course de la seule course disponible est vide. Réexamen
  avant la première expérience ciblant `q_usage` ou un passage (M6a).
- **Les longs arrêts de course sortent du support.** Au ravitaillement, le chemin
  lissé cumule le bruit GPS et les déplacements, et le ravitaillement est souvent à
  l'écart du tracé : `ρ` et `H` excluent les segments qui portent les plus longs
  arrêts. Aucune sortie d'entraînement n'est touchée. Réexamen avant la première
  expérience de l'effet « arrêts » ou la première course évaluée.
- **Le détecteur d'arrêts est strict** : des arrêts de 30 à 50 s restent `U`, et
  rien ne le valide encore.

**Ce qu'il faudra revisiter, et quand** : les lignes du `BACKLOG.md` ajoutées avec
cette décision, chacune avec son déclencheur. Une modification du protocole après
la première déclaration d'expérience est une **nouvelle version**, valable pour les
expériences suivantes seulement. Le jour où le backtest montrera qu'une hypothèse
du modèle était fausse, la réponse est un nouveau decision record, pas un doute sur
la méthode.
