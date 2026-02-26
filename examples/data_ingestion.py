#!/usr/bin/env python3
"""数据源导入示例 — Bear Notes + WeChat 模拟导入。

由于真实数据源依赖本地数据库文件，本示例用 mock 数据演示导入流程。
展示 Source Layer 的完整用法：添加源 → 处理 → 存储 → 溯源。

运行: python examples/data_ingestion.py
"""

import sys
import os
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from amber_memory import AmberMemory


# ============================================================
# 模拟数据：Bear Notes
# ============================================================
MOCK_BEAR_NOTES = [
    {
        "title": "Watchlace 架构设计",
        "content": """# Watchlace 架构设计

三层架构：
1. 日程骨架 — 日历事件、提醒、时间线
2. 记忆肌肉 — Amber Memory 提供长期记忆
3. 人格皮肤 — AI 人格层，决定说话方式和行为

技术栈：FastAPI + SQLite + Ark LLM
部署：本地优先，Mac Air 上跑 uvicorn""",
        "tags": ["项目", "Watchlace", "架构"],
        "created": 7,  # 天前
    },
    {
        "title": "关于记忆衰减的思考",
        "content": """人的记忆不是硬盘，不是存了就永远在。
遗忘是一种能力，不是缺陷。

ACT-R 模型说得好：记忆的强度取决于：
- 最近是否被访问（recency）
- 被访问了多少次（frequency）
- 情感强度（emotional valence）

Amber Memory 的衰减公式就是基于这个。
半衰期 14 天，比 Nowledge 的 30 天更激进。
因为 AI 的记忆应该更像工作记忆，不是档案。""",
        "tags": ["随感/Amber", "记忆", "认知科学"],
        "created": 14,
    },
    {
        "title": "周末读书笔记：思考快与慢",
        "content": """丹尼尔·卡尼曼的《思考快与慢》

系统1：快速、直觉、自动
系统2：慢速、理性、费力

AI Agent 的记忆检索也应该有两个系统：
- 快速路径：关键词匹配 + 衰减排序（像系统1）
- 慢速路径：意图分析 + 向量检索 + LLM 重排（像系统2）

这正好对应 Amber Memory 的 recall vs smart_recall。""",
        "tags": ["读书", "认知科学"],
        "created": 10,
    },
]

# ============================================================
# 模拟数据：WeChat 消息
# ============================================================
MOCK_WECHAT_MESSAGES = [
    {
        "contact": "老王",
        "messages": [
            {"sender": "老王", "content": "明天中午一起吃饭？", "time_offset_hours": 48},
            {"sender": "self", "content": "好啊，吃什么", "time_offset_hours": 47.9},
            {"sender": "老王", "content": "公司楼下新开了一家湘菜馆", "time_offset_hours": 47.8},
            {"sender": "self", "content": "行，12点见", "time_offset_hours": 47.5},
        ],
    },
    {
        "contact": "小李",
        "messages": [
            {"sender": "小李", "content": "最近在看什么书？", "time_offset_hours": 72},
            {"sender": "self", "content": "在看思考快与慢，挺好的", "time_offset_hours": 71},
            {"sender": "小李", "content": "推荐一下《原则》，达利欧写的", "time_offset_hours": 70},
            {"sender": "self", "content": "好的加到书单了", "time_offset_hours": 69},
        ],
    },
    {
        "contact": "妈妈",
        "messages": [
            {"sender": "妈妈", "content": "最近工作忙不忙？", "time_offset_hours": 24},
            {"sender": "self", "content": "还好，周末准备休息", "time_offset_hours": 23},
            {"sender": "妈妈", "content": "注意身体，别太累了", "time_offset_hours": 22},
            {"sender": "self", "content": "知道了妈，你也注意身体", "time_offset_hours": 21},
        ],
    },
]


