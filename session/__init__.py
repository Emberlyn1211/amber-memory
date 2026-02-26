"""Session modules for memory extraction, dedup, compression, and life proposals."""

from .memory_extractor import MemoryExtractor, CandidateMemory, MergedMemoryPayload
from .memory_deduplicator import MemoryDeduplicator, DedupDecision, DedupResult
from .compressor import SessionCompressor, ExtractionStats
from .life_proposals import LifeProposalEngine, Proposal

__all__ = [
    "MemoryExtractor", "CandidateMemory", "MergedMemoryPayload",
    "MemoryDeduplicator", "DedupDecision", "DedupResult",
    "SessionCompressor", "ExtractionStats",
    "LifeProposalEngine", "Proposal",
]
