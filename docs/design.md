# Amber Memory 系统设计文档

> 版本 1.0 · 2026-02-24 · 听潮 #32
>
> *"记忆不是数据库查询，是一个活着的、会呼吸的、会遗忘的系统。"*

---

## 目录

1. [项目愿景](#1-项目愿景)
2. [核心创新：8 维度模型](#2-核心创新8-维度模型)
3. [衰减算法详解](#3-衰减算法详解)
4. [禁忌系统设计](#4-禁忌系统设计)
5. [源层架构](#5-源层架构)
6. [去重策略](#6-去重策略)
7. [检索管线](#7-检索管线)
8. [人物图谱](#8-人物图谱)
9. [模式识别](#9-模式识别)
10. [与 OpenViking 的对比](#10-与-openviking-的对比)
11. [未来路线图](#11-未来路线图)
12. [性能考量](#12-性能考量)

---

## 1. 项目愿景

### 为什么 AI Agent 需要记忆系统

每一个和 AI 对话过的人都经历过这种挫败感：你花了半小时解释你的项目背景、你的偏好、你的工作方式，然后下一次对话，一切归零。AI 不记得你是谁，不记得你们讨论过什么，不记得你说过"别再推荐 Java 了"。

这不是 AI 的"bug"，这是架构层面的缺失。当前主流 LLM 的工作模式是无状态的请求-响应：每次对话都是一张白纸。Context window 提供了短期记忆（一次对话内），但没有任何机制处理跨 session 的长期记忆。

人类的记忆系统是一个精密的多层架构：

- **感觉记忆**（Sensory Memory）：持续不到 1 秒，过滤掉 99% 的输入
- **工作记忆**（Working Memory）：容量约 7±2 个 chunk，持续 15-30 秒
- **长期记忆**（Long-term Memory）：理论上无限容量，但需要编码和巩固

更关键的是，人类记忆不是一个被动的存储系统。它是主动的、选择性的、会衰减的。你不会记住今天午饭吃了什么（除非特别好吃），但你会记住初恋的名字。这种选择性遗忘不是缺陷，而是特性——它让你能在海量经历中快速定位真正重要的信息。

Amber Memory 的愿景就是为 AI Agent 构建一个类人的记忆系统。不是简单的"把所有对话存进数据库"，而是一个会提取、会分类、会遗忘、会联想的活的记忆体。

### 与人类记忆的类比

| 人类记忆 | Amber Memory | 对应机制 |
|---------|-------------|---------|
| 感觉记忆 | 源层（Source Layer） | 原始数据暂存，大部分不会进入长期记忆 |
| 工作记忆 | Context Window | LLM 的上下文窗口，当前对话 |
| 短期记忆 | L0 摘要层 | 一句话索引，永远加载，快速扫描 |
| 长期记忆 | L1/L2 详情层 | 按需加载，深度回忆 |
| 遗忘曲线 | 衰减算法 | 指数衰减 + 情感加权 + 访问强化 |
| 情感记忆增强 | Emotion Boost | 带情感标签的记忆衰减更慢 |
| 联想记忆 | Link Graph | 记忆之间的关联网络 |
| 选择性注意 | 禁忌系统 | 主动屏蔽不想被提及的内容 |

这个类比不是修辞手法，而是设计原则。Amber Memory 的每一个模块都能在认知科学中找到对应物。

---

## 2. 核心创新：8 维度模型

### OpenViking 的 6 分类

字节跳动 Viking 团队开源的 OpenViking 是目前最完整的 AI 记忆系统参考实现。它将记忆分为 6 类：

1. **Profile** — 用户基本信息
2. **Preferences** — 偏好设置
3. **Entities** — 实体（人、物、项目）
4. **Events** — 事件
5. **Cases** — 案例/经验
6. **Patterns** — 模式

这个分类在技术场景下够用，但在"个人 AI 伴侣"场景下有明显的盲区。

### 我们的 8 维度

Amber Memory 将记忆空间扩展为 8 个正交维度：

| 维度 | context_type | 核心问题 | OpenViking 对应 |
|------|-------------|---------|----------------|
| **人** | `person` | 这个人是谁？和我什么关系？ | Entities（部分） |
| **事** | `activity` | 发生了什么？ | Events |
| **物** | `object` | 这个东西/项目是什么状态？ | Entities（部分） |
| **偏好** | `preference` | 我喜欢/习惯什么？ | Preferences |
| **禁忌** | `taboo` | 什么不能提？ | ❌ 无 |
| **目标** | `goal` | 我想达成什么？ | ❌ 无 |
| **模式** | `pattern` | 有什么规律？ | Patterns |
| **思考** | `thought` | 我在想什么？ | ❌ 无 |

### 为什么 8 比 6 更好

**1. 人和物的分离**

OpenViking 把"人"和"物"都塞进 Entities。但人和物的生命周期完全不同：人有关系演变、互动历史、情感连接；物有版本状态、功能描述、使用频率。把它们混在一起，检索时要么过度召回，要么漏掉关键信息。

Amber Memory 将 `person` 和 `object` 分开，`person` 维度有专门的 PeopleGraph 支撑，追踪关系网络和互动历史。`object` 维度则专注于实体状态管理。

**2. 禁忌维度的引入**

这是 OpenViking 完全没有的。一个真正的个人 AI 需要知道什么不该说。用户的前任、去世的亲人、失败的创业——这些话题不是"不重要"，恰恰相反，它们极其重要，重要到需要专门的机制来处理。禁忌不是删除记忆，而是标记"知道但不主动提起"。

**3. 目标维度**

人类的记忆系统天然围绕目标组织。你记得"下周要交报告"不是因为这件事本身有多重要，而是因为它和你的目标（完成工作、获得晋升）直接相关。OpenViking 没有目标维度，意味着它无法理解用户行为背后的动机。

**4. 思考维度**

日记、随感、反思——这些是人类内心世界的直接映射。OpenViking 的 Cases 勉强能装下"经验教训"，但装不下"今天觉得很累，可能是因为连续加班三天"这种纯粹的内心独白。`thought` 维度让 AI 能理解用户的情感状态和思维方式。

### 维度间的正交性

8 个维度的设计遵循一个原则：**每条记忆应该明确属于且仅属于一个维度**。我们在 prompt 模板中定义了精确的分类规则和常见混淆的处理方式：

- "计划做 X" → `activity`（行动，不是实体）
- "项目 X 状态：Y" → `object`（描述实体状态）
- "用户喜欢 X" → `preference`（不是 person）
- "遇到问题 A，用方案 B 解决" → `pattern`（可复用的经验）
- "今天觉得..." → `thought`（内心活动）
- "不要提外公" → `taboo`（禁忌）

这种正交性保证了检索的精确性：当用户问"我喜欢什么酒"时，系统只需要搜索 `preference` 维度，而不是在所有记忆中大海捞针。

---

## 3. 衰减算法详解

### 认知科学基础

1885 年，德国心理学家赫尔曼·艾宾浩斯发表了人类历史上第一条遗忘曲线。他发现记忆的保持量随时间呈指数衰减：刚学完的内容，20 分钟后忘掉 42%，1 小时后忘掉 56%，1 天后忘掉 74%。

这条曲线后来被认知科学家 John Anderson 形式化为 ACT-R（Adaptive Control of Thought—Rational）模型。ACT-R 的核心公式是：

```
activation = base_level + spreading_activation + noise
base_level = ln(Σ t_j^(-d))
```

其中 `t_j` 是第 j 次访问距今的时间，`d` 是衰减参数（通常 ≈ 0.5）。

现代间隔重复系统 FSRS（Free Spaced Repetition Scheduler）在此基础上加入了难度因子和稳定性参数，用于优化学习效率。

Amber Memory 的衰减模型融合了 ACT-R 的指数衰减和 FSRS 的多因子加权思想，但做了关键简化——因为我们的目标不是"帮用户记住"，而是"帮 AI 决定什么值得记住"。

### 数学推导

Amber Memory 的记忆分数公式：

```
score = importance × recency × access_boost × link_boost × emotion_boost
```

各因子定义如下：

**Recency（时间衰减）**：

```
recency = exp(-λ × days_since_last_access)
λ = ln(2) / half_life_days
```

当 `half_life_days = 14` 时：

```
λ = ln(2) / 14 ≈ 0.0495
```

这意味着：
- 第 0 天：recency = 1.0（刚访问）
- 第 7 天：recency ≈ 0.707（衰减到 70.7%）
- 第 14 天：recency = 0.5（半衰期，衰减到 50%）
- 第 28 天：recency = 0.25（两个半衰期，25%）
- 第 56 天：recency ≈ 0.0625（四个半衰期，6.25%）

**Access Boost（访问频率强化）**：

```
access_boost = 1 + ln(1 + access_count) × 0.3
```

这是对数增长，避免频繁访问的记忆分数爆炸：
- 0 次访问：boost = 1.0
- 1 次：boost ≈ 1.208
- 5 次：boost ≈ 1.537
- 20 次：boost ≈ 1.913
- 100 次：boost ≈ 2.384

**Link Boost（关联强化）**：

```
link_boost = 1 + min(link_count, 10) × 0.05
```

上限为 1.5（10 条关联），防止"超级节点"垄断分数。

**Emotion Boost（情感加权）**：

| 情感 | 乘数 | 理由 |
|------|------|------|
| neutral | 1.0 | 基准 |
| anger | 1.1 | 愤怒记忆略强 |
| surprise | 1.15 | 意外事件印象深 |
| joy | 1.2 | 快乐记忆持久 |
| fear | 1.25 | 恐惧记忆强烈 |
| sadness | 1.3 | 悲伤记忆深刻 |
| nostalgia | 1.35 | 怀旧记忆持久 |
| love | 1.4 | 爱的记忆最持久 |

这个排序基于认知心理学研究：负面情感（恐惧、悲伤）比正面情感（快乐）产生更强的记忆编码，而与人际关系相关的情感（爱、怀旧）最为持久。

**Importance Floor（重要性地板）**：

```
final_score = max(raw_score, importance_floor × importance)
importance_floor = 0.05
```

这保证了高重要性的记忆永远不会完全消失。一条 importance=0.9 的记忆，即使 recency 衰减到 0，最终分数也不会低于 0.045。

### 为什么选 14 天半衰期

Nowledge Mem 使用 30 天半衰期，我们选择了更激进的 14 天。原因：

1. **AI Agent 的对话频率远高于人类学习频率**。一个活跃用户每天可能产生 10-50 条记忆，30 天半衰期会导致记忆库膨胀过快。
2. **14 天接近人类的"两周遗忘窗口"**。心理学研究表明，如果一个信息在两周内没有被回忆或使用，它大概率不会进入长期记忆。
3. **Access Boost 提供了自然的"间隔重复"**。真正重要的记忆会被反复访问，access_boost 会抵消时间衰减。14 天半衰期 + 访问强化 = 重要记忆长存，琐碎记忆自然淡去。
4. **可配置性**。`DecayParams` 是一个 dataclass，用户可以根据自己的使用模式调整半衰期。高频用户可以设为 7 天，低频用户可以设为 30 天。

---

## 4. 禁忌系统设计

### 为什么需要禁忌系统

想象这个场景：用户的外公去年去世了。AI 在某次对话中提取到了这条信息，存进了记忆。然后在某个春节，AI 热情地说："要不要给外公打个电话拜年？"

这不是 AI 的恶意，而是它缺乏一个关键能力：**知道什么不该说**。

禁忌系统不是审查系统。审查是"不允许存在"，禁忌是"知道但不主动提起"。这个区别至关重要：

- 审查删除信息 → 信息丢失，无法恢复
- 禁忌标记信息 → 信息保留，但检索时过滤

### 实现细节

禁忌系统由三个层面组成：

**1. 存储层：taboos 表**

```sql
CREATE TABLE taboos (
    id TEXT PRIMARY KEY,
    pattern TEXT NOT NULL,      -- 匹配模式（关键词或正则）
    description TEXT DEFAULT '', -- 为什么是禁忌
    scope TEXT DEFAULT 'global', -- 作用范围
    active INTEGER DEFAULT 1,   -- 是否激活
    created_at REAL NOT NULL
);
```

`scope` 字段支持未来的细粒度控制：`global`（全局禁忌）、`retrieval`（仅检索时过滤）、`extraction`（源层拦截，不提取为记忆）。

**2. 检索层过滤**

在 `AmberMemory.recall()` 中，每次检索结果都会经过禁忌过滤：

```python
if respect_taboos:
    taboos = self.store.list_taboos(active_only=True)
    if taboos:
        results = [
            ctx for ctx in results
            if not any(t["pattern"] in f"{ctx.abstract} {ctx.content}" for t in taboos)
        ]
```

这是一个后置过滤器：先检索，再过滤。这样做的好处是禁忌不影响记忆的存储和索引，只影响最终呈现。

**3. 源层拦截**

在 `_process_one_source()` 中，新数据进入源层时会检查禁忌：

```python
triggered = self.store.check_taboos(content)
if triggered:
    return []  # 不处理，不提取记忆
```

这是一个前置拦截器：如果原始数据触发了禁忌，直接跳过，不会产生任何记忆。

### 与隐私保护的关系

禁忌系统本质上是一个用户主权机制。它回答的问题是："谁有权决定 AI 记住什么？"

答案是：**用户**。

这和 GDPR 的"被遗忘权"（Right to be Forgotten）理念一致，但更进一步：

- GDPR 的被遗忘权是事后删除（数据已经被处理了）
- 禁忌系统是事前拦截 + 事后过滤（双重保护）

用户可以随时添加、查看、移除禁忌。禁忌的移除是软删除（`active = 0`），保留审计轨迹。

---

## 5. 源层架构

### 四层架构的设计哲学

```
源层 (Source)     → 原始数据：日记、微信对话、照片、日程、Bear Notes
                     ↓ LLM 拆解 + 结构化
记忆层 L0         → 一句话摘要（永远加载，~10 tokens）
记忆层 L1         → 一段概览（按需加载，~100 tokens）
记忆层 L2         → 完整记忆（深度查询时加载）
```

### 为什么不直接存记忆

一个朴素的设计是：对话进来 → LLM 提取记忆 → 存进数据库。为什么要多一个"源层"？

**1. 源层是 Truth，记忆层是 Interpretation**

源层存储的是原始数据：微信消息的原文、照片的文件路径、日记的 Markdown。这些数据是客观事实，不会因为 LLM 的理解偏差而失真。

记忆层存储的是 LLM 对原始数据的理解和提炼。这个理解可能有误，可能遗漏，可能随着模型升级而需要重新生成。

有了源层，记忆层就是可重建的。如果某天我们换了更好的 LLM，或者发现提取 prompt 有 bug，只需要重新处理源层数据，就能重建整个记忆库。

**2. 源层支持多数据源统一接入**

Amber Memory 的源层定义了 8 种数据类型：

| 类型 | 存储方式 | 来源 |
|------|---------|------|
| text | SQLite text | 日记、Bear Notes、文章 |
| chat | SQLite JSON | 微信、Telegram |
| image | 文件路径 + 语义描述 | 摄像头、截图 |
| voice | 文件路径 + 转写 | 微信语音、录音 |
| link | URL + 抓取内容 | 分享的推文/文章 |
| schedule | 结构化事件 | Watchlace 日程 |
| location | 坐标 + 地名 | 照片 EXIF、GPS |
| document | 文件路径 + 提取文本 | PDF、文件 |

每种数据类型有专门的 Source Adapter（如 `WeChatSource`、`BearSource`、`PhotoSource`、`LinkSource`），负责将原始数据标准化为源层记录。

**3. 源层实现了处理管线的解耦**

源层记录有一个 `processed` 标志位。新数据进入源层时 `processed = 0`，经过 LLM 提取后标记为 `processed = 1`，同时记录产生了哪些记忆 URI（`process_result`）。

这个设计让数据接入和记忆提取完全解耦：

- 数据接入可以批量、异步、离线进行
- 记忆提取可以按需、增量、重试
- 失败的提取不会丢失原始数据

**4. 溯源链接**

每条记忆的 `meta` 字段中保存了 `source_id`，通过 `trace_source()` 方法可以追溯到原始数据。这实现了完整的溯源链：

```
用户看到一条记忆 → 点击"为什么记住这个" → 追溯到源层记录 → 看到原始微信消息
```

这种透明性是建立用户信任的关键。

---

## 6. 去重策略

### 问题定义

记忆去重是整个系统中最微妙的部分。考虑这些场景：

- 用户说"我喜欢威士忌"，后来又说"我最喜欢泰斯卡风暴"——这是更新，不是重复
- 用户说"项目进度 50%"，后来说"项目进度 80%"——这是演进，旧的应该被替换
- 用户说"今天和老王吃饭"，后来说"昨天和老王吃饭聊了创业"——这是补充，应该合并
- 用户说"我喜欢咖啡"，后来说"我喜欢咖啡"——这是纯重复，应该跳过

简单的文本相似度无法区分这些情况。我们需要 LLM 的语义理解能力。

### 三种候选级决策

Amber Memory 的去重系统定义了三种候选级决策（candidate-level decision）：

**`skip` — 跳过**

候选记忆没有新信息。可能是纯重复、换了说法、或者信息太弱不值得存储。

触发条件：LLM 判断候选和已有记忆语义完全重叠，没有增量信息。

效果：什么都不做。不创建新记忆，不修改已有记忆。

**`create` — 创建**

候选记忆是有效的新信息，应该作为独立条目存储。

触发条件：LLM 判断候选和已有记忆主题不同，或者虽然相关但足够独立。

效果：创建新记忆。可选地删除被完全取代的旧记忆（通过 per-item `delete` action）。

**`none` — 不创建，但调整已有**

候选记忆本身不需要独立存储，但已有记忆需要更新。

触发条件：候选和已有记忆是同一主题的不同版本，应该合并而非并存。

效果：不创建新记忆，但通过 per-item action 合并或删除已有记忆。

### Per-item Actions：merge vs delete 的边界

对于每条已有的相似记忆，系统可以执行两种操作：

**`merge` — 合并**

将候选记忆的信息融入已有记忆。适用于：

- 细化：已有记忆说"喜欢威士忌"，候选说"最喜欢泰斯卡风暴" → 合并为更具体的偏好
- 纠正：已有记忆有部分错误，候选提供了正确信息 → 合并，以新为准
- 补充：已有记忆缺少细节，候选提供了补充 → 合并，保留两者的信息

合并通过 `memory_merge_bundle` prompt 模板实现，LLM 会生成新的 L0/L1/L2 三层内容，遵循"冲突以新为准，不冲突保留旧的"原则。

**`delete` — 删除**

完全移除已有记忆。这是一个高风险操作，只在严格条件下触发：

- 已有记忆被候选**完全**取代（不是部分冲突）
- 已有记忆的**所有**陈述都已过时或失效
- 主题和维度必须匹配（不能跨维度删除）

关键边界：**部分冲突不删除，用 merge**。这是一条硬规则，写在 dedup prompt 中。原因是删除是不可逆的（虽然源层数据还在），而 merge 是增量的、可追溯的。

### 硬约束

去重系统有一组硬约束，防止 LLM 产生不一致的决策：

1. `decision = skip` 时，不返回任何 per-item action
2. 任何 per-item 用了 `merge` 时，`decision` 必须是 `none`（不能同时创建新的又合并旧的）
3. `decision = create` 时，per-item 只能是 `delete`（创建新的可以顺便清理旧的，但不能合并）
4. URI 必须精确匹配已有记忆列表中的值
5. 不变的已有记忆不出现在 action list 中

代码中还有一个额外的归一化逻辑：如果 LLM 返回了 `create + merge` 的矛盾组合，系统会自动归一化为 `none`，优先保护已有数据。

### 分类特殊处理

不同维度的去重策略不同：

- **`person` 和 `preference`**：属于 `ALWAYS_MERGE_CATEGORIES`，跳过去重直接合并。因为人物信息和偏好天然是累积的，每次对话都可能补充新细节。
- **`person`、`object`、`preference`、`pattern`、`goal`**：属于 `MERGE_SUPPORTED_CATEGORIES`，支持 merge 操作。
- **`activity`、`taboo`、`thought`**：不支持 merge。事件是独立的（今天吃饭和昨天吃饭是两件事），禁忌是绝对的，思考是时间点的快照。

---

## 7. 检索管线

### 完整流程

Amber Memory 的检索管线是一个五阶段流水线，从用户的自然语言查询到最终的记忆列表：

```
用户消息 → 意图分析 → 多维度检索 → 分数传播 → 衰减加权 → 收敛排序 → [可选 LLM 重排]
```

### Stage 1：意图分析（Intent Analysis）

`IntentAnalyzer` 接收当前消息和最近对话历史，通过 LLM 生成一个 `QueryPlan`：

```python
@dataclass
class QueryPlan:
    queries: List[TypedQuery]   # 带维度标注的查询列表
    reasoning: str              # LLM 的分析过程
    session_context: str        # 会话上下文摘要
```

每个 `TypedQuery` 包含：
- `query`：具体的检索文本
- `context_type`：目标维度（person/activity/object/...）
- `intent`：查询目的
- `priority`：1-5 的优先级

例如，用户说"Frankie 上周做了什么决定？"，IntentAnalyzer 可能生成：

```json
{
  "queries": [
    {"query": "Frankie 决定", "context_type": "activity", "priority": 1},
    {"query": "Frankie", "context_type": "person", "priority": 3}
  ]
}
```

当没有 LLM 可用时，系统退化为简单的文本查询，保证基本功能不依赖外部服务。

### Stage 2：多维度检索

对 QueryPlan 中的每个 TypedQuery，系统并行执行两种检索：

**文本检索**：按维度搜索，将查询拆分为 token，在 abstract/overview/content/tags 中做 LIKE 匹配。评分基于字符重叠度、词重叠度和子串匹配奖励的组合：

```python
score = max(char_overlap, word_overlap) + substr_bonus
```

**向量检索**：如果配置了 embedding 函数，将查询文本编码为向量，与存储的记忆向量做余弦相似度计算。当前实现是暴力扫描（brute-force），对 10k 以下的记忆库足够快。

同时执行一次全局文本搜索，捕获跨维度的匹配。

### Stage 3：分数传播（Score Propagation）

这是 Amber Memory 从 OpenViking 继承并改进的核心机制。

每个维度有一个维度级分数（dimension score），等于该维度下最佳匹配的分数。然后，维度级分数会"传播"到该维度下的所有候选记忆：

```python
prop_score = α × max(text_score, vector_score) + (1 - α) × parent_score
```

其中 `α = 0.6`（SCORE_PROPAGATION_ALPHA）。

这意味着：如果 `preference` 维度整体和查询高度相关，那么该维度下即使文本匹配度不高的记忆也会获得分数提升。这模拟了人类记忆的"联想激活"——当你想到"威士忌"时，不仅会想到"泰斯卡风暴"，还会联想到"上次在酒吧的经历"。

### Stage 4：衰减加权

将时间衰减分数融入最终排名：

```python
final = text_weight × ts + vector_weight × vs + decay_weight × norm_decay + propagation_weight × prop_score
```

默认权重分配：
- 文本匹配：0.3
- 向量相似度：0.4
- 衰减分数：0.2
- 传播分数：0.1

向量相似度权重最高，因为语义匹配比关键词匹配更准确。衰减分数确保最近访问的记忆优先。传播分数作为补充信号。

### Stage 5：收敛检测与排序

系统设置了 `DEFAULT_THRESHOLD = 0.05` 的最低分数阈值，低于此分数的候选被过滤掉。剩余候选按 final score 降序排列，取 top-k。

`MAX_CONVERGENCE_ROUNDS = 2` 定义了收敛检测的轮数：如果连续两轮检索的 top-k 结果不变，提前终止。这在多轮迭代检索场景下节省计算。

### Stage 6：可选 LLM 重排

当 `rerank=True` 且有 LLM 可用时，系统会将 top-20 的结果发给 LLM 做最终排序。LLM 看到每条记忆的摘要和维度标签，返回排序后的编号列表。重排后的分数会根据位置做 boost 调整。

这一步是可选的，因为 LLM 调用有延迟和成本。对于大多数查询，前五个阶段已经足够准确。

### 访问刷新

检索完成后，所有返回的记忆都会被 `touch()`——更新 `last_accessed` 时间戳和 `access_count`。这实现了自然的"间隔重复"：被频繁检索的记忆衰减更慢。

---

## 8. 人物图谱

### 为什么需要人物图谱

人是记忆的锚点。当你回忆过去，几乎所有重要的记忆都和某个人有关：和谁吃的饭、和谁吵的架、谁教了你什么。一个没有人物概念的记忆系统，就像一本没有人物索引的小说——你知道发生了什么事，但不知道是谁做的。

Amber Memory 的 `PeopleGraph` 模块自动构建和维护一个人际关系网络，包含三个核心实体：

### 数据模型

**Person（人物）**

```python
@dataclass
class Person:
    id: str                     # 唯一 ID
    name: str                   # 主要名字
    aliases: List[str]          # 别名/昵称
    relationship: str           # 和用户的关系：family/friend/colleague/acquaintance
    description: str            # 这个人是谁
    first_seen: float           # 首次出现时间
    last_seen: float            # 最近出现时间
    interaction_count: int      # 互动次数
    importance: float           # 重要性 0-1
```

**Relationship（关系）**

```python
@dataclass
class Relationship:
    person_a: str       # 人物 A
    person_b: str       # 人物 B
    relation: str       # 关系类型：colleague, couple, siblings...
    strength: float     # 关系强度 0-1
    since: float        # 关系建立时间
```

**Interaction（互动记录）**

每次在记忆中提到某人，都会记录一条互动：时间戳、上下文、关联的记忆 URI、情感倾向。

### 自动构建方法论

人物图谱的构建分为两条路径：

**路径 1：数据源直接导入**

微信联系人通过 `WeChatSource.contacts_to_contexts()` 直接导入为 `person` 类型的记忆。每个联系人包含微信号、昵称、备注、是否群聊等信息。这是图谱的"种子数据"。

**路径 2：LLM 从文本中提取**

`PeopleGraph.extract_people_from_text()` 使用 LLM 从任意文本中提取人物提及：

```json
{
  "people": [
    {
      "name": "老王",
      "relationship": "colleague",
      "context": "一起讨论了新项目的技术方案"
    }
  ]
}
```

当 LLM 不可用时，退化为启发式提取：匹配"老X"、"小X"等中文姓名模式，以及"和XX"、"跟XX"等上下文模式。

**路径 3：别名解析**

同一个人可能有多个称呼：微信备注"张三"、对话中叫"老张"、群里叫"张总"。`find_person()` 方法支持按名字和别名模糊匹配，将不同称呼关联到同一个人物实体。

### 图谱的价值

人物图谱不仅是一个通讯录，它是记忆系统的"社交索引"：

- **关系查询**："我的同事有哪些？" → 按 relationship 过滤
- **互动历史**："我最近和老王聊了什么？" → 查 interactions 表
- **重要性排序**："谁是我最常联系的人？" → 按 interaction_count 排序
- **关系网络**："老王和小李什么关系？" → 查 relationships 表

---

## 9. 模式识别

### 从记忆中发现行为规律

人类大脑擅长从重复经历中提取模式："每周三下午开会"、"压力大的时候喜欢吃甜食"、"和老板谈话后心情总是不好"。这些模式不是某一条记忆，而是多条记忆的统计规律。

Amber Memory 的 `PatternDetector` 模块实现了两种模式识别方法：

### 启发式检测

**时间模式（Time Patterns）**

分析指定时间窗口内（默认 30 天）所有记忆的时间分布：

- **小时分布**：统计每个小时的记忆数量，找出活跃高峰。例如："活跃高峰在 22:00 左右（15 次记录）"
- **星期分布**：统计每个工作日的记忆数量，找出最忙的日子。例如："周三最活跃（8 次记录）"

置信度计算：`confidence = min(count / total_memories, 0.9)`，确保样本量足够时才报告高置信度。

**类别模式（Category Patterns）**

统计各维度记忆的占比，找出主导维度：

```python
for cat, count in cat_counts.most_common(3):
    ratio = count / total
    if ratio > 0.2:  # 超过 20% 才报告
        patterns.append(Pattern(
            description=f"近 {days} 天 {int(ratio*100)}% 的记忆是「{cat}」类型",
            confidence=ratio,
        ))
```

例如："近 30 天 45% 的记忆是 activity 类型"——说明用户最近在密集做事，而不是在思考或社交。

### LLM 深度检测

启发式方法只能发现统计规律，无法理解语义。`detect_with_llm()` 将最近的记忆摘要发给 LLM，让它发现更深层的模式：

```
[02-20 09:00] [activity] 和投资人开会
[02-20 14:00] [thought] 觉得融资进展太慢
[02-21 10:00] [activity] 修改商业计划书
[02-21 22:00] [thought] 焦虑，睡不着
[02-22 09:00] [activity] 又和另一个投资人开会
```

LLM 可能识别出："用户处于融资焦虑期，白天密集见投资人，晚上焦虑失眠，形成了一个压力循环模式。"

这种语义级别的模式识别是启发式方法无法做到的。

### 模式的持久化

检测到的模式存储在 `patterns` 表中，包含类型、描述、置信度、证据（支撑记忆的 URI 列表）、频率等字段。模式本身也可以作为 `pattern` 维度的记忆被检索到。

---

## 10. 与 OpenViking 的对比

### 我们保留了什么

**1. 文件系统范式（URI）**

OpenViking 最优雅的设计之一是用文件系统路径来组织记忆。每条记忆有一个唯一的 URI，像文件路径一样支持层级浏览和目录列表。

Amber Memory 完整保留了这个设计，URI 格式为 `/{source}/{category}/{path}`：

```
/wechat/messages/张三/2026-02-24
/self/thoughts/2026-02-24/about-memory
/bear/notes/随感_abc12345
```

**2. L0/L1/L2 三级内容**

OpenViking 的分层内容模型是 token 效率的关键：

- L0（~10 tokens）：永远加载，用于目录浏览和快速扫描
- L1（~100 tokens）：按需加载，用于相关性判断
- L2（无限）：深度查询时加载，完整内容

这个设计让系统可以在有限的 context window 中装入更多记忆的索引信息。

**3. 层级检索 + 分数传播**

从维度级分数传播到记忆级分数的机制，直接来自 OpenViking 的 HierarchicalRetriever。

**4. Session Compressor 管线**

extract → dedup → merge/create → store 的管线架构，是 OpenViking 的核心贡献之一。

### 我们扔掉了什么

**1. VikingDB 依赖**

OpenViking 深度绑定字节内部的 VikingDB 向量数据库。我们用 SQLite + 本地向量索引替代，实现了零外部依赖。向量存储为 BLOB，检索用暴力扫描。

**2. Pydantic 重型模型**

OpenViking 大量使用 Pydantic 做数据验证。我们用 Python dataclass 替代，更轻量，启动更快，依赖更少。

**3. 复杂的线程安全机制**

OpenViking 的 PromptManager 有线程锁、缓存失效等复杂机制。我们简化为单线程 + 简单字典缓存，因为 Amber Memory 是单用户系统，不需要并发安全。

**4. 6 分类模型**

用 8 维度替代，增加了 taboo、goal、thought 三个维度，拆分了 entities 为 person + object。

### 为什么这样取舍

核心原则：**Amber Memory 是个人 AI 伴侣的记忆系统，不是企业级知识库**。

OpenViking 的设计目标是通用的、可扩展的、企业级的。它需要处理多用户、高并发、大规模数据。这些需求在个人 AI 场景下不存在。

我们的设计目标是：
- **本地优先**：所有数据在本地，不依赖云服务
- **单用户**：不需要多租户隔离
- **轻量级**：SQLite 一个文件搞定，不需要部署数据库服务
- **隐私优先**：禁忌系统、源层拦截、透明溯源

