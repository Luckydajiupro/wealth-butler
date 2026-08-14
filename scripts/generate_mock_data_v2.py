"""
Mock数据生成脚本 V2 - 财富管家系统
基于公司真实产品手册生成150个客户及配套数据
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
MIN_TRANSACTIONS_PER_CUSTOMER = 3   # 每个客户最少交易数
MAX_TRANSACTIONS_PER_CUSTOMER = 15  # 每个客户最多交易数

# ============================================================
# 公司真实产品数据（来自个人理财产品手册）
# ============================================================
REAL_PRODUCTS = [
    # 基金类产品
    {
        'product_code': 'HB001',
        'product_name': 'XX货币市场基金',
        'product_type': '公募基金',
        'risk_level': 'R1',
        'min_investment': 1,
        'redemption_period_days': 1,
        'nav': 1.0000,
        'industry': '货币市场',
        'fund_manager': '王某',
        'status': '在售',
        'description': '货币市场基金，七日年化约2.0%，T+0快速赎回，适合C1保守型投资者'
    },
    {
        'product_code': 'ZQ001',
        'product_name': 'XX稳健增利债券A',
        'product_type': '公募基金',
        'risk_level': 'R2',
        'min_investment': 1000,
        'redemption_period_days': 1,
        'nav': 1.2235,
        'industry': '固定收益',
        'fund_manager': '李某',
        'status': '在售',
        'description': '纯债债券型基金，近一年收益4.52%，适合C2稳健型投资者'
    },
    {
        'product_code': 'HH001',
        'product_name': 'XX平衡优选混合',
        'product_type': '公募基金',
        'risk_level': 'R3',
        'min_investment': 5000,
        'redemption_period_days': 2,
        'nav': 1.6842,
        'industry': '混合型',
        'fund_manager': '张某',
        'status': '在售',
        'description': '偏股混合型，股票仓位50-70%，近一年收益8.23%，适合C3平衡型投资者'
    },
    {
        'product_code': 'GP001',
        'product_name': 'XX科技创新股票',
        'product_type': '公募基金',
        'risk_level': 'R4',
        'min_investment': 10000,
        'redemption_period_days': 2,
        'nav': 1.5238,
        'industry': '科技创新',
        'fund_manager': '陈某',
        'status': '在售',
        'description': '股票型基金，聚焦AI/半导体/新能源，近一年收益15.62%，适合C4进取型投资者'
    },
    {
        'product_code': 'QDII001',
        'product_name': 'XX全球精选QDII',
        'product_type': '公募基金',
        'risk_level': 'R4',
        'min_investment': 50000,
        'redemption_period_days': 10,
        'nav': 1.3862,
        'industry': '全球配置',
        'fund_manager': '刘某',
        'status': '在售',
        'description': 'QDII股票型，全球资产配置，近一年收益12.85%，适合C4进取型投资者'
    },
    {
        'product_code': 'GP002',
        'product_name': 'XX红利价值股票',
        'product_type': '公募基金',
        'risk_level': 'R3',
        'min_investment': 5000,
        'redemption_period_days': 2,
        'nav': 1.7852,
        'industry': '价值投资',
        'fund_manager': '赵某',
        'status': '在售',
        'description': '高股息价值股票基金，近一年收益6.85%，适合C3平衡型投资者'
    },
    # 银行理财产品
    {
        'product_code': 'LC001',
        'product_name': 'XX季季盈90天',
        'product_type': '银行理财',
        'risk_level': 'R2',
        'min_investment': 10000,
        'redemption_period_days': 90,
        'nav': 1.0000,
        'industry': '固定收益',
        'fund_manager': 'XX理财子公司',
        'status': '在售',
        'description': '90天封闭期理财，业绩基准4.0%，适合C2稳健型投资者'
    },
    {
        'product_code': 'LC002',
        'product_name': 'XX年年盈365天',
        'product_type': '银行理财',
        'risk_level': 'R3',
        'min_investment': 50000,
        'redemption_period_days': 365,
        'nav': 1.0000,
        'industry': '固定收益',
        'fund_manager': 'XX理财子公司',
        'status': '在售',
        'description': '365天封闭期理财，业绩基准4.8%，含少量权益仓位，适合C3平衡型'
    },
    {
        'product_code': 'JG001',
        'product_name': 'XX结构性存款91天',
        'product_type': '结构性存款',
        'risk_level': 'R2',
        'min_investment': 200000,
        'redemption_period_days': 91,
        'nav': 1.0000,
        'industry': '存款',
        'fund_manager': 'XX银行',
        'status': '在售',
        'description': '结构性存款，保底1.45%，最高4.2%，挂钩黄金/指数，适合C2稳健型'
    },
    # 保险产品
    {
        'product_code': 'BX001',
        'product_name': 'XX福享年金保险',
        'product_type': '保险',
        'risk_level': 'R2',
        'min_investment': 10000,
        'redemption_period_days': 3650,  # 10年
        'nav': 1.0000,
        'industry': '人寿保险',
        'fund_manager': 'XX人寿',
        'status': '在售',
        'description': '年金险+分红，预定利率3.0%，第5年起领取年金，适合养老规划'
    },
    {
        'product_code': 'BX002',
        'product_name': 'XX传世增额终身寿险',
        'product_type': '保险',
        'risk_level': 'R2',
        'min_investment': 10000,
        'redemption_period_days': 3650,  # 10年
        'nav': 1.0000,
        'industry': '人寿保险',
        'fund_manager': 'XX人寿',
        'status': '在售',
        'description': '增额终身寿，每年3.0%复利递增，适合财富传承和长期储蓄'
    }
]

# ============================================================
# 基础数据池（客户信息生成）
# ============================================================

SURNAMES = [
    "王", "李", "张", "刘", "陈", "杨", "黄", "赵", "周", "吴",
    "徐", "孙", "朱", "马", "胡", "郭", "林", "何", "高", "梁",
    "郑", "罗", "宋", "谢", "唐", "韩", "曹", "许", "邓", "萧",
    "冯", "曾", "程", "蔡", "彭", "潘", "袁", "于", "董", "余",
    "苏", "叶", "吕", "魏", "蒋", "田", "杜", "丁", "沈", "姜"
]

NAME_CHARS = [
    "伟", "芳", "娜", "秀", "敏", "静", "丽", "强", "磊", "军",
    "洋", "勇", "艳", "杰", "涛", "明", "超", "秀英", "霞", "平",
    "刚", "桂英", "建华", "文", "华", "金凤", "玉兰", "春梅", "雪", "婷",
    "宇", "浩", "欣", "悦", "晨", "睿", "瑞", "博", "宸", "轩"
]

CITIES = [
    "北京", "上海", "深圳", "广州", "杭州", "成都", "重庆", "南京",
    "苏州", "武汉", "西安", "天津", "青岛", "长沙", "宁波", "郑州"
]

# ============================================================
# 数据生成函数
# ============================================================

def generate_chinese_name() -> str:
    """生成真实的中文姓名"""
    surname = random.choice(SURNAMES)
    if random.random() < 0.3:
        return surname + random.choice(NAME_CHARS)
    else:
        return surname + random.choice(NAME_CHARS) + random.choice(NAME_CHARS)


def generate_phone() -> str:
    """生成手机号"""
    prefixes = ['130', '131', '133', '135', '136', '137', '138', '139',
                '150', '151', '152', '153', '155', '156', '158', '159',
                '180', '181', '182', '186', '187', '188', '189']
    return random.choice(prefixes) + ''.join([str(random.randint(0, 9)) for _ in range(8)])


def generate_email(idx: int) -> str:
    """生成邮箱"""
    domains = ['qq.com', '163.com', '126.com', 'sina.com', 'gmail.com']
    return f"customer{idx:04d}@{random.choice(domains)}"


def generate_id_card() -> str:
    """生成身份证号（模拟）"""
    area_code = random.choice(['110101', '310101', '440301', '440305', '330100', '510100'])
    birth_year = random.randint(1959, 1999)
    birth_month = random.randint(1, 12)
    birth_day = random.randint(1, 28)
    birth_date = f"{birth_year}{birth_month:02d}{birth_day:02d}"
    seq = random.randint(100, 999)
    check_code = random.choice('0123456789X')
    return f"{area_code}{birth_date}{seq}{check_code}"


def generate_users(count: int) -> List[Dict[str, Any]]:
    """生成用户数据"""
    users = []
    for i in range(1, count + 1):
        name = generate_chinese_name()
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
            'email': generate_email(i),
            'phone': generate_phone(),
            'password_hash': '$2b$12$abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG',
            'source_module': 'WealthButler',
            'status': 'active',
            'user_type': 'CUSTOMER',
            'customer_level': customer_level,
            'extra_data': json.dumps({
                'real_name': name,
                'id_card': generate_id_card(),
                'city': random.choice(CITIES),
                'occupation': random.choice(['企业高管', '公务员', '教师', '医生', '工程师',
                                            '自由职业', '企业主', '金融从业者', '律师', '其他'])
            }, ensure_ascii=False)
        })
    return users


def generate_customer_profiles(user_count: int) -> List[Dict[str, Any]]:
    """生成客户画像数据"""
    profiles = []
    for customer_id in range(1, user_count + 1):
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

        dim1 = round(random.uniform(base_score * 0.2, 25), 2)
        dim2 = round(random.uniform(base_score * 0.2, 25), 2)
        dim3 = round(random.uniform(base_score * 0.25, 30), 2)
        dim4 = round(random.uniform(base_score * 0.15, 20), 2)
        total_score = round(dim1 + dim2 + dim3 + dim4, 2)

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
                f"客户最近{random.randint(3, 6)}个月关注{random.choice(['科技', '消费', '医药', '新能源'])}主题",
                f"倾向于{random.choice(['长期持有', '短期波段', '定投'])}策略"
            ], ensure_ascii=False),
            'confidence_score': round(random.uniform(0.7, 0.95), 3),
            'updated_reason': random.choice(['定期', '事件', '行为'])
        })
    return profiles


def generate_transactions_and_holdings(users: List[Dict], products: List[Dict]) -> tuple:
    """生成交易和持仓数据"""
    transactions = []
    holdings_dict = {}
    transaction_id = 1

    available_products = [p for p in products if p['status'] == '在售']

    for user in users:
        customer_id = user['id']
        transaction_count = random.randint(MIN_TRANSACTIONS_PER_CUSTOMER, MAX_TRANSACTIONS_PER_CUSTOMER)

        for _ in range(transaction_count):
            product = random.choice(available_products)
            product_id = product['id']
            transaction_type = random.choices(
                ['申购', '赎回', '分红', '定投'],
                weights=[0.50, 0.30, 0.10, 0.10]
            )[0]

            transaction_time = datetime.now() - timedelta(
                days=random.randint(0, 180),
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59)
            )

            if transaction_type in ['申购', '定投']:
                amount = round(random.uniform(product['min_investment'], product['min_investment'] * 10), 2)
                shares = round(amount / product['nav'], 4)
                fee = round(amount * random.uniform(0.001, 0.015), 2)
            else:
                amount = round(random.uniform(1000, 100000), 2)
                shares = round(amount / product['nav'], 4)
                fee = round(amount * random.uniform(0.001, 0.005), 2)

            channel = random.choice(['APP', '网银', '柜台', '电话'])
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
                'payer_account_name': None,
                'device_fingerprint': device_fingerprint,
                'channel': channel,
                'status': '成交',
                'transaction_time': transaction_time.strftime('%Y-%m-%d %H:%M:%S')
            })

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

    holdings = []
    product_map = {p['id']: p for p in products}
    for key, holding_data in holdings_dict.items():
        if holding_data['shares'] > 0:
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
        return "'" + str(value).replace("'", "\\'").replace("\\", "\\\\") + "'"


def generate_insert_sql(table_name: str, data_list: List[Dict]) -> List[str]:
    """生成批量INSERT语句"""
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


# ============================================================
# 主函数
# ============================================================

def main():
    print("="*60)
    print("Mock数据生成 V2 - 基于真实产品手册")
    print("="*60)

    print(f"\n生成配置：")
    print(f"  - 客户数量: {CUSTOMER_COUNT}")
    print(f"  - 真实产品数量: {len(REAL_PRODUCTS)}")
    print(f"  - 预计交易数: {CUSTOMER_COUNT * 8} 左右")

    print("\n开始生成数据...")

    # 1. 准备产品数据（添加id和nav_date）
    products = []
    for i, p in enumerate(REAL_PRODUCTS, 1):
        product = p.copy()
        product['id'] = i
        product['nav_date'] = (datetime.now() - timedelta(days=random.randint(0, 3))).strftime('%Y-%m-%d')
        products.append(product)

    # 2. 生成用户
    print("  [1/4] 生成用户数据...")
    users = generate_users(CUSTOMER_COUNT)

    # 3. 生成客户画像
    print("  [2/4] 生成客户画像数据...")
    profiles = generate_customer_profiles(CUSTOMER_COUNT)

    # 4. 生成交易和持仓
    print("  [3/4] 生成交易和持仓数据...")
    transactions, holdings = generate_transactions_and_holdings(users, products)

    # 5. 生成SQL文件
    print("  [4/4] 生成SQL脚本...")

    with open('scripts/mock_data_seed.sql', 'w', encoding='utf-8') as f:
        f.write("-- ============================================================\n")
        f.write("-- 财富管家系统 Mock数据种子脚本 V2（基于真实产品手册）\n")
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
        f.write(f"-- 3. 真实产品数据 ({len(products)}条 - 来自公司产品手册)\n")
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
    print(f"  - 真实产品: {len(products)} 条")
    print(f"  - 交易流水: {len(transactions)} 条")
    print(f"  - 持仓: {len(holdings)} 条")
    print(f"\nSQL文件已生成: scripts/mock_data_seed.sql")

    # 输出数据样本供审核
    print("\n" + "="*60)
    print("数据样本预览（供审核）")
    print("="*60)

    print("\n【真实产品样本】全部11款产品：")
    for product in products:
        print(f"  {product['product_code']}: {product['product_name']}")
        print(f"    类型:{product['product_type']}, 风险:{product['risk_level']}, 净值:{product['nav']}, 起投:{product['min_investment']}")

    print("\n【用户样本】前3条：")
    for user in users[:3]:
        extra = json.loads(user['extra_data'])
        print(f"  ID:{user['id']}, 姓名:{extra['real_name']}, 等级:{user['customer_level']}, 城市:{extra['city']}")

    print("\n【交易样本】前5条：")
    for txn in transactions[:5]:
        prod = next((p for p in products if p['id'] == txn['product_id']), None)
        if prod:
            print(f"  客户{txn['customer_id']} {txn['transaction_type']} {prod['product_name']}, "
                  f"金额:{txn['amount']}, 时间:{txn['transaction_time']}")


if __name__ == "__main__":
    main()
