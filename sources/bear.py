"""Bear Notes data source adapter.

Reads directly from Bear's SQLite database (read-only).
Converts notes into Amber Memory source layer entries.

DB path: ~/Library/Group Containers/9K33E3U3T4.net.shinyfrog.bear/Application Data/database.sqlite
"""

import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..core.context import Context, ContextType
from ..core.uri import URI

BEAR_DB_PATH = os.path.expanduser(
    "~/Library/Group Containers/9K33E3U3T4.net.shinyfrog.bear/Application Data/database.sqlite"
)

# Bear stores dates as Core Data timestamps (seconds since 2001-01-01)
COREDATA_EPOCH = 978307200  # Unix timestamp of 2001-01-01 00:00:00 UTC


@dataclass
class BearNote:
    """A Bear note."""
    pk: int
    unique_id: str
    title: str
    text: str
    tags: List[str]
    created_at: float      # unix timestamp
    modified_at: float     # unix timestamp
    is_trashed: bool
    is_archived: bool


class BearSource:
    """Reads Bear Notes database and produces Amber Memory contexts."""

    def __init__(self, db_path: str = BEAR_DB_PATH):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Bear database not found: {self.db_path}")
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row

    def _to_unix(self, coredata_ts: Optional[float]) -> float:
        """Convert Core Data timestamp to Unix timestamp."""
        if coredata_ts is None or coredata_ts == 0:
            return time.time()
        return coredata_ts + COREDATA_EPOCH

    def get_notes(self, tag: Optional[str] = None, include_trashed: bool = False,
                  limit: int = 500) -> List[BearNote]:
        """Get notes, optionally filtered by tag."""
        if tag:
            query = """
                SELECT n.Z_PK, n.ZUNIQUEIDENTIFIER, n.ZTITLE, n.ZTEXT,
                       n.ZCREATIONDATE, n.ZMODIFICATIONDATE, n.ZTRASHED, n.ZARCHIVED
                FROM ZSFNOTE n
                JOIN Z_5TAGS zt ON n.Z_PK = zt.Z_5NOTES
                JOIN ZSFNOTETAG t ON t.Z_PK = zt.Z_13TAGS
                WHERE t.ZTITLE = ?
            """
            params = [tag]
            if not include_trashed:
                query += " AND n.ZTRASHED = 0 AND n.ZPERMANENTLYDELETED = 0"
            query += " ORDER BY n.ZMODIFICATIONDATE DESC LIMIT ?"
            params.append(limit)
            rows = self.conn.execute(query, params).fetchall()
        else:
            query = """
                SELECT Z_PK, ZUNIQUEIDENTIFIER, ZTITLE, ZTEXT,
                       ZCREATIONDATE, ZMODIFICATIONDATE, ZTRASHED, ZARCHIVED
                FROM ZSFNOTE WHERE 1=1
            """
            params = []
            if not include_trashed:
                query += " AND ZTRASHED = 0 AND ZPERMANENTLYDELETED = 0"
            query += " ORDER BY ZMODIFICATIONDATE DESC LIMIT ?"
            params.append(limit)
            rows = self.conn.execute(query, params).fetchall()

        notes = []
        for row in rows:
            tags = self._get_tags(row["Z_PK"])
            notes.append(BearNote(
                pk=row["Z_PK"],
                unique_id=row["ZUNIQUEIDENTIFIER"] or "",
                title=row["ZTITLE"] or "",
                text=row["ZTEXT"] or "",
                tags=tags,
                created_at=self._to_unix(row["ZCREATIONDATE"]),
                modified_at=self._to_unix(row["ZMODIFICATIONDATE"]),
                is_trashed=bool(row["ZTRASHED"]),
                is_archived=bool(row["ZARCHIVED"]),
            ))
        return notes

    def _get_tags(self, note_pk: int) -> List[str]:
        rows = self.conn.execute("""
            SELECT t.ZTITLE FROM ZSFNOTETAG t
            JOIN Z_5TAGS zt ON t.Z_PK = zt.Z_13TAGS
            WHERE zt.Z_5NOTES = ?
        """, (note_pk,)).fetchall()
        return [r["ZTITLE"] for r in rows]

    def get_amber_reflections(self) -> List[BearNote]:
        """Get all notes tagged 随感/Amber — previous Ambers' reflections."""
        return self.get_notes(tag="随感/Amber")

    def get_all_amber_notes(self) -> List[BearNote]:
        """Get all notes tagged Amber."""
        return self.get_notes(tag="Amber")

    def _clean_bear_text(self, text: str) -> str:
        """Remove Bear-specific markup from text."""
        # Remove Bear's internal markers
        text = re.sub(r'<!-- \{.*?\} -->', '', text)
        # Remove image markers
        text = re.sub(r'\[image:.*?\]', '[图片]', text)
        # Remove file markers
        text = re.sub(r'\[file:.*?\]', '[文件]', text)
        return text.strip()

    # --- Convert to Amber Memory Contexts ---

    def notes_to_contexts(self, notes: List[BearNote]) -> List[Context]:
        """Convert Bear notes to Amber Memory contexts."""
        contexts = []
        for note in notes:
            if not note.text or len(note.text.strip()) < 20:
                continue

            clean_text = self._clean_bear_text(note.text)
            # Determine context type from tags
            ctx_type = ContextType.THOUGHT  # default for Bear notes
            if any("projects" in t for t in note.tags):
                ctx_type = ContextType.OBJECT
            elif any("openclaw" in t for t in note.tags):
                ctx_type = ContextType.OBJECT

            # Importance based on tags
            importance = 0.5
            if "随感/Amber" in note.tags:
                importance = 0.7  # Amber reflections are important for identity
            elif "随感" in note.tags:
                importance = 0.6

            safe_title = note.title.replace("/", "_").replace(" ", "_")[:40]
            uri = f"/bear/notes/{safe_title}_{note.unique_id[:8]}"

            ctx = Context(
                uri=uri,
                parent_uri="/bear/notes",
                abstract=note.title,
                overview=clean_text[:200].replace("\n", " "),
                content=clean_text,
                context_type=ctx_type,
                category="notes",
                tags=["bear"] + note.tags,
                emotion="neutral",
                importance=importance,
                created_at=note.created_at,
                updated_at=note.modified_at,
                last_accessed=note.modified_at,
                event_time=note.created_at,
                meta={
                    "source": "bear",
                    "bear_id": note.unique_id,
                    "bear_title": note.title,
                },
            )
            contexts.append(ctx)
        return contexts

    def close(self):
        self.conn.close()
