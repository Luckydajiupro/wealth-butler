"""
Mock数据生成脚本 V3 - 财富管家系统
符合真实业务逻辑：
1. 历史交易可含其他公司产品（已赎回）
2. 当前持仓只能是本司11款产品
3. 风险等级均匀分布C1-C5各20%
4. 产品选择匹配客户风险等级
5. 年龄25-65岁合理分布
6. 资产配置分散（2-5只产品）
"""
import random
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Any

# ============================================================
# 配置参数
# ============================================================
CUSTOMER_COUNT = 150

# ============================================================
# 本司真实产品（当前在售，客户可持有）
# ============================================================
OUR_PRODUCTS = [
    {'product_code': 'HB001', 'product_name': 'XX货币市场基金', 'product_type': '公募基金', 'risk_level': 'R1',
     'min_investment': 1, 'redemption_period_days': 1, 'nav': 1.0000, 'industry': '货币市场', 'fund_manager': '王某', 'status': '在售'},
    {'product_code': 'ZQ001', 'product_name': 'XX稳健增利债券A', 'product_type': '公募基金', 'risk_level': 'R2',
     'min_investment': 1000, 'redemption_period_days': 1, 'nav': 1.2235, 'industry': '固定收益', 'fund_manager': '李某', 'status': '在售'},
    {'product_code': 'HH001', 'product_name': 'XX平衡优选混合', 'product_type': '公募基金', 'risk_level': 'R3',
     'min_investment': 5000, 'redemption_period_days': 2, 'nav': 1.6842, 'industry': '混合型', 'fund_manager': '张某', 'status': '在售'},
    {'product_code': 'GP001', 'product_name': 'XX科技创新股票', 'product_type': '公募基金', 'risk_level': 'R4',
     'min_investment': 10000, 'redemption_period_days': 2, 'nav': 1.5238, 'industry': '科技创新', 'fund_manager': '陈某', 'status': '在售'},
    {'product_code': 'QDII001', 'product_name': 'XX全球精选QDII', 'product_type': '公募基金', 'risk_level': 'R4',
     'min_investment': 50000, 'redemption_period_days': 10, 'nav': 1.3862, 'industry': '全球配置', 'fund_manager': '刘某', 'status': '在售'},
    {'product_code': 'GP002', 'product_name': 'XX红利价值股票', 'product_type': '公募基金', 'risk_level': 'R3',
     'min_investment': 5000, 'redemption_period_days': 2, 'nav': 1.7852, 'industry': '价值投资', 'fund_manager': '赵某', 'status': '在售'},
    {'product_code': 'LC001', 'product_name': 'XX季季盈90天', 'product_type': '银行理财', 'risk_level': 'R2',
     'min_investment': 10000, 'redemption_period_days': 90, 'nav': 1.0000, 'industry': '固定收益', 'fund_manager': 'XX理财子', 'status': '在售'},
    {'product_code': 'LC002', 'product_name': 'XX年年盈365天', 'product_type': '银行理财', 'risk_level': 'R3',
     'min_investment': 50000, 'redemption_period_days': 365, 'nav': 1.0000, 'industry': '固定收益', 'fund_manager': 'XX理财子', 'status': '在售'},
    {'product_code': 'JG001', 'product_name': 'XX结构性存款91天', 'product_type': '结构性存款', 'risk_level': 'R2',
     'min_investment': 200000, 'redemption_period_days': 91, 'nav': 1.0000, 'industry': '存款', 'fund_manager': 'XX银行', 'status': '在售'},
    {'product_code': 'BX001', 'product_name': 'XX福享年金保险', 'product_type': '保险', 'risk_level': 'R2',
     'min_investment': 10000, 'redemption_period_days': 3650, 'nav': 1.0000, 'industry': '人寿保险', 'fund_manager': 'XX人寿', 'status': '在售'},
    {'product_code': 'BX002', 'product_name': 'XX传世增额终身寿险', 'product_type': '保险', 'risk_level': 'R2',
     'min_investment': 10000, 'redemption_period_days': 3650, 'nav': 1.0000, 'industry': '人寿保险', 'fund_manager': 'XX人寿', 'status': '在售'},
]

