# 0001 — Séparation stricte données / code

- **Date** : 2026-09-11
- **Statut** : acceptée

## Contexte

Le projet manipule des données personnelles : historique Garmin complet (activités,
FC, sommeil, HRV), traces GPX de courses, identifiants d'accès. Le repo a trois
destinations connues : usage personnel, publication comme projet portfolio, et
éventuellement un déploiement où d'autres personnes importeraient leurs propres
données.

La version précédente du projet mélangeait code, données brutes, sorties
intermédiaires et livrables dans une même arborescence. C'était utilisable seul,
mais impubliable sans un tri long et risqué.

## Options envisagées

**A. Tout dans le repo, avec un `.gitignore` sur les dossiers de données.**
Simple au départ. Mais un `.gitignore` protège seulement ce qu'on a pensé à y
mettre, et les données finissent par se retrouver dans des fixtures de test « juste
pour essayer ». C'est ce qui rend un repo impubliable sans audit.

**B. Données hors du repo, chemin configuré par variable d'environnement, fixtures synthétiques commitées pour les tests.**
Une frontière physique plutôt qu'une règle de discipline. Coûte une configuration
initiale et oblige à fabriquer des fixtures.

**C. Deux dépôts séparés, code et données.**
La séparation la plus stricte, mais un dépôt git n'est pas un bon stockage pour des
gigaoctets de JSON, et ça double le travail de synchronisation.

## Décision

Option B. Les données réelles vivent dans un dossier externe pointé par
`MPA_DATA_DIR`. Le repo ne contient que du code et des fixtures synthétiques
minuscules.

## Pourquoi

- Le repo est publiable **à tout moment, sans nettoyage**. Ce qui veut dire qu'il le
  sera vraiment, au lieu d'attendre un grand tri qui n'arrive jamais.
- La CI tourne sur une machine vierge, sans accès aux données personnelles. Elle ne
  peut être verte que si le code ne dépend pas de fichiers privés — la contrainte
  est vérifiée mécaniquement, pas laissée à la vigilance.
- Les tests deviennent rapides et déterministes : des fixtures de quelques kilooctets
  plutôt que des exports de plusieurs centaines de mégaoctets.
- Le futur mode multi-utilisateur devient une question de configuration
  (`MPA_DATA_DIR` par utilisateur) plutôt qu'une réécriture.
- L'option A a été écartée parce qu'elle repose sur la discipline, et que le coût
  d'un seul oubli est une fuite de données personnelles dans un historique git
  public — difficile à rattraper.

## Conséquences

**Facile** : publier, faire tourner la CI, partager le code, tester vite.

**Contraignant** : aucun chemin en dur vers un dossier personnel, nulle part. Toute
lecture de données passe par la configuration. Il faut fabriquer et maintenir des
fixtures synthétiques représentatives.

**À revisiter** : quand le mode multi-utilisateur deviendra réel, le stockage devra
être repensé (qui possède quoi, durée de conservation, suppression). Cette décision
ne tranche pas ce sujet, elle le rend abordable.
