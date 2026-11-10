# 0020 — L'origine glissante : la règle d'estimation à l'origine

- **Date** : 2026-11-10
- **Statut** : acceptée (OG-1)

## Contexte

Le backtest projette toutes les performances avec une seule courbe, déclarée une fois
(`0010` D2.6). La courbe neuve de M6b est estimée sur une fenêtre qui contient les
performances qui la mesurent : **un score sur les activités qui ont estimé la courbe ne
valide pas sa généralisation.** Il faut, pour chaque performance, une courbe estimée sur ce
qu'on savait avant elle : non plus une courbe déclarée, mais une **règle d'estimation**.

La même règle sert l'usage : pour préparer une course le jour D, `mperf curve --at D` donne
la courbe « d'aujourd'hui ». Le backtest glissant vient après (OG-2) ; cette décision fixe
la règle, qu'il appellera sans la recoder.

Le cadrage et la passe experte de l'origine glissante sont hors du dépôt, avec les mesures
qui les fondent ; aucun chiffre tiré des données réelles n'est cité ici (règle 1). Les cas
T01 à T23 cités ci-dessous sont des cas construits, jours et valeurs inventés.

## Options envisagées

**La fenêtre.** 28 jours ; 56 jours ; tout le passé ; une demi-vie, qui pondère les sorties
récentes.

**La fin d'une activité.** L'index seul, qui admet la fuite de T01 : une activité que
l'index fait finir avant l'origine et la montre après apporte ce qu'elle a mesuré après
l'origine. La montre seule. La plus tardive des deux. Refuser tout désaccord.

**La borne basse de la fenêtre.** Sur la fin sûre ; sur la fin de l'index ; un horizon de
H heures, vérifié à la montre autour de la borne.

**Le seuil de support.** Fixe à 10 min ; propagé jusqu'au lecteur, qui lirait celui de la
courbe ; un seuil des diagnostics écrit à l'estimation, et la lecture libre du sien.

## Décision

**La règle qui gouverne tout : la courbe à l'origine ne lit que ce qui a fini avant
l'origine.** Une seule fonction de la règle, `estimate_at_origin`
(`estimation/origin.py`) : la commande l'appelle aujourd'hui, le backtest glissant et
l'interface demain. Elle rend la courbe en mémoire et n'écrit rien.

- **O1 — L'origine.** `o` = 00:00 à Paris du jour D − 7, D la date donnée à `--at`
  (`0010` D2.5). La règle reçoit `o`, un instant à fuseau, minuit à Paris, ramené en UTC ;
  un instant naïf ou une heure non nulle à Paris sont refusés. La commande refuse une
  origine postérieure à l'instant présent ; l'origine égale à l'instant est permise.
- **O2 — La fenêtre et sa borne basse.** `W` est un entier de jours d'au moins 1, ou `all`,
  « tout le passé », sans date fictive ; 56 par défaut, un choix d'usage, pas un résultat du
  backtest. La borne basse est `o` reculée de `W` jours **civils** à Paris : la fenêtre
  traverse les changements d'heure, et dure 23 ou 25 h un jour de changement.
