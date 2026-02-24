"""End-to-end integration test with real ARK API.

Tests the full pipeline: compress_session → hybrid_recall → smart_recall
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from amber_memory import AmberMemory, ArkLLM


async def main():
    api_key = os.environ.get("ARK_API_KEY")
    if not api_key:
        print("ERROR: ARK_API_KEY not set")
        return

    # Setup
    db_path = tempfile.mktemp(suffix=".db")
    llm = ArkLLM(api_key=api_key)
    mem = AmberMemory(db_path, llm_fn=llm.chat)

    print("=== Amber Memory E2E Test ===\n")

    # Test conversation (short, realistic)
    messages = [
        {"role": "user", "content": "今天和老王吃了顿火锅，他说下个月要去日本出差"},
        {"role": "assistant", "content": "听起来不错！老王是你同事吗？"},
        {"role": "user", "content": "对，我们在同一个组。他负责海外业务。对了，我决定下周开始每天跑步，减肥"},
        {"role": "assistant", "content": "跑步是个好习惯，打算每天跑多久？"},
        {"role": "user", "content": "先从3公里开始吧。还有个事，千万别在老王面前提他前女友的事，他会不高兴"},
    ]

    # Step 1: Compress session
    print("1. Compressing session (LLM extraction)...")
    memories = await mem.compress_session(
        messages=messages, user="Frankie", session_id="test-e2e-001",
    )
    print(f"   Extracted {len(memories)} memories:")
    for m in memories:
        print(f"   [{m.category}] {m.abstract}")
    print()

    # Step 2: Simple recall
    print("2. Text recall: '老王'")
    results = mem.recall("老王", limit=5)
    print(f"   Found {len(results)} results:")
    for ctx, score in results:
        print(f"   [{ctx.category}] score={score:.3f} — {ctx.abstract}")
    print()

    # Step 3: Stats
    stats = mem.stats()
    print(f"3. Stats: {stats['total']} memories, db={db_path}")
    print()

    # Cleanup
    mem.close()
    os.unlink(db_path)
    print("=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
