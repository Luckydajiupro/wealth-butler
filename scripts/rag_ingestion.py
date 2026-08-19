"""
RAG知识库切片入库脚本

功能：
1. 按照RAG切片入库策略.md要求处理7个源文件
2. 占位符清洗
3. 分文件类型切片（FAQ/产品/政策）
4. 生成1024维embedding（本地Ollama bge-m3）
5. 写入Milvus集合 + MySQL fin_knowledge_meta表
6. 支持幂等性（可重复执行）

责任人：李清华
创建时间：2026-08-17
"""
import os
import sys
import re
import json
import logging
import hashlib
from typing import List, Dict, Any, Tuple
from datetime import datetime

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

# 源文件目录
DATA_DIR = os.path.join(project_root, "")
FAQ_FILE = os.path.join(DATA_DIR, "公司信息/高频问答对.txt")
PRODUCT_FILE = os.path.join(DATA_DIR, "公司业务/个人理财产品手册.md")
POLICY_FILES = [
    os.path.join(DATA_DIR, "金融政策/反洗钱合规操作手册.md"),
    os.path.join(DATA_DIR, "金融政策/个人投资者适当性管理指南.md"),
    os.path.join(DATA_DIR, "金融政策/理财产品销售管理办法.md"),
    os.path.join(DATA_DIR, "用户研判规则/反洗钱可疑交易识别规则.md"),
    os.path.join(DATA_DIR, "用户研判规则/投资者风险画像研判规则.md"),
]

# 占位符替换词典（呼应RAG切片入库策略.md §4.1）
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


def compute_content_hash(content: str) -> str:
    """计算内容hash用于幂等性检查"""
    return hashlib.md5(content.encode('utf-8')).hexdigest()


def process_faq_file(file_path: str) -> List[Dict[str, Any]]:
    """
    处理FAQ文件
    格式：序号\t问题\t答案
    切片粒度：1行 = 1个chunk
    Embedding对象：question
    """
    logger.info(f"开始处理FAQ文件: {file_path}")

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 占位符清洗
    cleaned_content = clean_placeholder(content)

    chunks = []
    for line_no, line in enumerate(cleaned_content.strip().split('\n'), 1):
        if not line.strip():
            continue

        parts = line.split('\t')
        if len(parts) < 2:
            logger.warning(f"FAQ第{line_no}行格式不正确，跳过: {line[:50]}")
            continue

        # FAQ文件格式：问题\t答案（两列，无序号列）
        question, answer = parts[0], parts[1]

        chunk = {
            'title': question[:100],  # 截断至100字
            'question': question,
            'answer': answer,
            'text': question,  # FAQ用question做检索文本
            'source_file': os.path.basename(file_path),
            'knowledge_type': 'FAQ',
            'collection_name': 'fin_faq_collection',
            'metadata': {
                'question': question,
                'answer': answer,
                'source': os.path.basename(file_path),
                'seq_no': str(line_no)
            }
        }
        chunks.append(chunk)

    logger.info(f"FAQ文件切片完成，共{len(chunks)}条")
    return chunks


def process_product_file(file_path: str) -> List[Dict[str, Any]]:
    """
    处理产品手册文件
    切片粒度：按### 三级标题切分
    Embedding对象：content（整段markdown）
    """
    logger.info(f"开始处理产品文件: {file_path}")

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 占位符清洗
    cleaned_content = clean_placeholder(content)

    chunks = []
    lines = cleaned_content.split('\n')

    current_chapter = ""  # ## 二级标题
    current_section = ""  # ### 三级标题
    current_content = []

    for line in lines:
        # 匹配 ## 二级标题
        if line.startswith('## '):
            current_chapter = line[3:].strip()
            continue

        # 匹配 ### 三级标题
        if line.startswith('### '):
            # 保存前一个section
            if current_section and current_content:
                chunk = {
                    'title': current_section,
                    'text': '\n'.join(current_content),
                    'source_file': os.path.basename(file_path),
                    'knowledge_type': '产品说明书',
                    'collection_name': 'fin_product_collection',
                    'metadata': {
                        'title': current_section,
                        'chapter': current_chapter,
                        'source': os.path.basename(file_path),
                    }
                }
                chunks.append(chunk)

            # 开始新section
            current_section = line[4:].strip()
            current_content = []
            continue

        # 累积内容
        if current_section:
            current_content.append(line)

    # 保存最后一个section
    if current_section and current_content:
        chunk = {
            'title': current_section,
            'text': '\n'.join(current_content),
            'source_file': os.path.basename(file_path),
            'knowledge_type': '产品说明书',
            'collection_name': 'fin_product_collection',
            'metadata': {
                'title': current_section,
                'chapter': current_chapter,
                'source': os.path.basename(file_path),
            }
        }
        chunks.append(chunk)

    logger.info(f"产品文件切片完成，共{len(chunks)}条")
    return chunks


