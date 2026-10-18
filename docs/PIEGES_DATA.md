# Pièges data — à lire avant de toucher aux données Garmin

> Chacun de ces pièges a déjà été rencontré et payé, sur la version précédente du
> projet ou sur un export réel examiné. Les redécouvrir coûterait plusieurs heures
> chacun.
> Quand un nouveau piège est trouvé, il s'ajoute ici **le jour même**.

---

## Calculs

**La VAM réelle se calcule comme `D+ ÷ temps de mouvement`.**
Ne **pas** utiliser le champ `directVerticalSpeed` : il est quantifié (~720 paliers),
donc inexploitable pour une courbe fine. Pour une montée, le D+ du numérateur est le
gain pris *pendant* le mouvement (`docs/decisions/0014`) : le gain d'un trou, d'une
pause ou d'un arrêt n'entre pas au numérateur quand son temps n'est pas au
dénominateur. De même, une pente se lit sur un seul support : le gain et la longueur
des mêmes intervalles.

**Classer ou filtrer des montées par leur durée sélectionne sur la mesure** : à gain
égal, une montée lente dure plus longtemps. Une durée minimale écarte les montées
rapides, une frontière de régime en durée y fait passer une montée selon sa vitesse.
Les régimes se lisent sur le gain, à une vitesse de référence déclarée, et le gain
minimal se rapporte au pas d'échantillonnage (`docs/decisions/0014`).

**Le champ `directGradeAdjustedSpeed` (GAP) n'est pas fiable** aux transitions de
pente. Pour caractériser les descentes, utiliser la **vitesse brute par tranche de
pente** plutôt que le GAP fourni.

**`MAXHR = 210` dans les anciens scripts est une constante de normalisation**, pas
la FC max réelle de l'athlète. Ne pas la reprendre comme une donnée physiologique.

**Le D+ brut (somme des hausses) dépend du pas d'échantillonnage.** Deux sources de
la même sortie ne se comparent qu'après le même rééchantillonnage et le même lissage
(ceux du profil, `gpx/profile.py`).

---

## Structure de l'export Garmin

**`raw/activities/*.json`** — la *liste* des activités (index). Champs utiles :
`activityId`, `startTimeLocal`, `activityType.typeKey`, `distance`, `duration`,
`movingDuration`, `elevationGain`, `averageHR`, `maxHR`. **`duration` est le temps du
chronomètre** ; le temps écoulé est `elapsedDuration` : ils diffèrent quand la montre a
été arrêtée en route. `movingDuration` vaut 0 pour une activité sans déplacement
(escalade, renforcement…), et la distance, le D+ et le D− y manquent.

**`raw/activity_details/*.json`** — les streams point par point, sous-échantillonnés
(voir plus bas). La structure est indirecte et c'est le principal piège :

- `metricDescriptors` donne la correspondance `key → metricsIndex`
- les valeurs sont dans `activityDetailMetrics[i].metrics[index]`
- **il faut lire `metricDescriptors` à chaque fichier** : les indices ne sont pas
  garantis stables entre activités. Les coder en dur est un bug qui ne se voit pas.

Indices observés sur l'ancien export (à vérifier, pas à supposer) :
`sumDistance` 8 · `directElevation` 0 · `sumMovingDuration` 9 · `sumDuration` 3 ·
`directSpeed` 6 · `directHeartRate` 12 · `directVerticalSpeed` 13 *(quantifié, ne pas utiliser)*
Confirmé sur un export réel : ces indices changent d'un fichier à l'autre, pour toutes
les clés.

