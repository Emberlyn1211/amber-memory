"""Photo/image data source adapter.

Processes photos from Watchlace camera or any image:
1. Extract EXIF metadata (time, location, camera)
2. Call 豆包 VLM for scene description
3. Store as source layer entry with semantic description
4. All images must have timestamp; location when available

Designed for Watchlace's first-person POV camera:
- Every 12 seconds, take a photo
- Local AI filters unusable ones
- Remaining photos get scene descriptions
- Scene descriptions chain together to form "what you did today"
"""

import os
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class PhotoMeta:
    """Metadata extracted from a photo."""
    file_path: str
    timestamp: float                    # unix timestamp (required)
    latitude: Optional[float] = None    # GPS lat
    longitude: Optional[float] = None   # GPS lng
    location_name: str = ""             # reverse geocoded name
    camera: str = ""                    # camera/device name
    width: int = 0
    height: int = 0
    exif: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PhotoContext:
    """A photo with its semantic description."""
    meta: PhotoMeta
    description: str = ""       # VLM-generated scene description
    objects: List[str] = field(default_factory=list)   # detected objects
    activity: str = ""          # inferred activity ("开会", "吃饭", "走路")
    mood: str = ""              # inferred mood from scene


class PhotoSource:
    """Processes photos into source layer entries."""

    def __init__(self, vlm_fn=None):
        """
        Args:
            vlm_fn: async function(image_path: str, prompt: str) -> str
                    Calls VLM (豆包) with image and returns description.
                    If None, only extracts EXIF metadata.
        """
        self.vlm_fn = vlm_fn

    def extract_meta(self, file_path: str) -> PhotoMeta:
        """Extract EXIF metadata from an image file."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {file_path}")

        meta = PhotoMeta(
            file_path=str(path.absolute()),
            timestamp=path.stat().st_mtime,  # fallback to file mtime
        )

        try:
            # Try to read EXIF with PIL
            from PIL import Image
            from PIL.ExifTags import TAGS, GPSTAGS

            img = Image.open(file_path)
            meta.width, meta.height = img.size
            exif_data = img._getexif()

            if exif_data:
                for tag_id, value in exif_data.items():
                    tag = TAGS.get(tag_id, tag_id)
                    if tag == "DateTimeOriginal":
                        try:
                            from datetime import datetime
                            dt = datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
                            meta.timestamp = dt.timestamp()
                        except Exception:
                            pass
                    elif tag == "GPSInfo":
                        meta.latitude, meta.longitude = self._parse_gps(value)
                    elif tag == "Make":
                        meta.camera = str(value)
                    meta.exif[str(tag)] = str(value)[:100]
        except ImportError:
            # PIL not available, use basic file info
            pass
        except Exception:
            pass

        return meta

    def _parse_gps(self, gps_info: dict) -> tuple:
        """Parse GPS EXIF data to lat/lng floats."""
        try:
            from PIL.ExifTags import GPSTAGS
            gps = {}
            for key, val in gps_info.items():
                tag = GPSTAGS.get(key, key)
                gps[tag] = val

            def to_degrees(values):
                d, m, s = [float(v) for v in values]
                return d + m / 60.0 + s / 3600.0

            lat = to_degrees(gps.get("GPSLatitude", (0, 0, 0)))
            if gps.get("GPSLatitudeRef", "N") == "S":
                lat = -lat
            lng = to_degrees(gps.get("GPSLongitude", (0, 0, 0)))
            if gps.get("GPSLongitudeRef", "E") == "W":
                lng = -lng
            return (lat, lng) if lat != 0 or lng != 0 else (None, None)
        except Exception:
            return (None, None)

    async def describe(self, file_path: str) -> PhotoContext:
        """Extract metadata and generate semantic description."""
        meta = self.extract_meta(file_path)
        ctx = PhotoContext(meta=meta)

        if self.vlm_fn:
            prompt = """描述这张照片中的场景。用中文回答，包含：
1. 场景描述（一句话）
2. 看到的物品/人物
3. 推测的活动（在做什么）
4. 场景氛围

格式：
场景：...
物品：...
活动：...
氛围：..."""
            try:
                response = await self.vlm_fn(file_path, prompt)
                ctx.description = response

                # Parse structured fields
                for line in response.split("\n"):
                    line = line.strip()
                    if line.startswith("场景：") or line.startswith("场景:"):
                        ctx.description = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                    elif line.startswith("物品：") or line.startswith("物品:"):
                        ctx.objects = [o.strip() for o in line.split("：", 1)[-1].split(":", 1)[-1].split("、")]
                    elif line.startswith("活动：") or line.startswith("活动:"):
                        ctx.activity = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                    elif line.startswith("氛围：") or line.startswith("氛围:"):
                        ctx.mood = line.split("：", 1)[-1].split(":", 1)[-1].strip()
            except Exception:
                pass

        return ctx

    def to_source_dict(self, photo_ctx: PhotoContext) -> dict:
        """Convert to source layer fields for AmberMemory.add_source()."""
        meta = photo_ctx.meta
        description = photo_ctx.description or f"照片 ({meta.width}x{meta.height})"

        raw_content = description
        if photo_ctx.activity:
            raw_content = f"[{photo_ctx.activity}] {description}"
        if photo_ctx.objects:
            raw_content += f"\n物品: {', '.join(photo_ctx.objects)}"

        metadata = {
            "width": meta.width,
            "height": meta.height,
            "camera": meta.camera,
            "timestamp": meta.timestamp,
        }
        if meta.latitude is not None:
            metadata["latitude"] = meta.latitude
            metadata["longitude"] = meta.longitude
        if meta.location_name:
            metadata["location_name"] = meta.location_name

        return {
            "source_type": "image",
            "origin": "camera",
            "raw_content": raw_content,
            "file_path": meta.file_path,
            "metadata": metadata,
            "event_time": meta.timestamp,
        }
