"""
Mock数据生成脚本 - 财富管家系统
生成150个客户及配套的产品、交易、持仓等数据
"""
import random
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Any

# ============================================================
# 配置参数
# ============================================================
CUSTOMER_COUNT = 150  # 客户数量
PRODUCT_COUNT = 50    # 产品数量
MIN_TRANSACTIONS_PER_CUSTOMER = 3   # 每个客户最少交易数
MAX_TRANSACTIONS_PER_CUSTOMER = 15  # 每个客户最多交易数

# ============================================================
# 基础数据池
# ============================================================

# 真实的中文姓氏（高频100个）
SURNAMES = [
    "王", "李", "张", "刘", "陈", "杨", "黄", "赵", "周", "吴",
    "徐", "孙", "朱", "马", "胡", "郭", "林", "何", "高", "梁",
    "郑", "罗", "宋", "谢", "唐", "韩", "曹", "许", "邓", "萧",
    "冯", "曾", "程", "蔡", "彭", "潘", "袁", "于", "董", "余",
    "苏", "叶", "吕", "魏", "蒋", "田", "杜", "丁", "沈", "姜",
    "范", "江", "傅", "钟", "卢", "汪", "戴", "崔", "任", "陆",
    "廖", "姚", "方", "金", "邱", "夏", "谭", "韦", "贾", "邹",
    "石", "熊", "孟", "秦", "阎", "薛", "侯", "雷", "白", "龙",
    "段", "郝", "孔", "邵", "史", "毛", "常", "万", "顾", "赖",
    "武", "康", "贺", "严", "尹", "钱", "施", "牛", "洪", "龚"
]

# 真实的中文名字常用字
NAME_CHARS = [
    "伟", "芳", "娜", "秀", "敏", "静", "丽", "强", "磊", "军",
    "洋", "勇", "艳", "杰", "涛", "明", "超", "秀英", "霞", "平",
    "刚", "桂英", "建华", "文", "华", "金凤", "玉兰", "春梅", "雪", "婷",
    "宇", "浩", "欣", "悦", "晨", "睿", "瑞", "博", "宸", "轩",
    "诗", "嘉", "雨", "梓", "涵", "俊", "志", "鹏", "辉", "凯"
]

# 城市列表（一二线城市）
CITIES = [
    "北京", "上海", "深圳", "广州", "杭州", "成都", "重庆", "南京",
    "苏州", "武汉", "西安", "天津", "青岛", "长沙", "宁波", "郑州",
    "无锡", "佛山", "东莞", "厦门"
]

# 行业列表
INDUSTRIES = [
    "信息技术", "金融", "医疗健康", "制造业", "房地产", "教育",
    "零售", "能源", "交通运输", "建筑", "文化娱乐", "餐饮",
    "公共服务", "农业", "通信"
]

# 真实基金公司名称
FUND_COMPANIES = [
    "易方达基金", "华夏基金", "广发基金", "南方基金", "嘉实基金",
    "博时基金", "招商基金", "汇添富基金", "富国基金", "鹏华基金",
    "工银瑞信基金", "建信基金", "中银基金", "交银施罗德", "兴证全球",
    "中欧基金", "国泰基金", "银华基金", "华安基金", "天弘基金"
]

# 真实基金经理名字示例
FUND_MANAGERS = [
    "张坤", "刘彦春", "谢治宇", "朱少醒", "傅鹏博",
    "曹名长", "周蔚文", "董承非", "葛兰", "赵诣",
    "冯明远", "崔莹", "袁芳", "李晓星", "刘格菘",
    "萧楠", "王崇", "归凯", "杨浩", "周应波"
]

# 行业主题
INDUSTRY_THEMES = [
    "科技创新", "消费升级", "医药健康", "新能源", "智能制造",
    "大数据", "人工智能", "5G通信", "新材料", "环保",
    "军工", "半导体", "云计算", "物联网", "生物医药"
]

# ============================================================
# 数据生成函数
# ============================================================

def generate_chinese_name() -> str:
    """生成真实的中文姓名"""
    surname = random.choice(SURNAMES)
    if random.random() < 0.3:  # 30%概率单字名
        return surname + random.choice(NAME_CHARS)
    else:  # 70%概率双字名
        return surname + random.choice(NAME_CHARS) + random.choice(NAME_CHARS)


