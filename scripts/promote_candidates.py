#!/usr/bin/env python3
"""Promote validated candidate memories into canonical contexts.

Usage:
  python scripts/promote_candidates.py --db amber_memory.db --limit 100
"""

import argparse
import json
import sys
from pathlib import Path

workspace = Path(__file__).parent.parent
sys.path.insert(0, str(workspace))

from storage.sqlite_store import SQLiteStore
from storage.candidate_store import CandidateStore
from session.memory_extractor import CandidateMemory
from session.compressor import SessionCompressor, ExtractionStats


def row_to_candidate(row: dict) -> CandidateMemory:
    return CandidateMemory(
        category=row.get("memory_type", "thought"),
        abstract=row.get("abstract", ""),
        overview=row.get("overview", ""),
        content=row.get("content", ""),
        source_session=row.get("source_session", ""),
        language=row.get("language", "zh-CN"),
        source_id=row.get("source_id", ""),
        source_type=row.get("source_type", ""),
        source_span=row.get("source_span", ""),
        speaker_id=row.get("speaker_id", ""),
        speaker_name=row.get("speaker_name", ""),
        subject_guess=row.get("subject_guess", ""),
        evidence_quote=row.get("evidence_quote", ""),
        confidence=float(row.get("confidence", 0.5) or 0.5),
        extraction_reason=row.get("extraction_reason", ""),
        conflicts_with=json.loads(row.get("conflicts_with", "[]") or "[]"),
        meta=json.loads(row.get("meta", "{}") or "{}"),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="amber_memory.db")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    store = SQLiteStore(args.db)
    candidate_store = CandidateStore(store.conn)
    compressor = SessionCompressor(store=store, llm_fn=None, embedder=None, write_to_candidates=False)

    rows = candidate_store.get_pending(limit=args.limit)
    stats = ExtractionStats()
    promoted = 0

    import asyncio

    async def run():
        nonlocal promoted
        for row in rows:
            candidate = row_to_candidate(row)
            ctx = await compressor._process_candidate(candidate, candidate.source_session, stats)
            if ctx:
                candidate_store.update_status(row["id"], "accepted", accepted_context_id=ctx.id)
                promoted += 1
            else:
                candidate_store.update_status(row["id"], "merged")

    asyncio.run(run())
    print(json.dumps({
        "pending": len(rows),
        "promoted": promoted,
        "stats": {
            "created": stats.created,
            "merged": stats.merged,
            "deleted": stats.deleted,
            "skipped": stats.skipped,
        }
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
