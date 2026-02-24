"""Daily journal processor — converts daily markdown journals into structured memories.

Reads memory/YYYY-MM-DD.md files and extracts structured memories from them.
Each journal entry becomes multiple memories across different dimensions.

This is a key data source for amber-memory: the daily journals that Amber writes
contain rich context about events, decisions, people, and thoughts.
"""

import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..core.context import Context, ContextType
from ..storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


class JournalProcessor:
    """Processes daily journal files into amber-memory entries."""

    def __init__(self, store: SQLiteStore, journal_dir: str = "memory"):
        self.store = store
        self.journal_dir = Path(journal_dir).expanduser()

    def scan_journals(self, since_days: int = 30) -> List[Path]:
        """Find journal files from the last N days."""
        if not self.journal_dir.exists():
            return []

        cutoff = datetime.now().timestamp() - since_days * 86400
        journals = []

        for f in sorted(self.journal_dir.glob("*.md")):
            # Match YYYY-MM-DD.md pattern
            match = re.match(r'(\d{4}-\d{2}-\d{2})\.md$', f.name)
            if match:
                try:
                    dt = datetime.strptime(match.group(1), "%Y-%m-%d")
                    if dt.timestamp() >= cutoff:
                        journals.append(f)
                except ValueError:
                    continue

        return journals

    def process_journal(self, journal_path: Path) -> int:
        """Process a single journal file into memories.

        Returns number of memories created.
        """
        if not journal_path.exists():
            return 0

        content = journal_path.read_text(encoding="utf-8")
        if len(content.strip()) < 20:
            return 0

        # Extract date from filename
        match = re.match(r'(\d{4}-\d{2}-\d{2})', journal_path.stem)
        if not match:
            return 0

        date_str = match.group(1)
        try:
            event_time = datetime.strptime(date_str, "%Y-%m-%d").timestamp()
        except ValueError:
            event_time = time.time()

        source_id = f"journal_{date_str}"

        # Check if already processed
        existing = self.store.get_source(source_id)
        if existing and existing.get("processed"):
            return 0

        # Store as source
        self.store.put_source(
            source_id=source_id,
            source_type="text",
            origin="diary",
            raw_content=content,
            file_path=str(journal_path),
            event_time=event_time,
        )

        # Parse sections and create memories
        sections = self._parse_journal_sections(content)
        count = 0

        for title, body in sections:
            if len(body.strip()) < 15:
                continue

            category = self._infer_category(title, body)
            abstract = self._make_abstract(title, body)
            overview = body[:300].strip()

            uri = f"/diary/{date_str}/{self._slugify(title or str(count))}"

            # Skip if already exists
            if self.store.get(uri):
                continue

            ctx = Context(
                uri=uri,
                parent_uri=f"/diary/{date_str}",
                abstract=abstract,
                overview=overview,
                content=body,
                context_type=ContextType.MEMORY,
                category=category,
                importance=self._estimate_importance(body, category),
                event_time=event_time,
                tags=["diary", date_str],
                meta={"source_id": source_id, "section_title": title},
            )
            self.store.put(ctx)
            count += 1

        # Mark source as processed
        uris = [f"/diary/{date_str}/{self._slugify(t or str(i))}"
                for i, (t, _) in enumerate(sections)]
        self.store.mark_source_processed(source_id, uris)

        logger.info(f"Processed journal {date_str}: {count} memories")
        return count

    def process_all(self, since_days: int = 30) -> int:
        """Process all recent journals."""
        journals = self.scan_journals(since_days)
        total = 0
        for j in journals:
            total += self.process_journal(j)
        return total

    def _parse_journal_sections(self, content: str) -> List[Tuple[str, str]]:
        """Parse journal markdown into sections."""
        sections = []
        current_title = ""
        current_body = []

        for line in content.split("\n"):
            # Match ## or ### headers
            header_match = re.match(r'^#{2,4}\s+(.+)$', line)
            if header_match:
                if current_body:
                    body_text = "\n".join(current_body).strip()
                    if body_text:
                        sections.append((current_title, body_text))
                current_title = header_match.group(1).strip()
                current_body = []
            elif line.startswith("# "):
                # Top-level header (date), skip
                continue
            elif line.strip().startswith("---"):
                # Separator
                if current_body:
                    body_text = "\n".join(current_body).strip()
                    if body_text:
                        sections.append((current_title, body_text))
                    current_body = []
                    current_title = ""
            else:
                current_body.append(line)

        if current_body:
            body_text = "\n".join(current_body).strip()
            if body_text:
                sections.append((current_title, body_text))

        # If no sections found, treat entire content as one section
        if not sections and content.strip():
            sections.append(("", content.strip()))

        return sections

    def _infer_category(self, title: str, body: str) -> str:
        """Infer memory category from section title and content."""
        text = f"{title} {body[:200]}".lower()

        # Title-based rules
        title_lower = title.lower() if title else ""
        title_rules = {
            "person": ["人物", "联系", "关系", "认识", "朋友", "同事"],
            "activity": ["事件", "做了", "完成", "发生", "进展", "开发", "修复", "部署"],
            "object": ["项目", "工具", "配置", "安装", "设置", "基础设施"],
            "preference": ["偏好", "喜欢", "习惯", "风格"],
            "taboo": ["禁忌", "不要", "敏感", "注意"],
            "goal": ["目标", "计划", "待办", "todo", "下一步"],
            "pattern": ["规律", "模式", "流程", "教训", "经验"],
            "thought": ["思考", "感悟", "随感", "想法", "反思", "日记"],
        }

        for cat, keywords in title_rules.items():
            if any(kw in title_lower for kw in keywords):
                return cat

        # Content-based rules
        content_rules = {
            "activity": ["今天", "昨天", "刚才", "完成了", "搞定了", "修了", "写了"],
            "goal": ["打算", "计划", "要做", "下一步", "目标是"],
            "thought": ["觉得", "感觉", "想到", "意识到", "反思"],
            "person": ["他说", "她说", "跟我说", "告诉我"],
            "pattern": ["每次", "总是", "规律", "发现了一个"],
        }

        for cat, keywords in content_rules.items():
            if any(kw in text for kw in keywords):
                return cat

        return "activity"  # Default for journal entries

    def _make_abstract(self, title: str, body: str) -> str:
        """Generate L0 abstract from section."""
        if title:
            return title[:50]
        # First meaningful line
        for line in body.split("\n"):
            line = line.strip().lstrip("- *>")
            if len(line) >= 5:
                return line[:50]
        return body[:50].replace("\n", " ")

    def _estimate_importance(self, text: str, category: str) -> float:
        """Estimate importance of a journal section."""
        base = {
            "taboo": 0.9, "goal": 0.7, "person": 0.6,
            "preference": 0.5, "pattern": 0.6, "activity": 0.4,
            "object": 0.4, "thought": 0.3,
        }.get(category, 0.4)

        # Boost for important markers
        markers = ["重要", "关键", "核心", "决定", "承诺", "教训", "注意", "bug", "修复"]
        if any(m in text for m in markers):
            base += 0.15

        # Boost for longer, more detailed content
        if len(text) > 500:
            base += 0.1
        elif len(text) > 200:
            base += 0.05

        return min(base, 1.0)

    def _slugify(self, text: str) -> str:
        """Convert text to URL-safe slug."""
        # Keep Chinese characters and alphanumeric
        slug = re.sub(r'[^\w\u4e00-\u9fff-]', '_', text.lower())
        slug = re.sub(r'_+', '_', slug).strip('_')
        return slug[:50] or "untitled"