def process_policy_file(file_path: str) -> List[Dict[str, Any]]:
    """
    处理政策法规文件
    切片粒度：按### 条切分（或规则RW-XXX）
    Embedding对象：章/条前缀 + content
    """
    logger.info(f"开始处理政策文件: {file_path}")

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 占位符清洗
    cleaned_content = clean_placeholder(content)

    chunks = []
    lines = cleaned_content.split('\n')

    current_chapter = ""  # ## 第X章
    current_article = ""  # ### 第X条 或 规则RW-XXX
    current_content = []

    for line in lines:
        # 匹配 ## 章标题
        if line.startswith('## '):
            current_chapter = line[3:].strip()
            continue

        # 匹配 ### 条标题 或 规则标题
        if line.startswith('### '):
            # 保存前一条
            if current_article and current_content:
                # 拼接前缀：【章标题】条标题
                prefix = f"【{current_chapter}】{current_article}\n" if current_chapter else f"{current_article}\n"
                full_content = prefix + '\n'.join(current_content)

                chunk = {
                    'title': current_article,
                    'text': full_content,
                    'source_file': os.path.basename(file_path),
                    'knowledge_type': '政策法规',
                    'collection_name': 'fin_policy_collection',
                    'metadata': {
                        'title': current_article,
                        'chapter': current_chapter,
                        'policy_source': os.path.basename(file_path),
                        'source': os.path.basename(file_path),
                    }
                }
                chunks.append(chunk)

            # 开始新条
            current_article = line[4:].strip()
            current_content = []
            continue

        # 累积内容
        if current_article:
            current_content.append(line)

    # 保存最后一条
    if current_article and current_content:
        prefix = f"【{current_chapter}】{current_article}\n" if current_chapter else f"{current_article}\n"
        full_content = prefix + '\n'.join(current_content)

        chunk = {
            'title': current_article,
            'text': full_content,
            'source_file': os.path.basename(file_path),
            'knowledge_type': '政策法规',
            'collection_name': 'fin_policy_collection',
            'metadata': {
                'title': current_article,
                'chapter': current_chapter,
                'policy_source': os.path.basename(file_path),
                'source': os.path.basename(file_path),
            }
        }
        chunks.append(chunk)

    logger.info(f"政策文件切片完成，共{len(chunks)}条")
    return chunks


