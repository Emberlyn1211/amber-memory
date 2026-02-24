#!/usr/bin/env python3
"""Amber Memory 快速上手 — 5 分钟跑通核心功能。

无需 API Key，无需外部服务，纯本地 SQLite 即可运行。
演示：存储记忆 → 检索 → 衰减排名 → 统计。

运行: python examples/quickstart.py
"""

import sys
import os
import time

# 让 import 能找到项目根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from amber_memory import AmberMemory

# ============================================================
# 1. 创建记忆系统（使用临时数据库）
# ============================================================
DB_PATH = "/tmp/amber_quickstart.db"
mem = AmberMemory(DB_PATH)
print(f"✅ 记忆系统已创建: {mem}")

# ============================================================
# 2. 存储不同类型的记忆
# ============================================================
print("\n📝 存储记忆...")

# 高重要性 + 情感标记
mem.remember(
    "外公陈伯年 2018 年去世，享年 87 岁",
    source="diary",
    importance=0.95,
    emotion="sadness",
    tags=["家人", "外公"],
)

# 中等重要性的偏好
mem.remember(
    "Frankie 喜欢泰斯卡风暴威士忌，不加冰，纯饮",
    source="telegram",
    importance=0.7,
    emotion="joy",
    tags=["偏好", "威士忌"],
)

# 低重要性的日常
mem.remember(
    "今天中午在公司楼下吃了沙县小吃，点了拌面和蒸饺",
    source="self",
    importance=0.15,
    tags=["日常", "饮食"],
)

# 项目相关
mem.remember(
    "Watchlace 定位：日程骨架 + 记忆肌肉 + 人格皮肤，三层架构",
    source="notes",
    importance=0.85,
    tags=["项目", "Watchlace"],
)

# 目标
mem.remember(
    "下周开始每天跑步 5 公里，目标三个月减重 10 斤",
    source="telegram",
    importance=0.6,
    emotion="joy",
    tags=["目标", "健身"],
)

print(f"   已存储 5 条记忆")

# ============================================================
# 3. 文本检索
# ============================================================
print("\n🔍 文本检索: '威士忌'")
results = mem.recall("威士忌", limit=3)
for ctx, score in results:
    print(f"   [{score:.3f}] {ctx.to_l0()}")
    print(f"            {ctx.to_l1()}")

# ============================================================
# 4. 按标签检索
# ============================================================
print("\n🏷️  按标签检索: '偏好'")
results = mem.recall_by_tag("偏好", limit=5)
for ctx in results:
    print(f"   [{ctx.importance:.2f}] {ctx.abstract}")

# ============================================================
# 5. 衰减排名 — 最重要的记忆排在前面
# ============================================================
print("\n📊 衰减排名 Top 5:")
top = mem.top(limit=5)
for ctx, score in top:
    print(f"   [{score:.3f}] [{ctx.emotion:8s}] {ctx.abstract}")

# ============================================================
# 6. 查看即将遗忘的记忆
# ============================================================
print("\n💨 即将遗忘的记忆 (score < 0.1):")
fading = mem.fading(threshold=0.1)
if fading:
    for ctx in fading:
        print(f"   {ctx.abstract}")
else:
    print("   （暂无，所有记忆都还新鲜）")

# ============================================================
# 7. 获取单条记忆的详细信息
# ============================================================
print("\n📖 L0/L1/L2 三级内容展示:")
results = mem.recall("Watchlace", limit=1)
if results:
    ctx, score = results[0]
    print(f"   L0 (摘要): {ctx.to_l0()}")
    print(f"   L1 (概览): {ctx.to_l1()}")
    print(f"   L2 (全文): {ctx.to_l2()}")

# ============================================================
# 8. 统计信息
# ============================================================
print("\n📈 系统统计:")
stats = mem.stats()
for k, v in stats.items():
    print(f"   {k}: {v}")

# ============================================================
# 9. 清理
# ============================================================
mem.close()
print(f"\n🎉 完成！数据库: {DB_PATH}")
print("   可以用 sqlite3 直接查看: sqlite3 /tmp/amber_quickstart.db '.tables'")
