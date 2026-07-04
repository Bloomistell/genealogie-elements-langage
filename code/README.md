# Pipeline d'exploitation de l'API

Le code qui a produit l'étude, dans l'ordre d'exécution. Python ≥ 3.11,
dépendances : `pip install requests polars` (+ `qrcode` pour les diapositives).

```bash
cp .env.example .env      # renseigner PUBLIC_API_KEY (clé pk_event_… du hackathon)

python3 harvest.py all         # index + 8 957 comptes rendus (tier stable), ~30 min
python3 harvest_videos.py      # miroir brut (attribution de repli), ~20 min
python3 an_groups.py           # (uid AN, date) → groupe, depuis les dumps AMO*
python3 extract.py             # recherche littérale des 25 formules (config/subjects.json)
python3 aggregate.py           # séries mensuelles, taux/M mots, ordre d'adoption
python3 export_viz.py          # → viz-data.json (celui fourni dans ../data)
python3 build_report.py        # → rapport HTML autonome
python3 ../slides/build_slides.py  # → diapositives
```

\* `an_groups.py` attend les dumps ouverts **AMO** (acteurs/mandats/organes,
[data.assemblee-nationale.fr](https://data.assemblee-nationale.fr)) des
législatures XV-XVII, décompressés dans `../vote-analysis/data/AMOANR5L{15,16,17}/`
— adaptez `AMO_DIRS` à votre arborescence.

Notes utiles pour quiconque exploite l'API :

- `GET /v1/paragraphs` renvoie une **fenêtre classée plafonnée** (~500 résultats) —
  pour compter, téléchargez tout via `GET /v1/sessions` et cherchez localement.
- Le tier `stable` ne confirme un orateur qu'au-delà d'un seuil ; le **miroir brut**
  (`GET /v1/videos/{id}`) porte l'identification non confirmée (repli marqué
  `confirmed=false` dans nos tables).
- Le `party_name` de l'API peut être rattaché à la mauvaise législature — d'où la
  résolution **groupe-à-la-date** via les mandats AMO officiels.
- Le volume transcrit **triple** entre 2018 et 2025 : toujours normaliser en
  occurrences **par million de mots**.

`config/subjects.json` contient le lexique final (3 sujets, 25 formules, variantes,
exclusions, naissances vérifiées) ; `config/subjects-annexe.json` les trois sujets
candidats non retenus ; `../data/audits.json` le verdict d'audit de chaque formule.