def insert_chunk_to_db(chunk: Dict[str, Any], db: MySQLClient) -> Tuple[bool, str]:
    """
    将单个chunk写入Milvus + MySQL

    流程（RAG切片入库策略.md §2④）：
    1. 生成embedding
    2. 写入MySQL fin_knowledge_meta，status='待入库'
    3. 写入对应Milvus集合
    4. 回填milvus_pk到MySQL，status='已上线'

    返回：(成功标志, 错误信息)
    """
    try:
        # 1. 生成embedding
        text_for_embedding = chunk.get('text', '')
        if not text_for_embedding.strip():
            return False, "文本为空，无法生成embedding"

        logger.info(f"正在为chunk生成embedding: {chunk['title'][:30]}...")
        embedding = ollama_embedding(text_for_embedding)

        # 2. 写入MySQL（先占位）
        meta_record = KnowledgeMetaModel(
            knowledge_type=chunk['knowledge_type'],
            collection_name=chunk['collection_name'],
            title=chunk['title'],
            source_file=chunk['source_file'],
            status='待审核',  # 初始状态
            uploaded_by=1,  # 系统管理员ID占位
            milvus_collection=chunk['collection_name'],
        )

        # 保存到MySQL
        meta_id = meta_record.save()
        if not meta_id:
            return False, "MySQL写入失败"

        logger.info(f"MySQL记录已创建，ID={meta_id}")

        # 3. 根据collection_name写入对应Milvus集合
        collection_name = chunk['collection_name']

        if collection_name == 'fin_faq_collection':
            # FAQ集合的metadata字段是str类型（JSON字符串）
            metadata_str = json.dumps(chunk['metadata'], ensure_ascii=False)
            model = FaqCollectionModelV2(
                text=chunk['text'],
                metadata=metadata_str,
                embedding=embedding
            )
        elif collection_name == 'fin_product_collection':
            # Product集合的metadata字段是dict类型
            model = ProductCollectionModelV2(
                text=chunk['text'],
                metadata=chunk['metadata'],
                embedding=embedding
            )
        elif collection_name == 'fin_policy_collection':
            # Policy集合的metadata字段是dict类型
            model = PolicyCollectionModelV2(
                text=chunk['text'],
                metadata=chunk['metadata'],
                embedding=embedding
            )
        else:
            return False, f"未知的collection_name: {collection_name}"

        # 插入Milvus（insert是类方法，需要传入实例列表）
        ModelClass = type(model)
        result = ModelClass.insert([model])

        if not result or not result.get('success') or result.get('insert_count', 0) == 0:
            return False, "Milvus插入失败"

        logger.info(f"Milvus插入成功，insert_count={result.get('insert_count')}")

        # 4. 更新MySQL状态为已上线
        # 注：MilvusClient的auto_id模式下不返回生成的主键ID
        # 4天工期取向：milvus_pk留空，通过collection_name+source_file+title组合定位
        update_sql = f"""
            UPDATE {KnowledgeMetaModel.table_alias}
            SET status = '已上线'
            WHERE id = %s
        """
        db.execute_sync(update_sql, (meta_id,))

        logger.info(f"✅ chunk入库成功: {chunk['title'][:30]} (MySQL ID={meta_id})")
        return True, ""

    except Exception as e:
        logger.error(f"❌ chunk入库失败: {chunk['title'][:30]}, 错误: {str(e)}")
        return False, str(e)


def check_existing_record(source_file: str, title: str, db: MySQLClient) -> bool:
    """
    幂等性检查：查询是否已存在相同的记录
    返回True表示已存在且无需重新入库
    """
    sql = f"""
        SELECT id, status FROM {KnowledgeMetaModel.table_alias}
        WHERE source_file = %s AND title = %s AND status = '已上线'
    """
    result = db.execute_sync(sql, (source_file, title))
    return len(result) > 0 if result else False


def clear_collection(collection_name: str):
    """清空指定集合的所有数据"""
    logger.info(f"开始清空集合: {collection_name}")

    try:
        if collection_name == 'fin_faq_collection':
            FaqCollectionModelV2.delete_all()
        elif collection_name == 'fin_product_collection':
            ProductCollectionModelV2.delete_all()
        elif collection_name == 'fin_policy_collection':
            PolicyCollectionModelV2.delete_all()

        logger.info(f"✅ 集合 {collection_name} 已清空")
    except Exception as e:
        logger.error(f"❌ 清空集合 {collection_name} 失败: {str(e)}")


