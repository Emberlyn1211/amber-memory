#!/usr/bin/env python3
"""
用 yunnet (claude-opus-4-6) 模型处理未处理的源数据
简化版：直接调用 LLM，不依赖复杂的 extractor
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import json
import time
import requests
from datetime import datetime

DB_PATH = os.path.expanduser('~/.amber/memory.db')
BATCH_SIZE = 10
MAX_BATCHES = None

# yunnet API 配置（改用 Opus 4.6）
API_BASE = "https://ark.cn-beijing.volces.com/api/coding"
API_KEY = "2cad7b32-7bcc-4b36-a545-82bf75eadd8f"
MODEL = "claude-opus-4-6"

# 群聊跳过策略
TIER1_GROUPS = ['十一去哪', '司令部', '总统府']  # 核心圈，当私聊处理
TIER2_GROUPS = ['OpenClaw']  # 高质量群，正常提取
# 其他群默认跳过

def call_llm(prompt):
    """调用 yunnet LLM"""
    response = requests.post(
        f"{API_BASE}/v1/messages",
        headers={
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": MODEL,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}]
        },
        timeout=120
    )
    response.raise_for_status()
    data = response.json()
    # Kimi 返回 content[0]=thinking, content[1]=text
    for item in data["content"]:
        if item.get("type") == "text":
            return item["text"]
    return data["content"][0].get("text", "")

def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM sources WHERE processed = 0")
    total_unprocessed = cursor.fetchone()[0]
    print(f"未处理源数据：{total_unprocessed} 条")
    
    if total_unprocessed == 0:
        print("没有未处理的数据")
        return
    
    processed_count = 0
    extracted_count = 0
    batch_num = 0
    start_time = time.time()
    
    while True:
        cursor.execute("""
            SELECT id, type, origin, raw_content, metadata, created_at, event_time
            FROM sources 
            WHERE processed = 0 
            ORDER BY created_at ASC 
            LIMIT ?
        """, (BATCH_SIZE,))
        
        batch = cursor.fetchall()
        if not batch:
            break
        
        batch_num += 1
        if MAX_BATCHES and batch_num > MAX_BATCHES:
            print(f"达到最大批次限制 {MAX_BATCHES}，停止处理")
            break
        
        print(f"\n=== 批次 {batch_num} ({len(batch)} 条) ===")
        
        for row in batch:
            source_id, source_type, origin, raw_content, metadata_str, created_at, event_time = row
            print(f"处理 {source_id}...", flush=True)
            
            # 群聊跳过策略
            if source_type == 'chat' and origin.startswith('wechat:'):
                # 解析群名（从 metadata 或 raw_content）
                try:
                    metadata = json.loads(metadata_str) if metadata_str else {}
                    chat_name = metadata.get('chat_name', '')
                    
                    # 判断是否跳过
                    is_tier1 = any(g in chat_name for g in TIER1_GROUPS)
                    is_tier2 = any(g in chat_name for g in TIER2_GROUPS)
                    is_private = not chat_name or '@chatroom' not in origin
                    
                    if not (is_tier1 or is_tier2 or is_private):
                        # 跳过垃圾群
                        cursor.execute("""
                            UPDATE sources 
                            SET processed = 1, process_result = ? 
                            WHERE id = ?
                        """, (json.dumps({"skipped": "tier0_group"}), source_id))
                        processed_count += 1
                        conn.commit()
                        continue
                except:
                    pass  # 解析失败就正常处理
            
            try:
                # 使用完整的提取 prompt
                prompt = f"""分析以下对话，提取值得长期保存的记忆。

我们的用户叫 Frankie。以下所有记忆都是关于 Frankie 的。

## ⚠️ 身份识别规则（最重要！）

对话格式：`[时间] 发言人: 内容`

- 「我:」开头的消息 = **Frankie 本人说的**
- 其他任何名字开头的消息 = **对方说的，不是 Frankie**

### Frankie 的别名（全部是同一个人！）
以下名字全部指 Frankie 本人，不要为它们创建 person 条目：
- 张哲（真名）、子扬（网名）、黑（发小们的称呼）、阿哲（朋友的称呼）
- 「我:」开头的所有消息

### 不是人名的群名/昵称（绝对不要为它们创建 person 条目！）
- "十一去哪"、"十一去哪儿" = 发小群的群名
- "司令部"、"总统府" = 群聊名称

## 提取标准

### 值得记住的
- ✅ 个性化信息：专属于 Frankie 的，不是通用知识
- ✅ 长期有效：未来还会用到
- ✅ 具体明确：有细节，不是模糊概括

### 不值得记住的
- ❌ 通用知识
- ❌ 临时信息：一次性问答
- ❌ 群里别人的事：和 Frankie 无直接关系
- ❌ 群公告/广告/促销
- ❌ **对方的自我介绍当成 Frankie 的**
- ❌ **隐私信息**：地址、身份证号、银行卡号
- ❌ **群分享的网盘链接/资料**：不是 Frankie 的东西

## 维度定义

**person** - 人物（只提取重要关系）
- ✅ 家人、朋友、同事、合作伙伴
- ❌ 一次性服务人员（维修师傅、客服、销售）
- ❌ 群里不认识的人
- ❌ 只是加了微信但没互动的人
- 描述格式："XX 是 Frankie 的..."

