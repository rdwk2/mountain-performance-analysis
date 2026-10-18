# 0014 — Les montées et les tables de `processed/`

- **Date** : 2026-10-17
- **Statut** : acceptée (AN1-2b)

## Contexte

Q1 demande si la vitesse ascensionnelle progresse, à terrain comparable
(`docs/analyse/QUESTIONS.md`). Son unité est la montée. La charte en fixait trois
choses : une montée est un segment du profil du moteur ; sa définition doit être
robuste, avec un contrôle de stabilité ; une montée trop courte pour son pas
d'échantillonnage est écartée (`docs/analyse/CHARTE.md`, § 2). Elle fixait aussi
qu'une valeur que l'athlète ne déclare pas se calcule depuis ses données (§ 3).

Le temps de mouvement est celui du moteur : la partition M/S/U de `0010` D5, sous
cinq conventions, la centrale θc et quatre autres en sensibilité, sur l'altitude
lissée par bloc `z̃` de D4.4. AN1-2a l'a rendue commune (`src/mountain_perf/series.py`
et `clocks.py`) sans en changer une ligne.

Une passe experte sur la définition de la montée, appuyée sur des cas synthétiques et
sur des propriétés de la définition mesurées sur un export, a montré trois défauts
d'une définition naïve (le D+ du profil divisé par le temps de mouvement, bornes et
gain pris sur le profil, régimes par la durée) :

- **le gain d'un temps exclu** : le D+ gagné pendant une pause, un trou ou un arrêt
  entre au numérateur, alors que son temps n'est pas au dénominateur
  (`docs/PIEGES_DATA.md`) ;
- **les bornes sur le profil lissé** : le lissage rabote le sommet d'une côte courte
  et les bornes y englobent une part des replats voisins. La VAM d'une côte est
  sous-estimée, d'autant plus que la côte est courte : un changement de la taille des
  côtes au fil des mois ressemblerait à une tendance ;
- **la durée comme critère** : à gain égal, une montée lente dure plus longtemps.
  Classer ou filtrer les montées par leur durée, c'est sélectionner sur la mesure
  étudiée. La règle de la charte (« une durée d'au moins 30 pas ») en est une.

Elle a aussi listé ce qu'une définition doit voir sans le corriger : une remontée
mécanique, un saut d'altitude, une altitude sans baromètre, un baromètre qui dérive sur
une boucle, des lacets si serrés que la pente lue ne dit rien, un GPS qui erre pendant
un arrêt.

Restent à fixer : la montée (détection, bornes, gain) ; sa VAM ; ses régimes ; ce que
l'athlète déclare ; sa stabilité ; les tables, leur format et la commande qui les
écrit.

## Options envisagées

**La VAM.**

**A. Le D+ du profil divisé par le temps M.** La lecture littérale de
`docs/PIEGES_DATA.md`. Le gain d'un trou ou d'une pause entre au numérateur sans son
temps.

**B. Le gain pris en mouvement divisé par le temps en mouvement**, `G_M,θc / M_θc` :
l'horloge du gain somme les variations de `z̃` sur les intervalles d'état M de la
partition, comme l'horloge du temps somme leurs durées. Gain et temps sur le même
support.

**C. Le gain divisé par le « temps de progression »** (`M` moins le temps M passé
lentement et sans gain). Il retire un GPS qui erre pendant un arrêt, mais aussi le
temps lent réel d'une conversion à ski ou d'un passage délicat.

**Le domaine.**

**A. Tout sur le profil** (grille à pas fixe en distance) : le défaut des bornes.

**B. Tout en temps** : la détection sur une série bruitée, sans le profil que la charte
impose et que le moteur partage.

**C. Mixte** : la détection sur le profil du moteur ; les bornes et le gain en temps,
sur `z̃`, près des bornes du profil.

**Les régimes.**

**A. Par la durée** (côtes courtes, montées longues) : une sélection sur la mesure.

**B. Par le gain, avec une vitesse de référence calculée sur les VAM de l'athlète** :
la frontière dépend encore de la mesure.

**C. Par le gain, avec une vitesse de référence déclarée** (`V_ref`, dans
`athlete.toml`, défaut du projet) : la frontière ne dépend que du terrain et d'une
déclaration.

**Le stockage des tables.** Parquet par pyarrow (extra `analyse`, `0011`) ; ou le
codec commun en JSON, sans dépendance, mais une table d'analyse se lit par colonnes, et
les notebooks de `0012` la liront par pandas.

## Décision

**VAM B, domaine C, régimes C** ; des pentes lues chacune sur un seul support ;
une stabilité par variantes déclarées ; deux tables Parquet écrites par `mperf tables`,
régénérées par `just process`.

### La montée

La chaîne est écrite dans `src/mountain_perf/analyse/climbs.py`, paramètre par
paramètre (`CLIMB_PARAMETER_SPECS`). En résumé :

1. **La vue et ses horloges** : la vue positions et altitude de l'enregistrement
   (`stream_view`, `0013`), ses blocs, `z̃` et la partition M/S/U sous les cinq
   conventions, par les modules communs ; jamais par `mountain_perf.backtest`.
2. **La détection, sur le profil du moteur** (`gpx/profile.py`, défauts de `0008`),
   construit sur les mêmes positions et altitudes : hystérésis sur l'altitude du
   profil lissé (une contre-pente de moins de 10 m sur ce profil reste dans la
   montée ; le lissage atténue une contre-pente courte et raide, qui peut être plus
   profonde sur le terrain) ; une détection relâchée : une montée du profil dont le
   gain atteint la moitié du gain minimal `D_min` (point 4) est mesurée, car le lissage
   rabote les côtes courtes, dont le gain se juge ensuite en temps ; un replat (des
   pas de grille de pente sous 2 %) coupe si la distance parcourue en mouvement
   pendant lui atteint 250 m en longueur vraie (le seuil retranche ce que le lissage
   étale), à l'arrondi près comme en `0010` D5.2 (aux défauts, le seuil vaut trois pas
   de grille, qu'un replat parcouru tout entier en mouvement atteint au dernier
   chiffre près : sans la tolérance, l'arrondi des fonctions trigonométriques en
   déciderait, d'une plateforme à l'autre), et si son temps en mouvement dépasse un
   dixième de celui du plus court des deux morceaux qu'il sépare ; les fusions vont
   du replat le plus léger au plus lourd.
