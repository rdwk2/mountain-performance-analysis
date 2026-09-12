# BACKLOG

> Une ligne par idée. On n'implémente rien depuis ce fichier : on y pioche au
> moment de planifier le jalon suivant, et l'idée retenue devient une issue.
> Ajouter en bas. Barrer et dater quand c'est fait.

Format : `- [ ] (jalon visé) idée — pourquoi`

---

## Modèle

*(repris du `NOTES_MODELE.md` de l'ancien projet — c'était déjà une bonne liste)*

- [ ] (M6a) Calibrer les paramètres de fatigue sur des passages réels au lieu de les deviner à la main
- [ ] (M8) Deux courbes de descente : roulant / faux-plat vs raide — la faiblesse est spécifiquement sur le roulant (−37 % vs −23 %)
- [ ] (M7) Chaleur basée sur la température réelle de l'activité au lieu du forfait horaire
- [ ] (M7) Acclimatation à la chaleur comme modulateur (métrique Garmin disponible)
- [ ] (M6a) Fatigue cumulée en D+ encaissé (quads), en plus de la fraction de course
- [ ] (M7) Dette de sommeil réelle (Body Battery / heures de sommeil) au lieu du forfait nuit
- [ ] (M6b) Recalibrer la courbe après chaque bloc d'entraînement, et par saison
- [ ] (M4) Valider la prédiction contre une course réelle le jour J → boucle de correction
- [ ] (M6a) Effet d'altitude affiné par tranche d'altitude réelle plutôt qu'un seuil unique
- [ ] (M8) Fourchettes P50/P80 dérivées des données au lieu de trois jeux de paramètres à la main
- [ ] (M8) Vérifier la calibration de l'intervalle : ~80 % des temps réels dans le P80, sinon l'intervalle ment
- [ ] Effet de la technicité du terrain (non capturé par la pente seule) — commencer par regarder si le résidu du backtest corrèle avec quelque chose de mesurable
- [ ] Sensibilité du modèle : quel paramètre bouge le plus le temps final ? Utile pour savoir où investir

## Données et ingestion

- [ ] (M6b) Reprise après coupure et gestion du 429 Garmin (déjà résolu dans l'ancien script, à ne pas réinventer)
- [ ] Détecter et signaler les activités aberrantes (GPS perdu, pause oubliée, tapis)
- [ ] Températures : croiser météo de l'activité et capteur de la montre, voir lequel prédit le mieux
- [ ] Import de traces autres que Garmin (GPX/FIT génériques) pour ne pas être enfermé

## Outil et interface

- [ ] (M9) Comparer deux scénarios côte à côte sur le même tracé
- [ ] (M9) Export d'une table de marche imprimable (l'ancien projet produisait une fiche PDF utile en course)
- [ ] Points de ravitaillement / waypoints du GPX affichés dans le tableau de passages
- [ ] Plan hydrique et nutrition dérivé du temps par segment et de la température

## Long terme — hors périmètre actuel

- [ ] VTT : le modèle allure↔pente ne se transpose pas tel quel, il faut repartir des données
- [ ] Ski de randonnée : idem, plus la neige comme variable
- [ ] Corrélations données santé (HRV, sommeil, stress) × charge d'entraînement
- [ ] Déploiement en ligne : question ouverte de l'import et de la conservation des données d'autres utilisateurs
- [ ] Planification d'entraînement à partir du modèle

## Outillage et dépôt

- [ ] Commiter un `.vscode/settings.json` minimal (`"files.eol": "\n"`) et ajuster le `.gitignore`, qui exclut aujourd'hui tout `.vscode/` — évite de recréer des fichiers CRLF à la main
- [ ] Activer la protection de la branche `main` : exiger une pull request, puis ajouter l'exigence de CI verte une fois que le workflow a tourné au moins une fois