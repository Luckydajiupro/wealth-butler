#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RAG知识库切片入库脚本（完整版，符合docs/RAG切片入库策略.md规范）

功能：
1. 占位符清洗（placeholder_dict.json）
2. 按文档规范切片：
   - FAQ：1行1chunk，只对question做embedding
   - 产品手册：按###三级标题切分
   - 政策文档：按###条/规则切分，带章节前缀
3. 生成embedding（Ollama bge-m3）
4. 写入MySQL fin_knowledge_meta + Milvus集合
5. 幂等性支持（source_file+title去重）

Author: 李清华
Date: 2026-08-15
"""

import sys
import os
import re
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime

# 添加项目根目录到sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.Base.Client.ollamaClient import ollama_client
from app.Base.Client.milvusClient import MilvusClientSingleton
from app.WealthButler.Repository.faqCollectionModelV2 import FaqCollectionModelV2
from app.WealthButler.Repository.productCollectionModelV2 import ProductCollectionModelV2
from app.WealthButler.Repository.policyCollectionModelV2 import PolicyCollectionModelV2
from app.Base.Config.setting import settings
import pymysql

# 全局客户端
milvus_client = MilvusClientSingleton()


def get_mysql_connection():
    """获取MySQL连接"""
    return pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=str(settings.mysql.password),
        database=settings.mysql.name,
        charset='utf8mb4'
    )


def load_placeholder_dict(dict_path: str = "scripts/placeholder_dict.json") -> Dict[str, str]:
    """加载占位符替换词典"""
    full_path = project_root / dict_path
    with open(full_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def clean_placeholders(text: str, placeholder_dict: Dict[str, str]) -> str:
    """占位符清洗：按词典逐条替换"""
    for placeholder, replacement in placeholder_dict.items():
        text = text.replace(placeholder, replacement)
    return text


def compute_content_hash(content: str) -> str:
    """计算内容hash（用于幂等性判断）"""
    return hashlib.md5(content.encode('utf-8')).hexdigest()


def get_embedding(text: str) -> List[float]:
    """调用Ollama生成embedding"""
    try:
        resp = ollama_client.get_embedding(text, model="bge-m3")
        return resp
    except Exception as e:
        print(f"❌ Embedding生成失败: {e}")
        return [0.0] * 1024  # 返回零向量作为降级


def check_existing_chunk(cursor, source_file: str, title: str) -> Optional[int]:
    """
    检查MySQL是否已存在该chunk（幂等性）
    返回：已存在且status='已上线' → meta_id；否则 → None
    """
    sql = """
        SELECT id FROM fin_knowledge_meta
        WHERE file_path = %s AND title = %s AND status = '已上线'
        LIMIT 1
    """
    cursor.execute(sql, (source_file, title))
    row = cursor.fetchone()
    return row[0] if row else None


def insert_chunk_to_mysql(cursor, knowledge_type: str, source_file: str,
                          title: str, content: str, collection_name: str) -> int:
    """
    插入MySQL fin_knowledge_meta，返回自增id
    """
    sql = """
        INSERT INTO fin_knowledge_meta
        (knowledge_type, collection_name, title, file_path, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, '已上线', NOW(), NOW())
    """
    cursor.execute(sql, (
        knowledge_type,
        collection_name,
        title[:200],  # 截断至字段长度
        source_file
    ))
    return cursor.lastrowid


def update_chunk_status(cursor, meta_id: int, milvus_pk: str):
    """更新chunk计数（简化版，不回填milvus_pk因为表中没这个字段）"""
    # 表中没有milvus_pk字段，只更新updated_at
    sql = """
        UPDATE fin_knowledge_meta
        SET updated_at = NOW()
        WHERE id = %s
    """
    cursor.execute(sql, (meta_id,))


# ============================================================
# FAQ切片：1行1chunk，只对question做embedding
# ============================================================

def chunk_faq(file_path: str, placeholder_dict: Dict) -> List[Dict]:
    """
    切片FAQ文件（制表符分隔：问题\t答案）
    按规范：1行1chunk，只对question做embedding
    """
    chunks = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            parts = line.split('\t')
            if len(parts) < 2:
                print(f"[WARN] FAQ第{line_no}行格式异常，跳过: {line[:50]}")
                continue

            question, answer = parts[0], parts[1]

            # 占位符清洗
            question_clean = clean_placeholders(question, placeholder_dict)
            answer_clean = clean_placeholders(answer, placeholder_dict)

            chunks.append({
                'title': question_clean[:100],  # 标题取问题前100字
                'question': question_clean,
                'answer': answer_clean,
                'embedding_text': question_clean,  # 只对question做embedding
            })

    return chunks


def ingest_faq(faq_chunks: List[Dict], source_file: str):
    """FAQ入库"""
    conn = get_mysql_connection()
    cursor = conn.cursor()

    success_count = 0
    skip_count = 0

    for chunk in faq_chunks:
        title = chunk['title']

        # 幂等性检查
        existing_id = check_existing_chunk(cursor, source_file, title)
        if existing_id:
            skip_count += 1
            continue

        # 生成embedding
        embedding = get_embedding(chunk['embedding_text'])

        # 插入MySQL
        meta_id = insert_chunk_to_mysql(
            cursor,
            knowledge_type='FAQ',
            source_file=source_file,
            title=title,
            content=chunk['question'] + '\n' + chunk['answer'],
            collection_name='fin_faq_collection'
        )

        # 插入Milvus
        try:
            metadata_dict = {
                'question': chunk['question'],
                'answer': chunk['answer'],
                'meta_id': meta_id
            }

            # 创建Pydantic模型实例（不设置id字段）
            faq_instance = FaqCollectionModelV2(
                text=chunk['question'],  # 主文本字段存question
                metadata=json.dumps(metadata_dict, ensure_ascii=False),  # FAQ模型的metadata是str类型
                embedding=embedding
            )

            result = FaqCollectionModelV2.insert([faq_instance])
            milvus_pk = str(result['ids'][0]) if result.get('ids') else str(result.get('insert_count', ''))

            # 回填MySQL
            update_chunk_status(cursor, meta_id, milvus_pk)
            conn.commit()
            success_count += 1

        except Exception as e:
            print(f"[ERROR] FAQ插入Milvus失败 [{title}]: {type(e).__name__}: {str(e)}")
            conn.rollback()
            continue

    print(f"[OK] FAQ入库完成: 成功{success_count}条, 跳过{skip_count}条")
    cursor.close()
    conn.close()


# ============================================================
# 产品手册切片：按###三级标题切分
# ============================================================

def chunk_product_manual(file_path: str, placeholder_dict: Dict) -> List[Dict]:
    """
    切片产品手册Markdown
    按规范：以###三级标题为切分单元，保留完整的参数表格+投资策略+适合人群
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 占位符清洗
    content = clean_placeholders(content, placeholder_dict)

    chunks = []

    # 按###切分
    sections = re.split(r'\n###\s+', content)

    # 保留当前##二级标题上下文
    current_h2 = ""

    for section in sections:
        if not section.strip():
            continue

        # 检查是否是新的##二级标题
        h2_match = re.match(r'^##\s+(.+)', section)
        if h2_match:
            current_h2 = h2_match.group(1).strip()
            # 继续处理该section中的###
            section = section[h2_match.end():]

        # 提取###标题
        lines = section.split('\n')
        h3_title = lines[0].strip() if lines else ""

        if not h3_title:
            continue

        # 内容从第二行开始
        chunk_content = '\n'.join(lines[1:]).strip()

        if not chunk_content:
            continue

        # 尝试提取product_id（如果标题中有产品代码格式）
        product_id = None
        # 简单规则：如果标题中有括号包裹的代码（如"XX基金(FD001)"）
        code_match = re.search(r'\(([A-Z]{2}\d{3,})\)', h3_title)
        if code_match:
            product_id = code_match.group(1)

        chunks.append({
            'title': h3_title,
            'product_id': product_id,
            'content': chunk_content,
            'category': current_h2,  # 保留所属大类
            'embedding_text': chunk_content,  # 对content做embedding
        })

    return chunks


