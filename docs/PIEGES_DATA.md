# Pièges data — à lire avant de toucher aux données Garmin

> Chacun de ces pièges a déjà été rencontré et payé sur la version précédente du
> projet. Les redécouvrir coûterait plusieurs heures chacun.
> Quand un nouveau piège est trouvé, il s'ajoute ici **le jour même**.

---

## Calculs

**La VAM réelle se calcule comme `D+ ÷ temps de mouvement`.**
Ne **pas** utiliser le champ `directVerticalSpeed` : il est quantifié (~720 paliers),
donc inexploitable pour une courbe fine.

**Le champ `directGradeAdjustedSpeed` (GAP) n'est pas fiable** aux transitions de
pente. Pour caractériser les descentes, utiliser la **vitesse brute par tranche de
pente** plutôt que le GAP fourni.

**`MAXHR = 210` dans les anciens scripts est une constante de normalisation**, pas
la FC max réelle de l'athlète. Ne pas la reprendre comme une donnée physiologique.

---

## Structure de l'export Garmin

**`raw/activities/*.json`** — la *liste* des activités (index). Champs utiles :
`activityId`, `startTimeLocal`, `activityType.typeKey`, `distance`, `duration`,
`movingDuration`, `elevationGain`, `averageHR`, `maxHR`.

**`raw/activity_details/*.json`** — les streams point par point. La structure est
indirecte et c'est le principal piège :

- `metricDescriptors` donne la correspondance `key → metricsIndex`
- les valeurs sont dans `activityDetailMetrics[i].metrics[index]`
- **il faut lire `metricDescriptors` à chaque fichier** : les indices ne sont pas
  garantis stables entre activités. Les coder en dur est un bug qui ne se voit pas.

Indices observés sur l'ancien export (à vérifier, pas à supposer) :
`sumDistance` 8 · `directElevation` 0 · `sumMovingDuration` 9 · `sumDuration` 3 ·
`directSpeed` 6 · `directHeartRate` 12 · `directVerticalSpeed` 13 *(quantifié, ne pas utiliser)*

**Les fichiers santé sont un JSON par date**
(`resting_hr/2026-07-06.json`, `hrv/`, `sleep/`, `body_battery/`,
`training_readiness/`, `training_status/`, `stress/`, `respiration/`, `spo2/`,
`daily_summary/`).
Vérifier le **nom exact du champ** dans chaque famille : un champ de FC de repos
mal nommé a déjà produit silencieusement une colonne entière de `None`.

**Autres dossiers** : `activity_splits/`, `activity_weather/`, `activity_fit/`,
`range/` (prédictions de course).

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

---

## Performances de référence

**Les conventions de chronométrage sont mélangées dans `passages_tous.csv`.** Les
temps sont en principe relevés à la **sortie** du ravitaillement, mais certains
l'ont été à l'arrivée. Un ravito où l'on passe douze minutes produit alors un écart
de douze minutes qui n'est pas une erreur de modèle — et comme les cumuls
s'additionnent, il pollue tous les points suivants. Sans le savoir, on cherche un
effet de fatigue qui n'existe pas. D'où le champ de convention par passage sur
`ReferencePerformance`, avec `UNKNOWN` comme valeur honnête.
