#!/usr/bin/env python3
"""Build the 3-minute hackathon presentation (slides/index.html, self-contained).

Reuses the chart generators from code/build_report.py on data/viz-data.json.
Navigation: arrows / space / click. Print = one landscape page per slide
(export to PDF via the browser or scripts in the repo README).

Usage: python3 slides/build_slides.py  (needs `qrcode` for the closing slide)
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("report", REPO / "code" / "build_report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)

data = json.loads((REPO / "data" / "viz-data.json").read_text())
months = data["meta"]["months"]
quarters = data["meta"]["quarters"]
covid = next(s for s in data["subjects"] if s["key"] == "covid-etat-protecteur")
phrases = {p["key"]: p for p in covid["phrases"]}
qqec = phrases["quoi-qu-il-en-coute"]

lifecycle = report.lifecycle_svg(qqec, months, width=1040, height=300)
heatmap = report.heatmap_svg(qqec, quarters, width=1040)

try:
    import qrcode
    import qrcode.image.svg

    qr = qrcode.make("https://polyfact.com/recherche", image_factory=qrcode.image.svg.SvgPathImage, box_size=14)
    buf = io.BytesIO()
    qr.save(buf)
    qr_svg = buf.getvalue().decode().replace('<?xml version="1.0" encoding="UTF-8"?>', "")
except ImportError:
    print("[slides] qrcode not installed — QR omitted", file=sys.stderr)
    qr_svg = ""

html = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Généalogie des éléments de langage — Hackathon AN 2026</title>
<style>
:root {{
  --bg: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --accent: #2a78d6; --cell-zero: #f0efec;
  --seq-1: #9ec5f4; --seq-2: #6da7ec; --seq-3: #3987e5; --seq-4: #256abf; --seq-5: #184f95; --seq-6: #0d366b;
  --bloc-0: #d03b3b; --bloc-1: #eda100; --bloc-2: #2a78d6; --bloc-3: #184f95; --bloc-4: #4a3aa7;
}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; height: 100%; background: #1a1a19; }}
body {{ font: 20px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--ink); }}
.slide {{
  width: 100vw; height: 100vh; padding: 4.5vh 6vw; background: var(--bg);
  display: none; flex-direction: column; justify-content: center; position: relative; overflow: hidden;
}}
.slide.active {{ display: flex; }}
.eyebrow {{ font-size: .78rem; text-transform: uppercase; letter-spacing: .1em; color: var(--muted); margin-bottom: 1rem; }}
h1 {{ font-size: clamp(2.4rem, 5.4vw, 4.4rem); line-height: 1.06; margin: 0; letter-spacing: -0.015em; text-wrap: balance; font-weight: 700; }}
h2 {{ font-size: clamp(1.6rem, 3.2vw, 2.5rem); line-height: 1.12; margin: 0 0 1.2rem; letter-spacing: -0.01em; text-wrap: balance; font-weight: 700; }}
.sub {{ color: var(--ink-2); font-size: clamp(1rem, 1.7vw, 1.35rem); max-width: 62ch; }}
.big {{ font-size: clamp(3rem, 8vw, 6.5rem); font-weight: 300; line-height: 1; }}
.kicker {{ color: var(--accent); font-weight: 600; }}
svg.chart {{ width: 100%; height: auto; display: block; }}
svg .grid {{ stroke: var(--grid); }} svg .axis {{ stroke: var(--axis); }}
svg .tick {{ fill: var(--muted); font-size: 11px; }} svg .rowlab {{ fill: var(--ink-2); font-size: 11px; }}
svg .line {{ fill: none; stroke: var(--accent); stroke-width: 2.5; stroke-linejoin: round; stroke-linecap: round; }}
svg .area {{ fill: var(--accent); opacity: .1; }}
svg .dot {{ fill: var(--accent); stroke: var(--surface); stroke-width: 2; }}
svg .event {{ stroke: var(--ink-2); opacity: .65; }} svg .event-label {{ fill: var(--ink-2); font-size: 11px; }}
.cols {{ display: grid; grid-template-columns: 1fr 1fr; gap: 3vw; align-items: start; }}
.quote {{ border-left: 4px solid var(--accent); background: #2a78d60d; padding: .7rem 1.1rem; border-radius: 0 10px 10px 0; margin: 1rem 0 0; font-size: clamp(.95rem, 1.55vw, 1.2rem); }}
.quote footer {{ font-size: .8em; color: var(--ink-2); margin-top: .35rem; }}
.tiles {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-top: 1.4rem; }}
.tile {{ background: var(--surface); border: 1px solid var(--grid); border-radius: 14px; padding: 1rem 1.2rem; }}
.tile .v {{ font-size: clamp(1.8rem, 3.4vw, 2.8rem); font-weight: 300; }}
.tile .l {{ font-size: .82rem; color: var(--ink-2); margin-top: .2rem; }}
ul.method {{ margin: .8rem 0 0; padding: 0; list-style: none; font-size: clamp(1rem, 1.7vw, 1.3rem); }}
ul.method li {{ margin: .65rem 0; padding-left: 1.6rem; position: relative; }}
ul.method li::before {{ content: ""; position: absolute; left: 0; top: .48em; width: .65em; height: .65em; border-radius: 3px; background: var(--accent); }}
.foot {{ position: absolute; bottom: 3vh; left: 6vw; right: 6vw; display: flex; justify-content: space-between; font-size: .78rem; color: var(--muted); }}
.counter {{ position: fixed; bottom: 3vh; right: 2vw; font-size: .75rem; color: #898781; z-index: 5; }}
@media print {{
  html, body {{ background: var(--bg); }}
  .slide {{ display: flex !important; width: 297mm; height: 209mm; page-break-after: always; padding: 12mm 18mm; }}
  .counter {{ display: none; }}
}}
</style>
</head>
<body>

<section class="slide active">
  <div class="eyebrow">Hackathon Assemblée nationale 2026 · défi « Généalogie des éléments de langage »</div>
  <h1>Qui invente les mots de la politique —<br/>et que deviennent-ils ?</h1>
  <p class="sub" style="margin-top:1.4rem">Naissance, diffusion et mort des formules politiques dans <strong>l'intégralité</strong> des débats de l'Assemblée nationale, via l'API de transcription du hackathon.</p>
  <div class="tiles" style="max-width:52rem">
    <div class="tile"><div class="v">8 957</div><div class="l">séances — publiques, commissions, QAG</div></div>
    <div class="tile"><div class="v">114 M</div><div class="l">mots, horodatés et attribués</div></div>
    <div class="tile"><div class="v">2017 → 2026</div><div class="l">trois législatures</div></div>
  </div>
  <div class="foot"><span>Polyfact Research</span><span>polyfact.com/recherche</span></div>
</section>

<section class="slide">
  <div class="eyebrow">Le cas d'école — « quoi qu'il en coûte », 474 occurrences</div>
  <h2>Les mots du Président entrent à l'Assemblée<br/><span class="kicker">par la bouche de ses adversaires</span></h2>
  {lifecycle}
  <div class="cols" style="margin-top:1rem">
    <p class="sub" style="font-size:clamp(.95rem,1.5vw,1.15rem)">Allocution du <strong>12 mars 2020</strong>. Sept jours plus tard, quatre groupes le reprennent le même jour — <strong>Woerth (LR), Rabault (PS), Roussel (PCF)… avant la majorité</strong>. L'opposition le cite comme une reconnaissance de dette.</p>
    <blockquote class="quote">« …pour reprendre les mots du Président de la République, quoi qu'il en coûte. »
      <footer>Éric Woerth (LR) — 19 mars 2020, commission des finances</footer>
    </blockquote>
  </div>
  <div class="foot"><span>naissance → diffusion</span><span>Polyfact Research</span></div>
</section>

<section class="slide">
  <div class="eyebrow">La mort qui n'en est pas une</div>
  <div class="cols" style="align-items:center;margin-bottom:.6rem">
    <div class="big kicker">79 % posthume</div>
    <p class="sub" style="font-size:clamp(.95rem,1.5vw,1.15rem)">des usages viennent <strong>après</strong> l'acte de décès officiel (« le quoi qu'il en coûte, c'est fini », Bruno Le Maire, 30 août 2021). Pic absolu : <strong>octobre 2024</strong> — <strong>1 128 jours après</strong>. 170 orateurs, quatorze familles.</p>
  </div>
  <p class="sub" style="font-size:.95rem;margin:.2rem 0 .3rem">Diffusion par groupe — ordre des lignes = ordre d'adoption, ■ = première utilisation, foncé = usage intense</p>
  {heatmap}
  <p class="sub" style="margin-top:.8rem"><strong>Une formule ne meurt pas : elle se fossilise</strong> — en catégorie budgétaire que chaque camp retourne contre le budget de l'autre.</p>
  <div class="foot"><span>mort → fossilisation</span><span>Polyfact Research</span></div>
</section>

<section class="slide">
  <div class="eyebrow">Les généalogies inversées</div>
  <h2>La chronique médiatique se trompe d'auteur</h2>
  <div class="cols">
    <div>
      <p class="sub"><span class="kicker" style="font-size:1.3em">« les jours heureux »</span></p>
      <p class="sub">Attribué à Macron (13 avril 2020). Or Mathilde Panot (LFI) proposait un « pacte des jours heureux »… <strong>118 jours avant</strong> l'allocution. Le Président a repris une formule que la gauche avait réarmée avant lui.</p>
    </div>
    <div>
      <p class="sub"><span class="kicker" style="font-size:1.3em">« premiers de corvée »</span></p>
      <p class="sub">Forgée par Mélenchon en 24 h (2017), elle dort <strong>919 jours</strong>… et entre à l'Assemblée par un député <strong>de la majorité</strong> (avril 2020). En 2024, un socialiste l'attribue à Macron. En 2026, le RN emploie « premiers de cordée » au premier degré.</p>
    </div>
  </div>
  <p class="sub" style="margin-top:1.6rem"><strong>Le stade final d'un élément de langage, c'est l'anonymat :</strong> il a gagné quand plus personne ne se souvient de qui l'a dit.</p>
  <div class="foot"><span>l'oubli comme victoire</span><span>Polyfact Research</span></div>
</section>

<section class="slide">
  <div class="eyebrow">Méthode — en 30 secondes</div>
  <h2>Du littéral, de l'exhaustif, du vérifiable</h2>
  <ul class="method">
    <li><strong>Corpus intégral</strong> via l'API de transcription du hackathon — pas d'échantillon, pas de recherche plafonnée.</li>
    <li><strong>Recherche littérale</strong> de chaque formule (variantes + exclusions), <strong>faux positifs audités</strong> sur échantillons, formule par formule.</li>
    <li><strong>Groupes à la date de séance</strong> via les mandats officiels (données ouvertes AMO) — un élu qui change de groupe est compté où il siège.</li>
    <li><strong>Des taux, pas des comptes</strong> : occurrences par million de mots prononcés — le volume transcrit triple entre 2018 et 2025.</li>
    <li>Chaque affirmation <strong>contre-vérifiée dans les données</strong> — dates, attributions, comptages.</li>
  </ul>
  <div class="foot"><span>code public : github.com/Bloomistell/genealogie-elements-langage</span><span>Polyfact Research</span></div>
</section>

<section class="slide">
  <div class="cols" style="align-items:center">
    <div>
      <div class="eyebrow">Et ce n'est qu'un tiers de l'étude</div>
      <h2>L'étude complète, interactive :<br/><span class="kicker">polyfact.com/recherche</span></h2>
      <p class="sub" style="margin-top:1rem">Avec deux autres sujets et leurs 17 formules :</p>
      <ul class="method">
        <li><strong>Le lexique sécuritaire et identitaire</strong> — comment un mot monte des marges vers le ministre (« ensauvagement » : 1 010 jours d'incubation).</li>
        <li><strong>La bataille du vocabulaire écologique</strong> — la capture de la « planification écologique », 100 % LFI en 2017, présidentielle en 2022.</li>
      </ul>
      <p class="sub" style="margin-top:1rem">Rapport PDF, visualisations, méthode et code : tout est ouvert.</p>
    </div>
    <div style="max-width:340px;justify-self:center">{qr_svg}</div>
  </div>
  <div class="foot"><span>Polyfact Research — merci !</span><span>Polyfact Research</span></div>
</section>

<div class="counter" id="counter">1/6</div>
<script>
const slides = [...document.querySelectorAll('.slide')];
let i = 0;
function show(n) {{
  i = Math.max(0, Math.min(slides.length - 1, n));
  slides.forEach((s, j) => s.classList.toggle('active', j === i));
  document.getElementById('counter').textContent = (i + 1) + '/' + slides.length;
}}
addEventListener('keydown', (e) => {{
  if (['ArrowRight', ' ', 'PageDown'].includes(e.key)) show(i + 1);
  if (['ArrowLeft', 'PageUp'].includes(e.key)) show(i - 1);
}});
addEventListener('click', (e) => {{ if (!e.target.closest('a')) show(i + 1); }});
</script>
</body>
</html>
"""

out = REPO / "slides" / "index.html"
out.write_text(html)
print(f"[slides] {out} ({out.stat().st_size / 1024:.0f} KB)")
