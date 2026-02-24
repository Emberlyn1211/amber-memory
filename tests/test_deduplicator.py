"""Tests for session.memory_deduplicator — decision parsing, text overlap, decision paths."""

import asyncio
import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.context import Context
from storage.sqlite_store import SQLiteStore
from session.memory_deduplicator import (
    MemoryDeduplicator, DedupDecision, DedupResult,
    MemoryActionDecision, ExistingMemoryAction,
)
from session.memory_extractor import CandidateMemory


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class DeduplicatorTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = SQLiteStore(self.tmp.name)

    def tearDown(self):
        self.store.close()
        os.unlink(self.tmp.name)

    def _make_candidate(self, abstract="Test candidate", category="preference", content="Full content"):
        return CandidateMemory(
            category=category, abstract=abstract,
            overview="Overview", content=content,
        )

    def _make_existing(self, uri, abstract="Existing memory", category="preference"):
        ctx = Context(
            uri=uri, abstract=abstract, overview="Existing overview",
            content="Existing content", category=category,
        )
        self.store.put(ctx)
        return ctx


class TestTextOverlap(unittest.TestCase):
    """Test _text_overlap static method."""

    def test_identical_strings(self):
        score = MemoryDeduplicator._text_overlap("hello", "hello")
        self.assertEqual(score, 1.0)

    def test_no_overlap(self):
        score = MemoryDeduplicator._text_overlap("abc", "xyz")
        self.assertEqual(score, 0.0)

    def test_partial_overlap(self):
        score = MemoryDeduplicator._text_overlap("abcd", "cdef")
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)

    def test_empty_strings(self):
        self.assertEqual(MemoryDeduplicator._text_overlap("", ""), 0.0)
        self.assertEqual(MemoryDeduplicator._text_overlap("abc", ""), 0.0)
        self.assertEqual(MemoryDeduplicator._text_overlap("", "abc"), 0.0)

    def test_overlap_is_symmetric(self):
        a = MemoryDeduplicator._text_overlap("hello world", "world peace")
        b = MemoryDeduplicator._text_overlap("world peace", "hello world")
        self.assertAlmostEqual(a, b)


class TestDeduplicateNoSimilar(DeduplicatorTestBase):
    """Test dedup when no similar memories exist."""

    def test_no_similar_creates(self):
        dedup = MemoryDeduplicator(store=self.store)
        candidate = self._make_candidate(abstract="Completely unique memory xyz123")
        result = run(dedup.deduplicate(candidate))
        self.assertEqual(result.decision, DedupDecision.CREATE)
        self.assertEqual(len(result.similar_memories), 0)

    def test_no_llm_defaults_to_create(self):
        self._make_existing("/pref/1", abstract="Test candidate similar", category="preference")
        dedup = MemoryDeduplicator(store=self.store, llm_fn=None)
        candidate = self._make_candidate(abstract="Test candidate similar")
        result = run(dedup.deduplicate(candidate))
        self.assertEqual(result.decision, DedupDecision.CREATE)


class TestDeduplicateWithLLM(DeduplicatorTestBase):
    """Test dedup with mock LLM decisions."""

    def test_llm_skip_decision(self):
        self._make_existing("/pref/1", abstract="喜欢咖啡", category="preference")
        llm_response = '{"decision": "skip", "reason": "duplicate", "list": []}'
        mock_llm = AsyncMock(return_value=llm_response)
        dedup = MemoryDeduplicator(store=self.store, llm_fn=mock_llm)
        candidate = self._make_candidate(abstract="喜欢咖啡", category="preference")
        result = run(dedup.deduplicate(candidate))
        self.assertEqual(result.decision, DedupDecision.SKIP)

    def test_llm_create_decision(self):
        self._make_existing("/pref/1", abstract="喜欢咖啡", category="preference")
        llm_response = '{"decision": "create", "reason": "new info", "list": []}'
        mock_llm = AsyncMock(return_value=llm_response)
        dedup = MemoryDeduplicator(store=self.store, llm_fn=mock_llm)
        candidate = self._make_candidate(abstract="喜欢咖啡和茶", category="preference")
        result = run(dedup.deduplicate(candidate))
        self.assertEqual(result.decision, DedupDecision.CREATE)

    def test_llm_none_with_merge(self):
        existing = self._make_existing("/pref/1", abstract="喜欢咖啡", category="preference")
        llm_response = f'{{"decision": "none", "reason": "merge needed", "list": [{{"uri": "/pref/1", "decide": "merge", "reason": "same topic"}}]}}'
        mock_llm = AsyncMock(return_value=llm_response)
        dedup = MemoryDeduplicator(store=self.store, llm_fn=mock_llm)
        candidate = self._make_candidate(abstract="喜欢咖啡", category="preference")
        result = run(dedup.deduplicate(candidate))
        self.assertEqual(result.decision, DedupDecision.NONE)
        self.assertIsNotNone(result.actions)
        self.assertEqual(len(result.actions), 1)
        self.assertEqual(result.actions[0].decision, MemoryActionDecision.MERGE)

    def test_llm_create_with_delete(self):
        existing = self._make_existing("/pref/1", abstract="旧信息", category="preference")
        llm_response = f'{{"decision": "create", "reason": "replace old", "list": [{{"uri": "/pref/1", "decide": "delete", "reason": "outdated"}}]}}'
        mock_llm = AsyncMock(return_value=llm_response)
        dedup = MemoryDeduplicator(store=self.store, llm_fn=mock_llm)
        candidate = self._make_candidate(abstract="新信息", category="preference")
        result = run(dedup.deduplicate(candidate))
        self.assertEqual(result.decision, DedupDecision.CREATE)
        self.assertEqual(len(result.actions), 1)
        self.assertEqual(result.actions[0].decision, MemoryActionDecision.DELETE)

    def test_llm_failure_defaults_to_create(self):
        self._make_existing("/pref/1", abstract="喜欢咖啡", category="preference")
        mock_llm = AsyncMock(side_effect=Exception("LLM error"))
        dedup = MemoryDeduplicator(store=self.store, llm_fn=mock_llm)
        candidate = self._make_candidate(abstract="喜欢咖啡", category="preference")
        result = run(dedup.deduplicate(candidate))
        self.assertEqual(result.decision, DedupDecision.CREATE)