# ============================================================
# 其他公司产品（历史交易用，已赎回无持仓）
# ============================================================
OTHER_PRODUCTS = [
    {'product_code': 'YF001', 'product_name': '易方达蓝筹精选混合', 'product_type': '公募基金', 'risk_level': 'R3',
     'min_investment': 10, 'redemption_period_days': 2, 'nav': 2.1523, 'industry': '混合型', 'fund_manager': '张坤', 'status': '已下架'},
    {'product_code': 'HX001', 'product_name': '华夏回报混合A', 'product_type': '公募基金', 'risk_level': 'R3',
     'min_investment': 10, 'redemption_period_days': 2, 'nav': 1.8934, 'industry': '混合型', 'fund_manager': '刘彦春', 'status': '已下架'},
    {'product_code': 'GF001', 'product_name': '广发稳健增长混合', 'product_type': '公募基金', 'risk_level': 'R3',
     'min_investment': 10, 'redemption_period_days': 2, 'nav': 1.6421, 'industry': '混合型', 'fund_manager': '傅友兴', 'status': '已下架'},
    {'product_code': 'NF001', 'product_name': '南方成长先锋混合', 'product_type': '公募基金', 'risk_level': 'R4',
     'min_investment': 10, 'redemption_period_days': 2, 'nav': 1.3245, 'industry': '混合型', 'fund_manager': '茅炜', 'status': '已下架'},
    {'product_code': 'JS001', 'product_name': '嘉实优质企业混合', 'product_type': '公募基金', 'risk_level': 'R3',
     'min_investment': 10, 'redemption_period_days': 2, 'nav': 1.7823, 'industry': '混合型', 'fund_manager': '谢治宇', 'status': '已下架'},
]

# 风险等级映射：客户C等级 -> 可购买产品R等级
RISK_MATCHING = {
    'C1': ['R1'],
    'C2': ['R1', 'R2'],
    'C3': ['R1', 'R2', 'R3'],
    'C4': ['R1', 'R2', 'R3', 'R4'],
    'C5': ['R1', 'R2', 'R3', 'R4', 'R5']
}

SURNAMES = ["王", "李", "张", "刘", "陈", "杨", "黄", "赵", "周", "吴",
            "徐", "孙", "朱", "马", "胡", "郭", "林", "何", "高", "梁",
            "郑", "罗", "宋", "谢", "唐", "韩", "曹", "许", "邓", "萧"]

NAME_CHARS = ["伟", "芳", "娜", "秀", "敏", "静", "丽", "强", "磊", "军",
              "洋", "勇", "艳", "杰", "涛", "明", "超", "华", "霞", "平",
              "刚", "文", "宇", "浩", "欣", "悦", "晨", "睿", "瑞", "博"]

CITIES = ["北京", "上海", "深圳", "广州", "杭州", "成都", "重庆", "南京",
          "苏州", "武汉", "西安", "天津", "青岛", "长沙", "宁波", "郑州"]

def generate_chinese_name() -> str:
    surname = random.choice(SURNAMES)
    if random.random() < 0.3:
        return surname + random.choice(NAME_CHARS)
    else:
        return surname + random.choice(NAME_CHARS) + random.choice(NAME_CHARS)

def generate_phone() -> str:
    prefixes = ['130', '131', '133', '135', '136', '137', '138', '139',
                '150', '151', '152', '153', '155', '156', '158', '159',
                '180', '181', '182', '186', '187', '188', '189']
    return random.choice(prefixes) + ''.join([str(random.randint(0, 9)) for _ in range(8)])

def generate_email(idx: int) -> str:
    domains = ['qq.com', '163.com', '126.com', 'sina.com', 'gmail.com']
    return f"customer{idx:04d}@{random.choice(domains)}"

