"""
RAG混合检索阈值调优脚本

目标：
1. 测试不同的dense_weight和sparse_weight组合
2. 评估检索准确率和相关性
3. 确定最佳权重配置

评估指标：
- MRR (Mean Reciprocal Rank): 第一个相关结果的平均排名倒数
- Top-K准确率: 前K个结果中包含相关内容的比例
- 平均相似度分数
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_questions_30 import TEST_QUESTIONS, get_questions_by_collection
from app.WealthButler.Repository.productCollectionModelV2 import ProductCollectionModelV2
from app.WealthButler.Repository.policyCollectionModelV2 import PolicyCollectionModelV2
from app.Base.Client.ollamaClient import ollama_client
import json
import time


def check_relevance(result, expected_keywords):
    """
    检查检索结果是否相关

    Args:
        result: 检索结果项
        expected_keywords: 期望的关键词列表

    Returns:
        bool: 是否相关（至少匹配1个关键词）
    """
    entity = result.get('entity', {})
    text = entity.get('text', '').lower()

    # 检查是否包含任意期望关键词
    for keyword in expected_keywords:
        if keyword.lower() in text:
            return True
    return False


def evaluate_single_query(question, dense_weight, sparse_weight, top_k=5):
    """
    评估单个查询

    Returns:
        dict: {
            'query': 查询文本,
            'collection': 集合名称,
            'relevant_count': 相关结果数量,
            'first_relevant_rank': 第一个相关结果的排名（1-based），None表示无相关结果,
            'avg_score': 平均相似度分数,
            'results': 检索结果列表
        }
    """
    query = question['query']
    collection_type = question['collection']
    expected_keywords = question['expected_keywords']

    try:
        # 生成稠密向量
        embedding = ollama_client.get_embedding(query, model="bge-m3")

        # 选择集合
        if collection_type == 'product':
            CollectionModel = ProductCollectionModelV2
        else:
            CollectionModel = PolicyCollectionModelV2

        # 执行混合检索
        results = CollectionModel.hybrid_search(
            dense_vector=embedding,
            query_text=query,
            dense_weight=dense_weight,
            sparse_weight=sparse_weight,
            limit=top_k,
            output_fields=['text', 'metadata']
        )

        if not results or not results[0]:
            return {
                'query': query,
                'collection': collection_type,
                'relevant_count': 0,
                'first_relevant_rank': None,
                'avg_score': 0,
                'results': []
            }

        # 评估结果
        relevant_count = 0
        first_relevant_rank = None
        scores = []
        result_details = []

        for i, result in enumerate(results[0], 1):
            entity = result.get('entity', {})
            text = entity.get('text', '')
            score = result.get('distance', 0)
            scores.append(score)

            is_relevant = check_relevance(result, expected_keywords)
            if is_relevant:
                relevant_count += 1
                if first_relevant_rank is None:
                    first_relevant_rank = i

            result_details.append({
                'rank': i,
                'score': score,
                'is_relevant': is_relevant,
                'text_preview': text[:100]
            })

        return {
            'query': query,
            'collection': collection_type,
            'relevant_count': relevant_count,
            'first_relevant_rank': first_relevant_rank,
            'avg_score': sum(scores) / len(scores) if scores else 0,
            'results': result_details
        }

    except Exception as e:
        print(f"[ERROR] Query failed: {query} - {e}")
        return {
            'query': query,
            'collection': collection_type,
            'relevant_count': 0,
            'first_relevant_rank': None,
            'avg_score': 0,
            'results': [],
            'error': str(e)
        }


def calculate_metrics(eval_results):
    """
    计算整体评估指标

    Returns:
        dict: {
            'mrr': Mean Reciprocal Rank,
            'top1_accuracy': Top-1准确率,
            'top3_accuracy': Top-3准确率,
            'top5_accuracy': Top-5准确率,
            'avg_relevant_count': 平均相关结果数,
            'avg_score': 平均相似度分数
        }
    """
    reciprocal_ranks = []
    top1_hits = 0
    top3_hits = 0
    top5_hits = 0
    relevant_counts = []
    scores = []

    for result in eval_results:
        if result['first_relevant_rank'] is not None:
            reciprocal_ranks.append(1.0 / result['first_relevant_rank'])

            if result['first_relevant_rank'] == 1:
                top1_hits += 1
            if result['first_relevant_rank'] <= 3:
                top3_hits += 1
            if result['first_relevant_rank'] <= 5:
                top5_hits += 1
        else:
            reciprocal_ranks.append(0)

        relevant_counts.append(result['relevant_count'])
        scores.append(result['avg_score'])

    total = len(eval_results)

    return {
        'mrr': sum(reciprocal_ranks) / total if total > 0 else 0,
        'top1_accuracy': top1_hits / total if total > 0 else 0,
        'top3_accuracy': top3_hits / total if total > 0 else 0,
        'top5_accuracy': top5_hits / total if total > 0 else 0,
        'avg_relevant_count': sum(relevant_counts) / total if total > 0 else 0,
        'avg_score': sum(scores) / total if total > 0 else 0
    }


def test_weight_combination(dense_weight, sparse_weight, questions, top_k=5):
    """
    测试一组权重组合

    Returns:
        dict: 评估结果和指标
    """
    print(f"\n[Testing] dense_weight={dense_weight}, sparse_weight={sparse_weight}")
    print("=" * 60)

    eval_results = []

    for i, question in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {question['query'][:30]}...", end=" ", flush=True)

        result = evaluate_single_query(question, dense_weight, sparse_weight, top_k)
        eval_results.append(result)

        # 输出简要结果
        if result.get('error'):
            print("[ERROR]")
        elif result['first_relevant_rank']:
            print(f"[OK] rank={result['first_relevant_rank']}")
        else:
            print("[MISS]")

        time.sleep(0.1)  # 避免请求过快

    # 计算指标
    metrics = calculate_metrics(eval_results)

    print("\n[Metrics]")
    print(f"  MRR:             {metrics['mrr']:.4f}")
    print(f"  Top-1 Accuracy:  {metrics['top1_accuracy']:.2%}")
    print(f"  Top-3 Accuracy:  {metrics['top3_accuracy']:.2%}")
    print(f"  Top-5 Accuracy:  {metrics['top5_accuracy']:.2%}")
    print(f"  Avg Relevant:    {metrics['avg_relevant_count']:.2f}")
    print(f"  Avg Score:       {metrics['avg_score']:.4f}")

    return {
        'dense_weight': dense_weight,
        'sparse_weight': sparse_weight,
        'metrics': metrics,
        'eval_results': eval_results
    }


def main():
    """
    主函数：测试多组权重组合
    """
    print("RAG Hybrid Search Threshold Tuning")
    print("=" * 60)
    print(f"Total test questions: {len(TEST_QUESTIONS)}")
    print(f"  Product: {len(get_questions_by_collection('product'))}")
    print(f"  Policy:  {len(get_questions_by_collection('policy'))}")

    # 定义要测试的权重组合
    weight_combinations = [
        (1.0, 0.0),   # 纯稠密向量
        (0.9, 0.1),   # 稠密为主
        (0.8, 0.2),
        (0.7, 0.3),   # 当前默认
        (0.6, 0.4),
        (0.5, 0.5),   # 均衡
        (0.4, 0.6),
        (0.3, 0.7),   # BM25为主
        (0.2, 0.8),
        (0.0, 1.0),   # 纯BM25
    ]

    all_results = []

    for dense_w, sparse_w in weight_combinations:
        result = test_weight_combination(
            dense_weight=dense_w,
            sparse_weight=sparse_w,
            questions=TEST_QUESTIONS,
            top_k=5
        )
        all_results.append(result)

    # 保存结果
    output_file = "threshold_tuning_results.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] Results saved to {output_file}")

    # 输出最佳配置
    print("\n" + "=" * 60)
    print("Best Configurations by Metric:")
    print("=" * 60)

    best_mrr = max(all_results, key=lambda x: x['metrics']['mrr'])
    print(f"\nBest MRR: {best_mrr['metrics']['mrr']:.4f}")
    print(f"  dense_weight={best_mrr['dense_weight']}, sparse_weight={best_mrr['sparse_weight']}")

    best_top1 = max(all_results, key=lambda x: x['metrics']['top1_accuracy'])
    print(f"\nBest Top-1 Accuracy: {best_top1['metrics']['top1_accuracy']:.2%}")
    print(f"  dense_weight={best_top1['dense_weight']}, sparse_weight={best_top1['sparse_weight']}")

    best_top3 = max(all_results, key=lambda x: x['metrics']['top3_accuracy'])
    print(f"\nBest Top-3 Accuracy: {best_top3['metrics']['top3_accuracy']:.2%}")
    print(f"  dense_weight={best_top3['dense_weight']}, sparse_weight={best_top3['sparse_weight']}")

    best_top5 = max(all_results, key=lambda x: x['metrics']['top5_accuracy'])
    print(f"\nBest Top-5 Accuracy: {best_top5['metrics']['top5_accuracy']:.2%}")
    print(f"  dense_weight={best_top5['dense_weight']}, sparse_weight={best_top5['sparse_weight']}")


if __name__ == "__main__":
    main()
