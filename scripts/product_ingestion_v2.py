#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
产品手册入库脚本 V2（结构化切片版本）

核心改进：
1. 细粒度切片：每个产品的每个关键属性做一个chunk
2. 结构化metadata：提取产品属性到metadata字段
3. 支持混合检索：向量检索（语义匹配）+ 过滤检索（精确匹配product_code、category等）

切片策略：
- 每个产品生成多个chunk：
  * 产品概览chunk：包含产品名称、代码、类型、风险等级（用于"这个产品怎么样"类查询）
  * 收益率chunk：历史收益数据（用于"收益率多少"类查询）
  * 费率chunk：申购赎回费率（用于"手续费多少"类查询）
  * 适合人群chunk：投资策略+适合人群（用于"适合什么人"类查询）
  * 操作规则chunk：申购赎回规则（用于"怎么买/怎么赎回"类查询）

Author: 李清华
Date: 2026-08-15
"""

import sys
import re
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

# 添加项目根目录到sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.Base.Client.ollamaClient import ollama_client
from app.Base.Client.milvusClient import MilvusClientSingleton
from app.WealthButler.Repository.productCollectionModelV2 import ProductCollectionModelV2
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


def get_embedding(text: str) -> List[float]:
    """调用Ollama生成embedding"""
    try:
        resp = ollama_client.get_embedding(text, model="bge-m3")
        return resp
    except Exception as e:
        print(f"❌ Embedding生成失败: {e}")
        return [0.0] * 1024


def check_existing_chunk(cursor, source_file: str, title: str) -> Optional[int]:
    """检查MySQL是否已存在该chunk（幂等性）"""
    sql = """
        SELECT id FROM fin_knowledge_meta
        WHERE file_path = %s AND title = %s AND status = '已上线'
        LIMIT 1
    """
    cursor.execute(sql, (source_file, title))
    row = cursor.fetchone()
    return row[0] if row else None


def insert_chunk_to_mysql(cursor, knowledge_type: str, source_file: str,
                          title: str, collection_name: str) -> int:
    """插入chunk到MySQL fin_knowledge_meta表（适配现有表结构）"""
    sql = """
        INSERT INTO fin_knowledge_meta
        (knowledge_type, file_path, title, collection_name, status)
        VALUES (%s, %s, %s, %s, '已上线')
    """
    cursor.execute(sql, (knowledge_type, source_file, title, collection_name))
    return cursor.lastrowid


def extract_product_info(product_section: str) -> Dict:
    """
    从产品section中提取结构化信息
    返回：{
        'name': 产品名称,
        'code': 产品代码,
        'type': 产品类型,
        'risk_level': 风险等级,
        'min_amount': 起投金额,
        'params': {表格中的所有参数},
        'strategy': 投资策略,
        'suitable': 适合人群,
        'rules': 申购赎回规则
    }
    """
    result = {
        'name': '',
        'code': '',
        'type': '',
        'risk_level': '',
        'min_amount': '',
        'params': {},
        'strategy': '',
        'suitable': '',
        'rules': ''
    }

    # 提取标题（产品名称）- 注意：传入的product_section已经被split了，不含###
    lines = product_section.split('\n')
    if lines:
        first_line = lines[0].strip()
        # 去掉序号（如"1.1 "）
        name_match = re.match(r'^[\d.]+\s+(.+)', first_line)
        if name_match:
            result['name'] = name_match.group(1).strip()
        else:
            result['name'] = first_line

    # 提取表格参数
    table_match = re.search(r'\| 项目 \| 详情 \|(.+?)(?=\n\*\*|$)', product_section, re.DOTALL)
    if table_match:
        table_lines = table_match.group(1).strip().split('\n')
        for line in table_lines:
            if '|' not in line or '---' in line:
                continue
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 2:
                key, value = parts[0], parts[1]
                result['params'][key] = value

                # 映射关键字段
                if key == '产品代码':
                    result['code'] = value
                elif key in ['基金类型', '产品类型']:
                    result['type'] = value
                elif key == '风险等级':
                    result['risk_level'] = value
                elif key == '起投金额':
                    result['min_amount'] = value

    # 提取投资策略
    strategy_match = re.search(r'\*\*投资策略\*\*[：:]\s*(.+?)(?=\n\*\*|\n###|$)', product_section, re.DOTALL)
    if strategy_match:
        result['strategy'] = strategy_match.group(1).strip()

    # 提取适合人群
    suitable_match = re.search(r'\*\*适合人群\*\*[：:]\s*(.+?)(?=\n###|$)', product_section, re.DOTALL)
    if suitable_match:
        result['suitable'] = suitable_match.group(1).strip()

    # 提取申购赎回规则
    rules_match = re.search(r'\*\*申购赎回规则\*\*[：:]\s*(.+?)(?=\n\*\*|\n###|$)', product_section, re.DOTALL)
    if rules_match:
        result['rules'] = rules_match.group(1).strip()

    return result


def create_product_chunks(product_info: Dict, category: str, placeholder_dict: Dict) -> List[Dict]:
    """
    为一个产品生成多个细粒度chunk

    返回chunk列表，每个chunk包含：
    {
        'title': chunk标题（用于MySQL和幂等性判断）,
        'content': chunk内容（用于MySQL存储）,
        'embedding_text': 用于生成embedding的文本,
        'metadata': {
            'product_name': 产品名称,
            'product_code': 产品代码,
            'product_type': 产品类型,
            'risk_level': 风险等级,
            'category': 大类（基金/理财/保险）,
            'chunk_type': chunk类型（overview/return/fee/suitable/rules）,
            'attribute': 具体属性名（如"收益率"、"费率"）
        }
    }
    """
    chunks = []
    product_name = product_info['name']
    product_code = product_info['code']

    # 占位符清洗
    product_name = clean_placeholders(product_name, placeholder_dict)

    # 基础metadata
    base_metadata = {
        'product_name': product_name,
        'product_code': product_code,
        'product_type': product_info['type'],
        'risk_level': product_info['risk_level'],
        'category': category
    }

    # 1. 产品概览chunk
    overview_lines = [
        f"产品名称：{product_name}",
        f"产品代码：{product_code}",
        f"产品类型：{product_info['type']}",
        f"风险等级：{product_info['risk_level']}",
        f"起投金额：{product_info['min_amount']}"
    ]
    # 添加其他关键参数
    if '基金规模' in product_info['params']:
        overview_lines.append(f"基金规模：{product_info['params']['基金规模']}")
    if '基金经理' in product_info['params']:
        overview_lines.append(f"基金经理：{product_info['params']['基金经理']}")
    if '产品期限' in product_info['params']:
        overview_lines.append(f"产品期限：{product_info['params']['产品期限']}")

    overview_content = '\n'.join(overview_lines)
    chunks.append({
        'title': f"{product_name}-产品概览",
        'content': overview_content,
        'embedding_text': overview_content,
        'metadata': {**base_metadata, 'chunk_type': 'overview', 'attribute': '产品概览'}
    })

    # 2. 收益率chunk（如果有）
    return_lines = []
    for key in ['七日年化收益率', '近一年收益率', '近三年收益率', '近五年收益率',
                '业绩比较基准', '近一年实际收益率', '预定利率', '股息率']:
        if key in product_info['params']:
            return_lines.append(f"{key}：{product_info['params'][key]}")

    if return_lines:
        return_content = f"{product_name}\n" + '\n'.join(return_lines)
        chunks.append({
            'title': f"{product_name}-收益表现",
            'content': return_content,
            'embedding_text': return_content,
            'metadata': {**base_metadata, 'chunk_type': 'return', 'attribute': '收益率'}
        })

    # 3. 费率chunk
    fee_lines = []
    for key in ['申购费率', '赎回费率', '基金管理费', '托管费', '销售服务费',
                '管理费', '销售手续费']:
        if key in product_info['params']:
            fee_lines.append(f"{key}：{product_info['params'][key]}")

    if fee_lines:
        fee_content = f"{product_name}\n" + '\n'.join(fee_lines)
        chunks.append({
            'title': f"{product_name}-费率说明",
            'content': fee_content,
            'embedding_text': fee_content,
            'metadata': {**base_metadata, 'chunk_type': 'fee', 'attribute': '费率'}
        })

    # 4. 投资策略chunk（如果有）
    if product_info['strategy']:
        strategy_content = f"{product_name}投资策略：\n{clean_placeholders(product_info['strategy'], placeholder_dict)}"
        chunks.append({
            'title': f"{product_name}-投资策略",
            'content': strategy_content,
            'embedding_text': strategy_content,
            'metadata': {**base_metadata, 'chunk_type': 'strategy', 'attribute': '投资策略'}
        })

    # 5. 适合人群chunk（如果有）
    if product_info['suitable']:
        suitable_content = f"{product_name}适合人群：\n{clean_placeholders(product_info['suitable'], placeholder_dict)}"
        chunks.append({
            'title': f"{product_name}-适合人群",
            'content': suitable_content,
            'embedding_text': suitable_content,
            'metadata': {**base_metadata, 'chunk_type': 'suitable', 'attribute': '适合人群'}
        })

    # 6. 申购赎回规则chunk（如果有）
    if product_info['rules']:
        rules_content = f"{product_name}申购赎回规则：\n{clean_placeholders(product_info['rules'], placeholder_dict)}"
        chunks.append({
            'title': f"{product_name}-申购赎回规则",
            'content': rules_content,
            'embedding_text': rules_content,
            'metadata': {**base_metadata, 'chunk_type': 'rules', 'attribute': '操作规则'}
        })

    return chunks


def parse_product_manual(file_path: str, placeholder_dict: Dict) -> List[Dict]:
    """
    解析产品手册Markdown，返回所有产品的chunks
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    all_chunks = []

    # 按##二级标题切分（大类：基金/理财/保险）
    sections = re.split(r'\n##\s+', content)

    for section in sections:
        if not section.strip():
            continue

        # 识别大类（检查section前200字符）
        category = None
        section_head = section[:200]
        if '基金类产品' in section_head or '一、基金' in section_head:
            category = '基金'
        elif '银行理财产品' in section_head or '二、银行理财' in section_head:
            category = '银行理财'
        elif '保险产品' in section_head or '三、保险' in section_head:
            category = '保险'
        else:
            continue  # 跳过非产品section（如目录、对比表等）

        # 按###三级标题切分（单个产品）
        products = re.split(r'\n###\s+', section)

        for product_section in products[1:]:  # 跳过第一个（section标题）
            if not product_section.strip():
                continue

            # 提取产品结构化信息
            product_info = extract_product_info(product_section)

            if not product_info['name']:
                continue

            # 为该产品生成多个chunk
            product_chunks = create_product_chunks(product_info, category, placeholder_dict)
            all_chunks.extend(product_chunks)

    return all_chunks


