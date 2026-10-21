# 0016 — Interface v0

- **Date** : 2026-10-21
- **Statut** : acceptée (M5-1)

## Contexte

M5 de la ROADMAP : une interface « volontairement laide », pour avoir l'outil sous la
main tous les jours et vérifier que l'API du moteur est utilisable — charger un GPX,
choisir une courbe, régler les paramètres, voir le profil et le tableau des passages,
exporter en CSV, sans passer par la ligne de commande. L'interface génère ses contrôles
à partir du schéma de paramètres du moteur.

Contraintes déjà fixées :
- **Règle 7** de `CLAUDE.md` : pas de logique métier dans l'interface ; si elle calcule
  quelque chose, c'est que ça manque dans `src/`.
- **`0011`** : un extra `tableau` (Streamlit) existe déjà sur le papier, pour le tableau
  de bord de la piste analyse, et `ui/` est réservé à l'interface de M5.
- Le besoin de rdw : préparer une vraie sortie sans ligne de commande ; la piste
  analyse propose une seule appli, commune à l'interface du moteur et au tableau de bord
  d'AN2.

## Options envisagées

**A. Streamlit, extra `tableau`.** Pour : déjà accepté par `0011` pour le tableau de
bord ; contrôles, graphique, tableau, téléversement et téléchargement en quelques
lignes ; tests sans navigateur (`streamlit.testing.v1.AppTest`) ; typé (`py.typed`).
Contre : l'extra tire une trentaine de paquets (pandas, numpy, altair, starlette,
uvicorn…), mais le cœur n'en dépend pas (CI en deux temps) ; télémétrie active par
défaut, à couper.

**B. marimo en mode application.** Pour : prévu par `0011` dans le groupe
`analyse-dev`, que `0012` lui donne (le groupe n'existe pas encore). Contre : `0012` en
fait l'outil des notebooks jetables ; mêler les deux rôles brouille la règle 7.

**C. Une page HTML écrite par une commande.** Pour : aucune dépendance. Contre : pas de
réglage interactif ; il faut relancer la commande à chaque réglage, contraire à
« régler les paramètres, voir ».

**D. tkinter** (bibliothèque standard). Pour : aucune dépendance. Contre : graphique
dessiné à la main, code d'interface plus long, rien de partageable avec AN2.

## Décision

Streamlit (option A), en une seule appli multipage sous `src/mountain_perf/ui/` ; M5
ouvre l'extra `tableau`.

- **Les contrôles** sont générés depuis les specs des paramètres (`controls.py`), avec
  des plages d'affichage non stockées (`ParameterDisplay`), déclarées à côté de chaque
  tuple de specs.
- **Les fichiers** : un GPX est ajouté par téléversement, au choix dans `routes/` (un
  préparé) ou `sorties/` (une sortie) de `MPA_DATA_DIR` ; il est vérifié avant d'être
  écrit, n'en écrase jamais un autre, et rien n'est supprimé (`data_files.py`). La
  courbe est choisie dans `reference/`.
- **Rien n'est codé en deux fois** : ce qui vivait dans `cli.py` et que l'interface
  appelle passe en bibliothèque (`runs.py`, `reports.py`, `model/export.py`, trois
  formats de `units.py`), sans changer la sortie de `mperf`. L'export de la page est
  celui de `mperf project --csv` lancée avec les seules options qui s'écartent d'un
  défaut. Ce que la page calcule est dans `model/views.py`.
- **Les pages** : deux pages, deux PR (M5-1, la projection ; M5-2, la sortie) ; une page
  par module de `ui/`, déclarée par une ligne de `PAGES` dans `ui/app.py`.
- **La configuration** de Streamlit est dans `.streamlit/config.toml`, versionné : le
  serveur n'écoute que la machine, sans télémétrie.
- **Les clôtures** : `ui/` n'importe que la bibliothèque standard, `mountain_perf` et
  `streamlit` (un test, `tests/test_ui_imports.py`) ; Streamlit ne s'importe que sous
  `ui/` et dans ses tests, et pandas, numpy, altair nulle part ailleurs (TID251) ;
  Claude Code ne lance pas l'interface (le hook de `.claude/settings.json`).

## Pourquoi

- **Streamlit** est déjà accepté par `0011` pour le tableau de bord, se teste sans
  navigateur et est typé. **marimo** est réservé par `0012` aux notebooks jetables ; une
  **page HTML** n'a pas de réglage interactif ; **tkinter** n'a ni graphique ni partage
  avec AN2.
- **`ParameterDisplay` plutôt qu'un champ de `ParameterSpec`** : `ParameterSpec` est
  stocké au registre (`Declaration.matching` est un `ParameterSet`, qui porte ses
  specs) ; un champ de plus y demanderait un format de plus, pour un besoin
  d'affichage.
- **Deux dossiers fixes** : une appli dans un navigateur n'ouvre pas de sélecteur de
  dossier sur la machine.
- **Rien codé en deux fois** : une commande et une page qui font la même chose
  appellent la même fonction ; la même erreur sort la première, et le texte affiché est
  celui que la commande imprime.

## Conséquences

- **Facile** : un effet ajouté au moteur avec sa spec apparaît dans l'interface ; M5-2
  et AN2 ajoutent chacune une page (un module et une ligne de `PAGES`) sans toucher aux
  autres.
- **Choix reporté** : l'allure et la montée horaire moyennes sont montrées toutes deux,
  pour chaque tronçon ; le choix selon le régime de `0002`, et le seuil de pente qu'il
  demande, sont reportés à M9 (note datée dans `0002`).
- **Contraignant** : l'extra tire une trentaine de paquets, sans toucher au cœur ;
  `mypy` en deux étapes (sans l'extra, Streamlit vaut `Any` ; avec, ses types
  s'appliquent), et le code de `ui/` doit passer les deux.
- **À revisiter** : un cache (`st.cache_data`), si un long tracé rend la page lente ; un
  dossier d'ajout au choix, si le besoin revient.
