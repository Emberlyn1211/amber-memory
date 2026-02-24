#!/usr/bin/env python3
"""Migration tool - imports existing MEMORY.md and daily memory files into Amber Memory.

Usage:
    python3 -m amber_memory.migrate [--workspace /path/to/workspace] [--db /path/to/db]
    
This is non-destructive: original files are never modified or deleted.
"""

import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from amber_memory.core.context import Context, ContextType
from amber_memory.storage.sqlite_store import SQLiteStore
from amber_memory.client import AmberMemory


def parse_memory_md(filepath: str) -> List[Tuple[str, str, str, float]]:
    """Parse MEMORY.md into (section_title, content, category, importance) tuples."""
    with open(filepath, "r") as f:
        text = f.read()

    sections = []
    current_title = ""
    current_lines = []
    current_level = 0

    for line in text.split("\n"):
        # Detect headers
        header_match = re.match(r'^(#{1,4})\s+(.+)', line)
        if header_match:
            # Save previous section
            if current_title and current_lines:
                content = "\n".join(current_lines).strip()
                if content:
                    sections.append((current_title, content))
            current_title = header_match.group(2).strip()
            current_lines = []
            current_level = len(header_match.group(1))
        else:
            current_lines.append(line)

    # Last section
    if current_title and current_lines:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append((current_title, content))

    # Classify sections and assign importance
    results = []
    for title, content in sections:
        category, importance = classify_section(title, content)
        results.append((title, content, category, importance))

    return results


def classify_section(title: str, content: str) -> Tuple[str, float]:
    """Classify a memory section and assign importance."""
    title_lower = title.lower()

    # High importance
    if any(kw in title for kw in ["承诺", "关于 Frankie", "心结", "关于我"]):
        return "profile", 0.9
    if any(kw in title for kw in ["重要决定", "重要项目", "重要教训"]):
        return "events", 0.8
    if any(kw in title for kw in ["搞钱", "创业"]):
        return "events", 0.75
    if any(kw in title for kw in ["偏好", "审美"]):
        return "preferences", 0.7

    # Medium importance
    if any(kw in title for kw in ["基础设施", "安全", "工具", "定时任务"]):
        return "cases", 0.5
    if any(kw in title for kw in ["项目", "Watchlace", "EvoMap", "Twitter"]):
        return "entities", 0.6
    if any(kw in title for kw in ["思考", "连续性"]):
        return "patterns", 0.65

    # Lower importance
    if any(kw in title for kw in ["待办", "TODO"]):
        return "events", 0.4
    if any(kw in title for kw in ["读", "书"]):
        return "preferences", 0.5

    return "events", 0.5


def parse_daily_file(filepath: str) -> List[Tuple[str, str, float, float]]:
    """Parse a daily memory file into (title, content, importance, event_time) tuples."""
    with open(filepath, "r") as f:
        text = f.read()

    # Extract date from filename
    fname = Path(filepath).stem  # YYYY-MM-DD
    try:
        file_date = datetime.strptime(fname, "%Y-%m-%d")
        base_time = file_date.timestamp()
    except ValueError:
        base_time = time.time()

    sections = []
    current_title = ""
    current_lines = []

    for line in text.split("\n"):
        header_match = re.match(r'^(#{1,4})\s+(.+)', line)
        if header_match:
            if current_title and current_lines:
                content = "\n".join(current_lines).strip()
                if content and len(content) > 20:
                    sections.append((current_title, content, base_time))
            current_title = header_match.group(2).strip()
            current_lines = []
            # Try to extract time from title like "## 微信桥突破 (10:00-11:30)"
            time_match = re.search(r'(\d{1,2}):(\d{2})', current_title)
            if time_match:
                h, m = int(time_match.group(1)), int(time_match.group(2))
                base_time = file_date.replace(hour=h, minute=m).timestamp()
        else:
            current_lines.append(line)

    if current_title and current_lines:
        content = "\n".join(current_lines).strip()
        if content and len(content) > 20:
            sections.append((current_title, content, base_time))

    results = []
    for title, content, evt_time in sections:
        importance = 0.4  # daily entries default
        if any(kw in title for kw in ["突破", "成功", "完成", "重要"]):
            importance = 0.7
        if any(kw in title for kw in ["卡住", "失败", "教训"]):
            importance = 0.6
        results.append((title, content, importance, evt_time))

    return results


