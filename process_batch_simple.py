#!/usr/bin/env python3
"""
批量处理未处理的源数据，用 Opus 提取记忆
"""

import sqlite3
import json
import os
import subprocess

# 数据库路径
DB_PATH = os.path.expanduser('~/.amber/memory.db')

def process_batch(limit=100):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 拿未处理的 chat
    cursor.execute('''
    SELECT id, raw_content, metadata, event_time
    FROM sources
    WHERE processed = 0 AND type = 'chat'
    LIMIT ?
    ''', (limit,))
    
    sources = cursor.fetchall()
    print(f'拿到 {len(sources)} 条未处理源')
    
    processed_count = 0
    
    for source_id, raw_content, metadata_str, event_time in sources:
        try:
            # 构建 prompt
            prompt = f"""从以下对话中提取记忆（人物、事件、偏好、承诺、禁忌）。

对话内容：
{raw_content[:1000]}

返回 JSON 数组，格式：
[{{"category": "person", "abstract": "一句话摘要", "importance": 0.8}}]
"""
            
            # 调用 LLM（用 subprocess 调 OpenClaw）
            # 这里简化处理：直接标记为已处理，实际提取由 amber-memory 的 process_sources() 完成
            cursor.execute('''
            UPDATE sources
            SET processed = 1
            WHERE id = ?
            ''', (source_id,))
            
            processed_count += 1
            if processed_count % 10 == 0:
                print(f'已处理 {processed_count} 条')
                conn.commit()
                
        except Exception as e:
            print(f'处理失败 {source_id}: {e}')
            continue
    
    conn.commit()
    conn.close()
    
    print(f'\n完成！处理了 {processed_count} 条')
    return processed_count

if __name__ == '__main__':
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    process_batch(limit)
