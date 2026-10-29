# 0017 — Estimation de la courbe personnelle

- **Date** : 2026-10-29
- **Statut** : acceptée (M6b-1)

## Contexte

Le moteur projette avec une courbe allure ↔ pente lue dans un fichier (`0009`). La
seule courbe d'aujourd'hui, la v0, a été estimée hors du dépôt par l'ancien projet, sur
d'autres points, une autre pente et un autre temps que ceux du moteur : `0009` D6 en
accepte le biais d'échelle et dit que « la vraie réponse appartient au M6b », qui
possède l'estimateur.

M6b est partagé : l'ingestion des données Garmin est à la piste analyse (AN1, AN2-0,
`0013`), qui écrit `interim/` ; l'estimation de la courbe est au moteur, qui lit
`interim/` par ses vues, jamais `processed/`. Une règle gouverne tout ce qui suit : **la
courbe se mesure comme le moteur l'applique** — même grille du profil (`build_profile`,
`0008`), même pente (l'altitude lissée du profil), même distance (la haversine des
positions brutes, `d_r` de `0010` D4.4), même horloge de mouvement (`M` sous la
convention centrale θc, `0010` D5) ; et pour lire une courbe estimée, la règle de
support de `read_curve` et l'allure du moteur (`PaceModel`), jamais une copie.

## Options envisagées

