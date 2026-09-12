# 0002 — Unités internes et unités d'affichage

- **Date** : 2026-09-12
- **Statut** : acceptée

## Contexte

En course à pied on parle en **min/km**. En trail, en montée, on parle plutôt en
**VAM** (mètres de dénivelé par heure). Les fichiers de courbe de l'ancien projet
sont en **km/h**. Le modèle, lui, manipule une vitesse en fonction de la pente.

Quatre façons d'exprimer la même chose, et une question à trancher une fois :
qu'est-ce qui circule dans le code ?

## Options envisagées

**A. min/km partout**, puisque c'est ce qu'on lit et ce qu'on ressent.

**B. km/h partout**, comme les fichiers existants.

**C. m/s en interne, conversions explicites aux frontières, formatage à l'affichage.**

## Décision

Option C. **La vitesse circule en m/s dans tout le code.** Les conversions se font
à la lecture des fichiers et à l'affichage, jamais au milieu d'un calcul.

`min/km` et `VAM` sont des **formats d'affichage**, pas des unités de stockage.

## Pourquoi

**min/km est l'inverse d'une vitesse, et le modèle est multiplicatif.** Toutes les
équations sont de la forme `v = pace(pente) × effort × (1 − fatigue)`. Sur un
inverse, ces produits ne veulent plus rien dire : la moyenne de deux allures en
min/km n'est pas l'allure moyenne, et une interpolation linéaire entre deux points
d'une courbe en min/km ne donne pas la même courbe qu'en vitesse.

**Et surtout : en montée raide la vitesse tend vers zéro, donc min/km tend vers
l'infini.** C'est précisément le régime où l'on travaille en trail — des passages à
30-40 % de pente. Une courbe stockée en min/km diverge exactement là où on a besoin
qu'elle soit stable. C'est rédhibitoire.

**m/s plutôt que km/h** parce que `duration_s = distance_m / speed_ms` ne comporte
aucun facteur de conversion. Chaque `/3.6` ou `×3.6` glissé dans une formule est un
bug qui attend son heure, et ils se multiplient discrètement. Avec des distances en
mètres et des durées en secondes, le système est cohérent de bout en bout.

km/h aurait été défendable — plus lisible en débogage. Ce qui était **inacceptable**,
c'était de mélanger, pas de choisir l'un ou l'autre.

## Conséquences

**Règles pratiques :**

- toute variable porte son unité dans son nom : `speed_ms`, `distance_m`,
  `duration_s`, `elevation_m`, `grade` (fraction, pas pourcentage),
  `vertical_speed_ms`
- `grade = Δaltitude / distance horizontale` et `speed_ms` est la vitesse
  **horizontale** (celle que donne un GPX, distance 2D). La vitesse verticale en
  découle : `vertical_speed_ms = speed_ms × grade`
- `vertical_speed_ms` est **signée** : positive en montée, négative en descente.
  Il n'y a donc pas de variable séparée pour la descente. « VAM » (Velocità
  Ascensionale Media) est une **étiquette d'affichage** pour le cas positif,
  jamais un nom de variable
- les fichiers de courbe en km/h sont convertis **à la lecture**, une fois
- une couche de formatage sépare le calcul de l'affichage :
  - `format_pace(speed_ms)` → `"5:42 /km"`
  - `format_vam(vertical_speed_ms)` → `"620 m/h"` — la vitesse verticale étant
    déjà verticale, le formateur n'a pas besoin de la pente
- l'affichage choisit selon le régime : **VAM en montée soutenue** (min/km n'a
  aucun sens sur un mur), **min/km sur le plat et le roulant**
- ces fonctions de conversion sont écrites et testées dès le M0 : elles servent
  partout, et une erreur de facteur 3,6 découverte au M6 empoisonne tout ce qui
  précède

**À revisiter** : si un jour le projet couvre le VTT ou le ski de randonnée, les
formats d'affichage changeront (km/h en VTT, VAM en ski). L'unité interne, elle,
ne bougera pas — c'est bien l'intérêt de la séparation.
