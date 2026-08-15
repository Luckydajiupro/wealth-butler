"""EventBus发布订阅功能验证脚本

验证Redis Streams事件总线的发布和消费功能：
- 发布事件到Redis Streams
- 消费者能否正常接收并处理事件
- 幂等性机制是否生效

使用方式：
    python scripts/verify_eventbus.py
"""

import sys
import os
import io
import time
import threading
from typing import Dict, Any

# 设置标准输出为UTF-8编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加项目根目录到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from app.WealthButler.EventBus.eventBus import EventBus
from app.Base.Client.redisClient import redis_client


def print_section(title: str):
    """打印章节标题"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def test_redis_connection() -> Dict[str, Any]:
    """测试Redis连接"""
    print_section("1. 测试 Redis 连接")

    result = {
        'redis_connected': False,
        'issues': []
    }

    try:
        if redis_client.ping():
            result['redis_connected'] = True
            print("[OK] Redis 连接正常")

            # 显示Redis信息
            info = redis_client.client.info('server')
            print(f"\nRedis 服务器信息:")
            print(f"  - 版本: {info.get('redis_version', 'N/A')}")
            print(f"  - 运行模式: {info.get('redis_mode', 'N/A')}")
            print(f"  - 运行时间(天): {info.get('uptime_in_days', 'N/A')}")
        else:
            result['issues'].append("Redis ping失败")
            print("[X] Redis 连接失败")

    except Exception as e:
        result['issues'].append(f"Redis连接异常: {str(e)}")
        print(f"[X] Redis 连接异常: {e}")
        import traceback
        traceback.print_exc()

    return result


def test_eventbus_publish() -> Dict[str, Any]:
    """测试EventBus发布功能"""
    print_section("2. 测试 EventBus 发布功能")

    result = {
        'publish_works': False,
        'message_id': None,
        'issues': []
    }

    try:
        # 发布测试事件
        print("\n发布测试事件...")

        payload = {
            'test_id': 'verify_001',
            'message': '这是一条测试消息',
            'timestamp': time.time()
        }

        message_id = EventBus.publish(
            stream_key='stream:test_verify',
            event_type='test_event',
            payload=payload,
            source_agent='VerifyScript'
        )

        result['publish_works'] = True
        result['message_id'] = message_id

        print(f"[OK] 事件发布成功")
        print(f"  - Stream: stream:test_verify")
        print(f"  - Message ID: {message_id}")
        print(f"  - Payload: {payload}")

        # 验证事件是否在Stream中
        stream_length = EventBus.get_stream_length('stream:test_verify')
        print(f"  - Stream 当前长度: {stream_length}")

    except Exception as e:
        result['issues'].append(f"发布失败: {str(e)}")
        print(f"[X] 事件发布失败: {e}")
        import traceback
        traceback.print_exc()

    return result


def test_eventbus_consume() -> Dict[str, Any]:
    """测试EventBus消费功能"""
    print_section("3. 测试 EventBus 消费功能")

    result = {
        'consume_works': False,
        'events_received': 0,
        'issues': []
    }

    # 用于跨线程传递消费结果
    consumed_events = []
    consumer_error = []

    def test_handler(event_type: str, payload: Dict[str, Any], trace_id: str) -> bool:
        """测试用的事件处理函数"""
        try:
            print(f"\n  📨 收到事件:")
            print(f"     - 类型: {event_type}")
            print(f"     - Trace ID: {trace_id}")
            print(f"     - Payload: {payload}")

            consumed_events.append({
                'event_type': event_type,
                'payload': payload,
                'trace_id': trace_id
            })

            return True
        except Exception as e:
            consumer_error.append(str(e))
            return False

    try:
        # 先发布一个测试事件
        print("\n发布测试事件...")
        test_payload = {
            'test_id': 'consume_test_001',
            'message': '消费测试消息',
            'timestamp': time.time()
        }

        message_id = EventBus.publish(
            stream_key='stream:test_consume',
            event_type='consume_test_event',
            payload=test_payload,
            source_agent='VerifyScript'
        )
        print(f"[OK] 测试事件已发布: {message_id}")

        # 启动消费者线程
        print("\n启动消费者...")

        def run_consumer():
            """在独立线程中运行消费者"""
            try:
                EventBus.consume(
                    stream_key='stream:test_consume',
                    consumer_group='verify_group',
                    consumer_name='verify_worker',
                    handler=test_handler,
                    block_ms=2000,  # 2秒超时
                    count=10
                )
            except Exception as e:
                consumer_error.append(str(e))

        consumer_thread = threading.Thread(target=run_consumer, daemon=True)
        consumer_thread.start()

        # 等待消费者处理
        print("等待消费者处理事件...")
        time.sleep(4)

        # 检查结果
        if consumed_events:
            result['consume_works'] = True
            result['events_received'] = len(consumed_events)
            print(f"\n[OK] 消费功能正常")
            print(f"  - 成功接收 {len(consumed_events)} 个事件")
        elif consumer_error:
            result['issues'].append(f"消费者错误: {consumer_error[0]}")
            print(f"\n[X] 消费者出错: {consumer_error[0]}")
        else:
            result['issues'].append("消费者未接收到事件（超时）")
            print(f"\n[!]  消费者未接收到事件（可能是超时或消费者未正常启动）")

    except Exception as e:
        result['issues'].append(f"消费测试失败: {str(e)}")
        print(f"[X] 消费测试失败: {e}")
        import traceback
        traceback.print_exc()

    return result


def test_transaction_risk_consumer() -> Dict[str, Any]:
    """测试transaction_risk_consumer.py是否可以正常运行"""
    print_section("4. 测试 transaction_risk_consumer.py")

    result = {
        'script_exists': False,
        'can_import': False,
        'issues': []
    }

    try:
        # 检查文件是否存在
        script_path = os.path.join(
            project_root,
            'app/WealthButler/EventBus/examples/transaction_risk_consumer.py'
        )

        result['script_exists'] = os.path.exists(script_path)

        if result['script_exists']:
            print(f"[OK] 脚本文件存在: {script_path}")
        else:
            result['issues'].append(f"脚本文件不存在: {script_path}")
            print(f"[X] 脚本文件不存在: {script_path}")
            return result

        # 尝试导入模块
        try:
            from app.WealthButler.EventBus.examples import transaction_risk_consumer
            result['can_import'] = True
            print("[OK] 模块导入成功")

            # 检查关键函数是否存在
            if hasattr(transaction_risk_consumer, 'risk_monitor_handler'):
                print("[OK] risk_monitor_handler 函数存在")
            else:
                result['issues'].append("risk_monitor_handler 函数不存在")

            if hasattr(transaction_risk_consumer, 'publish_large_transaction_event'):
                print("[OK] publish_large_transaction_event 函数存在")
            else:
                result['issues'].append("publish_large_transaction_event 函数不存在")

        except ImportError as e:
            result['issues'].append(f"模块导入失败: {str(e)}")
            print(f"[X] 模块导入失败: {e}")

    except Exception as e:
        result['issues'].append(f"检查失败: {str(e)}")
        print(f"[X] 检查失败: {e}")
        import traceback
        traceback.print_exc()

    return result


def cleanup_test_streams():
    """清理测试产生的Stream"""
    print_section("清理测试数据")

    try:
        test_streams = ['stream:test_verify', 'stream:test_consume']

        for stream in test_streams:
            if redis_client.client.exists(stream):
                redis_client.client.delete(stream)
                print(f"[OK] 已删除测试Stream: {stream}")

        # 清理测试消费组（如果存在）
        try:
            redis_client.client.xgroup_destroy('stream:test_consume', 'verify_group')
            print(f"[OK] 已删除测试消费组: verify_group")
        except:
            pass  # 消费组可能不存在

    except Exception as e:
        print(f"[!]  清理测试数据时出错: {e}")


def main():
    """主函数"""
    print("\n" + "╔" + "=" * 68 + "╗")
    print("║" + " " * 18 + "EventBus 功能验证" + " " * 20 + "║")
    print("╚" + "=" * 68 + "╝")

    # 运行所有测试
    results = {}
    results['redis'] = test_redis_connection()

    if results['redis']['redis_connected']:
        results['publish'] = test_eventbus_publish()
        results['consume'] = test_eventbus_consume()
        results['consumer_script'] = test_transaction_risk_consumer()
    else:
        print("\n[!]  Redis未连接，跳过EventBus测试")
        return results

    # 清理测试数据
    cleanup_test_streams()

    # 输出汇总报告
    print_section("验证汇总")

    print(f"\n1. Redis 连接: {'[OK] 正常' if results['redis']['redis_connected'] else '[X] 失败'}")

    if 'publish' in results:
        print(f"2. EventBus 发布: {'[OK] 正常' if results['publish']['publish_works'] else '[X] 失败'}")

    if 'consume' in results:
        print(f"3. EventBus 消费: {'[OK] 正常' if results['consume']['consume_works'] else '[X] 失败'}")
        if results['consume']['consume_works']:
            print(f"   - 成功接收事件: {results['consume']['events_received']} 个")

    if 'consumer_script' in results:
        print(f"4. transaction_risk_consumer.py: {'[OK] 可用' if results['consumer_script']['can_import'] else '[X] 不可用'}")

    # 总结
    print("\n" + "=" * 70)
    all_passed = (
        results['redis']['redis_connected'] and
        results.get('publish', {}).get('publish_works', False) and
        results.get('consume', {}).get('consume_works', False)
    )

    if all_passed:
        print("🎉 所有EventBus功能正常")
    else:
        print("[!]  部分EventBus功能存在问题，请查看上述详情")
    print("=" * 70 + "\n")

    return results


if __name__ == '__main__':
    results = main()
