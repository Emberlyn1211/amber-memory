# Amber Memory — 架构文档

*最后更新：2026-02-26 余墨 #33*

## 一句话

Frankie 的个人记忆数据库。从微信聊天、Bear Notes、日记等数据源提取结构化记忆，供 Watchlace 和 Amber 使用。

## 目录结构

```
amber-memory/
├── core/                  # 核心模型
│   ├── context.py         # Context 数据模型（L0/L1/L2 + 衰减算法）
│   └── uri.py             # URI 文件系统范式
├── storage/
│   └── sqlite_store.py    # SQLite CRUD + 检索 + 链接 + 嵌入
├── sources/               # 数据源适配器（7个）
│   ├── wechat.py          # ✅ 在用 — 微信解密+消息提取
│   ├── bear.py            # ✅ 跑过 — Bear Notes 导入
│   ├── journal.py         # 📝 骨架 — memory/*.md 日记扫描
│   ├── photo.py           # 📝 骨架 — 照片 EXIF+VLM 语义
│   ├── voice.py           # 📝 骨架 — 语音转写（讯飞 STT）
│   ├── schedule.py        # 📝 骨架 — 读 Watchlace SQLite
│   └── link.py            # 📝 骨架 — URL 抓取+摘要
├── models/                # LLM/Embedding 接口
│   ├── ark_llm.py         # 豆包 ARK API
│   ├── claude_llm.py      # Claude API
│   ├── xunfei_stt.py      # 讯飞语音转写
│   └── embedder/          # 向量嵌入
│       ├── base.py
│       └── ark_embedder.py
├── retrieve/              # 检索层
│   ├── retriever.py       # 混合检索（文本+向量+衰减加权）
│   └── intent_analyzer.py # 意图分析（查询→8维度拆分）
├── session/               # 会话处理
│   ├── compressor.py      # Session 压缩（长对话→记忆）
│   ├── memory_extractor.py # LLM 记忆提取
│   ├── memory_deduplicator.py # 去重器
│   └── life_proposals.py  # 生活提案引擎
├── graph/
│   └── patterns.py        # 模式识别（行为规律检测）
├── integrations/
│   └── __init__.py        # OpenClaw context injection
├── sync/
│   └── __init__.py        # MEMORY.md 双向同步
├── prompts/
│   ├── manager.py         # Prompt 模板管理
│   └── templates/         # YAML prompt 模板
├── scripts/
│   └── reindex.py         # 向量索引重建
├── client.py              # 主接口 AmberMemory
├── cli.py                 # CLI 入口
├── migrate.py             # MEMORY.md → DB 迁移工具
├── demo.py                # 演示脚本
└── tests/                 # 12 个测试文件
```

## 数据库（~/.amber/memory.db）

### 表结构

#### contexts — 记忆主表（1102 条）
核心表，存所有提取出的记忆。每条记忆有三层：L0(abstract)、L1(overview)、L2(content)。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | `mem_` + 16位hex |
| uri | TEXT UNIQUE | `/wechat/memories/2026-02-26/abc12345` |
| parent_uri | TEXT | 父级 URI |
| abstract | TEXT | L0 一句话摘要（~10 tokens，永远加载）|
| overview | TEXT | L1 概览（~100 tokens，按需加载）|
| content | TEXT | L2 完整内容（深度查询时加载）|
| context_type | TEXT | 同 category |
| category | TEXT | 8维度之一：person/activity/object/preference/taboo/goal/pattern/thought |
| tags | TEXT JSON | 标签数组 |
| emotion | TEXT | 情绪标记 |
| importance | REAL | 重要度 0-1 |
| created_at | REAL | 创建时间戳 |
| updated_at | REAL | 更新时间戳 |
| last_accessed | REAL | 最后访问时间（衰减用）|
| event_time | REAL | 事件发生时间 |
| access_count | INT | 访问次数（衰减用）|
| source_session | TEXT | 来源 source ID |
| meta | TEXT JSON | 元数据（batch_id, protected 等）|

