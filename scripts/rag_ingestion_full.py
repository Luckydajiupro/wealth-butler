"""RAG 知识库完整入库脚本

严格按照 docs/RAG切片入库策略.md 实现：
1. 7个文件分类入库（FAQ/产品/政策）
2. 占位符清洗
3. 分文件类型切片：
   - FAQ：按行切片，只对 question 做 embedding
   - 产品说明书：按 ### 三级标题切片
   - 政策法规：按 ### 条切片，拼接章/条前缀
4. 插入 Milvus + MySQL 元数据

使用方式：
    python scripts/rag_ingestion_full.py --dry-run  # 测试不插入
    python scripts/rag_ingestion_full.py --real     # 真实插入
"""
import sys
import json
import re
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple

# 添加项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.Base.Client.ollamaClient import ollama_client
from app.Base.Client.milvusClient import MilvusClientSingleton
from app.Base.Client.minioClient import default_minio_client as minio_client
from app.WealthButler.Models.knowledgeMetaModel import KnowledgeMetaModel
from app.Base.Repository.base.baseDBModel import BaseDBModel
from app.Base.Repository.connections.mysqlConnection import MySQLConnection
from app.Base.Config.setting import settings

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================
# 配置
# ============================================================

# Milvus 客户端
milvus_client = MilvusClientSingleton()

# 占位符词典路径
PLACEHOLDER_FILE = project_root / 'scripts' / 'placeholder_dict.json'

# MinIO 桶名
MINIO_BUCKET = "fin-knowledge-raw"

# 源文档配置（按 RAG切片入库策略.md §1）
SOURCE_DOCS = {
    'FAQ': [
        'D:/lqh/金融/公司信息/高频问答对.txt'
    ],
    '产品说明书': [
        'D:/lqh/金融/公司业务/个人理财产品手册.md'
    ],
    '政策法规': [
        'D:/lqh/金融/金融政策/反洗钱合规操作手册.md',
        'D:/lqh/金融/金融政策/个人投资者适当性管理指南.md',
        'D:/lqh/金融/金融政策/理财产品销售管理办法.md',
        'D:/lqh/金融/用户研判规则/反洗钱可疑交易识别规则.md',
        'D:/lqh/金融/用户研判规则/投资者风险画像研判规则.md'
    ]
}

# Milvus 集合映射
COLLECTION_MAPPING = {
    'FAQ': 'fin_faq_collection',
    '产品说明书': 'fin_product_collection',
    '政策法规': 'fin_policy_collection'
}

# ============================================================
# 工具函数
# ============================================================

