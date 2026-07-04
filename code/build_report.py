#!/usr/bin/env python3
"""Build the final self-contained HTML report (French) from output/viz-data.json
and docs/analysis.json (interpretive copy; placeholders if absent).

Everything is inline: hand-rolled SVG charts (no JS libs), one small vanilla-JS
tooltip layer, light/dark themes from CSS custom properties. Charts follow the
dataviz method: thin marks, hairline grid, sequential ramp for magnitude,
validated bloc palette for identity, legends + table views, hover tooltips.

Usage: .venv/bin/python scripts/build_report.py [--subjects covid-etat-protecteur,securite-identite,ecologie-planification]
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"

# Validated palettes (scripts/validate_palette.js, light + dark surfaces).
BLOC_COLORS_LIGHT = {
    "gauche": "#d03b3b",
    "bloc central": "#eda100",
    "LR": "#2a78d6",
    "droite nationale": "#184f95",
    "gouvernement": "#4a3aa7",
}
BLOC_COLORS_DARK = {
    "gauche": "#e66767",
    "bloc central": "#c98500",
    "LR": "#3987e5",
    "droite nationale": "#d95926",
    "gouvernement": "#9085e9",
}
SEQ_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

FAMILY_BLOC = {
    "LFI": "gauche", "Socialistes": "gauche", "Écologistes": "gauche", "GDR / Communistes": "gauche",
    "Renaissance": "bloc central", "MoDem": "bloc central", "Horizons": "bloc central", "UDI / Agir": "bloc central",
    "LR": "LR", "RN": "droite nationale", "UDR": "droite nationale", "Gouvernement": "gouvernement",
}

E = html.escape


def nice_max(v: float) -> float:
    if v <= 0:
        return 1.0
    for candidate in [1, 2, 2.5, 5]:
        magnitude = 1
        while candidate * magnitude < v:
            magnitude *= 10
        pass
    import math
    exp = math.floor(math.log10(v))
    for m in [1, 2, 2.5, 5, 10]:
        c = m * 10**exp
        if c >= v:
            return c
    return 10 ** (exp + 1)


def year_ticks(months: list[str]) -> list[tuple[int, str]]:
    return [(i, m[:4]) for i, m in enumerate(months) if m.endswith("-01")]


def lifecycle_svg(phrase: dict, months: list[str], width: int = 860, height: int = 190) -> str:
    """Smoothed monthly rate line with area wash and event annotations."""
    pad_l, pad_r, pad_t, pad_b = 44, 14, 26, 22
    w, h = width - pad_l - pad_r, height - pad_t - pad_b
    series = phrase["monthly_rate_smooth"]
    raw = phrase["monthly_rate"]
    counts = phrase["monthly_counts"]
    vmax = nice_max(max(series) if max(series) > 0 else 1)
    n = len(months)

    def x(i: int) -> float:
        return pad_l + i / max(n - 1, 1) * w

    def y(v: float) -> float:
        return pad_t + h - min(v / vmax, 1) * h

    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(series))
    area = f"M {pad_l},{pad_t + h} L " + " L ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(series)) + f" L {x(n - 1):.1f},{pad_t + h} Z"

    grid = ""
    for frac in (0.5, 1.0):
        gy = y(vmax * frac)
        grid += f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{width - pad_r}" y2="{gy:.1f}" class="grid"/>'
        label = f"{vmax * frac:g}"
        grid += f'<text x="{pad_l - 6}" y="{gy + 3:.1f}" class="tick" text-anchor="end">{label}</text>'
    ticks = ""
    for i, yr in year_ticks(months):
        ticks += f'<line x1="{x(i):.1f}" y1="{pad_t + h}" x2="{x(i):.1f}" y2="{pad_t + h + 3}" class="axis"/>'
        if int(yr) % 2 == 1 or n < 60:
            ticks += f'<text x="{x(i):.1f}" y="{pad_t + h + 14}" class="tick" text-anchor="middle">{yr}</text>'

    annotations = ""
    for ev_key, ev_label in (("birth", "naissance"), ("capture_event", "capture"), ("death_event", "« c'est fini »")):
        ev = phrase.get(ev_key)
        if not ev or not ev.get("date"):
            continue
        m = ev["date"][:7]
        if m < months[0]:
            continue
        i = months.index(m) if m in months else None
        if i is None:
            continue
        annotations += (
            f'<line x1="{x(i):.1f}" y1="{pad_t - 4}" x2="{x(i):.1f}" y2="{pad_t + h}" class="event"/>'
            f'<text x="{x(i) + 3:.1f}" y="{pad_t + 6}" class="event-label">{E(ev_label)}</text>'
        )

    # peak direct label
    peak_i = max(range(n), key=lambda i: series[i])
    if series[peak_i] > 0:
        annotations += f'<circle cx="{x(peak_i):.1f}" cy="{y(series[peak_i]):.1f}" r="4" class="dot"/>'

    # invisible hover columns
    hover = ""
    for i in range(n):
        cx = x(i)
        hover += (
            f'<rect x="{cx - w / n / 2:.1f}" y="{pad_t}" width="{w / n:.2f}" height="{h}" fill="transparent" '
            f'data-tip="{E(months[i])} — {raw[i]:g} / M mots ({counts[i]} occ.)" data-x="{cx:.0f}"/>'
        )

    axis = f'<line x1="{pad_l}" y1="{pad_t + h}" x2="{width - pad_r}" y2="{pad_t + h}" class="axis"/>'
    return (
        f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label="Fréquence mensuelle de {E(phrase["canonical"])}">'
        f"{grid}{axis}{ticks}"
        f'<path d="{area}" class="area"/>'
        f'<polyline points="{pts}" class="line"/>'
        f"{annotations}{hover}</svg>"
    )


def heatmap_svg(phrase: dict, quarters: list[str], width: int = 860) -> str:
    """Family × quarter genealogy heatmap; rows in adoption order, first-use ring."""
    fams = phrase["families"]
    if not fams:
        return ""
    matrix = phrase["family_quarter_rate"]
    counts = phrase["family_quarter_count"]
    row_h, gap = 20, 2
    pad_l, pad_t, pad_b = 150, 24, 20
    n_q = len(quarters)
    cell_w = (width - pad_l - 10) / n_q
    height = pad_t + len(fams) * (row_h + gap) + pad_b
    vmax = max((max(row) for row in matrix if row), default=1) or 1

    def ramp(v: float) -> str:
        if v <= 0:
            return "var(--cell-zero)"
        idx = min(int((v / vmax) ** 0.5 * (len(SEQ_RAMP) - 1) + 0.999), len(SEQ_RAMP) - 1)
        return f"var(--seq-{max(idx, 1)})"

    first_q = {a["family"]: a["date"] for a in phrase["adoption"]}
    cells, labels = "", ""
    for r, fam in enumerate(fams):
        ry = pad_t + r * (row_h + gap)
        labels += f'<text x="{pad_l - 8}" y="{ry + row_h / 2 + 3.5}" class="rowlab" text-anchor="end">{E(fam)}</text>'
        for c, q in enumerate(quarters):
            v, cnt = matrix[r][c], counts[r][c]
            cx = pad_l + c * cell_w
            fq = first_q.get(fam, "")
            is_first = fq and (f"{fq[:4]}-T{(int(fq[5:7]) + 2) // 3}" == q)
            ring = ' stroke="var(--ink)" stroke-width="1.5"' if is_first else ""
            fill = ramp(v)
            cells += (
                f'<rect x="{cx + 0.5:.1f}" y="{ry}" width="{max(cell_w - 1, 1.5):.2f}" height="{row_h}" rx="2" fill="{fill}"{ring} '
                f'data-tip="{E(fam)} · {q} — {cnt} occ. ({v:g} / M mots du groupe)"/>'
            )
    ticks = ""
    for c, q in enumerate(quarters):
        if q.endswith("-T1") and int(q[:4]) % 2 == 1:
            ticks += f'<text x="{pad_l + c * cell_w:.1f}" y="{pad_t - 8}" class="tick">{q[:4]}</text>'
    return (
        f'<svg viewBox="0 0 {width} {height:.0f}" class="chart" role="img" aria-label="Diffusion de {E(phrase["canonical"])} par groupe">'
        f"{ticks}{labels}{cells}</svg>"
    )


def bloc_share_svg(phrase: dict, quarters: list[str], bloc_order: list[str], width: int = 860, min_n: int = 5) -> str:
    """Half-year 100% stacked shares by bloc (attributed occurrences only)."""
    halves: dict[str, list[int]] = {}
    for q in quarters:
        hy = q[:4] + ("-S1" if q[5:] in ("T1", "T2") else "-S2")
        vals = phrase["bloc_shares_by_quarter"].get(q, [0] * len(bloc_order))
        halves.setdefault(hy, [0] * len(bloc_order))
        halves[hy] = [a + b for a, b in zip(halves[hy], vals)]
    keys = sorted(halves)
    pad_l, pad_t, pad_b = 44, 20, 34
    h = 150
    height = pad_t + h + pad_b
    slot = (width - pad_l - 10) / len(keys)
    bar_w = min(slot - 4, 24)
    bars, ticks = "", ""
    for i, hy in enumerate(keys):
        vals = halves[hy]
        total = sum(vals)
        cx = pad_l + i * slot + (slot - bar_w) / 2
        if total < min_n:
            bars += f'<rect x="{cx:.1f}" y="{pad_t + h - 3}" width="{bar_w:.1f}" height="3" rx="1.5" fill="var(--cell-zero)" data-tip="{hy} — n&lt;{min_n}, non affiché"/>'
        else:
            y_cursor = pad_t + h
            for b, v in enumerate(vals):
                if v == 0:
                    continue
                seg_h = v / total * h
                y_cursor -= seg_h
                bars += (
                    f'<rect x="{cx:.1f}" y="{y_cursor + 1:.1f}" width="{bar_w:.1f}" height="{max(seg_h - 2, 1):.1f}" rx="2" '
                    f'fill="var(--bloc-{b})" data-tip="{E(bloc_order[b])} · {hy} — {v}/{total} occ. ({v / total * 100:.0f} %)"/>'
                )
        if hy.endswith("-S1"):
            ticks += f'<text x="{cx + bar_w / 2:.1f}" y="{pad_t + h + 14}" class="tick" text-anchor="middle">{hy[:4]}</text>'
    legend = "".join(
        f'<span class="key"><span class="swatch" style="background:var(--bloc-{i})"></span>{E(b)}</span>'
        for i, b in enumerate(bloc_order)
    )
    svg = (
        f'<svg viewBox="0 0 {width} {height:.0f}" class="chart" role="img" aria-label="Part des blocs dans l\'usage de {E(phrase["canonical"])}">'
        f'{bars}{ticks}</svg>'
    )
    return f'<div class="legend">{legend}</div>{svg}'


def table_view(phrase: dict, months: list[str]) -> str:
    rows = ""
    for i, m in enumerate(months):
        if phrase["monthly_counts"][i]:
            rows += f'<tr><td>{m}</td><td>{phrase["monthly_counts"][i]}</td><td>{phrase["monthly_rate"][i]:g}</td></tr>'
    return (
        '<details class="table-view"><summary>Voir les données (tableau)</summary>'
        '<table><thead><tr><th>Mois</th><th>Occurrences</th><th>Taux / M mots</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></details>"
    )


def quote_block(q: dict) -> str:
    bloc = FAMILY_BLOC.get(q.get("family", ""), None)
    dot = f'<span class="swatch" style="background:var(--bloc-{list(BLOC_COLORS_LIGHT).index(bloc)})"></span>' if bloc else ""
    fam = f" ({E(q['family'])})" if q.get("family") and q["family"] != "(non attribué)" else ""
    conf = "" if q.get("confirmed", True) else ' <span class="unconf" title="attribution non confirmée">†</span>'
    return (
        f'<blockquote class="quote"><p>« {E(q["quote"])} »</p>'
        f'<footer>{dot}{E(q.get("speaker") or "Orateur non identifié")}{fam}{conf} — {E(q["date"])}, {E(q.get("category", ""))}</footer></blockquote>'
    )


def build(subject_keys: list[str]) -> str:
    data = json.loads((OUT / "viz-data.json").read_text())
    analysis_path = ROOT / "docs" / "analysis.json"
    analysis = json.loads(analysis_path.read_text()) if analysis_path.exists() else {}
    months = data["meta"]["months"]
    quarters = data["meta"]["quarters"]
    bloc_order = data["meta"]["bloc_order"]

    subjects = [s for s in data["subjects"] if s["key"] in subject_keys]
    subjects.sort(key=lambda s: subject_keys.index(s["key"]))

    sections = ""
    for s in subjects:
        a = analysis.get(s["key"], {})
        phrases = sorted(s["phrases"], key=lambda p: -p["total"])
        cards = ""
        for p in phrases:
            pa = (a.get("phrases") or {}).get(p["key"], {})
            interp = pa.get("interpretation") or ""
            birth = p.get("birth") or {}
            birth_line = f'<p class="birth-line">Naissance publique : <strong>{E(birth.get("date", "?"))}</strong> — {E(birth.get("author", ""))}. {E(birth.get("event", ""))}</p>' if birth else ""
            show_capture = p.get("capture_event") or (pa.get("show_bloc_shares") if pa else False)
            bloc_chart = bloc_share_svg(p, quarters, bloc_order) if show_capture else ""
            heat = heatmap_svg(p, quarters)
            quotes = "".join(quote_block(q) for q in pa.get("quotes", [])[:2])
            cards += f"""
