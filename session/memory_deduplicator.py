"""Memory Deduplicator for Amber Memory.

LLM-assisted deduplication with candidate-level skip/create/none decisions
and per-existing merge/delete actions.

Adapted from OpenViking's MemoryDeduplicator, using our SQLite store
instead of VikingDB.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from ..core.context import Context
from ..prompts import render_prompt
from .memory_extractor import CandidateMemory, parse_json_from_response

logger = logging.getLogger(__name__)


class DedupDecision(str, Enum):
    SKIP = "skip"       # Duplicate, skip
    CREATE = "create"   # Create new memory
    NONE = "none"       # No candidate creation; resolve existing only


class MemoryActionDecision(str, Enum):
    MERGE = "merge"     # Merge candidate into existing
    DELETE = "delete"    # Delete existing memory


@dataclass
class ExistingMemoryAction:
    memory: Context
    decision: MemoryActionDecision
    reason: str = ""


@dataclass
class DedupResult:
    decision: DedupDecision
    candidate: CandidateMemory
    similar_memories: List[Context]
    actions: Optional[List[ExistingMemoryAction]] = None
    reason: str = ""


class MemoryDeduplicator:
    """Handles memory deduplication with vector similarity + LLM decision."""

    MAX_SIMILAR = 5
    SIMILARITY_THRESHOLD = 0.3

    def __init__(self, store, embedder=None, llm_fn=None):
        """
        Args:
            store: SQLiteStore instance
            embedder: Optional embedder for vector similarity search
            llm_fn: async function(prompt: str) -> str
        """
        self.store = store
        self.embedder = embedder
        self.llm_fn = llm_fn

    async def deduplicate(self, candidate: CandidateMemory) -> DedupResult:
        """Decide how to handle a candidate memory."""
        similar = self._find_similar(candidate)

        if not similar:
            return DedupResult(
                decision=DedupDecision.CREATE,
                candidate=candidate,
                similar_memories=[],
                actions=[],
                reason="No similar memories found",
            )

        if not self.llm_fn:
            # Without LLM, default to CREATE
            return DedupResult(
                decision=DedupDecision.CREATE,
                candidate=candidate,
                similar_memories=similar,
                actions=[],
                reason="No LLM available, defaulting to CREATE",
            )

        decision, reason, actions = await self._llm_decision(candidate, similar)
        return DedupResult(
            decision=decision,
            candidate=candidate,
            similar_memories=similar,
            actions=None if decision == DedupDecision.SKIP else actions,
            reason=reason,
        )

    def _find_similar(self, candidate: CandidateMemory) -> List[Context]:
        """Find similar existing memories using text search + optional vector search."""
        similar = []
        seen_uris = set()

        # Text search on abstract + content keywords
        keywords = candidate.abstract.split()[:5]
        for kw in keywords:
            if len(kw) < 2:
                continue
            results = self.store.search_text(kw, limit=10)
            for ctx in results:
                if ctx.uri not in seen_uris and ctx.category == candidate.category:
                    similar.append(ctx)
                    seen_uris.add(ctx.uri)

        # Also search by category
        category_results = self.store.search_by_category(candidate.category, limit=20)
        for ctx in category_results:
            if ctx.uri not in seen_uris:
                # Simple text overlap check
                if self._text_overlap(candidate.abstract, ctx.abstract) > 0.3:
                    similar.append(ctx)
                    seen_uris.add(ctx.uri)

        # TODO: Add vector similarity search when embedder is available
        # if self.embedder:
        #     embed_result = self.embedder.embed(candidate.abstract + " " + candidate.content[:200])
        #     vector_results = self.store.vector_search(embed_result.dense_vector, ...)

        return similar[:self.MAX_SIMILAR]

    @staticmethod
    def _text_overlap(a: str, b: str) -> float:
        """Simple character-level overlap ratio."""
        if not a or not b:
            return 0.0
        chars_a = set(a)
        chars_b = set(b)
        intersection = chars_a & chars_b
        union = chars_a | chars_b
        return len(intersection) / len(union) if union else 0.0

    async def _llm_decision(
        self,
        candidate: CandidateMemory,
        similar_memories: List[Context],
    ) -> Tuple[DedupDecision, str, List[ExistingMemoryAction]]:
        """Use LLM to decide deduplication action."""
        existing_formatted = []
        for i, mem in enumerate(similar_memories[:self.MAX_SIMILAR]):
            existing_formatted.append(
                f"{i + 1}. uri={mem.uri}\n   abstract={mem.abstract}"
            )

        prompt = render_prompt(
            "compression.dedup_decision",
            {
                "candidate_content": candidate.content,
                "candidate_abstract": candidate.abstract,
                "candidate_overview": candidate.overview,
                "existing_memories": "\n".join(existing_formatted),
            },
        )

        try:
            response = await self.llm_fn(prompt)
            data = parse_json_from_response(response) or {}
            return self._parse_decision(data, similar_memories)
        except Exception as e:
            logger.warning(f"LLM dedup failed: {e}")
            return DedupDecision.CREATE, f"LLM failed: {e}", []

    def _parse_decision(
        self,
        data: dict,
        similar_memories: List[Context],
    ) -> Tuple[DedupDecision, str, List[ExistingMemoryAction]]:
        """Parse LLM dedup response."""
        decision_str = str(data.get("decision", "create")).lower().strip()
        reason = str(data.get("reason", ""))

        decision_map = {
            "skip": DedupDecision.SKIP,
            "create": DedupDecision.CREATE,
            "none": DedupDecision.NONE,
            "merge": DedupDecision.NONE,  # backward compat
        }
        decision = decision_map.get(decision_str, DedupDecision.CREATE)

        raw_actions = data.get("list", [])
        if not isinstance(raw_actions, list):
            raw_actions = []

        # Legacy: {"decision":"merge"} without list
        if decision_str == "merge" and not raw_actions and similar_memories:
            raw_actions = [{
                "uri": similar_memories[0].uri,
                "decide": "merge",
                "reason": "Legacy merge",
            }]

        action_map = {
            "merge": MemoryActionDecision.MERGE,
            "delete": MemoryActionDecision.DELETE,
        }
        similar_by_uri = {m.uri: m for m in similar_memories}
        actions: List[ExistingMemoryAction] = []
        seen: Dict[str, MemoryActionDecision] = {}

        for item in raw_actions:
            if not isinstance(item, dict):
                continue
            action_str = str(item.get("decide", "")).lower().strip()
            action = action_map.get(action_str)
            if not action:
                continue

            memory = None
            uri = item.get("uri")
            if isinstance(uri, str):
                memory = similar_by_uri.get(uri)
            # Tolerate index-based
            if memory is None:
                index = item.get("index")
                if isinstance(index, int):
                    if 1 <= index <= len(similar_memories):
                        memory = similar_memories[index - 1]
                    elif 0 <= index < len(similar_memories):
                        memory = similar_memories[index]
            if memory is None:
                continue

            prev = seen.get(memory.uri)
            if prev and prev != action:
                actions = [a for a in actions if a.memory.uri != memory.uri]
                seen.pop(memory.uri, None)
                continue
            if prev == action:
                continue

            seen[memory.uri] = action
            actions.append(ExistingMemoryAction(
                memory=memory,
                decision=action,
                reason=str(item.get("reason", "")),
            ))

        # Normalize: skip should never carry actions
        if decision == DedupDecision.SKIP:
            return decision, reason, []

        # If any merge exists, decision must be none
        has_merge = any(a.decision == MemoryActionDecision.MERGE for a in actions)
        if decision == DedupDecision.CREATE and has_merge:
            decision = DedupDecision.NONE
            reason = f"{reason} | normalized:create+merge->none"

        # Create can only carry delete actions
        if decision == DedupDecision.CREATE:
            actions = [a for a in actions if a.decision == MemoryActionDecision.DELETE]

        return decision, reason, actions