**`activity_details` est sous-échantillonné.** Son nombre de lignes par activité est
plafonné, quelle que soit la durée de la sortie : le pas va de quelques secondes pour
une sortie courte à quelques dizaines de secondes pour une sortie très longue. En
montagne, ses points espacés coupent les lacets : la distance horizontale calculée sur
ses positions est trop courte, donc la pente trop forte et la vitesse horizontale trop
faible. Le D+ et la vitesse ascensionnelle d'une montée restent justes après le
lissage du profil. **Les séries d'une activité se lisent dans le FIT**
(`activity_fit/`, au pas d'enregistrement de la montre), pas dans `activity_details`
(`docs/decisions/0011`, `0013`).

**Les fichiers santé sont un JSON par date**
(`resting_hr/AAAA-MM-JJ.json`, `hrv/`, `sleep/`, `body_battery/`,
`training_readiness/`, `training_status/`, `stress/`, `respiration/`, `spo2/`,
`daily_summary/`).
Vérifier le **nom exact du champ** dans chaque famille : un champ de FC de repos
mal nommé a déjà produit silencieusement une colonne entière de `None`.

**Une nuit appartient au jour du réveil** (`sleep`, `hrv`) : la nuit qui précède une
sortie du jour J est dans le fichier du jour J, pas J−1. Dans `sleep`, les horodatages
dits « locaux » sont des millisecondes d'heure murale (un faux UTC) ; les « GMT » sont
de vrais instants.

**La FC de repos** est dans `resting_hr` sous
`allMetrics.metricsMap.WELLNESS_RESTING_HEART_RATE[0].value` ;
`heart_rate.restingHeartRate` porte la même valeur.

**`training_readiness` porte plusieurs entrées par jour** (au réveil, après un effort,
mises à jour en continu), distinguées par `inputContext` : la valeur « du jour » se
définit, par exemple la première entrée `AFTER_WAKEUP_RESET`.

**`training_status` range ses valeurs sous l'identifiant de la montre**
(`…DTOMap.<identifiant>…`) : un changement de montre, ou un autre athlète, change le
chemin.

**Les séries fines peuvent manquer sur une partie de la période** (HRV toutes les cinq
minutes, FC intrajournalière) alors que les résumés quotidiens existent. Cause
probable : un réglage du script d'export, à vérifier quand il sera repris dans
`legacy/`.

**Météo (`activity_weather/`)** : températures en °F (`temp`, `apparentTemp`,
`dewPoint`), vent probablement en mph. La mesure vient d'une station, parfois très
loin de la sortie et en fond de vallée pour une sortie en montagne, et l'observation
peut précéder le départ de plusieurs heures (constaté sur un export réel). Les
températures de la montre (°C : `minTemperature` et `maxTemperature` de `activities`,
champ `temperature` du FIT) sont chauffées par le corps.

**Valeurs sentinelles et aberrantes** : `avgElevation = -500` (activité sans
altitude) ; `splitSummaries[*].totalAscent` et `maxVerticalSpeed` peuvent être
aberrants. `elevationCorrected = true` signale une altitude recalée par Garmin, avec
une clé `directCorrectedElevation` dans les détails.

**Le firmware change souvent**, et seul le FIT le porte. Les métriques calculées par
la montre (Body Battery, Training Readiness, VO2max, charges…) peuvent changer de
niveau à chaque version.

**Identifiants personnels** : dans `activities` (`ownerId`, `ownerDisplayName`,
`ownerFullName`, URL de photo, `activityName`, `locationName`), dans `profile.json`, et
un `userProfilePK` ou `userId` dans presque chaque famille. L'ingestion ne garde que
ce dont les contrats ont besoin.

**Autres dossiers** : `activity_splits/`, `activity_weather/`, `activity_fit/`,
`range/` (prédictions de course).

---

## FIT (`activity_fit/`)

**fitdecode, par défaut, ne fait qu'avertir** sur un CRC faux ou une erreur de
décodage, et rend un fichier lu à moitié sans bruit : lire en mode strict
(`docs/decisions/0011`).

**Chaque canal peut manquer indépendamment des autres** : des enregistrements sans
position (le GPS qui capte au départ, une perte de signal), plus rarement sans
altitude ou sans FC. Ne pas supposer qu'un enregistrement porte tous les champs du
fichier.

**Le chronomètre a des pauses** : `total_elapsed_time` et `total_timer_time` de la
session diffèrent alors, et les messages `event` (arrêts et reprises du chronomètre)
disent où.

**Altitude et positions** : prendre `enhanced_altitude`, ou `altitude` à défaut, et
dire laquelle ; les positions sont en semicercles, à convertir en degrés à la lecture.
Les champs `unknown_<n>` sont propres à la montre : ne pas s'en servir.

**Un export peut contenir le FIT d'une autre marque** (`file_id.manufacturer`) : ne
rien supposer de la montre.

**fitdecode déduit des champs par expansion** : `enhanced_altitude` tiré d'`altitude`,
`enhanced_speed` tiré de `speed` (`FieldData.is_expanded`). Une montre qui n'écrit que
`speed` paraît écrire `enhanced_speed` : ne compter que les champs écrits.

**Un FIT peut contenir la sortie deux fois** : après l'arrêt final, le chronomètre
repart au départ et les enregistrements se répètent, à des instants déjà vus et avec
les mêmes valeurs (presque toutes). La distance d'un FIT peut aussi reculer
ponctuellement. On garde le premier passage, et l'on compte ce qu'on écarte, en
séparant le doublon de la mesure perdue.

**La valeur invalide est fréquente** : un record sans point GPS écrit souvent ses
positions à la valeur invalide de leur type (fitdecode rend `None`), plutôt que de les
omettre. Ce n'est pas une valeur. Le brut 0, lui, en est une pour le décodeur : une
altitude de −500 m (le codage a un décalage de 500 m), une position (0°, 0°) ; des
écrivains de FIT l'emploient pour « pas de valeur », comme `avgElevation = -500` dans
l'index.

**La correction d'altitude de Garmin Connect ne touche pas le FIT** : quand
`elevationCorrected` est vrai dans l'index, son D+ vient d'un modèle de terrain, et le
FIT garde l'altitude de la montre (ou n'en a pas).

