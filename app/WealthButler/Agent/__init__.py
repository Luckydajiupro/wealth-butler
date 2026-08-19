"""智能 Agent 层。

该包只导出正式工作流实现。风控 Agent 由事件总线和调度器触发，
不提供通用对话占位类。
"""

from importlib import import_module
from typing import Any


_EXPORTS = {
    "AnalystAgent": "app.WealthButler.Agent.analystAgent",
    "AdvisorAgent": "app.WealthButler.Agent.advisorAgent",
    "CustomerServiceAgent": "app.WealthButler.Agent.customerServiceAgent",
    "OperatorAgent": "app.WealthButler.Agent.operatorAgent",
    "RiskAgent": "app.WealthButler.Agent.riskAgent",
}


def __getattr__(name: str) -> Any:
    """延迟加载正式 Agent，避免导入包时初始化数据库或外部客户端。"""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value

__all__ = list(_EXPORTS)
