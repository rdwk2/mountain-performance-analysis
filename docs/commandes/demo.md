# `just demo` — les profils de démo

[← Les commandes](README.md)

`just demo <personnage>` construit, s'il manque, un dossier de démo sous `demo/<personnage>/` à
la racine du dépôt, puis lance l'interface dessus. Les données sont entièrement inventées,
construites à la demande et ignorées par git ([`0022`](../decisions/0022-profils-de-demo.md)).
Les nombres de la démo illustrent la chaîne ; ils ne mesurent pas le modèle.

```bash
just demo polyvalente
```

L'interface s'ouvre sur `http://localhost:8512` (le port est 8511 + le rang du personnage :
deux personnages se comparent dans deux onglets). Ctrl+C l'arrête.

## Les personnages

| Personnage | Port | Son entraînement | Ce qu'il montre |
|---|---|---|---|
| `debutant` | 8511 | 12 sorties en 5 semaines, pentes douces | l'avertissement « moins de 20 sorties » ; la course au-delà de son support ; à l'origine de la course à deux parties (bornée), la fenêtre de 28 jours lit 9 de ses sorties, celle de 56 les 12 (« tout le passé » y est identique) ; au jour par défaut, les deux en lisent 10 |
| `polyvalente` | 8512 | 4 mois, raide et roulant | le cas complet : lieux nommés, origine bornée, sortie face à son préparé, récupération, Q1 |
| `grimpeur` | 8513 | surtout le raide | rapide sur la partie raide, lent sur la roulante |
| `rouleur` | 8514 | surtout le roulant | l'inverse ; la partie raide hors de son support |
| `moyen` | 8515 | la pente moyenne | entre les deux ; la partie raide hors de son support |

Tous préparent deux courses inventées : `course_raide.gpx`, cinq jours après la construction,
et `deux_parties.gpx` (10 km très raides, puis 20 km roulants), trois semaines après. Leurs
historiques finissent la veille de la construction. Leurs jours portent les mêmes événements,
aux mêmes dates : une maladie de trois jours, un séjour en altitude, une course passée, un
changement de l'appareil des nuits (les sorties gardent leur montre) et deux nuits sans SpO2 ; la page récupération montre ainsi chaque marque
qu'elle sait montrer. Une normale demande 14 jours admis sur les 28 qui précèdent : le débutant
(35 jours d'historique) n'en a qu'à partir de son vingt-deuxième jour, et sa maladie et son séjour
tombent avant.

## Les dates

Le dossier est calé sur le jour où il est construit. Ouvert plus tard, il perd ses scénarios :
la course raide passe au sixième jour ; la course à deux parties n'est plus bornée au
quatorzième ; au soixante-deuxième, la fenêtre de 56 jours ne contient plus aucune activité.
La commande le dit à chaque lancement ; elle ne supprime rien : pour régénérer un dossier,
supprime-le.

## Les autres commandes sur un dossier de démo

`MPA_DATA_DIR` posé pour la commande seule, depuis la racine du dépôt. Sous bash, pour un dossier
construit le 2026-11-13 (les dates suivent celles que la commande affiche) :

```bash
MPA_DATA_DIR=demo/polyvalente just project deux_parties.gpx --at 2026-12-04
MPA_DATA_DIR=demo/polyvalente just curve essai --at 2026-11-18 --athlete polyvalente
```

La première projette la course à deux parties sur la courbe à son origine (bornée à
aujourd'hui) ; la seconde écrit la courbe à l'origine de la course raide dans `reference/`
(`mperf curve --at` refuse une origine à venir : son jour doit être au plus aujourd'hui + 7
jours).

Sous PowerShell : `$env:MPA_DATA_DIR = "demo/polyvalente"`, la commande, puis
`Remove-Item Env:MPA_DATA_DIR`. Une variable posée l'emporte sur `.env`. Ne pas pointer `.env`
dans `demo/` : le vrai dossier des données ne serait plus protégé par le hook, qui refuserait
en outre aux sessions Claude Code les recherches à la racine du dépôt (elle contiendrait le
dossier des données). Un dossier de démo ne reçoit que de l'inventé : une trace réelle (une
sortie, un préparé) va dans le dossier des données, jamais dans `demo/`.

Sans `just` : `uv run --extra ingest --extra analyse --extra tableau mperf demo polyvalente
--interface` ; sans `--interface`, la commande construit le dossier et s'arrête.
