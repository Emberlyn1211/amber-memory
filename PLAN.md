# Amber Memory — 开发计划

*最后更新：2026-02-24 听潮 #32*

## 架构

```
源层 (Source)     → 原始数据：日记、微信对话、照片、日程、Bear Notes、语音、链接
                     ↓ LLM 拆解 + 结构化
记忆层 L0         → 一句话摘要（永远加载，~10 tokens）
记忆层 L1         → 一段概览（按需加载，~100 tokens）
记忆层 L2         → 完整记忆（深度查询时加载）
```

## 8 维度模型

| 维度 | context_type | 说明 | 数据来源 |
|------|-------------|------|---------|
| 人 | person | 联系人、关系网络、互动历史 | 微信、通讯录、对话提取 |
| 事 | activity | 第一视角做了什么 | 摄像头照片语义、日程对账 |
| 物 | object | 物品、项目、地点、概念 | 照片识别、对话提取 |
| 偏好 | preference | 喜欢/不喜欢/习惯 | 行为积累、主动设置 |
| 禁忌 | taboo | 不想被提及的事 | 用户主动设置、AI 检测 |
| 目标 | goal | 短期/长期目标、进度 | 用户设置、日程分析 |
| 模式 | pattern | 作息规律、行为模式 | 照片+日程+位置自动识别 |
| 思考 | thought | 日记、随感、反思 | memory/*.md、Bear Notes |

## 源层数据类型

| 类型 | 存储 | 来源 | 必含元数据 |
|------|------|------|-----------|
| text | SQLite text | 日记、Bear Notes、文章 | timestamp |
| chat | SQLite JSON | 微信、Telegram | timestamp, sender, chat_id |
| image | 文件路径 + 语义描述 | 摄像头、截图 | timestamp, location(尽量) |
| voice | 文件路径 + 转写 | 微信语音、录音 | timestamp, duration |
| link | URL + 抓取内容 | 分享的推文/文章 | timestamp, url |
| schedule | 结构化事件 | Watchlace 日程 | timestamp, event_time |
| location | 坐标 + 地名 | 照片 EXIF、GPS | timestamp, lat, lng |
| document | 文件路径 + 提取文本 | PDF、文件 | timestamp |

---

## 开发清单

### Phase 1 — 核心架构 ✅ 已完成
- [x] Context 模型（L0/L1/L2 + 衰减算法）
- [x] URI 文件系统范式
- [x] SQLite 存储（CRUD + 检索 + 链接 + 嵌入）
- [x] 记忆提取器（LLM + 启发式）
- [x] 混合检索器（文本 + 向量 + 衰减加权）
- [x] 豆包 ARK API 集成
- [x] 微信数据源（解密 + 联系人 + 消息）
- [x] 迁移工具（MEMORY.md + 日记 → 401 条记忆）
- [x] context_type 扩展为 8 维度
- [x] 源层表 + CRUD + 处理管线
- [x] 禁忌系统（配置 + 检索过滤 + 源层拦截）
- [x] 透明记忆面板 API（查看/删除/溯源）
- [x] 29 个测试全通过

### Phase 2 — 数据源接入
**全量文字已完成（v8 跑完即固定），后续切增量模式：新消息实时处理，旧数据不回溯**

#### 增量模式（新消息进来时）
- [ ] 语音：silk → wav → 讯飞 STT → 文字 → 提取（价值最高，重要对话常用语音）
- [ ] 链接/文章：提取 URL → 抓正文 → 摘要 → 提取（反映兴趣偏好）
- [ ] 图片：豆包 VLM → 场景描述 → 提取（去哪了、和谁在一起）
- [ ] 朋友圈：见下方专项

#### 朋友圈数据源（专项）
- [x] sns.db XML 解析（文字/图片URL/点赞/评论/位置）
- [ ] 区分内容类型：纯图片 vs 链接文章 vs 视频 vs 封面图
- [ ] Mac 微信只缓存打开过的朋友圈，需要实时刷才有数据
- [ ] GUI 自动化刷朋友圈（难度高）：搜索联系人→点头像→点朋友圈→滚动→截图
  - 已知问题：聊天记录删了搜不到人、朋友圈权限（三天/半年/仅聊天）、Mac 入口深
  - 短期方案：Demo 时手动刷目标人朋友圈，sns.db 自动缓存，再跑解析
  - 长期方案：手机端 Frida hook 或无障碍服务（但 Frida 挂久了微信退登录）

#### 其他数据源
- [ ] 照片语义（豆包图像识别 → 场景描述 → 源层 image → 记忆层"事"）
- [ ] Watchlace 内部日程读取（API → 源层 schedule）
- [ ] 位置数据（照片 EXIF + GPS → 源层 location）
- [x] Bear Notes 导入（读 SQLite → 源层 text → 记忆层"思考"，已跑 297 篇）
- [ ] 微信换号支持（新 Frida + 自动检测 wxid）

### Phase 3 — 智能层
- [ ] 豆包 embedding 语义搜索（embeddings 表空，需跑 reindex.py）
- [x] LLM 自动提取（extract_batch.py + dedup.py，已跑 ~14000 条，产出 1100+ 记忆）
- [ ] 人物图谱（people 82人 + relationships 128条，但 interactions 空，需全量数据后跑）
- [ ] 模式识别引擎（patterns 10条，需更多数据）
- [ ] "生活提案"触发器（proposals 4条，代码写了没接入）
- [x] 承诺追踪（promise_tracker.py，已从现有记忆提取 110 条承诺）

### Phase 4 — Watchlace 智能层（非记忆，独立开发）
- [ ] 高德 API 接入（smart_reminder.py 骨架写好，差 API Key）
- [ ] 日程智能提醒（记忆层位置+模式 + 高德路线 → 提前提醒）
- [ ] 日程对账（照片语义 vs 日程计划，自动比对）
- [ ] 人格滑杆系统（Warmth/Playfulness/Banter/Formality/Pushiness/Chattiness）
- [ ] 漫画生成（照片 → 商业插画风格日报）
- [x] 语音 v2（流式 AI + MiniMax TTS + 预生成缓存）
- [x] Demo 场景模拟器（demo_scenario.py，见面前智能简报）
- [x] 承诺追踪 API + 记忆检索 API + 跨源冲突检测 API

### Phase 5 — 集成
- [ ] OpenClaw 集成（integrations/__init__.py 代码写好，未接入 session 启动流程）
- [ ] 反向导出 MEMORY.md（sync/__init__.py 代码写好，未跑过）
- [ ] Watchlace API 对接（记忆系统作为后端服务）
- [ ] 禁忌系统接入日常对话（taboos 表 + contexts taboo 条目 → system prompt 注入）
- [ ] 表结构文档 + 集成方案文档（ARCHITECTURE.md 已写）

---

## 设计原则

1. **源层永远不动** — 原始数据是 truth，只读不改
2. **记忆层可重建** — 源层完好就能重新导入
3. **透明可控** — 用户能看到记了什么、为什么记、一键删除
4. **禁忌优先** — 敏感内容不自动处理，需确认
5. **衰减是特色** — AI 也会遗忘，不重要的自然淡去
6. **溯源链接** — 每条记忆都能追回原始数据
7. **图片必带时间位置** — 尽量获取，取不到留空
