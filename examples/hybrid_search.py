#!/usr/bin/env python3
"""混合检索示例 — text + vector + decay 三路融合。

用 mock embedding 函数替代真实向量模型，展示完整的混合检索流程。

运行: python examples/hybrid_search.py
"""

import asyncio
import hashlib
import math
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from amber_memory import AmberMemory, Retriever
from amber_memory.retrieve.retriever import pack_vector


# ============================================================
# Mock Embedding — 用哈希生成伪向量，模拟语义相似度
# ============================================================
VECTOR_DIM = 64  # 真实模型通常 768/1024 维，这里用 64 维演示


def text_to_fake_vector(text: str) -> list:
    """用文本哈希生成伪向量。相似文本会有一定的向量相似度。"""
    # 基于字符 bigram 生成稳定的伪向量
    vec = [0.0] * VECTOR_DIM
    chars = list(text)
    for i, ch in enumerate(chars):
        idx = ord(ch) % VECTOR_DIM
        vec[idx] += 1.0
    # 归一化
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


async def mock_embed_fn(texts: list) -> list:
    """模拟 embedding 函数，返回伪向量列表。"""
    return [text_to_fake_vector(t) for t in texts]


async def main():
    print("=" * 60)
    print("Amber Memory — 混合检索演示 (text + vector + decay)")
    print("=" * 60)

    # --------------------------------------------------------
    # 1. 准备数据
    # --------------------------------------------------------
    DB_PATH = "/tmp/amber_hybrid_search.db"
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    mem = AmberMemory(DB_PATH, embed_fn=mock_embed_fn)
    print(f"\n✅ 记忆系统: {mem}")

    # 存储多条记忆，模拟不同时间和重要性
    test_memories = [
        # (内容, 来源, 重要性, 情感, 标签, 时间偏移天数)
        ("Frankie 喜欢泰斯卡风暴威士忌，不加冰纯饮", "telegram", 0.8, "joy", ["偏好", "酒"], 0),
        ("周末和小李去了精酿啤酒吧，试了 IPA 和世涛", "diary", 0.4, "joy", ["社交", "酒"], 3),
        ("Frankie 不喝白酒，觉得太辣", "telegram", 0.6, "neutral", ["偏好", "酒"], 10),
        ("今天买了一瓶山崎 12 年，准备周末品鉴", "self", 0.5, "joy", ["偏好", "威士忌"], 1),
        ("老王推荐了一家日本居酒屋，清酒很不错", "wechat", 0.3, "neutral", ["社交", "酒"], 7),
        ("Watchlace 项目进度：完成了记忆模块的设计", "notes", 0.9, "neutral", ["项目"], 2),
        ("下周要和投资人开会讨论融资方案", "calendar", 0.85, "neutral", ["工作", "融资"], 0),
        ("外公喜欢喝绍兴黄酒，每次过年都要温一壶", "diary", 0.7, "nostalgia", ["家人", "酒"], 30),
    ]

    print(f"\n📝 存储 {len(test_memories)} 条记忆...")
    stored_contexts = []
    for content, source, importance, emotion, tags, days_ago in test_memories:
        event_time = time.time() - days_ago * 86400
        ctx = mem.remember(
            content, source=source, importance=importance,
            emotion=emotion, tags=tags, event_time=event_time,
        )
        stored_contexts.append(ctx)
        print(f"   [{importance:.1f}] [{emotion:8s}] {content[:40]}...")

    # --------------------------------------------------------
    # 2. 为所有记忆生成向量索引
    # --------------------------------------------------------
    print(f"\n🔢 生成向量索引...")
    for ctx in stored_contexts:
        await mem.retriever.index_context(ctx)
    print(f"   已索引 {len(stored_contexts)} 条记忆")

    # --------------------------------------------------------
    # 3. 纯文本检索
    # --------------------------------------------------------
    print(f"\n{'='*50}")
    print("🔍 纯文本检索: 'Frankie 喜欢喝什么酒'")
    print(f"{'='*50}")
    results = mem.recall("Frankie 喜欢喝什么酒", limit=5)
    for i, (ctx, score) in enumerate(results, 1):
        print(f"   {i}. [{score:.3f}] {ctx.abstract}")

    # --------------------------------------------------------
    # 4. 混合检索 — 不同权重配比
    # --------------------------------------------------------
    query = "威士忌偏好"

    configs = [
        ("文本优先", 0.7, 0.2, 0.1),
        ("向量优先", 0.2, 0.6, 0.2),
        ("均衡模式", 0.4, 0.4, 0.2),
        ("衰减优先", 0.2, 0.2, 0.6),
    ]

    for name, tw, vw, dw in configs:
        print(f"\n{'='*50}")
        print(f"🔍 混合检索 [{name}]: '{query}'")
        print(f"   权重: text={tw} vector={vw} decay={dw}")
        print(f"{'='*50}")
        results = await mem.hybrid_recall(
            query, limit=5,
            text_weight=tw, vector_weight=vw, decay_weight=dw,
        )
        for i, (ctx, score) in enumerate(results, 1):
            days_old = (time.time() - (ctx.event_time or ctx.created_at)) / 86400
            print(f"   {i}. [{score:.3f}] (重要性={ctx.importance:.1f}, "
                  f"{days_old:.0f}天前, {ctx.emotion}) {ctx.abstract}")

    # --------------------------------------------------------
    # 5. 衰减效果对比
    # --------------------------------------------------------
    print(f"\n{'='*50}")
    print("⏳ 衰减效果对比")
    print(f"{'='*50}")
    print("   记忆越新、越重要、情感越强 → 分数越高\n")

    from amber_memory.core.context import DecayParams
    params = DecayParams(half_life_days=14.0)

    for ctx in stored_contexts:
        score = ctx.compute_score(params)
        days_old = (time.time() - (ctx.event_time or ctx.created_at)) / 86400
        bar = "█" * int(score * 40)
        print(f"   {score:.3f} {bar}")
        print(f"         {ctx.abstract[:50]} ({days_old:.0f}天前, {ctx.emotion})")

    # --------------------------------------------------------
    # 6. 禁忌过滤
    # --------------------------------------------------------
    print(f"\n{'='*50}")
    print("🚫 禁忌过滤演示")
    print(f"{'='*50}")

    # 添加禁忌：不提白酒
    mem.add_taboo("白酒", description="Frankie 不想被提醒白酒相关话题")
    print("   已添加禁忌: '白酒'")

    print("\n   检索 '酒' (启用禁忌过滤):")
    results = mem.recall("酒", limit=5, respect_taboos=True)
    for i, (ctx, score) in enumerate(results, 1):
        print(f"   {i}. [{score:.3f}] {ctx.abstract}")
    print("   → 注意：包含'白酒'的记忆已被过滤")

    mem.close()
    print(f"\n🎉 完成！")


if __name__ == "__main__":
    asyncio.run(main())
