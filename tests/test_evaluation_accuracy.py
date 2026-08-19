from scripts.evaluation_accuracy import (
    _contract_customer_classifier,
    _contract_operator_parser,
    _LiveEvaluators,
    _reference_sql_generator,
    evaluate_customer,
    evaluate_nl2sql,
    evaluate_operator,
    run,
)


def test_fixed_suite_contract_metrics_are_repeatable():
    first = run("contract", with_storage=False)
    second = run("contract", with_storage=False)

    assert first["customer_intent"] == second["customer_intent"]
    assert first["nl2sql"] == second["nl2sql"]
    assert first["operator"] == second["operator"]
    assert first["evidence_level"] == "deterministic_regression_proxy"
    assert first["customer_rag"] is None
    assert first["acceptance_passed"] is False


def test_customer_evaluator_reports_confusion_and_threshold():
    result = evaluate_customer(_contract_customer_classifier)

    assert result["case_count"] == 18
    assert result["correct"] <= result["case_count"]
    assert sum(result["confusion"].values()) == result["case_count"]
    assert result["passed"] == (result["accuracy"] >= 0.8)


def test_nl2sql_reference_queries_pass_guard_and_semantic_checks():
    result = evaluate_nl2sql(_reference_sql_generator)

    assert result["case_count"] == 10
    assert result["accuracy"] == 1.0
    assert all(item["guard_allowed"] and item["passed"] for item in result["details"])


def test_operator_contract_counts_intents_and_each_declared_field():
    result = evaluate_operator(_contract_operator_parser)

    assert result["case_count"] == 16
    assert result["intent_accuracy"] == 1.0
    assert result["parameter_accuracy"] == 1.0
    assert result["parameter_field_count"] > result["case_count"]


def test_operator_evaluator_does_not_hide_missing_parameters():
    result = evaluate_operator(lambda _text: {"intent": "purchase", "extracted_params": {}})

    assert result["intent_accuracy"] < 1.0
    assert result["parameter_accuracy"] == 0.0


def test_live_customer_evaluator_retries_invalid_json(monkeypatch):
    from app.WealthButler.Agent.customerServiceAgent import CustomerServiceAgent

    evaluator = object.__new__(_LiveEvaluators)
    responses = iter(["", '{"intent":"FAQ","confidence":0.9}'])
    evaluator._complete = lambda *_args, **_kwargs: next(responses)
    monkeypatch.setattr(CustomerServiceAgent, "_fast_path_intent", staticmethod(lambda _text: None))

    assert evaluator.customer("测试问题") == ("FAQ", 0.9)
