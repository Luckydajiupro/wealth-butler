"""业务操作 NL2API 的离线评测工具。

评测器不依赖具体模型；联调时向 ``evaluate_intent_parser`` 注入
``LLMIntentParser`` 即可获得真实模型的意图和参数提取指标。
"""

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Protocol


class EvaluationParser(Protocol):
    def parse(self, user_input: str) -> Dict[str, Any]: ...


def load_cases(path: str | Path) -> List[Dict[str, Any]]:
    """读取独立评测集，拒绝不完整的测试样本。"""
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError("评测集必须是 JSON 数组")
    for index, item in enumerate(payload):
        if not isinstance(item, dict) or not isinstance(item.get("user_input"), str):
            raise ValueError(f"第{index + 1}条评测样本缺少 user_input")
        if not isinstance(item.get("expected_intent"), str):
            raise ValueError(f"第{index + 1}条评测样本缺少 expected_intent")
        if not isinstance(item.get("expected_params", {}), dict):
            raise ValueError(f"第{index + 1}条评测样本的 expected_params 必须是对象")
    return payload


def evaluate_intent_parser(parser: EvaluationParser, cases: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """按意图和已声明参数分别计分，避免遗漏字段被错误算为正确。"""
    total = 0
    intent_correct = 0
    parameter_total = 0
    parameter_correct = 0
    details = []

    for case in cases:
        parsed = parser.parse(case["user_input"])
        if not isinstance(parsed, dict):
            parsed = {}
        actual_intent = parsed.get("intent")
        expected_params = case.get("expected_params", {})
        actual_params = parsed.get("extracted_params", {})
        if not isinstance(actual_params, dict):
            actual_params = {}

        total += 1
        is_intent_correct = actual_intent == case["expected_intent"]
        intent_correct += int(is_intent_correct)
        matched_fields = []
        for field, expected_value in expected_params.items():
            parameter_total += 1
            is_field_correct = actual_params.get(field) == expected_value
            parameter_correct += int(is_field_correct)
            if is_field_correct:
                matched_fields.append(field)
        details.append({
            "id": case.get("id"),
            "intent_correct": is_intent_correct,
            "matched_fields": matched_fields,
            "expected_field_count": len(expected_params),
        })

    if not total:
        raise ValueError("评测集不能为空")
    return {
        "case_count": total,
        "intent_accuracy": intent_correct / total,
        "parameter_accuracy": parameter_correct / parameter_total if parameter_total else 1.0,
        "details": details,
    }
