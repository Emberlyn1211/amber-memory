#!/usr/bin/env python3
"""Test candidate-first pipeline end-to-end.

Usage:
  python scripts/test_candidate_pipeline.py
"""

import asyncio
import sys
import tempfile
from pathlib import Path

workspace = Path(__file__).parent.parent
sys.path.insert(0, str(workspace))

from amber_memory.client import AmberMemory
from amber_memory.storage.candidate_store import CandidateStore
from amber_memory.session.candidate_validator import CandidateValidator


def test_candidate_pipeline():
    """Test that compress_session writes to candidates, not contexts."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    # Create AmberMemory with write_to_candidates=True (default)
    mem = AmberMemory(db_path=db_path)
    candidate_store = CandidateStore(mem.store.conn)

    # Simulate a chat session
    messages = [
        {"role": "user", "content": "Frankie: 我昨天搬到深圳南山了，住在科技园附近"},
        {"role": "assistant", "content": "好的，记下了"},
    ]

    # Run compress_session
    async def run():
        result = await mem.compress_session(
            messages=messages,
            user="frankie",
            session_id="test_session_001",
        )
        return result

    contexts = asyncio.run(run())

    # With write_to_candidates=True, contexts should be empty
    assert len(contexts) == 0, f"Expected 0 contexts, got {len(contexts)}"

    # But candidates should have been written
    pending = candidate_store.get_pending(limit=100)
    print(f"✓ Pending candidates: {len(pending)}")

    # Verify candidate structure
    for cand in pending:
        print(f"  - {cand['memory_type']}: {cand['abstract'][:40]}...")
        print(f"    speaker={cand.get('speaker_name', 'N/A')}, confidence={cand.get('confidence', 'N/A')}")
        assert cand["status"] in ("pending", "rejected"), f"Unexpected status: {cand['status']}"
        assert cand["source_session"] == "test_session_001"

    # Cleanup
    import os
    os.unlink(db_path)
    print("\n✓ Candidate pipeline test passed")


if __name__ == "__main__":
    test_candidate_pipeline()
