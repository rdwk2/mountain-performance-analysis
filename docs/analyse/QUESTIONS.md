# Questions de la piste analyse

*Version 1, validée le 2026-10-07. Ne contient aucun chiffre tiré des données.*

*Écrite avant toute analyse des relations entre variables : l'examen des données n'a
décrit les variables qu'une à une. Une version suivante s'écrira quand de nouvelles
questions viendront ; elle sera datée.*

## Principes

1. **Pour tout athlète.** Les questions sont celles de l'athlète qui a lancé le
   projet, mais le code qui y répond doit servir aussi à un autre athlète, sur ses
   propres données : aucun seuil propre à un athlète dans le code (FC max, zones,
   seuils de « grosse sortie », normales) ; tout cela se calcule depuis les données de
   l'athlète ou se déclare dans sa configuration.
2. **Une question = une unité, une mesure, un facteur, des confusions nommées.** La
   méthode détaillée, les bases à battre et le nombre d'essais viennent dans le plan
   d'analyse de chaque question, relu avant le code. Les confusions nommées ici sont
   les variables à traiter ; le schéma causal du plan dit, pour chacune, si elle
   confond ou si elle transmet l'effet (charte, § 5).
3. **« Déjà vue »** : une question dont une réponse a déjà été affichée sur les mêmes
   données (un tableau de bord antérieur, un notebook) reste exploratoire sur ces
   données ; elle ne se confirme que sur des données postérieures à sa déclaration
   (charte, § 8). Ce que chaque athlète a déjà vu se note hors du dépôt, avec ses
   données (`resultats/deja_vu.csv`, charte, § 10). Sur les données d'un autre
   athlète, aucune question n'est « déjà vue ». Ce marquage ne change pas l'ordre des
   questions : la piste refait tout.
4. **Chaque test compte pour un essai** ; la charte dit comment on les compte.

## Thème A — Progression

**Q1 — La VAM progresse-t-elle, à pente, durée et altitude comparables ?** *(AN1 :
figure descriptive ; inférence dans un jalon de question)*
- En régimes séparés, qui ne se comparent pas entre eux : (a) montées longues ; (b)
  côtes courtes ; (c) ski de randonnée. Raison : le terrain pratiqué peut changer avec
  la saison, et la date seule mêle alors forme et terrain.
- Unité : la montée (segment du profil du moteur, au-dessus d'une pente et d'une durée
  minimales), regroupée par sortie. Mesure : `vertical_speed_ms` = D+ ÷ temps de
  mouvement. Facteur : la date.
- Confusions : pente, durée de la montée, altitude, chaleur, place dans la sortie,
  intention, technicité, sac, intensité choisie (FC).

**Q2 — L'efficience en montée progresse-t-elle (VAM à FC comparable, ou par battement
au-dessus de la FC de repos) ?** Unité : la montée. Confusions : dérive cardiaque,
chaleur, FC optique, FC de repos du jour.

**Q3 — La VAM tient-elle au fil d'une longue sortie, et sa baisse diminue-t-elle au
fil de la saison ?** Unité : la montée, dans les sorties longues. Confusions :
l'altitude monte au fil de la sortie, le terrain change, les arrêts, la chaleur de la
journée. Lien : BACKLOG (M6a), « Fatigue cumulée en D+ encaissé ».

**Q4 — La descente progresse-t-elle, en raide et en roulant ?** Lien : BACKLOG (M8),
deux courbes de descente.

**Q12 — L'économie sur le plat progresse-t-elle, à FC comparable ?** Unité : les
segments plats. Confusions : altitude, chaleur, terrain.

## Thème B — Récupération

**Q5 — Après une grosse sortie, combien de nuits pour revenir à la normale (HRV de la
nuit, FC de repos) ?** Unité : l'événement « grosse sortie » (seuils fixés d'avance
dans le plan), suivi sur les nuits suivantes ; la normale est calculée par la piste
(fenêtre glissante), pas reprise de Garmin. Rappel : Garmin rattache une nuit au jour
du réveil. Confusions : sorties enchaînées, nuit en altitude, sommeil court, maladie.

**Q6 — La charge du jour se lit-elle dans les nuits suivantes (relation dose-réponse,
à plusieurs décalages) ?** Unité : le jour ; jours voisins dépendants (erreurs HAC ou
bootstrap par blocs).

**Q7 — Une grosse sortie change-t-elle la nuit qui suit (durée, FC de nuit, stress de
nuit) ?**

**Q13 — À charge comparable, le VTT coûte-t-il plus en récupération que le trail ?**
Unité : la sortie et les nuits suivantes. Confusions : durée, intensité,
enchaînements.

## Thème C — État du jour et performance

**Q8 — La nuit d'avant pèse-t-elle sur la performance (VAM à pente comparable, ou
résidu du moteur) ?** Unité : la sortie. Le calcul de puissance du plan dira quel
effet est visible ; « rien de visible » est une réponse. Lien : M7 (dette de
sommeil) ; une hypothèse retenue se déclare au registre du moteur.

**Q9 — Les indicateurs de Garmin (Training Readiness du réveil, Body Battery du matin,
statut HRV) prédisent-ils la journée mieux qu'une base naïve (« comme
d'habitude ») ?** Unité : la sortie.

## Thème D — Environnement

**Q10 — La chaleur pèse-t-elle sur la VAM et la FC, et sur la récupération, le
sommeil, le stress, à court et à long terme ?** Trois températures à distinguer : la
météo réelle au lieu et à l'altitude de la sortie (réanalyse ou station, à choisir),
la température du capteur de la montre (chauffée par le corps, donc reflet de la
charge thermique), et l'acclimatation que Garmin estime. Confusions : chaleur, saison,
région et altitude vont ensemble. Liens : BACKLOG, « croiser météo de l'activité et
capteur de la montre » ; M7.

**Q11 — L'altitude ralentit-elle la VAM, et l'acclimatation y change-t-elle quelque
chose ?** Lien : BACKLOG (M6a), effet d'altitude par tranche.

## Contrôle préalable (charte)

Les métriques calculées par Garmin changent-elles de niveau aux changements de
firmware ? À vérifier avant toute question qui les utilise.

## Ce que les questions demandent en plus des données Garmin

Un journal des événements tenu par l'athlète (blessure, maladie, course, déménagement,
séjour en altitude) : des facteurs de confusion que Garmin ne contient pas. La charte
le définit.

## Ordre des jalons (décidé le 2026-10-07)

- **AN1** : ingestion des activités ; tables `activités` et `montées` ; figure de Q1.
- **AN2** : ingestion des données journalières ; tableau de bord de suivi de la
  récupération.
- **Ensuite, une question (ou deux très proches) par jalon**, numéroté à son
  ouverture. Ordre choisi : Q2, Q3, Q4 ; les suivantes se choisissent à l'ouverture de
  chaque jalon.
