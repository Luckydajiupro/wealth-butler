"""正式 Operator Runtime 的延迟装配工厂。

该工厂只由 ``main.py`` 生命周期中的生产装配层显式调用。模块导入和工厂
定义均不创建数据库、Redis 或 LLM 连接。
"""

from __future__ import annotations

from typing import Any, Callable, Optional


_WRITE_DEPENDENCY_METHODS = {
    "transaction_gateway": ("execute",),
    "work_order_gateway": (
        "create_booking",
        "transition",
        "create_work_order",
        "claim",
        "submit_for_review",
        "complete",
        "reject",
    ),
    "risk_assessment_gateway": ("submit_assessment",),
    "customer_info_gateway": ("update_contact",),
    "risk_alert_gateway": ("report_suspicious_transaction",),
    "event_publisher": ("publish", "enqueue_retry"),
    "operation_audit_gateway": ("record",),
}

_READ_DEPENDENCY_METHODS = {
    "permission_gateway": ("has_permission",),
    "customer_gateway": ("exists",),
    "advisor_qualification_gateway": ("get_advisor_level",),
    "product_gateway": ("get_product", "list_products"),
    "holding_gateway": ("current_total_value", "current_r3_value", "get_position"),
}

_RULE_DEPENDENCY_METHODS = {
    "suitability_gateway": ("check",),
    "purchase_compliance_gateway": ("validate_purchase",),
    "operation_risk_gateway": ("validate_redeem", "validate_transfer"),
}


def _is_fake_dependency(dependency: Any) -> bool:
    cls = type(dependency)
    return cls.__name__.startswith("Fake") or cls.__module__.endswith(".operatorFakes")


def _require_methods(name: str, dependency: Any, methods: tuple[str, ...]) -> None:
    if dependency is None:
        raise ValueError(f"正式 Runtime 缺少依赖: {name}")
    if _is_fake_dependency(dependency):
        raise TypeError(f"正式 Runtime 禁止使用 Fake 依赖: {name}")
    missing = [method for method in methods if not callable(getattr(dependency, method, None))]
    if missing:
        raise TypeError(f"{name} 未实现必要方法: {', '.join(missing)}")


