"""OpenClaw integration — auto-load memory context for new sessions.

Two integration modes:
1. Context injection: Generate a memory summary for session system prompt
2. Bridge CLI: The amber-memory-skill bridge.py for OpenClaw tool calls

This module handles mode 1: generating context strings that OpenClaw
can inject into new sessions automatically.
"""

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..client import AmberMemory
from ..core.context import Context

logger = logging.getLogger(__name__)


class OpenClawIntegration:
    """Generate memory context for OpenClaw sessions."""

    # Max tokens budget for context injection
    DEFAULT_MAX_CHARS = 3000
    # How many top memories to include
    DEFAULT_TOP_LIMIT = 15
    # How many recent memories to include
    DEFAULT_RECENT_LIMIT = 10

    def __init__(self, memory: AmberMemory):
        self.memory = memory

    def generate_session_context(self, max_chars: int = None,
                                  user: str = "",
                                  include_people: bool = True,
                                  include_taboos: bool = True,
                                  include_patterns: bool = False,
                                  include_proposals: bool = False,
                                  ) -> str:
        """Generate a memory context block for a new OpenClaw session.

        This is injected into the system prompt so the agent "remembers"
        key facts about the user without loading the full DB.

        Returns a markdown-formatted context string.
        """
        max_chars = max_chars or self.DEFAULT_MAX_CHARS
        sections = []

        # 1. Key facts about the user (top memories by importance * decay)
        top = self.memory.top(limit=self.DEFAULT_TOP_LIMIT)
        if top:
            lines = ["## 关键记忆"]
            for ctx, score in top:
                cat_emoji = {
                    "person": "👤", "preference": "❤️", "goal": "🎯",
                    "taboo": "🚫", "activity": "📅", "object": "📦",
                    "pattern": "🔄", "thought": "💭",
                }.get(ctx.category, "📝")
                lines.append(f"- {cat_emoji} {ctx.abstract}")
            sections.append("\n".join(lines))

        # 2. Recent memories (last 3 days)
        now = time.time()
        recent = self.memory.recall_by_time(
            now - 3 * 86400, now, limit=self.DEFAULT_RECENT_LIMIT)
        if recent:
            lines = ["## 最近发生的事"]
            for ctx in recent:
                t = datetime.fromtimestamp(ctx.event_time or ctx.created_at)
                day = t.strftime("%m-%d")
                lines.append(f"- [{day}] {ctx.abstract}")
            sections.append("\n".join(lines))

        # 3. People context
        if include_people:
            people = self.memory.people.list_people(limit=10)
            if people:
                lines = ["## 重要的人"]
                for p in people:
                    desc = f" — {p.description}" if p.description else ""
                    rel = f" ({p.relationship})" if p.relationship else ""
                    lines.append(f"- **{p.name}**{rel}{desc}")
                sections.append("\n".join(lines))

        # 4. Active taboos
        if include_taboos:
            taboos = self.memory.list_taboos()
            active = [t for t in taboos if t.get("active", True)]
            if active:
                lines = ["## ⚠️ 禁忌"]
                for t in active:
                    desc = f" — {t['description']}" if t.get("description") else ""
                    lines.append(f"- 🚫 {t['pattern']}{desc}")
                sections.append("\n".join(lines))

        # 5. Active patterns
        if include_patterns:
            patterns = self.memory.patterns.list_patterns(limit=5)
            if patterns:
                lines = ["## 行为模式"]
                for p in patterns:
                    lines.append(f"- {p.description}")
                sections.append("\n".join(lines))

        # 6. Active proposals
        if include_proposals:
            try:
                from ..session.life_proposals import LifeProposalEngine
                engine = LifeProposalEngine(
                    store=self.memory.store,
                    patterns=self.memory.patterns,
                )
                proposals = engine.list_proposals(limit=3)
                if proposals:
                    lines = ["## 💡 待处理提案"]
                    for p in proposals:
                        lines.append(f"- [{p.trigger_type}] {p.empathy} → {p.action}")
                    sections.append("\n".join(lines))
            except Exception:
                pass

        # Assemble and truncate
        full = "\n\n".join(sections)
        if len(full) > max_chars:
            full = full[:max_chars - 20] + "\n\n...(记忆已截断)"

        return full

    def generate_recall_context(self, query: str, limit: int = 8,
                                 max_chars: int = 2000) -> str:
        """Generate context for a specific query (on-demand recall).

        Used when the agent needs to answer a question about the user.
        """
        results = self.memory.recall(query, limit=limit)
        if not results:
            return f"没有找到关于「{query}」的记忆。"

        lines = [f"## 关于「{query}」的记忆\n"]
        for ctx, score in results:
            t = ""
            if ctx.event_time:
                t = datetime.fromtimestamp(ctx.event_time).strftime("[%Y-%m-%d] ")
            cat = f"[{ctx.category}] " if ctx.category else ""
            lines.append(f"- {t}{cat}{ctx.abstract}")
            if ctx.overview and ctx.overview != ctx.abstract:
                lines.append(f"  {ctx.overview[:150]}")

        # Check taboos
        taboos = self.memory.store.list_taboos(active_only=True)
        triggered = [t for t in taboos if t["pattern"] in query]
        if triggered:
            lines.append(f"\n⚠️ 注意：查询涉及禁忌话题「{'、'.join(t['pattern'] for t in triggered)}」")

        text = "\n".join(lines)
        return text[:max_chars] if len(text) > max_chars else text

    def generate_person_context(self, name: str, max_chars: int = 1500) -> str:
        """Generate context about a specific person.

        Used before meetings or when discussing someone.
        """
        person = self.memory.people.find_person(name)
        if not person:
            return f"没有关于「{name}」的记录。"

        lines = [f"## 关于 {name}\n"]
        if person.relationship:
            lines.append(f"关系: {person.relationship}")
        if person.description:
            lines.append(f"备注: {person.description}")
        if person.interaction_count > 0:
            lines.append(f"互动次数: {person.interaction_count}")
        if person.last_seen:
            last = datetime.fromtimestamp(person.last_seen).strftime("%Y-%m-%d")
            lines.append(f"最近互动: {last}")

        # Recent interactions
        interactions = self.memory.people.get_interactions(name, limit=5)
        if interactions:
            lines.append("\n最近互动:")
            for inter in interactions:
                t = datetime.fromtimestamp(inter["timestamp"]).strftime("%m-%d")
                lines.append(f"- [{t}] {inter['description']}")

        # Related memories
        results = self.memory.recall(name, limit=5)
        if results:
            lines.append("\n相关记忆:")
            for ctx, _ in results:
                lines.append(f"- {ctx.abstract}")

        # Taboo warnings
        taboos = self.memory.store.list_taboos(active_only=True)
        warnings = [t for t in taboos if name in t.get("description", "")]
        if warnings:
            lines.append(f"\n⚠️ 禁忌: {'、'.join(t['pattern'] for t in warnings)}")

        text = "\n".join(lines)
        return text[:max_chars] if len(text) > max_chars else text

    def export_session_summary(self, messages: List[Dict[str, str]],
                                session_id: str = "") -> Dict[str, Any]:
        """After a session ends, summarize what should be remembered.

        Returns a dict with memories to store and context updates.
        """
        # Count messages by role
        user_msgs = [m for m in messages if m.get("role") == "user"]
        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]

        return {
            "session_id": session_id,
            "message_count": len(messages),
            "user_messages": len(user_msgs),
            "assistant_messages": len(assistant_msgs),
            "timestamp": time.time(),
            "needs_compression": len(messages) > 10,
        }

    def to_system_prompt_block(self, max_chars: int = None) -> str:
        """Generate a block suitable for injection into system prompt.

        Wrapped with markers so OpenClaw can identify and update it.
        """
        context = self.generate_session_context(max_chars=max_chars)
        if not context:
            return ""
        return f"""<!-- amber-memory-context-start -->
{context}
<!-- amber-memory-context-end -->"""