def generate_phone() -> str:
    """生成手机号"""
    prefixes = ['130', '131', '132', '133', '134', '135', '136', '137', '138', '139',
                '150', '151', '152', '153', '155', '156', '157', '158', '159',
                '180', '181', '182', '183', '184', '185', '186', '187', '188', '189']
    return random.choice(prefixes) + ''.join([str(random.randint(0, 9)) for _ in range(8)])


def generate_email(name: str) -> str:
    """生成邮箱"""
    domains = ['qq.com', '163.com', '126.com', 'sina.com', 'gmail.com', 'outlook.com']
    # 使用拼音或数字组合
    prefixes = [
        ''.join([chr(random.randint(97, 122)) for _ in range(random.randint(5, 10))]),
        f"user{random.randint(10000, 99999)}",
        f"{name.lower()}{random.randint(100, 999)}"
    ]
    return random.choice(prefixes) + '@' + random.choice(domains)


def generate_id_card() -> str:
    """生成身份证号（模拟）"""
    # 地区码
    area_code = random.choice(['110101', '310101', '440301', '440305', '330100', '510100'])
    # 出生日期（25-65岁）
    birth_year = random.randint(1959, 1999)
    birth_month = random.randint(1, 12)
    birth_day = random.randint(1, 28)
    birth_date = f"{birth_year}{birth_month:02d}{birth_day:02d}"
    # 顺序码
    seq = random.randint(100, 999)
    # 校验码（简化为随机）
    check_code = random.choice('0123456789X')
    return f"{area_code}{birth_date}{seq}{check_code}"


def generate_users(count: int) -> List[Dict[str, Any]]:
    """生成用户数据"""
    users = []
    for i in range(1, count + 1):
        name = generate_chinese_name()
        # 客户等级分布：普通60%，金卡25%，白金10%，钻石4%，私行1%
        level_rand = random.random()
        if level_rand < 0.60:
            customer_level = "普通"
        elif level_rand < 0.85:
            customer_level = "金卡"
        elif level_rand < 0.95:
            customer_level = "白金"
        elif level_rand < 0.99:
            customer_level = "钻石"
        else:
            customer_level = "私行"

        users.append({
            'id': i,
            'username': f"customer{i:04d}",
            'email': generate_email(name),
            'phone': generate_phone(),
            'password_hash': '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG',  # 固定mock hash
            'source_module': 'WealthButler',
            'status': 'active',
            'user_type': 'CUSTOMER',
            'customer_level': customer_level,
            'extra_data': json.dumps({
                'real_name': name,
                'id_card': generate_id_card(),
                'city': random.choice(CITIES),
                'occupation': random.choice(['企业高管', '公务员', '教师', '医生', '工程师', '自由职业', '企业主', '金融从业者', '律师', '其他'])
            }, ensure_ascii=False)
        })
    return users


def generate_customer_profiles(user_count: int) -> List[Dict[str, Any]]:
    """生成客户画像数据"""
    profiles = []
    for customer_id in range(1, user_count + 1):
        # 风险等级分布：C1(20%), C2(30%), C3(30%), C4(15%), C5(5%)
        risk_rand = random.random()
        if risk_rand < 0.20:
            risk_level = 'C1'
            base_score = random.uniform(0, 20)
        elif risk_rand < 0.50:
            risk_level = 'C2'
            base_score = random.uniform(20, 40)
        elif risk_rand < 0.80:
            risk_level = 'C3'
            base_score = random.uniform(40, 60)
        elif risk_rand < 0.95:
            risk_level = 'C4'
            base_score = random.uniform(60, 80)
        else:
            risk_level = 'C5'
            base_score = random.uniform(80, 100)

        # 四维度分数
        dim1 = round(random.uniform(base_score * 0.2, 25), 2)
        dim2 = round(random.uniform(base_score * 0.2, 25), 2)
        dim3 = round(random.uniform(base_score * 0.25, 30), 2)
        dim4 = round(random.uniform(base_score * 0.15, 20), 2)
        total_score = round(dim1 + dim2 + dim3 + dim4, 2)

        # FM熔断标记（5%概率命中）
        fm_flags = []
        if random.random() < 0.05:
            fm_flags = [random.choice(['FM-01', 'FM-02', 'FM-03', 'FM-04', 'FM-05'])]

        profiles.append({
            'customer_id': customer_id,
            'risk_level': risk_level,
            'risk_score': total_score,
            'dimension1_score': dim1,
            'dimension2_score': dim2,
            'dimension3_score': dim3,
            'dimension4_score': dim4,
            'fm_flags': json.dumps(fm_flags),
            'asset_allocation': json.dumps({
                '股票型': round(random.uniform(0, 50), 2),
                '债券型': round(random.uniform(10, 40), 2),
                '混合型': round(random.uniform(10, 30), 2),
                '货币型': round(random.uniform(5, 20), 2)
            }, ensure_ascii=False),
            'product_preference': json.dumps({
                '偏好类型': random.choice(['稳健型', '平衡型', '进取型']),
                '关注指标': random.sample(['收益率', '风险等级', '流动性', '历史业绩'], k=2)
            }, ensure_ascii=False),
            'memory_units': json.dumps([
                f"客户最近{random.randint(3, 6)}个月关注{random.choice(INDUSTRY_THEMES)}主题",
                f"倾向于{random.choice(['长期持有', '短期波段', '定投'])}策略"
            ], ensure_ascii=False),
            'confidence_score': round(random.uniform(0.7, 0.95), 3),
            'updated_reason': random.choice(['定期', '事件', '行为'])
        })
    return profiles