<article class="phrase" id="{p['key']}">
  <h4>« {E(p['canonical'])} » <span class="meta">{p['total']} occurrences · {E(p['first_date'] or '')} → {E(p['last_date'] or '')}</span></h4>
  {birth_line}
  {lifecycle_svg(p, months)}
  {table_view(p, months)}
  {f'<h5>Diffusion par groupe <span class="hint">(ordre des lignes = ordre d&rsquo;adoption après la naissance publique · <span class="ramp"></span> taux croissant, clair &rarr; foncé)</span></h5>{heat}' if heat else ''}
  {f'<h5>À qui appartient la formule ? <span class="hint">(parts semestrielles de la parole attribuée)</span></h5>{bloc_chart}' if bloc_chart else ''}
  {f'<div class="interp">{interp}</div>' if interp else ''}
  {quotes}
</article>"""
        stats = "".join(
            f'<div class="tile"><div class="label">{E(t["label"])}</div><div class="value">{E(t["value"])}</div><div class="sub">{E(t.get("sub", ""))}</div></div>'
            for t in a.get("tiles", [])
        )
        sections += f"""
<section class="subject" id="{s['key']}">
  <h2>{E(s['title_fr'])}</h2>
  <p class="storyline">{E(a.get('storyline') or s['storyline'])}</p>
  {f'<div class="tiles">{stats}</div>' if stats else ''}
  {f'<div class="synthese">{a["synthese"]}</div>' if a.get('synthese') else ''}
  {cards}