def main():
    """主入库流程"""
    logger.info("=" * 60)
    logger.info("开始RAG知识库切片入库")
    logger.info("=" * 60)

    # 初始化数据库连接
    db = MySQLClient()
    db.connect()

    # 统计信息
    stats = {
        'faq': {'total': 0, 'success': 0, 'skip': 0, 'fail': 0},
        'product': {'total': 0, 'success': 0, 'skip': 0, 'fail': 0},
        'policy': {'total': 0, 'success': 0, 'skip': 0, 'fail': 0},
    }

    # 清空现有数据（按需求要求）
    logger.info("\n" + "=" * 60)
    logger.info("清空现有集合数据")
    logger.info("=" * 60)
    clear_collection('fin_faq_collection')
    clear_collection('fin_product_collection')
    clear_collection('fin_policy_collection')

    # 1. 处理FAQ文件
    logger.info("\n" + "=" * 60)
    logger.info("步骤1: 处理FAQ文件")
    logger.info("=" * 60)

    if os.path.exists(FAQ_FILE):
        faq_chunks = process_faq_file(FAQ_FILE)
        stats['faq']['total'] = len(faq_chunks)

        for idx, chunk in enumerate(faq_chunks, 1):
            logger.info(f"处理FAQ chunk {idx}/{len(faq_chunks)}")

            # 幂等性检查
            if check_existing_record(chunk['source_file'], chunk['title'], db):
                logger.info(f"跳过已存在的chunk: {chunk['title'][:30]}")
                stats['faq']['skip'] += 1
                continue

            success, error = insert_chunk_to_db(chunk, db)
            if success:
                stats['faq']['success'] += 1
            else:
                stats['faq']['fail'] += 1
                logger.error(f"入库失败: {error}")
    else:
        logger.warning(f"FAQ文件不存在: {FAQ_FILE}")

    # 2. 处理产品文件
    logger.info("\n" + "=" * 60)
    logger.info("步骤2: 处理产品文件")
    logger.info("=" * 60)

    if os.path.exists(PRODUCT_FILE):
        product_chunks = process_product_file(PRODUCT_FILE)
        stats['product']['total'] = len(product_chunks)

        for idx, chunk in enumerate(product_chunks, 1):
            logger.info(f"处理产品chunk {idx}/{len(product_chunks)}")

            if check_existing_record(chunk['source_file'], chunk['title'], db):
                logger.info(f"跳过已存在的chunk: {chunk['title'][:30]}")
                stats['product']['skip'] += 1
                continue

            success, error = insert_chunk_to_db(chunk, db)
            if success:
                stats['product']['success'] += 1
            else:
                stats['product']['fail'] += 1
                logger.error(f"入库失败: {error}")
    else:
        logger.warning(f"产品文件不存在: {PRODUCT_FILE}")

    # 3. 处理政策法规文件
    logger.info("\n" + "=" * 60)
    logger.info("步骤3: 处理政策法规文件")
    logger.info("=" * 60)

    for policy_file in POLICY_FILES:
        if not os.path.exists(policy_file):
            logger.warning(f"政策文件不存在: {policy_file}")
            continue

        policy_chunks = process_policy_file(policy_file)
        stats['policy']['total'] += len(policy_chunks)

        for idx, chunk in enumerate(policy_chunks, 1):
            logger.info(f"处理政策chunk {idx}/{len(policy_chunks)} from {os.path.basename(policy_file)}")

            if check_existing_record(chunk['source_file'], chunk['title'], db):
                logger.info(f"跳过已存在的chunk: {chunk['title'][:30]}")
                stats['policy']['skip'] += 1
                continue

            success, error = insert_chunk_to_db(chunk, db)
            if success:
                stats['policy']['success'] += 1
            else:
                stats['policy']['fail'] += 1
                logger.error(f"入库失败: {error}")

    # 打印统计报告
    logger.info("\n" + "=" * 60)
    logger.info("入库统计报告")
    logger.info("=" * 60)
    logger.info(f"FAQ集合: 总计{stats['faq']['total']}条, 成功{stats['faq']['success']}条, 跳过{stats['faq']['skip']}条, 失败{stats['faq']['fail']}条")
    logger.info(f"产品集合: 总计{stats['product']['total']}条, 成功{stats['product']['success']}条, 跳过{stats['product']['skip']}条, 失败{stats['product']['fail']}条")
    logger.info(f"政策集合: 总计{stats['policy']['total']}条, 成功{stats['policy']['success']}条, 跳过{stats['policy']['skip']}条, 失败{stats['policy']['fail']}条")
    logger.info("=" * 60)

    # 关闭数据库连接
    db.close()

    logger.info("RAG知识库切片入库完成！")


if __name__ == '__main__':
    main()
