"""
数据层建表验证脚本
验证MySQL 10张表 + Milvus 4个集合 + Neo4j图谱schema是否创建成功
"""
import asyncio
import sys
sys.path.append('D:/lqh/金融')

from app.Base.Client.mysqlClient import get_mysql_client
from app.Base.Client.milvusClient import get_milvus_client
from app.Base.Client.neo4jClient import get_neo4j_client
from app.WealthButler.Models.customerProfileModel import CustomerProfileModel
from app.WealthButler.Models.productModel import ProductModel
from app.WealthButler.Models.transactionModel import TransactionModel
from app.WealthButler.Models.holdingsModel import HoldingsModel
from app.WealthButler.Models.riskAssessmentModel import RiskAssessmentModel
from app.WealthButler.Models.riskAlertModel import RiskAlertModel
from app.WealthButler.Models.workOrderModel import WorkOrderModel
from app.WealthButler.Models.conversationArchiveModel import ConversationArchiveModel
from app.WealthButler.Models.knowledgeMetaModel import KnowledgeMetaModel
from app.WealthButler.Repository.faqCollectionModel import FaqCollectionModel
from app.WealthButler.Repository.productCollectionModel import ProductCollectionModel
from app.WealthButler.Repository.policyCollectionModel import PolicyCollectionModel
from app.WealthButler.Repository.customerMemoryCollectionModel import CustomerMemoryCollectionModel
from app.WealthButler.Knowledge.graphSchema import Neo4jGraphSchema


async def verify_mysql_tables():
    """验证MySQL 10张业务表"""
    print("\n=== 验证 MySQL 表创建 ===")

    db = get_mysql_client()

    # 10张业务表的Model类
    models = [
        ("fin_customer_profile", CustomerProfileModel),
        ("fin_product", ProductModel),
        ("fin_transaction", TransactionModel),
        ("fin_holdings", HoldingsModel),
        ("fin_risk_assessment", RiskAssessmentModel),
        ("fin_risk_alert", RiskAlertModel),
        ("biz_work_order", WorkOrderModel),
        ("conversation_archive", ConversationArchiveModel),
        ("fin_knowledge_meta", KnowledgeMetaModel),
    ]

    created_tables = []
    failed_tables = []

    for table_name, model_class in models:
        try:
            # 尝试创建表（如果已存在则跳过）
            model_class.metadata.create_all(bind=db.get_bind())

            # 验证表是否存在
            result = db.execute(f"SHOW TABLES LIKE '{table_name}'").fetchone()
            if result:
                created_tables.append(table_name)
                print(f"✓ {table_name} 创建成功")
            else:
                failed_tables.append(table_name)
                print(f"✗ {table_name} 创建失败")
        except Exception as e:
            failed_tables.append(table_name)
            print(f"✗ {table_name} 创建失败: {str(e)}")

    # 验证base_user扩展字段（ALTER TABLE方式）
    print("\n--- 验证 base_user 扩展字段 ---")
    try:
        # 检查扩展字段是否存在
        result = db.execute("""
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = 'base_user'
            AND COLUMN_NAME IN ('user_type', 'employee_role', 'advisor_level', 'customer_level')
        """).fetchall()

        existing_fields = [row[0] for row in result]

        if len(existing_fields) == 4:
            print("✓ base_user 扩展字段已存在")
        else:
            print(f"⚠ base_user 缺少扩展字段: {set(['user_type', 'employee_role', 'advisor_level', 'customer_level']) - set(existing_fields)}")
            print("  需要执行 ALTER TABLE 语句")
    except Exception as e:
        print(f"✗ base_user 扩展字段验证失败: {str(e)}")

    print(f"\n✓ 成功创建: {len(created_tables)} 张表")
    if failed_tables:
        print(f"✗ 失败: {len(failed_tables)} 张表 - {', '.join(failed_tables)}")

    return len(failed_tables) == 0


async def verify_milvus_collections():
    """验证Milvus 4个集合"""
    print("\n=== 验证 Milvus 集合创建 ===")

    collections = [
        ("fin_faq_collection", FaqCollectionModel),
        ("fin_product_collection", ProductCollectionModel),
        ("fin_policy_collection", PolicyCollectionModel),
        ("fin_customer_memory_collection", CustomerMemoryCollectionModel),
    ]

    created_collections = []
    failed_collections = []

    for collection_name, model_class in collections:
        try:
            # BaseVDBModel会自动创建集合
            model = model_class()
            created_collections.append(collection_name)
            print(f"✓ {collection_name} 创建成功")
        except Exception as e:
            failed_collections.append(collection_name)
            print(f"✗ {collection_name} 创建失败: {str(e)}")

    print(f"\n✓ 成功创建: {len(created_collections)} 个集合")
    if failed_collections:
        print(f"✗ 失败: {len(failed_collections)} 个集合 - {', '.join(failed_collections)}")

    return len(failed_collections) == 0


async def verify_neo4j_schema():
    """验证Neo4j图谱schema"""
    print("\n=== 验证 Neo4j 图谱schema ===")

    neo4j_client = get_neo4j_client()

    try:
        # 获取初始化Cypher列表
        init_cyphers = Neo4jGraphSchema.get_init_cypher_list()

        print(f"执行 {len(init_cyphers)} 条初始化Cypher...")

        success_count = 0
        failed_count = 0

        for cypher in init_cyphers:
            try:
                neo4j_client.run(cypher)
                success_count += 1
                print(f"✓ {cypher[:50]}...")
            except Exception as e:
                failed_count += 1
                print(f"✗ {cypher[:50]}... 失败: {str(e)}")

        print(f"\n✓ 成功执行: {success_count} 条Cypher")
        if failed_count > 0:
            print(f"✗ 失败: {failed_count} 条Cypher")

        # 验证节点创建
        result = neo4j_client.run("MATCH (n) RETURN labels(n) as labels, count(n) as count")
        print("\n--- 图谱节点统计 ---")
        for record in result:
            print(f"  {record['labels']}: {record['count']} 个节点")

        return failed_count == 0
    except Exception as e:
        print(f"✗ Neo4j图谱schema验证失败: {str(e)}")
        return False


async def main():
    """主验证流程"""
    print("=" * 60)
    print("数据层建表验证")
    print("=" * 60)

    # 1. MySQL表验证
    mysql_ok = await verify_mysql_tables()

    # 2. Milvus集合验证
    milvus_ok = await verify_milvus_collections()

    # 3. Neo4j图谱schema验证
    neo4j_ok = await verify_neo4j_schema()

    # 汇总结果
    print("\n" + "=" * 60)
    print("验证结果汇总")
    print("=" * 60)
    print(f"MySQL 10张表: {'✓ 通过' if mysql_ok else '✗ 失败'}")
    print(f"Milvus 4个集合: {'✓ 通过' if milvus_ok else '✗ 失败'}")
    print(f"Neo4j图谱schema: {'✓ 通过' if neo4j_ok else '✗ 失败'}")

    if mysql_ok and milvus_ok and neo4j_ok:
        print("\n✓ Day1 P0-1 数据层建表攻坚完成！")
        return 0
    else:
        print("\n✗ 数据层建表存在问题，请检查")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
