#!/usr/bin/env python3
"""Reindex script — generate embeddings for all memories using 豆包 ARK API.

Usage:
    python3 -m amber_memory.scripts.reindex [--db PATH] [--batch 20] [--dry-run]

This uses the 豆包 embedding API (free quota), not Opus.
"""

import argparse
import asyncio
import os
import sys
import time

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from amber_memory.storage.sqlite_store import SQLiteStore
from amber_memory.models.embedder.ark_embedder import ArkEmbedder
from amber_memory.retrieve.retriever import Retriever, pack_vector, ALL_DIMENSIONS


async def reindex(db_path: str, batch_size: int = 20, dry_run: bool = False):
    """Reindex all memories that don't have embeddings yet."""
    store = SQLiteStore(db_path)
    
    # Check total memories
    total = store.count()
    print(f"📊 数据库: {db_path}")
    print(f"📊 总记忆数: {total}")
    
    # Count existing embeddings
    existing = store.conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    print(f"📊 已有 embedding: {existing}")
    print(f"📊 需要生成: {total - existing}")
    
    if dry_run:
        print("\n🔍 Dry run — 不会实际调用 API")
        # List what would be indexed
        for dim in ALL_DIMENSIONS:
            contexts = store.search_by_category(dim, limit=5000)
            need_index = [c for c in contexts if not store.get_embedding(c.uri)]
            if need_index:
                print(f"  [{dim}] {len(need_index)} 条待索引")
                for c in need_index[:3]:
                    print(f"    - {c.abstract[:50]}")
                if len(need_index) > 3:
                    print(f"    ... 还有 {len(need_index) - 3} 条")
        store.close()
        return

    # Initialize embedder
    api_key = os.environ.get("ARK_API_KEY")
    if not api_key:
        # Try loading from .env files
        for env_path in [
            os.path.expanduser("~/.openclaw/workspace/watchlace-dev/backend/.env"),
            os.path.expanduser("~/.amber/.env"),
            ".env",
        ]:
            if os.path.exists(env_path):
                with open(env_path) as f:
                    for line in f:
                        if line.startswith("ARK_API_KEY="):
                            api_key = line.split("=", 1)[1].strip().strip('"')
                            break
            if api_key:
                break

    if not api_key:
        print("❌ 找不到 ARK_API_KEY，请设置环境变量或在 .env 文件中配置")
        store.close()
        return

    embedder = ArkEmbedder(api_key=api_key)
    
    async def embed_fn(texts):
        result = await embedder.embed(texts)
        return [r.vector for r in result]

    retriever = Retriever(store=store, embed_fn=embed_fn)

    print(f"\n🚀 开始 reindex (batch_size={batch_size})...")
    start = time.time()
    
    indexed = 0
    errors = 0
    
    for dim in ALL_DIMENSIONS:
        contexts = store.search_by_category(dim, limit=5000)
        need_index = [c for c in contexts if not store.get_embedding(c.uri)]
        
        if not need_index:
            continue
            
        print(f"\n📂 [{dim}] {len(need_index)} 条待索引")
        
        batch_texts = []
        batch_ctxs = []
        
        for ctx in need_index:
            text = ctx.overview or ctx.abstract or (ctx.content or "")[:200]
            if not text or len(text.strip()) < 5:
                continue
            
            batch_texts.append(text)
            batch_ctxs.append(ctx)
            
            if len(batch_texts) >= batch_size:
                try:
                    embeddings = await embed_fn(batch_texts)
                    for c, emb in zip(batch_ctxs, embeddings):
                        store.put_embedding(c.uri, pack_vector(emb), model="ark")
                        indexed += 1
                    print(f"  ✅ {indexed} 条已索引", end="\r")
                except Exception as e:
                    errors += 1
                    print(f"  ❌ batch 失败: {e}")
                    # Rate limit backoff
                    await asyncio.sleep(2)
                
                batch_texts = []
                batch_ctxs = []
                # Small delay to respect rate limits
                await asyncio.sleep(0.5)
        
        # Final batch
        if batch_texts:
            try:
                embeddings = await embed_fn(batch_texts)
                for c, emb in zip(batch_ctxs, embeddings):
                    store.put_embedding(c.uri, pack_vector(emb), model="ark")
                    indexed += 1
            except Exception as e:
                errors += 1
                print(f"  ❌ final batch 失败: {e}")
    
    elapsed = time.time() - start
    print(f"\n\n✅ Reindex 完成!")
    print(f"📊 新增 embedding: {indexed}")
    print(f"📊 错误: {errors}")
    print(f"📊 耗时: {elapsed:.1f}s")
    print(f"📊 总 embedding: {existing + indexed}")
    
    store.close()


def main():
    parser = argparse.ArgumentParser(description="Amber Memory embedding reindex")
    parser.add_argument("--db", default=os.path.expanduser("~/.amber/memory.db"),
                        help="数据库路径")
    parser.add_argument("--batch", type=int, default=20, help="批量大小")
    parser.add_argument("--dry-run", action="store_true", help="只统计不执行")
    args = parser.parse_args()
    
    asyncio.get_event_loop().run_until_complete(
        reindex(args.db, args.batch, args.dry_run)
    )


if __name__ == "__main__":
    main()
