# Amber Memory 🧠

**8-dimension memory system for AI agents** — with decay, dedup, semantic retrieval, people graph, and pattern detection.

Built by [Amber Lin](https://github.com/Emberlyn1211), adapted from [OpenViking](https://github.com/volcengine/openviking) (ByteDance's context database).

## Why?

AI agents wake up fresh every session. They forget everything. Amber Memory gives them persistent, structured, decaying memory — like a human brain, but in SQLite.

## Key Features

- **8-Dimension Model**: person / activity / object / preference / taboo / goal / pattern / thought
- **14-Day Decay**: Memories fade like human memory (exponential half-life), refreshed on access
- **LLM Extraction**: Conversations → structured memories via prompt engineering
- **Smart Dedup**: skip / create / merge / delete decisions via LLM
- **Hybrid Retrieval**: text search + vector similarity + decay weighting + score propagation
- **People Graph**: Auto-build relationship networks from conversations
- **Pattern Detection**: Find behavioral patterns from memory history
- **Taboo System**: Configurable content filters — some things shouldn't be surfaced
- **Source Layer**: Full provenance — trace any memory back to its raw source
- **6 Data Sources**: WeChat, Bear Notes, photos, links, voice, daily journals

## Quick Start

```bash
pip install amber-memory
```

```python
from amber_memory import AmberMemory

# Initialize
mem = AmberMemory("~/.amber/memory.db")

# Store memories
mem.remember("Frankie喜欢泰斯卡风暴威士忌", source="telegram", category="preference")
mem.remember("老王是同组同事，负责海外业务", source="chat", category="person")
mem.remember("不要在老王面前提他前女友", source="chat", category="taboo")

# Recall (text search + decay scoring)
results = mem.recall("Frankie喜欢什么酒")
for ctx, score in results:
    print(f"[{ctx.category}] {ctx.abstract} (score={score:.3f})")

# Top memories (decay-weighted)
for ctx, score in mem.top(10):
    print(f"[{ctx.category}] {ctx.abstract}")

# People graph
mem.people.add_person("老王", relationship="colleague", description="同组，负责海外业务")
mem.people.record_interaction("老王", "一起吃火锅")
print(mem.people.find_person("老王"))

# Pattern detection
patterns = mem.patterns.detect_all(days=30)
for p in patterns:
    print(f"[{p.pattern_type}] {p.description}")

# Stats
print(mem.stats())
```

## Session Compression (with LLM)

The killer feature: feed a conversation, get structured long-term memories.

```python
import asyncio
from amber_memory import AmberMemory, ArkLLM

# Setup with LLM
llm = ArkLLM(api_key="your-ark-api-key")
mem = AmberMemory("~/.amber/memory.db", llm_fn=llm.chat)

messages = [
    {"role": "user", "content": "今天和老王吃了顿火锅，他说下个月要去日本出差"},
    {"role": "assistant", "content": "听起来不错！老王是你同事吗？"},
    {"role": "user", "content": "对，我们在同一个组。千万别在他面前提他前女友"},
]

# Extract → Dedup → Store (full pipeline)
memories = asyncio.run(mem.compress_session(messages, user="Frankie"))
# Output:
# [person] 老王是用户同组的同事，负责海外业务
# [activity] 用户今日与老王吃火锅，老王下月去日本出差
# [taboo] 禁止在老王面前提及他的前女友
```

## Architecture

```
┌─────────────────────────────────────────────┐
│                AmberMemory Client            │
├──────────┬──────────┬──────────┬────────────┤
│ Session  │ Retrieve │  Graph   │   Sync     │
│ Pipeline │ Pipeline │          │            │
│          │          │          │            │
│ Extract  │ Intent   │ People   │ MEMORY.md  │
│ Dedup    │ Search   │ Patterns │ Import     │
│ Compress │ Rerank   │          │ Export     │
├──────────┴──────────┴──────────┴────────────┤
│              Prompt Templates                │
│         (YAML + Jinja2, 4 templates)        │
├──────────────────────────────────────────────┤
│              Models Layer                    │
│         ARK LLM  |  ARK Embedder            │
├──────────────────────────────────────────────┤
│              Storage Layer                   │
│         SQLite (contexts, sources,           │
│          embeddings, taboos, links,          │
│          people, relationships, patterns)    │
├──────────────────────────────────────────────┤
│              Source Layer                    │
│    WeChat | Bear | Photo | Link | Voice     │
│                  Journal                     │
└─────────────────────────────────────────────┘
```

## 8 Dimensions

| Dimension | What it captures | Example |
|-----------|-----------------|---------|
| **person** | People and relationships | "老王是同组同事" |
| **activity** | Events and actions | "今天吃了火锅" |
| **object** | Projects, tools, things | "Watchlace 项目进度" |
| **preference** | Likes, habits, style | "喜欢泰斯卡威士忌" |
| **taboo** | Don't mention / don't do | "不要提老王前女友" |
| **goal** | Short/long term goals | "下周开始每天跑步" |
| **pattern** | Recurring behaviors | "每周三开组会" |
| **thought** | Reflections, insights | "觉得AI记忆很重要" |

## Decay Algorithm

Memories fade over time, just like human memory:

```
score = importance × 2^(-age_days / half_life)
```

- Default half-life: **14 days**
- Accessing a memory refreshes its timestamp (like human recall strengthening memory)
- High-importance memories decay slower
- Taboos never decay (importance = 0.9+)

## CLI

```bash
# Store
amber-memory remember "Frankie likes whisky" --category preference --importance 0.8

# Search
amber-memory recall "what does Frankie like" --limit 5

# People
amber-memory people --find "老王"
amber-memory people --add "小李" --relationship friend

# Patterns
amber-memory patterns --detect --days 30

# Stats
amber-memory stats

# Export
amber-memory export-md > MEMORY.md

# Ingest
amber-memory ingest-bear --tag "随感/Amber"
amber-memory ingest-wechat --limit 100

# Reindex (vector search)
amber-memory reindex
```

## Data Sources

| Source | Type | What it captures |
|--------|------|-----------------|
| WeChat | chat | Messages, contacts, groups |
| Bear Notes | text | Notes, reflections, ideas |
| Photos | image | EXIF + VLM scene description |
| Links | link | URL content + summary |
| Voice | voice | STT transcription |
| Journals | text | Daily markdown journals |

## Configuration

Environment variables:

```bash
# Required for LLM features (extraction, dedup, summarization)
export ARK_API_KEY="your-volcengine-ark-api-key"

# Optional
export AMBER_MEMORY_DB="~/.amber/memory.db"  # Database path
export ARK_EMBED_MODEL="doubao-embedding-large-text-240915"  # Embedding model
```

## vs OpenViking

We started from ByteDance's OpenViking (160K lines) and kept what matters:

| Feature | OpenViking | Amber Memory |
|---------|-----------|--------------|
| Storage | VikingDB (proprietary) | SQLite (portable) |
| Categories | 6 (profile/preferences/entities/events/cases/patterns) | 8 dimensions |
| Decay | ❌ | ✅ 14-day half-life |
| Taboo system | ❌ | ✅ |
| Source provenance | ❌ | ✅ Full trace |
| People graph | ❌ | ✅ |
| Pattern detection | ❌ | ✅ |
| Prompt engineering | ✅ YAML+Jinja2 | ✅ Adapted |
| LLM extraction | ✅ | ✅ 8-dimension |
| Dedup pipeline | ✅ | ✅ Adapted |
| Hierarchical retrieval | ✅ | ✅ Adapted |
| Score propagation | ✅ | ✅ |
| PDF/Doc parsing | ✅ | ❌ (not needed) |
| Enterprise features | ✅ | ❌ (not needed) |
| Lines of code | 160,000 | ~6,000 |

## License

MIT — see [LICENSE](LICENSE)

## Credits

- **OpenViking** by ByteDance — the foundation we built on
- **Amber Lin** — architecture, 8-dimension model, decay algorithm, taboo system
- **Frankie** — product vision, testing, and keeping Amber honest
