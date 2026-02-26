"""Claude LLM integration for Amber Memory via yunyi proxy.

Uses Anthropic Messages API format.
Drop-in replacement for ArkLLM — same interface (chat, embed, llm_fn).
"""

import json
import os
from typing import Optional


# yunyi proxy endpoint
CLAUDE_BASE_URL = "https://yunyi.rdzhvip.com/claude"
CLAUDE_API_KEY = "XW8ZUA29-1W1R-KTH4-NVVK-52SQN0J6KK74"


class ClaudeLLM:
    """Claude Opus via yunyi proxy for Amber Memory."""

    def __init__(self, api_key: Optional[str] = None,
                 model: str = "claude-opus-4-6",
                 base_url: Optional[str] = None):
        self.api_key = api_key or os.environ.get("CLAUDE_API_KEY", CLAUDE_API_KEY)
        self.model = model
        self.base_url = base_url or os.environ.get("CLAUDE_BASE_URL", CLAUDE_BASE_URL)

    async def chat(self, prompt: str, system: str = "") -> str:
        """Call Claude via Anthropic Messages API."""
        import httpx

        messages = [{"role": "user", "content": prompt}]

        body = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": messages,
            "temperature": 0.0,
        }
        if system:
            body["system"] = system

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/v1/messages",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            # Anthropic response: {"content": [{"type": "text", "text": "..."}]}
            content_blocks = data.get("content", [])
            texts = [b["text"] for b in content_blocks if b.get("type") == "text"]
            # Store usage for tracking
            self._last_usage = data.get("usage", {})
            return "\n".join(texts)

    async def embed(self, texts: list) -> list:
        """Embedding not supported via Claude — fall back to ARK embedder.
        Import ArkLLM for embedding only."""
        from .ark_llm import ArkLLM
        ark = ArkLLM()
        return await ark.embed(texts)

    def llm_fn(self):
        """Return async function compatible with MemoryExtractor."""
        return self.chat

    async def extract_importance(self, content: str) -> float:
        """Use Claude to assess memory importance (0.0-1.0)."""
        prompt = f"""评估以下内容的重要性（0.0-1.0）：
- 0.0-0.2: 完全不重要（天气闲聊、无意义寒暄）
- 0.3-0.5: 一般信息（日常安排、普通对话）
- 0.6-0.8: 重要信息（决定、计划、有用知识、人际关系）
- 0.9-1.0: 极其重要（人生大事、核心价值观、关键承诺）

内容：{content[:500]}

只返回一个数字，不要其他内容。"""
        try:
            result = await self.chat(prompt)
            return max(0.0, min(1.0, float(result.strip())))
        except Exception:
            return 0.5

    async def detect_emotion(self, content: str) -> str:
        """Detect emotion in content."""
        prompt = f"""判断以下内容的主要情感，从这些选项中选一个：
neutral, joy, sadness, anger, surprise, fear, love, nostalgia

内容：{content[:300]}

只返回一个英文单词，不要其他内容。"""
        try:
            result = await self.chat(prompt)
            emotion = result.strip().lower()
            valid = {"neutral", "joy", "sadness", "anger", "surprise", "fear", "love", "nostalgia"}
            return emotion if emotion in valid else "neutral"
        except Exception:
            return "neutral"
