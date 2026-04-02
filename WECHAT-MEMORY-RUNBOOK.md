# WeChat 记忆运行手册

*最后更新：2026-04-01*

---

## 一句话

微信数据库 → 解密 → 读取 → 提取候选 → 校验 → 去重 → 正式记忆

---

## 关键文件位置速查

### 原始数据（系统目录）
| 用途 | 路径 |
|------|------|
| 微信加密数据库 | `~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/<wxid>/db_storage/` |
| 文件缓存 | `~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/<wxid>/msg/file/<YYYY-MM>/` |
| Master Key | `~/.wechat_key` |

### 工作区脚本
| 用途 | 路径 |
|------|------|
| 解密脚本 | `wechat-bridge/decrypt_all.py` |
| 底层读取 | `wechat-bridge/reader.py` |
| 演示/调试 | `wechat-bridge/demo.py` |
| 消息监听 | `wechat-bridge/listener/listener_v2.py` |
| 批量提取 | `wechat-bridge/extract_batch.py` |
| 导入记忆 | `wechat-bridge/ingest_wechat.py` |
| 去重 | `wechat-bridge/dedup.py` |
| 朋友圈导入 | `wechat-bridge/import_moments.py` |
| amber-memory 接口 | `amber-memory/sources/wechat.py` |

### 中间产物
| 用途 | 路径 |
|------|------|
| 解密后数据库 | `/tmp/wechat_decrypted/` |
| 提取日志 | `wechat-bridge/logs/extract_*.log` |
| 进度记录 | `memory/wechat-decrypt-progress.md` |
| 逆向笔记 | `memory/wechat-reverse-engineering.md` |

---

## 标准运行流程

### 第一步：检查密钥
```bash
cat ~/.wechat_key
```
如果没有，需要重新用 Frida 提取（见下方）。

### 第二步：解密数据库
```bash
cd ~/clawd/workspace/wechat-bridge
python3 decrypt_all.py
```
输出：`/tmp/wechat_decrypted/`

### 第三步：验证读取
```bash
python3 demo.py
# 或指定联系人
python3 demo.py ziyang6372
```

### 第四步：批量提取到候选层
```bash
python3 extract_batch.py
```
输出到 `candidate_memories` 表（新架构）或中间文件。

### 第五步：校验与去重
```bash
python3 dedup.py
```

### 第六步：进入正式记忆
```bash
# 通过 amber-memory 接口
python3 ~/clawd/workspace/amber-memory/sources/wechat.py
```

---

## 定期维护节奏

| 频率 | 操作 |
|------|------|
| 每日 | 检查微信 DB 更新 → 增量解密 → 增量提取 → candidate |
| 每 2-3 日 | 跑校验 → 去重 → accepted 入 canonical |
| 每周 | 跑 Dream/consolidation → 合并 alias → 刷新摘要 |
| 每月 | 全量体检 → 冲突处理 → 抽样验收 |

---

## 常见问题

### Q: Master Key 失效了怎么办？
重新用 Frida 提取：
```bash
~/.local/bin/frida -n WeChat -l frida/dump_key_v3.js
```

### Q: 解密后的 DB 在哪？
`/tmp/wechat_decrypted/`

### Q: 朋友圈数据在哪？
解密后的 `sns.db`，用 `import_moments.py` 导入。

### Q: 日志在哪看？
`wechat-bridge/logs/`

---

## 相关历史文档

- `memory/wechat-decrypt-progress.md` — 解密过程记录
- `memory/wechat-reverse-engineering.md` — 逆向分析
- `wechat-bridge/README.md` — 架构说明
- `amber-memory/IMPROVEMENT-PLAN-v1.md` — 整体改进方案
