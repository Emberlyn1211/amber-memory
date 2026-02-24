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

