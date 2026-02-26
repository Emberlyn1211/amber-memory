"""AmberMemory client - the main interface.

Usage:
    from amber_memory import AmberMemory

    mem = AmberMemory("~/.amber/memory.db")
    
    # Store a memory
    mem.remember("Frankie喜欢泰斯卡风暴威士忌", source="telegram", importance=0.7)
    
    # Recall (hybrid: text + vector + decay)
    results = await mem.recall("Frankie喜欢喝什么酒")
    
    # Compress a session (extract → dedup → store)
    memories = await mem.compress_session(messages, user="Frankie")
    
    # Smart recall with intent analysis
    results = await mem.smart_recall(messages, "他喜欢什么酒？")
    
    # Ingest data sources
    mem.ingest_wechat()
    mem.ingest_bear(tag="随感/Amber")
"""

import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .core.context import Context, ContextType, DecayParams, DEFAULT_DECAY
from .core.uri import URI
from .storage.sqlite_store import SQLiteStore
from .retrieve.retriever import Retriever
from .retrieve.intent_analyzer import IntentAnalyzer
from .session.compressor import SessionCompressor
from .session.memory_extractor import MemoryExtractor
from .session.life_proposals import LifeProposalEngine
from .graph import PeopleGraph
from .graph.patterns import PatternDetector