def generate_products(count: int) -> List[Dict[str, Any]]:
    """生成产品数据"""
    products = []
    product_types = ['公募基金', '私募基金', '银行理财', '保险', '信托', '结构性存款']
    risk_levels = ['R1', 'R2', 'R3', 'R4', 'R5']

    for i in range(1, count + 1):
        product_type = random.choice(product_types)
        risk_level = random.choice(risk_levels)

        # 根据风险等级设置起投金额
        if risk_level in ['R1', 'R2']:
            min_investment = random.choice([1000, 5000, 10000, 50000])
        elif risk_level == 'R3':
            min_investment = random.choice([10000, 50000, 100000])
        else:
            min_investment = random.choice([100000, 500000, 1000000])

        # 生成产品名称
        company = random.choice(FUND_COMPANIES)
        theme = random.choice(INDUSTRY_THEMES)
        product_name = f"{company}{theme}{'混合' if random.random() > 0.5 else ''}{'A' if random.random() > 0.5 else 'C'}"

        # 净值（0.8-3.5之间）
        nav = round(random.uniform(0.8, 3.5), 4)

        products.append({
            'id': i,
            'product_code': f"P{i:06d}",
            'product_name': product_name,
            'product_type': product_type,
            'risk_level': risk_level,
            'min_investment': min_investment,
            'redemption_period_days': random.choice([1, 2, 3, 7, 15, 30, 90]),
            'nav': nav,
            'nav_date': (datetime.now() - timedelta(days=random.randint(0, 3))).strftime('%Y-%m-%d'),
            'industry': random.choice(INDUSTRIES),
            'fund_manager': random.choice(FUND_MANAGERS),
            'status': random.choices(['在售', '已下架', '封闭期'], weights=[0.85, 0.10, 0.05])[0],
            'description': f"本产品主要投资于{theme}领域，风险等级{risk_level}，适合{['保守', '稳健', '平衡', '进取', '激进'][int(risk_level[1])-1]}型投资者。"
        })
    return products


