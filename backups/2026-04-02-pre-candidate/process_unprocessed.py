#!/usr/bin/env python3
"""Process unprocessed sources from amber-memory database.

Reads sources with processed=0, extracts memories using LLM, writes to contexts table.
"""

import asyncio
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.context import Context, ContextType
from core.storage import SQLiteStorage
from session.memory_extractor import MemoryExtractor, DIMENSION_TO_TYPE

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


def fetch_unprocessed_batch(conn: sqlite3.Connection, offset: int, limit: int):
    """Fetch a batch of unprocessed sources."""
    cursor = conn.execute(
        """
        SELECT id, source_type, content, metadata, created_at
        FROM sources
        WHERE processed = 0
        ORDER BY created_at ASC
        LIMIT ? OFFSET ?
        """,
        (limit, offset)
    )
    return cursor.fetchall()


def format_source_as_messages(source_type: str, content: str, metadata: str):
    """Convert source data to message format for extractor."""
    try:
        meta = json.loads(metadata) if metadata else {}
    except:
        meta = {}
    
    if source_type == "wechat_chat":
        # WeChat message format
        sender = meta.get("sender", "unknown")
        return [{"role": "user", "content": f"[{sender}]: {content}"}]
    elif source_type == "diary":
        return [{"role": "user", "content": content}]
    elif source_type == "bear_note":
        title = meta.get("title", "")
        full_text = f"{title}\n\n{content}" if title else content
        return [{"role": "user", "content": full_text}]
    else:
        return [{"role": "user", "content": content}]


async def process_batch(storage: SQLiteStorage, extractor: MemoryExtractor, sources: list):
    """Process a batch of sources and extract memories."""
    processed_count = 0
    memory_count = 0
    
    for source_id, source_type, content, metadata, created_at in sources:
        try:
            # Format as messages
            messages = format_source_as_messages(source_type, content, metadata)
            
            # Extract memories
            candidates = await extractor.extract(
                messages=messages,
                user="frankie",
                session_id=f"source_{source_id}",
                summary=""
            )
            
            # Save to contexts table
            for candidate in candidates:
                context = extractor.candidate_to_context(
                    candidate,
                    session_id=f"source_{source_id}"
                )
                
                # Set source_uri to link back to source
                context.source_uri = f"amber://sources/{source_id}"
                
                # Save to database
                storage.save_context(context)
                memory_count += 1
            
            # Mark source as processed
            storage.conn.execute(
                "UPDATE sources SET processed = 1 WHERE id = ?",
                (source_id,)
            )
            storage.conn.commit()
            
            processed_count += 1
            
            if processed_count % 10 == 0:
                logger.info(f"Processed {processed_count} sources, extracted {memory_count} memories")
        
        except Exception as e:
            logger.error(f"Error processing source {source_id}: {e}")
            continue
    
    return processed_count, memory_count


async def main():
    """Main processing loop."""
    if not DB_PATH.exists():
        logger.error(f"Database not found: {DB_PATH}")
        return
    
    # Initialize storage
    storage = SQLiteStorage(str(DB_PATH))
    
    # Initialize extractor with Doubao LLM
    extractor = MemoryExtractor(llm_fn=call_doubao_llm)
    
    # Count unprocessed
    cursor = storage.conn.execute("SELECT COUNT(*) FROM sources WHERE processed = 0")
    total_unprocessed = cursor.fetchone()[0]
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
        
        sources = fetch_unprocessed_batch(storage.conn, offset, BATCH_SIZE)
        if not sources:
            break
        
        processed, memories = await process_batch(storage, extractor, sources)
        total_processed += processed
        total_memories += memories
        
        offset += BATCH_SIZE
        
        logger.info(f"Batch complete: {processed} sources → {memories} memories")
        logger.info(f"Progress: {total_processed}/{total_unprocessed} ({100*total_processed/total_unprocessed:.1f}%)")
    
    logger.info(f"\n=== Processing complete ===")
    logger.info(f"Total processed: {total_processed} sources")
    logger.info(f"Total extracted: {total_memories} memories")
    
    # Final stats
    cursor = storage.conn.execute("SELECT COUNT(*) FROM contexts")
    total_contexts = cursor.fetchone()[0]
    logger.info(f"Total contexts in database: {total_contexts}")


if __name__ == "__main__":
    asyncio.run(main())
