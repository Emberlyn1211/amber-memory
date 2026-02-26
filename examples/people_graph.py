#!/usr/bin/env python3
"""人物图谱构建示例 — 自动提取人物、建立关系网络。

展示 PeopleGraph 的完整用法：添加人物、建立关系、记录互动、查询图谱。

运行: python examples/people_graph.py
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from amber_memory import AmberMemory, PeopleGraph


def main():
    print("=" * 60)
    print("Amber Memory — 人物图谱构建演示")
    print("=" * 60)

    # --------------------------------------------------------
    # 1. 初始化
    # --------------------------------------------------------
    DB_PATH = "/tmp/amber_people_graph.db"
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    mem = AmberMemory(DB_PATH)
    graph = mem.people  # PeopleGraph 实例
    print(f"\n✅ 记忆系统: {mem}")

    # --------------------------------------------------------
    # 2. 添加人物
    # --------------------------------------------------------
    print("\n👥 添加人物...")

    wang = graph.add_person(
        name="老王",
        relationship="colleague",
        description="同组同事，负责海外业务线，性格开朗",
        aliases=["王大锤", "Wang"],
        importance=0.7,
        meta={"department": "海外业务", "city": "上海"},
    )
    print(f"   ✅ {wang.name} (ID: {wang.id})")

    xiaoli = graph.add_person(
        name="小李",
        relationship="friend",
        description="大学室友，现在在杭州做前端开发",
        aliases=["李明", "Leon"],
        importance=0.6,
        meta={"company": "阿里", "city": "杭州"},
    )
    print(f"   ✅ {xiaoli.name} (ID: {xiaoli.id})")

    mom = graph.add_person(
        name="妈妈",
        relationship="family",
        description="退休教师，住在老家",
        aliases=["老妈"],
        importance=0.95,
    )
    print(f"   ✅ {mom.name} (ID: {mom.id})")

    sarah = graph.add_person(
        name="Sarah",
        relationship="friend",
        description="在东京认识的朋友，做设计师",
        aliases=["莎拉"],
        importance=0.5,
        meta={"city": "东京", "profession": "UI设计"},
    )
    print(f"   ✅ {sarah.name} (ID: {sarah.id})")

    boss = graph.add_person(
        name="张总",
        relationship="colleague",
        description="部门总监，技术出身，决策果断",
        importance=0.8,
    )
    print(f"   ✅ {boss.name} (ID: {boss.id})")

    # --------------------------------------------------------
    # 3. 建立关系
    # --------------------------------------------------------
    print("\n🔗 建立关系...")

    graph.add_relationship(wang.id, boss.id, "上下级",
                           description="老王向张总汇报", strength=0.8)
    print(f"   {wang.name} ←上下级→ {boss.name}")

    graph.add_relationship(wang.id, xiaoli.id, "朋友",
                           description="通过 Frankie 认识", strength=0.4)
    print(f"   {wang.name} ←朋友→ {xiaoli.name}")

    graph.add_relationship(sarah.id, xiaoli.id, "网友",
                           description="在 Twitter 上互关", strength=0.3)
    print(f"   {sarah.name} ←网友→ {xiaoli.name}")

    # --------------------------------------------------------
    # 4. 记录互动
    # --------------------------------------------------------
    print("\n💬 记录互动...")

    # 存一些相关记忆，然后关联互动
    ctx1 = mem.remember(
        "和老王一起吃火锅，聊了日本出差的事",
        source="diary", importance=0.4, tags=["老王", "社交"],
    )
    graph.record_interaction(wang.id, "一起吃火锅", ctx1.uri, "joy")
    print(f"   📝 和{wang.name}吃火锅")

    ctx2 = mem.remember(
        "老王帮忙 review 了代码，提了几个好建议",
        source="work", importance=0.5, tags=["老王", "工作"],
    )
    graph.record_interaction(wang.id, "代码 review", ctx2.uri, "neutral")
    print(f"   📝 {wang.name}帮忙 review 代码")

    ctx3 = mem.remember(
        "周末和小李视频通话，聊了两个小时",
        source="wechat", importance=0.4, tags=["小李", "社交"],
    )
    graph.record_interaction(xiaoli.id, "视频通话", ctx3.uri, "joy")
    print(f"   📝 和{xiaoli.name}视频通话")

    ctx4 = mem.remember(
        "给妈妈打电话，她说最近血压有点高",
        source="phone", importance=0.7, emotion="sadness", tags=["妈妈", "健康"],
    )
    graph.record_interaction(mom.id, "电话关心健康", ctx4.uri, "sadness")
    print(f"   📝 给{mom.name}打电话")

    # --------------------------------------------------------
    # 5. 查询图谱
    # --------------------------------------------------------
    print(f"\n{'='*50}")
    print("📊 图谱查询")
    print(f"{'='*50}")

    # 按关系类型列出
    print("\n   👔 同事:")
    for p in graph.list_people(relationship="colleague"):
        print(f"      {p.name} — {p.description} (互动 {p.interaction_count} 次)")

    print("\n   👫 朋友:")
    for p in graph.list_people(relationship="friend"):
        print(f"      {p.name} — {p.description}")

    print("\n   👨‍👩‍👦 家人:")
    for p in graph.list_people(relationship="family"):
        print(f"      {p.name} — {p.description}")

    # 按名字查找
    print("\n   🔍 查找 '老王':")
    found = graph.find_person("老王")
    if found:
        print(f"      名字: {found.name}")
        print(f"      别名: {found.aliases}")
        print(f"      关系: {found.relationship}")
        print(f"      描述: {found.description}")
        print(f"      重要性: {found.importance}")
        print(f"      互动次数: {found.interaction_count}")

    # 按别名查找
    print("\n   🔍 按别名查找 'Leon':")
    found = graph.find_person("Leon")
    if found:
        print(f"      找到: {found.name} ({found.aliases})")

    # 查看某人的关系网络
    print(f"\n   🕸️  {wang.name}的关系网络:")
    rels = graph.get_relationships(wang.id)
    for rel in rels:
        other_id = rel.person_b if rel.person_a == wang.id else rel.person_a
        other = graph.get_person(other_id)
        other_name = other.name if other else other_id
        print(f"      ←{rel.relation}→ {other_name} (强度: {rel.strength})")

    # 查看互动历史
    print(f"\n   📅 {wang.name}的互动历史:")
    interactions = graph.get_interactions(wang.id, limit=5)
    for inter in interactions:
        from datetime import datetime
        dt = datetime.fromtimestamp(inter["timestamp"]).strftime("%m-%d %H:%M")
        print(f"      [{dt}] {inter['context']} ({inter['sentiment']})")

    # --------------------------------------------------------
    # 6. 统计
    # --------------------------------------------------------
    print(f"\n📈 图谱统计:")
    stats = graph.stats()
    for k, v in stats.items():
        print(f"   {k}: {v}")

    mem.close()
    print(f"\n🎉 完成！")


if __name__ == "__main__":
    main()
