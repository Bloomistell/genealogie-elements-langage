#!/usr/bin/env python3
"""Harvest raw video bundles (GET /v1/videos/{canonical_video_id}) for every
indexed session, keyed on disk by session id: data/videos/{session_id}.json.gz.

Why: the gated /v1/sessions transcript nulls speaker ids below the confirmation
threshold (~35% of paragraphs attributed); the raw bundle carries the un-gated
identification (~85%). The extraction step uses confirmed ids when present and
falls back to raw ids flagged `confirmed=false`.

Uses PUBLIC_API_KEY_RAW so it can run alongside harvest.py without contending
on the same per-key rate limit.

Usage: .venv/bin/python scripts/harvest_videos.py
"""

from __future__ import annotations

import gzip
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import harvest  # reuse env, pacing, retry machinery

ROOT = Path(__file__).resolve().parent.parent
VIDEOS_DIR = ROOT / "data" / "videos"
INDEX_PATH = ROOT / "data" / "sessions-index.jsonl"
ERRORS_PATH = ROOT / "data" / "videos-fetch-errors.jsonl"

RAW_KEY = harvest.ENV.get("PUBLIC_API_KEY_RAW") or harvest.ENV["PUBLIC_API_KEY"]
harvest.HEADERS = {**harvest.HEADERS, "Authorization": f"Bearer {RAW_KEY}"}


def fetch_one(session_id: str, video_id: str) -> str:
    out = VIDEOS_DIR / f"{session_id}.json.gz"
    if out.exists():
        return "cached"
    resp = harvest.get(f"{harvest.BASE}/v1/videos/{video_id}")
    if resp.status_code == 404:
        return "404"
    resp.raise_for_status()
    tmp = out.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        f.write(resp.text)
    tmp.rename(out)
    return "fetched"


def main() -> None:
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    pairs = []
    for line in INDEX_PATH.open():
        row = json.loads(line)
        vid = row.get("canonical_video_id") or row["id"]
        pairs.append((row["id"], vid))
    todo = [(s, v) for s, v in pairs if not (VIDEOS_DIR / f"{s}.json.gz").exists()]
    print(f"[videos] {len(pairs)} indexed, {len(pairs) - len(todo)} cached, {len(todo)} to fetch", flush=True)
    stats: Counter[str] = Counter()
    errors: list[dict] = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=harvest.FETCH_WORKERS) as pool:
        futures = {pool.submit(fetch_one, s, v): (s, v) for s, v in todo}
        for i, future in enumerate(as_completed(futures), 1):
            sid, vid = futures[future]
            try:
                stats[future.result()] += 1
            except Exception as exc:
                stats["error"] += 1
                errors.append({"id": sid, "video_id": vid, "error": str(exc)})
            if i % 200 == 0 or i == len(todo):
                rate = i / max(time.monotonic() - started, 1)
                eta_min = (len(todo) - i) / max(rate, 0.1) / 60
                print(f"[videos] {i}/{len(todo)} ({dict(stats)}) — {rate:.1f}/s, eta {eta_min:.0f} min", flush=True)
    if errors:
        with ERRORS_PATH.open("a") as f:
            for e in errors:
                f.write(json.dumps(e) + "\n")
    print(f"[videos] done: {dict(stats)}", flush=True)


if __name__ == "__main__":
    main()
