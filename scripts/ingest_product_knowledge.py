"""
产品知识文档切片入库脚本

功能：
1. 读取产品手册Markdown文档
2. 从MySQL fin_product表获取产品结构化数据
3. 按产品维度切片（每个产品一个chunk）
4. 清洗占位符
5. 生成向量并入库到Milvus fin_product_collection
6. 更新MySQL fin_knowledge_meta表

使用方式：
    python scripts/ingest_product_knowledge.py
"""

import sys
import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from decimal import Decimal

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.Base.Client.mysqlClient import MySQLClient
from app.Base.Client.milvusClient import MilvusClientSingleton
from app.Base.Ai.llms.ollamaEmbedding import ollama_embedding
from app.WealthButler.Models.productModel import ProductModel
from app.WealthButler.Models.knowledgeMetaModel import KnowledgeMetaModel

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PlaceholderCleaner:
    """占位符清洗器"""

    REPLACEMENT_DICT = {
        'XX科技（有限公司）': '锦鹏科技有限公司',
        'XX科技有限公司': '锦鹏科技有限公司',
        'XX科技': '锦鹏科技',
        'XX Tech Co., Ltd.': 'Jinpeng Tech Co., Ltd.',
        'www.xxtech.com': 'www.jinpengtech.com',
        '400-XXX-XXXX': '400-822-6699',
        'product_training@xxtech.com': 'product_training@jinpengtech.com',
        '20XX年3月15日': '2024年3月15日',
        '20XX年': '2024年',
    }

    @classmethod
    def clean(cls, text: str) -> str:
        """清洗文本中的占位符"""
        cleaned = text
        for placeholder, replacement in cls.REPLACEMENT_DICT.items():
            cleaned = cleaned.replace(placeholder, replacement)
        return cleaned


class ProductChunker:
    """产品文档切片器"""

    def __init__(self, markdown_path: str):
        self.markdown_path = Path(markdown_path)
        if not self.markdown_path.exists():
            raise FileNotFoundError(f"产品手册文件不存在: {markdown_path}")

        with open(self.markdown_path, 'r', encoding='utf-8') as f:
            self.content = f.read()

        # 清洗占位符
        self.content = PlaceholderCleaner.clean(self.content)

    def extract_product_chunks(self) -> List[Dict[str, Any]]:
        """
        按产品维度切片
        返回: [
            {
                'title': '1.1 XX货币市场基金',
                'product_code': 'JP000000',
                'content': '完整的产品说明文本',
                'section_type': 'product'  # 或 'general'
            },
            ...
        ]
        """
        chunks = []

        # 正则匹配三级标题（产品）
        # 格式: ### 1.1 XX货币市场基金
        pattern = r'###\s+([\d.]+)\s+(.+?)(?=\n###|\n##|\Z)'
        matches = re.finditer(pattern, self.content, re.DOTALL)

        for match in matches:
            section_number = match.group(1).strip()
            section_title = match.group(2).strip()
            section_content = match.group(0).strip()

            full_title = f"{section_number} {section_title}"

            # 判断是产品说明还是通用说明
            # 第一章到第三章是具体产品，第四章到第六章是通用说明
            is_product = section_number.startswith(('1.', '2.', '3.'))

            # 提取产品代码（如果是产品说明）
            product_code = None
            if is_product:
                code_match = re.search(r'\|\s*产品代码\s*\|\s*([A-Z0-9]+)\s*\|', section_content)
                if code_match:
                    product_code = code_match.group(1).strip()

            chunks.append({
                'title': full_title,
                'product_code': product_code,
                'content': section_content,
                'section_type': 'product' if is_product else 'general'
            })

        logger.info(f"成功提取 {len(chunks)} 个产品/说明段落")
        return chunks


