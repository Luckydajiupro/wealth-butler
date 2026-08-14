"""
补充数据生成脚本 - 员工、工单、风控、会话等
"""
import random
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any

SURNAMES = ["王", "李", "张", "刘", "陈", "杨", "黄", "赵", "周", "吴",
            "徐", "孙", "朱", "马", "胡", "郭", "林", "何", "高", "梁"]
NAME_CHARS = ["伟", "芳", "娜", "秀", "敏", "静", "丽", "强", "磊", "军",
              "洋", "勇", "艳", "杰", "涛", "明", "超", "华", "霞", "平"]
CITIES = ["北京", "上海", "深圳", "广州", "杭州", "成都", "重庆", "南京"]

def generate_chinese_name():
    surname = random.choice(SURNAMES)
    return surname + random.choice(NAME_CHARS) + (random.choice(NAME_CHARS) if random.random() > 0.3 else "")

def generate_phone():
    prefixes = ['130', '131', '133', '135', '136', '137', '138', '139',
                '150', '151', '152', '153', '186', '187', '188', '189']
    return random.choice(prefixes) + ''.join([str(random.randint(0, 9)) for _ in range(8)])

def generate_employees(count: int) -> List[Dict]:
    """生成员工数据"""
    employees = []
    roles = ['理财顾问', '风控专员', '客户经理', '业务管理员']
    advisor_levels = ['初级', '中级', '高级']

    for i in range(1, count + 1):
        name = generate_chinese_name()
        role = random.choice(roles)

        employees.append({
            'id': 150 + i,  # 从151开始，避免与客户ID冲突
            'username': f"employee{i:03d}",
            'email': f"employee{i:03d}@xxtech.com",
            'phone': generate_phone(),
            'password_hash': '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG',
            'source_module': 'WealthButler',
            'status': 'active',
            'user_type': 'EMPLOYEE',
            'employee_role': role,
            'advisor_level': random.choice(advisor_levels) if role == '理财顾问' else None,
            'extra_data': json.dumps({
                'real_name': name,
                'city': random.choice(CITIES),
                'department': {'理财顾问': '投顾部', '风控专员': '风控部', '客户经理': '客服部', '业务管理员': '运营部'}[role]
            }, ensure_ascii=False)
        })

    return employees

def generate_risk_assessments(customer_ids: List[int]) -> List[Dict]:
    """生成风险评估记录"""
    assessments = []

    for customer_id in customer_ids:
        # 每个客户1-2条风险评估记录
        count = random.randint(1, 2)
        for i in range(count):
            assessment_date = datetime.now() - timedelta(days=random.randint(30, 365))
            valid_until = assessment_date + timedelta(days=365)

            # 根据客户画像的风险等级生成评估结果
            risk_level = f"C{random.randint(1, 5)}"

            assessments.append({
                'customer_id': customer_id,
                'assessment_date': assessment_date.strftime('%Y-%m-%d'),
                'risk_level': risk_level,
                'assessment_method': random.choice(['问卷', '人工复核']),
                'score': random.randint(20, 100),
                'valid_until': valid_until.strftime('%Y-%m-%d'),
                'questionnaire_data': json.dumps({
                    'age': random.randint(25, 65),
                    'income_level': random.choice(['低', '中', '高']),
                    'investment_experience': random.choice(['无', '1-3年', '3年以上'])
                }, ensure_ascii=False),
                'assessor_id': random.randint(151, 170),
                'status': 'active' if i == 0 else 'expired'
            })

    return assessments

