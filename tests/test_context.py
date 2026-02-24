"""Tests for core.context — Context model, 8 dimensions, decay algorithm, URI."""

import math
import time
import unittest
from unittest.mock import patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.context import (
    Context, ContextType, MemoryCategory, EmotionTag,
    DecayParams, DEFAULT_DECAY,
)
from core.uri import URI


class TestContextType(unittest.TestCase):
    """Test the 8 context type dimensions."""

    def test_all_eight_dimensions_exist(self):
        expected = {"memory", "person", "activity", "object",
                    "preference", "taboo", "goal", "pattern", "thought"}
        actual = {ct.value for ct in ContextType}
        self.assertEqual(expected, actual)

    def test_context_type_is_string_enum(self):
        self.assertEqual(ContextType.PERSON, "person")
        self.assertEqual(ContextType.TABOO, "taboo")
        self.assertIsInstance(ContextType.MEMORY, str)

    def test_memory_category_values(self):
        expected = {"profile", "preferences", "entities", "events",
                    "taboos", "goals", "cases", "patterns", "thoughts"}
        actual = {mc.value for mc in MemoryCategory}
        self.assertEqual(expected, actual)

    def test_emotion_tag_values(self):
        expected = {"neutral", "joy", "sadness", "anger",
                    "surprise", "fear", "love", "nostalgia"}
        actual = {et.value for et in EmotionTag}
        self.assertEqual(expected, actual)


class TestDecayParams(unittest.TestCase):
    """Test DecayParams and decay_lambda calculation."""

    def test_default_half_life(self):
        self.assertEqual(DEFAULT_DECAY.half_life_days, 14.0)

    def test_decay_lambda_formula(self):
        params = DecayParams(half_life_days=14.0)
        expected = math.log(2) / 14.0
        self.assertAlmostEqual(params.decay_lambda, expected)

    def test_custom_half_life(self):
        params = DecayParams(half_life_days=30.0)
        expected = math.log(2) / 30.0
        self.assertAlmostEqual(params.decay_lambda, expected)

    def test_default_emotion_multipliers(self):
        params = DecayParams()
        self.assertEqual(params.emotion_multipliers["neutral"], 1.0)
        self.assertEqual(params.emotion_multipliers["love"], 1.4)
        self.assertEqual(params.emotion_multipliers["nostalgia"], 1.35)

    def test_importance_floor(self):
        self.assertEqual(DEFAULT_DECAY.importance_floor, 0.05)


class TestContextCreation(unittest.TestCase):
    """Test Context dataclass creation and defaults."""

    def test_default_context(self):
        ctx = Context()
        self.assertEqual(len(ctx.id), 16)
        self.assertEqual(ctx.uri, "")
        self.assertEqual(ctx.context_type, ContextType.MEMORY)
        self.assertEqual(ctx.importance, 0.5)
        self.assertEqual(ctx.access_count, 0)
        self.assertEqual(ctx.emotion, EmotionTag.NEUTRAL)
        self.assertIsInstance(ctx.tags, list)
        self.assertIsInstance(ctx.linked_uris, list)

    def test_custom_context(self):
        ctx = Context(
            id="test123",
            uri="/wechat/messages/test",
            abstract="Test memory",
            importance=0.8,
            tags=["test", "unit"],
            emotion="joy",
        )
        self.assertEqual(ctx.id, "test123")
        self.assertEqual(ctx.uri, "/wechat/messages/test")
        self.assertEqual(ctx.importance, 0.8)
        self.assertEqual(ctx.tags, ["test", "unit"])

    def test_unique_ids(self):
        ids = {Context().id for _ in range(100)}
        self.assertEqual(len(ids), 100)

    def test_timestamps_are_set(self):
        before = time.time()
        ctx = Context()
        after = time.time()
        self.assertGreaterEqual(ctx.created_at, before)
        self.assertLessEqual(ctx.created_at, after)


