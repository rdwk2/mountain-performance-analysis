# Charte de la piste analyse

*Version 2, validée le 2026-10-08 après une relecture experte indépendante ; § 2 mis à
jour le 2026-10-09 (source des séries d'activité). Sources : `docs/PIEGES_DATA.md`,
`docs/analyse/QUESTIONS.md` et les decision records du dépôt. Sans chiffre tiré des
données.*

*Ce que la charte fixe : comment la piste produit un résultat auquel on peut se fier.
Ce qu'elle ne fixe pas : la méthode de chaque question, qui vient dans son plan
d'analyse, relu, et qui doit respecter la charte.*

## 1. Les quatre principes

1. **Pour tout athlète.** Le code ne suppose rien de propre à un athlète ni à sa
   montre. Tout seuil personnel (FC max, zones, « grosse sortie », normales) se
   calcule depuis les données de l'athlète, selon les règles du § 3, ou se déclare
   dans sa configuration. Un athlète = un `MPA_DATA_DIR` (0001).
2. **Permanent.** Une question livre un outil durable, pas un rapport unique : une
   commande `mperf` ou une page du tableau de bord, qui se recalcule depuis `raw/` à
   chaque mise à jour des données. Tout résultat porte la période de données et
   l'empreinte des données qui l'ont produit.
3. **La mesure avant l'interprétation.** Toute estimation vient avec son incertitude.
   Toute prévision et tout modèle viennent avec leur **base à battre** : une référence
   naïve (« demain comme aujourd'hui », la moyenne des derniers jours), que le modèle
   doit faire mieux que prévoir pour servir à quelque chose — comme Naismith et Tobler
   pour le moteur au M4 (principe 3 de la ROADMAP). Un graphique descriptif n'en a pas
   besoin.
4. **Aucune donnée personnelle dans le dépôt** (règle 1) : ni sortie de notebook, ni
   figure, ni fixture tirée de vraies données, ni chiffre dans un brief destiné à
   l'agent de code ou une description de PR.

## 2. Les données : du brut aux tables

| Étage | Contenu | Écrit par | Dépendances |
|---|---|---|---|
| `raw/` | l'export Garmin, immuable (fichiers en lecture seule), et les sources extérieures (§ 12) | l'acquisition, et l'athlète | — |
| `interim/` | les contrats normalisés (activités, séries, nuits, jours), avec leurs `QualityFlag` | l'ingestion, dans `src/mountain_perf/ingest/` | **aucune** pour le lire ; l'écriture depuis les FIT demande l'extra `ingest` ; format décrit dans `docs/decisions/0013`, relu par le moteur avant fusion |
| `processed/` | les tables d'analyse : `jours`, `activités`, `montées` (plus tard `descentes`, `plats`) | le code d'analyse | l'extra `analyse` (`docs/decisions/0011`) |
| `resultats/` | les sorties de chaque question, datées (§ 10) | les commandes d'analyse | idem |

- **Le moteur ne lit jamais `processed/`** ; il lit `interim/` par les contrats
  (`docs/decisions/0013`).
- Tout est régénérable depuis `raw/` par une commande : supprimer `interim/` et
  `processed/` ne perd rien.
- **Distance et profil** : par les fonctions du moteur (`gpx/geo.py`,
  `gpx/profile.py`), jamais réimplémentées. Une montée est un segment du profil du
  moteur.
- **Source des séries d'activité** : les séries d'une activité (positions, altitude,
  temps, FC) viennent du FIT, à pleine résolution, lu par fitdecode
  (`docs/decisions/0011` et `0013`). `activity_details` suffit pour le D+ et
  la VAM, pas pour la distance horizontale en montagne (`docs/PIEGES_DATA.md`) ; s'il
  sert, il se relit par `metricDescriptors` à chaque fichier.
- **Validité par régime.** Une mesure n'entre dans une question que validée dans le
  régime où elle sert. Une mesure tirée d'`activity_details` se compare aux FIT sur un
  échantillon de chaque régime, avec l'écart rapporté. Sur un export réel, en plaine
  comme en montagne : D+ et VAM équivalents ; distance horizontale non équivalente en
  montagne.
- **Définition robuste de la montée.** La VAM d'une même montée peut changer nettement
  selon qu'un petit replat la coupe ou non : la définition (hystérésis, fusion des
  replats) se fige dans le brief d'AN1, avec un contrôle de stabilité.
- **Durée minimale relative au pas.** Une montée n'est retenue que si sa durée dépasse
  30 fois le pas d'échantillonnage de son fichier (erreur de durée sous ~3 %). Le pas
  est une colonne de la table `montées`.
- **Pièges** : `docs/PIEGES_DATA.md`.

## 3. Configuration, seuils et notes de l'athlète

**Trois fichiers tenus à la main sous `MPA_DATA_DIR`**, lus par la bibliothèque,
jamais écrits par elle (sauf l'ajout de lignes neuves aux notes de sorties par la
commande de préremplissage) :

- **`athlete.toml`** : ce que les données ne disent pas, ou ce que l'athlète veut
  fixer (identifiant, fuseau de référence, FC max déclarée, sports pris en compte).
  Toute valeur absente se calcule depuis les données, avec sa méthode écrite.
- **`journal.csv`** : les événements que Garmin ne contient pas. Une ligne par
  événement : `debut`, `fin`, `type` (`maladie`, `blessure`, `course`, `deplacement`,
  `sejour_altitude`, `etalon`, `autre`), `note`. Chaque question dit quels types elle
  exclut ou contrôle. Les jours `maladie` et `blessure` sont exclus par défaut des
  normales et des relations ; un plan peut faire autrement s'il le dit, et un plan
  dont le facteur est la charge rapporte l'estimation avec et sans ces jours, et
  regarde la maladie aussi comme une issue (§ 5).
- **Les notes de sorties** (facultatives) : une ligne par sortie, pour ce que Garmin
  ne mesure pas (l'export n'a ni effort perçu ni ressenti) : intention (`facile`,
  `endurance`, `seance`, `course`), décidée la veille ou le jour même, capteur de FC
  (poignet ou ceinture), sac (`leger`, `lourd`). **Facile et rapide à remplir** : un
  classeur Excel prérempli par une commande avec les sorties de l'export (date, type,
  distance), où l'athlète choisit dans des listes déroulantes ; un formulaire du
  tableau de bord pourra le remplacer plus tard. La bibliothèque le lit, ne l'écrit
  jamais ; seule la commande de préremplissage y ajoute des lignes neuves, sans
  toucher aux lignes remplies. Chaque mois noté est un mois où ces confusions
  deviennent mesurables.