3. **Les bornes et le gain, en temps** : sur `z̃`, près de chaque borne du profil (à
   moins de `w_eff`), le dernier instant à 1 m du minimum et le premier à 1 m du
   maximum. Puis un replat, même montant, reste hors de la montée : la borne de départ
   avance tant que `z̃` monte de moins de 2 % (la pente d'un replat) sur le pas de
   grille de distance réalisée qui la suit, et se place, dans le premier pas qui monte
   d'au moins autant, au dernier instant à 1 m du minimum de ce pas ; la borne d'arrivée
   recule de même, au premier instant à 1 m du maximum de son pas. Sans ce
   resserrement, la tolérance lue sur toute la fenêtre posait la borne au bout d'un
   replat qui monte de 1 à 2 %, jusqu'à 200 m hors de la montée : la VAM s'y diluait, et
   la coupe du point 2 ne lisait plus le temps du replat (constat 1 de la relecture de
   la PR #31). Le resserrement se lit à un pas de grille près, et au bruit de `z̃`
   près : un bout de replat plus court qu'un pas peut rester dans la montée (quand la
   tolérance lue sur la fenêtre pose déjà la borne à moins d'un pas du pied ou du haut,
   ce que font un replat à peine montant, le bruit ou un enregistrement espacé), et près
   de 2 % le bruit de l'altitude sur un pas décide s'il monte assez. Les variantes de la
   stabilité (pente des replats à ± 1 point, tolérance, grille) en marquent une partie ;
   un bout qui ôte moins de 5 % à la VAM laisse la montée stable. Le gain `G` est le
   maximum moins le minimum de `z̃` là où les bornes se placent. La clé d'une montée est son
   instant de départ.
4. **Les filtres, sur les mesures** : un gain d'au moins
   `D_min_eff = max(D_min ; n × pas × V_haute)`, avec `D_min` = 20 m, `n` = 30 pas et
   `V_haute` = 2 000 m/h (une vitesse ascensionnelle soutenue de très haut niveau : la
   montée dure au moins 30 pas même à cette vitesse ; le pas est l'intervalle médian
   de la montée) ; une longueur parcourue en M positive ; une pente au-dessus de 5 %
   (le seuil « montée » de `0010` D6), lue sur toute la montée :
   `z̃(t_b*) − z̃(t_a*)` divisée par la distance réalisée `d_r` de `0010` entre les
   mêmes instants, trous compris. Une montée dont le gain est pris en partie hors de M
   (un trou, un arrêt) reste donc dans la table ; un drapeau la marque quand cette part
   dépasse son seuil, ou quand sa pente en M ne dépasse plus la pente minimale
   (« pente non résolue »). Une montée sans aucune
   longueur parcourue en M (tout son gain dans un trou) n'a ni pente en M ni VAM : elle
   est écartée, et le D+ du canal d'altitude pendant les trous reste dans la table
   `activites`.

La durée n'entre dans aucun filtre : elle reste un contrôle (le pas médian et le plus
long intervalle de la montée sont des colonnes).

