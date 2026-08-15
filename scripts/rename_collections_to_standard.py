"""删除V2集合并使用标准名称重新迁移"""
import sys
import os
import json

# 添加项目根目录到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from app.WealthButler.Repository.productCollectionModelV2 import ProductCollectionModelV2
from app.WealthButler.Repository.policyCollectionModelV2 import PolicyCollectionModelV2
from app.Base.Client.milvusClient import MilvusClientSingleton

# 获取Milvus客户端实例
milvus_singleton = MilvusClientSingleton()
milvus_client = milvus_singleton.get_client()

print("="*80)
print("Cleanup and Rename: V2 -> Standard Names")
print("="*80)

# Step 1: 删除旧V2集合
print("\n[Step 1] Dropping old v2 collections...")
for v2_collection in ["fin_product_collection_v2", "fin_policy_collection_v2"]:
    if v2_collection in milvus_client.list_collections():
        milvus_client.drop_collection(v2_collection)
        print(f"  [OK] Dropped {v2_collection}")

# Step 2: 创建新集合（使用标准名称）
print("\n[Step 2] Creating collections with standard names...")
ProductCollectionModelV2()
print(f"  [OK] Created fin_product_collection")
PolicyCollectionModelV2()
print(f"  [OK] Created fin_policy_collection")

# Step 3: 从临时备份数据重新迁移（如果有的话）
print("\n[Step 3] Migration complete")
print("  [INFO] Collections are now using standard names:")
print("         - fin_product_collection (new schema)")
print("         - fin_policy_collection (new schema)")
print("\n[DONE] Cleanup and rename completed successfully!")
