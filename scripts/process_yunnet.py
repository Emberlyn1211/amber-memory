#!/usr/bin/env python3
"""
用 yunnet (claude-opus-4-6) 模型处理未处理的源数据
"""
import sys
import os

# 添加 amber-memory 根目录到 Python 路径
amber_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if amber_root not in sys.path:
    sys.path.insert(0, amber_root)

import sqlite3
import json
import time
from datetime import datetime

# 使用绝对导入
from core.context import Context, ContextType
from core.store import MemoryStore
from models.claude_llm import ClaudeLLM

DB_PATH = os.path.expanduser('~/.amber/memory.db')
BATCH_SIZE = 10  # 每批处理 10 条
MAX_BATCHES = None  # None = 全部处理，或设置数字限制批次

def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 统计未处理数量
    cursor.execute("SELECT COUNT(*) FROM sources WHERE processed = 0")
    total_unprocessed = cursor.fetchone()[0]
    print(f"未处理源数据：{total_unprocessed} 条")
    
    if total_unprocessed == 0:
        print("没有未处理的数据")
        return
    
    # 初始化 LLM 和 store
    llm = ClaudeLLM(
        provider='yunnet',
        model='claude-opus-4-6'
    )
    store = MemoryStore(db_path=DB_PATH)
    
    processed_count = 0
    extracted_count = 0
    batch_num = 0
    
    start_time = time.time()
    
    while True:
        # 获取一批未处理的数据
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
            
            try:
                metadata = json.loads(metadata_str) if metadata_str else {}
                
                # 简单提取（直接用 LLM，不走完整的 extractor）
                prompt = f"""从以下对话中提取记忆（人/事/物/偏好/禁忌/目标/模式/思考）：

{raw_content[:2000]}

返回 JSON 数组，每条记忆格式：
{{"type": "person|activity|object|preference|taboo|goal|pattern|thought", "abstract": "一句话摘要", "overview": "详细描述"}}
"""
                
                response = llm.chat([{"role": "user", "content": prompt}])
                
                # 解析并保存记忆
                try:
                    memories_data = json.loads(response)
                    memory_ids = []
                    
                    for mem in memories_data:
                        ctx = Context(
                            uri=f"source:{source_id}/{len(memory_ids)}",
                            context_type=mem.get('type', 'memory'),
                            abstract=mem.get('abstract', ''),
                            overview=mem.get('overview', ''),
                            created_at=created_at,
                            event_time=event_time or created_at
                        )
                        store.add_context(ctx)
                        memory_ids.append(ctx.id)
                        extracted_count += 1
                    
                    # 标记为已处理
                    cursor.execute("""
                        UPDATE sources 
                        SET processed = 1, 
                            process_result = ? 
                        WHERE id = ?
                    """, (json.dumps(memory_ids), source_id))
                    
                except json.JSONDecodeError:
                    # LLM 返回格式不对，标记为已处理但无记忆
                    cursor.execute("""
                        UPDATE sources 
                        SET processed = 1, 
                            process_result = ? 
                        WHERE id = ?
                    """, (json.dumps([]), source_id))
                
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
                # 标记为已处理但记录错误
                cursor.execute("""
                    UPDATE sources 
                    SET processed = 1, 
                        process_result = ? 
                    WHERE id = ?
                """, (json.dumps({"error": str(e)}), source_id))
                processed_count += 1
            
            conn.commit()
    
    elapsed = time.time() - start_time
    print(f"\n=== 完成 ===")
    print(f"处理：{processed_count} 条源数据")
    print(f"提取：{extracted_count} 条记忆")
    print(f"耗时：{elapsed/60:.1f} 分钟")
    print(f"速度：{processed_count/elapsed:.2f} 条/秒")
    
    conn.close()

if __name__ == '__main__':
    main()
