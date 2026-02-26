"""Amber Memory - AI Agent 的记忆系统

Core: 8-dimension context model + decay algorithm + SQLite storage
Session: LLM extraction → dedup → merge/create → store → life proposals
Retrieval: text + vector + decay hybrid search + intent analysis
Sources: WeChat, Bear Notes, links, photos, journals, voice
Integration: OpenClaw context injection, MEMORY.md sync
"""
from .core.context import Context, ContextType, MemoryCategory, DecayParams
from .core.uri import URI
from .storage.sqlite_store import SQLiteStore
from .session.memory_extractor import MemoryExtractor
from .session.memory_deduplicator import MemoryDeduplicator
from .session.compressor import SessionCompressor
from .session.life_proposals import LifeProposalEngine, Proposal
from .retrieve.retriever import Retriever
from .retrieve.intent_analyzer import IntentAnalyzer
from .models.ark_llm import ArkLLM
from .models.embedder import ArkEmbedder
from .graph import PeopleGraph
from .graph.patterns import PatternDetector
from .integrations import OpenClawIntegration
from .sync import MemoryMdSync
from .client import AmberMemory

__all__ = [
    "AmberMemory", "Context", "ContextType", "MemoryCategory",
    "DecayParams", "URI", "SQLiteStore",
    "MemoryExtractor", "MemoryDeduplicator", "SessionCompressor",
    "LifeProposalEngine", "Proposal",
    "Retriever", "IntentAnalyzer",
    "ArkLLM", "ArkEmbedder", "PeopleGraph", "PatternDetector",
    "OpenClawIntegration", "MemoryMdSync",
]
