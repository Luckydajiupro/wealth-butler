"""风险评估 JSON 字段的模型回归测试。"""

from datetime import datetime, timedelta
from decimal import Decimal
import json

import pytest
from pydantic import ValidationError

from app.WealthButler.Models.riskAssessmentModel import RiskAssessmentModel


def _record(answers):
    now = datetime(2026, 8, 17, 10, 0, 0)
    return RiskAssessmentModel(
        customer_id=1,
        total_score=Decimal("28"),
        risk_level="C1",
        answers=answers,
        assessment_time=now,
        valid_until=now + timedelta(days=365),
    )


def test_answers_accepts_mysql_json_string():
    record = _record('[{"question_id":"Q1","score":0}]')
    assert record.answers == [{"question_id": "Q1", "score": 0}]


def test_answers_accepts_legacy_question_keyed_json_object():
    record = _record('{"Q1":{"score":10,"option_ids":["D"]}}')

    assert record.answers == {"Q1": {"score": 10, "option_ids": ["D"]}}


def test_structured_answers_are_encoded_for_database_driver():
    answers = [{"question_no": 1, "option": "B", "score": 20}]

    encoded = RiskAssessmentModel._prepare_db_value(answers)

    assert isinstance(encoded, str)
    assert json.loads(encoded) == answers


@pytest.mark.parametrize("value", ['{"question_id":"Q1"}', "not-json"])
def test_answers_invalid_json_fails_closed(value):
    with pytest.raises((ValidationError, ValueError)):
        _record(value)