### Ses mesures

- **VAM principale** : `G_M,θc / M_θc`. Les états viennent de la partition de `0010`
  D5, lue sans la changer ; l'horloge du gain est une fonction de la piste qui la lit.
- **Variante** : `(G_M + G_U) / (M + U)` sous θc. **Enveloppe** : la plus petite et la
  plus grande des deux formes sur les cinq conventions.
- **Le temps M lent** : le temps des intervalles M (θc) dont la fenêtre de `0010` D5
  va au plus à 0,03 m/s verticalement (le seuil de θc) et à 0,30 m/s
  horizontalement (trois fois celui de θc), deux paramètres déclarés ; comparaisons
  brutes, sans la tolérance d'arrondi de D5.2. C'est un GPS qui erre pendant un arrêt
  que M a gardé, ou une progression lente sans gain. **Le temps de progression**
  (`M` moins le temps M lent) reste une sensibilité, pas la VAM principale.
- **La pente de la montée** (colonne `grade`, strates) : `G_M,θc / L_M`, le gain et la
  longueur parcourue des mêmes intervalles M, ceux de la VAM.
- **Deux pentes, chacune sur un seul support.** Le rapport `G / L_M` de la passe
  experte mêlait deux supports : `G` est pris aux extrêmes de `z̃` près des bornes, à
  la tolérance près ; `L_M`, entre les deux instants. Il surestimait de
  `2 × tolérance / G` la pente d'une côte courte, au voisinage de la pente minimale.
  La strate lit la pente des intervalles M, comme la VAM ; le filtre lit celle de toute
  la montée, pour ne pas retirer sans le dire une montée dont le gain est pris hors de
  M.
- **Contexte** : sport, heure locale, appareil, baromètre ; altitudes, sinuosité,
  déplacement net ; ce qui précède la montée (temps M, D+ et D− du profil) ; FC en M
  et sa couverture, FC de la seconde moitié, température.

### Régimes, strates et drapeaux

- **Régimes, par le gain** (`ClimbRegime`) : à pied, côtes jusqu'à `V_ref × 5 min`,
  montées longues dès `V_ref × 15 min`, intermédiaires entre les deux (dans la table,
  dans aucun panneau de la figure de Q1) ; ski de randonnée au-delà de `V_ref × 5 min`,
  et en dessous à part ; tout autre sport, ou un type sans famille, à part.
- **`V_ref` se déclare** dans la table `[analyse]` d'`athlete.toml` (en m/h), défaut du
  projet 900 m/h, et ne se calcule pas sur les données : **exception à la charte**
  (§ 3), pour que les régimes ne dépendent pas de la mesure. `athlete.toml` peut aussi
  déclarer les produits (fabricant et numéro de produit du FIT, jamais un numéro de
  série) qui portent un baromètre, pour les fichiers qui ne le décrivent pas.
- **Strates** : pente (`G_M,θc / L_M`) de la pente minimale à 15 %, de 15 à 30 %,
  au-delà ; « non résolue » au-delà d'une sinuosité de 6, ou quand la pente en M ne
  dépasse pas la pente minimale (une part du gain est alors prise hors de M). Altitude
  moyenne en M : sous 1 500 m, de 1 500 à 2 500 m, au-delà.