#### sources — 源数据表（17388 条）
原始数据，只读不改。每条是一天某个联系人的聊天记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | `src_wx_` + hex |
| type | TEXT | `wechat_chat` / `bear_note` / `journal` 等 |
| origin | TEXT | 来源标识 |
| raw_content | TEXT | 原始文本 |
| metadata | TEXT JSON | `{chat_id, contact_name, is_group, msg_count, date}` |
| processed | INT | 0=未处理, 1=已处理 |
| process_result | TEXT JSON | 提取结果摘要 |

#### people — 人物表（82 人）
从 contexts 里的 person 条目聚合出来的人物档案。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | |
| name | TEXT | 真名 |
| aliases | TEXT JSON | 别名列表 |
| relationship | TEXT | 与 Frankie 的关系 |
| description | TEXT | 简介 |
| importance | REAL | 重要度 |
| last_seen | REAL | 最后互动时间 |

#### relationships — 关系表（128 条）
人与人之间的关系。

| 字段 | 类型 | 说明 |
|------|------|------|
| person_a | TEXT PK | 人物A |
| person_b | TEXT PK | 人物B |
| relation | TEXT PK | 关系类型（同事/发小/家人等）|
| strength | REAL | 关系强度 0-1 |

#### taboos — 禁忌规则表（2 条）
正则匹配规则，给代码用的自动检测。

| 字段 | 类型 | 说明 |
|------|------|------|
| pattern | TEXT | 正则表达式 |
| description | TEXT | 说明 |
| scope | TEXT | `global` / 特定场景 |
| active | INT | 是否启用 |

注意：contexts 表里 category=taboo 的条目是 LLM 提取的具体禁忌内容，和这个表互补。

#### patterns — 行为模式表（10 条）
自动检测的行为规律。

#### proposals — 生活提案表（4 条）
基于模式识别生成的主动建议。

#### interactions — 互动记录表（0 条，未使用）
#### embeddings — 向量索引表（0 条，未使用）
#### links — 记忆关联表（0 条，未使用）


## 8 维度模型

| 维度 | category | 条目数 | 说明 | 数据来源 |
|------|----------|--------|------|---------|
| 人 | person | ~200+ | 联系人档案、关系、互动 | 微信对话提取 |
| 事 | activity | ~100+ | 做了什么事 | 微信对话、照片语义 |
| 物 | object | ~50+ | 物品、设备 | 对话提取 |
| 偏好 | preference | ~80+ | 喜好/习惯 | 行为积累 |
| 禁忌 | taboo | 2 | 不想被提及的事 | 手动设置 + LLM 检测 |
| 目标 | goal | ~30+ | 短期/长期目标 | 对话提取 |
| 模式 | pattern | ~50+ | 行为规律 | 对话提取 |
| 思考 | thought | ~100+ | 想法、反思 | 日记、Bear Notes |

## 三层记忆（L0/L1/L2）

```
L0 (abstract)  — 一句话，~10 tokens，永远加载到 context
                 例："Frankie 喜欢泰斯卡风暴威士忌"

L1 (overview)  — 一段概览，~100 tokens，按需加载
                 例："Frankie 偏好泰斯卡风暴（Talisker Storm），
                      是岛屿型单一麦芽，喜欢其烟熏海盐风味..."

L2 (content)   — 完整内容，深度查询时加载
                 例：完整的对话上下文、多次提及的汇总
```

## 衰减算法

记忆会随时间"遗忘"，模拟人类记忆：
- 半衰期 14 天（可配置）
- 每次访问重置衰减
- importance 高的衰减更慢
- 公式：`score = importance * decay_factor * (1 + log(access_count + 1))`

## 使用方法

### Python API

```python
from amber_memory import AmberMemory

mem = AmberMemory("~/.amber/memory.db")

# 存记忆
mem.remember("Frankie 喜欢泰斯卡风暴威士忌", source="telegram", importance=0.7)

# 检索（混合：文本 + 向量 + 衰减）
results = await mem.recall("Frankie 喜欢喝什么酒")

# 获取 top 记忆（按 importance * decay 排序）
top = mem.top(limit=15)

# 压缩 session（提取记忆 + 去重 + 存储）
memories = await mem.compress_session(messages, user="Frankie")

# 智能检索（意图分析 → 多维度查询）
results = await mem.smart_recall(messages, "他喜欢什么酒？")
```

