#!/usr/bin/env python3
"""Aggregate raw phrase occurrences into lifecycle-analysis tables.

Reads output/occurrences.parquet + output/speaker_words.parquet (from extract.py)
plus config/groups.json, and writes to output/:

  monthly_phrase.parquet         phrase × month: count, corpus rate (per M words)
  monthly_phrase_family.parquet  phrase × month × family: count, family rate
  births.json                    first 15 dated occurrences per phrase, quoted
  lifecycle.json                 per phrase: birth, family adoption order, peak,
                                 venue split, yearly family shares, death signals
  party_inventory.json           party_name → family mapping audit

Usage: .venv/bin/python scripts/aggregate.py
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
GROUPS = json.loads((ROOT / "config" / "groups.json").read_text())


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


UNATTRIBUTED = set(GROUPS["unattributed"])


def family_of(party_name: str) -> str:
    if party_name in UNATTRIBUTED or not party_name:
        return "(non attribué)"
    n = norm(party_name)
    for rule in GROUPS["families"]:
        if any(p in n for p in rule["patterns"]):
            return rule["family"]
    return "Autres"


BLOC = {r["family"]: r["bloc"] for r in GROUPS["families"]}


class AmoResolver:
    """(PA uid, date) → groupe politique from official AN open data (era-correct)."""

    def __init__(self) -> None:
        df = pl.read_parquet(OUT / "an_group_membership.parquet")
        self.by_uid: dict[str, list[tuple[str, str, str]]] = {}
        for r in df.iter_rows(named=True):
            self.by_uid.setdefault(r["uid"], []).append(
                (r["date_start"], r["date_end"] or "9999-12-31", r["group_name"])
            )

    def resolve(self, uid: str, date: str) -> str | None:
        for start, end, name in self.by_uid.get(uid, ()):
            if start <= date <= end:
                return name
        return None


def add_family(df: pl.DataFrame, amo: AmoResolver) -> pl.DataFrame:
    """Era-correct family: Gouvernement bench as-is, else AMO mandate at the
    session date, else the API's party_name — then the family map."""
    pairs = df.select("actor_id", "date", "party_name").unique()
    resolved = []
    for r in pairs.iter_rows(named=True):
        if r["party_name"] == "Gouvernement":
            fam = "Gouvernement"
        else:
            group = amo.resolve(r["actor_id"], r["date"]) if r["actor_id"] else None
            fam = family_of(group) if group else family_of(r["party_name"])
        resolved.append({**r, "family": fam})
    return df.join(pl.DataFrame(resolved), on=["actor_id", "date", "party_name"], how="left")


def main() -> None:
    occ = pl.read_parquet(OUT / "occurrences.parquet")
    words = pl.read_parquet(OUT / "speaker_words.parquet")

    amo = AmoResolver()
    occ = add_family(occ, amo).with_columns(pl.col("date").str.slice(0, 7).alias("month"))
    words = add_family(words, amo).with_columns(pl.col("date").str.slice(0, 7).alias("month"))

    # Audit table: which party_name landed in which family, with word volume.
    inventory = (
        words.group_by("party_name", "family")
        .agg(pl.col("num_words").sum().alias("words"))
        .sort("words", descending=True)
    )
    (OUT / "party_inventory.json").write_text(
        json.dumps(inventory.to_dicts(), indent=2, ensure_ascii=False)
    )

    corpus_month = words.group_by("month").agg(pl.col("num_words").sum().alias("corpus_words"))
    family_month = words.group_by("month", "family").agg(
        pl.col("num_words").sum().alias("family_words")
    )

    monthly = (
        occ.group_by("subject_key", "phrase_key", "month")
        .agg(pl.col("n_in_sentence").sum().alias("count"))
        .join(corpus_month, on="month")
        .with_columns((pl.col("count") / pl.col("corpus_words") * 1_000_000).alias("rate_pm"))
        .sort("subject_key", "phrase_key", "month")
    )
    monthly.write_parquet(OUT / "monthly_phrase.parquet")

    monthly_family = (
        occ.group_by("subject_key", "phrase_key", "month", "family")
        .agg(pl.col("n_in_sentence").sum().alias("count"))
        .join(family_month, on=["month", "family"], how="left")
        .with_columns((pl.col("count") / pl.col("family_words") * 1_000_000).alias("rate_pm"))
        .sort("subject_key", "phrase_key", "month", "family")
    )
    monthly_family.write_parquet(OUT / "monthly_phrase_family.parquet")

    births: dict[str, list[dict]] = {}
    lifecycle: list[dict] = []
    for (subject_key, phrase_key), grp in sorted(
        occ.group_by("subject_key", "phrase_key"), key=lambda kv: kv[0]
    ):
        g = grp.sort("date", "start_offset_ms")
        first = g.row(0, named=True)
        total = int(g["n_in_sentence"].sum())

        births[phrase_key] = [
            {
                "date": r["date"],
                "speaker": r["speaker"] or "(non identifié)",
                "family": r["family"],
                "party_name": r["party_name"],
                "confirmed": r["confirmed"],
                "category": r["category"],
                "organ": r["organ"],
                "session_id": r["session_id"],
                "session_title": r["session_title"],
                "quote": r["sentence_text"],
            }
            for r in g.head(15).iter_rows(named=True)
        ]

        by_month = g.group_by("month").agg(pl.col("n_in_sentence").sum().alias("c")).sort("month")
        peak = by_month.sort("c", descending=True).row(0, named=True)

        attributed = g.filter(~pl.col("family").is_in(["(non attribué)"]))
        fam_first = (
            attributed.group_by("family")
            .agg(pl.col("date").min().alias("first_date"), pl.col("n_in_sentence").sum().alias("n"))
            .sort("first_date")
        )
        fam_year = (
            attributed.with_columns(pl.col("date").str.slice(0, 4).alias("year"))
            .group_by("year", "family")
            .agg(pl.col("n_in_sentence").sum().alias("n"))
            .sort("year", "family")
        )
        venue = g.group_by("category").agg(pl.col("n_in_sentence").sum().alias("n")).sort("n", descending=True)

        lifecycle.append(
            {
                "subject_key": subject_key,
                "phrase_key": phrase_key,
                "total": total,
                "first_date": first["date"],
                "first_speaker": first["speaker"] or "(non identifié)",
                "first_family": first["family"],
                "first_confirmed": first["confirmed"],
                "first_quote": first["sentence_text"],
                "last_date": g["date"].max(),
                "peak_month": peak["month"],
                "peak_count": int(peak["c"]),
                "active_months": by_month.height,
                "n_speakers": attributed["actor_id"].n_unique(),
                "n_families": fam_first.height,
                "family_adoption_order": fam_first.to_dicts(),
                "family_by_year": fam_year.to_dicts(),
                "venue_split": venue.to_dicts(),
            }
        )

    (OUT / "births.json").write_text(json.dumps(births, indent=2, ensure_ascii=False))
    (OUT / "lifecycle.json").write_text(json.dumps(lifecycle, indent=2, ensure_ascii=False))
    print(f"[aggregate] {len(lifecycle)} phrases → monthly tables + births.json + lifecycle.json")
    for entry in lifecycle:
        print(
            f"  {entry['phrase_key']:34s} n={entry['total']:6d} "
            f"{entry['first_date']} → {entry['last_date']} peak {entry['peak_month']} "
            f"families={entry['n_families']}"
        )


if __name__ == "__main__":
    main()
