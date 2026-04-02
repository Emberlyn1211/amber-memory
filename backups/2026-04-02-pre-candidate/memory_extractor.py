"""Memory Extractor for Amber Memory.

Extracts candidate memories from conversation using LLM + prompt templates.
Stage 1 writes candidate memories first; canonical contexts come later.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ..core.context import Context, ContextType
from ..prompts import render_prompt

logger = logging.getLogger(__name__)


DIMENSION_TO_TYPE = {
    "person": ContextType.PERSON,
    "activity": ContextType.ACTIVITY,
    "object": ContextType.OBJECT,
    "place": ContextType.MEMORY,
    "preference": ContextType.PREFERENCE,
    "taboo": ContextType.TABOO,
    "goal": ContextType.GOAL,
    "pattern": ContextType.PATTERN,
    "thought": ContextType.THOUGHT,
}

ALWAYS_MERGE_CATEGORIES = {"person", "preference"}
MERGE_SUPPORTED_CATEGORIES = {"person", "object", "preference", "pattern", "goal"}


@dataclass
class CandidateMemory:
    category: str
    abstract: str
    overview: str
    content: str
    source_session: str = ""
    user: str = ""
    language: str = "zh-CN"
    source_id: str = ""
    source_type: str = "chat"
    source_span: str = ""
    speaker_id: str = ""
    speaker_name: str = ""
    subject_guess: str = ""
    evidence_quote: str = ""
    confidence: float = 0.5
    extraction_reason: str = ""
    conflicts_with: Optional[List[str]] = None
    meta: Optional[Dict[str, Any]] = None

    def to_record(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "source_session": self.source_session,
            "source_span": self.source_span,
            "speaker_id": self.speaker_id,
            "speaker_name": self.speaker_name,
            "subject_guess": self.subject_guess,
            "memory_type": self.category,
            "abstract": self.abstract,
            "overview": self.overview,
            "content": self.content,
            "evidence_quote": self.evidence_quote,
            "confidence": self.confidence,
            "extraction_reason": self.extraction_reason,
            "language": self.language,
            "conflicts_with": self.conflicts_with or [],
            "meta": self.meta or {},
        }


@dataclass
class MergedMemoryPayload:
    abstract: str
    overview: str
    content: str
    reason: str = ""


def parse_json_from_response(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    patterns = [
        r'```json\s*\n?(.*?)\n?\s*```',
        r'```\s*\n?(.*?)\n?\s*```',
        r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1) if '```' in pattern else match.group(0))
            except (json.JSONDecodeError, IndexError):
                continue
    return None


def detect_language(messages: List[Dict[str, str]], fallback: str = "zh-CN") -> str:
    user_text = " ".join(
        m.get("content", "") for m in messages
        if m.get("role") == "user" and m.get("content")
    )
    if not user_text:
        return fallback
    han_count = len(re.findall(r'[\u4e00-\u9fff]', user_text))
    kana_count = len(re.findall(r'[\u3040-\u30ff]', user_text))
    if kana_count > 0:
        return "ja"
    if han_count > 5:
        return "zh-CN"
    return "en"


class MemoryExtractor:
    def __init__(self, llm_fn=None):
        self.llm_fn = llm_fn

    async def extract(
        self,
        messages: List[Dict[str, str]],
        user: str = "",
        session_id: str = "",
        summary: str = "",
        source_id: str = "",
        source_type: str = "chat",
    ) -> List[CandidateMemory]:
        if not self.llm_fn:
            logger.warning("No LLM function provided, skipping extraction")
            return []
        if not messages:
            return []

        formatted = "\n".join(
            f"[{m.get('role', 'user')}]: {m.get('content', '')}"
            for m in messages if m.get("content")
        )
        if not formatted:
            return []

        output_language = detect_language(messages)
        prompt = render_prompt(
            "compression.memory_extraction",
            {
                "summary": summary,
                "recent_messages": formatted,
                "user": user or "unknown",
                "output_language": output_language,
            },
        )

        try:
            response = await self.llm_fn(prompt)
            data = parse_json_from_response(response) or {}

            candidates = []
            for mem in data.get("memories", []):
                category = mem.get("category", "thought")
                if category not in DIMENSION_TO_TYPE:
                    category = "thought"

                candidates.append(CandidateMemory(
                    category=category,
                    abstract=mem.get("abstract", ""),
                    overview=mem.get("overview", ""),
                    content=mem.get("content", ""),
                    source_session=session_id,
                    user=user,
                    language=output_language,
                    source_id=source_id,
                    source_type=source_type,
                    source_span=mem.get("source_span", ""),
                    speaker_id=mem.get("speaker_id", ""),
                    speaker_name=mem.get("speaker_name", ""),
                    subject_guess=mem.get("subject_guess", user),
                    evidence_quote=mem.get("evidence_quote", ""),
                    confidence=float(mem.get("confidence", 0.5)),
                    extraction_reason=mem.get("reason", ""),
                    conflicts_with=mem.get("conflicts_with", []),
                    meta=mem.get("meta", {}),
                ))

            logger.info(f"Extracted {len(candidates)} candidate memories")
            return candidates
        except Exception as e:
            logger.error(f"Memory extraction failed: {e}")
            return []

    async def merge_memory_bundle(
        self,
        existing_abstract: str,
        existing_overview: str,
        existing_content: str,
        new_abstract: str,
        new_overview: str,
        new_content: str,
        category: str,
        output_language: str = "zh-CN",
    ) -> Optional[MergedMemoryPayload]:
        if not self.llm_fn:
            return None
        prompt = render_prompt(
            "compression.memory_merge_bundle",
            {
                "existing_abstract": existing_abstract,
                "existing_overview": existing_overview,
                "existing_content": existing_content,
                "new_abstract": new_abstract,
                "new_overview": new_overview,
                "new_content": new_content,
                "category": category,
                "output_language": output_language,
            },
        )
        try:
            response = await self.llm_fn(prompt)
            data = parse_json_from_response(response) or {}
            abstract = str(data.get("abstract", "")).strip()
            content = str(data.get("content", "")).strip()
            if not abstract or not content:
                logger.error("Merge bundle missing abstract/content")
                return None
            return MergedMemoryPayload(
                abstract=abstract,
                overview=str(data.get("overview", "")).strip(),
                content=content,
                reason=str(data.get("reason", "")).strip(),
            )
        except Exception as e:
            logger.error(f"Memory merge bundle failed: {e}")
            return None

    def candidate_to_context(self, candidate: CandidateMemory, session_id: str = "") -> Context:
        context_type = DIMENSION_TO_TYPE.get(candidate.category, ContextType.MEMORY)
        uri = f"amber://memories/{candidate.category}/{uuid4().hex[:12]}"
        return Context(
            uri=uri,
            parent_uri=f"amber://memories/{candidate.category}",
            abstract=candidate.abstract,
            overview=candidate.overview,
            content=candidate.content,
            context_type=context_type.value,
            category=candidate.category,
            source_session=session_id or candidate.source_session,
            meta={
                "confidence": candidate.confidence,
                "evidence_quote": candidate.evidence_quote,
                "speaker_id": candidate.speaker_id,
                "speaker_name": candidate.speaker_name,
                "subject_guess": candidate.subject_guess,
                "source_id": candidate.source_id,
                "source_span": candidate.source_span,
                **(candidate.meta or {}),
            },
        )