class AmberMemory:
    """Main interface to Amber's memory system."""

    def __init__(self, db_path: str = "~/.amber/memory.db", llm_fn=None,
                 embed_fn=None, embedder=None,
                 decay_params: DecayParams = DEFAULT_DECAY):
        """
        Args:
            db_path: Path to SQLite database
            llm_fn: Optional async function(prompt: str) -> str for LLM calls
            embed_fn: Optional async function(texts: list) -> list[list[float]]
            embedder: Optional ArkEmbedder instance (used by deduplicator)
            decay_params: Memory decay configuration
        """
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteStore(str(self.db_path))
        self.llm_fn = llm_fn
        self.embed_fn = embed_fn
        self.decay_params = decay_params

        # Session pipeline: extract → dedup → store
        self.compressor = SessionCompressor(
            store=self.store, llm_fn=llm_fn, embedder=embedder,
        )
        # Retrieval: hybrid search + intent analysis
        self.retriever = Retriever(
            store=self.store, embed_fn=embed_fn, decay_params=decay_params,
        )
        self.intent_analyzer = IntentAnalyzer(llm_fn=llm_fn)
        # People graph
        self.people = PeopleGraph(store=self.store)
        # Pattern detection
        self.patterns = PatternDetector(store=self.store)
        # Life proposals
        self.proposals = LifeProposalEngine(
            store=self.store, patterns=self.patterns,
            llm_fn=llm_fn, decay_params=decay_params,
        )

    # --- Core API ---

    def remember(self, content: str, source: str = "self",
                 importance: float = 0.5, tags: Optional[List[str]] = None,
                 emotion: str = "neutral", event_time: Optional[float] = None,
                 uri: Optional[str] = None, category: str = "memory") -> Context:
        """Store a memory directly (no LLM)."""
        now = time.time()
        date = datetime.fromtimestamp(event_time or now).strftime("%Y-%m-%d")
        
        if not uri:
            from uuid import uuid4
            short_id = uuid4().hex[:8]
            uri = f"/{source}/memories/{date}/{short_id}"

        ctx = Context(
            uri=uri,
            parent_uri="/".join(uri.split("/")[:-1]),
            abstract=content[:30].replace("\n", " "),
            overview=content[:150].replace("\n", " "),
            content=content,
            context_type=ContextType.MEMORY,
            category=category,
            tags=tags or [],
            emotion=emotion,
            importance=importance,
            event_time=event_time or now,
        )
        self.store.put(ctx)
        return ctx

    async def compress_session(
        self,
        messages: List[Dict[str, str]],
        user: str = "",
        session_id: str = "",
        summary: str = "",
    ) -> List[Context]:
        """Extract and store long-term memories from a conversation session.
        
        Full pipeline: LLM extract → dedup → merge/create → store → index.
        """
        memories = await self.compressor.compress(
            messages=messages, user=user,
            session_id=session_id, summary=summary,
        )
        # Index new memories for vector search
        for ctx in memories:
            await self.retriever.index_context(ctx)
        return memories

    def recall(self, query: str, limit: int = 10,
               respect_taboos: bool = True) -> List[Tuple[Context, float]]:
        """Simple text recall with decay scoring (sync)."""
        results = self.store.search_text(query, limit=limit * 3)
        
        if respect_taboos:
            taboos = self.store.list_taboos(active_only=True)
            if taboos:
                results = [
                    ctx for ctx in results
                    if not any(t["pattern"] in f"{ctx.abstract} {ctx.content}" for t in taboos)
                ]
        
        scored = [(ctx, ctx.compute_score(self.decay_params)) for ctx in results]
        scored.sort(key=lambda x: x[1], reverse=True)
        for ctx, _ in scored[:limit]:
            self.store.touch(ctx.uri)
        return scored[:limit]

    async def hybrid_recall(self, query: str, limit: int = 10,
                            text_weight: float = 0.4,
                            vector_weight: float = 0.4,
                            decay_weight: float = 0.2) -> List[Tuple[Context, float]]:
        """Hybrid recall: text + vector + decay (async)."""
        return await self.retriever.search(
            query, limit=limit,
            text_weight=text_weight,
            vector_weight=vector_weight,
            decay_weight=decay_weight,
        )

    async def smart_recall(
        self,
        messages: List[Dict[str, str]],
        current_message: str,
        summary: str = "",
        limit: int = 10,
    ) -> List[Tuple[Context, float]]:
        """Intent-aware recall: analyze query → generate plan → retrieve."""
        plan = await self.intent_analyzer.analyze(
            messages=messages,
            current_message=current_message,
            summary=summary,
        )
        
        all_results: Dict[str, Tuple[Context, float]] = {}
        for typed_query in sorted(plan.queries, key=lambda q: q.priority):
            results = await self.retriever.search(
                typed_query.query, limit=limit,
            )
            for ctx, score in results:
                priority_boost = 1.0 + (5 - typed_query.priority) * 0.1
                boosted = score * priority_boost
                if ctx.uri not in all_results or all_results[ctx.uri][1] < boosted:
                    all_results[ctx.uri] = (ctx, boosted)

        ranked = sorted(all_results.values(), key=lambda x: x[1], reverse=True)
        return ranked[:limit]

    def recall_by_time(self, start: float, end: float, limit: int = 50) -> List[Context]:
        return self.store.search_by_time_range(start, end, limit)

    def recall_by_tag(self, tag: str, limit: int = 20) -> List[Context]:
        return self.store.search_by_tag(tag, limit)

    def top(self, limit: int = 20) -> List[Tuple[Context, float]]:
        return self.store.get_top_memories(limit, self.decay_params)

    def fading(self, threshold: float = 0.1) -> List[Context]:
        return self.store.get_decayed(threshold, self.decay_params)

    def forget(self, uri: str) -> bool:
        return self.store.delete(uri)

    def link(self, uri_a: str, uri_b: str, relation: str = "related"):
        self.store.add_link(uri_a, uri_b, relation)

    def get(self, uri: str) -> Optional[Context]:
        ctx = self.store.get(uri)
        if ctx:
            self.store.touch(uri)
        return ctx

    # --- Source Layer ---

    def add_source(self, source_type: str, origin: str, raw_content: str = "",
                   file_path: str = "", metadata: Optional[Dict] = None,
                   event_time: Optional[float] = None) -> str:
        from uuid import uuid4
        source_id = uuid4().hex[:16]
        self.store.put_source(source_id, source_type, origin,
                              raw_content, file_path, metadata, event_time)
        return source_id

    def process_sources(self, limit: int = 50) -> int:
        unprocessed = self.store.list_unprocessed_sources(limit)
        count = 0
        for src in unprocessed:
            uris = self._process_one_source(src)
            self.store.mark_source_processed(src["id"], uris)
            count += len(uris)
        return count

    def _process_one_source(self, src: Dict) -> List[str]:
        content = src["raw_content"]
        if not content or len(content.strip()) < 10:
            return []

        triggered = self.store.check_taboos(content)
        if triggered:
            return []

        now = time.time()
        date = datetime.fromtimestamp(src.get("event_time") or now).strftime("%Y-%m-%d")
        from uuid import uuid4
        short_id = uuid4().hex[:8]
        uri = f"/{src['origin']}/memories/{date}/{short_id}"

        ctx = Context(
            uri=uri,
            parent_uri=f"/{src['origin']}/memories/{date}",
            abstract=content[:30].replace("\n", " "),
            overview=content[:150].replace("\n", " "),
            content=content,
            context_type=self._guess_context_type(src),
            importance=0.4,
            event_time=src.get("event_time"),
            tags=[src["origin"], src["type"]],
            meta={"source_id": src["id"], "source_type": src["type"],
                  "source_origin": src["origin"]},
        )
        self.store.put(ctx)
        return [uri]

    def _guess_context_type(self, src: Dict) -> str:
        t = src.get("type", "")
        mapping = {
            "chat": ContextType.ACTIVITY, "image": ContextType.ACTIVITY,
            "schedule": ContextType.ACTIVITY, "link": ContextType.OBJECT,
            "location": ContextType.OBJECT,
        }
        if t in mapping:
            return mapping[t]
        if t in ("text", "voice") and src.get("origin") in ("diary", "bear"):
            return ContextType.THOUGHT
        return ContextType.MEMORY

    def trace_source(self, uri: str) -> Optional[Dict]:
        ctx = self.store.get(uri)
        if not ctx or not ctx.meta.get("source_id"):
            return None
        return self.store.get_source(ctx.meta["source_id"])

    # --- Taboo System ---

    def add_taboo(self, pattern: str, description: str = "", scope: str = "global") -> str:
        return self.store.add_taboo(pattern, description, scope)

    def list_taboos(self) -> List[Dict]:
        return self.store.list_taboos()

    def remove_taboo(self, taboo_id: str) -> bool:
        return self.store.remove_taboo(taboo_id)

    # --- Data Source Ingestion ---

    def check_proposals(self, context: str = "") -> list:
        """Check all heuristic triggers and return life proposals."""
        return self.proposals.check_all()

    async def check_proposals_with_llm(self, context: str = "") -> list:
        """Check all triggers including LLM-powered proposals."""
        return await self.proposals.check_all_with_llm(context)

    def social_prep(self, person_name: str):
        """Generate social prep context before meeting someone."""
        return self.proposals.check_social_prep(person_name)

    def dismiss_proposal(self, proposal_id: str):
        """Dismiss a proposal."""
        self.proposals.dismiss(proposal_id)

    def act_on_proposal(self, proposal_id: str):
        """Mark a proposal as acted upon."""
        self.proposals.act_on(proposal_id)

    def list_proposals(self, include_dismissed: bool = False, limit: int = 10):
        """List recent proposals."""
        return self.proposals.list_proposals(include_dismissed, limit)

    # --- OpenClaw Integration ---

    def session_context(self, max_chars: int = 3000, **kwargs) -> str:
        """Generate memory context for a new OpenClaw session."""
        from .integrations import OpenClawIntegration
        integration = OpenClawIntegration(self)
        return integration.generate_session_context(max_chars=max_chars, **kwargs)

    def recall_context(self, query: str, limit: int = 8, max_chars: int = 2000) -> str:
        """Generate recall context for a specific query."""
        from .integrations import OpenClawIntegration
        integration = OpenClawIntegration(self)
        return integration.generate_recall_context(query, limit, max_chars)

    def person_context(self, name: str, max_chars: int = 1500) -> str:
        """Generate context about a specific person."""
        from .integrations import OpenClawIntegration
        integration = OpenClawIntegration(self)
        return integration.generate_person_context(name, max_chars)

    # --- MEMORY.md Sync ---

    def export_memory_md(self, md_path: str = "MEMORY.md", **kwargs) -> str:
        """Export DB to MEMORY.md format."""
        from .sync import MemoryMdSync
        sync = MemoryMdSync(self)
        return sync.export_to_md(md_path, **kwargs)

    def import_memory_md(self, md_path: str = "MEMORY.md") -> int:
        """Import MEMORY.md into DB."""
        from .sync import MemoryMdSync
        sync = MemoryMdSync(self)
        return sync.import_from_md(md_path)

    # --- Data Source Ingestion (original) ---

    def ingest_wechat(self, limit: int = 100, since: Optional[float] = None) -> int:
        from .sources.wechat import WeChatSource
        try:
            wx = WeChatSource()
        except FileNotFoundError:
            return 0
        count = 0
        for ctx in wx.contacts_to_contexts(wx.get_contacts()):
            if not self.store.get(ctx.uri):
                self.store.put(ctx)
                count += 1
        for ctx in wx.messages_to_contexts(wx.get_messages(limit=limit, since=since)):
            if not self.store.get(ctx.uri):
                self.store.put(ctx)
                count += 1
        return count

    def ingest_bear(self, tag: Optional[str] = None, limit: int = 500) -> int:
        from .sources.bear import BearSource
        try:
            bear = BearSource()
        except FileNotFoundError:
            return 0
        count = 0
        try:
            for ctx in bear.notes_to_contexts(bear.get_notes(tag=tag, limit=limit)):
                if not self.store.get(ctx.uri):
                    self.store.put(ctx)
                    count += 1
        finally:
            bear.close()
        return count

    # --- Indexing ---

    async def reindex(self, batch_size: int = 20) -> int:
        """Reindex all memories for vector search."""
        return await self.retriever.reindex_all(batch_size=batch_size)

    # --- Stats ---

    def stats(self) -> Dict[str, Any]:
        base = self.store.stats()
        base["db_path"] = str(self.db_path)
        base["decay_half_life_days"] = self.decay_params.half_life_days
        base["has_llm"] = self.llm_fn is not None
        base["has_embeddings"] = self.embed_fn is not None
        return base

    def __repr__(self):
        return f"AmberMemory(db={self.db_path}, memories={self.store.count()})"

    def close(self):
        self.store.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
