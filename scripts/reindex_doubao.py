#!/usr/bin/env python3
"""
Reindex amber-memory with 豆包 multimodal embedding API.
Adds embedding vectors to all contexts for semantic search.
"""
import sqlite3
import json
import time
import sys
import os
import requests

DB_PATH = os.path.expanduser("~/.amber/memory.db")
ARK_API_KEY = "f1665946-441a-4ed5-b716-cc67ddd8abfc"
ARK_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal"
MODEL = "ep-20260228010804-gbtgr"
BATCH_SIZE = 1  # API seems to take one input at a time
SLEEP_BETWEEN = 0.1  # rate limit safety


def get_embedding(text: str) -> list:
    """Get embedding vector from 豆包 API."""
    resp = requests.post(
        ARK_ENDPOINT,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ARK_API_KEY}",
        },
        json={
            "model": MODEL,
            "input": [{"type": "text", "text": text[:2000]}],  # truncate long text
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["data"]["embedding"]


def ensure_embedding_column(db):
    """Add embedding column if not exists."""
    cols = [r[1] for r in db.execute("PRAGMA table_info(contexts)").fetchall()]
    if "embedding" not in cols:
        db.execute("ALTER TABLE contexts ADD COLUMN embedding TEXT")
        db.commit()
        print("Added 'embedding' column to contexts table")


def main():
    db = sqlite3.connect(DB_PATH)
    ensure_embedding_column(db)

    # Get all contexts without embeddings
    rows = db.execute(
        "SELECT id, abstract, content FROM contexts WHERE embedding IS NULL"
    ).fetchall()
    total = len(rows)
    print(f"Total to index: {total}")

    if total == 0:
        print("All contexts already have embeddings!")
        return

    success = 0
    errors = 0
    start = time.time()

    for i, (ctx_id, abstract, content) in enumerate(rows):
        # Use abstract as primary text, fall back to content
        text = abstract or (content or "")[:500]
        if not text.strip():
            continue

        try:
            emb = get_embedding(text)
            db.execute(
                "UPDATE contexts SET embedding = ? WHERE id = ?",
                (json.dumps(emb), ctx_id),
            )
            success += 1

            if success % 50 == 0:
                db.commit()
                elapsed = time.time() - start
                rate = success / elapsed
                remaining = (total - i) / rate if rate > 0 else 0
                print(f"[{i+1}/{total}] {success} done, {errors} errors, "
                      f"{rate:.1f}/s, ~{remaining:.0f}s remaining")

        except Exception as e:
            errors += 1
            if errors > 20:
                print(f"[ABORT] Too many errors: {e}")
                break
            print(f"[{i+1}/{total}] Error for {ctx_id}: {e}")

        time.sleep(SLEEP_BETWEEN)

    db.commit()
    db.close()
    elapsed = time.time() - start
    print(f"\nDone! {success}/{total} indexed, {errors} errors, {elapsed:.1f}s")


if __name__ == "__main__":
    main()
