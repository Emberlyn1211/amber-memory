"""Voice data source — processes audio files into text memories.

Pipeline:
1. Accept audio file (ogg, mp3, wav, m4a)
2. Transcribe via STT (讯飞 or other)
3. Store transcription as source layer entry
4. Optionally extract memories from transcription via LLM

Supports:
- WeChat voice messages (silk/ogg format)
- Watchlace voice recordings
- Any audio file with STT
"""

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.context import Context, ContextType

logger = logging.getLogger(__name__)


@dataclass
class VoiceContent:
    """Processed voice content."""
    file_path: str
    duration_seconds: float = 0.0
    transcription: str = ""
    language: str = "zh"
    speaker: str = ""
    timestamp: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)


class VoiceSource:
    """Processes voice/audio files into source layer entries."""

    # Supported audio formats
    SUPPORTED_FORMATS = {".ogg", ".mp3", ".wav", ".m4a", ".silk", ".amr", ".flac"}

    def __init__(self, stt_fn=None):
        """
        Args:
            stt_fn: async function(file_path: str) -> str
                    Transcribes audio file and returns text.
                    If None, voice processing is skipped.
        """
        self.stt_fn = stt_fn

    def validate_file(self, file_path: str) -> bool:
        """Check if file exists and is a supported format."""
        path = Path(file_path)
        if not path.exists():
            return False
        return path.suffix.lower() in self.SUPPORTED_FORMATS

    async def transcribe(self, file_path: str, speaker: str = "",
                         timestamp: float = None) -> VoiceContent:
        """Transcribe an audio file."""
        path = Path(file_path)
        content = VoiceContent(
            file_path=str(path.absolute()),
            timestamp=timestamp or path.stat().st_mtime,
            speaker=speaker,
        )

        # Get duration if ffprobe available
        content.duration_seconds = self._get_duration(file_path)

        if not self.stt_fn:
            logger.warning("No STT function provided, skipping transcription")
            return content

        try:
            text = await self.stt_fn(file_path)
            content.transcription = text.strip()

            # Detect language
            import re
            han_count = len(re.findall(r'[\u4e00-\u9fff]', text[:200]))
            content.language = "zh" if han_count > 5 else "en"

        except Exception as e:
            logger.error(f"Transcription failed for {file_path}: {e}")
            content.meta["error"] = str(e)

        return content

    def to_source_dict(self, voice: VoiceContent) -> dict:
        """Convert to source layer fields for AmberMemory.add_source()."""
        raw = voice.transcription or f"[语音消息 {voice.duration_seconds:.0f}秒]"
        if voice.speaker:
            raw = f"[{voice.speaker}]: {raw}"

        return {
            "source_type": "voice",
            "origin": "voice",
            "raw_content": raw,
            "file_path": voice.file_path,
            "metadata": {
                "duration": voice.duration_seconds,
                "speaker": voice.speaker,
                "language": voice.language,
            },
            "event_time": voice.timestamp,
        }

    def to_context(self, voice: VoiceContent, uri: Optional[str] = None) -> Context:
        """Convert directly to a Context object."""
        from uuid import uuid4
        from datetime import datetime

        if not uri:
            date = datetime.fromtimestamp(voice.timestamp).strftime("%Y-%m-%d")
            uri = f"/voice/{date}/{uuid4().hex[:8]}"

        text = voice.transcription or f"[语音消息 {voice.duration_seconds:.0f}秒]"
        abstract = text[:50].replace("\n", " ")
        if voice.speaker:
            abstract = f"[{voice.speaker}] {abstract}"

        return Context(
            uri=uri,
            parent_uri="/".join(uri.split("/")[:-1]),
            abstract=abstract,
            overview=text[:300],
            content=text,
            context_type=ContextType.ACTIVITY,
            category="activity",
            importance=0.3,
            event_time=voice.timestamp,
            tags=["voice", voice.language],
            meta={
                "file_path": voice.file_path,
                "duration": voice.duration_seconds,
                "speaker": voice.speaker,
            },
        )

    def _get_duration(self, file_path: str) -> float:
        """Get audio duration using ffprobe."""
        try:
            import subprocess
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", file_path],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
        except Exception:
            pass
        return 0.0

    async def process_directory(self, dir_path: str, speaker: str = "",
                                since: float = None) -> List[VoiceContent]:
        """Process all audio files in a directory."""
        path = Path(dir_path)
        if not path.exists():
            return []

        results = []
        for f in sorted(path.iterdir()):
            if not self.validate_file(str(f)):
                continue
            if since and f.stat().st_mtime < since:
                continue

            content = await self.transcribe(str(f), speaker=speaker)
            if content.transcription:
                results.append(content)

        return results
