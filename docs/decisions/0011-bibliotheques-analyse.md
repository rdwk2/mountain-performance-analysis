# 0011 — Bibliothèques de la piste analyse

- **Date** : 2026-10-08
- **Statut** : acceptée

## Contexte

Le moteur de prédiction n'a aucune dépendance de calcul : dataclasses gelées plutôt
que pydantic (0007), Python pur sans numpy (M4b-3). Il code lui-même les quelques
calculs dont il a besoin, petits et testés au bit près.

La piste analyse (statistiques sur les données d'un athlète, tableau de bord, plus
tard apprentissage) ne peut pas suivre ce choix : recoder des tableaux de données, des
régressions ou des modèles mixtes n'aurait aucun sens. Il faut donc des bibliothèques,
sans que le cœur du moteur en dépende (règle 5), et sans que leur absence de typage
défasse mypy strict.

Contraintes déjà fixées :
- **Frontière** (décision du 2026-10-06, partagée avec le moteur) : l'ingestion
  (`raw/` → contrats → `interim/`) est dans le cœur, sans dépendance ; les tables de
  `processed/` relèvent de l'analyse ; le moteur ne lit jamais `processed/`.
- **Charte de la piste** (`docs/analyse/CHARTE.md`) : estimations avec intervalles,
  inférence sous dépendance (variance EWC, erreurs groupées CR2 avec degrés de liberté
  de Bell-McCaffrey ou bootstrap sauvage par grappes, bandes simultanées max-t, test
  de Diebold-Mariano corrigé, modèles mixtes REML), notebooks marimo.
- **Lecture des FIT** (décision du 2026-10-08) : les positions à pleine résolution
  viennent du FIT (les détails coupent les lacets en montagne, et M6b estimera la
  courbe allure-pente sur ces positions) ; lecture par une bibliothèque, déclarée à
  part. Le moteur l'accepte comme exception à la règle « sans dépendance » de
  l'ingestion, qui visait les calculs et pydantic, pas le décodage d'un format
  binaire.

## Options envisagées

**A. Tout dans les dépendances du projet.** Simple ; mais le moteur hérite de toutes
les bibliothèques, ce que le projet refuse depuis M1.

**B. Des extras (`[project.optional-dependencies]`), et des clôtures d'import.** Une
bibliothèque n'est installée que pour l'usage qui la demande ; une règle de lint
interdit de l'importer hors de son module ; la CI vérifie que le cœur s'importe et se
teste sans aucun extra.

**C. Un second paquet dans le même dépôt (espace de travail uv).** Étanchéité
maximale ; mais deux paquets, deux configurations, une CI plus lourde, pour un gain
que B obtient déjà par la CI.

## Décision

Option B : quatre extras, ouverts chacun avec la première PR qui en a l'usage, et des
clôtures d'import vérifiées par le lint et par la CI.

| Extra | Bibliothèques | Importées seulement par | Ouvert par |
|---|---|---|---|
| `ingest` | fitdecode | `src/mountain_perf/ingest/fit.py` (lecteur FIT), seul | AN1 |
| `analyse` | numpy, pandas, pyarrow (Parquet), scipy, statsmodels, plotly, openpyxl (classeur des notes de sorties) | `src/mountain_perf/analyse/` | AN1 (chacune avec la PR qui l'utilise) |
| `tableau` | streamlit | le module du tableau de bord, fixé à AN2 avec le moteur (`ui/` porte l'interface M5) | AN2 |
| `ml` | scikit-learn | `src/mountain_perf/analyse/` | la première question d'apprentissage |

Groupe de développement à part (`[dependency-groups]`, `analyse-dev`) :
`pandas-stubs`, `scipy-stubs`, `types-openpyxl` et `marimo` (notebooks). Il n'entre
pas dans `dev`, que `uv sync` installe par défaut : les stubs tirent numpy, que la
première étape de la CI ne doit pas avoir.

**Écrits dans la piste plutôt que pris dans une bibliothèque** (petites fonctions de
`analyse/`, testées comme celles du moteur) : variance EWC, erreurs groupées CR2 et
degrés de liberté de Bell-McCaffrey, bootstrap sauvage par grappes (poids de
Rademacher et de Webb), bandes simultanées max-t, test de Diebold-Mariano avec la
correction de Harvey-Leybourne-Newbold, longueur de bloc de Politis-White, contrôle
par décalage circulaire. Les modèles mixtes (REML, pentes aléatoires) viennent de
statsmodels (`MixedLM`).

**Lecteur FIT** (conditions posées pour le moteur) :
- *Isolement* : fitdecode n'est importé que par `ingest/fit.py`. Aucun module de
  `schemas/`, `gpx/`, `model/`, `backtest/`, ni le lecteur d'`interim/`, ne
  l'importe : la règle de lint ci-dessous, un test d'imports (sur le modèle des
  `tests/test_*_imports.py` du moteur) et la CI, qui teste le cœur sans l'extra.
- *`interim/` lisible sans lui* : le contrat d'`interim/` et son lecteur sont dans
  `src/`, sans dépendance. Seule l'écriture d'`interim/` à partir des FIT demande
  l'extra.
- *Une seule enveloppe typée* : `ingest/fit.py` est l'unique endroit où des valeurs de
  fitdecode circulent ; il rend des contrats typés. Aucun `type: ignore` hors de ce
  module.
- *Lecture stricte* : contrôle CRC et gestion d'erreurs en mode `RAISE` (fitdecode les
  met par défaut en simple avertissement). Un fichier refusé est signalé et écarté,
  jamais lu à moitié. Sur un export réel examiné, tous les FIT passent ce contrôle.
- *Unités aux frontières* : conversions à la lecture, unités dans les noms (positions
  de semicircles en degrés, `*_deg` ; altitude en mètres, `*_m` ; et la source de
  l'altitude dite : `enhanced_altitude`, ou `altitude` à défaut).
- *Provenance sans identifiant* : de `file_id`, seuls le type, le fabricant, le
  produit et la date de création passent dans `interim/` ; ni numéro de série ni
  identifiant de l'appareil (règle 1).
- *Tests* : version figée par `uv.lock` ; les tests ne décodent que des FIT
  synthétiques, minuscules, écrits par une aide de test (aucun FIT réel dans le dépôt,
  règle 1), dont au moins un à horodatage compressé et un à champ de développeur.
  fitdecode ne sait pas écrire : l'aide de test est un petit écrivain FIT en Python
  pur (en-tête, messages de définition et de données, CRC), qui sert aussi à tester le
  refus d'un CRC faux. L'export réel examiné n'en contient pas : ces deux tests
  couvrent d'autres montres. Les tests du lecteur comparent aussi à des valeurs
  écrites en dur, indépendantes de l'écrivain (des semicercles connus et leurs degrés,
  une altitude brute et ses mètres) : une même erreur d'échelle des deux côtés ne
  passe pas.
- *Champs* : la liste des champs portés dans `interim/` (dont ceux dont M6b a besoin)
  est fixée par `0013`, l'ingestion et le format d'`interim/`, relu par le moteur
  avant fusion.

**Typage** : mypy strict reste la règle sur `src/`. Une dérogation par module
(`[[tool.mypy.overrides]]`, `ignore_missing_imports`), écrite et justifiée, pour les
seules bibliothèques sans marqueur `py.typed` ni stubs : aujourd'hui fitdecode,
statsmodels, plotly, pyarrow et scikit-learn, à revérifier sur la version figée par la
PR qui ouvre l'extra. Chacune passe par une seule petite enveloppe typée, pour que les
valeurs `Any` ne se répandent pas. `notebooks/` reste hors des cibles de mypy (`files`
de `pyproject.toml`).

**Clôtures d'import** : la règle `ruff` `banned-api` (TID251) interdit d'importer les
bibliothèques d'un extra hors des modules du tableau ci-dessus et de leurs tests ;
`notebooks/` n'importe que celles de l'extra `analyse` (`0012`). Un test vérifie
que `import mountain_perf` et les modules du moteur ne chargent aucune d'elles (les
modules chargés, pas seulement les imports écrits).

