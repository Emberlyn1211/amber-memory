#!/usr/bin/env python3
"""
Reindex embeddings for all contexts without embeddings.
Uses OpenAI text-embedding-3-small via OpenClaw gateway.
"""

import sqlite3
import json
import time
from pathlib import Path
import requests
from typing import List

AMBER_DB = Path.home() / ".amber" / "memory.db"
GATEWAY_URL = "http://127.0.0.1:18789/v1/embeddings"
GATEWAY_TOKEN = "54e5217d7a30160d76201a99e7cc654107a4c88376a482b5"

def get_embedding(text: str) -> List[float]:
    """Get embedding from OpenClaw gateway."""
    response = requests.post(
        GATEWAY_URL,
        headers={
            "Authorization": f"Bearer {GATEWAY_TOKEN}",
            "Content-Type": "application/json"
        },
        json={
            "model": "text-embedding-3-small",
            "input": text
        },
        timeout=30
    )
    response.raise_for_status()
    data = response.json()
    return data["data"][0]["embedding"]

def reindex():
    """Reindex all contexts without embeddings."""
    db = sqlite3.connect(str(AMBER_DB))
    
    # Get contexts without embeddings
    cursor = db.execute("""
        SELECT id, uri, abstract, content 
        FROM contexts 
        WHERE embedding IS NULL
        ORDER BY created_at DESC
    """)
    
    rows = cursor.fetchall()
    total = len(rows)
    
    print(f"Found {total} contexts without embeddings")
    print("Starting reindex...")
    
    success = 0
    errors = 0
    
    for i, (ctx_id, uri, abstract, content) in enumerate(rows, 1):
        try:
            # Use abstract if available, otherwise content
            text = abstract if abstract else content
            if not text:
                print(f"[{i}/{total}] SKIP {uri} - no text")
                continue
            
            # Get embedding
            embedding = get_embedding(text)
            embedding_json = json.dumps(embedding)
            
            # Update database
            db.execute(
                "UPDATE contexts SET embedding = ? WHERE id = ?",
                (embedding_json, ctx_id)
            )
            db.commit()
            
            success += 1
            
            if i % 10 == 0:
                print(f"[{i}/{total}] Progress: {success} success, {errors} errors")
            
            # Rate limiting
            time.sleep(0.1)
            
        except Exception as e:
            errors += 1
            print(f"[{i}/{total}] ERROR {uri}: {e}")
            continue
    
    db.close()
    
    print("\n" + "="*50)
    print("Reindex complete")
    print(f"  Success: {success}")
    print(f"  Errors: {errors}")
    print(f"  Total: {total}")
    print("="*50)

if __name__ == "__main__":
    reindex()
