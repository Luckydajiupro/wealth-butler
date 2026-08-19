"""
客服Agent检索效果测试脚本

测试场景：
1. 常见问题检索（FAQ）
2. 产品咨询检索
3. 政策法规检索
4. 阈值边界测试

运行方式：
    cd D:/lqh/金融
    python scripts/test_retrieval_quality.py
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.WealthButler.Service.knowledgeService import KnowledgeService
from app.WealthButler.Agent.customerServiceAgent import CustomerServiceAgent


def test_retrieval_scores():
    """测试不同问题的检索分数"""
    print("=" * 80)
    print("检索分数测试")
    print("=" * 80)

    test_cases = [
        # (查询, 集合, 期望类型)
        ("今日收益", "fin_faq_collection", "FAQ"),
        ("如何查看持仓", "fin_faq_collection", "FAQ"),
        ("忘记密码怎么办", "fin_faq_collection", "FAQ"),
        ("有什么稳健型产品", "fin_product_collection", "产品"),
        ("债券型基金风险", "fin_product_collection", "产品"),
        ("基金赎回手续费", "fin_policy_collection", "政策"),
        ("交易时间", "fin_faq_collection", "FAQ"),
    ]

    # 当前阈值设置
    thresholds = CustomerServiceAgent.RETRIEVAL_THRESHOLDS

    results = []

    for query, collection, category in test_cases:
        print(f"\n查询: {query}")
        print(f"集合: {collection} | 阈值: {thresholds[collection]}")
        print("-" * 80)

        try:
            retrieved = KnowledgeService.retrieve(
                query=query,
                collection=collection,
                top_k=1
            )

            if retrieved:
                top_score = retrieved[0].get('score', 0)
                top_content = retrieved[0].get('content', '')[:80]
                threshold = thresholds[collection]
                passed = top_score >= threshold

                print(f"最高分数: {top_score:.4f}")
                print(f"是否通过: {'✓ 是' if passed else '✗ 否'}")
                print(f"内容预览: {top_content}...")

                results.append({
                    'query': query,
                    'category': category,
                    'score': top_score,
                    'threshold': threshold,
                    'passed': passed
                })
            else:
                print("无检索结果")
                results.append({
                    'query': query,
                    'category': category,
                    'score': 0,
                    'threshold': thresholds[collection],
                    'passed': False
                })

        except Exception as e:
            print(f"检索失败: {e}")

    # 汇总统计
    print("\n" + "=" * 80)
    print("汇总统计")
    print("=" * 80)

    total = len(results)
    passed = sum(1 for r in results if r['passed'])
    failed = total - passed

    print(f"\n总测试数: {total}")
    print(f"通过阈值: {passed} ({passed/total*100:.1f}%)")
    print(f"未通过阈值: {failed} ({failed/total*100:.1f}%)")

    print("\n分数分布:")
    for r in results:
        status = "✓" if r['passed'] else "✗"
        print(f"  {status} {r['query']:<20} | 分数: {r['score']:.4f} | 阈值: {r['threshold']}")

    print("\n建议:")
    if failed > total * 0.3:
        print("  ⚠️  未通过率较高（>30%），建议：")
        print("     1. 降低检索阈值（当前FAQ=0.55，可考虑0.50）")
        print("     2. 检查知识库数据质量和覆盖度")
        print("     3. 优化embedding模型（当前使用bge-m3）")
    else:
        print("  ✓ 通过率良好，阈值设置合理")

    return results


def test_end_to_end():
    """测试端到端Agent响应"""
    print("\n" + "=" * 80)
    print("端到端Agent响应测试")
    print("=" * 80)

    agent = CustomerServiceAgent(validate_customer=True)

    test_queries = [
        "今日收益",
        "如何购买基金",
        "忘记密码怎么办",
    ]

    for query in test_queries:
        print(f"\n用户: {query}")
        print("-" * 80)

        try:
            result = agent.run(
                user_input=query,
                customer_id=1,
                session_id=f'test_{hash(query)}'
            )

            if result.success:
                output = result.output[:200]
                print(f"Agent: {output}...")

                # 检查是否转人工
                if '转人工' in result.output or '客户经理' in result.output or '人工客服' in result.output:
                    print("状态: ⚠️  转人工")
                else:
                    print("状态: ✓ 正常回答")
            else:
                print(f"失败: {result.error_msg}")

        except Exception as e:
            print(f"异常: {e}")


def main():
    """主函数"""
    print("\n" + "=" * 80)
    print("客服Agent检索效果测试")
    print("=" * 80)
    print()

    # 测试1: 检索分数
    results = test_retrieval_scores()

    # 测试2: 端到端响应
    test_end_to_end()

    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)

    return 0


if __name__ == '__main__':
    exit(main())
