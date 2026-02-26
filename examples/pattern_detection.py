#!/usr/bin/env python3
"""模式识别示例 — 从记忆历史中发现行为模式。

展示 PatternDetector 的时间模式、分类模式检测，以及 LLM 辅助的深度分析。

运行: python examples/pattern_detection.py
"""

import asyncio
import json
import sys
import os
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from amber_memory import AmberMemory, PatternDetector


# ============================================================
# Mock LLM — 模拟 LLM 的模式分析
# ============================================================
async def mock_llm(prompt: str) -> str:
    """模拟 LLM 返回模式分析结果。"""
    return json.dumps({
        "patterns": [
            {
                "type": "habit",
                "description": "工作日晚上 10-11 点是写日记和反思的固定时间",
                "confidence": 0.8,
                "frequency": "daily"
            },
            {
                "type": "social",
                "description": "每周五下午和同事有社交活动（聚餐或喝酒）",
                "confidence": 0.7,
                "frequency": "weekly"
            },
            {
                "type": "emotion",
                "description": "周一的记忆情感偏负面（工作压力），周末偏正面",
                "confidence": 0.6,
                "frequency": "weekly"
            },
        ]
    }, ensure_ascii=False)


def populate_mock_memories(mem: AmberMemory):
    """填充 30 天的模拟记忆数据，制造可识别的模式。"""
    now = time.time()
    count = 0

    # 模式 1: 工作日晚上写日记（周一到周五，22:00 左右）
    for day_offset in range(30):
        t = now - day_offset * 86400
        dt = datetime.fromtimestamp(t)
        if dt.weekday() < 5:  # 工作日
            # 晚上 22 点的日记
            evening = t - (dt.hour - 22) * 3600 if dt.hour >= 22 else t - dt.hour * 3600 + 22 * 3600
            mem.remember(
                f"今日反思：{['项目进展顺利', '遇到了技术难题', '和团队讨论了方案', '完成了代码审查', '准备明天的会议'][day_offset % 5]}",
                source="diary", importance=0.4, emotion="neutral",
                tags=["日记", "反思"], event_time=evening,
                category="thought",
            )
            count += 1

    # 模式 2: 周五下午社交
    for week in range(4):
        friday = now - (7 * week + (datetime.fromtimestamp(now).weekday() - 4) % 7) * 86400
        friday_afternoon = friday - (datetime.fromtimestamp(friday).hour - 17) * 3600
        activities = ["和老王去喝精酿", "团队聚餐吃烤肉", "和小李去酒吧", "部门团建打桌游"]
        mem.remember(
            activities[week % len(activities)],
            source="diary", importance=0.5, emotion="joy",
            tags=["社交", "周五"], event_time=friday_afternoon,
            category="activity",
        )
        count += 1

    # 模式 3: 周一工作压力
    for week in range(4):
        monday = now - (7 * week + (datetime.fromtimestamp(now).weekday() - 0) % 7) * 86400
        monday_morning = monday - (datetime.fromtimestamp(monday).hour - 9) * 3600
        stresses = ["周一例会又拖了两小时", "需求又变了，重新排期", "线上出了 bug 紧急修复", "老板临时加了个需求"]
        mem.remember(
            stresses[week % len(stresses)],
            source="work", importance=0.6, emotion="anger",
            tags=["工作", "压力", "周一"], event_time=monday_morning,
            category="activity",
        )
        count += 1

    # 模式 4: 周末运动
    for week in range(4):
        saturday = now - (7 * week + (datetime.fromtimestamp(now).weekday() - 5) % 7) * 86400
        saturday_morning = saturday - (datetime.fromtimestamp(saturday).hour - 8) * 3600
        exercises = ["晨跑 5 公里", "去健身房练了胸肌", "骑车去了滴水湖", "游泳 1000 米"]
        mem.remember(
            exercises[week % len(exercises)],
            source="self", importance=0.4, emotion="joy",
            tags=["运动", "周末"], event_time=saturday_morning,
            category="activity",
        )
        count += 1

    # 一些零散记忆
    scattered = [
        ("买了新的机械键盘，Cherry 红轴", "self", 0.3, "joy", ["购物"], 5),
        ("读完了《思考快与慢》，很有启发", "bear", 0.6, "neutral", ["读书"], 8),
        ("Frankie 喜欢深夜听 lo-fi 音乐写代码", "self", 0.5, "neutral", ["偏好"], 12),
        ("和妈妈视频通话，她身体还好", "phone", 0.7, "love", ["家人"], 3),
        ("发现了一家很好的咖啡馆，手冲不错", "self", 0.3, "joy", ["探店"], 6),
    ]
    for content, source, imp, emo, tags, days in scattered:
        mem.remember(content, source=source, importance=imp, emotion=emo,
                     tags=tags, event_time=now - days * 86400)
        count += 1

    return count


