"""
智能财富管家 - 真实业务数据生成脚本

按照《财富管家模拟真实数据要求》文档生成：
- 30个员工（理财顾问、客户经理、风控专员、业务管理员等）
- 180个客户（C1-C5风险分布，完整生命周期）
- 客户画像、风险评估、持仓、交易、工单、预警等全链路数据
"""

import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import List, Dict, Any

# 添加项目根目录到路径
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.Base.Client.mysqlClient import MySQLClient
from app.Base.Service.authService import AuthService

# 命名空间
NAMESPACE = "WB-SEED-20260817"

# 中文姓氏和名字库
SURNAMES = ["王", "李", "张", "刘", "陈", "杨", "黄", "赵", "吴", "周", "徐", "孙", "马", "朱", "胡", "郭", "何", "林", "高", "罗"]
GIVEN_NAMES = ["伟", "芳", "娜", "敏", "静", "丽", "强", "磊", "军", "洋", "勇", "艳", "杰", "娟", "涛", "明", "超", "秀英", "建华", "志强"]

# 职业列表
OCCUPATIONS = ["企业高管", "公务员", "教师", "医生", "工程师", "律师", "会计师", "自由职业者", "退休人员", "私营企业主"]

# 城市列表
CITIES = ["北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京", "天津", "重庆"]

# 员工角色配置
EMPLOYEE_ROLES = {
    "advisor": {
        "name": "理财顾问",
        "count": 10,
        "role_name": "advisor",
        "levels": ["初级", "中级", "高级"]
    },
    "risk_officer": {
        "name": "风控专员",
        "count": 5,
        "role_name": "risk_officer",
        "levels": [None]
    },
    "operator": {
        "name": "客户经理",
        "count": 8,
        "role_name": "operator",
        "levels": [None]
    },
    "customer_service": {
        "name": "客服人员",
        "count": 5,
        "role_name": "customer_service",
        "levels": [None]
    },
    "business_admin": {
        "name": "业务管理员",
        "count": 2,
        "role_name": "business_admin",
        "levels": [None]
    }
}

# 风险等级分布（180人）
RISK_DISTRIBUTION = {
    "C1": 36,   # 20%
    "C2": 42,   # 23%
    "C3": 48,   # 27%
    "C4": 36,   # 20%
    "C5": 18    # 10%
}

# 风险等级对应的资产范围
ASSET_RANGES = {
    "C1": (500_000, 1_500_000),
    "C2": (1_500_000, 3_500_000),
    "C3": (3_500_000, 8_000_000),
    "C4": (8_000_000, 30_000_000),
    "C5": (30_000_000, 500_000_000)
}

# 客户等级映射
CUSTOMER_LEVELS = {
    "C1": "普通",
    "C2": "金卡",
    "C3": "白金",
    "C4": "钻石",
    "C5": "私行"
}


