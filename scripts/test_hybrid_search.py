"""
测试BM25混合检索功能
"""
import sys
sys.path.append('D:/lqh/金融')

from app.WealthButler.Repository.productCollectionModelV2 import ProductCollectionModelV2
from app.Base.Client.ollamaClient import ollama_client

def test_hybrid_search():
    """测试混合检索"""
    print("="*60)
    print("测试BM25混合检索功能")
    print("="*60)

    # 测试查询
    test_queries = [
        "货币基金的收益率是多少？",
        "哪些基金适合保守型投资者？",
        "基金申购费率是多少？"
    ]

    for query in test_queries:
        print(f"\n[查询] {query}")

        # 生成稠密向量
        embedding_resp = ollama_client.get_embedding(query, model="bge-m3")
        # ollama_client.get_embedding直接返回list
        dense_vector = embedding_resp if isinstance(embedding_resp, list) else embedding_resp.get('embedding', [])

        try:
            # 执行混合检索
            results = ProductCollectionModelV2.hybrid_search(
                dense_vector=dense_vector,
                query_text=query,
                dense_weight=0.7,
                sparse_weight=0.3,
                limit=3,
                output_fields=['text', 'metadata']
            )

            print(f"  检索结果数: {len(results)}")

            if results:
                for i, result in enumerate(results[0], 1):
                    entity = result.get('entity', {})
                    text = entity.get('text', '')[:100]
                    metadata = entity.get('metadata', {})

                    # metadata可能是JSON字符串，需要解析
                    if isinstance(metadata, str):
                        import json
                        try:
                            metadata = json.loads(metadata)
                        except:
                            metadata = {}

                    score = result.get('distance', 0)

                    print(f"\n  结果 {i}:")
                    print(f"    相似度: {score:.4f}")
                    print(f"    产品: {metadata.get('product_name', 'N/A')}")
                    print(f"    类型: {metadata.get('chunk_type', 'N/A')}")
                    print(f"    文本: {text}...")
            else:
                print("  无检索结果")

        except Exception as e:
            print(f"  [ERROR] 混合检索失败: {e}")
            print(f"  错误类型: {type(e).__name__}")
            import traceback
            traceback.print_exc()

    print("\n" + "="*60)
    print("[SUCCESS] 混合检索测试完成")
    print("="*60)

if __name__ == "__main__":
    test_hybrid_search()
