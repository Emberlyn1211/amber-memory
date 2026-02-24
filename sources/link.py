"""Link/article data source adapter.

Processes URLs shared by the user:
1. Fetch the page content
2. Extract readable text (markdown)
3. Store as source layer entry
4. Generate memory from extracted content
"""

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


@dataclass
class LinkContent:
    """Extracted content from a URL."""
    url: str
    title: str
    domain: str
    text: str
    fetched_at: float


class LinkSource:
    """Processes URLs into source layer entries."""

    @staticmethod
    def parse_url(url: str) -> dict:
        """Extract metadata from URL."""
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        return {
            "url": url,
            "domain": domain,
            "url_hash": url_hash,
        }

    @staticmethod
    async def fetch(url: str, max_chars: int = 5000) -> Optional[LinkContent]:
        """Fetch and extract readable content from a URL."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
                })
                resp.raise_for_status()
                html = resp.text
        except Exception:
            return None

        # Simple HTML to text extraction
        title = ""
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
        if title_match:
            title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()

        # Strip HTML tags for basic text extraction
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        if len(text) > max_chars:
            text = text[:max_chars]

        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")

        return LinkContent(
            url=url,
            title=title or domain,
            domain=domain,
            text=text,
            fetched_at=time.time(),
        )

    @staticmethod
    def to_source_dict(link: LinkContent) -> dict:
        """Convert to source layer fields for AmberMemory.add_source()."""
        return {
            "source_type": "link",
            "origin": f"web/{link.domain}",
            "raw_content": f"# {link.title}\n\nURL: {link.url}\n\n{link.text}",
            "metadata": {
                "url": link.url,
                "domain": link.domain,
                "title": link.title,
                "fetched_at": link.fetched_at,
            },
            "event_time": link.fetched_at,
        }
