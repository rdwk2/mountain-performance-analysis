# 0009 — Moteur de projection v0

- **Date** : 2026-09-20
- **Statut** : acceptée

## Contexte

Le M2 produit un `RouteProfile` : une grille de distance, une altitude lissée, des
lieux nommés résolus. Les contrats de la performance existent depuis le M1b mais
rien ne les produit. Le M3 ferme la tranche verticale — GPX → profil →
vitesse(pente) × effort → temps cumulés — et doit pour cela trancher six questions
que ni le M1 ni le M2 n'avaient à poser.

Contraintes qui pèsent sur toutes : aucune dépendance nouvelle ; aucun contrat du
M1 modifié ; les défauts de grille `grid_step_m = 50` et `smoothing_window_m = 150`
restent tels quels, **provisoires** (calage post-M2 clos sans validation générale) ;
et **ce jalon ne mesure rien** — l'erreur du modèle est le M4.

## Options envisagées

### D2 — sur quelles tranches de la courbe s'appuyer

**A. Toutes les tranches du fichier.** Les pentes extrêmes sont estimées sur une à
trois minutes de données : du bruit promu au rang de mesure.

**B. Filtre plat `time_min >= seuil`.** Simple, mais il retient une tranche bien
fournie située **au-delà** d'un trou, comme si la courbe y était continue.

**C. Plage contiguë autour de 0 %, chaque tranche au-dessus du seuil.** Retenue.

### D3 — interpoler l'allure ou la vitesse entre deux tranches

**A. Interpolation linéaire de la vitesse.** L'intuition immédiate, et la
convention qu'un lecteur pressé suppose.

**B. Interpolation linéaire de l'allure `p = 1/v`.** Retenue.

### D4 — que faire au-delà de la dernière tranche retenue

**A. Prolonger la droite d'interpolation.** Donne une vitesse négative en pente
raide : absurde, et rien ne l'arrête.

**B. Figer la vitesse horizontale du bord.** Prédit qu'on monte à +80 % aussi vite
qu'à +45 %, donc une vitesse verticale qui explose.

**C. Figer la vitesse verticale du bord** — `v(g) = v(g_b)·|g_b|/|g|`. Retenue.

**D. Refuser de projeter hors du support.** Écarté : un tracé réel de montagne sort
toujours de la plage, et refuser rendrait l'outil inutilisable.

### D5 — le facteur d'effort

**A. Défaut 0,92**, la valeur de `MODELE_V1.md`.

**B. Défaut 1**, `effort = 1` désignant la référence empirique des activités qui ont
construit la courbe. Retenue.

**C. Un effort dépendant de la pente.** Écarté : aucune mesure ne le calibre, et il
se confondrait avec la forme de la courbe elle-même.

### D6 — le biais d'échelle entre estimation et application

**A. Corriger par un facteur mesuré** sur deux tracés réels.

**B. Réestimer la courbe au même opérateur de pente** avant de livrer le M3.

**C. Accepter le biais, le documenter, ne pas le corriger.** Retenue.

### D8 — d'où vient la provenance de la courbe

**A. Déduire les dates du nom de fichier.** `courbe_<début>_<fin>.csv` les
contient, mais pas la tolérance de FC, ni le type d'activité, ni la largeur de
tranche — et un fichier renommé mentirait sans que rien ne le détecte.

**B. Des options de ligne de commande** (`--curve-from`, `--curve-estimator`…).

**C. Des valeurs par défaut** quand l'information manque.

**D. Un fichier compagnon `<stem>.meta.json`, obligatoire.** Retenue.

Sous-question, tranchée le même jour : **le sport**, que `PaceCurve` exige et que le
CSV ne porte pas davantage que les dates. Trois options écartées — une constante
`Sport.FOOT` en dur dans le lecteur ; une clé facultative avec `foot` par défaut ;
une déduction depuis `source_activity_types`. Retenue : **une clé `sport`
obligatoire** dans le compagnon.

## Décision

**D2** — ne sont retenues que les tranches d'au moins `curve_min_support_min`
minutes (défaut 10), **en plage contiguë autour de 0 %** ; une tranche isolée
au-delà d'un trou est écartée même si elle dépasse le seuil.

**D3** — entre deux centres de tranche, c'est l'**allure** `p = 1/v` qui est
interpolée linéairement, pas la vitesse.

**D4** — au-delà du dernier centre retenu de chaque côté, la **vitesse verticale du
bord est figée** : `v(g) = v(g_b)·|g_b|/|g|`.

**D5** — l'effort est un facteur multiplicatif unique sur la vitesse, **défaut 1**,
sans dépendance à la pente.

**D6** — le biais d'échelle entre la pente d'estimation et la pente d'application
est **accepté, documenté, non corrigé**.

**D8** — la provenance vit dans un fichier compagnon `<stem>.meta.json` **à côté du
CSV et obligatoire**, qui porte aussi le sport.

## Pourquoi

