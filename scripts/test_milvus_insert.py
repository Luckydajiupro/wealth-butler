#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试Milvus插入功能"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.Base.Client.ollamaClient import ollama_client
from app.WealthButler.Repository.faqCollectionModelV2 import FaqCollectionModelV2
import json

# 测试embedding生成
print("测试embedding生成...")
try:
    test_text = "公司全称是什么?"
    embedding = ollama_client.get_embedding(test_text, model="bge-m3")
    print(f"Embedding维度: {len(embedding)}")
    print(f"Embedding示例: {embedding[:5]}...")
except Exception as e:
    print(f"Embedding生成失败: {type(e).__name__}: {e}")
    sys.exit(1)

# 测试Milvus插入
print("\n测试Milvus插入...")
try:
    metadata_dict = {
        'question': '测试问题',
        'answer': '测试答案',
        'meta_id': 999
    }

    insert_data = [{
        'text': '测试问题',
        'metadata': json.dumps(metadata_dict, ensure_ascii=False),
        'embedding': embedding
    }]

    result = FaqCollectionModelV2.insert(insert_data)
    print(f"插入成功，返回结果: {result}")
except Exception as e:
    print(f"插入失败: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
