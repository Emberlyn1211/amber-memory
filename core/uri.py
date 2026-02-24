"""URI system for Amber Memory.

Inspired by OpenViking's file-system paradigm.
Every memory has a unique URI like a file path.
"""

from dataclasses import dataclass
from typing import Optional
import hashlib


@dataclass
class URI:
    """Memory URI - unique identifier in file-system paradigm.
    
    Format: /{source}/{category}/{identifier}
    Examples:
        /wechat/messages/张三/2026-02-24
        /telegram/conversations/frankie/2026-02-24
        /calendar/events/2026-02-24/meeting-with-vc
        /self/thoughts/2026-02-24/about-memory
        /wechat/contacts/张三
        /wechat/moments/张三/2026-02-24
    """
    source: str      # wechat, telegram, calendar, self, photo, ...
    category: str    # messages, contacts, events, thoughts, moments, ...
    path: str        # rest of the path
    
    @property
    def full(self) -> str:
        return f"/{self.source}/{self.category}/{self.path}"
    
    @property
    def parent(self) -> Optional['URI']:
        parts = self.path.rsplit("/", 1)
        if len(parts) > 1:
            return URI(self.source, self.category, parts[0])
        return URI(self.source, self.category, "")
    
    @property 
    def hash_id(self) -> str:
        return hashlib.md5(self.full.encode()).hexdigest()[:16]
    
    @classmethod
    def parse(cls, uri_str: str) -> 'URI':
        parts = uri_str.strip("/").split("/", 2)
        if len(parts) < 2:
            raise ValueError(f"Invalid URI: {uri_str}")
        source = parts[0]
        category = parts[1]
        path = parts[2] if len(parts) > 2 else ""
        return cls(source, category, path)
    
    @classmethod
    def from_wechat_msg(cls, contact: str, date: str) -> 'URI':
        return cls("wechat", "messages", f"{contact}/{date}")
    
    @classmethod
    def from_wechat_contact(cls, contact: str) -> 'URI':
        return cls("wechat", "contacts", contact)
    
    @classmethod
    def from_telegram(cls, chat: str, date: str) -> 'URI':
        return cls("telegram", "conversations", f"{chat}/{date}")
    
    @classmethod
    def from_calendar(cls, date: str, event_id: str = "") -> 'URI':
        path = f"{date}/{event_id}" if event_id else date
        return cls("calendar", "events", path)
    
    @classmethod
    def from_thought(cls, date: str, topic: str = "") -> 'URI':
        path = f"{date}/{topic}" if topic else date
        return cls("self", "thoughts", path)
    
    def __str__(self) -> str:
        return self.full
    
    def __hash__(self) -> int:
        return hash(self.full)
    
    def __eq__(self, other) -> bool:
        if isinstance(other, URI):
            return self.full == other.full
        return False