**D2 — pourquoi la contiguïté, et pas un filtre plat.** Le filtre plat (B) est ce
qu'on écrit d'abord, et il est faux pour une raison précise : retenir `+65 %` parce
qu'elle a 12 minutes de données, alors que `+50 %` et `+55 %` n'en ont que trois,
revient à interpoler à travers un trou et à présenter le résultat comme une mesure.
La contiguïté **se lit sur les lignes présentes**, pas sur la grille théorique des
pentes : une tranche absente du fichier — fichier au pas de 10 points, tranche
jamais parcourue — n'est pas un trou. C'est ce qui rend la sélection déterministe :
il n'y a ni ex æquo à départager, ni « tranche la plus proche de zéro » à choisir.
Toutes les tranches (A) ont été écartées parce que les pentes extrêmes pèsent une à
trois minutes chacune et que rien ne les distingue alors du bruit.

Deux garde-fous complètent la règle, et chacun paie une dette précise. Le **noyau**
doit encadrer strictement le plat, sinon le prolongement de D4 est indéfini
(`C = 0`, division par zéro) ou absurde (allure nulle à plat, donc vitesse infinie).
L'**écartement minimal de 1 %** aux deux bords est ce qui rend la finitude de
l'allure démontrable plutôt qu'espérée : avec `v >= 0,01 km/h` et `|g_b| >= 0,01`,
la vitesse verticale de bord vaut au moins `1/36 000` m/s, donc l'allure à `|g| =
1000` vaut au plus `3,6e7` s/m. Sans lui, deux tranches à `±1e-304 %` passent toutes
les autres règles et font déborder l'allure.

**D3 — pourquoi l'allure, et c'est démontrable.** Supposons qu'un intervalle de
grille de longueur `Δd` soit en réalité composé de deux morceaux de pentes `g₀` et
`g₁`, occupant les fractions `1−λ` et `λ` de la distance. Sa pente moyenne — celle
que la grille voit — vaut exactement `ḡ = (1−λ)g₀ + λg₁`, et son temps réel vaut
`T = Δd · [(1−λ)p₀ + λp₁] = Δd · p_L(ḡ)`. **L'interpolation en allure est donc
exacte pour ce mélange, pas approchée**, et c'est précisément la situation d'une
grille grossière dont chaque pente est une moyenne de pentes plus fines.
L'interpolation en vitesse (A) ne correspond à aucun mélange naturel : elle
supposerait une moyenne de vitesses pondérée par la distance, ce qui n'est pas la
façon dont le temps s'accumule.

L'écart entre les deux conventions se calcule exactement :
`p_L/p_V − 1 = λ(1−λ)·(v₁−v₀)²/(v₀v₁)`. Il est toujours positif ou nul — D3 est donc
le plus conservateur des deux —, il s'annule aux nœuds, et il est maximal au milieu
d'un intervalle. Sur la courbe retenue, le pire cas par intervalle vaut 1,44 %, et
**l'écart mesuré sur un temps total est de 0,37 %**.

La décision `0002` n'est pas contredite : elle interdit de **stocker** une vitesse
sous forme d'allure et d'interpoler une courbe ainsi stockée. `PaceCurve` reste en
m/s ; l'allure n'existe qu'à l'intérieur du calcul, en secondes par mètre, cohérente
avec `T = Σ Δd · p`.

**D4 — pourquoi la vitesse verticale, et ce que ça ne prouve pas.** Figer la vitesse
horizontale (B) revient à dire qu'on monte à +80 % aussi vite qu'à +45 %, ce
qu'aucune observation ne soutient. Prolonger la droite (A) donne des vitesses
négatives. Figer la vitesse verticale est la seule des trois qui reste bornée et qui
raccorde exactement au bord — `v = C/|g|` redonne `v(g_b)` en `g = g_b`, sans qu'on
ait à forcer la continuité.

**Ce régime est une propriété de cette courbe, pas une loi.** Les tranches écartées
par le seuil n'ont pas servi à le construire : elles permettent donc de le
contrôler. En montée, le prolongement retombe sur elles à moins de 1 % jusqu'à
+65 %. En descente, il est **systématiquement plus lent** que les quelques minutes
mesurées au-delà de −45 % (−16,5 % à −60 %). Les deux lectures se défendent : soit
la vitesse verticale de descente continue d'augmenter en pente raide, soit ces
tranches, qui pèsent une à trois minutes chacune, sont du bruit. Le choix
conservateur est retenu, et c'est le M4 qui tranchera. À réexaminer à chaque
nouvelle courbe.

**D5 — pourquoi pas 0,92.** Cette valeur ajoutait 8,7 % au temps sans aucune mesure
pour la justifier, et compensait dans l'ancien modèle des effets que v0 n'a pas
(fatigue, arrêts, chaleur). La reprendre ici reviendrait à corriger un biais qui
n'existe pas encore. `effort = 1` a en revanche un sens précis et vérifiable : la
référence empirique des activités qui ont construit la courbe. Les bornes `[0,5 ;
1,5]` sont plus larges que l'usage utile (0,7–1,2) pour ne pas transformer une
exploration en erreur de contrat.

**D6 — pourquoi accepter un biais mesuré.** La courbe a été estimée sur des pentes
mesurées **entre échantillons Garmin** ; le moteur les applique sur une grille de
50 m lissée à 150 m. Mesuré sur deux tracés réels : le temps projeté ne dépend du
couple (pas, lissage) que par la largeur `W = (2k+1)·h` sur laquelle la pente est
calculée — à `W` égal, deux pas différents donnent le même temps à 0,3 % près — et
il baisse de 2,9 à 3,3 % quand `W` passe de 10 m à 150 m.

Corriger par un facteur (A) figerait dans le code un nombre mesuré sur deux tracés,
c'est-à-dire un réglage déguisé en loi. Réestimer la courbe (B) est la **vraie**
réponse, mais elle appartient au M6b, qui possède l'estimateur. En attendant, un
biais connu et écrit vaut mieux qu'une correction inventée : une projection porte
donc `profile.build_parameters`, l'échelle qui l'a produite, et une ligne de
`BACKLOG.md` demande la réestimation au même opérateur de pente.

**Corollaire, et il compte** : l'invariance du temps au changement de largeur `W`
est **fausse**. Un test qui l'affirmerait serait un test faux qui passe. Ce qui est
testé à la place, c'est l'**additivité** — doubler la densité de points sans changer
les altitudes interpolées ne change pas le temps —, qui attrape une erreur
d'intégration sans affirmer ce qui n'est pas vrai.

**D8 — pourquoi obligatoire, et pourquoi un fichier.** `CurveProvenance` exige trois
champs **non devinables** : `date_from`, `date_to`, `generated_at`. Le CSV de
l'ancien outil ne contient que des nombres. Déduire du nom de fichier (A), c'est
inventer une provenance : le nom n'encode ni la tolérance de FC, ni le type
d'activité, ni la largeur de tranche, et un fichier renommé mentirait en silence.
Des options de ligne de commande (B) seraient à retaper à chaque appel, donc fausses
un jour sur deux, et elles ne vivraient pas avec le fichier. Des valeurs par défaut
(C) sont la pire : elles produisent une projection qui affirme une provenance fausse
**sans le signaler**.

Un fichier compagnon voyage avec la donnée, s'écrit une fois, se lit à l'œil, et
`json` est dans la bibliothèque standard. Il prépare surtout le M6b : l'estimateur
écrira le CSV **et** son compagnon dans le même geste, et `estimator` portera alors
ses vrais paramètres au lieu d'une phrase écrite à la main. Le rendre obligatoire
coûte deux minutes une fois ; le rendre facultatif coûterait une projection dont on
ne peut plus dire sur quoi elle repose — exactement ce que la décision `0001`
cherche à empêcher.

Le **sport** suit le même raisonnement, et c'est pour ça qu'il est dans le même
fichier plutôt qu'en constante. `Sport` n'est pas une étiquette : c'est la famille
de modèle, et appliquer la mauvaise courbe ne lève aucune erreur. Une constante en
dur serait un mensonge le jour de la deuxième courbe ; un défaut `foot` serait le
même mensonge, silencieux ; et déduire de `source_activity_types` serait une
inférence sur une chaîne libre, ce que la décision `0004` refuse précisément.

## Conséquences

**Ce que ça rend facile.** Une projection dit exactement d'où elle vient : la
courbe par son nom **et** son empreinte (`curve_ref = <nom>#<12 premiers caractères
du sha256>` — le nom seul ne suffit pas, deux courbes peuvent le partager), les
paramètres du modèle par son `ParameterSet`, l'échelle de grille par
`profile.build_parameters`. Les diagnostics disent quelle part de la distance et du
temps est passée par le prolongement, ce qui rend D4 vérifiable en usage au lieu
d'être un chemin mort. Une deuxième courbe s'ajoute sans toucher au code.

**Ce que ça rend difficile.** Une courbe sans compagnon ne se lit pas : c'est voulu,
mais c'est un pas de plus à chaque nouvelle courbe. Le seuil de support est un
réglage par défaut d'aujourd'hui, pas un critère justifié — le bon critère serait le
nombre d'activités contributrices et leur dispersion, tous deux absents du fichier.

**Ce qu'il faudra revisiter, et quand.**

- **M4** — le prolongement en descente est peut-être trop conservateur ; l'écart aux
  tranches écartées (jusqu'à −16,5 % à −60 %) est exactement ce qu'un backtest peut
  trancher. Le seuil de support de 10 minutes mérite le même examen.
- **M6b** — réestimer la courbe avec le **même opérateur de pente** que le moteur,
  ce qui supprime le biais de D6 ; et aligner la définition de `sample_count`, où la
  lecture M3 met des secondes de données faute de comptage de points dans le CSV.
- **À chaque nouvelle courbe** — D4 décrit *cette* courbe. Le contrôle a posteriori
  sur les tranches écartées est à refaire.

Ce jalon produit un outil utilisable. **Ce n'est pas un modèle validé** : la mesure
de son erreur est le M4, et rien ici ne doit prétendre le contraire.
