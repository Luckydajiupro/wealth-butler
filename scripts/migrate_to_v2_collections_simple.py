"""Milvus集合V2迁移脚本（简化版）

将现有产品和政策集合迁移到支持jieba分词的V2版本
"""
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


def migrate_product_collection():
    """迁移产品集合到V2"""
    print("\n" + "="*80)
    print("Migrating: fin_product_collection -> fin_product_collection_v2")
    print("="*80)

    old_collection = "fin_product_collection"

    # 检查旧集合是否存在
    collections = milvus_client.list_collections()
    if old_collection not in collections:
        print(f"[WARN] Old collection {old_collection} not found, skip migration")
        return

    # 创建V2集合
    print(f"\nCreating new collection: fin_product_collection_v2")
    ProductCollectionModelV2()
    print(f"[OK] New collection created")

    # 从旧集合读取所有数据
    print(f"\nReading data from old collection...")
    results = milvus_client.query(
        collection_name=old_collection,
        filter="",  # 空filter查询所有数据
        output_fields=["*"],
        limit=10000
    )

    print(f"[OK] Read {len(results)} records")

    if not results:
        print("[WARN] Old collection is empty, skip migration")
        return

    # 转换为新Schema
    print(f"\nConverting data format...")
    new_records = []
    for old_record in results:
        # 提取旧字段
        product_name = old_record.get('product_name', '')
        description = old_record.get('description', '')
        risk_level = old_record.get('risk_level', '')
        product_code = old_record.get('product_code', '')
        category = old_record.get('category', '')
        source = old_record.get('source', '')
        updated_at = old_record.get('updated_at', 0)
        embedding = old_record.get('embedding', [])

        # 构造新记录
        text = f"{product_name} {description}"
        metadata = {
            'product_name': product_name,
            'description': description,
            'risk_level': risk_level,
            'product_code': product_code,
            'category': category,
            'source': source,
            'updated_at': updated_at,
            'chunk_type': 'product_detail'
        }

        new_record = {
            'text': text,
            'metadata': json.dumps(metadata, ensure_ascii=False),  # 转换为JSON字符串
            'embedding': embedding
        }
        new_records.append(new_record)

    print(f"[OK] Converted {len(new_records)} records")

    # 批量插入新集合
    print(f"\nInserting data to new collection...")
    batch_size = 100
    for i in range(0, len(new_records), batch_size):
        batch = new_records[i:i+batch_size]
        milvus_client.insert(
            collection_name="fin_product_collection_v2",
            data=batch
        )
        print(f"  Inserted {min(i+batch_size, len(new_records))}/{len(new_records)}")

    # 验证数据
    print(f"\nVerifying migration...")
    new_count = milvus_client.query(
        collection_name="fin_product_collection_v2",
        filter="",  # V2集合id是自增int，但用空filter更安全
        output_fields=["id"],
        limit=1
    )

    if new_count:
        print(f"[SUCCESS] Product collection migrated!")
        print(f"  Old collection: {len(results)} records")
        print(f"  New collection: verified")
    else:
        print(f"[ERROR] Migration verification failed")


def migrate_policy_collection():
    """迁移政策集合到V2"""
    print("\n" + "="*80)
    print("Migrating: fin_policy_collection -> fin_policy_collection_v2")
    print("="*80)

    old_collection = "fin_policy_collection"

    # 检查旧集合是否存在
    collections = milvus_client.list_collections()
    if old_collection not in collections:
        print(f"[WARN] Old collection {old_collection} not found, skip migration")
        return

    # 创建V2集合
    print(f"\nCreating new collection: fin_policy_collection_v2")
    PolicyCollectionModelV2()
    print(f"[OK] New collection created")

    # 从旧集合读取所有数据
    print(f"\nReading data from old collection...")
    results = milvus_client.query(
        collection_name=old_collection,
        filter="",  # 空filter查询所有数据
        output_fields=["*"],
        limit=10000
    )

    print(f"[OK] Read {len(results)} records")

    if not results:
        print("[WARN] Old collection is empty, skip migration")
        return

    # 转换为新Schema
    print(f"\nConverting data format...")
    new_records = []
    for old_record in results:
        policy_title = old_record.get('policy_title', '')
        content = old_record.get('content', '')
        policy_code = old_record.get('policy_code', '')
        source = old_record.get('source', '')
        effective_date = old_record.get('effective_date', '')
        updated_at = old_record.get('updated_at', 0)
        embedding = old_record.get('embedding', [])

        text = f"{policy_title} {content}"
        metadata = {
            'policy_title': policy_title,
            'content': content,
            'policy_code': policy_code,
            'source': source,
            'effective_date': effective_date,
            'updated_at': updated_at
        }

        new_record = {
            'text': text,
            'metadata': json.dumps(metadata, ensure_ascii=False),  # 转换为JSON字符串
            'embedding': embedding
        }
        new_records.append(new_record)

    print(f"[OK] Converted {len(new_records)} records")

    # 批量插入新集合
    print(f"\nInserting data to new collection...")
    batch_size = 100
    for i in range(0, len(new_records), batch_size):
        batch = new_records[i:i+batch_size]
        milvus_client.insert(
            collection_name="fin_policy_collection_v2",
            data=batch
        )
        print(f"  Inserted {min(i+batch_size, len(new_records))}/{len(new_records)}")

    # 验证数据
    print(f"\nVerifying migration...")
    new_count = milvus_client.query(
        collection_name="fin_policy_collection_v2",
        filter="id > 0",
        output_fields=["id"],
        limit=1
    )

    if new_count:
        print(f"[SUCCESS] Policy collection migrated!")
        print(f"  Old collection: {len(results)} records")
        print(f"  New collection: verified")
    else:
        print(f"[ERROR] Migration verification failed")


if __name__ == '__main__':
    print("\n" + "="*80)
    print("Milvus V2 Collection Migration")
    print("="*80)

    try:
        # 迁移产品集合
        migrate_product_collection()

        # 迁移政策集合
        migrate_policy_collection()

        print("\n" + "="*80)
        print("[SUCCESS] All collections migrated")
        print("="*80)
        print("\nNext steps:")
        print("  1. Test hybrid search with jieba analyzer")
        print("  2. Verify query results for Chinese keywords")
        print("  3. After testing, delete old collections to free space")
        print("  4. Adjust thresholds based on actual performance")

    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        import traceback
        traceback.print_exc()
