#!/usr/bin/env python3
"""
RAG 测试脚本：把当前记忆向量化，测试语义检索
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import numpy as np
from sentence_transformers import SentenceTransformer
from typing import List, Tuple
import time

DB_PATH = os.path.expanduser('~/.amber/memory.db')

class SimpleRAG:
    def __init__(self, model_name='BAAI/bge-small-zh-v1.5'):
        print(f"加载模型 {model_name}...")
        self.model = SentenceTransformer(model_name)
        self.embeddings = []
        self.texts = []
        self.ids = []
        
    def load_memories(self):
        """从 SQLite 加载记忆"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, context_type, abstract, overview 
            FROM contexts 
            ORDER BY created_at DESC
        """)
        
        rows = cursor.fetchall()
        print(f"加载了 {len(rows)} 条记忆")
        
        for row in rows:
            ctx_id, ctx_type, abstract, overview = row
            # 合并 abstract 和 overview 作为检索文本
            text = f"{abstract}\n{overview}"
            self.texts.append(text)
            self.ids.append(ctx_id)
        
        conn.close()
        
    def build_index(self):
        """构建向量索引"""
        print(f"正在向量化 {len(self.texts)} 条记忆...")
        start = time.time()
        
        # 批量编码
        self.embeddings = self.model.encode(
            self.texts,
            batch_size=32,
            show_progress_bar=True,
            convert_to_numpy=True
        )
        
        elapsed = time.time() - start
        print(f"✅ 向量化完成，耗时 {elapsed:.2f} 秒")
        print(f"向量维度: {self.embeddings.shape}")
        
    def search(self, query: str, top_k: int = 5) -> List[Tuple[str, float, str]]:
        """语义搜索"""
        # 查询向量化
        query_embedding = self.model.encode([query], convert_to_numpy=True)[0]
        
        # 计算余弦相似度
        similarities = np.dot(self.embeddings, query_embedding) / (
            np.linalg.norm(self.embeddings, axis=1) * np.linalg.norm(query_embedding)
        )
        
        # 排序
        top_indices = np.argsort(similarities)[::-1][:top_k]
        
        results = []
        for idx in top_indices:
            results.append((
                self.ids[idx],
                float(similarities[idx]),
                self.texts[idx][:200]  # 只返回前 200 字符
            ))
        
        return results

def main():
    # 初始化
    rag = SimpleRAG()
    
    # 加载记忆
    rag.load_memories()
    
    if len(rag.texts) == 0:
        print("没有记忆数据")
        return
    
    # 构建索引
    rag.build_index()
    
    # 测试查询
    test_queries = [
        "Frankie 的家人有哪些？",
        "关于木马的记忆",
        "Watchlace 项目",
        "记忆提取系统",
    ]
    
    print("\n" + "="*60)
    print("测试语义检索")
    print("="*60)
    
    for query in test_queries:
        print(f"\n查询: {query}")
        print("-" * 60)
        
        start = time.time()
        results = rag.search(query, top_k=3)
        elapsed = time.time() - start
        
        for i, (ctx_id, score, text) in enumerate(results, 1):
            print(f"\n{i}. 相似度: {score:.4f}")
            print(f"   ID: {ctx_id}")
            print(f"   内容: {text}")
        
        print(f"\n查询耗时: {elapsed*1000:.2f} ms")

if __name__ == '__main__':
    main()
