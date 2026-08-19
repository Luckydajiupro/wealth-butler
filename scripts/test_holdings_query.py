"""持仓查询功能测试脚本

测试场景：
1. 今日收益查询
2. 持仓列表查询
3. 总资产查询
4. 验证意图分类准确性
5. 验证工具调用正确性

运行方式：
    cd D:/lqh/金融
    python scripts/test_holdings_query.py
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.WealthButler.Agent.customerServiceAgent import CustomerServiceAgent


def test_holdings_queries():
    """测试持仓查询功能"""
    print("=" * 80)
    print("持仓查询功能测试")
    print("=" * 80)

    agent = CustomerServiceAgent(validate_customer=True)

    test_cases = [
        ("今日收益", "today_profit"),
        ("我的持仓情况", "holdings_list"),
        ("查询总资产", "total_asset"),
        ("今天赚了多少钱", "today_profit"),
        ("我持有哪些产品", "holdings_list"),
        ("我的总资产是多少", "total_asset"),
    ]

    results = []

    for query, expected_type in test_cases:
        print(f"\n查询: {query}")
        print(f"期望类型: {expected_type}")
        print("-" * 80)

        try:
            result = agent.run(
                user_input=query,
                customer_id=1,
                session_id=f'test_{hash(query)}'
            )

            if result.success:
                intent = result.metadata.get("intent")
                confidence = result.metadata.get("intent_confidence")
                query_type = result.metadata.get("holdings_query_type")

                print(f"Agent回复: {result.output[:150]}")
                print(f"意图识别: {intent} (置信度: {confidence})")
                print(f"查询类型: {query_type}")

                # 检查HoldingsTool是否被调用
                holdings_tool_used = any(
                    tc.get('name') == 'HoldingsQuery'
                    for tc in result.tool_calls
                )

                # 检查是否转人工
                transferred = result.metadata.get('transfer_ticket_id') is not None

                test_passed = (
                    intent == "holdings_query" and
                    holdings_tool_used and
                    not transferred and
                    query_type == expected_type
                )

                status = "通过" if test_passed else "失败"
                print(f"测试结果: {status}")

                results.append({
                    'query': query,
                    'expected_type': expected_type,
                    'actual_type': query_type,
                    'intent': intent,
                    'confidence': confidence,
                    'tool_used': holdings_tool_used,
                    'transferred': transferred,
                    'passed': test_passed
                })
            else:
                print(f"失败: {result.error_msg}")
                results.append({
                    'query': query,
                    'passed': False,
                    'error': result.error_msg
                })

        except Exception as e:
            print(f"异常: {e}")
            results.append({
                'query': query,
                'passed': False,
                'error': str(e)
            })

    # 汇总统计
    print("\n" + "=" * 80)
    print("测试汇总")
    print("=" * 80)

    total = len(results)
    passed = sum(1 for r in results if r.get('passed'))
    failed = total - passed

    print(f"\n总测试数: {total}")
    print(f"通过: {passed} ({passed/total*100:.1f}%)")
    print(f"失败: {failed} ({failed/total*100:.1f}%)")

    print("\n详细结果:")
    for r in results:
        status = "通过" if r.get('passed') else "失败"
        print(f"  [{status}] {r['query']}")
        if not r.get('passed') and r.get('error'):
            print(f"        错误: {r['error']}")
        elif r.get('actual_type'):
            print(f"        类型: {r['actual_type']} | 意图: {r['intent']} | 工具调用: {r['tool_used']}")

    return results


def test_non_holdings_queries():
    """测试非持仓查询仍正常工作"""
    print("\n" + "=" * 80)
    print("非持仓查询功能验证")
    print("=" * 80)

    agent = CustomerServiceAgent(validate_customer=True)

    test_cases = [
        ("你好", "chitchat"),
        ("如何购买基金", "product_consult"),
        ("客服电话是多少", "faq"),
    ]

    for query, expected_intent in test_cases:
        print(f"\n查询: {query}")
        print(f"期望意图: {expected_intent}")
        print("-" * 80)

        try:
            result = agent.run(
                user_input=query,
                customer_id=1,
                session_id=f'test_{hash(query)}'
            )

            if result.success:
                intent = result.metadata.get("intent")
                print(f"Agent回复: {result.output[:100]}")
                print(f"实际意图: {intent}")

                # 检查是否错误调用了HoldingsTool
                holdings_tool_used = any(
                    tc.get('name') == 'HoldingsQuery'
                    for tc in result.tool_calls
                )

                if holdings_tool_used:
                    print("警告: 非持仓查询错误调用了HoldingsTool")
                elif intent == expected_intent:
                    print("状态: 通过")
                else:
                    print(f"状态: 意图不匹配 (期望 {expected_intent}, 实际 {intent})")
            else:
                print(f"失败: {result.error_msg}")

        except Exception as e:
            print(f"异常: {e}")


def main():
    """主函数"""
    print("\n" + "=" * 80)
    print("CustomerServiceAgent 持仓查询功能测试")
    print("=" * 80)
    print()

    # 测试1: 持仓查询
    holdings_results = test_holdings_queries()

    # 测试2: 非持仓查询
    test_non_holdings_queries()

    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)

    # 返回码
    all_passed = all(r.get('passed') for r in holdings_results)
    return 0 if all_passed else 1


if __name__ == '__main__':
    exit(main())
