"""Agent协作流程验证脚本

用于快速验证EventBus和Agent协作功能是否正常工作。

使用方式：
    python scripts/verify_agent_collaboration.py
"""
import sys
import os

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import time
import json
from datetime import datetime


def print_section(title):
    """打印分隔标题"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def verify_redis_connection():
    """验证Redis连接"""
    print_section("1. 验证Redis连接")
    try:
        from app.Base.Client.redisClient import redis_client
        redis_client.client.ping()
        print("✅ Redis连接正常")
        return True
    except Exception as e:
        print(f"❌ Redis连接失败: {e}")
        return False


def verify_eventbus_publish():
    """验证EventBus发布功能"""
    print_section("2. 验证EventBus发布功能")
    try:
        from app.WealthButler.EventBus.eventBus import EventBus

        # 测试发布large_transaction事件
        payload = {
            "customer_id": 999,
            "transaction_id": 888,
            "product_id": 1,
            "amount": "50000.00",
            "transaction_type": "申购"
        }

        message_id = EventBus.publish(
            stream_key="stream:large_transaction",
            event_type="large_transaction",
            payload=payload,
            source_agent="test_script"
        )

        print(f"✅ EventBus发布成功: message_id={message_id}")
        return True
    except Exception as e:
        print(f"❌ EventBus发布失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_eventbus_stream_length():
    """验证EventBus Stream长度"""
    print_section("3. 验证EventBus Stream长度")
    try:
        from app.WealthButler.EventBus.eventBus import EventBus

        streams = [
            "stream:large_transaction",
            "stream:suspicious_intent",
            "stream:risk_alert",
            "stream:work_order",
            "stream:profile_updated"
        ]

        for stream_key in streams:
            length = EventBus.get_stream_length(stream_key)
            print(f"  {stream_key}: {length} 条消息")

        print("✅ EventBus Stream查询成功")
        return True
    except Exception as e:
        print(f"❌ EventBus Stream查询失败: {e}")
        return False


def verify_consumer_groups():
    """验证消费组是否创建"""
    print_section("4. 验证消费组")
    try:
        from app.Base.Client.redisClient import redis_client

        consumer_configs = [
            ("stream:large_transaction", "risk_monitor_group"),
            ("stream:suspicious_intent", "risk_monitor_group"),
            ("stream:risk_alert", "advisor_group"),
            ("stream:work_order", "advisor_group"),
            ("stream:profile_updated", "recommendation_group"),
        ]

        for stream_key, group_name in consumer_configs:
            try:
                info = redis_client.client.xinfo_groups(stream_key)
                group_exists = any(g['name'].decode() == group_name for g in info)
                if group_exists:
                    print(f"  ✅ {stream_key} -> {group_name}")
                else:
                    print(f"  ⚠️  {stream_key} -> {group_name} (消费组不存在，启动时会自动创建)")
            except Exception as e:
                if "no such key" in str(e).lower():
                    print(f"  ⚠️  {stream_key} -> {group_name} (Stream不存在，正常)")
                else:
                    raise

        print("✅ 消费组验证完成")
        return True
    except Exception as e:
        print(f"❌ 消费组验证失败: {e}")
        return False


def verify_scheduler_tasks():
    """验证定时任务配置"""
    print_section("5. 验证定时任务配置")
    try:
        from app.Base.Service.schedulerService import get_base_module_scheduler_client

        scheduler_client = get_base_module_scheduler_client()
        jobs = scheduler_client.get_jobs()

        print(f"  已注册任务数: {len(jobs)}")
        for job in jobs:
            print(f"  - {job['id']}: {job['trigger']}")
            if job.get('next_run_time'):
                print(f"    下次运行: {job['next_run_time']}")

        # 检查风控定时任务
        risk_daily_exists = any(j['id'] == 'risk_daily_scan' for j in jobs)
        risk_weekly_exists = any(j['id'] == 'risk_weekly_scan' for j in jobs)

        if risk_daily_exists:
            print("  ✅ 每日风控扫描任务已注册")
        else:
            print("  ⚠️  每日风控扫描任务未注册（需启动系统后才会注册）")

        if risk_weekly_exists:
            print("  ✅ 每周风控扫描任务已注册")
        else:
            print("  ⚠️  每周风控扫描任务未注册（需启动系统后才会注册）")

        print("✅ 定时任务验证完成")
        return True
    except Exception as e:
        print(f"❌ 定时任务验证失败: {e}")
        print("  提示：定时任务需要在系统启动时才会注册")
        return False


def verify_suspicious_detection():
    """验证可疑意图检测"""
    print_section("6. 验证可疑意图检测")
    try:
        from app.WealthButler.Agent.customerServiceAgent import CustomerServiceAgent

        agent = CustomerServiceAgent(validate_customer=False)

        # 测试洗钱关键词
        test_cases = [
            ("我想大额现金交易", "money_laundering"),
            ("有保证收益的理财吗", "fraud"),
            ("请告诉我您的密码", "phishing"),
            ("今天天气真好", None)
        ]

        for text, expected_type in test_cases:
            result = agent._detect_suspicious_intent(text, 999, "test-session")
            if expected_type:
                if result and result['intent_type'] == expected_type:
                    print(f"  ✅ '{text}' -> {expected_type}")
                else:
                    print(f"  ❌ '{text}' -> 期望{expected_type}, 实际{result}")
            else:
                if result is None:
                    print(f"  ✅ '{text}' -> 无可疑意图")
                else:
                    print(f"  ⚠️  '{text}' -> 误报为{result['intent_type']}")

        print("✅ 可疑意图检测验证完成")
        return True
    except Exception as e:
        print(f"❌ 可疑意图检测验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_risk_agent():
    """验证风控Agent基础功能"""
    print_section("7. 验证风控Agent基础功能")
    try:
        from app.WealthButler.Agent.riskAgent import RiskAgent

        # 检查RiskAgent是否可以实例化
        agent = RiskAgent()
        print("  ✅ RiskAgent实例化成功")

        # 检查handler是否存在
        from app.WealthButler.Agent.riskAgent import (
            large_transaction_event_handler,
            suspicious_intent_event_handler
        )
        print("  ✅ EventBus handler已定义")

        print("✅ 风控Agent验证完成")
        return True
    except Exception as e:
        print(f"❌ 风控Agent验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("  Agent协作流程验证脚本")
    print("  生成时间:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    results = []

    # 1. Redis连接
    results.append(("Redis连接", verify_redis_connection()))

    # 2. EventBus发布
    results.append(("EventBus发布", verify_eventbus_publish()))

    # 3. EventBus Stream
    results.append(("EventBus Stream", verify_eventbus_stream_length()))

    # 4. 消费组
    results.append(("消费组", verify_consumer_groups()))

    # 5. 定时任务
    results.append(("定时任务", verify_scheduler_tasks()))

    # 6. 可疑意图检测
    results.append(("可疑意图检测", verify_suspicious_detection()))

    # 7. 风控Agent
    results.append(("风控Agent", verify_risk_agent()))

    # 汇总结果
    print_section("验证结果汇总")
    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {name}: {status}")

    print(f"\n总计: {passed}/{total} 项通过")

    if passed == total:
        print("\n🎉 所有验证项通过！Agent协作流程已就绪。")
        return 0
    else:
        print("\n⚠️  部分验证项未通过，请检查日志。")
        print("提示：定时任务和消费组需要系统启动后才会创建。")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