async def main():
    print("=" * 60)
    print("Amber Memory — 模式识别演示")
    print("=" * 60)

    # --------------------------------------------------------
    # 1. 准备数据
    # --------------------------------------------------------
    DB_PATH = "/tmp/amber_patterns.db"
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    mem = AmberMemory(DB_PATH, llm_fn=mock_llm)
    detector = mem.patterns  # PatternDetector 实例

    print(f"\n📝 填充模拟数据...")
    count = populate_mock_memories(mem)
    print(f"   已存储 {count} 条记忆（模拟 30 天）")

    # --------------------------------------------------------
    # 2. 时间模式检测
    # --------------------------------------------------------
    print(f"\n{'='*50}")
    print("⏰ 时间模式检测")
    print(f"{'='*50}")

    time_patterns = detector.detect_time_patterns(days=30)
    if time_patterns:
        for p in time_patterns:
            print(f"\n   📌 {p.description}")
            print(f"      类型: {p.pattern_type} | 频率: {p.frequency}")
            print(f"      置信度: {p.confidence:.2f}")
    else:
        print("   未检测到明显的时间模式")

    # --------------------------------------------------------
    # 3. 分类模式检测
    # --------------------------------------------------------
    print(f"\n{'='*50}")
    print("📂 分类模式检测")
    print(f"{'='*50}")

    cat_patterns = detector.detect_category_patterns(days=30)
    if cat_patterns:
        for p in cat_patterns:
            print(f"\n   📌 {p.description}")
            print(f"      置信度: {p.confidence:.2f}")
            if p.meta:
                print(f"      详情: {p.meta}")
    else:
        print("   未检测到明显的分类模式")

    # --------------------------------------------------------
    # 4. 一键检测所有模式
    # --------------------------------------------------------
    print(f"\n{'='*50}")
    print("🔍 一键检测所有启发式模式")
    print(f"{'='*50}")

    all_patterns = detector.detect_all(days=30)
    print(f"   共检测到 {len(all_patterns)} 个模式（已保存到数据库）")

    # --------------------------------------------------------
    # 5. LLM 辅助深度分析
    # --------------------------------------------------------
    print(f"\n{'='*50}")
    print("🤖 LLM 辅助深度模式分析")
    print(f"{'='*50}")

    llm_patterns = await detector.detect_with_llm(mock_llm, days=14, limit=30)
    for p in llm_patterns:
        print(f"\n   📌 {p.description}")
        print(f"      类型: {p.pattern_type} | 频率: {p.frequency}")
        print(f"      置信度: {p.confidence:.2f}")

    # --------------------------------------------------------
    # 6. 查看已保存的模式
    # --------------------------------------------------------
    print(f"\n{'='*50}")
    print("💾 已保存的模式")
    print(f"{'='*50}")

    saved = detector.list_patterns(limit=10)
    for p in saved:
        print(f"   [{p.confidence:.2f}] [{p.pattern_type:8s}] {p.description}")

    # --------------------------------------------------------
    # 7. 统计
    # --------------------------------------------------------
    print(f"\n📈 统计:")
    print(f"   记忆总数: {mem.stats()['total']}")
    print(f"   模式总数: {detector.stats()['patterns']}")

    mem.close()
    print(f"\n🎉 完成！")


if __name__ == "__main__":
    asyncio.run(main())
