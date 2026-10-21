# 0015 — La figure de Q1

- **Date** : 2026-10-20
- **Statut** : acceptée (AN1-2c)

## Contexte

AN1 se finit sur une figure descriptive de Q1 : « la VAM progresse-t-elle, à pente,
gain et altitude comparables ? » (`docs/analyse/QUESTIONS.md`). Descriptive veut dire
exploratoire : pas d'estimation, pas d'intervalle d'inférence, pas de tendance ; la
question aura son plan, son estimation et ses essais comptés dans un jalon à elle
(`docs/analyse/CHARTE.md`, §§ 6 et 8). La figure doit pourtant se lire sans tromper :
dire ce qu'elle écarte et pourquoi (§ 5 bis), ce qui tient sous les variantes de la
définition de la montée (`0014`, « La stabilité »), et d'où elle vient (§ 10 : la
commande, la version du code, la période, l'empreinte des données, les seuils figés).

Les montées existent (`processed/montees.parquet`, `0014`) : une ligne par montée, son
régime, ses strates, ses drapeaux, sa stabilité. Restent à choisir : l'unité d'un
point, son résumé, la stabilité au niveau de la figure, ce que montre la vue
principale, le rendu, et la forme des résultats. La passe experte d'AN1-2 a proposé un
dessin (une sortie par point, régimes séparés, facettes par strate de pente) ; la
conception l'a retenu, rdw a tranché les points restants.

## Options envisagées

**Le résumé d'un point** (une activité, dans un régime et des strates).

**A. La moyenne des VAM de ses montées.** Couper une montée en deux à un arrêt change
la moyenne sans rien changer à ce qui a été monté.

**B. La médiane.** Même défaut, et instable à deux ou trois montées.

**C. Le rapport des sommes**, `Σ G_M,θc / Σ M_θc` : le gain pris en mouvement de ses
montées, divisé par leur temps en mouvement. Couper une montée sans changer le temps
inclus ne le change pas.

**La stabilité de la figure.**

**A. Retirer les montées instables.** Une montée que les variantes coupent en morceaux
peut être « instable » au sens de `0014` (quand aucun morceau ne la recouvre à 50 %),
alors que le point, qui somme ses morceaux, en garde le gain, au replat qui les sépare
près, tant qu'ils restent dans son panneau et ses strates : la figure perdrait une
grande part des côtes.

**B. Afficher la part de montées instables d'un point.** Même confusion entre la montée
et le point.

**C. La stabilité du point**, recalculée sous chaque variante sur les montées de la
variante : le critère de la montée, transposé. Elle demande les montées des variantes,
que la stabilité des montées calcule déjà et jette.

**Où vivent les montées des variantes.**

**A. Recalculées par la figure depuis `interim/`.** La figure relirait `interim/` et
referait la chaîne ; elle ne lirait plus seulement `processed/`.

**B. Une troisième table de `processed/`**, écrite par `mperf tables` avec les deux
autres.

**La tendance.** **A.** Une courbe lissée par panneau (LOESS) ; **B.** aucune.

**Le rendu.** **A.** Une image fixe (matplotlib, hors des bibliothèques de `0011`) ;
**B.** une page HTML autonome par plotly (retenu par `0011`), le détail d'un point au
survol.

## Décision

Résumé **C** ; stabilité **C** ; montées des variantes **B** ; pas de tendance (**B**,
décision de rdw) ; rendu **B**. `mperf q1`, extra `analyse`, écrit un dossier de
résultats jamais réécrit.

### La table des variantes