def generate_risk_alerts() -> List[Dict]:
    """生成风险预警记录"""
    alerts = []
    rule_codes = ['RW-001', 'RW-002', 'RW-003', 'AML-001', 'AML-002']

    # 生成10-20条预警
    for i in range(random.randint(10, 20)):
        customer_id = random.randint(1, 150)
        alert_time = datetime.now() - timedelta(days=random.randint(1, 90))

        alerts.append({
            'customer_id': customer_id,
            'transaction_id': random.randint(1, 1274) if random.random() > 0.3 else None,
            'rule_code': random.choice(rule_codes),
            'alert_level': random.choice(['低', '中', '高']),
            'alert_reason': f"触发{random.choice(rule_codes)}规则：{random.choice(['大额交易', '频繁交易', '异常设备', '可疑对手方'])}",
            'alert_time': alert_time.strftime('%Y-%m-%d %H:%M:%S'),
            'evidence_snapshot': json.dumps({
                'amount': random.randint(10000, 500000),
                'frequency': random.randint(5, 20)
            }, ensure_ascii=False),
            'handler_id': random.randint(151, 170),
            'status': random.choice(['待处理', '处理中', '已处理', '误报']),
            'handle_result': random.choice(['正常交易', '客户解释合理', '继续观察', None]),
            'handled_at': (alert_time + timedelta(days=random.randint(1, 7))).strftime('%Y-%m-%d %H:%M:%S') if random.random() > 0.3 else None
        })

    return alerts

def generate_work_orders() -> List[Dict]:
    """生成工单记录"""
    orders = []
    order_types = ['适当性例外审批', '大额赎回审批', '产品投诉处理', '账户异常处理']

    # 生成20-30个工单
    for i in range(random.randint(20, 30)):
        customer_id = random.randint(1, 150)
        created_at = datetime.now() - timedelta(days=random.randint(1, 180))

        status = random.choice(['待处理', '处理中', '已完成', '已取消'])

        orders.append({
            'customer_id': customer_id,
            'order_type': random.choice(order_types),
            'title': f"客户{customer_id}的{random.choice(order_types)}",
            'description': f"客户申请{random.choice(['超额购买', '紧急赎回', '投诉产品', '修改信息'])}",
            'priority': random.choice(['低', '中', '高']),
            'status': status,
            'creator_id': random.randint(1, 150),
            'handler_id': random.randint(151, 170),
            'created_at': created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': (created_at + timedelta(days=random.randint(0, 30))).strftime('%Y-%m-%d %H:%M:%S'),
            'closed_at': (created_at + timedelta(days=random.randint(1, 30))).strftime('%Y-%m-%d %H:%M:%S') if status == '已完成' else None
        })

    return orders

