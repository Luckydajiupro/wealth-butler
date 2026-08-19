"""
修复 Milvus fin_product_collection 集合的标量字段
从 text 字段的 Markdown 表格中解析产品信息
"""
import re
import logging
from typing import Dict, List, Any
from app.Base.Client.milvusClient import MilvusClientSingleton

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def parse_markdown_table(text: str) -> Dict[str, str]:
    """
    从 Markdown 表格中解析产品信息

    示例格式：
    ### 1.1 XX货币市场基金
    | 项目 | 内容 |
    |------|------|
    | 产品代码 | JP000000 |
    | 产品名称 | XX货币市场基金 |
    | 风险等级 | R1（低风险） |
    | 产品类型 | 货币市场基金 |
    | 预期收益率 | 3.0%-4.0% |
    """
    result = {}

    try:
        # 提取产品名称（从标题）
        title_match = re.search(r'###\s+\d+\.\d+\s+(.+)', text)
        if title_match:
            result['product_name'] = title_match.group(1).strip()

        # 解析表格行
        # 匹配格式: | 项目名 | 内容 |
        table_rows = re.findall(r'\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|', text)

        for key, value in table_rows:
            key = key.strip()
            value = value.strip()

            # 跳过表头和分隔行
            if key in ['项目', '------', '---'] or not value or value.startswith('---'):
                continue

            # 映射字段
            if '产品代码' in key:
                result['product_code'] = value
            elif '产品名称' in key:
                result['product_name'] = value
            elif '风险等级' in key:
                # 提取 R1-R5
                risk_match = re.search(r'R(\d)', value)
                if risk_match:
                    result['risk_level'] = f"R{risk_match.group(1)}"
                else:
                    result['risk_level'] = value
            elif '产品类型' in key:
                result['product_type'] = value
            elif '预期收益率' in key or '年化收益率' in key:
                # 提取收益率范围，如 "3.0%-4.0%" 或 "5.5%"
                rate_match = re.findall(r'(\d+\.?\d*)%', value)
                if len(rate_match) >= 2:
                    result['expected_return_min'] = float(rate_match[0])
                    result['expected_return_max'] = float(rate_match[1])
                elif len(rate_match) == 1:
                    result['expected_return_min'] = float(rate_match[0])
                    result['expected_return_max'] = float(rate_match[0])

        logger.info(f"解析成功: {result.get('product_name', 'Unknown')}")

    except Exception as e:
        logger.error(f"解析失败: {e}")
        logger.debug(f"Text content: {text[:200]}...")

    return result


def query_all_records(client: MilvusClientSingleton, collection_name: str) -> List[Dict[str, Any]]:
    """查询集合中的所有记录"""
    logger.info(f"开始查询集合: {collection_name}")

    try:
        # 查询所有记录，获取所有字段（包括向量字段，upsert时需要）
        results = client.query(
            collection_name=collection_name,
            filter="id > 0",  # 查询所有记录
            output_fields=["*"],  # 获取所有字段
            limit=100
        )

        logger.info(f"查询到 {len(results)} 条记录")
        return results

    except Exception as e:
        logger.error(f"查询失败: {e}")
        return []


def update_scalar_fields(client: MilvusClientSingleton, collection_name: str, records: List[Dict[str, Any]]):
    """更新标量字段"""
    logger.info("开始更新标量字段...")

    update_data = []
    success_count = 0
    skip_count = 0

    for record in records:
        record_id = record.get('id')
        text = record.get('text', '')

        # 检查是否已经有正确的数据
        if record.get('product_name') and record.get('product_name') != '':
            logger.info(f"记录 {record_id} 已有数据，跳过: {record.get('product_name')}")
            skip_count += 1
            continue

        # 解析 text 字段
        parsed = parse_markdown_table(text)

        if not parsed.get('product_name'):
            logger.warning(f"记录 {record_id} 无法解析产品名称，跳过")
            skip_count += 1
            continue

        # 准备更新数据 - 必须包含所有必需字段
        # 注意：text_sparse 是函数输出字段，不能手动提供
        update_record = {
            'id': record_id,
            # 保留原有字段
            'text': record.get('text', ''),
            'metadata': record.get('metadata', ''),
            'embedding': record.get('embedding', []),
            # 更新标量字段
            'product_name': parsed.get('product_name', ''),
            'product_code': parsed.get('product_code', f'AUTO_{record_id}'),
            'risk_level': parsed.get('risk_level', ''),
            'product_type': parsed.get('product_type', ''),
            'expected_return_min': parsed.get('expected_return_min', 0.0),
            'expected_return_max': parsed.get('expected_return_max', 0.0),
            'status': '在售'
        }

        update_data.append(update_record)
        success_count += 1

        logger.info(f"准备更新记录 {record_id}: {update_record['product_name']} | "
                   f"{update_record['risk_level']} | {update_record['product_type']}")

    # 批量更新
    if update_data:
        logger.info(f"\n开始批量更新 {len(update_data)} 条记录...")
        try:
            result = client.upsert(collection_name=collection_name, data=update_data)
            logger.info(f"✅ 更新完成: {result}")
            logger.info(f"成功: {success_count} 条, 跳过: {skip_count} 条")
        except Exception as e:
            logger.error(f"❌ 批量更新失败: {e}")
            logger.error(f"更新数据示例: {update_data[0] if update_data else 'None'}")
    else:
        logger.info(f"无需更新，所有记录已有数据或无法解析")