</section>"""

    meta_section = ""
    if analysis.get("_meta"):
        meta_section = f'<section class="subject" id="meta"><h2>Ce que les trois sujets disent ensemble</h2>{analysis["_meta"]}</section>'

    total_words = data["meta"]["total_words"]
    return f"""<title>Généalogie des éléments de langage — Assemblée nationale 2017-2026</title>
<style>
:root {{
  --bg: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --accent: #2a78d6; --cell-zero: #f0efec;
  --bloc-0: #d03b3b; --bloc-1: #eda100; --bloc-2: #2a78d6; --bloc-3: #184f95; --bloc-4: #4a3aa7;
  --seq-1: #9ec5f4; --seq-2: #6da7ec; --seq-3: #3987e5; --seq-4: #256abf; --seq-5: #184f95; --seq-6: #0d366b;
}}
@media (prefers-color-scheme: dark) {{ :root {{
  --bg: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --accent: #3987e5; --cell-zero: #232322;
  --bloc-0: #e66767; --bloc-1: #c98500; --bloc-2: #3987e5; --bloc-3: #d95926; --bloc-4: #9085e9;
  --seq-1: #1c4a80; --seq-2: #1c5cab; --seq-3: #2a78d6; --seq-4: #5598e7; --seq-5: #86b6ef; --seq-6: #cde2fb;
}} }}
:root[data-theme="light"] {{
  --bg: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --accent: #2a78d6; --cell-zero: #f0efec;
  --bloc-0: #d03b3b; --bloc-1: #eda100; --bloc-2: #2a78d6; --bloc-3: #184f95; --bloc-4: #4a3aa7;
  --seq-1: #9ec5f4; --seq-2: #6da7ec; --seq-3: #3987e5; --seq-4: #256abf; --seq-5: #184f95; --seq-6: #0d366b;
}}
:root[data-theme="dark"] {{
  --bg: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --accent: #3987e5; --cell-zero: #232322;
  --bloc-0: #e66767; --bloc-1: #c98500; --bloc-2: #3987e5; --bloc-3: #d95926; --bloc-4: #9085e9;
  --seq-1: #1c4a80; --seq-2: #1c5cab; --seq-3: #2a78d6; --seq-4: #5598e7; --seq-5: #86b6ef; --seq-6: #cde2fb;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }}
.wrap {{ max-width: 940px; margin: 0 auto; padding: 2rem 1rem 4rem; }}
header.hero .eyebrow {{ font-size: .72rem; text-transform: uppercase; letter-spacing: .09em; color: var(--muted); margin: 0 0 .5rem; }}
header.hero .eyebrow a {{ color: inherit; text-decoration: none; border-bottom: 1px solid var(--grid); }}
header.hero h1 {{ font-size: clamp(1.6rem, 4.5vw, 2.5rem); line-height: 1.12; margin: 0 0 .5rem; letter-spacing: -0.015em; text-wrap: balance; }}
header.hero .sub {{ color: var(--ink-2); max-width: 62ch; }}
section.subject > h2 {{ text-wrap: balance; }}
a {{ color: var(--accent); }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin: 1.2rem 0; }}
.tile {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: .8rem .9rem; }}
.tile .label {{ font-size: .8rem; color: var(--ink-2); }}
.tile .value {{ font-size: 1.7rem; font-weight: 600; margin-top: .1rem; }}
.tile .sub {{ font-size: .78rem; color: var(--muted); }}
section.subject {{ margin-top: 3rem; }}
section.subject > h2 {{ font-size: 1.45rem; border-bottom: 1px solid var(--grid); padding-bottom: .4rem; }}
.storyline {{ color: var(--ink-2); max-width: 72ch; }}
article.phrase {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1rem 1.1rem; margin: 1.1rem 0; overflow: hidden; }}
article.phrase h4 {{ margin: 0 0 .3rem; font-size: 1.08rem; }}
article.phrase h4 .meta {{ font-weight: 400; font-size: .8rem; color: var(--muted); margin-left: .4rem; }}
article.phrase h5 {{ margin: 1.1rem 0 .3rem; font-size: .9rem; color: var(--ink-2); }}
article.phrase h5 .hint {{ font-weight: 400; font-size: .75rem; color: var(--muted); }}
.ramp {{ display: inline-block; width: 44px; height: 8px; border-radius: 3px; vertical-align: baseline;
  background: linear-gradient(90deg, var(--seq-1), var(--seq-3), var(--seq-6)); }}
