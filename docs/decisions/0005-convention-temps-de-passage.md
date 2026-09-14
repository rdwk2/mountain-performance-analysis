# 0005 — Convention des temps de passage

- **Date** : 2026-09-14
- **Statut** : acceptée

## Contexte

Dès qu'il y a des arrêts, « temps de passage » est ambigu : arrivée au
ravitaillement, ou départ. Sur une base de vie où l'on passe douze minutes, ce n'est
pas un détail. La question se pose au M1b, au moment d'écrire les contrats de la
projection (`Passage`) et de la vérité terrain (`ReferencePerformance`) : quel temps
portent-ils ?

## Options envisagées

**A. Un seul temps par point, à l'arrivée.** Simple, mais ne sait pas représenter un
arrêt, et ne correspond ni au raisonnement de course ni aux barrières horaires.

**B. Un seul temps par point, au départ.** Colle au raisonnement de course, mais
confond temps de déplacement et temps d'arrêt dans un même chiffre.

**C. Les deux temps au contrat, `DEPARTURE` par défaut, et la convention des relevés
déclarée passage par passage, avec `UNKNOWN` comme valeur légitime.**

## Décision

Option C : `Passage` porte `arrival_s` et `departure_s` ; `DEPARTURE` est la
convention par défaut du projet ; `ReferencePerformance` déclare sa convention **par
passage** (`TimingConvention`), `UNKNOWN` compris.

## Pourquoi

Le raisonnement de course (« j'arrive, je suis censé repartir à telle heure ») et les
barrières horaires se calent sur le départ : c'est le défaut naturel. `ARRIVAL` reste
disponible en option d'affichage et d'export.

A et B sont écartées parce qu'un seul chiffre ne permet pas de séparer le temps
arrêté du temps de déplacement, donc pas d'attribuer un résidu.

La convention est portée par passage parce que les relevés réels mélangent les deux
sans le signaler (`docs/PIEGES_DATA.md`). Un décalage non déclaré se propage dans tous
les cumulés suivants, où il **imite une dérive de fin de course** : on chercherait un
effet de fatigue qui n'existe pas. `UNKNOWN` est plus honnête qu'une convention
devinée.

## Conséquences

- Le temps d'arrêt est `departure_s - arrival_s`. En M3 le modèle ne connaît pas les
  arrêts et les deux sont égaux ; au M6a ils s'écartent **sans que le contrat bouge**.
- Le multiplicateur d'arrêts global de `MODELE_V1.md` devient inapplicable tel quel :
  il faudra décider où répartir le temps arrêté (ligne de `BACKLOG.md` posée en M1a).
  Le contrat est volontairement en avance sur le modèle.
- L'appariement d'un relevé `UNKNOWN` avec une projection reste à décider au M4.