### OpenClaw Context Injection（未接入）

```python
from amber_memory.integrations import OpenClawIntegration

integration = OpenClawIntegration(mem)

# 新 session 启动时注入
context_block = integration.to_system_prompt_block(max_chars=3000)
# 输出：关键记忆 + 最近事件 + 重要人物 + 禁忌

# 按需查询
recall = integration.generate_recall_context("木马是谁")

# 见面前拉人物档案
person = integration.generate_person_context("余青")
```

### 批量提取（当前在用）

```bash
cd wechat-bridge/
python3 -u extract_batch.py --limit 3000   # 跑未处理的源数据
python3 -u extract_batch.py --dry-run       # 只估算不跑
python3 -u extract_batch.py --skip-groups   # 跳过群聊
```

提取流程：`sources 表 → LLM 提取 → dedup.py 去重 → contexts 表`

### 去重逻辑（dedup.py）

- person 类型：按名字匹配（精确/子串/相似度>0.7）
- 其他类型：关键词 Jaccard 相似度 > 0.5 判为同一条
- merge 时：内容追加前做 Jaccard 相似度检测（>0.55 判重复，不追加）
- 不调 LLM，纯文本匹配

## 集成方案（TODO）

### 1. OpenClaw Session 启动注入

每次新 session 启动时：
1. 调 `integration.generate_session_context()` 生成记忆摘要
2. 注入到 system prompt 的 `<!-- amber-memory-context-start -->` 块
3. 包含：top 15 关键记忆 + 最近 3 天事件 + 重要人物 + 活跃禁忌

**接入方式：** 需要在 OpenClaw 的 session 初始化流程中加 hook，或者写成 workspace 文件自动加载。

### 2. 按需检索

当 Amber 需要回答关于 Frankie 的问题时：
1. 调 `integration.generate_recall_context(query)` 
2. 返回相关记忆 + 禁忌警告

### 3. 人物档案

见面/聊天前自动拉取：
1. 调 `integration.generate_person_context(name)`
2. 返回：关系、互动历史、相关记忆、禁忌

### 4. 生活提案

基于模式识别主动建议：
1. `life_proposals.py` 检测触发条件
2. 生成提案：共情 + 证据 + 行动 + 确认
3. 通过 Watchlace 语音播报

### 5. Watchlace 对接

amber-memory 作为 Watchlace 的记忆后端：
- `sources/schedule.py` 读 Watchlace 的 `watchlace.db`（SQLite）
- 日程数据导入源层 → 提取 activity 记忆
- 反向：Watchlace 调 amber-memory API 获取用户上下文

### 6. MEMORY.md 双向同步

- 导入：`sync/` 解析 MEMORY.md → 导入 DB（已有 migrate.py）
- 导出：DB → 生成 MEMORY.md（按维度组织，重要的在前）
- 定期同步，保持两边一致

## 当前状态总结

| 模块 | 状态 | 说明 |
|------|------|------|
| 核心模型 | ✅ 完成 | Context + URI + 衰减 + SQLite |
| 微信源 | ✅ 在用 | 17388 条源数据，~14000 已处理 |
| Bear 源 | ✅ 跑过 | 297 篇导入 |
| 其他 5 个源 | 📝 骨架 | 代码写了，没接真数据 |
| 批量提取 | ✅ 在用 | extract_batch.py + dedup.py |
| 去重 | ✅ 刚修 | 加了内容相似度检测 |
| 检索 | 📝 未测 | retriever.py 324行，没跑过真数据 |
| 向量索引 | ❌ 未做 | embeddings 表空，需跑 reindex.py |
| 人物图谱 | 📝 部分 | people 82人 + relationships 128条，但 interactions 空 |
| 模式识别 | 📝 部分 | patterns 10条，需要更多数据 |
| 生活提案 | 📝 部分 | proposals 4条，未接入 |
| Context Injection | 📝 未接 | 代码写好了，没接入 OpenClaw |
| MEMORY.md 同步 | 📝 未接 | 代码写好了，没跑过 |
