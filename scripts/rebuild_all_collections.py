"""完整的Milvus集合清理和重建脚本

删除所有旧集合，创建统一的三字段Schema（id/text/metadata/embedding）
"""
import sys
import os

# 添加项目根目录到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from app.Base.Client.milvusClient import MilvusClientSingleton
from app.WealthButler.Repository.faqCollectionModelV2 import FaqCollectionModelV2
from app.WealthButler.Repository.productCollectionModelV2 import ProductCollectionModelV2
from app.WealthButler.Repository.policyCollectionModelV2 import PolicyCollectionModelV2

# 获取Milvus客户端实例
milvus_singleton = MilvusClientSingleton()
milvus_client = milvus_singleton.get_client()

print("="*80)
print("Milvus Collection Cleanup and Rebuild")
print("="*80)

print("\n[Step 1] List current collections:")
collections = milvus_client.list_collections()
for collection in collections:
    print(f"  - {collection}")

print("\n[Step 2] Drop old collections...")
# 删除所有需要重建的集合
collections_to_drop = [
    "fin_faq_collection",
    "fin_product_collection",
    "fin_policy_collection",
    "fin_product_collection_v2",
    "fin_policy_collection_v2"
]

for collection in collections_to_drop:
    if collection in collections:
        milvus_client.drop_collection(collection)
        print(f"  [OK] Dropped {collection}")
    else:
        print(f"  [SKIP] {collection} not found")

print("\n[Step 3] Create new collections with unified schema...")
# 创建统一三字段Schema的集合
FaqCollectionModelV2()
print(f"  [OK] Created fin_faq_collection (V2 schema)")

ProductCollectionModelV2()
print(f"  [OK] Created fin_product_collection (V2 schema)")

PolicyCollectionModelV2()
print(f"  [OK] Created fin_policy_collection (V2 schema)")

print("\n[Step 4] Verify new collections:")
new_collections = milvus_client.list_collections()
for collection in new_collections:
    print(f"  - {collection}")

print("\n" + "="*80)
print("[SUCCESS] All collections rebuilt with unified schema!")
print("="*80)
print("\nNext step:")
print("  Run: python scripts/rag_ingestion.py")
print("  This will populate all collections with data")
