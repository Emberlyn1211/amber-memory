"""People Graph — automatic relationship network from memories.

Builds and maintains a graph of people mentioned in memories:
- Auto-extracts person entities from conversations
- Tracks relationships (family, friend, colleague, etc.)
- Records interaction history and frequency
- Supports querying by relationship, recency, importance

Storage: SQLite tables (people, relationships, interactions)
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


@dataclass
class Person:
    """A person entity in the graph."""
    id: str                          # Unique ID (auto-generated)
    name: str                        # Primary name
    aliases: List[str] = field(default_factory=list)  # Other names/nicknames
    relationship: str = ""           # To the user: family/friend/colleague/acquaintance
    description: str = ""            # Who they are
    tags: List[str] = field(default_factory=list)
    first_seen: float = 0.0         # First mention timestamp
    last_seen: float = 0.0          # Last mention timestamp
    interaction_count: int = 0       # How many times mentioned
    importance: float = 0.5          # 0-1
    meta: Dict[str, Any] = field(default_factory=dict)  # Extra info

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "aliases": self.aliases,
            "relationship": self.relationship, "description": self.description,
            "tags": self.tags, "first_seen": self.first_seen,
            "last_seen": self.last_seen, "interaction_count": self.interaction_count,
            "importance": self.importance, "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Person":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Relationship:
    """A relationship between two people."""
    person_a: str       # Person ID
    person_b: str       # Person ID
    relation: str       # e.g. "colleague", "couple", "siblings"
    description: str = ""
    strength: float = 0.5  # 0-1
    since: float = 0.0


class PeopleGraph:
    """Manages the people knowledge graph."""

    PEOPLE_TABLE = """CREATE TABLE IF NOT EXISTS people (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        aliases TEXT DEFAULT '[]',
        relationship TEXT DEFAULT '',
        description TEXT DEFAULT '',
        tags TEXT DEFAULT '[]',
        first_seen REAL DEFAULT 0,
        last_seen REAL DEFAULT 0,
        interaction_count INTEGER DEFAULT 0,
        importance REAL DEFAULT 0.5,
        meta TEXT DEFAULT '{}'
    )"""

    RELATIONSHIPS_TABLE = """CREATE TABLE IF NOT EXISTS relationships (
        person_a TEXT NOT NULL,
        person_b TEXT NOT NULL,
        relation TEXT NOT NULL,
        description TEXT DEFAULT '',
        strength REAL DEFAULT 0.5,
        since REAL DEFAULT 0,
        PRIMARY KEY (person_a, person_b, relation)
    )"""

    INTERACTIONS_TABLE = """CREATE TABLE IF NOT EXISTS interactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id TEXT NOT NULL,
        timestamp REAL NOT NULL,
        context TEXT DEFAULT '',
        memory_uri TEXT DEFAULT '',
        sentiment TEXT DEFAULT 'neutral'
    )"""

    def __init__(self, store: SQLiteStore):
        self.store = store
        self._init_tables()

    def _init_tables(self):
        """Create people graph tables if they don't exist."""
        conn = self.store.conn
        conn.execute(self.PEOPLE_TABLE)
        conn.execute(self.RELATIONSHIPS_TABLE)
        conn.execute(self.INTERACTIONS_TABLE)
        conn.commit()

    # --- Person CRUD ---

    def add_person(self, name: str, relationship: str = "",
                   description: str = "", aliases: List[str] = None,
                   importance: float = 0.5, meta: Dict = None) -> Person:
        """Add a new person to the graph."""
        from uuid import uuid4
        pid = f"p_{uuid4().hex[:8]}"
        now = time.time()
        person = Person(
            id=pid, name=name, aliases=aliases or [],
            relationship=relationship, description=description,
            first_seen=now, last_seen=now, importance=importance,
            meta=meta or {},
        )
        self.store.conn.execute(
            """INSERT OR REPLACE INTO people 
               (id, name, aliases, relationship, description, tags, 
                first_seen, last_seen, interaction_count, importance, meta)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, name, json.dumps(aliases or []), relationship, description,
             json.dumps([]), now, now, 0, importance, json.dumps(meta or {}))
        )
        self.store.conn.commit()
        return person

    def get_person(self, person_id: str) -> Optional[Person]:
        row = self.store.conn.execute(
            "SELECT * FROM people WHERE id = ?", (person_id,)
        ).fetchone()
        return self._row_to_person(row) if row else None

    def find_person(self, name: str) -> Optional[Person]:
        """Find person by name or alias."""
        # Exact name match
        row = self.store.conn.execute(
            "SELECT * FROM people WHERE name = ?", (name,)
        ).fetchone()
        if row:
            return self._row_to_person(row)
        # Alias search
        rows = self.store.conn.execute(
            "SELECT * FROM people WHERE aliases LIKE ?", (f'%"{name}"%',)
        ).fetchall()
        if rows:
            return self._row_to_person(rows[0])
        # Fuzzy name match
        row = self.store.conn.execute(
            "SELECT * FROM people WHERE name LIKE ?", (f'%{name}%',)
        ).fetchone()
        return self._row_to_person(row) if row else None

    def update_person(self, person_id: str, **kwargs) -> bool:
        """Update person fields."""
        allowed = {"name", "aliases", "relationship", "description",
                   "tags", "importance", "meta"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        # Serialize lists/dicts
        for k in ("aliases", "tags"):
            if k in updates and isinstance(updates[k], list):
                updates[k] = json.dumps(updates[k])
        if "meta" in updates and isinstance(updates["meta"], dict):
            updates["meta"] = json.dumps(updates["meta"])

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [person_id]
        self.store.conn.execute(
            f"UPDATE people SET {set_clause} WHERE id = ?", values
        )
        self.store.conn.commit()
        return True

    def list_people(self, relationship: str = None, limit: int = 50,
                    sort_by: str = "last_seen") -> List[Person]:
        """List people, optionally filtered by relationship."""
        query = "SELECT * FROM people"
        params = []
        if relationship:
            query += " WHERE relationship = ?"
            params.append(relationship)
        query += f" ORDER BY {sort_by} DESC LIMIT ?"
        params.append(limit)
        rows = self.store.conn.execute(query, params).fetchall()
        return [self._row_to_person(r) for r in rows]

    # --- Relationships ---

    def add_relationship(self, person_a: str, person_b: str,
                         relation: str, description: str = "",
                         strength: float = 0.5):
        """Add a relationship between two people."""
        self.store.conn.execute(
            """INSERT OR REPLACE INTO relationships 
               (person_a, person_b, relation, description, strength, since)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (person_a, person_b, relation, description, strength, time.time())
        )
        self.store.conn.commit()

    def get_relationships(self, person_id: str) -> List[Relationship]:
        """Get all relationships for a person."""
        rows = self.store.conn.execute(
            """SELECT * FROM relationships 
               WHERE person_a = ? OR person_b = ?""",
            (person_id, person_id)
        ).fetchall()
        return [Relationship(
            person_a=r[0], person_b=r[1], relation=r[2],
            description=r[3], strength=r[4], since=r[5],
        ) for r in rows]

    # --- Interactions ---

    def record_interaction(self, person_id: str, context: str = "",
                           memory_uri: str = "", sentiment: str = "neutral"):
        """Record an interaction with a person."""
        now = time.time()
        self.store.conn.execute(
            """INSERT INTO interactions (person_id, timestamp, context, memory_uri, sentiment)
               VALUES (?, ?, ?, ?, ?)""",
            (person_id, now, context, memory_uri, sentiment)
        )
        # Update person stats
        self.store.conn.execute(
            """UPDATE people SET last_seen = ?, interaction_count = interaction_count + 1
               WHERE id = ?""",
            (now, person_id)
        )
        self.store.conn.commit()

    def get_interactions(self, person_id: str, limit: int = 20) -> List[Dict]:
        """Get recent interactions with a person."""
        rows = self.store.conn.execute(
            """SELECT timestamp, context, memory_uri, sentiment 
               FROM interactions WHERE person_id = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (person_id, limit)
        ).fetchall()
        return [{"timestamp": r[0], "context": r[1],
                 "memory_uri": r[2], "sentiment": r[3]} for r in rows]

    # --- LLM-assisted extraction ---

    async def extract_people_from_text(self, text: str, llm_fn=None) -> List[Dict]:
        """Use LLM to extract person mentions from text."""
        if not llm_fn:
            return self._simple_extract(text)

        prompt = f"""从以下文本中提取提到的人物信息。

文本: {text[:1000]}

返回 JSON:
{{
  "people": [
    {{
      "name": "名字",
      "relationship": "family/friend/colleague/acquaintance/other",
      "context": "在文本中的上下文（一句话）"
    }}
  ]
}}

没有人物就返回 {{"people": []}}"""

        try:
            from ..session.memory_extractor import parse_json_from_response
            response = await llm_fn(prompt)
            data = parse_json_from_response(response) or {}
            return data.get("people", [])
        except Exception as e:
            logger.error(f"People extraction failed: {e}")
            return self._simple_extract(text)

    def _simple_extract(self, text: str) -> List[Dict]:
        """Simple heuristic person extraction (no LLM)."""
        # Look for common Chinese name patterns (2-3 chars after relationship words)
        patterns = [
            r'(?:老|小|大)[A-Za-z\u4e00-\u9fff]',  # 老王, 小李
            r'(?:和|跟|与|给|找|问|叫)([A-Za-z\u4e00-\u9fff]{2,4})',  # 和XX
        ]
        names = set()
        for p in patterns:
            for m in re.finditer(p, text):
                name = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
                if len(name) >= 2:
                    names.add(name)
        return [{"name": n, "relationship": "", "context": ""} for n in names]

    # --- Stats ---

    def stats(self) -> Dict[str, Any]:
        total = self.store.conn.execute("SELECT COUNT(*) FROM people").fetchone()[0]
        rels = self.store.conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
        interactions = self.store.conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
        return {"people": total, "relationships": rels, "interactions": interactions}

    # --- Internal ---

    def _row_to_person(self, row) -> Person:
        return Person(
            id=row[0], name=row[1],
            aliases=json.loads(row[2]) if row[2] else [],
            relationship=row[3], description=row[4],
            tags=json.loads(row[5]) if row[5] else [],
            first_seen=row[6], last_seen=row[7],
            interaction_count=row[8], importance=row[9],
            meta=json.loads(row[10]) if row[10] else {},
        )
