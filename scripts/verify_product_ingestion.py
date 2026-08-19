"""
验证产品知识入库结果

功能：
1. 检查Milvus集合中的数据
2. 检查MySQL元数据表
3. 执行示例检索测试
"""

import sys
import logging
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.Base.Client.mysqlClient import MySQLClient
from app.Base.Client.milvusClient import MilvusClientSingleton
from app.Base.Ai.llms.ollamaEmbedding import ollama_embedding

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def verify_product_knowledge():
    """验证产品知识入库"""
    collection_name = "fin_product_collection"

    logger.info("=" * 80)
    logger.info("产品知识入库验证报告")
    logger.info("=" * 80)

    # 1. 检查Milvus集合
    logger.info("\n【1. Milvus集合检查】")
    try:
        milvus_client = MilvusClientSingleton()
        client = milvus_client.get_client()

        # 确保集合已加载
        if not client.has_collection(collection_name):
            logger.error(f"❌ 集合 {collection_name} 不存在！")
            return

        load_state = client.get_load_state(collection_name=collection_name)
        if load_state.get("state") != "Loaded":
            logger.info(f"加载集合 {collection_name}...")
            client.load_collection(collection_name=collection_name)

        # 查询所有数据
        all_records = milvus_client.query(
            collection_name=collection_name,
            filter="",
            output_fields=["text", "product_name", "product_code", "risk_level", "product_type", "metadata"],
            limit=100
        )

        logger.info(f"✅ 集合 {collection_name} 中共有 {len(all_records)} 条记录")

        # 统计产品类型分布
        product_types = {}
        risk_levels = {}
        has_product_code = 0

        for record in all_records:
            ptype = record.get('product_type', '')
            if ptype:
                product_types[ptype] = product_types.get(ptype, 0) + 1

            risk = record.get('risk_level', '')
            if risk:
                risk_levels[risk] = risk_levels.get(risk, 0) + 1

            if record.get('product_code'):
                has_product_code += 1

        logger.info(f"  - 有产品代码的记录: {has_product_code}/{len(all_records)}")
        logger.info(f"  - 产品类型分布: {product_types}")
        logger.info(f"  - 风险等级分布: {risk_levels}")

        # 显示前3条示例
        logger.info("\n示例记录（前3条）:")
        for idx, record in enumerate(all_records[:3], 1):
            text = record.get('text', '')
            preview = text[:100] + '...' if len(text) > 100 else text
            logger.info(f"\n  [{idx}] 产品代码: {record.get('product_code', 'N/A')}")
            logger.info(f"      产品名称: {record.get('product_name', 'N/A')}")
            logger.info(f"      风险等级: {record.get('risk_level', 'N/A')}")
            logger.info(f"      产品类型: {record.get('product_type', 'N/A')}")
            logger.info(f"      文本预览: {preview}")

    except Exception as e:
        logger.error(f"❌ Milvus检查失败: {e}", exc_info=True)

    # 2. 检查MySQL元数据
    logger.info("\n【2. MySQL元数据检查】")
    try:
        mysql_client = MySQLClient()

        # 查询产品知识元数据
        sql = """
            SELECT id, title, source_file, chunk_count, status, created_at
            FROM fin_knowledge_meta
            WHERE collection_name = %s
            ORDER BY id DESC
        """
        results = mysql_client.execute_sync(sql, (collection_name,))

        logger.info(f"✅ MySQL中共有 {len(results)} 条产品知识元数据记录")

        online_count = sum(1 for r in results if r['status'] == '已上线')
        logger.info(f"  - 已上线: {online_count}")
        logger.info(f"  - 其他状态: {len(results) - online_count}")

        if results:
            logger.info("\n最新5条元数据记录:")
            for idx, record in enumerate(results[:5], 1):
                logger.info(f"  [{idx}] ID:{record['id']} | {record['title'][:50]} | 状态:{record['status']}")

    except Exception as e:
        logger.error(f"❌ MySQL检查失败: {e}", exc_info=True)

    # 3. 执行检索测试
    logger.info("\n【3. 检索功能测试】")
    test_queries = [
        "货币基金",
        "债券基金",
        "风险等级R3的产品",
    ]

    try:
        for query in test_queries:
            logger.info(f"\n测试查询: '{query}'")

            # 生成查询向量
            query_vec = ollama_embedding(query)

            # 执行向量检索
            search_results = milvus_client.search(
                collection_name=collection_name,
                data=[query_vec],
                anns_field="embedding",
                limit=3,
                output_fields=["product_name", "product_code", "risk_level"]
            )

            if search_results and len(search_results[0]) > 0:
                logger.info(f"  ✅ 找到 {len(search_results[0])} 条结果:")
                for idx, hit in enumerate(search_results[0], 1):
                    entity = hit.get('entity', {})
                    distance = hit.get('distance', 0)
                    logger.info(f"    [{idx}] 相似度:{distance:.4f} | "
                              f"产品:{entity.get('product_name', 'N/A')} | "
                              f"代码:{entity.get('product_code', 'N/A')} | "
                              f"风险:{entity.get('risk_level', 'N/A')}")
            else:
                logger.warning(f"  ⚠️ 未找到匹配结果")

    except Exception as e:
        logger.error(f"❌ 检索测试失败: {e}", exc_info=True)

    logger.info("\n" + "=" * 80)
    logger.info("验证完成")
    logger.info("=" * 80)


if __name__ == "__main__":
    verify_product_knowledge()
