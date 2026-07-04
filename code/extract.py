#!/usr/bin/env python3
"""Scan the harvested corpus for lexicon phrases → occurrence + denominator tables.

Reads config/subjects.json (the phrase lexicon) and every data/sessions/*.json.gz,
then writes:

  output/occurrences.parquet   one row per phrase match (subject, phrase, session,
                               date, venue, organ, speaker, group, sentence text…)
  output/speaker_words.parquet one row per (session, actor): word count + group —
                               the denominator for "share of speech" normalization.
  output/extract-summary.json  match counts per phrase, for a quick sanity read.

Matching is on normalized text (lowercase, diacritics stripped, typographic
apostrophes unified) with word boundaries, so lexicon patterns are written
accent-less: "quoi qu'il en coute". Patterns are regex fragments (alternations
and optional groups allowed).

Usage: .venv/bin/python scripts/extract.py [--sample N]
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import unicodedata
from multiprocessing import Pool
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = ROOT / "data" / "sessions"
VIDEOS_DIR = ROOT / "data" / "videos"
CONFIG_PATH = ROOT / "config" / "subjects.json"
OUT_DIR = ROOT / "output"

APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "‘": "'"})


def normalize(text: str) -> str:
    """lowercase, strip diacritics, unify apostrophes — the matching space."""
    text = text.translate(APOSTROPHES).lower()
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def load_lexicon() -> list[dict]:
    """Flatten config into [{subject_key, phrase_key, role, regex}]. Patterns are
    joined per phrase into one compiled alternation with word boundaries."""
    config = json.loads(CONFIG_PATH.read_text())
    lexicon = []
    for subject in config["subjects"]:
        for phrase in subject["phrases"]:
            patterns = phrase["patterns"]
            alternation = "|".join(f"(?:{p})" for p in patterns)
            regex = re.compile(rf"\b(?:{alternation})\b")
            exclude = phrase.get("exclude")
            lexicon.append(
                {
                    "subject_key": subject["key"],
                    "phrase_key": phrase["key"],
                    "role": phrase.get("role", "core"),
                    "regex": regex,
                    # a sentence matching this is dropped (known false-positive contexts)
                    "exclude": re.compile("|".join(exclude)) if exclude else None,
                }
            )
    return lexicon


LEXICON: list[dict] = []  # populated in each worker via init


def _init_worker() -> None:
    global LEXICON
    LEXICON = load_lexicon()


def scan_session(path: Path) -> tuple[list[dict], list[dict]]:
    """Return (occurrence rows, speaker word-count rows) for one session file."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        doc = json.load(f)

    session_id = doc["id"]
    date = (doc.get("broadcast_started_at") or "")[:10]
    meta = doc.get("metadata") or {}
    category = meta.get("category") or "?"
    organ = meta.get("organ") or ""
    title = doc.get("title") or ""

    actors = {a["id"]: a for a in doc.get("actors") or []}

    # Raw (un-gated) speaker ids from the /v1/videos bundle: fallback attribution
    # for paragraphs the stable tier leaves unconfirmed (flagged confirmed=false).
    raw_by_para: dict[str, str] = {}
    video_path = VIDEOS_DIR / f"{session_id}.json.gz"
    if video_path.exists():
        try:
            with gzip.open(video_path, "rt", encoding="utf-8") as f:
                vdoc = json.load(f)
            for a in vdoc.get("actors") or []:
                actors.setdefault(a["id"], a)
            for p in (vdoc.get("transcript") or {}).get("paragraphs") or []:
                if p.get("actor_id") and p.get("id"):
                    raw_by_para[p["id"]] = p["actor_id"]
        except (OSError, json.JSONDecodeError):
            pass  # raw bundle missing/corrupt — confirmed-only for this session

    def group_of(actor_id: str | None) -> tuple[str, str, str]:
        a = actors.get(actor_id or "")
        if not a:
            return "", "(non identifié)", ""
        name = f"{a.get('first_name') or ''} {a.get('last_name') or ''}".strip()
        return name, a.get("party_name") or "(sans groupe)", a.get("role") or ""

    occurrences: list[dict] = []
    words: dict[tuple[str | None, bool], int] = {}
    paragraphs = (doc.get("transcript") or {}).get("paragraphs") or []
    for para in paragraphs:
        confirmed = bool(para.get("actor_id"))
        actor_id = para.get("actor_id") or raw_by_para.get(para.get("id") or "")
        key = (actor_id, confirmed)
        words[key] = words.get(key, 0) + (para.get("num_words") or 0)
        for sentence in para.get("sentences") or []:
            text = sentence.get("text") or ""
            norm = normalize(text)
            for entry in LEXICON:
                n_hits = len(entry["regex"].findall(norm))
                if not n_hits:
                    continue
                if entry["exclude"] is not None and entry["exclude"].search(norm):
                    continue
                speaker, party, role = group_of(actor_id)
                occurrences.append(
                    {
                        "subject_key": entry["subject_key"],
                        "phrase_key": entry["phrase_key"],
                        "phrase_role": entry["role"],
                        "n_in_sentence": n_hits,
                        "session_id": session_id,
                        "date": date,
                        "category": category,
                        "organ": organ,
                        "session_title": title,
                        "actor_id": actor_id or "",
                        "confirmed": confirmed,
                        "speaker": speaker,
                        "party_name": party,
                        "speaker_role": role,
                        "paragraph_id": para.get("id") or "",
                        "start_offset_ms": para.get("start_offset_ms") or 0,
                        "sentence_text": text,
                    }
                )

    word_rows = []
    for (actor_id, confirmed), n_words in words.items():
        speaker, party, role = group_of(actor_id)
        word_rows.append(
            {
                "session_id": session_id,
                "date": date,
                "category": category,
                "actor_id": actor_id or "",
                "confirmed": confirmed,
                "speaker": speaker,
                "party_name": party,
                "num_words": n_words,
            }
        )
    return occurrences, word_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=0, help="scan only N sessions (smoke test)")
    args = parser.parse_args()

    if not CONFIG_PATH.exists():
        sys.exit(f"missing lexicon: {CONFIG_PATH}")
    files = sorted(SESSIONS_DIR.glob("*.json.gz"))
    if args.sample:
        files = files[:: max(len(files) // args.sample, 1)][: args.sample]
    print(f"[extract] scanning {len(files)} sessions with {len(load_lexicon())} phrases")

    all_occurrences: list[dict] = []
    all_words: list[dict] = []
    with Pool(processes=8, initializer=_init_worker) as pool:
        for i, (occ, words) in enumerate(pool.imap_unordered(scan_session, files, chunksize=16), 1):
            all_occurrences.extend(occ)
            all_words.extend(words)
            if i % 1000 == 0:
                print(f"[extract] {i}/{len(files)} sessions, {len(all_occurrences)} matches so far", flush=True)

    OUT_DIR.mkdir(exist_ok=True)
    occ_df = pl.DataFrame(all_occurrences) if all_occurrences else pl.DataFrame()
    words_df = pl.DataFrame(all_words)
    occ_df.write_parquet(OUT_DIR / "occurrences.parquet")
    words_df.write_parquet(OUT_DIR / "speaker_words.parquet")

    summary = (
        occ_df.group_by("subject_key", "phrase_key")
        .agg(pl.col("n_in_sentence").sum().alias("total"), pl.col("date").min().alias("first"), pl.col("date").max().alias("last"))
        .sort("subject_key", "total", descending=[False, True])
        .to_dicts()
        if not occ_df.is_empty()
        else []
    )
    (OUT_DIR / "extract-summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"[extract] {len(all_occurrences)} occurrence rows, {len(all_words)} speaker-word rows")


if __name__ == "__main__":
    main()
