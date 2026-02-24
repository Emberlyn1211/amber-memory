"""Intent Analyzer for Amber Memory retrieval.

Analyzes query intent and generates retrieval plans across 8 dimensions.
Adapted from OpenViking's IntentAnalyzer.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..prompts import render_prompt
from ..session.memory_extractor import parse_json_from_response

logger = logging.getLogger(__name__)


@dataclass
class TypedQuery:
    query: str
    context_type: str       # person|activity|object|preference|taboo|goal|pattern|thought
    intent: str = ""
    priority: int = 3       # 1=highest, 5=lowest


@dataclass
class QueryPlan:
    queries: List[TypedQuery] = field(default_factory=list)
    reasoning: str = ""
    session_context: str = ""


class IntentAnalyzer:
    """Generates query plans from session context."""

    def __init__(self, llm_fn=None, max_recent: int = 10):
        self.llm_fn = llm_fn
        self.max_recent = max_recent

    async def analyze(
        self,
        messages: List[Dict[str, str]],
        current_message: str = "",
        summary: str = "",
        context_type: Optional[str] = None,
    ) -> QueryPlan:
        """Analyze intent and generate retrieval plan."""
        if not self.llm_fn:
            # Without LLM, create a simple text query
            return QueryPlan(
                queries=[TypedQuery(query=current_message, context_type="memory", priority=1)],
                reasoning="No LLM, using raw query",
            )

        recent = messages[-self.max_recent:] if messages else []
        recent_text = "\n".join(
            f"[{m.get('role', 'user')}]: {m.get('content', '')}"
            for m in recent if m.get("content")
        ) or "None"

        prompt = render_prompt(
            "retrieval.intent_analysis",
            {
                "compression_summary": summary or "None",
                "recent_messages": recent_text,
                "current_message": current_message or "None",
                "context_type": context_type or "",
            },
        )

        try:
            response = await self.llm_fn(prompt)
            data = parse_json_from_response(response) or {}

            queries = []
            valid_types = {
                "person", "activity", "object", "preference",
                "taboo", "goal", "pattern", "thought", "memory"
            }
            for q in data.get("queries", []):
                ct = q.get("context_type", "memory")
                if ct not in valid_types:
                    ct = "memory"
                queries.append(TypedQuery(
                    query=q.get("query", ""),
                    context_type=ct,
                    intent=q.get("intent", ""),
                    priority=q.get("priority", 3),
                ))

            return QueryPlan(
                queries=queries,
                reasoning=data.get("reasoning", ""),
                session_context=summary or "",
            )

        except Exception as e:
            logger.error(f"Intent analysis failed: {e}")
            return QueryPlan(
                queries=[TypedQuery(query=current_message, context_type="memory", priority=1)],
                reasoning=f"Fallback: {e}",
            )
