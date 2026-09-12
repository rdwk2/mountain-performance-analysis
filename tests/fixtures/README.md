# Fixtures de test

**Uniquement des données synthétiques.** Jamais de données personnelles.

C'est la règle 1 de `CLAUDE.md`, et la frontière physique de la décision
[`0001-separation-data-code.md`](../../docs/decisions/0001-separation-data-code.md) :
le dépôt est publiable à tout moment, sans nettoyage.

## Ce qui est accepté ici

- des fichiers **minuscules** (quelques points, quelques lignes), **inventés** à la
  main, avec des valeurs rondes qui rendent les résultats attendus calculables de
  tête ;
- un commentaire ou un en-tête qui dit ce que la fixture représente et quel test
  s'en sert.

## Ce qui est interdit ici

- tout extrait d'un export Garmin, d'une activité, d'une trace GPX de sortie ou de
  course réelle — **même tronqué, même anonymisé** ;
- tout fichier copié depuis `MPA_DATA_DIR`.

Une fixture qui a besoin d'être « réaliste » se fabrique : on écrit un petit
générateur, on ne copie pas.

En cas de doute, la question à se poser : « si ce fichier apparaît sur GitHub
public demain, est-ce un problème ? ». Si la réponse n'est pas un non franc,
ça ne va pas ici.
