"""SQLite storage backend for Amber Memory.

Replaces OpenViking's VikingDB with local SQLite.
Stores contexts (memories) with full L0/L1/L2 content and decay metadata.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.context import Context, DecayParams, DEFAULT_DECAY


class SQLiteStore:
    """Local SQLite storage for memories."""

    def __init__(self, db_path: str = "amber_memory.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_tables()

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS contexts (
                id TEXT PRIMARY KEY,
                uri TEXT UNIQUE NOT NULL,
                parent_uri TEXT DEFAULT '',
                abstract TEXT DEFAULT '',
                overview TEXT DEFAULT '',
                content TEXT DEFAULT '',
                context_type TEXT DEFAULT 'memory',
                category TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                emotion TEXT DEFAULT 'neutral',
                importance REAL DEFAULT 0.5,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_accessed REAL NOT NULL,
                event_time REAL,
                access_count INTEGER DEFAULT 0,
                link_count INTEGER DEFAULT 0,
                linked_uris TEXT DEFAULT '[]',
                source_session TEXT DEFAULT '',
                meta TEXT DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_contexts_uri ON contexts(uri);
            CREATE INDEX IF NOT EXISTS idx_contexts_parent ON contexts(parent_uri);
            CREATE INDEX IF NOT EXISTS idx_contexts_type ON contexts(context_type);
            CREATE INDEX IF NOT EXISTS idx_contexts_category ON contexts(category);
            CREATE INDEX IF NOT EXISTS idx_contexts_created ON contexts(created_at);
            CREATE INDEX IF NOT EXISTS idx_contexts_importance ON contexts(importance);
            CREATE INDEX IF NOT EXISTS idx_contexts_last_accessed ON contexts(last_accessed);

            CREATE TABLE IF NOT EXISTS links (
                source_uri TEXT NOT NULL,
                target_uri TEXT NOT NULL,
                relation TEXT DEFAULT 'related',
                weight REAL DEFAULT 1.0,
                created_at REAL NOT NULL,
                PRIMARY KEY (source_uri, target_uri)
            );

            CREATE INDEX IF NOT EXISTS idx_links_source ON links(source_uri);
            CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_uri);

            CREATE TABLE IF NOT EXISTS embeddings (
                uri TEXT PRIMARY KEY,
                vector BLOB NOT NULL,
                model TEXT DEFAULT '',
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                origin TEXT NOT NULL,
                raw_content TEXT DEFAULT '',
                file_path TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}',
                created_at REAL NOT NULL,
                event_time REAL,
                processed INTEGER DEFAULT 0,
                process_result TEXT DEFAULT '[]'
            );

            CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(type);
            CREATE INDEX IF NOT EXISTS idx_sources_origin ON sources(origin);
            CREATE INDEX IF NOT EXISTS idx_sources_created ON sources(created_at);
            CREATE INDEX IF NOT EXISTS idx_sources_processed ON sources(processed);

            CREATE TABLE IF NOT EXISTS taboos (
                id TEXT PRIMARY KEY,
                pattern TEXT NOT NULL,
                description TEXT DEFAULT '',
                scope TEXT DEFAULT 'global',
                active INTEGER DEFAULT 1,
                created_at REAL NOT NULL
            );
        """)
        self.conn.commit()

    # --- CRUD ---

    def put(self, ctx: Context) -> None:
        """Insert or replace a context."""
        ctx.updated_at = time.time()
        self.conn.execute("""
            INSERT OR REPLACE INTO contexts 
            (id, uri, parent_uri, abstract, overview, content,
             context_type, category, tags, emotion, importance,
             created_at, updated_at, last_accessed, event_time,
             access_count, link_count, linked_uris, source_session, meta)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            ctx.id, ctx.uri, ctx.parent_uri,
            ctx.abstract, ctx.overview, ctx.content,
            ctx.context_type, ctx.category,
            json.dumps(ctx.tags, ensure_ascii=False), ctx.emotion, ctx.importance,
            ctx.created_at, ctx.updated_at, ctx.last_accessed,
            ctx.event_time, ctx.access_count, ctx.link_count,
            json.dumps(ctx.linked_uris), ctx.source_session,
            json.dumps(ctx.meta),
        ))
        self.conn.commit()

    def get(self, uri: str) -> Optional[Context]:
        """Get a context by URI."""
        row = self.conn.execute(
            "SELECT * FROM contexts WHERE uri = ?", (uri,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_context(row)

    def get_by_id(self, ctx_id: str) -> Optional[Context]:
        row = self.conn.execute(
            "SELECT * FROM contexts WHERE id = ?", (ctx_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_context(row)

    def delete(self, uri: str) -> bool:
        cur = self.conn.execute("DELETE FROM contexts WHERE uri = ?", (uri,))
        self.conn.execute("DELETE FROM links WHERE source_uri = ? OR target_uri = ?", (uri, uri))
        self.conn.execute("DELETE FROM embeddings WHERE uri = ?", (uri,))
        self.conn.commit()
        return cur.rowcount > 0

    def touch(self, uri: str) -> None:
        """Record access, refresh decay timer."""
        now = time.time()
        self.conn.execute("""
            UPDATE contexts SET access_count = access_count + 1,
            last_accessed = ? WHERE uri = ?
        """, (now, uri))
        self.conn.commit()

    # --- Query ---

    def list_children(self, parent_uri: str) -> List[Context]:
        """List direct children of a URI (directory listing)."""
        rows = self.conn.execute(
            "SELECT * FROM contexts WHERE parent_uri = ? ORDER BY created_at DESC",
            (parent_uri,)
        ).fetchall()
        return [self._row_to_context(r) for r in rows]

    def search_by_type(self, context_type: str, limit: int = 50) -> List[Context]:
        rows = self.conn.execute(
            "SELECT * FROM contexts WHERE context_type = ? ORDER BY last_accessed DESC LIMIT ?",
            (context_type, limit)
        ).fetchall()
        return [self._row_to_context(r) for r in rows]

    def search_by_category(self, category: str, limit: int = 50) -> List[Context]:
        rows = self.conn.execute(
            "SELECT * FROM contexts WHERE category = ? ORDER BY last_accessed DESC LIMIT ?",
            (category, limit)
        ).fetchall()
        return [self._row_to_context(r) for r in rows]

    def search_by_tag(self, tag: str, limit: int = 50) -> List[Context]:
        rows = self.conn.execute(
            "SELECT * FROM contexts WHERE tags LIKE ? ORDER BY last_accessed DESC LIMIT ?",
            (f'%"{tag}"%', limit)
        ).fetchall()
        return [self._row_to_context(r) for r in rows]

    def search_by_time_range(self, start: float, end: float, limit: int = 100) -> List[Context]:
        """Search by event_time (or created_at if no event_time)."""
        rows = self.conn.execute("""
            SELECT * FROM contexts 
            WHERE COALESCE(event_time, created_at) BETWEEN ? AND ?
            ORDER BY COALESCE(event_time, created_at) DESC LIMIT ?
        """, (start, end, limit)).fetchall()
        return [self._row_to_context(r) for r in rows]

    def search_text(self, query: str, limit: int = 20) -> List[Context]:
        """Full-text search across abstract, overview, content.
        Splits query into tokens and matches any token (OR logic).
        """
        # Split query into meaningful tokens (2+ chars)
        tokens = [t for t in query.replace("，", " ").replace(",", " ").split() if len(t) >= 2]
        if not tokens:
            tokens = [query]
        
        # Build OR conditions for each token
        conditions = []
        params = []
        for token in tokens:
            pattern = f"%{token}%"
            conditions.append("(abstract LIKE ? OR overview LIKE ? OR content LIKE ? OR tags LIKE ?)")
            params.extend([pattern, pattern, pattern, pattern])
        
        where = " OR ".join(conditions)
        rows = self.conn.execute(f"""
            SELECT * FROM contexts 
            WHERE {where}
            ORDER BY importance DESC, last_accessed DESC LIMIT ?
        """, params + [limit]).fetchall()
        return [self._row_to_context(r) for r in rows]

    def get_top_memories(self, limit: int = 20, params: DecayParams = DEFAULT_DECAY) -> List[tuple]:
        """Get top memories ranked by decay score."""
        rows = self.conn.execute(
            "SELECT * FROM contexts ORDER BY importance DESC"
        ).fetchall()
        contexts = [self._row_to_context(r) for r in rows]
        scored = [(ctx, ctx.compute_score(params)) for ctx in contexts]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def get_decayed(self, threshold: float = 0.05, params: DecayParams = DEFAULT_DECAY) -> List[Context]:
        """Get memories that have decayed below threshold (candidates for forgetting)."""
        rows = self.conn.execute("SELECT * FROM contexts").fetchall()
        contexts = [self._row_to_context(r) for r in rows]
        return [ctx for ctx in contexts if ctx.compute_score(params) < threshold]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM contexts").fetchone()[0]

    def stats(self) -> Dict[str, Any]:
        total = self.count()
        by_type = {}
        for row in self.conn.execute(
            "SELECT context_type, COUNT(*) as cnt FROM contexts GROUP BY context_type"
        ).fetchall():
            by_type[row["context_type"]] = row["cnt"]
        by_source = {}
        for row in self.conn.execute("""
            SELECT SUBSTR(uri, 2, INSTR(SUBSTR(uri, 2), '/') - 1) as src, COUNT(*) as cnt 
            FROM contexts GROUP BY src
        """).fetchall():
            by_source[row["src"] or "unknown"] = row["cnt"]
        return {"total": total, "by_type": by_type, "by_source": by_source}

    # --- Links ---

    def add_link(self, source_uri: str, target_uri: str, relation: str = "related", weight: float = 1.0):
        self.conn.execute("""
            INSERT OR REPLACE INTO links (source_uri, target_uri, relation, weight, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (source_uri, target_uri, relation, weight, time.time()))
        for uri in (source_uri, target_uri):
            self.conn.execute(
                "UPDATE contexts SET link_count = (SELECT COUNT(*) FROM links WHERE source_uri = ? OR target_uri = ?) WHERE uri = ?",
                (uri, uri, uri))
        self.conn.commit()

    def get_links(self, uri: str) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM links WHERE source_uri = ? OR target_uri = ?", (uri, uri)
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Embeddings ---

    def put_embedding(self, uri: str, vector: bytes, model: str = ""):
        self.conn.execute("""
            INSERT OR REPLACE INTO embeddings (uri, vector, model, updated_at)
            VALUES (?, ?, ?, ?)
        """, (uri, vector, model, time.time()))
        self.conn.commit()

    def get_embedding(self, uri: str) -> Optional[bytes]:
        row = self.conn.execute("SELECT vector FROM embeddings WHERE uri = ?", (uri,)).fetchone()
        return row["vector"] if row else None

    # --- Source Layer ---

    def put_source(self, source_id: str, source_type: str, origin: str,
                   raw_content: str = "", file_path: str = "",
                   metadata: Optional[Dict] = None, event_time: Optional[float] = None) -> None:
        import time as _time
        self.conn.execute("""
            INSERT OR REPLACE INTO sources (id, type, origin, raw_content, file_path,
            metadata, created_at, event_time, processed, process_result)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, '[]')
        """, (source_id, source_type, origin, raw_content, file_path,
              json.dumps(metadata or {}, ensure_ascii=False), _time.time(), event_time))
        self.conn.commit()

    def get_source(self, source_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        return dict(row) if row else None

    def list_unprocessed_sources(self, limit: int = 100) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM sources WHERE processed = 0 ORDER BY created_at ASC LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in rows]

    def mark_source_processed(self, source_id: str, memory_uris: List[str]) -> None:
        self.conn.execute("""
            UPDATE sources SET processed = 1, process_result = ? WHERE id = ?
        """, (json.dumps(memory_uris), source_id))
        self.conn.commit()

    def source_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]

    # --- Taboo System ---

    def add_taboo(self, pattern: str, description: str = "", scope: str = "global") -> str:
        from uuid import uuid4
        taboo_id = uuid4().hex[:12]
        self.conn.execute("""
            INSERT INTO taboos (id, pattern, description, scope, active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
        """, (taboo_id, pattern, description, scope, time.time()))
        self.conn.commit()
        return taboo_id

    def list_taboos(self, active_only: bool = True) -> List[Dict[str, Any]]:
        query = "SELECT * FROM taboos"
        if active_only:
            query += " WHERE active = 1"
        return [dict(r) for r in self.conn.execute(query).fetchall()]

    def remove_taboo(self, taboo_id: str) -> bool:
        cur = self.conn.execute("UPDATE taboos SET active = 0 WHERE id = ?", (taboo_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def check_taboos(self, text: str) -> List[Dict[str, Any]]:
        """Check if text triggers any active taboos."""
        taboos = self.list_taboos(active_only=True)
        triggered = []
        for t in taboos:
            if t["pattern"] in text:
                triggered.append(t)
        return triggered

    # --- Internal ---

    def _row_to_context(self, row: sqlite3.Row) -> Context:
        return Context(
            id=row["id"], uri=row["uri"], parent_uri=row["parent_uri"],
            abstract=row["abstract"], overview=row["overview"], content=row["content"],
            context_type=row["context_type"], category=row["category"],
            tags=json.loads(row["tags"]), emotion=row["emotion"],
            importance=row["importance"], created_at=row["created_at"],
            updated_at=row["updated_at"], last_accessed=row["last_accessed"],
            event_time=row["event_time"], access_count=row["access_count"],
            link_count=row["link_count"], linked_uris=json.loads(row["linked_uris"]),
            source_session=row["source_session"], meta=json.loads(row["meta"]),
        )

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