def migrate(workspace: str = None, db_path: str = None, dry_run: bool = False):
    """Run the migration."""
    workspace = workspace or os.path.expanduser("~/.openclaw/workspace")
    db_path = db_path or os.path.expanduser("~/.amber/memory.db")

    print(f"🧠 Amber Memory Migration")
    print(f"   Workspace: {workspace}")
    print(f"   Database:  {db_path}")
    if dry_run:
        print(f"   Mode: DRY RUN (no writes)")
    print()

    mem = AmberMemory(db_path=db_path)
    total = 0

    # 1. Import MEMORY.md
    memory_md = os.path.join(workspace, "MEMORY.md")
    if os.path.exists(memory_md):
        print(f"📄 Parsing MEMORY.md...")
        sections = parse_memory_md(memory_md)
        print(f"   Found {len(sections)} sections")
        for title, content, category, importance in sections:
            uri = f"/self/{category}/{title.replace(' ', '_').replace('/', '_')}"
            abstract = title
            overview = content[:150].replace("\n", " ")

            if not dry_run:
                ctx = Context(
                    uri=uri,
                    parent_uri=f"/self/{category}",
                    abstract=abstract,
                    overview=overview,
                    content=content,
                    context_type=ContextType.MEMORY,
                    category=category,
                    importance=importance,
                    tags=["memory_md", category],
                    meta={"source": "MEMORY.md", "section": title},
                )
                existing = mem.store.get(uri)
                if not existing:
                    mem.store.put(ctx)
                    total += 1
            print(f"   [{importance:.1f}] {category:12s} | {title[:50]}")
    else:
        print(f"   ⚠️ MEMORY.md not found")

    # 2. Import daily memory files
    memory_dir = os.path.join(workspace, "memory")
    if os.path.isdir(memory_dir):
        daily_files = sorted(Path(memory_dir).glob("202?-??-??.md"))
        print(f"\n📅 Found {len(daily_files)} daily memory files")
        for fpath in daily_files:
            date_str = fpath.stem
            sections = parse_daily_file(str(fpath))
            if not sections:
                continue
            print(f"   {date_str}: {len(sections)} sections")
            for title, content, importance, evt_time in sections:
                safe_title = title.replace(" ", "_").replace("/", "_")[:40]
                uri = f"/self/daily/{date_str}/{safe_title}"

                if not dry_run:
                    ctx = Context(
                        uri=uri,
                        parent_uri=f"/self/daily/{date_str}",
                        abstract=title,
                        overview=content[:150].replace("\n", " "),
                        content=content,
                        context_type=ContextType.EVENT,
                        category="daily",
                        importance=importance,
                        event_time=evt_time,
                        tags=["daily", date_str],
                        meta={"source": f"memory/{date_str}.md", "section": title},
                    )
                    existing = mem.store.get(uri)
                    if not existing:
                        mem.store.put(ctx)
                        total += 1
    else:
        print(f"   ⚠️ memory/ directory not found")

    # 3. Summary
    print(f"\n{'=' * 50}")
    if dry_run:
        print(f"🔍 DRY RUN: would import {total} memories")
    else:
        print(f"✅ Imported {total} new memories")
        stats = mem.stats()
        print(f"   Total in DB: {stats['total']}")
        print(f"   By type: {stats['by_type']}")
        print(f"   By source: {stats['by_source']}")
        print(f"   Database: {db_path}")

    mem.close()
    return total


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Migrate existing memories to Amber Memory")
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--db", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    migrate(workspace=args.workspace, db_path=args.db, dry_run=args.dry_run)
