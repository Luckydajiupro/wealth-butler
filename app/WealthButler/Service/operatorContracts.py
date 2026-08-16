"""业务操作 Agent 的稳定输入输出契约。"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional
from uuid import uuid4


INTENT_PERMISSIONS = {
    "purchase": "operation:purchase",
    "redeem": "operation:redeem",
    "transfer": "operation:transfer",
    "reassess": "risk:reassess",
    "update_info": "customer:info_update",
    "product_query": "product:query",
    "suspicious_report": "risk:suspicious_report",
    "workorder_create": "workorder:create",
}

CONFIRMATION_THRESHOLDS = {
    "purchase": Decimal("10000"),
    "transfer": Decimal("50000"),
}


class IdempotencyConflictError(RuntimeError):
    """同一幂等键被用于不同业务请求时抛出。"""


def to_decimal(value: Any, field_name: str) -> Decimal:
    """将外部金额转换为精确十进制，避免 float 参与资金判断。"""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是有效金额") from exc
    if not amount.is_finite():
        raise ValueError(f"{field_name} 必须是有限数值")
    return amount


@dataclass(frozen=True)
class OperationCommand:
    """已完成解析和归一化的业务操作命令。"""

    intent: str
    params: Dict[str, Any]
    confidence: float = 1.0
    trace_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass
class OperationResult:
    """确定性业务层返回值，供 Tool、Agent 和后续 API 共用。"""

    success: bool
    code: str
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "code": self.code,
            "message": self.message,
            "data": self.data,
            "metadata": self.metadata,
        }
