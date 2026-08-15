"""
数据层完整性检查脚本

检查项：
1. MySQL 10张业务表是否全部建成
2. Milvus 4个集合是否全部建成（含V2集合）
3. Neo4j图谱schema是否就绪
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.Base.Client.milvusClient import MilvusClientSingleton
from app.Base.Client.neo4jClient import Neo4jClientSingleton


def check_mysql_tables():
    """检查MySQL 10张表"""
    print("[MySQL Tables Check]")
    print("=" * 60)

    # 预期的10张表
    expected_tables = [
        'base_user',
        'fin_customer_profile',
        'fin_product',
        'fin_transaction',
        'fin_holdings',
        'fin_risk_assessment',
        'fin_risk_alert',
        'fin_work_order',
        'fin_knowledge_meta',
        'fin_conversation_archive'
    ]

    try:
        from app.Base.Client.mysqlClient import mysql_client

        result = mysql_client.query('SHOW TABLES')
        existing_tables = [list(r.values())[0] for r in result]

        missing_tables = []
        for table in expected_tables:
            if table in existing_tables:
                print(f"[OK] {table}")
            else:
                print(f"[MISSING] {table}")
                missing_tables.append(table)

        print(f"\nTotal: {len(existing_tables)}/{len(expected_tables)} tables exist")

        if missing_tables:
            print(f"\n[WARNING] Missing tables: {', '.join(missing_tables)}")
            return False
        else:
            print("\n[SUCCESS] All MySQL tables exist")
            return True

    except Exception as e:
        print(f"[ERROR] MySQL check failed: {e}")
        return False


def check_milvus_collections():
    """检查Milvus集合"""
    print("\n[Milvus Collections Check]")
    print("=" * 60)

    # 预期的集合（V1 + V2）
    expected_collections = {
        'V1': [
            'fin_faq_collection',
            'fin_product_collection',
            'fin_policy_collection',
            'fin_customer_memory_collection'
        ],
        'V2': [
            'fin_faq_collection_v2',
            'fin_product_collection_v2',
            'fin_policy_collection_v2'
        ]
    }

    try:
        milvus_client = MilvusClientSingleton().client
        existing_collections = milvus_client.list_collections()

        print("\n[V1 Collections]")
        v1_missing = []
        for collection in expected_collections['V1']:
            if collection in existing_collections:
                print(f"[OK] {collection}")
            else:
                print(f"[MISSING] {collection}")
                v1_missing.append(collection)

        print("\n[V2 Collections]")
        v2_missing = []
        for collection in expected_collections['V2']:
            if collection in existing_collections:
                # 检查数据量
                count_result = milvus_client.query(
                    collection_name=collection,
                    filter="",
                    output_fields=["count(*)"]
                )
                count = count_result[0].get('count(*)', 0) if count_result else 0
                print(f"[OK] {collection} ({count} records)")
            else:
                print(f"[MISSING] {collection}")
                v2_missing.append(collection)

        print(f"\nTotal: {len([c for c in existing_collections if 'fin_' in c])} collections exist")

        if v2_missing:
            print(f"\n[WARNING] Missing V2 collections: {', '.join(v2_missing)}")
            return False
        else:
            print("\n[SUCCESS] All V2 collections exist and have data")
            return True

    except Exception as e:
        print(f"[ERROR] Milvus check failed: {e}")
        return False


def check_neo4j_schema():
    """检查Neo4j图谱schema"""
    print("\n[Neo4j Schema Check]")
    print("=" * 60)

    try:
        neo4j_client = Neo4jClientSingleton()

        # 检查节点标签
        print("\n[Node Labels]")
        result = neo4j_client.run_cypher("CALL db.labels()")
        labels = [record['label'] for record in result]

        expected_labels = ['Customer', 'Product', 'RiskFactor', 'Policy']
        for label in expected_labels:
            if label in labels:
                print(f"[OK] {label}")
            else:
                print(f"[MISSING] {label}")

        # 检查关系类型
        print("\n[Relationship Types]")
        result = neo4j_client.run_cypher("CALL db.relationshipTypes()")
        rel_types = [record['relationshipType'] for record in result]

        expected_rels = ['HOLDS', 'HAS_RISK', 'COMPLIES_WITH', 'SIMILAR_TO']
        for rel in expected_rels:
            if rel in rel_types:
                print(f"[OK] {rel}")
            else:
                print(f"[MISSING] {rel}")

        # 检查约束和索引
        print("\n[Constraints]")
        result = neo4j_client.run_cypher("SHOW CONSTRAINTS")
        constraints = [record.get('name', 'N/A') for record in result]
        print(f"Total constraints: {len(constraints)}")
        for constraint in constraints[:5]:
            print(f"  - {constraint}")

        print("\n[Indexes]")
        result = neo4j_client.run_cypher("SHOW INDEXES")
        indexes = [record.get('name', 'N/A') for record in result]
        print(f"Total indexes: {len(indexes)}")
        for index in indexes[:5]:
            print(f"  - {index}")

        print("\n[SUCCESS] Neo4j schema check completed")
        return True

    except Exception as e:
        print(f"[ERROR] Neo4j check failed: {e}")
        return False


def main():
    """主函数"""
    print("Data Layer Completeness Check")
    print("=" * 60)

    results = {
        'mysql': check_mysql_tables(),
        'milvus': check_milvus_collections(),
        'neo4j': check_neo4j_schema()
    }

    print("\n" + "=" * 60)
    print("[Summary]")
    print("=" * 60)

    for component, status in results.items():
        status_str = "[OK]" if status else "[FAIL]"
        print(f"{status_str} {component.upper()}")

    all_passed = all(results.values())

    if all_passed:
        print("\n[SUCCESS] All data layer components are complete")
        return 0
    else:
        print("\n[WARNING] Some components have issues, please check above")
        return 1


if __name__ == "__main__":
    exit(main())
