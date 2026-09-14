# 0006 — Le temps

- **Date** : 2026-09-13
- **Statut** : acceptée

## Contexte

Les effets de chaleur et de nuit du modèle raisonnent en heure locale. Garmin fournit
`startTimeLocal` à côté d'instants en UTC, et les fichiers GPX horodatent en UTC.
Python autorise des `datetime` naïfs, sans fuseau, qui se comparent entre eux sans
erreur. La question : quelle représentation du temps circule dans le code ?

## Options envisagées

**A. Heure locale naïve**, comme on la lit sur la montre.

**B. Instants *aware*, stockage et comparaisons en UTC, décalage local conservé à
côté** ; les durées restent des offsets en secondes.

**C. Timestamps numériques** (secondes depuis l'époque) partout.

## Décision

Option B : tout `datetime` est *aware* ; stockage et comparaisons en UTC ; le
décalage local est conservé à côté (`utc_offset_s`) là où l'heure locale sert ; les
durées sont des secondes (`duration_s`, `cutoff_s`).

## Pourquoi

Un `datetime` naïf se propage sans bruit et produit des décalages d'une heure
(changement d'heure, fuseau d'une course à l'étranger) qui ressemblent à des erreurs
de modèle et coûtent des jours à diagnostiquer. A est donc écartée.

C perd le fuseau et rend chaque lecture humaine pénible ; elle ne dispense pas de
conserver l'heure locale pour les effets de chaleur et de nuit.

C'est le même raisonnement que `0002` sur les unités : une représentation interne
unique, des conversions aux frontières.

**Heure solaire.** Ce qui compte physiquement pour la chaleur et la nuit est l'heure
*solaire*, mieux approchée par la longitude que par le fuseau administratif. Sur les
Alpes l'écart est de quelques dizaines de minutes : négligeable aujourd'hui, à
ressortir le jour où une course se projette à l'autre bout d'un fuseau.

## Conséquences

- La validation refuse le `datetime` naïf à la construction (`require_aware`), et
  les contrats normalisent en UTC (`SourceRef.retrieved_at` dès M1a).
- `utc_offset_s` apparaît avec les types qui ont un usage de l'heure locale
  (`Activity`, M1b) ; la note sur l'heure solaire y sera reprise en docstring.
- L'heure solaire (longitude) reste une approximation future si le projet sort des
  Alpes.

> **Note du 2026-09-14 (M1b) — précision du stockage.** *Aware* partout reste la
> décision. La normalisation en UTC ne s'applique qu'aux instants **sans heure locale
> signifiante** (`SourceRef.retrieved_at`, `generated_at`). Un instant dont l'heure
> locale a un sens physique (`Activity.start_time`, `Projection.start_time`) se stocke
> dans **son fuseau à décalage fixe**, et le décalage est porté par ce fuseau plutôt
> que par un champ parallèle : `utc_offset_s` est une propriété lue sur le fuseau.
> Raison : normaliser en UTC puis garder un champ `utc_offset_s` à côté faisait deux
> sources de vérité (`0007`), dont le recoupement n'était pas idempotent — un objet
> normalisé ne se re-validait plus.
