"""
RAG知识库切片入库测试脚本（简化版，仅处理少量数据验证流程）
"""
import os
import sys
import re
import json
import logging
from typing import List, Dict, Any

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.Base.Ai.llms.ollamaEmbedding import ollama_embedding
from app.WealthButler.Repository.faqCollectionModelV2 import FaqCollectionModelV2
from app.WealthButler.Repository.productCollectionModelV2 import ProductCollectionModelV2
from app.WealthButler.Repository.policyCollectionModelV2 import PolicyCollectionModelV2
from app.WealthButler.Models.knowledgeMetaModel import KnowledgeMetaModel
from app.Base.Client.mysqlClient import MySQLClient

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 占位符替换词典
PLACEHOLDER_DICT = {
    r'XX科技(?:有限公司)?': '锦鹏科技有限公司',
    r'XX Tech Co\., Ltd\.': 'Jinpeng Tech Co., Ltd.',
    r'www\.xxtech\.com': 'www.jinpengtech.com',
    r'400-XXX-XXXX': '400-822-6699',
    r'某市': '临江市',
    r'20XX年X月XX日': '2014年6月18日',
    r'20XX年': '2014年',
    r'X亿元': '8亿元',
    r'XX,XXX万元': '80,000万元',
    r'X,XXX人': '3,200人',
}

def clean_placeholder(text: str) -> str:
    """占位符清洗"""
    for pattern, replacement in PLACEHOLDER_DICT.items():
        text = re.sub(pattern, replacement, text)
    return text

def test_faq_ingestion():
    """测试FAQ入库（只处理前3条）"""
    logger.info("=" * 60)
    logger.info("测试FAQ入库")
    logger.info("=" * 60)

    db = MySQLClient()
    db.connect()

    faq_file = os.path.join(project_root, "公司信息/高频问答对.txt")

    with open(faq_file, 'r', encoding='utf-8') as f:
        content = f.read()

    cleaned_content = clean_placeholder(content)
    lines = cleaned_content.strip().split('\n')[:3]  # 只取前3条

    success_count = 0

    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            continue

        parts = line.split('\t')
        if len(parts) < 2:
            logger.warning(f"FAQ第{line_no}行格式不正确")
            continue

        question, answer = parts[0], parts[1]

        logger.info(f"\n处理FAQ {line_no}: {question[:30]}...")

        # 生成embedding
        try:
            embedding = ollama_embedding(question)
            logger.info(f"Embedding生成成功，维度={len(embedding)}")
        except Exception as e:
            logger.error(f"Embedding生成失败: {e}")
            continue

        # 写入MySQL
        try:
            meta_record = KnowledgeMetaModel(
                knowledge_type='FAQ',
                collection_name='fin_faq_collection',
                title=question[:100],
                source_file='高频问答对.txt',
                status='待审核',
                uploaded_by=1,
                milvus_collection='fin_faq_collection',
            )
            meta_id = meta_record.save()
            logger.info(f"MySQL记录创建成功，ID={meta_id}")
        except Exception as e:
            logger.error(f"MySQL写入失败: {e}")
            continue

        # 写入Milvus
        try:
            metadata_str = json.dumps({
                'question': question,
                'answer': answer,
                'source': '高频问答对.txt',
                'seq_no': str(line_no)
            }, ensure_ascii=False)

            model = FaqCollectionModelV2(
                text=question,
                metadata=metadata_str,
                embedding=embedding
            )

            result = FaqCollectionModelV2.insert([model])
            logger.info(f"Milvus插入返回结果: {result}")

            if result and result.get('success') and result.get('insert_count', 0) > 0:
                logger.info(f"Milvus插入成功，insert_count={result.get('insert_count')}")

                # 注：MilvusClient的auto_id模式下不返回生成的主键ID
                # 4天工期取向：milvus_pk留空，通过collection_name+source_file+title组合定位
                update_sql = f"""
                    UPDATE {KnowledgeMetaModel.table_alias}
                    SET status = '已上线'
                    WHERE id = %s
                """
                db.execute_sync(update_sql, (meta_id,))
                logger.info(f"✅ FAQ入库成功: {question[:30]}")
                success_count += 1
            else:
                logger.error(f"Milvus插入返回结果异常: {result}")

        except Exception as e:
            logger.error(f"Milvus插入失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            continue

    db.close()
    logger.info(f"\n测试完成，成功入库 {success_count}/{len(lines)} 条FAQ")
    return success_count > 0

if __name__ == '__main__':
    success = test_faq_ingestion()
    if success:
        logger.info("\n✅ 测试通过！现在可以运行完整的 rag_ingestion.py 脚本")
    else:
        logger.error("\n❌ 测试失败，请检查错误信息")