`processed/variantes.parquet` (`ClimbVariantRow`) : une ligne par montée retenue de
chaque variante déclarée de la définition, pour une activité qui a au moins une montée
de référence ; ses bornes en temps, `G`, `G_M,θc`, `M_θc`, et son régime, ses strates
et ses drapeaux sous les paramètres de la variante. Rien n'est recalculé : ce sont les
montées que la stabilité des montées obtient déjà. Clé `(activity_ref, variant,
start_offset_s)`. Les trois tables portent la même provenance, qui gagne le compte des
variantes et le commit du code ; elles prennent ensemble la place de `processed/`
(`0014`, « Précisions d'AN1-2c »).

### Les points

Trois panneaux, qui ne se comparent pas entre eux : (a) montées longues, (b) côtes,
(c) ski de randonnée. Les intermédiaires, le ski court et les autres sports restent au
flux. Un point est une activité × un panneau × une strate de pente × une strate
d'altitude, placé à la date et l'heure locales de départ de l'activité ; il porte le
nombre de ses montées, `Σ G_M,θc`, `Σ M_θc`, son résumé (option C), et l'enveloppe des
horloges : la plus petite et la plus grande des dix valeurs `Σ G_M,θ / Σ M_θ` et
`Σ (G_M + G_U)_θ / Σ (M + U)_θ` sur les cinq conventions (au survol seulement ; ce n'est
pas un intervalle).

**Vue principale** : les montées du régime du panneau, sauf les montées marquées, les
montées d'une activité à plusieurs sessions (le sport d'une session n'est relié à aucun
régime) et les montées sans strate ; chaque exclusion est comptée au flux, chaque
drapeau à part. **Vue de sensibilité** : les mêmes points, sur les seules montées
stables. Une facette (une strate de pente d'un panneau) qui compte moins de `N`
activités distinctes, celles dont un point y a un résumé positif, ne s'affiche pas
(`N` = 5, paramètre déclaré), dans chaque vue ; un point dont le résumé n'est pas
positif ne se place pas sur l'axe logarithmique ; les deux sont comptés au flux.

### La stabilité du point

Pour chaque variante `v`, la part de chaque montée du point couverte en temps écoulé
par la réunion des montées de `v` de la même activité, non marquées, du même panneau
et des mêmes strates ; `kept_v`, le gain du point pondéré par ces parts, divisé par
`Σ G_M,θc`. Le point est **retrouvé** dans `v` si `kept_v ≥ 0,8` ; son résumé sous `v`
est le rapport des sommes des montées de `v` de l'activité, non marquées, du même
panneau et des mêmes strates (le point tel que `v` le dessinerait). Il est **stable**
s'il est retrouvé dans au moins 80 % des variantes et si l'écart relatif de son résumé
y reste sous 5 % ; comme pour la montée, une variante qui le retrouve sans résumé (sans
temps en M) n'entre pas dans l'écart.
Le régime et les strates d'une montée de `v` se lisent sur elle, sous les paramètres
de `v`. Une montée que `v` coupe en deux reste couverte si ses morceaux restent dans
le panneau et les strates du point, au temps qui les sépare près : le replat ou la
contre-pente où `v` coupe, et tout arrêt qui s'y trouve, comptent comme perdus, si
bien qu'un long arrêt à cet endroit peut faire que `v` ne retrouve plus le point ; et
le résumé sous `v` ne compte plus le temps ni le gain de ce replat. Un morceau qui
sort du panneau ou des strates du point ne le couvre plus, comme une montée que `v`
marque, ou qu'elle réunit à une autre en une montée d'un autre régime. Ainsi, un
morceau dont le gain est sous celui qui ouvre le panneau en sort, même quand la
montée entière y était. Le symbole creux dit donc qu'une variante dessinerait le
point autrement, avec moins de gain dans son panneau et ses strates ou une autre VAM,
ou qu'elle en coupe une montée en morceaux que sépare un temps long, un arrêt par
exemple. Les trois seuils sont déclarés (`Q1_PARAMETER_SPECS`). La part du gain
retrouvée, 0,8, est propre au point (une montée est retrouvée à un recouvrement de
0,5, `0014`) ; la part des variantes, 0,8, et l'écart, 5 %, reprennent les valeurs de
la stabilité des montées, sans en dépendre.

### Le flux

Une ligne par mois (date locale de départ) pour toutes les activités : entrées de
l'index, avec vue, à plusieurs sessions ; puis une ligne par mois et par panneau :
montées du régime, marquées (et par drapeau), d'une activité à plusieurs sessions, sans
strate, gardées (dont instables) ; points de la vue principale (dont instables, parmi
les montrés), cachés, au résumé non positif ; points de la vue de sensibilité, cachés,
au résumé non positif (un point de la vue principale sans montée stable n'y est pas).
La part des exclusions selon le mois (charte, § 5 bis) s'y lit.

### La figure

Une page HTML autonome, plotly.js inclus une fois, deux figures (vue principale, vue de
sensibilité), même dessin : une rangée par panneau, une colonne par strate de pente ; x,
la date et l'heure locales de départ, même étendue partout (la période, du premier au
dernier départ en heure murale locale) ; y, la VAM en m/h (conversion à
l'affichage), échelle logarithmique, même étendue pour les facettes d'un panneau et pour
les deux vues, aucun axe commun entre panneaux ; la couleur dit la strate d'altitude, la
taille `Σ M_θc` (un diamètre de 6 à 18 px, affine en sa racine, sur une seule échelle
pour les deux vues : le plancher garde visibles les plus petits points, et l'aire
n'est pas proportionnelle au temps), le symbole la stabilité du point (creux :
instable ; vue principale seulement) ; un trait pointillé à chaque changement de
montre (fabricant et produit, entre deux activités enregistrées consécutives qui les
disent tous deux). Une facette cachée porte sa mention (« moins de N activités », ou
« aucun résumé positif ») ; une facette sans point reste vide. Un en-tête dit la
période, l'empreinte d'`interim/`, et que la figure est descriptive. Le rendu est
déterministe : les mêmes entrées donnent les mêmes octets.

### Les résultats

`MPA_DATA_DIR/resultats/Q1/<date>_<empreinte>/` : `figure.html`, `points.csv`,
`flux.csv` et `provenance.json` (la question, la commande, le commit et la version du
paquet, la date de génération, la période, la provenance des tables lues, les
paramètres de la figure, le SHA-256 de chaque fichier). `<date>` est la date locale de
génération ; `<empreinte>`, les douze premiers chiffres du SHA-256 de la provenance sans
cette date : les mêmes tables, le même code et les mêmes paramètres donnent la même
empreinte. Un dossier qui existe déjà n'est jamais réécrit ; un dossier s'écrit sous un
nom temporaire, puis prend le sien.

### La commande

`mperf q1` (`just q1`) : l'état git du paquet (un clone modifié est refusé, comme
`just backtest`), les tables de `processed/` (des tables d'avant AN1-2c, une table qui
manque ou qui ne se relit pas sont refusées, avec un message qui dit de relancer
`just process`), la figure, le dossier. L'état git (`src/mountain_perf/gitstate.py`) est rendu commun au
moteur et à la piste ; `backtest/execution.py` garde ses messages. Le hook de
`.claude/settings.json` refuse la commande à Claude Code : elle écrit sous
`MPA_DATA_DIR`. **`analyse/plot.py` est le seul module qui importe plotly**, tests
compris (`ruff`, TID251) ; le calcul (`analyse/q1.py`) et l'écriture des résultats
(`analyse/results.py`) sont en Python pur.

## Pourquoi

- **Le rapport des sommes** : c'est la seule des trois lectures qu'une coupe ne change
  pas. Le cas de l'expert : une montée de 300 m coupée en deux à un arrêt, deux moitiés
  montées à 700 et 500 m/h ; la moyenne dit 600 m/h, le rapport des sommes environ
  583 m/h, comme la montée entière.
- **Une activité par point, pas une montée** : les montées d'une même sortie ne sont pas
  indépendantes (même jour, même forme, même chaleur) ; un point par montée donnerait à
  une sortie riche en côtes un poids qu'elle n'a pas. La strate d'altitude reste dans le
  point, parce que l'altitude est une confusion de Q1.
- **La stabilité du point plutôt que celle des montées** : le critère de `0014` juge
  la montée, qu'une variante peut couper en morceaux qui restent dans le panneau et
  les strates du point : la montée peut alors être instable, et le point ne pas
  l'être. Le transposer garde son sens (« la variante retrouve-t-elle ce que je
  dessine ? ») au niveau de ce qui est dessiné, et deux de ses trois seuils. Retirer
  les montées instables reste regardable, comme sensibilité
  (la seconde vue), pas comme vue principale.
