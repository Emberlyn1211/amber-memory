"""MEMORY.md sync — bidirectional sync between amber-memory DB and MEMORY.md file.

Two directions:
1. Import: Parse MEMORY.md → ingest into amber-memory (migration)
2. Export: amber-memory DB → generate MEMORY.md (reverse sync)

The export generates a curated, human-readable MEMORY.md organized by dimension,
with the most important and recent memories surfaced first.
"""

import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..client import AmberMemory
from ..core.context import Context

logger = logging.getLogger(__name__)


class MemoryMdSync:
    """Bidirectional sync between amber-memory and MEMORY.md."""

    # Section headers in MEMORY.md mapped to our dimensions
    SECTION_MAP = {
        "关于我": "person",
        "关于 Frankie": "person",
        "About Me": "person",
        "人物": "person",
        "People": "person",
        "事件": "activity",
        "Events": "activity",
        "项目": "object",
        "Projects": "object",
        "重要项目": "object",
        "偏好": "preference",
        "Preferences": "preference",
        "审美偏好": "preference",
        "禁忌": "taboo",
        "心结": "taboo",
        "目标": "goal",
        "Goals": "goal",
        "搞钱计划": "goal",
        "待办事项": "goal",
        "模式": "pattern",
        "Patterns": "pattern",
        "工作流程规则": "pattern",
        "重要教训": "pattern",
        "思考": "thought",
        "我的思考": "thought",
        "Thoughts": "thought",
        "基础设施": "object",
        "Infrastructure": "object",
    }

    def __init__(self, memory: AmberMemory):
        self.memory = memory

    def import_from_md(self, md_path: str, source: str = "memory_md") -> int:
        """Parse MEMORY.md and import into amber-memory.

        Returns number of memories imported.
        """
        path = Path(md_path).expanduser()
        if not path.exists():
            logger.warning(f"MEMORY.md not found: {path}")
            return 0

        content = path.read_text(encoding="utf-8")
        sections = self._parse_sections(content)
        count = 0

        for title, body in sections:
            category = self._title_to_category(title)
            paragraphs = self._split_paragraphs(body)

            for para in paragraphs:
                if len(para.strip()) < 10:
                    continue

                # Check if already imported (by content similarity)
                existing = self.memory.recall(para[:30], limit=3)
                if any(self._is_duplicate(para, ctx.content) for ctx, _ in existing):
                    continue

                self.memory.remember(
                    content=para,
                    source=source,
                    category=category,
                    importance=self._estimate_importance(para, category),
                )
                count += 1

        logger.info(f"Imported {count} memories from {md_path}")
        return count

    def export_to_md(self, md_path: str, limit: int = 80,
                     include_people: bool = True,
                     include_patterns: bool = True) -> str:
        """Export amber-memory DB to MEMORY.md format.

        Returns the generated markdown content.
        """
        lines = []
        lines.append("# MEMORY.md — Amber 的长期记忆\n")
        lines.append(f"*自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")

        # Get top memories grouped by category
        results = self.memory.top(limit=limit)
        by_cat: Dict[str, List[Tuple[Context, float]]] = {}
        for ctx, score in results:
            cat = ctx.category or "memory"
            by_cat.setdefault(cat, []).append((ctx, score))

        # Render each dimension
        dim_config = [
            ("person", "关于身边的人", "👤"),
            ("goal", "目标与计划", "🎯"),
            ("preference", "偏好与习惯", "❤️"),
            ("activity", "重要事件", "📅"),
            ("object", "项目与物品", "📦"),
            ("pattern", "规律与模式", "🔄"),
            ("thought", "思考与感悟", "💭"),
            ("taboo", "禁忌", "🚫"),
        ]

        for cat, title, emoji in dim_config:
            items = by_cat.get(cat, [])
            if not items:
                continue

            lines.append(f"\n## {emoji} {title}\n")
            for ctx, score in items:
                # Use abstract as bullet point
                lines.append(f"- **{ctx.abstract}**")
                # Add overview as sub-content
                if ctx.overview:
                    for line in ctx.overview.split("\n"):
                        line = line.strip()
                        if line and line != ctx.abstract:
                            lines.append(f"  {line}")
                # Add key content details (truncated)
                if ctx.content and ctx.content != ctx.overview:
                    content_preview = ctx.content[:200].replace("\n", " ").strip()
                    if content_preview and content_preview != ctx.abstract:
                        lines.append(f"  > {content_preview}")
                lines.append("")

        # Uncategorized
        other = by_cat.get("memory", [])
        if other:
            lines.append("\n## 📝 其他记忆\n")
            for ctx, score in other:
                lines.append(f"- {ctx.abstract}")
            lines.append("")

        # People graph
        if include_people:
            people = self.memory.people.list_people(limit=30)
            if people:
                lines.append("\n## 👥 人际关系\n")
                for p in people:
                    parts = [f"**{p.name}**"]
                    if p.relationship:
                        parts.append(f"({p.relationship})")
                    if p.description:
                        parts.append(f"— {p.description}")
                    if p.interaction_count > 0:
                        parts.append(f"[{p.interaction_count}次互动]")
                    lines.append(f"- {' '.join(parts)}")
                lines.append("")

        # Patterns
        if include_patterns:
            patterns = self.memory.patterns.list_patterns(limit=10)
            if patterns:
                lines.append("\n## 🔍 发现的模式\n")
                for p in patterns:
                    conf = f" (置信度 {p.confidence:.0%})" if p.confidence > 0 else ""
                    lines.append(f"- [{p.pattern_type}] {p.description}{conf}")
                lines.append("")

        # Stats footer
        stats = self.memory.stats()
        lines.append("\n---\n")
        lines.append(f"*总记忆数: {stats.get('total', 0)} | ")
        lines.append(f"衰减半衰期: {stats.get('decay_half_life_days', 14)} 天 | ")
        lines.append(f"数据库: {stats.get('db_path', 'unknown')}*\n")

        md_content = "\n".join(lines)

        # Write to file
        path = Path(md_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(md_content, encoding="utf-8")
        logger.info(f"Exported {len(results)} memories to {md_path}")

        return md_content

    def _parse_sections(self, content: str) -> List[Tuple[str, str]]:
        """Parse markdown into (title, body) sections."""
        sections = []
        current_title = ""
        current_body = []

        for line in content.split("\n"):
            if line.startswith("## "):
                if current_title or current_body:
                    sections.append((current_title, "\n".join(current_body)))
                current_title = line[3:].strip()
                # Remove emoji prefixes
                current_title = re.sub(r'^[^\w\u4e00-\u9fff]+', '', current_title).strip()
                current_body = []
            elif line.startswith("# "):
                # Top-level header, skip
                continue
            else:
                current_body.append(line)

        if current_title or current_body:
            sections.append((current_title, "\n".join(current_body)))

        return sections

    def _title_to_category(self, title: str) -> str:
        """Map section title to dimension category."""
        for key, cat in self.SECTION_MAP.items():
            if key in title:
                return cat
        return "memory"

    def _split_paragraphs(self, text: str) -> List[str]:
        """Split text into meaningful paragraphs."""
        paragraphs = []
        current = []

        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                if current:
                    paragraphs.append("\n".join(current))
                    current = []
            elif stripped.startswith("- ") or stripped.startswith("* "):
                if current:
                    paragraphs.append("\n".join(current))
                    current = []
                # Bullet point as its own paragraph
                paragraphs.append(stripped[2:])
            elif stripped.startswith("**") and stripped.endswith("**"):
                # Bold line as its own paragraph
                paragraphs.append(stripped.strip("*").strip())
            else:
                current.append(stripped)

        if current:
            paragraphs.append("\n".join(current))

        return [p for p in paragraphs if len(p.strip()) >= 10]

    def _is_duplicate(self, new_text: str, existing_text: str) -> bool:
        """Check if two texts are substantially the same."""
        if not new_text or not existing_text:
            return False
        # Simple character overlap check
        new_chars = set(new_text[:100])
        existing_chars = set(existing_text[:100])
        overlap = len(new_chars & existing_chars) / max(len(new_chars | existing_chars), 1)
        return overlap > 0.7

    def _estimate_importance(self, text: str, category: str) -> float:
        """Heuristic importance estimation."""
        base = {
            "taboo": 0.9, "goal": 0.7, "person": 0.6,
            "preference": 0.5, "pattern": 0.5, "activity": 0.4,
            "object": 0.4, "thought": 0.3, "memory": 0.3,
        }.get(category, 0.4)

        # Boost for longer, more detailed content
        if len(text) > 200:
            base += 0.1
        # Boost for content with specific markers
        if any(kw in text for kw in ["重要", "关键", "核心", "承诺", "决定"]):
            base += 0.1

        return min(base, 1.0)
