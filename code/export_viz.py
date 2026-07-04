#!/usr/bin/env python3
"""Export everything the report/visualizations need into output/viz-data.json.

Per subject and phrase: monthly corpus-wide rate series (raw + 3-month centered
rolling mean), family × quarter usage matrices (rate per million words of that
family's speech), quarterly bloc shares (attributed occurrences only), adoption
order with each family's first quote, lifecycle stats, and corpus metadata.

Usage: .venv/bin/python scripts/export_viz.py
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"

BLOC_OF = {
    "LFI": "gauche",
    "Socialistes": "gauche",
    "Écologistes": "gauche",
    "GDR / Communistes": "gauche",
    "Renaissance": "bloc central",
    "MoDem": "bloc central",
    "Horizons": "bloc central",
    "UDI / Agir": "bloc central",
    "LR": "LR",
    "RN": "droite nationale",
    "UDR": "droite nationale",
    "Gouvernement": "gouvernement",
}
BLOC_ORDER = ["gauche", "bloc central", "LR", "droite nationale", "gouvernement"]


def month_range(months: list[str]) -> list[str]:
    """Continuous month axis from corpus min to max."""
    lo, hi = min(months), max(months)
    out, y, m = [], int(lo[:4]), int(lo[5:7])
    while f"{y:04d}-{m:02d}" <= hi:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def rolling3(values: list[float]) -> list[float]:
    out = []
    for i in range(len(values)):
        window = values[max(0, i - 1) : i + 2]
        out.append(round(sum(window) / len(window), 3))
    return out


def main() -> None:
    config = json.loads((ROOT / "config" / "subjects.json").read_text())
    monthly = pl.read_parquet(OUT / "monthly_phrase.parquet")
    occ = pl.read_parquet(OUT / "occurrences.parquet")
    words = pl.read_parquet(OUT / "speaker_words.parquet")
    lifecycle = {r["phrase_key"]: r for r in json.loads((OUT / "lifecycle.json").read_text())}
    births = json.loads((OUT / "births.json").read_text())

    # Re-derive family on occurrences via aggregate's resolver (kept in one place).
    import importlib.util

    spec = importlib.util.spec_from_file_location("aggregate", ROOT / "scripts" / "aggregate.py")
    agg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agg)
    amo = agg.AmoResolver()
    occ = agg.add_family(occ, amo).with_columns(
        pl.col("date").str.slice(0, 7).alias("month"),
        (pl.col("date").str.slice(0, 4) + "-T" + ((pl.col("date").str.slice(5, 2).cast(pl.Int32) + 2) // 3).cast(pl.String)).alias("quarter"),
    )
    words = agg.add_family(words, amo).with_columns(
        pl.col("date").str.slice(0, 7).alias("month"),
        (pl.col("date").str.slice(0, 4) + "-T" + ((pl.col("date").str.slice(5, 2).cast(pl.Int32) + 2) // 3).cast(pl.String)).alias("quarter"),
    )

    axis = month_range(monthly["month"].to_list())
    corpus_month = dict(
        words.group_by("month").agg(pl.col("num_words").sum()).iter_rows()
    )
    family_quarter_words = {
        (r["family"], r["quarter"]): r["num_words"]
        for r in words.group_by("family", "quarter").agg(pl.col("num_words").sum()).iter_rows(named=True)
    }
    quarters = sorted({q for _, q in family_quarter_words})

    subjects_out = []
    for subject in config["subjects"]:
        phrases_out = []
        for ph in subject["phrases"]:
            k = ph["key"]
            m = {r["month"]: r for r in monthly.filter(pl.col("phrase_key") == k).iter_rows(named=True)}
            counts = [int(m[a]["count"]) if a in m else 0 for a in axis]
            rates = [round(float(m[a]["rate_pm"]), 3) if a in m else 0.0 for a in axis]
            po = occ.filter(pl.col("phrase_key") == k)
            attributed = po.filter(pl.col("family") != "(non attribué)")

            # family × quarter rate matrix — rows ordered by ADOPTION: first use on
            # or after the phrase's public birth (pre-birth idiomatic background
            # must not drive the genealogy order); background-only families last.
            birth_date = ((ph.get("birth") or {}).get("date") or "")[:10]
            fam_stats = (
                attributed.group_by("family")
                .agg(
                    pl.col("date").min().alias("first_any"),
                    pl.col("date").filter(pl.col("date") >= birth_date).min().alias("first_post"),
                    pl.col("n_in_sentence").sum().alias("n"),
                )
                .with_columns(pl.col("first_post").fill_null("9999").alias("sort_key"))
                .sort("sort_key", "first_any")
            )
            fams = [r["family"] for r in fam_stats.iter_rows(named=True) if r["n"] >= 2]
            fq = {
                (r["family"], r["quarter"]): r["n"]
                for r in attributed.group_by("family", "quarter").agg(pl.col("n_in_sentence").sum().alias("n")).iter_rows(named=True)
            }
            matrix = [
                [
                    round(fq.get((f, q), 0) / max(family_quarter_words.get((f, q), 0), 1) * 1_000_000, 2)
                    for q in quarters
                ]
                for f in fams
            ]
            counts_matrix = [[int(fq.get((f, q), 0)) for q in quarters] for f in fams]

            # quarterly bloc shares (attributed only)
            bloc_q = (
                attributed.with_columns(
                    pl.col("family").replace_strict(BLOC_OF, default="autres").alias("bloc")
                )
                .filter(pl.col("bloc") != "autres")
                .group_by("quarter", "bloc")
                .agg(pl.col("n_in_sentence").sum().alias("n"))
            )
            bq = {(r["quarter"], r["bloc"]): r["n"] for r in bloc_q.iter_rows(named=True)}
            bloc_shares = {
                q: [int(bq.get((q, b), 0)) for b in BLOC_ORDER] for q in quarters
            }

            # first quote per family (adoption genealogy) — post-birth when possible
            first_by_family = []
            for f in fams:
                fo_df = attributed.filter(pl.col("family") == f)
                post = fo_df.filter(pl.col("date") >= birth_date) if birth_date else fo_df
                fo = (post if post.height else fo_df).sort("date", "start_offset_ms").row(0, named=True)
                first_by_family.append(
                    {
                        "family": f,
                        "date": fo["date"],
                        "speaker": fo["speaker"] or "(non identifié)",
                        "quote": fo["sentence_text"],
                        "category": fo["category"],
                        "confirmed": fo["confirmed"],
                        "pre_birth_background": bool(birth_date) and not post.height,
                    }
                )

            lc = lifecycle.get(k, {})
            phrases_out.append(
                {
                    "key": k,
                    "canonical": ph["canonical"],
                    "role": ph.get("role", "core"),
                    "birth": ph.get("birth"),
                    "capture_event": ph.get("capture_event"),
                    "death_event": ph.get("death_event"),
                    "total": lc.get("total", 0),
                    "first_date": lc.get("first_date"),
                    "last_date": lc.get("last_date"),
                    "peak_month": lc.get("peak_month"),
                    "n_speakers": lc.get("n_speakers"),
                    "venue_split": lc.get("venue_split"),
                    "monthly_counts": counts,
                    "monthly_rate": rates,
                    "monthly_rate_smooth": rolling3(rates),
                    "families": fams,
                    "family_quarter_rate": matrix,
                    "family_quarter_count": counts_matrix,
                    "bloc_shares_by_quarter": bloc_shares,
                    "adoption": first_by_family,
                    "first_15": births.get(k, [])[:15],
                }
            )
        subjects_out.append(
            {
                "key": subject["key"],
                "title_fr": subject["title_fr"],
                "storyline": subject.get("storyline", ""),
                "phrases": phrases_out,
            }
        )

    meta = {
        "sessions": 8957,
        "window": [axis[0], axis[-1]],
        "months": axis,
        "quarters": quarters,
        "bloc_order": BLOC_ORDER,
        "corpus_words_by_month": {a: int(corpus_month.get(a, 0)) for a in axis},
        "total_words": int(sum(corpus_month.values())),
    }
    (OUT / "viz-data.json").write_text(
        json.dumps({"meta": meta, "subjects": subjects_out}, ensure_ascii=False)
    )
    size = (OUT / "viz-data.json").stat().st_size
    print(f"[export] viz-data.json written ({size/1e6:.1f} MB, {len(subjects_out)} subjects)")


if __name__ == "__main__":
    main()