def ingest_product_chunks(chunks: List[Dict], source_file: str):
    """产品chunks入库"""
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
        metadata = chunk['metadata']
        meta_id = insert_chunk_to_mysql(
            cursor,
            knowledge_type='产品说明书',  # 使用enum中的值
            source_file=source_file,
            title=title,
            collection_name='fin_product_collection'
        )

        # 插入Milvus
        try:
            metadata_with_id = {**metadata, 'meta_id': meta_id}

            # 创建Pydantic模型实例
            product_instance = ProductCollectionModelV2(
                text=chunk['content'],  # 主文本字段存完整内容
                metadata=metadata_with_id,  # metadata是dict类型，不需要json.dumps
                embedding=embedding
            )

            result = ProductCollectionModelV2.insert([product_instance])
            conn.commit()
            success_count += 1

        except Exception as e:
            print(f"[ERROR] 插入Milvus失败: {title}, 错误: {e}")
            conn.rollback()
            continue

    cursor.close()
    conn.close()

    return success_count, skip_count


def main():
    print("=" * 60)
    print("产品手册入库脚本 V2（结构化切片）")
    print("=" * 60)

    # 加载占位符词典
    placeholder_dict = load_placeholder_dict()
    print(f"[OK] 占位符词典加载: {len(placeholder_dict)}条\n")

    # 解析产品手册
    product_manual_path = project_root / "公司业务" / "个人理财产品手册.md"
    print(f"[INFO] 解析产品手册: {product_manual_path.name}")

    chunks = parse_product_manual(product_manual_path, placeholder_dict)
    print(f"[OK] 生成产品chunks: {len(chunks)}个\n")

    # 入库
    print("[INFO] 开始入库到MySQL + Milvus...")
    source_file = "公司业务/个人理财产品手册.md"
    success_count, skip_count = ingest_product_chunks(chunks, source_file)

    print(f"\n[SUCCESS] 产品手册入库完成: 成功{success_count}个, 跳过{skip_count}个")
    print("=" * 60)


if __name__ == "__main__":
    main()
