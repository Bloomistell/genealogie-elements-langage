#!/usr/bin/env python3
"""Sample random occurrences per phrase for qualitative review (false-positive
audit, irony/negation reading). Writes output/quote-samples.json:
{phrase_key: [{date, speaker, family?, category, quote}, …]}

Usage: .venv/bin/python scripts/sample_quotes.py [--per-phrase 30] [--seed 42]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-phrase", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    occ = pl.read_parquet(OUT / "occurrences.parquet")
    samples: dict[str, list[dict]] = {}
    for (phrase_key,), grp in occ.group_by("phrase_key"):
        n = min(args.per_phrase, grp.height)
        rows = grp.sample(n=n, seed=args.seed, shuffle=True).sort("date")
        samples[str(phrase_key)] = [
            {
                "date": r["date"],
                "speaker": r["speaker"] or "(non identifié)",
                "party_name": r["party_name"],
                "category": r["category"],
                "organ": r["organ"],
                "quote": r["sentence_text"],
            }
            for r in rows.iter_rows(named=True)
        ]
    (OUT / "quote-samples.json").write_text(json.dumps(samples, indent=2, ensure_ascii=False))
    counts = {k: len(v) for k, v in sorted(samples.items())}
    print(f"[samples] {sum(counts.values())} quotes across {len(counts)} phrases → quote-samples.json")


if __name__ == "__main__":
    main()
