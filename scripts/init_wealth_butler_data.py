#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
财富管家Mock数据初始化脚本
为所有业务表生成测试数据，支持前端页面和API测试

执行方式：
    python scripts/init_wealth_butler_data.py
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal
import random

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.Base.Service.authService import AuthService
from app.Base.Models.userModel import UserModel
from app.Base.Models.roleModel import RoleModel
from app.Base.Models.userRoleModel import UserRoleModel
from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel
from app.WealthButler.Models.productModel import ProductModel
from app.WealthButler.Models.holdingsModel import HoldingsModel
from app.WealthButler.Models.transactionModel import TransactionModel
from app.WealthButler.Models.workOrderModel import WorkOrderModel
from app.WealthButler.Models.riskAlertModel import RiskAlertModel


def init_roles():
    """初始化角色（确保预置角色存在）"""
    print("\n=== 初始化角色 ===")
    RoleModel.ensure_builtin_roles(source_module="fin")
    print("✓ 预置角色已确保存在")


def init_users():
    """初始化测试用户（2个客户 + 4个员工）"""
    print("\n=== 初始化用户 ===")

    users_data = [
        # 客户账号
        {
            "username": "customer_zhang",
            "password": "123456",
            "user_type": "CUSTOMER",
            "customer_level": "钻石",
            "extra_data": {"real_name": "张先生", "id_card": "110101198001011234"},
            "role_name": "user",
        },
        {
            "username": "customer_li",
            "password": "123456",
            "user_type": "CUSTOMER",
            "customer_level": "白金",
            "extra_data": {"real_name": "李女士", "id_card": "110101199001015678"},
            "role_name": "user",
        },
        # 员工账号
        {
            "username": "advisor_wang",
            "password": "123456",
            "user_type": "EMPLOYEE",
            "employee_role": "理财顾问",
            "advisor_level": "高级",
            "extra_data": {"real_name": "王顾问"},
            "role_name": "advisor",
        },
        {
            "username": "risk_zhao",
            "password": "123456",
            "user_type": "EMPLOYEE",
            "employee_role": "风控专员",
            "extra_data": {"real_name": "赵专员"},
            "role_name": "risk_officer",
        },
        {
            "username": "operator_liu",
            "password": "123456",
            "user_type": "EMPLOYEE",
            "employee_role": "客户经理",
            "extra_data": {"real_name": "刘经理"},
            "role_name": "operator",
        },
        {
            "username": "admin",
            "password": "123456",
            "user_type": "EMPLOYEE",
            "employee_role": "业务管理员",
            "extra_data": {"real_name": "系统管理员"},
            "role_name": "business_admin",
        },
    ]

    created_users = {}

    for user_data in users_data:
        username = user_data["username"]

        # 检查用户是否已存在
        existing = UserModel.find_by_username(username)
        if existing:
            print(f"  用户 {username} 已存在，跳过创建")
            created_users[username] = existing
            continue

        # 创建用户（使用BaseUserExtModel以支持扩展字段）
        user = BaseUserExtModel(
            username=username,
            password_hash=AuthService.hash_password(user_data["password"]),
            source_module="fin",
            status="active",
            user_type=user_data.get("user_type", "CUSTOMER"),
            employee_role=user_data.get("employee_role"),
            advisor_level=user_data.get("advisor_level"),
            customer_level=user_data.get("customer_level", "普通"),
            extra_data=user_data.get("extra_data"),
        )

        user_id = user.save()
        if user_id > 0:
            print(f"✓ 创建用户: {username} (ID={user_id})")
            created_users[username] = user

            # 分配角色
            role_name = user_data["role_name"]
            role = RoleModel.find_by_name(role_name, source_module="fin")
            if role:
                UserRoleModel.grant_role(user_id, role.id, source_module="fin")
                print(f"  → 分配角色: {role.display_name}")
        else:
            print(f"✗ 创建用户 {username} 失败")

    return created_users


