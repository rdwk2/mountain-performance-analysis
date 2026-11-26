# 0025 — La courbe en couches

- **Date** : 2026-11-24
- **Statut** : acceptée

## Contexte

La courbe allure ↔ pente mêle deux choses : sa **forme**, les vitesses relatives d'une
pente à l'autre, stables et gourmandes en données ; et son **niveau**, un facteur commun,
qui évolue avec la saison, la progression ou une blessure. Le chantier de la courbe en
couches (décision de rdw du 2026-11-23) les sépare, chacune jugée à part : la forme se lit
sur un an, le niveau se tire vers les dernières semaines ; viendront ensuite un facteur
de durée appris sur l'athlète (la couche 2) et le fade (la couche 3).

La couche 1 est une **règle de base**, pas un effet (`0010`, précision OG-2, point 6) :
elle fait la courbe `κ_j` de chaque performance, lit toutes les activités finies avant
`o_j` des types choisis, courses comprises, et se compare aux fenêtres comme elles se
comparent entre elles : une DÉCLARATION par règle, puis le rapport de comparaison. Elle
s'ajoute aux fenêtres de la règle à l'origine (`0020`, O2) comme un choix de plus ; **le
défaut reste 56 jours** jusqu'à une exécution comparée, puis une décision de rdw.

## Décision

**La règle `layered`, « en couches ».** À une origine `o`, la courbe en couches est la
courbe que la règle à l'origine rend pour la fenêtre de 365 jours, dont chaque vitesse de
tranche (`speed_ms`) est multipliée par `s = exp(−κ·Δ)`, et les quantiles du niveau
décalés de `−κ·Δ` ; tout le reste (le support, les comptes, les vitesses écoulées, les
diagnostics) est celui de la courbe de 365 jours. Rien de la règle n'est recodé : la
sélection, l'estimation, la borne basse et les décisions sur les fins sont celles de
`0020`, sous la fenêtre de 365 jours.

**Trois constantes** (`estimation/decision.py`), que ni l'utilisateur ni le registre ne
règlent : la fenêtre de forme, `LAYERED_SHAPE_DAYS = 365` jours ; la fenêtre de niveau,
`LAYERED_LEVEL_DAYS = 56` jours ; `LAYERED_KAPPA = κ = ½`.

**L'écart récent `Δ`, par un ajustement joint des niveaux** (`estimation/levels.py`).
Les activités de l'ajustement sont les retenues de la courbe de 365 jours qui ont au
moins une cellule de temps M positif ; `c` les numérote dans l'ordre des retenues, `k` est
une tranche de pente (les 38 de `0017`). `ℓ_ck` et `T_ck` sont la longueur et le temps M
des intervalles retenus de `c` de temps M positif dans la tranche `k` ; `T_c = Σ_k T_ck`
est le poids de `c`. Le modèle : `T_ck ≈ ℓ_ck · exp(−a_c − f_k)`, une vitesse
`exp(a_c + f_k)` par activité et par tranche, ajusté une fois, par ajustement
proportionnel itératif, sur **toutes** les tranches de temps M positif, sans seuil de
support. À la lettre, toute somme par `math.fsum` dans l'ordre dit :

1. `T_c` la somme des temps de `c`, dans l'ordre de ses tranches ; pour chaque tranche
   présente, dans l'ordre croissant, `t_k` et `l_k`, les sommes des temps et des
   longueurs des activités qui l'ont, dans l'ordre des activités ;
