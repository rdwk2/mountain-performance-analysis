# 0003 — Portée multi-sport des contrats

- **Date** : 2026-09-13
- **Statut** : acceptée

## Contexte

Le VTT et le ski de randonnée sont des objectifs annoncés du projet. Le premier
outil, lui, ne sait projeter que des temps à pied, à partir d'une seule courbe
allure↔pente. Au moment d'écrire les contrats de données (M1), la question est : que
paie-t-on maintenant pour les sports qui viendront ?

## Options envisagées

**A. Rien.** Contrats écrits pour la course à pied seule ; on les reprendra le jour
venu. Coût nul aujourd'hui, mais un champ ajouté plus tard casse tous les fichiers
et les signatures qui le traversent.

**B. Généralité dans les données.** Une énumération `Sport` déclarée, la validation
des croisements, et rien d'autre : pas de branche par sport dans le code.

**C. Généralité dans le code.** Interfaces abstraites de courbe et de moteur, une
implémentation par sport, points de variation posés dès maintenant.

## Décision

Option B : on paie la généralité **en champs de données**, pas en points de
variation dans le code.

## Pourquoi

Six septièmes des schémas décrivent de la géométrie et de la mesure (tracé, profil,
enregistrement, provenance) : ils sont agnostiques du sport gratuitement. Tout le
contenu spécifique est concentré dans la courbe et le moteur — et généraliser
ceux-là est aujourd'hui impossible, faute de données et d'hypothèses sur le ski ou
le VTT.

C est écartée parce qu'une abstraction écrite avec une seule implémentation est
presque toujours la mauvaise : on la dessine d'après le seul cas connu, et le
deuxième cas la contredit. A est écartée parce que déclarer une énumération de trois
valeurs ne coûte presque rien, alors que l'ajouter au milieu des fichiers générés
coûterait une régénération et une relecture de tous les contrats.

`Route` ne porte **pas** de sport : le même sentier se court, se marche et se skie.
Le sport entre au moment de choisir une courbe, pas au moment de lire un tracé.

## Conséquences

- Aucun `if sport == …` n'est légitime avant l'intégration d'une deuxième courbe,
  sauf pour valider une cohérence.
- Une nouvelle valeur de `Sport` se justifie par un changement de *forme* du modèle,
  pas par un changement de nom d'activité.
- Ce qui rendra un deuxième sport bon marché n'est pas ce schéma, mais le harnais de
  backtest du M4 : c'est lui qui dira si une courbe tient.
- **À revisiter** : à l'arrivée de la deuxième courbe.