class TestContextDecay(unittest.TestCase):
    """Test compute_score decay algorithm."""

    def test_fresh_memory_high_score(self):
        ctx = Context(importance=1.0)
        score = ctx.compute_score(now=ctx.last_accessed)
        self.assertGreater(score, 0.9)

    def test_half_life_decay(self):
        now = time.time()
        ctx = Context(importance=1.0, last_accessed=now - 14 * 86400)
        score = ctx.compute_score(now=now)
        # After one half-life, recency ~ 0.5
        self.assertAlmostEqual(score, 0.5, delta=0.15)

    def test_very_old_memory_has_floor(self):
        now = time.time()
        ctx = Context(importance=0.5, last_accessed=now - 365 * 86400)
        score = ctx.compute_score(now=now)
        floor = DEFAULT_DECAY.importance_floor * ctx.importance
        self.assertGreaterEqual(score, floor)

    def test_access_count_boosts_score(self):
        now = time.time()
        ctx_low = Context(importance=0.5, last_accessed=now - 7 * 86400, access_count=0)
        ctx_high = Context(importance=0.5, last_accessed=now - 7 * 86400, access_count=50)
        self.assertGreater(
            ctx_high.compute_score(now=now),
            ctx_low.compute_score(now=now),
        )

    def test_link_count_boosts_score(self):
        now = time.time()
        ctx_no_links = Context(importance=0.5, last_accessed=now, link_count=0)
        ctx_links = Context(importance=0.5, last_accessed=now, link_count=10)
        self.assertGreater(
            ctx_links.compute_score(now=now),
            ctx_no_links.compute_score(now=now),
        )

    def test_link_count_capped_at_10(self):
        now = time.time()
        ctx_10 = Context(importance=0.5, last_accessed=now, link_count=10)
        ctx_100 = Context(importance=0.5, last_accessed=now, link_count=100)
        self.assertAlmostEqual(
            ctx_10.compute_score(now=now),
            ctx_100.compute_score(now=now),
        )

    def test_emotion_boost(self):
        now = time.time()
        ctx_neutral = Context(importance=0.5, last_accessed=now, emotion="neutral")
        ctx_love = Context(importance=0.5, last_accessed=now, emotion="love")
        self.assertGreater(
            ctx_love.compute_score(now=now),
            ctx_neutral.compute_score(now=now),
        )

    def test_zero_importance_zero_score(self):
        ctx = Context(importance=0.0)
        score = ctx.compute_score()
        self.assertEqual(score, 0.0)


class TestContextMethods(unittest.TestCase):
    """Test Context helper methods."""

    def test_touch_increments_access(self):
        ctx = Context()
        old_count = ctx.access_count
        old_time = ctx.last_accessed
        time.sleep(0.01)
        ctx.touch()
        self.assertEqual(ctx.access_count, old_count + 1)
        self.assertGreater(ctx.last_accessed, old_time)

    def test_to_l0_returns_abstract(self):
        ctx = Context(abstract="Short summary", uri="/test")
        self.assertEqual(ctx.to_l0(), "Short summary")

    def test_to_l0_fallback_to_uri(self):
        ctx = Context(uri="/test/path")
        self.assertEqual(ctx.to_l0(), "/test/path")

    def test_to_l1_returns_overview(self):
        ctx = Context(overview="Detailed overview", abstract="Short")
        self.assertEqual(ctx.to_l1(), "Detailed overview")

    def test_to_l2_returns_content(self):
        ctx = Context(content="Full content here", overview="Overview")
        self.assertEqual(ctx.to_l2(), "Full content here")

    def test_to_dict_roundtrip(self):
        ctx = Context(
            uri="/test/roundtrip",
            abstract="Test",
            tags=["a", "b"],
            importance=0.7,
        )
        d = ctx.to_dict()
        ctx2 = Context.from_dict(d)
        self.assertEqual(ctx.uri, ctx2.uri)
        self.assertEqual(ctx.abstract, ctx2.abstract)
        self.assertEqual(ctx.tags, ctx2.tags)
        self.assertAlmostEqual(ctx.importance, ctx2.importance)

    def test_from_dict_ignores_extra_keys(self):
        d = {"uri": "/test", "abstract": "hi", "unknown_field": 42}
        ctx = Context.from_dict(d)
        self.assertEqual(ctx.uri, "/test")


if __name__ == "__main__":
    unittest.main()
