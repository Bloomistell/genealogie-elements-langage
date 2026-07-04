#!/usr/bin/env python3
"""Build an authoritative (PA uid, date) → groupe politique table from the AN
open-data AMO dumps (acteurs/mandats/organes, data.assemblee-nationale.fr).

Why: the API's per-session party_name is sometimes resolved against the wrong
legislature's actor record (e.g. "Union des Droites" labels on 2021 speech).
The AMO mandates carry exact date ranges per group membership, so we resolve
groups era-correctly and keep the API label only as a fallback.

Reads the dumps already present in ../vote-analysis/data/AMOANR5L1{5,6,7}
(re-downloadable from data.assemblee-nationale.fr, « Acteurs / mandats /
organes »). Writes output/an_group_membership.parquet with one row per GP
mandate: uid, group_name, date_start, date_end (empty = ongoing).

Usage: .venv/bin/python scripts/an_groups.py
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
AMO_DIRS = [
    ROOT.parent / "vote-analysis" / "data" / f"AMOANR5L{n}" for n in (15, 16, 17)
]
OUT = ROOT / "output"


def main() -> None:
    organes: dict[str, dict] = {}
    for amo in AMO_DIRS:
        for path in (amo / "organe").glob("PO*.json"):
            doc = json.loads(path.read_text())
            org = doc.get("organe", doc)
            organes[org["uid"]] = org

    rows: list[dict] = []
    seen: set[tuple] = set()
    n_actors = 0
    for amo in AMO_DIRS:
        for path in (amo / "acteur").glob("PA*.json"):
            doc = json.loads(path.read_text())
            actor = doc.get("acteur", doc)
            uid = actor["uid"]["#text"] if isinstance(actor["uid"], dict) else actor["uid"]
            n_actors += 1
            mandates = (actor.get("mandats") or {}).get("mandat") or []
            if isinstance(mandates, dict):
                mandates = [mandates]
            for m in mandates:
                if m.get("typeOrgane") != "GP":
                    continue
                org_ref = (m.get("organes") or {}).get("organeRef")
                org = organes.get(org_ref or "")
                name = (org or {}).get("libelle") or org_ref or "?"
                key = (uid, org_ref, m.get("dateDebut"), m.get("dateFin"))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "uid": uid,
                        "group_name": name,
                        "date_start": m.get("dateDebut") or "",
                        "date_end": m.get("dateFin") or "",
                    }
                )

    df = pl.DataFrame(rows).sort("uid", "date_start")
    OUT.mkdir(exist_ok=True)
    df.write_parquet(OUT / "an_group_membership.parquet")
    print(f"[an_groups] {n_actors} actor files, {df.height} GP mandate rows, "
          f"{df['uid'].n_unique()} unique actors → an_group_membership.parquet")


if __name__ == "__main__":
    main()
