#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""清理向量库并重新入库 - Phase 5 数据重建专用脚本

只清理向量数据，不删除集合结构。按照RAG切片入库策略重新入库：
- FAQ: 39条问答对
- 产品: 按###三级标题切分
- 政策: 5份文档按条文切分

严格遵循：
1. 稠密向量1024维 (Ollama bge-m3)
2. 稀疏向量BM25自动生成
3. 元数据字段完整
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from app.Base.Client.milvusClient import MilvusClientSingleton
from app.Base.Client.mysqlClient import MySQLClient
from app.Base.Ai.llms.ollamaEmbedding import ollama_embedding
import json
import re
from datetime import datetime
from typing import List, Dict, Any

# 初始化客户端
milvus_client = MilvusClientSingleton().get_client()
mysql_client = MySQLClient()

COLLECTIONS = ['fin_faq_collection', 'fin_product_collection', 'fin_policy_collection']
NAMESPACE = "WB-SEED-20260817"

# 占位符清洗词典
PLACEHOLDER_DICT = {
    r'XX科技(?:（有限公司）)?': '锦鹏科技有限公司',
    r'XX Tech Co\., Ltd\.': 'Jinpeng Tech Co., Ltd.',
    r'www\.xxtech\.com': 'www.jinpengtech.com',
    r'400-XXX-XXXX': '400-822-6699',
    r'某市': '临江市',
    r'20XX年X月XX日': '2014年6月18日',
    r'X亿元(?:（XX,XXX万元）)?': '8亿元（80,000万元）',
    r'X,XXX人': '3,200人',
}


def clean_placeholder(text: str) -> str:
    """清洗占位符"""
    for pattern, replacement in PLACEHOLDER_DICT.items():
        text = re.sub(pattern, replacement, text)
    return text


def clean_collections():
    """清理三个集合的数据（不删除集合结构）"""
    print("\n" + "="*80)
    print("第1步：清理Milvus集合数据")
    print("="*80)

    for coll_name in COLLECTIONS:
        try:
            stats = milvus_client.get_collection_stats(coll_name)
            row_count = stats.get("row_count", 0)
            print(f"\n[INFO] {coll_name}: 当前 {row_count} 条记录")

            if row_count > 0:
                # 删除所有数据（Milvus 2.3+ 使用 delete with expr ""）
                milvus_client.delete(
                    collection_name=coll_name,
                    expr="id > 0"  # 删除所有记录
                )
                print(f"[SUCCESS] {coll_name}: 已清理所有数据")
            else:
                print(f"[INFO] {coll_name}: 已经是空集合")
        except Exception as e:
            print(f"[ERROR] {coll_name}: 清理失败 - {str(e)}")


def clean_mysql_metadata():
    """清理MySQL fin_knowledge_meta表"""
    print("\n" + "="*80)
    print("第2步：清理MySQL元数据")
    print("="*80)

    try:
        # 查询当前记录数
        result = mysql_client.execute_sync(
            "SELECT COUNT(*) as cnt FROM fin_knowledge_meta WHERE deleted_at IS NULL"
        )
        count = result[0]['cnt'] if result else 0
        print(f"\n[INFO] fin_knowledge_meta: 当前 {count} 条记录")

        if count > 0:
            # 软删除（设置deleted_at）
            affected = mysql_client.execute_sync("""
                UPDATE fin_knowledge_meta
                SET deleted_at = NOW(), status = '已下线'
                WHERE deleted_at IS NULL
            """)
            print(f"[SUCCESS] fin_knowledge_meta: 已软删除 {affected} 条记录")
        else:
            print(f"[INFO] fin_knowledge_meta: 已经是空表")
    except Exception as e:
        print(f"[ERROR] fin_knowledge_meta: 清理失败 - {str(e)}")


