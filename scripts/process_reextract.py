#!/usr/bin/env python3
"""Re-extract memories from sources with enhanced rules.

Key rules:
1. Preserve 木马 memories (VIP list)
2. Group chat filtering:
   - tier0 (junk groups) → skip
   - tier1 (core circle) → treat as private chat
   - tier2 (quality groups) → keep
3. 9-dimension model: person/activity/object/place/preference/taboo/goal/pattern/thought
"""

import asyncio
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import List, Dict, Optional

# Add workspace to path (amber_memory is a symlink in workspace)
workspace_dir = Path.home() / ".openclaw" / "workspace"
sys.path.insert(0, str(workspace_dir))

# Import from amber_memory package
import amber_memory
from amber_memory.client import AmberMemory

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".amber" / "memory.db"
BATCH_SIZE = 10  # Test with small batch first

# Doubao ARK API config
ARK_API_KEY = os.getenv("ARK_API_KEY", "2cad7b32-7bcc-4b36-a545-82bf75eadd8f")
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
ARK_MODEL = "ep-20260228010804-gbtgr"  # doubao multimodal embedding endpoint

# VIP list (木马 etc.)
VIP_LIST = """
- 木马：Frankie 最重要的人，所有相关记忆都要提取（只是不主动提及）
- 张丙萱（父亲，微信名颍川散人/风轻扬）
- 母亲
- 外婆
- 发小们（十一去哪群成员）
"""

# Group chat tiers
TIER0_JUNK_GROUPS = [
    "乐高", "游戏", "广告", "羊毛", "拼单", "团购",
    # Add more junk group keywords
]

TIER1_CORE_GROUPS = [
    "十一去哪", "十一去哪儿", "司令部", "总统府",
    # Add more core group names
]

TIER2_QUALITY_GROUPS = [
    "OpenClaw", "缘社", "生财有术",
    # Add more quality group names
]


def classify_group(group_name: str) -> str:
    """Classify group chat tier."""
    if not group_name:
        return "unknown"
    
    group_lower = group_name.lower()
    
    # Check tier0 (junk)
    for keyword in TIER0_JUNK_GROUPS:
        if keyword.lower() in group_lower:
            return "tier0"
    
    # Check tier1 (core)
    for name in TIER1_CORE_GROUPS:
        if name in group_name:
            return "tier1"
    
    # Check tier2 (quality)
    for name in TIER2_QUALITY_GROUPS:
        if name in group_name:
            return "tier2"
    
    # Default: treat as tier2 (keep)
    return "tier2"


async def call_doubao_llm(prompt: str) -> str:
    """Call Doubao LLM via ARK API."""
    import aiohttp
    import ssl
    
    # Disable SSL verification for Python 3.7
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    url = f"{ARK_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {ARK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": ARK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
    }
    
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.post(url, headers=headers, json=payload, timeout=60) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"ARK API error {resp.status}: {text}")
            data = await resp.json()
            return data["choices"][0]["message"]["content"]


def format_source_as_messages(source_type: str, content: str, metadata: str):
    """Convert source data to message format for compress_session."""
    try:
        meta = json.loads(metadata) if metadata else {}
    except:
        meta = {}
    
    # Check if group chat
    is_group = meta.get("is_group", False)
    group_name = meta.get("group_name", "")
    
    if is_group and group_name:
        tier = classify_group(group_name)
        if tier == "tier0":
            # Skip junk groups
            return None, None
        elif tier == "tier1":
            # Treat as private chat
            is_group = False
    
    if source_type == "chat":
        # WeChat message format
        sender = meta.get("sender", "unknown")
        return [{"role": "user", "content": f"[{sender}]: {content}"}], is_group
    elif source_type == "text":
        # Diary or note
        return [{"role": "user", "content": content}], False
    else:
        return [{"role": "user", "content": content}], False