class TestParseDecision(DeduplicatorTestBase):
    """Test _parse_decision logic."""

    def test_skip_clears_actions(self):
        dedup = MemoryDeduplicator(store=self.store)
        existing = [Context(uri="/a", abstract="A")]
        decision, reason, actions = dedup._parse_decision(
            {"decision": "skip", "reason": "dup", "list": [{"uri": "/a", "decide": "merge"}]},
            existing,
        )
        self.assertEqual(decision, DedupDecision.SKIP)
        self.assertEqual(len(actions), 0)

    def test_create_with_merge_normalizes_to_none(self):
        dedup = MemoryDeduplicator(store=self.store)
        existing = [Context(uri="/a", abstract="A")]
        decision, reason, actions = dedup._parse_decision(
            {"decision": "create", "list": [{"uri": "/a", "decide": "merge"}]},
            existing,
        )
        self.assertEqual(decision, DedupDecision.NONE)

    def test_create_only_keeps_delete_actions(self):
        dedup = MemoryDeduplicator(store=self.store)
        existing = [Context(uri="/a", abstract="A"), Context(uri="/b", abstract="B")]
        decision, reason, actions = dedup._parse_decision(
            {"decision": "create", "list": [
                {"uri": "/a", "decide": "delete"},
                {"uri": "/b", "decide": "merge"},
            ]},
            existing,
        )
        # merge present → normalized to none
        self.assertEqual(decision, DedupDecision.NONE)

    def test_legacy_merge_decision(self):
        dedup = MemoryDeduplicator(store=self.store)
        existing = [Context(uri="/a", abstract="A")]
        decision, reason, actions = dedup._parse_decision(
            {"decision": "merge"},
            existing,
        )
        self.assertEqual(decision, DedupDecision.NONE)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].decision, MemoryActionDecision.MERGE)

    def test_index_based_action(self):
        dedup = MemoryDeduplicator(store=self.store)
        existing = [Context(uri="/a", abstract="A"), Context(uri="/b", abstract="B")]
        decision, reason, actions = dedup._parse_decision(
            {"decision": "none", "list": [{"index": 2, "decide": "delete", "reason": "old"}]},
            existing,
        )
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].memory.uri, "/b")

    def test_conflicting_actions_for_same_uri_removed(self):
        dedup = MemoryDeduplicator(store=self.store)
        existing = [Context(uri="/a", abstract="A")]
        decision, reason, actions = dedup._parse_decision(
            {"decision": "none", "list": [
                {"uri": "/a", "decide": "merge", "reason": "r1"},
                {"uri": "/a", "decide": "delete", "reason": "r2"},
            ]},
            existing,
        )
        # Conflicting actions for same URI should be removed
        self.assertEqual(len(actions), 0)

    def test_unknown_decision_defaults_to_create(self):
        dedup = MemoryDeduplicator(store=self.store)
        decision, reason, actions = dedup._parse_decision(
            {"decision": "unknown_value"}, [],
        )
        self.assertEqual(decision, DedupDecision.CREATE)


class TestFindSimilar(DeduplicatorTestBase):
    """Test _find_similar method."""

    def test_finds_by_text_search(self):
        self._make_existing("/pref/coffee", abstract="喜欢喝咖啡", category="preference")
        dedup = MemoryDeduplicator(store=self.store)
        candidate = self._make_candidate(abstract="喜欢喝咖啡每天", category="preference")
        similar = dedup._find_similar(candidate)
        self.assertGreater(len(similar), 0)

    def test_max_similar_limit(self):
        for i in range(10):
            self._make_existing(f"/pref/{i}", abstract=f"共同关键词 item{i}", category="preference")
        dedup = MemoryDeduplicator(store=self.store)
        candidate = self._make_candidate(abstract="共同关键词 test", category="preference")
        similar = dedup._find_similar(candidate)
        self.assertLessEqual(len(similar), dedup.MAX_SIMILAR)


if __name__ == "__main__":
    unittest.main()