def init_products():
    """初始化理财产品（10个产品）"""
    print("\n=== 初始化理财产品 ===")

    products_data = [
        # 货币基金（R1）
        {"code": "MF001", "name": "天天宝货币A", "type": "公募基金", "risk": "R1", "min": 0.01, "nav": 1.0000, "manager": "某某基金"},
        {"code": "MF002", "name": "现金增利货币", "type": "公募基金", "risk": "R1", "min": 0.01, "nav": 1.0000, "manager": "某某基金"},

        # 债券基金（R2）
        {"code": "BF001", "name": "稳健债券A", "type": "公募基金", "risk": "R2", "min": 1000, "nav": 1.1234, "manager": "李经理"},
        {"code": "BF002", "name": "纯债增强", "type": "公募基金", "risk": "R2", "min": 1000, "nav": 1.0987, "manager": "王经理"},

        # 混合基金（R3）
        {"code": "HF001", "name": "平衡配置混合", "type": "公募基金", "risk": "R3", "min": 1000, "nav": 1.2567, "manager": "张经理"},
        {"code": "HF002", "name": "灵活配置A", "type": "公募基金", "risk": "R3", "min": 1000, "nav": 1.3456, "manager": "赵经理"},
        {"code": "HF003", "name": "稳健增长混合", "type": "公募基金", "risk": "R3", "min": 1000, "nav": 1.1890, "manager": "刘经理"},

        # 股票基金（R4）
        {"code": "SF001", "name": "成长精选股票", "type": "公募基金", "risk": "R4", "min": 1000, "nav": 1.4523, "manager": "钱经理"},
        {"code": "SF002", "name": "科技创新股票", "type": "公募基金", "risk": "R4", "min": 1000, "nav": 1.3789, "manager": "孙经理"},

        # 私募基金（R5）
        {"code": "PF001", "name": "量化对冲1号", "type": "私募基金", "risk": "R5", "min": 1000000, "nav": 1.5234, "manager": "周经理"},
    ]

    created_products = []

    for p in products_data:
        existing = ProductModel.find_by_product_code(p["code"])
        if existing:
            print(f"  产品 {p['code']} 已存在，跳过创建")
            created_products.append(existing)
            continue

        product = ProductModel(
            product_code=p["code"],
            product_name=p["name"],
            product_type=p["type"],
            risk_level=p["risk"],
            min_investment=Decimal(str(p["min"])),
            nav=Decimal(str(p["nav"])),
            nav_date=datetime.now(),
            fund_manager=p["manager"],
            status="在售",
        )

        product_id = product.save()
        if product_id > 0:
            print(f"✓ 创建产品: {p['code']} - {p['name']}")
            created_products.append(product)
        else:
            print(f"✗ 创建产品 {p['code']} 失败")

    return created_products


