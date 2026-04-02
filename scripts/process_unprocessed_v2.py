#!/usr/bin/env python3
"""Process unprocessed sources using AmberMemory's compress_session.

Candidate-first mode: compress_session writes to candidate_memories first.
Run promote_candidates.py later to promote to contexts.
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Add parent directory to path
amber_memory_dir = Path(__file__).parent.parent
sys.path.insert(0, str(amber_memory_dir))

# Import from amber_memory package
import amber_memory
from amber_memory.client import AmberMemory

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".amber" / "memory.db"
BATCH_SIZE = 100

# Doubao ARK API config
ARK_API_KEY = os.getenv("ARK_API_KEY", "2cad7b32-7bcc-4b36-a545-82bf75eadd8f")
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
ARK_MODEL = "ep-20250224155838-xqxzl"  # doubao-pro-32k


async def call_doubao_llm(prompt: str) -> str:
    """Call Doubao LLM via ARK API."""
    import aiohttp
    
    url = f"{ARK_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {ARK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": ARK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
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
    
    if source_type == "chat":
        # WeChat message format
        sender = meta.get("sender", "unknown")
        return [{"role": "user", "content": f"[{sender}]: {content}"}]
    elif source_type == "text":
        # Diary or note
        return [{"role": "user", "content": content}]
    else:
        return [{"role": "user", "content": content}]


async def process_batch(memory: AmberMemory, sources: list):
    """Process a batch of sources and extract memories.

    Candidate-first mode: compress_session stages pending candidates,
    so mark_source_processed stores candidate IDs/empty list for now.
    """
    processed_count = 0
    candidate_count = 0
    
    for source_id, source_type, content, metadata, created_at in sources:
        try:
            # Format as messages
            messages = format_source_as_messages(source_type, content, metadata)
            
            # Extract memories using compress_session (now writes candidates by default)
            memories = await memory.compress_session(
                messages=messages,
                user="frankie",
                session_id=f"source_{source_id}",
                summary=""
            )
            
            # Candidate-first path: compress_session returns [] and stages into candidate_memories
            memory.store.mark_source_processed(
                source_id,
                [m.uri for m in memories] if memories else []
            )
            
            processed_count += 1
            candidate_count += len(memories)
            
            if processed_count % 10 == 0:
                logger.info(f"Processed {processed_count} sources, staged {candidate_count} direct memories")
        
        except Exception as e:
            logger.error(f"Error processing source {source_id}: {e}")
            # Mark as processed even if failed to avoid reprocessing
            memory.store.mark_source_processed(source_id, [])
            continue
    
    return processed_count, candidate_count


async def main():
    """Main processing loop."""
    if not DB_PATH.exists():
        logger.error(f"Database not found: {DB_PATH}")
        return
    
    # Initialize AmberMemory with Doubao LLM
    memory = AmberMemory(
        db_path=str(DB_PATH),
        llm_fn=call_doubao_llm
    )
    
    # Count unprocessed
    unprocessed = memory.store.list_unprocessed_sources(limit=10000)
    total_unprocessed = len(unprocessed)
    logger.info(f"Found {total_unprocessed} unprocessed sources")
    
    if total_unprocessed == 0:
        logger.info("No unprocessed sources, exiting")
        return
    
    # Process in batches
    offset = 0
    total_processed = 0
    total_memories = 0
    
    while offset < total_unprocessed:
        logger.info(f"\n=== Processing batch {offset // BATCH_SIZE + 1} (offset {offset}) ===")
        
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
                json.dumps(src.get("metadata", {})),
                src.get("created_at", 0)
            )
            for src in batch
        ]
        
        processed, memories = await process_batch(memory, sources)
        total_processed += processed
        total_memories += memories
        
        offset += BATCH_SIZE
        
        logger.info(f"Batch complete: {processed} sources → {memories} direct memories (candidate-first mode)")
        logger.info(f"Progress: {total_processed}/{total_unprocessed} ({100*total_processed/total_unprocessed:.1f}%)")
    
    logger.info(f"\n=== Processing complete ===")
    logger.info(f"Total processed: {total_processed} sources")
    logger.info(f"Total staged direct memories: {total_memories} (candidate-first mode usually returns 0 here)")
    
    # Final stats
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.execute("SELECT COUNT(*) FROM contexts")
    total_contexts = cursor.fetchone()[0]
    cursor = conn.execute("SELECT COUNT(*) FROM candidate_memories WHERE status = 'pending'")
    total_candidates = cursor.fetchone()[0]
    logger.info(f"Total contexts in database: {total_contexts}")
    logger.info(f"Pending candidates in database: {total_candidates}")
    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
