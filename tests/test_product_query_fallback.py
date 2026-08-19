from app.WealthButler.Tools.nl2apiTool import NL2APITool


class UnknownParser:
    def parse(self, _user_input):
        return {"intent": "unknown", "confidence": 0.0, "extracted_params": {}}


def test_specific_product_followup_falls_back_to_read_only_query():
    tool = NL2APITool(intent_parser=UnknownParser())
    result = tool.execute("XX平衡优选混合的起购金额和风险等级", {})

    assert result["intent"] == "product_query"
    assert result["confidence"] == 0.95
    assert result["extracted_params"]["keyword"] == "XX平衡优选混合"
    assert result["missing_params"] == []
    assert result["normalization_errors"] == []


def test_transaction_word_does_not_get_product_query_fallback():
    tool = NL2APITool(intent_parser=UnknownParser())
    result = tool.execute("为当前客户办理申购", {})

    assert result["intent"] == "unknown"
