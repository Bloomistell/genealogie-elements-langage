#!/usr/bin/env python3
"""Harvest the AN transcript corpus (2017 → today) from the hackathon public API.

Two phases, both resumable:

  index  — page GET /v1/sessions?type=all (newest first) to the end of the corpus,
           writing one JSON line per session to data/sessions-index.jsonl.
  fetch  — GET /v1/sessions/{id} for every indexed session that is not yet on disk,
           storing the full response as data/sessions/{id}.json.gz.

Usage:
  .venv/bin/python scripts/harvest.py [index|fetch|all]   (default: all)

Auth: reads PUBLIC_API_KEY (and optional PUBLIC_API_BASE) from the project .env.
The default per-key rate limit is 10 QPS per API instance; we self-throttle below
that and honor 429s, so a full run is polite and takes ~30-60 min.
"""

from __future__ import annotations

import gzip
import json
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SESSIONS_DIR = DATA / "sessions"
INDEX_PATH = DATA / "sessions-index.jsonl"
ERRORS_PATH = DATA / "fetch-errors.jsonl"
SUMMARY_PATH = DATA / "harvest-summary.json"

PAGE_LIMIT = 100
FETCH_WORKERS = 8
TARGET_QPS = 8.0
MAX_RETRIES = 8


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


ENV = load_env()
BASE = ENV.get("PUBLIC_API_BASE", "https://public-api-851357790188.europe-west1.run.app")
KEY = ENV.get("PUBLIC_API_KEY", "")
if not KEY:
    sys.exit("PUBLIC_API_KEY missing from research/genealogie-elements-langage/.env")

HEADERS = {"Authorization": f"Bearer {KEY}", "User-Agent": "polyfact-research-genealogie/0.1"}


class RateLimiter:
    """Simple thread-safe pacing: at most TARGET_QPS requests started per second."""

    def __init__(self, qps: float):
        self.interval = 1.0 / qps
        self.lock = threading.Lock()
        self.next_at = time.monotonic()

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            slot = max(self.next_at, now)
            self.next_at = slot + self.interval
        delay = slot - now
        if delay > 0:
            time.sleep(delay)


LIMITER = RateLimiter(TARGET_QPS)
SESSION = requests.Session()
ADAPTER = requests.adapters.HTTPAdapter(pool_connections=FETCH_WORKERS, pool_maxsize=FETCH_WORKERS)
SESSION.mount("https://", ADAPTER)


def get(url: str, params: dict | None = None) -> requests.Response:
    """GET with pacing, retries with backoff, and 429 Retry-After handling."""
    for attempt in range(MAX_RETRIES):
        LIMITER.wait()
        try:
            resp = SESSION.get(url, params=params, headers=HEADERS, timeout=120)
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(min(2**attempt, 30))
            print(f"[retry {attempt + 1}] {url} — {exc}", flush=True)
            continue
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After") or resp.headers.get("RateLimit-Reset")
            try:
                wait_s = min(float(retry_after), 120.0) if retry_after else 2.0**attempt
            except ValueError:
                wait_s = 2.0**attempt
            time.sleep(max(wait_s, 1.0))
            continue
        if resp.status_code >= 500:
            if attempt == MAX_RETRIES - 1:
                resp.raise_for_status()
            time.sleep(min(2**attempt, 30))
            continue
        return resp
    raise RuntimeError(f"exhausted retries for {url}")


def index() -> None:
    """Page the sessions list to the end, newest first, into sessions-index.jsonl."""
    DATA.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    cursor: str | None = None
    page = 0
    while True:
        params: dict[str, str | int] = {"type": "all", "limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        resp = get(f"{BASE}/v1/sessions", params)
        resp.raise_for_status()
        body = resp.json()
        batch = body.get("data", [])
        rows.extend(batch)
        page += 1
        pagination = body.get("pagination", {})
        cursor = pagination.get("next_cursor")
        if batch:
            print(f"[index] page {page}: +{len(batch)} (oldest so far: {batch[-1].get('broadcast_started_at')})", flush=True)
        if not pagination.get("has_more") or not cursor:
            break
    with INDEX_PATH.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[index] done: {len(rows)} sessions -> {INDEX_PATH}", flush=True)


def fetch_one(session_id: str) -> tuple[str, str]:
    out = SESSIONS_DIR / f"{session_id}.json.gz"
    if out.exists():
        return session_id, "cached"
    resp = get(f"{BASE}/v1/sessions/{session_id}")
    if resp.status_code == 404:
        return session_id, "404"
    resp.raise_for_status()
    tmp = out.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        f.write(resp.text)
    tmp.rename(out)
    return session_id, "fetched"


def fetch() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    ids = [json.loads(line)["id"] for line in INDEX_PATH.open()]
    todo = [sid for sid in ids if not (SESSIONS_DIR / f"{sid}.json.gz").exists()]
    print(f"[fetch] {len(ids)} indexed, {len(ids) - len(todo)} cached, {len(todo)} to fetch", flush=True)
    stats: Counter[str] = Counter()
    errors: list[dict] = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        futures = {pool.submit(fetch_one, sid): sid for sid in todo}
        for i, future in enumerate(as_completed(futures), 1):
            sid = futures[future]
            try:
                _, outcome = future.result()
                stats[outcome] += 1
            except Exception as exc:  # keep harvesting; log the casualty
                stats["error"] += 1
                errors.append({"id": sid, "error": str(exc)})
            if i % 200 == 0 or i == len(todo):
                rate = i / max(time.monotonic() - started, 1)
                eta_min = (len(todo) - i) / max(rate, 0.1) / 60
                print(f"[fetch] {i}/{len(todo)} ({dict(stats)}) — {rate:.1f}/s, eta {eta_min:.0f} min", flush=True)
    if errors:
        with ERRORS_PATH.open("a") as f:
            for e in errors:
                f.write(json.dumps(e) + "\n")
    print(f"[fetch] done: {dict(stats)}", flush=True)


def summarize() -> None:
    by_year: Counter[str] = Counter()
    by_category: Counter[str] = Counter()
    n = 0
    earliest, latest = "9999", "0000"
    for line in INDEX_PATH.open():
        row = json.loads(line)
        n += 1
        date = row.get("broadcast_started_at") or ""
        by_year[date[:4]] += 1
        by_category[row.get("category") or "?"] += 1
        earliest, latest = min(earliest, date or earliest), max(latest, date or latest)
    on_disk = len(list(SESSIONS_DIR.glob("*.json.gz")))
    summary = {
        "sessions_indexed": n,
        "sessions_on_disk": on_disk,
        "earliest": earliest,
        "latest": latest,
        "by_year": dict(sorted(by_year.items())),
        "by_category": dict(by_category.most_common()),
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("index", "all"):
        index()
    if cmd in ("fetch", "all"):
        fetch()
    summarize()