**Les grandeurs calculées depuis les données** :
- **Seuils** : un seuil calculé (« grosse sortie », pente minimale d'une montée…) se
  fige par version du plan : méthode, période de calcul et valeur écrites dans le
  résultat. Le recalculer fait une nouvelle version. En prévision, il se calcule à
  date (§ 7). Une lecture promue fige les siens à sa déclaration (§ 8).
- **FC max estimée** : par un estimateur robuste écrit (haut quantile d'une FC tenue
  une à deux minutes, après filtrage des artefacts), jamais le maximum observé. Une
  série en zones se recalcule tout entière avec la même valeur.
- **Normales** : une couverture minimale de nuits présentes sur la fenêtre, sinon
  valeur absente.
- **Capacités** : le code vérifie ce que la montre de l'athlète mesure (baromètre, FC,
  HRV nocturne) et n'ouvre pas une question qui en a besoin sans cette mesure.

## 4. Les unités d'observation

| Unité | Définition |
|---|---|
| **le jour** | la journée Garmin ; **la nuit appartient au jour du réveil**. « Décalage 1 » = la nuit qui suit le jour de la sortie, c'est-à-dire la nuit rattachée au jour suivant (un test synthétique le vérifie) |
| **la sortie** | une activité ; une journée à plusieurs sorties se traite comme le dit le plan |
| **la montée** (puis descente, plat) | un segment du profil du moteur au-dessus d'une pente et d'une durée minimales (§ 2) |
| **l'événement** | une « grosse sortie », une maladie… suivi sur une fenêtre fixée d'avance. La normale de référence se calcule sur une fenêtre close avant l'événement, hors jours d'événement. La réponse se compare à des jours témoins sans événement, appariés (jour de la semaine, saison, charge des jours précédents). La durée de retour se lit sur la courbe de réponse moyenne, estimée nuit par nuit avec une bande simultanée : la première nuit où la bande tient dans ± le plus petit écart utile. Jamais la moyenne des premiers franchissements de seuil |

