# Modèle v1 — spécification de départ

> **Statut : point de départ, pas vérité.**
> Ce document reprend le modèle construit sur la version précédente du projet
> (v2026.1). Les équations sont une bonne base de travail ; **les valeurs
> numériques ont été réglées à la main, sans validation quantitative**. C'est
> précisément ce que le jalon M4 doit corriger.
>
> Rien ici ne doit être implémenté d'un bloc. Le jalon M3 n'implémente que la
> partie 1. Les modificateurs arrivent un par un en M6a et M7, chacun validé par
> le backtest.

---

## 1. Le cœur — ce qui est implémenté en M3

Une **courbe empirique vitesse = f(pente)**, mesurée sur les sorties de l'athlète,
appliquée le long du tracé.

```
GPX → grille à pas fixe (50 m, altitude lissée) → pente par pas
    → pace(pente) interpolée → cumul des temps
```

En M3, un seul modificateur : un facteur d'effort global.

```
v = pace(pente) × effort
```

`effort` représente la forme et l'allure choisie, entre ~0,88 (prudent) et ~0,96
(optimiste). C'est un réglage, pas une mesure.

---

## 2. Les modificateurs — M6a et M7, un par un

Forme complète du modèle précédent, **pour référence** :

```
descente (pente < −3 %) :
  v = pace(pente) · effort · (1 − fatD · frac · min((profondeur/DREF)^DPOW, CAP)) · tod

montée et plat :
  v = pace(pente) · effort · (1 − (BASEFADE + fatU · max(0, (frac−0.5)/0.5))) · (1 − alt_pen) · tod

temps écoulé = temps de mouvement × stop
```

où :

- `frac` — fraction de la course parcourue, de 0 à 1
- `profondeur` — D− cumulé **dans la descente en cours**, remis à zéro dès que ça
  remonte. C'est l'idée centrale du modèle : 1000 m de D− ne se valent pas au km 15
  et au km 120.
- `alt_pen = max(0, (altitude − ALTTHR) / 1000) · ALTK`
- `tod` — effet de l'heure : pénalité de chaleur l'après-midi en partie basse,
  dette de sommeil croissante après un long temps d'effort
- `stop` — facteur d'arrêts (ravitaillements, pauses)

### Valeurs de départ (v2026.1) — à recalibrer, pas à croire

| Constante | Valeur | Rôle |
|---|---|---|
| `DREF` | 650 | profondeur de descente de référence (m) |
| `CAP` | 1.35 | plafond du terme de profondeur |
| `DPOW` | 1.5 | exposant du terme de profondeur |
| `BASEFADE` | 0.06 | perte de base en montée |
| `ALTTHR` | 2400 | seuil d'altitude (m) |
| `ALTK` | 0.08 | coefficient d'altitude |
| chaleur | −5 % entre 11 h et 18 h sous 1800 m | forfaitaire |
| nuit | dette croissante après ~18 h d'effort | forfaitaire |

Réglages par scénario :

| | `effort` | `fatU` | `fatD` | `stop` |
|---|---|---|---|---|
| prudent | 0.88 | 0.33 | 0.50 | 1.15 |
| réaliste | 0.92 | 0.22 | 0.40 | 1.11 |
| optimiste | 0.96 | 0.14 | 0.30 | 1.06 |

---

## 3. Hypothèses, et ce qui les soutient

À traiter comme des hypothèses à tester, pas comme des acquis.

**Fade en montée quasi nul en première moitié.** Justifié par une absence de dérive
cardiaque observée sur la course de référence. → testable : le résidu du backtest
doit-il vraiment être nul avant mi-course ?

**La descente se dégrade avec la profondeur, pas seulement avec l'avancement.**
Observation : les longues descentes tardives coûtent cher, les courtes restent
rapides même tard. → c'est l'hypothèse la plus spécifique du modèle, et donc celle
qui mérite le plus d'être validée sérieusement.

**Le frais et la nuit sont plutôt favorables.** Observation sur la course de
référence : efficience de grimpe nettement meilleure de nuit qu'en milieu de
journée. Le modèle ne bonifie pas la nuit, il évite seulement de la pénaliser.

**La chaleur coûte ~5 % l'après-midi en partie basse.** Forfaitaire et grossier —
remplacé en M7 par la température réelle.

**La faiblesse en descente roulante n'est pas modélisée séparément** en v1 : la
courbe unique l'absorbe en moyenne. C'est le sujet du M8.

---

## 4. Repères physiologiques de référence

Des valeurs mesurées sur la saison précédente servent d'ordres de grandeur et de
tests de vraisemblance (une projection qui les contredit franchement est suspecte) :
l'intensité d'entraînement habituelle et la vitesse à plat qui lui correspond, la FC
en course, la VAM selon l'heure et la chaleur, l'efficience de grimpe (VAM ÷ FC).
**Ce sont des repères datés, pas des constantes du modèle** ; tirés des données de
l'athlète, ils vivent avec elles, hors du dépôt (`MPA_DATA_DIR`, règle 1 de
`CLAUDE.md`).

---

## 5. Où trouver la référence

L'implémentation précédente et ses fichiers de paramètres sont conservés hors du
repo, dans `$MPA_DATA_DIR/reference/`. Ils servent de **spécification
et de test de non-régression** — la nouvelle implémentation doit retrouver
approximativement les mêmes courbes sur les mêmes entrées — et non de code à
reprendre.
