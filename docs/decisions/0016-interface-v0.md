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
  formats de `units.py`), sans changer la sortie de `mperf`. L'export de la page a le
  texte de `mperf project --csv` lancée avec les seules options qui s'écartent d'un
  défaut, aux fins de ligne près (la commande écrit des CRLF sous Windows). Ce que la
  page calcule est dans `model/views.py`.
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
  autres, sauf pour mettre en commun ce qu'elles partagent (M5-2 : l'abscisse des
  figures, `DISTANCE_AXIS`, passée de la page « projection » à `components.py`).
- **Choix reporté** : l'allure et la montée horaire moyennes sont montrées toutes deux,
  pour chaque tronçon ; le choix selon le régime de `0002`, et le seuil de pente qu'il
  demande, sont reportés à M9 (note datée dans `0002`).
- **Contraignant** : l'extra tire une trentaine de paquets, sans toucher au cœur ;
  `mypy` en deux étapes (sans l'extra, Streamlit vaut `Any` ; avec, ses types
  s'appliquent), et le code de `ui/` doit passer les deux.
- **À revisiter** : un cache (`st.cache_data`), si un long tracé rend la page lente ; un
  dossier d'ajout au choix, si le besoin revient.

## M5-2 — la page « sortie » (2026-10-22)

- **Ce qu'elle fait** : elle compare une sortie à son préparé par `mperf match --curve` —
  un préparé de `routes/`, une trace de `sorties/`, une courbe de `reference/`, puis
  « Comparer ». C'est le contrôle d'une sortie par **v0 brut à l'effort 1**, sans
  manifeste, ni calage, ni baselines, sans réglage (les paramètres de l'appariement à
  leurs défauts) ; elle ne rejoue pas le backtest et **n'écrit rien**, ni au registre ni
  ailleurs. Ce n'est pas une erreur du modèle : le chiffre qui fait foi reste celui du
  backtest. Le calcul ne se fait qu'au clic ; le résultat est gardé dans
  `st.session_state` avec les trois fichiers comparés, et masqué quand un autre trio est
  choisi.
- **L'enchaînement** de `mperf match` est dans `runs.py` (`match_outing`, puis
  `check_outing`, en deux temps comme la commande, qui imprime ses dix premières sections
  avant de calculer les scores) ; la commande et la page l'appellent, et la sortie de
  `mperf match` n'a pas changé. Ce que la page montre en plus est dans `outing_views.py`,
  qui ne lit que les contrats, avec les libellés que la commande et la page partagent.
- **Pourquoi `runs.py` importe `backtest/` et `ui/` non** : l'appariement, les passages
  et les scores de v0 brut vivent dans `backtest/` ; les recopier coderait deux fois la
  même chose. `runs.py` n'en importe que les **modules purs** — `calendar`, `geometry`,
  `matching`, `passages`, `scoring`, `segments` —, jamais le registre, l'exécution
  enregistrée ni le paquet lui-même ; une liste testée le dit
  (`tests/test_ui_imports.py`, `RUNS_BACKTEST_MODULES`). `ui/` n'importe toujours aucun
  module de `backtest/` : l'interface ne touche jamais au protocole scellé.
- **L'effort effectif** : `e* = exp(L)`, `L` le niveau du support (`0010` D7.1), celui
  que publie `mperf match`, jamais celui du sous-support à temps positifs (D5.5), qui est
  un diagnostic. Pour v0, la durée prévue est inversement proportionnelle à l'effort,
  donc `e* = P / T` : l'effort auquel v0 aurait prévu le temps réel sur la partie
  comparée. Il est montré sous chaque horloge du rapport, **sur le préparé** (usage) et
  **sur le chemin suivi** (contrôle), côte à côte : le temps réel `T` est le même, seul
  le temps prévu change, et le rapport des deux vaut `exp(G)`, `G = L_usage −
  L_contrôle` (`0010` D3). Ses limites, écrites dans la page : il est rétrospectif ;
  limité au support comparé ; faussé par les arrêts sous l'écoulé ; il mêle l'effort du
  jour et l'erreur du modèle (la courbe, les pentes) ; sur le préparé, s'y ajoute l'écart
  entre le préparé et le chemin suivi (raccourcis, détours, GPS).
- **« Dans la fenêtre »** : la règle de `0010` D2.2, celle des fourchettes — le **jour
  civil à Paris du premier instant de la trace**, entre `date_from` et `date_to` du
  compagnon de la courbe, bornes comprises. Dans la fenêtre, un avertissement en tête de
  la page : l'écart y est optimiste. Ce jour est écrit en tête de la page.
- **La partie comparée et le préfixe comparable** sont deux publications distinctes de
  `0010` D4.11, écrites séparément : la partie comparée (tous les segments admis, sa
  part du préparé) peut aller au-delà du préfixe comparable (jusqu'au premier segment
  non admis), où s'arrêtent les écarts aux points. L'écart cumulé `C_k` (`0010` D7.3)
  est celui de l'usage, avec le plus grand en valeur absolue sous chaque horloge.
- **Ce qui n'est pas montré** : les régimes (`E_R`, `D_R`), les enveloppes, les épisodes
  d'arrêt, `q_usage`, le rapport complet ; on les lit dans `mperf match --curve`
  (`BACKLOG.md`, si le détail manque à l'usage).
