"""RAG 知识库切片入库脚本

根据 docs/RAG知识库切片与向量化策略.md 的规范，将源文档切片并写入三层存储：
1. MySQL fin_knowledge_meta 表（元数据）
2. Milvus 对应集合（向量 + 文本）
3. MinIO fin-documents 桶（原始文件）

使用本地 Ollama bge-m3 模型生成 1024 维向量。

运行方式：
    python scripts/rag_ingestion.py
"""
import os
import re
import json
import hashlib
import logging
from pathlib import Path
from typing import List, Dict, Tuple
from datetime import datetime

from app.Base.Client.ollamaClient import ollama_client
from app.Base.Client.minioClient import default_minio_client as minio_client
from app.Base.Client.milvusClient import milvus_client
from app.WealthButler.Models.knowledgeMetaModel import KnowledgeMetaModel
from app.Base.Repository.base.baseDBModel import BaseDBModel
from app.Base.Repository.base.mysqlConnection import MySQLConnection
from app.Base.Config.setting import settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================
# 配置常量
# ============================================================

# Ollama 模型配置
EMBEDDING_MODEL = "bge-m3:latest"
EMBEDDING_DIM = 1024

# MinIO 桶名
MINIO_BUCKET = "fin-documents"

# 源文档路径映射（相对于项目根目录）
SOURCE_DOCS = {
    'FAQ': [
        'docs/公司信息/高频问答对.txt'
    ],
    '产品说明书': [
        'docs/公司业务/个人理财产品手册.md'
    ],
    '政策法规': [
        'docs/金融政策/商业银行理财业务管理办法.pdf',
        'docs/金融政策/资管新规.pdf',
        'docs/金融政策/银行业消费者权益保护工作指引.pdf',
        'docs/金融政策/商业银行代理销售业务管理办法.pdf',
        'docs/金融政策/银行保险机构消费者权益保护管理办法.pdf'
    ]
}

# Milvus 集合映射
COLLECTION_MAPPING = {
    'FAQ': 'fin_faq_collection',
    '产品说明书': 'fin_product_collection',
    '政策法规': 'fin_policy_collection'
}

# 切片策略（字符数）
CHUNK_STRATEGIES = {
    'FAQ': {'size': 200, 'overlap': 0},      # FAQ 按条目切片，不重叠
    '产品说明书': {'size': 500, 'overlap': 50},  # 产品说明按章节切片
    '政策法规': {'size': 800, 'overlap': 100}   # 政策法规按段落切片
}


# ============================================================
# 工具函数
# ============================================================

def calculate_file_hash(file_path: str) -> str:
    """计算文件 SHA256 哈希值"""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def read_file_content(file_path: str) -> str:
    """读取文件内容（支持 txt/md，pdf 暂不处理）"""
    ext = Path(file_path).suffix.lower()

    if ext in ['.txt', '.md']:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    elif ext == '.pdf':
        # TODO: 使用 PyPDF2 或 pdfplumber 提取文本
        logger.warning(f"PDF 文件暂不支持：{file_path}")
        return ""
    else:
        logger.warning(f"不支持的文件格式：{file_path}")
        return ""


def chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    """文本切片（滑动窗口）

    Args:
        text: 原始文本
        chunk_size: 切片大小（字符数）
        overlap: 重叠字符数

    Returns:
        切片列表
    """
    if not text or chunk_size <= 0:
        return []

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        # 滑动窗口
        start += (chunk_size - overlap)

    return chunks


def chunk_faq(text: str) -> List[Dict[str, str]]:
    """FAQ 专用切片（按 Q&A 条目切分）

    假设格式：
        Q: 问题1
        A: 答案1

        Q: 问题2
        A: 答案2

    Returns:
        [{'question': '...', 'answer': '...', 'text': 'Q: ...\nA: ...'}]
    """
    chunks = []
    pattern = r'Q[:：]\s*(.*?)\s*A[:：]\s*(.*?)(?=\nQ[:：]|\Z)'

    matches = re.findall(pattern, text, re.DOTALL)

    for i, (question, answer) in enumerate(matches, 1):
        question = question.strip()
        answer = answer.strip()

        if question and answer:
            chunks.append({
                'question': question,
                'answer': answer,
                'text': f"Q: {question}\nA: {answer}",
                'index': i
            })

    logger.info(f"FAQ 切片完成：共 {len(chunks)} 条")
    return chunks


def get_embedding(text: str) -> List[float]:
    """调用 Ollama bge-m3 生成向量"""
    try:
        response = ollama_client.embed(EMBEDDING_MODEL, text)
        embedding = response['embeddings'][0]

        if len(embedding) != EMBEDDING_DIM:
            raise ValueError(f"向量维度不匹配：期望 {EMBEDDING_DIM}，实际 {len(embedding)}")

        return embedding

    except Exception as e:
        logger.error(f"向量生成失败: {e}")
        raise


def upload_to_minio(file_path: str, object_name: str) -> str:
    """上传文件到 MinIO

    Returns:
        MinIO 对象路径（用于 file_path 字段）
    """
    try:
        with open(file_path, 'rb') as f:
            file_data = f.read()
            file_size = len(file_data)

        # 使用底层 client.put_object
        minio_client.client.put_object(
            bucket_name=MINIO_BUCKET,
            object_name=object_name,
            data=f,
            length=file_size
        )

        minio_path = f"{MINIO_BUCKET}/{object_name}"
        logger.info(f"文件已上传到 MinIO: {minio_path}")
        return minio_path

    except Exception as e:
        logger.error(f"MinIO 上传失败: {e}")
        raise