class BusinessDataGenerator:
    """真实业务数据生成器"""

    def __init__(self):
        self.client = MySQLClient()
        self.employees = []
        self.customers = []
        self.products = []
        self.base_date = datetime.now()

    def generate_all(self):
        """生成所有数据"""
        print("="*80)
        print("智能财富管家 - 真实业务数据生成")
        print("="*80)
        print(f"命名空间: {NAMESPACE}")
        print(f"基准日期: {self.base_date.strftime('%Y-%m-%d')}")
        print()

        try:
            # 1. 加载产品数据
            self.load_products()

            # 2. 生成员工
            self.generate_employees()

            # 3. 生成客户
            self.generate_customers()

            # 4. 生成客户画像
            self.generate_customer_profiles()

            # 5. 生成风险评估
            self.generate_risk_assessments()

            # 6. 生成持仓和交易
            self.generate_holdings_and_transactions()

            # 7. 生成工单
            self.generate_work_orders()

            # 8. 生成风险预警
            self.generate_risk_alerts()

            # 9. 生成会话归档
            self.generate_conversations()

            print()
            print("="*80)
            print("数据生成完成！")
            print("="*80)
            self.print_summary()

        except Exception as e:
            print(f"\n[FATAL ERROR] {str(e)}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    def load_products(self):
        """加载产品数据"""
        print("="*80)
        print("第1步：加载产品数据")
        print("="*80)

        result = self.client.execute_sync("""
            SELECT id, product_code, product_name, risk_level, status, nav
            FROM fin_product
            WHERE status = '在售'
            ORDER BY risk_level, id
        """, ())

        self.products = result
        print(f"[SUCCESS] 加载 {len(self.products)} 个在售产品")

        # 按风险等级分组
        self.products_by_risk = {}
        for product in self.products:
            risk = product['risk_level']
            if risk not in self.products_by_risk:
                self.products_by_risk[risk] = []
            self.products_by_risk[risk].append(product)

        for risk, prods in self.products_by_risk.items():
            print(f"  {risk}: {len(prods)} 个产品")

    def generate_employees(self):
        """生成员工账号"""
        print("\n" + "="*80)
        print("第2步：生成员工账号（30人）")
        print("="*80)

        password_hash = AuthService.hash_password("123456")
        seq = 1

        for role_key, config in EMPLOYEE_ROLES.items():
            count = config["count"]
            role_name_cn = config["name"]
            role_name_en = config["role_name"]
            levels = config["levels"]

            for i in range(count):
                username = f"wb_seed_{role_name_en}_{seq:02d}"
                name = self.generate_chinese_name()
                level = levels[i % len(levels)] if levels[0] is not None else None

                try:
                    # 插入base_user
                    self.client.execute_sync("""
                        INSERT INTO base_user
                        (username, email, password_hash, user_type, source_module, status,
                         extra_data, employee_role, advisor_level, customer_level)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        username,
                        f"{username}@jinpengtech.com",
                        password_hash,
                        "EMPLOYEE",
                        "fin",
                        "active",
                        json.dumps({
                            "seed_namespace": NAMESPACE,
                            "display_name": name,
                            "employee_id": f"E{seq:04d}"
                        }, ensure_ascii=False),
                        role_name_cn,
                        level,
                        "普通"
                    ))

                    # 获取ID
                    result = self.client.execute_sync("SELECT LAST_INSERT_ID() as id", ())
                    user_id = result[0]['id']

                    # 分配角色
                    role_result = self.client.execute_sync("""
                        SELECT id FROM base_role
                        WHERE name = %s AND source_module = 'fin'
                        LIMIT 1
                    """, (role_name_en,))

                    if role_result:
                        self.client.execute_sync("""
                            INSERT INTO base_user_role (user_id, role_id, source_module)
                            VALUES (%s, %s, %s)
                        """, (user_id, role_result[0]['id'], 'fin'))

                    self.employees.append({
                        'id': user_id,
                        'username': username,
                        'name': name,
                        'role': role_key,
                        'role_name_cn': role_name_cn,
                        'level': level
                    })

                    seq += 1

                except Exception as e:
                    print(f"[ERROR] 生成员工 {username} 失败: {str(e)}")
                    continue

        print(f"[SUCCESS] 员工账号生成完成: {len(self.employees)} 人")

        # 统计各角色人数
        role_counts = {}
        for emp in self.employees:
            role = emp['role_name_cn']
            role_counts[role] = role_counts.get(role, 0) + 1

        for role, count in role_counts.items():
            print(f"  {role}: {count} 人")

    def generate_customers(self):
        """生成客户账号"""
        print("\n" + "="*80)
        print("第3步：生成客户账号（180人）")
        print("="*80)

        password_hash = AuthService.hash_password("123456")
        seq = 1

        # 获取理财顾问和客户经理列表
        advisors = [e for e in self.employees if e['role'] == 'advisor']
        managers = [e for e in self.employees if e['role'] == 'operator']

        if not advisors or not managers:
            raise Exception("必须先生成理财顾问和客户经理")

        for risk_level, count in RISK_DISTRIBUTION.items():
            asset_min, asset_max = ASSET_RANGES[risk_level]
            customer_level = CUSTOMER_LEVELS[risk_level]

            for i in range(count):
                username = f"wb_seed_customer_{seq:03d}"
                name = self.generate_chinese_name()

                # 生成出生日期（25-70岁）
                age = random.randint(25, 70)
                birthdate = (self.base_date - timedelta(days=age*365)).strftime('%Y-%m-%d')

                # 资产
                assets = Decimal(str(random.randint(asset_min, asset_max)))

                # 分配顾问和经理
                advisor = advisors[seq % len(advisors)]
                manager = managers[seq % len(managers)]

                # 职业
                occupation = random.choice(OCCUPATIONS)

                # 城市
                city = random.choice(CITIES)

                # 是否专业投资者（C5中30%是专业投资者）
                is_professional = 1 if (risk_level == 'C5' and i % 3 == 0) else 0

                try:
                    self.client.execute_sync("""
                        INSERT INTO base_user
                        (username, email, password_hash, user_type, source_module, status,
                         extra_data, employee_role, advisor_level, customer_level)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        username,
                        f"{username}@example.com",
                        password_hash,
                        "CUSTOMER",
                        "fin",
                        "active" if random.random() > 0.05 else "inactive",  # 5%概率inactive
                        json.dumps({
                            "seed_namespace": NAMESPACE,
                            "display_name": name,
                            "birthday": birthdate,
                            "occupation": occupation,
                            "city": city,
                            "total_assets": str(assets),
                            "advisor_username": advisor['username'],
                            "customer_manager_username": manager['username']
                        }, ensure_ascii=False),
                        None,
                        None,
                        customer_level
                    ))

                    result = self.client.execute_sync("SELECT LAST_INSERT_ID() as id", ())
                    customer_id = result[0]['id']

                    self.customers.append({
                        'id': customer_id,
                        'username': username,
                        'name': name,
                        'risk_level': risk_level,
                        'customer_level': customer_level,
                        'assets': assets,
                        'advisor_id': advisor['id'],
                        'manager_id': manager['id'],
                        'birthdate': birthdate,
                        'occupation': occupation,
                        'city': city,
                        'is_professional': is_professional
                    })

                    seq += 1

                    if seq % 30 == 0:
                        print(f"[PROGRESS] 已生成 {seq-1}/180 个客户")

                except Exception as e:
                    print(f"[ERROR] 生成客户 {name} 失败: {str(e)}")
                    continue

        print(f"[SUCCESS] 客户账号生成完成: {len(self.customers)} 人")

        # 统计风险等级分布
        risk_counts = {}
        for cust in self.customers:
            risk = cust['risk_level']
            risk_counts[risk] = risk_counts.get(risk, 0) + 1

        for risk in ['C1', 'C2', 'C3', 'C4', 'C5']:
            count = risk_counts.get(risk, 0)
            print(f"  {risk}: {count} 人")

    def generate_chinese_name(self):
        """生成中文姓名"""
        surname = random.choice(SURNAMES)
        given = random.choice(GIVEN_NAMES)
        return surname + given

    def generate_customer_profiles(self):
        """生成客户画像"""
        print("\n" + "="*80)
        print("第4步：生成客户画像")
        print("="*80)

        # 风险分数映射
        risk_scores = {
            "C1": Decimal("28"),
            "C2": Decimal("43"),
            "C3": Decimal("58"),
            "C4": Decimal("74"),
            "C5": Decimal("88")
        }

        # 四维度分数映射
        dimensions = {
            "C1": (Decimal("14"), Decimal("7"), Decimal("5"), Decimal("2")),
            "C2": (Decimal("17"), Decimal("11"), Decimal("10"), Decimal("5")),
            "C3": (Decimal("20"), Decimal("16"), Decimal("16"), Decimal("6")),
            "C4": (Decimal("23"), Decimal("21"), Decimal("24"), Decimal("6")),
            "C5": (Decimal("23"), Decimal("24"), Decimal("28"), Decimal("13"))
        }

        for idx, customer in enumerate(self.customers, 1):
            risk_level = customer['risk_level']
            dims = dimensions[risk_level]

            try:
                self.client.execute_sync("""
                    INSERT INTO fin_customer_profile
                    (customer_id, advisor_id, risk_level, risk_score,
                     dimension1_score, dimension2_score, dimension3_score, dimension4_score,
                     fm_flags, asset_allocation, product_preference, memory_units,
                     confidence_score, updated_reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    customer['id'],
                    customer['advisor_id'],
                    risk_level,
                    risk_scores[risk_level],
                    dims[0], dims[1], dims[2], dims[3],
                    json.dumps([]),
                    json.dumps({"total_assets": str(customer['assets']), "currency": "CNY"}),
                    json.dumps({"seed_namespace": NAMESPACE, "risk": risk_level}),
                    json.dumps([{
                        "unit_id": f"{NAMESPACE}:{customer['username']}",
                        "tag": "种子客户",
                        "content": f"{customer['name']}的财富画像",
                        "status": "active"
                    }]),
                    "0.950",
                    "人工触发"
                ))

                if idx % 30 == 0:
                    print(f"[PROGRESS] 已生成 {idx}/180 个客户画像")

            except Exception as e:
                print(f"[ERROR] 生成客户 {customer['name']} 画像失败: {str(e)}")

        print(f"[SUCCESS] 客户画像生成完成")

    def generate_risk_assessments(self):
        """生成风险评估"""
        print("\n" + "="*80)
        print("第5步：生成风险评估")
        print("="*80)

        # 16题答案模板（按风险等级）
        answer_templates = {
            "C1": {"q1": "A", "q2": "A", "q3": "A", "q4": "A", "q5": "A", "q6": "A", "q7": "A", "q8": "A",
                   "q9": "A", "q10": "A", "q11": "A", "q12": "A", "q13": "A", "q14": "A", "q15": "A", "q16": "A"},
            "C2": {"q1": "B", "q2": "A", "q3": "B", "q4": "B", "q5": "A", "q6": "B", "q7": "B", "q8": "A",
                   "q9": "B", "q10": "A", "q11": "B", "q12": "B", "q13": "A", "q14": "B", "q15": "A", "q16": "B"},
            "C3": {"q1": "B", "q2": "B", "q3": "C", "q4": "B", "q5": "B", "q6": "C", "q7": "B", "q8": "B",
                   "q9": "C", "q10": "B", "q11": "C", "q12": "B", "q13": "B", "q14": "C", "q15": "B", "q16": "C"},
            "C4": {"q1": "C", "q2": "C", "q3": "D", "q4": "C", "q5": "C", "q6": "D", "q7": "C", "q8": "C",
                   "q9": "D", "q10": "C", "q11": "D", "q12": "C", "q13": "C", "q14": "D", "q15": "C", "q16": "D"},
            "C5": {"q1": "D", "q2": "D", "q3": "D", "q4": "D", "q5": "D", "q6": "D", "q7": "D", "q8": "D",
                   "q9": "D", "q10": "D", "q11": "D", "q12": "D", "q13": "D", "q14": "D", "q15": "D", "q16": "D"}
        }

        risk_scores = {"C1": Decimal("28"), "C2": Decimal("43"), "C3": Decimal("58"),
                      "C4": Decimal("74"), "C5": Decimal("88")}

        # 85%-95%的客户有有效测评
        assess_count = int(len(self.customers) * 0.90)
        customers_to_assess = random.sample(self.customers, assess_count)

        for idx, customer in enumerate(customers_to_assess, 1):
            risk_level = customer['risk_level']
            answers = answer_templates[risk_level].copy()
            answers["seed_namespace"] = NAMESPACE

            # 评估时间：30-90天前
            days_ago = random.randint(30, 90)
            assessment_time = (self.base_date - timedelta(days=days_ago)).strftime('%Y-%m-%d %H:%M:%S')
            valid_until = (self.base_date + timedelta(days=365-days_ago)).strftime('%Y-%m-%d %H:%M:%S')

            try:
                self.client.execute_sync("""
                    INSERT INTO fin_risk_assessment
                    (customer_id, total_score, risk_level, answers,
                     is_professional_investor, assessment_time, valid_until)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    customer['id'],
                    risk_scores[risk_level],
                    risk_level,
                    json.dumps(answers, ensure_ascii=False),
                    customer['is_professional'],
                    assessment_time,
                    valid_until
                ))

                if idx % 30 == 0:
                    print(f"[PROGRESS] 已生成 {idx}/{len(customers_to_assess)} 份风险评估")

            except Exception as e:
                print(f"[ERROR] 生成客户 {customer['name']} 风险评估失败: {str(e)}")

        print(f"[SUCCESS] 风险评估生成完成: {len(customers_to_assess)} 份")

    def generate_holdings_and_transactions(self):
        """生成持仓和交易"""
        print("\n" + "="*80)
        print("第6步：生成持仓和交易")
        print("="*80)

        transaction_seq = 1

        # 80%的客户有投资
        active_customers = random.sample(self.customers, int(len(self.customers) * 0.80))

        for idx, customer in enumerate(active_customers, 1):
            risk_level = customer['risk_level']

            # 根据风险等级选择合适的产品
            suitable_risks = self.get_suitable_product_risks(risk_level)
            available_products = []
            for r in suitable_risks:
                if r in self.products_by_risk:
                    available_products.extend(self.products_by_risk[r])

            if not available_products:
                continue

            # 每个客户持有1-5个产品
            num_holdings = random.randint(1, min(5, len(available_products)))
            selected_products = random.sample(available_products, num_holdings)

            for product in selected_products:
                # 申购时间：6-12个月前
                days_ago = random.randint(180, 365)
                purchase_date = (self.base_date - timedelta(days=days_ago)).strftime('%Y-%m-%d %H:%M:%S')

                # 申购金额
                min_amount = 10000
                max_amount = int(customer['assets'] * Decimal('0.3'))
                purchase_amount = Decimal(str(random.randint(min_amount, max_amount)))

                # 申购净值
                purchase_nav = Decimal(str(round(random.uniform(0.95, 1.05), 4)))

                # 份额
                shares = purchase_amount / purchase_nav

                # 当前净值
                current_nav = Decimal(str(product['nav']))

                # 当前市值
                current_value = shares * current_nav

                try:
                    # 插入交易记录
                    self.client.execute_sync("""
                        INSERT INTO fin_transaction
                        (customer_id, employee_id, trace_id, idempotency_key,
                         product_id, transaction_type, amount, shares, nav, fee,
                         is_cash, status, transaction_time)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        customer['id'],
                        customer['advisor_id'],
                        f"{NAMESPACE}:tx:{transaction_seq:06d}",
                        f"{NAMESPACE}:idem:{transaction_seq:06d}",
                        product['id'],
                        "申购",
                        str(purchase_amount),
                        str(shares),
                        str(purchase_nav),
                        str(purchase_amount * Decimal('0.015')),  # 1.5%手续费
                        0,
                        "成交",
                        purchase_date
                    ))

                    transaction_seq += 1

                    # 插入持仓记录
                    self.client.execute_sync("""
                        INSERT INTO fin_holdings
                        (customer_id, product_id, shares, cost_amount, current_value,
                         purchase_date, last_update_time)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        customer['id'],
                        product['id'],
                        str(shares),
                        str(purchase_amount),
                        str(current_value),
                        purchase_date,
                        self.base_date.strftime('%Y-%m-%d %H:%M:%S')
                    ))

                except Exception as e:
                    print(f"[ERROR] 生成客户 {customer['name']} 交易失败: {str(e)}")
                    continue

            if idx % 20 == 0:
                print(f"[PROGRESS] 已处理 {idx}/{len(active_customers)} 个客户")

        print(f"[SUCCESS] 持仓和交易生成完成")

    def get_suitable_product_risks(self, customer_risk):
        """获取客户适合的产品风险等级"""
        risk_map = {
            "C1": ["R1"],
            "C2": ["R1", "R2"],
            "C3": ["R1", "R2", "R3"],
            "C4": ["R1", "R2", "R3", "R4"],
            "C5": ["R1", "R2", "R3", "R4", "R5"]
        }
        return risk_map.get(customer_risk, ["R1"])

    def generate_work_orders(self):
        """生成工单"""
        print("\n" + "="*80)
        print("第7步：生成工单")
        print("="*80)

        # 20%的客户有工单
        customers_with_orders = random.sample(self.customers, int(len(self.customers) * 0.20))

        work_order_types = [
            ("产品咨询", "客服专员", "普通"),
            ("申购申请", "理财顾问", "普通"),
            ("赎回申请", "理财顾问", "普通"),
            ("转账审核", "客户经理", "高"),
            ("账户变更", "客户经理", "普通"),
            ("投诉处理", "业务管理员", "高"),
            ("风险预警处理", "风控专员", "紧急")
        ]

        for customer in customers_with_orders:
            wo_type, handler_role, priority = random.choice(work_order_types)

            # 创建时间：7-60天前
            days_ago = random.randint(7, 60)
            created_at = (self.base_date - timedelta(days=days_ago)).strftime('%Y-%m-%d %H:%M:%S')

            # 状态
            status = random.choice(["待处理", "处理中", "已完成", "已完成"])

            try:
                self.client.execute_sync("""
                    INSERT INTO biz_work_order
                    (customer_id, business_type, source, title, intent_summary,
                     priority, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    customer['id'],
                    wo_type,
                    "客户服务",
                    f"{customer['name']}的{wo_type}",
                    f"客户{customer['name']}申请{wo_type}",
                    priority,
                    status,
                    created_at
                ))

            except Exception as e:
                print(f"[ERROR] 生成工单失败: {str(e)}")

        print(f"[SUCCESS] 工单生成完成: {len(customers_with_orders)} 条")

    def generate_risk_alerts(self):
        """生成风险预警"""
        print("\n" + "="*80)
        print("第8步：生成风险预警")
        print("="*80)

        # 10%的客户有风险预警
        customers_with_alerts = random.sample(self.customers, int(len(self.customers) * 0.10))

        alert_types = [
            ("夜间大额转账", "high", "黄", "RW-001"),
            ("短期频繁交易", "medium", "蓝", "RW-002"),
            ("风险等级不适配", "high", "黄", "SUITABILITY-001"),
            ("异常地区登录", "medium", "蓝", "RW-005")
        ]

        for customer in customers_with_alerts:
            alert_type, severity, level, rule_code = random.choice(alert_types)

            # 预警时间：1-30天前
            days_ago = random.randint(1, 30)
            created_at = (self.base_date - timedelta(days=days_ago)).strftime('%Y-%m-%d %H:%M:%S')

            # 状态
            status = random.choice(["待处理", "处理中", "已处理"])

            try:
                self.client.execute_sync("""
                    INSERT INTO fin_risk_alert
                    (customer_id, alert_type, severity, alert_level, rule_code,
                     transaction_ids, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    customer['id'],
                    alert_type,
                    severity,
                    level,
                    rule_code,
                    json.dumps([]),
                    status,
                    created_at
                ))

            except Exception as e:
                print(f"[ERROR] 生成风险预警失败: {str(e)}")

        print(f"[SUCCESS] 风险预警生成完成: {len(customers_with_alerts)} 条")

    def generate_conversations(self):
        """生成会话归档"""
        print("\n" + "="*80)
        print("第9步：生成会话归档")
        print("="*80)

        # 30%的客户有会话记录
        customers_with_conv = random.sample(self.customers, int(len(self.customers) * 0.30))

        for customer in customers_with_conv:
            session_id = f"{NAMESPACE}:session:{customer['username']}"

            # 会话时间：1-90天前
            days_ago = random.randint(1, 90)
            created_at = (self.base_date - timedelta(days=days_ago)).strftime('%Y-%m-%d %H:%M:%S')

            try:
                self.client.execute_sync("""
                    INSERT INTO conversation_archive
                    (session_id, customer_id, agent_type, message_count,
                     summary, emotion, is_resolved, is_transferred_to_human,
                     archive_reason, created_at, archived_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    session_id,
                    customer['id'],
                    random.choice(["客服Agent", "投顾Agent"]),
                    random.randint(5, 20),
                    f"客户咨询{random.choice(['产品信息', '账户查询', '收益情况', '费率说明'])}",
                    random.choice(["neutral", "positive"]),
                    1,
                    0,
                    "会话正常结束",
                    created_at,
                    created_at
                ))

            except Exception as e:
                print(f"[ERROR] 生成会话归档失败: {str(e)}")

        print(f"[SUCCESS] 会话归档生成完成: {len(customers_with_conv)} 条")

    def print_summary(self):
        """打印生成摘要"""
        # 统计数据
        result = self.client.execute_sync("SELECT COUNT(*) as count FROM base_user WHERE user_type='EMPLOYEE'", ())
        emp_count = result[0]['count']

        result = self.client.execute_sync("SELECT COUNT(*) as count FROM base_user WHERE user_type='CUSTOMER'", ())
        cust_count = result[0]['count']

        result = self.client.execute_sync("SELECT COUNT(*) as count FROM fin_customer_profile", ())
        profile_count = result[0]['count']

        print(f"员工: {emp_count} 人")
        print(f"客户: {cust_count} 人")
        print(f"客户画像: {profile_count} 条")


def main():
    parser = argparse.ArgumentParser(description='生成真实业务数据')
    parser.add_argument('--confirm', required=True,
                       help='确认生成（必须传入 GENERATE_REALISTIC_DATA）')

    args = parser.parse_args()

    if args.confirm != "GENERATE_REALISTIC_DATA":
        print("[ERROR] 必须传入 --confirm GENERATE_REALISTIC_DATA 才能执行")
        sys.exit(1)

    generator = BusinessDataGenerator()
    generator.generate_all()


if __name__ == '__main__':
    main()
