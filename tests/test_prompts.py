"""Tests for Prompt template system — loading, rendering, variables, defaults."""

import os
import tempfile
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from prompts.manager import PromptManager


class TestPromptManagerInit(unittest.TestCase):
    """Test PromptManager initialization and template discovery."""

    def setUp(self):
        self.manager = PromptManager()

    def test_manager_creates(self):
        self.assertIsNotNone(self.manager)

    def test_templates_dir_exists(self):
        templates_dir = os.path.join(os.path.dirname(__file__), '..', 'prompts', 'templates')
        self.assertTrue(os.path.exists(templates_dir))

    def test_load_memory_extraction(self):
        template = self.manager.get_template("memory_extraction")
        self.assertIsNotNone(template)

    def test_load_dedup_decision(self):
        template = self.manager.get_template("dedup_decision")
        self.assertIsNotNone(template)

    def test_load_intent_analysis(self):
        template = self.manager.get_template("intent_analysis")
        self.assertIsNotNone(template)

    def test_load_memory_merge_bundle(self):
        template = self.manager.get_template("memory_merge_bundle")
        self.assertIsNotNone(template)

    def test_load_nonexistent_template(self):
        with self.assertRaises(Exception):
            self.manager.get_template("does_not_exist")

    def test_list_templates(self):
        templates = self.manager.list_templates()
        self.assertIsInstance(templates, list)
        self.assertGreaterEqual(len(templates), 4)


class TestPromptRendering(unittest.TestCase):
    """Test template rendering with variables."""

    def setUp(self):
        self.manager = PromptManager()

    def test_render_memory_extraction(self):
        result = self.manager.render("memory_extraction", {
            "messages": [
                {"role": "user", "content": "今天和老王吃了火锅"},
                {"role": "assistant", "content": "听起来不错！"},
            ],
            "user_name": "Frankie",
            "existing_memories": [],
        })
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 50)
        self.assertIn("Frankie", result)

    def test_render_dedup_decision(self):
        result = self.manager.render("dedup_decision", {
            "new_memory": "老王是同组同事",
            "existing_memories": [
                {"abstract": "老王在海外部门", "category": "person"},
            ],
        })
        self.assertIsInstance(result, str)
        self.assertIn("老王", result)

    def test_render_intent_analysis(self):
        result = self.manager.render("intent_analysis", {
            "query": "Frankie喜欢什么酒",
            "available_dimensions": ["person", "preference", "activity"],
        })
        self.assertIsInstance(result, str)
        self.assertIn("Frankie", result)

    def test_render_with_empty_messages(self):
        result = self.manager.render("memory_extraction", {
            "messages": [],
            "user_name": "Test",
            "existing_memories": [],
        })
        self.assertIsInstance(result, str)

    def test_render_with_long_content(self):
        long_msg = "这是一段很长的消息。" * 100
        result = self.manager.render("memory_extraction", {
            "messages": [{"role": "user", "content": long_msg}],
            "user_name": "Frankie",
            "existing_memories": [],
        })
        self.assertIsInstance(result, str)

    def test_render_preserves_chinese(self):
        result = self.manager.render("memory_extraction", {
            "messages": [{"role": "user", "content": "我喜欢吃麻辣火锅"}],
            "user_name": "小明",
            "existing_memories": [],
        })
        self.assertIn("小明", result)

    def test_render_with_special_chars(self):
        result = self.manager.render("memory_extraction", {
            "messages": [{"role": "user", "content": "价格是$100 & <tag>"}],
            "user_name": "Test",
            "existing_memories": [],
        })
        self.assertIsInstance(result, str)


class TestPromptCaching(unittest.TestCase):
    """Test template caching behavior."""

    def setUp(self):
        self.manager = PromptManager()

    def test_same_template_cached(self):
        t1 = self.manager.get_template("memory_extraction")
        t2 = self.manager.get_template("memory_extraction")
        # Should be the same object (cached)
        self.assertIs(t1, t2)

    def test_different_templates_different(self):
        t1 = self.manager.get_template("memory_extraction")
        t2 = self.manager.get_template("dedup_decision")
        self.assertIsNot(t1, t2)


class TestPromptValidation(unittest.TestCase):
    """Test template validation."""

    def setUp(self):
        self.manager = PromptManager()

    def test_missing_required_var_handled(self):
        # Should either use default or raise clear error
        try:
            result = self.manager.render("memory_extraction", {})
            # If it renders with defaults, that's fine
            self.assertIsInstance(result, str)
        except (KeyError, TypeError) as e:
            # If it raises, should be a clear error
            self.assertIsInstance(e, (KeyError, TypeError))

    def test_extra_vars_ignored(self):
        result = self.manager.render("memory_extraction", {
            "messages": [],
            "user_name": "Test",
            "existing_memories": [],
            "extra_unused_var": "should be ignored",
            "another_one": 42,
        })
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
