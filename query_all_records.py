"""查询所有记录并显示详细信息"""
from app.Base.Client.milvusClient import MilvusClientSingleton

client = MilvusClientSingleton()
collection_name = "fin_product_collection"

# 查询所有记录
results = client.query(
    collection_name=collection_name,
    filter="id > 0",
    output_fields=["id", "product_name", "product_code", "risk_level", "product_type",
                  "expected_return_min", "expected_return_max", "status"],
    limit=100
)

print(f"总记录数: {len(results)}")

if results:
    print("\n所有记录:")
    print("="*80)
    for i, record in enumerate(results, 1):
        print(f"\n{i}. ID: {record.get('id')}")
        print(f"   产品名称: [{record.get('product_name')}]")
        print(f"   产品代码: [{record.get('product_code')}]")
        print(f"   风险等级: [{record.get('risk_level')}]")
        print(f"   产品类型: [{record.get('product_type')}]")
        print(f"   预期收益: {record.get('expected_return_min')} - {record.get('expected_return_max')}")
        print(f"   状态: [{record.get('status')}]")

        # 检查字段类型
        if i == 1:
            print(f"\n   字段类型检查:")
            print(f"   product_name type: {type(record.get('product_name'))}")
            print(f"   product_name repr: {repr(record.get('product_name'))}")
else:
    print("未查询到任何记录")