Un plan d'analyse nomme toujours son unité, et donne l'effectif en unités
indépendantes, pas en lignes.

## 4 bis. L'inférence sous dépendance (règles communes à tous les plans)

1. **L'effectif est celui du niveau où varie le facteur.** Un facteur qui varie entre
   sorties (date, nuit d'avant, chaleur du jour) se juge sur les sorties : on résume
   d'abord chaque sortie (effet de sortie d'un modèle des montées, avec les
   covariables de la montée), puis on analyse la série des sorties. Un facteur qui
   varie dans la sortie (pente, place dans la sortie) se juge par un modèle mixte à
   effet aléatoire de sortie **et pente aléatoire pour ce facteur**, ajusté par REML.
2. **Erreurs groupées.** Jamais avec la loi normale. Correction CR2 et degrés de
   liberté de Bell-McCaffrey, ou bootstrap sauvage par grappes (poids de Webb sous 12
   grappes). Sous 10 grappes, on n'en fait pas : on agrège.
3. **Dépendance entre sorties.** Le plan rapporte l'autocorrélation des résidus au
   niveau de la sortie, en fonction de l'écart en jours. Si elle n'est pas
   négligeable, il la modélise (corrélation exponentielle en jours). Sous une
   quarantaine de sorties, l'intervalle reste optimiste, et il est affiché comme tel.
4. **Série journalière.** Variance EWC (cosinus à poids égaux) et loi de Student à B
   degrés de liberté, avec B = min(⌈0,4·T^(2/3)⌉ ; ⌊T/(3w)⌋). T = nombre de jours du
   calendrier ; w = la plus longue fenêtre de la relation, facteur ou mesure, en jours
   (pour une moyenne exponentielle de constante τ, w = 2τ). Si B < 3, la relation
   n'est pas estimable sur la période : on la décrit, sans intervalle. Newey-West avec
   le nombre de retards par défaut d'une bibliothèque est exclu.
5. **Bootstrap par blocs.** Seulement avec au moins vingt blocs (T/ℓ ≥ 20) et ℓ ≥ w ;
   ℓ choisi par la règle de Politis-White, arrondi au multiple de 7 jours supérieur,
   écrit dans le plan. Sinon, EWC.
6. **Contrôle par décalage.** Une relation entre deux séries journalières se compare à
   la même relation avec le facteur décalé circulairement (décalages d'au moins 2w).
   Un effet qui ne s'en distingue pas se lit comme une dérive commune.
7. **Calendrier complet.** Les séries journalières vivent sur tous les jours du
   calendrier, jours manquants compris (contribution nulle au score), jamais sur les
   seules lignes présentes : sinon retards, blocs et cosinus sont faux.

## 5. Les facteurs de confusion à traiter partout

Chaque plan les reprend un par un et dit, pour chacun, s'il l'ajuste, le stratifie,
l'exclut, ou pourquoi il l'ignore. Un petit schéma causal accompagne chaque plan ; il
distingue **ce qui confond** (à ajuster) de **ce qui transmet** (à ne pas ajuster pour
un effet total : la FC dans Q1, la température du capteur dans Q10, la maladie dans Q5
à Q7), et dit, pour chaque flèche à bloquer, par quelle variable et avec quelle
qualité de mesure.

- **Saison, région, terrain** : le terrain pratiqué peut changer avec la saison. On
  compare dans un même régime (Q1 : montées longues, côtes courtes, ski). C'est
  nécessaire, pas suffisant : dans un régime, la date reste liée à la chaleur, à
  l'altitude des itinéraires, au sol.
- **Le plan de mesure avant l'ajustement.** Un plan qui juge une progression utilise
  d'abord les parcours répétés (effet fixe de parcours), puis le reste. Sans parcours
  répétés couvrant deux saisons, une progression entre saisons n'est pas estimable, et
  le plan le dit. Un **parcours étalon**, refait à intervalles réguliers en toute
  saison, est la mesure la plus propre. L'athlète le choisit, de préférence parmi ses
  parcours les plus répétés et praticables en toute saison. Ses passages se
  reconnaissent **automatiquement**, par l'appariement du moteur contre un GPX de
  référence rangé dans `MPA_DATA_DIR/routes/`, sans saisie à la main ; le type
  `etalon` du journal ne sert qu'aux parcours que l'appariement ne reconnaît pas.
- **Altitude** : de la montée, et du sommeil (déduit des activités voisines, ou
  déclaré au journal).
- **Chaleur** : par une température de l'air au lieu et à l'altitude de l'effort (§
  12).
