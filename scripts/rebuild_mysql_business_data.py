#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MySQL业务数据重建脚本 - 模拟真实金融理财全生命周期

清理旧数据并生成180客户+30员工的完整业务数据：
- 每个客户有完整的开户→风评→咨询→申购→持仓→交易→风控→工单全流程
- 每个客户分配对应的员工负责人（理财顾问、客户经理等）
- 真实化名、完整时间线、合理的业务关联

使用namespace: WB-SEED-20260817
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal
import json
import random
import argparse

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from app.Base.Client.mysqlClient import MySQLClient
import hashlib

NAMESPACE = "WB-SEED-20260817"
APPLY_CONFIRMATION = "REBUILD_MYSQL_BUSINESS_DATA"

# 客户风险等级分布
RISK_DISTRIBUTION = {
    "C1": 36,  # 保守型
    "C2": 42,  # 稳健型
    "C3": 48,  # 平衡型
    "C4": 36,  # 进取型
    "C5": 18,  # 激进型
}

# 客户等级
CUSTOMER_LEVELS = {
    "C1": "普通",
    "C2": "金卡",
    "C3": "白金",
    "C4": "钻石",
    "C5": "私行"
}

# 风险评分范围
RISK_SCORES = {
    "C1": (20, 35),
    "C2": (36, 50),
    "C3": (51, 65),
    "C4": (66, 80),
    "C5": (81, 100)
}

# 资产规模范围
ASSET_RANGES = {
    "C1": (500000, 1500000),
    "C2": (1500000, 3000000),
    "C3": (3000000, 8000000),
    "C4": (8000000, 50000000),
    "C5": (50000000, 500000000)
}

# 姓氏和名字库
SURNAMES = ["赵", "钱", "孙", "李", "周", "吴", "郑", "王", "冯", "陈", "褚", "卫",
            "蒋", "沈", "韩", "杨", "朱", "秦", "许", "何", "吕", "施", "张", "孔"]

GIVEN_NAMES = ["安宁", "嘉诚", "思远", "雨桐", "明轩", "欣怡", "俊杰", "文静", "志强", "晓雯",
               "建国", "秀兰", "伟", "芳", "静", "丽", "强", "军", "涛", "敏",
               "浩然", "子涵", "梓轩", "雨萱", "诗涵", "宇轩", "佳怡", "若曦", "思琪", "雨欣"]

OCCUPATIONS = ["企业高管", "公务员", "医生", "教师", "工程师", "律师", "会计师",
               "企业主", "自由职业者", "退休人员", "IT从业者", "金融从业者"]

# 员工角色配置
EMPLOYEE_ROLES = {
    "advisor": {"count": 10, "name": "理财顾问", "level_range": ["初级", "中级", "高级"]},
    "risk_officer": {"count": 5, "name": "风控专员", "level_range": ["中级", "高级"]},
    "operator": {"count": 8, "name": "客户经理", "level_range": ["初级", "中级", "高级"]},
    "customer_service": {"count": 5, "name": "客服专员", "level_range": ["初级", "中级"]},
    "admin": {"count": 2, "name": "管理员", "level_range": ["高级"]}
}