def generate_conversation_archive() -> List[Dict]:
    """生成会话归档记录"""
    archives = []
    agent_types = ['客服Agent', '投顾Agent', '风控Agent', '数据分析Agent']

    # 生成50-100条会话记录
    for i in range(random.randint(50, 100)):
        customer_id = random.randint(1, 150)
        start_time = datetime.now() - timedelta(days=random.randint(1, 90))

        archives.append({
            'customer_id': customer_id,
            'agent_type': random.choice(agent_types),
            'session_start': start_time.strftime('%Y-%m-%d %H:%M:%S'),
            'session_end': (start_time + timedelta(minutes=random.randint(5, 60))).strftime('%Y-%m-%d %H:%M:%S'),
            'message_count': random.randint(5, 50),
            'summary': f"客户咨询{random.choice(['产品信息', '收益情况', '赎回流程', '风险评估', '账户问题'])}",
            'sentiment_score': round(random.uniform(0.5, 1.0), 2),
            'archived_at': (start_time + timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
        })

    return archives

def generate_knowledge_meta() -> List[Dict]:
    """生成知识库元数据"""
    metas = []
    categories = ['产品说明书', '政策法规', 'FAQ', '操作指南', '话术模板']

    # 生成20-30条知识条目
    for i in range(random.randint(20, 30)):
        created_at = datetime.now() - timedelta(days=random.randint(30, 365))

        metas.append({
            'title': f"{random.choice(['XX货币基金', 'XX债券基金', '适当性管理', '反洗钱', '客户服务'])}相关文档",
            'category': random.choice(categories),
            'file_path': f"/knowledge/{random.choice(categories)}/{i}.pdf",
            'file_size': random.randint(100000, 5000000),
            'file_hash': f"md5_{random.randint(100000, 999999)}",
            'version': f"v{random.randint(1, 5)}.{random.randint(0, 9)}",
            'status': random.choice(['生效中', '已归档']),
            'effective_date': created_at.strftime('%Y-%m-%d'),
            'expire_date': (created_at + timedelta(days=random.randint(365, 1095))).strftime('%Y-%m-%d') if random.random() > 0.5 else None,
            'source': random.choice(['公司内部', '监管机构', '基金公司']),
            'uploader_id': random.randint(151, 170),
            'created_at': created_at.strftime('%Y-%m-%d %H:%M:%S')
        })

    return metas

def format_sql_value(value):
    if value is None:
        return 'NULL'
    elif isinstance(value, (int, float)):
        return str(value)
    elif isinstance(value, bool):
        return '1' if value else '0'
    else:
        return "'" + str(value).replace("'", "\\'").replace("\\", "\\\\") + "'"

def generate_insert_sql(table_name: str, data_list: List[Dict]) -> List[str]:
    if not data_list:
        return []
    sqls = []
    batch_size = 100
    for i in range(0, len(data_list), batch_size):
        batch = data_list[i:i + batch_size]
        columns = list(batch[0].keys())
        sql = f"INSERT INTO `{table_name}` (`{'`, `'.join(columns)}`) VALUES\n"
        values_parts = []
        for row in batch:
            values = [format_sql_value(row[col]) for col in columns]
            values_parts.append(f"({', '.join(values)})")
        sql += ',\n'.join(values_parts) + ';'
        sqls.append(sql)
    return sqls

def main():
    print("="*60)
    print("补充数据生成 - 员工、工单、风控、会话等")
    print("="*60)

    # 获取现有客户ID列表
    customer_ids = list(range(1, 151))

    print("\n生成数据...")
    employees = generate_employees(20)  # 20个员工
    risk_assessments = generate_risk_assessments(customer_ids)
    risk_alerts = generate_risk_alerts()
    work_orders = generate_work_orders()
    conversation_archive = generate_conversation_archive()
    knowledge_meta = generate_knowledge_meta()

    print("\n生成SQL...")
    with open('scripts/supplement_data_seed.sql', 'w', encoding='utf-8') as f:
        f.write("-- ============================================================\n")
        f.write("-- 补充数据种子脚本\n")
        f.write(f"-- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("-- ============================================================\n\n")
        f.write("USE wealth_butler;\nSET FOREIGN_KEY_CHECKS=0;\n\n")

        f.write(f"-- 1. 员工数据 ({len(employees)}条)\n")
        f.write("-- ============================================================\n\n")
        for sql in generate_insert_sql('base_user', employees):
            f.write(sql + "\n\n")

        f.write(f"-- 2. 风险评估记录 ({len(risk_assessments)}条)\n")
        f.write("-- ============================================================\n\n")
        for sql in generate_insert_sql('fin_risk_assessment', risk_assessments):
            f.write(sql + "\n\n")

        f.write(f"-- 3. 风险预警记录 ({len(risk_alerts)}条)\n")
        f.write("-- ============================================================\n\n")
        for sql in generate_insert_sql('fin_risk_alert', risk_alerts):
            f.write(sql + "\n\n")

        f.write(f"-- 4. 工单记录 ({len(work_orders)}条)\n")
        f.write("-- ============================================================\n\n")
        for sql in generate_insert_sql('biz_work_order', work_orders):
            f.write(sql + "\n\n")

        f.write(f"-- 5. 会话归档 ({len(conversation_archive)}条)\n")
        f.write("-- ============================================================\n\n")
        for sql in generate_insert_sql('conversation_archive', conversation_archive):
            f.write(sql + "\n\n")

        f.write(f"-- 6. 知识库元数据 ({len(knowledge_meta)}条)\n")
        f.write("-- ============================================================\n\n")
        for sql in generate_insert_sql('fin_knowledge_meta', knowledge_meta):
            f.write(sql + "\n\n")

        f.write("SET FOREIGN_KEY_CHECKS=1;\n-- 完成\n")

    print(f"\n[完成] 补充数据生成完成")
    print(f"  员工: {len(employees)}")
    print(f"  风险评估: {len(risk_assessments)}")
    print(f"  风险预警: {len(risk_alerts)}")
    print(f"  工单: {len(work_orders)}")
    print(f"  会话归档: {len(conversation_archive)}")
    print(f"  知识库元数据: {len(knowledge_meta)}")
    print(f"\nSQL文件: scripts/supplement_data_seed.sql")

if __name__ == "__main__":
    main()