def ingest_faq():
    """入库FAQ数据：高频问答对.txt"""
    print("\n" + "="*80)
    print("第3步：入库FAQ数据")
    print("="*80)

    faq_file = project_root / "公司信息" / "高频问答对.txt"
    if not faq_file.exists():
        print(f"[ERROR] FAQ文件不存在: {faq_file}")
        return

    with open(faq_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    inserted_count = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue

        parts = line.split('\t')
        if len(parts) < 3:
            continue

        seq, question, answer = parts[0], parts[1], parts[2]

        # 清洗占位符
        question = clean_placeholder(question)
        answer = clean_placeholder(answer)

        # 生成embedding
        try:
            embedding = ollama_embedding(question)
            if len(embedding) != 1024:
                print(f"[WARNING] FAQ #{seq}: embedding维度错误 {len(embedding)}, 跳过")
                continue
        except Exception as e:
            print(f"[ERROR] FAQ #{seq}: embedding生成失败 - {str(e)}")
            continue

        # 插入MySQL元数据
        try:
            result = mysql_client.execute_sync("""
                INSERT INTO fin_knowledge_meta
                (knowledge_type, title, source_file, extra_data, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            """, (
                'FAQ',
                question[:100],  # title截断至100字
                '高频问答对.txt',
                json.dumps({'namespace': NAMESPACE, 'seq': seq}, ensure_ascii=False),
                '已入库'
            ))

            # 获取插入的ID
            id_result = mysql_client.execute_sync("SELECT LAST_INSERT_ID() as id")
            meta_id = id_result[0]['id']
        except Exception as e:
            print(f"[ERROR] FAQ #{seq}: MySQL插入失败 - {str(e)}")
            continue

        # 插入Milvus
        try:
            milvus_data = [{
                "content_dense": embedding,
                "question": question,
                "answer": answer,
                "source_file": "高频问答对.txt",
                "knowledge_type": "FAQ",
                "meta_id": meta_id
            }]

            result = milvus_client.insert(
                collection_name='fin_faq_collection',
                data=milvus_data
            )

            # 回填milvus_pk
            milvus_pk = result['ids'][0] if result.get('ids') else None
            if milvus_pk:
                mysql_client.execute_sync(
                    "UPDATE fin_knowledge_meta SET milvus_pk = %s WHERE id = %s",
                    (str(milvus_pk), meta_id)
                )

            inserted_count += 1
            print(f"[SUCCESS] FAQ #{seq}: 已入库 (meta_id={meta_id}, milvus_pk={milvus_pk})")
        except Exception as e:
            print(f"[ERROR] FAQ #{seq}: Milvus插入失败 - {str(e)}")

    print(f"\n[SUMMARY] FAQ入库完成: {inserted_count}/39 条")


def ingest_products():
    """入库产品数据：个人理财产品手册.md"""
    print("\n" + "="*80)
    print("第4步：入库产品数据")
    print("="*80)

    product_file = project_root / "公司业务" / "个人理财产品手册.md"
    if not product_file.exists():
        print(f"[ERROR] 产品文件不存在: {product_file}")
        return

    with open(product_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 清洗占位符
    content = clean_placeholder(content)

    # 按###三级标题切分
    chunks = []
    current_h2 = ""

    lines = content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # 记录二级标题（章）
        if line.startswith('## '):
            current_h2 = line[3:].strip()
            i += 1
            continue

        # 三级标题（产品/小节）
        if line.startswith('### '):
            title = line[4:].strip()
            chunk_content = []
            i += 1

            # 收集该小节的内容直到下一个标题
            while i < len(lines):
                next_line = lines[i].strip()
                if next_line.startswith('##'):
                    break
                chunk_content.append(lines[i])
                i += 1

            chunk_text = '\n'.join(chunk_content).strip()
            if chunk_text:
                chunks.append({
                    'title': title,
                    'content': f"【{current_h2}】{title}\n\n{chunk_text}",
                    'h2': current_h2
                })
        else:
            i += 1

    print(f"[INFO] 产品手册切分为 {len(chunks)} 个chunk")

    inserted_count = 0
    for idx, chunk in enumerate(chunks, 1):
        # 生成embedding
        try:
            embedding = ollama_embedding(chunk['content'])
            if len(embedding) != 1024:
                print(f"[WARNING] 产品chunk #{idx}: embedding维度错误 {len(embedding)}, 跳过")
                continue
        except Exception as e:
            print(f"[ERROR] 产品chunk #{idx}: embedding生成失败 - {str(e)}")
            continue

        # 插入MySQL元数据
        try:
            mysql_client.execute_sync("""
                INSERT INTO fin_knowledge_meta
                (knowledge_type, title, source_file, extra_data, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            """, (
                '产品说明',
                chunk['title'][:100],
                '个人理财产品手册.md',
                json.dumps({'namespace': NAMESPACE, 'h2': chunk['h2']}, ensure_ascii=False),
                '已入库'
            ))

            id_result = mysql_client.execute_sync("SELECT LAST_INSERT_ID() as id")
            meta_id = id_result[0]['id']
        except Exception as e:
            print(f"[ERROR] 产品chunk #{idx}: MySQL插入失败 - {str(e)}")
            continue

        # 插入Milvus（混合检索：稠密+稀疏）
        try:
            milvus_data = [{
                "content_dense": embedding,
                "content": chunk['content'],  # BM25稀疏向量由Milvus自动生成
                "title": chunk['title'],
                "source_file": "个人理财产品手册.md",
                "knowledge_type": "产品说明",
                "meta_id": meta_id
            }]

            result = milvus_client.insert(
                collection_name='fin_product_collection',
                data=milvus_data
            )

            # 回填milvus_pk
            milvus_pk = result['ids'][0] if result.get('ids') else None
            if milvus_pk:
                mysql_client.execute_sync(
                    "UPDATE fin_knowledge_meta SET milvus_pk = %s WHERE id = %s",
                    (str(milvus_pk), meta_id)
                )

            inserted_count += 1
            if idx % 5 == 0:
                print(f"[PROGRESS] 产品chunk: {idx}/{len(chunks)}")
        except Exception as e:
            print(f"[ERROR] 产品chunk #{idx}: Milvus插入失败 - {str(e)}")

    print(f"\n[SUMMARY] 产品入库完成: {inserted_count}/{len(chunks)} 条")


def ingest_policies():
    """入库政策数据：5份文档"""
    print("\n" + "="*80)
    print("第5步：入库政策数据")
    print("="*80)

    policy_files = [
        project_root / "金融政策" / "反洗钱合规操作手册.md",
        project_root / "金融政策" / "个人投资者适当性管理指南.md",
        project_root / "金融政策" / "理财产品销售管理办法.md",
        project_root / "用户研判规则" / "反洗钱可疑交易识别规则.md",
        project_root / "用户研判规则" / "投资者风险画像研判规则.md",
    ]

    total_inserted = 0

    for policy_file in policy_files:
        if not policy_file.exists():
            print(f"[WARNING] 政策文件不存在: {policy_file.name}, 跳过")
            continue

        print(f"\n[INFO] 处理文件: {policy_file.name}")

        with open(policy_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # 清洗占位符
        content = clean_placeholder(content)

        # 按###条文切分
        chunks = []
        current_h2 = ""

        lines = content.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # 记录二级标题（章）
            if line.startswith('## '):
                current_h2 = line[3:].strip()
                i += 1
                continue

            # 三级标题（条文）
            if line.startswith('### '):
                title = line[4:].strip()
                chunk_content = []
                i += 1

                # 收集该条文的内容
                while i < len(lines):
                    next_line = lines[i].strip()
                    if next_line.startswith('##'):
                        break
                    chunk_content.append(lines[i])
                    i += 1

                chunk_text = '\n'.join(chunk_content).strip()
                if chunk_text:
                    # 拼接章/条前缀
                    full_content = f"【{current_h2}】{title}\n\n{chunk_text}"
                    chunks.append({
                        'title': title,
                        'content': full_content,
                        'h2': current_h2,
                        'source_file': policy_file.name
                    })
            else:
                i += 1

        print(f"[INFO] {policy_file.name} 切分为 {len(chunks)} 个chunk")

        # 入库每个chunk
        for idx, chunk in enumerate(chunks, 1):
            # 生成embedding
            try:
                embedding = ollama_embedding(chunk['content'])
                if len(embedding) != 1024:
                    print(f"[WARNING] {policy_file.name} chunk #{idx}: embedding维度错误, 跳过")
                    continue
            except Exception as e:
                print(f"[ERROR] {policy_file.name} chunk #{idx}: embedding失败 - {str(e)}")
                continue

            # 插入MySQL元数据
            try:
                mysql_client.execute_sync("""
                    INSERT INTO fin_knowledge_meta
                    (knowledge_type, title, source_file, extra_data, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                """, (
                    '政策法规',
                    chunk['title'][:100],
                    chunk['source_file'],
                    json.dumps({'namespace': NAMESPACE, 'h2': chunk['h2']}, ensure_ascii=False),
                    '已入库'
                ))

                id_result = mysql_client.execute_sync("SELECT LAST_INSERT_ID() as id")
                meta_id = id_result[0]['id']
            except Exception as e:
                print(f"[ERROR] {policy_file.name} chunk #{idx}: MySQL插入失败 - {str(e)}")
                continue

            # 插入Milvus（混合检索）
            try:
                milvus_data = [{
                    "content_dense": embedding,
                    "content": chunk['content'],
                    "title": chunk['title'],
                    "policy_source": chunk['source_file'],
                    "source_file": chunk['source_file'],
                    "knowledge_type": "政策法规",
                    "meta_id": meta_id
                }]

                result = milvus_client.insert(
                    collection_name='fin_policy_collection',
                    data=milvus_data
                )

                # 回填milvus_pk
                milvus_pk = result['ids'][0] if result.get('ids') else None
                if milvus_pk:
                    mysql_client.execute_sync(
                        "UPDATE fin_knowledge_meta SET milvus_pk = %s WHERE id = %s",
                        (str(milvus_pk), meta_id)
                    )

                total_inserted += 1
            except Exception as e:
                print(f"[ERROR] {policy_file.name} chunk #{idx}: Milvus插入失败 - {str(e)}")

        print(f"[SUCCESS] {policy_file.name}: {len(chunks)} 个chunk处理完成")

    print(f"\n[SUMMARY] 政策入库完成: {total_inserted} 条")


def verify_ingestion():
    """验证入库结果"""
    print("\n" + "="*80)
    print("第6步：验证入库结果")
    print("="*80)

    # 检查Milvus
    for coll_name in COLLECTIONS:
        try:
            stats = milvus_client.get_collection_stats(coll_name)
            row_count = stats.get("row_count", 0)
            print(f"[INFO] {coll_name}: {row_count} 条记录")
        except Exception as e:
            print(f"[ERROR] {coll_name}: {str(e)}")

    # 检查MySQL
    try:
        results = mysql_client.execute_sync("""
            SELECT knowledge_type, COUNT(*) as cnt
            FROM fin_knowledge_meta
            WHERE deleted_at IS NULL AND status = '已入库'
            GROUP BY knowledge_type
        """)
        print(f"\n[INFO] fin_knowledge_meta:")
        for row in results:
            print(f"  - {row['knowledge_type']}: {row['cnt']} 条")
    except Exception as e:
        print(f"[ERROR] MySQL查询失败: {str(e)}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='清理并重新入库向量数据')
    parser.add_argument('--dry-run', action='store_true', help='预览操作不执行')
    parser.add_argument('--clean-only', action='store_true', help='只清理不入库')
    parser.add_argument('--ingest-only', action='store_true', help='只入库不清理')

    args = parser.parse_args()

    if args.dry_run:
        print("[DRY-RUN] 预览模式，不会修改数据")
        print("实际执行请运行: python scripts/clean_and_reingest_vectors.py")
        sys.exit(0)

    try:
        if not args.ingest_only:
            clean_collections()
            clean_mysql_metadata()

        if not args.clean_only:
            ingest_faq()
            ingest_products()
            ingest_policies()
            verify_ingestion()

        print("\n" + "="*80)
        print("✅ 向量库清理和重新入库完成")
        print("="*80)
    except Exception as e:
        print(f"\n[FATAL ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
