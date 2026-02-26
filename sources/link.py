"""Link/article data source — fetches and processes URLs into memories.

When a user shares a URL, this module:
1. Fetches the page content (via requests or web_fetch)
2. Extracts readable text (title, body, metadata)
3. Optionally summarizes with LLM
4. Stores as source layer entry with full text and summary
"""

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from ..core.context import Context, ContextType

logger = logging.getLogger(__name__)


@dataclass
class LinkContent:
    """Extracted content from a URL."""
    url: str
    title: str = ""
    body: str = ""
    author: str = ""
    published: str = ""
    domain: str = ""
    word_count: int = 0
    language: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


class LinkSource:
    """Processes URLs into source layer entries."""

    # Max content length to store
    MAX_CONTENT_LENGTH = 10000
    # Max content to send to LLM for summarization
    MAX_LLM_INPUT = 3000

    def __init__(self, llm_fn=None):
        """
        Args:
            llm_fn: Optional async function(prompt: str) -> str for summarization
        """
        self.llm_fn = llm_fn

    def fetch(self, url: str, timeout: int = 15) -> LinkContent:
        """Fetch and extract readable content from a URL."""
        import requests

        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")

        content = LinkContent(url=url, domain=domain)

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
            resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            resp.raise_for_status()
            html = resp.text

            # Extract title
            title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
            if title_match:
                content.title = self._clean_html(title_match.group(1)).strip()[:200]

            # Extract meta description
            desc_match = re.search(
                r'<meta[^>]*name=["\']description["\'][^>]*content=["\'](.*?)["\']',
                html, re.IGNORECASE
            )
            if desc_match:
                content.meta["description"] = self._clean_html(desc_match.group(1))[:500]

            # Extract og:title, og:description
            for prop in ["og:title", "og:description", "og:author", "article:published_time"]:
                og_match = re.search(
                    rf'<meta[^>]*property=["\']{ re.escape(prop) }["\'][^>]*content=["\'](.*?)["\']',
                    html, re.IGNORECASE
                )
                if og_match:
                    key = prop.split(":")[-1]
                    content.meta[key] = self._clean_html(og_match.group(1))[:500]

            if "author" in content.meta:
                content.author = content.meta["author"]
            if "published_time" in content.meta:
                content.published = content.meta["published_time"]

            # Extract body text (simple approach: strip tags)
            body = self._extract_body(html)
            content.body = body[:self.MAX_CONTENT_LENGTH]
            content.word_count = len(body)

            # Detect language
            han_count = len(re.findall(r'[\u4e00-\u9fff]', body[:500]))
            content.language = "zh" if han_count > 20 else "en"

        except Exception as e:
            logger.error(f"Failed to fetch {url}: {e}")
            content.meta["error"] = str(e)

        return content

    async def summarize(self, content: LinkContent) -> str:
        """Use LLM to summarize the article."""
        if not self.llm_fn or not content.body:
            return ""

        text = content.body[:self.MAX_LLM_INPUT]
        title_hint = f"标题: {content.title}\n" if content.title else ""

        prompt = f"""{title_hint}总结以下文章的核心内容，用 2-3 句话概括要点。

{text}

只返回总结，不要其他内容。"""

        try:
            return await self.llm_fn(prompt)
        except Exception as e:
            logger.error(f"Summarization failed: {e}")
            return ""

    def to_source_dict(self, content: LinkContent, summary: str = "") -> dict:
        """Convert to source layer fields for AmberMemory.add_source()."""
        raw = summary or content.meta.get("description", "") or content.body[:500]
        if content.title:
            raw = f"{content.title}\n\n{raw}"

        return {
            "source_type": "link",
            "origin": content.domain or "web",
            "raw_content": raw,
            "file_path": "",
            "metadata": {
                "url": content.url,
                "title": content.title,
                "domain": content.domain,
                "author": content.author,
                "published": content.published,
                "word_count": content.word_count,
                "language": content.language,
            },
            "event_time": time.time(),
        }

    def to_context(self, content: LinkContent, summary: str = "",
                   uri: Optional[str] = None) -> Context:
        """Convert directly to a Context object."""
        from uuid import uuid4
        if not uri:
            slug = re.sub(r'[^\w]', '_', content.domain)[:20]
            uri = f"/web/{slug}/{uuid4().hex[:8]}"

        abstract = content.title or content.url[:50]
        overview = summary or content.meta.get("description", "") or content.body[:200]

        return Context(
            uri=uri,
            parent_uri="/web/" + (content.domain or "unknown"),
            abstract=abstract[:100],
            overview=overview[:500],
            content=content.body[:self.MAX_CONTENT_LENGTH] if content.body else overview,
            context_type=ContextType.OBJECT,
            category="object",
            importance=0.3,
            event_time=time.time(),
            tags=["link", content.domain],
            meta={
                "url": content.url,
                "title": content.title,
                "author": content.author,
            },
        )

    def _clean_html(self, text: str) -> str:
        """Remove HTML tags and decode entities."""
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'&amp;', '&', text)
        text = re.sub(r'&lt;', '<', text)
        text = re.sub(r'&gt;', '>', text)
        text = re.sub(r'&quot;', '"', text)
        text = re.sub(r'&#\d+;', '', text)
        text = re.sub(r'&\w+;', '', text)
        return text.strip()

    def _extract_body(self, html: str) -> str:
        """Extract readable body text from HTML."""
        # Remove script, style, nav, header, footer
        for tag in ["script", "style", "nav", "header", "footer", "aside", "noscript"]:
            html = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # Remove all tags
        text = re.sub(r'<[^>]+>', '\n', html)

        # Clean up whitespace
        lines = []
        for line in text.split("\n"):
            line = line.strip()
            if len(line) > 5:  # Skip very short lines (likely nav items)
                lines.append(line)

        return "\n".join(lines)
