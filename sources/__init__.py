"""Data source adapters for Amber Memory.

Each source converts raw data into the source layer format:
- WeChat messages and contacts
- Bear Notes
- Photos with EXIF + VLM scene description
- Links/articles with content extraction
- Voice/audio with STT transcription
- Daily journals (markdown files)
- Watchlace schedule/calendar data
"""

from .wechat import WeChatSource
from .bear import BearSource
from .photo import PhotoSource, PhotoMeta, PhotoContext
from .link import LinkSource, LinkContent
from .voice import VoiceSource, VoiceContent
from .journal import JournalProcessor
from .schedule import ScheduleSource

__all__ = [
    "WeChatSource", "BearSource",
    "PhotoSource", "PhotoMeta", "PhotoContext",
    "LinkSource", "LinkContent",
    "VoiceSource", "VoiceContent",
    "JournalProcessor",
    "ScheduleSource",
]
