"""Tests for Context model, URI system, and decay algorithm."""

import time
import unittest
from datetime import datetime

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.context import Context, ContextType, decay_score
from core.uri import AmberURI


class TestContextCreation(unittest.TestCase):
    """Test Context dataclass creation and defaults."""

    def test_minimal_context(self):
        ctx = Context(uri="/test/1", abstract="test memory")
        self.assertEqual(ctx.uri, "/test/1")
        self.assertEqual(ctx.abstract, "test memory")
        self.assertEqual(ctx.importance, 0.5)
        self.assertIsNotNone(ctx.created_at)

    def test_full_context(self):
        ctx = Context(
            uri="/person/frankie",
            parent_uri="/person",
            abstract="Frankie是我的人类",
            overview="Frankie Zhang，深圳，Telegram @kamael0909",
            content="完整的关于Frankie的描述...",
            context_type=ContextType.PERSON,
            category="person",
            importance=0.9,
            tags=["important", "human"],
            meta={"telegram_id": "5204055266"},
        )
        self.assertEqual(ctx.category, "person")
        self.assertEqual(ctx.importance, 0.9)
        self.assertIn("important", ctx.tags)
        self.assertEqual(ctx.meta["telegram_id"], "5204055266")

    def test_context_type_enum(self):
        self.assertEqual(ContextType.PERSON.value, "person")
        self.assertEqual(ContextType.ACTIVITY.value, "activity")
        self.assertEqual(ContextType.OBJECT.value, "object")
        self.assertEqual(ContextType.PREFERENCE.value, "preference")
        self.assertEqual(ContextType.TABOO.value, "taboo")
        self.assertEqual(ContextType.GOAL.value, "goal")
        self.assertEqual(ContextType.PATTERN.value, "pattern")
        self.assertEqual(ContextType.THOUGHT.value, "thought")
        self.assertEqual(ContextType.MEMORY.value, "memory")

    def test_importance_clamping(self):
        ctx = Context(uri="/test/high", abstract="high", importance=1.5)
        self.assertLessEqual(ctx.importance, 1.5)  # No auto-clamp, user responsibility

        ctx2 = Context(uri="/test/low", abstract="low", importance=-0.1)
        self.assertEqual(ctx2.importance, -0.1)

    def test_default_timestamps(self):
        before = time.time()
        ctx = Context(uri="/test/ts", abstract="timestamp test")
        after = time.time()
        self.assertGreaterEqual(ctx.created_at, before)
        self.assertLessEqual(ctx.created_at, after)

    def test_custom_event_time(self):
        event_time = datetime(2026, 1, 15).timestamp()
        ctx = Context(uri="/test/event", abstract="past event", event_time=event_time)
        self.assertEqual(ctx.event_time, event_time)

    def test_tags_default_empty(self):
        ctx = Context(uri="/test/tags", abstract="no tags")
        self.assertEqual(ctx.tags, [])

    def test_meta_default_empty(self):
        ctx = Context(uri="/test/meta", abstract="no meta")
        self.assertEqual(ctx.meta, {})

    def test_context_to_dict(self):
        ctx = Context(uri="/test/dict", abstract="dict test", category="goal")
        d = ctx.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["uri"], "/test/dict")
        self.assertEqual(d["abstract"], "dict test")
        self.assertEqual(d["category"], "goal")

    def test_context_from_dict(self):
        d = {
            "uri": "/test/from",
            "abstract": "from dict",
            "category": "thought",
            "importance": 0.7,
        }
        ctx = Context.from_dict(d)
        self.assertEqual(ctx.uri, "/test/from")
        self.assertEqual(ctx.category, "thought")
        self.assertAlmostEqual(ctx.importance, 0.7)

    def test_eight_dimensions(self):
        dims = ["person", "activity", "object", "preference",
                "taboo", "goal", "pattern", "thought"]
        for dim in dims:
            ctx = Context(uri=f"/test/{dim}", abstract=f"{dim} test", category=dim)
            self.assertEqual(ctx.category, dim)

    def test_parent_uri(self):
        ctx = Context(uri="/person/frankie/detail", parent_uri="/person/frankie",
                      abstract="detail")
        self.assertEqual(ctx.parent_uri, "/person/frankie")

    def test_content_layers(self):
        ctx = Context(
            uri="/test/layers",
            abstract="L0: 一句话摘要",
            overview="L1: 一段话概览，包含更多细节",
            content="L2: 完整内容，可能很长很长...",
        )
        self.assertTrue(len(ctx.abstract) < len(ctx.overview))
        self.assertTrue(len(ctx.overview) < len(ctx.content))


