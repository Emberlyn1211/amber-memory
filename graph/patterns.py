"""Pattern Recognition — detect behavioral patterns from memory history.

Analyzes memories over time to find:
- Recurring activities (weekly meetings, daily habits)
- Emotional patterns (mood cycles, stress triggers)
- Relationship patterns (who you interact with when)
- Time patterns (when you're most productive, social, etc.)
"""

import json
import logging
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..storage.sqlite_store import SQLiteStore
from ..core.context import Context

logger = logging.getLogger(__name__)


@dataclass
class Pattern:
    """A detected behavioral pattern."""
    id: str
    pattern_type: str       # time/activity/emotion/social/habit
    description: str        # Human-readable description
    confidence: float       # 0-1
    evidence: List[str]     # Memory URIs that support this pattern
    frequency: str = ""     # daily/weekly/monthly/irregular
    meta: Dict[str, Any] = field(default_factory=dict)
    detected_at: float = 0.0


class PatternDetector:
    """Detects patterns from memory history."""

    PATTERNS_TABLE = """CREATE TABLE IF NOT EXISTS patterns (
        id TEXT PRIMARY KEY,
        pattern_type TEXT NOT NULL,
        description TEXT NOT NULL,
        confidence REAL DEFAULT 0.5,
        evidence TEXT DEFAULT '[]',
        frequency TEXT DEFAULT '',
        meta TEXT DEFAULT '{}',
        detected_at REAL DEFAULT 0
    )"""

    def __init__(self, store: SQLiteStore):
        self.store = store
        self._init_table()

    def _init_table(self):
        self.store.conn.execute(self.PATTERNS_TABLE)
        self.store.conn.commit()

    def detect_time_patterns(self, days: int = 30) -> List[Pattern]:
        """Detect time-based patterns (when things happen)."""
        now = time.time()
        since = now - days * 86400
        memories = self.store.search_by_time_range(since, now, limit=500)
        if len(memories) < 5:
            return []

        # Analyze hour distribution
        hour_counts = Counter()
        weekday_counts = Counter()
        for ctx in memories:
            t = ctx.event_time or ctx.created_at
            if t:
                dt = datetime.fromtimestamp(t)
                hour_counts[dt.hour] += 1
                weekday_counts[dt.weekday()] += 1

        patterns = []
        # Peak hours
        if hour_counts:
            peak_hour = hour_counts.most_common(1)[0]
            if peak_hour[1] >= 5:
                from uuid import uuid4
                patterns.append(Pattern(
                    id=f"tp_{uuid4().hex[:8]}",
                    pattern_type="time",
                    description=f"活跃高峰在 {peak_hour[0]}:00 左右（{peak_hour[1]} 次记录）",
                    confidence=min(peak_hour[1] / len(memories), 0.9),
                    evidence=[],
                    frequency="daily",
                    detected_at=now,
                ))

        # Weekday patterns
        if weekday_counts:
            day_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            busiest = weekday_counts.most_common(1)[0]
            if busiest[1] >= 3:
                from uuid import uuid4
                patterns.append(Pattern(
                    id=f"tp_{uuid4().hex[:8]}",
                    pattern_type="time",
                    description=f"{day_names[busiest[0]]}最活跃（{busiest[1]} 次记录）",
                    confidence=min(busiest[1] / len(memories), 0.9),
                    evidence=[],
                    frequency="weekly",
                    detected_at=now,
                ))

        return patterns

    def detect_category_patterns(self, days: int = 30) -> List[Pattern]:
        """Detect which memory categories dominate."""
        now = time.time()
        since = now - days * 86400
        memories = self.store.search_by_time_range(since, now, limit=500)
        if len(memories) < 5:
            return []

        cat_counts = Counter(ctx.category for ctx in memories if ctx.category)
        patterns = []
        total = sum(cat_counts.values())

        for cat, count in cat_counts.most_common(3):
            ratio = count / total
            if ratio > 0.2:
                from uuid import uuid4
                patterns.append(Pattern(
                    id=f"cp_{uuid4().hex[:8]}",
                    pattern_type="activity",
                    description=f"近 {days} 天 {int(ratio*100)}% 的记忆是「{cat}」类型",
                    confidence=ratio,
                    evidence=[ctx.uri for ctx in memories if ctx.category == cat][:5],
                    frequency="monthly",
                    detected_at=now,
                    meta={"category": cat, "count": count, "ratio": ratio},
                ))

        return patterns

    async def detect_with_llm(self, llm_fn, days: int = 14, limit: int = 50) -> List[Pattern]:
        """Use LLM to detect deeper patterns from recent memories."""
        now = time.time()
        since = now - days * 86400
        memories = self.store.search_by_time_range(since, now, limit=limit)
        if len(memories) < 5:
            return []

        summaries = []
        for ctx in memories:
            t = datetime.fromtimestamp(ctx.event_time or ctx.created_at).strftime("%m-%d %H:%M")
            summaries.append(f"[{t}] [{ctx.category}] {ctx.abstract}")

        prompt = f"""分析以下 {len(summaries)} 条记忆，找出行为模式。

{chr(10).join(summaries)}

找出 2-5 个模式，返回 JSON:
{{
  "patterns": [
    {{
      "type": "time|activity|emotion|social|habit",
      "description": "模式描述",
      "confidence": 0.0-1.0,
      "frequency": "daily|weekly|monthly|irregular"
    }}
  ]
}}"""

        try:
            from ..session.memory_extractor import parse_json_from_response
            response = await llm_fn(prompt)
            data = parse_json_from_response(response) or {}
            patterns = []
            for p in data.get("patterns", []):
                from uuid import uuid4
                patterns.append(Pattern(
                    id=f"lp_{uuid4().hex[:8]}",
                    pattern_type=p.get("type", "habit"),
                    description=p.get("description", ""),
                    confidence=p.get("confidence", 0.5),
                    evidence=[],
                    frequency=p.get("frequency", "irregular"),
                    detected_at=now,
                ))
            return patterns
        except Exception as e:
            logger.error(f"LLM pattern detection failed: {e}")
            return []

    def save_pattern(self, pattern: Pattern):
        """Persist a detected pattern."""
        self.store.conn.execute(
            """INSERT OR REPLACE INTO patterns 
               (id, pattern_type, description, confidence, evidence, frequency, meta, detected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (pattern.id, pattern.pattern_type, pattern.description,
             pattern.confidence, json.dumps(pattern.evidence),
             pattern.frequency, json.dumps(pattern.meta), pattern.detected_at)
        )
        self.store.conn.commit()

    def list_patterns(self, pattern_type: str = None, limit: int = 20) -> List[Pattern]:
        """List saved patterns."""
        query = "SELECT * FROM patterns"
        params = []
        if pattern_type:
            query += " WHERE pattern_type = ?"
            params.append(pattern_type)
        query += " ORDER BY confidence DESC LIMIT ?"
        params.append(limit)
        rows = self.store.conn.execute(query, params).fetchall()
        return [Pattern(
            id=r[0], pattern_type=r[1], description=r[2],
            confidence=r[3], evidence=json.loads(r[4]) if r[4] else [],
            frequency=r[5], meta=json.loads(r[6]) if r[6] else {},
            detected_at=r[7],
        ) for r in rows]

    def detect_all(self, days: int = 30) -> List[Pattern]:
        """Run all heuristic pattern detectors."""
        patterns = []
        patterns.extend(self.detect_time_patterns(days))
        patterns.extend(self.detect_category_patterns(days))
        for p in patterns:
            self.save_pattern(p)
        return patterns

    def stats(self) -> Dict[str, int]:
        total = self.store.conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
        return {"patterns": total}
