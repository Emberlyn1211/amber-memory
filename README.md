# Amber Memory

**AI Agent 的认知记忆系统 | A Cognitive Memory System for AI Agents**

Amber Memory 是为 AI Agent 定制的 Context Database，灵感来自字节跳动 [OpenViking](https://github.com/volcengine/OpenViking) 和 [Nowledge Mem](https://nowledge-labs.ai) 的记忆衰减模型。它让 AI 拥有类人的长期记忆能力——能记住重要的事、遗忘不重要的事、从对话中自动提取知识、并在需要时精准召回。

Amber Memory is a Context Database designed for AI Agents, inspired by ByteDance's [OpenViking](https://github.com/volcengine/OpenViking) and [Nowledge Mem](https://nowledge-labs.ai)'s memory decay model. It gives AI agents human-like long-term memory — remembering what matters, forgetting what doesn't, automatically extracting knowledge from conversations, and recalling it precisely when needed.

---

## 目录 / Table of Contents

- [核心特性 / Core Features](#核心特性--core-features)
- [架构概览 / Architecture Overview](#架构概览--architecture-overview)
- [快速开始 / Quick Start](#快速开始--quick-start)
- [安装 / Installation](#安装--installation)
- [使用示例 / Usage Examples](#使用示例--usage-examples)
- [8 维度记忆模型 / 8-Dimension Memory Model](#8-维度记忆模型--8-dimension-memory-model)
- [记忆衰减算法 / Memory Decay Algorithm](#记忆衰减算法--memory-decay-algorithm)
- [API 参考 / API Reference](#api-参考--api-reference)
- [数据源 / Data Sources](#数据源--data-sources)
- [迁移工具 / Migration Tool](#迁移工具--migration-tool)
- [测试 / Testing](#测试--testing)
- [设计原则 / Design Principles](#设计原则--design-principles)
- [致谢 / Acknowledgments](#致谢--acknowledgments)

---

## 核心特性 / Core Features

### L0/L1/L2 三级上下文 | Three-Level Context Hierarchy

```
L0 — 摘要 (Abstract)    ~10 tokens    永远加载，用于目录浏览
L1 — 概览 (Overview)    ~100 tokens   按需加载，用于相关性判断
L2 — 全文 (Content)     无限制        深度查询时加载
```

每条记忆都有三个层级，按需加载以节省 token。就像文件系统的目录结构——先看文件名（L0），再看摘要（L1），最后打开全文（L2）。

Every memory has three levels, loaded on demand to save tokens. Like a file system — browse filenames (L0), read summaries (L1), then open full content (L2).

### 记忆衰减 | Memory Decay

基于 ACT-R 认知科学模型 + FSRS 间隔重复算法。AI 也会遗忘——不重要的记忆自然淡去，重要的、常被访问的、有情感的记忆持续保鲜。

Based on ACT-R cognitive science model + FSRS spaced repetition algorithm. AI forgets too — unimportant memories naturally fade, while important, frequently accessed, and emotional memories stay fresh.

### 8 维度分类 | 8-Dimension Classification

人(person)、事(activity)、物(object)、偏好(preference)、禁忌(taboo)、目标(goal)、模式(pattern)、思考(thought)——覆盖 AI Agent 需要记住的一切。

Person, Activity, Object, Preference, Taboo, Goal, Pattern, Thought — covering everything an AI Agent needs to remember.

### 文件系统范式 | File System Paradigm

每条记忆都有唯一 URI，像文件路径一样组织：`/wechat/messages/张三/2026-02-24`。支持目录浏览、父子关系、层级检索。

Every memory has a unique URI, organized like file paths: `/wechat/messages/张三/2026-02-24`. Supports directory browsing, parent-child relationships, and hierarchical retrieval.

### 混合检索 | Hybrid Retrieval

文本搜索 + 向量语义搜索 + 衰减加权 + 意图分析 + 分数传播，多维度融合排序。

Text search + vector semantic search + decay weighting + intent analysis + score propagation, multi-dimensional fusion ranking.

### 禁忌系统 | Taboo System

用户可以设置不想被提及的话题。禁忌在检索和数据源处理两个层面生效，确保敏感内容不会被意外召回。

Users can set topics they don't want mentioned. Taboos are enforced at both retrieval and source processing layers, ensuring sensitive content is never accidentally recalled.

### 本地优先 | Local-First

SQLite + 向量索引，无外部服务依赖。数据完全在本地，隐私安全。

SQLite + vector index, no external service dependencies. Data stays completely local, privacy-safe.

### 多数据源 | Multi-Source

微信、Bear Notes、照片、链接/文章、日历——统一接入，统一处理。

WeChat, Bear Notes, photos, links/articles, calendar — unified ingestion, unified processing.

---

## 架构概览 / Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        AmberMemory Client                       │
│                     (统一入口 / Unified API)                     │
├─────────┬──────────┬──────────┬──────────┬──────────┬───────────┤
│ Session │ Retrieve │  Graph   │ Sources  │  Models  │  Storage  │
│  管线   │   检索   │  图谱    │  数据源  │  模型层  │   存储    │
├─────────┼──────────┼──────────┼──────────┼──────────┼───────────┤
│Extractor│ Retriever│ People   │ WeChat   │ ArkLLM   │ SQLite    │
│Dedup    │ Intent   │ Graph    │ Bear     │ Ark      │ Store     │
│Compress │ Analyzer │ Pattern  │ Photo    │ Embedder │           │
│         │          │ Detector │ Link     │          │           │
└─────────┴──────────┴──────────┴──────────┴──────────┴───────────┘
                              │
                    ┌─────────┴─────────┐
                    │   Prompt Manager   │
                    │  (YAML + Jinja2)   │
                    └───────────────────┘
```

### 数据流 / Data Flow

```
源数据 (Raw Data)                    记忆层 (Memory Layer)
┌──────────┐                        ┌────────────────────┐
│ 微信消息  │──┐                     │  L0: 一句话摘要     │
│ Bear笔记  │  │   LLM 提取/拆解     │  L1: 段落概览       │
│ 照片EXIF  │──┼──────────────────→  │  L2: 完整内容       │
│ 链接文章  │  │   8维度分类          │  + 衰减元数据       │
│ 日程事件  │──┘   重要性评估         │  + URI唯一标识      │
└──────────┘                        └────────────────────┘
                                              │
                                    ┌─────────┴─────────┐
                                    │   混合检索引擎      │
                                    │  Text + Vector     │
                                    │  + Decay + Intent  │
                                    └───────────────────┘
```

### Session 压缩管线 / Session Compression Pipeline

```
对话消息 ──→ MemoryExtractor ──→ MemoryDeduplicator ──→ SessionCompressor ──→ SQLiteStore
              (LLM提取)          (去重/合并决策)         (编排存储)           (持久化)
              
              提取候选记忆         查找相似记忆            创建/合并/跳过       写入数据库
              8维度分类            LLM判断关系             删除失效记忆         生成向量索引
              L0/L1/L2生成        skip/create/merge       重要性评估
```

---

## 快速开始 / Quick Start

```python
from amber_memory import AmberMemory

# 创建记忆系统实例
mem = AmberMemory("~/.amber/memory.db")

# 存储一条记忆
mem.remember(
    "Frankie 喜欢泰斯卡风暴威士忌",
    source="telegram",
    importance=0.7,
    tags=["frankie", "偏好"],
    emotion="joy",
)

# 检索记忆
results = mem.recall("Frankie 喜欢喝什么酒")
for ctx, score in results:
    print(f"[{score:.3f}] {ctx.abstract}")

# 查看统计
print(mem.stats())
```

---

## 安装 / Installation

### 依赖 / Dependencies

```
Python >= 3.7
PyYAML
Jinja2
httpx (async HTTP, for ARK API)
requests (sync HTTP, for embedder)
```

### 可选依赖 / Optional Dependencies

```
Pillow          — 照片 EXIF 提取
zstandard       — 微信消息解压
sqlcipher       — 微信数据库解密 (CLI tool)
```

### 安装步骤 / Installation Steps

```bash
# 克隆项目
git clone <repo-url> amber-memory
cd amber-memory

# 安装依赖
pip install pyyaml jinja2 httpx requests

# 可选：照片处理
pip install Pillow

# 可选：微信数据源
pip install zstandard
brew install sqlcipher  # macOS

# 设置环境变量（如需 LLM/Embedding 功能）
export ARK_API_KEY="your-volcengine-ark-api-key"
```

### 作为模块使用 / Use as Module

```bash
# 项目结构允许直接作为 Python 包导入
# 将 amber-memory 的父目录加入 PYTHONPATH
export PYTHONPATH="/path/to/amber-memory/parent:$PYTHONPATH"

# 或在代码中
import sys
sys.path.insert(0, "/path/to/amber-memory/parent")
from amber_memory import AmberMemory
```

---

## 使用示例 / Usage Examples

### 基础：存储和检索 / Basic: Store and Recall

```python
from amber_memory import AmberMemory

mem = AmberMemory("~/.amber/memory.db")

# 存储不同类型的记忆
mem.remember("外公陈伯年 2018 年去世", importance=0.95, emotion="sadness")
mem.remember("Watchlace 定位：日程骨架+记忆肌肉+人格皮肤", importance=0.9)
mem.remember("今天中午吃了沙县小吃", importance=0.1)

# 文本检索（带衰减加权）
results = mem.recall("Watchlace 是什么", limit=5)
for ctx, score in results:
    print(f"[{score:.3f}] {ctx.to_l0()}")  # L0 摘要
    print(f"          {ctx.to_l1()}")        # L1 概览

# 按标签检索
results = mem.recall_by_tag("偏好", limit=10)

# 按时间范围检索
import time
results = mem.recall_by_time(
    start=time.time() - 7 * 86400,  # 7天前
    end=time.time(),
    limit=20,
)

# 查看衰减排名
top = mem.top(limit=10)
for ctx, score in top:
    print(f"[{score:.3f}] {ctx.abstract}")

# 查看正在遗忘的记忆
fading = mem.fading(threshold=0.1)
for ctx in fading:
    print(f"即将遗忘: {ctx.abstract}")
```

### 进阶：Session 压缩 / Advanced: Session Compression

```python
import asyncio
from amber_memory import AmberMemory, ArkLLM

async def main():
    llm = ArkLLM(api_key="your-key")
    mem = AmberMemory("~/.amber/memory.db", llm_fn=llm.chat)

    # 模拟一段对话
    messages = [
        {"role": "user", "content": "今天和老王吃了火锅，他说下个月去日本出差"},
        {"role": "assistant", "content": "老王是你同事吗？"},
        {"role": "user", "content": "对，同一个组，负责海外业务。我决定下周开始跑步减肥"},
        {"role": "user", "content": "千万别在老王面前提他前女友"},
    ]

    # 自动提取并存储长期记忆
    memories = await mem.compress_session(
        messages=messages,
        user="Frankie",
        session_id="session-001",
    )
    
    for m in memories:
        print(f"[{m.category}] {m.abstract}")
    # 可能输出:
    # [person] 老王：同事，同组，负责海外业务
    # [activity] 和老王吃火锅，老王下月去日本出差
    # [goal] 下周开始每天跑步减肥
    # [taboo] 不要在老王面前提他前女友

asyncio.run(main())
```

### 进阶：智能检索 / Advanced: Smart Recall

```python
import asyncio
from amber_memory import AmberMemory, ArkLLM

async def main():
    llm = ArkLLM(api_key="your-key")
    mem = AmberMemory("~/.amber/memory.db", llm_fn=llm.chat, embed_fn=llm.embed)

    # 混合检索（文本 + 向量 + 衰减）
    results = await mem.hybrid_recall(
        "Frankie 的饮食偏好",
        limit=5,
        text_weight=0.4,
        vector_weight=0.4,
        decay_weight=0.2,
    )

    # 意图感知检索（分析对话上下文，生成多维查询计划）
    messages = [
        {"role": "user", "content": "帮我准备和老王的会议"},
    ]
    results = await mem.smart_recall(
        messages=messages,
        current_message="帮我准备和老王的会议",
        limit=10,
    )
    # IntentAnalyzer 会自动生成:
    # - person 查询: "老王的信息"
    # - activity 查询: "和老王最近的互动"
    # - taboo 查询: "和老王相关的禁忌"

asyncio.run(main())
```

### 数据源接入 / Data Source Ingestion

```python
from amber_memory import AmberMemory
import time

mem = AmberMemory("~/.amber/memory.db")

# 导入微信数据（需要解密后的数据库）
count = mem.ingest_wechat(limit=100)
print(f"导入了 {count} 条微信记忆")

# 导入 Bear Notes
count = mem.ingest_bear(tag="随感/Amber")
print(f"导入了 {count} 条 Bear 笔记")

# 手动添加数据源
sid = mem.add_source(
    source_type="text",
    origin="diary",
    raw_content="今天和 Frankie 聊了创业方向，决定做 Agent 信任基础设施",
    event_time=time.time(),
)

# 处理未处理的数据源
processed = mem.process_sources(limit=50)
print(f"处理了 {processed} 条源数据")

# 溯源：从记忆追回原始数据
source = mem.trace_source("/self/memories/2026-02-24/abc123")
if source:
    print(f"原始数据: {source['raw_content']}")
```

### 禁忌系统 / Taboo System

```python
from amber_memory import AmberMemory

mem = AmberMemory("~/.amber/memory.db")

# 添加禁忌
tid = mem.add_taboo("外公", description="不主动提起外公去世的事")

# 检索时自动过滤
results = mem.recall("外公", respect_taboos=True)   # 返回空
results = mem.recall("外公", respect_taboos=False)  # 正常返回

# 数据源处理时也会过滤
mem.add_source("text", "telegram", raw_content="聊到了外公的事...")
mem.process_sources()  # 这条会被禁忌拦截，不会生成记忆

# 管理禁忌
taboos = mem.list_taboos()
mem.remove_taboo(tid)
```

### 人物图谱 / People Graph

```python
from amber_memory import AmberMemory

mem = AmberMemory("~/.amber/memory.db")

# 添加人物
person = mem.people.add_person(
    name="老王",
    relationship="colleague",
    description="同组同事，负责海外业务",
    importance=0.7,
)

# 查找人物
p = mem.people.find_person("老王")

# 记录互动
mem.people.record_interaction(
    person_id=p.id,
    context="一起吃火锅",
    memory_uri="/self/memories/2026-02-24/hotpot",
    sentiment="joy",
)

# 查看互动历史
interactions = mem.people.get_interactions(p.id, limit=10)
```

### 模式识别 / Pattern Detection

```python
from amber_memory import AmberMemory

mem = AmberMemory("~/.amber/memory.db")

# 启发式模式检测
patterns = mem.patterns.detect_all(days=30)
for p in patterns:
    print(f"[{p.pattern_type}] {p.description} (confidence={p.confidence:.2f})")
```

---

## 8 维度记忆模型 / 8-Dimension Memory Model

| 维度 Dimension | context_type | 说明 Description | 数据来源 Sources |
|---|---|---|---|
| 人 Person | `person` | 联系人、关系网络、互动历史 | 微信、通讯录、对话提取 |
| 事 Activity | `activity` | 第一视角做了什么 | 照片语义、日程对账 |
| 物 Object | `object` | 物品、项目、地点、概念 | 照片识别、对话提取 |
| 偏好 Preference | `preference` | 喜欢/不喜欢/习惯 | 行为积累、主动设置 |
| 禁忌 Taboo | `taboo` | 不想被提及的事 | 用户设置、AI 检测 |
| 目标 Goal | `goal` | 短期/长期目标、进度 | 用户设置、日程分析 |
| 模式 Pattern | `pattern` | 作息规律、行为模式 | 照片+日程+位置自动识别 |
| 思考 Thought | `thought` | 日记、随感、反思 | memory/*.md、Bear Notes |

---

## 记忆衰减算法 / Memory Decay Algorithm

```
score = importance × recency × access_boost × link_boost × emotion_boost

recency        = exp(-λ × days_since_last_access)
                 λ = ln(2) / half_life_days  (default: 14 days)

access_boost   = 1 + ln(1 + access_count) × 0.3

link_boost     = 1 + min(link_count, 10) × 0.05

emotion_boost  = {neutral: 1.0, joy: 1.2, sadness: 1.3, anger: 1.1,
                  surprise: 1.15, fear: 1.25, love: 1.4, nostalgia: 1.35}

importance_floor = 0.05 × importance  (memories never fully disappear)
```

### 衰减曲线示例 / Decay Curve Example

```
importance=0.8, emotion=love, access_count=3

Day   0: 0.9408 ████████████████████████████████████████
Day   1: 0.8954 █████████████████████████████████████
Day   3: 0.8107 █████████████████████████████████
Day   7: 0.6656 ███████████████████████████
Day  14: 0.4706 ███████████████████
Day  30: 0.2218 █████████
Day  60: 0.0587 ██
Day  90: 0.0400 █  (floor)
```

---

## API 参考 / API Reference

详细 API 文档请参阅 [docs/api-reference.md](docs/api-reference.md)。

For detailed API documentation, see [docs/api-reference.md](docs/api-reference.md).

### 核心类 / Core Classes

| 类 Class | 说明 Description |
|---|---|
| `AmberMemory` | 主入口，统一 API |
| `Context` | 记忆单元，L0/L1/L2 + 衰减元数据 |
| `URI` | 文件系统范式的唯一标识 |
| `SQLiteStore` | SQLite 存储后端 |
| `Retriever` | 混合层级检索器 |
| `IntentAnalyzer` | 意图分析 + 查询规划 |
| `SessionCompressor` | Session 压缩管线编排 |
| `MemoryExtractor` | LLM 记忆提取 |
| `MemoryDeduplicator` | LLM 去重决策 |
| `ArkLLM` | 火山方舟 LLM 客户端 |
| `ArkEmbedder` | 火山方舟 Embedding 客户端 |
| `PeopleGraph` | 人物关系图谱 |
| `PatternDetector` | 行为模式识别 |

---

## 数据源 / Data Sources

| 数据源 Source | 模块 Module | 状态 Status | 说明 Description |
|---|---|---|---|
| 微信 WeChat | `sources/wechat.py` | ✅ Phase 1 | 解密 SQLite → 联系人 + 消息 |
| Bear Notes | `sources/bear.py` | ✅ Phase 1 | 直接读 Bear SQLite 数据库 |
| 照片 Photo | `sources/photo.py` | 🔧 Phase 2 | EXIF 提取 + VLM 场景描述 |
| 链接 Link | `sources/link.py` | 🔧 Phase 2 | URL 抓取 + 文本提取 |

---

## 迁移工具 / Migration Tool

从现有的 `MEMORY.md` 和 `memory/*.md` 日记文件迁移到 Amber Memory：

```bash
# 预览（不写入）
python3 -m amber_memory.migrate --dry-run

# 执行迁移
python3 -m amber_memory.migrate --workspace ~/.openclaw/workspace --db ~/.amber/memory.db
```

迁移是非破坏性的——原始文件不会被修改或删除。

---

## 测试 / Testing

```bash
# 运行核心测试（29 个测试）
python3 -m pytest tests/test_core.py -v

# 运行 E2E 测试（需要 ARK_API_KEY）
ARK_API_KEY=your-key python3 tests/test_e2e.py

# 运行 Demo
python3 -m amber_memory.demo
```

---

## 设计原则 / Design Principles

1. **源层永远不动** — 原始数据是 truth，只读不改
2. **记忆层可重建** — 源层完好就能重新导入
3. **透明可控** — 用户能看到记了什么、为什么记、一键删除
4. **禁忌优先** — 敏感内容不自动处理，需确认
5. **衰减是特色** — AI 也会遗忘，不重要的自然淡去
6. **溯源链接** — 每条记忆都能追回原始数据
7. **图片必带时间位置** — 尽量获取，取不到留空

---

## 致谢 / Acknowledgments

- [OpenViking](https://github.com/volcengine/OpenViking) — 字节 Viking 团队的 Context Database
- [Nowledge Mem](https://nowledge-labs.ai) — 记忆衰减模型（ACT-R + FSRS）
- [火山方舟 ARK](https://www.volcengine.com/product/ark) — 豆包大模型 API

---

## License

Private project. All rights reserved.
