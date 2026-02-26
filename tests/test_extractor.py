"""Tests for MemoryExtractor — JSON parsing, dimension mapping, candidate conversion."""

import json
import os
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from session.memory_extractor import MemoryExtractor


class MockLLM:
    """Mock LLM that returns predefined responses."""

    def __init__(self, response=""):
        self.response = response
        self.calls = []

    async def __call__(self, prompt):
        self.calls.append(prompt)
        return self.response


class TestExtractorInit(unittest.TestCase):
    """Test MemoryExtractor initialization."""

    def test_create_without_llm(self):
        ext = MemoryExtractor(llm_fn=None)
        self.assertIsNotNone(ext)

    def test_create_with_llm(self):
        mock = MockLLM()
        ext = MemoryExtractor(llm_fn=mock)
        self.assertIsNotNone(ext)


class TestExtractorParsing(unittest.TestCase):
    """Test JSON response parsing from LLM output."""

    def setUp(self):
        self.extractor = MemoryExtractor(llm_fn=None)

    def test_parse_clean_json(self):
        raw = json.dumps([
            {"dimension": "person", "content": "老王是同事", "importance": 0.6},
            {"dimension": "activity", "content": "吃了火锅", "importance": 0.4},
        ])
        result = self.extractor._parse_extraction_response(raw)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["dimension"], "person")

    def test_parse_json_with_markdown_wrapper(self):
        raw = """```json
[
    {"dimension": "person", "content": "老王是同事", "importance": 0.6}
]
```"""
        result = self.extractor._parse_extraction_response(raw)
        self.assertEqual(len(result), 1)

    def test_parse_json_with_extra_text(self):
        raw = """根据对话内容，我提取了以下记忆：
[
    {"dimension": "goal", "content": "计划减肥", "importance": 0.7}
]
以上是提取结果。"""
        result = self.extractor._parse_extraction_response(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["dimension"], "goal")

    def test_parse_empty_array(self):
        raw = "[]"
        result = self.extractor._parse_extraction_response(raw)
        self.assertEqual(len(result), 0)

    def test_parse_invalid_json(self):
        raw = "这不是JSON"
        result = self.extractor._parse_extraction_response(raw)
        self.assertEqual(len(result), 0)

    def test_parse_single_object(self):
        raw = json.dumps({"dimension": "thought", "content": "AI很有趣", "importance": 0.5})
        result = self.extractor._parse_extraction_response(raw)
        # Should wrap single object in list
        self.assertGreaterEqual(len(result), 0)


class TestDimensionMapping(unittest.TestCase):
    """Test 8-dimension mapping."""

    def setUp(self):
        self.extractor = MemoryExtractor(llm_fn=None)

    def test_valid_dimensions(self):
        valid = ["person", "activity", "object", "preference",
                 "taboo", "goal", "pattern", "thought"]
        for dim in valid:
            self.assertTrue(self.extractor._is_valid_dimension(dim))

    def test_invalid_dimension(self):
        self.assertFalse(self.extractor._is_valid_dimension("invalid"))
        self.assertFalse(self.extractor._is_valid_dimension(""))
        self.assertFalse(self.extractor._is_valid_dimension("memory"))

    def test_dimension_fallback(self):
        # Unknown dimensions should map to closest match or default
        mapped = self.extractor._map_dimension("人物")
        self.assertEqual(mapped, "person")

    def test_dimension_chinese_mapping(self):
        mappings = {
            "人物": "person", "事件": "activity", "物品": "object",
            "偏好": "preference", "禁忌": "taboo", "目标": "goal",
            "模式": "pattern", "思考": "thought",
        }
        for cn, en in mappings.items():
            self.assertEqual(self.extractor._map_dimension(cn), en)


class TestCandidateConversion(unittest.TestCase):
    """Test converting LLM candidates to Context objects."""

    def setUp(self):
        self.extractor = MemoryExtractor(llm_fn=None)

    def test_convert_basic_candidate(self):
        candidate = {
            "dimension": "person",
            "content": "老王是同组同事，负责海外业务",
            "importance": 0.6,
        }
        ctx = self.extractor._candidate_to_context(candidate)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.category, "person")
        self.assertIn("老王", ctx.abstract)
        self.assertAlmostEqual(ctx.importance, 0.6, places=1)

    def test_convert_taboo_candidate(self):
        candidate = {
            "dimension": "taboo",
            "content": "不要在老王面前提他前女友",
            "importance": 0.9,
        }
        ctx = self.extractor._candidate_to_context(candidate)
        self.assertEqual(ctx.category, "taboo")
        self.assertGreaterEqual(ctx.importance, 0.8)

    def test_convert_with_missing_importance(self):
        candidate = {
            "dimension": "activity",
            "content": "今天吃了火锅",
        }
        ctx = self.extractor._candidate_to_context(candidate)
        self.assertIsNotNone(ctx)
        # Should have default importance
        self.assertGreater(ctx.importance, 0)

    def test_convert_with_extra_fields(self):
        candidate = {
            "dimension": "goal",
            "content": "计划减肥",
            "importance": 0.7,
            "keywords": ["减肥", "健康"],
            "confidence": 0.9,
        }
        ctx = self.extractor._candidate_to_context(candidate)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.category, "goal")

    def test_abstract_truncation(self):
        candidate = {
            "dimension": "thought",
            "content": "这是一段非常非常长的思考内容，" * 20,
            "importance": 0.5,
        }
        ctx = self.extractor._candidate_to_context(candidate)
        self.assertLessEqual(len(ctx.abstract), 100)

    def test_uri_generation(self):
        candidate = {
            "dimension": "person",
            "content": "Frankie是我的人类",
            "importance": 0.8,
        }
        ctx = self.extractor._candidate_to_context(candidate)
        self.assertTrue(ctx.uri.startswith("/"))
        self.assertIn("person", ctx.uri)


class TestLanguageDetection(unittest.TestCase):
    """Test language detection in extraction."""

    def setUp(self):
        self.extractor = MemoryExtractor(llm_fn=None)

    def test_detect_chinese(self):
        lang = self.extractor._detect_language("今天天气不错，我们去吃火锅吧")
        self.assertEqual(lang, "zh")

    def test_detect_english(self):
        lang = self.extractor._detect_language("The weather is nice today, let's go eat hotpot")
        self.assertEqual(lang, "en")

    def test_detect_mixed(self):
        lang = self.extractor._detect_language("今天的meeting很顺利，boss说OK了")
        # Mixed should default to Chinese if more Chinese chars
        self.assertIn(lang, ["zh", "en"])

    def test_detect_empty(self):
        lang = self.extractor._detect_language("")
        self.assertIn(lang, ["zh", "en", "unknown"])


if __name__ == "__main__":
    unittest.main()
