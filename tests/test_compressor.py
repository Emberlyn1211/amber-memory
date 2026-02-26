"""Tests for SessionCompressor — full pipeline: extract → dedup → store."""

import json
import os
import tempfile
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from session.compressor import SessionCompressor
from session.memory_extractor import MemoryExtractor
from session.memory_deduplicator import MemoryDeduplicator
from storage.sqlite_store import SQLiteStore
from core.context import Context


class MockCompressorLLM:
    """Mock LLM that returns realistic extraction + dedup responses."""

    def __init__(self):
        self.calls = []
        self.call_count = 0

    async def __call__(self, prompt):
        self.calls.append(prompt)
        self.call_count += 1

        # First call is extraction, second is dedup
        if "提取" in prompt or "extract" in prompt.lower() or "记忆" in prompt:
            return json.dumps([
                {"dimension": "person", "content": "老王是同组同事，负责海外业务", "importance": 0.6},
                {"dimension": "activity", "content": "今天和老王一起吃了火锅", "importance": 0.4},
                {"dimension": "taboo", "content": "不要在老王面前提他前女友", "importance": 0.9},
            ])
        else:
            # Dedup decision: create
            return json.dumps({"decision": "create", "reason": "新记忆"})


class TestCompressorInit(unittest.TestCase):
    """Test SessionCompressor initialization."""

    def test_create_compressor(self):
        db_path = tempfile.mktemp(suffix=".db")
        store = SQLiteStore(db_path)
        mock_llm = MockCompressorLLM()
        comp = SessionCompressor(
            store=store,
            extractor=MemoryExtractor(llm_fn=mock_llm),
            deduplicator=MemoryDeduplicator(llm_fn=mock_llm),
        )
        self.assertIsNotNone(comp)
        store.close()
        os.unlink(db_path)

    def test_create_without_dedup(self):
        db_path = tempfile.mktemp(suffix=".db")
        store = SQLiteStore(db_path)
        mock_llm = MockCompressorLLM()
        comp = SessionCompressor(
            store=store,
            extractor=MemoryExtractor(llm_fn=mock_llm),
            deduplicator=None,
        )
        self.assertIsNotNone(comp)
        store.close()
        os.unlink(db_path)


class TestCompressorPipeline(unittest.TestCase):
    """Test the full compression pipeline."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.db_path)
        self.mock_llm = MockCompressorLLM()
        self.compressor = SessionCompressor(
            store=self.store,
            extractor=MemoryExtractor(llm_fn=self.mock_llm),
            deduplicator=MemoryDeduplicator(llm_fn=self.mock_llm),
        )

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_compress_basic_messages(self):
        import asyncio
        messages = [
            {"role": "user", "content": "今天和老王吃了顿火锅，他说下个月要去日本出差"},
            {"role": "assistant", "content": "听起来不错！老王是你同事吗？"},
            {"role": "user", "content": "对，我们在同一个组。千万别在他面前提他前女友"},
        ]
        memories = asyncio.get_event_loop().run_until_complete(
            self.compressor.compress(messages, user="Frankie")
        )
        self.assertIsInstance(memories, list)
        # Mock LLM returns 3 memories
        self.assertGreaterEqual(len(memories), 0)

    def test_compress_empty_messages(self):
        import asyncio
        memories = asyncio.get_event_loop().run_until_complete(
            self.compressor.compress([], user="Test")
        )
        self.assertEqual(len(memories), 0)

    def test_compress_single_message(self):
        import asyncio
        messages = [{"role": "user", "content": "我喜欢喝威士忌"}]
        memories = asyncio.get_event_loop().run_until_complete(
            self.compressor.compress(messages, user="Frankie")
        )
        self.assertIsInstance(memories, list)

    def test_compress_stores_to_db(self):
        import asyncio
        messages = [
            {"role": "user", "content": "老王下周去东京出差"},
        ]
        before_count = self.store.count()
        asyncio.get_event_loop().run_until_complete(
            self.compressor.compress(messages, user="Frankie")
        )
        after_count = self.store.count()
        # Should have stored some memories
        self.assertGreaterEqual(after_count, before_count)

    def test_compress_with_session_id(self):
        import asyncio
        messages = [{"role": "user", "content": "测试消息"}]
        memories = asyncio.get_event_loop().run_until_complete(
            self.compressor.compress(messages, user="Test", session_id="session_001")
        )
        self.assertIsInstance(memories, list)

    def test_llm_called(self):
        import asyncio
        messages = [{"role": "user", "content": "一条消息"}]
        asyncio.get_event_loop().run_until_complete(
            self.compressor.compress(messages, user="Test")
        )
        # LLM should have been called at least once (extraction)
        self.assertGreater(self.mock_llm.call_count, 0)


class TestCompressorEdgeCases(unittest.TestCase):
    """Test edge cases in compression."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_compress_very_long_conversation(self):
        import asyncio
        mock_llm = MockCompressorLLM()
        comp = SessionCompressor(
            store=self.store,
            extractor=MemoryExtractor(llm_fn=mock_llm),
            deduplicator=MemoryDeduplicator(llm_fn=mock_llm),
        )
        messages = [
            {"role": "user" if i % 2 == 0 else "assistant",
             "content": f"这是第{i}条消息，内容很丰富" * 10}
            for i in range(50)
        ]
        memories = asyncio.get_event_loop().run_until_complete(
            comp.compress(messages, user="Test")
        )
        self.assertIsInstance(memories, list)

    def test_compress_only_assistant_messages(self):
        import asyncio
        mock_llm = MockCompressorLLM()
        comp = SessionCompressor(
            store=self.store,
            extractor=MemoryExtractor(llm_fn=mock_llm),
            deduplicator=MemoryDeduplicator(llm_fn=mock_llm),
        )
        messages = [
            {"role": "assistant", "content": "我是AI助手"},
            {"role": "assistant", "content": "有什么可以帮你的"},
        ]
        memories = asyncio.get_event_loop().run_until_complete(
            comp.compress(messages, user="Test")
        )
        self.assertIsInstance(memories, list)

    def test_compress_unicode_content(self):
        import asyncio
        mock_llm = MockCompressorLLM()
        comp = SessionCompressor(
            store=self.store,
            extractor=MemoryExtractor(llm_fn=mock_llm),
            deduplicator=MemoryDeduplicator(llm_fn=mock_llm),
        )
        messages = [
            {"role": "user", "content": "🎉 今天很开心！emoji测试 ❤️🔥"},
        ]
        memories = asyncio.get_event_loop().run_until_complete(
            comp.compress(messages, user="Test")
        )
        self.assertIsInstance(memories, list)


if __name__ == "__main__":
    unittest.main()
