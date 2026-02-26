# Amber Memory 完整教程

> AI Agent 的认知记忆系统 — 从安装到高级用法

## 目录

- [简介](#简介)
- [安装与配置](#安装与配置)
- [核心概念](#核心概念)
- [快速上手](#快速上手)
- [记忆存储与检索](#记忆存储与检索)
- [Session 压缩管线](#session-压缩管线)
- [混合检索引擎](#混合检索引擎)
- [人物图谱](#人物图谱)
- [模式识别](#模式识别)
- [数据源导入](#数据源导入)
- [禁忌系统](#禁忌系统)
- [导出与同步](#导出与同步)
- [衰减算法详解](#衰减算法详解)
- [最佳实践](#最佳实践)
- [常见问题](#常见问题)

---

## 简介

Amber Memory 是为 AI Agent 设计的认知记忆系统。灵感来自字节跳动 OpenViking 和 Nowledge Mem 的记忆衰减模型，它让 AI 拥有类人的长期记忆能力：

- **记住重要的事** — 高重要性、高情感强度的记忆持续保鲜
- **遗忘不重要的事** — 基于 ACT-R 认知科学模型的指数衰减
- **自动提取知识** — 从对话中用 LLM 提取结构化记忆
- **精准召回** — 文本 + 向量 + 衰减的混合检索

### 设计哲学

1. **本地优先** — SQLite 存储，无外部服务依赖，数据完全在本地
2. **三级内容** — L0 摘要 / L1 概览 / L2 全文，按需加载节省 token
3. **八维分类** — 人、事、物、偏好、禁忌、目标、模式、思考
4. **文件系统范式** — 每条记忆有唯一 URI，像文件路径一样组织

---

## 安装与配置

### 基础依赖

```bash
# 克隆项目
git clone <repo-url> amber-memory
cd amber-memory

# 安装核心依赖
pip install pyyaml jinja2 httpx requests
```

### 可选依赖

```bash
# 照片 EXIF 提取
pip install Pillow

# 微信数据源（消息解压）
pip install zstandard
brew install sqlcipher  # macOS
```

### 环境变量

如果需要 LLM 提取和向量检索功能：

```bash
export ARK_API_KEY="your-volcengine-ark-api-key"
```

不设置 API Key 也能使用基础功能（手动存储、文本检索、衰减排名）。

### 作为 Python 模块导入

```python
import sys
sys.path.insert(0, "/path/to/amber-memory/..")

from amber_memory import AmberMemory
```

---

## 核心概念

### L0 / L1 / L2 三级内容

每条记忆都有三个层级，按需加载以节省 token：

| 层级 | 名称 | 长度 | 用途 |
|------|------|------|------|
| L0 | 摘要 (abstract) | ~10 tokens | 目录浏览，快速扫描 |
| L1 | 概览 (overview) | ~100 tokens | 相关性判断 |
| L2 | 全文 (content) | 无限制 | 深度查询 |

```python
ctx = mem.recall("威士忌", limit=1)[0][0]
print(ctx.to_l0())  # "Frankie 喜欢泰斯卡风暴威士忌"
print(ctx.to_l1())  # "Frankie 喜欢泰斯卡风暴威士忌，不加冰，纯饮..."
print(ctx.to_l2())  # 完整内容
```

### 八维度分类

| 维度 | 英文 | 说明 | 示例 |
|------|------|------|------|
| 人 | person | 联系人、关系 | "老王是同组同事" |
| 事 | activity | 做了什么 | "和老王吃火锅" |
| 物 | object | 物品、项目、概念 | "Watchlace 项目" |
| 偏好 | preference | 喜好/习惯 | "喜欢泰斯卡威士忌" |
| 禁忌 | taboo | 敏感话题 | "别提老王前女友" |
| 目标 | goal | 短期/长期目标 | "每天跑步 5 公里" |
| 模式 | pattern | 行为规律 | "周五下午社交" |
| 思考 | thought | 日记、反思 | "关于记忆衰减的思考" |

### URI 唯一标识

每条记忆都有唯一 URI，像文件路径一样组织：

```
/telegram/memories/2026-02-24/a1b2c3d4
/wechat/messages/老王/2026-02-24
/bear/notes/Watchlace架构设计_f8e9a1b2
amber://memories/person/c3d4e5f6a7b8
```

### 记忆衰减

基于 ACT-R 认知科学模型，记忆分数随时间指数衰减：

```
score = importance × recency × access_boost × link_boost × emotion_boost
```

- **recency**: `exp(-λ × days)`，半衰期 14 天
- **access_boost**: `1 + log(1 + access_count) × 0.3`
- **link_boost**: `1 + min(link_count, 10) × 0.05`
- **emotion_boost**: neutral=1.0, love=1.4, nostalgia=1.35, sadness=1.3

---

## 快速上手

最简单的用法，5 行代码：

```python
from amber_memory import AmberMemory

mem = AmberMemory("/tmp/my_memory.db")
mem.remember("Frankie 喜欢泰斯卡威士忌", importance=0.7, emotion="joy")
results = mem.recall("威士忌")
print(results[0][0].content)  # "Frankie 喜欢泰斯卡威士忌"
```

完整示例见 `examples/quickstart.py`。

---

## 记忆存储与检索

### 存储

```python
ctx = mem.remember(
    content="外公陈伯年 2018 年去世",
    source="diary",           # 来源标识
    importance=0.95,          # 重要性 0-1
    emotion="sadness",        # 情感标签
    tags=["家人", "外公"],     # 标签列表
    event_time=1546300800,    # 事件发生时间（Unix 时间戳）
    category="person",        # 分类
)
print(ctx.uri)  # 自动生成的 URI
```

### 检索方式

```python
# 1. 文本检索（带衰减加权）
results = mem.recall("外公", limit=5)

# 2. 按标签
results = mem.recall_by_tag("家人", limit=10)

# 3. 按时间范围
import time
results = mem.recall_by_time(
    start=time.time() - 7 * 86400,
    end=time.time(),
)

# 4. 衰减排名
top = mem.top(limit=10)

# 5. 即将遗忘的记忆
fading = mem.fading(threshold=0.1)
```

### 记忆操作

```python
# 获取单条记忆
ctx = mem.get("/telegram/memories/2026-02-24/a1b2c3d4")

# 删除记忆
mem.forget("/telegram/memories/2026-02-24/a1b2c3d4")

# 关联两条记忆
mem.link(uri_a, uri_b, relation="related")
```

---

## Session 压缩管线

这是 Amber Memory 最核心的功能：从对话中自动提取长期记忆。

### 管线流程

```
对话消息 → MemoryExtractor → MemoryDeduplicator → SessionCompressor → SQLiteStore
            (LLM 提取)       (去重/合并决策)       (编排存储)          (持久化)
```

### 使用方法

```python
import asyncio
from amber_memory import AmberMemory

async def main():
    mem = AmberMemory("memory.db", llm_fn=your_llm_function)

    messages = [
        {"role": "user", "content": "今天和老王吃了火锅"},
        {"role": "assistant", "content": "老王是你同事吗？"},
        {"role": "user", "content": "对，他负责海外业务"},
    ]

    memories = await mem.compress_session(
        messages=messages,
        user="Frankie",
        session_id="session-001",
    )

    for m in memories:
        print(f"[{m.category}] {m.abstract}")

asyncio.run(main())
```

### 去重决策

提取的候选记忆会经过去重检查：

- **SKIP** — 完全重复，跳过
- **CREATE** — 全新记忆，创建
- **MERGE** — 与已有记忆合并（更新内容）
- **DELETE** — 已有记忆过时，删除后创建新的

完整示例见 `examples/session_compression.py`。

---

## 混合检索引擎

### 三路融合

```python
results = await mem.hybrid_recall(
    "Frankie 的饮食偏好",
    limit=5,
    text_weight=0.4,     # 文本匹配权重
    vector_weight=0.4,   # 向量语义权重
    decay_weight=0.2,    # 衰减分数权重
)
```

### 意图感知检索

```python
results = await mem.smart_recall(
    messages=conversation_history,
    current_message="帮我准备和老王的会议",
    limit=10,
)
# IntentAnalyzer 自动生成多维查询计划：
# - person: "老王的信息"
# - activity: "和老王最近的互动"
# - taboo: "和老王相关的禁忌"
```

完整示例见 `examples/hybrid_search.py`。

---

## 人物图谱

```python
graph = mem.people

# 添加人物
wang = graph.add_person("老王", relationship="colleague",
                        description="同组同事", importance=0.7)

# 建立关系
graph.add_relationship(wang.id, boss.id, "上下级", strength=0.8)

# 记录互动
graph.record_interaction(wang.id, "一起吃火锅", memory_uri, "joy")

# 查询
person = graph.find_person("老王")
rels = graph.get_relationships(wang.id)
history = graph.get_interactions(wang.id, limit=10)
```

完整示例见 `examples/people_graph.py`。

---

## 模式识别

```python
detector = mem.patterns

# 启发式检测
time_patterns = detector.detect_time_patterns(days=30)
cat_patterns = detector.detect_category_patterns(days=30)

# 一键检测所有
all_patterns = detector.detect_all(days=30)

# LLM 辅助深度分析
deep_patterns = await detector.detect_with_llm(llm_fn, days=14)
```

完整示例见 `examples/pattern_detection.py`。

---

## 数据源导入

### Source Layer 架构

```
原始数据 → add_source() → process_sources() → 记忆
                                ↓
                          禁忌检查 → 拦截敏感内容
```

### 手动导入

```python
# 添加数据源
source_id = mem.add_source(
    source_type="chat",
    origin="wechat",
    raw_content="对话内容...",
    metadata={"contact": "老王"},
    event_time=time.time(),
)

# 处理所有未处理的源
count = mem.process_sources()
```

### 内置数据源

```python
# Bear Notes（需要本地 Bear 数据库）
count = mem.ingest_bear(tag="随感/Amber")

# WeChat（需要解密的微信数据库）
count = mem.ingest_wechat(limit=100)
```

完整示例见 `examples/data_ingestion.py`。

---

## 禁忌系统

```python
# 添加禁忌
mem.add_taboo("前女友", description="敏感话题")

# 检索时自动过滤
results = mem.recall("老王", respect_taboos=True)

# 数据源导入时自动拦截
mem.process_sources()  # 包含禁忌词的内容不会被处理

# 管理禁忌
taboos = mem.list_taboos()
mem.remove_taboo(taboo_id)
```

完整示例见 `examples/taboo_system.py`。

---

## 导出与同步

Amber Memory 的数据可以导出为 Markdown 文件，方便阅读和同步。

导出方式包括：
- 全量导出（按衰减分数排序）
- 按分类导出（每个维度一个文件）
- 人物图谱导出
- 每日摘要
- Bear Notes 同步格式

完整示例见 `examples/export_and_sync.py`。

---

## 衰减算法详解

### 公式

```
score = importance × recency × access_boost × link_boost × emotion_boost
```

### 参数配置

```python
from amber_memory.core.context import DecayParams

params = DecayParams(
    half_life_days=14.0,       # 半衰期（天）
    importance_floor=0.05,     # 最低分数（永不完全遗忘）
    access_weight=0.3,         # 访问频率权重
    link_weight=0.05,          # 关联记忆权重
    emotion_multipliers={      # 情感加成
        "neutral": 1.0,
        "joy": 1.2,
        "love": 1.4,
        "nostalgia": 1.35,
        "sadness": 1.3,
    },
)

mem = AmberMemory("memory.db", decay_params=params)
```

### 衰减曲线

以 importance=0.8 的记忆为例：

```
Day 0:  score ≈ 0.800  ████████████████████
Day 7:  score ≈ 0.566  ██████████████
Day 14: score ≈ 0.400  ██████████
Day 28: score ≈ 0.200  █████
Day 56: score ≈ 0.050  █ (触及 floor)
```

情感强烈的记忆衰减更慢（emotion_boost > 1.0），频繁访问的记忆会被"刷新"（access_boost）。

---

## 最佳实践

1. **重要性评估要准确** — 这是衰减算法的基础，建议用 LLM 评估
2. **禁忌词要全面** — 同一个概念的多种表述都要覆盖
3. **定期 reindex** — 新增记忆后运行 `await mem.reindex()` 更新向量索引
4. **善用标签** — 标签是最快的检索路径
5. **Session 压缩要及时** — 对话结束后立即压缩，避免上下文丢失
6. **导出备份** — 定期导出 Markdown 作为人类可读的备份
7. **调整半衰期** — 根据场景调整，工作助手用 7 天，个人日记用 30 天

---

## 常见问题

**Q: 不设置 LLM 能用吗？**
A: 能。基础功能（手动存储、文本检索、衰减排名、禁忌系统）不需要 LLM。Session 压缩和意图分析需要 LLM。

**Q: 数据存在哪里？**
A: SQLite 数据库文件，默认 `~/.amber/memory.db`。完全本地，不上传任何数据。

**Q: 向量检索需要 GPU 吗？**
A: 不需要。向量通过 API（如火山方舟 Embedding）生成，本地只做余弦相似度计算。小规模（<10k 条）暴力搜索即可。

**Q: 如何迁移数据？**
A: SQLite 文件可以直接复制。也可以用导出功能生成 Markdown，再导入到新实例。

**Q: 记忆会被真正删除吗？**
A: `forget()` 会从数据库删除。衰减只是降低分数，不会删除数据。`fading()` 可以找到低分记忆，由你决定是否清理。
