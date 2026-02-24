"""Tests for session.memory_extractor — JSON parsing, language detection, candidate conversion."""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from session.memory_extractor import (
    CandidateMemory, MergedMemoryPayload, MemoryExtractor,
    parse_json_from_response, detect_language,
    DIMENSION_TO_TYPE, ALWAYS_MERGE_CATEGORIES, MERGE_SUPPORTED_CATEGORIES,
)
from core.context import ContextType


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestParseJsonFromResponse(unittest.TestCase):
    """Test JSON extraction from LLM responses."""

    def test_plain_json(self):
        result = parse_json_from_response('{"key": "value"}')
        self.assertEqual(result, {"key": "value"})

    def test_json_in_code_block(self):
        text = '```json\n{"memories": []}\n```'
        result = parse_json_from_response(text)
        self.assertEqual(result, {"memories": []})

    def test_json_in_plain_code_block(self):
        text = '```\n{"a": 1}\n```'
        result = parse_json_from_response(text)
        self.assertEqual(result, {"a": 1})

    def test_json_embedded_in_text(self):
        text = 'Here is the result:\n{"decision": "create", "reason": "new"}\nDone.'
        result = parse_json_from_response(text)
        self.assertEqual(result["decision"], "create")

    def test_empty_string(self):
        self.assertIsNone(parse_json_from_response(""))

    def test_none_input(self):
        self.assertIsNone(parse_json_from_response(None))

    def test_invalid_json(self):
        self.assertIsNone(parse_json_from_response("not json at all"))

    def test_nested_json(self):
        text = '{"memories": [{"category": "person", "abstract": "test"}]}'
        result = parse_json_from_response(text)
        self.assertEqual(len(result["memories"]), 1)

    def test_whitespace_around_json(self):
        text = '  \n  {"key": "val"}  \n  '
        result = parse_json_from_response(text)
        self.assertEqual(result, {"key": "val"})


class TestDetectLanguage(unittest.TestCase):
    """Test language detection from messages."""

    def test_chinese_messages(self):
        msgs = [{"role": "user", "content": "你好，今天天气怎么样？我想出去走走。"}]
        self.assertEqual(detect_language(msgs), "zh-CN")

    def test_english_messages(self):
        msgs = [{"role": "user", "content": "Hello, how are you doing today?"}]
        self.assertEqual(detect_language(msgs), "en")

    def test_japanese_messages(self):
        msgs = [{"role": "user", "content": "こんにちは、元気ですか？"}]
        self.assertEqual(detect_language(msgs), "ja")

    def test_empty_messages(self):
        self.assertEqual(detect_language([]), "zh-CN")

    def test_no_user_messages(self):
        msgs = [{"role": "assistant", "content": "你好"}]
        self.assertEqual(detect_language(msgs), "zh-CN")

    def test_mixed_messages_chinese_dominant(self):
        msgs = [
            {"role": "user", "content": "帮我看看这个代码有什么问题"},
            {"role": "user", "content": "function test() { return 1; }"},
        ]
        self.assertEqual(detect_language(msgs), "zh-CN")

    def test_custom_fallback(self):
        self.assertEqual(detect_language([], fallback="fr"), "fr")


class TestDimensionMapping(unittest.TestCase):
    """Test dimension constants."""

    def test_all_eight_dimensions_mapped(self):
        expected = {"person", "activity", "object", "preference",
                    "taboo", "goal", "pattern", "thought"}
        self.assertEqual(set(DIMENSION_TO_TYPE.keys()), expected)

    def test_always_merge_categories(self):
        self.assertIn("person", ALWAYS_MERGE_CATEGORIES)
        self.assertIn("preference", ALWAYS_MERGE_CATEGORIES)

    def test_merge_supported_categories(self):
        for cat in ALWAYS_MERGE_CATEGORIES:
            self.assertIn(cat, MERGE_SUPPORTED_CATEGORIES)


