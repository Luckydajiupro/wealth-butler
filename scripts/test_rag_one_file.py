"""测试 RAG 入库流程（单文件验证）

只处理高频问答对.txt，验证：
1. 占位符清洗
2. FAQ 按行切片
3. 只对 question 生成向量
4. 插入 Milvus（fin_faq_collection）
5. 写入 MySQL 元数据
"""
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

# 添加项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.Base.Client.ollamaClient import ollama_client
from app.Base.Client.milvusClient import MilvusClientSingleton
from app.WealthButler.Models.knowledgeMetaModel import KnowledgeMetaModel
from app.Base.Repository.base.baseDBModel import BaseDBModel
from app.Base.Repository.connections.mysqlConnection import MySQLConnection
from app.Base.Config.setting import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 创建 Milvus 客户端
milvus_client = MilvusClientSingleton()

# 占位符词典（从 placeholder_dict.json 加载）
PLACEHOLDER_FILE = project_root / 'scripts' / 'placeholder_dict.json'

def load_placeholder_dict():
    """加载占位符词典"""
    if PLACEHOLDER_FILE.exists():
        with open(PLACEHOLDER_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def clean_text_with_placeholders(text: str, placeholder_dict: dict) -> str:
    """用占位符词典清洗文本"""
    for placeholder, real_value in placeholder_dict.items():
        text = text.replace(placeholder, real_value)
    return text

def parse_faq_file(file_path: str, placeholder_dict: dict):
    """解析 FAQ 文件（制表符分隔：问题\\t答案）

    Returns:
        [{'question': '...', 'answer': '...', 'question_clean': '...', 'answer_clean': '...'}]
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    faqs = []
    for line_num, line in enumerate(lines, 1):
        parts = line.strip().split('\t')

        if len(parts) != 2:
            logger.warning(f"跳过格式不正确的行 {line_num}: 期望2列，实际{len(parts)}列")
            continue

        question = parts[0].strip()
        answer = parts[1].strip()

        if not question or not answer:
            logger.warning(f"跳过空内容行 {line_num}")
            continue

        # 占位符清洗
        question_clean = clean_text_with_placeholders(question, placeholder_dict)
        answer_clean = clean_text_with_placeholders(answer, placeholder_dict)

        faqs.append({
            'question': question,
            'answer': answer,
            'question_clean': question_clean,
            'answer_clean': answer_clean
        })

    logger.info(f"FAQ 解析完成：共 {len(faqs)} 条")
    return faqs


def generate_embedding(text: str):
    """生成向量"""
    embedding = ollama_client.get_embedding(text, model='bge-m3')
    if len(embedding) != 1024:
        raise ValueError(f"向量维度不匹配：期望 1024，实际 {len(embedding)}")
    return embedding


def test_faq_ingestion(dry_run=True):
    """测试 FAQ 入库流程

    Args:
        dry_run: True 只测试不插入，False 真实插入
    """
    logger.info("=" * 80)
    logger.info(f"测试 FAQ 入库流程 (dry_run={dry_run})")
    logger.info("=" * 80)

    # 1. 加载占位符词典
    placeholder_dict = load_placeholder_dict()
    logger.info(f"✓ 占位符词典已加载: {len(placeholder_dict)} 条规则")

    # 2. 初始化数据库连接
    mysql_config = settings.mysql.model_dump()
    db_connection = MySQLConnection(
        host=mysql_config['host'],
        user=mysql_config['user'],
        password=mysql_config['password'],
        database=mysql_config['name'],
        port=mysql_config['port'],
        charset=mysql_config['charset']
    )
    BaseDBModel.set_default_db_connection(db_connection)
    logger.info("✓ 数据库连接已初始化")

    # 3. 解析 FAQ 文件
    faq_file = 'D:/lqh/金融/公司信息/高频问答对.txt'
    faqs = parse_faq_file(faq_file, placeholder_dict)

    # 只测试前3条
    test_faqs = faqs[:3] if dry_run else faqs
    logger.info(f"处理 {len(test_faqs)} 条 FAQ（共{len(faqs)}条）")

    # 4. 生成向量（只对 question 做 embedding）
    logger.info("生成向量（只对 question）...")
    for i, faq in enumerate(test_faqs, 1):
        faq['embedding'] = generate_embedding(faq['question_clean'])
        if i % 5 == 0 or i == len(test_faqs):
            logger.info(f"  已生成 {i}/{len(test_faqs)} 个向量")

    # 5. 准备 Milvus 插入数据
    # fin_faq_collection schema: id(auto), question, answer, source, category, updated_at, embedding
    # 注意：id 是 auto_id=True，不要提供
    milvus_data = []
    for i, faq in enumerate(test_faqs, 1):
        milvus_data.append({
            'question': faq['question_clean'][:500],
            'answer': faq['answer_clean'][:2000],
            'source': '高频问答对.txt',
            'category': '公司信息',
            'updated_at': datetime.now().strftime('%Y-%m-%d'),
            'embedding': faq['embedding']
        })

    logger.info(f"\n准备插入 {len(milvus_data)} 条数据到 fin_faq_collection")
    logger.info(f"示例数据:")
    logger.info(f"  Question: {milvus_data[0]['question'][:50]}...")
    logger.info(f"  Answer: {milvus_data[0]['answer'][:50]}...")
    logger.info(f"  Embedding维度: {len(milvus_data[0]['embedding'])}")

    if dry_run:
        logger.info("\n[DRY RUN] 跳过实际插入")
        logger.info("=" * 80)
        logger.info("✓ 测试通过，流程正常")
        logger.info("运行 test_faq_ingestion(dry_run=False) 可真实插入")
        logger.info("=" * 80)
        return

    # 6. 插入 Milvus
    logger.info("插入 Milvus...")
    result = milvus_client.insert(
        collection_name='fin_faq_collection',
        data=milvus_data
    )
    pk_list = result.get('ids', []) if isinstance(result, dict) else []
    logger.info(f"✓ Milvus 插入成功：{len(pk_list)} 条")

    # 7. 写入 MySQL 元数据
    logger.info("写入 MySQL 元数据...")
    meta = KnowledgeMetaModel(
        knowledge_type='FAQ',
        collection_name='fin_faq_collection',
        title='高频问答对',
        source=faq_file,
        version='1.0',
        file_path=faq_file,
        chunk_count=len(test_faqs),
        status='已上线'
    )
    meta_id = meta.save()
    logger.info(f"✓ 元数据已保存: id={meta_id}")

    logger.info("\n" + "=" * 80)
    logger.info("✓ 入库完成")
    logger.info(f"  - FAQ数: {len(test_faqs)}")
    logger.info(f"  - Meta ID: {meta_id}")
    logger.info("=" * 80)


if __name__ == '__main__':
    import sys

    # 从命令行参数判断是否真实插入
    dry_run = '--real' not in sys.argv

    if dry_run:
        logger.info("执行 dry run 测试（添加 --real 参数可真实插入）")
        test_faq_ingestion(dry_run=True)
    else:
        logger.info("执行真实插入...")
        test_faq_ingestion(dry_run=False)