async def process_batch(memory: AmberMemory, sources: list):
    """Process a batch of sources and stage memories to candidate_memories."""
    processed_count = 0
    candidate_count = 0
    skipped_count = 0
    
    for source_id, source_type, content, metadata, created_at in sources:
        try:
            # Format as messages
            result = format_source_as_messages(source_type, content, metadata)
            if result is None or result[0] is None:
                # Skip tier0 junk groups
                memory.store.mark_source_processed(source_id, [])
                skipped_count += 1
                continue
            
            messages, is_group = result
            
            # Build summary with VIP list and group context
            summary_parts = []
            if is_group:
                summary_parts.append("⚠️ 这是群聊记录，只提取 Frankie（「我:」）的记忆。")
            summary_parts.append(f"\n🌟 重要人物（VIP）：\n{VIP_LIST}")
            summary = "\n".join(summary_parts)
            
            # compress_session now writes to candidate_memories (pending), not contexts
            await memory.compress_session(
                messages=messages,
                user="frankie",
                session_id=f"source_{source_id}",
                summary=summary,
            )
            
            # Count staged candidates for this source
            cur = memory.store.conn.execute(
                "SELECT COUNT(*) FROM candidate_memories WHERE source_session = ? AND status = 'pending'",
                (f"source_{source_id}",)
            )
            staged = cur.fetchone()[0]
            candidate_count += staged
            
            # Mark source as processed
            memory.store.mark_source_processed(source_id, [])
            
            processed_count += 1
            
            if processed_count % 100 == 0:
                logger.info(f"Processed {processed_count} sources, staged {candidate_count} candidates, skipped {skipped_count}")
        
        except Exception as e:
            logger.error(f"Error processing source {source_id}: {e}")
            memory.store.mark_source_processed(source_id, [])
            continue
    
    return processed_count, candidate_count, skipped_count


async def main():
    """Main processing loop."""
    if not DB_PATH.exists():
        logger.error(f"Database not found: {DB_PATH}")
        return
    
    # Ask for confirmation to clear contexts
    print("\n⚠️  This will:")
    print("1. Clear all existing contexts (memories)")
    print("2. Reset all sources to unprocessed")
    print("3. Re-extract memories with new rules")
    print("\nContinue? (yes/no): ", end="")
    
    # Auto-confirm in non-interactive mode
    if not sys.stdin.isatty():
        confirm = "yes"
        print("yes (auto-confirmed)")
    else:
        confirm = input().strip().lower()
    
    if confirm != "yes":
        print("Aborted.")
        return
    
    # Clear contexts and reset sources
    logger.info("Clearing contexts table...")
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DELETE FROM contexts")
    conn.execute("UPDATE sources SET processed = 0, process_result = '[]'")
    conn.commit()
    conn.close()
    logger.info("Contexts cleared, sources reset.")
    
    # Initialize AmberMemory with Doubao LLM
    memory = AmberMemory(
        db_path=str(DB_PATH),
        llm_fn=call_doubao_llm
    )
    
    # Count unprocessed - use direct SQL instead of list_unprocessed_sources
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT id, type, raw_content, metadata, created_at FROM sources WHERE processed = 0 ORDER BY created_at ASC"
    )
    unprocessed = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    total_unprocessed = len(unprocessed)
    logger.info(f"Found {total_unprocessed} unprocessed sources")
    
    if total_unprocessed == 0:
        logger.info("No unprocessed sources, exiting")
        return
    
    # Process in batches
    offset = 0
    total_processed = 0
    total_memories = 0
    total_skipped = 0
    
    while offset < total_unprocessed:
        batch_num = offset // BATCH_SIZE + 1
        logger.info(f"\n=== Batch {batch_num} (offset {offset}) ===")
        
        # Get batch
        batch = unprocessed[offset:offset + BATCH_SIZE]
        if not batch:
            break
        
        # Convert to tuple format expected by process_batch
        sources = [
            (
                src["id"],
                src["type"],
                src["raw_content"],
                src["metadata"],
                src["created_at"]
            )
            for src in batch
        ]
        
        processed, staged, skipped = await process_batch(memory, sources)
        total_processed += processed
        total_memories += staged
        total_skipped += skipped
        
        offset += BATCH_SIZE
        
        logger.info(f"Batch {batch_num} complete: {processed} sources → {staged} candidates staged (skipped {skipped})")
        logger.info(f"Progress: {total_processed + total_skipped}/{total_unprocessed} ({100*(total_processed + total_skipped)/total_unprocessed:.1f}%)")
    
    logger.info(f"\n=== Processing complete ===")
    logger.info(f"Total processed: {total_processed} sources")
    logger.info(f"Total skipped: {total_skipped} sources (tier0 junk groups)")
    logger.info(f"Total staged: {total_memories} candidates in pending")
    
    # Final stats
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.execute("SELECT COUNT(*) FROM contexts")
    total_contexts = cursor.fetchone()[0]
    cursor = conn.execute("SELECT COUNT(*) FROM candidate_memories")
    total_candidates = cursor.fetchone()[0]
    cursor = conn.execute("SELECT COUNT(*) FROM candidate_memories WHERE status='pending'")
    pending_candidates = cursor.fetchone()[0]
    
    conn.close()
    
    logger.info(f"\nFinal database stats:")
    logger.info(f"Total contexts (canonical): {total_contexts}")
    logger.info(f"Total candidates: {total_candidates}")
    logger.info(f"Pending candidates: {pending_candidates} (run promote_candidates.py to promote)")


if __name__ == "__main__":
    asyncio.run(main())