def main():
    print("=" * 60)
    print("Amber Memory — 数据源导入演示")
    print("=" * 60)

    DB_PATH = "/tmp/amber_ingestion.db"
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    mem = AmberMemory(DB_PATH)
    print(f"\n✅ 记忆系统: {mem}")

    # ========================================================
    # Part 1: Bear Notes 导入
    # ========================================================
    print(f"\n{'='*50}")
    print("🐻 Bear Notes 导入")
    print(f"{'='*50}")

    for note in MOCK_BEAR_NOTES:
        event_time = time.time() - note["created"] * 86400
        source_id = mem.add_source(
            source_type="text",
            origin="bear",
            raw_content=note["content"],
            metadata={"title": note["title"], "tags": note["tags"]},
            event_time=event_time,
        )
        print(f"   📄 添加源: {note['title']} (ID: {source_id})")

    # 处理所有未处理的源
    processed = mem.process_sources()
    print(f"\n   ⚙️  处理完成: {processed} 条记忆已生成")

    # ========================================================
    # Part 2: WeChat 消息导入
    # ========================================================
    print(f"\n{'='*50}")
    print("💬 WeChat 消息导入")
    print(f"{'='*50}")

    for chat in MOCK_WECHAT_MESSAGES:
        contact = chat["contact"]
        # 将消息组合成对话文本
        lines = []
        earliest_time = time.time()
        for msg in chat["messages"]:
            t = time.time() - msg["time_offset_hours"] * 3600
            earliest_time = min(earliest_time, t)
            sender = "我" if msg["sender"] == "self" else msg["sender"]
            lines.append(f"[{sender}] {msg['content']}")

        conversation = "\n".join(lines)
        source_id = mem.add_source(
            source_type="chat",
            origin="wechat",
            raw_content=conversation,
            metadata={"contact": contact, "msg_count": len(chat["messages"])},
            event_time=earliest_time,
        )
        print(f"   💬 添加源: 和{contact}的对话 ({len(chat['messages'])}条, ID: {source_id})")

    processed = mem.process_sources()
    print(f"\n   ⚙️  处理完成: {processed} 条记忆已生成")

    # ========================================================
    # Part 3: 禁忌过滤演示
    # ========================================================
    print(f"\n{'='*50}")
    print("🚫 禁忌过滤 — 敏感内容不会被导入")
    print(f"{'='*50}")

    # 先添加禁忌
    mem.add_taboo("前女友", description="不想被提及的话题")
    print("   已添加禁忌: '前女友'")

    # 尝试导入包含禁忌词的内容
    source_id = mem.add_source(
        source_type="chat",
        origin="wechat",
        raw_content="[老王] 我前女友昨天给我发消息了\n[我] 别想了，向前看",
        metadata={"contact": "老王"},
    )
    processed = mem.process_sources()
    print(f"   导入包含禁忌词的对话 → 生成 {processed} 条记忆")
    print("   → 包含'前女友'的内容被禁忌系统拦截，未生成记忆")

    # ========================================================
    # Part 4: 溯源 — 从记忆追溯到原始数据
    # ========================================================
    print(f"\n{'='*50}")
    print("🔍 溯源 — 从记忆追溯到原始数据源")
    print(f"{'='*50}")

    results = mem.recall("Watchlace", limit=1)
    if results:
        ctx, score = results[0]
        print(f"   记忆: {ctx.abstract}")
        print(f"   URI:  {ctx.uri}")

        source = mem.trace_source(ctx.uri)
        if source:
            meta = source.get("metadata", "{}")
            if isinstance(meta, str):
                import json
                meta = json.loads(meta)
            print(f"   原始来源: {source['origin']} / {source['type']}")
            print(f"   标题: {meta.get('title', 'N/A')}")
        else:
            print("   （此记忆无关联数据源）")

    # ========================================================
    # Part 5: 统计
    # ========================================================
    print(f"\n{'='*50}")
    print("📈 导入统计")
    print(f"{'='*50}")

    stats = mem.stats()
    print(f"   总记忆数: {stats['total']}")
    print(f"   按来源: {stats.get('by_source', {})}")
    print(f"   按类型: {stats.get('by_type', {})}")
    print(f"   数据源总数: {mem.store.source_count()}")

    # 检索验证
    print(f"\n🔍 检索验证:")
    for query in ["Watchlace", "老王", "读书"]:
        results = mem.recall(query, limit=2)
        print(f"   '{query}': {len(results)} 条结果")
        for ctx, score in results:
            print(f"      [{score:.3f}] {ctx.abstract}")

    mem.close()
    print(f"\n🎉 完成！")


if __name__ == "__main__":
    main()
