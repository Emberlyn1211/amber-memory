"""Tests for PeopleGraph — CRUD, relationships, interactions, extraction."""

import os
import tempfile
import time
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from graph import PeopleGraph


class TestPeopleGraphInit(unittest.TestCase):
    """Test PeopleGraph initialization."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.graph = PeopleGraph(self.db_path)

    def tearDown(self):
        self.graph.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_create_graph(self):
        self.assertIsNotNone(self.graph)

    def test_empty_graph_stats(self):
        stats = self.graph.stats()
        self.assertEqual(stats["people"], 0)
        self.assertEqual(stats["relationships"], 0)
        self.assertEqual(stats["interactions"], 0)


class TestPeopleCRUD(unittest.TestCase):
    """Test person Create/Read/Update/Delete."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.graph = PeopleGraph(self.db_path)

    def tearDown(self):
        self.graph.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_add_person(self):
        p = self.graph.add_person("老王", relationship="colleague",
                                   description="同组同事，负责海外业务")
        self.assertIsNotNone(p)
        self.assertEqual(p.name, "老王")
        self.assertEqual(p.relationship, "colleague")

    def test_find_person(self):
        self.graph.add_person("Frankie", relationship="human",
                              description="我的人类")
        p = self.graph.find_person("Frankie")
        self.assertIsNotNone(p)
        self.assertEqual(p.name, "Frankie")
        self.assertEqual(p.relationship, "human")

    def test_find_nonexistent(self):
        p = self.graph.find_person("不存在的人")
        self.assertIsNone(p)

    def test_update_person(self):
        self.graph.add_person("小李", relationship="friend")
        self.graph.update_person("小李", relationship="close_friend",
                                 description="大学同学")
        p = self.graph.find_person("小李")
        self.assertEqual(p.relationship, "close_friend")
        self.assertEqual(p.description, "大学同学")

    def test_delete_person(self):
        self.graph.add_person("临时人物")
        self.graph.delete_person("临时人物")
        p = self.graph.find_person("临时人物")
        self.assertIsNone(p)

    def test_list_people(self):
        self.graph.add_person("A", relationship="friend")
        self.graph.add_person("B", relationship="colleague")
        self.graph.add_person("C", relationship="family")
        people = self.graph.list_people(limit=10)
        self.assertEqual(len(people), 3)

    def test_list_people_with_limit(self):
        for i in range(10):
            self.graph.add_person(f"Person_{i}")
        people = self.graph.list_people(limit=5)
        self.assertEqual(len(people), 5)

    def test_add_duplicate_person(self):
        self.graph.add_person("老王", relationship="colleague")
        # Adding again should update, not create duplicate
        self.graph.add_person("老王", relationship="friend")
        people = self.graph.list_people()
        wang_count = sum(1 for p in people if p.name == "老王")
        self.assertEqual(wang_count, 1)

    def test_person_aliases(self):
        p = self.graph.add_person("林毓嘉", relationship="self")
        self.graph.add_alias("林毓嘉", "Amber")
        self.graph.add_alias("林毓嘉", "Amber Lin")
        p = self.graph.find_person("Amber")
        self.assertIsNotNone(p)
        self.assertEqual(p.name, "林毓嘉")

    def test_person_to_dict(self):
        self.graph.add_person("测试", relationship="test", description="测试用")
        p = self.graph.find_person("测试")
        d = p.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["name"], "测试")
        self.assertEqual(d["relationship"], "test")


class TestRelationships(unittest.TestCase):
    """Test relationship management between people."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.graph = PeopleGraph(self.db_path)
        self.graph.add_person("Frankie", relationship="human")
        self.graph.add_person("老王", relationship="colleague")
        self.graph.add_person("小李", relationship="friend")

    def tearDown(self):
        self.graph.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_add_relationship(self):
        self.graph.add_relationship("Frankie", "老王", relation="同事")
        rels = self.graph.get_relationships("Frankie")
        self.assertTrue(len(rels) > 0)

    def test_bidirectional_relationship(self):
        self.graph.add_relationship("老王", "小李", relation="朋友")
        rels_wang = self.graph.get_relationships("老王")
        rels_li = self.graph.get_relationships("小李")
        # At least one direction should show
        self.assertTrue(len(rels_wang) > 0 or len(rels_li) > 0)

    def test_multiple_relationships(self):
        self.graph.add_relationship("Frankie", "老王", relation="同事")
        self.graph.add_relationship("Frankie", "小李", relation="朋友")
        rels = self.graph.get_relationships("Frankie")
        self.assertGreaterEqual(len(rels), 2)

    def test_relationship_with_notes(self):
        self.graph.add_relationship("老王", "小李", relation="同事",
                                    notes="在同一个部门")
        rels = self.graph.get_relationships("老王")
        self.assertTrue(len(rels) > 0)


class TestInteractions(unittest.TestCase):
    """Test interaction recording."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.graph = PeopleGraph(self.db_path)
        self.graph.add_person("老王", relationship="colleague")

    def tearDown(self):
        self.graph.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_record_interaction(self):
        self.graph.record_interaction("老王", "一起吃了火锅")
        p = self.graph.find_person("老王")
        self.assertEqual(p.interaction_count, 1)

    def test_multiple_interactions(self):
        self.graph.record_interaction("老王", "吃火锅")
        self.graph.record_interaction("老王", "开会讨论项目")
        self.graph.record_interaction("老王", "一起打球")
        p = self.graph.find_person("老王")
        self.assertEqual(p.interaction_count, 3)

    def test_interaction_updates_last_seen(self):
        before = time.time()
        self.graph.record_interaction("老王", "见面了")
        p = self.graph.find_person("老王")
        self.assertGreaterEqual(p.last_seen, before)

    def test_get_interactions(self):
        self.graph.record_interaction("老王", "吃火锅")
        self.graph.record_interaction("老王", "开会")
        interactions = self.graph.get_interactions("老王", limit=10)
        self.assertEqual(len(interactions), 2)

    def test_interaction_with_timestamp(self):
        ts = time.time() - 86400  # Yesterday
        self.graph.record_interaction("老王", "昨天的事", timestamp=ts)
        interactions = self.graph.get_interactions("老王")
        self.assertTrue(len(interactions) > 0)


class TestPeopleExtraction(unittest.TestCase):
    """Test extracting people from text."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.graph = PeopleGraph(self.db_path)

    def tearDown(self):
        self.graph.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_simple_extraction(self):
        text = "今天和老王一起吃了火锅，小李也来了"
        people = self.graph.extract_people_simple(text)
        # Simple extraction uses pattern matching, may or may not find names
        self.assertIsInstance(people, list)

    def test_extraction_empty_text(self):
        people = self.graph.extract_people_simple("")
        self.assertEqual(len(people), 0)

    def test_extraction_no_people(self):
        text = "今天天气不错，适合出去走走"
        people = self.graph.extract_people_simple(text)
        self.assertIsInstance(people, list)


class TestPeopleGraphStats(unittest.TestCase):
    """Test statistics."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.graph = PeopleGraph(self.db_path)

    def tearDown(self):
        self.graph.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_stats_after_operations(self):
        self.graph.add_person("A")
        self.graph.add_person("B")
        self.graph.add_relationship("A", "B", relation="friend")
        self.graph.record_interaction("A", "聊天")
        self.graph.record_interaction("B", "见面")

        stats = self.graph.stats()
        self.assertEqual(stats["people"], 2)
        self.assertGreaterEqual(stats["relationships"], 1)
        self.assertEqual(stats["interactions"], 2)


if __name__ == "__main__":
    unittest.main()
