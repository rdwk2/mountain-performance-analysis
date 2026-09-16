# 0008 — Géométrie, lissage et résolution des passages

- **Date** : 2026-09-17
- **Statut** : acceptée

## Contexte

M2 est le premier jalon qui lit un fichier et calcule un profil. Quatre choix de
convention deviennent invisibles une fois codés : distance, ordre des opérations,
lissage et séparation des passages. Ils sont fixés par le brief M2 révision 5 et
ses prescriptions finales, sans modifier les contrats M1.

## Options envisagées

**Distance.** Loi des cosinus sphérique, calcul sur ellipsoïde ou haversine sur
une sphère. L'altitude reste exclue de la distance (décision 0002).

**Lissage.** Lisser les points source ou rééchantillonner d'abord ; nettoyer la
comptabilité du D+ par un seuil ou nettoyer le profil lui-même.

**Passages.** Chercher les minima de la suite des écarts aux segments, ou lire
les minima de distance le long de l'abscisse sur les paramètres de projection.
Pour séparer les candidats proches, « garder le meilleur » ne suffit pas à
définir une sélection reproductible.

## Décision

1. **Distance orthodromique par haversine**, sur une sphère de rayon
   `EARTH_RADIUS_M = 6_371_008.8` m (rayon moyen WGS84, R1 IUGG), horizontale 2D.
   La constante vit uniquement dans `gpx/geo.py`.
2. **Abscisse curviligne → grille à pas fixe → lissage**. Les points consécutifs
   confondus sont écartés, en conservant le premier, par le même utilitaire pour
   la lecture, la grille et la résolution. Une longueur nulle est refusée.
   La grille finit exactement en `L` : pour `L >= h`, avec `n = floor(L/h)`,
   remplacer `n*h` par `L` si le reste est inférieur à `h/2`, sinon ajouter `L`.
   Les intervalles sont dans `[h/2, 3h/2]`. Pour `L < h`, la grille `(0, L)` est
   exemptée de cette borne. L'altitude est interpolée linéairement en abscisse.
3. **Moyenne glissante symétrique**, fenêtre demandée `w` en mètres et
   `k = floor(w/(2h))`. Elle porte sur `2k+1` points, se rétrécit aux deux bords
   et conserve la taille de la grille. Avec `k = 0`, aucun lissage ; la largeur
   nominale effective est `(2k+1)*h`. **Aucun seuil de comptage du D+** : les
   cumuls restent les propriétés M1 du profil lissé.
4. **Candidats lus sur `t`, puis suppression non maximale gloutonne**.
   La projection point-segment utilise le plan local ancré au premier point A :
   `x = R*Δλ*cos(φ_A)`, `y = R*Δφ`, avec `t` borné à `[0, 1]`.
   Un candidat est un minimum de la distance au tracé le long de l'abscisse :
   intérieur si `0 < t_i < 1` ; sommet si `t_i = 1` et `t_{i+1} = 0` ; début si
   `t_0 = 0` ; fin si `t_dernier = 1`. Les candidats de même abscisse sont
   confondus. Aucune comparaison des écarts de segments voisins ne les définit.

Pour chaque lieu, filtrer les candidats dont l'écart est
`<= point_match_max_offset_m`, puis les trier par **(écart, abscisse) croissants**.
Retenir le premier et écarter définitivement tous ceux à **moins de**
`point_match_min_separation_m` de son abscisse ; répéter jusqu'à épuisement.
À séparation nulle, chaque minimum admissible est conservé. Un même lieu peut
ainsi donner plusieurs passages. L'altitude de chaque passage est interpolée sur
le profil lissé, indépendamment de celle du waypoint ; le résultat est trié par
abscisse.

## Pourquoi

La haversine reste stable sur les petits segments, contrairement à la loi des
cosinus, et ne demande aucune dépendance. Son écart à l'ellipsoïde reste sous
0,3 % aux latitudes alpines mais **dépend de l'azimut** : environ +0,06 % nord-sud
et −0,28 % est-ouest à 45°. Ce n'est pas une borne générale. Ce biais ne se
simplifie dans `durée = distance / vitesse` que si les orientations moyennes du
tracé et des activités ayant construit la courbe se ressemblent : à mesurer en
M6b, sans le supposer.

Rééchantillonner avant de lisser rend la fenêtre exprimable en mètres et assure
la stabilité à la densité source dans les conditions testées. Un seuil de
comptage du D+ ne nettoierait que le total et laisserait au moteur des pentes
bruitées ; le lissage agit sur le profil qui sera réellement consommé.

Comparer les écarts aux segments perd l'un des deux minima voisins d'un
aller-retour, puis le retrouve après subdivision : cela rend les passages
dépendants de la densité source. La définition par `t` conserve ces deux minima.
La règle de séparation est nommée parce que trois lectures plausibles de
« garder le meilleur » donnent trois nombres de passages sur les lacets. Celle
retenue montre les passages possibles ; M4 et M5 pourront traiter l'ambiguïté.

## Conséquences

- Le profil **n'est pas invariant au changement de pas de grille**, qui change
  la fenêtre effective. Les défauts des quatre paramètres sont provisoires.
- La commande affiche la fenêtre effective, les D+/D− lissés et bruts, les
  doublons, les raccords de tronçons, les waypoints sans nom et les lieux non
  résolus avec leur écart minimal. La bibliothèque produit ces diagnostics dans
  `ProfileBuildResult`, via `build_profile_with_diagnostics` ; `build_profile`
  conserve sa signature et retourne un `RouteProfile` M1 inchangé.
- Le nettoyage du bruit d'altitude passe entièrement par le lissage. Aucun
  `QualityFlag`, écrêtage, inférence de `PointKind` ou seuil de D+ n'est ajouté.
- La lecture utilise `xml.etree.ElementTree` et le nom local des balises. Les
  valeurs numériques illisibles ou manquantes lèvent `GpxError` ; les violations
  physiques restent des `ContractError`. La commande les affiche sans traceback.
- **À revisiter en M6b** : reprendre exactement la convention de distance pour
  la courbe et la confronter au `sumDistance` Garmin, en tenant compte de l'azimut.
