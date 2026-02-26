"""Life Proposals — proactive suggestions based on memory patterns.

The "生活提案" system: instead of waiting for queries, proactively suggest
actions based on detected patterns, upcoming events, and contextual signals.

A proposal has 4 parts:
1. 共情 (Empathy) — acknowledge the situation
2. 证据 (Evidence) — cite specific memories/patterns
3. 行动 (Action) — concrete suggestion
4. 确认 (Confirm) — ask before acting

Triggers:
- Time-based: recurring patterns (e.g., "每周四开完周会情绪下降")
- Context-based: current situation matches a known pattern
- Decay-based: important memories about to fade
- Social-based: upcoming interaction with someone (prep context)
- Anomaly-based: deviation from normal patterns
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

from ..core.context import Context, DecayParams, DEFAULT_DECAY
from ..storage.sqlite_store import SQLiteStore
from ..graph.patterns import PatternDetector, Pattern

logger = logging.getLogger(__name__)


@dataclass
class Proposal:
    """A proactive life suggestion."""
    id: str
    trigger_type: str       # time|context|decay|social|anomaly
    empathy: str            # 共情：acknowledge the situation
    evidence: List[str]     # 证据：memory URIs or pattern IDs
    evidence_text: str      # Human-readable evidence summary
    action: str             # 行动：concrete suggestion
    confidence: float       # 0-1
    priority: int           # 1-5 (1=highest)
    created_at: float = 0.0
    dismissed: bool = False
    acted_on: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_message(self) -> str:
        """Format as a natural message."""
        parts = []
        if self.empathy:
            parts.append(self.empathy)
        if self.evidence_text:
            parts.append(f"（{self.evidence_text}）")
        if self.action:
            parts.append(self.action)
        return "\n".join(parts)

    def to_dict(self) -> Dict:
        return {
            "id": self.id, "trigger_type": self.trigger_type,
            "empathy": self.empathy, "evidence": self.evidence,
            "evidence_text": self.evidence_text, "action": self.action,
            "confidence": self.confidence, "priority": self.priority,
            "created_at": self.created_at, "dismissed": self.dismissed,
            "acted_on": self.acted_on, "meta": self.meta,
        }


class LifeProposalEngine:
    """Generate proactive life suggestions from memory + patterns."""

    PROPOSALS_TABLE = """CREATE TABLE IF NOT EXISTS proposals (
        id TEXT PRIMARY KEY,
        trigger_type TEXT NOT NULL,
        empathy TEXT DEFAULT '',
        evidence TEXT DEFAULT '[]',
        evidence_text TEXT DEFAULT '',
        action TEXT DEFAULT '',
        confidence REAL DEFAULT 0.5,
        priority INTEGER DEFAULT 3,
        created_at REAL DEFAULT 0,
        dismissed INTEGER DEFAULT 0,
        acted_on INTEGER DEFAULT 0,
        meta TEXT DEFAULT '{}'
    )"""

    def __init__(self, store: SQLiteStore, patterns: PatternDetector,
                 llm_fn: Optional[Callable] = None,
                 decay_params: DecayParams = DEFAULT_DECAY):
        self.store = store
        self.patterns = patterns
        self.llm_fn = llm_fn
        self.decay_params = decay_params
        self._init_table()

    def _init_table(self):
        self.store.conn.execute(self.PROPOSALS_TABLE)
        self.store.conn.commit()

    # --- Trigger: Fading Memories ---

    def check_fading_memories(self, threshold: float = 0.15,
                              min_importance: float = 0.6,
                              limit: int = 5) -> List[Proposal]:
        """Find important memories about to fade and suggest reinforcement."""
        fading = self.store.get_decayed(threshold, self.decay_params)
        proposals = []

        for ctx in fading[:limit]:
            if ctx.importance < min_importance:
                continue
            # Skip if we already proposed about this recently
            if self._recently_proposed("decay", ctx.uri, hours=72):
                continue

            cat_label = {
                "person": "关于一个人", "goal": "一个目标",
                "preference": "一个偏好", "taboo": "一个禁忌",
                "activity": "一件事", "thought": "一个想法",
            }.get(ctx.category, "一条记忆")

            proposal = Proposal(
                id=f"fp_{uuid4().hex[:8]}",
                trigger_type="decay",
                empathy=f"有{cat_label}快要被遗忘了",
                evidence=[ctx.uri],
                evidence_text=ctx.abstract,
                action=f"要不要回顾一下？「{ctx.abstract}」",
                confidence=0.7,
                priority=3,
                created_at=time.time(),
                meta={"fading_uri": ctx.uri, "current_score": ctx.compute_score(self.decay_params)},
            )
            proposals.append(proposal)

        return proposals

    # --- Trigger: Social Prep ---

    def check_social_prep(self, person_name: str) -> Optional[Proposal]:
        """Before meeting someone, prep relevant context."""
        # Search for memories about this person
        results = self.store.search_text(person_name, limit=10)
        if not results:
            return None

        # Find recent interactions
        recent = [ctx for ctx in results
                  if ctx.event_time and time.time() - ctx.event_time < 30 * 86400]
        older = [ctx for ctx in results
                 if not ctx.event_time or time.time() - ctx.event_time >= 30 * 86400]

        evidence_parts = []
        if recent:
            evidence_parts.append(f"最近：{recent[0].abstract}")
        if older:
            evidence_parts.append(f"之前：{older[0].abstract}")

        # Check taboos related to this person
        taboos = self.store.list_taboos(active_only=True)
        taboo_warnings = [t for t in taboos
                          if person_name in t.get("description", "")]

        action_parts = []
        if evidence_parts:
            action_parts.append("上次聊的：" + "；".join(evidence_parts))
        if taboo_warnings:
            action_parts.append("⚠️ 注意别提：" + "、".join(
                t["pattern"] for t in taboo_warnings))

        if not action_parts:
            return None

        return Proposal(
            id=f"sp_{uuid4().hex[:8]}",
            trigger_type="social",
            empathy=f"你要见 {person_name}",
            evidence=[ctx.uri for ctx in results[:5]],
            evidence_text=f"找到 {len(results)} 条相关记忆",
            action="\n".join(action_parts),
            confidence=0.8,
            priority=2,
            created_at=time.time(),
            meta={"person": person_name, "taboo_count": len(taboo_warnings)},
        )

    # --- Trigger: Pattern-based ---

    def check_pattern_triggers(self) -> List[Proposal]:
        """Check if current time/context matches known patterns."""
        now = datetime.now()
        hour = now.hour
        weekday = now.weekday()
        proposals = []

        saved_patterns = self.patterns.list_patterns(limit=20)
        for pattern in saved_patterns:
            if pattern.confidence < 0.5:
                continue
            if self._recently_proposed("pattern", pattern.id, hours=24):
                continue

            # Time pattern: check if current hour/day matches
            if pattern.pattern_type == "time":
                meta = pattern.meta or {}
                if "hour" in meta and abs(meta["hour"] - hour) <= 1:
                    proposals.append(Proposal(
                        id=f"pp_{uuid4().hex[:8]}",
                        trigger_type="time",
                        empathy=f"现在是 {hour}:00",
                        evidence=[],
                        evidence_text=pattern.description,
                        action=f"根据你的习惯，这个时间通常会{pattern.description}",
                        confidence=pattern.confidence,
                        priority=4,
                        created_at=time.time(),
                        meta={"pattern_id": pattern.id},
                    ))

        return proposals

    # --- Trigger: Anomaly ---

    def check_anomalies(self, days: int = 7) -> List[Proposal]:
        """Detect deviations from normal patterns."""
        now = time.time()
        recent = self.store.search_by_time_range(now - days * 86400, now, limit=200)
        older = self.store.search_by_time_range(
            now - (days * 3) * 86400, now - days * 86400, limit=200)

        if len(recent) < 3 or len(older) < 3:
            return []

        # Compare category distributions
        from collections import Counter
        recent_cats = Counter(ctx.category for ctx in recent if ctx.category)
        older_cats = Counter(ctx.category for ctx in older if ctx.category)

        proposals = []
        # Normalize
        recent_total = sum(recent_cats.values()) or 1
        older_total = sum(older_cats.values()) or 1

        for cat in set(list(recent_cats.keys()) + list(older_cats.keys())):
            recent_ratio = recent_cats.get(cat, 0) / recent_total
            older_ratio = older_cats.get(cat, 0) / older_total

            # Significant increase
            if recent_ratio > older_ratio + 0.2 and recent_cats.get(cat, 0) >= 3:
                proposals.append(Proposal(
                    id=f"ap_{uuid4().hex[:8]}",
                    trigger_type="anomaly",
                    empathy=f"最近「{cat}」类的记忆明显增多了",
                    evidence=[],
                    evidence_text=f"近 {days} 天占 {recent_ratio:.0%}，之前只有 {older_ratio:.0%}",
                    action="是生活节奏变了，还是有什么特别的事？",
                    confidence=0.6,
                    priority=4,
                    created_at=time.time(),
                    meta={"category": cat, "recent_ratio": recent_ratio,
                          "older_ratio": older_ratio},
                ))

            # Significant decrease (something dropped off)
            if older_ratio > recent_ratio + 0.2 and older_cats.get(cat, 0) >= 3:
                if recent_cats.get(cat, 0) == 0:
                    proposals.append(Proposal(
                        id=f"ap_{uuid4().hex[:8]}",
                        trigger_type="anomaly",
                        empathy=f"最近没有「{cat}」类的记忆了",
                        evidence=[],
                        evidence_text=f"之前占 {older_ratio:.0%}，最近 {days} 天为零",
                        action="是有意放下了，还是忘了？",
                        confidence=0.5,
                        priority=5,
                        created_at=time.time(),
                        meta={"category": cat, "dropped": True},
                    ))

        return proposals

    # --- LLM-powered proposals ---

    async def generate_with_llm(self, context: str = "",
                                recent_limit: int = 20) -> List[Proposal]:
        """Use LLM to generate contextual life proposals."""
        if not self.llm_fn:
            return []

        now = time.time()
        recent = self.store.search_by_time_range(now - 7 * 86400, now, limit=recent_limit)
        if not recent:
            return []

        summaries = []
        for ctx in recent:
            t = datetime.fromtimestamp(ctx.event_time or ctx.created_at).strftime("%m-%d")
            summaries.append(f"[{t}][{ctx.category}] {ctx.abstract}")

        # Get active patterns
        patterns = self.patterns.list_patterns(limit=5)
        pattern_text = "\n".join(f"- {p.description}" for p in patterns) if patterns else "暂无"

        # Get taboos
        taboos = self.store.list_taboos(active_only=True)
        taboo_text = "、".join(t["pattern"] for t in taboos[:5]) if taboos else "暂无"

        prompt = f"""你是一个贴心的生活助理。根据以下记忆和模式，生成 1-3 个生活提案。

