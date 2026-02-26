#!/usr/bin/env python3
"""禁忌系统使用示例 — 管理敏感话题，防止意外召回。

禁忌在两个层面生效：
1. 检索层：recall() 时过滤包含禁忌词的结果
2. 数据源层：process_sources() 时拦截包含禁忌词的内容

运行: python examples/taboo_system.py
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from amber_memory import AmberMemory


def main():
    print("=" * 60)
    print("Amber Memory — 禁忌系统演示")
    print("=" * 60)

    DB_PATH = "/tmp/amber_taboo.db"
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    mem = AmberMemory(DB_PATH)
    print(f"\n✅ 记忆系统: {mem}")

    # ========================================================
    # 1. 存储一些记忆（包含敏感内容）
    # ========================================================
    print("\n📝 存储记忆...")

    memories_data = [
        ("和老王吃火锅，聊了很多", "diary", 0.5, ["老王", "社交"]),
        ("老王提到他前女友最近结婚了", "wechat", 0.3, ["老王", "八卦"]),
        ("Frankie 的前女友小美在朋友圈发了旅行照", "wechat", 0.2, ["社交"]),
        ("今天股票亏了 3000 块", "self", 0.4, ["投资", "亏损"]),
        ("这个月投资组合整体亏损 15%", "finance", 0.5, ["投资", "亏损"]),
        ("Frankie 喜欢泰斯卡威士忌", "telegram", 0.7, ["偏好"]),
        ("周末去了新开的精酿酒吧", "diary", 0.4, ["社交", "酒"]),
        ("和小李讨论了创业想法", "wechat", 0.6, ["创业", "小李"]),
    ]

    for content, source, importance, tags in memories_data:
        mem.remember(content, source=source, importance=importance, tags=tags)
        print(f"   [{importance:.1f}] {content}")

    # ========================================================
    # 2. 检索（无禁忌）
    # ========================================================
    print(f"\n{'='*50}")
    print("🔍 检索 '老王'（无禁忌过滤）")
    print(f"{'='*50}")

    results = mem.recall("老王", limit=5, respect_taboos=False)
    for ctx, score in results:
        print(f"   [{score:.3f}] {ctx.abstract}")
    print(f"   → 共 {len(results)} 条结果，包含所有内容")

    # ========================================================
    # 3. 添加禁忌
    # ========================================================
    print(f"\n{'='*50}")
    print("🚫 添加禁忌规则")
    print(f"{'='*50}")

    t1 = mem.add_taboo(
        pattern="前女友",
        description="不想被提及任何人的前女友话题",
        scope="global",
    )
    print(f"   ✅ 禁忌 1: '前女友' (ID: {t1}, 全局)")

    t2 = mem.add_taboo(
        pattern="亏损",
        description="投资亏损是敏感话题，不要主动提起",
        scope="global",
    )
    print(f"   ✅ 禁忌 2: '亏损' (ID: {t2}, 全局)")

    t3 = mem.add_taboo(
        pattern="亏了",
        description="同上，另一种表述",
        scope="global",
    )
    print(f"   ✅ 禁忌 3: '亏了' (ID: {t3}, 全局)")

    # ========================================================
    # 4. 检索（启用禁忌）
    # ========================================================
    print(f"\n{'='*50}")
    print("🔍 检索 '老王'（启用禁忌过滤）")
    print(f"{'='*50}")

    results = mem.recall("老王", limit=5, respect_taboos=True)
    for ctx, score in results:
        print(f"   [{score:.3f}] {ctx.abstract}")
    print(f"   → 共 {len(results)} 条结果，'前女友'相关已过滤")

    print(f"\n🔍 检索 '投资'（启用禁忌过滤）")
    results = mem.recall("投资", limit=5, respect_taboos=True)
    for ctx, score in results:
        print(f"   [{score:.3f}] {ctx.abstract}")
    if not results:
        print("   → 0 条结果，所有投资亏损记忆都被过滤了")

    # ========================================================
    # 5. 禁忌检查 API
    # ========================================================
    print(f"\n{'='*50}")
    print("🔎 禁忌检查 API — 检测文本是否触发禁忌")
    print(f"{'='*50}")

    test_texts = [
        "老王的前女友最近怎么样了？",
        "今天和老王一起吃饭",
        "这个月投资亏损了不少",
        "Frankie 喜欢喝威士忌",
    ]

    for text in test_texts:
        triggered = mem.store.check_taboos(text)
        if triggered:
            patterns = [t["pattern"] for t in triggered]
            print(f"   ⚠️  '{text}' → 触发禁忌: {patterns}")
        else:
            print(f"   ✅ '{text}' → 安全")

    # ========================================================
    # 6. 数据源层禁忌拦截
    # ========================================================
    print(f"\n{'='*50}")
    print("🛡️  数据源层禁忌拦截")
    print(f"{'='*50}")

    # 添加一条包含禁忌词的数据源
    sid1 = mem.add_source("chat", "wechat", "老王说他前女友又给他打电话了")
    sid2 = mem.add_source("chat", "wechat", "明天一起去打羽毛球吧")

    processed = mem.process_sources()
    print(f"   添加了 2 条数据源，处理后生成 {processed} 条记忆")
    print("   → 包含'前女友'的数据源被拦截，只有安全内容被处理")

    # ========================================================
    # 7. 管理禁忌
    # ========================================================
    print(f"\n{'='*50}")
    print("⚙️  管理禁忌")
    print(f"{'='*50}")

    # 列出所有禁忌
    print("\n   当前禁忌列表:")
    taboos = mem.list_taboos()
    for t in taboos:
        status = "🟢 活跃" if t.get("active") else "🔴 已停用"
        print(f"   {status} [{t['id']}] '{t['pattern']}' — {t.get('description', '')}")

    # 移除一个禁忌
    print(f"\n   移除禁忌 '亏了' (ID: {t3})...")
    mem.remove_taboo(t3)

    print("\n   更新后的禁忌列表:")
    taboos = mem.list_taboos()
    for t in taboos:
        print(f"   🟢 [{t['id']}] '{t['pattern']}' — {t.get('description', '')}")

    # 验证移除效果
    print(f"\n🔍 再次检索 '投资':")
    results = mem.recall("投资", limit=5, respect_taboos=True)
    for ctx, score in results:
        print(f"   [{score:.3f}] {ctx.abstract}")
    print("   → '亏了'禁忌已移除，但'亏损'禁忌仍生效")

    # ========================================================
    # 8. 最佳实践
    # ========================================================
    print(f"\n{'='*50}")
    print("💡 禁忌系统最佳实践")
    print(f"{'='*50}")
    print("""
   1. 禁忌词要覆盖多种表述（如 '亏损' + '亏了' + '赔了'）
   2. 用 scope 区分全局禁忌和特定场景禁忌
   3. 定期 review 禁忌列表，移除不再需要的
   4. 禁忌只是过滤，原始数据仍在数据库中
   5. 可以用 respect_taboos=False 临时绕过（仅限调试）
""")

    mem.close()
    print(f"🎉 完成！")


if __name__ == "__main__":
    main()
