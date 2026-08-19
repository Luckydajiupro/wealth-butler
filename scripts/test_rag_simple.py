"""简化的 RAG 组件测试脚本

只测试 Ollama embedding 和 Milvus 插入，不涉及 MySQL。
"""
import logging
from app.Base.Client.ollamaClient import ollama_client
from app.Base.Client.milvusClient import MilvusClientSingleton

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 创建 Milvus 客户端实例
milvus_client = MilvusClientSingleton()

def test_ollama_embedding():
    """测试 Ollama bge-m3 向量生成"""
    logger.info("=" * 60)
    logger.info("测试 1: Ollama 向量生成")
    logger.info("=" * 60)

    text = "银行理财产品的风险等级分为R1到R5五个等级"

    embedding = ollama_client.get_embedding(text, model="bge-m3")

    logger.info(f"文本: {text}")
    logger.info(f"向量维度: {len(embedding)}")
    logger.info(f"向量前5维: {embedding[:5]}")
    logger.info("✓ Ollama 向量生成成功\n")

    return embedding


def test_milvus_insert(embedding):
    """测试 Milvus 插入"""
    logger.info("=" * 60)
    logger.info("测试 2: Milvus 数据插入")
    logger.info("=" * 60)

    collection_name = "fin_faq_collection"

    # 准备测试数据（匹配 fin_faq_collection 的 schema）
    test_data = {
        'question': '什么是银行理财产品的风险等级？',
        'answer': '银行理财产品的风险等级分为R1到R5五个等级',
        'source': 'test',
        'category': '理财知识',
        'updated_at': '2026-08-15',
        'embedding': embedding
    }

    # 插入（使用字典格式）
    result = milvus_client.insert(
        collection_name=collection_name,
        data=[test_data]
    )

    logger.info(f"插入结果: {result}")
    logger.info("✓ Milvus 插入成功\n")


if __name__ == '__main__':
    logger.info("\n开始测试 RAG 核心组件...\n")

    try:
        # 测试 1: Ollama
        embedding = test_ollama_embedding()

        # 测试 2: Milvus
        test_milvus_insert(embedding)

        logger.info("=" * 60)
        logger.info("✓ 所有测试通过")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"✗ 测试失败: {e}", exc_info=True)