- **Drapeaux** (`ClimbFlag`), qui marquent sans retirer : gain hors de M au-delà de
  20 % ; temps M lent au-delà de 10 % ; non humaine (VAM au-delà de 3 000 m/h, ou à
  pied une vitesse horizontale en M au-delà de 10 m/s) ; pic (une variation d'altitude
  brute au-delà de 3 m/s entre deux enregistrements) ; pente non résolue (la strate
  « non résolue », par la même règle) ; altitude
  non barométrique ; dérive altimétrique (une boucle, arrivée à moins de 50 m du
  départ, dont la fermeture altimétrique dépasse 5 m/h).

Tous les seuils sont des paramètres déclarés (`CLIMB_PARAMETER_SPECS`,
`QUALITY_PARAMETER_SPECS`, `REGIME_PARAMETER_SPECS`, `STABILITY_PARAMETER_SPECS`),
communs à tous les athlètes, sauf `V_ref`, et la provenance des tables les porte
tous.

### La stabilité

Chaque régénération recalcule la chaîne sous douze variantes déclarées, une à la fois
(`analyse/stability.py`) : hystérésis, longueur des replats, rapport de temps des
replats et tolérance des bornes, chacun divisé et multiplié par deux ; pente des
replats à ± 1 point ; lissage du profil sur 250 m (cinq points de la grille par
défaut : la variante fixe les mètres) ; grille de 25 m. Une montée est retrouvée dans
une variante si une montée de la variante la recouvre en temps avec un indice de
Jaccard d'au moins 0,5. Elle est **stable** si elle est retrouvée dans au
moins 80 % des variantes et si l'écart relatif de sa VAM principale y reste sous 5 %.
Une montée instable est marquée (colonne `stable`), jamais retirée. La stabilité au
niveau de la figure vient avec elle (AN1-2c).

### Les tables

- **`processed/activites.parquet`** (`ActivityRow`) : une ligne par entrée de l'index
  de l'export, de tout type, avec ou sans enregistrement : les valeurs de l'index
  (préfixe `index_`, jamais recalculées), les horloges, le pas, les trous, les pauses,
  la boucle, l'appareil, la FC moyenne, et les comptes de montées par régime.
- **`processed/montees.parquet`** (`ClimbRow`) : une ligne par montée retenue, clé
  `(activity_ref, start_offset_s)` ; les colonnes par convention sont des listes de
  cinq valeurs, dans l'ordre de `CLOCK_CONVENTIONS`.
- **La provenance** (`ProcessedProvenance`), dans les métadonnées des deux fichiers :
  l'empreinte d'`interim/activities/`, la version du paquet, `V_ref` et sa source,
  les produits déclarés barométriques, tous les paramètres de la définition, les
  comptes. Aucun instant de génération : le même `interim/`, le même code, le même
  `athlete.toml` et la même version de pyarrow (celle de `uv.lock`) écrivent les mêmes
  octets sur la même plateforme. D'une plateforme à l'autre (Windows, Linux), les fonctions
  trigonométriques du système peuvent différer d'une unité du dernier chiffre, et les
  valeurs qui en dépendent dans leurs derniers chiffres : deux plateformes se
  comparent valeur par valeur, à une tolérance relative. La version du paquet ne
  distingue pas deux états du code (`BACKLOG`).
- Les contrats sont dans `src/mountain_perf/schemas/processed.py`, publiés par le
  dictionnaire de données. Le calcul (`analyse/tables.py`) est en Python pur ;
  **`analyse/parquet.py` est le seul module qui importe pyarrow**, tests compris
  (`ruff`, TID251). Un instant local s'écrit en deux colonnes : l'heure murale, sans
  fuseau, et son décalage en secondes.

### Les commandes

- **`mperf tables`** : `MPA_DATA_DIR/interim/` → `MPA_DATA_DIR/processed/`, avec
  l'extra `analyse` (pyarrow) ; sans lui, un message dit comment l'installer. Les
  deux fichiers s'écrivent sous un nom temporaire, puis se mettent en place.
- **`just process`** : l'ingestion (`mperf ingest`, extra `ingest`), puis
  `mperf tables` (extra `analyse`) : la commande qui régénère `interim/` et
  `processed/` depuis `raw/`.
