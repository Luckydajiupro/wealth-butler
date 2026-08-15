"""数据重新迁移到标准名称集合"""
import sys
import os
import json

# 添加项目根目录到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from app.Base.Client.milvusClient import MilvusClientSingleton

# 获取Milvus客户端实例
milvus_singleton = MilvusClientSingleton()
milvus_client = milvus_singleton.get_client()

print("="*80)
print("Re-import RAG data to standard collections")
print("="*80)

print("\n[INFO] Current collections:")
for collection in milvus_client.list_collections():
    print(f"  - {collection}")

print("\n[INFO] Data migration needed:")
print("  The new collections (fin_product_collection, fin_policy_collection)")
print("  are currently empty. Please run the RAG ingestion scripts:")
print("")
print("  python scripts/rag_ingestion.py")
print("")
print("  This will populate the collections with fresh data using the new schema.")