def init_holdings_and_transactions(users, products):
    """初始化客户持仓和交易记录"""
    print("\n=== 初始化持仓和交易记录 ===")

    customer_zhang = users.get("customer_zhang")
    customer_li = users.get("customer_li")

    if not customer_zhang or not customer_li:
        print("✗ 客户账号不存在，跳过持仓初始化")
        return

    # 张先生的持仓（5个产品，总资产约123万）
    zhang_holdings = [
        {"product_code": "MF001", "amount": 50000, "purchase_days_ago": 180},
        {"product_code": "BF001", "amount": 200000, "purchase_days_ago": 150},
        {"product_code": "HF001", "amount": 300000, "purchase_days_ago": 120},
        {"product_code": "SF001", "amount": 400000, "purchase_days_ago": 90},
        {"product_code": "PF001", "amount": 280000, "purchase_days_ago": 60},
    ]

    # 李女士的持仓（3个产品，总资产约56万）
    li_holdings = [
        {"product_code": "MF002", "amount": 80000, "purchase_days_ago": 200},
        {"product_code": "BF002", "amount": 200000, "purchase_days_ago": 160},
        {"product_code": "HF002", "amount": 280000, "purchase_days_ago": 100},
    ]

    def create_holdings_for_customer(customer, holdings_list, customer_name):
        for h in holdings_list:
            product = ProductModel.find_by_product_code(h["product_code"])
            if not product:
                print(f"  产品 {h['product_code']} 不存在，跳过")
                continue

            # 检查是否已有持仓
            existing = HoldingsModel.find_by_customer_and_product(customer.id, product.id)
            if existing:
                print(f"  {customer_name} 持仓 {h['product_code']} 已存在，跳过")
                continue

            # 计算持仓数据
            cost_amount = Decimal(str(h["amount"]))
            nav = product.nav or Decimal("1.0")
            shares = cost_amount / nav
            current_value = shares * nav
            profit_loss = current_value - cost_amount
            profit_ratio = profit_loss / cost_amount if cost_amount > 0 else Decimal("0")

            purchase_date = datetime.now() - timedelta(days=h["purchase_days_ago"])

            # 创建持仓记录
            holding = HoldingsModel(
                customer_id=customer.id,
                product_id=product.id,
                shares=shares,
                cost_amount=cost_amount,
                current_value=current_value,
                profit_loss=profit_loss,
                profit_ratio=profit_ratio,
                purchase_date=purchase_date,
            )

            holding_id = holding.save()
            if holding_id > 0:
                print(f"✓ {customer_name} 持仓: {h['product_code']} (成本={cost_amount}, 市值={current_value})")

                # 创建对应的申购交易记录
                transaction = TransactionModel(
                    customer_id=customer.id,
                    product_id=product.id,
                    transaction_type="申购",
                    amount=cost_amount,
                    shares=shares,
                    nav=nav,
                    fee=Decimal("0"),
                    status="成交",
                    transaction_time=purchase_date,
                    channel="APP",
                )

                trans_id = transaction.save()
                if trans_id > 0:
                    print(f"  → 创建交易记录 (ID={trans_id})")
            else:
                print(f"✗ 创建持仓失败")

    create_holdings_for_customer(customer_zhang, zhang_holdings, "张先生")
    create_holdings_for_customer(customer_li, li_holdings, "李女士")


