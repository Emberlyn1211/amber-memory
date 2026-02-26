#!/usr/bin/env python3
"""导出 Markdown + 同步示例 — 将记忆导出为可读文档。

展示如何将 Amber Memory 中的记忆导出为 Markdown 文件，
支持按分类、按时间、按人物等维度导出。

运行: python examples/export_and_sync.py
"""

import sys
import os
import time
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from amber_memory import AmberMemory
from amber_memory.core.context import DecayParams


# ============================================================
# 导出工具函数
# ============================================================

def export_all_memories_md(mem: AmberMemory, output_path: str) -> str:
    """导出所有记忆为一个 Markdown 文件。"""
    lines = ["# Amber Memory 导出\n"]
    lines.append(f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    stats = mem.stats()
    lines.append(f"总记忆数: {stats['total']}\n")

    # 按衰减分数排序
    top = mem.top(limit=100)
    lines.append("## 记忆列表（按重要性排序）\n")

    for i, (ctx, score) in enumerate(top, 1):
        event_dt = datetime.fromtimestamp(
            ctx.event_time or ctx.created_at
        ).strftime("%Y-%m-%d")
        lines.append(f"### {i}. {ctx.abstract}\n")
        lines.append(f"- **分数**: {score:.3f}")
        lines.append(f"- **类型**: {ctx.context_type}")
        lines.append(f"- **情感**: {ctx.emotion}")
        lines.append(f"- **日期**: {event_dt}")
        lines.append(f"- **URI**: `{ctx.uri}`")
        if ctx.tags:
            lines.append(f"- **标签**: {', '.join(ctx.tags)}")
        lines.append(f"\n{ctx.content}\n")
        lines.append("---\n")

    content = "\n".join(lines)
    Path(output_path).write_text(content, encoding="utf-8")
    return content


def export_by_category_md(mem: AmberMemory, output_dir: str) -> dict:
    """按分类导出为多个 Markdown 文件。"""
    os.makedirs(output_dir, exist_ok=True)
    categories = ["person", "activity", "preference", "taboo",
                   "goal", "pattern", "thought", "object"]
    exported = {}

    for cat in categories:
        results = mem.store.search_by_category(cat, limit=100)
        if not results:
            continue

        lines = [f"# {cat.title()} 记忆\n"]
        lines.append(f"共 {len(results)} 条\n")

        for ctx in results:
            event_dt = datetime.fromtimestamp(
                ctx.event_time or ctx.created_at
            ).strftime("%Y-%m-%d")
            lines.append(f"## {ctx.abstract}\n")
            lines.append(f"*{event_dt} | 重要性: {ctx.importance:.2f} | {ctx.emotion}*\n")
            lines.append(f"{ctx.content}\n")
            lines.append("---\n")

        path = os.path.join(output_dir, f"{cat}.md")
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        exported[cat] = len(results)

    return exported


def export_people_md(mem: AmberMemory, output_path: str) -> str:
    """导出人物图谱为 Markdown。"""
    graph = mem.people
    people = graph.list_people(limit=50)

    lines = ["# 人物图谱\n"]
    lines.append(f"共 {len(people)} 人\n")

    for p in people:
        lines.append(f"## {p.name}\n")
        if p.aliases:
            lines.append(f"- **别名**: {', '.join(p.aliases)}")
        lines.append(f"- **关系**: {p.relationship or '未知'}")
        lines.append(f"- **描述**: {p.description or '无'}")
        lines.append(f"- **重要性**: {p.importance:.2f}")
        lines.append(f"- **互动次数**: {p.interaction_count}")

        # 关系网络
        rels = graph.get_relationships(p.id)
        if rels:
            lines.append("\n**关系网络:**\n")
            for rel in rels:
                other_id = rel.person_b if rel.person_a == p.id else rel.person_a
                other = graph.get_person(other_id)
                other_name = other.name if other else other_id
                lines.append(f"- {rel.relation} → {other_name} (强度: {rel.strength})")

        # 最近互动
        interactions = graph.get_interactions(p.id, limit=3)
        if interactions:
            lines.append("\n**最近互动:**\n")
            for inter in interactions:
                dt = datetime.fromtimestamp(inter["timestamp"]).strftime("%m-%d")
                lines.append(f"- [{dt}] {inter['context']}")

        lines.append("\n---\n")

    content = "\n".join(lines)
    Path(output_path).write_text(content, encoding="utf-8")
    return content


def export_daily_digest_md(mem: AmberMemory, output_path: str, days: int = 7) -> str:
    """导出最近 N 天的每日摘要。"""
    now = time.time()
    lines = [f"# 最近 {days} 天记忆摘要\n"]

    for day_offset in range(days):
        day_start = now - (day_offset + 1) * 86400
        day_end = now - day_offset * 86400
        date_str = datetime.fromtimestamp(day_end).strftime("%Y-%m-%d (%A)")

        memories = mem.recall_by_time(day_start, day_end, limit=20)
        if not memories:
            continue

        lines.append(f"## {date_str}\n")
        for ctx in memories:
            emoji = {"joy": "😊", "sadness": "😢", "anger": "😤",
                     "love": "❤️", "nostalgia": "🥹", "neutral": "📝"
                     }.get(ctx.emotion, "📝")
            lines.append(f"- {emoji} [{ctx.importance:.1f}] {ctx.abstract}")

        lines.append("")

    content = "\n".join(lines)
    Path(output_path).write_text(content, encoding="utf-8")
    return content


def sync_to_bear_format(mem: AmberMemory) -> str:
    """生成适合同步到 Bear Notes 的 Markdown 内容。"""
    lines = ["# Amber Memory 同步\n"]
    lines.append(f"#openclaw #amber-memory\n")
    lines.append(f"*最后同步: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")

    # Top 10 记忆
    lines.append("## 🔝 Top 10 记忆\n")
    top = mem.top(limit=10)
    for ctx, score in top:
        lines.append(f"- [{score:.2f}] {ctx.abstract}")

    # 即将遗忘
    lines.append("\n## 💨 即将遗忘\n")
    fading = mem.fading(threshold=0.1)
    if fading:
        for ctx in fading[:5]:
            lines.append(f"- {ctx.abstract}")
    else:
        lines.append("- （暂无）")

    # 统计
    lines.append("\n## 📊 统计\n")
    stats = mem.stats()
    lines.append(f"- 总记忆: {stats['total']}")
    for src, cnt in stats.get("by_source", {}).items():
        lines.append(f"- {src}: {cnt}")

    return "\n".join(lines)


# ============================================================
# 主程序
# ============================================================

def main():
    print("=" * 60)
    print("Amber Memory — 导出 & 同步演示")
    print("=" * 60)

    DB_PATH = "/tmp/amber_export.db"
    EXPORT_DIR = "/tmp/amber_export"
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    os.makedirs(EXPORT_DIR, exist_ok=True)

    mem = AmberMemory(DB_PATH)

    # 填充数据
    print("\n📝 填充演示数据...")
    now = time.time()

    test_data = [
        ("Frankie 喜欢泰斯卡风暴威士忌", "telegram", 0.8, "joy", ["偏好"], 0),
        ("外公陈伯年 2018 年去世", "diary", 0.95, "sadness", ["家人"], 30),
        ("Watchlace 完成了记忆模块设计", "notes", 0.85, "neutral", ["项目"], 2),
        ("和老王吃火锅聊出差", "diary", 0.4, "joy", ["社交"], 1),
        ("下周开始每天跑步", "self", 0.6, "joy", ["目标"], 0),
        ("读完了思考快与慢", "bear", 0.6, "neutral", ["读书"], 5),
        ("今天中午吃了沙县小吃", "self", 0.1, "neutral", ["日常"], 0),
        ("和投资人讨论了融资方案", "work", 0.8, "neutral", ["工作"], 3),
    ]

    for content, source, imp, emo, tags, days in test_data:
        mem.remember(content, source=source, importance=imp,
                     emotion=emo, tags=tags, event_time=now - days * 86400)

    # 添加人物
    graph = mem.people
    wang = graph.add_person("老王", "colleague", "同组同事", importance=0.7)
    mom = graph.add_person("妈妈", "family", "退休教师", importance=0.95)
    graph.add_relationship(wang.id, mom.id, "不认识")
    graph.record_interaction(wang.id, "一起吃火锅")

    print(f"   已存储 {len(test_data)} 条记忆 + {graph.stats()['people']} 个人物")

    # ========================================================
    # 导出 1: 全量导出
    # ========================================================
    print(f"\n{'='*50}")
    print("📄 导出 1: 全量 Markdown")
    print(f"{'='*50}")

    path = os.path.join(EXPORT_DIR, "all_memories.md")
    export_all_memories_md(mem, path)
    size = os.path.getsize(path)
    print(f"   ✅ {path} ({size} bytes)")

    # ========================================================
    # 导出 2: 按分类导出
    # ========================================================
    print(f"\n{'='*50}")
    print("📂 导出 2: 按分类导出")
    print(f"{'='*50}")

    cat_dir = os.path.join(EXPORT_DIR, "by_category")
    exported = export_by_category_md(mem, cat_dir)
    for cat, count in exported.items():
        print(f"   ✅ {cat}.md ({count} 条)")

    # ========================================================
    # 导出 3: 人物图谱
    # ========================================================
    print(f"\n{'='*50}")
    print("👥 导出 3: 人物图谱")
    print(f"{'='*50}")

    path = os.path.join(EXPORT_DIR, "people.md")
    export_people_md(mem, path)
    print(f"   ✅ {path}")

    # ========================================================
    # 导出 4: 每日摘要
    # ========================================================
    print(f"\n{'='*50}")
    print("📅 导出 4: 每日摘要")
    print(f"{'='*50}")

    path = os.path.join(EXPORT_DIR, "daily_digest.md")
    export_daily_digest_md(mem, path, days=7)
    print(f"   ✅ {path}")

    # ========================================================
    # 导出 5: Bear Notes 同步格式
    # ========================================================
    print(f"\n{'='*50}")
    print("🐻 导出 5: Bear Notes 同步格式")
    print(f"{'='*50}")

    bear_content = sync_to_bear_format(mem)
    bear_path = os.path.join(EXPORT_DIR, "bear_sync.md")
    Path(bear_path).write_text(bear_content, encoding="utf-8")
    print(f"   ✅ {bear_path}")
    print(f"\n   预览:\n")
    for line in bear_content.split("\n")[:15]:
        print(f"   {line}")
    print("   ...")

    # ========================================================
    # 总结
    # ========================================================
    print(f"\n{'='*50}")
    print("📁 导出文件列表")
    print(f"{'='*50}")

    for root, dirs, files in os.walk(EXPORT_DIR):
        level = root.replace(EXPORT_DIR, "").count(os.sep)
        indent = "   " * (level + 1)
        print(f"{indent}{os.path.basename(root)}/")
        sub_indent = "   " * (level + 2)
        for f in files:
            fpath = os.path.join(root, f)
            size = os.path.getsize(fpath)
            print(f"{sub_indent}{f} ({size} bytes)")

    mem.close()
    print(f"\n🎉 完成！所有文件导出到: {EXPORT_DIR}")


if __name__ == "__main__":
    main()