def generate_id_card_with_age() -> tuple:
    """生成身份证号并返回年龄（25-65岁）"""
    area_code = random.choice(['110101', '310101', '440301', '440305', '330100', '510100'])
    age = random.randint(25, 65)
    birth_year = datetime.now().year - age
    birth_month = random.randint(1, 12)
    birth_day = random.randint(1, 28)
    birth_date = f"{birth_year}{birth_month:02d}{birth_day:02d}"
    seq = random.randint(100, 999)
    check_code = random.choice('0123456789X')
    id_card = f"{area_code}{birth_date}{seq}{check_code}"
    return id_card, age

def generate_users(count: int) -> List[Dict[str, Any]]:
    """生成用户数据（包含总资产规划，符合客户等级分层）"""
    users = []
    # 确保风险等级均匀分布
    risk_levels = ['C1'] * 30 + ['C2'] * 30 + ['C3'] * 30 + ['C4'] * 30 + ['C5'] * 30
    random.shuffle(risk_levels)

    # 客户等级分布：普通60%、金卡25%、白金10%、钻石4%、私行1%
    customer_levels = (['普通'] * 90 + ['金卡'] * 38 + ['白金'] * 15 +
                       ['钻石'] * 6 + ['私行'] * 1)
    random.shuffle(customer_levels)

    for i in range(1, count + 1):
        name = generate_chinese_name()
        id_card, age = generate_id_card_with_age()
        risk_level = risk_levels[i-1]
        customer_level = customer_levels[i-1]

        # 根据客户等级设定总资产范围（符合财富管理行业标准）
        if customer_level == '普通':
            # 普通客户：10-100万
            total_assets = random.uniform(100000, 1000000)
        elif customer_level == '金卡':
            # 金卡客户：50-300万
            total_assets = random.uniform(500000, 3000000)
        elif customer_level == '白金':
            # 白金客户：200-1000万
            total_assets = random.uniform(2000000, 10000000)
        elif customer_level == '钻石':
            # 钻石客户：800-3000万
            total_assets = random.uniform(8000000, 30000000)
        else:  # 私行
            # 私行客户：3000万-2亿
            total_assets = random.uniform(30000000, 200000000)

        # 资产结构设计（根据年龄和资产规模调整）
        # 年轻人房产比例高，年长者流动资产多
        # 高净值客户流动资产比例更高
        if age < 40:
            real_estate_ratio = random.uniform(0.60, 0.75)  # 年轻人房产比例高
        elif age < 55:
            real_estate_ratio = random.uniform(0.50, 0.65)
        else:
            real_estate_ratio = random.uniform(0.40, 0.60)  # 年长者流动资产多

        # 高净值客户流动资产占比更高
        if customer_level in ['钻石', '私行']:
            real_estate_ratio *= 0.8  # 降低房产比例

        real_estate = total_assets * real_estate_ratio
        liquid_assets = total_assets - real_estate

        # 流动资产中，投入理财产品的比例
        # 客户等级越高，理财投资比例越高
        base_investment_ratio = {
            'C1': random.uniform(0.20, 0.35),
            'C2': random.uniform(0.25, 0.45),
            'C3': random.uniform(0.30, 0.50),
            'C4': random.uniform(0.35, 0.55),
            'C5': random.uniform(0.40, 0.60),
        }[risk_level]

        # 高净值客户投资比例更高
        level_multiplier = {
            '普通': 1.0,
            '金卡': 1.1,
            '白金': 1.2,
            '钻石': 1.3,
            '私行': 1.4
        }[customer_level]

        investment_ratio = min(0.80, base_investment_ratio * level_multiplier)
        investment_amount = liquid_assets * investment_ratio

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
            'risk_level': risk_level,
            'age': age,
            'total_assets': round(total_assets, 2),
            'real_estate': round(real_estate, 2),
            'liquid_assets': round(liquid_assets, 2),
            'investment_amount': round(investment_amount, 2),
            'extra_data': json.dumps({
                'real_name': name,
                'id_card': id_card,
                'city': random.choice(CITIES),
                'age': age,
                'occupation': random.choice(['企业高管', '公务员', '教师', '医生', '工程师',
                                            '自由职业', '企业主', '金融从业者', '律师', '其他']),
                'asset_structure': {
                    'total_assets': round(total_assets, 2),
                    'real_estate': round(real_estate, 2),
                    'liquid_assets': round(liquid_assets, 2),
                    'financial_products': round(investment_amount, 2),
                    'cash_reserve': round(liquid_assets - investment_amount, 2)
                }
            }, ensure_ascii=False)
        })
    return users

