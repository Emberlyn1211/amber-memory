"""Session Compressor — orchestrates extract → dedup → store pipeline.

Adapted from OpenViking's SessionCompressor. Ties together:
- MemoryExtractor (LLM extraction)
- MemoryDeduplicator (LLM dedup)
- SQLiteStore (persistence)
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from ..core.context import Context
from ..storage.sqlite_store import SQLiteStore
from .memory_deduplicator import (
    DedupDecision, MemoryActionDecision, MemoryDeduplicator
)
from .memory_extractor import (
    CandidateMemory, MemoryExtractor, ALWAYS_MERGE_CATEGORIES,
    MERGE_SUPPORTED_CATEGORIES
)

logger = logging.getLogger(__name__)


@dataclass
class ExtractionStats:
    created: int = 0
    merged: int = 0
    deleted: int = 0
    skipped: int = 0

    def __str__(self):
        return f"created={self.created} merged={self.merged} deleted={self.deleted} skipped={self.skipped}"


class SessionCompressor:
    """Orchestrates memory extraction from conversation sessions."""

    def __init__(self, store: SQLiteStore, llm_fn=None, embedder=None):
        self.store = store
        self.extractor = MemoryExtractor(llm_fn=llm_fn)
        self.deduplicator = MemoryDeduplicator(
            store=store, embedder=embedder, llm_fn=llm_fn
        )
        self.llm_fn = llm_fn

    async def compress(
        self,
        messages: List[Dict[str, str]],
        user: str = "",
        session_id: str = "",
        summary: str = "",
    ) -> List[Context]:
        """Extract and store long-term memories from messages.

        Full pipeline: extract → dedup → merge/create → store.
        Returns list of created/updated Context objects.
        """
        if not messages:
            return []

        # Step 1: Extract candidates
        candidates = await self.extractor.extract(
            messages=messages, user=user,
            session_id=session_id, summary=summary,
        )
        if not candidates:
            return []

        # Step 2: Process each candidate through dedup pipeline
        memories: List[Context] = []
        stats = ExtractionStats()

        for candidate in candidates:
            ctx = await self._process_candidate(
                candidate, session_id, stats
            )
            if ctx:
                memories.append(ctx)

        logger.info(f"Session compression: {stats}")
        return memories

    async def _process_candidate(
        self,
        candidate: CandidateMemory,
        session_id: str,
        stats: ExtractionStats,
    ) -> Optional[Context]:
        """Process a single candidate through dedup and storage."""

        # Always-merge categories skip dedup
        if candidate.category in ALWAYS_MERGE_CATEGORIES:
            return await self._create_and_store(candidate, session_id, stats)

        # Dedup check
        result = await self.deduplicator.deduplicate(candidate)
        actions = result.actions or []
        decision = result.decision

        # Normalize: create + merge → none
        if decision == DedupDecision.CREATE and any(
            a.decision == MemoryActionDecision.MERGE for a in actions
        ):
            decision = DedupDecision.NONE

        if decision == DedupDecision.SKIP:
            stats.skipped += 1
            return None

        if decision == DedupDecision.NONE:
            if not actions:
                stats.skipped += 1
                return None
            for action in actions:
                if action.decision == MemoryActionDecision.DELETE:
                    self.store.delete(action.memory.uri)
                    stats.deleted += 1
                elif action.decision == MemoryActionDecision.MERGE:
                    if candidate.category in MERGE_SUPPORTED_CATEGORIES:
                        await self._merge_into_existing(
                            candidate, action.memory, stats
                        )
                    else:
                        stats.skipped += 1
            return None

        if decision == DedupDecision.CREATE:
            # Delete invalidated memories first
            for action in actions:
                if action.decision == MemoryActionDecision.DELETE:
                    self.store.delete(action.memory.uri)
                    stats.deleted += 1
            return await self._create_and_store(candidate, session_id, stats)

        stats.skipped += 1
        return None

    async def _create_and_store(
        self,
        candidate: CandidateMemory,
        session_id: str,
        stats: ExtractionStats,
    ) -> Optional[Context]:
        """Create Context from candidate and store it."""
        ctx = self.extractor.candidate_to_context(candidate, session_id)

        # Try to assess importance via LLM
        if self.llm_fn:
            try:
                from ..models.ark_llm import ArkLLM
                # Use a lightweight importance prompt
                importance_prompt = (
                    f"评估重要性(0.0-1.0)，只返回数字：\n{candidate.abstract}"
                )
                result = await self.llm_fn(importance_prompt)
                ctx.importance = max(0.0, min(1.0, float(result.strip())))
            except Exception:
                ctx.importance = 0.5

        self.store.put(ctx)
        stats.created += 1
        logger.info(f"Created memory: {ctx.uri} — {ctx.abstract[:60]}")
        return ctx

    async def _merge_into_existing(
        self,
        candidate: CandidateMemory,
        target: Context,
        stats: ExtractionStats,
    ) -> bool:
        """Merge candidate into an existing memory."""
        payload = await self.extractor.merge_memory_bundle(
            existing_abstract=target.abstract,
            existing_overview=target.overview,
            existing_content=target.content,
            new_abstract=candidate.abstract,
            new_overview=candidate.overview,
            new_content=candidate.content,
            category=candidate.category,
            output_language=candidate.language,
        )
        if not payload:
            stats.skipped += 1
            return False

        target.abstract = payload.abstract
        target.overview = payload.overview
        target.content = payload.content
        self.store.put(target)
        stats.merged += 1
        logger.info(f"Merged into: {target.uri} — {target.abstract[:60]}")
        return True
