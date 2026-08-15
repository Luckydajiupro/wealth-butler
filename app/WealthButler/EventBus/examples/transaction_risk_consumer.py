"""交易风控事件消费示例

演示场景：大额交易事件 → 风控监测 Agent 消费 → 触发反洗钱规则 → 写入风控告警表

使用方式：
    python app/WealthButler/EventBus/examples/transaction_risk_consumer.py

功能说明：
    1. 模拟发布大额交易事件到 stream:large_transaction
    2. 风控监测消费者消费该事件
    3. 应用反洗钱规则 RW-001（单日累计交易 ≥5万）
    4. 触发告警写入 fin_risk_alert 表
    5. 打印完整处理流程日志

开发者可复用本示例：
    - 替换 stream_key 为自己的业务队列
    - 修改 handler 函数实现自己的业务逻辑
    - 调整 event_type 和 payload 结构
"""

import sys
import os
import time
import threading
from decimal import Decimal
from datetime import datetime

# 添加项目根目录到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, project_root)

from app.WealthButler.EventBus.eventBus import EventBus
from app.WealthButler.Models.riskAlertModel import RiskAlertModel


# ══════════════════════════════════════════════════════════════
# 第一部分：事件发布（Producer）
# ══════════════════════════════════════════════════════════════

def publish_large_transaction_event():
    """模拟发布大额交易事件

    业务场景：用户完成一笔 60000 元的基金购买，触发大额交易监控
    """
    print("\n" + "="*60)
    print("【步骤 1】发布大额交易事件")
    print("="*60)

    # 构造交易事件载荷
    payload = {
        'transaction_id': 202408150001,
        'customer_id': 1001,
        'customer_name': '张三',
        'product_code': 'FUND_005827',
        'product_name': '易方达蓝筹精选混合',
        'transaction_type': 'buy',
        'amount': 60000.00,
        'transaction_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'channel': 'mobile_app'
    }

    # 发布到 stream:large_transaction
    message_id = EventBus.publish(
        stream_key='stream:large_transaction',
        event_type='large_transaction_detected',
        payload=payload
    )

    print(f"✅ 事件已发布")
    print(f"   Stream Key: stream:large_transaction")
    print(f"   Message ID: {message_id}")
    print(f"   交易金额: ¥{payload['amount']:,.2f}")
    print(f"   客户: {payload['customer_name']} (ID: {payload['customer_id']})")
    print(f"   产品: {payload['product_name']}")


# ══════════════════════════════════════════════════════════════
# 第二部分：事件消费（Consumer）
# ══════════════════════════════════════════════════════════════

def risk_monitor_handler(event_type: str, payload: dict, trace_id: str) -> bool:
    """风控监测 Agent 的事件处理函数

    Args:
        event_type: 事件类型（如 large_transaction_detected）
        payload: 事件载荷（业务数据）
        trace_id: 分布式跟踪 ID

    Returns:
        bool: True 表示处理成功（ACK），False 表示失败（不 ACK，保留在 Pending List）
    """
    print("\n" + "="*60)
    print("【步骤 2】风控监测 Agent 消费事件")
    print("="*60)
    print(f"事件类型: {event_type}")
    print(f"跟踪 ID: {trace_id}")
    print(f"交易金额: ¥{payload['amount']:,.2f}")

    try:
        # ──────────────────────────────────────────────────────
        # 步骤 2.1：应用反洗钱规则 RW-001
        # ──────────────────────────────────────────────────────
        print("\n【步骤 2.1】应用反洗钱规则 RW-001")

        amount = payload['amount']
        threshold = 50000.00

        if amount >= threshold:
            print(f"⚠️  触发规则: 单日累计交易 ≥ ¥{threshold:,.2f}")
            print(f"   实际金额: ¥{amount:,.2f}")
            print(f"   超出金额: ¥{amount - threshold:,.2f}")

            # ──────────────────────────────────────────────────
            # 步骤 2.2：写入风控告警表
            # ──────────────────────────────────────────────────
            print("\n【步骤 2.2】写入风控告警表")

            alert = RiskAlertModel(
                customer_id=payload['customer_id'],
                rule_id='RW-001',
                rule_name='单日累计交易金额超阈值',
                severity='high',
                confidence=Decimal('0.95'),
                trigger_details={
                    'threshold': threshold,
                    'actual_amount': amount,
                    'excess_amount': amount - threshold,
                    'transaction_type': payload['transaction_type'],
                    'product_code': payload['product_code'],
                    'channel': payload['channel'],
                    'trace_id': trace_id
                },
                related_transaction_id=payload['transaction_id'],
                status='待处理'
            )

            # 保存到数据库
            alert.save()
            print(f"✅ 风控告警已入库")
            print(f"   告警 ID: {alert.id}")
            print(f"   规则: {alert.rule_id} - {alert.rule_name}")
            print(f"   严重程度: {alert.severity}")
            print(f"   置信度: {alert.confidence}")
            print(f"   状态: {alert.status}")

        else:
            print(f"✓ 未触发规则（金额 ¥{amount:,.2f} < 阈值 ¥{threshold:,.2f}）")

        # ──────────────────────────────────────────────────────
        # 步骤 2.3：返回处理成功
        # ──────────────────────────────────────────────────────
        print("\n【步骤 2.3】处理完成，返回 ACK")
        return True

    except Exception as e:
        print(f"\n❌ 处理失败: {e}")
        import traceback
        traceback.print_exc()
        # 返回 False，消息保留在 Pending List，等待重试
        return False