- **O3 — La fin sûre et la sélection.** La fin sûre d'une activité est la plus tardive de la
  fin de l'index (départ + écoulé de l'index) et de la fin de l'enregistrement (le dernier
  instant de tous ses canaux, le départ de chaque session et, si elle a un écoulé, sa fin,
  ses événements de chronomètre). Sans écoulé à l'index, la fin est « inférée » ; sans écoulé
  ni enregistrement, « inconnue » : jamais admise. Une activité est **candidate** si sa fin
  sûre est **avant** l'origine et sa fin basse (la fin de l'index, à défaut d'écoulé la fin
  sûre) **à la borne basse ou après**. Elle entre en entier ou pas du tout ; les
  comparaisons sont strictes, sans tolérance. L'index décide **seul** « finie avant la
  fenêtre » (fin de l'index avant la borne basse) et « finie à l'origine ou après » (fin de
  l'index à l'origine ou après) : ces décisions ne lisent pas l'enregistrement. La sélection
  n'est jamais traduite en plage de dates ; celle de `--from/--to` (`0017`, P2.2) reste.
- **O4 — Le corpus et le noyau.** Le corpus (athlète, index, enregistrements, empreinte
  SHA-256 de chaque document lu) est attesté une fois, au chargement, puis contrôlé par son
  constructeur. La règle est un noyau déterministe : sans horloge, sans git, sans fichier,
  sans environnement. L'enveloppe de provenance (commit, `generated_at`) est assemblée par
  la commande.
- **O5 — L'ordre et l'égalité.** L'ordre canonique de l'index, aussi au chargement ;
  l'égalité au bit à mêmes objets, paramètres, code et environnement.
- **O6 — Le sort de chaque activité.** Trois ensembles : inspectées, candidates, retenues et
  contributrices. Chaque référence porte son sort et son motif, par une extension commune de
  l'estimateur (`ActivityFate`) : deux affectations inverses donnent les mêmes tranches, pas
  les mêmes sorts (T21).
- **O7 — L'historique et le démarrage à froid.** Le compagnon publie, sans fenêtre, les
  sorties à pied et celles des types choisis que l'**index** fait finir avant l'origine, et
  celles parties avant l'origine sans écoulé à l'index. Sous 20 sorties à pied connues, un
  avertissement : un repère indicatif, pas un seuil de validité ; avec des sorties à pied
  sans écoulé à l'index, il dit « historique incomplet ».
- **O8 — Les dates.** `data_available_at` est la plus tardive des fins sûres des candidates,
  `last_retained_end` celle des retenues ; aucune date pour un ensemble vide. Ce ne sont ni
  l'instant d'acquisition des exports, ni `generated_at`, ni le figement d'une déclaration.
- **O9 — Trois issues.** Absence (aucune candidate, ou aucune tranche estimée), courbe non
  projetable (des tranches, un support impossible au seuil des diagnostics), courbe
  projetable. Une entrée invalide, seuil hors garde-fous compris, même sans candidate, ou un
  enregistrement manquant au corpus est une erreur, pas une absence. Le diagnostic survit
  sans courbe ; la commande n'écrit rien et dit pourquoi.
- **O10 — Le seuil des diagnostics.** Deux seuils, deux rôles. Le seuil de **lecture**
  (`mperf project --min-support-min`, le curseur de la page Projection, le registre du
  backtest) filtre les tranches sans rien recalculer : inchangé. Le seuil des
  **diagnostics** (`mperf curve --min-support-min`, 10 min par défaut, les garde-fous de
  `curve_min_support_min`) sert à l'estimation à calculer le niveau, la forme, le contrôle
  des lignes et le verdict « projetable » ; elle l'écrit au compagnon
  (`diagnostic_support_threshold_min`), une information, jamais une contrainte de lecture.
  `None` dans une provenance : une courbe d'avant OG-1, aux diagnostics à 10 min.
- **O11 — Le compagnon.** Le document d'estimation porte toujours `mode` (« plage » ou
  « origine ») et `origin` (`null` pour une plage) ; `support_grade_range`, la plage de
  support au seuil des diagnostics, ou `null`. À l'origine, une ligne par activité inspectée,
  dans l'ordre de l'index : sa décision, sa méthode, ses instants, son empreinte, son sort.
  Une ligne que l'index a décidée seul n'a pas lu son enregistrement : elle écrit `null`
  pour la fin sûre et pour l'empreinte ; la méthode décide, pas la décision.
- **O12 — La commande.** `--at` exclut `--from/--to` ; `--window` seulement avec `--at` ; une
  courbe ou un compagnon déjà là, refusés avant toute lecture ; l'horloge lue à la frontière.
  `date_from` et `date_to` de la provenance sont, à l'origine, l'étendue descriptive des
  jours locaux de départ des retenues ; le mode est un champ structuré du document.
- **O13 — L'athlète.** La clé (athlète, référence) pour toute jointure et tout cache ; le
  corpus porte son athlète, la règle refuse un autre athlète que le sien.

