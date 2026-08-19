"""智能财富管家真实 MySQL 演示种子。

默认仅输出离线计划；连接预检、写入、校验和回滚均需显式参数。所有种子使用
稳定自然键和独立 namespace，已存在但不属于本 namespace 的同名数据会失败关闭。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from dotenv import load_dotenv


NAMESPACE = "WB-SEED-20260817"
APPLY_CONFIRMATION = "APPLY_WB_SEED_20260817"
ROLLBACK_CONFIRMATION = "ROLLBACK_WB_SEED_20260817"
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CORE_CUSTOMERS = (
    {
        "username": "wb_seed_c1_elderly", "name": "陈秀兰", "birthday": "1966-03-15",
        "customer_level": "普通", "risk_level": "C1", "score": Decimal("28.00"),
        "professional": 0, "assets": Decimal("1200000.00"), "occupation": "退休教师",
        "dimensions": (Decimal("14"), Decimal("7"), Decimal("5"), Decimal("2")),
    },
    {
        "username": "wb_seed_c3_balanced", "name": "张伟", "birthday": "1991-06-18",
        "customer_level": "金卡", "risk_level": "C3", "score": Decimal("58.00"),
        "professional": 0, "assets": Decimal("3500000.00"), "occupation": "互联网产品经理",
        "dimensions": (Decimal("20"), Decimal("16"), Decimal("16"), Decimal("6")),
    },
    {
        "username": "wb_seed_c4_professional", "name": "王建国", "birthday": "1981-05-20",
        "customer_level": "钻石", "risk_level": "C4", "score": Decimal("76.00"),
        "professional": 1, "assets": Decimal("300000000.00"), "occupation": "企业主",
        "dimensions": (Decimal("24"), Decimal("22"), Decimal("24"), Decimal("6")),
    },
    {
        "username": "wb_seed_c5_aggressive", "name": "李明", "birthday": "1988-11-08",
        "customer_level": "白金", "risk_level": "C5", "score": Decimal("88.00"),
        "professional": 0, "assets": Decimal("12000000.00"), "occupation": "资深投资者",
        "dimensions": (Decimal("23"), Decimal("24"), Decimal("28"), Decimal("13")),
    },
)


def _build_customers() -> tuple[dict[str, Any], ...]:
    """生成固定风险分布的180名客户，同时保留需求§11四个核心场景。"""
    targets = {"C1": 36, "C2": 42, "C3": 48, "C4": 36, "C5": 18}
    scores = {"C1": Decimal("28"), "C2": Decimal("43"), "C3": Decimal("58"),
              "C4": Decimal("74"), "C5": Decimal("88")}
    dimensions = {
        "C1": (Decimal("14"), Decimal("7"), Decimal("5"), Decimal("2")),
        "C2": (Decimal("17"), Decimal("11"), Decimal("10"), Decimal("5")),
        "C3": (Decimal("20"), Decimal("16"), Decimal("16"), Decimal("6")),
        "C4": (Decimal("23"), Decimal("21"), Decimal("24"), Decimal("6")),
        "C5": (Decimal("23"), Decimal("24"), Decimal("28"), Decimal("13")),
    }
    result = list(CORE_CUSTOMERS)
    existing = {level: sum(item["risk_level"] == level for item in result) for level in targets}
    sequence = 5
    occupations = ("教师", "工程师", "医生", "企业管理人员", "自由职业者", "会计")
    levels = ("普通", "金卡", "白金", "钻石", "私行")
    surnames = ("赵", "钱", "孙", "李", "周", "吴", "郑", "王", "冯", "陈", "褚", "卫",
                "蒋", "沈", "韩", "杨", "朱", "秦", "许", "何")
    given_names = ("安宁", "嘉诚", "思远", "雨桐", "明轩", "欣怡", "俊杰", "文静", "志强", "晓雯")
    for risk_level, target in targets.items():
        for offset in range(target - existing[risk_level]):
            year = 1954 + ((sequence * 7 + offset) % 48)
            assets = Decimal(str({"C1": 800000, "C2": 1800000, "C3": 4500000,
                                  "C4": 18000000, "C5": 50000000}[risk_level] + offset * 50000))
            result.append({
                "username": f"wb_seed_customer_{sequence:03d}",
                "name": surnames[(sequence - 5) % len(surnames)] + given_names[(sequence - 5) // len(surnames)],
                "birthday": f"{year:04d}-{(offset % 12) + 1:02d}-{(offset % 27) + 1:02d}",
                "customer_level": levels[min(int(risk_level[1]) - 1, 4)],
                "risk_level": risk_level, "score": scores[risk_level],
                "professional": int(risk_level == "C5" and offset % 3 == 0),
                "assets": assets, "occupation": occupations[(sequence + offset) % len(occupations)],
                "dimensions": dimensions[risk_level],
            })
            sequence += 1
    return tuple(result)


CUSTOMERS = _build_customers()


def _validate_customer_display_names(customers: Sequence[Mapping[str, Any]]) -> None:
    """种子客户展示名必须是可读化名，账号自然键不得泄露到前端。"""
    invalid = []
    for customer in customers:
        name = str(customer.get("name", "")).strip()
        if (not name or len(name) < 2 or len(name) > 8
                or re.search(r"\d", name)
                or "客户" in name
                or re.fullmatch(r"[A-Za-z0-9_\-]+", name)):
            invalid.append(f"{customer.get('username')}={name!r}")
    if invalid:
        raise AssertionError("客户展示名不是可读化名: " + ", ".join(invalid[:10]))


_validate_customer_display_names(CUSTOMERS)

CORE_EMPLOYEES = (
    ("wb_seed_advisor", "种子理财顾问", "理财顾问", "高级", "advisor"),
    ("wb_seed_risk", "种子风控专员", "风控专员", None, "risk_officer"),
    ("wb_seed_operator", "种子客户经理", "客户经理", None, "operator"),
    ("wb_seed_admin", "种子业务管理员", "业务管理员", None, "business_admin"),
)


def _build_employees() -> tuple[tuple[str, str, str, str | None, str], ...]:
    result = list(CORE_EMPLOYEES)
    result.extend((f"wb_seed_advisor_{index:02d}", f"种子理财顾问{index:02d}", "理财顾问",
                   ("初级", "中级", "高级")[(index - 2) % 3], "advisor") for index in range(2, 13))
    result.extend((f"wb_seed_operator_{index:02d}", f"种子客户经理{index:02d}", "客户经理", None, "operator")
                  for index in range(2, 7))
    result.extend((f"wb_seed_risk_{index:02d}", f"种子风控专员{index:02d}", "风控专员", None, "risk_officer")
                  for index in range(2, 6))
    result.extend((f"wb_seed_business_{index:02d}", f"种子业务运营{index:02d}", "业务管理员", None, "business_admin")
                  for index in range(1, 4))
    result.extend((f"wb_seed_compliance_{index:02d}", f"种子合规复核{index:02d}", "风控专员", None, "risk_officer")
                  for index in range(1, 3))
    result.append(("wb_seed_admin_02", "种子业务管理员02", "业务管理员", None, "business_admin"))
    if len(result) != 30:
        raise AssertionError("员工种子数量必须为30")
    return tuple(result)


EMPLOYEES = _build_employees()

CORE_PRODUCTS = (
    ("WBSEED-R1-CASH", "稳健现金管理", "银行理财", "R1", "1000.00", "1.0000", "现金管理"),
    ("WBSEED-R2-BOND", "稳健债券组合", "公募基金", "R2", "1000.00", "1.2500", "债券"),
    ("WBSEED-R3-MIX", "平衡混合基金", "公募基金", "R3", "10000.00", "1.6000", "多资产"),
    ("WBSEED-R4-EQUITY", "成长权益精选", "公募基金", "R4", "10000.00", "2.0000", "科技"),
    ("WBSEED-R5-PRIVATE", "企业传承私募", "私募基金", "R5", "1000000.00", "1.0500", "综合"),
)


def _build_products() -> tuple[tuple[str, str, str, str, str, str, str], ...]:
    result = list(CORE_PRODUCTS)
    types = {"R1": "银行理财", "R2": "公募基金", "R3": "公募基金",
             "R4": "公募基金", "R5": "私募基金"}
    navs = {"R1": Decimal("1.0000"), "R2": Decimal("1.2000"), "R3": Decimal("1.5000"),
            "R4": Decimal("2.0000"), "R5": Decimal("1.1000")}
    industries = ("现金管理", "债券", "多资产", "科技", "消费", "医药", "新能源", "综合")
    product_names = {
        "R1": ("安盈现金管理", "日日稳健", "短债添利", "流动性优选", "稳享存款策略"),
        "R2": ("稳享纯债", "固收增强", "利率债优选", "信用债精选", "稳健收益组合"),
        "R3": ("均衡配置", "多资产稳进", "股债平衡", "价值均衡", "全天候配置"),
        "R4": ("成长权益精选", "科技创新成长", "消费升级优选", "医药健康成长", "新能源趋势"),
        "R5": ("量化对冲精选", "企业成长私募", "全球机会策略", "专精特新策略", "绝对收益私募"),
    }
    for risk_number in range(1, 6):
        risk = f"R{risk_number}"
        for index in range(2, 12):
            minimum = "1000000.00" if risk == "R5" else ("10000.00" if risk_number >= 3 else "1000.00")
            base_name = product_names[risk][(index - 2) % len(product_names[risk])]
            series = ((index - 2) // len(product_names[risk])) + 1
            result.append((f"WBSEED-{risk}-{index:03d}", f"{base_name}{series}号", types[risk], risk,
                           minimum, str(navs[risk] + Decimal(index) / Decimal("100")),
                           industries[(risk_number + index) % len(industries)]))
    if len(result) != 55:
        raise AssertionError("产品种子数量必须为55")
    return tuple(result)


PRODUCTS = _build_products()

ROLE_PERMISSIONS = {
    "advisor": ["product:query", "product:recommend", "operation:purchase", "operation:redeem",
                "risk:reassess", "risk:suspicious_report", "data:nl2sql_query"],
    "risk_officer": ["product:query", "risk:suspicious_report", "risk:override", "data:nl2sql_query"],
    "operator": ["product:query", "operation:transfer", "customer:info_update",
                 "risk:suspicious_report", "workorder:create", "data:nl2sql_query"],
    "business_admin": ["risk:override", "data:nl2sql_query"],
}

TABLES = (
    "base_user", "base_role", "base_user_role", "fin_customer_profile", "fin_product",
    "fin_transaction", "fin_holdings", "fin_risk_assessment", "fin_risk_alert",
    "biz_work_order", "conversation_archive", "fin_knowledge_meta", "biz_operation_audit",
    "biz_compliance_evidence", "fin_verified_payee",
)

REQUIRED_COLUMNS = {
    "base_user": {"id", "username", "password_hash", "source_module", "status", "extra_data",
                  "user_type", "employee_role", "advisor_level", "customer_level"},
    "base_role": {"id", "name", "permissions", "source_module"},
    "base_user_role": {"user_id", "role_id", "source_module"},
    "fin_customer_profile": {"customer_id", "advisor_id", "risk_level", "risk_score", "memory_units"},
    "fin_product": {"id", "product_code", "product_name", "risk_level", "description"},
    "fin_transaction": {"id", "customer_id", "employee_id", "trace_id", "idempotency_key",
                        "product_id", "transaction_type", "amount", "status", "transaction_time"},
    "fin_holdings": {"customer_id", "product_id", "shares", "cost_amount", "current_value"},
    "fin_risk_assessment": {"customer_id", "total_score", "risk_level", "answers",
                            "is_professional_investor", "assessment_time", "valid_until"},
    "fin_risk_alert": {"id", "customer_id", "alert_type", "transaction_ids", "handle_note"},
    "biz_work_order": {"customer_id", "intent_summary", "related_alert_id", "handled_by"},
    "conversation_archive": {"id", "session_id"},
    "fin_knowledge_meta": {"title", "source_file", "minio_object_key", "uploaded_by"},
    "biz_operation_audit": {"audit_event_id", "trace_id", "employee_id", "customer_id", "intent"},
    "biz_compliance_evidence": {"event_id", "evidence_id", "customer_id", "product_id",
                                "evidence_type", "verified_by", "trace_id"},
    "fin_verified_payee": {"customer_id", "account_hmac", "account_last4", "payee_name_hmac",
                           "status", "trace_id"},
}

SEED_ENUM_VALUES = {
    "base_user.status": {"active"}, "base_user.user_type": {"CUSTOMER", "EMPLOYEE"},
    "base_user.employee_role": {"理财顾问", "风控专员", "客户经理", "业务管理员"},
    "base_user.advisor_level": {"初级", "中级", "高级"},
    "base_user.customer_level": {"普通", "金卡", "白金", "钻石", "私行"},
    "fin_customer_profile.risk_level": {"C1", "C2", "C3", "C4", "C5"},
    "fin_customer_profile.updated_reason": {"人工触发"},
    "fin_product.product_type": {"公募基金", "私募基金", "银行理财"},
    "fin_product.risk_level": {"R1", "R2", "R3", "R4", "R5"},
    "fin_product.status": {"在售"},
    "fin_transaction.transaction_type": {"申购", "转账"},
    "fin_transaction.status": {"成交", "失败"},
    "fin_risk_assessment.risk_level": {"C1", "C2", "C3", "C4", "C5"},
    "fin_risk_alert.severity": {"medium", "high"},
    "fin_risk_alert.alert_level": {"蓝", "黄"},
    "fin_risk_alert.rule_weight_tier": {"中信号", "强信号"},
    "fin_risk_alert.status": {"待处理", "处理中"},
    "biz_work_order.order_type": {"风控预警", "客户转介"},
    "biz_work_order.source": {"系统生成", "转介工单"},
    "biz_work_order.priority": {"中", "高"},
    "biz_work_order.status": {"待处理", "处理中"},
    "conversation_archive.agent_type": {"customer_service"},
    "conversation_archive.sentiment": {"negative"},
    "conversation_archive.archive_reason": {"会话结束"},
    "fin_knowledge_meta.knowledge_type": {"FAQ", "产品说明书", "政策法规"},
    "fin_knowledge_meta.status": {"待审核"},
    "biz_compliance_evidence.action": {"ISSUED"},
    "fin_verified_payee.status": {"VERIFIED"},
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def validate_seed_password(password: str | None) -> str:
    """Apply 时只接受足够强的环境密码，错误信息不回显原值。"""
    if not password or len(password) < 20:
        raise ValueError("WEALTH_BUTLER_SEED_PASSWORD 至少需要20个字符")
    checks = (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]")
    if not all(re.search(pattern, password) for pattern in checks):
        raise ValueError("WEALTH_BUTLER_SEED_PASSWORD 必须包含大小写字母、数字和符号")
    return password


def render_plan() -> str:
    return "\n".join((
        f"DRY RUN ONLY: namespace={NAMESPACE}; no database connection opened.",
        "Plan: inspect schema and collisions; seed 180 customers, 30 employees and 55 products.",
        "Plan: seed profiles/assessments and linked transactions, holdings, alerts, work orders.",
        "Plan: insert conversation, knowledge metadata, audit, evidence and HMAC-only payee rows.",
        f"Connected preview: --connect-dry-run; apply requires --apply --confirm {APPLY_CONFIRMATION}.",
    ))


def _connect():
    load_dotenv(ROOT / ".env", override=False)
    required = ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("数据库配置缺失: " + ", ".join(missing))
    import pymysql
    return pymysql.connect(
        host=os.environ["DB_HOST"], port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"], charset=os.environ.get("DB_CHARSET", "utf8mb4"),
        autocommit=False, cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=int(os.environ.get("DB_CONNECT_TIMEOUT", "10")),
    )


def inspect_schema(connection: Any) -> dict[str, dict[str, Any]]:
    cursor = connection.cursor()
    result = {}
    try:
        for table in TABLES:
            cursor.execute(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION", (table,),
            )
            columns = [row["COLUMN_NAME"] for row in cursor.fetchall()]
            if columns:
                cursor.execute(f"SELECT COUNT(*) AS count FROM `{table}`")
                rows = int(cursor.fetchone()["count"])
            else:
                rows = None
            result[table] = {"columns": columns, "rows": rows}
        return result
    finally:
        cursor.close()


def inspect_enum_contracts(connection: Any) -> dict[str, list[str]]:
    """只读解析种子涉及表的真实 ENUM 值，供写入前一次性契约检查。"""
    cursor = connection.cursor()
    try:
        placeholders = ",".join(["%s"] * len(TABLES))
        cursor.execute(
            "SELECT TABLE_NAME,COLUMN_NAME,COLUMN_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND DATA_TYPE='enum' AND TABLE_NAME IN (" + placeholders + ") "
            "ORDER BY TABLE_NAME,ORDINAL_POSITION", TABLES,
        )
        result = {}
        for row in cursor.fetchall():
            result[f"{row['TABLE_NAME']}.{row['COLUMN_NAME']}"] = [
                value.replace("''", "'")
                for value in re.findall(r"'((?:''|[^'])*)'", row["COLUMN_TYPE"])
            ]
        return result
    finally:
        cursor.close()


def validate_schema(schema: Mapping[str, Mapping[str, Any]]) -> None:
    problems = []
    for table, required in REQUIRED_COLUMNS.items():
        missing = sorted(required - set(schema.get(table, {}).get("columns", ())))
        if missing:
            problems.append(f"{table}: missing {','.join(missing)}")
    conversation = set(schema["conversation_archive"]["columns"])
    legacy = {"customer_id", "agent_type", "messages", "archive_reason", "start_time", "end_time"}
    documented = {"user_id", "agent_type", "role", "content", "archived_at", "created_at"}
    if not (legacy <= conversation or documented <= conversation):
        problems.append("conversation_archive: unsupported schema variant")
    if problems:
        raise RuntimeError("Schema preflight failed: " + "; ".join(problems))


def validate_enum_contracts(actual: Mapping[str, Sequence[str]]) -> None:
    problems = []
    for field, required_values in SEED_ENUM_VALUES.items():
        missing = sorted(required_values - set(actual.get(field, ())))
        if missing:
            problems.append(f"{field}:{','.join(missing)}")
    if problems:
        raise RuntimeError("ENUM contract preflight failed: " + "; ".join(problems))


def _one(cursor: Any, sql: str, params: tuple[Any, ...]) -> Mapping[str, Any] | None:
    cursor.execute(sql, params)
    return cursor.fetchone()


def _owned_json(raw: Any) -> bool:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(value, Mapping) and value.get("seed_namespace") == NAMESPACE


def preflight(connection: Any) -> dict[str, Any]:
    """检查同名碰撞并生成只含自然键和数量的安全摘要。"""
    schema = inspect_schema(connection)
    validate_schema(schema)
    validate_enum_contracts(inspect_enum_contracts(connection))
    cursor = connection.cursor()
    existing = {"users": 0, "products": 0, "transactions": 0, "evidence": 0}
    try:
        for username in [item["username"] for item in CUSTOMERS] + [item[0] for item in EMPLOYEES]:
            row = _one(cursor, "SELECT extra_data FROM base_user WHERE username=%s", (username,))
            if row:
                if not _owned_json(row["extra_data"]):
                    raise RuntimeError(f"用户名碰撞且非本种子所有: {username}")
                existing["users"] += 1
        for code, *_rest in PRODUCTS:
            row = _one(cursor, "SELECT description FROM fin_product WHERE product_code=%s", (code,))
            if row:
                if f"[{NAMESPACE}]" not in str(row["description"] or ""):
                    raise RuntimeError(f"产品编码碰撞且非本种子所有: {code}")
                existing["products"] += 1
        cursor.execute(
            "SELECT COUNT(*) AS count FROM fin_transaction WHERE idempotency_key LIKE %s",
            (NAMESPACE + ":%",),
        )
        existing["transactions"] = int(cursor.fetchone()["count"])
        cursor.execute(
            "SELECT COUNT(*) AS count FROM biz_compliance_evidence WHERE event_id LIKE %s",
            (NAMESPACE + ":%",),
        )
        existing["evidence"] = int(cursor.fetchone()["count"])
        return {"schema": schema, "existing_seed": existing}
    finally:
        cursor.close()


def _insert_once(cursor: Any, table: str, key_sql: str, key_params: tuple[Any, ...],
                 values: Mapping[str, Any]) -> bool:
    if _one(cursor, f"SELECT 1 AS present FROM `{table}` WHERE {key_sql} LIMIT 1", key_params):
        return False
    columns = list(values)
    cursor.execute(
        f"INSERT INTO `{table}` ({','.join(f'`{name}`' for name in columns)}) "
        f"VALUES ({','.join(['%s'] * len(columns))})",
        tuple(values[name] for name in columns),
    )
    return True


def _id_map(cursor: Any, table: str, natural_column: str, keys: Sequence[str]) -> dict[str, int]:
    placeholders = ",".join(["%s"] * len(keys))
    cursor.execute(
        f"SELECT id, `{natural_column}` AS natural_key FROM `{table}` "
        f"WHERE `{natural_column}` IN ({placeholders})", tuple(keys),
    )
    result = {str(row["natural_key"]): int(row["id"]) for row in cursor.fetchall()}
    missing = sorted(set(keys) - set(result))
    if missing:
        raise RuntimeError(f"自然键回查失败: {table}:{','.join(missing)}")
    return result


def apply_seed(connection: Any, password: str) -> dict[str, Any]:
    """在单一事务中幂等插入；绝不更新已有记录。"""
    validate_seed_password(password)
    preflight(connection)
    from app.Base.Service.authService import AuthService
    from app.WealthButler.Utils.payeeFingerprint import fingerprint, normalize_account, normalize_name

    inserted = {table: 0 for table in TABLES}
    cursor = connection.cursor()
    try:
        password_hash = AuthService.hash_password(password)
        advisor_keys = [item[0] for item in EMPLOYEES if item[4] == "advisor"]
        manager_keys = [item[0] for item in EMPLOYEES if item[4] == "operator"]
        for customer_index, customer in enumerate(CUSTOMERS):
            extra = {
                "seed_namespace": NAMESPACE, "display_name": customer["name"],
                "birthday": customer["birthday"], "occupation": customer["occupation"],
                "total_assets": str(customer["assets"]),
                "digital_ability": "弱" if customer["risk_level"] == "C1" else "正常",
                "advisor_username": advisor_keys[customer_index % len(advisor_keys)],
                "customer_manager_username": manager_keys[customer_index % len(manager_keys)],
            }
            values = {
                "username": customer["username"], "email": customer["username"] + "@seed.invalid",
                "password_hash": password_hash, "source_module": "fin", "status": "active",
                "extra_data": _json(extra), "user_type": "CUSTOMER", "employee_role": None,
                "advisor_level": None, "customer_level": customer["customer_level"],
            }
            inserted["base_user"] += _insert_once(cursor, "base_user", "username=%s", (customer["username"],), values)
        for username, display_name, employee_role, advisor_level, _role in EMPLOYEES:
            values = {
                "username": username, "email": username + "@seed.invalid", "password_hash": password_hash,
                "source_module": "fin", "status": "active",
                "extra_data": _json({"seed_namespace": NAMESPACE, "display_name": display_name}),
                "user_type": "EMPLOYEE", "employee_role": employee_role,
                "advisor_level": advisor_level, "customer_level": "普通",
            }
            inserted["base_user"] += _insert_once(cursor, "base_user", "username=%s", (username,), values)

        user_keys = [item["username"] for item in CUSTOMERS] + [item[0] for item in EMPLOYEES]
        users = _id_map(cursor, "base_user", "username", user_keys)
        for username, _display, _employee_role, _level, role_name in EMPLOYEES:
            role = _one(cursor, "SELECT id, permissions FROM base_role WHERE name=%s AND source_module=%s", (role_name, "fin"))
            if not role:
                raise RuntimeError(f"缺少财富管家内置角色: {role_name}")
            permissions = json.loads(role["permissions"]) if isinstance(role["permissions"], str) else role["permissions"]
            missing = sorted(set(ROLE_PERMISSIONS[role_name]) - set(permissions or []))
            if missing:
                raise RuntimeError(f"角色权限不完整: {role_name}:{','.join(missing)}")
            inserted["base_user_role"] += _insert_once(
                cursor, "base_user_role", "user_id=%s AND role_id=%s AND source_module=%s",
                (users[username], role["id"], "fin"),
                {"user_id": users[username], "role_id": role["id"], "source_module": "fin",
                 "granted_by": users["wb_seed_operator"]},
            )

        for code, name, product_type, risk, minimum, nav, industry in PRODUCTS:
            values = {
                "product_code": code, "product_name": name, "product_type": product_type,
                "risk_level": risk, "min_investment": minimum, "redemption_period_days": 3,
                "nav": nav, "nav_date": "2026-08-15", "industry": industry,
                "fund_manager": "种子基金管理人", "status": "在售",
                "description": f"[{NAMESPACE}] 用于端到端验收的{risk}级演示产品。",
            }
            inserted["fin_product"] += _insert_once(cursor, "fin_product", "product_code=%s", (code,), values)
        products = _id_map(cursor, "fin_product", "product_code", [item[0] for item in PRODUCTS])

        for customer_index, customer in enumerate(CUSTOMERS):
            customer_id = users[customer["username"]]
            d1, d2, d3, d4 = customer["dimensions"]
            from app.WealthButler.Service.riskAssessService import RiskAssessService

            target_score = {"C1": 2, "C2": 4, "C3": 6, "C4": 8, "C5": 10}[customer["risk_level"]]
            selected = {}
            stored_answers = [{"seed_namespace": NAMESPACE}]
            for question in RiskAssessService.get_questionnaire():
                option_index = min(
                    range(len(question["options"])),
                    key=lambda index: abs(question["options"][index]["score"] - target_score),
                )
                selected[question["id"]] = option_index
                stored_answers.append({
                    "question_no": question["id"],
                    "option": chr(ord("A") + option_index),
                    "option_index": option_index,
                    "score": question["options"][option_index]["score"],
                })
            calculated_score, calculated_level = RiskAssessService.calculate_risk_level(selected)
            if calculated_level != customer["risk_level"]:
                raise RuntimeError(
                    f"风评种子不可复算: {customer['username']} expected={customer['risk_level']} actual={calculated_level}"
                )
            profile = {
                "customer_id": customer_id,
                "advisor_id": users[advisor_keys[customer_index % len(advisor_keys)]],
                "risk_level": calculated_level,
                "risk_score": calculated_score, "dimension1_score": d1, "dimension2_score": d2,
                "dimension3_score": d3, "dimension4_score": d4, "fm_flags": _json([]),
                "asset_allocation": _json({"total_assets": str(customer["assets"]), "currency": "CNY"}),
                "product_preference": _json({"seed_namespace": NAMESPACE, "risk": customer["risk_level"]}),
                "memory_units": _json([{"unit_id": NAMESPACE + ":" + customer["username"],
                    "tag": "验收客户", "content": customer["name"] + "端到端验收画像", "status": "active"}]),
                "confidence_score": "0.950", "updated_reason": "人工触发",
            }
            inserted["fin_customer_profile"] += _insert_once(
                cursor, "fin_customer_profile", "customer_id=%s", (customer_id,), profile,
            )
            assessment = {
                "customer_id": customer_id, "total_score": calculated_score,
                "risk_level": calculated_level, "answers": _json(stored_answers),
                "is_professional_investor": customer["professional"],
                "assessment_time": "2026-08-15 10:00:00", "valid_until": "2027-08-15 10:00:00",
            }
            inserted["fin_risk_assessment"] += _insert_once(
                cursor, "fin_risk_assessment", "customer_id=%s AND JSON_CONTAINS(answers,%s)",
                (customer_id, _json({"seed_namespace": NAMESPACE})), assessment,
            )

        advisor = users["wb_seed_advisor"]
        operator = users["wb_seed_operator"]
        transaction_specs = (
            ("normal-c3-r3", "wb_seed_c3_balanced", advisor, "WBSEED-R3-MIX", "申购", "100000.00", "62500.0000", "1.6000", "成交", None, "2026-08-14 10:30:00"),
            ("c1-existing-r3", "wb_seed_c1_elderly", advisor, "WBSEED-R3-MIX", "申购", "200000.00", "125000.0000", "1.6000", "成交", None, "2026-07-10 10:00:00"),
            ("c1-r5-rejected", "wb_seed_c1_elderly", advisor, "WBSEED-R5-PRIVATE", "申购", "1000000.00", None, "1.0500", "失败", "SUITABILITY_REJECTED", "2026-08-15 11:00:00"),
            ("c4-professional-r5", "wb_seed_c4_professional", advisor, "WBSEED-R5-PRIVATE", "申购", "1000000.00", "952380.9524", "1.0500", "成交", None, "2026-08-15 14:00:00"),
            ("c5-r4", "wb_seed_c5_aggressive", advisor, "WBSEED-R4-EQUITY", "申购", "600000.00", "300000.0000", "2.0000", "成交", None, "2026-08-12 15:00:00"),
            ("c5-suspicious-transfer", "wb_seed_c5_aggressive", operator, None, "转账", "680000.00", None, None, "成交", None, "2026-08-15 02:15:00"),
        )
        for suffix, customer_key, employee_id, product_code, tx_type, amount, shares, nav, status, failure, tx_time in transaction_specs:
            values = {
                "customer_id": users[customer_key], "employee_id": employee_id,
                "trace_id": f"{NAMESPACE}:trace:{suffix}", "idempotency_key": f"{NAMESPACE}:{suffix}",
                "product_id": products[product_code] if product_code else None,
                "transaction_type": tx_type, "amount": amount, "shares": shares, "nav": nav,
                "fee": "0.00", "is_cash": 0,
                "counterparty_account": "WBSEED-FAKE-0001" if tx_type == "转账" else None,
                "counterparty_name": "种子演示收款方" if tx_type == "转账" else None,
                "counterparty_region": "高风险地区-演示" if tx_type == "转账" else None,
                "payer_account_name": "第三方演示付款人" if tx_type == "转账" else None,
                "device_fingerprint": NAMESPACE + ":device-1", "channel": "APP", "status": status,
                "failure_code": failure, "failure_reason": "适当性等级不匹配" if failure else None,
                "transaction_time": tx_time,
            }
            inserted["fin_transaction"] += _insert_once(
                cursor, "fin_transaction", "idempotency_key=%s", (values["idempotency_key"],), values,
            )
        tx_ids = _id_map(cursor, "fin_transaction", "idempotency_key", [NAMESPACE + ":" + row[0] for row in transaction_specs])

        holdings = (
            ("wb_seed_c1_elderly", "WBSEED-R3-MIX", "100000.0000", "200000.00", "160000.00", "-40000.00", "-0.2000"),
            ("wb_seed_c3_balanced", "WBSEED-R2-BOND", "160000.0000", "190000.00", "200000.00", "10000.00", "0.0526"),
            ("wb_seed_c3_balanced", "WBSEED-R3-MIX", "62500.0000", "100000.00", "100000.00", "0.00", "0.0000"),
            ("wb_seed_c4_professional", "WBSEED-R5-PRIVATE", "952380.9524", "1000000.00", "1000000.00", "0.00", "0.0000"),
            ("wb_seed_c5_aggressive", "WBSEED-R4-EQUITY", "300000.0000", "600000.00", "600000.00", "0.00", "0.0000"),
        )
        for customer_key, product_code, shares, cost, value, pnl, ratio in holdings:
            values = {"customer_id": users[customer_key], "product_id": products[product_code],
                      "shares": shares, "cost_amount": cost, "current_value": value,
                      "profit_loss": pnl, "profit_ratio": ratio}
            inserted["fin_holdings"] += _insert_once(
                cursor, "fin_holdings", "customer_id=%s AND product_id=%s",
                (values["customer_id"], values["product_id"]), values,
            )

        # 其余176名客户各生成一笔与风险等级相符的成交及一份算术一致持仓。
        core_usernames = {item["username"] for item in CORE_CUSTOMERS}
        product_by_risk = {risk: [item for item in PRODUCTS if item[3] == risk]
                           for risk in ("R1", "R2", "R3", "R4", "R5")}
        bulk_tx_ids = {}
        for index, customer in enumerate(CUSTOMERS):
            if customer["username"] in core_usernames:
                continue
            risk_number = int(customer["risk_level"][1])
            product_spec = product_by_risk[f"R{risk_number}"][index % len(product_by_risk[f"R{risk_number}"])]
            product_code, _name, _type, _risk, _minimum, nav_text, _industry = product_spec
            nav_value = Decimal(nav_text)
            amount = max(Decimal(_minimum), min(customer["assets"] * Decimal("0.05"), Decimal("800000")))
            amount = amount.quantize(Decimal("0.01"))
            shares = (amount / nav_value).quantize(Decimal("0.0001"))
            current_value = (shares * nav_value).quantize(Decimal("0.01"))
            suffix = "portfolio-" + customer["username"]
            tx_values = {
                "customer_id": users[customer["username"]],
                "employee_id": users[advisor_keys[index % len(advisor_keys)]],
                "trace_id": f"{NAMESPACE}:trace:{suffix}", "idempotency_key": f"{NAMESPACE}:{suffix}",
                "product_id": products[product_code], "transaction_type": "申购", "amount": amount,
                "shares": shares, "nav": nav_value, "fee": "0.00", "is_cash": 0,
                "device_fingerprint": f"{NAMESPACE}:device-{index % 24:02d}", "channel": "APP",
                "status": "成交", "transaction_time": f"2026-08-{(index % 14) + 1:02d} 10:30:00",
            }
            inserted["fin_transaction"] += _insert_once(
                cursor, "fin_transaction", "idempotency_key=%s", (tx_values["idempotency_key"],), tx_values,
            )
            tx_row = _one(cursor, "SELECT id FROM fin_transaction WHERE idempotency_key=%s",
                          (tx_values["idempotency_key"],))
            bulk_tx_ids[customer["username"]] = int(tx_row["id"])
            holding_values = {
                "customer_id": users[customer["username"]], "product_id": products[product_code],
                "shares": shares, "cost_amount": amount, "current_value": current_value,
                "profit_loss": current_value - amount,
                "profit_ratio": ((current_value - amount) / amount).quantize(Decimal("0.0001")),
            }
            inserted["fin_holdings"] += _insert_once(
                cursor, "fin_holdings", "customer_id=%s AND product_id=%s",
                (holding_values["customer_id"], holding_values["product_id"]), holding_values,
            )

        alert_values = {
            "customer_id": users["wb_seed_c5_aggressive"], "alert_type": "RW-011", "alert_level": "黄",
            "rule_id": "RW-011", "rule_name": "高风险地区交易", "severity": "high",
            "rule_weight_tier": "强信号",
            "transaction_ids": _json([tx_ids[NAMESPACE + ":c5-suspicious-transfer"]]),
            "related_transaction_id": tx_ids[NAMESPACE + ":c5-suspicious-transfer"],
            "trigger_details": _json({"seed_namespace": NAMESPACE, "scenario": "night-high-risk-region"}),
            "confidence": "0.650", "is_repeat": 1, "repeat_trigger_count": 3,
            "status": "处理中", "handle_note": f"[{NAMESPACE}] 高风险地区夜间大额转账演示",
            "handled_by": users["wb_seed_risk"],
        }
        inserted["fin_risk_alert"] += _insert_once(
            cursor, "fin_risk_alert", "customer_id=%s AND alert_type=%s AND handle_note=%s",
            (alert_values["customer_id"], alert_values["alert_type"], alert_values["handle_note"]), alert_values,
        )
        alert = _one(cursor, "SELECT id FROM fin_risk_alert WHERE customer_id=%s AND alert_type=%s AND handle_note=%s",
                     (alert_values["customer_id"], alert_values["alert_type"], alert_values["handle_note"]))
        work_values = {"order_no": "WBSEED-WO-RISK-001", "order_type": "风控预警", "source": "系统生成",
                       "customer_id": alert_values["customer_id"],
                       "customer_name": next(item["name"] for item in CUSTOMERS if item["username"] == "wb_seed_c5_aggressive"),
                       "title": "高风险转账复核",
                       "description": "夜间大额转账且对手方位于高风险地区，需要人工复核。",
                       "intent_summary": f"[{NAMESPACE}] 复核高风险地区夜间大额转账",
                       "related_alert_id": alert["id"], "handled_by": users["wb_seed_risk"],
                       "status": "处理中", "priority": "高"}
        inserted["biz_work_order"] += _insert_once(cursor, "biz_work_order", "intent_summary=%s",
                                                    (work_values["intent_summary"],), work_values)

        # 约10%的客户形成规则可解释的预警，其中一半进入人工工单。
        alert_customers = [customer for index, customer in enumerate(CUSTOMERS) if index % 10 == 9]
        for alert_index, customer in enumerate(alert_customers, start=1):
            customer_id = users[customer["username"]]
            related_tx_id = bulk_tx_ids[customer["username"]]
            note = f"[{NAMESPACE}] 批量验收预警{alert_index:02d}"
            values = {
                "customer_id": customer_id, "rule_id": "RW-003", "rule_name": "交易频率异常",
                "severity": "medium", "confidence": "0.500",
                "trigger_details": _json({"seed_namespace": NAMESPACE, "scenario": "frequency-demo"}),
                "related_transaction_id": related_tx_id, "alert_type": "RW-003", "alert_level": "蓝",
                "rule_weight_tier": "中信号", "transaction_ids": _json([related_tx_id]),
                "is_repeat": 0, "repeat_trigger_count": 1, "status": "待处理", "handle_note": note,
            }
            inserted["fin_risk_alert"] += _insert_once(
                cursor, "fin_risk_alert", "customer_id=%s AND alert_type=%s AND handle_note=%s",
                (customer_id, "RW-003", note), values,
            )
            if alert_index <= 9:
                alert_row = _one(cursor, "SELECT id FROM fin_risk_alert WHERE customer_id=%s AND handle_note=%s",
                                 (customer_id, note))
                summary = f"[{NAMESPACE}] 复核批量验收预警{alert_index:02d}"
                order_values = {
                    "order_no": f"WBSEED-WO-{alert_index + 1:03d}", "order_type": "风控预警",
                    "source": "系统生成", "customer_id": customer_id,
                    "customer_name": customer["name"], "title": "交易频率异常复核",
                    "description": "种子数据构造的可解释规则预警，需要人工复核。", "priority": "中",
                    "status": "待处理", "related_entity_type": "risk_alert",
                    "related_entity_id": alert_row["id"], "related_alert_id": alert_row["id"],
                    "intent_summary": summary,
                }
                inserted["biz_work_order"] += _insert_once(
                    cursor, "biz_work_order", "intent_summary=%s", (summary,), order_values,
                )

        # 为每名理财顾问构造一个符合其业务范围、且客户关联完整的待办事项。
        advisor_scenarios = (
            ("申购服务", "客户明确申请申购与本人风险等级匹配的产品，请顾问确认投资目标和金额。"),
            ("赎回服务", "客户明确申请部分赎回现有持仓，请顾问确认份额和到账安排。"),
            ("产品配置", "客户希望基于有效风险测评获得资产配置和产品组合建议。"),
        )
        for advisor_index, advisor_key in enumerate(advisor_keys, start=1):
            customer = CUSTOMERS[advisor_index - 1]
            scenario, description = advisor_scenarios[(advisor_index - 1) % len(advisor_scenarios)]
            summary = f"[{NAMESPACE}] {scenario}：{customer['name']}"
            order_values = {
                "order_no": f"WBSEED-WO-ADVISOR-{advisor_index:03d}",
                "order_type": "客户转介", "source": "转介工单",
                "customer_id": users[customer["username"]], "customer_name": customer["name"],
                "title": scenario, "description": description, "intent_summary": summary,
                "status": "待处理", "priority": "中",
                "handle_records": _json([{
                    "action": "客服Agent转介", "target_role": "理财顾问",
                    "assigned_advisor": advisor_key, "seed_namespace": NAMESPACE,
                }]),
            }
            inserted["biz_work_order"] += _insert_once(
                cursor, "biz_work_order", "order_no=%s", (order_values["order_no"],), order_values,
            )

        conversation_columns = set(inspect_schema(connection)["conversation_archive"]["columns"])
        session_id = NAMESPACE + ":conversation:c1-fraud"
        if "customer_id" in conversation_columns:
            conversation_values = {
                "session_id": session_id, "customer_id": users["wb_seed_c1_elderly"],
                "agent_type": "customer_service", "message_count": 2,
                "messages": _json([{"role": "user", "content": "陌生人让我转账怎么办"},
                                   {"role": "assistant", "content": "请暂停操作并核实身份"}]),
                "summary": f"[{NAMESPACE}] 防诈骗演示", "sentiment": "negative", "resolved": 1,
                "transferred_to_human": 0, "archive_reason": "会话结束",
                "start_time": "2026-08-15 09:00:00", "end_time": "2026-08-15 09:02:00",
            }
        else:
            conversation_values = {
                "session_id": session_id, "user_id": users["wb_seed_c1_elderly"], "agent_type": "客服",
                "role": "user", "content": f"[{NAMESPACE}] 陌生人让我转账怎么办",
                "tool_calls": _json([]), "archived_at": "2026-08-15 09:02:00",
                "created_at": "2026-08-15 09:00:00",
            }
        inserted["conversation_archive"] += _insert_once(
            cursor, "conversation_archive", "session_id=%s", (session_id,), conversation_values,
        )

        knowledge = (
            ("FAQ", "防诈骗转账核验", "fin_faq_collection", "faq/fraud-prevention.md"),
            ("产品说明书", "企业传承私募产品说明", "fin_product_collection", "product/r5-private.md"),
            ("政策法规", "投资者适当性管理规则", "fin_policy_collection", "policy/suitability.md"),
        )
        for kind, title, collection, object_suffix in knowledge:
            full_title = f"[{NAMESPACE}] {title}"
            values = {"knowledge_type": kind, "title": full_title,
                      "collection_name": collection, "source": f"{NAMESPACE}验收素材", "version": "1.0",
                      "file_path": f"{NAMESPACE}/{object_suffix}", "chunk_count": 0,
                      "source_file": f"{NAMESPACE}-{object_suffix.rsplit('/', 1)[-1]}",
                      "milvus_collection": collection, "milvus_pk": None,
                      "minio_object_key": f"{NAMESPACE}/{object_suffix}", "status": "待审核",
                      "uploaded_by": users["wb_seed_operator"]}
            inserted["fin_knowledge_meta"] += _insert_once(cursor, "fin_knowledge_meta", "title=%s", (full_title,), values)

        audit_values = {
            "audit_event_id": NAMESPACE + ":audit:c1-r5-rejected",
            "trace_id": NAMESPACE + ":trace:c1-r5-rejected", "employee_id": advisor,
            "customer_id": users["wb_seed_c1_elderly"], "intent": "purchase",
            "parameter_names": _json(["customer_id", "product_id", "amount"]),
            "success": 0, "result_code": "REJECTED", "failure_code": "SUITABILITY_REJECTED",
            "failure_reason": "适当性等级不匹配",
        }
        inserted["biz_operation_audit"] += _insert_once(cursor, "biz_operation_audit", "audit_event_id=%s",
                                                         (audit_values["audit_event_id"],), audit_values)

        evidence_contracts = (
            ("risk-disclosure", "RISK_DISCLOSURE_SIGNED",
             "minio://fin-compliance-evidence/wb-seed/20260817/evidence/c4-professional-r5-private-risk-disclosure-v1.json",
             "9c7759d99f7f007bdb9af3ff77487766fdbe31c5e38c6b6af8338919119f9027"),
            ("risk-notification", "RISK_NOTIFICATION_ACKNOWLEDGED",
             "minio://fin-compliance-evidence/wb-seed/20260817/evidence/c4-professional-r5-private-risk-notification-v1.json",
             "8f1a3234b44a10f05e99cdeb93768c00673d13e08140e14e2c65852d0f835f48"),
            ("double-record", "DOUBLE_RECORD_COMPLETED",
             "minio://fin-compliance-evidence/wb-seed/20260817/evidence/c4-professional-r5-private-double-record-v1.json",
             "794fa8089e3f1344fac126d317d58c89ec99a97244cf40ef4a323f7e251d9e09"),
        )
        for suffix, evidence_type, artifact_uri, artifact_sha256 in evidence_contracts:
            event_id = f"{NAMESPACE}:evidence:{suffix}"
            evidence_values = {
                "event_id": event_id, "evidence_id": event_id, "action": "ISSUED",
                "customer_id": users["wb_seed_c4_professional"],
                "product_id": products["WBSEED-R5-PRIVATE"], "evidence_type": evidence_type,
                "artifact_uri": artifact_uri, "artifact_sha256": artifact_sha256,
                "completed_at": "2026-08-15 13:55:00", "valid_until": "2027-08-15 13:55:00",
                "verified_by": users["wb_seed_risk"], "verification_method": "SEED_DEMO",
                "trace_id": NAMESPACE + ":trace:c4-professional-r5",
                "metadata": _json({"seed_namespace": NAMESPACE, "purpose": "e2e"}),
            }
            inserted["biz_compliance_evidence"] += _insert_once(
                cursor, "biz_compliance_evidence", "event_id=%s", (event_id,), evidence_values,
            )

        hmac_secret = os.environ.get("WEALTH_BUTLER_PAYEE_HMAC_KEY")
        if not hmac_secret or len(hmac_secret.encode()) < 32:
            raise RuntimeError("WEALTH_BUTLER_PAYEE_HMAC_KEY 未配置或不足32字节")
        payee_customers = (CUSTOMERS[0], CUSTOMERS[1], *CUSTOMERS[4:22])
        for payee_index, customer in enumerate(payee_customers, start=1):
            payee_customer = users[customer["username"]]
            fake_account = f"WBSEED{payee_index:012d}"
            fake_name = f"种子演示收款方{payee_index:02d}"
            account_hmac = fingerprint(hmac_secret, "account", payee_customer, normalize_account(fake_account))
            payee_values = {
                "customer_id": payee_customer, "account_hmac": account_hmac,
                "account_last4": fake_account[-4:],
                "payee_name_hmac": fingerprint(hmac_secret, "name", payee_customer, normalize_name(fake_name)),
                "verification_method": "SEED_DEMO", "status": "VERIFIED",
                "verified_by": users["wb_seed_operator"], "verified_at": "2026-08-15 10:00:00",
                "valid_until": "2027-08-15 10:00:00",
                "trace_id": f"{NAMESPACE}:payee:{payee_index:02d}",
            }
            inserted["fin_verified_payee"] += _insert_once(
                cursor, "fin_verified_payee", "customer_id=%s AND account_hmac=%s",
                (payee_customer, account_hmac), payee_values,
            )
        connection.commit()
        return {"inserted": inserted, "ids": {"users": users, "products": products}}
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def verify_seed(connection: Any, password: str | None = None) -> dict[str, Any]:
    preflight_result = preflight(connection)
    cursor = connection.cursor()
    try:
        users = _id_map(cursor, "base_user", "username",
                        [item["username"] for item in CUSTOMERS] + [item[0] for item in EMPLOYEES])
        products = _id_map(cursor, "fin_product", "product_code", [item[0] for item in PRODUCTS])
        checks = {}
        customer_ids = tuple(users[item["username"]] for item in CUSTOMERS)
        placeholders = ",".join(["%s"] * len(customer_ids))
        cursor.execute("SELECT COUNT(*) AS count FROM fin_customer_profile WHERE customer_id IN (" +
                       placeholders + ")", customer_ids)
        checks["profiles"] = int(cursor.fetchone()["count"]) == len(CUSTOMERS)
        cursor.execute(
            "SELECT COUNT(*) AS count FROM base_user c "
            "JOIN base_user a ON a.username=JSON_UNQUOTE(JSON_EXTRACT(c.extra_data,'$.advisor_username')) "
            "JOIN base_user m ON m.username=JSON_UNQUOTE(JSON_EXTRACT(c.extra_data,'$.customer_manager_username')) "
            "WHERE c.id IN (" + placeholders + ") AND a.user_type='EMPLOYEE' AND a.employee_role='理财顾问' "
            "AND m.user_type='EMPLOYEE' AND m.employee_role='客户经理'",
            customer_ids,
        )
        checks["customer_employee_links"] = int(cursor.fetchone()["count"]) == len(CUSTOMERS)
        cursor.execute("SELECT COUNT(*) AS count FROM fin_risk_assessment WHERE customer_id IN (" +
                       placeholders + ") AND valid_until > assessment_time", customer_ids)
        checks["assessments"] = int(cursor.fetchone()["count"]) >= len(CUSTOMERS)
        cursor.execute("SELECT COUNT(*) AS count FROM fin_transaction WHERE idempotency_key LIKE %s",
                       (NAMESPACE + ":%",))
        checks["transactions"] = int(cursor.fetchone()["count"]) == len(CUSTOMERS) + 2
        cursor.execute(
            "SELECT COUNT(*) AS count FROM fin_holdings h JOIN fin_product p ON p.id=h.product_id "
            "WHERE h.customer_id IN (" + placeholders + ") AND ABS(h.current_value-h.shares*p.nav) < 0.02",
            customer_ids,
        )
        checks["holding_arithmetic"] = int(cursor.fetchone()["count"]) == len(CUSTOMERS) + 1
        cursor.execute("SELECT COUNT(*) AS count FROM biz_compliance_evidence WHERE event_id LIKE %s",
                       (NAMESPACE + ":%",))
        checks["compliance_evidence"] = int(cursor.fetchone()["count"]) == 3
        cursor.execute("SELECT COUNT(*) AS count FROM fin_verified_payee WHERE trace_id LIKE %s AND status='VERIFIED'",
                       (NAMESPACE + ":payee:%",))
        checks["verified_payee"] = int(cursor.fetchone()["count"]) == 20
        cursor.execute("SELECT COUNT(*) AS count FROM fin_risk_alert WHERE handle_note LIKE %s",
                       (f"[{NAMESPACE}]%",))
        checks["risk_alerts"] = int(cursor.fetchone()["count"]) == 19
        cursor.execute("SELECT COUNT(*) AS count FROM biz_work_order WHERE intent_summary LIKE %s",
                       (f"[{NAMESPACE}]%",))
        checks["work_orders"] = int(cursor.fetchone()["count"]) == 22
        cursor.execute("SELECT COUNT(*) AS count FROM base_user_role WHERE user_id IN (" +
                       ",".join(["%s"] * len(EMPLOYEES)) + ") AND source_module='fin'",
                       tuple(users[item[0]] for item in EMPLOYEES))
        checks["employee_roles"] = int(cursor.fetchone()["count"]) >= len(EMPLOYEES)
        if password is not None:
            from app.Base.Service.authService import AuthService
            cursor.execute("SELECT password_hash,status FROM base_user WHERE username LIKE 'wb_seed_%'")
            rows = cursor.fetchall()
            checks["credentials_valid"] = len(rows) == len(CUSTOMERS) + len(EMPLOYEES) and all(
                row["status"] == "active" and AuthService.verify_password(password, row["password_hash"])
                for row in rows
            )
            auth_cases = {
                "wb_seed_c1_elderly": ("CUSTOMER", None, (), ("operation:purchase",)),
                "wb_seed_advisor": ("EMPLOYEE", "理财顾问", ("operation:purchase",), ("operation:transfer", "risk:override")),
                "wb_seed_risk": ("EMPLOYEE", "风控专员", ("risk:override",), ("operation:purchase", "operation:transfer")),
                "wb_seed_operator": ("EMPLOYEE", "客户经理", ("operation:transfer",), ("operation:purchase", "risk:override")),
                "wb_seed_admin": ("EMPLOYEE", "业务管理员", ("risk:override", "data:nl2sql_query"), ("operation:purchase", "operation:transfer")),
            }
            auth_results = {}
            for username, (user_type, employee_role, allowed, denied) in auth_cases.items():
                login_ok, user, _access, _refresh, _message = AuthService.login(username, password)
                identity = _one(cursor, "SELECT user_type,employee_role FROM base_user WHERE username=%s",
                                (username,))
                identity_ok = bool(identity and identity["user_type"] == user_type and
                                   identity["employee_role"] == employee_role)
                permission_ok = bool(user and all(AuthService.has_permission(user.id, item, "fin") for item in allowed)
                                     and all(not AuthService.has_permission(user.id, item, "fin") for item in denied))
                auth_results[username] = {"login": bool(login_ok), "identity": identity_ok,
                                          "permissions": permission_ok}
            checks["auth_matrix"] = all(all(item.values()) for item in auth_results.values())
        else:
            auth_results = {}
        checks["all"] = all(checks.values())
        if not checks["all"]:
            raise RuntimeError("种子一致性校验失败: " + ",".join(name for name, ok in checks.items() if not ok))
        return {"checks": checks, "auth": auth_results,
                "row_counts": {name: data["rows"] for name, data in preflight_result["schema"].items()},
                "ids": {"users": users, "products": products}}
    finally:
        cursor.close()


def rollback_seed(connection: Any) -> dict[str, int]:
    """只删除可由 namespace 或 seed 自然键证明所有权的行。"""
    preflight(connection)
    cursor = connection.cursor()
    deleted = {}
    try:
        users = _id_map(cursor, "base_user", "username",
                        [item["username"] for item in CUSTOMERS] + [item[0] for item in EMPLOYEES])
        products = _id_map(cursor, "fin_product", "product_code", [item[0] for item in PRODUCTS])
        user_ids = tuple(users.values())
        product_ids = tuple(products.values())
        operations = (
            ("fin_verified_payee", "trace_id LIKE %s", (NAMESPACE + ":payee:%",)),
            ("biz_compliance_evidence", "event_id LIKE %s", (NAMESPACE + ":%",)),
            ("biz_operation_audit", "audit_event_id LIKE %s", (NAMESPACE + ":%",)),
            ("fin_knowledge_meta", "title LIKE %s", (f"[{NAMESPACE}]%",)),
            ("conversation_archive", "session_id LIKE %s", (NAMESPACE + ":%",)),
            ("biz_work_order", "intent_summary LIKE %s", (f"[{NAMESPACE}]%",)),
            ("fin_risk_alert", "handle_note LIKE %s", (f"[{NAMESPACE}]%",)),
            ("fin_holdings", "customer_id IN (" + ",".join(["%s"] * len(user_ids)) + ") AND product_id IN (" +
             ",".join(["%s"] * len(product_ids)) + ")", user_ids + product_ids),
            ("fin_transaction", "idempotency_key LIKE %s", (NAMESPACE + ":%",)),
            ("fin_risk_assessment", "customer_id IN (" + ",".join(["%s"] * len(CUSTOMERS)) + ") AND JSON_CONTAINS(answers,%s)",
             tuple(users[item["username"]] for item in CUSTOMERS) + (_json({"seed_namespace": NAMESPACE}),)),
            ("fin_customer_profile", "customer_id IN (" + ",".join(["%s"] * len(CUSTOMERS)) + ")",
             tuple(users[item["username"]] for item in CUSTOMERS)),
            ("base_user_role", "user_id IN (" + ",".join(["%s"] * len(user_ids)) + ")", user_ids),
        )
        for table, where, params in operations:
            cursor.execute(f"DELETE FROM `{table}` WHERE {where}", params)
            deleted[table] = cursor.rowcount
        cursor.execute("DELETE FROM fin_product WHERE product_code LIKE 'WBSEED-%' AND description LIKE %s",
                       (f"[{NAMESPACE}]%",))
        deleted["fin_product"] = cursor.rowcount
        owned_users = []
        for username, user_id in users.items():
            row = _one(cursor, "SELECT extra_data FROM base_user WHERE id=%s", (user_id,))
            if row and _owned_json(row["extra_data"]):
                owned_users.append(user_id)
        if owned_users:
            cursor.execute("DELETE FROM base_user WHERE id IN (" + ",".join(["%s"] * len(owned_users)) + ")",
                           tuple(owned_users))
        deleted["base_user"] = cursor.rowcount
        connection.commit()
        return deleted
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WealthButler MySQL seed (offline dry-run by default)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--connect-dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    mode.add_argument("--inspect-enums", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not any((args.connect_dry_run, args.apply, args.verify, args.rollback, args.inspect_enums)):
        print(render_plan())
        return 0
    if args.apply and args.confirm != APPLY_CONFIRMATION:
        raise SystemExit(f"--apply requires --confirm {APPLY_CONFIRMATION}")
    if args.rollback and args.confirm != ROLLBACK_CONFIRMATION:
        raise SystemExit(f"--rollback requires --confirm {ROLLBACK_CONFIRMATION}")
    load_dotenv(ROOT / ".env", override=False)
    password = os.environ.get("WEALTH_BUTLER_SEED_PASSWORD")
    connection = _connect()
    try:
        if args.inspect_enums:
            print(json.dumps(inspect_enum_contracts(connection), ensure_ascii=True, sort_keys=True))
        elif args.connect_dry_run:
            preview = preflight(connection)
            print(json.dumps({"namespace": NAMESPACE, "existing_seed": preview["existing_seed"],
                              "row_counts": {k: v["rows"] for k, v in preview["schema"].items()}},
                             ensure_ascii=False, sort_keys=True))
        elif args.apply:
            before = {k: v["rows"] for k, v in preflight(connection)["schema"].items()}
            result = apply_seed(connection, validate_seed_password(password))
            verified = verify_seed(connection, password)
            print(json.dumps({"namespace": NAMESPACE, "before": before, "inserted": result["inserted"],
                              "after": verified["row_counts"], "checks": verified["checks"],
                              "auth": verified["auth"], "ids": verified["ids"]},
                             ensure_ascii=False, sort_keys=True))
        elif args.verify:
            print(json.dumps(verify_seed(connection), ensure_ascii=False, sort_keys=True))
        else:
            print(json.dumps({"namespace": NAMESPACE, "deleted": rollback_seed(connection)},
                             ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