def init_work_orders(users):
    """初始化工单数据（15条工单）"""
    print("\n=== 初始化工单数据 ===")

    customer_zhang = users.get("customer_zhang")
    customer_li = users.get("customer_li")
    advisor_wang = users.get("advisor_wang")
    operator_liu = users.get("operator_liu")

    if not all([customer_zhang, customer_li]):
        print("✗ 客户账号不存在，跳过工单初始化")
        return

    workorders_data = [
        # 客户转介（申购/赎回类）- 5条待处理
        {
            "type": "客户转介",
            "customer_id": customer_zhang.id,
            "customer_name": "张先生",
            "summary": "客户咨询申购成长精选股票基金50万元",
            "status": "待处理",
            "priority": "普通",
            "days_ago": 2,
        },
        {
            "type": "客户转介",
            "customer_id": customer_li.id,
            "customer_name": "李女士",
            "summary": "客户申请赎回灵活配置A基金部分份额",
            "status": "待处理",
            "priority": "普通",
            "days_ago": 1,
        },
        {
            "type": "客户转介",
            "customer_id": customer_zhang.id,
            "customer_name": "张先生",
            "summary": "客户咨询量化对冲1号私募基金追加投资",
            "status": "待处理",
            "priority": "紧急",
            "days_ago": 0,
        },
        {
            "type": "客户转介",
            "customer_id": customer_li.id,
            "customer_name": "李女士",
            "summary": "客户申购天天宝货币A 10万元",
            "status": "待处理",
            "priority": "普通",
            "days_ago": 3,
        },
        {
            "type": "客户转介",
            "customer_id": customer_zhang.id,
            "customer_name": "张先生",
            "summary": "客户赎回纯债增强基金全部份额",
            "status": "待处理",
            "priority": "普通",
            "days_ago": 1,
        },
        # 客户转介（转账类）- 3条待处理/处理中
        {
            "type": "客户转介",
            "customer_id": customer_li.id,
            "customer_name": "李女士",
            "summary": "客户申请转账至银行卡，金额15万元",
            "status": "待处理",
            "priority": "紧急",
            "days_ago": 0,
        },
        {
            "type": "客户转介",
            "customer_id": customer_zhang.id,
            "customer_name": "张先生",
            "summary": "客户申请转账至第三方账户，金额80万元",
            "status": "处理中",
            "priority": "紧急",
            "handled_by": operator_liu.id if operator_liu else None,
            "handler_name": "刘经理" if operator_liu else None,
            "days_ago": 1,
        },
        {
            "type": "客户转介",
            "customer_id": customer_li.id,
            "customer_name": "李女士",
            "summary": "客户咨询大额转账手续费优惠政策",
            "status": "处理中",
            "priority": "普通",
            "handled_by": advisor_wang.id if advisor_wang else None,
            "handler_name": "王顾问" if advisor_wang else None,
            "days_ago": 2,
        },
        # 风险预警 - 4条
        {
            "type": "风险预警",
            "customer_id": customer_zhang.id,
            "customer_name": "张先生",
            "summary": "触发RW-003高风险产品集中度预警",
            "status": "待处理",
            "priority": "紧急",
            "days_ago": 0,
        },
        {
            "type": "风险预警",
            "customer_id": customer_li.id,
            "customer_name": "李女士",
            "summary": "触发RW-001单笔大额交易预警",
            "status": "待处理",
            "priority": "普通",
            "days_ago": 1,
        },
        {
            "type": "风险预警",
            "customer_id": customer_zhang.id,
            "customer_name": "张先生",
            "summary": "触发RW-015反洗钱可疑交易预警",
            "status": "处理中",
            "priority": "紧急",
            "handled_by": operator_liu.id if operator_liu else None,
            "handler_name": "刘经理" if operator_liu else None,
            "days_ago": 2,
        },
        {
            "type": "风险预警",
            "customer_id": customer_li.id,
            "customer_name": "李女士",
            "summary": "触发RW-005风险承受能力不匹配预警",
            "status": "处理中",
            "priority": "普通",
            "handled_by": advisor_wang.id if advisor_wang else None,
            "handler_name": "王顾问" if advisor_wang else None,
            "days_ago": 3,
        },
        # 信息变更 - 2条已完成
        {
            "type": "信息变更",
            "customer_id": customer_zhang.id,
            "customer_name": "张先生",
            "summary": "客户更新联系电话和邮箱地址",
            "status": "已完成",
            "priority": "普通",
            "handled_by": operator_liu.id if operator_liu else None,
            "handler_name": "刘经理" if operator_liu else None,
            "days_ago": 5,
        },
        {
            "type": "信息变更",
            "customer_id": customer_li.id,
            "customer_name": "李女士",
            "summary": "客户更新银行卡信息",
            "status": "已完成",
            "priority": "普通",
            "handled_by": operator_liu.id if operator_liu else None,
            "handler_name": "刘经理" if operator_liu else None,
            "days_ago": 7,
        },
        # 其他 - 1条已驳回
        {
            "type": "其他",
            "customer_id": customer_zhang.id,
            "customer_name": "张先生",
            "summary": "客户投诉手续费收取过高",
            "status": "已驳回",
            "priority": "普通",
            "handled_by": advisor_wang.id if advisor_wang else None,
            "handler_name": "王顾问" if advisor_wang else None,
            "remark": "经核实，手续费收取符合合同约定",
            "days_ago": 10,
        },
    ]

    for wo in workorders_data:
        created_at = datetime.now() - timedelta(days=wo["days_ago"])
        handled_at = created_at + timedelta(hours=2) if wo.get("handled_by") else None
        completed_at = handled_at + timedelta(hours=3) if wo["status"] in ["已完成", "已驳回"] else None

        workorder = WorkOrderModel(
            order_type=wo["type"],
            customer_id=wo["customer_id"],
            customer_name=wo["customer_name"],
            intent_summary=wo["summary"],
            status=wo["status"],
            priority=wo["priority"],
            handled_by=wo.get("handled_by"),
            handler_name=wo.get("handler_name"),
            handled_at=handled_at,
            completed_at=completed_at,
            remark=wo.get("remark"),
        )

        wo_id = workorder.save()
        if wo_id > 0:
            print(f"✓ 创建工单: [{wo['type']}] {wo['summary'][:30]}... (状态={wo['status']})")
        else:
            print(f"✗ 创建工单失败")


