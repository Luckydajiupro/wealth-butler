"""
客服Agent集成验证脚本

功能：
1. 测试所有模块导入
2. 测试Agent实例化
3. 测试Tool实例化
4. 输出集成状态报告

使用方法：
cd D:/lqh/金融
python scripts/test_customer_agent_integration.py
"""
import sys
import os

# 确保路径正确
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_imports():
    """测试所有模块导入"""
    print("=" * 60)
    print("测试1：模块导入验证")
    print("=" * 60)

    test_cases = [
        ("Agent层", "app.WealthButler.Agent.customerServiceAgent", "CustomerServiceAgent"),
        ("Tools层-知识检索", "app.WealthButler.Tools.knowledgeRetrievalTool", "KnowledgeRetrievalTool"),
        ("Tools层-画像提取", "app.WealthButler.Tools.profileExtractTool", "ProfileExtractTool"),
        ("Tools层-工单创建", "app.WealthButler.Tools.workOrderTool", "WorkOrderTool"),
        ("Service层-客服", "app.WealthButler.Service.customerService", "CustomerService"),
        ("Service层-知识库", "app.WealthButler.Service.knowledgeService", "KnowledgeService"),
        ("Service层-工单", "app.WealthButler.Service.workOrderService", "WorkOrderService"),
        ("Service层-嵌入", "app.WealthButler.Service.ollamaEmbeddingService", "OllamaEmbeddingService"),
        ("Repository层", "app.WealthButler.Repository.customerServiceRepository", "CustomerServiceRepository"),
        ("Prompts层", "app.WealthButler.Prompts.customerServicePrompts", "SYSTEM_PROMPT"),
        ("API层", "app.WealthButler.Api.chatApi", "router"),
    ]

    success_count = 0
    failed_modules = []

    for name, module_path, attr_name in test_cases:
        try:
            module = __import__(module_path, fromlist=[attr_name])
            getattr(module, attr_name)
            print(f"  [{name:20s}] SUCCESS - {attr_name}")
            success_count += 1
        except Exception as e:
            print(f"  [{name:20s}] FAILED - {e}")
            failed_modules.append(name)

    print(f"\n导入测试结果: {success_count}/{len(test_cases)} 通过")

    if failed_modules:
        print(f"失败模块: {', '.join(failed_modules)}")
        return False
    return True