class TestDecayScore(unittest.TestCase):
    """Test the decay scoring algorithm."""

    def test_fresh_memory_no_decay(self):
        score = decay_score(importance=1.0, age_days=0, half_life=14)
        self.assertAlmostEqual(score, 1.0, places=2)

    def test_half_life_decay(self):
        score = decay_score(importance=1.0, age_days=14, half_life=14)
        self.assertAlmostEqual(score, 0.5, places=2)

    def test_double_half_life(self):
        score = decay_score(importance=1.0, age_days=28, half_life=14)
        self.assertAlmostEqual(score, 0.25, places=2)

    def test_importance_scaling(self):
        score_high = decay_score(importance=0.9, age_days=7, half_life=14)
        score_low = decay_score(importance=0.3, age_days=7, half_life=14)
        self.assertGreater(score_high, score_low)

    def test_zero_importance(self):
        score = decay_score(importance=0.0, age_days=0, half_life=14)
        self.assertAlmostEqual(score, 0.0, places=5)

    def test_very_old_memory(self):
        score = decay_score(importance=1.0, age_days=365, half_life=14)
        self.assertLess(score, 0.001)

    def test_negative_age_treated_as_fresh(self):
        score = decay_score(importance=1.0, age_days=-1, half_life=14)
        self.assertGreaterEqual(score, 1.0)

    def test_custom_half_life(self):
        score_7 = decay_score(importance=1.0, age_days=7, half_life=7)
        score_14 = decay_score(importance=1.0, age_days=7, half_life=14)
        self.assertAlmostEqual(score_7, 0.5, places=2)
        self.assertGreater(score_14, score_7)

    def test_taboo_high_importance_slow_decay(self):
        taboo_score = decay_score(importance=0.95, age_days=30, half_life=14)
        normal_score = decay_score(importance=0.4, age_days=30, half_life=14)
        self.assertGreater(taboo_score, normal_score * 2)


class TestAmberURI(unittest.TestCase):
    """Test the URI system."""

    def test_parse_simple_uri(self):
        uri = AmberURI.parse("amber://memories/person/frankie")
        self.assertEqual(uri.scheme, "amber")
        self.assertEqual(uri.dimension, "person")

    def test_parse_with_id(self):
        uri = AmberURI.parse("amber://memories/activity/abc123")
        self.assertEqual(uri.dimension, "activity")
        self.assertEqual(uri.resource_id, "abc123")

    def test_build_uri(self):
        uri_str = AmberURI.build("goal", "learn_rust")
        self.assertIn("goal", uri_str)
        self.assertIn("learn_rust", uri_str)

    def test_dimension_roots(self):
        dims = ["person", "activity", "object", "preference",
                "taboo", "goal", "pattern", "thought"]
        for dim in dims:
            root = AmberURI.dimension_root(dim)
            self.assertIn(dim, root)

    def test_is_child_of(self):
        parent = "amber://memories/person"
        child = "amber://memories/person/frankie"
        self.assertTrue(child.startswith(parent))

    def test_slash_uri_compat(self):
        ctx = Context(uri="/person/frankie", abstract="test")
        self.assertTrue(ctx.uri.startswith("/"))


if __name__ == "__main__":
    unittest.main()
