"""
RAG混合检索阈值调优测试集

包含30个测试问题，覆盖：
- 产品咨询（15题）
- 政策法规（15题）

每个问题包含：
- query: 用户问题
- expected_keywords: 期望检索结果包含的关键词
- collection: 目标集合（product/policy）
"""

TEST_QUESTIONS = [
    # ========== 产品咨询类（15题） ==========
    {
        "id": 1,
        "query": "货币基金的收益率是多少？",
        "expected_keywords": ["货币", "收益", "年化"],
        "collection": "product",
        "category": "收益查询"
    },
    {
        "id": 2,
        "query": "稳健型理财产品有哪些？",
        "expected_keywords": ["稳健", "低风险", "固定收益"],
        "collection": "product",
        "category": "产品筛选"
    },
    {
        "id": 3,
        "query": "债券型基金的风险等级",
        "expected_keywords": ["债券", "风险", "中低"],
        "collection": "product",
        "category": "风险评估"
    },
    {
        "id": 4,
        "query": "购买基金需要哪些费用？",
        "expected_keywords": ["费用", "申购费", "赎回费", "管理费"],
        "collection": "product",
        "category": "费用咨询"
    },
    {
        "id": 5,
        "query": "混合型基金适合什么人？",
        "expected_keywords": ["混合", "风险偏好", "适合"],
        "collection": "product",
        "category": "适配性"
    },
    {
        "id": 6,
        "query": "股票型基金最低投资金额",
        "expected_keywords": ["股票", "起购", "最低"],
        "collection": "product",
        "category": "投资门槛"
    },
    {
        "id": 7,
        "query": "定期存款和理财产品的区别",
        "expected_keywords": ["定期", "理财", "区别", "收益"],
        "collection": "product",
        "category": "产品对比"
    },
    {
        "id": 8,
        "query": "如何选择适合自己的基金？",
        "expected_keywords": ["选择", "风险", "收益", "期限"],
        "collection": "product",
        "category": "投资建议"
    },
    {
        "id": 9,
        "query": "私募基金的认购条件",
        "expected_keywords": ["私募", "合格投资者", "门槛"],
        "collection": "product",
        "category": "准入条件"
    },
    {
        "id": 10,
        "query": "指数基金和主动型基金哪个好？",
        "expected_keywords": ["指数", "主动", "费率", "收益"],
        "collection": "product",
        "category": "产品对比"
    },
    {
        "id": 11,
        "query": "基金赎回到账时间",
        "expected_keywords": ["赎回", "到账", "T+"],
        "collection": "product",
        "category": "交易规则"
    },
    {
        "id": 12,
        "query": "什么是净值型理财产品？",
        "expected_keywords": ["净值", "浮动", "开放"],
        "collection": "product",
        "category": "产品概念"
    },
    {
        "id": 13,
        "query": "FOF基金的优势",
        "expected_keywords": ["FOF", "分散", "专业"],
        "collection": "product",
        "category": "产品特点"
    },
    {
        "id": 14,
        "query": "QDII基金投资哪些市场？",
        "expected_keywords": ["QDII", "海外", "市场"],
        "collection": "product",
        "category": "投资范围"
    },
    {
        "id": 15,
        "query": "保本理财产品还有吗？",
        "expected_keywords": ["保本", "资管新规", "净值"],
        "collection": "product",
        "category": "政策影响"
    },

    # ========== 政策法规类（15题） ==========
    {
        "id": 16,
        "query": "投资者适当性管理的要求",
        "expected_keywords": ["适当性", "风险匹配", "评估"],
        "collection": "policy",
        "category": "投资者保护"
    },
    {
        "id": 17,
        "query": "反洗钱需要核实哪些信息？",
        "expected_keywords": ["反洗钱", "身份", "核实"],
        "collection": "policy",
        "category": "合规要求"
    },
    {
        "id": 18,
        "query": "私募基金销售规范",
        "expected_keywords": ["私募", "合格投资者", "风险揭示"],
        "collection": "policy",
        "category": "销售规范"
    },
    {
        "id": 19,
        "query": "理财产品信息披露要求",
        "expected_keywords": ["信息披露", "定期", "重大事项"],
        "collection": "policy",
        "category": "信息披露"
    },
    {
        "id": 20,
        "query": "双录制度是什么？",
        "expected_keywords": ["双录", "录音", "录像", "销售"],
        "collection": "policy",
        "category": "销售管理"
    },
    {
        "id": 21,
        "query": "基金销售人员资格要求",
        "expected_keywords": ["资格", "从业", "考试"],
        "collection": "policy",
        "category": "从业规范"
    },
    {
        "id": 22,
        "query": "资管新规对理财产品的影响",
        "expected_keywords": ["资管新规", "净值", "刚兑"],
        "collection": "policy",
        "category": "监管政策"
    },
    {
        "id": 23,
        "query": "客户风险评估多久做一次？",
        "expected_keywords": ["风险评估", "定期", "更新"],
        "collection": "policy",
        "category": "投资者管理"
    },
    {
        "id": 24,
        "query": "理财子公司的业务范围",
        "expected_keywords": ["理财子公司", "业务", "范围"],
        "collection": "policy",
        "category": "机构监管"
    },
    {
        "id": 25,
        "query": "产品销售适当性原则",
        "expected_keywords": ["适当性", "匹配", "风险承受"],
        "collection": "policy",
        "category": "销售规范"
    },
    {
        "id": 26,
        "query": "大额交易报告标准",
        "expected_keywords": ["大额", "报告", "20万"],
        "collection": "policy",
        "category": "反洗钱"
    },
    {
        "id": 27,
        "query": "冷静期和犹豫期的规定",
        "expected_keywords": ["冷静期", "犹豫期", "撤销"],
        "collection": "policy",
        "category": "投资者权益"
    },
    {
        "id": 28,
        "query": "公募基金流动性风险管理",
        "expected_keywords": ["流动性", "风险", "管理"],
        "collection": "policy",
        "category": "风险管理"
    },
    {
        "id": 29,
        "query": "理财产品集中度限制",
        "expected_keywords": ["集中度", "限制", "比例"],
        "collection": "policy",
        "category": "投资限制"
    },
    {
        "id": 30,
        "query": "投资者投诉处理流程",
        "expected_keywords": ["投诉", "处理", "流程"],
        "collection": "policy",
        "category": "客户服务"
    }
]


def get_questions_by_collection(collection):
    """按集合筛选问题"""
    return [q for q in TEST_QUESTIONS if q["collection"] == collection]


def get_questions_by_category(category):
    """按类别筛选问题"""
    return [q for q in TEST_QUESTIONS if q["category"] == category]


if __name__ == "__main__":
    print(f"Total questions: {len(TEST_QUESTIONS)}")
    print(f"Product questions: {len(get_questions_by_collection('product'))}")
    print(f"Policy questions: {len(get_questions_by_collection('policy'))}")

    # 按类别统计
    categories = {}
    for q in TEST_QUESTIONS:
        cat = q["category"]
        categories[cat] = categories.get(cat, 0) + 1

    print("\nQuestions by category:")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")