.birth-line {{ font-size: .88rem; color: var(--ink-2); margin: .2rem 0 .6rem; }}
svg.chart {{ width: 100%; height: auto; display: block; }}
svg .grid {{ stroke: var(--grid); stroke-width: 1; }}
svg .axis {{ stroke: var(--axis); stroke-width: 1; }}
svg .tick {{ fill: var(--muted); font-size: 10px; }}
svg .rowlab {{ fill: var(--ink-2); font-size: 10.5px; }}
svg .line {{ fill: none; stroke: var(--accent); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }}
svg .area {{ fill: var(--accent); opacity: .1; }}
svg .dot {{ fill: var(--accent); stroke: var(--surface); stroke-width: 2; }}
svg .event {{ stroke: var(--ink-2); stroke-width: 1; stroke-dasharray: none; opacity: .6; }}
svg .event-label {{ fill: var(--ink-2); font-size: 9.5px; }}
.legend {{ display: flex; flex-wrap: wrap; gap: .7rem; font-size: .8rem; color: var(--ink-2); margin: .3rem 0; }}
.key {{ display: inline-flex; align-items: center; gap: .35rem; }}
.swatch {{ width: 10px; height: 10px; border-radius: 3px; display: inline-block; }}
.interp {{ max-width: 72ch; }}
.interp p {{ margin: .6rem 0; }}
blockquote.quote {{ border-left: 3px solid var(--accent); margin: .8rem 0; padding: .4rem .9rem; background: color-mix(in srgb, var(--accent) 4%, transparent); border-radius: 0 8px 8px 0; }}
blockquote.quote p {{ margin: .2rem 0; font-size: .95rem; }}
blockquote.quote footer {{ font-size: .8rem; color: var(--ink-2); display: flex; align-items: center; gap: .35rem; }}
.unconf {{ color: var(--muted); }}
details.table-view {{ margin: .4rem 0 0; font-size: .85rem; }}
details.table-view summary {{ cursor: pointer; color: var(--muted); font-size: .8rem; }}
details.table-view table {{ border-collapse: collapse; margin-top: .4rem; }}
details.table-view td, details.table-view th {{ border-bottom: 1px solid var(--grid); padding: .15rem .6rem .15rem 0; text-align: left; font-variant-numeric: tabular-nums; }}
details.methode {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: .7rem 1rem; margin: 1.2rem 0; font-size: .9rem; color: var(--ink-2); }}
details.methode summary {{ cursor: pointer; color: var(--ink); font-weight: 600; }}
#tooltip {{ position: fixed; pointer-events: none; background: var(--ink); color: var(--bg); font-size: .78rem; padding: .3rem .55rem; border-radius: 6px; opacity: 0; transition: opacity .08s; z-index: 10; max-width: 320px; }}
footer.page {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--grid); color: var(--muted); font-size: .85rem; }}
@media (max-width: 640px) {{ .tiles {{ grid-template-columns: repeat(2, 1fr); }} }}
@media print {{
  body {{ background: #fff; }}
  .wrap {{ max-width: none; padding: 0; }}
  section.subject {{ break-before: page; }}
  article.phrase {{ break-inside: avoid; }}
  .tiles, .tile, blockquote.quote, svg.chart {{ break-inside: avoid; }}
  details.table-view {{ display: none; }}
  #tooltip {{ display: none; }}
  a {{ text-decoration: none; }}
}}
</style>
<div class="wrap">
<header class="hero">
  <p class="eyebrow"><a href="https://hackathon2026.assemblee-nationale.fr/defis/32c39148-b460-4e6a-9616-ec8a59ed4c53">Hackathon Assemblée nationale 2026 · défi officiel</a></p>
  <h1>Généalogie des éléments de langage</h1>
  <p class="sub">Naissance, diffusion et mort des formules politiques dans les débats de l'Assemblée nationale, de juin 2017 à juillet 2026 — séances publiques, commissions et questions au gouvernement, lues intégralement via l'API de transcription de l'Assemblée.</p>
  <div class="tiles">
    <div class="tile"><div class="label">Séances analysées</div><div class="value">8 957</div><div class="sub">2 670 séances publiques · 6 200 commissions</div></div>
    <div class="tile"><div class="label">Mots prononcés</div><div class="value">{total_words / 1e6:.0f} M</div><div class="sub">juin 2017 → juillet 2026</div></div>
    <div class="tile"><div class="label">Formules suivies</div><div class="value">{sum(len(s['phrases']) for s in subjects)}</div><div class="sub">3 sujets, variantes incluses</div></div>
    <div class="tile"><div class="label">Occurrences relevées</div><div class="value">{sum(p['total'] for s in subjects for p in s['phrases']):,}</div><div class="sub">après audit des faux positifs</div></div>
  </div>
</header>
<details class="methode"><summary>Méthode (résumé)</summary>
<p>Corpus : l'intégralité des transcriptions de l'API hackathon (8 957 séances, tier <i>stable</i>), plus le miroir brut pour l'attribution des orateurs non confirmés (marqués †). Chaque formule est recherchée littéralement (variantes orthographiques et flexions, texte normalisé) avec des exclusions pour les contextes hors-sujet, auditées manuellement sur échantillons par phrase. Les groupes politiques sont résolus à la date de la séance via les données ouvertes officielles (mandats AMO, data.assemblee-nationale.fr) — un orateur qui change de groupe est compté dans le groupe du moment. Les taux sont exprimés en occurrences par million de mots prononcés (corpus entier ou parole du groupe), ce qui neutralise l'inflation du volume transcrit (le corpus 2025 est ~3× plus volumineux que 2018). La couverture d'attribution baisse en 2025-2026 (extension du corpus aux auditions) : les parts par groupe excluent la parole non attribuée. Événements de naissance vérifiés sur sources publiques (voir <code>docs/recherche-sujets.md</code>).</p>
</details>
{sections}
{meta_section}
<footer class="page">
<p>Données : API de transcription Assemblée nationale (hackathon 2026) · transcriptions Polyfact · mandats AMO data.assemblee-nationale.fr. Code : <code>research/genealogie-elements-langage/</code>. † = attribution d'orateur non confirmée (miroir brut).</p>
</footer>
</div>
<div id="tooltip"></div>
<script>
const tip = document.getElementById('tooltip');
document.addEventListener('mousemove', (e) => {{
  const t = e.target.closest('[data-tip]');
  if (t) {{
    tip.textContent = t.getAttribute('data-tip');
    tip.style.opacity = 1;
    const pad = 12;
    let tx = e.clientX + pad, ty = e.clientY + pad;
    const r = tip.getBoundingClientRect();
    if (tx + r.width > innerWidth - 8) tx = e.clientX - r.width - pad;
    if (ty + r.height > innerHeight - 8) ty = e.clientY - r.height - pad;
    tip.style.left = tx + 'px'; tip.style.top = ty + 'px';
  }} else tip.style.opacity = 0;
}});
</script>
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--subjects",
        default="covid-etat-protecteur,securite-identite,ecologie-planification",
    )
    parser.add_argument("--out", default=str(OUT / "report.html"))
    args = parser.parse_args()
    html_text = build(args.subjects.split(","))
    Path(args.out).write_text(html_text)
    print(f"[report] {args.out} ({len(html_text) / 1e6:.2f} MB)")