**L'unité d'observation.** Les points successifs de la source (l'ancien projet), dont la
pente n'est pas celle du moteur ; ou les intervalles de la grille du profil du moteur,
qui portent la pente que le moteur appliquera.

**Le temps.** Le temps en mouvement `M` ; `M + U`, qui garde les trous ; ou l'écoulé, qui
garde les arrêts et mélange la vitesse de marche et celle des pauses.

**La valeur d'une tranche.** (a) la somme des longueurs sur la somme des temps M, qui
pèse par le temps ; (b) la médiane des vitesses des activités, qui pèse par activité ;
(c) une moyenne tronquée ; ou un modèle à effet de sortie (`ln v = a_j + f_k`).

**Les tranches.** Des pas réguliers de 5 %, de 2,5 % ou de 10 %, ou des tranches
variables, fines là où les données sont denses ; centrées sur leur milieu nominal ou sur
la pente moyenne de leurs observations.

**La dispersion.** L'étalement des vitesses des intervalles de 50 m, ou une vitesse par
sortie, séparée en un niveau (la sortie entière) et une forme (une tranche contre les
autres).

**La FC.** Un filtre par activité (sa FC moyenne) ou par intervalle ; un retard fixe ou
estimé par sortie.

**La provenance.** Tout dans le contrat `CurveProvenance`, ou le contrat pour ce que
`read_curve` relit et un compagnon pour le reste.

**Le temps long.** Une courbe par fenêtre de dates déclarée, ou une origine glissante qui
pondère les sorties récentes.

## Décision

Les règles ci-dessous, numérotées comme dans le code (« `0017`, P2.4 »).

**P1 — l'intervalle et ses temps.**

- **P1.1 — la trace et les refus.** La trace est celle du moteur, tirée de
  l'enregistrement (`trace_view`, commune au moteur et à la piste analyse) : la vue
  positions et altitude, ses instants depuis le premier. Sans elle (pas de positions,
  pas d'altitude, moins de deux instants), l'activité est écartée « sans trace » ; un
  profil impossible (aucune longueur : deux positions identiques) est un motif compté,
  « profil impossible », jamais une exception.
- **P1.2 — abscisses et intervalles.** Le profil du moteur se construit sur les
  positions et altitudes **brutes** de la trace, aux défauts de `0008` ; ses intervalles
  sont ceux de sa grille, le dernier plus court. Une position répétée ne change rien.
- **P1.3 — les bornes.** L'instant d'une abscisse de la grille est lu sur la distance
  réalisée `d_r` : le premier enregistrement d'abscisse strictement supérieure et son
  prédécesseur, entre lesquels l'instant s'interpole ; à abscisse égale (un arrêt),
  c'est le **dernier** instant qui compte, et un arrêt revient à l'intervalle où la
  distance s'arrête. La **première borne est le premier instant** de la trace, la
  dernière le dernier : les intervalles pavent toute la trace, une attente au départ
  comprise.
- **P1.4 — les temps.** Chaque intervalle a ses temps M, S, U sous θc, lus sur les
  horloges cumulées de `0010` D5.3, interpolées entre deux instants. Sa **longueur
  entière** compte, les trous gardés, dans U, sans traitement.
- **P1.5 — ce qu'un intervalle apporte à la courbe en mouvement.** Sa longueur et son
  temps M s'il a du temps M ; un intervalle sans temps M ne porte que des arrêts ou des
  trous. La vitesse en mouvement `ℓ / M` n'est jamais un motif d'écart : un temps M très
  court sur une longue distance n'est pas un intervalle aberrant, et son écart de
  vitesse se voit au fichier (P3.7).
- **P1.6 — la vitesse écoulée et le rapport.** Par tranche, une vitesse écoulée, sur
  tous ses intervalles retenus, ceux sans temps M compris ; et le rapport écoulé / M de
  la courbe, sur tous les intervalles retenus. Deux numérateurs de longueur sont
  publiés, celui des intervalles de temps M positif et celui de tous. Le rapport est un
  descriptif du corpus, jamais un facteur de conversion.

**P2 — les activités.**

- **P2.1 — types.** Par défaut `trail_running` seul ; une liste de types vide est
  refusée, jamais « aucun filtre ».
- **P2.2 — fenêtre.** Une fenêtre de dates déclarée, bornes comprises, sur le jour civil
  local du départ que dit l'index (`0013`, précision 3) ; il peut différer du jour à
  Paris de `0010` (D0, D2.2) pour une sortie enregistrée sous un autre fuseau.
- **P2.3 — durée.** Une durée minimale (comprise) et une durée maximale (exclue), sur
  l'écoulé de la trace, plafond ignoré.
- **P2.4 — plafond.** Un plafond depuis le départ, aucun par défaut : il **coupe**
  l'intervalle qui le traverse (sa longueur jusqu'à la distance réalisée au plafond, sa
  fin au plafond, sa pente celle de l'intervalle du profil) et retire ceux qui
  commencent au plafond ou après, comptés. La FC décalée d'un intervalle coupé se lit
  sur sa partie gardée, et peut donc venir d'après le plafond. L'estimateur refuse des
  intervalles coupés à un autre plafond que celui de la sélection.
- **P2.5 — courses.** Les courses sont gardées : l'index ne les distingue pas.
- **P2.6 — comptes.** Des comptes par étage — candidates, avec intervalles, éligibles,
  retenues, en mouvement, de la médiane, avec un niveau ; intervalles de la grille,
  coupés, retenus, retenus sans temps M ; longueurs, temps et écoulés retenus ; écarts
  par motif, avec leur longueur. Un intervalle n'est écarté qu'une fois, au premier
  motif.

**P3 — les tranches.**

- **P3.1 — bornes.** Des tranches variables, en pour mille de pente entiers : 10 % de
  −100 à −40 %, 5 % de −40 à −15 %, 2,5 % de −15 à +35 %, 5 % de +35 à +40 %, 10 % de +40
  à +100 % (38 tranches). Une tranche est `[lo ; hi[` ; +100 % est hors du domaine.
- **P3.2 — centres.** Les centres nominaux `(lo + hi) / 2`, écrits exactement.
- **P3.3 — (a).** Le défaut : somme des longueurs sur somme des temps M, sur les
  cellules (une activité dans une tranche) de temps M positif ; `sample_count` est le
  nombre de ces activités, `time_min` leur temps M. Une tranche sans temps M n'existe
  pas.
- **P3.4 — (b).** En option : la médiane des vitesses des activités qui ont au moins
  60 s de temps M dans la tranche ; pour un nombre pair, la moyenne des deux vitesses du
  milieu.
- **P3.5 — comptes de la tranche.** Avec (b), le temps et le nombre d'activités qui
  portent la valeur sont ceux des seules activités de la médiane ; les diagnostics
  (temps M de toutes les cellules, longueurs, écoulé, concentration des poids `n_eff`,
  plus grande part d'une activité, pente moyenne) vont au compagnon.
- **P3.6 — valeurs aberrantes.** Un intervalle est écarté, et compté, pour une pente
  hors domaine, un écoulé nul, ou une vitesse hors d'échelle : une vitesse écoulée de
  plus de 25 km/h, une vitesse verticale (signée) de plus de 2 500 m/h en montée ou de
  plus de 5 000 m/h en descente ; les seuils atteints sont gardés. Ces garde-fous ne
  sont ni un détecteur de véhicule ni une preuve de marche.
- **P3.7 — le fichier.** Une ligne que `read_curve` refuserait n'est **pas écrite** :
  rien n'est écrit, et l'erreur dit la tranche. Un support impossible (`0009` D2), lui,
  s'écrit et se dit : la courbe est non projetable, sans niveau ni forme.

**P4 — la dispersion.**

- **P4.1 — niveau.** Par activité, `λ = ln(T / P)` : son temps M contre le temps que le
  moteur prévoit sur la courbe estimée (`PaceModel`, prolongement compris), sur ses
  seuls intervalles de temps M positif. Un **diagnostic d'ajustement, en échantillon** :
  la courbe contient l'activité. Absent si la courbe n'est pas projetable — jamais
  `λ = 0`.
- **P4.2 — quantiles.** p10, p50, p90 du niveau et leur nombre, au compagnon, par la
  règle de rang de `0010` D11 (rang `⌈n·a/b⌉`) : `n = 0` absent, `n = 1` ponctuel, p50
  la médiane inférieure.
- **P4.3 — forme.** Par tranche, l'écart interquartile de `ln(P_jk / M_jk) + λ_j`, la
  forme lue contre le temps **prévu par le moteur** sur la cellule (jamais
  `ln(v_jk / v_k)`, qui confond la forme avec la répartition des pentes dans la
  tranche), sur les cellules d'au moins 120 s de temps M ; rien sous 5 activités.
- **P4.4 — unité.** Le niveau et la forme sont des logarithmes, sans unité : la forme
  s'écrit telle quelle, jamais comme `dispersion_ms`.

**P5 — la FC.**

- **P5.1 — FC d'un intervalle.** La moyenne de la FC sur la fenêtre de l'intervalle
  décalée de 60 s (0 permis), dans le temps de la trace : l'intégrale **exacte** de la FC
  interpolée sur les pas reliés (10 s au plus), un pas coupé par la fenêtre comptant
  pour sa partie dedans, divisée par la durée couverte ; indéfinie sous 80 % de
  couverture.
- **P5.2 — sélection.** Un filtre par intervalle, bande fermée de 10 bpm, aux pentes de
  −5 % ou plus seulement ; les descentes plus raides sont gardées sans filtre :
  « observations de descente non filtrées ».
- **P5.3 — courbe filtrée.** Les comptes disent les retenues qui ont un intervalle
  filtré et celles qui n'ont que des descentes. Sans centre, aucun filtre.
- **P5.4 — provenance.** Centre, largeur et décalage dans le compagnon, seulement avec
  un filtre ; la méthode identifiable (`method`, l'intégration de la FC, le pas relié
  maximal, la convention d'horloge).

**Le fichier.** Le CSV de l'ancien projet, étendu par trois colonnes (`kmh_elapsed`,
`activities`, `shape_iqr`) que `read_curve` lit comme l'ancien : dans l'en-tête étendu,
`sample_count` est le nombre d'activités, `hr` et `shape_iqr` peuvent être vides.
`CurveProvenance` gagne l'athlète, la durée maximale, le plafond et le décalage de FC ;
le compagnon porte en plus, sous `estimation`, ce que `read_curve` ignore : la méthode,
les paramètres, le niveau, les écarts, les comptes, les diagnostics des tranches et les
exports lus — par leur instant d'acquisition, ceux des entrées **et** ceux des
enregistrements (`0013`, précision 16). Une courbe n'est jamais réécrite ; le compagnon
s'écrit avant le CSV et s'efface si le CSV échoue.

**La commande.** `mperf curve <nom> --from --to --athlete` (et `just curve`), lancée par
l'humain : les durées en minutes à la ligne de commande ; un arbre modifié refusé (la
courbe dit le commit qui l'a estimée) ; une courbe existante refusée avant toute
lecture ; `MPA_DATA_DIR/reference/<nom>.csv` et son compagnon.

**Ce que les sorties ne sont pas.** Le niveau est un diagnostic d'ajustement en
échantillon ; `n_eff` mesure la concentration des poids, pas un nombre de jours
indépendants ; écoulé / M n'est pas un facteur de conversion ; les garde-fous ne sont ni
un détecteur de véhicule ni une preuve de marche ; une courbe filtrée par la FC est une
sélection descriptive (« observations de descente non filtrées »), pas l'effet d'une
consigne de FC.

## Pourquoi

**Le même opérateur que le moteur.** Mesurée sur la grille, la pente et l'horloge que le
moteur applique, la courbe ne porte plus le biais d'échelle de `0009` D6 : c'est la
raison d'être de M6b.

**(a) plutôt que (b).** L'avantage brut de (b), mesuré hors du dépôt au cadrage et à la
passe experte de M6b, est un **niveau** — un décalage d'ensemble —, que le comparateur
recalé du backtest absorbe, et qui ne tient pas à origine passée. (a) pèse chaque
seconde de mouvement également, ne demande aucun seuil par activité, et reste le défaut ;
(b) est une option. Un modèle à effet de sortie, non régularisé, échoue : rejeté comme
défaut, pas comme famille. Ni lissage ni monotonie ne sont imposés : la courbe dit ce
que les données disent.

**Les tranches variables.** Fines de −15 à +35 %, la plage des pentes courantes en
trail, larges aux extrêmes, où une tranche étroite réunirait trop peu de temps ; des
bornes entières pour que les centres s'écrivent exactement.

**La dispersion en niveau et forme.** Le bruit d'un intervalle à l'autre se compense le
long d'un parcours ; le niveau du jour, non. Séparer le niveau d'une sortie de sa forme
dit ce qui compte pour des fourchettes, et la forme se lit contre le temps prévu par le
moteur pour ne pas confondre la forme avec la répartition des pentes dans une tranche.

**Le plafond qui coupe.** Une sortie plafonnée doit ne rien apporter d'après le plafond :
garder entier l'intervalle qui le traverse et publier le dépassement aurait mêlé les deux
(choix de rdw).

**La FC exacte.** Couper un pas au prorata de ses deux échantillons biaise la moyenne
d'une fenêtre qui commence ou finit dans une rampe ; l'intégrale exacte de la FC
interpolée, non. Aucun chiffre tiré des données réelles n'est cité ici (règle 1) : tout
ce qui fonde ces choix a été mesuré hors du dépôt, au cadrage et à la passe experte de
M6b.

## Conséquences

**Ce que ça rend facile.** Une courbe par fenêtre et par filtre, avec sa provenance
complète ; la comparaison de la v0 et de la courbe neuve par deux `just backtest`, sans
toucher au moteur.

**Ce que ça rend difficile.** Le support peut ne pas exister (une fenêtre courte, un
plafond bas) : la courbe s'écrit, non projetable, et ne sert pas au moteur tant que le
critère de support reste celui de `0009`.

**Ce qu'il faudra revisiter.**

- La vitesse selon la durée de la sortie (M6a) : les sorties longues sont plus lentes à
  pente égale.
- L'origine glissante, au lieu d'une fenêtre déclarée.
- Les vecteurs conjoints par sortie et par régime pour M8 ; ne jamais ajouter le niveau
  de la courbe aux `Z_c` de `0010` D11 (double compte).
- Le critère de support (`0009`), maintenant que le fichier porte le nombre d'activités
  et la forme de chaque tranche.
- Le refus, par le backtest, d'une courbe d'un autre athlète que celui du manifeste.