class ProductKnowledgeIngestor:
    """产品知识入库器"""

    def __init__(self):
        self.mysql_client = MySQLClient()
        self.milvus_client = MilvusClientSingleton()
        self.collection_name = "fin_product_collection"

    def get_products_from_db(self) -> Dict[str, Dict[str, Any]]:
        """从MySQL获取产品列表，返回以product_code为key的字典"""
        products = {}
        try:
            sql = "SELECT * FROM fin_product WHERE status = '在售'"
            results = self.mysql_client.execute_sync(sql)

            for row in results:
                product_code = row.get('product_code')
                if product_code:
                    products[product_code] = row

            logger.info(f"从数据库加载 {len(products)} 个在售产品")
        except Exception as e:
            logger.error(f"查询产品列表失败: {e}")

        return products

    def check_existing(self, title: str, source_file: str) -> Optional[int]:
        """检查是否已存在该chunk，返回existing record id"""
        try:
            sql = """
                SELECT id FROM fin_knowledge_meta
                WHERE title = %s AND source_file = %s AND status = '已上线'
                LIMIT 1
            """
            results = self.mysql_client.execute_sync(sql, (title, source_file))
            if results:
                return results[0].get('id')
        except Exception as e:
            logger.warning(f"检查已存在记录失败: {e}")
        return None

    def ingest_chunk(
        self,
        chunk: Dict[str, Any],
        product_info: Optional[Dict[str, Any]] = None
    ) -> bool:
        """入库单个chunk"""
        title = chunk['title']
        content = chunk['content']
        product_code = chunk.get('product_code')

        # 检查是否已存在
        existing_id = self.check_existing(title, '个人理财产品手册.md')
        if existing_id:
            logger.info(f"跳过已存在的chunk: {title}")
            return True

        try:
            # 1. 生成embedding
            logger.info(f"生成embedding: {title}")
            embedding = ollama_embedding(content)

            # 2. 准备Milvus数据
            # 根据实际schema填充所有标量字段
            milvus_data = {
                'text': content,  # 用于BM25
                'embedding': embedding,
                'product_code': '',
                'product_name': '',
                'risk_level': '',
                'product_type': '',
                'expected_return_min': 0.0,
                'expected_return_max': 0.0,
                'status': '在售',
            }

            # 构建metadata（存放额外信息）
            metadata = {
                'title': title,
                'source_file': '个人理财产品手册.md',
                'section_type': chunk['section_type'],
            }

            # 如果有产品信息，填充结构化字段
            if product_info:
                milvus_data['product_code'] = product_info.get('product_code', '')
                milvus_data['product_name'] = product_info.get('product_name', '')
                milvus_data['risk_level'] = product_info.get('risk_level', '')
                milvus_data['product_type'] = product_info.get('product_type', '')
                milvus_data['status'] = product_info.get('status', '在售')

                # 从产品描述中提取收益率（简化处理，实际应该解析文档）
                # 这里使用默认值
                milvus_data['expected_return_min'] = 0.0
                milvus_data['expected_return_max'] = 0.0

                # 补充到metadata
                metadata['product_id'] = product_info.get('id', 0)
            elif product_code:
                milvus_data['product_code'] = product_code

            # metadata必须转为JSON字符串
            milvus_data['metadata'] = json.dumps(metadata, ensure_ascii=False)

            # 3. 插入Milvus
            logger.info(f"插入Milvus: {title}")
            insert_result = self.milvus_client.insert(
                collection_name=self.collection_name,
                data=[milvus_data]
            )

            if not insert_result.get('success', False):
                logger.error(f"Milvus插入失败: {title}")
                return False

            # 4. 记录到MySQL fin_knowledge_meta
            logger.info(f"记录元数据到MySQL: {title}")
            meta_record = KnowledgeMetaModel(
                knowledge_type='产品说明书',
                collection_name=self.collection_name,
                title=title,
                source='个人理财产品手册.md',
                source_file='个人理财产品手册.md',
                milvus_collection=self.collection_name,
                file_path=f'公司业务/个人理财产品手册.md',
                chunk_count=1,
                status='已上线',
                uploaded_by=1  # 系统管理员
            )

            record_id = meta_record.save()
            if record_id <= 0:
                logger.warning(f"MySQL元数据记录失败: {title}")

            logger.info(f"✅ 成功入库: {title}")
            return True

        except Exception as e:
            logger.error(f"❌ 入库失败 {title}: {e}", exc_info=True)
            return False

    def run(self, markdown_path: str):
        """执行完整的入库流程"""
        logger.info("=" * 80)
        logger.info("开始产品知识文档切片入库")
        logger.info("=" * 80)

        # 1. 读取并切片产品手册
        logger.info(f"读取产品手册: {markdown_path}")
        chunker = ProductChunker(markdown_path)
        chunks = chunker.extract_product_chunks()

        # 2. 获取产品结构化数据
        logger.info("查询产品结构化数据...")
        products = self.get_products_from_db()

        # 3. 逐chunk入库
        success_count = 0
        fail_count = 0
        skip_count = 0

        for chunk in chunks:
            product_code = chunk.get('product_code')
            product_info = products.get(product_code) if product_code else None

            if product_code and not product_info:
                logger.warning(f"产品代码 {product_code} 在数据库中不存在，使用默认值")

            result = self.ingest_chunk(chunk, product_info)
            if result:
                success_count += 1
            else:
                fail_count += 1

        # 4. 统计报告
        logger.info("=" * 80)
        logger.info("入库完成统计")
        logger.info("=" * 80)
        logger.info(f"总chunk数: {len(chunks)}")
        logger.info(f"成功入库: {success_count}")
        logger.info(f"失败: {fail_count}")
        logger.info("=" * 80)

        # 5. 验证
        self.verify_ingestion()

    def verify_ingestion(self):
        """验证入库结果"""
        logger.info("\n开始验证入库结果...")

        try:
            # 确保集合已加载
            client = self.milvus_client.get_client()
            load_state = client.get_load_state(collection_name=self.collection_name)
            if load_state.get("state") != "Loaded":
                logger.info(f"加载集合 {self.collection_name} 到内存...")
                client.load_collection(collection_name=self.collection_name)

            # 查询Milvus集合数据量
            query_result = self.milvus_client.query(
                collection_name=self.collection_name,
                filter="",
                output_fields=["text", "product_name", "product_code"],
                limit=5
            )

            logger.info(f"Milvus集合 {self.collection_name} 示例数据:")
            for idx, item in enumerate(query_result[:3], 1):
                text = item.get('text', '')
                preview = text[:100] + '...' if len(text) > 100 else text
                logger.info(f"  [{idx}] {preview}")

            # 查询MySQL元数据
            sql = """
                SELECT COUNT(*) as cnt FROM fin_knowledge_meta
                WHERE collection_name = %s AND status = '已上线'
            """
            results = self.mysql_client.execute_sync(sql, (self.collection_name,))
            meta_count = results[0]['cnt'] if results else 0
            logger.info(f"MySQL fin_knowledge_meta 表中产品知识记录数: {meta_count}")

        except Exception as e:
            logger.error(f"验证失败: {e}", exc_info=True)


def main():
    """主函数"""
    markdown_path = "D:/lqh/金融/公司业务/个人理财产品手册.md"

    ingestor = ProductKnowledgeIngestor()
    ingestor.run(markdown_path)


if __name__ == "__main__":
    main()
