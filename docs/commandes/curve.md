# `just curve` — la courbe personnelle

`just curve` (`mperf curve`) estime une courbe allure ↔ pente depuis les activités de
`MPA_DATA_DIR/interim/` — l'`interim/` régénéré par `just ingest`, lu par les vues du
moteur, jamais `processed/` — et l'écrit dans `MPA_DATA_DIR/reference/<nom>.csv`, avec
son compagnon `<nom>.meta.json` ; ni l'un ni l'autre n'est jamais réécrit
([`0017`](../decisions/0017-estimation-de-la-courbe.md)).

La courbe se mesure comme le moteur l'applique : sur les intervalles de la grille du
profil du moteur, chacun avec la pente de l'altitude lissée du profil, sa longueur
entière (la distance des positions brutes, trous compris) et son temps en mouvement
sous la convention centrale θc (`0010` D5) ; une vitesse écoulée s'y ajoute, par tranche.
Les tranches sont variables (2,5 % de −15 à +35 %, 5 % ailleurs jusqu'à ±40 %, 10 %
au-delà), à centres nominaux ; la valeur d'une tranche est (a), la somme des longueurs
sur la somme des temps en mouvement, ou, en option, (b), la médiane des vitesses des
activités. Le compagnon dit les quantiles p10, p50 et p90 du niveau des activités (le
niveau d'une activité : son temps en mouvement contre le temps que le moteur prévoit sur
la courbe, un diagnostic d'ajustement, en échantillon ; les niveaux par activité ne sont
pas gardés) et, par tranche, la forme de la courbe (l'écart interquartile, le niveau
retiré). Avec `--hr-center`, un filtre de FC ne garde que les intervalles dont la FC,
décalée de 60 s, est dans une bande de 10 bpm, aux pentes de −5 % ou plus seulement.

| Option | Défaut | Rôle |
|---|---|---|
| `--from`, `--to` | — (avec `--to` / `--from`, ou `--at`) | Premier et dernier jour de la plage, compris (`AAAA-MM-JJ`) |
| `--at` | — | Jour D de la règle à l'origine (`AAAA-MM-JJ`) ; exclut `--from` et `--to` |
| `--window` | 56 | Fenêtre de la règle, en jours, ou `all` ; avec `--at` |
| `--athlete` | — (obligatoire) | Pseudonyme de l'athlète (celui du manifeste) |
| `--types` | `trail_running` | Types de la source retenus, séparés par des virgules, sans espace |
| `--min-duration-min` | — | Durée minimale d'une sortie, en minutes |
| `--max-duration-min` | — | Durée maximale (exclue) d'une sortie, en minutes |
| `--max-elapsed-min` | — | Plafond depuis le départ, en minutes |
| `--hr-center` | — | Centre de la bande de FC (bpm) |
| `--hr-width` | 10 | Largeur de la bande (bpm) |
| `--hr-lag` | 60 | Décalage de la FC (s) |
| `--min-support-min` | 10 | Seuil de support des diagnostics (niveau, forme, verdict) ; une lecture garde le sien |
| `--value` | `a` | Valeur d'une tranche : (a) somme / somme, (b) médiane des activités |

```bash
just curve <nom> --from AAAA-MM-JJ --to AAAA-MM-JJ --athlete <pseudonyme>
just curve <nom> --at AAAA-MM-JJ --athlete <pseudonyme>
```

**À une origine.** `--at D` estime la courbe que la règle donne à l'origine, 00:00 à Paris
de D − 7 jours ([`0020`](../decisions/0020-origine-glissante.md)) : sur les activités
finies avant l'origine (l'activité entière, la plus tardive des fins de l'index et de la
montre) et, pour une fenêtre de W jours, dont la fin d'index est dans les W jours civils
avant l'origine. C'est une courbe **reconstituée depuis le corpus figé identifié**. Le résumé
dit l'origine, les décisions, l'historique et l'avertissement des moins de 20 sorties à
pied ; une absence n'écrit rien.

Comme [`just backtest`](backtest.md), la commande refuse un clone dont un fichier suivi est modifié :
la courbe dit le commit qui l'a estimée. Une courbe dont le support ne se lit pas
(`0009` D2) s'écrit quand même, sans niveau ni forme, et la commande le dit. Elle donne
les activités retenues et les tranches, les écarts par motif, les intervalles coupés au
plafond, le nombre d'activités avec un niveau et le rapport écoulé / temps en mouvement.
Pas d'exemple ici : sur les données réelles, ces nombres restent hors du dépôt. Le
détail est dans [`0017`](../decisions/0017-estimation-de-la-courbe.md).