def generate_customer_profiles(users: List[Dict]) -> List[Dict[str, Any]]:
    """生成客户画像数据"""
    profiles = []
    for user in users:
        risk_level = user['risk_level']
        total_assets = user['total_assets']
        investment_amount = user['investment_amount']

        # 根据风险等级设定基础分数
        base_scores = {'C1': 10, 'C2': 30, 'C3': 50, 'C4': 70, 'C5': 90}
        base_score = base_scores[risk_level]

        dim1 = round(random.uniform(base_score * 0.2, min(base_score * 0.3, 25)), 2)
        dim2 = round(random.uniform(base_score * 0.2, min(base_score * 0.3, 25)), 2)
        dim3 = round(random.uniform(base_score * 0.25, min(base_score * 0.35, 30)), 2)
        dim4 = round(random.uniform(base_score * 0.15, min(base_score * 0.25, 20)), 2)
        total_score = round(dim1 + dim2 + dim3 + dim4, 2)

        fm_flags = []
        # FM-05: 客户总资产不足以支撑高风险投资（总资产<50万但买R4/R5）
        if total_assets < 500000 and risk_level in ['C4', 'C5']:
            if random.random() < 0.5:
                fm_flags.append('FM-05')
        # 其他FM标记
        elif random.random() < 0.03:
            fm_flags.append(random.choice(['FM-01', 'FM-02', 'FM-03', 'FM-04']))

        profiles.append({
            'customer_id': user['id'],
            'risk_level': risk_level,
            'risk_score': total_score,
            'dimension1_score': dim1,
            'dimension2_score': dim2,
            'dimension3_score': dim3,
            'dimension4_score': dim4,
            'fm_flags': json.dumps(fm_flags),
            'asset_allocation': json.dumps({
                '股票型': round((investment_amount * random.uniform(0, 0.5 if risk_level in ['C4', 'C5'] else 0.3)) / investment_amount * 100, 2) if investment_amount > 0 else 0,
                '债券型': round((investment_amount * random.uniform(0.2 if risk_level == 'C1' else 0.1, 0.5)) / investment_amount * 100, 2) if investment_amount > 0 else 0,
                '混合型': round((investment_amount * random.uniform(0.1, 0.4 if risk_level in ['C3', 'C4'] else 0.2)) / investment_amount * 100, 2) if investment_amount > 0 else 0,
                '货币型': round((investment_amount * random.uniform(0.1 if risk_level in ['C1', 'C2'] else 0.05, 0.3)) / investment_amount * 100, 2) if investment_amount > 0 else 0
            }, ensure_ascii=False),
            'product_preference': json.dumps({
                '偏好类型': {'C1': '稳健型', 'C2': '稳健型', 'C3': '平衡型', 'C4': '进取型', 'C5': '进取型'}[risk_level],
                '关注指标': random.sample(['收益率', '风险等级', '流动性', '历史业绩'], k=2)
            }, ensure_ascii=False),
            'memory_units': json.dumps([
                f"客户年龄{user['age']}岁，风险等级{risk_level}，总资产{round(total_assets/10000, 1)}万元",
                f"投入理财产品{round(investment_amount/10000, 1)}万元，占流动资产{round(investment_amount/user['liquid_assets']*100, 1)}%",
                f"倾向于{random.choice(['长期持有', '中期持有', '定投'])}策略"
            ], ensure_ascii=False),
            'confidence_score': round(random.uniform(0.75, 0.95), 3),
            'updated_reason': random.choice(['定期', '事件', '行为'])
        })
    return profiles

