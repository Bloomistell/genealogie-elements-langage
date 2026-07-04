# Généalogie des éléments de langage

**Défi officiel du [Hackathon 2026 de l'Assemblée nationale](https://hackathon2026.assemblee-nationale.fr/defis/32c39148-b460-4e6a-9616-ec8a59ed4c53)** — qui invente les mots de la politique, qui les reprend, et que deviennent-ils ?

À partir de l'API de transcription que Polyfact a construite sur les données publiques de l'Assemblée nationale (vidéos des débats) et mise à disposition du hackathon, nous avons parcouru **l'intégralité des débats transcrits** — 8 957 séances (séances publiques, commissions, questions au gouvernement), 114 millions de mots, juin 2017 → juillet 2026 — pour retracer la **naissance**, la **diffusion** (au sein d'un groupe, puis entre groupes) et la **mort** de 25 formules politiques.

**➡ L'étude complète, interactive et bilingue : [polyfact.com/recherche](https://polyfact.com/recherche)**

## Trois résultats en une phrase chacun

1. **Les mots du Président entrent à l'Assemblée par la bouche de ses adversaires** — « quoi qu'il en coûte » est importé sept jours après l'allocution par Woerth (LR), Rabault (PS) et Roussel (PCF), avant la majorité.
2. **79 % des « quoi qu'il en coûte » sont posthumes** — prononcés après le « c'est fini » de Bruno Le Maire, avec un pic absolu 1 128 jours après : une formule ne meurt pas, elle se fossilise en catégorie budgétaire.
3. **Les généalogies s'inversent** — « les jours heureux » circulait chez Mathilde Panot 118 jours avant Macron ; « premiers de corvée » (Mélenchon) entre à l'Assemblée par un député de la majorité, avant d'être attribué… à Macron. Le stade final d'un élément de langage, c'est l'anonymat.

## Contenu du dépôt

| Chemin | Quoi |
|---|---|
| [`hackathon-an-2026/DEFI.md`](hackathon-an-2026/DEFI.md) | La fiche du défi (template officiel rempli) |
| [`slides/index.html`](slides/index.html) | La présentation (3 min, autonome — flèches/clic pour naviguer) |
| [`slides.pdf`](hackathon-an-2026/docs/slides.pdf) · [`rapport.pdf`](hackathon-an-2026/docs/rapport.pdf) | Les diapositives et le rapport complet en PDF |
| [`code/`](code/) | Le pipeline d'exploitation de l'API (moisson → extraction → agrégation → rapport) |
| [`data/`](data/) | Les agrégats publiables : séries par formule/groupe (`viz-data.json`), comptages (`extract-summary.json`), audit des faux positifs (`audits.json`) |
| [`hackathon-an-2026/images/`](hackathon-an-2026/images/) | Visuels du défi |

## Méthode (résumé)

1. **Moisson intégrale** (`code/harvest.py`) — l'index des séances puis chaque compte rendu via notre API de transcription (la recherche de l'API est plafonnée à 500 résultats : pour des séries temporelles honnêtes, il faut tout télécharger), plus le miroir brut pour l'attribution des orateurs non confirmés.
2. **Extraction littérale auditée** (`code/extract.py`, lexique dans `code/config/subjects.json`) — variantes orthographiques et flexions sur texte normalisé, exclusions de contextes hors-sujet ; faux positifs audités sur échantillons, formule par formule (`data/audits.json`).
3. **Groupes à la date de séance** (`code/an_groups.py`) — résolution (uid AN, date) → groupe via les mandats officiels AMO (data.assemblee-nationale.fr) ; un élu qui change de groupe est compté où il siège.
4. **Des taux, pas des comptes** (`code/aggregate.py`) — occurrences par million de mots prononcés ; le volume transcrit triple entre 2018 et 2025.

Reproduction complète : voir [`code/README.md`](code/README.md). Ce dépôt ne contient pas le code de l'API elle-même (service de l'Assemblée/Polyfact), uniquement le code qui l'exploite.

## Équipe

**Polyfact** — [polyfact.com](https://polyfact.com) · Jules Potel