def insert_to_milvus(collection_name: str, chunks: List[Dict]) -> List[int]:
    """批量插入 Milvus

    Args:
        collection_name: 集合名称
        chunks: 切片列表，每个元素包含 text, embedding, metadata

    Returns:
        插入的主键列表
    """
    if not chunks:
        return []

    try:
        # 准备数据
        embeddings = [chunk['embedding'] for chunk in chunks]
        texts = [chunk['text'] for chunk in chunks]
        metadatas = [json.dumps(chunk.get('metadata', {}), ensure_ascii=False) for chunk in chunks]

        # 插入
        result = milvus_client.insert(
            collection_name=collection_name,
            data=[embeddings, texts, metadatas]
        )

        # result 是字典，需要提取主键列表
        if isinstance(result, dict):
            pk_list = result.get('ids', [])
        else:
            pk_list = []

        logger.info(f"Milvus 插入成功：{collection_name}，{len(pk_list)} 条")
        return pk_list

    except Exception as e:
        logger.error(f"Milvus 插入失败: {e}")
        raise


# ============================================================
# 主流程
# ============================================================

def process_document(
    file_path: str,
    knowledge_type: str,
    collection_name: str
) -> Tuple[int, int]:
    """处理单个文档

    Returns:
        (meta_id, chunk_count)
    """
    logger.info("=" * 80)
    logger.info(f"处理文档: {file_path}")
    logger.info(f"知识类型: {knowledge_type}")
    logger.info("=" * 80)

    # 1. 读取文件内容
    content = read_file_content(file_path)
    if not content:
        logger.warning(f"文件内容为空，跳过: {file_path}")
        return (0, 0)

    # 2. 文本切片
    strategy = CHUNK_STRATEGIES[knowledge_type]

    if knowledge_type == 'FAQ':
        faq_chunks = chunk_faq(content)
        chunks_text = [item['text'] for item in faq_chunks]
    else:
        chunks_text = chunk_text(content, strategy['size'], strategy['overlap'])

    if not chunks_text:
        logger.warning(f"切片结果为空，跳过: {file_path}")
        return (0, 0)

    logger.info(f"切片完成：共 {len(chunks_text)} 片")

    # 3. 生成向量
    logger.info("生成向量...")
    chunks_with_embedding = []

    for i, text in enumerate(chunks_text, 1):
        embedding = get_embedding(text)
        chunks_with_embedding.append({
            'text': text,
            'embedding': embedding,
            'metadata': {
                'source': file_path,
                'chunk_index': i,
                'knowledge_type': knowledge_type
            }
        })

        if i % 10 == 0:
            logger.info(f"  已生成 {i}/{len(chunks_text)} 个向量...")

    logger.info(f"向量生成完成：{len(chunks_with_embedding)} 个")

    # 4. 上传原始文件到 MinIO
    file_name = Path(file_path).name
    file_hash = calculate_file_hash(file_path)
    object_name = f"{knowledge_type}/{file_hash[:8]}_{file_name}"
    minio_path = upload_to_minio(file_path, object_name)

    # 5. 插入 Milvus
    insert_to_milvus(collection_name, chunks_with_embedding)

    # 6. 写入 MySQL 元数据
    meta = KnowledgeMetaModel(
        knowledge_type=knowledge_type,
        collection_name=collection_name,
        title=Path(file_path).stem,
        source=file_path,
        version="1.0",
        file_path=minio_path,
        chunk_count=len(chunks_text),
        status="已上线"
    )

    meta_id = meta.save()
    logger.info(f"元数据已保存到 MySQL: id={meta_id}")

    logger.info(f"✓ 文档处理完成: {file_path}")
    logger.info(f"  - 切片数: {len(chunks_text)}")
    logger.info(f"  - Meta ID: {meta_id}")
    logger.info("")

    return (meta_id, len(chunks_text))


def main():
    """主入口"""
    logger.info("\n" + "=" * 80)
    logger.info("RAG 知识库切片入库脚本")
    logger.info("=" * 80 + "\n")

    # 初始化数据库连接
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

    # 检查 MinIO 桶
    if not minio_client.client.bucket_exists(MINIO_BUCKET):
        minio_client.client.make_bucket(MINIO_BUCKET)
        logger.info(f"✓ MinIO 桶已创建: {MINIO_BUCKET}")
    else:
        logger.info(f"✓ MinIO 桶已存在: {MINIO_BUCKET}")

    # 处理所有文档
    total_files = 0
    total_chunks = 0

    for knowledge_type, file_list in SOURCE_DOCS.items():
        collection_name = COLLECTION_MAPPING[knowledge_type]

        for file_path in file_list:
            if not os.path.exists(file_path):
                logger.warning(f"文件不存在，跳过: {file_path}")
                continue

            try:
                meta_id, chunk_count = process_document(
                    file_path=file_path,
                    knowledge_type=knowledge_type,
                    collection_name=collection_name
                )

                if meta_id > 0:
                    total_files += 1
                    total_chunks += chunk_count

            except Exception as e:
                logger.error(f"处理文档失败: {file_path}, 错误: {e}", exc_info=True)

    # 汇总统计
    logger.info("\n" + "=" * 80)
    logger.info("入库完成")
    logger.info("=" * 80)
    logger.info(f"✓ 文档总数: {total_files}")
    logger.info(f"✓ 切片总数: {total_chunks}")
    logger.info("=" * 80 + "\n")


if __name__ == '__main__':
    main()
