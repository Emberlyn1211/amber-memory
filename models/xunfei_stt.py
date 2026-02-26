"""讯飞 Speech-to-Text (语音听写) via WebSocket API.

Usage:
    stt = XunfeiSTT()
    text = await stt.transcribe("/path/to/audio.wav")

Supports: pcm, wav, ogg, mp3, m4a (auto-converts to pcm via ffmpeg)
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urlparse

logger = logging.getLogger(__name__)

# 讯飞 credentials (same as TTS)
APPID = os.environ.get("XUNFEI_APPID", "2bbe1106")
API_KEY = os.environ.get("XUNFEI_API_KEY", "6dfb5a9f68ab53e45a37b91433f9c451")
API_SECRET = os.environ.get("XUNFEI_API_SECRET", "YmJjYTNlYWJmOWEyMDNkZTJkZmY3OTA4")

# WebSocket endpoint for 语音听写
WSS_URL = "wss://iat-api.xfyun.cn/v2/iat"

# Audio config
FRAME_SIZE = 8000  # bytes per frame
FRAME_INTERVAL = 0.04  # seconds between frames


class XunfeiSTT:
    """讯飞语音听写 WebSocket client."""

    def __init__(self, appid=APPID, api_key=API_KEY, api_secret=API_SECRET,
                 language="zh_cn", domain="iat", accent="mandarin"):
        self.appid = appid
        self.api_key = api_key
        self.api_secret = api_secret
        self.language = language
        self.domain = domain
        self.accent = accent

    def _build_auth_url(self) -> str:
        """Build authenticated WebSocket URL with HMAC-SHA256 signature."""
        parsed = urlparse(WSS_URL)
        now = datetime.utcnow()
        date = now.strftime("%a, %d %b %Y %H:%M:%S GMT")

        signature_origin = (
            f"host: {parsed.netloc}\n"
            f"date: {date}\n"
            f"GET {parsed.path} HTTP/1.1"
        )
        signature = base64.b64encode(
            hmac.new(
                self.api_secret.encode(),
                signature_origin.encode(),
                hashlib.sha256
            ).digest()
        ).decode()

        authorization_origin = (
            f'api_key="{self.api_key}", '
            f'algorithm="hmac-sha256", '
            f'headers="host date request-line", '
            f'signature="{signature}"'
        )
        authorization = base64.b64encode(authorization_origin.encode()).decode()

        params = {
            "authorization": authorization,
            "date": date,
            "host": parsed.netloc,
        }
        return f"{WSS_URL}?{urlencode(params)}"

    def _convert_to_pcm(self, file_path: str) -> str:
        """Convert audio file to 16kHz 16bit mono PCM using ffmpeg."""
        suffix = Path(file_path).suffix.lower()
        if suffix == ".pcm":
            return file_path

        out_path = tempfile.mktemp(suffix=".pcm")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", file_path,
                 "-ar", "16000", "-ac", "1", "-f", "s16le", out_path],
                capture_output=True, timeout=30, check=True
            )
            return out_path
        except Exception as e:
            logger.error(f"ffmpeg conversion failed: {e}")
            raise

    async def transcribe(self, file_path: str) -> str:
        """Transcribe audio file to text.
        
        Args:
            file_path: Path to audio file (wav, ogg, mp3, m4a, pcm)
            
        Returns:
            Transcribed text string
        """
        try:
            import websockets
        except ImportError:
            raise ImportError("pip install websockets")

        # Convert to PCM
        pcm_path = self._convert_to_pcm(file_path)
        cleanup_pcm = pcm_path != file_path

        try:
            with open(pcm_path, "rb") as f:
                audio_data = f.read()
        finally:
            if cleanup_pcm and os.path.exists(pcm_path):
                os.unlink(pcm_path)

        if not audio_data:
            return ""

        url = self._build_auth_url()
        result_parts = []

        try:
            async with websockets.connect(url) as ws:
                # Send audio in frames
                total = len(audio_data)
                offset = 0
                frame_num = 0

                while offset < total:
                    chunk = audio_data[offset:offset + FRAME_SIZE]
                    offset += FRAME_SIZE

                    # Determine status: 0=first, 1=middle, 2=last
                    if frame_num == 0:
                        status = 0
                    elif offset >= total:
                        status = 2
                    else:
                        status = 1

                    payload = {
                        "common": {"app_id": self.appid},
                        "business": {
                            "language": self.language,
                            "domain": self.domain,
                            "accent": self.accent,
                            "vad_eos": 3000,
                            "dwa": "wpgs",  # 动态修正
                        },
                        "data": {
                            "status": status,
                            "format": "audio/L16;rate=16000",
                            "encoding": "raw",
                            "audio": base64.b64encode(chunk).decode(),
                        },
                    }

                    # Only send common+business on first frame
                    if frame_num > 0:
                        del payload["common"]
                        del payload["business"]

                    await ws.send(json.dumps(payload))
                    frame_num += 1

                    # Small delay between frames
                    if status != 2:
                        await asyncio.sleep(FRAME_INTERVAL)

                # Receive results
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=10)
                        resp = json.loads(msg)

                        code = resp.get("code", -1)
                        if code != 0:
                            logger.error(f"讯飞 STT error: code={code}, msg={resp.get('message')}")
                            break

                        data = resp.get("data", {})
                        result = data.get("result", {})
                        ws_list = result.get("ws", [])

                        for ws_item in ws_list:
                            for cw in ws_item.get("cw", []):
                                word = cw.get("w", "")
                                if word:
                                    result_parts.append(word)

                        # Check if final result
                        if data.get("status") == 2:
                            break

                    except asyncio.TimeoutError:
                        break

        except Exception as e:
            logger.error(f"讯飞 STT WebSocket error: {e}")
            raise

        return "".join(result_parts).strip()


async def create_stt_fn():
    """Create an STT function for VoiceSource."""
    stt = XunfeiSTT()
    return stt.transcribe
