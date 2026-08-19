#!/usr/bin/env python
"""Milvus 与 Neo4j 真实业务种子数据脚本。

默认仅执行预检。写入时只追加 Milvus 数据，Neo4j 仅使用 MERGE/SET，
不删除集合、不清空图、不覆盖其他命名空间的数据。

使用方式：
    python scripts/seed_vector_graph_data.py --dry-run
    python scripts/seed_vector_graph_data.py --apply --confirm APPLY_WB_SEED_20260817
    python scripts/seed_vector_graph_data.py --verify
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


NAMESPACE = "WB-SEED-20260817"
APPLY_CONFIRMATION = "APPLY_WB_SEED_20260817"
EMBEDDING_DIM = 1024
TARGET_COLLECTION_ROWS = 100

CUSTOMERS = {
    "wb_seed_c1_elderly": {
        "name": "陈秀兰",
        "risk_level": "C1",
        "profile": "60岁退休教师，金融资产约120万元，数字能力较弱，关注养老、反诈和低波动配置",
    },
    "wb_seed_c3_balanced": {
        "name": "林安平",
        "risk_level": "C3",
        "profile": "平衡型投资者，关注股债平衡、流动性和长期复利",
    },
    "wb_seed_c4_professional": {
        "name": "王建国",
        "risk_level": "C4",
        "profile": "45岁企业主，总资产约3亿元，风评76分，专业投资者认定中，关注复杂产品与财富传承",
    },
    "wb_seed_c5_aggressive": {
        "name": "周锐达",
        "risk_level": "C5",
        "profile": "激进型投资者，关注权益成长、全球分散与回撤管理",
    },
}

PRODUCTS = {
    "WBSEED-R1-CASH": {"name": "安心现金管理货币基金", "risk_level": "R1", "type": "公募基金", "industry": "货币市场"},
    "WBSEED-R2-BOND": {"name": "稳健中短债基金", "risk_level": "R2", "type": "公募基金", "industry": "债券"},
    "WBSEED-R3-MIX": {"name": "平衡配置混合基金", "risk_level": "R3", "type": "公募基金", "industry": "多资产配置"},
    "WBSEED-R4-EQUITY": {"name": "科技创新股票基金", "risk_level": "R4", "type": "公募基金", "industry": "信息技术"},
    "WBSEED-R5-PRIVATE": {"name": "专业投资者量化对冲私募", "risk_level": "R5", "type": "私募基金", "industry": "量化投资"},
}

COLLECTIONS = {
    "faq": "fin_faq_collection",
    "product": "fin_product_collection",
    "policy": "fin_policy_collection",
    "memory": "fin_customer_memory_collection",
}


@dataclass(frozen=True)
class SeedItem:
    stable_key: str
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class MySQLSeedData:
    customers: dict[str, dict[str, Any]]
    employees: dict[str, dict[str, Any]]
    products: dict[str, dict[str, Any]]
    holdings: list[dict[str, Any]]


FAQ_ROWS = [
    ("什么是客户风险等级C1到C5？", "C1至C5表示客户承受投资损失的能力，等级越高可承受的产品风险通常越高。"),
    ("C1客户可以购买哪些产品？", "C1客户仅允许购买R1和R2产品，不得购买R3及以上产品。"),
    ("风险评估有效期多久？", "风险评估有效期为12个月，过期后冻结新购，但允许赎回存量持仓。"),
    ("买理财为什么要做适当性匹配？", "适当性匹配用于确保客户的风险承受能力与产品风险等级相容，避免不当销售。"),
    ("申购多少金额需要二次确认？", "单笔申购超过1万元时必须完成二次确认，确认前不执行交易。"),
    ("转账多少金额需要二次确认？", "单笔转账超过5万元时必须完成二次确认。"),
    ("哪些情形需要双录？", "普通投资者首次购买R3及以上产品、65岁以上购买非R1产品、豁免越级购买、单笔超过50万元或销售复杂私募产品时需双录。"),
    ("私募基金可以一键申购吗？", "不可以。私募和资管类产品只能在系统内提交预约与资格初核，后续需线下核验、风险揭示、双录和冷静期。"),
    ("什么是私募基金24小时冷静期？", "私募类产品自合同签署起设24小时冷静期，期间可无条件申请退出。"),
    ("货币基金有什么风险？", "货币基金通常为R1，流动性较好，但仍不承诺保本保收益，存在市场与流动性风险。"),
    ("债券基金为什么会亏损？", "债券基金受利率变动、信用违约、估值波动和流动性影响，净值可能下跌。"),
    ("股票基金适合养老短期资金吗？", "通常不适合短期刚性养老支出资金，应根据期限、流动性需求和客户风险等级判断。"),
    ("为什么要分散投资？", "分散投资可减少单一产品、行业或市场对组合的集中影响，但不能消除所有风险。"),
    ("如何识别保证收益的投资诈骗？", "正规金融产品不应承诺“稳赚不赔”或“无风险高收益”，应核实机构资质、合同与资金去向。"),
    ("工作人员会索要验证码或交易密码吗？", "不会。任何人索要验证码、登录密码或交易密码都应拒绝，并通过官方渠道核实。"),
    ("发现可疑转账应怎么办？", "立即停止后续操作，保留对话与交易证据，联系官方客服或报警，不要再向陌生账户汇款。"),
    ("客户能否直接让AI执行转账？", "不能。客户只直接使用客服Agent，转账由具备权限的客户经理代为发起并完成合规校验。"),
    ("客户如何转人工服务？", "客服Agent识别到转人工意图后会创建客户转介工单，由理财顾问或客户经理领取处理。"),
    ("为什么高净值客户也要做风险评估？", "资产规模和风险承受能力是独立维度，高净值不等于可自动承受高风险。"),
    ("专业投资者认定需要哪些条件？", "应同时核验金融资产、收入、投资经验和专业测试，认定中不能视为已取得豁免。"),
    ("专业投资者可以免除所有风险提示吗？", "不可以。豁免部分适当性匹配时，仍需完成信息核实和风险告知。"),
    ("老年客户购买理财有哪些额外保护？", "65岁以上购买非R1产品需双录，高龄和高风险场景还需按熔断规则执行当面确认或特殊审批。"),
    ("风险揭示书是产品保本承诺吗？", "不是。风险揭示书用于说明产品风险并留存客户知情证据，不改变产品风险也不代表保本。"),
    ("实时风控为什么还要回查交易流水？", "事件流只是触发信号，交易表才是权威业务事实，回查可避免伪造事件金额导致误报。"),
    ("预警是否等于客户已经违规？", "不等于。风险预警是待调查事项，需由风控专员核实证据并处置。"),
    ("今日收益数据不完整时会怎么处理？", "系统不会伪造收益，只返回可靠的总资产或累计浮动盈亏，并明确标记今日收益数据不可用。"),
    ("赎回基金前需要注意什么？", "应核对可赎回份额、赎回费、到账时间、净值确认规则和剩余持仓风险。"),
    ("投资产品的历史收益能代表未来吗？", "不能。历史收益只是过往表现，不构成未来业绩或本金安全的保证。"),
    ("什么是流动性风险？", "流动性风险是指产品不能在需要时间内以合理价格变现，或赎回到账时间超出预期的可能性。"),
    ("养老资金配置为什么要预留应急现金？", "预留应急现金可用于医疗和日常刚性支出，避免在市场下跌时被迫赎回长期产品。"),
]

MEMORY_TOPICS = [
    ("风险偏好", "客户明确接受与自身风险等级匹配的产品，不以高收益承诺代替风险判断"),
    ("流动性", "客户要求组合保留可于短期内变现的资金，以应对紧急支出"),
    ("投资期限", "客户区分短期备用金和长期增值资金，不混用两类目标"),
    ("收益预期", "客户理解历史业绩不预示未来，并拒绝保本保收益话术"),
    ("回撤承受", "客户希望在市场明显下跌时先复核目标和持仓，避免情绪化操作"),
    ("行业分散", "客户关注行业集中度，希望推荐时显示新产品对现有持仓的分散效果"),
    ("市场分散", "客户希望权益暴露不只集中于单一市场，同时关注汇率风险"),
    ("债券信用", "客户在债券配置中关注发行人信用、久期和利率波动"),
    ("基金费率", "客户要求比较申购费、赎回费、管理费和持有期对总成本的影响"),
    ("赎回到账", "客户关注赎回确认日和实际到账时间，避免影响日常资金安排"),
    ("适当性", "客户同意交易前以有效风评记录作为强合规判断依据"),
    ("风险揭示", "客户理解签署风险揭示书是知情证据，不代表产品风险被消除"),
    ("二次确认", "客户希望大额申购或转账在真正执行前再次展示金额、产品与收款方"),
    ("双录留痕", "客户理解特定高风险或特殊人群场景需完成录音录像并长期留存"),
    ("私募冷静期", "客户理解私募类产品不能一键成交，签约后还有24小时冷静期"),
    ("反诈偏好", "客户要求涉及陌生收款账户、验证码或高收益承诺时优先给出反诈提示"),
    ("收款方验证", "客户转账前要求核对收款人姓名、账号后四位和历史验证状态"),
    ("养老目标", "客户要求养老资金优先保障日常生活和医疗支出，再谋求长期增值"),
    ("家庭协助", "客户允许家人协助理解界面和材料，但身份验证、风险确认与交易授权必须由本人完成"),
    ("数字适老", "客户偏好更大字体、简短步骤、清晰风险提示和可随时转人工的服务"),
    ("专业认定", "客户理解专业投资者认定中不等于已取得豁免，必须等待合规核验结果"),
    ("财富传承", "客户关注财富传承安排中的流动性、受益人意愿、期限与合规文件留存"),
    ("集中度上限", "客户希望新申购前重新计算高风险持仓占比，不使用过期缓存结果"),
    ("定期复评", "客户接受在风评到期前提醒，资产或行为明显变化时及时重新评估"),
    ("人工复核", "客户希望在AI判断与本人自评差异较大时转人工复核，并保留判断依据"),
]

POLICY_ROWS = [
    ("适当性匹配原则", "客户风险等级与产品风险等级必须执行正向匹配，C1不得购买R3及以上产品。"),
    ("双录触发与保存", "首次购买R3+、高龄客户购买非R1、越级豁免、单笔超过50万或复杂私募产品需双录，记录长期保存。"),
    ("反洗钱大额报告线", "现金单笔或当日累计达5万元，自然人转账单笔达20万元或当日累计达50万元时进入相应报告和审查流程。"),
    ("风评过期处理", "风险评估超过12个月后冻结新购，允许赎回存量持仓，完成重评后方可解冻。"),
    ("私募冷静期与回访", "私募类产品设24小时冷静期，届满前由非销售人员录音回访确认，冷静期内可无条件退出。"),
]


def build_faq_items() -> list[SeedItem]:
    return [
        SeedItem(
            stable_key=f"wbseed-faq-{index:03d}",
            text=f"Q: {question}\nA: {answer}",
            metadata={
                "namespace": NAMESPACE,
                "stable_key": f"wbseed-faq-{index:03d}",
                "question": question,
                "answer": answer,
                "category": "智能财富管家验收知识",
                "source": "docs/智能财富管家系统-项目需求文档.md",
            },
        )
        for index, (question, answer) in enumerate(FAQ_ROWS, start=1)
    ]


def build_product_items() -> list[SeedItem]:
    templates = [
        ("overview", "{name}是{risk}的{type}，种子产品编码为{code}，核心风险暴露为{industry}。"),
        ("risk", "{name}的产品风险等级是{risk}，交易前必须根据客户C1-C5风评执行适当性匹配。"),
        ("suitability", "{name}的适当性判断不只比较风险等级，还要检查风评有效期、特殊人群限制与合规证据。"),
        ("liquidity", "{name}的咨询应同时说明赎回确认、到账时间与流动性风险，不把账面市值当作随时可用现金。"),
        ("allocation", "{name}在组合中属于{industry}暴露，推荐时应结合客户现有行业集中度评估分散效果。"),
        ("operation", "{name}的申购必须经过RBAC、顾问资质、适当性、熔断、合规证据和金额二次确认检查。"),
    ]
    result: list[SeedItem] = []
    # 按属性交错产品，当只需补部分差额时仍保证五档风险产品都有语料。
    for chunk_type, template in templates:
        for code, product in PRODUCTS.items():
            stable_key = f"wbseed-product-{code.lower()}-{chunk_type}"
            text = template.format(code=code, **product, risk=product["risk_level"])
            result.append(
                SeedItem(
                    stable_key=stable_key,
                    text=text,
                    metadata={
                        "namespace": NAMESPACE,
                        "stable_key": stable_key,
                        "product_code": code,
                        "product_name": product["name"],
                        "risk_level": product["risk_level"],
                        "product_type": product["type"],
                        "industry": product["industry"],
                        "chunk_type": chunk_type,
                        "source": "WB-SEED-20260817/MySQL/fin_product",
                    },
                )
            )
    return result


def build_policy_items() -> list[SeedItem]:
    return [
        SeedItem(
            stable_key=f"wbseed-policy-{index:03d}",
            text=f"政策主题：{title}\n{content}",
            metadata={
                "namespace": NAMESPACE,
                "stable_key": f"wbseed-policy-{index:03d}",
                "policy_title": title,
                "category": "金融合规",
                "source": "docs/智能财富管家系统-项目需求文档.md",
            },
        )
        for index, (title, content) in enumerate(POLICY_ROWS, start=1)
    ]


def build_memory_items(customer_ids: dict[str, int]) -> list[SeedItem]:
    items: list[SeedItem] = []
    for customer_key, customer in CUSTOMERS.items():
        customer_id = customer_ids[customer_key]
        for index, (topic, statement) in enumerate(MEMORY_TOPICS, start=1):
            stable_key = f"wbseed-memory-{customer_key.removeprefix('wb_seed_')}-{index:02d}"
            content = (
                f"[namespace={NAMESPACE}][stable_key={stable_key}] "
                f"{customer['name']}（{customer['risk_level']}）：{customer['profile']}。"
                f"记忆主题“{topic}”：{statement}。"
            )
            items.append(
                SeedItem(
                    stable_key=stable_key,
                    text=content,
                    metadata={
                        "customer_id": str(customer_id),
                        "memory_type": topic,
                        "session_id": NAMESPACE,
                        "agent_type": "seed_pipeline",
                        "importance": "0.80",
                        "created_at": "20260817",
                        "last_accessed_at": "20260817",
                        "access_count": "0",
                    },
                )
            )
    return items


def _json_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _mysql_json(value: Any) -> dict[str, Any]:
    """兼容 pymysql 返回 JSON 字符串或已解码对象。"""
    return value if isinstance(value, dict) else _json_metadata(value)


def existing_stable_keys(rows: Iterable[dict[str, Any]], memory: bool = False) -> set[str]:
    if memory:
        keys = set()
        pattern = re.compile(r"^\[namespace=" + re.escape(NAMESPACE) + r"\]\[stable_key=([^\]]+)\]")
        for row in rows:
            if row.get("session_id") != NAMESPACE:
                continue
            match = pattern.match(str(row.get("content") or ""))
            if match:
                keys.add(match.group(1))
        return keys
    keys = set()
    for row in rows:
        metadata = _json_metadata(row.get("metadata"))
        if metadata.get("namespace") == NAMESPACE and metadata.get("stable_key"):
            keys.add(str(metadata["stable_key"]))
    return keys


def namespace_row_count(rows: Iterable[dict[str, Any]], memory: bool = False) -> int:
    if memory:
        return sum(1 for row in rows if row.get("session_id") == NAMESPACE)
    return sum(1 for row in rows if _json_metadata(row.get("metadata")).get("namespace") == NAMESPACE)


def select_missing_items(
    candidates: Sequence[SeedItem], existing_keys: set[str], current_count: int, target: int = TARGET_COLLECTION_ROWS
) -> list[SeedItem]:
    deficit = max(0, target - current_count)
    missing = [item for item in candidates if item.stable_key not in existing_keys]
    return missing[:deficit]


def validate_embedding(vector: Sequence[Any]) -> list[float]:
    if len(vector) != EMBEDDING_DIM:
        raise RuntimeError(f"Embedding维度错误：期望{EMBEDDING_DIM}，实际{len(vector)}")
    normalized = [float(value) for value in vector]
    if not all(math.isfinite(value) for value in normalized):
        raise RuntimeError("Embedding包含非有限数值")
    if not any(value != 0.0 for value in normalized):
        raise RuntimeError("Embedding是零向量，拒绝写入")
    return normalized


def get_embedding(text: str) -> list[float]:
    from app.Base.Client.ollamaClient import ollama_client

    # 实施时禁止降级为零向量，任何失败都交给上层终止。
    return validate_embedding(ollama_client.get_embedding(text, model="bge-m3"))


def resolve_mysql_seed_data() -> MySQLSeedData:
    import pymysql
    from app.Base.Config.setting import settings

    connection = pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=str(settings.mysql.password),
        database=settings.mysql.name,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT u.id, u.username, u.employee_role, u.extra_data, p.risk_level "
                "FROM base_user u LEFT JOIN fin_customer_profile p ON p.customer_id=u.id "
                "WHERE JSON_UNQUOTE(JSON_EXTRACT(u.extra_data, '$.seed_namespace'))=%s "
                "AND u.user_type='CUSTOMER' AND u.status='active' AND u.deleted_at IS NULL ORDER BY u.username",
                (NAMESPACE,),
            )
            customers = {str(row["username"]): dict(row) for row in cursor.fetchall()}

            cursor.execute(
                "SELECT id, username, employee_role, advisor_level, extra_data FROM base_user "
                "WHERE JSON_UNQUOTE(JSON_EXTRACT(extra_data, '$.seed_namespace'))=%s "
                "AND user_type='EMPLOYEE' AND status='active' AND deleted_at IS NULL ORDER BY username",
                (NAMESPACE,),
            )
            employees = {str(row["username"]): dict(row) for row in cursor.fetchall()}

            cursor.execute(
                "SELECT id, product_code, product_name, product_type, risk_level, industry, fund_manager "
                "FROM fin_product WHERE description LIKE %s ORDER BY product_code",
                (f"[{NAMESPACE}]%",),
            )
            products = {str(row["product_code"]): dict(row) for row in cursor.fetchall()}

            if customers and products:
                cursor.execute(
                    f"SELECT h.customer_id, h.product_id, h.shares, h.current_value, p.product_code "
                    f"FROM fin_holdings h JOIN fin_product p ON p.id=h.product_id "
                    f"WHERE h.customer_id IN ({','.join(['%s'] * len(customers))}) "
                    f"AND p.product_code IN ({','.join(['%s'] * len(products))}) "
                    "AND h.deleted_at IS NULL",
                    tuple(int(row["id"]) for row in customers.values()) + tuple(products),
                )
                holdings = [dict(row) for row in cursor.fetchall()]
            else:
                holdings = []
    finally:
        connection.close()

    missing_customers = sorted(set(CUSTOMERS) - set(customers))
    missing_products = sorted(set(PRODUCTS) - set(products))
    missing_employees = sorted({"wb_seed_advisor", "wb_seed_risk", "wb_seed_operator"} - set(employees))
    if missing_customers or missing_products or missing_employees:
        raise RuntimeError(
            "MySQL稳定种子依赖不完整："
            f"missing_customers={missing_customers}, missing_employees={missing_employees}, "
            f"missing_products={missing_products}"
        )
    if len(customers) < 180 or len(employees) < 30 or len(products) < 50:
        raise RuntimeError(
            f"MySQL种子规模不足：customers={len(customers)}, employees={len(employees)}, products={len(products)}"
        )
    for code, expected in PRODUCTS.items():
        actual = products[code]
        if actual.get("risk_level") != expected["risk_level"]:
            raise RuntimeError(f"MySQL产品{code}风险等级不一致")
    for key, row in customers.items():
        if not row.get("risk_level"):
            raise RuntimeError(f"MySQL客户{key}缺少风险等级")
    return MySQLSeedData(customers=customers, employees=employees, products=products, holdings=holdings)


def get_milvus_client():
    from app.Base.Client.milvusClient import MilvusClientSingleton

    return MilvusClientSingleton().get_client()


def query_collection_rows(client: Any, collection_name: str, memory: bool = False) -> list[dict[str, Any]]:
    if memory:
        return client.query(
            collection_name=collection_name,
            filter='id != ""',
            output_fields=["id", "session_id", "content"],
            limit=16384,
        )
    return client.query(
        collection_name=collection_name,
        filter="id >= 0",
        output_fields=["id", "metadata"],
        limit=16384,
    )


def inspect_milvus(client: Any) -> dict[str, dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    for logical_name, collection_name in COLLECTIONS.items():
        if not client.has_collection(collection_name):
            raise RuntimeError(f"Milvus集合不存在：{collection_name}")
        description = client.describe_collection(collection_name)
        fields = {field["name"]: field for field in description.get("fields", [])}
        required = {"id", "embedding"}
        required.update({"content", "session_id", "customer_id"} if logical_name == "memory" else {"text", "metadata"})
        if not required.issubset(fields):
            raise RuntimeError(f"Milvus集合{collection_name}缺少字段：{sorted(required - set(fields))}")
        embedding_dim = int((fields["embedding"].get("params") or {}).get("dim", 0))
        if embedding_dim != EMBEDDING_DIM:
            raise RuntimeError(f"Milvus集合{collection_name}向量维度不是{EMBEDDING_DIM}")
        if logical_name == "memory" and not bool(description.get("auto_id")):
            raise RuntimeError("memory集合已迁移为非auto_id schema，需先更新兼容写入策略")
        row_count = int(client.get_collection_stats(collection_name).get("row_count", 0))
        rows = query_collection_rows(client, collection_name, memory=logical_name == "memory")
        inventory[logical_name] = {
            "collection": collection_name,
            "row_count": row_count,
            "namespace_keys": existing_stable_keys(rows, memory=logical_name == "memory"),
            "namespace_row_count": namespace_row_count(rows, memory=logical_name == "memory"),
        }
    return inventory


def build_milvus_plan(inventory: dict[str, dict[str, Any]], customer_ids: dict[str, int]) -> dict[str, list[SeedItem]]:
    candidates = {
        "faq": build_faq_items(),
        "product": build_product_items(),
        "policy": build_policy_items(),
        "memory": build_memory_items(customer_ids),
    }
    return {
        logical_name: select_missing_items(
            candidates[logical_name],
            inventory[logical_name]["namespace_keys"],
            inventory[logical_name]["row_count"],
        )
        for logical_name in COLLECTIONS
    }


def insert_milvus_items(client: Any, logical_name: str, items: Sequence[SeedItem]) -> int:
    if not items:
        return 0
    data = []
    for item in items:
        embedding = get_embedding(item.text)
        if logical_name == "memory":
            row = {
                "customer_id": item.metadata["customer_id"],
                "memory_type": item.metadata["memory_type"],
                "content": item.text,
                "session_id": item.metadata["session_id"],
                "agent_type": item.metadata["agent_type"],
                "importance": item.metadata["importance"],
                "created_at": item.metadata["created_at"],
                "last_accessed_at": item.metadata["last_accessed_at"],
                "access_count": item.metadata["access_count"],
                "embedding": embedding,
            }
        else:
            row = {
                "text": item.text,
                "metadata": json.dumps(item.metadata, ensure_ascii=False, sort_keys=True),
                "embedding": embedding,
            }
        data.append(row)
    result = client.insert(collection_name=COLLECTIONS[logical_name], data=data)
    insert_count = int(result.get("insert_count", len(result.get("ids", [])))) if isinstance(result, dict) else 0
    if insert_count != len(data):
        raise RuntimeError(f"Milvus {logical_name}写入数量不一致：{insert_count}/{len(data)}")
    flush = getattr(client, "flush", None)
    if callable(flush):
        flush(collection_name=COLLECTIONS[logical_name])
    return insert_count


INDUSTRIES = [
    "银行", "保险", "证券", "资产管理", "信托", "房地产", "建筑材料", "电力", "公用事业", "交通运输",
    "汽车", "新能源", "光伏", "风电", "储能", "半导体", "软件", "云计算", "网络安全", "人工智能",
    "通信", "电子", "医药", "医疗器械", "消费品", "食品饮料", "家电", "农业", "化工", "有色金属",
]

MARKETS = ["货币市场", "债券市场", "A股", "港股", "美股", "银行间市场", "黄金市场", "外汇市场"]

MANAGERS = [
    "现金管理策略团队", "利率债投资团队", "信用债投资团队", "股债平衡配置团队", "科技成长研究团队",
    "量化对冲策略团队", "全球资产配置团队", "绝对收益策略团队", "低波红利研究团队", "多资产风险预算团队",
]

POLICY_NODES = [
    "个人投资者适当性管理指南", "理财产品销售管理办法", "反洗钱合规操作手册", "反洗钱可疑交易识别规则", "投资者风险画像研判规则",
    "金融消费者权益保护", "客户身份识别与持续尽调", "大额交易和可疑交易报告", "金融产品风险揭示", "销售录音录像管理",
    "私募投资基金冷静期", "专业投资者认定", "老年金融消费者保护", "个人信息与数据脱敏", "业务操作二次确认",
    "基金申购赎回业务规则", "金融反诈风险提示", "异常账户非柜面交易限制", "投资者风评到期复评", "风险预警误报处理",
]

TOPICS = [topic for topic, _ in MEMORY_TOPICS] + ["货币基金", "债券基金", "混合基金", "股票基金", "私募基金"]


def _neo4j_write(client: Any, cypher: str, parameters: dict[str, Any]) -> None:
    result = client.run(cypher, parameters)
    if not result:
        raise RuntimeError("Neo4j写入未返回确认结果")


def seed_neo4j(
    client: Any,
    seed_data: MySQLSeedData,
) -> None:
    constraints = [
        "CREATE CONSTRAINT employee_id_unique IF NOT EXISTS FOR (e:Employee) REQUIRE e.employee_id IS UNIQUE",
        "CREATE CONSTRAINT policy_seed_key_unique IF NOT EXISTS FOR (p:Policy) REQUIRE p.stable_key IS UNIQUE",
        "CREATE CONSTRAINT topic_seed_key_unique IF NOT EXISTS FOR (t:KnowledgeTopic) REQUIRE t.stable_key IS UNIQUE",
    ]
    for cypher in constraints:
        client.run(cypher)

    customer_rows = []
    for key, row in seed_data.customers.items():
        extra = _mysql_json(row.get("extra_data"))
        customer_rows.append({
            "customer_id": int(row["id"]), "stable_key": key,
            "name": str(extra.get("display_name") or key), "risk_level": str(row["risk_level"]),
            "advisor_username": extra.get("advisor_username"),
            "manager_username": extra.get("customer_manager_username"), "namespace": NAMESPACE,
        })
    employee_rows = []
    for key, row in seed_data.employees.items():
        extra = _mysql_json(row.get("extra_data"))
        employee_rows.append({
            "employee_id": int(row["id"]), "stable_key": key,
            "name": str(extra.get("display_name") or key), "employee_role": str(row.get("employee_role") or ""),
            "advisor_level": str(row.get("advisor_level") or ""), "namespace": NAMESPACE,
        })
    product_rows = [
        {
            "product_id": int(row["id"]), "stable_key": code, "product_code": code,
            "product_name": str(row["product_name"]), "risk_level": str(row["risk_level"]),
            "product_type": str(row["product_type"]), "industry": str(row.get("industry") or "未分类"),
            "fund_manager": str(row.get("fund_manager") or "未登记管理人"), "namespace": NAMESPACE,
        }
        for code, row in seed_data.products.items()
    ]
    _neo4j_write(client, "UNWIND $rows AS row MERGE (n:Customer {customer_id: row.customer_id}) SET n += row RETURN count(n) AS touched", {"rows": customer_rows})
    _neo4j_write(client, "UNWIND $rows AS row MERGE (n:Employee {employee_id: row.employee_id}) SET n += row RETURN count(n) AS touched", {"rows": employee_rows})
    _neo4j_write(client, "UNWIND $rows AS row MERGE (n:Product {product_id: row.product_id}) SET n += row RETURN count(n) AS touched", {"rows": product_rows})

    risk_rows = [{"level": level, "namespace": NAMESPACE, "stable_key": f"risk-{level.lower()}"} for level in [f"C{i}" for i in range(1, 6)] + [f"R{i}" for i in range(1, 6)]]
    market_rows = [{"market_name": name, "namespace": NAMESPACE, "stable_key": f"market-{index:02d}"} for index, name in enumerate(MARKETS, start=1)]
    all_industries = list(dict.fromkeys(INDUSTRIES + [row["industry"] for row in product_rows]))
    all_managers = list(dict.fromkeys(MANAGERS + [row["fund_manager"] for row in product_rows]))
    industry_rows = [{"industry_name": name, "namespace": NAMESPACE, "stable_key": f"industry-{index:02d}"} for index, name in enumerate(all_industries, start=1)]
    manager_rows = [{"manager_name": name, "namespace": NAMESPACE, "stable_key": f"manager-{index:02d}"} for index, name in enumerate(all_managers, start=1)]
    policy_rows = [{"title": name, "namespace": NAMESPACE, "stable_key": f"policy-{index:02d}"} for index, name in enumerate(POLICY_NODES, start=1)]
    topic_rows = [{"name": name, "namespace": NAMESPACE, "stable_key": f"topic-{index:02d}"} for index, name in enumerate(TOPICS, start=1)]
    for label, key, rows in [
        ("RiskLevel", "level", risk_rows), ("Market", "market_name", market_rows),
        ("Industry", "industry_name", industry_rows), ("FundManager", "manager_name", manager_rows),
        ("Policy", "stable_key", policy_rows), ("KnowledgeTopic", "stable_key", topic_rows),
    ]:
        _neo4j_write(client, f"UNWIND $rows AS row MERGE (n:{label} {{{key}: row.{key}}}) SET n += row RETURN count(n) AS touched", {"rows": rows})

    _neo4j_write(client, "UNWIND $rows AS row MATCH (c:Customer {customer_id: row.customer_id}), (r:RiskLevel {level: row.risk_level}) MERGE (c)-[x:HAS_RISK_LEVEL {stable_key: row.stable_key}]->(r) SET x.namespace=$namespace RETURN count(x) AS touched", {"rows": customer_rows, "namespace": NAMESPACE})

    employee_id_by_key = {row["stable_key"]: row["employee_id"] for row in employee_rows}
    service_rows = []
    for customer in customer_rows:
        for service_type, username in (("ADVISORY", customer["advisor_username"]), ("OPERATIONS", customer["manager_username"])):
            if username not in employee_id_by_key:
                raise RuntimeError(f"客户{customer['stable_key']}引用了非种子员工：{username}")
            service_rows.append({
                "employee_id": employee_id_by_key[username], "customer_id": customer["customer_id"],
                "service_type": service_type,
                "stable_key": f"serves-{username}-{customer['stable_key']}-{service_type.lower()}",
            })
    _neo4j_write(client, "UNWIND $rows AS row MATCH (e:Employee {employee_id: row.employee_id}), (c:Customer {customer_id: row.customer_id}) MERGE (e)-[x:SERVES {stable_key: row.stable_key}]->(c) SET x.namespace=$namespace, x.service_type=row.service_type RETURN count(x) AS touched", {"rows": service_rows, "namespace": NAMESPACE})

    holding_rows = []
    customer_key_by_id = {int(row["id"]): key for key, row in seed_data.customers.items()}
    for holding in seed_data.holdings:
        code = str(holding["product_code"])
        customer_key = customer_key_by_id[int(holding["customer_id"])]
        holding_rows.append({
            "customer_id": int(holding["customer_id"]), "product_id": int(holding["product_id"]),
            "shares": str(holding["shares"]), "market_value": str(holding["current_value"] or 0),
            "stable_key": f"holding-{customer_key}-{code.lower()}",
        })
    if holding_rows:
        _neo4j_write(client, "UNWIND $rows AS row MATCH (c:Customer {customer_id: row.customer_id}), (p:Product {product_id: row.product_id}) MERGE (c)-[x:INVESTS_IN {stable_key: row.stable_key}]->(p) SET x.namespace=$namespace, x.shares=row.shares, x.market_value=row.market_value RETURN count(x) AS touched", {"rows": holding_rows, "namespace": NAMESPACE})

    product_industries = []
    for product_index, row in enumerate(product_rows):
        code = row["product_code"]
        names = [row["industry"], INDUSTRIES[product_index % len(INDUSTRIES)]]
        for industry_name in dict.fromkeys(names):
            product_industries.append({"code": code, "industry_name": industry_name, "stable_key": f"product-industry-{code.lower()}-{all_industries.index(industry_name):02d}"})
    _neo4j_write(client, "UNWIND $rows AS row MATCH (p:Product {product_code: row.code}), (i:Industry {industry_name: row.industry_name}) MERGE (p)-[x:BELONGS_TO {stable_key: row.stable_key}]->(i) SET x.namespace=$namespace RETURN count(x) AS touched", {"rows": product_industries, "namespace": NAMESPACE})

    manager_links = [{"code": row["product_code"], "manager_name": row["fund_manager"], "stable_key": f"product-manager-{row['product_code'].lower()}"} for row in product_rows]
    _neo4j_write(client, "UNWIND $rows AS row MATCH (p:Product {product_code: row.code}), (m:FundManager {manager_name: row.manager_name}) MERGE (p)-[x:MANAGED_BY {stable_key: row.stable_key}]->(m) SET x.namespace=$namespace RETURN count(x) AS touched", {"rows": manager_links, "namespace": NAMESPACE})

    suitability = []
    minimum_customer_rank = {"R1": 1, "R2": 1, "R3": 2, "R4": 3, "R5": 4}
    for product in product_rows:
        code = product["product_code"]
        for rank in range(minimum_customer_rank[product["risk_level"]], 6):
            suitability.append({"code": code, "level": f"C{rank}", "stable_key": f"suitable-{code.lower()}-c{rank}"})
    _neo4j_write(client, "UNWIND $rows AS row MATCH (p:Product {product_code: row.code}), (r:RiskLevel {level: row.level}) MERGE (p)-[x:SUITABLE_FOR {stable_key: row.stable_key}]->(r) SET x.namespace=$namespace RETURN count(x) AS touched", {"rows": suitability, "namespace": NAMESPACE})

    market_links = []
    for index, industry in enumerate(all_industries):
        for market in (MARKETS[index % len(MARKETS)], MARKETS[(index + 2) % len(MARKETS)]):
            market_links.append({"industry": industry, "market": market, "stable_key": f"industry-market-{index:02d}-{MARKETS.index(market):02d}"})
    _neo4j_write(client, "UNWIND $rows AS row MATCH (i:Industry {industry_name: row.industry}), (m:Market {market_name: row.market}) MERGE (i)-[x:LOCATED_IN {stable_key: row.stable_key}]->(m) SET x.namespace=$namespace RETURN count(x) AS touched", {"rows": market_links, "namespace": NAMESPACE})

    policy_topic_links = [{"policy": f"policy-{(index % len(POLICY_NODES)) + 1:02d}", "topic": f"topic-{index + 1:02d}", "stable_key": f"topic-policy-{index + 1:02d}-a"} for index in range(len(TOPICS))]
    policy_topic_links += [{"policy": f"policy-{((index + 7) % len(POLICY_NODES)) + 1:02d}", "topic": f"topic-{index + 1:02d}", "stable_key": f"topic-policy-{index + 1:02d}-b"} for index in range(len(TOPICS))]
    _neo4j_write(client, "UNWIND $rows AS row MATCH (t:KnowledgeTopic {stable_key: row.topic}), (p:Policy {stable_key: row.policy}) MERGE (t)-[x:GOVERNED_BY {stable_key: row.stable_key}]->(p) SET x.namespace=$namespace RETURN count(x) AS touched", {"rows": policy_topic_links, "namespace": NAMESPACE})

    product_topic_links = []
    for product_index, product in enumerate(product_rows):
        code = product["product_code"]
        for offset in range(3):
            topic_index = (product_index * 5 + offset) % len(TOPICS) + 1
            product_topic_links.append({"code": code, "topic": f"topic-{topic_index:02d}", "stable_key": f"product-topic-{code.lower()}-{topic_index:02d}"})
    _neo4j_write(client, "UNWIND $rows AS row MATCH (p:Product {product_code: row.code}), (t:KnowledgeTopic {stable_key: row.topic}) MERGE (p)-[x:HAS_TOPIC {stable_key: row.stable_key}]->(t) SET x.namespace=$namespace RETURN count(x) AS touched", {"rows": product_topic_links, "namespace": NAMESPACE})

    industry_topic_links = []
    for index, industry in enumerate(all_industries):
        for offset in (0, 11):
            topic_index = (index + offset) % len(TOPICS) + 1
            industry_topic_links.append({"industry": industry, "topic": f"topic-{topic_index:02d}", "stable_key": f"industry-topic-{index:02d}-{topic_index:02d}"})
    _neo4j_write(client, "UNWIND $rows AS row MATCH (i:Industry {industry_name: row.industry}), (t:KnowledgeTopic {stable_key: row.topic}) MERGE (i)-[x:HAS_TOPIC {stable_key: row.stable_key}]->(t) SET x.namespace=$namespace RETURN count(x) AS touched", {"rows": industry_topic_links, "namespace": NAMESPACE})


def inspect_neo4j(client: Any) -> dict[str, int]:
    rows = client.run(
        "CALL () { MATCH (n) RETURN count(n) AS nodes } "
        "CALL () { MATCH ()-[r]->() RETURN count(r) AS relationships } "
        "RETURN nodes, relationships"
    )
    if not rows:
        raise RuntimeError("Neo4j统计查询失败")
    return {"nodes": int(rows[0]["nodes"]), "relationships": int(rows[0]["relationships"])}


def verify_all(
    milvus_client: Any,
    neo4j_client: Any,
    seed_data: MySQLSeedData,
) -> dict[str, Any]:
    inventory = inspect_milvus(milvus_client)
    expected_namespace_counts = {"faq": 0, "product": 0, "policy": 0, "memory": 100}
    errors = []
    for logical_name, details in inventory.items():
        if details["row_count"] < TARGET_COLLECTION_ROWS:
            errors.append(f"{details['collection']}总数不足{TARGET_COLLECTION_ROWS}")
        if logical_name == "memory" and len(details["namespace_keys"]) != expected_namespace_counts["memory"]:
            errors.append("长期记忆命名空间数据应恰为100条")
        if details["namespace_row_count"] != len(details["namespace_keys"]):
            errors.append(f"{details['collection']}命名空间内存在重复stable_key")

    graph_counts = inspect_neo4j(neo4j_client)
    if graph_counts["nodes"] <= 100:
        errors.append("Neo4j总节点数未达到>100")
    if graph_counts["relationships"] <= 200:
        errors.append("Neo4j总关系数未达到>200")
    cross_rows = neo4j_client.run(
        "MATCH (c:Customer) WHERE c.namespace=$namespace RETURN c.stable_key AS stable_key, c.customer_id AS customer_id "
        "UNION ALL MATCH (e:Employee) WHERE e.namespace=$namespace RETURN e.stable_key AS stable_key, e.employee_id AS customer_id "
        "UNION ALL MATCH (p:Product) WHERE p.namespace=$namespace RETURN p.product_code AS stable_key, p.product_id AS customer_id",
        {"namespace": NAMESPACE},
    )
    expected_cross = {(key, int(row["id"])) for key, row in seed_data.customers.items()}
    expected_cross |= {(key, int(row["id"])) for key, row in seed_data.employees.items()}
    expected_cross |= {(code, int(row["id"])) for code, row in seed_data.products.items()}
    actual_cross = {(str(row["stable_key"]), int(row["customer_id"])) for row in cross_rows}
    if actual_cross != expected_cross:
        errors.append("Neo4j核心客户/产品与MySQL稳定键映射不一致")

    graph_holdings = neo4j_client.run(
        "MATCH (c:Customer)-[r:INVESTS_IN]->(p:Product) WHERE r.namespace=$namespace "
        "RETURN c.customer_id AS customer_id, p.product_id AS product_id, r.shares AS shares, r.market_value AS market_value",
        {"namespace": NAMESPACE},
    )
    mysql_holding_keys = {(int(row["customer_id"]), int(row["product_id"])) for row in seed_data.holdings}
    graph_holding_keys = {(int(row["customer_id"]), int(row["product_id"])) for row in graph_holdings}
    if graph_holding_keys != mysql_holding_keys:
        errors.append("Neo4j INVESTS_IN与MySQL种子持仓集合不一致")

    service_rows = neo4j_client.run(
        "MATCH (e:Employee)-[r:SERVES]->(c:Customer) WHERE r.namespace=$namespace "
        "RETURN e.stable_key AS employee_key, c.stable_key AS customer_key, r.service_type AS service_type",
        {"namespace": NAMESPACE},
    )
    expected_services = set()
    for customer_key, row in seed_data.customers.items():
        extra = _mysql_json(row.get("extra_data"))
        expected_services.add((str(extra.get("advisor_username")), customer_key, "ADVISORY"))
        expected_services.add((str(extra.get("customer_manager_username")), customer_key, "OPERATIONS"))
    actual_services = {
        (str(row["employee_key"]), str(row["customer_key"]), str(row["service_type"])) for row in service_rows
    }
    if actual_services != expected_services:
        errors.append("Neo4j SERVES与MySQL客户服务分配不一致")

    if errors:
        raise RuntimeError("验证失败：" + "；".join(errors))
    return {
        "milvus": {name: {"row_count": value["row_count"], "namespace_count": value["namespace_row_count"]} for name, value in inventory.items()},
        "neo4j": graph_counts,
        "mysql_cross_keys": {
            "customers": len(seed_data.customers), "employees": len(seed_data.employees),
            "products": len(seed_data.products), "holdings": len(seed_data.holdings),
        },
    }


def run(mode: str) -> dict[str, Any]:
    seed_data = resolve_mysql_seed_data()
    core_customer_ids = {key: int(seed_data.customers[key]["id"]) for key in CUSTOMERS}
    milvus_client = get_milvus_client()
    inventory = inspect_milvus(milvus_client)

    from app.Base.Client.neo4jClient import Neo4jClient

    with Neo4jClient() as neo4j_client:
        before_graph = inspect_neo4j(neo4j_client)
        if mode == "verify":
            return verify_all(milvus_client, neo4j_client, seed_data)

        plan = build_milvus_plan(inventory, core_customer_ids)
        report: dict[str, Any] = {
            "mode": mode,
            "namespace": NAMESPACE,
            "mysql_cross_keys": {
                "customers": len(seed_data.customers), "employees": len(seed_data.employees),
                "products": len(seed_data.products), "holdings": len(seed_data.holdings),
            },
            "milvus_before": {name: value["row_count"] for name, value in inventory.items()},
            "milvus_planned_inserts": {name: len(items) for name, items in plan.items()},
            "neo4j_before": before_graph,
        }
        if mode == "dry-run":
            return report

        inserted = {}
        for logical_name, items in plan.items():
            inserted[logical_name] = insert_milvus_items(milvus_client, logical_name, items)
        seed_neo4j(neo4j_client, seed_data)
        report["milvus_inserted"] = inserted
        report["verification"] = verify_all(milvus_client, neo4j_client, seed_data)
        return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="幂等追加 Milvus/Neo4j 业务种子数据")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="仅预检和输出计划（默认）")
    modes.add_argument("--apply", action="store_true", help="实际追加种子数据")
    modes.add_argument("--verify", action="store_true", help="只读验证数据量和跨库映射")
    parser.add_argument("--confirm", default="", help="apply必须提供的确认串")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.apply and args.confirm != APPLY_CONFIRMATION:
        raise SystemExit(f"--apply 必须同时提供 --confirm {APPLY_CONFIRMATION}")
    mode = "apply" if args.apply else "verify" if args.verify else "dry-run"
    report = run(mode)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
