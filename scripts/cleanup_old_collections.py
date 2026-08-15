"""查看并清理Milvus集合脚本"""
import sys
import os

# 添加项目根目录到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from app.Base.Client.milvusClient import MilvusClientSingleton

# 获取Milvus客户端实例
milvus_singleton = MilvusClientSingleton()
milvus_client = milvus_singleton.get_client()

print("Current Milvus collections:")
print("="*80)
collections = milvus_client.list_collections()
for collection in collections:
    print(f"  - {collection}")

print("\n" + "="*80)
print("Collections to DELETE (old v1):")
print("  - fin_product_collection")
print("  - fin_policy_collection")
print("\nCollections to RENAME (v2 -> standard):")
print("  - fin_product_collection_v2  -->  fin_product_collection")
print("  - fin_policy_collection_v2   -->  fin_policy_collection")
print("="*80)

# 询问用户确认
confirm = input("\nProceed with cleanup? (yes/no): ")
if confirm.lower() != 'yes':
    print("Cancelled.")
    sys.exit(0)

# 删除旧集合
print("\n[Step 1] Deleting old collections...")
for old_collection in ["fin_product_collection", "fin_policy_collection"]:
    if old_collection in collections:
        milvus_client.drop_collection(old_collection)
        print(f"  [OK] Dropped {old_collection}")
    else:
        print(f"  [SKIP] {old_collection} not found")

print("\n[Step 2] Renaming v2 collections...")
print("  [INFO] Milvus does not support rename, need to recreate")
print("  [TODO] Update Model definitions to use standard names")
print("         - productCollectionModelV2.py: collection_alias = 'fin_product_collection'")
print("         - policyCollectionModelV2.py: collection_alias = 'fin_policy_collection'")
print("  [TODO] Re-run migration script with new Model definitions")

print("\n[DONE] Old collections deleted. Please update Model code and re-migrate.")