def generate_transactions_and_holdings(users: List[Dict], products: List[Dict]) -> tuple:
    """生成交易和持仓数据"""
    transactions = []
    holdings_dict = {}  # {(customer_id, product_id): holding_data}
    transaction_id = 1

    # 筛选在售产品
    available_products = [p for p in products if p['status'] == '在售']

    for user in users:
        customer_id = user['id']
        # 每个客户随机交易3-15笔
        transaction_count = random.randint(MIN_TRANSACTIONS_PER_CUSTOMER, MAX_TRANSACTIONS_PER_CUSTOMER)

        # 客户的交易历史（时间范围：过去6个月）
        for _ in range(transaction_count):
            product = random.choice(available_products)
            product_id = product['id']
            transaction_type = random.choices(
                ['申购', '赎回', '分红', '定投'],
                weights=[0.50, 0.30, 0.10, 0.10]
            )[0]

            # 交易时间（过去180天内随机）
            transaction_time = datetime.now() - timedelta(
                days=random.randint(0, 180),
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59)
            )

            # 交易金额
            if transaction_type in ['申购', '定投']:
                amount = round(random.uniform(product['min_investment'], product['min_investment'] * 10), 2)
                shares = round(amount / product['nav'], 4)
                fee = round(amount * random.uniform(0.001, 0.015), 2)
            else:  # 赎回、分红
                amount = round(random.uniform(1000, 100000), 2)
                shares = round(amount / product['nav'], 4)
                fee = round(amount * random.uniform(0.001, 0.005), 2)

            # 渠道
            channel = random.choice(['APP', '网银', '柜台', '电话'])

            # 设备指纹
            device_fingerprint = f"DEV{random.randint(100000, 999999)}"

            transactions.append({
                'id': transaction_id,
                'customer_id': customer_id,
                'product_id': product_id,
                'transaction_type': transaction_type,
                'amount': amount,
                'shares': shares if transaction_type in ['申购', '赎回'] else None,
                'nav': product['nav'],
                'fee': fee,
                'is_cash': random.choice([0, 1]) if random.random() < 0.1 else 0,
                'counterparty_account': f"{random.randint(6200000000000000, 6299999999999999)}" if random.random() < 0.3 else None,
                'counterparty_name': generate_chinese_name() if random.random() < 0.2 else None,
                'counterparty_region': random.choice(CITIES) if random.random() < 0.2 else None,
                'payer_account_name': user['extra_data'] if random.random() < 0.1 else None,
                'device_fingerprint': device_fingerprint,
                'channel': channel,
                'status': '成交',
                'transaction_time': transaction_time.strftime('%Y-%m-%d %H:%M:%S')
            })

            # 更新持仓
            key = (customer_id, product_id)
            if key not in holdings_dict:
                holdings_dict[key] = {
                    'customer_id': customer_id,
                    'product_id': product_id,
                    'shares': 0,
                    'cost_amount': 0
                }

            if transaction_type in ['申购', '定投']:
                holdings_dict[key]['shares'] += shares
                holdings_dict[key]['cost_amount'] += amount
            elif transaction_type == '赎回':
                holdings_dict[key]['shares'] -= shares
                holdings_dict[key]['cost_amount'] -= amount

            transaction_id += 1

    # 计算持仓市值和盈亏
    holdings = []
    product_map = {p['id']: p for p in products}
    for key, holding_data in holdings_dict.items():
        if holding_data['shares'] > 0:  # 只保留有份额的持仓
            product = product_map[holding_data['product_id']]
            current_value = round(holding_data['shares'] * product['nav'], 2)
            profit_loss = round(current_value - holding_data['cost_amount'], 2)
            profit_ratio = round(profit_loss / holding_data['cost_amount'], 4) if holding_data['cost_amount'] > 0 else 0

            holdings.append({
                'customer_id': holding_data['customer_id'],
                'product_id': holding_data['product_id'],
                'shares': round(holding_data['shares'], 4),
                'cost_amount': round(holding_data['cost_amount'], 2),
                'current_value': current_value,
                'profit_loss': profit_loss,
                'profit_ratio': profit_ratio
            })

    return transactions, holdings


def format_sql_value(value) -> str:
    """格式化SQL值"""
    if value is None:
        return 'NULL'
    elif isinstance(value, (int, float, Decimal)):
        return str(value)
    elif isinstance(value, bool):
        return '1' if value else '0'
    else:
        # 转义单引号
        return "'" + str(value).replace("'", "\\'").replace("\\", "\\\\") + "'"


def generate_insert_sql(table_name: str, data_list: List[Dict]) -> List[str]:
    """生成批量INSERT语句"""
    if not data_list:
        return []

    sqls = []
    batch_size = 100  # 每100条一个INSERT

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


# ============================================================
# 主函数
# ============================================================

