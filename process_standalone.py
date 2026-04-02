#!/usr/bin/env python3
"""Process unprocessed sources - standalone script.

Directly uses SQLite and calls Doubao API.
"""

import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".amber" / "memory.db"
BATCH_SIZE = 50  # Smaller batch to avoid rate limits

# Doubao ARK API config
ARK_API_KEY = os.getenv("ARK_API_KEY", "2cad7b32-7bcc-4b36-a545-82bf75eadd8f")
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
ARK_MODEL = "doubao-seed-1-8-251228"  # Default model from ark_llm.py


async def call_doubao_llm(prompt: str) -> str:
    """Call Doubao LLM via ARK API."""
    import aiohttp
    import ssl
    
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
    
    # Create SSL context that doesn't verify certificates
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"ARK API error {resp.status}: {text}")
            data = await resp.json()
            return data["choices"][0]["message"]["content"]


def parse_json_from_response(text: str):
    """Extract JSON from LLM response."""
    import re
    
    if not text:
        return None
    
    text = text.strip()
    
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Try extracting from code block
    patterns = [
        r'```json\s*\n?(.*?)\n?\s*```',
        r'```\s*\n?(.*?)\n?\s*```',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
    
    return None


async def extract_memories(content: str, metadata: dict) -> list:
    """Extract memories from content using LLM."""
    
    logger.info(f"Extracting memories from content (length: {len(content)})")
    
    prompt = f"""从以下对话/文本中提取记忆。

内容：
{content[:2000]}

提取规则：
1. 识别 8 个维度：person（人物）、activity（活动）、object（物品/项目）、preference（偏好）、taboo（禁忌）、goal（目标/承诺）、pattern（模式）、thought（思考/感受）
2. 每条记忆包含：
   - category: 维度类别
   - abstract: 一句话摘要（10-30字）
   - overview: 简要概述（50-150字）
   - content: 完整内容（可选，重要记忆才需要）

返回 JSON 格式：
{{
  "memories": [
    {{
      "category": "person",
      "abstract": "张三是我的同事",
      "overview": "张三在公司技术部工作，擅长Python开发",
      "content": "..."
    }}
  ]
}}

注意：
- 只提取有价值的记忆，普通闲聊可以跳过
- 如果没有值得记录的内容，返回空数组
- 只返回 JSON，不要其他文字
"""
    
    try:
        logger.info("Calling LLM...")
        response = await call_doubao_llm(prompt)
        logger.info(f"LLM response received (length: {len(response)})")
        data = parse_json_from_response(response)
        
        if not data or "memories" not in data:
            return []
        
        return data["memories"]
    
    except Exception as e:
        logger.error(f"LLM extraction failed: {e}")
        return []


def save_memory(conn: sqlite3.Connection, memory: dict, source_id: int):
    """Save a memory to contexts table."""
    import time
    from uuid import uuid4
    
    category = memory.get("category", "activity")
    abstract = memory.get("abstract", "")
    overview = memory.get("overview", "")
    content = memory.get("content", overview)
    
    if not abstract:
        return None
    
    # Generate URI
    now = time.time()
    date = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
    short_id = uuid4().hex[:8]
    uri = f"/wechat/memories/{date}/{short_id}"
    
    # Insert into contexts
    conn.execute('''
    INSERT INTO contexts (
        id, uri, parent_uri, abstract, overview, content,
        context_type, category, importance, 
        created_at, updated_at, last_accessed,
        source_session, meta
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        uri, uri, f"/wechat/memories/{date}",
        abstract, overview, content,
        "memory", category, 0.5,
        now, now, now,
        f"source:{source_id}",
        json.dumps({"source_id": source_id})
    ))
    
    return uri


async def process_batch(conn: sqlite3.Connection, sources: list):
    """Process a batch of sources."""
    processed_count = 0
    memory_count = 0
    
    for source_id, source_type, raw_content, metadata_str, created_at in sources:
        try:
            metadata = json.loads(metadata_str) if metadata_str else {}
            
            # Extract memories
            memories = await extract_memories(raw_content, metadata)
            
            # Save memories
            uris = []
            for mem in memories:
                uri = save_memory(conn, mem, source_id)
                if uri:
                    uris.append(uri)
                    memory_count += 1
            
            # Mark source as processed
            conn.execute('''
            UPDATE sources
            SET processed = 1, process_result = ?
            WHERE id = ?
            ''', (json.dumps(uris), source_id))
            
            processed_count += 1
            
            if processed_count % 10 == 0:
                logger.info(f"Processed {processed_count} sources, extracted {memory_count} memories")
                conn.commit()
            
            # Rate limiting
            await asyncio.sleep(0.5)
        
        except Exception as e:
            logger.error(f"Error processing source {source_id}: {e}")
            # Mark as processed to avoid reprocessing
            conn.execute('UPDATE sources SET processed = 1 WHERE id = ?', (source_id,))
            continue
    
    conn.commit()
    return processed_count, memory_count


async def main():
    """Main processing loop."""
    if not DB_PATH.exists():
        logger.error(f"Database not found: {DB_PATH}")
        return
    
    conn = sqlite3.connect(str(DB_PATH))
    
    # Count unprocessed
    cursor = conn.execute("SELECT COUNT(*) FROM sources WHERE processed = 0")
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
        
        # Fetch batch
        cursor = conn.execute('''
        SELECT id, type, raw_content, metadata, created_at
        FROM sources
        WHERE processed = 0
        ORDER BY created_at ASC
        LIMIT ? OFFSET ?
        ''', (BATCH_SIZE, offset))
        
        sources = cursor.fetchall()
        if not sources:
            break
        
        processed, memories = await process_batch(conn, sources)
        total_processed += processed
        total_memories += memories
        
        offset += BATCH_SIZE
        
        logger.info(f"Batch complete: {processed} sources → {memories} memories")
        logger.info(f"Progress: {total_processed}/{total_unprocessed} ({100*total_processed/total_unprocessed:.1f}%)")
    
    logger.info(f"\n=== Processing complete ===")
    logger.info(f"Total processed: {total_processed} sources")
    logger.info(f"Total extracted: {total_memories} memories")
    
    # Final stats
    cursor = conn.execute("SELECT COUNT(*) FROM contexts")
    total_contexts = cursor.fetchone()[0]
    logger.info(f"Total contexts in database: {total_contexts}")
    
    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
