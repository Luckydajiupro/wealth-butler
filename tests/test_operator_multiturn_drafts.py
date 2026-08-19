from datetime import datetime, timedelta, timezone

from app.WealthButler.Service.operatorApiRuntime import OperatorApiRuntimeFactory
from app.WealthButler.Service.operatorDraftStore import OperatorDraftStore


def _candidate(intent, params, confidence=0.99):
    return {"intent": intent, "confidence": confidence, "extracted_params": params}


def _confirm_if_required(runtime, result):
    if result["code"] != "CONFIRMATION_REQUIRED":
        return result
    return runtime.confirm(8, result["metadata"]["confirm_token"], "confirm")


def test_multiturn_draft_merges_only_with_same_employee_customer_and_session():
    runtime = OperatorApiRuntimeFactory.create_fake()
    first = runtime.execute(8, 1001, "申购这个产品", _candidate("purchase", {"product_name": "阶段5模拟R3公募基金"}), "s-1")
    assert first["code"] == "MISSING_PARAMS"
    assert first["metadata"]["missing_params"] == ["amount"]

    completed = _confirm_if_required(
        runtime,
        runtime.execute(8, 1001, "金额500元", _candidate("purchase", {"amount": "500"}), "s-1"),
    )
    assert completed["code"] == "TRANSACTION_SUCCEEDED"

    isolated = runtime.execute(8, 1001, "金额500元", _candidate("purchase", {"amount": "500"}), "other-session")
    assert isolated["code"] == "MISSING_PARAMS"
    assert isolated["metadata"]["missing_params"] == ["product_id"]


def test_switching_intent_replaces_and_cancel_clears_draft():
    runtime = OperatorApiRuntimeFactory.create_fake()
    runtime.execute(8, 1001, "申购", _candidate("purchase", {"product_id": 1}), "s-2")
    switched = runtime.execute(8, 1001, "转账100元", _candidate("transfer", {"amount": "100"}), "s-2")
    assert switched["code"] == "MISSING_PARAMS"
    assert runtime.agent.draft_store.get(8, 1001, "s-2").intent == "transfer"

    cancelled = runtime.execute(8, 1001, "取消操作", None, "s-2")
    assert cancelled["code"] == "OPERATION_DRAFT_CANCELLED"
    assert runtime.agent.draft_store.get(8, 1001, "s-2") is None


def test_underclassified_short_followup_keeps_trusted_draft_intent():
    runtime = OperatorApiRuntimeFactory.create_fake()
    runtime.execute(8, 1001, "办理申购", _candidate("purchase", {"product_id": 1}), "short-reply")

    result = runtime.execute(8, 1001, "稍后补金额", None, "short-reply")

    assert result["code"] == "MISSING_PARAMS"
    assert result["metadata"]["missing_params"] == ["amount"]
    assert runtime.agent.draft_store.get(8, 1001, "short-reply").intent == "purchase"


def test_product_name_and_redeem_ratio_are_resolved_from_gateways():
    runtime = OperatorApiRuntimeFactory.create_fake()
    runtime.holdings.positions[(1001, 1)] = {
        "customer_id": 1001,
        "product_id": 1,
        "shares": "100.000000",
        "current_value": "1000.00",
        "average_cost": "10.00",
    }
    result = _confirm_if_required(runtime, runtime.execute(
        8,
        1001,
        "赎回阶段5模拟R3公募基金的30%",
        _candidate("redeem", {"product_name": "阶段5模拟R3公募基金", "redeem_ratio": "0.3"}),
        "s-3",
    ))
    assert result["code"] == "TRANSACTION_SUCCEEDED"
    assert str(result["data"]["shares"]) == "30.000000"


def test_redeem_ratio_accepts_all_half_and_percent_without_model_arithmetic():
    for ratio, expected in (("全部", "100.000000"), ("一半", "50.000000"), ("30%", "30.000000")):
        runtime = OperatorApiRuntimeFactory.create_fake()
        runtime.holdings.positions[(1001, 1)] = {
            "customer_id": 1001,
            "product_id": 1,
            "shares": "100.000000",
            "current_value": "1000.00",
            "average_cost": "10.00",
        }
        result = _confirm_if_required(runtime, runtime.execute(
            8,
            1001,
            f"赎回{ratio}",
            _candidate("redeem", {"product_id": 1, "redeem_ratio": ratio}),
            f"ratio-{ratio}",
        ))
        assert result["code"] == "TRANSACTION_SUCCEEDED"
        assert str(result["data"]["shares"]) == expected


def test_failed_business_validation_retains_draft_for_correction():
    runtime = OperatorApiRuntimeFactory.create_fake()
    failed = runtime.execute(
        8,
        1001,
        "赎回10份",
        _candidate("redeem", {"product_id": 1, "shares": "10"}),
        "retain-on-failure",
    )
    assert failed["code"] == "REDEEMABLE_HOLDING_NOT_FOUND"
    draft = runtime.agent.draft_store.get(8, 1001, "retain-on-failure")
    assert draft is not None
    assert draft.intent == "redeem"
    assert draft.params == {"product_id": 1, "shares": "10"}


def test_unrelated_unknown_message_does_not_replay_retained_draft():
    runtime = OperatorApiRuntimeFactory.create_fake()
    runtime.execute(
        8,
        1001,
        "赎回10份",
        _candidate("redeem", {"product_id": 1, "shares": "10"}),
        "no-replay",
    )
    result = runtime.execute(8, 1001, "今天天气怎么样", _candidate("unknown", {}), "no-replay")
    assert result["code"] == "LOW_CONFIDENCE"


def test_draft_ttl_and_identity_isolation():
    now = datetime(2026, 8, 17, tzinfo=timezone.utc)
    clock = {"value": now}
    store = OperatorDraftStore(ttl_seconds=60, now=lambda: clock["value"])
    store.save(8, 1001, "same", "purchase", {"product_id": 1})
    assert store.get(8, 1001, "same") is not None
    assert store.get(9, 1001, "same") is None
    assert store.get(8, 1002, "same") is None
    clock["value"] = now + timedelta(seconds=61)
    assert store.get(8, 1001, "same") is None
