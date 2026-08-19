"""检查 fin_product_collection 的 schema"""
from app.Base.Client.milvusClient import MilvusClientSingleton

client = MilvusClientSingleton()
collection_name = "fin_product_collection"

# 获取集合描述
desc = client.get_client().describe_collection(collection_name=collection_name)

print("="*60)
print(f"集合: {collection_name}")
print("="*60)
print("\n字段列表:")
for field in desc['fields']:
    print(f"\n字段名: {field['name']}")
    print(f"  类型: {field['type']}")
    print(f"  是否主键: {field.get('is_primary', False)}")
    print(f"  自动ID: {field.get('auto_id', False)}")
    if 'params' in field:
        print(f"  参数: {field['params']}")

# 查询一条完整记录
print("\n" + "="*60)
print("查询第一条完整记录的所有字段:")
print("="*60)

results = client.query(
    collection_name=collection_name,
    filter="id > 0",
    output_fields=["*"],  # 获取所有字段
    limit=1
)

if results:
    record = results[0]
    print(f"\n记录ID: {record.get('id')}")
    for key, value in record.items():
        if key == 'embedding':
            print(f"  {key}: <向量，维度={len(value)}>")
        elif key == 'text_sparse':
            print(f"  {key}: <稀疏向量>")
        elif key == 'text':
            text_preview = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
            print(f"  {key}: {text_preview}")
        else:
            print(f"  {key}: {value}")
