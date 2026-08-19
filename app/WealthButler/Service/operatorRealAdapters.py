"""业务操作 Agent 的真实只读数据 Adapter。

本模块只负责读取身份、权限、产品和持仓。依赖允许注入，以便离线测试；
正式运行未注入时才延迟加载项目现有 Service/Model，避免模块导入即连接数据库。
"""

from decimal import Decimal, InvalidOperation
import logging
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)
_PRIVATE_PRODUCT_TYPES = {"私募基金", "信托"}
_PRODUCT_FIELDS = (
    "product_code",
    "product_name",
    "product_type",
    "risk_level",
    "min_investment",
    "redemption_period_days",
    "nav",
    "nav_date",
    "industry",
    "fund_manager",
    "status",
    "description",
)


def _valid_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _active_user(user: Any, expected_type: str) -> bool:
    return bool(
        user
        and getattr(user, "user_type", None) == expected_type
        and getattr(user, "status", None) == "active"
        and getattr(user, "deleted_at", None) is None
    )


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"数据库金额字段不是有效 Decimal: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"数据库金额字段不是有限 Decimal: {value!r}")
    return result


def _positive_page_value(value: Any, field: str, default: int, maximum: Optional[int] = None) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field} 必须为正整数")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须为正整数") from exc
    if parsed <= 0 or str(parsed) != str(value).strip():
        raise ValueError(f"{field} 必须为正整数")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{field} 不能超过 {maximum}")
    return parsed


class AuthPermissionGateway:
    """通过统一用户类型和 AuthService RBAC 判断员工权限。"""

    def __init__(self, auth_service: Any = None, user_model: Any = None):
        if auth_service is None:
            from app.Base.Service.authService import AuthService

            auth_service = AuthService
        if user_model is None:
            from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel

            user_model = BaseUserExtModel
        self.auth_service = auth_service
        self.user_model = user_model

    def has_permission(self, employee_id: int, permission: str) -> bool:
        if not _valid_id(employee_id) or not isinstance(permission, str) or not permission.strip():
            return False
        user = self.user_model.get_by_id(employee_id)
        if not _active_user(user, "EMPLOYEE"):
            return False
        try:
            return bool(self.auth_service.has_permission(
                employee_id,
                permission.strip(),
                getattr(user, "source_module", None),
            ))
        except Exception:
            logger.exception("员工权限查询失败: employee_id=%s", employee_id)
            return False


class ModelCustomerGateway:
    """以统一用户表中的有效 CUSTOMER 记录确认客户存在。"""

    def __init__(self, user_model: Any = None):
        if user_model is None:
            from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel

            user_model = BaseUserExtModel
        self.user_model = user_model

    def exists(self, customer_id: int) -> bool:
        if not _valid_id(customer_id):
            return False
        return _active_user(self.user_model.get_by_id(customer_id), "CUSTOMER")


class ModelAdvisorQualificationGateway:
    """返回有效客户经理的模拟业务经办资质。"""

    def __init__(self, user_model: Any = None):
        if user_model is None:
            from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel

            user_model = BaseUserExtModel
        self.user_model = user_model

    def get_advisor_level(self, employee_id: int) -> Optional[str]:
        if not _valid_id(employee_id):
            return None
        user = self.user_model.get_by_id(employee_id)
        if not _active_user(user, "EMPLOYEE") or getattr(user, "employee_role", None) != "客户经理":
            return None
        level = getattr(user, "advisor_level", None)
        # 现有数据表沿用 advisor_level 字段；客户经理没有填写时按模拟经办资质处理。
        return level if level in {"初级", "中级", "高级"} else "业务经办"