**CI en deux temps** : (1) `uv sync --locked`, puis les contrôles du cœur, sans aucun
extra : le moteur reste sans dépendance ; (2)
`uv sync --locked --all-extras --group analyse-dev`, puis toute la suite. Le moyen de
l'étape 1 (une recette `just` dédiée, les tests d'un extra sautés quand il manque, des
cibles de mypy restreintes) se fixe avec la PR qui ouvre le premier extra.

## Pourquoi

- **B plutôt que A** : le moteur reste ce qu'il est depuis M1, et un athlète qui ne
  veut que la prédiction n'installe rien de plus. **B plutôt que C** : la CI en deux
  temps et la règle de lint donnent la même garantie qu'un second paquet, sans doubler
  la configuration.
- **fitdecode** (licence MIT, Python pur, aucune dépendance à l'exécution) : il a
  décodé sans erreur, CRC compris, tous les FIT d'un export réel. Un décodeur maison
  serait la couche la plus exposée aux erreurs silencieuses du projet ; le moteur
  l'écarte aussi : « c'est le cas où l'expérience accumulée d'une bibliothèque compte
  le plus ». **Le SDK officiel de Garmin est écarté** : sa licence (« FIT Protocol
  License Agreement ») limite l'usage à des fins internes, interdit de le mettre à
  disposition de tiers et de s'en servir pour une comparaison, et le déclare
  confidentiel ; elle ne convient pas à un dépôt public.
- **Méthodes écrites dans la piste** : aucune bibliothèque Python maintenue ne les
  fournit ensemble. statsmodels n'offre pas CR2 ni les degrés de liberté de
  Bell-McCaffrey (à confirmer dans sa documentation au brief d'AN1) ; `wildboottest`
  tire à l'exécution numba, statsmodels, pytest et poetry, et sa dernière version date
  de 2024. Chacune tient en quelques dizaines de lignes de numpy, et se vérifie par
  des propriétés et par simulation (taux de faux positifs sous l'hypothèse nulle).
- **pyarrow pour Parquet** plutôt que DuckDB : pandas lit et écrit Parquet par
  pyarrow ; DuckDB n'apporterait rien aux premières questions. À revoir si une table
  devient trop grosse pour la mémoire.
- **openpyxl** : le classeur des notes de sorties doit être facile à remplir (listes
  déroulantes), ce qu'un CSV n'offre pas.
- **Écartées ou repoussées** : pydantic (la frontière sans dépendance de l'ingestion ;
  `0013`) ; polars (statsmodels attend pandas) ; DuckDB ; `arch` (une seule
  fonction utile, la longueur de bloc, écrite dans la piste) ; SHAP (avec la première
  question d'apprentissage qui l'utiliserait).

## Conséquences

- **Facile** : ajouter une bibliothèque à un extra, avec sa PR ; savoir, par le lint,
  qui a le droit de l'importer.
- **Contraignant** : chaque bibliothèque non typée demande son enveloppe ; chaque
  méthode écrite dans la piste demande ses tests de propriété et une simulation de
  couverture ; le lecteur FIT demande un petit écrivain FIT de test.
- **À revisiter** : DuckDB si `processed/` dépasse la mémoire ; le lecteur FIT si
  fitdecode cessait d'être maintenu (le format de base change peu ; les champs
  inconnus restent lisibles) ; `ml` à la première question d'apprentissage.