2. `u_k = t_k / l_k`, une allure en s/m ;
3. au plus 1 000 tours : `e_c = T_c / Σ_k ℓ_ck u_k`, puis `u'_k = t_k / Σ_c e_c ℓ_ck` ;
   `u` prend `u'`, **puis** l'arrêt si `max_k |ln(u'_k / u_k)| < 10⁻¹⁰` ;
4. après la boucle, `e_c` recalculé avec le `u` final : le temps ajusté de chaque
   activité égale alors son temps, même sans convergence ;
5. `f_k = −ln u_k`, `c₀ = Σ_k t_k f_k / Σ_k t_k`, et le niveau
   **`λ_c = ln e_c − c₀`**, au signe du moteur (`λ_c > 0` : plus lent que la forme, comme
   `λ_j` de `0017`, P4.2).

Le niveau est défini à une constante près, commune à toutes les activités ; seules ses
différences comptent. Avec `λ̄` la moyenne des `λ_c` pesée par `T_c`, sur toutes les
activités de l'ajustement (`λ̄_toutes`) ou sur les récentes (`λ̄_récentes`) :
**`Δ = λ̄_récentes − λ̄_toutes`** ; `Δ > 0` : les 56 derniers jours plus lents que l'année.
Le facteur des vitesses est **`s = exp(−κ·Δ)`** : le niveau est tiré à mi-chemin vers
celui des 56 derniers jours.

**Récente.** Une activité de l'ajustement est récente si la règle de la fenêtre de 56 jours
la garderait candidate : la décision sur la fin de l'index, puis sur la fin sûre (`0020`,
O2 et O3), sous la borne de 56 jours civils à Paris, sur les fins déjà lues ; aucun second
calcul de dates.

**Sans correction, la courbe de 365 jours** (`s = 1`, `Δ` absent, une raison écrite) :
moins de deux activités dans l'ajustement ; ou aucune activité de l'ajustement dans les 56
jours. Toutes récentes : `Δ = 0`, `s = 1`.

**Le compagnon** dit la règle, sous `layered` seulement : la section `origin` porte
`"window": "layered"` et, juste après `lower_bound`, la clé `level_layer` (la fenêtre de
niveau, sa borne basse, `κ`, les activités de l'ajustement et les récentes, `Δ`, `s`, les
tours de la boucle et sa convergence, la raison d'une absence de correction ; `null` pour
une courbe absente) ; la méthode et l'estimateur de la provenance nomment la règle. Sous
une fenêtre, aucune clé et aucun texte ne changent.

**Une limite, dite.** Des activités sans aucune tranche commune (des composantes
disjointes) ont des niveaux relatifs non identifiables : ils sont fixés par le départ de
la boucle (`u_k = t_k / l_k`), non par les données — le même algorithme et le même départ
que le juge du banc.

## Ce que le banc a jugé, et les écarts

La règle s'appelle `DF(365 ; ½)` au banc (la recherche de la conception, sur des archives
publiques de coureurs). Le banc l'écrit `L = L_T365 − ½ (ā₅₆ − ā₃₆₅)`, `L` = ln(prévu /
réel), `ā` des niveaux au signe contraire de `λ` : multiplier le temps prévu par
`exp(−½ (ā₅₆ − ā₃₆₅))`, c'est multiplier les vitesses par `exp(−½ Δ)` avec
`Δ = −(ā₅₆ − ā₃₆₅)`. Le même calcul.

| Ce que le banc fait | Ce que fait le logiciel | Écart |
|---|---|---|
| les sorties lues finies dans les 365 jours avant `o` (au moins 2), temps en mouvement non nul | les retenues de la courbe de 365 jours (les candidates de la règle, après les exclusions de `0017`) qui ont une cellule de temps M positif ; au moins 2 | la sélection du logiciel (types, durées, FC éventuelle) au lieu du prétraitement du banc |
| un seul ajustement de Poisson à lien logarithme, temps attendu `ℓ_ck · exp(−a_c − f_k)`, par ajustement proportionnel itératif ; toutes les tranches de temps non nul, sans seuil de support | le même algorithme, à la lettre, sur les mêmes tranches | aucun (ordre des sommes : `fsum`) |
| le poids d'une sortie : la somme de ses temps en mouvement par tranche | `T_c = Σ_k T_ck` | aucun |
| `ā₃₆₅`, `ā₅₆` : moyennes des niveaux du même ajustement, pesées par le poids ; pas de table de 56 jours | `λ̄_toutes`, `λ̄_récentes`, de même | aucun |
| récente : finie à `o − 56 × 24 h` ou après, `o` à 00:00 UTC de J − 7 | récente : la règle de la fenêtre de 56 jours (`0020` O2, O3 : jours civils de Paris, fins de l'index et fin sûre), `o` à 00:00 à Paris | une à deux heures aux bornes, jamais jugées (comme `0020` O1) |
| aucune sortie dans les 56 jours : la sortie prévue n'est pas jugée | pas de correction : la courbe de 365 jours, `s = 1` | le choix neutre (le banc ne dit rien de ce cas) |
| moins de 2 sorties dans la fenêtre : non jugée | pas de correction, `s = 1` | idem |
| toutes les sorties récentes : `ā₅₆ = ā₃₆₅` | `Δ = 0`, `s = 1` | aucun |
| la courbe d'un an `T(365)` : la vitesse d'une tranche = Σ longueurs / Σ temps, support à 10 min | la courbe de 365 jours du moteur, valeur de la sélection (« somme » ou « médiane »), son support | identique sous « somme » ; la forme du moteur sous « médiane » |
| la longueur d'une tranche : celle des intervalles retenus de temps M positif | `_Cell.length_moving_m` | aucun |
| une sortie n'est jugée que si au moins 20 sorties lues finissent avant son origine, que la courbe de tout le passé et `T(365)` existent | la règle s'applique dès que la courbe de 365 jours existe | le banc ne dit rien des historiques courts ; la règle y est le calcul ci-dessus, sans garde de plus |

**Ce qui est établi, et ce qui ne l'est pas.** Au banc, le niveau à mi-chemin bat la courbe
de tout le passé chez 143 coureurs neufs **sous la forme de tout le passé** (−0,0044
[−0,0075 ; −0,0014] sur `|L|`). Sous la forme d'un an (`DF(365 ; ½)`), il est mesuré sur
des coureurs déjà vus (−0,0029 et −0,0047 contre la courbe d'un an), et lu après coup,
sans déclaration, sur 133 coureurs neufs (−0,0027 [−0,0050 ; −0,0004]) : une description,
pas une confirmation. Une session de confirmation (« E7 »), déclarée d'avance, a jugé
depuis `DF(365 ; ½)` sur 290 coureurs neufs, avec la définition que ce logiciel code :
contre la courbe d'un an, −0,0040 [−0,0060 ; −0,0023] sur `|L|`, **confirmé** ; contre le
niveau à mi-chemin sous la forme de tout le passé, +0,0023 [−0,0006 ; +0,0057] : « pas
pire » (à +0,003 près) **non établi** (après lecture : la même erreur en médiane, l'écart
moyen porté par quelques coureurs ; moins bon que lui à 4 à 7 sorties dans les 56 jours et
au premier passage, des descriptions). À 16 sorties et plus dans les 56 jours, toutes les
prévisions du banc sont de 1,6 à 3,1 % trop lentes, celles du niveau à mi-chemin comprises
(une description).

## Conséquences

**Le registre au format 7** (`0010`, précision OG-2, point 14). Une exécution en couches
écrit son document de règle dans un type neuf, `LayeredRollingRule` (les champs de
`RollingRule`, puis la fenêtre de niveau et `κ`) ; la DÉCLARATION glissante porte la
fenêtre de niveau et `κ` de sa règle (`null` pour une fenêtre) et la fenêtre de niveau de
chaque règle de la commande. Toute ligne et tout document neufs s'écrivent au format 7 ;
les lignes et documents des formats 1 à 6 se relisent et se réécrivent à l'octet.

**L'accord** vérifie aussi, pour une règle en couches, son document de règle (ses champs
de niveau, ses constantes) et la section de niveau de chaque compagnon : sa fenêtre de
niveau, `κ`, sa borne basse recalculée ; il ne vérifie ni `Δ`, ni le facteur, ni les
comptes de la couche, descriptifs, sans réestimer aucune courbe.

**Ce qui ne change pas** : les fenêtres — leur courbe et son compagnon à l'octet, leur
document de règle au contenu inchangé ; la projection, le calage, les métriques ; la
courbe rendue garde le contrat d'aujourd'hui (`PaceCurve`, `κ_j`), et tout ce qui la lit
en aval marche sans changement.

**La suite** : une exécution comparée des courses passées sous 56 jours et sous
`layered`, ce qu'on y lit écrit avant ; puis la décision du défaut par rdw. La couche 2
(un facteur de durée appris sur l'athlète) amendera cette décision.