- **Une troisième table** : la figure ne lit que `processed/`, comme toute question ;
  la stabilité des montées calcule déjà les montées des variantes, et les garder coûte
  une table, pas un calcul.
- **Pas de tendance** : une courbe lissée est une estimation sans intervalle ni essai
  compté ; elle se lirait comme un résultat. L'œil voit déjà la forme du nuage ; la
  tendance viendra avec le plan de Q1.
- **Le seuil de facette** : en dessous de cinq activités, une facette se lit comme une
  série de points isolés, et chaque point y pèse trop ; la règle se compte au flux et se
  déclare, elle se change avec rdw.
- **Le commit dans les tables et dans les résultats** : la charte demande la version du
  code ; la version du paquet ne change pas d'un commit à l'autre. Les résultats portent
  les deux commits (celui des tables, celui de la figure) ; `mperf q1` ne refuse pas des
  tables d'un autre commit, il le dit.

## Conséquences

- **Facile** : relancer la figure à chaque mise à jour des données (`just process`,
  puis `just q1`) ; retrouver, par `provenance.json`, de quelles tables, de quel code et
  de quels seuils vient une figure ; relire `points.csv` et `flux.csv` sans plotly.
- **Garde-fou « déjà vu »** (charte, § 6) : la figure montre la VAM selon la date. Une
  fois regardée sur les données réelles, la relation de Q1 est « déjà vue » : rdw la
  note dans `resultats/deja_vu.csv`, et le plan de Q1 en tiendra compte.
- **Non promis** : une tendance, un effet, un intervalle ; la comparabilité entre
  montres (le trait pointillé la signale, il ne la corrige pas) ; un point stable quand
  sa facette est cachée (sa stabilité se calcule, elle ne se montre pas).
- **À revisiter** : le seuil de facette et les seuils de la stabilité du point, avec
  le plan de Q1, comme la part couverte lue en temps écoulé (un long arrêt à l'endroit
  d'une coupe peut faire manquer le point à la variante qui coupe, ou retirer cette
  variante de l'écart ; le temps entre deux montées d'une variante pourrait ne compter
  ni pour ni contre) ; une vue par sport à l'intérieur d'un panneau, si un panneau mêle
  des sports qui ne se comparent pas ; le résumé, si la question passe de la sortie à
  la montée.