- **Heure de début** : elle porte la chaleur du jour et la distance au sommeil.
- **Charge récente** : charges aiguë et chronique recalculées depuis les activités,
  par une méthode écrite. **Pas de rapport couplé** : elles entrent séparément, ou la
  chronique exclut la fenêtre aiguë.
- **Maladie, blessure, déplacements** : par le journal (§ 3).
- **Firmware** : pour toute mesure calculée par la montre (§ 11).
- **Intention de la sortie** : par les notes de sorties (§ 3) si l'athlète les tient ;
  sinon le plan propose comment l'approcher (FC moyenne, durée, étiquette Garmin).
- **L'athlète réagit à ses données.** Le schéma causal dit si l'athlète voyait le
  facteur avant de choisir la sortie (sa nuit, sa HRV, sa Training Readiness). Pour Q8
  et Q9, le plan analyse d'abord les sorties décidées avant la nuit (courses, sorties
  prévues, notées au journal ou dans les notes de sorties), ou dit pourquoi il ne le
  peut pas.
- **Effet direct ou total.** Quand le facteur se répète dans le temps (la charge), le
  plan dit s'il estime l'effet direct (retards multiples) ou total (projection
  locale).

## 5 bis. Les manques

Un manque n'est jamais ignoré en silence. Chaque plan rapporte un diagramme de flux :
unités prévues, présentes, exclues, par motif. Il rapporte la part de manques selon le
niveau du facteur (par exemple nuits manquantes après une grosse sortie et après un
jour ordinaire). Si elle en dépend, les cas complets ne suffisent pas : le plan ajoute
une analyse de sensibilité (bornes, ou imputation sous hypothèse écrite). Une série
qui ne couvre qu'une partie de la période restreint la question à cette partie, qui
est aussi une saison.

## 6. L'incertitude et le nombre d'essais

- **On estime, on ne fait pas que tester.** Tout résultat se donne comme une
  estimation avec un intervalle (95 % par défaut). Une p-valeur seule n'est jamais un
  résultat. Les mesures multiplicatives (VAM, durées) s'analysent en échelle log :
  effets en log-rapport, affichés en pour cent.
- **L'effet qui compterait, et ce qu'on peut voir.** Chaque plan déclare d'avance le
  plus petit effet utile. Son calcul de puissance se fait **par simulation sur le plan
  réel** : dates réelles des unités, valeurs réelles du facteur et des covariables,
  estimateur et méthode d'intervalle du plan ; seuls la mesure (simulée) et l'effet
  (imposé) changent. La variance résiduelle vient d'une source qui ne regarde pas
  l'effet : la référence de répétabilité du moteur (D8), ou les résidus d'un modèle
  sans le facteur. Le plan rapporte le plus petit effet visible à 80 %, et, pour le
  plus petit effet utile, la puissance et le facteur d'exagération d'un résultat qui
  ressortirait (erreur de type M). Jamais de puissance « observée ».
- **Trois lectures.** Effet établi : l'intervalle exclut zéro. Absence d'effet utile :
  l'intervalle tient tout entier dans ± le plus petit effet utile (équivalence).
  Sinon : non tranché. « Rien de visible » n'est pas « pas d'effet ».
- **Pour tout athlète.** Le calcul de puissance tourne sur les données de chaque
  athlète. Une page du tableau de bord dont l'effet utile n'est pas visible avec ses
  données le dit (« données insuffisantes pour juger un effet de x % »).
- **Les essais se comptent**, comme au registre du moteur (D14) : chaque plan liste
  ses comparaisons (mesures × décalages × sous-groupes). Holm va avec des intervalles
  de Bonferroni (niveau 1 − α/m). Une famille corrélée (même relation à plusieurs
  décalages ou seuils) se rend par une bande simultanée de type max-t.
  Benjamini-Hochberg va avec des intervalles FCR pour les lectures retenues. Toutes
  les comparaisons faites sont rapportées, y compris celles qui ne donnent rien.
