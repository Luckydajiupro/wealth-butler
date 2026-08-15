"""删除V2集合脚本（重新开始迁移前使用）"""
import sys
import os

# 添加项目根目录到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from app.Base.Client.milvusClient import MilvusClientSingleton

# 获取Milvus客户端实例
milvus_singleton = MilvusClientSingleton()
milvus_client = milvus_singleton.get_client()

print("Dropping V2 collections...")

# 删除产品集合V2
if "fin_product_collection_v2" in milvus_client.list_collections():
    milvus_client.drop_collection("fin_product_collection_v2")
    print("[OK] Dropped fin_product_collection_v2")
else:
    print("[SKIP] fin_product_collection_v2 not found")

# 删除政策集合V2
if "fin_policy_collection_v2" in milvus_client.list_collections():
    milvus_client.drop_collection("fin_policy_collection_v2")
    print("[OK] Dropped fin_policy_collection_v2")
else:
    print("[SKIP] fin_policy_collection_v2 not found")

print("\nDone! Now you can run migrate_to_v2_collections_simple.py")
