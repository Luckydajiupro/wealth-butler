#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证新增API端点的可用性
"""
import sys
import io
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_URL = "http://localhost:8010"

def test_new_endpoints():
    """测试新增的5个API端点"""
    print("=" * 60)
    print("验证新增API端点")
    print("=" * 60)
    print()

    # 登录获取token
    print("[1/6] 登录获取Token...")
    login_resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": "admin", "password": "123456"},
        timeout=10
    )

    if login_resp.status_code != 200:
        print(f"✗ 登录失败: {login_resp.status_code}")
        return

    token = login_resp.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"✓ 登录成功")
    print()

    # 测试新增的5个端点
    tests = [
        {
            "name": "统计数据",
            "method": "GET",
            "url": "/api/wealth/analyst/statistics",
            "expected_keys": ["total_customers", "total_aum", "total_transactions_today", "total_alerts_pending"]
        },
        {
            "name": "查询历史（简化版）",
            "method": "GET",
            "url": "/api/wealth/analyst/history?limit=5",
            "expected_keys": ["history"]
        },
        {
            "name": "客户画像",
            "method": "GET",
            "url": "/api/wealth/analyst/profile/1001",
            "expected_keys": ["customer_id", "username", "risk_level"]
        },
        {
            "name": "风险评估问卷",
            "method": "GET",
            "url": "/api/wealth/analyst/risk-assessment/questionnaire",
            "expected_keys": ["questions"]
        },
        {
            "name": "提交风险评估",
            "method": "POST",
            "url": "/api/wealth/analyst/risk-assessment/submit",
            "payload": {
                "customer_id": 1001,
                "answers": {"1": "A", "2": "B", "3": "A", "4": "B", "5": "C"}
            },
            "expected_keys": ["customer_id", "risk_level", "total_score"]
        }
    ]

    passed = 0
    failed = 0

    for i, test in enumerate(tests, start=2):
        print(f"[{i}/6] 测试: {test['name']}")
        print(f"     {test['method']} {test['url']}")

        try:
            if test['method'] == 'GET':
                resp = requests.get(f"{BASE_URL}{test['url']}", headers=headers, timeout=10)
            else:
                resp = requests.post(
                    f"{BASE_URL}{test['url']}",
                    headers=headers,
                    json=test.get('payload'),
                    timeout=10
                )

            if resp.status_code == 200:
                data = resp.json().get('data', {})
                missing_keys = [k for k in test['expected_keys'] if k not in data]

                if missing_keys:
                    print(f"     ✗ 缺少字段: {missing_keys}")
                    failed += 1
                else:
                    print(f"     ✓ 成功 (HTTP 200, 数据完整)")
                    passed += 1
            else:
                print(f"     ✗ 失败 (HTTP {resp.status_code})")
                print(f"     响应: {resp.text[:100]}")
                failed += 1

        except Exception as e:
            print(f"     ✗ 异常: {e}")
            failed += 1

        print()

    print("=" * 60)
    print(f"测试完成: {passed} 通过, {failed} 失败")
    print("=" * 60)

if __name__ == "__main__":
    test_new_endpoints()