def init_risk_alerts(users):
    """初始化风险预警（12条预警）"""
    print("\n=== 初始化风险预警 ===")

    customer_zhang = users.get("customer_zhang")
    customer_li = users.get("customer_li")
    risk_zhao = users.get("risk_zhao")
    advisor_wang = users.get("advisor_wang")

    if not all([customer_zhang, customer_li]):
        print("✗ 客户账号不存在，跳过风险预警初始化")
        return

    risk_alerts_data = [
        # 高风险（需管理员裁决）- 4条待处理
        {
            "customer_id": customer_zhang.id,
            "rule_id": "RW-003",
            "rule_name": "高风险产品集中度超标",
            "severity": "高",
            "confidence": 0.95,
            "details": {"reason": "R4/R5级产品占比达68%，超过50%阈值"},
            "need_override": True,
            "status": "待处理",
            "days_ago": 0,
        },
        {
            "customer_id": customer_zhang.id,
            "rule_id": "RW-007",
            "rule_name": "客户年龄与产品期限不匹配",
            "severity": "高",
            "confidence": 0.88,
            "details": {"reason": "客户年龄65岁，购买10年期产品"},
            "need_override": True,
            "status": "待处理",
            "days_ago": 1,
        },
        {
            "customer_id": customer_li.id,
            "rule_id": "RW-015",
            "rule_name": "反洗钱可疑交易",
            "severity": "严重",
            "confidence": 0.92,
            "details": {"reason": "7天内多次大额现金交易，累计超过20万元"},
            "need_override": True,
            "status": "待处理",
            "days_ago": 0,
        },
        {
            "customer_id": customer_zhang.id,
            "rule_id": "RW-003",
            "rule_name": "高风险产品集中度超标",
            "severity": "高",
            "confidence": 0.90,
            "details": {"reason": "私募基金占比超过40%"},
            "need_override": True,
            "status": "待处理",
            "days_ago": 2,
        },
        # 中风险 - 5条待处理/处理中
        {
            "customer_id": customer_zhang.id,
            "rule_id": "RW-001",
            "rule_name": "单笔大额交易",
            "severity": "中",
            "confidence": 0.85,
            "details": {"reason": "单笔申购金额50万元，超过20万元阈值"},
            "need_override": False,
            "status": "待处理",
            "days_ago": 1,
        },
        {
            "customer_id": customer_li.id,
            "rule_id": "RW-005",
            "rule_name": "风险承受能力不匹配",
            "severity": "中",
            "confidence": 0.80,
            "details": {"reason": "客户风险等级R2，购买R4产品"},
            "need_override": False,
            "status": "待处理",
            "days_ago": 2,
        },
        {
            "customer_id": customer_zhang.id,
            "rule_id": "RW-001",
            "rule_name": "单笔大额交易",
            "severity": "中",
            "confidence": 0.87,
            "details": {"reason": "单笔赎回金额80万元"},
            "need_override": False,
            "status": "处理中",
            "handler_id": risk_zhao.id if risk_zhao else None,
            "days_ago": 3,
        },
        {
            "customer_id": customer_li.id,
            "rule_id": "RW-005",
            "rule_name": "风险承受能力不匹配",
            "severity": "中",
            "confidence": 0.78,
            "details": {"reason": "客户未做过风险评估，购买R3产品"},
            "need_override": False,
            "status": "处理中",
            "handler_id": advisor_wang.id if advisor_wang else None,
            "days_ago": 4,
        },
        {
            "customer_id": customer_zhang.id,
            "rule_id": "RW-001",
            "rule_name": "单笔大额交易",
            "severity": "中",
            "confidence": 0.83,
            "details": {"reason": "单笔转账金额30万元"},
            "need_override": False,
            "status": "待处理",
            "days_ago": 0,
        },
        # 低风险 - 3条已确认/误报
        {
            "customer_id": customer_li.id,
            "rule_id": "RW-010",
            "rule_name": "交易频率异常",
            "severity": "低",
            "confidence": 0.65,
            "details": {"reason": "7天内交易5笔"},
            "need_override": False,
            "status": "已确认",
            "handler_id": risk_zhao.id if risk_zhao else None,
            "handle_result": "经核实，客户交易行为正常",
            "days_ago": 5,
        },
        {
            "customer_id": customer_zhang.id,
            "rule_id": "RW-010",
            "rule_name": "交易频率异常",
            "severity": "低",
            "confidence": 0.60,
            "details": {"reason": "短期内多次小额申购"},
            "need_override": False,
            "status": "误报",
            "handler_id": risk_zhao.id if risk_zhao else None,
            "handle_result": "客户正常理财操作，非异常行为",
            "days_ago": 7,
        },
        {
            "customer_id": customer_li.id,
            "rule_id": "RW-010",
            "rule_name": "交易频率异常",
            "severity": "低",
            "confidence": 0.58,
            "details": {"reason": "连续3天有交易记录"},
            "need_override": False,
            "status": "误报",
            "handler_id": advisor_wang.id if advisor_wang else None,
            "handle_result": "客户调整资产配置，属于正常操作",
            "days_ago": 10,
        },
    ]

    for alert in risk_alerts_data:
        created_at = datetime.now() - timedelta(days=alert["days_ago"])
        handled_at = created_at + timedelta(hours=1) if alert.get("handler_id") else None

        risk_alert = RiskAlertModel(
            customer_id=alert["customer_id"],
            rule_id=alert["rule_id"],
            rule_name=alert["rule_name"],
            severity=alert["severity"],
            confidence=Decimal(str(alert["confidence"])),
            trigger_details=alert["details"],
            related_transaction_id=None,  # 简化处理，实际应关联具体交易
            status=alert["status"],
            need_override=alert["need_override"],
            handler_id=alert.get("handler_id"),
            handle_result=alert.get("handle_result"),
            handled_at=handled_at,
        )

        alert_id = risk_alert.save()
        if alert_id > 0:
            print(f"✓ 创建风险预警: [{alert['rule_id']}] {alert['rule_name']} (严重度={alert['severity']}, 状态={alert['status']})")
        else:
            print(f"✗ 创建风险预警失败")


def main():
    """主函数"""
    print("=" * 60)
    print("财富管家Mock数据初始化")
    print("=" * 60)

    try:
        # 1. 初始化角色
        init_roles()

        # 2. 初始化用户
        users = init_users()

        # 3. 初始化产品
        products = init_products()

        # 4. 初始化持仓和交易记录
        init_holdings_and_transactions(users, products)

        # 5. 初始化工单
        init_work_orders(users)

        # 6. 初始化风险预警
        init_risk_alerts(users)

        print("\n" + "=" * 60)
        print("✓ 数据初始化完成")
        print("=" * 60)
        print("\n测试账号（密码均为123456）：")
        print("  客户账号: customer_zhang, customer_li")
        print("  员工账号: advisor_wang, risk_zhao, operator_liu, admin")
        print("\n可以使用这些账号登录前端系统进行测试")

    except Exception as e:
        print(f"\n✗ 初始化过程出现错误: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
