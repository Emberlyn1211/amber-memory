"""Tests for prompts.manager — template loading, rendering, variable substitution, defaults."""

import os
import tempfile
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from prompts.manager import PromptManager, render_prompt, get_manager


class TestPromptManagerLoading(unittest.TestCase):
    """Test template loading from YAML files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        cat_dir = Path(self.tmpdir) / "compression"
        cat_dir.mkdir()
        (cat_dir / "test_prompt.yaml").write_text(
            'template: "Hello {{ name }}"\n'
            'variables:\n'
            '  - name: name\n'
            '    type: string\n'
            '    required: true\n'
            'llm_config:\n'
            '  temperature: 0.5\n',
            encoding="utf-8",
        )
        (cat_dir / "with_defaults.yaml").write_text(
            'template: "Hi {{ name }}, age={{ age }}"\n'
            'variables:\n'
            '  - name: name\n'
            '    default: "World"\n'
            '  - name: age\n'
            '    default: "25"\n',
            encoding="utf-8",
        )
        (cat_dir / "with_max_length.yaml").write_text(
            'template: "Content: {{ body }}"\n'
            'variables:\n'
            '  - name: body\n'
            '    max_length: 10\n',
            encoding="utf-8",
        )
        self.manager = PromptManager(templates_dir=Path(self.tmpdir))

    def test_load_template(self):
        data = self.manager.load_template("compression.test_prompt")
        self.assertIn("template", data)
        self.assertEqual(data["template"], "Hello {{ name }}")

    def test_load_template_caching(self):
        d1 = self.manager.load_template("compression.test_prompt")
        d2 = self.manager.load_template("compression.test_prompt")
        self.assertIs(d1, d2)

    def test_load_nonexistent_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.manager.load_template("compression.nonexistent")

    def test_render_basic(self):
        result = self.manager.render("compression.test_prompt", {"name": "Amber"})
        self.assertEqual(result, "Hello Amber")

    def test_render_with_defaults(self):
        result = self.manager.render("compression.with_defaults", {})
        self.assertIn("World", result)
        self.assertIn("25", result)

    def test_render_override_defaults(self):
        result = self.manager.render("compression.with_defaults", {"name": "Frankie", "age": "30"})
        self.assertIn("Frankie", result)
        self.assertIn("30", result)

    def test_render_max_length_truncation(self):
        result = self.manager.render("compression.with_max_length", {"body": "A" * 100})
        # body should be truncated to 10 chars
        self.assertIn("A" * 10, result)
        self.assertNotIn("A" * 11, result)

    def test_get_llm_config(self):
        config = self.manager.get_llm_config("compression.test_prompt")
        self.assertEqual(config["temperature"], 0.5)

    def test_get_llm_config_missing(self):
        config = self.manager.get_llm_config("compression.with_defaults")
        self.assertEqual(config, {})

    def test_render_empty_variables(self):
        result = self.manager.render("compression.test_prompt", {"name": ""})
        self.assertEqual(result, "Hello ")


class TestPromptManagerRealTemplates(unittest.TestCase):
    """Test loading real project templates."""

    def setUp(self):
        templates_dir = Path(__file__).parent.parent / "prompts" / "templates"
        if not templates_dir.exists():
            self.skipTest("Templates directory not found")
        self.manager = PromptManager(templates_dir=templates_dir)

    def test_load_memory_extraction(self):
        data = self.manager.load_template("compression.memory_extraction")
        self.assertIn("template", data)
        self.assertIn("variables", data)

    def test_render_memory_extraction(self):
        result = self.manager.render("compression.memory_extraction", {
            "summary": "Test summary",
            "recent_messages": "[user]: Hello",
            "user": "TestUser",
            "output_language": "en",
        })
        self.assertIn("TestUser", result)
        self.assertIn("[user]: Hello", result)

    def test_load_dedup_decision(self):
        data = self.manager.load_template("compression.dedup_decision")
        self.assertIn("template", data)

    def test_render_dedup_decision(self):
        result = self.manager.render("compression.dedup_decision", {
            "candidate_content": "New fact",
            "candidate_abstract": "Abstract",
            "candidate_overview": "Overview",
            "existing_memories": "1. uri=/test\n   abstract=Old fact",
        })
        self.assertIn("New fact", result)
        self.assertIn("Old fact", result)

    def test_load_merge_bundle(self):
        data = self.manager.load_template("compression.memory_merge_bundle")
        self.assertIn("template", data)

    def test_render_merge_bundle_with_defaults(self):
        result = self.manager.render("compression.memory_merge_bundle", {
            "existing_content": "Old content",
            "new_content": "New content",
            "category": "preference",
        })
        self.assertIn("Old content", result)
        self.assertIn("preference", result)

    def test_load_intent_analysis(self):
        data = self.manager.load_template("retrieval.intent_analysis")
        self.assertIn("template", data)

    def test_render_intent_analysis(self):
        result = self.manager.render("retrieval.intent_analysis", {
            "recent_messages": "[user]: What's up",
            "current_message": "Tell me about Frankie",
        })
        self.assertIn("Tell me about Frankie", result)


class TestGlobalSingleton(unittest.TestCase):
    """Test module-level convenience functions."""

    def test_get_manager_returns_same_instance(self):
        m1 = get_manager()
        m2 = get_manager()
        self.assertIs(m1, m2)

    def test_render_prompt_convenience(self):
        # This uses the global singleton with real templates
        templates_dir = Path(__file__).parent.parent / "prompts" / "templates"
        if not templates_dir.exists():
            self.skipTest("Templates directory not found")
        # Just verify it doesn't crash
        result = render_prompt("compression.memory_extraction", {
            "summary": "",
            "recent_messages": "test",
            "user": "test",
            "output_language": "en",
        })
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)


if __name__ == "__main__":
    unittest.main()