- Le hook de `.claude/settings.json` refuse les deux à Claude Code, comme
  `just ingest` : elles écrivent sous `MPA_DATA_DIR`.

L'extra `analyse` ne prend que pyarrow ; plotly viendra avec la figure (AN1-2c),
pandas, numpy et le groupe `analyse-dev` avec la première question qui en aura
besoin.

## Pourquoi

- **VAM B** : c'est la lecture exacte de « le D+ gagné pendant une pause ne se divise
  pas par un temps de mouvement qui l'exclut ». Sur les cas synthétiques de la passe
  experte (une montée coupée d'un trou), A s'écarte de la VAM vraie et B la retrouve.
  **C est écartée** comme mesure principale : elle retirerait le temps lent réel du ski
  de randonnée ; elle reste une sensibilité, et le drapeau du temps M lent marque le
  GPS qui erre.
- **Domaine C** : sur une côte pointue synthétique entre deux replats, A sous-estime la
  VAM d'autant plus que la côte est courte, C la retrouve, même entre deux replats qui
  montent de moins de 2 % (point 3). B perdrait le profil commun
  avec le moteur, que la charte impose et dont la détection a besoin (une grille à pas
  fixe, lissée).
- **Régimes C** : A sélectionne sur la mesure ; B aussi, d'un cran plus loin (un
  athlète qui progresse verrait la frontière de ses régimes bouger avec sa VAM, et
  des montées changer de régime). Une vitesse déclarée
  rend la frontière indépendante de la mesure ; son défaut convient à un athlète
  entraîné, et la provenance dit si elle a été déclarée.
- **La règle des 30 pas devient un filtre par le gain** pour la même raison : la durée
  d'une montée dépend de la VAM ; le gain minimal relatif au pas garde l'intention de
  la charte (une erreur de durée bornée par le pas) sans sélectionner sur la mesure.
- **Les pentes sur un seul support** : même leçon que pour la VAM ; un rapport se lit
  sur un seul support. Le filtre sur toute la montée, plutôt que sur les intervalles
  M : une montée dont le gain tombe dans un trou a une pente faible en M ; la retirer
  ferait disparaître sans motif ce que le drapeau du gain hors de M doit montrer.
- **Le seuil du temps M lent à 10 %** plutôt que 5 % : à 5 %, il marquerait le temps
  lent réel du ski de randonnée ; à 10 %, il marque encore un GPS qui erre pendant un
  arrêt (le cas de la passe experte).
- **Marquer sans retirer** : la figure dit, par motif, ce qu'elle écarte de sa vue
  principale ; une table qui retirerait déciderait à la place de la question.
- **Parquet par pyarrow** : `0011` l'avait retenu ; une table d'analyse se lit par
  colonnes, et le codec JSON garde son rôle (`interim/`, le registre du moteur).

## Conséquences

- **Facile** : régénérer `processed/` depuis `interim/` (`mperf tables`), ou tout
  depuis `raw/` (`just process`) ; relire une table sans rien recalculer ; savoir, par
  la provenance, de quel `interim/` et de quels paramètres elle vient.
- **Le moteur ne lit jamais `processed/`** (charte, § 2) ; `analyse/` n'importe jamais
  `mountain_perf.backtest`, et le moteur n'importe pas `analyse/` (tests de
  `tests/test_analyse_imports.py`).
- **Une colonne `rank` n'est pas un identifiant** : changer la définition change les
  rangs. La clé est l'instant de départ.
- **Non promis** : une VAM juste sans baromètre attesté ; la FC d'une côte de moins
  de deux minutes ; une pente lue quand la strate est « non résolue » ; que S soit un
  arrêt réel (le détecteur de `0010` n'est pas validé) ; la comparabilité entre
  montres ; une charge ; les descentes et les plats ; l'alpinisme, la via ferrata et
  l'escalade à l'échelle d'un ressaut.
- **À revisiter** : les seuils, quand une autre montre ou un autre athlète passera par
  la chaîne ; les variantes de la stabilité, si une variante instable domine ; les
  trous de D4.4 en enregistrement « intelligent » (`BACKLOG`, M6b) ; DuckDB si
  `processed/` dépasse la mémoire (`0011`).
