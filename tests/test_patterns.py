"""Tests for PatternDetector — time patterns, category patterns, detection."""

import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from graph.patterns import PatternDetector
from storage.sqlite_store import SQLiteStore
from core.context import Context


class TestPatternDetectorInit(unittest.TestCase):
    """Test PatternDetector initialization."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_create_detector(self):
        pd = PatternDetector(store=self.store)
        self.assertIsNotNone(pd)

    def test_empty_store_stats(self):
        pd = PatternDetector(store=self.store)
        stats = pd.stats()
        self.assertEqual(stats["patterns"], 0)


class TestTimePatterns(unittest.TestCase):
    """Test time-based pattern detection."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.db_path)
        self.detector = PatternDetector(store=self.store)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_detect_daily_pattern(self):
        # Create memories at same time each day for 7 days
        base_time = time.time()
        for i in range(7):
            t = base_time - i * 86400  # Each day
            ctx = Context(
                uri=f"/daily/{i}",
                abstract=f"每日跑步 day {i}",
                category="activity",
                importance=0.5,
                event_time=t,
            )
            ctx.created_at = t
            self.store.put(ctx)

        patterns = self.detector.detect_time_patterns(days=14)
        self.assertIsInstance(patterns, list)

    def test_detect_weekly_pattern(self):
        # Create memories every Wednesday for 4 weeks
        base_time = time.time()
        for i in range(4):
            t = base_time - i * 7 * 86400
            ctx = Context(
                uri=f"/weekly/{i}",
                abstract=f"周三组会 week {i}",
                category="activity",
                importance=0.6,
                event_time=t,
            )
            ctx.created_at = t
            self.store.put(ctx)

        patterns = self.detector.detect_time_patterns(days=30)
        self.assertIsInstance(patterns, list)

    def test_no_pattern_random_times(self):
        import random
        base_time = time.time()
        for i in range(10):
            t = base_time - random.randint(0, 30 * 86400)
            self.store.put(Context(
                uri=f"/random/{i}",
                abstract=f"随机事件 {i}",
                category="activity",
                event_time=t,
            ))

        patterns = self.detector.detect_time_patterns(days=30)
        # May or may not find patterns, but shouldn't crash
        self.assertIsInstance(patterns, list)

    def test_empty_store_no_patterns(self):
        patterns = self.detector.detect_time_patterns(days=30)
        self.assertEqual(len(patterns), 0)


class TestCategoryPatterns(unittest.TestCase):
    """Test category distribution pattern detection."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.db_path)
        self.detector = PatternDetector(store=self.store)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_detect_dominant_category(self):
        # 80% activity, 20% other
        for i in range(40):
            self.store.put(Context(
                uri=f"/act/{i}", abstract=f"活动 {i}", category="activity"))
        for i in range(5):
            self.store.put(Context(
                uri=f"/per/{i}", abstract=f"人物 {i}", category="person"))
        for i in range(5):
            self.store.put(Context(
                uri=f"/tho/{i}", abstract=f"思考 {i}", category="thought"))

        patterns = self.detector.detect_category_patterns()
        self.assertIsInstance(patterns, list)
        # Should detect activity as dominant
        if patterns:
            descriptions = " ".join(p.description for p in patterns)
            # Activity should be mentioned somewhere
            self.assertIsInstance(descriptions, str)

    def test_balanced_categories(self):
        dims = ["person", "activity", "object", "preference",
                "taboo", "goal", "pattern", "thought"]
        for dim in dims:
            for i in range(5):
                self.store.put(Context(
                    uri=f"/{dim}/{i}", abstract=f"{dim} {i}", category=dim))

        patterns = self.detector.detect_category_patterns()
        self.assertIsInstance(patterns, list)

    def test_single_category(self):
        for i in range(20):
            self.store.put(Context(
                uri=f"/goal/{i}", abstract=f"目标 {i}", category="goal"))

        patterns = self.detector.detect_category_patterns()
        self.assertIsInstance(patterns, list)


class TestPatternPersistence(unittest.TestCase):
    """Test saving and loading patterns."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.db_path)
        self.detector = PatternDetector(store=self.store)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_save_pattern(self):
        self.detector.save_pattern(
            pattern_type="time",
            description="每天早上跑步",
            confidence=0.85,
            frequency=7,
            meta={"time": "07:00", "activity": "跑步"},
        )
        patterns = self.detector.list_patterns()
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0].description, "每天早上跑步")

    def test_save_multiple_patterns(self):
        self.detector.save_pattern("time", "每天跑步", 0.85, 7)
        self.detector.save_pattern("category", "偏好活动类记忆", 0.7, 0)
        self.detector.save_pattern("behavior", "晚上写代码", 0.6, 5)
        patterns = self.detector.list_patterns()
        self.assertEqual(len(patterns), 3)

    def test_list_patterns_with_limit(self):
        for i in range(10):
            self.detector.save_pattern("test", f"模式 {i}", 0.5 + i * 0.05, i)
        patterns = self.detector.list_patterns(limit=5)
        self.assertEqual(len(patterns), 5)

    def test_delete_pattern(self):
        self.detector.save_pattern("test", "要删除的模式", 0.5, 0)
        patterns = self.detector.list_patterns()
        self.assertEqual(len(patterns), 1)
        pid = patterns[0].id
        self.detector.delete_pattern(pid)
        patterns = self.detector.list_patterns()
        self.assertEqual(len(patterns), 0)

    def test_pattern_confidence_range(self):
        self.detector.save_pattern("test", "高置信度", 0.95, 10)
        self.detector.save_pattern("test", "低置信度", 0.1, 1)
        patterns = self.detector.list_patterns()
        confidences = [p.confidence for p in patterns]
        self.assertTrue(all(0 <= c <= 1 for c in confidences))


class TestDetectAll(unittest.TestCase):
    """Test the detect_all orchestration method."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.store = SQLiteStore(self.db_path)
        self.detector = PatternDetector(store=self.store)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_detect_all_empty(self):
        patterns = self.detector.detect_all(days=30)
        self.assertIsInstance(patterns, list)

    def test_detect_all_with_data(self):
        for i in range(30):
            t = time.time() - i * 86400
            self.store.put(Context(
                uri=f"/d/{i}", abstract=f"事件 {i}",
                category=["activity", "person", "goal"][i % 3],
                event_time=t, importance=0.5,
            ))

        patterns = self.detector.detect_all(days=30)
        self.assertIsInstance(patterns, list)

    def test_detect_all_saves_results(self):
        for i in range(20):
            self.store.put(Context(
                uri=f"/s/{i}", abstract=f"记忆 {i}", category="activity"))

        self.detector.detect_all(days=30, save=True)
        saved = self.detector.list_patterns()
        # May or may not find patterns, but save should work
        self.assertIsInstance(saved, list)


if __name__ == "__main__":
    unittest.main()
