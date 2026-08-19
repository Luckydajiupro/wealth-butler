#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RAG知识库测试问题集
用于测试金融知识库的检索质量和相似度阈值调优
"""

import json
from typing import List, Dict
from datetime import datetime

# 测试问题集定义
TEST_QUESTIONS = [
    # ==================== FAQ类问题 (10道) ====================
    {
        "id": "FAQ-001",
        "category": "FAQ",
        "difficulty": "简单",
        "question": "公司的客服电话是多少？服务时间是什么？",
        "expected_source": "高频问答对.txt",
        "keywords": ["客服", "电话", "400", "服务时间"],
        "notes": "简单事实查询，应直接匹配FAQ第9条"
    },
    {
        "id": "FAQ-002",
        "category": "FAQ",
        "difficulty": "简单",
        "question": "基金申购后多久能确认份额？",
        "expected_source": "高频问答对.txt",
        "keywords": ["申购", "确认", "T+1", "份额"],
        "notes": "简单时效查询，对应FAQ第15条"
    },
    {
        "id": "FAQ-003",
        "category": "FAQ",
        "difficulty": "中等",
        "question": "基金和理财产品到底有什么不同？我该怎么选？",
        "expected_source": "高频问答对.txt",
        "keywords": ["基金", "理财", "区别", "净值"],
        "notes": "产品对比类问题，对应FAQ第11条"
    },
    {
        "id": "FAQ-004",
        "category": "FAQ",
        "difficulty": "中等",
        "question": "什么是风险评估？为什么开户必须做这个？",
        "expected_source": "高频问答对.txt",
        "keywords": ["风险评估", "KYC", "问卷", "C1-C5"],
        "notes": "概念解释类，对应FAQ第22条"
    },
    {
        "id": "FAQ-005",
        "category": "FAQ",
        "difficulty": "中等",
        "question": "我想更换绑定的银行卡，怎么操作？",
        "expected_source": "高频问答对.txt",
        "keywords": ["银行卡", "更换", "人脸识别"],
        "notes": "操作流程类，对应FAQ第31条"
    },
    {
        "id": "FAQ-006",
        "category": "FAQ",
        "difficulty": "复杂",
        "question": "基金定投是什么意思？真的能赚钱吗？",
        "expected_source": "高频问答对.txt",
        "keywords": ["定投", "平均成本法", "长期投资"],
        "notes": "策略解释类，对应FAQ第30条"
    },
    {
        "id": "FAQ-007",
        "category": "FAQ",
        "difficulty": "边界",
        "question": "我的风险评估是C2稳健型，可以买R3的混合基金吗？",
        "expected_source": "高频问答对.txt + 个人投资者适当性管理指南.md",
        "keywords": ["C2", "R3", "适当性", "匹配"],
        "notes": "跨文档查询，需要结合FAQ第23条和适当性政策"
    },
    {
        "id": "FAQ-008",
        "category": "FAQ",
        "difficulty": "边界",
        "question": "货币基金和债券基金哪个收益更高？风险呢？",
        "expected_source": "高频问答对.txt + 个人理财产品手册.md",
        "keywords": ["货币基金", "债券基金", "收益", "风险"],
        "notes": "对比分析类，对应FAQ第12条"
    },
    {
        "id": "FAQ-009",
        "category": "FAQ",
        "difficulty": "跨领域",
        "question": "购买基金需要进行反洗钱审查吗？",
        "expected_source": "高频问答对.txt + 反洗钱合规操作手册.md",
        "keywords": ["反洗钱", "身份识别", "大额交易"],
        "notes": "跨领域问题，涉及FAQ第27条和反洗钱政策"
    },
    {
        "id": "FAQ-010",
        "category": "FAQ",
        "difficulty": "跨领域",
        "question": "如果我一次性申购100万的基金，申购费率有优惠吗？",
        "expected_source": "高频问答对.txt + 理财产品销售管理办法.md",
        "keywords": ["大额申购", "费率优惠", "100万"],
        "notes": "大额交易费率查询，对应FAQ第17条和销售办法第16条"
    },

    # ==================== 产品类问题 (10道) ====================
    {
        "id": "PRODUCT-001",
        "category": "产品",
        "difficulty": "简单",
        "question": "XX货币市场基金的起投金额是多少？",
        "expected_source": "个人理财产品手册.md",
        "keywords": ["货币基金", "起投", "1元"],
        "notes": "简单产品参数查询"
    },
    {
        "id": "PRODUCT-002",
        "category": "产品",
        "difficulty": "简单",
        "question": "锦鹏科技创新股票基金是什么风险等级？",
        "expected_source": "个人理财产品手册.md",
        "keywords": ["科技创新", "股票", "R4", "中高风险"],
        "notes": "风险等级查询"
    },
    {
        "id": "PRODUCT-003",
        "category": "产品",
        "difficulty": "中等",
        "question": "XX稳健增利债券A和XX平衡优选混合基金有什么区别？",
        "expected_source": "个人理财产品手册.md",
        "keywords": ["债券基金", "混合基金", "股票仓位", "风险"],
        "notes": "产品对比，涉及投资策略、风险等级、收益差异"
    },
    {
        "id": "PRODUCT-004",
        "category": "产品",
        "difficulty": "中等",
        "question": "哪些基金产品适合保守型投资者？",
        "expected_source": "个人理财产品手册.md",
        "keywords": ["保守型", "C1", "货币基金", "债券基金", "R1", "R2"],
        "notes": "产品推荐类查询"
    },
    {
        "id": "PRODUCT-005",
        "category": "产品",
        "difficulty": "复杂",
        "question": "我有10万元闲钱打算投资3年，风险承受能力中等，应该选什么产品组合？",
        "expected_source": "个人理财产品手册.md",
        "keywords": ["资产配置", "平衡型", "3年", "组合"],
        "notes": "资产配置建议，需要匹配产品对比表第4.2节"
    },
    {
        "id": "PRODUCT-006",
        "category": "产品",
        "difficulty": "复杂",
        "question": "XX红利价值股票基金和锦鹏科技创新股票基金哪个波动更大？",
        "expected_source": "个人理财产品手册.md",
        "keywords": ["最大回撤", "波动", "红利", "科技"],
        "notes": "风险指标对比，需要比较最大回撤数据"
    },
    {
        "id": "PRODUCT-007",
        "category": "产品",
        "difficulty": "边界",
        "question": "为什么QDII基金赎回到账需要7-10天这么长时间？",
        "expected_source": "个人理财产品手册.md",
        "keywords": ["QDII", "赎回", "跨境", "外汇"],
        "notes": "产品机制解释类"
    },
    {
        "id": "PRODUCT-008",
        "category": "产品",
        "difficulty": "边界",
        "question": "我买了基金3天就想卖，赎回费率是多少？",
        "expected_source": "个人理财产品手册.md",
        "keywords": ["持有<7天", "1.5%", "惩罚性赎回费"],
        "notes": "费率边界条件查询"
    },
    {
        "id": "PRODUCT-009",
        "category": "产品",
        "difficulty": "跨领域",
        "question": "购买私募基金需要满足什么条件？",
        "expected_source": "个人理财产品手册.md + 个人投资者适当性管理指南.md",
        "keywords": ["私募", "合格投资者", "500万", "100万"],
        "notes": "涉及合格投资者认定标准"
    },
    {
        "id": "PRODUCT-010",
        "category": "产品",
        "difficulty": "跨领域",
        "question": "XX福享年金保险和XX传世增额终身寿险有什么区别？哪个更适合养老规划？",
        "expected_source": "个人理财产品手册.md",
        "keywords": ["年金险", "增额寿", "养老", "现金价值"],
        "notes": "保险产品对比，涉及产品结构和适用场景"
    },

    # ==================== 政策类问题 (10道) ====================
    {
        "id": "POLICY-001",
        "category": "政策",
        "difficulty": "简单",
        "question": "个人单笔现金交易多少金额以上需要上报大额交易？",
        "expected_source": "反洗钱合规操作手册.md",
        "keywords": ["大额交易", "5万元", "现金"],
        "notes": "简单政策阈值查询，对应第十条"
    },
    {
        "id": "POLICY-002",
        "category": "政策",
        "difficulty": "简单",
        "question": "投资者风险评估的有效期是多长时间？",
        "expected_source": "个人投资者适当性管理指南.md",
        "keywords": ["风险评估", "12个月", "有效期"],
        "notes": "简单时效查询，对应第二十四条"
    },
    {
        "id": "POLICY-003",
        "category": "政策",
        "difficulty": "中等",
        "question": "客户身份识别KYC需要核实哪些信息？",
        "expected_source": "反洗钱合规操作手册.md",
        "keywords": ["KYC", "身份证", "联系电话", "居住地址", "职业"],
        "notes": "政策要求列举，对应第五条"
    },
    {
        "id": "POLICY-004",
        "category": "政策",
        "difficulty": "中等",
        "question": "哪些情况下销售理财产品必须进行录音录像？",
        "expected_source": "理财产品销售管理办法.md + 个人投资者适当性管理指南.md",
        "keywords": ["双录", "首次购买R3", "65周岁", "50万"],
        "notes": "双录触发条件查询"
    },
    {
        "id": "POLICY-005",
        "category": "政策",
        "difficulty": "复杂",
        "question": "什么是投资者适当性管理？C3平衡型投资者可以购买哪些风险等级的产品？",
        "expected_source": "个人投资者适当性管理指南.md",
        "keywords": ["适当性", "C3", "R1-R3", "匹配矩阵"],
        "notes": "政策原理+匹配规则，对应第十二条"
    },
    {
        "id": "POLICY-006",
        "category": "政策",
        "difficulty": "复杂",
        "question": "什么情况下需要对客户进行身份重新识别？",
        "expected_source": "反洗钱合规操作手册.md",
        "keywords": ["重新识别", "证件到期", "异常交易", "负面信息"],
        "notes": "触发条件列举，对应第七条"
    },
    {
        "id": "POLICY-007",
        "category": "政策",
        "difficulty": "边界",
        "question": "如果客户多次进行49999元的交易，会被识别为可疑交易吗？",
        "expected_source": "反洗钱合规操作手册.md",
        "keywords": ["拆分交易", "规避报告", "可疑特征", "ST-24"],
        "notes": "边界case，涉及拆分交易防范和可疑交易识别"
    },
    {
        "id": "POLICY-008",
        "category": "政策",
        "difficulty": "边界",
        "question": "私募基金的冷静期是多长？这期间我可以退出吗？",
        "expected_source": "个人投资者适当性管理指南.md",
        "keywords": ["冷静期", "24小时", "无条件解除"],
        "notes": "投资者保护机制，对应第二十一条"
    },
    {
        "id": "POLICY-009",
        "category": "政策",
        "difficulty": "跨领域",
        "question": "65岁以上老年人购买理财产品有什么特殊要求？",
        "expected_source": "理财产品销售管理办法.md + 个人投资者适当性管理指南.md",
        "keywords": ["65周岁", "双录", "非R1产品"],
        "notes": "老年人保护政策，跨双录和适当性管理"
    },
    {
        "id": "POLICY-010",
        "category": "政策",
        "difficulty": "跨领域",
        "question": "什么是受益所有人识别？机构客户需要提供哪些材料？",
        "expected_source": "反洗钱合规操作手册.md",
        "keywords": ["受益所有人", "25%", "股权穿透", "实际控制"],
        "notes": "反洗钱核心制度，对应第八条"
    }
]

# 阈值推荐配置
THRESHOLD_RECOMMENDATIONS = {
    "faq": 0.75,      # FAQ类问题：表述多样但答案明确
    "product": 0.70,  # 产品类问题：需要精确检索产品参数
    "policy": 0.80    # 政策类问题：政策解读需要高准确性
}

# 难度对应的预期召回数
DIFFICULTY_RECALL_EXPECTATION = {
    "简单": {"min_recall": 1, "max_recall": 3},
    "中等": {"min_recall": 2, "max_recall": 5},
    "复杂": {"min_recall": 3, "max_recall": 8},
    "边界": {"min_recall": 2, "max_recall": 6},
    "跨领域": {"min_recall": 4, "max_recall": 10}
}


def export_to_json(output_file: str = "test_questions.json"):
    """导出测试问题集为JSON格式"""
    data = {
        "metadata": {
            "title": "RAG知识库测试问题集",
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "total_questions": len(TEST_QUESTIONS),
            "categories": {
                "FAQ": len([q for q in TEST_QUESTIONS if q["category"] == "FAQ"]),
                "产品": len([q for q in TEST_QUESTIONS if q["category"] == "产品"]),
                "政策": len([q for q in TEST_QUESTIONS if q["category"] == "政策"])
            }
        },
        "threshold_recommendations": THRESHOLD_RECOMMENDATIONS,
        "difficulty_expectations": DIFFICULTY_RECALL_EXPECTATION,
        "questions": TEST_QUESTIONS
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ 测试问题集已导出到: {output_file}")
    print(f"📊 总计 {len(TEST_QUESTIONS)} 道测试问题")
    print(f"   - FAQ类: {data['metadata']['categories']['FAQ']}道")
    print(f"   - 产品类: {data['metadata']['categories']['产品']}道")
    print(f"   - 政策类: {data['metadata']['categories']['政策']}道")


def print_summary():
    """打印测试问题集摘要"""
    print("=" * 80)
    print("RAG知识库测试问题集摘要".center(80))
    print("=" * 80)
    print()

    categories = {}
    difficulties = {}

    for q in TEST_QUESTIONS:
        cat = q["category"]
        diff = q["difficulty"]
        categories[cat] = categories.get(cat, 0) + 1
        difficulties[diff] = difficulties.get(diff, 0) + 1

    print("📂 按类别分布:")
    for cat, count in sorted(categories.items()):
        print(f"   {cat}: {count}道")

    print()
    print("📊 按难度分布:")
    for diff, count in sorted(difficulties.items(), key=lambda x:
                               ["简单", "中等", "复杂", "边界", "跨领域"].index(x[0])):
        print(f"   {diff}: {count}道")

    print()
    print("🎯 推荐阈值:")
    for cat, threshold in THRESHOLD_RECOMMENDATIONS.items():
        print(f"   {cat.upper()}类: {threshold}")

    print()
    print("=" * 80)


if __name__ == "__main__":
    print_summary()
    print()
    export_to_json("D:/lqh/金融/scripts/test_questions.json")
