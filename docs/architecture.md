# Amber Memory — 架构文档 / Architecture Document

*最后更新 / Last Updated: 2026-02-24*

---

## 目录 / Table of Contents

- [系统总览 / System Overview](#系统总览--system-overview)
- [设计哲学 / Design Philosophy](#设计哲学--design-philosophy)
- [模块详解 / Module Deep Dive](#模块详解--module-deep-dive)
  - [core — 核心模型](#core--核心模型)
  - [storage — 存储层](#storage--存储层)
  - [session — Session 管线](#session--session-管线)
  - [retrieve — 检索引擎](#retrieve--检索引擎)
  - [models — 模型层](#models--模型层)
  - [sources — 数据源适配器](#sources--数据源适配器)
  - [graph — 图谱与模式](#graph--图谱与模式)
  - [prompts — 提示词管理](#prompts--提示词管理)
  - [client — 统一入口](#client--统一入口)
- [数据流 / Data Flow](#数据流--data-flow)
- [衰减模型 / Decay Model](#衰减模型--decay-model)
- [去重策略 / Deduplication Strategy](#去重策略--deduplication-strategy)
- [检索架构 / Retrieval Architecture](#检索架构--retrieval-architecture)
- [安全与隐私 / Security & Privacy](#安全与隐私--security--privacy)
- [扩展性 / Extensibility](#扩展性--extensibility)
- [与 OpenViking 的差异 / Differences from OpenViking](#与-openviking-的差异--differences-from-openviking)

---

## 系统总览 / System Overview

Amber Memory 是一个为 AI Agent（具体来说是 Amber，一个运行在 OpenClaw 上的个人 AI 助手）设计的认知记忆系统。它解决的核心问题是：**AI Agent 如何在多个 session 之间保持连贯的长期记忆？**

Amber Memory is a cognitive memory system designed for AI Agents (specifically Amber, a personal AI assistant running on OpenClaw). The core problem it solves: **How can an AI Agent maintain coherent long-term memory across multiple sessions?**

### 核心架构图 / Core Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          AmberMemory Client                         │
│                        (client.py — 统一 API)                       │
├──────────┬───────────┬───────────┬───────────┬───────────┬──────────┤
│          │           │           │           │           │          │
│  Session │  Retrieve │   Graph   │  Sources  │  Models   │ Storage  │
│  Pipeline│  Engine   │  Module   │  Adapters │  Layer    │  Layer   │
│          │           │           │           │           │          │
│ ┌──────┐ │ ┌───────┐ │ ┌───────┐ │ ┌───────┐ │ ┌───────┐ │ ┌──────┐│
│ │Extract│ │ │Retriev│ │ │People │ │ │WeChat │ │ │ArkLLM│ │ │SQLite││
│ │  or   │ │ │  er   │ │ │ Graph │ │ │Source │ │ │      │ │ │Store ││
│ ├──────┤ │ ├───────┤ │ ├───────┤ │ ├───────┤ │ ├───────┤ │ │      ││
│ │Dedup │ │ │Intent │ │ │Pattern│ │ │Bear   │ │ │Ark   │ │ │ 5 表 ││
│ │licatr│ │ │Analyz │ │ │Detect │ │ │Source │ │ │Embed │ │ │      ││
│ ├──────┤ │ │  er   │ │ │  or   │ │ ├───────┤ │ │  der │ │ │      ││
│ │Comprs│ │ │       │ │ │       │ │ │Photo  │ │ │      │ │ │      ││
│ │  sor │ │ │       │ │ │       │ │ │Link   │ │ │      │ │ │      ││
│ └──────┘ │ └───────┘ │ └───────┘ │ └───────┘ │ └───────┘ │ └──────┘│
├──────────┴───────────┴───────────┴───────────┴───────────┴──────────┤
│                        Prompt Manager (YAML + Jinja2)               │
└─────────────────────────────────────────────────────────────────────┘
```

### 技术栈 / Technology Stack

| 层级 Layer | 技术 Technology | 选型理由 Rationale |
|---|---|---|
| 语言 Language | Python 3.7+ | AI 生态最丰富，与 OpenClaw 集成方便 |
| 存储 Storage | SQLite (WAL mode) | 本地优先，零配置，单文件数据库 |
| 向量索引 Vector | 内存暴力搜索 Brute-force | <10k 记忆时足够快，避免引入额外依赖 |
| LLM | 火山方舟 ARK API (豆包) | 国内可用，性价比高，支持 embedding |
| 模板 Templates | YAML + Jinja2 | 结构化配置 + 灵活渲染 |
| HTTP | httpx (async) + requests (sync) | async 用于 LLM 调用，sync 用于 embedding |

---

## 设计哲学 / Design Philosophy

### 1. 认知科学驱动 / Cognitive Science Driven

Amber Memory 不是简单的 key-value 存储或向量数据库。它模拟人类记忆的工作方式：

- **分层加载**：人回忆时先想到模糊印象（L0），再想起细节（L1），最后回忆全貌（L2）
- **自然遗忘**：不重要的事自然淡去，重要的事历久弥新
- **情感加权**：情感强烈的记忆更持久（love × 1.4, sadness × 1.3）
- **频率强化**：经常被回忆的记忆更不容易遗忘（access_boost）
- **关联网络**：与其他记忆关联越多，越不容易遗忘（link_boost）

### 2. 文件系统范式 / File System Paradigm

受 OpenViking 启发，每条记忆都有唯一 URI，像文件路径一样组织：

```
/wechat/messages/张三/2026-02-24     — 微信消息
/telegram/conversations/frankie/...   — Telegram 对话
/self/thoughts/2026-02-24/about-ai    — 个人思考
/bear/notes/随感_abc12345             — Bear 笔记
amber://memories/person/a1b2c3d4      — 提取的人物记忆
```

这个设计带来几个好处：
- **层级浏览**：可以像浏览文件夹一样浏览记忆
- **父子关系**：子记忆继承父目录的上下文
- **去重友好**：URI 天然唯一，避免重复存储
- **溯源简单**：从 URI 就能看出记忆来源

### 3. 源层与记忆层分离 / Source-Memory Separation

```
源层 (Source Layer)          记忆层 (Memory Layer)
┌──────────────────┐        ┌──────────────────┐
│ 原始数据，只读    │  LLM   │ 结构化记忆        │
│ 微信消息原文      │ ────→  │ L0/L1/L2 三级     │
│ Bear 笔记原文     │ 提取   │ 8 维度分类        │
│ 照片 EXIF        │        │ 衰减元数据        │
│ 链接原始 HTML     │        │ 可重建            │
└──────────────────┘        └──────────────────┘
```

**源层永远不动**——这是最重要的设计原则。原始数据是 ground truth，记忆层是从源层派生的。如果记忆层出了问题，可以从源层重新生成。

### 4. 8 维度模型 / 8-Dimension Model

为什么是 8 个维度而不是自由标签？因为：

- **LLM 分类更准确**：有限的选项比开放式标签更容易让 LLM 正确分类
- **检索更高效**：可以按维度做分区检索，减少搜索空间
- **去重更精准**：同维度内的记忆才需要去重，跨维度不会误合并
- **覆盖完整**：8 个维度覆盖了 AI Agent 需要记住的所有类型

### 5. 本地优先 / Local-First

所有数据存储在本地 SQLite 文件中，不依赖任何外部数据库服务。LLM 和 Embedding API 是可选的——没有它们，系统仍然可以工作（只是少了 LLM 提取和向量搜索能力）。

---

## 模块详解 / Module Deep Dive

### core — 核心模型

**文件 / Files:** `core/context.py`, `core/uri.py`

#### Context (context.py)

Context 是整个系统的核心数据结构——一个记忆单元。

**设计决策：**

1. **Dataclass 而非 ORM**：使用 Python dataclass 而非 SQLAlchemy 等 ORM。原因是记忆系统的数据模型相对简单，dataclass 更轻量、更灵活，且不引入额外依赖。

2. **ContextType 使用 str Enum**：`ContextType(str, Enum)` 继承 str，这样序列化到 JSON/SQLite 时自动变成字符串，不需要额外转换。8 个维度 + 1 个通用 `MEMORY` 类型。

3. **EmotionTag 固定集合**：8 种情感标签（neutral, joy, sadness, anger, surprise, fear, love, nostalgia）。不用自由文本是因为衰减算法需要精确的 emotion_multiplier 映射。

4. **DecayParams 可配置**：衰减参数抽取为独立 dataclass，支持不同场景使用不同衰减策略。默认半衰期 14 天（比 Nowledge 的 30 天更激进，因为 AI Agent 的记忆更新更频繁）。

5. **compute_score() 纯函数**：衰减分数计算是纯函数，接受可选的 `now` 参数，方便测试和模拟。

6. **to_dict() / from_dict() 序列化**：手动实现而非用 `dataclasses.asdict()`，因为需要控制哪些字段序列化（比如 embedding 不序列化到 dict）。

#### URI (uri.py)

URI 是记忆的唯一标识符，采用文件系统路径范式。

**设计决策：**

1. **三段式结构**：`/{source}/{category}/{path}`。source 标识数据来源（wechat, telegram, self），category 标识数据类型（messages, contacts, thoughts），path 是具体路径。

2. **hash_id 用 MD5 前 16 位**：不需要密码学安全性，只需要唯一性。MD5 足够快，16 位 hex 在百万级记忆中碰撞概率极低。

3. **工厂方法**：`from_wechat_msg()`, `from_telegram()`, `from_thought()` 等工厂方法封装了 URI 构造逻辑，避免调用方拼字符串。

4. **parent 属性**：通过路径分割实现父子关系，支持目录浏览。

---

### storage — 存储层

**文件 / Files:** `storage/sqlite_store.py`

SQLiteStore 是整个系统的持久化层，替代 OpenViking 的 VikingDB。

**设计决策：**

1. **SQLite WAL 模式**：`PRAGMA journal_mode=WAL` 启用 Write-Ahead Logging，支持并发读写，显著提升性能。

2. **5 张表的设计**：

| 表 Table | 用途 Purpose | 主键 PK |
|---|---|---|
| `contexts` | 记忆主表，存储 L0/L1/L2 + 元数据 | `id` (UUID hex) |
| `links` | 记忆间的关联关系 | `(source_uri, target_uri)` |
| `embeddings` | 向量索引，二进制存储 | `uri` |
| `sources` | 源层数据（原始数据） | `id` (UUID hex) |
| `taboos` | 禁忌规则 | `id` (UUID hex) |

3. **JSON 字段**：`tags`, `linked_uris`, `meta` 使用 JSON 字符串存储在 TEXT 列中。SQLite 没有原生 JSON 列类型，但 `LIKE` 查询对 JSON 数组足够用（如 `tags LIKE '%"搞钱"%'`）。

4. **INSERT OR REPLACE**：put() 使用 `INSERT OR REPLACE` 实现 upsert 语义。URI 有 UNIQUE 约束，重复写入会覆盖。

5. **向量存储为 BLOB**：embedding 向量用 `struct.pack` 序列化为二进制 BLOB，比 JSON 数组节省 ~4x 空间，读取也更快。

6. **全文搜索用 LIKE**：没有使用 SQLite FTS5 扩展，而是用 `LIKE '%keyword%'` 做全文搜索。原因：(a) 中文分词需要额外配置 FTS tokenizer；(b) 记忆量 <10k 时 LIKE 性能足够；(c) 向量搜索是主要的语义检索手段。

7. **索引策略**：在 `uri`, `parent_uri`, `context_type`, `category`, `created_at`, `importance`, `last_accessed` 上建索引，覆盖所有常用查询模式。

8. **touch() 刷新衰减**：每次访问记忆时调用 `touch()`，更新 `access_count` 和 `last_accessed`，刷新衰减计时器。这是 ACT-R 模型中"rehearsal"（复述）的实现。

---

### session — Session 管线

**文件 / Files:** `session/memory_extractor.py`, `session/memory_deduplicator.py`, `session/compressor.py`

Session 管线是 Amber Memory 最复杂的部分，负责从对话中自动提取长期记忆。

#### MemoryExtractor (memory_extractor.py)

**职责**：调用 LLM，从对话消息中提取候选记忆。

**设计决策：**

1. **CandidateMemory 中间结构**：提取结果不直接生成 Context，而是先生成 CandidateMemory。这样去重器可以在存储前做决策。

2. **语言检测**：`detect_language()` 通过统计 CJK 字符比例判断语言，确保 LLM 用正确的语言输出。

3. **parse_json_from_response()**：LLM 返回的 JSON 经常包裹在 markdown code block 中，这个函数处理各种格式：直接 JSON、```json 包裹、```包裹、以及从文本中提取 JSON 对象。

4. **ALWAYS_MERGE_CATEGORIES**：`person` 和 `preference` 类型的记忆总是走合并路径（跳过去重），因为人物信息和偏好天然是累积更新的。

5. **MERGE_SUPPORTED_CATEGORIES**：只有 `person`, `object`, `preference`, `pattern`, `goal` 支持合并。`activity`, `taboo`, `thought` 是独立事件，不应合并。

6. **merge_memory_bundle()**：合并两条记忆时，使用专门的 LLM prompt 生成合并后的 L0/L1/L2。冲突时以新记忆为准。

#### MemoryDeduplicator (memory_deduplicator.py)

**职责**：判断候选记忆与已有记忆的关系，决定 skip/create/merge/delete。

**设计决策：**

1. **三级决策模型**：

```
候选级决策 (Candidate-level):
  skip   — 完全重复，丢弃候选
  create — 新信息，创建新记忆
  none   — 候选不存储，但需要调整已有记忆

已有记忆级动作 (Per-existing action):
  merge  — 将候选信息合并到已有记忆
  delete — 删除已有记忆（被候选完全取代）
```

2. **硬约束规范化**：LLM 的决策可能不一致（比如同时说 create 和 merge），代码层面做了严格规范化：
   - `skip` 不能带 actions
   - `create` + `merge` → 降级为 `none`（不能同时创建新的又合并到旧的）
   - `create` 只能带 `delete` actions

3. **文本相似度兜底**：`_text_overlap()` 用字符集交集比计算相似度，作为没有 LLM 时的兜底方案。

4. **MAX_SIMILAR = 5**：最多取 5 条相似记忆给 LLM 判断，避免 prompt 过长。

#### SessionCompressor (compressor.py)

**职责**：编排整个 extract → dedup → store 管线。

**设计决策：**

1. **ExtractionStats 统计**：跟踪 created/merged/deleted/skipped 数量，方便调试和监控。

2. **LLM 重要性评估**：存储前用 LLM 评估重要性（0.0-1.0），失败时默认 0.5。

3. **管线是 async**：整个管线是异步的，因为 LLM 调用是 I/O 密集型操作。

---

### retrieve — 检索引擎

**文件 / Files:** `retrieve/retriever.py`, `retrieve/intent_analyzer.py`

#### Retriever (retriever.py)

**职责**：混合层级检索，融合文本、向量、衰减、传播四种信号。

**设计决策：**

1. **四维度评分**：

```
final_score = text_weight × text_score
            + vector_weight × vector_score
            + decay_weight × decay_score
            + propagation_weight × propagation_score

默认权重: text=0.3, vector=0.4, decay=0.2, propagation=0.1
```

2. **分数传播 (Score Propagation)**：从 OpenViking 借鉴的核心机制。维度级别的相关性分数会传播到该维度下的所有记忆：

```
propagation_score = α × max(text_score, vector_score) + (1-α) × parent_dimension_score
α = 0.6 (SCORE_PROPAGATION_ALPHA)
```

这意味着：如果"person"维度整体与查询高度相关，那么该维度下的所有记忆都会获得额外加分。

3. **暴力向量搜索**：当前使用 O(n) 暴力搜索所有 embedding。在 <10k 记忆时性能可接受（~50ms）。未来可以替换为 FAISS 或 HNSW。

4. **CJK 文本匹配**：`_text_match()` 同时使用字符重叠和词重叠两种方式，因为中文分词不可靠，字符级匹配更稳健。子串完全匹配额外加 0.3 分。

5. **可选 LLM Reranking**：检索结果可以用 LLM 重排序，但默认关闭（增加延迟和成本）。

6. **向量打包**：`pack_vector()` / `unpack_vector()` 使用 `struct` 模块将 float 列表序列化为紧凑的二进制格式。

#### IntentAnalyzer (intent_analyzer.py)

**职责**：分析查询意图，生成跨 8 维度的检索计划。

**设计决策：**

1. **QueryPlan 结构**：一个查询可能需要从多个维度检索。比如"帮我准备和老王的会议"需要查 person（老王是谁）、activity（最近互动）、taboo（禁忌话题）。

2. **优先级 1-5**：每个子查询有优先级，高优先级的结果获得更高的 boost。

3. **无 LLM 降级**：没有 LLM 时，直接用原始查询文本作为单一查询，不做意图分析。

---

