#!/usr/bin/env python3
"""
清理Milvus集合并重新完整入库
"""
import sys
sys.path.insert(0, 'D:/lqh/金融')

from app.Base.Repository.base.baseVDB import BaseVDBModel
from app.WealthButler.Repository.faqCollectionModelV2 import FaqCollectionModelV2
from app.WealthButler.Repository.productCollectionModelV2 import ProductCollectionModelV2
from app.WealthButler.Repository.policyCollectionModelV2 import PolicyCollectionModelV2

print("=" * 60)
print("清理Milvus集合")
print("=" * 60)

# 删除并重建三个集合
collections = [
    ('FAQ集合', FaqCollectionModelV2),
    ('产品集合', ProductCollectionModelV2),
    ('政策集合', PolicyCollectionModelV2)
]

for name, model in collections:
    try:
        print(f"\n[1] 删除 {name}...")
        collection_name = model.get_collection_name()
        connection = model.get_connection()

        # 删除集合
        if connection.has_collection(collection_name):
            connection.drop_collection(collection_name)
            print(f"    ✓ 已删除集合: {collection_name}")
        else:
            print(f"    - 集合不存在: {collection_name}")

        # 重建集合
        print(f"[2] 重建 {name}...")
        model.create_collection()
        print(f"    ✓ 已重建集合: {collection_name}")

    except Exception as e:
        print(f"    ✗ 错误: {e}")

print("\n" + "=" * 60)
print("清理完成，准备重新入库...")
print("=" * 60)

# 运行完整入库脚本
import subprocess
result = subprocess.run(
    ['python', 'scripts/rag_ingestion_full.py'],
    cwd='D:/lqh/金融',
    capture_output=True,
    text=True
)

print(result.stdout)
if result.stderr:
    print("错误输出:", result.stderr)

print("\n" + "=" * 60)
print("完成")
print("=" * 60)
