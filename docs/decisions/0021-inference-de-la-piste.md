# 0021 — L'inférence de la piste analyse

- **Date** : 2026-11-13
- **Statut** : acceptée (AN3-1)

## Contexte

La première question de la piste à demander un intervalle sous dépendance est Q2
(l'efficience en montée progresse-t-elle ?). Son plan d'analyse, figé hors du dépôt
avant tout calcul sur le réel (`docs/analyse/CHARTE.md`, § 6), demande : un modèle des
journées en moindres carrés généralisés, de covariance `V = diag(d) + τ²·I +
σ²_u·exp(−Δ/φ)` estimée par REML ; des intervalles de Student ; un bootstrap
paramétrique sous `V` ; des sensibilités (Huber, spline cubique naturelle, bootstrap
sauvage par grappes) ; une bande simultanée max-t ; Holm et Bonferroni ; la règle des
trois lectures ; l'autocorrélation des résidus ; une simulation de puissance et un seuil
calibré. `0011` a prévu que la plupart de ces méthodes s'écrivent dans la piste, sur
numpy et scipy.

## Options envisagées

**A. statsmodels.** Il a les MCO, la GLS à `V` connue, Huber (`RLM`) et Holm, mais ni
CR2, ni REML d'une covariance exponentielle en jours, ni bootstrap sauvage ; il tire
pandas et patsy, et n'est pas typé (une enveloppe et une dérogation mypy).

**B. numpy et scipy seuls, tout le reste écrit dans la piste.** Quelques centaines de
lignes, testées par des cas calculés à la main et des propriétés, et comparées à une
seconde implémentation tenue hors du dépôt.

## Décision

B : un paquet `analyse/inference/`, seul importeur de numpy et de scipy, qui ne sait
rien des montées ni des journées ; `analyse/q2.py` le branchera sur les données. Le
REML de la covariance de Q2 y est écrit, et non pris à `MixedLM` (note de `0011`).

## Conventions

- **Quantiles** : la statistique d'ordre `x₍⌈q·B⌉₎`, sans interpolation (à `B = 2 000`,
  les bornes à 2,5 et 97,5 % sont les 50ᵉ et 1 950ᵉ valeurs).
- **Graines** : un générateur par usage, `SeedSequence(graine racine, spawn_key=(…))` ;
  aucun état global. Une simulation donne le même résultat quel que soit le nombre de
  processus.
- **REML** : `−2ℓ_R` sans la constante ; `φ` borné ; profil sur 12 valeurs de `φ`
  (géométriques entre les bornes), puis un affinement gardé seulement s'il fait au
  moins aussi bien ; drapeaux « à la borne » ; `φ` « non identifié » si
  `σ̂²_u/(τ̂² + σ̂²_u) < 0,01`. `d` (la variance de l'étage précédent) est traitée comme
  connue : son incertitude n'entre pas dans l'intervalle.
- **Lectures** : « établi » si chaque intervalle exclut 0 au sens strict, tous du même
  côté ; sinon « absence d'effet utile » si chacun tient dans `]−δ ; +δ[` ; sinon
  « non tranché ». Lues sur l'échelle de l'effet (pour Q2 : la fraction par an).
- **Autocorrélation des résidus** : les résidus centrés ; pour chaque classe d'écart en
  jours, la moyenne des produits des paires de la classe, divisée par la variance (sur
  `n`).
- **Bootstrap sauvage par grappes** : bootstrap-t non restreint, studentisé par CR2,
  intervalle symétrique ; poids de Webb sous 12 grappes, Rademacher au-delà (tous les
  tirages possibles quand `2^G` ne dépasse pas le nombre demandé) ; refusé sous 10
  grappes.
- **Bootstrap sauvage des résidus** : un poids par ligne, de Rademacher (±1, à pile ou
  face), appliqué au résidu tel quel, sans correction de levier.
- **Bande max-t** : sur des courbes réestimées (pour Q2 : par bootstrap sauvage des
  résidus) ; un point sans dispersion est exclu du maximum, et la bande y vaut
  l'estimation.
- **Huber** : `c = 1,345`, échelle = MAD autour de 0, réestimée à chaque itération,
  covariance « H1 ».
- **Puissance** : la probabilité de lire « établi » dans le sens de l'effet simulé ;
  l'erreur S est la part des « établi » de sens contraire, l'erreur M la moyenne de
  `|estimation|/|effet|` parmi les « établi » (Gelman et Carlin, 2014) ; le plus petit
  effet visible se lit sur la grille simulée, sans interpolation. Dans une simulation,
  un bootstrap emboîté garde `V` fixée (le réajustement devient linéaire) ; la
  puissance rapportée est donc un peu optimiste, et se dit ainsi. **Seuil calibré** :
  le seuil α des intervalles, choisi sur une grille contre le pire des scénarios,
  seulement si le taux de faux « établi » au seuil nominal dépasse le seuil de
  déclenchement du plan.
- **Ce qui n'est pas écrit** : les ddl de Bell-McCaffrey, la variance EWC, le bootstrap
  par blocs et la longueur de bloc de Politis-White, Diebold-Mariano, le contrôle par
  décalage circulaire (aucune question en cours n'en a besoin) ; ils viendront avec la
  question qui les demandera.

## Pourquoi

statsmodels n'aurait fourni que la moitié facile (MCO, Huber, Holm), au prix de deux
bibliothèques non typées de plus ; la moitié difficile (REML de cette covariance, CR2,
bootstrap sauvage, puissance) s'écrit de toute façon. Les conventions sont écrites ici
parce qu'une valeur littérale de test en dépend (un quantile, une graine) et qu'un
résultat de la piste doit se refaire au tirage près.

## Conséquences

- **Facile** : Q1 reprendra les mêmes outils (son inférence suit Q2) ; un nouvel
  estimateur s'ajoute au paquet, avec ses cas et sa contre-épreuve.
- **Contraignant** : chaque fonction déterministe a des cas calculés à la main ;
  celles qui tirent, une propriété ou une simulation ; chaque estimateur, une propriété
  ou une simulation ; les méthodes que `0011` range parmi celles « écrites dans la
  piste » (CR2, bootstrap sauvage par grappes, bande max-t) ont en plus leur simulation
  de couverture ; une simulation se vérifie contre une formule fermée quand il y en a
  une.
- **À revisiter** : le temps d'un REML (quelques dixièmes de seconde sur quelques
  dizaines de lignes) si une question demande des millions d'ajustements ;
  Bell-McCaffrey si un plan l'emploie.
