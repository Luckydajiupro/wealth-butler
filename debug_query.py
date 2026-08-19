"""调试查询：查看更新后的实际数据"""
from app.Base.Client.milvusClient import MilvusClientSingleton

client = MilvusClientSingleton()
collection_name = "fin_product_collection"

# 查询第一条记录
results = client.query(
    collection_name=collection_name,
    filter="id == 468389132003717326",
    output_fields=["id", "product_name", "product_code", "risk_level", "product_type",
                  "expected_return_min", "expected_return_max", "status", "text"],
    limit=1
)

if results:
    record = results[0]
    print("="*60)
    print("查询结果:")
    print("="*60)
    print(f"ID: {record.get('id')}")
    print(f"产品名称: {record.get('product_name')}")
    print(f"产品代码: {record.get('product_code')}")
    print(f"风险等级: {record.get('risk_level')}")
    print(f"产品类型: {record.get('product_type')}")
    print(f"预期收益率: {record.get('expected_return_min')}% - {record.get('expected_return_max')}%")
    print(f"状态: {record.get('status')}")
    print(f"\ntext字段前100字符:")
    print(record.get('text', '')[:100])
else:
    print("未查询到记录")