def main():
    print("="*60)
    print("Mock数据生成 - 财富管家系统")
    print("="*60)

    print(f"\n生成配置：")
    print(f"  - 客户数量: {CUSTOMER_COUNT}")
    print(f"  - 产品数量: {PRODUCT_COUNT}")
    print(f"  - 预计交易数: {CUSTOMER_COUNT * 8} 左右")

    print("\n开始生成数据...")

    # 1. 生成用户
    print("  [1/5] 生成用户数据...")
    users = generate_users(CUSTOMER_COUNT)

    # 2. 生成客户画像
    print("  [2/5] 生成客户画像数据...")
    profiles = generate_customer_profiles(CUSTOMER_COUNT)

    # 3. 生成产品
    print("  [3/5] 生成产品数据...")
    products = generate_products(PRODUCT_COUNT)

    # 4. 生成交易和持仓
    print("  [4/5] 生成交易和持仓数据...")
    transactions, holdings = generate_transactions_and_holdings(users, products)

    # 5. 生成SQL文件
    print("  [5/5] 生成SQL脚本...")

    with open('scripts/mock_data_seed.sql', 'w', encoding='utf-8') as f:
        f.write("-- ============================================================\n")
        f.write("-- 财富管家系统 Mock数据种子脚本\n")
        f.write(f"-- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"-- 客户数: {len(users)}, 产品数: {len(products)}, 交易数: {len(transactions)}, 持仓数: {len(holdings)}\n")
        f.write("-- ============================================================\n\n")

        f.write("USE wealth_butler;\n\n")
        f.write("SET FOREIGN_KEY_CHECKS=0;\n\n")

        # 用户数据
        f.write("-- ============================================================\n")
        f.write(f"-- 1. 用户数据 ({len(users)}条)\n")
        f.write("-- ============================================================\n\n")
        for sql in generate_insert_sql('base_user', users):
            f.write(sql + "\n\n")

        # 客户画像
        f.write("-- ============================================================\n")
        f.write(f"-- 2. 客户画像 ({len(profiles)}条)\n")
        f.write("-- ============================================================\n\n")
        for sql in generate_insert_sql('fin_customer_profile', profiles):
            f.write(sql + "\n\n")

        # 产品
        f.write("-- ============================================================\n")
        f.write(f"-- 3. 产品数据 ({len(products)}条)\n")
        f.write("-- ============================================================\n\n")
        for sql in generate_insert_sql('fin_product', products):
            f.write(sql + "\n\n")

        # 交易
        f.write("-- ============================================================\n")
        f.write(f"-- 4. 交易流水 ({len(transactions)}条)\n")
        f.write("-- ============================================================\n\n")
        for sql in generate_insert_sql('fin_transaction', transactions):
            f.write(sql + "\n\n")

        # 持仓
        f.write("-- ============================================================\n")
        f.write(f"-- 5. 持仓数据 ({len(holdings)}条)\n")
        f.write("-- ============================================================\n\n")
        for sql in generate_insert_sql('fin_holdings', holdings):
            f.write(sql + "\n\n")

        f.write("SET FOREIGN_KEY_CHECKS=1;\n\n")
        f.write("-- 数据导入完成\n")

    print("\n数据生成完成！")
    print(f"\n统计信息：")
    print(f"  - 用户: {len(users)} 条")
    print(f"  - 客户画像: {len(profiles)} 条")
    print(f"  - 产品: {len(products)} 条")
    print(f"  - 交易流水: {len(transactions)} 条")
    print(f"  - 持仓: {len(holdings)} 条")
    print(f"\nSQL文件已生成: scripts/mock_data_seed.sql")
    print(f"文件大小约: {sum([len(users), len(profiles), len(products), len(transactions), len(holdings)]) * 0.5:.1f} KB")

    # 输出数据样本供审核
    print("\n" + "="*60)
    print("数据样本预览（供审核）")
    print("="*60)

    print("\n【用户样本】前3条：")
    for user in users[:3]:
        extra = json.loads(user['extra_data'])
        print(f"  ID:{user['id']}, 用户名:{user['username']}, 姓名:{extra['real_name']}, "
              f"手机:{user['phone']}, 等级:{user['customer_level']}, 城市:{extra['city']}")

    print("\n【客户画像样本】前3条：")
    for profile in profiles[:3]:
        print(f"  客户ID:{profile['customer_id']}, 风险等级:{profile['risk_level']}, "
              f"综合评分:{profile['risk_score']}, FM标记:{profile['fm_flags']}")

    print("\n【产品样本】前5条：")
    for product in products[:5]:
        print(f"  {product['product_code']}: {product['product_name']}, "
              f"类型:{product['product_type']}, 风险:{product['risk_level']}, "
              f"净值:{product['nav']}, 起投:{product['min_investment']}")

    print("\n【交易样本】前5条：")
    for txn in transactions[:5]:
        print(f"  客户{txn['customer_id']} {txn['transaction_type']} 产品{txn['product_id']}, "
              f"金额:{txn['amount']}, 时间:{txn['transaction_time']}")

    print("\n【持仓样本】前5条：")
    for holding in holdings[:5]:
        print(f"  客户{holding['customer_id']} 持有产品{holding['product_id']}, "
              f"份额:{holding['shares']}, 成本:{holding['cost_amount']}, "
              f"市值:{holding['current_value']}, 盈亏:{holding['profit_loss']}")


if __name__ == "__main__":
    main()
