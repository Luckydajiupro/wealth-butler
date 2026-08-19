"""
RAG知识库入库结果验证脚本
"""
import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.WealthButler.Repository.faqCollectionModelV2 import FaqCollectionModelV2
from app.WealthButler.Repository.productCollectionModelV2 import ProductCollectionModelV2
from app.WealthButler.Repository.policyCollectionModelV2 import PolicyCollectionModelV2
from app.WealthButler.Models.knowledgeMetaModel import KnowledgeMetaModel
from app.Base.Client.mysqlClient import MySQLClient

def verify_milvus_data():
    """验证Milvus集合数据"""
    print("=" * 80)
    print("Milvus集合数据验证")
    print("=" * 80)

    try:
        # 查询FAQ集合
        faq_count = FaqCollectionModelV2.count()
        print(f"✅ fin_faq_collection: {faq_count} 条记录")
    except Exception as e:
        print(f"❌ fin_faq_collection查询失败: {e}")

    try:
        # 查询产品集合
        product_count = ProductCollectionModelV2.count()
        print(f"✅ fin_product_collection: {product_count} 条记录")
    except Exception as e:
        print(f"❌ fin_product_collection查询失败: {e}")

    try:
        # 查询政策集合
        policy_count = PolicyCollectionModelV2.count()
        print(f"✅ fin_policy_collection: {policy_count} 条记录")
    except Exception as e:
        print(f"❌ fin_policy_collection查询失败: {e}")

def verify_mysql_data():
    """验证MySQL元数据"""
    print("\n" + "=" * 80)
    print("MySQL元数据验证")
    print("=" * 80)

    db = MySQLClient()
    db.connect()

    try:
        # 按知识类型统计
        sql = f"""
            SELECT knowledge_type, status, COUNT(*) as count
            FROM {KnowledgeMetaModel.table_alias}
            GROUP BY knowledge_type, status
            ORDER BY knowledge_type, status
        """
        results = db.execute_sync(sql)

        print("\n按知识类型和状态统计：")
        for row in results:
            print(f"  {row['knowledge_type']} - {row['status']}: {row['count']} 条")

        # 按集合统计
        sql = f"""
            SELECT collection_name, status, COUNT(*) as count
            FROM {KnowledgeMetaModel.table_alias}
            GROUP BY collection_name, status
            ORDER BY collection_name, status
        """
        results = db.execute_sync(sql)

        print("\n按集合和状态统计：")
        for row in results:
            print(f"  {row['collection_name']} - {row['status']}: {row['count']} 条")

        # 按源文件统计
        sql = f"""
            SELECT source_file, COUNT(*) as count
            FROM {KnowledgeMetaModel.table_alias}
            WHERE status = '已上线'
            GROUP BY source_file
            ORDER BY source_file
        """
        results = db.execute_sync(sql)

        print("\n按源文件统计（已上线）：")
        for row in results:
            print(f"  {row['source_file']}: {row['count']} 条")

    except Exception as e:
        print(f"❌ MySQL查询失败: {e}")
    finally:
        db.close()

def generate_summary():
    """生成入库总结报告"""
    print("\n" + "=" * 80)
    print("RAG知识库入库总结")
    print("=" * 80)

    db = MySQLClient()
    db.connect()

    try:
        sql = f"""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = '已上线' THEN 1 ELSE 0 END) as online,
                SUM(CASE WHEN status = '待审核' THEN 1 ELSE 0 END) as pending
            FROM {KnowledgeMetaModel.table_alias}
        """
        result = db.execute_sync(sql)

        if result and len(result) > 0:
            row = result[0]
            print(f"\n总记录数: {row['total']}")
            print(f"已上线: {row['online']}")
            print(f"待审核: {row['pending']}")
            print(f"\n✅ 入库成功率: {row['online']/row['total']*100:.1f}%")

    except Exception as e:
        print(f"❌ 统计失败: {e}")
    finally:
        db.close()

if __name__ == '__main__':
    verify_milvus_data()
    verify_mysql_data()
    generate_summary()
    print("\n" + "=" * 80)