class TestMemoryExtractorExtract(unittest.TestCase):
    """Test MemoryExtractor.extract with mock LLM."""

    def test_extract_no_llm_returns_empty(self):
        ext = MemoryExtractor(llm_fn=None)
        result = run(ext.extract([{"role": "user", "content": "hello"}]))
        self.assertEqual(result, [])

    def test_extract_empty_messages(self):
        ext = MemoryExtractor(llm_fn=AsyncMock())
        result = run(ext.extract([]))
        self.assertEqual(result, [])

    def test_extract_success(self):
        llm_response = '{"memories": [{"category": "preference", "abstract": "喜欢咖啡", "overview": "用户喜欢喝咖啡", "content": "用户表示每天早上都要喝一杯咖啡"}]}'
        mock_llm = AsyncMock(return_value=llm_response)
        ext = MemoryExtractor(llm_fn=mock_llm)
        msgs = [{"role": "user", "content": "我每天早上都要喝一杯咖啡"}]
        result = run(ext.extract(msgs, user="Frankie", session_id="s1"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].category, "preference")
        self.assertEqual(result[0].abstract, "喜欢咖啡")
        self.assertEqual(result[0].language, "zh-CN")

    def test_extract_invalid_category_defaults_to_thought(self):
        llm_response = '{"memories": [{"category": "invalid_cat", "abstract": "test", "overview": "", "content": "test"}]}'
        mock_llm = AsyncMock(return_value=llm_response)
        ext = MemoryExtractor(llm_fn=mock_llm)
        result = run(ext.extract([{"role": "user", "content": "test"}]))
        self.assertEqual(result[0].category, "thought")

    def test_extract_llm_failure_returns_empty(self):
        mock_llm = AsyncMock(side_effect=Exception("LLM down"))
        ext = MemoryExtractor(llm_fn=mock_llm)
        result = run(ext.extract([{"role": "user", "content": "test"}]))
        self.assertEqual(result, [])

    def test_extract_multiple_memories(self):
        llm_response = '{"memories": [{"category": "person", "abstract": "A", "overview": "", "content": "A"}, {"category": "goal", "abstract": "B", "overview": "", "content": "B"}]}'
        mock_llm = AsyncMock(return_value=llm_response)
        ext = MemoryExtractor(llm_fn=mock_llm)
        result = run(ext.extract([{"role": "user", "content": "test"}]))
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].category, "person")
        self.assertEqual(result[1].category, "goal")


class TestCandidateToContext(unittest.TestCase):
    """Test candidate_to_context conversion."""

    def test_basic_conversion(self):
        ext = MemoryExtractor()
        candidate = CandidateMemory(
            category="preference", abstract="Likes coffee",
            overview="User likes coffee", content="Full detail",
            source_session="s1", user="Frankie",
        )
        ctx = ext.candidate_to_context(candidate, session_id="s1")
        self.assertIn("preference", ctx.uri)
        self.assertEqual(ctx.abstract, "Likes coffee")
        self.assertEqual(ctx.context_type, ContextType.PREFERENCE.value)
        self.assertEqual(ctx.category, "preference")
        self.assertEqual(ctx.source_session, "s1")

    def test_unknown_category_defaults_to_memory(self):
        ext = MemoryExtractor()
        candidate = CandidateMemory(
            category="unknown", abstract="X", overview="", content="X",
        )
        ctx = ext.candidate_to_context(candidate)
        self.assertEqual(ctx.context_type, ContextType.MEMORY.value)

    def test_parent_uri_set(self):
        ext = MemoryExtractor()
        candidate = CandidateMemory(
            category="goal", abstract="X", overview="", content="X",
        )
        ctx = ext.candidate_to_context(candidate)
        self.assertEqual(ctx.parent_uri, "amber://memories/goal")


class TestMergeMemoryBundle(unittest.TestCase):
    """Test merge_memory_bundle with mock LLM."""

    def test_merge_no_llm(self):
        ext = MemoryExtractor(llm_fn=None)
        result = run(ext.merge_memory_bundle("a", "b", "c", "d", "e", "f", "person"))
        self.assertIsNone(result)

    def test_merge_success(self):
        llm_response = '{"abstract": "Merged abstract", "overview": "Merged overview", "content": "Merged content", "reason": "combined"}'
        mock_llm = AsyncMock(return_value=llm_response)
        ext = MemoryExtractor(llm_fn=mock_llm)
        result = run(ext.merge_memory_bundle("old_a", "old_o", "old_c", "new_a", "new_o", "new_c", "person"))
        self.assertIsNotNone(result)
        self.assertEqual(result.abstract, "Merged abstract")
        self.assertEqual(result.content, "Merged content")

    def test_merge_missing_fields_returns_none(self):
        llm_response = '{"overview": "only overview"}'
        mock_llm = AsyncMock(return_value=llm_response)
        ext = MemoryExtractor(llm_fn=mock_llm)
        result = run(ext.merge_memory_bundle("a", "b", "c", "d", "e", "f", "person"))
        self.assertIsNone(result)

    def test_merge_llm_failure(self):
        mock_llm = AsyncMock(side_effect=Exception("fail"))
        ext = MemoryExtractor(llm_fn=mock_llm)
        result = run(ext.merge_memory_bundle("a", "b", "c", "d", "e", "f", "person"))
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
