# Amber Memory System - Changelog

## 2026-03-06

### 修正 importance 误标
- **person_fan_qiuying**: 1.0 → 0.8（重要家人，不是禁忌）
- **person_frankie_zhangzhe**: 1.0 → 0.9（核心信息，不是禁忌）
- 现在只有 2 条真正的禁忌（木马 + 不催睡觉）

### Watchlace 集成 Phase 1 完成
- 新增 amber_memory.py API 路由
- 实现 /api/memory/recall（语义搜索）
- 实现 /api/memory/top（最重要记忆）
- 实现 /api/memory/fading（即将遗忘）
- 实现 /api/memory/stats（统计信息）
- 禁忌系统测试通过
- 半衰期算法验证通过
- 向量化率 92.4%（8672/9386）

## 统计信息

- **总记忆数**: 9,386 条
- **向量化**: 8,672 条（92.4%）
- **禁忌**: 2 条
- **数据库大小**: 583MB
- **数据库位置**: ~/.amber/memory.db

## 数据分布

| 类别 | 数量 |
|------|------|
| activity | 4,829 |
| person | 890 |
| object | 782 |
| pattern | 739 |
| preference | 737 |
| place | 734 |
| thought | 355 |
| goal | 318 |
| taboo | 2 |
