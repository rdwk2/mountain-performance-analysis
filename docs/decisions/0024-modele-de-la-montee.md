# 0024 — Le modèle de la montée des tableaux de bord

- **Date** : 2026-11-23
- **Statut** : acceptée

## Contexte

AN4 donne à la piste des tableaux de bord qui se recalculent à l'affichage depuis
`processed/`, sans verdict (charte, § 8), sur la Fenêtre commune (`0019`, section
AN4-1). Les pages de la montée et du déclin (AN4-2b, AN4-3) montrent la VAM à FC égale
au fil des jours, selon la FC, selon l'altitude et selon le D+ de la sortie. Trois
contraintes pèsent : une sortie compte peu de montées, souvent une seule ; les montées
d'une même sortie partagent la forme du jour, la météo, le sommeil ; le niveau de
l'athlète suit la saison, et avec lui la FC moyenne et l'altitude des sorties. Une
fenêtre de quelques semaines ne porte qu'une poignée de sorties.

## Options envisagées

**A. Un modèle par Fenêtre, seul.** Simple ; mais sur une poignée de sorties, l'effet de
la FC et le déclin selon le D+ ne s'estiment pas, et changent d'une Fenêtre à l'autre
sans raison.

**B. Un modèle mixte au niveau des montées** (effet aléatoire de sortie, pente
aléatoire, charte § 4 bis.1), écrit dans `inference/`. Il tire aussi l'effet de la FC
des écarts entre sorties, que la saison confond (une sortie d'été est plus rapide et
d'une autre FC moyenne) ; il demande un modèle mixte neuf dans `inference/` et un
ajustement lourd à chaque affichage.

**C. Trois étages, le premier en deux temps.** La structure lue dans la sortie, sur
toute l'histoire ; la Fenêtre mêlée à l'histoire par un poids ; le niveau de chaque jour,
lissé ; avec les outils qui existent (`linear.py`, `reml.py`, `clusters.py`), plus les
degrés de liberté de Bell-McCaffrey.

## Décision

C : un paquet `analyse/ascent/`, Python pur, sans numpy, qui appelle `inference/` ; deux
fonctions s'y ajoutent, les degrés de liberté de Bell-McCaffrey et l'intervalle CR2 qui
les emploie (`clusters.py`, `0021`).

## Conventions

**Échelle et unités.** Tout se calcule sur `y = ln(VAM)`, la VAM en m/s ; le D+ et
l'altitude en km (pentes par 1 000 m) ; le temps en mois de `365,25 / 12` jours. Une
sortie est une activité ; son jour, celui de son départ, au décalage local.

**La sélection.** Les montées longues et intermédiaires ; écartées, dans l'ordre, au
premier motif : `plusieurs_sessions`, `regime_non_retenu`, `drapeau_exclu` (les six
drapeaux de Q2), `vitesse_absente`, `altitude_absente`, `fc_indefinie` (FC décalée,
couverture 0,8). L'appareil et le journal sont marqués, jamais filtrés.

**Les références.** Sur l'année écoulée (les 365 jours qui finissent au dernier jour des
données) : la FC de référence, la médiane des FC, et les deux autres FC, les quartiles 25
et 75, arrondis à 5 bpm ; l'altitude de référence, la médiane arrondie à 100 m ; le D+ de
référence, la moyenne ; le régime de référence, la montée longue.

