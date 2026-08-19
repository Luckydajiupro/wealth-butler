"""持仓今日收益必须使用真实的当日与上一交易日净值。"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.WealthButler.Api import holdingsApi
from app.WealthButler.Tools.holdingsTool import HoldingsTool


def test_holdings_tool_uses_the_same_daily_profit_result_as_the_api():
    with patch.object(
        holdingsApi,
        "calculate_today_profit",
        return_value={
            "today_profit": 197.13,
            "today_profit_rate": 0.01,
            "total_value": 1971329.52,
            "calculation_source": "simulated",
            "as_of_date": date.today().isoformat(),
        },
    ):
        result = HoldingsTool().execute(query_type="today_profit", customer_id=7)

    assert result["success"] is True
    assert result["profit_amount"] == 197.13
    assert result["profit_ratio"] == 0.01
    assert result["calculation_source"] == "simulated"
    assert result["message"] == "您今日收益为+197.13元，收益率为+0.01%（模拟）"


def test_today_profit_api_returns_stable_simulation_when_market_data_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        holdingsApi,
        "_get_customer",
        lambda credentials: SimpleNamespace(id=7),
    )
    monkeypatch.setattr(
        holdingsApi.HoldingsModel,
        "find_by_customer_id",
        lambda customer_id: [SimpleNamespace(product_id=9, shares=Decimal("100"), current_value=Decimal("110"))],
    )
    monkeypatch.setattr(
        holdingsApi.ProductModel,
        "get_by_id",
        lambda product_id: SimpleNamespace(
            id=product_id, nav=Decimal("1.1000"), nav_date=date.today(),
            product_type="公募基金", risk_level="R3",
        ),
    )
    monkeypatch.setattr(
        holdingsApi.ProductNavHistoryModel,
        "find_latest_before",
        lambda product_id, before_date: None,
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token")

    first = holdingsApi.get_today_profit(credentials)
    second = holdingsApi.get_today_profit(credentials)

    assert first.data == second.data
    assert first.data["calculation_source"] == "simulated"
    assert first.data["estimated_product_ids"] == [9]
    assert -0.5 <= first.data["today_profit_rate"] <= 0.6
    assert first.data["today_profit"] == pytest.approx(
        110 * first.data["today_profit_rate"] / 100, abs=0.01
    )


def test_today_profit_uses_today_and_previous_nav(monkeypatch):
    monkeypatch.setattr(
        holdingsApi, "_get_customer", lambda credentials: SimpleNamespace(id=7)
    )
    monkeypatch.setattr(
        holdingsApi.HoldingsModel,
        "find_by_customer_id",
        lambda customer_id: [SimpleNamespace(product_id=9, shares=Decimal("100"))],
    )
    monkeypatch.setattr(
        holdingsApi.ProductModel,
        "get_by_id",
        lambda product_id: SimpleNamespace(nav=Decimal("1.1000"), nav_date=date.today()),
    )
    monkeypatch.setattr(
        holdingsApi.ProductNavHistoryModel,
        "find_latest_before",
        lambda product_id, before_date: SimpleNamespace(nav=Decimal("1.0000")),
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token")

    response = holdingsApi.get_today_profit(credentials)

    assert response.data["today_profit"] == 10.0
    assert response.data["today_profit_rate"] == 10.0
    assert response.data["calculation_source"] == "market_nav"


def test_money_market_simulation_uses_small_positive_daily_rate():
    product = SimpleNamespace(
        id=9, product_type="公募基金", product_name="XX货币市场基金", risk_level="R1"
    )

    rate = holdingsApi._simulated_daily_rate(7, product, date.today())

    assert Decimal("0.01") <= rate <= Decimal("0.02")
    assert rate == rate.quantize(Decimal("0.01"))