## Ce que la règle ne promet pas

- L'égalité entre plateformes.
- Une fin certifiée : la fin sûre est une convention conservatrice de fin connue.
- La version du fichier disponible à l'origine : la fin prouve une antériorité d'événement
  sous convention, pas l'état d'`interim/` à `o` (T15).
- La détection d'une erreur d'étiquette d'athlète : le corpus d'un autre athlète sous ce nom
  reste indétectable, le format d'`interim/` ne porte pas d'athlète.
- L'accord de l'historique avec la règle : il lit l'index seul ; une sortie que l'index fait
  finir avant l'origine et la montre après y compte « finie » (T01), une sortie sans écoulé
  à l'index y est hors des finies et souvent candidate pour la règle.
- La fin sûre d'une activité que l'index décide seul : son enregistrement n'est pas lu, et
  le compagnon écrit `null`.
- La courbe « qu'on aurait eue » : la courbe à l'origine est **reconstituée depuis le corpus
  figé identifié**. Ses diagnostics restent en échantillon.

## Pourquoi

**La plus tardive des deux fins.** L'index seul laisse passer la fuite de T01 ; la montre
seule ignore un index dont l'écoulé dépasse l'enregistrement ; refuser tout désaccord
perdrait des sorties pour un écart d'une fraction de seconde. La plus tardive garde la seule
propriété qui compte : rien de ce qui a eu lieu à l'origine ou après n'entre dans la courbe.

**La borne basse sur la fin de l'index.** La borne basse n'est pas une garde contre la
fuite : aucune information postérieure à l'origine n'y passe, elle dit quelles sorties sont
assez récentes. La fin de l'index suffit, et elle évite de lire un enregistrement pour le
savoir : mesuré hors du dépôt, les mêmes sélections pour bien moins d'enregistrements lus.
Un horizon vérifié à la montre autour de la borne reste possible si une mesure le demande
(`BACKLOG`).

**La lecture libre de son seuil.** Faire lire à chaque lecteur le seuil écrit dans la courbe
changeait `mperf project`, la page et le registre pour un gain nul : le seuil de lecture est
un réglage de la lecture, le seuil des diagnostics un fait de l'estimation.

**La fenêtre et l'historique.** Une demi-vie a été mesurée sans gain sur un banc
multi-athlète, hors du dépôt : la fenêtre déclarée reste. L'avertissement compte les sorties
à pied, pas les seules sorties des types choisis : le repère vient d'un banc qui les compte
ainsi. Un athlète sans candidate n'a pas de courbe : ni la courbe d'un autre athlète, ni un
a priori de population.

**Une seule fonction.** Une règle recodée par la commande, le backtest et l'interface
divergerait ; le noyau sans horloge ni fichier la rend appelable des trois, et testable sans
disque.

## Conséquences

**Ce que ça rend facile.** Une courbe par origine, sans recoder la règle ; un score hors
échantillon pour chaque performance, quand OG-2 l'appellera.

**Ce que ça rend difficile.** Le coût d'une courbe par origine. Le cache viendra à OG-UI et à
OG-2, avec pour clé l'athlète, la référence, l'empreinte du document, la version du code, les
paramètres effectifs du profil, `hr_lag_s`, `hr_min_coverage`, le plafond et l'environnement.

**Ce qu'OG-2 ajoutera.** Le mode glissant du backtest et sa disponibilité (précisions de
`0010` D2.2 et D2.6) ; le refus d'une courbe d'un autre athlète que celui du manifeste ; le
calage (a) (D9.2) ; l'amendement de D9.3 (« sur `C_j` seulement » vaut pour les paramètres
propres des effets, pas pour la règle d'estimation de la base) ; D10.7 entier ; le réservoir
des fourchettes (D11) ; les mêmes courbes par performance (D13) ; le registre au format 6
(D14) ; le rapport (D15).

**Ce qu'il faudra revisiter.** Le support compté en passages (intervalles de 50 m et sorties
distinctes) ; l'horizon des fins à la borne basse ; les sorties en bordure de fenêtre.
