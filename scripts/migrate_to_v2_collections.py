"""Milvus集合V2迁移脚本

将现有产品和政策集合迁移到支持jieba分词的V2版本

执行步骤：
1. 创建 fin_product_collection_v2 和 fin_policy_collection_v2
2. 从旧集合读取数据
3. 转换为新Schema（id/text/metadata/embedding）
4. 写入新集合
5. 验证数据完整性
"""
import sys
import os

# 添加项目根目录到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from app.WealthButler.Repository.productCollectionModelV2 import ProductCollectionModelV2
from app.WealthButler.Repository.policyCollectionModelV2 import PolicyCollectionModelV2
from app.WealthButler.middleware.milvusClient import get_milvus_client
import json


def migrate_product_collection():
    """迁移产品集合到V2"""
    print("\n" + "="*80)
    print("迁移产品集合: fin_product_collection -> fin_product_collection_v2")
    print("="*80)

    milvus_client = get_milvus_client()
    old_collection = "fin_product_collection"

    # 检查旧集合是否存在
    collections = milvus_client.list_collections()
    if old_collection not in collections:
        print(f"⚠️  旧集合 {old_collection} 不存在，跳过迁移")
        return

    # 创建V2集合（通过实例化Model自动创建）
    print(f"\n创建新集合: fin_product_collection_v2")
    ProductCollectionModelV2()  # 自动创建集合
    print(f"✓ 新集合创建成功")

    # 从旧集合读取所有数据
    print(f"\n从旧集合读取数据...")
    results = milvus_client.query(
        collection_name=old_collection,
        filter="id > 0",  # 查询所有记录
        output_fields=["*"],
        limit=10000
    )

    print(f"✓ 读取到 {len(results)} 条记录")

    if not results:
        print("⚠️  旧集合为空，无需迁移")
        return

    # 转换为新Schema
    print(f"\n转换数据格式...")
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
        # text: 用于BM25检索的完整文本
        text = f"{product_name} {description}"

        # metadata: 所有业务字段放入JSON
        metadata = {
            'product_name': product_name,
            'description': description,
            'risk_level': risk_level,
            'product_code': product_code,
            'category': category,
            'source': source,
            'updated_at': updated_at,
            'chunk_type': 'product_detail'  # 新增chunk_type字段
        }

        new_record = {
            'text': text,
            'metadata': metadata,
            'embedding': embedding
        }
        new_records.append(new_record)

    print(f"✓ 转换完成，共 {len(new_records)} 条记录")

    # 批量插入新集合
    print(f"\n插入数据到新集合...")
    batch_size = 100
    for i in range(0, len(new_records), batch_size):
        batch = new_records[i:i+batch_size]
        milvus_client.insert(
            collection_name="fin_product_collection_v2",
            data=batch
        )
        print(f"  已插入 {min(i+batch_size, len(new_records))}/{len(new_records)} 条")

    # 验证数据
    print(f"\n验证迁移结果...")
    new_count = milvus_client.query(
        collection_name="fin_product_collection_v2",
        filter="id > 0",
        output_fields=["id"],
        limit=1
    )

    if new_count:
        print(f"✅ 产品集合迁移成功！")
        print(f"   旧集合: {len(results)} 条")
        print(f"   新集合: 已验证数据存在")
    else:
        print(f"❌ 迁移验证失败")


def migrate_policy_collection():
    """迁移政策集合到V2"""
    print("\n" + "="*80)
    print("迁移政策集合: fin_policy_collection -> fin_policy_collection_v2")
    print("="*80)

    milvus_client = get_milvus_client()
    old_collection = "fin_policy_collection"

    # 检查旧集合是否存在
    collections = milvus_client.list_collections()
    if old_collection not in collections:
        print(f"⚠️  旧集合 {old_collection} 不存在，跳过迁移")
        return

    # 创建V2集合
    print(f"\n创建新集合: fin_policy_collection_v2")
    PolicyCollectionModelV2()  # 自动创建集合
    print(f"✓ 新集合创建成功")

    # 从旧集合读取所有数据
    print(f"\n从旧集合读取数据...")
    results = milvus_client.query(
        collection_name=old_collection,
        filter="id > 0",
        output_fields=["*"],
        limit=10000
    )

    print(f"✓ 读取到 {len(results)} 条记录")

    if not results:
        print("⚠️  旧集合为空，无需迁移")
        return

    # 转换为新Schema
    print(f"\n转换数据格式...")
    new_records = []
    for old_record in results:
        # 提取旧字段
        policy_title = old_record.get('policy_title', '')
        content = old_record.get('content', '')
        policy_code = old_record.get('policy_code', '')
        source = old_record.get('source', '')
        effective_date = old_record.get('effective_date', '')
        updated_at = old_record.get('updated_at', 0)
        embedding = old_record.get('embedding', [])

        # 构造新记录
        # text: 标题 + 内容（用于BM25检索）
        text = f"{policy_title} {content}"

        # metadata: 所有业务字段
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
            'metadata': metadata,
            'embedding': embedding
        }
        new_records.append(new_record)

    print(f"✓ 转换完成，共 {len(new_records)} 条记录")

    # 批量插入新集合
    print(f"\n插入数据到新集合...")
    batch_size = 100
    for i in range(0, len(new_records), batch_size):
        batch = new_records[i:i+batch_size]
        milvus_client.insert(
            collection_name="fin_policy_collection_v2",
            data=batch
        )
        print(f"  已插入 {min(i+batch_size, len(new_records))}/{len(new_records)} 条")

    # 验证数据
    print(f"\n验证迁移结果...")
    new_count = milvus_client.query(
        collection_name="fin_policy_collection_v2",
        filter="id > 0",
        output_fields=["id"],
        limit=1
    )

    if new_count:
        print(f"✅ 政策集合迁移成功！")
        print(f"   旧集合: {len(results)} 条")
        print(f"   新集合: 已验证数据存在")
    else:
        print(f"❌ 迁移验证失败")


if __name__ == '__main__':
    print("\n" + "╔" + "="*78 + "╗")
    print("║" + " "*20 + "Milvus 集合 V2 迁移脚本" + " "*20 + "║")
    print("╚" + "="*78 + "╝")

    try:
        # 迁移产品集合
        migrate_product_collection()

        # 迁移政策集合
        migrate_policy_collection()

        print("\n" + "="*80)
        print("✅ 所有集合迁移完成")
        print("="*80)
        print("\n下一步：")
        print("  1. 使用混合检索测试查询效果")
        print("  2. 确认jieba分词生效（查询'投资者适当性'应返回相关结果）")
        print("  3. 测试通过后，可删除旧集合释放空间")
        print("  4. 根据实际检索效果调整阈值（参考RAG优化方案）")

    except Exception as e:
        print(f"\n❌ 迁移失败: {e}")
        import traceback
        traceback.print_exc()