- **Vocabulaire.** Dans un plan : lectures « principales » et « secondaires ».
  « Confirmatoire » est réservé à la vérification d'une lecture promue (§ 8).
- **Choix figés.** Les choix d'analyse (seuils, pente et durée minimales d'une montée,
  fenêtres, exclusions, transformation) se figent dans le plan avant tout calcul sur
  données réelles. Un choix changé après avoir vu un résultat compte pour un essai de
  plus. Les variantes plausibles se déclarent d'avance et se rapportent toutes
  (sensibilité), jamais la meilleure seule ; un estimateur robuste (Huber, ou médiane)
  fait partie des sensibilités déclarées.
- **Déjà vue.** Une relation regardée dans un notebook ou un tableau de bord avant son
  plan est « déjà vue » sur ces données.
- **Un seul athlète.** Les conclusions valent pour cet athlète. Une relation retrouvée
  chez un second athlète, sur ses propres données, n'est pas une généralisation, mais
  elle pèse beaucoup plus.

## 7. Prévoir : bases à battre et validation dans l'ordre du temps

- **Bases à battre**, toujours : la persistance et la moyenne glissante ; pour une
  performance, « comme la dernière sortie comparable ».
- **À date.** Toute grandeur dérivée qu'utilise une prévision faite au jour t
  (normale, seuil, FC max, zones, standardisation, paramètre estimé de segmentation,
  réglage) se calcule avec les seules données disponibles à t. Fenêtres à droite
  seulement. En validation, ces grandeurs se réestiment à chaque origine, dans la
  partie apprentissage.
- **Purge.** Un exemple d'apprentissage dont la cible déborde l'origine est retiré :
  l'écart entre apprentissage et évaluation est l'horizon de la cible. On coupe par
  jour, jamais au milieu d'une sortie.
- **Origine glissante.** On apprend jusqu'à t, on prévoit t+1…t+h, on avance.
  Sélection et réglages se font dans chaque partie apprentissage (validation
  imbriquée) ; chaque modèle essayé compte pour un essai. Avec scikit-learn,
  `TimeSeriesSplit` coupe par numéro de ligne : trier par date et couper aux limites
  des jours.
- **Battre la base** = écart moyen de perte (modèle − base) négatif, avec un
  intervalle (Diebold-Mariano, correction de Harvey-Leybourne-Newbold, variance
  robuste à l'autocorrélation) dont la borne haute est sous zéro. Sinon le tableau de
  bord n'affiche pas la prévision, ou l'affiche « ne bat pas la base ».
- **Une métrique d'erreur écrite d'avance** par plan.
- **Métriques Garmin.** Avant leur premier usage en prévision : deux exports d'une
  même période, faits à des dates différentes, doivent donner les mêmes valeurs ;
  sinon la métrique est révisée après coup et n'entre pas dans une prévision.

## 8. Le permanent : un outil qui évolue

- Les tableaux de bord et les commandes se recalculent à chaque mise à jour, et ce
  qu'on en lit évolue avec eux. C'est voulu. Les questions de la liste sont des axes
  de recherche, pas des tests à trancher une fois.
- Ils affichent des **estimations avec leurs intervalles**, sans verdict (ni
  « significatif », ni étoiles). Une bande ponctuelle se dit telle ; une lecture de
  tendance demande une bande simultanée. La fin d'une courbe lissée (la demi-fenêtre
  la plus récente) s'affiche comme provisoire, ou le lissage se fait à droite. Ce qui
  n'est pas promu porte la mention « exploratoire ».
