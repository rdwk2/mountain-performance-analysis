# 0004 — Le point remarquable comme pivot

- **Date** : 2026-09-13
- **Statut** : acceptée

## Contexte

Un GPX porte une géométrie **et** des points nommés (départ, ravitaillements, cols,
sommets). En écrivant les contrats du tracé (M1a), il faut décider si ces points
entrent dans le contrat, et sous quelle forme.

## Options envisagées

**A. Géométrie seule.** Les points nommés restent hors contrat ; on les lira quand
on en aura besoin.

**B. Un seul objet « point sur le tracé »**, avec son nom et son abscisse, résolu dès
la lecture.

**C. Deux objets** : le **lieu** tel qu'il est dans le fichier (`NamedPoint`, dans
`Route`), et le **passage** résolu sur le tracé (`ResolvedPoint`, dans
`RouteProfile`), avec une **liste** de passages et non un passage par lieu.

## Décision

Option C.

## Pourquoi

Sans points nommés, une projection ne produit pas de temps de passage, et le
backtest du M4 n'a rien à comparer : sa vérité terrain est faite de temps relevés à
des points nommés. A retire donc au projet sa seule mesure.

B confond deux choses qui n'ont ni le même producteur ni la même fiabilité. Le lieu
est une donnée du fichier, lue telle quelle. Le passage est le résultat d'un calcul
du M2 (minima de distance au tracé, seuils), avec un écart au tracé qui dit sa
qualité. Les mélanger obligerait la lecture GPX à résoudre, c'est-à-dire à calculer.

La liste de passages vient d'un cas réel : un lieu traversé deux fois —
aller-retour au sommet, boucle dont le départ est l'arrivée, source croisée à la
montée et à la descente. Décidée maintenant, une liste est gratuite ; découverte au
M4, elle casse le format de sortie des projections et du backtest.

## Conséquences

- `RouteProfile.resolved_points` peut contenir deux entrées portant le même
  `NamedPoint` ; c'est un invariant testé, avec une fixture dédiée (« sucette »).
- Les points nommés bornent les segments : ils définissent ce que le M4 pourra
  mesurer.
- `NamedPoint.kind` n'est jamais inféré en M1 ; la valeur honnête est `UNKNOWN`.
- `cutoff_s` est provisoirement porté par `NamedPoint`, alors qu'une barrière
  horaire appartient à une course : à déplacer le jour où une notion de course aura
  un cas d'usage.