class DataGenerator:
    def __init__(self):
        self.client = MySQLClient()
        self.customers = []
        self.employees = []
        self.products = []

    def generate_password_hash(self, password="123456"):
        """生成密码hash"""
        return hashlib.sha256(password.encode()).hexdigest()

    def clean_old_data(self):
        """清理旧客户数据（不删除产品和知识库）"""
        print("\n" + "="*80)
        print("第1步：清理旧客户数据")
        print("="*80)

        # 查询旧客户ID
        old_customers = self.client.execute_sync("""
            SELECT id FROM base_user
            WHERE user_type='CUSTOMER'
            AND (username LIKE 'wb_seed_%%' OR username LIKE 'customer_%%')
        """, ())

        customer_ids = tuple([c['id'] for c in old_customers]) if old_customers else ()

        print(f"[INFO] 找到 {len(customer_ids)} 个旧客户账号")

        if not customer_ids:
            print("[INFO] 没有需要清理的旧数据")
            return

        # 清理关联表（按外键依赖顺序）
        tables_to_clean = [
            ("biz_work_order", "customer_id"),
            ("fin_risk_alert", "customer_id"),
            ("fin_transaction", "customer_id"),
            ("fin_holdings", "customer_id"),
            ("fin_risk_assessment", "customer_id"),
            ("fin_customer_profile", "customer_id"),
            ("conversation_archive", "customer_id"),
            ("base_llm_conversation", "user_id"),
            ("base_llm_session", "user_id"),
            ("base_user_role", "user_id"),
        ]

        for table, column in tables_to_clean:
            try:
                if len(customer_ids) == 1:
                    result = self.client.execute_sync(
                        f"DELETE FROM {table} WHERE {column} = %s",
                        (customer_ids[0],)
                    )
                else:
                    placeholders = ','.join(['%s'] * len(customer_ids))
                    result = self.client.execute_sync(
                        f"DELETE FROM {table} WHERE {column} IN ({placeholders})",
                        customer_ids
                    )
                print(f"[SUCCESS] {table}: 删除 {result} 条记录")
            except Exception as e:
                print(f"[WARNING] {table}: {str(e)}")

        # 删除客户账号
        try:
            if len(customer_ids) == 1:
                result = self.client.execute_sync(
                    "DELETE FROM base_user WHERE id = %s",
                    (customer_ids[0],)
                )
            else:
                placeholders = ','.join(['%s'] * len(customer_ids))
                result = self.client.execute_sync(
                    f"DELETE FROM base_user WHERE id IN ({placeholders})",
                    customer_ids
                )
            print(f"[SUCCESS] base_user: 删除 {result} 个客户账号")
        except Exception as e:
            print(f"[ERROR] base_user: {str(e)}")

        # 清理旧员工账号（wb_seed_employee_*）
        old_employees = self.client.execute_sync("""
            SELECT id FROM base_user
            WHERE user_type='EMPLOYEE'
            AND username LIKE 'wb_seed_employee_%%'
        """, ())

        if old_employees:
            employee_ids = tuple([e['id'] for e in old_employees])
            print(f"[INFO] 找到 {len(employee_ids)} 个旧员工账号")

            try:
                self.client.execute_sync(
                    "DELETE FROM base_user_role WHERE user_id IN ({})".format(
                        ','.join(['%s'] * len(employee_ids))
                    ),
                    employee_ids
                )

                self.client.execute_sync(
                    "DELETE FROM base_user WHERE id IN ({})".format(
                        ','.join(['%s'] * len(employee_ids))
                    ),
                    employee_ids
                )
                print(f"[SUCCESS] 删除 {len(employee_ids)} 个旧员工账号")
            except Exception as e:
                print(f"[ERROR] 清理旧员工失败: {str(e)}")

    def generate_employees(self):
        """生成30个员工账号"""
        print("\n" + "="*80)
        print("第2步：生成员工账号（30人）")
        print("="*80)

        employee_seq = 1
        password_hash = self.generate_password_hash("123456")

        for role_key, role_config in EMPLOYEE_ROLES.items():
            count = role_config["count"]
            role_name = role_config["name"]
            levels = role_config["level_range"]

            for i in range(count):
                username = f"wb_seed_employee_{employee_seq:03d}"
                name = f"{SURNAMES[employee_seq % len(SURNAMES)]}{GIVEN_NAMES[(employee_seq * 3) % len(GIVEN_NAMES)]}"
                level = levels[i % len(levels)]

                try:
                    # 插入用户表
                    self.client.execute_sync("""
                        INSERT INTO base_user
                        (username, password_hash, user_type, source_module, extra_data,
                         employee_role, advisor_level, customer_level, status, email)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        username,
                        password_hash,
                        "EMPLOYEE",
                        "fin",
                        json.dumps({
                            "seed_namespace": NAMESPACE,
                            "display_name": name,
                            "employee_id": f"E{employee_seq:04d}"
                        }, ensure_ascii=False),
                        role_name,
                        level if role_key == "advisor" else None,
                        "普通",
                        "active",
                        f"{username}@seed.invalid"
                    ))

                    # 获取插入的ID
                    result = self.client.execute_sync("SELECT LAST_INSERT_ID() as id", ())
                    user_id = result[0]['id']

                    # 分配角色
                    role_id = self._get_role_id(role_key)
                    if role_id:
                        self.client.execute_sync("""
                            INSERT INTO base_user_role (user_id, role_id, created_at, updated_at)
                            VALUES (%s, %s, NOW(), NOW())
                        """, (user_id, role_id))

                    self.employees.append({
                        'id': user_id,
                        'username': username,
                        'name': name,
                        'role': role_key,
                        'role_name': role_name,
                        'level': level
                    })

                    if employee_seq % 5 == 0:
                        print(f"[PROGRESS] 已生成 {employee_seq}/{sum(r['count'] for r in EMPLOYEE_ROLES.values())} 个员工")

                    employee_seq += 1
                except Exception as e:
                    print(f"[ERROR] 生成员工 {username} 失败: {str(e)}")

        print(f"[SUCCESS] 员工账号生成完成: {len(self.employees)} 人")

    def _get_role_id(self, role_key):
        """获取角色ID"""
        role_mapping = {
            "advisor": "advisor",
            "risk_officer": "risk_officer",
            "operator": "operator",
            "customer_service": "customer_service",
            "admin": "admin"
        }

        role_name = role_mapping.get(role_key)
        if not role_name:
            return None

        try:
            result = self.client.execute_sync(
                "SELECT id FROM base_role WHERE name = %s AND source_module = 'fin' LIMIT 1",
                (role_name,)
            )
            return result[0]['id'] if result else None
        except:
            return None

    def generate_customers(self):
        """生成180个客户账号"""
        print("\n" + "="*80)
        print("第3步：生成客户账号（180人）")
        print("="*80)

        customer_seq = 1
        password_hash = self.generate_password_hash("123456")

        # 获取理财顾问列表（用于分配客户）
        advisors = [e for e in self.employees if e['role'] == 'advisor']

        for risk_level, count in RISK_DISTRIBUTION.items():
            for i in range(count):
                username = f"wb_seed_customer_{customer_seq:03d}"
                name = f"{SURNAMES[(customer_seq * 7) % len(SURNAMES)]}{GIVEN_NAMES[(customer_seq * 11) % len(GIVEN_NAMES)]}"

                # 生成年龄（25-70岁）
                age = 25 + (customer_seq * 13) % 46
                birth_year = 2024 - age
                birthday = f"{birth_year:04d}-{((customer_seq % 12) + 1):02d}-{((customer_seq % 28) + 1):02d}"

                # 资产规模
                asset_min, asset_max = ASSET_RANGES[risk_level]
                assets = Decimal(str(random.randint(asset_min, asset_max)))

                # 风险评分
                score_min, score_max = RISK_SCORES[risk_level]
                risk_score = Decimal(str(random.randint(score_min, score_max)))

                # 客户等级
                customer_level = CUSTOMER_LEVELS[risk_level]

                # 分配理财顾问
                advisor = advisors[customer_seq % len(advisors)]

                # 职业
                occupation = OCCUPATIONS[customer_seq % len(OCCUPATIONS)]

                # 是否专业投资者
                is_professional = 1 if risk_level == "C5" and i % 3 == 0 else 0

                try:
                    # 插入用户表
                    self.client.execute_sync("""
                        INSERT INTO base_user
                        (username, password_hash, user_type, source_module, extra_data, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                    """, (
                        username,
                        password_hash,
                        "CUSTOMER",
                        "WealthButler",
                        json.dumps({
                            "namespace": NAMESPACE,
                            "display_name": name,
                            "customer_id": f"C{customer_seq:06d}",
                            "birthday": birthday,
                            "occupation": occupation,
                            "advisor_id": advisor['id'],
                            "advisor_name": advisor['name']
                        }, ensure_ascii=False)
                    ))

                    # 获取插入的ID
                    result = self.client.execute_sync("SELECT LAST_INSERT_ID() as id", ())
                    user_id = result[0]['id']

                    # 分配客户角色
                    customer_role_id = self._get_role_id("customer")
                    if customer_role_id:
                        self.client.execute_sync("""
                            INSERT INTO base_user_role (user_id, role_id, created_at, updated_at)
                            VALUES (%s, %s, NOW(), NOW())
                        """, (user_id, customer_role_id))

                    self.customers.append({
                        'id': user_id,
                        'username': username,
                        'name': name,
                        'birthday': birthday,
                        'customer_level': customer_level,
                        'risk_level': risk_level,
                        'risk_score': risk_score,
                        'assets': assets,
                        'occupation': occupation,
                        'is_professional': is_professional,
                        'advisor_id': advisor['id'],
                        'advisor_name': advisor['name']
                    })

                    if customer_seq % 20 == 0:
                        print(f"[PROGRESS] 已生成 {customer_seq}/180 个客户")

                    customer_seq += 1
                except Exception as e:
                    print(f"[ERROR] 生成客户 {username} 失败: {str(e)}")

        print(f"[SUCCESS] 客户账号生成完成: {len(self.customers)} 人")

    def generate_customer_profiles(self):
        """生成客户画像"""
        print("\n" + "="*80)
        print("第4步：生成客户画像")
        print("="*80)

        for idx, customer in enumerate(self.customers, 1):
            # 四维度评分（总分100）
            risk_level = customer['risk_level']

            if risk_level == "C1":
                dims = (Decimal("15"), Decimal("8"), Decimal("5"), Decimal("2"))
            elif risk_level == "C2":
                dims = (Decimal("18"), Decimal("12"), Decimal("11"), Decimal("5"))
            elif risk_level == "C3":
                dims = (Decimal("21"), Decimal("17"), Decimal("17"), Decimal("7"))
            elif risk_level == "C4":
                dims = (Decimal("24"), Decimal("22"), Decimal("24"), Decimal("8"))
            else:  # C5
                dims = (Decimal("25"), Decimal("25"), Decimal("30"), Decimal("15"))

            try:
                self.client.execute_sync("""
                    INSERT INTO fin_customer_profile
                    (customer_id, advisor_id, risk_level, risk_score,
                     dimension1_score, dimension2_score, dimension3_score, dimension4_score,
                     fm_flags, asset_allocation, product_preference, memory_units,
                     confidence_score, updated_reason, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                """, (
                    customer['id'],
                    customer['advisor_id'],
                    customer['risk_level'],
                    customer['risk_score'],
                    dims[0],  # dimension1: 财务状况
                    dims[1],  # dimension2: 投资经验
                    dims[2],  # dimension3: 风险偏好
                    dims[3],  # dimension4: 投资目标
                    json.dumps([]),  # fm_flags
                    json.dumps({"total_assets": str(customer['assets']), "currency": "CNY"}),  # asset_allocation
                    json.dumps({"seed_namespace": NAMESPACE, "risk": customer['risk_level']}),  # product_preference
                    json.dumps([{
                        "unit_id": f"{NAMESPACE}:{customer['username']}",
                        "tag": "种子客户",
                        "content": f"{customer['name']}的财富画像",
                        "status": "active"
                    }]),  # memory_units
                    "0.950",  # confidence_score
                    "人工触发"  # updated_reason
                ))

                if idx % 30 == 0:
                    print(f"[PROGRESS] 已生成 {idx}/180 个客户画像")
            except Exception as e:
                print(f"[ERROR] 生成客户 {customer['name']} 画像失败: {str(e)}")

        print(f"[SUCCESS] 客户画像生成完成")

    def generate_risk_assessments(self):
        """生成风险评估记录"""
        print("\n" + "="*80)
        print("第5步：生成风险评估记录")
        print("="*80)

        # 16题问卷模板
        questionnaire_template = [
            {"question": "您的年龄", "answer": "", "score": 0},
            {"question": "您的家庭年收入", "answer": "", "score": 0},
            {"question": "您计划用于投资的资金占可支配资产的比例", "answer": "", "score": 0},
            {"question": "您投资理财产品的主要目的", "answer": "", "score": 0},
            {"question": "您的投资经验", "answer": "", "score": 0},
            {"question": "您是否了解各类理财产品的风险", "answer": "", "score": 0},
            {"question": "以下哪种描述最符合您的投资态度", "answer": "", "score": 0},
            {"question": "如果您的投资出现亏损，您会", "answer": "", "score": 0},
            {"question": "如果市场出现波动，您会", "answer": "", "score": 0},
            {"question": "您能承受的最大投资损失比例", "answer": "", "score": 0},
            {"question": "您的投资期限偏好", "answer": "", "score": 0},
            {"question": "您是否有稳定的收入来源", "answer": "", "score": 0},
            {"question": "您的家庭负担情况", "answer": "", "score": 0},
            {"question": "您是否持有其他投资产品", "answer": "", "score": 0},
            {"question": "您希望的投资收益率", "answer": "", "score": 0},
            {"question": "您对投资风险的理解", "answer": "", "score": 0}
        ]

        for idx, customer in enumerate(self.customers, 1):
            questionnaire = questionnaire_template.copy()
            total_score = int(customer['risk_score'])

            try:
                self.client.execute_sync("""
                    INSERT INTO fin_risk_assessment
                    (customer_id, questionnaire_data, total_score, risk_level,
                     assessment_date, assessor_id, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, NOW(), %s, NOW(), NOW())
                """, (
                    customer['id'],
                    json.dumps(questionnaire, ensure_ascii=False),
                    total_score,
                    customer['risk_level'],
                    customer['advisor_id']
                ))

                if idx % 30 == 0:
                    print(f"[PROGRESS] 已生成 {idx}/180 个风险评估")
            except Exception as e:
                print(f"[ERROR] 生成客户 {customer['name']} 风险评估失败: {str(e)}")

        print(f"[SUCCESS] 风险评估生成完成")

    def load_products(self):
        """加载产品列表"""
        products = self.client.execute_sync("""
            SELECT id, product_name, product_type, risk_level,
                   expected_return_min, expected_return_max
            FROM fin_product
            WHERE status = '在售'
            LIMIT 100
        """, ())

        self.products = products if products else []
        print(f"[INFO] 加载了 {len(self.products)} 个产品")

    def generate_holdings_and_transactions(self):
        """生成持仓和交易记录"""
        print("\n" + "="*80)
        print("第6步：生成持仓和交易记录")
        print("="*80)

        if not self.products:
            print("[WARNING] 没有可用产品，跳过持仓和交易生成")
            return

        for idx, customer in enumerate(self.customers, 1):
            # 每个客户持有2-5个产品
            num_holdings = random.randint(2, 5)
            customer_products = random.sample(self.products, min(num_holdings, len(self.products)))

            for product in customer_products:
                # 申购金额（根据资产规模）
                purchase_amount = Decimal(str(random.randint(10000, int(customer['assets'] * Decimal("0.3")))))
                quantity = purchase_amount  # 简化：份额=金额

                # 当前净值（1.0-1.5之间）
                current_nav = Decimal(str(round(random.uniform(1.0, 1.5), 4)))
                current_value = quantity * current_nav

                # 收益
                profit = current_value - purchase_amount
                profit_rate = (profit / purchase_amount * 100) if purchase_amount > 0 else Decimal("0")

                # 持仓日期（30-365天前）
                days_ago = random.randint(30, 365)
                purchase_date = datetime.now() - timedelta(days=days_ago)

                try:
                    # 生成持仓记录
                    self.client.execute_sync("""
                        INSERT INTO fin_holdings
                        (customer_id, product_id, product_name, quantity,
                         purchase_amount, current_nav, current_value,
                         profit, profit_rate, purchase_date, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    """, (
                        customer['id'],
                        product['id'],
                        product['product_name'],
                        quantity,
                        purchase_amount,
                        current_nav,
                        current_value,
                        profit,
                        profit_rate,
                        purchase_date
                    ))

                    # 生成对应的申购交易记录
                    self.client.execute_sync("""
                        INSERT INTO fin_transaction
                        (customer_id, product_id, transaction_type, amount,
                         quantity, nav, transaction_date, status,
                         operator_id, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    """, (
                        customer['id'],
                        product['id'],
                        "申购",
                        purchase_amount,
                        quantity,
                        Decimal("1.0000"),
                        purchase_date,
                        "成功",
                        customer['advisor_id']
                    ))

                    # 随机生成1-3笔加仓或赎回交易
                    num_additional_txns = random.randint(0, 3)
                    for _ in range(num_additional_txns):
                        txn_type = random.choice(["申购", "赎回"])
                        txn_days_ago = random.randint(1, days_ago - 1)
                        txn_date = datetime.now() - timedelta(days=txn_days_ago)
                        txn_amount = Decimal(str(random.randint(5000, int(purchase_amount * Decimal("0.5")))))

                        self.client.execute_sync("""
                            INSERT INTO fin_transaction
                            (customer_id, product_id, transaction_type, amount,
                             quantity, nav, transaction_date, status,
                             operator_id, created_at, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                        """, (
                            customer['id'],
                            product['id'],
                            txn_type,
                            txn_amount,
                            txn_amount,
                            Decimal(str(round(random.uniform(0.95, 1.2), 4))),
                            txn_date,
                            "成功",
                            customer['advisor_id']
                        ))

                except Exception as e:
                    print(f"[ERROR] 生成客户 {customer['name']} 持仓失败: {str(e)}")

            if idx % 30 == 0:
                print(f"[PROGRESS] 已生成 {idx}/180 个客户的持仓和交易")

        print(f"[SUCCESS] 持仓和交易记录生成完成")

    def generate_work_orders(self):
        """生成工单记录"""
        print("\n" + "="*80)
        print("第7步：生成工单记录")
        print("="*80)

        order_types = ["客户转介", "投诉处理", "产品咨询", "业务办理", "风险预警", "账户问题", "其他"]
        priorities = ["高", "中", "低"]
        statuses = ["待处理", "处理中", "已完成", "已关闭"]

        # 每个客户生成0-3个工单
        for idx, customer in enumerate(self.customers, 1):
            num_orders = random.randint(0, 3)

            for _ in range(num_orders):
                order_type = random.choice(order_types)
                priority = random.choice(priorities)
                status = random.choice(statuses)

                days_ago = random.randint(1, 180)
                created_date = datetime.now() - timedelta(days=days_ago)

                # 分配处理人
                if order_type == "风险预警":
                    handler = random.choice([e for e in self.employees if e['role'] == 'risk_officer'])
                elif order_type in ["客户转介", "产品咨询"]:
                    handler = next((e for e in self.employees if e['id'] == customer['advisor_id']), None)
                else:
                    handler = random.choice([e for e in self.employees if e['role'] in ['operator', 'customer_service']])

                if not handler:
                    continue

                description = f"客户{customer['name']}的{order_type}工单"

                try:
                    self.client.execute_sync("""
                        INSERT INTO biz_work_order
                        (order_type, customer_id, customer_name, description,
                         priority, status, handler_id, handler_name,
                         created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """, (
                        order_type,
                        customer['id'],
                        customer['name'],
                        description,
                        priority,
                        status,
                        handler['id'],
                        handler['name'],
                        created_date
                    ))
                except Exception as e:
                    print(f"[ERROR] 生成工单失败: {str(e)}")

            if idx % 30 == 0:
                print(f"[PROGRESS] 已处理 {idx}/180 个客户的工单")

        print(f"[SUCCESS] 工单记录生成完成")

    def generate_risk_alerts(self):
        """生成风险预警记录"""
        print("\n" + "="*80)
        print("第8步：生成风险预警记录")
        print("="*80)

        alert_types = ["大额交易", "频繁交易", "集中度风险", "适当性违规", "可疑交易"]
        severities = ["低", "中", "高", "极高"]
        statuses = ["待处理", "已处理", "已忽略"]

        # 随机为20%的客户生成1-2条风险预警
        sample_size = int(len(self.customers) * 0.2)
        risky_customers = random.sample(self.customers, sample_size)

        for idx, customer in enumerate(risky_customers, 1):
            num_alerts = random.randint(1, 2)

            for _ in range(num_alerts):
                alert_type = random.choice(alert_types)
                severity = random.choice(severities)
                status = random.choice(statuses)

                days_ago = random.randint(1, 90)
                triggered_date = datetime.now() - timedelta(days=days_ago)

                # 触发原因
                if alert_type == "大额交易":
                    reason = f"单笔交易金额{random.randint(50, 500)}万元，超过阈值"
                elif alert_type == "频繁交易":
                    reason = f"近7日交易{random.randint(10, 30)}笔，超过正常频率"
                elif alert_type == "集中度风险":
                    reason = f"单一产品持仓占比{random.randint(60, 90)}%，超过警戒线"
                elif alert_type == "适当性违规":
                    reason = f"客户风险等级{customer['risk_level']}持有R{random.randint(4, 5)}产品"
                else:
                    reason = "交易模式异常，疑似洗钱风险"

                # 关联规则
                rule_id = f"RW-{random.randint(1, 20):03d}"

                try:
                    self.client.execute_sync("""
                        INSERT INTO fin_risk_alert
                        (alert_type, customer_id, customer_name, severity,
                         trigger_reason, rule_id, status, triggered_at, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    """, (
                        alert_type,
                        customer['id'],
                        customer['name'],
                        severity,
                        reason,
                        rule_id,
                        status,
                        triggered_date
                    ))
                except Exception as e:
                    print(f"[ERROR] 生成风险预警失败: {str(e)}")

            if idx % 10 == 0:
                print(f"[PROGRESS] 已处理 {idx}/{sample_size} 个风险客户")

        print(f"[SUCCESS] 风险预警记录生成完成")

    def verify_data(self):
        """验证生成的数据"""
        print("\n" + "="*80)
        print("第9步：验证生成的数据")
        print("="*80)

        tables = [
            ("base_user", "WHERE user_type='CUSTOMER' AND username LIKE 'wb_seed_%%'"),
            ("base_user", "WHERE user_type='EMPLOYEE' AND username LIKE 'wb_seed_%%'"),
            ("fin_customer_profile", ""),
            ("fin_risk_assessment", ""),
            ("fin_holdings", ""),
            ("fin_transaction", ""),
            ("biz_work_order", "WHERE customer_name IS NOT NULL"),
            ("fin_risk_alert", "")
        ]

        for table, condition in tables:
            try:
                sql = f"SELECT COUNT(*) as cnt FROM {table} {condition}"
                result = self.client.execute_sync(sql, ())
                count = result[0]['cnt'] if result else 0

                if table == "base_user" and "CUSTOMER" in condition:
                    print(f"[INFO] 客户账号: {count} 个")
                elif table == "base_user" and "EMPLOYEE" in condition:
                    print(f"[INFO] 员工账号: {count} 个")
                else:
                    print(f"[INFO] {table}: {count} 条记录")
            except Exception as e:
                print(f"[ERROR] {table}: {str(e)}")


def main():
    parser = argparse.ArgumentParser(description='MySQL业务数据重建脚本')
    parser.add_argument('--dry-run', action='store_true', help='预览模式')
    parser.add_argument('--clean-only', action='store_true', help='只清理不生成')
    parser.add_argument('--confirm', type=str, help=f'确认执行：{APPLY_CONFIRMATION}')

    args = parser.parse_args()

    if args.dry_run:
        print("[DRY-RUN] 预览模式")
        print("实际执行命令: python scripts/rebuild_mysql_business_data.py --confirm REBUILD_MYSQL_BUSINESS_DATA")
        return

    if not args.clean_only and args.confirm != APPLY_CONFIRMATION:
        print(f"[ERROR] 需要确认短语: --confirm {APPLY_CONFIRMATION}")
        return

    generator = DataGenerator()

    try:
        # 清理旧数据
        generator.clean_old_data()

        if args.clean_only:
            print("\n[INFO] 清理完成，跳过数据生成")
            return

        # 生成新数据
        generator.generate_employees()
        generator.generate_customers()
        generator.generate_customer_profiles()
        generator.generate_risk_assessments()
        generator.load_products()
        generator.generate_holdings_and_transactions()
        generator.generate_work_orders()
        generator.generate_risk_alerts()
        generator.verify_data()

        print("\n" + "="*80)
        print("✅ MySQL业务数据重建完成")
        print("="*80)
        print(f"- 员工: 30人")
        print(f"- 客户: 180人（C1:36, C2:42, C3:48, C4:36, C5:18）")
        print(f"- 每个客户都有：画像、风评、持仓、交易记录")
        print(f"- 每个客户都分配了对应的理财顾问")
        print(f"- 工单和风险预警按真实场景分布")

    except Exception as e:
        print(f"\n[FATAL ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
