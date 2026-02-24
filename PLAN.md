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
- [ ] 照片语义（豆包图像识别 → 场景描述 → 源层 image → 记忆层"事"）
- [ ] Watchlace 内部日程读取（API → 源层 schedule）
- [ ] 位置数据（照片 EXIF + GPS → 源层 location）
- [ ] Bear Notes 导入（读 SQLite → 源层 text → 记忆层"思考"）
- [ ] 微信换号支持（新 Frida + 自动检测 wxid）
- [ ] 链接/文章处理（URL → 抓取 → 源层 link）
- [ ] 语音处理（讯飞 STT → 源层 voice）

### Phase 3 — 智能层
- [ ] 豆包 embedding 语义搜索
- [ ] LLM 自动提取（对话 → 人/事/物/偏好/禁忌/目标/模式/思考）
- [ ] 人物图谱（entity + 关系网络 + 互动历史聚合）
- [ ] 模式识别引擎（历史数据 → 行为规律）
- [ ] "生活提案"触发器（共情+证据+行动+确认）

### Phase 4 — Watchlace 智能层（非记忆，独立开发）
- [ ] 高德 API 接入（路线规划/出发时间/堵车预估）
- [ ] 日程智能提醒（记忆层位置+模式 + 高德路线 → 提前提醒）
- [ ] 日程对账（照片语义 vs 日程计划，自动比对）
- [ ] 人格滑杆系统（Warmth/Playfulness/Banter/Formality/Pushiness/Chattiness）
- [ ] 漫画生成（照片 → 商业插画风格日报）

### Phase 5 — 集成
- [ ] OpenClaw 集成（新 session 自动加载上下文）
- [ ] 反向导出 MEMORY.md
- [ ] Watchlace API 对接（记忆系统作为后端服务）

---

## 设计原则

1. **源层永远不动** — 原始数据是 truth，只读不改
2. **记忆层可重建** — 源层完好就能重新导入
3. **透明可控** — 用户能看到记了什么、为什么记、一键删除
4. **禁忌优先** — 敏感内容不自动处理，需确认
5. **衰减是特色** — AI 也会遗忘，不重要的自然淡去
6. **溯源链接** — 每条记忆都能追回原始数据
7. **图片必带时间位置** — 尽量获取，取不到留空
