#!/usr/bin/env python3
"""
批量处理未处理的源数据
用 Opus 提取记忆，直接写入 contexts 表
"""

import sqlite3
import json
import os
import time
from datetime import datetime

DB_PATH = os.path.expanduser('~/.amber/memory.db')

def call_llm(prompt):
    """调用 LLM（通过 OpenClaw）"""
    import subprocess
    import tempfile
    
    # 写 prompt 到临时文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(prompt)
        prompt_file = f.name
    
    try:
        # 调用 openclaw（假设有 agent 命令）
        # 这里简化：直接返回空，实际需要调 API
        result = subprocess.run(
            ['openclaw', 'agent', '--agent', 'main', '--message', f'cat {prompt_file}'],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.stdout
    except Exception as e:
        print(f'LLM 调用失败: {e}')
        return '[]'
    finally:
        os.unlink(prompt_file)

def extract_memories_from_chat(raw_content, metadata):
    """从聊天记录提取记忆"""
    
    # 构建 prompt
    prompt = f"""从以下微信对话中提取记忆。

对话内容：
{raw_content[:2000]}

提取规则：
1. 提取人物（person）、活动（activity）、偏好（preference）、承诺（goal）
2. 每条记忆一句话摘要
3. 重要性 0-1（普通聊天 0.3，重要事件 0.8）
4. 返回 JSON 数组

格式：
[
  {{"category": "person", "abstract": "张三是我的同事", "importance": 0.5}},
  {{"category": "activity", "abstract": "2022年2月去了北京", "importance": 0.6}}
]

只返回 JSON，不要其他文字。如果没有值得记录的内容，返回 []
"""
    
    # 调用 LLM
    result = call_llm(prompt)
    
    try:
        memories = json.loads(result)
        return memories if isinstance(memories, list) else []
    except:
        return []

def process_batch(limit=100):
    """处理一批未处理的源"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 拿未处理的 chat
    cursor.execute('''
    SELECT id, raw_content, metadata, event_time, origin
    FROM sources
    WHERE processed = 0 AND type = 'chat'
    ORDER BY event_time DESC
    LIMIT ?
    ''', (limit,))
    
    sources = cursor.fetchall()
    print(f'\\n拿到 {len(sources)} 条未处理源')
    
    processed_count = 0
    memory_count = 0
    
    for source_id, raw_content, metadata_str, event_time, origin in sources:
        try:
            metadata = json.loads(metadata_str) if metadata_str else {}
            
            # 提取记忆
            memories = extract_memories_from_chat(raw_content, metadata)
            
            # 写入 contexts 表
            for mem in memories:
                category = mem.get('category', 'activity')
                abstract = mem.get('abstract', '')
                importance = mem.get('importance', 0.5)
                
                if not abstract:
                    continue
                
                # 生成 URI
                uri = f"memory:{category}:{int(time.time() * 1000)}"
                
                # 插入
                cursor.execute('''
                INSERT INTO contexts (
                    id, uri, abstract, context_type, category, 
                    importance, created_at, updated_at, last_accessed,
                    event_time, source_session, meta
                ) VALUES (?, ?, ?, 'memory', ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    uri, uri, abstract, category,
                    importance, time.time(), time.time(), time.time(),
                    event_time, origin, json.dumps(metadata)
                ))
                
                memory_count += 1
            
            # 标记源为已处理
            cursor.execute('''
            UPDATE sources
            SET processed = 1, process_result = ?
            WHERE id = ?
            ''', (json.dumps(memories), source_id))
            
            processed_count += 1
            
            if processed_count % 10 == 0:
                print(f'已处理 {processed_count} 条源，提取 {memory_count} 条记忆')
                conn.commit()
            
            # 避免 API 限流
            time.sleep(0.5)
                
        except Exception as e:
            print(f'处理失败 {source_id}: {e}')
            continue
    
    conn.commit()
    conn.close()
    
    print(f'\\n完成！处理了 {processed_count} 条源，提取了 {memory_count} 条记忆')
    return processed_count, memory_count

if __name__ == '__main__':
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    
    print(f'开始处理 {limit} 条未处理源...')
    print(f'数据库：{DB_PATH}')
    
    process_batch(limit)
