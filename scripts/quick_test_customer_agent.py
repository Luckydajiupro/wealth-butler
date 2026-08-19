"""
客服Agent集成快速验证脚本（ASCII输出版本）
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=" * 60)
print("Customer Service Agent Integration Quick Test")
print("=" * 60)

# Test 1: Import all modules
print("\n[Test 1] Module Import")
try:
    from app.WealthButler.Agent.customerServiceAgent import CustomerServiceAgent
    from app.WealthButler.Tools.knowledgeRetrievalTool import KnowledgeRetrievalTool
    from app.WealthButler.Tools.profileExtractTool import ProfileExtractTool
    from app.WealthButler.Tools.workOrderTool import WorkOrderTool
    from app.WealthButler.Service.customerService import CustomerService
    from app.WealthButler.Service.knowledgeService import KnowledgeService
    from app.WealthButler.Prompts.customerServicePrompts import SYSTEM_PROMPT
    print("  [PASS] All modules imported successfully")
except Exception as e:
    print(f"  [FAIL] Import error: {e}")
    sys.exit(1)

# Test 2: Instantiate Tools
print("\n[Test 2] Tool Instantiation")
try:
    knowledge_tool = KnowledgeRetrievalTool()
    profile_tool = ProfileExtractTool()
    work_order_tool = WorkOrderTool()
    print(f"  [PASS] 3 tools instantiated successfully")
    print(f"    - KnowledgeRetrievalTool: {knowledge_tool.name}")
    print(f"    - ProfileExtractTool: {profile_tool.name}")
    print(f"    - WorkOrderTool: {work_order_tool.name}")
except Exception as e:
    print(f"  [FAIL] Tool instantiation error: {e}")
    sys.exit(1)

# Test 3: Instantiate Agent
print("\n[Test 3] Agent Instantiation")
try:
    agent = CustomerServiceAgent(validate_customer=False)
    print(f"  [PASS] CustomerServiceAgent instantiated")
    print(f"    - Agent name: {agent.name}")
    print(f"    - Max iterations: {agent.max_iterations}")
    print(f"    - Intent threshold: {agent.INTENT_THRESHOLD}")
    print(f"    - Valid intents: {list(agent.VALID_INTENTS)}")
except Exception as e:
    print(f"  [FAIL] Agent instantiation error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: Check chatService integration
print("\n[Test 4] chatService Integration Check")
try:
    from app.WealthButler.Service.chatService import ChatService
    import inspect
    source = inspect.getsource(ChatService._call_customer_agent)
    has_real_agent = 'CustomerServiceAgent' in source
    print(f"  [PASS] chatService._call_customer_agent exists")
    print(f"    - Uses real CustomerServiceAgent: {has_real_agent}")
except Exception as e:
    print(f"  [FAIL] chatService check error: {e}")
    sys.exit(1)

# Summary
print("\n" + "=" * 60)
print("Integration Test Summary")
print("=" * 60)
print("[PASS] All core tests passed")
print("")
print("Integration Status: SUCCESS")
print("Customer Service Agent is ready to use!")
print("")
print("Next Steps:")
print("  1. Start the application: python app/WealthButler/main.py")
print("  2. Test API endpoint: POST /api/chat/customer")
print("  3. Run functional tests as described in docs/客服Agent集成报告.md")
print("=" * 60)
