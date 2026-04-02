# Amber Memory 改进方案 v1

*起草：Amber*
*日期：2026-04-01*

## 核心目标

不是"提取更多"，而是"让进入正式记忆的东西更稳、更可校正、更可整理"。

---

## 四层架构

```
Source Layer
  原始聊天/日记/图片/链接/语音/微信数据库
  ↓
Candidate Layer
  LLM提取候选，带证据、置信度、归因
  ↓
Canonical Layer
  正式长期记忆（已校验、去重、合并）
  ↓
Narrative Layer
  MEMORY.md / 摘要 / prompt capsules
```

---

## 最优先改进项

### 1. Candidate Layer（最高优先级）
- 新增 `candidate_memories` 表
- 提取器只写这里，不直接污染正式库
- 字段：evidence_quote, source_span, confidence, speaker_id

### 2. Validation Layer
- 群聊 speaker 校验
- 时间规范化（相对日期转绝对）
- taboo 拦截
- 冲突检测

### 3. Consolidation/Dream Layer
- 每日/每两日运行
- 合并 alias、重复记忆
- 修正过时结论
- 刷新 MEMORY.md

### 4. Person Entity Resolution
- 新增 `people` 表
- canonical_name + aliases
- 所有人物记忆挂 person_id

---

## 两周 MVP

### Week 1
- [ ] 建 `candidate_memories` 表
- [ ] 提取器改写入 candidate
- [ ] 加 evidence_quote / source_span
- [ ] 加规则校验器 v1（speaker/时间/taboo）
- [ ] 加 valid_from / valid_to

### Week 2
- [ ] 最小 consolidation job
- [ ] 检索结果带 confidence/source_count
- [ ] 微信增量 pipeline 命令

---

## 微信流程

见独立文档：`WECHAT-MEMORY-RUNBOOK.md`

---

## 关键数据结构

### canonical contexts 新增字段
- confidence
- source_count
- last_verified_at
- valid_from / valid_to
- stability (stable/drifting/conflicting)
- person_id / place_id
- conflict_group_id

### candidate_memories 表
见上文。

### people 表
- person_id
- canonical_name
- aliases_json
- source_names_json
- relation_to_frankie
- confidence
- taboo_level

---

## 要避免的坑

1. 不要把所有提取结果直接入正式库
2. 不要把 schema 再越搞越多，先把边界钉死
3. 不要只加 embedding，不补验证层
4. 不要把 MEMORY.md 当原始事实库
5. 不要让 taboo 只做检索过滤
