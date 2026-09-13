# 0007 — Forme des données

- **Date** : 2026-09-13
- **Statut** : acceptée

## Contexte

M1 écrit les contrats de données : ce qui circule entre les modules. Avant d'écrire
quinze types, il faut fixer une fois comment ils s'écrivent, pour que M1b et les
jalons suivants ne rediscutent pas la forme à chaque type. Contraintes : un ultra à
1 Hz fait ~150 000 points ; le dépôt n'a aucune dépendance de runtime ; M1 ne fait
aucune entrée/sortie.

## Options envisagées

**Séries de points.** A. une liste d'objets « point » ; B. un objet qui porte des
tableaux parallèles de même longueur.

**Mécanisme de schéma.** A. pydantic ; B. `@dataclass(frozen=True)` de la
bibliothèque standard, validation dans `__post_init__`.

**Champs dérivés.** A. stocker les grandeurs utiles (pente, D+ cumulé) à côté des
données ; B. ne stocker que ce qui n'est pas recalculable, le reste en propriétés.

**Immutabilité des tableaux.** A. copier en tuple à la construction ; B. ne rien
faire et documenter ; C. ne pas copier, mais refuser une séquence mutable.

## Décision

Tableaux parallèles (`Sequence[float]`) ; dataclasses gelées ; un champ est stocké
seulement s'il ne peut pas être recalculé à partir des autres champs du même objet ;
les tableaux ne sont pas copiés mais doivent être immuables (tuple aujourd'hui).

## Pourquoi

**Tableaux parallèles.** `Sequence[float]` accueille un `tuple` aujourd'hui et un
`ndarray` demain sans toucher une signature, alors que 150 000 objets Python ne
passent pas l'échelle.

**Dataclasses plutôt que pydantic.** L'argument principal de pydantic est de parser
une entrée non fiable. M1 ne fait aucune entrée/sortie : l'argument ne s'applique
pas encore. La vraie question se posera au M6b, fichiers Garmin sous les yeux, sans
dépendance de runtime à porter d'ici là.

**Stocké vs dérivé.** Deux champs qui portent la même information finissent
toujours par diverger : l'un est corrigé, l'autre oublié, et l'écran et l'export
affichent deux totaux différents. La règle porte sur les champs *du même objet* : un
`ResolvedPoint` stocke son abscisse, résultat d'un calcul du M2, parce qu'il ne porte
pas le tracé.

**Séquences immuables refusées plutôt que copiées.** Un objet gelé qui porte une
`list` reste modifiable au travers d'elle. Payer une copie de 150 000 points pour une
garantie qu'on abandonnera au M6b (numpy) est un mauvais échange ; s'en remettre à la
discipline l'est aussi. `require_immutable_sequence` refuse la `list` avec un
message qui dit de passer un tuple : zéro copie, garantie mécanique, un seul endroit
à élargir quand `ndarray` (non inscriptible) arrivera.

**Pas de `slots`.** `slots=True` interdit `functools.cached_property`. Si le coût de
recalcul de la pente ou des cumuls devient visible, on mémoïse par
`cached_property` — on ne duplique jamais en champ stocké.

## Conséquences

- `RouteProfile.grade`, `cumulative_ascent_m`, `cumulative_descent_m` sont des
  propriétés ; un test vérifie qu'ils ne sont pas des champs.
- Toutes les stratégies de test et fixtures produisent des tuples.
- Toute valeur flottante de contrat est finie (`require_finite`) : un NaN empoisonne
  les cumuls sans lever.
- Chaque type documente cinq rubriques (Champs · Invariants · Producteur ·
  Consommateurs · Non promis) ; le dictionnaire de données est généré depuis ces
  docstrings.
- numpy et pydantic restent des conversations de règle 5 pour les jalons où ils
  serviront vraiment (M6b). **À revisiter** alors : `require_immutable_sequence`
  devra accepter un `ndarray` non inscriptible.
