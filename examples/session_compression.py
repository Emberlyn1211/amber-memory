#!/usr/bin/env python3
"""Session 压缩完整示例 — 展示 extract → dedup → store 管线。

模拟一段对话，用 mock LLM 替代真实 API，展示完整的记忆提取流程。

运行: python examples/session_compression.py
"""

import asyncio
import json
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from amber_memory import (
    AmberMemory, SessionCompressor, MemoryExtractor,
    MemoryDeduplicator, SQLiteStore,
)
from amber_memory.session.memory_extractor import CandidateMemory


# ============================================================
# Mock LLM — 模拟 LLM 返回，不需要真实 API
# ============================================================
MOCK_EXTRACTION_RESPONSE = json.dumps({
    "memories": [
        {
            "category": "person",
            "abstract": "老王：同事，负责海外业务",
            "overview": "老王是同组同事，负责海外业务线，下个月要去日本出差",
            "content": "老王是 Frankie 的同组同事，负责海外业务线。计划下个月去日本出差。"
        },
        {
            "category": "activity",
            "abstract": "和老王吃火锅",
            "overview": "今天中午和老王一起去吃了火锅，聊了工作和出差计划",
            "content": "今天中午和老王一起去公司附近吃了火锅，老王提到下个月要去日本出差。"
        },
        {
            "category": "goal",
            "abstract": "下周开始跑步减肥",
            "overview": "Frankie 决定下周开始每天跑步，目标是减肥",
            "content": "Frankie 决定从下周开始每天跑步，目标是减肥健身。"
        },
        {
            "category": "taboo",
            "abstract": "不要在老王面前提前女友",
            "overview": "老王的前女友是敏感话题，不要在他面前提起",
            "content": "千万不要在老王面前提他前女友的事情，这是禁忌话题。"
        },
        {
            "category": "preference",
            "abstract": "Frankie 喜欢吃火锅",
            "overview": "Frankie 喜欢吃火锅，经常和同事一起去",
            "content": "Frankie 喜欢吃火锅，今天又和老王去吃了。"
        }
    ]
}, ensure_ascii=False)

# 模拟去重决策：对于新记忆，默认 create
MOCK_DEDUP_RESPONSE = json.dumps({
    "decision": "create",
    "reason": "No similar memory found",
    "list": []
})

# 模拟重要性评估
MOCK_IMPORTANCE_RESPONSES = {
    "老王": "0.6",
    "火锅": "0.3",
    "跑步": "0.5",
    "前女友": "0.8",
    "喜欢": "0.4",
}

# 调用计数器
call_count = {"extract": 0, "dedup": 0, "importance": 0}


async def mock_llm(prompt: str) -> str:
    """模拟 LLM 调用，根据 prompt 内容返回不同结果。"""
    # 记忆提取 prompt
    if "记忆提取" in prompt or "memory" in prompt.lower() and "extraction" in prompt.lower():
        call_count["extract"] += 1
        print(f"   🤖 [Mock LLM] 记忆提取调用 #{call_count['extract']}")
        return MOCK_EXTRACTION_RESPONSE

    # 去重决策 prompt
    if "重复" in prompt or "dedup" in prompt.lower() or "决策" in prompt:
        call_count["dedup"] += 1
        print(f"   🤖 [Mock LLM] 去重决策调用 #{call_count['dedup']}")
        return MOCK_DEDUP_RESPONSE

    # 重要性评估 prompt
    if "重要性" in prompt or "评估" in prompt:
        call_count["importance"] += 1
        for key, val in MOCK_IMPORTANCE_RESPONSES.items():
            if key in prompt:
                return val
        return "0.5"

    # 默认返回
    return MOCK_EXTRACTION_RESPONSE


async def main():
    print("=" * 60)
    print("Amber Memory — Session 压缩管线演示")
    print("=" * 60)

    # --------------------------------------------------------
    # 1. 准备：创建记忆系统
    # --------------------------------------------------------
    DB_PATH = "/tmp/amber_session_demo.db"
    # 清理旧数据
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    mem = AmberMemory(DB_PATH, llm_fn=mock_llm)
    print(f"\n✅ 记忆系统: {mem}")

    # --------------------------------------------------------
    # 2. 模拟对话消息
    # --------------------------------------------------------
    messages = [
        {"role": "user", "content": "今天中午和老王去吃了火锅"},
        {"role": "assistant", "content": "听起来不错！老王是你同事吗？"},
        {"role": "user", "content": "对，同一个组的，他负责海外业务。他说下个月要去日本出差"},
        {"role": "assistant", "content": "日本出差挺好的，你有什么计划吗？"},
        {"role": "user", "content": "我决定下周开始每天跑步减肥"},
        {"role": "assistant", "content": "加油！坚持就是胜利"},
        {"role": "user", "content": "对了，千万别在老王面前提他前女友，他会很不高兴"},
    ]

    print(f"\n💬 输入对话 ({len(messages)} 条消息):")
    for m in messages:
        role = "👤" if m["role"] == "user" else "🤖"
        print(f"   {role} {m['content']}")

    # --------------------------------------------------------
    # 3. 执行 Session 压缩
    # --------------------------------------------------------
    print(f"\n⚙️  开始 Session 压缩管线...")
    print("   Pipeline: extract → dedup → store")
    print()

    memories = await mem.compress_session(
        messages=messages,
        user="Frankie",
        session_id="demo-session-001",
        summary="Frankie 和同事老王吃火锅，聊了出差和减肥计划",
    )

    # --------------------------------------------------------
    # 4. 查看提取结果
    # --------------------------------------------------------
    print(f"\n📦 提取结果: {len(memories)} 条记忆")
    print("-" * 50)
    for i, ctx in enumerate(memories, 1):
        print(f"\n  [{i}] 类型: {ctx.context_type} | 分类: {ctx.category}")
        print(f"      URI:  {ctx.uri}")
        print(f"      L0:   {ctx.abstract}")
        print(f"      L1:   {ctx.overview}")
        print(f"      L2:   {ctx.content}")
        print(f"      重要性: {ctx.importance:.2f} | 情感: {ctx.emotion}")

    # --------------------------------------------------------
    # 5. 验证存储
    # --------------------------------------------------------
    print(f"\n💾 验证存储...")
    stats = mem.stats()
    print(f"   总记忆数: {stats['total']}")
    print(f"   按类型: {stats.get('by_type', {})}")

    # --------------------------------------------------------
    # 6. 检索验证
    # --------------------------------------------------------
    print(f"\n🔍 检索验证:")

    print("   查询 '老王':")
    results = mem.recall("老王", limit=3)
    for ctx, score in results:
        print(f"      [{score:.3f}] {ctx.abstract}")

    print("   查询 '减肥':")
    results = mem.recall("减肥", limit=3)
    for ctx, score in results:
        print(f"      [{score:.3f}] {ctx.abstract}")

    # --------------------------------------------------------
    # 7. LLM 调用统计
    # --------------------------------------------------------
    print(f"\n📊 Mock LLM 调用统计:")
    for k, v in call_count.items():
        print(f"   {k}: {v} 次")

    mem.close()
    print(f"\n🎉 完成！")


if __name__ == "__main__":
    asyncio.run(main())