当前时间: {datetime.now().strftime("%Y-%m-%d %H:%M %A")}
{f"当前情境: {context}" if context else ""}

最近记忆:
{chr(10).join(summaries)}

已发现的模式:
{pattern_text}

禁忌话题: {taboo_text}

每个提案包含:
- empathy: 共情（一句话，承认现状）
- evidence: 证据（引用哪条记忆或模式）
- action: 建议（具体可执行的行动）
- priority: 1-5（1最紧急）

返回 JSON:
{{"proposals": [
  {{"empathy": "...", "evidence": "...", "action": "...", "priority": 3}}
]}}"""

        try:
            response = await self.llm_fn(prompt)
            # Parse JSON from response
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                return []
            data = json.loads(json_match.group())

            proposals = []
            for p in data.get("proposals", []):
                proposals.append(Proposal(
                    id=f"llm_{uuid4().hex[:8]}",
                    trigger_type="context",
                    empathy=p.get("empathy", ""),
                    evidence=[],
                    evidence_text=p.get("evidence", ""),
                    action=p.get("action", ""),
                    confidence=0.7,
                    priority=p.get("priority", 3),
                    created_at=now,
                ))
            return proposals
        except Exception as e:
            logger.error(f"LLM proposal generation failed: {e}")
            return []

    # --- Orchestration ---

    def check_all(self) -> List[Proposal]:
        """Run all heuristic triggers and return proposals sorted by priority."""
        proposals = []
        proposals.extend(self.check_fading_memories())
        proposals.extend(self.check_pattern_triggers())
        proposals.extend(self.check_anomalies())
        # Sort: lower priority number = more important
        proposals.sort(key=lambda p: (p.priority, -p.confidence))
        # Save all
        for p in proposals:
            self._save_proposal(p)
        return proposals

    async def check_all_with_llm(self, context: str = "") -> List[Proposal]:
        """Run all triggers including LLM-powered ones."""
        proposals = self.check_all()
        if self.llm_fn:
            llm_proposals = await self.generate_with_llm(context)
            proposals.extend(llm_proposals)
            for p in llm_proposals:
                self._save_proposal(p)
        proposals.sort(key=lambda p: (p.priority, -p.confidence))
        return proposals

    # --- Proposal Management ---

    def dismiss(self, proposal_id: str):
        """Mark a proposal as dismissed."""
        self.store.conn.execute(
            "UPDATE proposals SET dismissed = 1 WHERE id = ?", (proposal_id,))
        self.store.conn.commit()

    def act_on(self, proposal_id: str):
        """Mark a proposal as acted upon."""
        self.store.conn.execute(
            "UPDATE proposals SET acted_on = 1 WHERE id = ?", (proposal_id,))
        self.store.conn.commit()

    def list_proposals(self, include_dismissed: bool = False,
                       limit: int = 10) -> List[Proposal]:
        """List recent proposals."""
        query = "SELECT * FROM proposals"
        if not include_dismissed:
            query += " WHERE dismissed = 0"
        query += " ORDER BY created_at DESC LIMIT ?"
        rows = self.store.conn.execute(query, (limit,)).fetchall()
        return [self._row_to_proposal(r) for r in rows]

    def _save_proposal(self, p: Proposal):
        self.store.conn.execute(
            """INSERT OR REPLACE INTO proposals
               (id, trigger_type, empathy, evidence, evidence_text, action,
                confidence, priority, created_at, dismissed, acted_on, meta)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (p.id, p.trigger_type, p.empathy, json.dumps(p.evidence),
             p.evidence_text, p.action, p.confidence, p.priority,
             p.created_at, int(p.dismissed), int(p.acted_on), json.dumps(p.meta))
        )
        self.store.conn.commit()

    def _row_to_proposal(self, row) -> Proposal:
        return Proposal(
            id=row[0], trigger_type=row[1], empathy=row[2],
            evidence=json.loads(row[3]) if row[3] else [],
            evidence_text=row[4], action=row[5],
            confidence=row[6], priority=row[7],
            created_at=row[8], dismissed=bool(row[9]),
            acted_on=bool(row[10]),
            meta=json.loads(row[11]) if row[11] else {},
        )

    def _recently_proposed(self, trigger_type: str, key: str,
                           hours: int = 24) -> bool:
        """Check if we already proposed about this recently."""
        since = time.time() - hours * 3600
        rows = self.store.conn.execute(
            """SELECT COUNT(*) FROM proposals
               WHERE trigger_type = ? AND created_at > ?
               AND (meta LIKE ? OR evidence LIKE ?)""",
            (trigger_type, since, f'%{key}%', f'%{key}%')
        ).fetchone()
        return rows[0] > 0 if rows else False

    def stats(self) -> Dict[str, int]:
        total = self.store.conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
        active = self.store.conn.execute(
            "SELECT COUNT(*) FROM proposals WHERE dismissed = 0").fetchone()[0]
        acted = self.store.conn.execute(
            "SELECT COUNT(*) FROM proposals WHERE acted_on = 1").fetchone()[0]
        return {"total": total, "active": active, "acted_on": acted}
