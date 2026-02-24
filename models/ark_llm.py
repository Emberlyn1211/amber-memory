"""ARK (火山方舟) LLM integration for Amber Memory.

Uses 豆包 models via volcengine ARK API for:
1. Memory extraction (raw data → structured L0/L1/L2)
2. Memory merging (combine old + new)
3. Importance scoring
4. Embedding generation (for semantic search)
"""

import json
import os
from typing import Optional

# ARK API endpoint
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"


class ArkLLM:
    """火山方舟 LLM client for Amber Memory."""

    def __init__(self, api_key: Optional[str] = None,
                 model: str = "doubao-seed-1-8-251228",
                 embedding_model: str = "doubao-embedding-large-text-240915"):
        self.api_key = api_key or os.environ.get("ARK_API_KEY", "")
        self.model = model
        self.embedding_model = embedding_model
        if not self.api_key:
            raise ValueError("ARK_API_KEY not set. Set env var or pass api_key.")

    async def chat(self, prompt: str, system: str = "") -> str:
        """Call ARK chat completion."""
        import httpx
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{ARK_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 2000,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def embed(self, texts: list) -> list:
        """Generate embeddings via ARK embedding API."""
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{ARK_BASE_URL}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.embedding_model,
                    "input": texts,
                    "encoding_format": "float",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return [item["embedding"] for item in data["data"]]

    def llm_fn(self):
        """Return an async function compatible with MemoryExtractor."""
        return self.chat

    async def extract_importance(self, content: str) -> float:
        """Use LLM to assess memory importance (0.0-1.0)."""
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
