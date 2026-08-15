"""
业务负责人反馈问题修复脚本

修复内容：
1. WorkOrderModel: order_type增加"客户转介"，status默认改为"待处理"，增加"已驳回"状态
2. Permission: 增加8个业务操作权限常量
3. EventBus consumer.py: 修复tx_type字段名错误
4. EventBus eventBus.py: 修复get_redis_client()调用、datetime导入、event_type命名
5. EventBus ACK时机修复：改为成功后ACK，保证at-least-once语义
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def generate_fixes():
    """生成修复文件内容"""

    fixes = []

    # ==================== 修复1: WorkOrderModel ====================
    fixes.append({
        'file': 'app/WealthButler/Models/workOrderModel.py',
        'description': 'WorkOrderModel: 增加客户转介类型，修改默认状态为待处理，增加已驳回状态',
        'old_order_type': "'风控预警','投诉','咨询','账户变更','业务申请','系统故障'",
        'new_order_type': "'风控预警','投诉','咨询','账户变更','业务申请','系统故障','客户转介'",
        'old_status': "'待分配','处理中','待审核','已完成','已关闭'",
        'new_status': "'待处理','处理中','待审核','已完成','已驳回'",
        'old_default_status': "DEFAULT '待分配'",
        'new_default_status': "DEFAULT '待处理'",
        'old_find_pending': "WHERE status IN ('待分配', '处理中')",
        'new_find_pending': "WHERE status IN ('待处理', '处理中')"
    })

    # ==================== 修复2: Permission常量 ====================
    fixes.append({
        'file': 'app/Base/Middleware/rbac.py (或新建permission.py)',
        'description': '增加8个业务操作权限常量',
        'new_permissions': """
# 业务操作权限
OPERATION_PURCHASE = "operation:purchase"           # 申购操作
OPERATION_REDEEM = "operation:redeem"               # 赎回操作
OPERATION_TRANSFER = "operation:transfer"           # 转账操作
RISK_REASSESS = "risk:reassess"                     # 风险重评
CUSTOMER_INFO_UPDATE = "customer:info_update"       # 客户信息更新
PRODUCT_QUERY = "product:query"                     # 产品查询
RISK_SUSPICIOUS_REPORT = "risk:suspicious_report"   # 可疑行为上报
WORKORDER_CREATE = "workorder:create"               # 创建工单
"""
    })

    # ==================== 修复3: consumer.py tx_type字段 ====================
    fixes.append({
        'file': 'app/WealthButler/EventBus/consumer.py',
        'description': '修复tx_type字段名为transaction_type',
        'line': 82,
        'old': 'f"tx_type={event.tx_type}"',
        'new': 'f"transaction_type={event.transaction_type}"'
    })

    # ==================== 修复4: eventBus.py多处错误 ====================
    fixes.append({
        'file': 'app/WealthButler/EventBus/eventBus.py',
        'description': '修复get_redis_client()调用、datetime导入、event_type统一',
        'issues': [
            '调用了未定义的get_redis_client()，应改为RedisClientSingleton()',
            '死信逻辑使用datetime但未导入',
            'event_type="large_transaction_detected"应统一为"large_transaction"'
        ]
    })

    # ==================== 修复5: ACK时机 ====================
    fixes.append({
        'file': 'app/WealthButler/EventBus/eventBus.py consume()方法',
        'description': 'ACK时机修正：改为Handler成功后ACK，保证at-least-once语义',
        'current_logic': '先ACK再执行Handler，Handler失败无法重放',
        'new_logic': 'Handler成功后ACK，失败则不ACK留在PEL中待重放，或写入死信队列'
    })

    return fixes


def print_fixes():
    """打印所有修复项"""
    fixes = generate_fixes()

    print("=" * 80)
    print("业务负责人反馈问题修复清单")
    print("=" * 80)

    for i, fix in enumerate(fixes, 1):
        print(f"\n[修复 {i}] {fix['description']}")
        print(f"文件: {fix['file']}")

        if 'old_order_type' in fix:
            print(f"\norder_type枚举:")
            print(f"  旧: {fix['old_order_type']}")
            print(f"  新: {fix['new_order_type']}")

            print(f"\nstatus枚举:")
            print(f"  旧: {fix['old_status']}")
            print(f"  新: {fix['new_status']}")

            print(f"\n默认状态:")
            print(f"  旧: {fix['old_default_status']}")
            print(f"  新: {fix['new_default_status']}")

            print(f"\nfind_pending()查询:")
            print(f"  旧: {fix['old_find_pending']}")
            print(f"  新: {fix['new_find_pending']}")

        elif 'new_permissions' in fix:
            print(fix['new_permissions'])

        elif 'line' in fix:
            print(f"行号: {fix['line']}")
            print(f"  旧: {fix['old']}")
            print(f"  新: {fix['new']}")

        elif 'issues' in fix:
            print("问题列表:")
            for issue in fix['issues']:
                print(f"  - {issue}")

        elif 'current_logic' in fix:
            print(f"当前逻辑: {fix['current_logic']}")
            print(f"修正逻辑: {fix['new_logic']}")

    print("\n" + "=" * 80)
    print("[重要提醒]")
    print("=" * 80)
    print("1. 存量数据迁移: 请先检查biz_work_order表中是否有'待分配'/'已关闭'状态数据")
    print("2. 如有存量数据，需要先迁移:")
    print("   UPDATE biz_work_order SET status='待处理' WHERE status='待分配';")
    print("   UPDATE biz_work_order SET status='已完成' WHERE status='已关闭';")
    print("3. ACK时机修改会影响at-least-once语义，需要完整测试消费重放")
    print("4. 大额事件payload已冻结: customer_id + transaction_id必填")
    print("=" * 80)


if __name__ == "__main__":
    print_fixes()
