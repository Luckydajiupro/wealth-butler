from app.WealthButler.Agent.customerServiceAgent import CustomerServiceAgent


def test_customer_suitability_query_fast_path_is_read_only():
    assert CustomerServiceAgent._fast_path_intent("我适合什么产品？") == (
        "suitability_query", 0.99
    )
    assert CustomerServiceAgent._fast_path_intent("推荐适合我的产品") == (
        "suitability_query", 0.99
    )


def test_transfer_response_contains_advisor_name_contract():
    source = open("app/WealthButler/Agent/customerServiceAgent.py", encoding="utf-8").read()
    assert "负责理财顾问：{advisor_name}" in source
    assert "已为您转接负责理财顾问{advisor_name}" in source


def test_customer_can_explicitly_request_an_advisor():
    assert CustomerServiceAgent._fast_path_intent("我要找理财顾问") == (
        "transfer_to_human", 0.98
    )
    assert CustomerServiceAgent._business_subtype_for_transfer("我要找理财顾问") == "产品配置"
    assert CustomerServiceAgent._fast_path_intent("转接人工") == (
        "transfer_to_human", 0.98
    )
    assert CustomerServiceAgent._business_subtype_for_transfer("转接人工") == "产品配置"
    assert CustomerServiceAgent._fast_path_intent("找人工") == ("transfer_to_human", 0.98)
    assert CustomerServiceAgent._business_subtype_for_transfer("找人工") == "产品配置"


def test_contextual_advisor_transfer_keeps_advisor_intent():
    result = CustomerServiceAgent._resolve_contextual_follow_up(
        "转接人工",
        [{"role": "assistant", "content": "如需专业顾问一对一服务，我可以为您转接理财顾问。"}],
    )
    assert result == ("transfer_to_human", 0.99, "我要找理财顾问，进行产品配置咨询")
