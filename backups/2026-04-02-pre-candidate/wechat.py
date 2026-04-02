"""WeChat data source adapter.

Reads from decrypted WeChat 4.x SQLite databases.
Converts messages, contacts, and sessions into Amber Memory contexts.

DB paths: ~/Library/Containers/com.tencent.xinWeChat/Data/Documents/
          xwechat_files/{wxid}/db_storage/
"""

import json
import os
import sqlite3
import struct
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.context import Context, ContextType
from ..core.uri import URI


# WeChat DB base path
WECHAT_DB_BASE = os.path.expanduser(
    "~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"
)
KEY_CACHE_PATH = os.path.expanduser("~/.wechat_key_cache.json")


@dataclass
class WeChatMessage:
    """A decoded WeChat message."""
    msg_id: int
    sender: str
    content: str
    timestamp: float
    msg_type: int
    is_self: bool
    chat_id: str  # conversation partner or group
    raw: Optional[bytes] = None


@dataclass
class WeChatContact:
    """A WeChat contact."""
    username: str       # wxid_xxx or group id
    nickname: str
    remark: str         # user-set alias
    avatar_url: str = ""
    is_group: bool = False


class WeChatSource:
    """Reads decrypted WeChat databases and produces Amber Memory contexts."""

    def __init__(self, wxid: Optional[str] = None, db_base: str = WECHAT_DB_BASE):
        self.db_base = Path(db_base)
        self.wxid = wxid or self._detect_wxid()
        self.db_dir = self.db_base / self.wxid / "db_storage"
        self.key_cache = self._load_key_cache()
        self._contact_cache: Dict[str, WeChatContact] = {}

    def _detect_wxid(self) -> str:
        """Auto-detect wxid from directory listing."""
        if not self.db_base.exists():
            raise FileNotFoundError(f"WeChat data dir not found: {self.db_base}")
        wxids = [d.name for d in self.db_base.iterdir()
                 if d.is_dir() and d.name.startswith("wxid_")]
        if not wxids:
            raise FileNotFoundError("No wxid directory found")
        return wxids[0]

    def _load_key_cache(self) -> Dict[str, str]:
        try:
            with open(KEY_CACHE_PATH) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _open_db(self, db_name: str) -> Optional[sqlite3.Connection]:
        """Open a decrypted WeChat database.
        
        Uses sqlcipher CLI to decrypt to a temp plaintext copy,
        then opens with regular sqlite3.
        """
        import subprocess
        import tempfile

        db_path = self.db_dir / db_name
        if not db_path.exists():
            return None

        # Get the raw key for this DB from cache
        salt_hex = db_path.read_bytes()[:16].hex()
        raw_key = self.key_cache.get(salt_hex)
        if not raw_key:
            return None

        # Decrypt to temp file using sqlcipher CLI
        tmp_path = Path(tempfile.mktemp(suffix=".db"))
        pragma_key = f"x'{raw_key}{salt_hex}'"
        
        sql_commands = f"""
PRAGMA key = "{pragma_key}";
PRAGMA cipher_page_size = 4096;
PRAGMA cipher_hmac_algorithm = HMAC_SHA512;
PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;
ATTACH DATABASE '{tmp_path}' AS plaintext KEY '';
SELECT sqlcipher_export('plaintext');
DETACH DATABASE plaintext;
"""
        try:
            result = subprocess.run(
                ["sqlcipher", str(db_path)],
                input=sql_commands, capture_output=True, text=True, timeout=30
            )
            if not tmp_path.exists() or tmp_path.stat().st_size == 0:
                return None
            
            conn = sqlite3.connect(str(tmp_path))
            conn.row_factory = sqlite3.Row
            # Verify it works
            conn.execute("SELECT count(*) FROM sqlite_master")
            return conn
        except Exception as e:
            import traceback; traceback.print_exc()
            if tmp_path.exists():
                tmp_path.unlink()
            return None

    def get_contacts(self) -> List[WeChatContact]:
        """Read contacts from contact.db."""
        conn = self._open_db("contact/contact.db")
        if not conn:
            return []
        try:
            rows = conn.execute("""
                SELECT username, nick_name, remark, big_head_url, is_in_chat_room
                FROM contact WHERE nick_name != '' OR remark != ''
            """).fetchall()
            contacts = []
            for row in rows:
                username = row["username"] or ""
                nickname = row["nick_name"] or ""
                remark = row["remark"] or ""
                is_group = "@chatroom" in username
                contact = WeChatContact(
                    username=username,
                    nickname=nickname,
                    remark=remark,
                    avatar_url=row["big_head_url"] or "",
                    is_group=is_group,
                )
                contacts.append(contact)
                self._contact_cache[username] = contact
                # Also cache by MD5 hash of username (used in Msg_ table names)
                import hashlib
                username_hash = hashlib.md5(username.encode()).hexdigest()
                self._contact_cache[username_hash] = contact
            return contacts
        finally:
            conn.close()

    def _parse_contact_remark(self, blob: Optional[bytes]) -> Tuple[str, str]:
        """Parse contact remark blob to extract nickname and remark."""
        if not blob:
            return ("", "")
        try:
            # WeChat stores contact info as protobuf-like blob
            # Field 1 = remark, Field 2 = nickname (roughly)
            nickname = ""
            remark = ""
            pos = 0
            while pos < len(blob):
                if pos + 2 > len(blob):
                    break
                field_tag = blob[pos]
                pos += 1
                if field_tag & 0x07 == 2:  # length-delimited
                    length = blob[pos]
                    pos += 1
                    if length > 0 and pos + length <= len(blob):
                        try:
                            text = blob[pos:pos+length].decode("utf-8", errors="ignore")
                            field_num = field_tag >> 3
                            if field_num == 1:
                                remark = text
                            elif field_num == 2:
                                nickname = text
                        except Exception:
                            pass
                    pos += length
                else:
                    pos += 1
            return (nickname, remark)
        except Exception:
            return ("", "")

    def get_messages(self, limit: int = 100, since: Optional[float] = None) -> List[WeChatMessage]:
        """Read messages from message DBs."""
        messages = []
        msg_dir = self.db_dir / "message"
        if not msg_dir.exists():
            return []

        for db_file in sorted(msg_dir.glob("message_*.db")):
            if "fts" in db_file.name or "resource" in db_file.name:
                continue
            conn = self._open_db(f"message/{db_file.name}")
            if not conn:
                continue
            try:
                tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
                ).fetchall()
                for table in tables:
                    tname = table["name"] if isinstance(table, sqlite3.Row) else table[0]
                    if since:
                        query = f"SELECT rowid, * FROM {tname} WHERE create_time > ? ORDER BY create_time DESC LIMIT ?"
                        params = [int(since), limit]
                    else:
                        query = f"SELECT rowid, * FROM {tname} ORDER BY create_time DESC LIMIT ?"
                        params = [limit]
                    try:
                        rows = conn.execute(query, params).fetchall()
                    except Exception:
                        continue
                    for row in rows:
                        msg = self._parse_message(row, tname)
                        if msg:
                            messages.append(msg)
            finally:
                conn.close()

        messages.sort(key=lambda m: m.timestamp, reverse=True)
        return messages[:limit]

    def _parse_message(self, row: sqlite3.Row, table_name: str) -> Optional[WeChatMessage]:
        """Parse a message row into WeChatMessage."""
        try:
            msg_id = row["local_id"] if "local_id" in row.keys() else 0
            create_time = row["create_time"] if "create_time" in row.keys() else 0
            msg_type = row["local_type"] if "local_type" in row.keys() else 0
            real_sender_id = row["real_sender_id"] if "real_sender_id" in row.keys() else 0

            # Decode content: check WCDB_CT flag and compress_content
            content = ""
            ct_flag = row["WCDB_CT_message_content"] if "WCDB_CT_message_content" in row.keys() else 0
            compress_content = row["compress_content"] if "compress_content" in row.keys() else None
            message_content = row["message_content"] if "message_content" in row.keys() else None

            if compress_content:
                try:
                    import zstandard as zstd
                    content = zstd.ZstdDecompressor().decompress(compress_content).decode("utf-8", errors="replace")
                except Exception:
                    pass

            if not content and message_content:
                if isinstance(message_content, bytes):
                    if ct_flag == 4:
                        try:
                            import zstandard as zstd
                            content = zstd.ZstdDecompressor().decompress(message_content).decode("utf-8", errors="replace")
                        except Exception:
                            content = ""
                    else:
                        try:
                            content = message_content.decode("utf-8", errors="replace")
                        except Exception:
                            content = ""
                elif isinstance(message_content, str):
                    content = message_content

            if not content or content.startswith("<msg>"):
                return None  # Skip empty and system XML messages

            # real_sender_id: 1=other, 2=self, 3=system
            is_self = (real_sender_id == 2)
            chat_id = table_name.replace("Msg_", "")

            return WeChatMessage(
                msg_id=msg_id,
                sender="self" if is_self else chat_id,
                content=content.strip(),
                timestamp=float(create_time),
                msg_type=msg_type,
                is_self=is_self,
                chat_id=chat_id,
            )
        except Exception:
            return None

    def get_contact_name(self, username: str) -> str:
        """Get display name for a contact."""
        if not self._contact_cache:
            self.get_contacts()
        contact = self._contact_cache.get(username)
        if contact:
            return contact.remark or contact.nickname or username
        return username

    # --- Convert to Amber Memory Contexts ---

    def messages_to_contexts(self, messages: List[WeChatMessage]) -> List[Context]:
        """Convert WeChat messages to Amber Memory contexts."""
        # Group messages by chat_id and date
        from collections import defaultdict
        from datetime import datetime

        grouped: Dict[str, List[WeChatMessage]] = defaultdict(list)
        for msg in messages:
            dt = datetime.fromtimestamp(msg.timestamp)
            key = f"{msg.chat_id}/{dt.strftime('%Y-%m-%d')}"
            grouped[key].append(msg)

        contexts = []
        for key, msgs in grouped.items():
            chat_id, date = key.rsplit("/", 1)
            contact_name = self.get_contact_name(chat_id)
            msgs.sort(key=lambda m: m.timestamp)

            # Build conversation text
            lines = []
            for m in msgs:
                sender = "我" if m.is_self else contact_name
                lines.append(f"[{sender}] {m.content}")
            full_text = "\n".join(lines)

            # L0: summary
            abstract = f"和{contact_name}的对话 ({date})"
            # L1: first few messages
            overview = "\n".join(lines[:5])
            if len(lines) > 5:
                overview += f"\n... (共{len(lines)}条消息)"

            uri = URI.from_wechat_msg(contact_name, date)
            ctx = Context(
                uri=uri.full,
                parent_uri=uri.parent.full if uri.parent else "",
                abstract=abstract,
                overview=overview,
                content=full_text,
                context_type=ContextType.EVENT,
                category="messages",
                tags=["wechat", contact_name],
                importance=0.3,  # default, can be upgraded by extractor
                event_time=msgs[0].timestamp,
                meta={"source": "wechat", "chat_id": chat_id,
                      "contact": contact_name, "msg_count": len(msgs)},
            )
            contexts.append(ctx)

        return contexts

    def contacts_to_contexts(self, contacts: List[WeChatContact]) -> List[Context]:
        """Convert WeChat contacts to entity contexts."""
        contexts = []
        for c in contacts:
            if not c.nickname and not c.remark:
                continue
            name = c.remark or c.nickname
            uri = URI.from_wechat_contact(name)
            ctx = Context(
                uri=uri.full,
                parent_uri=uri.parent.full if uri.parent else "",
                abstract=f"微信联系人: {name}",
                overview=f"微信号: {c.username}, 昵称: {c.nickname}, 备注: {c.remark}",
                content=f"微信联系人 {name}\n微信号: {c.username}\n昵称: {c.nickname}\n备注: {c.remark}\n群聊: {'是' if c.is_group else '否'}",
                context_type=ContextType.ENTITY,
                category="contacts",
                tags=["wechat", "contact"],
                importance=0.2,
                meta={"source": "wechat", "username": c.username, "is_group": c.is_group},
            )
            contexts.append(ctx)
        return contexts
