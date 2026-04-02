"""Candidate memory storage operations."""
import json
import time
from typing import Dict, List, Optional


class CandidateStore:
    """Operations for candidate_memories table."""

    def __init__(self, conn):
        self.conn = conn

    def insert(self, candidate: dict) -> str:
        """Insert a new candidate memory."""
        import uuid
        candidate_id = str(uuid.uuid4())
        now = time.time()

        self.conn.execute("""
            INSERT INTO candidate_memories 
            (id, source_id, source_type, source_session, source_span, speaker_id, speaker_name,
             subject_guess, memory_type, abstract, overview, content, evidence_quote,
             confidence, extraction_reason, language, conflicts_with, status, created_at, meta)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            candidate_id,
            candidate.get("source_id", ""),
            candidate.get("source_type", ""),
            candidate.get("source_session", ""),
            candidate.get("source_span", ""),
            candidate.get("speaker_id", ""),
            candidate.get("speaker_name", ""),
            candidate.get("subject_guess", ""),
            candidate.get("memory_type", "thought"),
            candidate.get("abstract", ""),
            candidate.get("overview", ""),
            candidate.get("content", ""),
            candidate.get("evidence_quote", ""),
            candidate.get("confidence", 0.5),
            candidate.get("extraction_reason", ""),
            candidate.get("language", "zh-CN"),
            json.dumps(candidate.get("conflicts_with", [])),
            candidate.get("status", "pending"),
            now,
            json.dumps(candidate.get("meta", {}))
        ))
        self.conn.commit()
        return candidate_id

    def get_pending(self, limit: int = 100) -> List[dict]:
        """Get pending candidates for review."""
        rows = self.conn.execute(
            "SELECT * FROM candidate_memories WHERE status = 'pending' ORDER BY created_at LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def update_status(self, candidate_id: str, status: str, accepted_context_id: str = "", meta: Optional[dict] = None):
        """Update candidate status (pending/accepted/rejected/merged)."""
        now = time.time()
        self.conn.execute("""
            UPDATE candidate_memories 
            SET status = ?, reviewed_at = ?, accepted_context_id = ?,
                meta = COALESCE(meta, '{}') || ?
            WHERE id = ?
        """, (status, now, accepted_context_id, json.dumps(meta or {}), candidate_id))
        self.conn.commit()

    def find_conflicts(self, candidate: dict) -> List[dict]:
        """Find potentially conflicting existing candidates."""
        mem_type = candidate.get("memory_type", "")
        subject = candidate.get("subject_guess", "")

        rows = self.conn.execute("""
            SELECT * FROM candidate_memories 
            WHERE memory_type = ? AND subject_guess = ? AND status != 'rejected'
        """, (mem_type, subject)).fetchall()

        return [dict(r) for r in rows]