**La pause automatique se déclenche aussi en montée raide**, quand la vitesse
horizontale passe sous son seuil : la montre cesse d'enregistrer pendant que l'athlète
monte. Le D+ gagné pendant une pause ne se divise pas par un temps de mouvement qui
l'exclut. Le déclencheur de chaque pause est écrit dans l'événement du chronomètre
(`timer_trigger` : `manual` ou `auto`).

**Un FIT multisport porte plusieurs sessions** (message `session`).

**Chaque FIT est dans une archive** `activity_fit/<identifiant>.zip`, à un seul membre
`.fit`.

---

## Acquisition

**Le rate-limit 429 de Garmin porte sur le *login*, pas sur la récupération de
données.** Une fois le token obtenu et sauvegardé, les lancements suivants ne
déclenchent plus le problème.

Conséquences pratiques :
- ne pas marteler le script pendant un blocage, chaque tentative peut prolonger la
  pénalité (attendre 15–60 min, parfois plus)
- un changement d'IP débloque souvent immédiatement
- l'acquisition doit être **reprenable** : relancer après une coupure doit continuer,
  pas recommencer

Il n'y a **pas d'API officielle Garmin** pour les données personnelles ; on passe
par une bibliothèque communautaire. Elle casse de temps en temps — raison de plus
pour que `raw/` soit immuable et que tout le reste soit régénérable sans
re-téléchargement.

---

## Altitude et tracés

**Le lissage de l'altitude change le D+ total de plusieurs centaines de mètres**
sur un long tracé. Le paramètre de lissage doit être explicite, documenté, et pris
en compte quand on compare deux sources.

**Les exports d'altitude diffèrent entre outils** (traces issues d'applications de
cartographie vs traces recalées sur réseau de sentiers). Deux GPX du même parcours
peuvent annoncer des D+ très différents. Le recalage sur sentier déforme aussi
localement le tracé.

**La densité d'échantillonnage varie fortement d'une source à l'autre.** Toujours
rééchantillonner sur une grille à pas fixe avant de calculer quoi que ce soit ;
un calcul de pente point-à-point sur des points irréguliers donne du bruit.

**Les bornes d'une côte prises sur le profil lissé sous-estiment sa VAM**, d'autant
plus que la côte est courte : le lissage rabote son sommet, et les bornes englobent
une part des replats voisins. Détecter sur le profil, mais placer les bornes et lire le
gain en temps, sur l'altitude lissée par bloc du moteur (`docs/decisions/0014`).

**Une montée peut ne pas être humaine** : une remontée mécanique (un télésiège pendant
une sortie de ski), un véhicule. Sa VAM ou sa vitesse horizontale sort de toute échelle
humaine ; elle se marque, avec des seuils déclarés, et ne se corrige pas.

**L'altitude barométrique dérive avec la pression** : sur une boucle, l'arrivée ne
revient pas exactement à l'altitude du départ. La fermeture altimétrique d'une boucle,
rapportée à sa durée, en est un indicateur ; une montée sans baromètre attesté (le FIT
ne décrit pas toujours ses capteurs) a une altitude GPS, plus bruitée.

---

## Performances de référence

**Les conventions de chronométrage sont mélangées dans `passages_tous.csv`.** Les
temps sont en principe relevés à la **sortie** du ravitaillement, mais certains
l'ont été à l'arrivée. Un ravito où l'on passe douze minutes produit alors un écart
de douze minutes qui n'est pas une erreur de modèle — et comme les cumuls
s'additionnent, il pollue tous les points suivants. Sans le savoir, on cherche un
effet de fatigue qui n'existe pas. D'où le champ de convention par passage sur
`ReferencePerformance`, avec `UNKNOWN` comme valeur honnête.
