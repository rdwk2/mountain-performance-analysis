# Interface : `just ui`

L'interface ([`0016`](../decisions/0016-interface-v0.md)) est une appli Streamlit
locale, sur `MPA_DATA_DIR`, avec les extras `tableau` et `analyse`. Elle ne calcule rien
(règle 7 de [`CLAUDE.md`](../../CLAUDE.md)) : ce qu'elle montre vient des fonctions mêmes de
`mperf` et de la bibliothèque. Quatre pages : « projection » et « sortie » (M5),
« récupération » et « Q1 » (la piste analyse, AN2-3).

```bash
just ui
```

puis `http://localhost:8501` dans le navigateur.

- **L'ajout d'un fichier** (barre latérale, sur les pages « projection » et « sortie ») : un GPX téléversé va,
  au choix, dans les préparés (`routes/`) ou dans les sorties (`sorties/`, une trace
  horodatée). Il est lu d'abord, comme la page le lira, puis écrit sous son nom, au clic
  seulement ; un fichier de même nom n'est jamais écrasé, et rien n'est supprimé.
- **La page « projection »** : un préparé (un GPX de `MPA_DATA_DIR/routes/`) et une
  courbe (un CSV de `MPA_DATA_DIR/reference/` et son compagnon `.meta.json`), choisis
  dans la barre latérale.
  - **Les réglages** sont générés depuis les specs des paramètres du profil et du
    moteur : un curseur par paramètre, sur sa plage d'affichage.
  - **Elle montre** la synthèse de `mperf project` (son texte même), le profil avec les
    passages, la vitesse projetée, et le tableau des passages, avec, pour chaque
    tronçon, l'allure et la montée horaire moyennes ; une heure de départ facultative, à
    l'heure de Paris, donne l'heure de chaque passage.
  - **L'export CSV** des passages a le texte de `mperf project --csv` lancée avec les
    seules options qui s'écartent d'un défaut (aux fins de ligne près : sous Windows, la
    commande écrit des CRLF, la page des LF). C'est un format pour un programme
    (virgules, point décimal, UTF-8 sans marque d'en-tête) : Excel en français ne
    l'ouvre pas tel quel (`BACKLOG.md`).
- **La page « sortie »** : un préparé, la trace d'une sortie faite sur lui (un GPX de
  `MPA_DATA_DIR/sorties/`) et une courbe, puis « Comparer » : rien n'est calculé avant
  le clic. Elle montre le jour de la sortie (le jour à Paris de son premier instant),
  la partie comparée du préparé et le préfixe comparable (`0010` D4.11), prévu contre
  réalisé sous les horloges du rapport, et l'effort effectif `e* = exp(L)` sur le
  préparé et sur le chemin suivi, avec ses limites : rétrospectif, limité à la partie
  comparée, faussé par les arrêts sous l'écoulé, il mêle l'effort du jour et l'erreur
  du modèle, et, sur le préparé, l'écart entre le préparé et le chemin suivi. Puis
  l'écart cumulé aux points, et le plus grand. Un avertissement en tête quand la sortie
  tombe dans la période d'estimation de la courbe (`0010` D2.2). C'est le contrôle d'une
  sortie par v0 brut, à l'effort 1, sans réglage, et rien n'est écrit : pas une erreur
  du modèle, dont le chiffre qui fait foi reste celui du backtest. Le détail (régimes,
  enveloppes, épisodes) : `mperf match --curve`.
- **La page « récupération »** : la table `jours` de `processed/`, sans rien calculer
  ([`0019`](../decisions/0019-table-jours-et-normales.md), section AN2-3). Les six
  mesures de la nuit et du repos, chacune contre sa normale et sa plage : un point plein
  pour une valeur admise dans la normale, un point creux pour une valeur écartée (la
  raison au survol), un trait gris en pied quand il n'y a pas de valeur ; la normale en
  pointillé quand sa fenêtre mêle l'avant et l'après d'une rupture ou d'un jour
  incertain. Puis le journal (`journal.csv`) en rubans, l'activité du jour (durées par
  famille, charge selon Garmin), et, à part, la HRV selon Garmin. Par défaut les 8
  dernières semaines, au choix toute la table. Exploratoire : aucune alerte, aucun
  verdict. Les tables restent en mémoire tant que leur provenance ne change pas.
- **La page « Q1 »** : la dernière figure écrite par `just q1`, telle quelle, avec sa
  date, et un avertissement si elle ne vient pas des tables actuelles
  ([`0015`](../decisions/0015-figure-de-q1.md), section AN2-3).
