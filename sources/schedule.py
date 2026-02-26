"""Schedule data source — syncs Watchlace calendar into amber-memory source layer.

Reads blocks/tasks from Watchlace DB, groups by day, stores as source records.
LLM extraction then finds patterns (work habits, schedule preferences, etc.)
"""

import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Watchlace DB path
WATCHLACE_DB = os.environ.get(
    "WATCHLACE_DB",
    os.path.expanduser("~/.openclaw/workspace/watchlace-dev/backend/watchlace.db")
)
AMBER_DB = os.path.expanduser("~/.amber/memory.db")


class ScheduleSource:
    """Syncs Watchlace calendar data into amber-memory source layer."""

    def __init__(self, watchlace_db: str = WATCHLACE_DB, amber_db: str = AMBER_DB):
        self.watchlace_db = watchlace_db
        self.amber_db = amber_db

    def _get_watchlace_db(self) -> sqlite3.Connection:
        if not Path(self.watchlace_db).exists():
            raise FileNotFoundError(f"Watchlace DB not found: {self.watchlace_db}")
        return sqlite3.connect(self.watchlace_db, timeout=10)

    def _get_amber_db(self) -> sqlite3.Connection:
        return sqlite3.connect(self.amber_db, timeout=30)

    def read_day(self, date: str) -> List[dict]:
        """Read all blocks/tasks for a given date from Watchlace.
        
        Args:
            date: YYYY-MM-DD format
            
        Returns:
            List of block dicts with task info
        """
        db = self._get_watchlace_db()
        try:
            day_start = f"{date} 00:00:00"
            day_end = f"{date} 23:59:59"

            rows = db.execute("""
                SELECT b.id, b.start_time, b.end_time, b.status,
                       t.id as task_id, t.title, t.priority, t.category
                FROM blocks b
                LEFT JOIN tasks t ON b.task_id = t.id
                WHERE b.start_time >= ? AND b.start_time <= ?
                ORDER BY b.start_time
            """, (day_start, day_end)).fetchall()

            blocks = []
            for r in rows:
                blocks.append({
                    "block_id": r[0],
                    "start_time": r[1],
                    "end_time": r[2],
                    "status": r[3],
                    "task_id": r[4],
                    "title": r[5] or "未命名",
                    "priority": r[6] or "normal",
                    "category": r[7] or "general",
                })
            return blocks
        finally:
            db.close()

    def read_range(self, start_date: str, end_date: str) -> Dict[str, List[dict]]:
        """Read blocks for a date range, grouped by day."""
        result = {}
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        
        current = start
        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            blocks = self.read_day(date_str)
            if blocks:
                result[date_str] = blocks
            current += timedelta(days=1)
        
        return result

    def format_day_text(self, date: str, blocks: List[dict]) -> str:
        """Format a day's schedule as readable text for LLM processing."""
        if not blocks:
            return f"{date}: 无日程安排"

        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        dt = datetime.strptime(date, "%Y-%m-%d")
        weekday = weekday_names[dt.weekday()]

        lines = [f"日期: {date} ({weekday})"]
        lines.append(f"共 {len(blocks)} 个时间块\n")

        completed = 0
        total_mins = 0

        for b in blocks:
            start = b["start_time"].split(" ")[1][:5] if " " in b["start_time"] else b["start_time"][:5]
            end = b["end_time"].split(" ")[1][:5] if " " in b["end_time"] else b["end_time"][:5]
            status_icon = "✅" if b["status"] == "done" else "⏳"
            priority_icon = {"high": "🔴", "normal": "🟡", "low": "🟢"}.get(b["priority"], "")

            lines.append(f"{status_icon} {start}-{end} {priority_icon}{b['title']} [{b['category']}]")

            if b["status"] == "done":
                completed += 1

            # Calculate duration
            try:
                s = datetime.strptime(b["start_time"], "%Y-%m-%d %H:%M:%S")
                e = datetime.strptime(b["end_time"], "%Y-%m-%d %H:%M:%S")
                total_mins += (e - s).total_seconds() / 60
            except (ValueError, TypeError):
                pass

        lines.append(f"\n完成率: {completed}/{len(blocks)} ({completed/len(blocks)*100:.0f}%)")
        lines.append(f"总时长: {total_mins/60:.1f} 小时")

        return "\n".join(lines)

    def sync_to_sources(self, days_back: int = 7, days_forward: int = 3) -> Tuple[int, int]:
        """Sync Watchlace calendar data into amber-memory source layer.
        
        Args:
            days_back: How many past days to sync
            days_forward: How many future days to sync
            
        Returns:
            (new_records, skipped_records) tuple
        """
        from uuid import uuid4

        today = datetime.now()
        start = today - timedelta(days=days_back)
        end = today + timedelta(days=days_forward)

        amber_db = self._get_amber_db()
        new = 0
        skipped = 0

        try:
            current = start
            while current <= end:
                date_str = current.strftime("%Y-%m-%d")

                # Check if already synced
                existing = amber_db.execute(
                    "SELECT id FROM sources WHERE type='schedule' AND origin='watchlace' "
                    "AND json_extract(metadata, '$.date')=?",
                    (date_str,)
                ).fetchone()

                if existing:
                    # Update if it's today or future (schedule might have changed)
                    if current.date() >= today.date():
                        blocks = self.read_day(date_str)
                        if blocks:
                            text = self.format_day_text(date_str, blocks)
                            amber_db.execute(
                                "UPDATE sources SET raw_content=?, processed=0 WHERE id=?",
                                (text, existing[0])
                            )
                            new += 1
                        else:
                            skipped += 1
                    else:
                        skipped += 1
                    current += timedelta(days=1)
                    continue

                # Read and store
                blocks = self.read_day(date_str)
                if not blocks:
                    current += timedelta(days=1)
                    continue

                text = self.format_day_text(date_str, blocks)
                src_id = uuid4().hex[:16]
                now = time.time()
                event_time = datetime.strptime(date_str, "%Y-%m-%d").timestamp()

                metadata = {
                    "date": date_str,
                    "block_count": len(blocks),
                    "completed": sum(1 for b in blocks if b["status"] == "done"),
                    "categories": list(set(b["category"] for b in blocks)),
                }

                amber_db.execute(
                    "INSERT INTO sources (id, type, origin, raw_content, file_path, metadata, "
                    "created_at, event_time, processed, process_result) "
                    "VALUES (?, 'schedule', 'watchlace', ?, '', ?, ?, ?, 0, NULL)",
                    (src_id, text, json.dumps(metadata, ensure_ascii=False), now, event_time)
                )
                new += 1
                current += timedelta(days=1)

            amber_db.commit()
        finally:
            amber_db.close()

        return new, skipped

    def get_today_summary(self) -> str:
        """Get a quick text summary of today's schedule."""
        today = datetime.now().strftime("%Y-%m-%d")
        blocks = self.read_day(today)
        return self.format_day_text(today, blocks)

    def get_upcoming(self, hours: int = 4) -> List[dict]:
        """Get upcoming blocks in the next N hours."""
        now = datetime.now()
        end = now + timedelta(hours=hours)
        
        db = self._get_watchlace_db()
        try:
            rows = db.execute("""
                SELECT b.start_time, b.end_time, b.status,
                       t.title, t.priority, t.category
                FROM blocks b
                LEFT JOIN tasks t ON b.task_id = t.id
                WHERE b.start_time >= ? AND b.start_time <= ?
                  AND b.status != 'done'
                ORDER BY b.start_time
            """, (now.strftime("%Y-%m-%d %H:%M:%S"),
                  end.strftime("%Y-%m-%d %H:%M:%S"))).fetchall()

            return [
                {
                    "start_time": r[0],
                    "end_time": r[1],
                    "status": r[2],
                    "title": r[3] or "未命名",
                    "priority": r[4] or "normal",
                    "category": r[5] or "general",
                }
                for r in rows
            ]
        finally:
            db.close()