- **Promouvoir une lecture.** Une seule chose demande plus : quand une lecture devient
  l'entrée d'autre chose — un paramètre du moteur, une règle que l'outil affiche à
  l'athlète, une affirmation écrite (README, compte rendu). Elle se **déclare** alors,
  puis se **vérifie** :
  - **La déclaration fige ensemble** : l'hypothèse et son sens ; l'estimateur, le code
    (commit), l'unité, les exclusions, les seuils ; l'estimation de découverte et son
    intervalle ; le plus petit effet utile ; le critère ; l'échéance ; la période et
    l'empreinte des données de découverte.
  - **Données neuves seulement.** La vérification s'estime sur les seules unités dont
    la date d'événement (pas d'ingestion) est postérieure à la déclaration, jamais
    mêlées aux données de découverte. Un historique ancien importé plus tard (autre
    montre, autre plateforme) est antérieur.
  - **Critère.** Vérifiée : l'intervalle unilatéral à 95 % exclut zéro dans le sens
    déclaré. Infirmée : l'intervalle exclut le plus petit effet utile. Sinon : non
    tranchée.
  - **Échéance calculée** : le nombre de nouvelles unités qui donne 80 % de puissance
    au critère pour le plus petit effet utile (pas pour l'estimation de découverte).
    Si ce nombre dépasse un an de données au rythme observé, la lecture ne se promeut
    pas : elle reste exploratoire.
  - **Une seule lecture.** Le tableau de bord reste visible ; ni le critère ni
    l'échéance ne changent. Une déclaration ne se retire pas et ne se prolonge pas : à
    l'échéance, son résultat s'écrit, « non tranchée » compris.
  - **Valeur transmise.** Une règle affichée ou une affirmation écrite prend la valeur
    estimée sur les données de vérification. Pour le moteur, son protocole décide
    (0010, D10) ; on lui déclare une règle d'estimation (D10.1) plutôt que la valeur
    de découverte.
  - **En attente**, une règle affichée porte la mention « provisoire ».
  - **Par athlète.** Une lecture se promeut et se vérifie athlète par athlète. Chez un
    autre athlète, la même règle repart exploratoire ; elle peut s'afficher « vérifiée
    chez un autre athlète », jamais « vérifiée ».
  - **Où.** Pour le moteur, son registre (0010, D10.7, D14). Pour le reste,
    `resultats/essais.jsonl` (§ 10), qui chaîne ses lignes par empreinte comme le
    registre (D14) ; l'empreinte de la dernière ligne se recopie dans le compte rendu
    de chaque déclaration.
- Chaque résultat garde sa date et l'empreinte des données.

## 9. Les notebooks et la règle 7

La règle 7 (« pas de logique métier dans l'interface, ni dans un notebook »), prise à
la lettre, interdit l'exploration. Précision (`docs/decisions/0012`) :

- **Un notebook peut calculer pour explorer, et ce calcul est jetable.**
- **Tout chiffre rapporté vient d'une fonction testée de `src/`.** « Rapporté » :
  repris dans un compte rendu, une décision, le tableau de bord, le journal des essais
  ou le moteur.
- **Un notebook ne lit que `processed/`** (et la configuration), jamais `raw/`.
- **Ce qu'un notebook a regardé est « déjà vu »** (§ 6), et un choix d'analyse essayé
  dans un notebook puis changé dans le plan compte pour un essai.
- **Outil : marimo.** Chaque notebook est un fichier `.py`, sans sortie, lisible en
  diff et par `ruff` ; le dossier `__marimo__/` sera exclu par `.gitignore`.
- **Garde-fou mécanique** : un contrôle en CI refuse tout `.ipynb`, et tout fichier de
  données hors de `tests/fixtures/` ; il arrive avec le premier notebook.
- `notebooks/` reste hors des cibles de mypy.

## 10. Où vivent les résultats

| Quoi | Où | Jamais |
|---|---|---|
| tables d'analyse | `MPA_DATA_DIR/processed/` | dans le dépôt |
| résultats d'une question | `MPA_DATA_DIR/resultats/<question>/<date>_<empreinte>/` : tableau, figure, et un petit fichier qui dit la commande, la version du code, la période, l'empreinte des données, les seuils figés et la graine de toute simulation ou bootstrap | écrasés |
| journal des essais de la piste | `MPA_DATA_DIR/resultats/essais.jsonl`, en ajout seul, lignes chaînées par empreinte (§ 8) | réécrit |
| ce que l'athlète a déjà vu (§ 6) | `MPA_DATA_DIR/resultats/deja_vu.csv`, tenu à la main : une ligne par question ou relation regardée avant son plan, avec la date et l'endroit (notebook, tableau de bord) | dans le dépôt |
| comptes rendus et arbitrages | hors du dépôt, avec les notes de conception | dans le dépôt |
| dans le dépôt | le code, les tests, des fixtures synthétiques, des figures faites sur données synthétiques | une figure ou un chiffre de vraies données |

## 11. Les mesures calculées par la montre

Body Battery, Training Readiness, Training Status, statut et normale HRV, score de
sommeil, VO2max, charges, acclimatation sont des boîtes noires ; mais les mesures
dites « directes » (durée et phases du sommeil, FC de repos au sens de Garmin, HRV de
la nuit, détection du mouvement) sont aussi des algorithmes du firmware. Règles :
- on préfère les mesures les plus proches du capteur, et la charge recalculée depuis
  les activités ;
- un indicateur composite s'affiche comme ce qu'il est : « selon Garmin » ;
- **contrôle préalable**, pour toute mesure calculée par la montre, composite ou non :
  on modélise la mesure par ses entrées (par exemple Body Battery du matin selon durée
  de sommeil, HRV et stress) et on cherche un saut **dans le résidu** à chaque
  changement de firmware ; un saut de la mesure sans saut de ses entrées est
  algorithmique (témoin négatif). L'intervalle de date incertain (entre la dernière
  activité à l'ancienne version et la première à la nouvelle) est exclu des fenêtres.
  Chaque saut se rapporte avec son intervalle, simultané sur l'ensemble des versions ;
  un saut dont l'intervalle n'exclut pas un saut utile se déclare « non exclu ». Un
  changement de montre est une rupture d'office. Les changements côté serveur restent
  un risque déclaré, non contrôlé ;
- un indicateur composite entre dans une relation seulement si le plan dit pourquoi
  une mesure plus directe ne suffit pas (Q9 est l'exception : elle les juge).

## 12. La chaleur et les sources extérieures

- La source de température se choisit au jalon de Q10. Candidates : réanalyse
  (Open-Meteo : ERA5-Land, IFS), stations d'un service météorologique national, météo
  Garmin (station parfois lointaine).
- **Le capteur de la montre** mesure un mélange de l'air, de l'effort, des vêtements
  et du soleil. Trois usages, à ne pas confondre :
  - **indicateur de charge thermique**, rapporté à une normale personnelle à effort
    comparable (même bande de FC) : légitime, et peut-être l'un des plus parlants (une
    sortie par grand froid ne chauffe pas le capteur comme une sortie en pleine
    chaleur) ; il s'affiche au tableau de bord et sert d'issue ou de médiateur ;
  - **exposition** dans « chaleur → performance » : seulement sous une forme corrigée
    de l'effort (par exemple le capteur dans les premières minutes, ou le résidu d'un
    modèle capteur ~ effort), **validée contre une température de l'air** là où les
    deux existent ; brut, jamais, puisque l'effort étudié le fait monter ;
  - un résultat d'exposition obtenu avec le capteur brut est à refaire.
- **Correction d'altitude faite localement**, avec l'altitude barométrique de la
  trace, sans l'envoyer au fournisseur.
- **Exposition le long de la trace**, pondérée par le temps et interpolée à l'heure,
  pas la valeur au point de départ.
- **Une source pour toute la période.** Un changement de source ou de version (données
  provisoires puis consolidées) est une rupture, comme un firmware. La date de
  récupération et la version se rangent dans `raw/<source>/`.
- **Une seule variable d'exposition, choisie d'avance** (température de l'air, ou un
  indice de contrainte thermique) ; chaque variable de plus est un essai.
- **Toute source extérieure** s'acquiert par une commande, se range dans
  `raw/<source>/` (immuable, régénérable sans retéléchargement), et ne reçoit que des
  coordonnées arrondies à la maille de son modèle.

## 13. Les cycles de relecture

Chaque relecture se fait dans une conversation neuve, qui n'a pas écrit ce qu'elle
relit.

| Produit | Référence du relecteur | Cycle |
|---|---|---|
| code de `src/` (contrats, ingestion, fonctions d'analyse, calculs du tableau de bord) | le brief, puis le plan | brief relu → plan de l'agent de code relu → PR → relecture profonde → correctifs → relecture bornée → fusion. Pour l'ingestion, deux relectures profondes indépendantes |
| plan d'analyse d'une question | la liste des questions et cette charte | relecture experte → plan relu → code → relecture de la PR contre le plan |
| notebook d'exploration | aucune | pas de relecture ; aucun de ses chiffres n'est un résultat (§ 9) |
| tableau de bord | le brief (pages et sources) | brief relu, puis une relecture de la PR qui vérifie qu'il ne calcule rien (règle 7) |

## 14. Validation

Version 1 validée le 2026-10-07 ; version 2, après la relecture experte, validée le
2026-10-08.
