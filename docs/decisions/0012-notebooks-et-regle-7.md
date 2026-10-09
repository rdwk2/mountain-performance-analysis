# 0012 — Notebooks et règle 7

- **Date** : 2026-10-08
- **Statut** : acceptée

## Contexte

La règle 7 de `CLAUDE.md` dit : « Pas de logique métier dans l'interface, ni dans un
notebook. L'UI et les notebooks appellent la bibliothèque. S'ils calculent quelque
chose, c'est que ça manque dans `src/`. » Elle a été écrite pour le moteur, qui ne
s'est pas servi de notebooks.

La piste analyse explore des données. Prise à la lettre, la règle interdit
l'exploration : regarder une distribution, essayer un regroupement avant d'écrire une
fonction. Laissée floue, elle laisse un chiffre calculé dans un notebook finir dans un
compte rendu sans avoir été testé. Et un notebook est le format le plus exposé à la
règle 1 : ses sorties, tableaux et figures, contiennent les données qu'il a lues.

Deux questions, donc : que peut calculer un notebook, et sous quel format.

## Options envisagées

Pour la règle :

**A. La règle à la lettre** : un notebook n'appelle que des fonctions de `src/`.
Explorer demande d'abord d'écrire des fonctions testées : c'est lent, et l'on teste du
code qu'on jettera.

**B. Exploration libre, résultats contrôlés** : un notebook peut calculer pour
explorer ; ce calcul est jetable ; tout chiffre rapporté vient d'une fonction testée
de `src/`.

**C. Pas de notebooks**, des scripts : mais `scripts/` est réservé à l'outillage du
dépôt, et un script ne montre rien en cours de route.

Pour l'outil :

**A. Jupyter** (`.ipynb`) : un JSON qui range les sorties à côté du code. Son diff est
illisible, et il garde des données personnelles dans ses sorties si l'on oublie de les
vider ; `nbstripout` ou un crochet de commit en font une affaire de discipline.

**B. marimo** : chaque notebook est un fichier `.py`, sans sortie par construction,
lisible en diff et vérifiable par `ruff`. L'exécution est réactive : les cellules se
recalculent dans l'ordre de leurs dépendances, pas dans l'ordre où on les a lancées.

## Décision

Règle : option B. Outil : marimo.

- Un notebook peut calculer pour explorer ; ce calcul est jetable.
- **Tout chiffre rapporté** (repris dans un compte rendu, une décision, le tableau de
  bord, le journal des essais de la piste ou le moteur) vient d'une fonction testée de
  `src/`.
- Un notebook ne lit que `processed/` et la configuration de l'athlète, jamais
  `raw/` : il passe par les mêmes tables que les commandes.
- Ce qu'un notebook a regardé est « déjà vu » au sens de la charte
  (`docs/analyse/CHARTE.md`, § 6) : une relation regardée avant son plan d'analyse
  reste exploratoire sur ces données, et un choix d'analyse essayé dans un notebook
  puis changé dans le plan compte pour un essai.
- Les notebooks vivent dans `notebooks/`, en fichiers marimo ; le dossier
  `__marimo__/` (sorties mises en cache) sera exclu par `.gitignore` avec le premier
  notebook.
- Un contrôle de la CI refuse tout `.ipynb` et tout fichier de données hors de
  `tests/fixtures/` ; il arrive avec la PR qui ajoute le premier notebook.
- `notebooks/` reste hors des cibles de mypy (`files` de `pyproject.toml`) ; `ruff`
  s'y applique, et la clôture d'import des extras l'autorise à importer les
  bibliothèques de l'extra `analyse` (`0011`).
- marimo s'installe par le groupe de développement `analyse-dev` (`0011`), jamais
  avec le cœur.

## Pourquoi

- **B plutôt que A** : explorer est le premier pas de toute question. Exiger une
  fonction testée pour chaque regard rendrait l'exploration plus chère que l'analyse,
  et le test porterait sur du code jeté. Ce qui doit être sûr, c'est ce qui sort du
  notebook : la règle porte là.
- **B plutôt que C** : un script ne montre rien en cours de route, et `scripts/` reste
  à l'outillage.
- **« Déjà vu »** : un regard dans un notebook est un essai que personne ne
  compterait. La charte le compte, pour qu'une relation trouvée en explorant ne se
  présente pas ensuite comme confirmée.
- **marimo plutôt que Jupyter** : une frontière plutôt qu'une discipline, comme pour
  les données (`0001`). Un fichier sans sortie ne peut pas faire fuir de données, et
  un `.py` se relit en diff et passe `ruff` comme le reste du code. Le contrôle de la
  CI tient la règle mécaniquement.

## Conséquences

- **Facile** : explorer sans attendre une fonction ; relire un notebook comme du code.
- **Contraignant** : un chiffre vu dans un notebook n'est pas un résultat tant qu'une
  fonction de `src/` ne le recalcule pas. Un notebook ne lit pas `raw/` : il attend
  les tables de `processed/` (AN1).
- **À revisiter** : l'outil, si marimo cessait d'être maintenu (les notebooks,
  fichiers `.py`, resteraient lisibles) ; le contrôle de la CI, à la première PR qui
  ajoute un notebook.