def create_real_runtime(
    *,
    intent_parser: Any,
    transaction_gateway: Any = None,
    work_order_gateway: Any = None,
    risk_assessment_gateway: Any = None,
    customer_info_gateway: Any = None,
    risk_alert_gateway: Any = None,
    event_publisher: Any = None,
    operation_audit_gateway: Any = None,
    confirmation_gateway: Any = None,
    redis_client: Any = None,
    permission_gateway: Any = None,
    customer_gateway: Any = None,
    advisor_qualification_gateway: Any = None,
    product_gateway: Any = None,
    holding_gateway: Any = None,
    suitability_gateway: Any = None,
    purchase_compliance_gateway: Any = None,
    operation_risk_gateway: Any = None,
    compliance_evidence_loader: Optional[Callable[[int, int], Any]] = None,
    holding_summary_loader: Optional[Callable[[int, str], Any]] = None,
    payee_verifier: Optional[Callable[[int, dict], Optional[bool]]] = None,
) -> Any:
    """组装正式 Runtime；写依赖缺失、接口不完整或使用 Fake 时立即失败。

    ``confirmation_gateway`` 必须是 ``RedisConfirmationGateway``。也可以显式
    传入一个已配置的 ``redis_client``，由本工厂创建 Redis Gateway；两者不能
    同时传入。规则所需的留痕、持仓汇总和收款方核验读取器同样必须显式提供，
    以免缺失合规数据时被默认当作通过。
    """
    if not callable(getattr(intent_parser, "parse", None)):
        raise TypeError("正式 Runtime 必须注入实现 parse() 的 IntentParser")
    if _is_fake_dependency(intent_parser):
        raise TypeError("正式 Runtime 禁止使用 Fake IntentParser")

    write_dependencies = {
        "transaction_gateway": transaction_gateway,
        "work_order_gateway": work_order_gateway,
        "risk_assessment_gateway": risk_assessment_gateway,
        "customer_info_gateway": customer_info_gateway,
        "risk_alert_gateway": risk_alert_gateway,
        "event_publisher": event_publisher,
        "operation_audit_gateway": operation_audit_gateway,
    }
    for name, methods in _WRITE_DEPENDENCY_METHODS.items():
        _require_methods(name, write_dependencies[name], methods)

    # 延迟导入：导入 builder 本身不会加载模型、Redis 客户端或 Agent。
    from app.WealthButler.Service.operatorRealAdapters import (
        AuthPermissionGateway,
        ModelAdvisorQualificationGateway,
        ModelCustomerGateway,
        ModelHoldingGateway,
        ModelProductGateway,
    )
    from app.WealthButler.Service.operatorRuleAdapters import (
        ModelOperationRiskGateway,
        ModelPurchaseComplianceGateway,
        ModelSuitabilityGateway,
    )

    permission_gateway = permission_gateway or AuthPermissionGateway()
    customer_gateway = customer_gateway or ModelCustomerGateway()
    advisor_qualification_gateway = (
        advisor_qualification_gateway or ModelAdvisorQualificationGateway()
    )
    product_gateway = product_gateway or ModelProductGateway()
    holding_gateway = holding_gateway or ModelHoldingGateway()

    suitability_gateway = suitability_gateway or ModelSuitabilityGateway()
    if purchase_compliance_gateway is None:
        if compliance_evidence_loader is None or holding_summary_loader is None:
            raise ValueError(
                "正式 Runtime 自动构造申购合规 Adapter 时必须注入 "
                "compliance_evidence_loader 和 holding_summary_loader"
            )
        purchase_compliance_gateway = ModelPurchaseComplianceGateway(
            suitability_gateway=suitability_gateway,
            evidence_loader=compliance_evidence_loader,
            holding_summary_loader=holding_summary_loader,
        )
    if operation_risk_gateway is None:
        if payee_verifier is None:
            raise ValueError("正式 Runtime 自动构造交易风险 Adapter 时必须注入 payee_verifier")
        operation_risk_gateway = ModelOperationRiskGateway(payee_verifier=payee_verifier)

    read_dependencies = {
        "permission_gateway": permission_gateway,
        "customer_gateway": customer_gateway,
        "advisor_qualification_gateway": advisor_qualification_gateway,
        "product_gateway": product_gateway,
        "holding_gateway": holding_gateway,
    }
    rule_dependencies = {
        "suitability_gateway": suitability_gateway,
        "purchase_compliance_gateway": purchase_compliance_gateway,
        "operation_risk_gateway": operation_risk_gateway,
    }
    for name, methods in _READ_DEPENDENCY_METHODS.items():
        _require_methods(name, read_dependencies[name], methods)
    for name, methods in _RULE_DEPENDENCY_METHODS.items():
        _require_methods(name, rule_dependencies[name], methods)

    if confirmation_gateway is not None and redis_client is not None:
        raise ValueError("confirmation_gateway 与 redis_client 只能注入一个")
    from app.WealthButler.Service.redisConfirmationGateway import RedisConfirmationGateway

    if confirmation_gateway is None:
        if redis_client is None:
            raise ValueError("正式 Runtime 必须注入 Redis 确认存储")
        _require_methods("redis_client", redis_client, ("eval", "hget", "delete"))
        confirmation_gateway = RedisConfirmationGateway(redis_client)
    if not isinstance(confirmation_gateway, RedisConfirmationGateway):
        raise TypeError("正式 Runtime 的确认存储必须是 RedisConfirmationGateway")
    _require_methods(
        "confirmation_gateway", confirmation_gateway, ("save", "get", "compare_and_set")
    )

    from app.WealthButler.Service.confirmationService import ConfirmationService
    from app.WealthButler.Service.operationService import OperationService
    from app.WealthButler.Service.operatorApiRuntime import OperatorApiRuntimeFactory

    confirmation_service = ConfirmationService(confirmation_gateway=confirmation_gateway)
    service = OperationService(
        **read_dependencies,
        **rule_dependencies,
        **write_dependencies,
        confirmation_service=confirmation_service,
    )
    dependencies = {
        **read_dependencies,
        **rule_dependencies,
        **write_dependencies,
        "confirmations": confirmation_gateway,
    }
    runtime = OperatorApiRuntimeFactory.create_real(
        operation_service=service,
        intent_parser=intent_parser,
        **dependencies,
    )
    if runtime.runtime_mode != "real":
        raise RuntimeError("正式 Runtime 装配结果模式异常")
    return runtime


__all__ = ["create_real_runtime"]