def verify_results(client: MilvusClientSingleton, collection_name: str):
    """验证更新结果"""
    logger.info("\n" + "="*60)
    logger.info("验证更新结果")
    logger.info("="*60)

    try:
        # 查询所有记录
        results = client.query(
            collection_name=collection_name,
            filter="id > 0",
            output_fields=["id", "product_name", "product_code", "risk_level", "product_type",
                          "expected_return_min", "expected_return_max", "status"],
            limit=100
        )

        logger.info(f"\n总记录数: {len(results)}")

        # 统计
        filled_count = sum(1 for r in results if r.get('product_name') and r.get('product_name') != '')
        empty_count = len(results) - filled_count

        logger.info(f"已填充: {filled_count} 条")
        logger.info(f"未填充: {empty_count} 条")

        # 显示前5条记录
        logger.info("\n前5条记录:")
        for i, record in enumerate(results[:5], 1):
            logger.info(f"\n{i}. ID: {record.get('id')}")
            logger.info(f"   产品名称: {record.get('product_name')}")
            logger.info(f"   产品代码: {record.get('product_code')}")
            logger.info(f"   风险等级: {record.get('risk_level')}")
            logger.info(f"   产品类型: {record.get('product_type')}")
            logger.info(f"   预期收益: {record.get('expected_return_min')}% - {record.get('expected_return_max')}%")
            logger.info(f"   状态: {record.get('status')}")

        # 测试标量过滤查询
        logger.info("\n" + "="*60)
        logger.info("测试标量过滤查询")
        logger.info("="*60)

        # 测试1: 按风险等级查询
        r3_products = client.query(
            collection_name=collection_name,
            filter='risk_level == "R3"',
            output_fields=["product_name", "risk_level"],
            limit=10
        )
        logger.info(f"\n风险等级为 R3 的产品数量: {len(r3_products)}")
        for p in r3_products[:3]:
            logger.info(f"  - {p.get('product_name')} ({p.get('risk_level')})")

        # 测试2: 按收益率查询
        high_return_products = client.query(
            collection_name=collection_name,
            filter='expected_return_min >= 4.0',
            output_fields=["product_name", "expected_return_min", "expected_return_max"],
            limit=10
        )
        logger.info(f"\n预期收益率 >= 4.0% 的产品数量: {len(high_return_products)}")
        for p in high_return_products[:3]:
            logger.info(f"  - {p.get('product_name')} "
                       f"({p.get('expected_return_min')}%-{p.get('expected_return_max')}%)")

    except Exception as e:
        logger.error(f"验证失败: {e}")


def main():
    """主函数"""
    logger.info("="*60)
    logger.info("开始修复 fin_product_collection 标量字段")
    logger.info("="*60)

    # 初始化 Milvus 客户端
    client = MilvusClientSingleton()
    collection_name = "fin_product_collection"

    # 步骤1: 查询当前数据
    records = query_all_records(client, collection_name)

    if not records:
        logger.error("未查询到任何记录，退出")
        return

    # 显示第一条记录的 text 内容作为示例
    logger.info("\n" + "="*60)
    logger.info("第一条记录的 text 内容示例:")
    logger.info("="*60)
    first_text = records[0].get('text', '')
    logger.info(first_text[:500] + "..." if len(first_text) > 500 else first_text)

    # 步骤2: 更新标量字段
    update_scalar_fields(client, collection_name, records)

    # 步骤3: 验证结果
    verify_results(client, collection_name)

    logger.info("\n" + "="*60)
    logger.info("修复完成！")
    logger.info("="*60)


if __name__ == "__main__":
    main()
