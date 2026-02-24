"""Amber Memory CLI — command-line interface for the memory system.

Usage:
    amber-memory remember "some text" --source telegram --importance 0.8
    amber-memory recall "query text" --limit 10
    amber-memory stats
    amber-memory people --list
    amber-memory patterns --detect
    amber-memory export-md
    amber-memory ingest-bear --tag "随感/Amber"
    amber-memory reindex
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


def get_memory(with_llm: bool = False, with_embed: bool = False):
    """Initialize AmberMemory with optional LLM and embedder."""
    from .client import AmberMemory
    db_path = os.environ.get("AMBER_MEMORY_DB", "~/.amber/memory.db")
    llm_fn = None
    embed_fn = None

    api_key = os.environ.get("ARK_API_KEY", "")
    if with_llm and api_key:
        from .models.ark_llm import ArkLLM
        llm = ArkLLM(api_key=api_key)
        llm_fn = llm.chat

    if with_embed and api_key:
        from .models.embedder.ark_embedder import ArkEmbedder
        embedder = ArkEmbedder(api_key=api_key)
        embed_fn = lambda texts: asyncio.get_event_loop().run_until_complete(
            _batch_embed(embedder, texts)
        )

    return AmberMemory(db_path, llm_fn=llm_fn, embed_fn=embed_fn)


async def _batch_embed(embedder, texts):
    """Wrapper to make sync embedder work with async interface."""
    results = embedder.embed_batch(texts)
    return [r.dense_vector for r in results]


def cmd_remember(args):
    """Store a memory."""
    mem = get_memory()
    ctx = mem.remember(
        args.text, source=args.source,
        importance=args.importance, category=args.category,
    )
    print(f"✅ Stored: [{ctx.category}] {ctx.abstract}")
    print(f"   URI: {ctx.uri}")
    mem.close()


def cmd_recall(args):
    """Search memories."""
    mem = get_memory()
    results = mem.recall(args.query, limit=args.limit)
    if not results:
        print("No memories found.")
    else:
        print(f"Found {len(results)} memories:\n")
        for i, (ctx, score) in enumerate(results, 1):
            print(f"  {i}. [{ctx.category}] {ctx.abstract}")
            print(f"     score={score:.3f} | uri={ctx.uri}")
            if args.full and ctx.content:
                content = ctx.content[:200].replace('\n', ' ')
                print(f"     {content}")
            print()
    mem.close()


def cmd_compress(args):
    """Compress messages file into long-term memory."""
    mem = get_memory(with_llm=True)
    if not mem.llm_fn:
        print("❌ ARK_API_KEY not set. Cannot compress without LLM.")
        return

    messages = json.loads(Path(args.messages).read_text())
    print(f"Compressing {len(messages)} messages...")

    async def run():
        return await mem.compress_session(
            messages=messages, user=args.user, session_id=args.session or "",
        )

    memories = asyncio.run(run())
    print(f"\n✅ Extracted {len(memories)} memories:")
    for ctx in memories:
        print(f"  [{ctx.category}] {ctx.abstract}")
    mem.close()


def cmd_context(args):
    """Get top memories for context injection."""
    mem = get_memory()
    results = mem.top(limit=args.limit)
    for ctx, score in results:
        line = f"[{ctx.category}] {ctx.abstract}"
        if args.scores:
            line += f" (score={score:.3f})"
        print(line)
    mem.close()


def cmd_people(args):
    """Manage people graph."""
    mem = get_memory()
    if args.find:
        person = mem.people.find_person(args.find)
        if person:
            d = person.to_dict()
            print(f"👤 {d['name']}")
            print(f"   Relationship: {d['relationship'] or 'unknown'}")
            print(f"   Description: {d['description'] or 'none'}")
            print(f"   Interactions: {d['interaction_count']}")
            print(f"   Last seen: {datetime.fromtimestamp(d['last_seen']).strftime('%Y-%m-%d %H:%M') if d['last_seen'] else 'never'}")
            if d['aliases']:
                print(f"   Aliases: {', '.join(d['aliases'])}")
        else:
            print(f"Person '{args.find}' not found.")
    elif args.add:
        person = mem.people.add_person(
            args.add, relationship=args.relationship or "",
            description=args.description or "",
        )
        print(f"✅ Added: {person.name} (id={person.id})")
    else:
        people = mem.people.list_people(limit=args.limit)
        if not people:
            print("No people in graph yet.")
        else:
            print(f"👥 {len(people)} people:\n")
            for p in people:
                rel = f" ({p.relationship})" if p.relationship else ""
                count = f" [{p.interaction_count} interactions]" if p.interaction_count else ""
                print(f"  • {p.name}{rel}{count}")
    mem.close()


def cmd_patterns(args):
    """Detect or list patterns."""
    mem = get_memory()
    if args.detect:
        print(f"Detecting patterns from last {args.days} days...")
        patterns = mem.patterns.detect_all(days=args.days)
        if not patterns:
            print("No patterns detected.")
        else:
            print(f"\n🔍 Found {len(patterns)} patterns:\n")
            for p in patterns:
                print(f"  [{p.pattern_type}] {p.description}")
                print(f"    confidence={p.confidence:.2f} frequency={p.frequency}")
    else:
        patterns = mem.patterns.list_patterns(limit=args.limit)
        if not patterns:
            print("No saved patterns.")
        else:
            for p in patterns:
                print(f"  [{p.pattern_type}] {p.description} (conf={p.confidence:.2f})")
    mem.close()


def cmd_stats(args):
    """Show memory system statistics."""
    mem = get_memory()
    stats = mem.stats()
    people_stats = mem.people.stats()
    pattern_stats = mem.patterns.stats()

    print("📊 Amber Memory Stats\n")
    print(f"  Memories:      {stats.get('total', 0)}")
    print(f"  By type:       {stats.get('by_type', {})}")
    print(f"  People:        {people_stats.get('people', 0)}")
    print(f"  Relationships: {people_stats.get('relationships', 0)}")
    print(f"  Interactions:  {people_stats.get('interactions', 0)}")
    print(f"  Patterns:      {pattern_stats.get('patterns', 0)}")
    print(f"  Database:      {stats.get('db_path', 'unknown')}")
    print(f"  Decay:         {stats.get('decay_half_life_days', 14)} day half-life")
    print(f"  LLM:           {'✅' if stats.get('has_llm') else '❌'}")
    print(f"  Embeddings:    {'✅' if stats.get('has_embeddings') else '❌'}")
    mem.close()


def cmd_ingest_bear(args):
    """Ingest Bear Notes."""
    mem = get_memory()
    print(f"Ingesting Bear Notes{' (tag: ' + args.tag + ')' if args.tag else ''}...")
    count = mem.ingest_bear(tag=args.tag, limit=args.limit)
    print(f"✅ Imported {count} notes")
    mem.close()


def cmd_ingest_wechat(args):
    """Ingest WeChat messages."""
    mem = get_memory()
    print("Ingesting WeChat data...")
    count = mem.ingest_wechat(limit=args.limit)
    print(f"✅ Imported {count} items")
    mem.close()


def cmd_reindex(args):
    """Reindex all memories for vector search."""
    mem = get_memory(with_embed=True)
    if not mem.embed_fn:
        print("❌ ARK_API_KEY not set. Cannot reindex without embedder.")
        return

    print("Reindexing all memories...")

    async def run():
        return await mem.retriever.reindex_all(batch_size=args.batch_size)

    count = asyncio.run(run())
    print(f"✅ Indexed {count} memories")
    mem.close()


def cmd_export_md(args):
    """Export memories as Markdown."""
    mem = get_memory()
    results = mem.top(limit=args.limit)

    print("# Amber Memory Export\n")
    print(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")

    by_cat = {}
    for ctx, score in results:
        cat = ctx.category or "other"
        by_cat.setdefault(cat, []).append((ctx, score))

    cat_names = {
        "person": "👤 人物", "activity": "📅 事件", "object": "📦 项目/物品",
        "preference": "❤️ 偏好", "taboo": "🚫 禁忌", "goal": "🎯 目标",
        "pattern": "🔄 模式", "thought": "💭 思考", "memory": "📝 记忆",
    }

    for cat in ["person", "goal", "preference", "activity", "object",
                "pattern", "thought", "taboo", "memory"]:
        items = by_cat.get(cat, [])
        if not items:
            continue
        print(f"\n## {cat_names.get(cat, cat)}\n")
        for ctx, score in items:
            print(f"- **{ctx.abstract}**")
            if ctx.overview:
                for line in ctx.overview.split("\n")[:3]:
                    if line.strip():
                        print(f"  {line.strip()}")

    people = mem.people.list_people(limit=30)
    if people:
        print("\n## 👥 人际关系\n")
        for p in people:
            desc = f" — {p.description}" if p.description else ""
            rel = f" ({p.relationship})" if p.relationship else ""
            print(f"- **{p.name}**{rel}{desc}")

    mem.close()


def cmd_forget(args):
    """Delete a memory by URI."""
    mem = get_memory()
    if mem.forget(args.uri):
        print(f"✅ Forgotten: {args.uri}")
    else:
        print(f"❌ Not found: {args.uri}")
    mem.close()


def cmd_taboo(args):
    """Manage taboos."""
    mem = get_memory()
    if args.add:
        tid = mem.add_taboo(args.add, description=args.description or "")
        print(f"✅ Added taboo: {args.add} (id={tid})")
    elif args.remove:
        if mem.remove_taboo(args.remove):
            print(f"✅ Removed taboo: {args.remove}")
        else:
            print(f"❌ Taboo not found: {args.remove}")
    else:
        taboos = mem.list_taboos()
        if not taboos:
            print("No taboos configured.")
        else:
            print(f"🚫 {len(taboos)} taboos:\n")
            for t in taboos:
                print(f"  • [{t.get('id', '?')}] {t.get('pattern', '')} — {t.get('description', '')}")
    mem.close()


def main():
    parser = argparse.ArgumentParser(
        description="Amber Memory — 8-dimension memory system for AI agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  amber-memory remember "Frankie likes Talisker Storm" --source telegram
  amber-memory recall "what does Frankie like" --limit 5
  amber-memory people --find "老王"
  amber-memory patterns --detect --days 30
  amber-memory stats
  amber-memory export-md > memories.md
        """,
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # remember
    p = sub.add_parser("remember", help="Store a memory")
    p.add_argument("text", help="Memory content")
    p.add_argument("--source", default="manual", help="Source (default: manual)")
    p.add_argument("--importance", type=float, default=0.5, help="Importance 0-1")
    p.add_argument("--category", default="memory", help="Category (person/activity/object/preference/taboo/goal/pattern/thought)")

    # recall
    p = sub.add_parser("recall", help="Search memories")
    p.add_argument("query", help="Search query")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--full", action="store_true", help="Show full content")

    # compress
    p = sub.add_parser("compress", help="Compress messages into memories")
    p.add_argument("--messages", required=True, help="JSON file with messages")
    p.add_argument("--user", default="", help="User name")
    p.add_argument("--session", default="", help="Session ID")

    # context
    p = sub.add_parser("context", help="Get top memories for context")
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--scores", action="store_true")

    # people
    p = sub.add_parser("people", help="Manage people graph")
    p.add_argument("--find", default="", help="Find person by name")
    p.add_argument("--add", default="", help="Add new person")
    p.add_argument("--relationship", default="", help="Relationship type")
    p.add_argument("--description", default="", help="Description")
    p.add_argument("--limit", type=int, default=20)

    # patterns
    p = sub.add_parser("patterns", help="Detect or list patterns")
    p.add_argument("--detect", action="store_true", help="Run detection")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--limit", type=int, default=20)

    # stats
    sub.add_parser("stats", help="Show statistics")

    # ingest-bear
    p = sub.add_parser("ingest-bear", help="Import Bear Notes")
    p.add_argument("--tag", default=None, help="Filter by tag")
    p.add_argument("--limit", type=int, default=500)

    # ingest-wechat
    p = sub.add_parser("ingest-wechat", help="Import WeChat data")
    p.add_argument("--limit", type=int, default=100)

    # reindex
    p = sub.add_parser("reindex", help="Reindex for vector search")
    p.add_argument("--batch-size", type=int, default=20)

    # export-md
    p = sub.add_parser("export-md", help="Export as Markdown")
    p.add_argument("--limit", type=int, default=50)

    # forget
    p = sub.add_parser("forget", help="Delete a memory")
    p.add_argument("uri", help="Memory URI to delete")

    # taboo
    p = sub.add_parser("taboo", help="Manage taboos")
    p.add_argument("--add", default="", help="Add taboo pattern")
    p.add_argument("--remove", default="", help="Remove taboo by ID")
    p.add_argument("--description", default="", help="Taboo description")

    args = parser.parse_args()
    commands = {
        "remember": cmd_remember, "recall": cmd_recall,
        "compress": cmd_compress, "context": cmd_context,
        "people": cmd_people, "patterns": cmd_patterns,
        "stats": cmd_stats, "ingest-bear": cmd_ingest_bear,
        "ingest-wechat": cmd_ingest_wechat, "reindex": cmd_reindex,
        "export-md": cmd_export_md, "forget": cmd_forget,
        "taboo": cmd_taboo,
    }
    fn = commands.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