def test_tool_instantiation():
    """测试Tool实例化"""
    print("\n" + "=" * 60)
    print("测试2：Tool实例化验证")
    print("=" * 60)

    try:
        from app.WealthButler.Tools.knowledgeRetrievalTool import KnowledgeRetrievalTool
        from app.WealthButler.Tools.profileExtractTool import ProfileExtractTool
        from app.WealthButler.Tools.workOrderTool import WorkOrderTool

        # 实例化Tools
        knowledge_tool = KnowledgeRetrievalTool()
        print(f"  [KnowledgeRetrievalTool] SUCCESS")
        print(f"    - name: {knowledge_tool.name}")
        print(f"    - description: {knowledge_tool.description[:50]}...")

        profile_tool = ProfileExtractTool()
        print(f"  [ProfileExtractTool] SUCCESS")
        print(f"    - name: {profile_tool.name}")
        print(f"    - description: {profile_tool.description[:50]}...")

        work_order_tool = WorkOrderTool()
        print(f"  [WorkOrderTool] SUCCESS")
        print(f"    - name: {work_order_tool.name}")
        print(f"    - description: {work_order_tool.description[:50]}...")

        print("\nTool实例化测试: 3/3 通过")
        return True

    except Exception as e:
        print(f"\nTool实例化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_agent_instantiation():
    """测试Agent实例化"""
    print("\n" + "=" * 60)
    print("测试3：Agent实例化验证")
    print("=" * 60)

    try:
        from app.WealthButler.Agent.customerServiceAgent import CustomerServiceAgent

        # 实例化Agent（不进行客户校验以避免数据库依赖）
        agent = CustomerServiceAgent(validate_customer=False)

        print(f"  [CustomerServiceAgent] SUCCESS")
        print(f"    - name: {agent.name}")
        print(f"    - tools: {len(agent.tools)} 个工具")
        print(f"    - max_iterations: {agent.max_iterations}")
        print(f"    - intent_threshold: {agent.INTENT_THRESHOLD}")
        print(f"    - valid_intents: {len(agent.VALID_INTENTS)} 个意图")

        # 检查Tools
        tool_names = [tool.name for tool in agent.tools]
        print(f"    - tool_names: {', '.join(tool_names)}")

        print("\nAgent实例化测试: 通过")
        return True

    except Exception as e:
        print(f"\nAgent实例化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_prompt_templates():
    """测试提示词模板"""
    print("\n" + "=" * 60)
    print("测试4：提示词模板验证")
    print("=" * 60)

    try:
        from app.WealthButler.Prompts.customerServicePrompts import (
            SYSTEM_PROMPT,
            INTENT_CLASSIFY_PROMPT,
            ANSWER_PROMPT,
            FALLBACK_MESSAGE,
            TRANSFER_MESSAGE
        )

        print(f"  [SYSTEM_PROMPT] 长度: {len(SYSTEM_PROMPT)} 字符")
        print(f"    - 包含'角色定义': {'角色定义' in SYSTEM_PROMPT}")
        print(f"    - 包含'能力边界': {'能力边界' in SYSTEM_PROMPT}")
        print(f"    - 包含'合规红线': {'合规红线' in SYSTEM_PROMPT}")

        print(f"  [INTENT_CLASSIFY_PROMPT] 长度: {len(INTENT_CLASSIFY_PROMPT)} 字符")
        print(f"    - 包含5类意图: {all(intent in INTENT_CLASSIFY_PROMPT for intent in ['product_consult', 'policy_explain', 'faq', 'chitchat', 'transfer_to_human'])}")

        print(f"  [ANSWER_PROMPT] 长度: {len(ANSWER_PROMPT)} 字符")
        print(f"  [FALLBACK_MESSAGE] {FALLBACK_MESSAGE}")
        print(f"  [TRANSFER_MESSAGE] {TRANSFER_MESSAGE}")

        print("\n提示词模板测试: 通过")
        return True

    except Exception as e:
        print(f"\n提示词模板测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_chatservice_integration():
    """测试chatService集成"""
    print("\n" + "=" * 60)
    print("测试5：chatService.py集成验证")
    print("=" * 60)

    try:
        from app.WealthButler.Service.chatService import ChatService

        # 检查_call_customer_agent方法是否存在
        if hasattr(ChatService, '_call_customer_agent'):
            print(f"  [_call_customer_agent] SUCCESS - 方法存在")

            # 读取源码检查是否导入了真实Agent
            import inspect
            source = inspect.getsource(ChatService._call_customer_agent)

            has_import = 'from app.WealthButler.Agent.customerServiceAgent import CustomerServiceAgent' in source
            has_instantiation = 'CustomerServiceAgent(' in source

            print(f"    - 导入真实Agent: {has_import}")
            print(f"    - 实例化Agent: {has_instantiation}")

            if has_import and has_instantiation:
                print("\nchatService集成测试: 通过 (已集成真实Agent)")
                return True
            else:
                print("\nchatService集成测试: 警告 (仍在使用Mock)")
                return False
        else:
            print(f"  [_call_customer_agent] FAILED - 方法不存在")
            return False

    except Exception as e:
        print(f"\nchatService集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主函数"""
    print("\n")
    print("╔════════════════════════════════════════════════════════════╗")
    print("║          客服Agent集成验证脚本                              ║")
    print("║          Customer Service Agent Integration Test           ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print()

    results = []

    # 执行所有测试
    results.append(("模块导入", test_imports()))
    results.append(("Tool实例化", test_tool_instantiation()))
    results.append(("Agent实例化", test_agent_instantiation()))
    results.append(("提示词模板", test_prompt_templates()))
    results.append(("chatService集成", test_chatservice_integration()))

    # 汇总结果
    print("\n" + "=" * 60)
    print("最终测试报告")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "PASS" if result else "FAIL"
        symbol = "✓" if result else "✗"
        print(f"  [{symbol}] {name:20s} - {status}")

    print(f"\n总计: {passed}/{total} 测试通过")

    if passed == total:
        print("\n状态: 所有测试通过，客服Agent集成成功！")
        print("下一步: 执行端到端功能测试")
        return 0
    else:
        print(f"\n状态: {total - passed} 个测试失败，需要修复")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