def start_risk_monitor_consumer():
    """启动风控监测消费者（阻塞式，常驻后台）"""
    print("\n" + "="*60)
    print("【步骤 3】启动风控监测消费者")
    print("="*60)
    print("消费组: risk_monitor_group")
    print("消费者: worker-1")
    print("Stream: stream:large_transaction")
    print("\n等待事件...")

    # 阻塞式消费（会一直运行直到 KeyboardInterrupt）
    EventBus.consume(
        stream_key='stream:large_transaction',
        consumer_group='risk_monitor_group',
        consumer_name='worker-1',
        handler=risk_monitor_handler,
        block_ms=5000,  # 阻塞超时 5 秒
        count=10  # 每次最多拉取 10 条
    )


# ══════════════════════════════════════════════════════════════
# 第三部分：完整流程演示（发布 + 消费）
# ══════════════════════════════════════════════════════════════

def demo_full_flow():
    """完整流程演示：先启动消费者，再发布事件"""

    print("\n" + "╔" + "="*58 + "╗")
    print("║" + " "*15 + "交易风控事件消费示例" + " "*15 + "║")
    print("╚" + "="*58 + "╝")

    # 在独立线程中启动消费者（避免阻塞主线程）
    consumer_thread = threading.Thread(
        target=start_risk_monitor_consumer,
        daemon=True  # 守护线程，主线程退出时自动退出
    )
    consumer_thread.start()

    # 等待消费者启动
    time.sleep(2)

    # 发布事件
    publish_large_transaction_event()

    # 等待消费者处理完成
    print("\n等待消费者处理...")
    time.sleep(3)

    # 查询结果
    print("\n" + "="*60)
    print("【步骤 4】查询风控告警记录")
    print("="*60)

    alerts = RiskAlertModel.find_by_customer_id(customer_id=1001, limit=5)
    if alerts:
        print(f"✅ 查询到 {len(alerts)} 条告警记录：\n")
        for alert in alerts:
            print(f"  • ID: {alert.id} | 规则: {alert.rule_id} | "
                  f"严重程度: {alert.severity} | 状态: {alert.status}")
            print(f"    创建时间: {alert.created_at}")
            print(f"    触发详情: {alert.trigger_details}\n")
    else:
        print("⚠️  未查询到告警记录")

    print("\n" + "="*60)
    print("【演示完成】")
    print("="*60)
    print("\n提示：")
    print("  1. 消费者线程仍在后台运行，等待新事件")
    print("  2. 按 Ctrl+C 退出程序")
    print("  3. 实际部署时应使用进程管理工具（如 Supervisor）运行消费者")


if __name__ == '__main__':
    demo_full_flow()

    # 保持主线程运行，让消费者继续工作
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n程序已退出")