def load_placeholder_dict() -> dict:
    """加载占位符词典"""
    if PLACEHOLDER_FILE.exists():
        with open(PLACEHOLDER_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def clean_text(text: str, placeholder_dict: dict) -> str:
    """占位符清洗"""
    for placeholder, real_value in placeholder_dict.items():
        text = text.replace(placeholder, real_value)
    return text


def generate_embedding(text: str) -> List[float]:
    """生成向量（调用 Ollama bge-m3）"""
    embedding = ollama_client.get_embedding(text, model='bge-m3')
    if len(embedding) != 1024:
        raise ValueError(f"向量维度不匹配：期望 1024，实际 {len(embedding)}")
    return embedding


# ============================================================
# FAQ 处理（按 RAG切片入库策略.md §3.1）
# ============================================================

def parse_faq_file(file_path: str, placeholder_dict: dict) -> List[Dict]:
    """解析 FAQ 文件：制表符分隔（问题\\t答案），1行=1个chunk"""
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    chunks = []
    for line_num, line in enumerate(lines, 1):
        parts = line.strip().split('\t')
        if len(parts) != 2:
            logger.warning(f"跳过格式不正确的行 {line_num}")
            continue

        question = clean_text(parts[0].strip(), placeholder_dict)
        answer = clean_text(parts[1].strip(), placeholder_dict)

        if not question or not answer:
            continue

        chunks.append({
            'question': question,
            'answer': answer,
            'title': question[:100]  # 取问题前100字作为 title
        })

    logger.info(f"FAQ 切片完成：{len(chunks)} 条")
    return chunks


def faq_to_milvus_data(chunks: List[Dict], source_file: str) -> List[Dict]:
    """FAQ chunks 转 Milvus 插入格式

    只对 question 做 embedding（纯稠密检索）
    Schema: question, answer, source, category, updated_at, embedding (id auto)
    """
    data = []
    for chunk in chunks:
        # 只对 question 生成向量
        embedding = generate_embedding(chunk['question'])

        data.append({
            'question': chunk['question'][:500],
            'answer': chunk['answer'][:2000],
            'source': Path(source_file).name,
            'category': '公司信息',
            'updated_at': datetime.now().strftime('%Y-%m-%d'),
            'embedding': embedding
        })

    return data


# ============================================================
# 产品说明书处理（按 RAG切片入库策略.md §3.2）
# ============================================================

def parse_product_manual(file_path: str, placeholder_dict: dict) -> List[Dict]:
    """解析产品说明书：按 ### 三级标题切片"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    content = clean_text(content, placeholder_dict)

    # 按 ### 标题切分
    pattern = r'###\s+(.+?)\n(.*?)(?=###|\Z)'
    matches = re.findall(pattern, content, re.DOTALL)

    chunks = []
    for title, body in matches:
        title = title.strip()
        body = body.strip()

        if not body:
            continue

        chunks.append({
            'title': title,
            'content': f"### {title}\n\n{body}"
        })

    logger.info(f"产品说明书切片完成：{len(chunks)} 个段落")
    return chunks


def product_to_milvus_data(chunks: List[Dict], source_file: str) -> List[Dict]:
    """产品 chunks 转 Milvus 插入格式

    对 content 做 embedding（混合检索：稠密0.7+BM25稀疏0.3）
    Schema: product_name, product_code, content, product_type, risk_level,
            source, updated_at, embedding (id auto, content_sparse auto)
    """
    data = []
    for chunk in chunks:
        embedding = generate_embedding(chunk['content'])

        data.append({
            'product_name': chunk['title'][:200],
            'product_code': '',
            'content': chunk['content'][:65535],
            'product_type': '理财产品',
            'risk_level': 'R2',
            'source': Path(source_file).name,
            'updated_at': datetime.now().strftime('%Y-%m-%d'),
            'embedding': embedding
        })

    return data


# ============================================================
# 政策法规处理（按 RAG切片入库策略.md §3.3）
# ============================================================

def parse_policy_document(file_path: str, placeholder_dict: dict) -> List[Dict]:
    """解析政策法规：按 ### 条切片，拼接章/条前缀"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    content = clean_text(content, placeholder_dict)

    # 提取章标题（## 第X章）
    chapters = re.split(r'(##\s+第.+?章\s+.+?)\n', content)

    chunks = []
    current_chapter = ""

    for i in range(1, len(chapters), 2):
        if i >= len(chapters):
            break

        chapter_title = chapters[i].strip().replace('## ', '')
        chapter_content = chapters[i+1] if i+1 < len(chapters) else ""

        # 按 ### 条切分
        articles = re.split(r'(###\s+第.+?条\s+.+?)\n', chapter_content)

        for j in range(1, len(articles), 2):
            if j >= len(articles):
                break

            article_title = articles[j].strip().replace('### ', '')
            article_body = articles[j+1] if j+1 < len(articles) else ""
            article_body = article_body.strip()

            if not article_body:
                continue

            # 拼接前缀：【章标题】条标题\n正文
            full_content = f"【{chapter_title}】{article_title}\n\n{article_body}"

            chunks.append({
                'title': article_title,
                'content': full_content
            })

    logger.info(f"政策法规切片完成：{len(chunks)} 条")
    return chunks


def policy_to_milvus_data(chunks: List[Dict], source_file: str) -> List[Dict]:
    """政策 chunks 转 Milvus 插入格式

    对 content 做 embedding（混合检索：稠密0.7+BM25稀疏0.3）
    Schema: title, policy_no, content, category, issuer, effective_date,
            source, updated_at, embedding (id auto, content_sparse auto)
    """
    data = []
    for chunk in chunks:
        embedding = generate_embedding(chunk['content'])

        data.append({
            'title': chunk['title'][:500],
            'policy_no': '',
            'content': chunk['content'][:65535],
            'category': '监管政策',
            'issuer': '银保监会',
            'effective_date': '2024-01-01',
            'source': Path(source_file).name,
            'updated_at': datetime.now().strftime('%Y-%m-%d'),
            'embedding': embedding
        })

    return data


# ============================================================
# 主流程
# ============================================================

def process_file(file_path: str, knowledge_type: str, placeholder_dict: dict, dry_run: bool) -> Tuple[int, int]:
    """处理单个文件

    Returns:
        (meta_id, chunk_count)
    """
    logger.info("=" * 80)
    logger.info(f"处理文件: {file_path}")
    logger.info(f"知识类型: {knowledge_type}")
    logger.info("=" * 80)

    # 1. 切片
    if knowledge_type == 'FAQ':
        chunks = parse_faq_file(file_path, placeholder_dict)
        milvus_data = faq_to_milvus_data(chunks, file_path)
    elif knowledge_type == '产品说明书':
        chunks = parse_product_manual(file_path, placeholder_dict)
        milvus_data = product_to_milvus_data(chunks, file_path)
    elif knowledge_type == '政策法规':
        chunks = parse_policy_document(file_path, placeholder_dict)
        milvus_data = policy_to_milvus_data(chunks, file_path)
    else:
        raise ValueError(f"未知的知识类型: {knowledge_type}")

    if not milvus_data:
        logger.warning(f"文件切片为空，跳过: {file_path}")
        return (0, 0)

    logger.info(f"切片完成：{len(milvus_data)} 条")
    logger.info(f"示例数据:")
    logger.info(f"  Keys: {list(milvus_data[0].keys())}")
    logger.info(f"  First field value: {str(list(milvus_data[0].values())[0])[:100]}...")

    if dry_run:
        logger.info("[DRY RUN] 跳过实际插入")
        return (0, len(milvus_data))

    # 2. 插入 Milvus
    collection_name = COLLECTION_MAPPING[knowledge_type]
    logger.info(f"插入 Milvus: {collection_name}...")
    result = milvus_client.insert(
        collection_name=collection_name,
        data=milvus_data
    )
    pk_list = result.get('ids', []) if isinstance(result, dict) else []
    logger.info(f"✓ Milvus 插入成功：{len(pk_list)} 条")

    # 3. 写入 MySQL 元数据
    logger.info("写入 MySQL 元数据...")
    meta = KnowledgeMetaModel(
        knowledge_type=knowledge_type,
        collection_name=collection_name,
        title=Path(file_path).stem,
        source=file_path,
        version='1.0',
        file_path=file_path,
        chunk_count=len(milvus_data),
        status='已上线'
    )
    meta_id = meta.save()
    logger.info(f"✓ 元数据已保存: id={meta_id}\n")

    return (meta_id, len(milvus_data))


def main(dry_run: bool = True):
    """主入口"""
    logger.info("\n" + "=" * 80)
    logger.info(f"RAG 知识库完整入库脚本 (dry_run={dry_run})")
    logger.info("=" * 80 + "\n")

    # 1. 加载占位符词典
    placeholder_dict = load_placeholder_dict()
    logger.info(f"✓ 占位符词典已加载: {len(placeholder_dict)} 条规则\n")

    # 2. 初始化数据库连接
    if not dry_run:
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
        logger.info("✓ 数据库连接已初始化\n")

        # 检查 MinIO 桶（暂时跳过，专注 Milvus+MySQL 入库）
        # if not minio_client.client.bucket_exists(MINIO_BUCKET):
        #     minio_client.client.make_bucket(MINIO_BUCKET)
        #     logger.info(f"✓ MinIO 桶已创建: {MINIO_BUCKET}\n")
        logger.info("⚠ MinIO 原文归档暂时跳过\n")

    # 3. 处理所有文件
    total_files = 0
    total_chunks = 0

    for knowledge_type, file_list in SOURCE_DOCS.items():
        for file_path in file_list:
            if not Path(file_path).exists():
                logger.warning(f"文件不存在，跳过: {file_path}\n")
                continue

            try:
                meta_id, chunk_count = process_file(file_path, knowledge_type, placeholder_dict, dry_run)
                if chunk_count > 0:
                    total_files += 1
                    total_chunks += chunk_count
            except Exception as e:
                logger.error(f"处理文件失败: {file_path}, 错误: {e}", exc_info=True)

    # 4. 汇总统计
    logger.info("\n" + "=" * 80)
    logger.info("入库完成" if not dry_run else "测试完成")
    logger.info("=" * 80)
    logger.info(f"✓ 文档总数: {total_files}")
    logger.info(f"✓ 切片总数: {total_chunks}")
    logger.info("=" * 80 + "\n")


if __name__ == '__main__':
    dry_run = '--real' not in sys.argv

    if dry_run:
        logger.info("执行 dry run 测试（添加 --real 参数可真实插入）\n")
    else:
        logger.info("执行真实插入...\n")

    main(dry_run=dry_run)