def ingest_product_manual(chunks: List[Dict], source_file: str):
    """产品手册入库"""
    conn = get_mysql_connection()
    cursor = conn.cursor()

    success_count = 0
    skip_count = 0

    for chunk in chunks:
        title = chunk['title']

        # 幂等性检查
        existing_id = check_existing_chunk(cursor, source_file, title)
        if existing_id:
            skip_count += 1
            continue

        # 生成embedding
        embedding = get_embedding(chunk['embedding_text'])

        # 插入MySQL
        meta_id = insert_chunk_to_mysql(
            cursor,
            knowledge_type='产品说明书',
            source_file=source_file,
            title=title,
            content=chunk['content'],
            collection_name='fin_product_collection'
        )

        # 插入Milvus
        try:
            metadata_dict = {
                'product_id': chunk['product_id'],
                'category': chunk['category'],
                'title': title,
                'meta_id': meta_id
            }

            # 创建Pydantic模型实例（不设置id字段）
            product_instance = ProductCollectionModelV2(
                text=chunk['content'],
                metadata=metadata_dict,  # 直接传dict，不要json.dumps
                embedding=embedding
            )

            result = ProductCollectionModelV2.insert([product_instance])
            milvus_pk = str(result['ids'][0]) if result.get('ids') else str(result.get('insert_count', ''))

            # 回填MySQL
            update_chunk_status(cursor, meta_id, milvus_pk)
            conn.commit()
            success_count += 1

        except Exception as e:
            print(f"[ERROR] 产品手册插入Milvus失败 [{title}]: {e}")
            conn.rollback()
            continue

    print(f"[OK] 产品手册入库完成: 成功{success_count}条, 跳过{skip_count}条")
    cursor.close()
    conn.close()