**activity** - 事件（发生过的事）
- Frankie 做了什么、完成了什么、发生了什么
- 一次性服务归这里（"找维修师傅修了燃气灶"）

**object** - 实体物品（只提取 Frankie 拥有的）
- ✅ Frankie 的宠物、电脑、家具、车
- ❌ 群里别人分享的资料/链接
- ❌ 只是聊到但不拥有的东西

**place** - 地点
- Frankie 的居住地、工作地、常去的地方

**preference** - 偏好
- Frankie 的倾向性选择、习惯

**taboo** - 禁忌
- 不能提的话题、不想见的人

**goal** - 目标
- Frankie 想达成的事

**pattern** - 模式
- Frankie 的行为规律、处理问题的方法

**thought** - 思考
- Frankie 的想法、感悟

## 最近对话
{raw_content[:2000]}

返回 JSON:
{{
  "memories": [
    {{
      "type": "person|activity|object|place|preference|taboo|goal|pattern|thought",
      "abstract": "一句话摘要",
      "overview": "详细描述"
    }}
  ]
}}

注意：
- 没有值得记录的就返回 {{"memories": []}}
- person 只提取重要关系，不要提取服务人员/陌生人
- object 只提取 Frankie 拥有的东西，不要提取群分享的链接
- 对方的职业/经历是对方的，不是 Frankie 的
"""
                
                response = call_llm(prompt)
                
                # 解析并保存记忆到 contexts 表
                try:
                    result = json.loads(response)
                    memories_data = result.get("memories", [])
                    memory_ids = []
                    
                    for i, mem in enumerate(memories_data):
                        ctx_id = f"{source_id}_{i}"
                        ctx_uri = f"/source/{source_id}/{i}"
                        
                        # 数据库写入重试（最多3次）
                        for retry in range(3):
                            try:
                                cursor.execute("""
                                    INSERT INTO contexts (
                                        id, uri, context_type, abstract, overview, 
                                        created_at, updated_at, last_accessed, event_time
                                    )
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    ctx_id,
                                    ctx_uri,
                                    mem.get('type', 'memory'),
                                    mem.get('abstract', ''),
                                    mem.get('overview', ''),
                                    created_at,
                                    created_at,
                                    created_at,
                                    event_time or created_at
                                ))
                                memory_ids.append(ctx_id)
                                extracted_count += 1
                                break
                            except sqlite3.OperationalError as db_err:
                                if 'locked' in str(db_err) and retry < 2:
                                    time.sleep(0.5)
                                    continue
                                raise
                    
                    # UPDATE 也加重试
                    for retry in range(3):
                        try:
                            cursor.execute("""
                                UPDATE sources 
                                SET processed = 1, process_result = ? 
                                WHERE id = ?
                            """, (json.dumps(memory_ids), source_id))
                            break
                        except sqlite3.OperationalError as db_err:
                            if 'locked' in str(db_err) and retry < 2:
                                time.sleep(0.5)
                                continue
                            raise
                    
                except (json.JSONDecodeError, KeyError):
                    for retry in range(3):
                        try:
                            cursor.execute("""
                                UPDATE sources 
                                SET processed = 1, process_result = ? 
                                WHERE id = ?
                            """, (json.dumps([]), source_id))
                            break
                        except sqlite3.OperationalError as db_err:
                            if 'locked' in str(db_err) and retry < 2:
                                time.sleep(0.5)
                                continue
                            raise
                
                processed_count += 1
                
                if processed_count % 10 == 0:
                    elapsed = time.time() - start_time
                    rate = processed_count / elapsed
                    remaining = (total_unprocessed - processed_count) / rate if rate > 0 else 0
                    print(f"进度：{processed_count}/{total_unprocessed} ({processed_count/total_unprocessed*100:.1f}%) | "
                          f"提取：{extracted_count} 条记忆 | "
                          f"速度：{rate:.2f} 条/秒 | "
                          f"预计剩余：{remaining/60:.1f} 分钟")
                
            except Exception as e:
                print(f"处理失败 {source_id}: {e}")
                # 标记失败也加重试
                for retry in range(3):
                    try:
                        cursor.execute("""
                            UPDATE sources 
                            SET processed = 1, process_result = ? 
                            WHERE id = ?
                        """, (json.dumps({"error": str(e)}), source_id))
                        break
                    except sqlite3.OperationalError as db_err:
                        if 'locked' in str(db_err) and retry < 2:
                            time.sleep(0.5)
                            continue
                        print(f"标记失败也失败了: {db_err}")
                processed_count += 1
            
            # commit 也加重试
            for retry in range(3):
                try:
                    conn.commit()
                    break
                except sqlite3.OperationalError as db_err:
                    if 'locked' in str(db_err) and retry < 2:
                        time.sleep(0.5)
                        continue
                    print(f"commit 失败: {db_err}")
    
    elapsed = time.time() - start_time
    print(f"\n=== 完成 ===")
    print(f"处理：{processed_count} 条源数据")
    print(f"提取：{extracted_count} 条记忆")
    print(f"耗时：{elapsed/60:.1f} 分钟")
    print(f"速度：{processed_count/elapsed:.2f} 条/秒")
    
    conn.close()

if __name__ == '__main__':
    main()