class ModelProductGateway:
    """使用 ProductModel 提供确定字段、筛选和有界分页。"""

    def __init__(self, product_model: Any = None):
        if product_model is None:
            from app.WealthButler.Models.productModel import ProductModel

            product_model = ProductModel
        self.product_model = product_model

    @staticmethod
    def _to_dict(product: Any) -> Dict[str, Any]:
        product_type = getattr(product, "product_type", None)
        item = {"product_id": getattr(product, "id", None)}
        item.update({field: getattr(product, field, None) for field in _PRODUCT_FIELDS})
        item["admission_tier"] = "仅预约" if product_type in _PRIVATE_PRODUCT_TYPES else "可执行"
        return item

    def get_product(self, product_id: int) -> Optional[Dict[str, Any]]:
        if not _valid_id(product_id):
            return None
        product = self.product_model.get_by_id(product_id)
        return self._to_dict(product) if product else None

    def list_products(self, **filters: Any) -> Dict[str, Any]:
        allowed = {"product_type", "risk_level", "status", "keyword", "page", "per_page"}
        unknown = set(filters) - allowed
        if unknown:
            raise ValueError("不支持的产品筛选字段: " + "、".join(sorted(unknown)))

        page = _positive_page_value(filters.get("page"), "page", 1)
        per_page = _positive_page_value(filters.get("per_page"), "per_page", 20, maximum=100)
        exact_filters = {
            field: filters[field]
            for field in ("product_type", "risk_level", "status")
            if filters.get(field) is not None
        }
        products = list(self.product_model.find_by(order_by="id", order="ASC", **exact_filters))

        keyword = filters.get("keyword")
        if keyword is not None:
            if not isinstance(keyword, str):
                raise ValueError("keyword 必须为字符串")
            normalized_keyword = keyword.strip().casefold()
            if normalized_keyword:
                products = [
                    product for product in products
                    if normalized_keyword in str(getattr(product, "product_name", "")).casefold()
                    or normalized_keyword in str(getattr(product, "product_code", "")).casefold()
                ]

        total = len(products)
        start = (page - 1) * per_page
        return {
            "items": [self._to_dict(product) for product in products[start:start + per_page]],
            "total": total,
            "page": page,
            "per_page": per_page,
        }


class ModelHoldingGateway:
    """从有效持仓计算 Decimal 市值，并按产品风险等级汇总。"""

    def __init__(self, holdings_model: Any = None, product_model: Any = None):
        if holdings_model is None:
            from app.WealthButler.Models.holdingsModel import HoldingsModel

            holdings_model = HoldingsModel
        if product_model is None:
            from app.WealthButler.Models.productModel import ProductModel

            product_model = ProductModel
        self.holdings_model = holdings_model
        self.product_model = product_model

    @staticmethod
    def _active_positions(positions: list[Any]) -> list[Any]:
        return [
            position for position in positions
            if getattr(position, "deleted_at", None) is None and _decimal(getattr(position, "shares", None)) > 0
        ]

    def current_total_value(self, customer_id: int) -> Decimal:
        if not _valid_id(customer_id):
            return Decimal("0")
        positions = self._active_positions(list(self.holdings_model.find_by_customer_id(customer_id)))
        return sum((_decimal(getattr(item, "current_value", None)) for item in positions), Decimal("0"))

    def current_r3_value(self, customer_id: int) -> Decimal:
        if not _valid_id(customer_id):
            return Decimal("0")
        positions = self._active_positions(list(self.holdings_model.find_by_customer_id(customer_id)))
        total = Decimal("0")
        for position in positions:
            product_id = getattr(position, "product_id", None)
            if not _valid_id(product_id):
                continue
            product = self.product_model.get_by_id(product_id)
            if product and getattr(product, "risk_level", None) == "R3":
                total += _decimal(getattr(position, "current_value", None))
        return total

    def get_position(self, customer_id: int, product_id: int) -> Dict[str, Any]:
        empty = {
            "customer_id": customer_id,
            "product_id": product_id,
            "shares": Decimal("0"),
            "current_value": Decimal("0"),
            "average_cost": Decimal("0"),
        }
        if not _valid_id(customer_id) or not _valid_id(product_id):
            return empty
        position = self.holdings_model.find_by_customer_and_product(customer_id, product_id)
        if not position or getattr(position, "deleted_at", None) is not None:
            return empty
        shares = _decimal(getattr(position, "shares", None))
        if shares <= 0:
            return empty
        cost_amount = _decimal(getattr(position, "cost_amount", None))
        return {
            "customer_id": customer_id,
            "product_id": product_id,
            "shares": shares,
            "current_value": _decimal(getattr(position, "current_value", None)),
            "average_cost": cost_amount / shares if shares else Decimal("0"),
        }


__all__ = [
    "AuthPermissionGateway",
    "ModelCustomerGateway",
    "ModelAdvisorQualificationGateway",
    "ModelProductGateway",
    "ModelHoldingGateway",
]
