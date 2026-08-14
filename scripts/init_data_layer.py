"""
数据层统一建表脚本
执行前请先配置好.env文件中的数据库连接信息
"""
import sys
import os

# 添加项目根目录到path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.Base.Client.mysqlClient import MySQLClient
from app.Base.Client.neo4jClient import Neo4jClient


def init_mysql_tables():
    """初始化MySQL表"""
    print("\n" + "=" * 60)
    print("MySQL表初始化")
    print("=" * 60)

    # 导入所有Model（导入时会自动调用_ensure_table_exists建表）
    from app.Base.Models.userModel import UserModel
    from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel
    from app.WealthButler.Models.customerProfileModel import CustomerProfileModel
    from app.WealthButler.Models.productModel import ProductModel
    from app.WealthButler.Models.transactionModel import TransactionModel
    from app.WealthButler.Models.holdingsModel import HoldingsModel
    from app.WealthButler.Models.riskAssessmentModel import RiskAssessmentModel
    from app.WealthButler.Models.riskAlertModel import RiskAlertModel
    from app.WealthButler.Models.workOrderModel import WorkOrderModel
    from app.WealthButler.Models.conversationArchiveModel import ConversationArchiveModel
    from app.WealthButler.Models.knowledgeMetaModel import KnowledgeMetaModel

    models = [
        ("base_user", UserModel),
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

    print("\n开始创建MySQL表...")
    success_count = 0

    for table_name, model_class in models:
        try:
            # 调用_ensure_table_exists会自动创建表
            model_class._ensure_table_exists()
            print(f"[OK] {table_name} 创建成功")
            success_count += 1
        except Exception as e:
            print(f"[FAIL] {table_name} 创建失败: {str(e)}")

    # base_user扩展字段（需要手动执行ALTER TABLE）
    print("\n--- 扩展 base_user 表字段 ---")
    try:
        db = MySQLClient()
        db.connect()

        # 定义需要添加的字段和索引
        columns_to_add = [
            ("user_type", "ALTER TABLE `base_user` ADD COLUMN `user_type` ENUM('CUSTOMER','EMPLOYEE') NOT NULL DEFAULT 'CUSTOMER' COMMENT '用户大类'"),
            ("employee_role", "ALTER TABLE `base_user` ADD COLUMN `employee_role` ENUM('理财顾问','风控专员','客户经理','业务管理员') COMMENT '员工主角色'"),
            ("advisor_level", "ALTER TABLE `base_user` ADD COLUMN `advisor_level` ENUM('初级','中级','高级') COMMENT '理财顾问执业等级'"),
            ("customer_level", "ALTER TABLE `base_user` ADD COLUMN `customer_level` ENUM('普通','金卡','白金','钻石','私行') DEFAULT '普通' COMMENT '客户等级'"),
        ]

        indexes_to_add = [
            ("idx_user_type", "ALTER TABLE `base_user` ADD INDEX `idx_user_type` (`user_type`)")
        ]

        # 检查并添加字段
        for column_name, alter_sql in columns_to_add:
            check_sql = f"SELECT COUNT(*) as cnt FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='base_user' AND COLUMN_NAME='{column_name}'"
            result = db.execute_sync(check_sql)
            if result and result[0]['cnt'] == 0:
                db.execute_sync(alter_sql)
                print(f"[OK] 字段 {column_name} 添加成功")
            else:
                print(f"[SKIP] 字段 {column_name} 已存在")

        # 检查并添加索引
        for index_name, alter_sql in indexes_to_add:
            check_sql = f"SELECT COUNT(*) as cnt FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='base_user' AND INDEX_NAME='{index_name}'"
            result = db.execute_sync(check_sql)
            if result and result[0]['cnt'] == 0:
                db.execute_sync(alter_sql)
                print(f"[OK] 索引 {index_name} 添加成功")
            else:
                print(f"[SKIP] 索引 {index_name} 已存在")

        db.close()
        print("[OK] base_user 扩展完成")
        success_count += 1
    except Exception as e:
        print(f"[FAIL] base_user 扩展字段失败: {str(e)}")

    print(f"\n[完成] MySQL表创建完成: {success_count}/10")


def init_milvus_collections():
    """初始化Milvus集合"""
    print("\n" + "=" * 60)
    print("Milvus集合初始化")
    print("=" * 60)

    from app.WealthButler.Repository.faqCollectionModel import FaqCollectionModel
    from app.WealthButler.Repository.productCollectionModel import ProductCollectionModel
    from app.WealthButler.Repository.policyCollectionModel import PolicyCollectionModel
    from app.WealthButler.Repository.customerMemoryCollectionModel import CustomerMemoryCollectionModel

    collections = [
        ("fin_faq_collection", FaqCollectionModel),
        ("fin_product_collection", ProductCollectionModel),
        ("fin_policy_collection", PolicyCollectionModel),
        ("fin_customer_memory_collection", CustomerMemoryCollectionModel),
    ]

    print("\n开始创建Milvus集合...")
    success_count = 0

    for collection_name, model_class in collections:
        try:
            # 实例化Model会自动创建集合
            model_class._check_and_create_collection()
            print(f"[OK] {collection_name} 创建成功")
            success_count += 1
        except Exception as e:
            print(f"[FAIL] {collection_name} 创建失败: {str(e)}")

    print(f"\n[完成] Milvus集合创建完成: {success_count}/4")


def init_neo4j_schema():
    """初始化Neo4j图谱schema"""
    print("\n" + "=" * 60)
    print("Neo4j图谱Schema初始化")
    print("=" * 60)

    from app.WealthButler.Knowledge.graphSchema import Neo4jGraphSchema

    neo4j_client = Neo4jClient()
    init_cyphers = Neo4jGraphSchema.get_init_cypher_list()

    print(f"\n开始执行 {len(init_cyphers)} 条初始化Cypher...")
    success_count = 0

    for cypher in init_cyphers:
        try:
            neo4j_client.run(cypher)
            success_count += 1
            print(f"[OK] {cypher[:60]}...")
        except Exception as e:
            print(f"[FAIL] {cypher[:60]}... 失败: {str(e)}")

    print(f"\n[完成] Neo4j schema初始化完成: {success_count}/{len(init_cyphers)}")


def main():
    """主函数"""
    print("=" * 60)
    print("智能财富管家系统 - 数据层统一建表")
    print("=" * 60)
    print("\n请确保已配置好.env文件中的数据库连接信息：")
    print("  - MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE")
    print("  - MILVUS_HOST, MILVUS_PORT")
    print("  - NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD")
    print("\n开始初始化...")

    # 1. MySQL表初始化
    try:
        init_mysql_tables()
    except Exception as e:
        print(f"\n[ERROR] MySQL表初始化失败: {str(e)}")

    # 2. Milvus集合初始化
    try:
        init_milvus_collections()
    except Exception as e:
        print(f"\n[ERROR] Milvus集合初始化失败: {str(e)}")

    # 3. Neo4j图谱schema初始化
    try:
        init_neo4j_schema()
    except Exception as e:
        print(f"\n[ERROR] Neo4j schema初始化失败: {str(e)}")

    print("\n" + "=" * 60)
    print("数据层初始化完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