# ============================================================
# 政策文档切片：按###条/规则切分，带章节前缀
# ============================================================

def chunk_policy_doc(file_path: str, placeholder_dict: Dict) -> List[Dict]:
    """
    切片政策文档Markdown
    按规范：以###（第X条/规则RW-XXX）为主切分单元
    - 超过1500字按####小节拆分
    - 拼接章/条前缀到content
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 占位符清洗
    content = clean_placeholders(content, placeholder_dict)

    chunks = []

    # 按###切分
    sections = re.split(r'\n###\s+', content)

    # 保留当前##章标题上下文
    current_chapter = ""

    for section in sections:
        if not section.strip():
            continue

        # 检查是否是新的##章标题
        h2_match = re.match(r'^##\s+(.+)', section)
        if h2_match:
            current_chapter = h2_match.group(1).strip()
            section = section[h2_match.end():]

        lines = section.split('\n')
        h3_title = lines[0].strip() if lines else ""

        if not h3_title:
            continue

        # 内容从第二行开始
        raw_content = '\n'.join(lines[1:]).strip()

        if not raw_content:
            continue

        # 检查是否需要按####小节拆分（超过1500字）
        if len(raw_content) > 1500:
            # 按####拆分
            subsections = re.split(r'\n####\s+', raw_content)

            for idx, subsec in enumerate(subsections):
                if not subsec.strip():
                    continue

                sub_lines = subsec.split('\n')
                h4_title = sub_lines[0].strip() if sub_lines else f"{idx+1}"
                sub_content = '\n'.join(sub_lines[1:]).strip()

                if not sub_content:
                    continue

                # 拼接前缀
                prefixed_content = f"【{current_chapter}】{h3_title}\n{h4_title}\n{sub_content}"

                chunks.append({
                    'title': f"{h3_title} - {h4_title}",
                    'policy_source': Path(file_path).name,
                    'content': prefixed_content,
                    'embedding_text': prefixed_content,
                })
        else:
            # 不拆分，整条作为一个chunk
            prefixed_content = f"【{current_chapter}】{h3_title}\n{raw_content}"

            chunks.append({
                'title': h3_title,
                'policy_source': Path(file_path).name,
                'content': prefixed_content,
                'embedding_text': prefixed_content,
            })

    return chunks


def ingest_policy_docs(chunks: List[Dict], source_file: str):
    """政策文档入库"""
    conn = get_mysql_connection()
    cursor = conn.cursor()

    success_count = 0
    skip_count = 0

    for chunk in chunks:
        title = chunk['title']

        # 幂等性检查
        existing_id = check_existing_chunk(cursor, source_file, title)
        if existing_id:
            skip_count += 1
            continue

        # 生成embedding
        embedding = get_embedding(chunk['embedding_text'])

        # 插入MySQL
        meta_id = insert_chunk_to_mysql(
            cursor,
            knowledge_type='政策法规',
            source_file=source_file,
            title=title,
            content=chunk['content'],
            collection_name='fin_policy_collection'
        )

        # 插入Milvus
        try:
            metadata_dict = {
                'policy_source': chunk['policy_source'],
                'title': title,
                'meta_id': meta_id
            }

            # 创建Pydantic模型实例（不设置id字段）
            policy_instance = PolicyCollectionModelV2(
                text=chunk['content'],
                metadata=metadata_dict,  # 直接传dict，不要json.dumps
                embedding=embedding
            )

            result = PolicyCollectionModelV2.insert([policy_instance])
            milvus_pk = str(result['ids'][0]) if result.get('ids') else str(result.get('insert_count', ''))

            # 回填MySQL
            update_chunk_status(cursor, meta_id, milvus_pk)
            conn.commit()
            success_count += 1

        except Exception as e:
            print(f"[ERROR] 政策文档插入Milvus失败 [{title}]: {e}")
            conn.rollback()
            continue

    print(f"[OK] 政策文档入库完成: 成功{success_count}条, 跳过{skip_count}条")
    cursor.close()
    conn.close()


# ============================================================
# 主流程
# ============================================================

def main():
    """主入库流程"""
    print("=" * 60)
    print("RAG知识库切片入库（完整规范版）")
    print("=" * 60)

    # 加载占位符词典
    placeholder_dict = load_placeholder_dict()
    print(f"[OK] 加载占位符词典: {len(placeholder_dict)}条")

    # 数据文件在项目根目录，不在data子目录
    data_dir = project_root

    # ========== 1. FAQ入库 ==========
    print("\n[1/3] 处理FAQ...")
    faq_file = data_dir / "公司信息" / "高频问答对.txt"
    if faq_file.exists():
        faq_chunks = chunk_faq(str(faq_file), placeholder_dict)
        print(f"   切片完成: {len(faq_chunks)}条")
        ingest_faq(faq_chunks, "高频问答对.txt")
    else:
        print(f"   [WARN] 文件不存在: {faq_file}")

    # ========== 2. 产品手册入库 ==========
    print("\n[2/3] 处理产品手册...")
    product_file = data_dir / "公司业务" / "个人理财产品手册.md"
    if product_file.exists():
        product_chunks = chunk_product_manual(str(product_file), placeholder_dict)
        print(f"   切片完成: {len(product_chunks)}条")
        ingest_product_manual(product_chunks, "个人理财产品手册.md")
    else:
        print(f"   [WARN] 文件不存在: {product_file}")

    # ========== 3. 政策文档入库 ==========
    print("\n[3/3] 处理政策文档...")
    policy_files = [
        data_dir / "金融政策" / "反洗钱合规操作手册.md",
        data_dir / "金融政策" / "个人投资者适当性管理指南.md",
        data_dir / "金融政策" / "理财产品销售管理办法.md",
        data_dir / "用户研判规则" / "反洗钱可疑交易识别规则.md",
        data_dir / "用户研判规则" / "投资者风险画像研判规则.md",
    ]

    for policy_file in policy_files:
        if policy_file.exists():
            print(f"\n   处理: {policy_file.name}")
            policy_chunks = chunk_policy_doc(str(policy_file), placeholder_dict)
            print(f"   切片完成: {len(policy_chunks)}条")
            ingest_policy_docs(policy_chunks, policy_file.name)
        else:
            print(f"   [WARN] 文件不存在: {policy_file}")

    print("\n" + "=" * 60)
    print("[SUCCESS] 全部入库完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