def generate_transactions_and_holdings(users: List[Dict], our_products: List[Dict], other_products: List[Dict]) -> tuple:
    """生成交易和持仓数据 - 符合风险匹配原则"""
    transactions = []
    holdings_dict = {}
    transaction_id = 1

    for user in users:
        customer_id = user['id']
        risk_level = user['risk_level']
        allowed_risk_levels = RISK_MATCHING[risk_level]

        # 筛选可购买的本司产品
        our_allowed = [p for p in our_products if p['risk_level'] in allowed_risk_levels]
        # 其他公司产品（历史）
        other_allowed = [p for p in other_products if p['risk_level'] in allowed_risk_levels]

        # 1. 生成历史交易（其他公司产品，已赎回）
        history_count = random.randint(2, 5)
        for _ in range(history_count):
            if not other_allowed:
                break
            product = random.choice(other_allowed)
            product_id = product['id']

            # 申购
            buy_time = datetime.now() - timedelta(days=random.randint(180, 365))
            buy_amount = round(random.uniform(product['min_investment'], product['min_investment'] * 5), 2)
            buy_shares = round(buy_amount / product['nav'], 4)

            transactions.append({
                'id': transaction_id,
                'customer_id': customer_id,
                'product_id': product_id,
                'transaction_type': '申购',
                'amount': buy_amount,
                'shares': buy_shares,
                'nav': product['nav'],
                'fee': round(buy_amount * 0.015, 2),
                'is_cash': 0,
                'counterparty_account': None,
                'counterparty_name': None,
                'counterparty_region': None,
                'payer_account_name': None,
                'device_fingerprint': f"DEV{random.randint(100000, 999999)}",
                'channel': random.choice(['APP', '网银', '柜台']),
                'status': '成交',
                'transaction_time': buy_time.strftime('%Y-%m-%d %H:%M:%S')
            })
            transaction_id += 1

            # 赎回（几个月后）
            sell_time = buy_time + timedelta(days=random.randint(60, 150))
            transactions.append({
                'id': transaction_id,
                'customer_id': customer_id,
                'product_id': product_id,
                'transaction_type': '赎回',
                'amount': buy_amount * random.uniform(0.95, 1.1),  # 略有盈亏
                'shares': buy_shares,
                'nav': product['nav'] * random.uniform(0.95, 1.1),
                'fee': round(buy_amount * 0.005, 2),
                'is_cash': 0,
                'counterparty_account': None,
                'counterparty_name': None,
                'counterparty_region': None,
                'payer_account_name': None,
                'device_fingerprint': f"DEV{random.randint(100000, 999999)}",
                'channel': random.choice(['APP', '网银']),
                'status': '成交',
                'transaction_time': sell_time.strftime('%Y-%m-%d %H:%M:%S')
            })
            transaction_id += 1

        # 2. 生成本司产品的当前持仓（根据客户投资金额分配）
        if not our_allowed:
            continue

        investment_amount = user['investment_amount']
        if investment_amount < 1:  # 投资金额太小，跳过
            continue

        # 根据可选产品数量和投资金额决定持仓数量
        max_holding = min(5, len(our_allowed))
        min_holding = min(1, max_holding)

        # 投资金额越大，持仓越分散
        if investment_amount < 10000:
            holding_count = min_holding
        elif investment_amount < 50000:
            holding_count = random.randint(min_holding, min(2, max_holding))
        elif investment_amount < 200000:
            holding_count = random.randint(min_holding, min(3, max_holding))
        else:
            holding_count = random.randint(min(2, min_holding), max_holding)

        selected_products = random.sample(our_allowed, holding_count)

        # 将投资金额分配到各产品（随机权重）
        weights = [random.uniform(1, 10) for _ in range(holding_count)]
        total_weight = sum(weights)
        allocations = [investment_amount * (w / total_weight) for w in weights]

        for idx, product in enumerate(selected_products):
            product_id = product['id']
            allocated_amount = allocations[idx]

            # 确保满足起投金额
            if allocated_amount < product['min_investment']:
                allocated_amount = product['min_investment']

            # 随机生成1-3笔申购（定投效果）
            purchase_count = random.randint(1, 3)
            per_purchase = allocated_amount / purchase_count

            for _ in range(purchase_count):
                buy_time = datetime.now() - timedelta(days=random.randint(30, 120))
                buy_amount = round(per_purchase * random.uniform(0.8, 1.2), 2)  # 略有波动
                buy_shares = round(buy_amount / product['nav'], 4)

                transactions.append({
                    'id': transaction_id,
                    'customer_id': customer_id,
                    'product_id': product_id,
                    'transaction_type': random.choice(['申购', '定投']),
                    'amount': buy_amount,
                    'shares': buy_shares,
                    'nav': product['nav'],
                    'fee': round(buy_amount * random.uniform(0.001, 0.015), 2),
                    'is_cash': 0,
                    'counterparty_account': None,
                    'counterparty_name': None,
                    'counterparty_region': None,
                    'payer_account_name': None,
                    'device_fingerprint': f"DEV{random.randint(100000, 999999)}",
                    'channel': random.choice(['APP', '网银']),
                    'status': '成交',
                    'transaction_time': buy_time.strftime('%Y-%m-%d %H:%M:%S')
                })
                transaction_id += 1

                # 累积持仓
                key = (customer_id, product_id)
                if key not in holdings_dict:
                    holdings_dict[key] = {'customer_id': customer_id, 'product_id': product_id, 'shares': 0, 'cost_amount': 0}
                holdings_dict[key]['shares'] += buy_shares
                holdings_dict[key]['cost_amount'] += buy_amount

    # 计算持仓市值和盈亏
    holdings = []
    product_map = {p['id']: p for p in our_products + other_products}
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
    if value is None:
        return 'NULL'
    elif isinstance(value, (int, float, Decimal)):
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
    print("Mock数据生成 V3 - 符合真实业务逻辑")
    print("="*60)

    # 准备产品数据
    our_products_with_id = []
    for i, p in enumerate(OUR_PRODUCTS, 1):
        product = p.copy()
        product['id'] = i
        product['nav_date'] = (datetime.now() - timedelta(days=random.randint(0, 2))).strftime('%Y-%m-%d')
        product['description'] = f"{p['product_name']}, 风险等级{p['risk_level']}, 起投{p['min_investment']}元"
        our_products_with_id.append(product)

    other_products_with_id = []
    for i, p in enumerate(OTHER_PRODUCTS, len(OUR_PRODUCTS) + 1):
        product = p.copy()
        product['id'] = i
        product['nav_date'] = (datetime.now() - timedelta(days=random.randint(180, 365))).strftime('%Y-%m-%d')
        product['description'] = f"{p['product_name']}（其他公司产品，历史交易用）"
        other_products_with_id.append(product)

    print(f"\n配置：")
    print(f"  - 客户数量: {CUSTOMER_COUNT}")
    print(f"  - 本司产品: {len(our_products_with_id)}款（当前可持有）")
    print(f"  - 其他产品: {len(other_products_with_id)}款（历史交易用）")
    print(f"  - 风险等级分布: C1-C5 各30人（均匀分布）")
    print(f"  - 年龄范围: 25-65岁")

    print("\n生成数据...")
    users = generate_users(CUSTOMER_COUNT)
    profiles = generate_customer_profiles(users)
    transactions, holdings = generate_transactions_and_holdings(users, our_products_with_id, other_products_with_id)

    # 统计资产信息
    total_assets_sum = sum([u['total_assets'] for u in users])
    investment_sum = sum([u['investment_amount'] for u in users])
    holding_value_sum = sum([h['current_value'] for h in holdings])

    # 移除临时字段
    for user in users:
        del user['risk_level']
        del user['age']
        del user['total_assets']
        del user['real_estate']
        del user['liquid_assets']
        del user['investment_amount']

    all_products = our_products_with_id + other_products_with_id

    print("\n生成SQL...")
    with open('scripts/mock_data_seed.sql', 'w', encoding='utf-8') as f:
        f.write("-- ============================================================\n")
        f.write("-- 财富管家系统 Mock数据 V3（符合真实业务逻辑）\n")
        f.write(f"-- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"-- 客户:{len(users)}, 产品:{len(all_products)}, 交易:{len(transactions)}, 持仓:{len(holdings)}\n")
        f.write("-- ============================================================\n\n")
        f.write("USE wealth_butler;\nSET FOREIGN_KEY_CHECKS=0;\n\n")

        f.write(f"-- 1. 用户数据 ({len(users)}条)\n")
        f.write("-- ============================================================\n\n")
        for sql in generate_insert_sql('base_user', users):
            f.write(sql + "\n\n")

        f.write(f"-- 2. 客户画像 ({len(profiles)}条)\n")
        f.write("-- ============================================================\n\n")
        for sql in generate_insert_sql('fin_customer_profile', profiles):
            f.write(sql + "\n\n")

        f.write(f"-- 3. 产品数据 (本司{len(our_products_with_id)}款+其他{len(other_products_with_id)}款)\n")
        f.write("-- ============================================================\n\n")
        for sql in generate_insert_sql('fin_product', all_products):
            f.write(sql + "\n\n")

        f.write(f"-- 4. 交易流水 ({len(transactions)}条)\n")
        f.write("-- ============================================================\n\n")
        for sql in generate_insert_sql('fin_transaction', transactions):
            f.write(sql + "\n\n")

        f.write(f"-- 5. 持仓数据 ({len(holdings)}条 - 仅本司产品)\n")
        f.write("-- ============================================================\n\n")
        for sql in generate_insert_sql('fin_holdings', holdings):
            f.write(sql + "\n\n")

        f.write("SET FOREIGN_KEY_CHECKS=1;\n-- 完成\n")

    print(f"\n[完成] 数据生成完成")
    print(f"  用户: {len(users)}")
    print(f"  画像: {len(profiles)}")
    print(f"  产品: {len(all_products)} (本司{len(our_products_with_id)} + 其他{len(other_products_with_id)})")
    print(f"  交易: {len(transactions)}")
    print(f"  持仓: {len(holdings)} (仅本司产品)")

    print("\n风险等级分布统计：")
    for level in ['C1', 'C2', 'C3', 'C4', 'C5']:
        count = len([p for p in profiles if p['risk_level'] == level])
        print(f"  {level}: {count}人")

    print("\n客户等级分布统计：")
    level_stats = {}
    for user in users:
        level = json.loads(user['extra_data'])['asset_structure']
        customer_level = user['customer_level']
        if customer_level not in level_stats:
            level_stats[customer_level] = {'count': 0, 'assets': 0}
        level_stats[customer_level]['count'] += 1
        level_stats[customer_level]['assets'] += level['total_assets']

    for level in ['普通', '金卡', '白金', '钻石', '私行']:
        if level in level_stats:
            stats = level_stats[level]
            avg = stats['assets'] / stats['count']
            print(f"  {level}: {stats['count']}人, 人均资产{round(avg/10000, 1)}万元")

    print("\n资产配置统计：")
    print(f"  客户总资产合计: {round(total_assets_sum/10000, 2)}万元")
    print(f"  投入理财产品: {round(investment_sum/10000, 2)}万元 (占总资产{round(investment_sum/total_assets_sum*100, 1)}%)")
    print(f"  当前持仓市值: {round(holding_value_sum/10000, 2)}万元")
    print(f"  人均投资金额: {round(investment_sum/CUSTOMER_COUNT/10000, 2)}万元")

    print(f"\nSQL文件: scripts/mock_data_seed.sql")

if __name__ == "__main__":
    main()
