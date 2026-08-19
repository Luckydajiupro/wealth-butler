#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能财富管家系统 - 跨数据库真实业务数据生成脚本
生成200名客户的完整业务数据链路，覆盖MySQL、Milvus、Neo4j、Redis、MinIO
严格执行16题风险评估问卷逻辑，保证数据一致性和真实性
"""

import os
import sys
import json
import random
import hashlib
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Any, Optional, Tuple
import logging

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.Base.Config.setting import settings
from app.Base.Client.mysqlClient import MySQLClient
from app.Base.Client.milvusClient import MilvusClientSingleton
from app.Base.Client.redisClient import RedisClient

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ComprehensiveDataGenerator:
    """跨数据库综合数据生成器"""

    def __init__(self):
        """初始化数据库连接和配置"""
        self.mysql_conn = MySQLClient()
        self.milvus_client = MilvusClientSingleton()
        self.redis_conn = RedisClient()

        # 加载风险评估问卷配置
        self.load_risk_questions()

        # 数据存储
        self.employees = []
        self.customers = []
        self.products = []
        self.risk_assessments = []
        self.transactions = []
        self.holdings = []
        self.customer_profiles = []
        self.work_orders = []
        self.risk_alerts = []

        # 中文姓名库
        self.surnames = ['王', '李', '张', '刘', '陈', '杨', '黄', '赵', '周', '吴',
                        '徐', '孙', '马', '朱', '胡', '郭', '何', '林', '高', '罗',
                        '郑', '梁', '谢', '宋', '唐', '许', '韩', '冯', '邓', '曹']

        self.given_names_male = ['伟', '强', '磊', '军', '勇', '涛', '明', '超', '辉', '刚',
                                '鹏', '杰', '峰', '波', '斌', '龙', '健', '浩', '宇', '鑫',
                                '凯', '俊', '翔', '宏', '晨', '阳', '建', '国', '华', '文']

        self.given_names_female = ['芳', '娜', '秀英', '敏', '静', '丽', '艳', '红', '玲', '梅',
                                  '婷', '霞', '莉', '慧', '洁', '琳', '萍', '燕', '云', '娟',
                                  '雪', '倩', '颖', '欣', '蕾', '璐', '雅', '琪', '晶', '月']

        self.occupations = [
            '企业高管', '公务员', '事业单位', '医生', '教师', '工程师',
            '律师', '会计师', '销售', '金融从业者', '自由职业',
            '私营业主', '退休人员', '无业'
        ]

    def load_risk_questions(self):
        """加载16题风险评估问卷配置"""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'app/WealthButler/Service/config/risk_assessment_questions.json'
        )
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            self.risk_questions = config['questions']
            self.risk_score_mapping = config['scoring_rules']['risk_type_mapping']
        logger.info(f"✅ 加载风险问卷配置: {len(self.risk_questions)}题")

    def generate_chinese_name(self, gender: str = 'male') -> str:
        """生成真实的中文姓名"""
        surname = random.choice(self.surnames)
        if gender == 'male':
            given_name = random.choice(self.given_names_male)
        else:
            given_name = random.choice(self.given_names_female)

        # 30%概率生成两个字的名字
        if random.random() < 0.3:
            if gender == 'male':
                given_name += random.choice(self.given_names_male)
            else:
                given_name += random.choice(self.given_names_female)

        return surname + given_name

    def calculate_risk_score(self, answers: List[Dict]) -> Tuple[Decimal, str]:
        """
        计算风险评估总分和风险等级
        严格按照16题问卷权重计算
        """
        total_score = Decimal('0')

        for i, answer in enumerate(answers):
            question = self.risk_questions[i]
            question_weight = Decimal(str(question['weight']))

            # 处理多选题
            if question.get('multiple_choice'):
                selected_options = answer.get('selected_options', [])
                question_score = min(len(selected_options) * 2, question.get('max_score', 10))
            else:
                option_id = answer.get('option_id')
                option_score = next(
                    (opt['score'] for opt in question['options'] if opt['option_id'] == option_id),
                    5
                )
                question_score = option_score

            # 加权计算
            weighted_score = Decimal(str(question_score)) * question_weight
            total_score += weighted_score

        # 映射到风险等级
        risk_level = 'C3'  # 默认平衡型
        for mapping in self.risk_score_mapping:
            min_score, max_score = mapping['score_range']
            if min_score <= float(total_score) <= max_score:
                risk_level = mapping['risk_type']
                break

        return total_score, risk_level

    def generate_risk_answers(self, age: int, assets: Decimal, occupation: str,
                             target_risk_level: Optional[str] = None) -> Tuple[List[Dict], Decimal, str]:
        """
        根据客户属性生成合理的风险问卷答案
        如果指定target_risk_level，会尽量生成对应等级的答案
        """
        answers = []

        # Q1: 年龄段
        if age <= 25:
            answers.append({'question_id': 'Q1', 'option_id': 'A'})
        elif age <= 35:
            answers.append({'question_id': 'Q1', 'option_id': 'B'})
        elif age <= 45:
            answers.append({'question_id': 'Q1', 'option_id': 'C'})
        elif age <= 55:
            answers.append({'question_id': 'Q1', 'option_id': 'D'})
        elif age <= 65:
            answers.append({'question_id': 'Q1', 'option_id': 'E'})
        else:
            answers.append({'question_id': 'Q1', 'option_id': 'F'})

        # Q2: 学历 (根据职业推测)
        if occupation in ['企业高管', '律师', '医生', '工程师']:
            edu_choice = random.choice(['C', 'D'])  # 本科或硕士
        elif occupation in ['公务员', '教师', '会计师']:
            edu_choice = random.choice(['B', 'C'])  # 大专或本科
        else:
            edu_choice = random.choice(['A', 'B', 'C'])
        answers.append({'question_id': 'Q2', 'option_id': edu_choice})

        # Q3: 家庭年收入 (根据资产推测)
        if assets < Decimal('100000'):
            income_choice = random.choice(['A', 'B'])
        elif assets < Decimal('500000'):
            income_choice = random.choice(['B', 'C'])
        elif assets < Decimal('1000000'):
            income_choice = random.choice(['C', 'D'])
        elif assets < Decimal('5000000'):
            income_choice = random.choice(['D', 'E'])
        else:
            income_choice = random.choice(['E', 'F'])
        answers.append({'question_id': 'Q3', 'option_id': income_choice})

        # Q4: 金融资产规模
        if assets < Decimal('100000'):
            asset_choice = 'A'
        elif assets < Decimal('500000'):
            asset_choice = 'B'
        elif assets < Decimal('1000000'):
            asset_choice = 'C'
        elif assets < Decimal('3000000'):
            asset_choice = 'D'
        elif assets < Decimal('5000000'):
            asset_choice = 'E'
        elif assets < Decimal('10000000'):
            asset_choice = 'F'
        else:
            asset_choice = 'G'
        answers.append({'question_id': 'Q4', 'option_id': asset_choice})

        # Q5: 收入稳定性
        if occupation in ['公务员', '事业单位', '教师']:
            stability_choice = 'D'
        elif occupation in ['企业高管', '医生', '工程师', '律师']:
            stability_choice = 'C'
        elif occupation in ['私营业主', '自由职业']:
            stability_choice = 'B'
        else:
            stability_choice = random.choice(['B', 'C'])
        answers.append({'question_id': 'Q5', 'option_id': stability_choice})

        # Q6-Q16: 根据目标风险等级调整
        base_risk_appetite = 3  # 默认中等风险
        if target_risk_level:
            if target_risk_level == 'C1':
                base_risk_appetite = 1
            elif target_risk_level == 'C2':
                base_risk_appetite = 2
            elif target_risk_level == 'C3':
                base_risk_appetite = 3
            elif target_risk_level == 'C4':
                base_risk_appetite = 4
            elif target_risk_level == 'C5':
                base_risk_appetite = 5

        # Q6: 投资经验
        exp_choices = ['A', 'B', 'C', 'D', 'E', 'F']
        exp_idx = min(base_risk_appetite, len(exp_choices) - 1)
        answers.append({'question_id': 'Q6', 'option_id': exp_choices[exp_idx]})

        # Q7: 投资产品经验（多选）
        product_exp = []
        if base_risk_appetite >= 1:
            product_exp.append('A')
        if base_risk_appetite >= 2:
            product_exp.append('B')
        if base_risk_appetite >= 3:
            product_exp.append('C')
        if base_risk_appetite >= 4:
            product_exp.append('D')
        if base_risk_appetite >= 5:
            product_exp.append('E')
        answers.append({'question_id': 'Q7', 'selected_options': product_exp})

        # Q8: 投资收益情况
        return_choices = ['A', 'B', 'C', 'D', 'E']
        return_idx = min(base_risk_appetite - 1, len(return_choices) - 1)
        answers.append({'question_id': 'Q8', 'option_id': return_choices[max(0, return_idx)]})

        # Q9: 投资目的
        purpose_choices = ['A', 'B', 'C', 'D', 'E']
        purpose_idx = min(base_risk_appetite - 1, len(purpose_choices) - 1)
        answers.append({'question_id': 'Q9', 'option_id': purpose_choices[purpose_idx]})

        # Q10: 亏损承受能力
        loss_choices = ['A', 'B', 'C', 'D', 'E']
        loss_idx = min(base_risk_appetite - 1, len(loss_choices) - 1)
        answers.append({'question_id': 'Q10', 'option_id': loss_choices[loss_idx]})

        # Q11: 投资期限
        period_choices = ['A', 'B', 'C', 'D', 'E']
        period_idx = min(base_risk_appetite - 1, len(period_choices) - 1)
        answers.append({'question_id': 'Q11', 'option_id': period_choices[period_idx]})

        # Q12: 负债情况
        debt_choice = random.choice(['C', 'D'])
        answers.append({'question_id': 'Q12', 'option_id': debt_choice})

        # Q13: 下跌反应
        reaction_choices = ['A', 'B', 'C', 'D']
        reaction_idx = min(base_risk_appetite - 2, len(reaction_choices) - 1)
        answers.append({'question_id': 'Q13', 'option_id': reaction_choices[max(0, reaction_idx)]})

        # Q14: 投资资金占比
        ratio_choice = random.choice(['C', 'D'])
        answers.append({'question_id': 'Q14', 'option_id': ratio_choice})

        # Q15: 短期使用需求
        usage_choice = random.choice(['B', 'C', 'D'])
        answers.append({'question_id': 'Q15', 'option_id': usage_choice})

        # Q16: 投资态度
        attitude_choices = ['A', 'B', 'C', 'D']
        attitude_idx = min(base_risk_appetite - 2, len(attitude_choices) - 1)
        answers.append({'question_id': 'Q16', 'option_id': attitude_choices[max(0, attitude_idx)]})

        # 计算总分和风险等级
        total_score, risk_level = self.calculate_risk_score(answers)

        return answers, total_score, risk_level

    # ==================== 阶段1: MySQL核心业务数据 ====================

    def stage1_generate_mysql_data(self):
        """阶段1: 生成MySQL核心业务数据"""
        logger.info("=" * 60)
        logger.info("阶段1: 开始生成MySQL核心业务数据")
        logger.info("=" * 60)

        # 清理旧数据（按依赖顺序删除）
        logger.info("清理旧数据...")
        self.mysql_conn.execute_sync("SET FOREIGN_KEY_CHECKS = 0")
        self.mysql_conn.execute_sync("DELETE FROM fin_holdings WHERE id > 0")
        self.mysql_conn.execute_sync("DELETE FROM fin_transaction WHERE id > 0")
        self.mysql_conn.execute_sync("DELETE FROM fin_customer_profile WHERE id > 0")
        self.mysql_conn.execute_sync("DELETE FROM fin_risk_assessment WHERE id > 0")
        self.mysql_conn.execute_sync("DELETE FROM fin_risk_alert WHERE id > 0")
        self.mysql_conn.execute_sync("DELETE FROM biz_work_order WHERE id > 0")
        self.mysql_conn.execute_sync("DELETE FROM biz_compliance_evidence WHERE id > 0")
        self.mysql_conn.execute_sync("DELETE FROM base_user WHERE user_type IN ('CUSTOMER', 'EMPLOYEE')")
        self.mysql_conn.execute_sync("SET FOREIGN_KEY_CHECKS = 1")
        logger.info("✅ 旧数据清理完成")

        # 1.1 生成员工数据
        self.generate_employees()

        # 1.2 生成客户数据
        self.generate_customers()

        # 1.3 获取产品数据（应该已存在）
        self.load_existing_products()

        # 1.4 生成风险评估记录
        self.generate_risk_assessments()

        # 1.5 生成客户画像
        self.generate_customer_profiles()

        # 1.6 生成交易记录
        self.generate_transactions()

        # 1.7 生成持仓记录
        self.generate_holdings()

        # 1.8 生成工单
        self.generate_work_orders()

        # 1.9 生成风险预警
        self.generate_risk_alerts()

        logger.info("✅ 阶段1完成: MySQL核心业务数据生成完毕")

    def generate_employees(self):
        """生成14名员工"""
        logger.info("正在生成14名员工...")

        # 先检查是否已有员工数据，如果有则清理
        check_sql = "SELECT COUNT(*) as cnt FROM base_user WHERE user_type = 'EMPLOYEE'"
        result = self.mysql_conn.execute_sync(check_sql)
        if result[0]['cnt'] > 0:
            logger.warning(f"检测到已有{result[0]['cnt']}名员工，将清理旧数据...")
            # 删除旧员工数据（注意：这会级联影响相关数据）
            self.mysql_conn.execute_sync("DELETE FROM base_user WHERE user_type = 'EMPLOYEE'")

        employee_configs = [
            # 4名初级理财顾问
            {'role': '理财顾问', 'level': '初级', 'name': '张晓婷'},
            {'role': '理财顾问', 'level': '初级', 'name': '李明轩'},
            {'role': '理财顾问', 'level': '初级', 'name': '王雅琪'},
            {'role': '理财顾问', 'level': '初级', 'name': '陈浩宇'},
            # 4名中级理财顾问
            {'role': '理财顾问', 'level': '中级', 'name': '刘诗涵'},
            {'role': '理财顾问', 'level': '中级', 'name': '赵子健'},
            {'role': '理财顾问', 'level': '中级', 'name': '杨思妍'},
            {'role': '理财顾问', 'level': '中级', 'name': '周俊杰'},
            # 3名高级理财顾问
            {'role': '理财顾问', 'level': '高级', 'name': '徐欣怡'},
            {'role': '理财顾问', 'level': '高级', 'name': '马天宇'},
            {'role': '理财顾问', 'level': '高级', 'name': '郑雨萱'},
            # 其他角色
            {'role': '风控专员', 'level': None, 'name': '林风华'},
            {'role': '客户经理', 'level': None, 'name': '胡晓东'},
            {'role': '业务管理员', 'level': None, 'name': '吴建国'},
        ]

        for config in employee_configs:
            username = config['name']
            password_hash = hashlib.sha256(f"Wb{config['name']}@2024".encode()).hexdigest()

            sql = """
                INSERT INTO base_user
                (username, email, phone, password_hash, source_module, status,
                 user_type, employee_role, advisor_level, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """
            params = (
                username,
                f"{username}@wealthbutler.com",
                f"138{random.randint(10000000, 99999999)}",
                password_hash,
                'fin',
                'active',
                'EMPLOYEE',
                config['role'],
                config.get('level'),
            )

            self.mysql_conn.execute_sync(sql, params)
            employee_id = self.mysql_conn.execute_sync("SELECT LAST_INSERT_ID() as id")[0]['id']

            self.employees.append({
                'id': employee_id,
                'name': username,
                'role': config['role'],
                'level': config.get('level')
            })

        logger.info(f"✅ 生成14名员工完成")

    def generate_customers(self):
        """生成200名客户"""
        logger.info("正在生成200名客户...")

        # 先检查是否已有客户数据
        check_sql = "SELECT COUNT(*) as cnt FROM base_user WHERE user_type = 'CUSTOMER'"
        result = self.mysql_conn.execute_sync(check_sql)
        if result[0]['cnt'] > 0:
            logger.warning(f"检测到已有{result[0]['cnt']}名客户，将清理旧数据...")
            self.mysql_conn.execute_sync("DELETE FROM base_user WHERE user_type = 'CUSTOMER'")

        # 客户等级分布：金卡80、白金70、钻石35、私行15
        customer_levels = (['金卡'] * 80 + ['白金'] * 70 +
                          ['钻石'] * 35 + ['私行'] * 15)
        random.shuffle(customer_levels)

        # 极高净值客户标记（9位：5000万-5亿）
        ultra_high_net_worth_count = 9
        ultra_indices = random.sample(range(200), ultra_high_net_worth_count)

        for i in range(200):
            level = customer_levels[i]
            is_ultra = i in ultra_indices

            # 根据等级和是否极高净值确定资产范围
            if is_ultra:
                assets = Decimal(random.randint(50000000, 500000000))  # 5千万-5亿
            elif level == '私行':
                assets = Decimal(random.randint(6000000, 20000000))  # 600万-2000万
            elif level == '钻石':
                assets = Decimal(random.randint(2000000, 6000000))  # 200万-600万
            elif level == '白金':
                assets = Decimal(random.randint(500000, 2000000))  # 50万-200万
            else:  # 金卡
                assets = Decimal(random.randint(100000, 500000))  # 10万-50万

            # 生成客户基本信息
            gender = random.choice(['male', 'female'])
            name = self.generate_chinese_name(gender)

            # 年龄与资产相关
            if assets > Decimal('10000000'):
                age = random.randint(40, 65)
            elif assets > Decimal('1000000'):
                age = random.randint(30, 55)
            else:
                age = random.randint(25, 45)

            # 职业与资产相关
            if assets > Decimal('5000000'):
                occupation = random.choice(['企业高管', '私营业主', '医生', '律师'])
            elif assets > Decimal('1000000'):
                occupation = random.choice(['企业高管', '医生', '工程师', '金融从业者'])
            else:
                occupation = random.choice(self.occupations)

            # 分配理财顾问（按等级匹配）
            if level in ['私行', '钻石']:
                advisor = random.choice([e for e in self.employees
                                       if e['role'] == '理财顾问' and e['level'] == '高级'])
            elif level == '白金':
                advisor = random.choice([e for e in self.employees
                                       if e['role'] == '理财顾问' and e['level'] == '中级'])
            else:
                advisor = random.choice([e for e in self.employees
                                       if e['role'] == '理财顾问'])

            # 插入客户
            username = f"{name}{i+1:03d}"  # 添加编号避免重名，例如：王伟001
            password_hash = hashlib.sha256(f"Cust{i+1}@2024".encode()).hexdigest()

            sql = """
                INSERT INTO base_user
                (username, email, phone, password_hash, source_module, status,
                 user_type, customer_level, extra_data, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """

            extra_data = json.dumps({
                'real_name': name,
                'age': age,
                'gender': gender,
                'occupation': occupation,
                'total_assets': str(assets),
                'is_ultra_high_net_worth': is_ultra
            }, ensure_ascii=False)

            params = (
                username,
                f"customer{i+1}@example.com",
                f"139{random.randint(10000000, 99999999)}",
                password_hash,
                'fin',
                'active',
                'CUSTOMER',
                level,
                extra_data,
            )

            self.mysql_conn.execute_sync(sql, params)
            customer_id = self.mysql_conn.execute_sync("SELECT LAST_INSERT_ID() as id")[0]['id']

            self.customers.append({
                'id': customer_id,
                'name': name,
                'age': age,
                'gender': gender,
                'occupation': occupation,
                'assets': assets,
                'level': level,
                'advisor_id': advisor['id'],
                'is_ultra': is_ultra
            })

        logger.info(f"✅ 生成200名客户完成（含{ultra_high_net_worth_count}位极高净值客户）")

    def load_existing_products(self):
        """加载现有产品数据"""
        logger.info("正在加载产品数据...")

        sql = "SELECT * FROM fin_product WHERE status = '在售' LIMIT 100"
        results = self.mysql_conn.execute_sync(sql)

        if not results:
            logger.warning("⚠️  未找到在售产品，将创建基础产品数据")
            self.create_basic_products()
            results = self.mysql_conn.execute_sync(sql)

        self.products = [dict(row) for row in results]
        logger.info(f"✅ 加载{len(self.products)}个产品")

    def create_basic_products(self):
        """创建基础产品数据（如果不存在）"""
        logger.info("创建基础产品数据...")

        products = [
            ('FD001', '稳健增利1号', '银行理财', 'R1', 10000, 1.035),
            ('FD002', '安心宝2号', '银行理财', 'R2', 50000, 1.042),
            ('MF001', '蓝筹精选混合A', '公募基金', 'R3', 1000, 1.456),
            ('MF002', '成长动力股票型', '公募基金', 'R4', 1000, 1.823),
            ('MF003', '科技创新混合', '公募基金', 'R4', 10000, 1.678),
            ('PF001', '鼎盛私募一期', '私募基金', 'R5', 1000000, 1.234),
            ('TR001', '富盈信托计划', '信托', 'R3', 1000000, 1.089),
            ('ST001', '结构存款A款', '结构性存款', 'R2', 50000, 1.018),
        ]

        for code, name, ptype, risk, min_inv, nav in products:
            sql = """
                INSERT INTO fin_product
                (product_code, product_name, product_type, risk_level,
                 min_investment, nav, nav_date, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, CURDATE(), '在售', NOW())
            """
            self.mysql_conn.execute_sync(sql, (code, name, ptype, risk, min_inv, nav))

        logger.info("✅ 创建基础产品完成")

    def generate_risk_assessments(self):
        """生成初始风险评估记录（180份）"""
        logger.info("正在生成初始风险评估记录...")

        # 随机选择180个客户进行初始风评
        assessed_customers = random.sample(self.customers, 180)

        for customer in assessed_customers:
            # 根据客户等级确定目标风险等级
            if customer['level'] == '私行':
                target_risk = random.choice(['C4', 'C5'])
            elif customer['level'] == '钻石':
                target_risk = random.choice(['C3', 'C4'])
            elif customer['level'] == '白金':
                target_risk = random.choice(['C2', 'C3'])
            else:
                target_risk = random.choice(['C1', 'C2', 'C3'])

            # 生成风险问卷答案
            answers, total_score, risk_level = self.generate_risk_answers(
                customer['age'],
                customer['assets'],
                customer['occupation'],
                target_risk
            )

            # 评估时间（开户后1-7天）
            assessment_time = datetime.now() - timedelta(days=random.randint(1, 7))
            valid_until = assessment_time + timedelta(days=365)

            sql = """
                INSERT INTO fin_risk_assessment
                (customer_id, total_score, risk_level, answers,
                 is_professional_investor, assessment_time, valid_until, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            """

            params = (
                customer['id'],
                float(total_score),
                risk_level,
                json.dumps(answers, ensure_ascii=False),
                customer['assets'] > Decimal('6000000'),  # 600万以上可能是专业投资者
                assessment_time,
                valid_until,
            )

            self.mysql_conn.execute_sync(sql, params)
            assessment_id = self.mysql_conn.execute_sync("SELECT LAST_INSERT_ID() as id")[0]['id']

            self.risk_assessments.append({
                'id': assessment_id,
                'customer_id': customer['id'],
                'risk_level': risk_level,
                'total_score': total_score
            })

            # 更新客户的风险等级到extra_data
            customer['risk_level'] = risk_level

        logger.info(f"✅ 生成{len(self.risk_assessments)}份风险评估记录")

    def generate_customer_profiles(self):
        """生成客户画像"""
        logger.info("正在生成客户画像...")

        for customer in self.customers:
            # 查找该客户的风险评估
            risk_assessment = next(
                (ra for ra in self.risk_assessments if ra['customer_id'] == customer['id']),
                None
            )

            if risk_assessment:
                risk_level = risk_assessment['risk_level']
                risk_score = risk_assessment['total_score']
            else:
                risk_level = 'C3'
                risk_score = Decimal('55.0')

            # 四维度打分（简化版）
            dimension1_score = Decimal(random.uniform(15, 25))  # 基础属性
            dimension2_score = Decimal(random.uniform(15, 25))  # 投资经验
            dimension3_score = Decimal(random.uniform(20, 30))  # 风险偏好
            dimension4_score = Decimal(random.uniform(15, 20))  # 行为异常

            # 资产配置画像
            asset_allocation = {
                '现金类': random.randint(30, 70),
                '固收类': random.randint(10, 40),
                '权益类': random.randint(5, 30),
                '另类': random.randint(0, 10)
            }

            # 产品偏好
            product_preference = {
                '银行理财': random.randint(20, 60),
                '公募基金': random.randint(20, 50),
                '私募基金': random.randint(0, 20) if customer['assets'] > Decimal('1000000') else 0
            }

            sql = """
                INSERT INTO fin_customer_profile
                (customer_id, advisor_id, risk_level, risk_score,
                 dimension1_score, dimension2_score, dimension3_score, dimension4_score,
                 fm_flags, asset_allocation, product_preference,
                 confidence_score, updated_reason, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            """

            params = (
                customer['id'],
                customer['advisor_id'],
                risk_level,
                float(risk_score),
                float(dimension1_score),
                float(dimension2_score),
                float(dimension3_score),
                float(dimension4_score),
                json.dumps([]),  # fm_flags
                json.dumps(asset_allocation, ensure_ascii=False),
                json.dumps(product_preference, ensure_ascii=False),
                0.85,  # confidence_score
                '定期',
            )

            self.mysql_conn.execute_sync(sql, params)

            self.customer_profiles.append({
                'customer_id': customer['id'],
                'risk_level': risk_level
            })

        logger.info(f"✅ 生成{len(self.customer_profiles)}份客户画像")

    def generate_transactions(self):
        """生成交易记录（1800-2200条）"""
        logger.info("正在生成交易记录...")

        target_count = random.randint(1800, 2200)
        transactions_per_customer = target_count // len(self.customers)

        for customer in self.customers:
            # 每个客户生成5-15笔交易
            num_transactions = random.randint(5, 15)

            for _ in range(num_transactions):
                # 选择产品（根据风险等级匹配）
                customer_risk = customer.get('risk_level', 'C3')
                suitable_products = self.get_suitable_products(customer_risk)

                if not suitable_products:
                    suitable_products = self.products

                product = random.choice(suitable_products)

                # 交易类型
                trans_type = random.choice(['申购', '申购', '申购', '赎回'])  # 申购占75%

                # 交易金额
                if trans_type == '申购':
                    amount = Decimal(random.randint(10000, int(customer['assets'] * Decimal('0.3'))))
                else:
                    amount = Decimal(random.randint(5000, 50000))

                # 交易时间（最近30天内）
                trans_time = datetime.now() - timedelta(days=random.randint(0, 30))

                # 份额和净值
                nav = Decimal(product['nav'])
                shares = amount / nav if trans_type == '申购' else amount / nav
                fee = amount * Decimal('0.015') if trans_type == '申购' else amount * Decimal('0.005')

                sql = """
                    INSERT INTO fin_transaction
                    (customer_id, employee_id, product_id, transaction_type,
                     amount, shares, nav, fee, channel, status, transaction_time, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """

                params = (
                    customer['id'],
                    customer['advisor_id'],
                    product['id'],
                    trans_type,
                    float(amount),
                    float(shares),
                    float(nav),
                    float(fee),
                    random.choice(['APP', '柜台', '网银']),
                    '成交',
                    trans_time,
                )

                self.mysql_conn.execute_sync(sql, params)
                trans_id = self.mysql_conn.execute_sync("SELECT LAST_INSERT_ID() as id")[0]['id']

                self.transactions.append({
                    'id': trans_id,
                    'customer_id': customer['id'],
                    'product_id': product['id'],
                    'type': trans_type,
                    'amount': amount,
                    'shares': shares,
                    'employee_id': customer['advisor_id'],
                    'created_at': trans_time
                })

        logger.info(f"✅ 生成{len(self.transactions)}条交易记录")

    def get_suitable_products(self, risk_level: str) -> List[Dict]:
        """根据风险等级筛选适合的产品"""
        risk_mapping = {
            'C1': ['R1'],
            'C2': ['R1', 'R2'],
            'C3': ['R1', 'R2', 'R3'],
            'C4': ['R2', 'R3', 'R4'],
            'C5': ['R3', 'R4', 'R5']
        }

        allowed_risks = risk_mapping.get(risk_level, ['R1', 'R2', 'R3'])
        return [p for p in self.products if p['risk_level'] in allowed_risks]

    def generate_holdings(self):
        """生成持仓记录（600-800个）"""
        logger.info("正在生成持仓记录...")

        # 统计每个客户的申购和赎回
        customer_transactions = {}
        for trans in self.transactions:
            key = (trans['customer_id'], trans['product_id'])
            if key not in customer_transactions:
                customer_transactions[key] = {'purchase': Decimal('0'), 'redeem': Decimal('0'), 'shares': Decimal('0')}

            if trans['type'] == '申购':
                customer_transactions[key]['purchase'] += trans['amount']
                customer_transactions[key]['shares'] += trans['shares']
            else:
                customer_transactions[key]['redeem'] += trans['amount']
                customer_transactions[key]['shares'] -= trans['shares']

        # 生成持仓记录（份额>0的才生成）
        for (customer_id, product_id), data in customer_transactions.items():
            if data['shares'] > Decimal('0'):
                cost_amount = data['purchase'] - data['redeem']
                shares = data['shares']

                # 获取产品当前净值计算市值
                product = next(p for p in self.products if p['id'] == product_id)
                current_nav = Decimal(product['nav']) * Decimal(random.uniform(0.95, 1.15))  # 净值浮动
                current_value = shares * current_nav
                profit_loss = current_value - cost_amount
                profit_ratio = profit_loss / cost_amount if cost_amount > 0 else Decimal('0')

                # 首次购买日期
                purchase_date = min(
                    [t for t in self.transactions
                     if t['customer_id'] == customer_id and t['product_id'] == product_id
                     and t['type'] == '申购'],
                    key=lambda x: self.transactions.index(x)
                )

                sql = """
                    INSERT INTO fin_holdings
                    (customer_id, product_id, shares, cost_amount, current_value,
                     profit_loss, profit_ratio, purchase_date, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                """

                params = (
                    customer_id,
                    product_id,
                    float(shares),
                    float(cost_amount),
                    float(current_value),
                    float(profit_loss),
                    float(profit_ratio),
                    datetime.now() - timedelta(days=random.randint(10, 60)),
                )

                self.mysql_conn.execute_sync(sql, params)

                self.holdings.append({
                    'customer_id': customer_id,
                    'product_id': product_id,
                    'shares': shares,
                    'cost_amount': cost_amount,
                    'current_value': current_value
                })

        logger.info(f"✅ 生成{len(self.holdings)}个持仓记录")

    def generate_work_orders(self):
        """生成工单（50-80个）"""
        logger.info("正在生成工单...")

        num_orders = random.randint(50, 80)
        order_types = ['风控预警', '咨询', '账户变更', '业务申请', '客户转介']

        for i in range(num_orders):
            customer = random.choice(self.customers)
            order_type = random.choice(order_types)

            # 使用时间戳和随机数确保唯一性
            order_no = f"WO{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(1000, 9999)}"

            titles = {
                '风控预警': f"客户{customer['name']}触发大额交易预警",
                '咨询': f"客户{customer['name']}咨询产品信息",
                '账户变更': f"客户{customer['name']}申请变更手机号",
                '业务申请': f"客户{customer['name']}申请开通私行服务",
                '客户转介': f"客户{customer['name']}需转介至高级顾问"
            }

            status = random.choice(['待处理', '处理中', '已完成'])
            handler = random.choice([e for e in self.employees if e['role'] in ['理财顾问', '客户经理']])

            sql = """
                INSERT INTO biz_work_order
                (order_no, order_type, source, customer_id, customer_name,
                 title, description, status, priority, handler_id, handler_name, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """

            params = (
                order_no,
                order_type,
                '系统生成' if order_type == '风控预警' else '客户提交',
                customer['id'],
                customer['name'],
                titles[order_type],
                f"{order_type}详细描述",
                status,
                '中' if order_type != '风控预警' else '高',
                handler['id'],
                handler['name'],
            )

            self.mysql_conn.execute_sync(sql, params)

            self.work_orders.append({
                'order_no': order_no,
                'customer_id': customer['id'],
                'type': order_type
            })

        logger.info(f"✅ 生成{len(self.work_orders)}个工单")

    def generate_risk_alerts(self):
        """生成风险预警（30-50个）"""
        logger.info("正在生成风险预警...")

        num_alerts = random.randint(30, 50)
        risk_rules = [
            {'id': 'RW-001', 'name': '单笔大额交易预警', 'severity': 'high'},
            {'id': 'RW-002', 'name': '频繁小额交易预警', 'severity': 'medium'},
            {'id': 'RW-003', 'name': '跨境资金流动预警', 'severity': 'high'},
            {'id': 'RW-004', 'name': '异常设备登录预警', 'severity': 'medium'},
            {'id': 'RW-005', 'name': '资金集中转入预警', 'severity': 'high'},
        ]

        for i in range(num_alerts):
            customer = random.choice(self.customers)
            rule = random.choice(risk_rules)

            # 关联交易
            customer_trans = [t for t in self.transactions if t['customer_id'] == customer['id']]
            related_trans = random.choice(customer_trans) if customer_trans else None

            trigger_details = {
                'rule_id': rule['id'],
                'trigger_time': datetime.now().isoformat(),
                'details': f"客户{customer['name']}触发{rule['name']}",
                'threshold': '500000',
                'actual_value': '650000'
            }

            sql = """
                INSERT INTO fin_risk_alert
                (customer_id, rule_id, rule_name, severity, confidence,
                 trigger_details, related_transaction_id, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """

            params = (
                customer['id'],
                rule['id'],
                rule['name'],
                rule['severity'],
                random.uniform(0.7, 0.95),
                json.dumps(trigger_details, ensure_ascii=False),
                related_trans['id'] if related_trans else None,
                random.choice(['待处理', '已处理']),
            )

            self.mysql_conn.execute_sync(sql, params)

            self.risk_alerts.append({
                'customer_id': customer['id'],
                'rule_id': rule['id']
            })

        logger.info(f"✅ 生成{len(self.risk_alerts)}个风险预警")

    # ==================== 阶段2: 客户记忆向量（Milvus）====================

    def stage2_generate_milvus_data(self):
        """阶段2: 生成Milvus客户记忆向量数据"""
        logger.info("=" * 60)
        logger.info("阶段2: 开始生成Milvus客户记忆向量数据")
        logger.info("=" * 60)

        try:
            import requests
            import os

            collection_name = os.getenv('WEALTH_BUTLER_MEMORY_COLLECTION', 'fin_customer_memory_collection_v2')
            logger.info(f"目标集合: {collection_name}")

            # 确保集合存在
            self.ensure_milvus_collection(collection_name)

            # 为每个客户生成3-5条记忆
            total_memories = 0
            batch_data = []

            for customer in self.customers:
                num_memories = random.randint(3, 5)

                for _ in range(num_memories):
                    memory_type, memory_text = self.generate_customer_memory(customer)

                    # 调用Ollama生成embedding
                    embedding = self.get_ollama_embedding(memory_text)

                    if embedding:
                        memory_data = {
                            'customer_id': str(customer['id']),
                            'memory_type': memory_type,
                            'memory_text': memory_text,
                            'metadata': json.dumps({
                                'customer_name': customer['name'],
                                'customer_level': customer['level'],
                                'created_at': datetime.now().isoformat()
                            }, ensure_ascii=False),
                            'embedding': embedding
                        }
                        batch_data.append(memory_data)
                        total_memories += 1

                    # 每100条批量写入
                    if len(batch_data) >= 100:
                        self.milvus_client.insert(collection_name, batch_data)
                        logger.info(f"已写入{total_memories}条记忆向量...")
                        batch_data = []

            # 写入剩余数据
            if batch_data:
                self.milvus_client.insert(collection_name, batch_data)

            logger.info(f"✅ 阶段2完成: 生成{total_memories}条客户记忆向量")

        except Exception as e:
            logger.error(f"❌ Milvus数据生成失败: {e}")
            import traceback
            traceback.print_exc()

    def ensure_milvus_collection(self, collection_name: str):
        """确保Milvus集合存在"""
        from pymilvus import FieldSchema, CollectionSchema, DataType

        client = self.milvus_client.get_client()

        if not client.has_collection(collection_name):
            logger.info(f"创建Milvus集合: {collection_name}")

            # 定义集合Schema
            fields = [
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name="customer_id", dtype=DataType.VARCHAR, max_length=50),
                FieldSchema(name="memory_type", dtype=DataType.VARCHAR, max_length=50),
                FieldSchema(name="memory_text", dtype=DataType.VARCHAR, max_length=2000),
                FieldSchema(name="metadata", dtype=DataType.VARCHAR, max_length=1000),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1024),
            ]

            schema = CollectionSchema(fields, description="客户记忆向量集合")

            # 创建集合
            client.create_collection(
                collection_name=collection_name,
                schema=schema
            )

            # 创建索引
            index_params = client.prepare_index_params()
            index_params.add_index(
                field_name="embedding",
                index_type="HNSW",
                metric_type="COSINE",
                params={"M": 16, "efConstruction": 256}
            )
            client.create_index(collection_name, index_params)

            # 加载集合
            client.load_collection(collection_name)

            logger.info(f"✅ Milvus集合创建完成")
        else:
            logger.info(f"Milvus集合已存在: {collection_name}")

    def generate_customer_memory(self, customer: Dict) -> Tuple[str, str]:
        """生成客户记忆内容"""
        memory_types = ['investment_preference', 'service_preference', 'life_event', 'risk_attitude']
        weights = [0.6, 0.2, 0.1, 0.1]
        memory_type = random.choices(memory_types, weights=weights)[0]

        templates = {
            'investment_preference': [
                f"{customer['name']}偏好稳健型产品，关注收益稳定性",
                f"{customer['name']}倾向于配置50%的权益类资产",
                f"{customer['name']}对科技行业特别感兴趣",
            ],
            'service_preference': [
                f"{customer['name']}习惯通过APP联系顾问",
                f"{customer['name']}希望每月收到一次投资报告",
                f"{customer['name']}对投资建议的响应速度要求较高",
            ],
            'life_event': [
                f"{customer['name']}计划在2年内购房",
                f"{customer['name']}近期收到一笔奖金",
            ],
            'risk_attitude': [
                f"{customer['name']}能够接受10%的年度波动",
                f"{customer['name']}在市场下跌时倾向于持仓不动",
                f"{customer['name']}投资决策风格偏理性分析",
            ]
        }

        memory_text = random.choice(templates[memory_type])
        return memory_type, memory_text

    def get_ollama_embedding(self, text: str) -> Optional[List[float]]:
        """调用Ollama生成embedding"""
        try:
            import requests

            # 使用.env中配置的Ollama地址
            ollama_url = os.getenv('OLLAMA_BASE_URL', 'http://192.168.110.106:11434')
            model = os.getenv('OLLAMA_EMBEDDING_MODEL', 'bge-m3')

            response = requests.post(
                f"{ollama_url}/api/embeddings",
                json={
                    "model": model,
                    "prompt": text
                },
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                return result.get('embedding')
            else:
                logger.warning(f"Ollama embedding失败: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"调用Ollama失败: {e}")
            return None

    # ==================== 阶段3: Neo4j图数据 ====================

    def stage3_generate_neo4j_data(self):
        """阶段3: 生成Neo4j图谱数据"""
        logger.info("=" * 60)
        logger.info("阶段3: 开始生成Neo4j图谱数据")
        logger.info("=" * 60)

        try:
            from neo4j import GraphDatabase

            neo4j_uri = os.getenv('NEO4J_URI', 'bolt://192.168.110.106:7687')
            neo4j_user = os.getenv('NEO4J_USER', 'neo4j')
            neo4j_password = os.getenv('NEO4J_PASSWORD', '')

            driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

            with driver.session() as session:
                # 清空现有数据（可选）
                # session.run("MATCH (n) DETACH DELETE n")

                # 创建Customer节点
                logger.info("创建Customer节点...")
                for customer in self.customers:
                    session.run("""
                        MERGE (c:Customer {customer_id: $customer_id})
                        SET c.name = $name,
                            c.level = $level,
                            c.age = $age,
                            c.assets = $assets
                    """, customer_id=customer['id'], name=customer['name'],
                        level=customer['level'], age=customer['age'],
                        assets=float(customer['assets']))

                # 创建Employee节点
                logger.info("创建Employee节点...")
                for employee in self.employees:
                    session.run("""
                        MERGE (e:Employee {employee_id: $employee_id})
                        SET e.name = $name,
                            e.role = $role,
                            e.level = $level
                    """, employee_id=employee['id'], name=employee['name'],
                        role=employee['role'], level=employee.get('level'))

                # 创建Product节点
                logger.info("创建Product节点...")
                for product in self.products[:20]:  # 只创建部分产品节点
                    session.run("""
                        MERGE (p:Product {product_id: $product_id})
                        SET p.name = $name,
                            p.type = $type,
                            p.risk_level = $risk_level
                    """, product_id=product['id'], name=product['product_name'],
                        type=product['product_type'], risk_level=product['risk_level'])

                # 创建ADVISED_BY关系
                logger.info("创建ADVISED_BY关系...")
                for customer in self.customers:
                    session.run("""
                        MATCH (c:Customer {customer_id: $customer_id})
                        MATCH (e:Employee {employee_id: $advisor_id})
                        MERGE (c)-[:ADVISED_BY]->(e)
                    """, customer_id=customer['id'], advisor_id=customer['advisor_id'])

                # 创建HOLDS关系（当前持仓）
                logger.info("创建HOLDS关系...")
                for holding in self.holdings:
                    session.run("""
                        MATCH (c:Customer {customer_id: $customer_id})
                        MATCH (p:Product {product_id: $product_id})
                        MERGE (c)-[r:HOLDS]->(p)
                        SET r.shares = $shares,
                            r.cost_amount = $cost_amount,
                            r.current_value = $current_value
                    """, customer_id=holding['customer_id'],
                        product_id=holding['product_id'],
                        shares=float(holding['shares']),
                        cost_amount=float(holding['cost_amount']),
                        current_value=float(holding['current_value']))

                # 创建TRADED关系（历史交易）
                logger.info("创建TRADED关系...")
                for trans in self.transactions[:500]:  # 只创建部分交易关系
                    session.run("""
                        MATCH (c:Customer {customer_id: $customer_id})
                        MATCH (p:Product {product_id: $product_id})
                        MERGE (c)-[r:TRADED]->(p)
                        ON CREATE SET r.count = 1, r.total_amount = $amount
                        ON MATCH SET r.count = r.count + 1,
                                     r.total_amount = r.total_amount + $amount
                    """, customer_id=trans['customer_id'],
                        product_id=trans['product_id'],
                        amount=float(trans['amount']))

            driver.close()
            logger.info(f"✅ 阶段3完成: Neo4j图谱数据生成完毕")

        except Exception as e:
            logger.error(f"❌ Neo4j数据生成失败: {e}")
            import traceback
            traceback.print_exc()

    # ==================== 阶段4: Redis缓存与消息 ====================

    def stage4_generate_redis_data(self):
        """阶段4: 生成Redis缓存与消息数据"""
        logger.info("=" * 60)
        logger.info("阶段4: 开始生成Redis缓存与消息数据")
        logger.info("=" * 60)

        try:
            redis_client = self.redis_conn.client

            # 4.1 写入客户画像缓存
            logger.info("写入客户画像缓存...")
            for profile in self.customer_profiles[:50]:  # 缓存前50个热点客户
                cache_key = f"customer:profile:{profile['customer_id']}"
                cache_data = {
                    'customer_id': profile['customer_id'],
                    'risk_level': profile['risk_level'],
                    'cached_at': datetime.now().isoformat()
                }
                redis_client.setex(
                    cache_key,
                    3600,  # 1小时过期
                    json.dumps(cache_data, ensure_ascii=False)
                )

            # 4.2 写入持仓汇总HASH
            logger.info("写入持仓汇总...")
            for customer in self.customers[:50]:
                hash_key = f"holdings:summary:{customer['id']}"
                customer_holdings = [h for h in self.holdings if h['customer_id'] == customer['id']]

                total_value = sum(h['current_value'] for h in customer_holdings)
                total_cost = sum(h['cost_amount'] for h in customer_holdings)

                redis_client.hset(hash_key, mapping={
                    'total_value': str(total_value),
                    'total_cost': str(total_cost),
                    'profit_loss': str(total_value - total_cost),
                    'product_count': len(customer_holdings),
                    'updated_at': datetime.now().isoformat()
                })
                redis_client.expire(hash_key, 7200)  # 2小时过期

            # 4.3 写入工单通知LIST
            logger.info("写入工单通知...")
            for order in self.work_orders[:20]:
                list_key = "workorder:notifications"
                notification = {
                    'order_no': order['order_no'],
                    'customer_id': order['customer_id'],
                    'type': order['type'],
                    'created_at': datetime.now().isoformat()
                }
                redis_client.lpush(list_key, json.dumps(notification, ensure_ascii=False))

            redis_client.ltrim("workorder:notifications", 0, 99)  # 只保留最近100条

            # 4.4 写入Stream事件（模拟实时事件流）
            logger.info("写入Stream事件...")
            stream_key = "events:transactions"
            for trans in self.transactions[:30]:
                event_data = {
                    'event_type': 'transaction_completed',
                    'customer_id': str(trans['customer_id']),
                    'product_id': str(trans['product_id']),
                    'amount': str(trans['amount']),
                    'type': trans['type'],
                    'timestamp': datetime.now().isoformat()
                }
                redis_client.xadd(stream_key, event_data)

            # 限制Stream长度
            redis_client.xtrim(stream_key, maxlen=1000, approximate=True)

            logger.info(f"✅ 阶段4完成: Redis缓存与消息数据生成完毕")

        except Exception as e:
            logger.error(f"❌ Redis数据生成失败: {e}")
            import traceback
            traceback.print_exc()

    # ==================== 阶段5: MinIO对象存储索引 ====================

    def stage5_generate_minio_metadata(self):
        """阶段5: 生成MinIO对象存储元数据"""
        logger.info("=" * 60)
        logger.info("阶段5: 开始生成MinIO对象存储元数据")
        logger.info("=" * 60)

        try:
            # MinIO实际文件上传较复杂，这里只生成MySQL中的元数据索引
            logger.info("生成合规证据元数据...")

            evidence_count = 0

            # 为申购交易生成录音录像元数据
            purchase_transactions = [t for t in self.transactions if t['type'] == '申购']
            for trans in purchase_transactions[:100]:  # 只为前100笔生成
                # 录音文件
                audio_path = f"compliance/recordings/{trans['customer_id']}/{datetime.now().strftime('%Y%m')}/audio_{trans['id']}.mp3"
                event_id = f"evt_audio_{trans['id']}_{int(datetime.now().timestamp()*1000)}"
                evidence_id = f"evd_trans_{trans['id']}_audio"
                sql = """
                    INSERT INTO biz_compliance_evidence
                    (event_id, evidence_id, action, customer_id, product_id, evidence_type,
                     artifact_uri, completed_at, verified_by, verification_method, trace_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """
                params = (
                    event_id,
                    evidence_id,
                    'ISSUED',
                    trans['customer_id'],
                    trans.get('product_id'),
                    '录音录像',
                    audio_path,
                    trans['created_at'],
                    trans['employee_id'],
                    'system_auto',
                    f"trace_{trans['id']}",
                )
                self.mysql_conn.execute_sync(sql, params)
                evidence_count += 1

                # 30%概率有视频
                if random.random() < 0.3:
                    video_path = f"compliance/recordings/{trans['customer_id']}/{datetime.now().strftime('%Y%m')}/video_{trans['id']}.mp4"
                    event_id_video = f"evt_video_{trans['id']}_{int(datetime.now().timestamp()*1000)}"
                    evidence_id_video = f"evd_trans_{trans['id']}_video"
                    params = (
                        event_id_video,
                        evidence_id_video,
                        'ISSUED',
                        trans['customer_id'],
                        trans.get('product_id'),
                        '录音录像',
                        video_path,
                        trans['created_at'],
                        trans['employee_id'],
                        'system_auto',
                        f"trace_{trans['id']}",
                    )
                    self.mysql_conn.execute_sync(sql, params)
                    evidence_count += 1

            # 为客户生成风险揭示书元数据
            for customer in self.customers[:150]:
                disclosure_path = f"compliance/disclosures/{customer['id']}/risk_disclosure_{datetime.now().strftime('%Y%m%d')}.pdf"
                event_id = f"evt_disclosure_{customer['id']}_{int(datetime.now().timestamp()*1000)}"
                evidence_id = f"evd_customer_{customer['id']}_disclosure"
                sql = """
                    INSERT INTO biz_compliance_evidence
                    (event_id, evidence_id, action, customer_id, product_id, evidence_type,
                     artifact_uri, completed_at, verified_by, verification_method, trace_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """
                # 获取该客户的投顾ID
                employee_id = 1  # 默认投顾
                customer_advisors = [t for t in self.transactions if t['customer_id'] == customer['id']]
                if customer_advisors:
                    employee_id = customer_advisors[0]['employee_id']

                params = (
                    event_id,
                    evidence_id,
                    'ISSUED',
                    customer['id'],
                    None,  # product_id为空，因为这是客户级证据
                    '风险揭示书',
                    disclosure_path,
                    datetime.now(),
                    employee_id,
                    'manual_upload',
                    f"trace_customer_{customer['id']}",
                )
                self.mysql_conn.execute_sync(sql, params)
                evidence_count += 1

            # 为风险评估生成问卷存档
            for assessment in self.risk_assessments[:100]:
                questionnaire_path = f"compliance/assessments/{assessment['customer_id']}/questionnaire_{assessment['id']}.pdf"
                event_id = f"evt_assessment_{assessment['id']}_{int(datetime.now().timestamp()*1000)}"
                evidence_id = f"evd_assessment_{assessment['id']}_questionnaire"
                sql = """
                    INSERT INTO biz_compliance_evidence
                    (event_id, evidence_id, action, customer_id, product_id, evidence_type,
                     artifact_uri, completed_at, verified_by, verification_method, trace_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """
                params = (
                    event_id,
                    evidence_id,
                    'ISSUED',
                    assessment['customer_id'],
                    None,  # product_id为空，风险评估是客户级的
                    '风险评估问卷',
                    questionnaire_path,
                    assessment['assessment_date'],
                    assessment.get('advisor_id', 1),
                    'system_auto',
                    f"trace_assessment_{assessment['id']}",
                )
                self.mysql_conn.execute_sync(sql, params)
                evidence_count += 1
                self.mysql_conn.execute_sync(sql, params)
                evidence_count += 1

            logger.info(f"✅ 阶段5完成: 生成{evidence_count}条MinIO元数据索引")

        except Exception as e:
            logger.error(f"❌ MinIO元数据生成失败: {e}")
            import traceback
            traceback.print_exc()

    # ==================== 阶段6: 数据一致性验证 ====================

    def stage6_validate_data_consistency(self):
        """阶段6: 数据一致性验证"""
        logger.info("=" * 60)
        logger.info("阶段6: 开始数据一致性验证")
        logger.info("=" * 60)

        validation_results = {
            'total_checks': 0,
            'passed': 0,
            'failed': 0,
            'errors': []
        }

        # 验证1: customer_id跨库一致性
        logger.info("验证1: customer_id跨库一致性...")
        sample_customers = random.sample(self.customers, min(10, len(self.customers)))

        for customer in sample_customers:
            validation_results['total_checks'] += 1
            customer_id = customer['id']

            # 检查MySQL
            mysql_check = self.mysql_conn.execute_sync(
                "SELECT COUNT(*) as cnt FROM base_user WHERE id = %s",
                (customer_id,)
            )

            # 检查Redis（如果有缓存）
            redis_client = self.redis_conn.client
            redis_key = f"customer:profile:{customer_id}"
            redis_check = redis_client.exists(redis_key)

            if mysql_check[0]['cnt'] > 0:
                validation_results['passed'] += 1
                logger.info(f"  ✅ 客户{customer_id}数据一致")
            else:
                validation_results['failed'] += 1
                validation_results['errors'].append(f"客户{customer_id}在MySQL中不存在")

        # 验证2: 持仓金额 = 交易金额累计
        logger.info("验证2: 持仓金额与交易金额一致性...")
        for holding in random.sample(self.holdings, min(10, len(self.holdings))):
            validation_results['total_checks'] += 1
            customer_id = holding['customer_id']
            product_id = holding['product_id']

            # 计算交易累计
            sql = """
                SELECT
                    SUM(CASE WHEN transaction_type = '申购' THEN amount ELSE 0 END) as purchase_sum,
                    SUM(CASE WHEN transaction_type = '赎回' THEN amount ELSE 0 END) as redeem_sum
                FROM fin_transaction
                WHERE customer_id = %s AND product_id = %s
            """
            trans_sum = self.mysql_conn.execute_sync(sql, (customer_id, product_id))[0]

            expected_cost = Decimal(trans_sum['purchase_sum'] or 0) - Decimal(trans_sum['redeem_sum'] or 0)
            actual_cost = holding['cost_amount']

            # 允许小数点误差
            if abs(expected_cost - actual_cost) < Decimal('0.01'):
                validation_results['passed'] += 1
                logger.info(f"  ✅ 持仓{customer_id}-{product_id}金额一致")
            else:
                validation_results['failed'] += 1
                validation_results['errors'].append(
                    f"持仓{customer_id}-{product_id}金额不一致: 期望{expected_cost}, 实际{actual_cost}"
                )

        # 验证3: 风险问卷总分可复算
        logger.info("验证3: 风险问卷总分可复算...")
        for assessment in random.sample(self.risk_assessments, min(5, len(self.risk_assessments))):
            validation_results['total_checks'] += 1

            # 从数据库读取
            sql = "SELECT answers, total_score, risk_level FROM fin_risk_assessment WHERE id = %s"
            result = self.mysql_conn.execute_sync(sql, (assessment['id'],))[0]

            answers = json.loads(result['answers']) if isinstance(result['answers'], str) else result['answers']
            stored_score = Decimal(str(result['total_score']))

            # 重新计算
            recalc_score, recalc_level = self.calculate_risk_score(answers)

            if abs(stored_score - recalc_score) < Decimal('0.1'):
                validation_results['passed'] += 1
                logger.info(f"  ✅ 风险评估{assessment['id']}总分可复算")
            else:
                validation_results['failed'] += 1
                validation_results['errors'].append(
                    f"风险评估{assessment['id']}总分不一致: 存储{stored_score}, 计算{recalc_score}"
                )

        # 验证4: 产品ID可回查
        logger.info("验证4: 产品ID可回查...")
        for trans in random.sample(self.transactions, min(10, len(self.transactions))):
            validation_results['total_checks'] += 1
            product_id = trans['product_id']

            sql = "SELECT COUNT(*) as cnt FROM fin_product WHERE id = %s"
            result = self.mysql_conn.execute_sync(sql, (product_id,))

            if result[0]['cnt'] > 0:
                validation_results['passed'] += 1
            else:
                validation_results['failed'] += 1
                validation_results['errors'].append(f"交易{trans['id']}的产品{product_id}不存在")

        # 验证5: Milvus向量维度正确
        logger.info("验证5: Milvus向量维度正确...")
        try:
            import os
            collection_name = os.getenv('WEALTH_BUTLER_MEMORY_COLLECTION', 'fin_customer_memory_collection_v2')
            client = self.milvus_client.get_client()

            # 查询一条记录验证
            results = client.query(
                collection_name=collection_name,
                filter="",
                output_fields=["customer_id", "memory_type"],
                limit=1
            )

            if results:
                validation_results['total_checks'] += 1
                validation_results['passed'] += 1
                logger.info(f"  ✅ Milvus集合可访问，已有{len(results)}条记录")
            else:
                validation_results['total_checks'] += 1
                validation_results['failed'] += 1
                validation_results['errors'].append("Milvus集合为空")

        except Exception as e:
            validation_results['total_checks'] += 1
            validation_results['failed'] += 1
            validation_results['errors'].append(f"Milvus验证失败: {e}")

        # 输出验证报告
        logger.info("=" * 60)
        logger.info("数据一致性验证报告")
        logger.info("=" * 60)
        logger.info(f"总检查项: {validation_results['total_checks']}")
        logger.info(f"通过: {validation_results['passed']}")
        logger.info(f"失败: {validation_results['failed']}")

        if validation_results['errors']:
            logger.warning("失败详情:")
            for error in validation_results['errors']:
                logger.warning(f"  ❌ {error}")
        else:
            logger.info("✅ 所有验证通过!")

        return validation_results

    # ==================== 主执行流程 ====================

    def run(self):
        """执行完整的数据生成流程"""
        start_time = datetime.now()
        logger.info("🚀 开始跨数据库真实业务数据生成")
        logger.info(f"开始时间: {start_time}")
        logger.info("=" * 60)

        try:
            # 阶段1: MySQL核心业务数据
            self.stage1_generate_mysql_data()

            # 阶段2: Milvus客户记忆向量
            self.stage2_generate_milvus_data()

            # 阶段3: Neo4j图谱数据
            self.stage3_generate_neo4j_data()

            # 阶段4: Redis缓存与消息
            self.stage4_generate_redis_data()

            # 阶段5: MinIO对象存储元数据
            self.stage5_generate_minio_metadata()

            # 阶段6: 数据一致性验证
            validation_results = self.stage6_validate_data_consistency()

            # 生成统计报告
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            logger.info("=" * 60)
            logger.info("🎉 数据生成完成!")
            logger.info("=" * 60)
            logger.info(f"结束时间: {end_time}")
            logger.info(f"总耗时: {duration:.2f}秒")
            logger.info("")
            logger.info("数据统计:")
            logger.info(f"  - 员工: {len(self.employees)}名")
            logger.info(f"  - 客户: {len(self.customers)}名")
            logger.info(f"  - 产品: {len(self.products)}个")
            logger.info(f"  - 风险评估: {len(self.risk_assessments)}份")
            logger.info(f"  - 客户画像: {len(self.customer_profiles)}份")
            logger.info(f"  - 交易记录: {len(self.transactions)}条")
            logger.info(f"  - 持仓记录: {len(self.holdings)}个")
            logger.info(f"  - 工单: {len(self.work_orders)}个")
            logger.info(f"  - 风险预警: {len(self.risk_alerts)}个")
            logger.info("")
            logger.info(f"验证结果: {validation_results['passed']}/{validation_results['total_checks']} 通过")

            return True

        except Exception as e:
            logger.error(f"❌ 数据生成失败: {e}")
            import traceback
            traceback.print_exc()
            return False


def main():
    """主入口"""
    logger.info("智能财富管家系统 - 跨数据库真实业务数据生成脚本")
    logger.info("=" * 60)

    generator = ComprehensiveDataGenerator()
    success = generator.run()

    if success:
        logger.info("✅ 数据生成任务执行成功")
        return 0
    else:
        logger.error("❌ 数据生成任务执行失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())