**L'étage 1, la structure, sur toute l'histoire.**
`y_ij = a(t_j) + β·x_ij + g·D_ij + λ·A_ij + ρ·I_ij + γ_D·(D̄_j − D_ref) + γ_A·(Ā_j − A_ref) + u_j + e_ij`,
`x = ln(FC / FC_réf)`, `D` le D+ au milieu de la montée, `A` son altitude moyenne, `I` le
régime intermédiaire. (i) Dans la sortie : les moindres carrés sur les colonnes et la
réponse centrées par sortie, sur les sorties à deux montées ou plus (dix au moins) ;
`s²_e = rᵀr / (N − G − q)` ; une colonne portée par moins de deux sorties sort du plan ;
si c'est celle de β ou de `g`, l'étage 1 se dit « données insuffisantes » (sans β, G1 et
G2 n'ont rien à montrer ; sans `g`, G3) ;
covariance CR2 par sortie, intervalles de Student aux degrés de liberté de Bell-McCaffrey
(voir « Les intervalles ») ; « non séparable » quand le facteur d'inflation de la
variance de β ou de `g` dépasse 10. λ se dit « données insuffisantes » quand son erreur
type CR2 dépasse 0,05 par 1 000 m, ou quand sa colonne sort du plan. (ii) Entre sorties :
les résumés
`r̄_j = moyenne(y − β·x − g·D − λ·A − ρ·I)` en moindres carrés généralisés sur
`[1, D̄_j − D_ref, Ā_j − A_ref]` sous `V = diag(s²_e / n_j) + σu²·I + s²_a·exp(−Δt/φ)`
(`reml.py`, `φ` entre 7 et 365 jours) : la composante corrélée est le niveau `a(t)`.
Le résumé lu aux références, `s_j = r̄_j − γ_D·(D̄_j − D_ref) − γ_A·(Ā_j − A_ref) +
g·D_ref + λ·A_ref`, de variance empruntée `v_j = σu² + s²_e / n_j`.

**L'étage 2, la Fenêtre.** Le niveau `a_w`, la moyenne des `s_j` de la Fenêtre ; la
tendance `c`, la pente des `s_j` en mois (six sorties au moins, sur deux jours ou plus),
sa variance empruntée, son intervalle à 95 % par la loi normale ; la couleur se lit sur
cet intervalle, éteinte au-delà de 120 jours et sur tout l'historique ; pour un dégradé, la tendance rétrécie
`k_c·c`, `k_c = τ(w)² / (τ(w)² + var(c))` (`τ(w)` : la vitesse habituelle à la longueur
de la Fenêtre, ci-dessous), rapportée à l'échelle `m` et ramenée à `[−1 ; 1]`. β et `g` de la Fenêtre, dans la sortie
(réponse sans `λ·A + ρ·I`, variance à `s²_e` de l'étage 1), mêlés à ceux de l'histoire :
`k = τ² / (τ² + var_fenêtre)` (`τ = τ_β` pour β, `τ_g` pour `g`),
`valeur = histoire + k·(fenêtre − histoire)`,
`variance = (1 − k)²·var_histoire + k·var_fenêtre`, `τ_β = 0,15`, `τ_g = 0,03` par
1 000 m ; « emprunté à l'histoire » quand `k` de `g` est sous 0,2. La courbe de G2 :
`a_w + β·x`, de variance `var(a_w) + x²·var(β)` (la covariance de `a_w` et de β est
négligée), bornée aux centiles 5 et 95 des FC des montées de la Fenêtre.

**L'étage 3, le jour.** Sur les résumés des `N` jours qui finissent à la dernière
sortie au plus tard le jour `d` (`N` = 56 jours par défaut) : la moyenne `m̄` ; avec trois sorties ou plus, sur deux jours ou plus, la pente `ĉ`, son erreur `e²`, le
poids `k = τ² / (τ² + e²)` ; le niveau lu à la dernière sortie, `m̄ + k·ĉ·ℓ` (`ℓ`,
l'écart en mois de la dernière sortie à la date moyenne), de variance `Σ v_j / n² +
ℓ²·k·e²` ; entre deux sorties la fenêtre ne glisse pas : la valeur reste gelée et la variance
s'ouvre de `(τ·Δ)²` (`Δ` en mois depuis la dernière sortie) ; la courbe s'arrête 28 jours après la dernière sortie. À une FC
lue, la variance de l'étage 1 sur la moyenne s'ajoute (`qᵀ·Σ·q`, et celle de `γ`).
L'étage 3 ne lit pas la Fenêtre.

**La vitesse habituelle `τ`.** Sur des périodes disjointes de la longueur voulue
(`N`, ou celle de la Fenêtre pour l'échelle), sur toute l'histoire, en remontant depuis
le dernier jour des données, chacune d'au moins cinq sorties sur deux jours ou plus : `τ² = variance des pentes − moyenne de leurs
erreurs²`, ramené à 0 s'il est négatif ; estimée avec douze périodes au moins, plafonnée à 0,05 par mois ; sinon
0,03 par mois, « par défaut ». L'échelle des couleurs, `m = 2·τ`, entre 0,01 et 0,10 par
mois.

**Les intervalles.** Les coefficients de l'étage 1 : covariance CR2 par sortie et degrés
de liberté de Bell-McCaffrey (charte, § 4 bis.2 ; `bell_mccaffrey_df` et `cr2_interval`,
écrits pour AN4-2a dans `inference/clusters.py`, `0021`). Deux écarts à § 4 bis.2, ceux
d'un tableau de bord (charte, § 8) plutôt que d'un plan : les bandes du niveau (étages 2
et 3, courbe de G2) prennent la loi normale, sur des variances empruntées à l'étage 1,
covariance CR2 de l'étage 1 comprise ; β et `g` de la Fenêtre, la covariance classique à
`s²_e` de l'étage 1, même sous dix sorties (leur poids reste petit). Chaque bande se dit
ponctuelle.

**Les états**, rendus comme des valeurs : « données insuffisantes », « sans objet »,
« non séparable », « à cheval sur une rupture d'appareil », « emprunté à l'histoire »,
« par défaut », « estimé ».

Les constantes : `analyse/ascent/parameters.py`.

## Pourquoi

Le centrage par sortie retire de l'effet de la FC, du déclin et de l'altitude tout ce
qui varie entre sorties — la saison, la forme du jour, le choix de l'allure d'une longue
sortie — comme Q2 le fait par journée ; une sortie à une seule montée n'y apporte rien,
et c'est le prix (option B l'aurait gardée, au risque de la confusion). Les intervalles
CR2 par sortie restent justes quand la pente varie d'une sortie à l'autre (charte, § 4
bis.2), ce que demande la pente aléatoire de § 4 bis.1. Le niveau qui suit le temps
protège `γ_D`, `γ_A` et l'effet de sortie de la saison ; la covariance de `reml.py`
l'avait déjà. Le poids continu remplace des seuils de nombre de sorties qui feraient
sauter une courbe d'un jour à l'autre. L'étage 3 ne lit que l'étage 1 : la courbe du
jour ne change pas quand on change de Fenêtre. Une seule tendance par courbe : la
couleur est une seule décision, son intervalle suffit (la bande simultanée de la charte,
§ 8, vaut pour une courbe lue point par point). Les valeurs par défaut (`τ`, les seuils)
ont été essayées par la conception sur des mondes inventés (un athlète mince, un riche,
avec et sans saison : couverture du niveau, part des fausses couleurs), jamais sur des
données réelles. Option A : les fenêtres minces ne portent pas la structure.

## Conséquences

- Les pages d'AN4-2b (la montée) et d'AN4-3 (le déclin) lisent ce paquet ; il ne
  connaît ni Streamlit ni le cache.
- Chez un athlète mince, la Fenêtre emprunte presque tout à l'histoire (β, `g`), `τ`
  reste « par défaut », la tendance demande six sorties : les pages le disent par les
  états.
- À revoir : `τ_β` et `τ_g` selon la longueur de la Fenêtre, le poids du jour, le terme
  `δ`, deux activités le même jour (`BACKLOG`).
