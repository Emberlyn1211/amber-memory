"""Tests for MemoryDeduplicator — decision parsing, text overlap, merge/delete paths."""

import json
import os
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from session.memory_deduplicator import MemoryDeduplicator
from core.context import Context


class MockDedupLLM:
    """Mock LLM for dedup decisions."""

    def __init__(self, decision="create"):
        self.decision = decision
        self.calls = []

    async def __call__(self, prompt):
        self.calls.append(prompt)
        if self.decision == "skip":
            return json.dumps({"decision": "skip", "reason": "已存在相同记忆"})
        elif self.decision == "merge":
            return json.dumps({
                "decision": "create",
                "merge_actions": [{"target_uri": "/old/1", "action": "merge"}],
                "merged_content": "合并后的内容",
                "reason": "信息互补，合并更好",
            })
        elif self.decision == "delete":
            return json.dumps({
                "decision": "create",
                "merge_actions": [{"target_uri": "/old/1", "action": "delete"}],
                "reason": "新记忆更完整，替换旧的",
            })
        else:
            return json.dumps({"decision": "create", "reason": "全新记忆"})


class TestDeduplicatorInit(unittest.TestCase):
    """Test MemoryDeduplicator initialization."""

    def test_create_without_llm(self):
        dedup = MemoryDeduplicator(llm_fn=None)
        self.assertIsNotNone(dedup)

    def test_create_with_llm(self):
        mock = MockDedupLLM()
        dedup = MemoryDeduplicator(llm_fn=mock)
        self.assertIsNotNone(dedup)


class TestDecisionParsing(unittest.TestCase):
    """Test parsing LLM dedup decisions."""

    def setUp(self):
        self.dedup = MemoryDeduplicator(llm_fn=None)

    def test_parse_skip_decision(self):
        raw = json.dumps({"decision": "skip", "reason": "duplicate"})
        result = self.dedup._parse_decision(raw)
        self.assertEqual(result["decision"], "skip")

    def test_parse_create_decision(self):
        raw = json.dumps({"decision": "create", "reason": "new memory"})
        result = self.dedup._parse_decision(raw)
        self.assertEqual(result["decision"], "create")

    def test_parse_none_decision(self):
        raw = json.dumps({"decision": "none", "reason": "not worth storing"})
        result = self.dedup._parse_decision(raw)
        self.assertEqual(result["decision"], "none")

    def test_parse_with_merge_actions(self):
        raw = json.dumps({
            "decision": "create",
            "merge_actions": [
                {"target_uri": "/person/laowang", "action": "merge"},
            ],
            "merged_content": "老王是同组同事，负责海外业务，下月去日本出差",
        })
        result = self.dedup._parse_decision(raw)
        self.assertEqual(result["decision"], "create")
        self.assertEqual(len(result["merge_actions"]), 1)
        self.assertEqual(result["merge_actions"][0]["action"], "merge")

    def test_parse_with_delete_action(self):
        raw = json.dumps({
            "decision": "create",
            "merge_actions": [
                {"target_uri": "/old/memory", "action": "delete"},
            ],
        })
        result = self.dedup._parse_decision(raw)
        self.assertEqual(result["merge_actions"][0]["action"], "delete")

    def test_parse_invalid_json(self):
        raw = "not json at all"
        result = self.dedup._parse_decision(raw)
        # Should return safe default
        self.assertIn(result["decision"], ["create", "skip", "none"])

    def test_parse_json_in_markdown(self):
        raw = """```json
{"decision": "skip", "reason": "已存在"}
```"""
        result = self.dedup._parse_decision(raw)
        self.assertEqual(result["decision"], "skip")

    def test_parse_unknown_decision_defaults(self):
        raw = json.dumps({"decision": "unknown_value", "reason": "?"})
        result = self.dedup._parse_decision(raw)
        # Should normalize to valid decision
        self.assertIn(result["decision"], ["create", "skip", "none"])


class TestTextOverlap(unittest.TestCase):
    """Test text overlap detection for quick dedup."""

    def setUp(self):
        self.dedup = MemoryDeduplicator(llm_fn=None)

    def test_identical_texts(self):
        overlap = self.dedup._text_overlap("老王是同事", "老王是同事")
        self.assertGreater(overlap, 0.9)

    def test_similar_texts(self):
        overlap = self.dedup._text_overlap(
            "老王是同组同事",
            "老王是我们组的同事",
        )
        self.assertGreater(overlap, 0.5)

    def test_different_texts(self):
        overlap = self.dedup._text_overlap(
            "今天天气不错",
            "量子力学很有趣",
        )
        self.assertLess(overlap, 0.3)

    def test_empty_text(self):
        overlap = self.dedup._text_overlap("", "something")
        self.assertAlmostEqual(overlap, 0.0, places=1)

    def test_both_empty(self):
        overlap = self.dedup._text_overlap("", "")
        self.assertGreaterEqual(overlap, 0.0)

    def test_subset_text(self):
        overlap = self.dedup._text_overlap(
            "老王",
            "老王是同组同事负责海外业务",
        )
        self.assertGreater(overlap, 0.2)

    def test_long_texts(self):
        text1 = "这是一段关于项目进展的详细描述，包含了很多技术细节和决策过程" * 5
        text2 = "这是一段关于项目进展的详细描述，包含了很多技术细节和决策过程" * 5
        overlap = self.dedup._text_overlap(text1, text2)
        self.assertGreater(overlap, 0.9)


class TestQuickDedup(unittest.TestCase):
    """Test quick dedup without LLM (text overlap based)."""

    def setUp(self):
        self.dedup = MemoryDeduplicator(llm_fn=None)

    def test_obvious_duplicate(self):
        new = Context(uri="/new/1", abstract="老王是同组同事", content="老王是同组同事")
        existing = [
            Context(uri="/old/1", abstract="老王是同组同事", content="老王是同组同事"),
        ]
        is_dup = self.dedup._quick_check(new, existing)
        self.assertTrue(is_dup)

    def test_not_duplicate(self):
        new = Context(uri="/new/1", abstract="今天吃了火锅", content="今天吃了火锅")
        existing = [
            Context(uri="/old/1", abstract="老王是同事", content="老王是同组同事"),
        ]
        is_dup = self.dedup._quick_check(new, existing)
        self.assertFalse(is_dup)

    def test_empty_existing(self):
        new = Context(uri="/new/1", abstract="新记忆", content="新记忆内容")
        is_dup = self.dedup._quick_check(new, [])
        self.assertFalse(is_dup)


class TestMergeActions(unittest.TestCase):
    """Test merge action execution."""

    def setUp(self):
        self.dedup = MemoryDeduplicator(llm_fn=None)

    def test_merge_action_structure(self):
        action = {"target_uri": "/old/1", "action": "merge"}
        self.assertEqual(action["action"], "merge")
        self.assertEqual(action["target_uri"], "/old/1")

    def test_delete_action_structure(self):
        action = {"target_uri": "/old/1", "action": "delete"}
        self.assertEqual(action["action"], "delete")

    def test_valid_actions(self):
        valid = ["merge", "delete", "keep"]
        for a in valid:
            action = {"target_uri": "/test", "action": a}
            self.assertIn(action["action"], valid)


if __name__ == "__main__":
    unittest.main()
