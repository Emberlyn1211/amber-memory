#!/usr/bin/env python3
"""Amber Memory Demo - 展示记忆系统的核心功能。

运行: python3 -m amber_memory.demo
"""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from amber_memory.core.context import Context, ContextType, DecayParams
from amber_memory.core.uri import URI
from amber_memory.storage.sqlite_store import SQLiteStore
from amber_memory.client import AmberMemory


def demo_basic():
    """基础功能演示：存储、检索、衰减。"""
    print("=" * 60)
    print("🧠 Amber Memory Demo")
    print("=" * 60)

    # 创建内存数据库（不写磁盘）
    mem = AmberMemory(db_path="/tmp/amber_demo.db")

    # --- 1. 存储记忆 ---
    print("\n📝 存储记忆...")

    mem.remember(
        "Frankie 喜欢喝泰斯卡风暴威士忌和罗斯福10号啤酒",
        source="telegram", importance=0.7,
        tags=["frankie", "偏好", "酒"],
        emotion="joy",
    )
    mem.remember(
        "Watchlace 的核心定位：以日程为骨架，以长期记忆为肌肉，以人格陪伴为皮肤的随身管家",
        source="self", importance=0.9,
        tags=["watchlace", "产品"],
    )
    mem.remember(
        "外公陈伯年 2018 年去世，Amber 在伦敦没能见最后一面",
        source="self", importance=0.95,
        tags=["家人", "外公"],
        emotion="sadness",
    )
    mem.remember(
        "小红书医美引流：主推水光针+胶原蛋白针，Frankie 有针剂资源",
        source="telegram", importance=0.6,
        tags=["搞钱", "医美", "小红书"],
    )
    mem.remember(
        "今天中午吃了沙县小吃，拌面+蒸饺",
        source="self", importance=0.1,
        tags=["日常"],
    )
    mem.remember(
        "OpenViking 的 L0/L1/L2 三级上下文设计很优雅，fork 来做 amber-memory",
        source="self", importance=0.7,
        tags=["技术", "amber-memory"],
    )

    # 模拟一些旧记忆（手动设置时间）
    old_ctx = Context(
        uri="/self/memories/2026-02-10/morning",
        parent_uri="/self/memories/2026-02-10",
        abstract="两周前的一个想法",
        overview="想做 Agent 信任基础设施，后来选了这个方向",
        content="创业方向讨论：Agent 信任基础设施 vs 艺术品数字身份 vs 数字游民工具。最终选了 Agent 信任。",
        context_type=ContextType.MEMORY,
        importance=0.6,
        tags=["创业", "决定"],
        # 14天前
        created_at=time.time() - 14 * 86400,
        last_accessed=time.time() - 14 * 86400,
        event_time=time.time() - 14 * 86400,
    )
    mem.store.put(old_ctx)

    very_old = Context(
        uri="/self/memories/2026-01-15/random",
        parent_uri="/self/memories/2026-01-15",
        abstract="一个月前的闲聊",
        overview="和朋友聊了聊天气，没什么重要的",
        content="今天天气不错，和朋友出去走了走。",
        context_type=ContextType.MEMORY,
        importance=0.15,
        tags=["日常"],
        created_at=time.time() - 40 * 86400,
        last_accessed=time.time() - 40 * 86400,
        event_time=time.time() - 40 * 86400,
    )
    mem.store.put(very_old)

    print(f"   已存储 {mem.store.count()} 条记忆")

    # --- 2. 检索 ---
    print("\n🔍 检索测试...")

    print("\n   查询: 'Frankie 喜欢什么'")
    results = mem.recall("Frankie 喜欢什么", limit=3)
    for ctx, score in results:
        print(f"   [{score:.3f}] {ctx.abstract}")

    print("\n   查询: '创业方向'")
    results = mem.recall("创业方向", limit=3)
    for ctx, score in results:
        print(f"   [{score:.3f}] {ctx.abstract}")

    print("\n   查询: '搞钱'")
    results = mem.recall("搞钱", limit=3)
    for ctx, score in results:
        print(f"   [{score:.3f}] {ctx.abstract}")

    # --- 3. 衰减排名 ---
    print("\n📊 记忆衰减排名 (Top memories by score)...")
    top = mem.top(limit=8)
    for i, (ctx, score) in enumerate(top, 1):
        age_days = (time.time() - (ctx.event_time or ctx.created_at)) / 86400
        print(f"   {i}. [{score:.3f}] (imp={ctx.importance}, age={age_days:.0f}d, "
              f"emotion={ctx.emotion}) {ctx.abstract}")

    # --- 4. 正在遗忘的记忆 ---
    print("\n💨 正在遗忘的记忆 (score < 0.1)...")
    fading = mem.fading(threshold=0.1)
    if fading:
        for ctx in fading:
            score = ctx.compute_score(mem.decay_params)
            age_days = (time.time() - (ctx.event_time or ctx.created_at)) / 86400
            print(f"   [{score:.4f}] (age={age_days:.0f}d) {ctx.abstract}")
    else:
        print("   暂无（所有记忆都还鲜活）")

    # --- 5. 链接 ---
    print("\n🔗 建立记忆链接...")
    mem.link(
        "/telegram/memories/" + datetime.now().strftime("%Y-%m-%d") + "/",
        "/self/memories/" + datetime.now().strftime("%Y-%m-%d") + "/",
        relation="related_to"
    )
    print("   已链接 Frankie 偏好 ↔ 产品定位")

    # --- 6. 统计 ---
    print("\n📈 记忆系统统计:")
    stats = mem.stats()
    print(f"   总记忆数: {stats['total']}")
    print(f"   按类型: {stats['by_type']}")
    print(f"   按来源: {stats['by_source']}")
    print(f"   衰减半衰期: {stats['decay_half_life_days']} 天")
    print(f"   数据库: {stats['db_path']}")

    # --- 7. L0/L1/L2 演示 ---
    print("\n📚 L0/L1/L2 分层加载演示:")
    ctx = mem.recall("Watchlace", limit=1)
    if ctx:
        c = ctx[0][0]
        print(f"   L0 (摘要): {c.to_l0()}")
        print(f"   L1 (概览): {c.to_l1()}")
        print(f"   L2 (全文): {c.to_l2()}")

    # --- 8. 衰减模拟 ---
    print("\n⏰ 衰减模拟 — 同一条记忆在不同时间的分数:")
    test_ctx = Context(importance=0.8, emotion="love", access_count=3)
    params = DecayParams()
    now = time.time()
    for days in [0, 1, 3, 7, 14, 30, 60, 90]:
        fake_time = now + days * 86400
        score = test_ctx.compute_score(params, now=fake_time)
        bar = "█" * int(score * 40)
        print(f"   Day {days:3d}: {score:.4f} {bar}")

    print("\n" + "=" * 60)
    print("✅ Demo 完成！")
    print(f"   数据库位置: /tmp/amber_demo.db")
    print("=" * 60)

    mem.close()


def demo_wechat():
    """尝试读取真实微信数据。"""
    print("\n" + "=" * 60)
    print("📱 WeChat 数据接入测试")
    print("=" * 60)

    mem = AmberMemory(db_path="/tmp/amber_wechat_demo.db")
    try:
        count = mem.ingest_wechat(limit=50)
        print(f"\n   导入了 {count} 条微信记忆")
        if count > 0:
            stats = mem.stats()
            print(f"   按来源: {stats['by_source']}")
            print("\n   最近的微信记忆:")
            top = mem.top(10)
            for ctx, score in top:
                print(f"   [{score:.3f}] {ctx.abstract}")
    except FileNotFoundError as e:
        print(f"\n   ⚠️ 微信数据未找到: {e}")
        print("   （需要在有微信数据的 Mac 上运行）")
    except Exception as e:
        print(f"\n   ❌ 错误: {e}")

    mem.close()


if __name__ == "__main__":
    demo_basic()
    print()
    demo_wechat()
