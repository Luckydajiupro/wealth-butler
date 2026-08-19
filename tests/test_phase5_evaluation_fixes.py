"""固定题集暴露的生产契约回归测试。"""

from app.WealthButler.Service.advisorService import AdvisorService
from app.WealthButler.Models.productModel import ProductModel
from app.WealthButler.Service.productService import ProductService
from app.WealthButler.Tools.graphQueryTool import GraphQueryTool
from app.WealthButler.Tools.nl2apiTool import LLMIntentParser


def test_nl2api_prompt_declares_canonical_fields_and_forbidden_aliases() -> None:
    prompt = LLMIntentParser._build_prompt("转账60000元到账号6222，收款人张三")

    assert "counterparty_account" in prompt
    assert "counterparty_name" in prompt
    assert "product_id" in prompt
    assert "禁止输出 product、product_code、account、payee、payee_name 等别名" in prompt


def test_graph_rows_produce_product_level_scores() -> None:
    result = GraphQueryTool._normalize_rows([
        {"product_code": "P-TECH", "industry_name": "科技", "market_value": 80},
        {"product_code": "P-HEALTH", "industry_name": "医药", "market_value": 20},
    ])

    assert result["product_scores"] == {"P-TECH": 0.2, "P-HEALTH": 0.8}


def test_advisor_uses_industry_concentration_for_unseen_candidates() -> None:
    products = [
        {"id": 1, "product_code": "P-TECH", "industry": "科技", "risk_level": "R2"},
        {"id": 2, "product_code": "P-CONSUMER", "industry": "消费", "risk_level": "R2"},
    ]
    ranked = AdvisorService().rank_products(
        products,
        graph_result={"industry_weights": {"科技": 100.0}, "graph_score": 0.0},
        vector_scores={"P-TECH": 0.5, "P-CONSUMER": 0.5},
        context={"risk_assessment": {"risk_level": "C2"}},
        top_k=2,
    )

    by_code = {item["product_code"]: item for item in ranked}
    assert by_code["P-TECH"]["graph_score"] == 0.0
    assert by_code["P-CONSUMER"]["graph_score"] == 1.0
    assert ranked[0]["product_code"] == "P-CONSUMER"


def test_advisor_uses_real_nav_history_and_enriched_holding_industry() -> None:
    service = AdvisorService(
        product_loader=lambda: [
            {"id": 1, "product_code": "P-TECH", "product_name": "科技基金", "industry": "科技", "risk_level": "R2", "status": "在售"},
            {"id": 2, "product_code": "P-HEALTH", "product_name": "医药基金", "industry": "医药", "risk_level": "R2", "status": "在售"},
        ],
        nav_history_loader=lambda _ids: {
            1: [{"nav": 1.0}, {"nav": 1.05}],
            2: [{"nav": 1.0}, {"nav": 1.10}],
        },
    )

    products = service.load_products()
    holdings = service._enrich_holdings([{"product_id": 1, "current_value": 100}], products)

    assert products[0]["return_source"] == "nav_history_90d"
    assert products[0]["return_score"] == 0.0
    assert products[1]["return_score"] == 1.0
    assert holdings[0]["industry"] == "科技"


def test_advisor_term_and_preference_scores_are_neutral_without_preferences() -> None:
    assert AdvisorService._term_score(0, {}) == 0.5
    assert AdvisorService._preference_score({"product_type": "公募基金"}, {}) == 0.5
    assert AdvisorService._term_score(7, {"liquidity": "灵活，随时可取"}) > 0.9
    assert AdvisorService._preference_score(
        {"product_type": "银行理财"},
        {"product_preference": {"type": "银行理财"}},
    ) == 1.0


def test_advisor_model_serialization_preserves_product_id() -> None:
    product = ProductModel(
        id=42,
        product_code="P-DETAIL",
        product_name="详情测试产品",
        product_type="公募基金",
        risk_level="R2",
    )

    assert AdvisorService._model_to_dict(product)["id"] == 42


def test_product_detail_service_uses_base_model_primary_key_lookup(monkeypatch) -> None:
    expected = object()
    monkeypatch.setattr(ProductModel, "get_by_id", lambda product_id: expected if product_id == 42 else None)

    assert ProductService.get_product_by_id(42) is expected
