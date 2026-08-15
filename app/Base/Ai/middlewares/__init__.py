"""
Agent 中间件模块

提供可观测性、安全性、评估等中间件。
"""
from app.Base.Ai.middlewares.base import AgentContext, Middleware, MiddlewareChain
from app.Base.Ai.middlewares.logging import LoggingMiddleware
from app.Base.Ai.middlewares.metrics import MetricsMiddleware
from app.Base.Ai.middlewares.safety_middleware import SafetyMiddleware
from app.Base.Ai.middlewares.eval_middleware import EvalMiddleware

# 安全防护器
from app.Base.Ai.middlewares.safety import (
    SafetyGuard,
    GuardResult,
    SafetyException,
    PromptInjectionDetector,
    SensitiveWordFilter,
    PIIMasker,
    ToolGuard,
)

# 评估器
from app.Base.Ai.middlewares.eval import (
    BaseEvaluator,
    EvalResult,
)
from app.Base.Ai.middlewares.eval.llm_judge import LLMJudgeEvaluator
from app.Base.Ai.middlewares.eval.ab_test import ABTestEvaluator

__all__ = [
    # 基类
    "AgentContext",
    "Middleware",
    "MiddlewareChain",
    # 中间件
    "LoggingMiddleware",
    "MetricsMiddleware",
    "SafetyMiddleware",
    "EvalMiddleware",
    # 安全防护
    "SafetyGuard",
    "GuardResult",
    "SafetyException",
    "PromptInjectionDetector",
    "SensitiveWordFilter",
    "PIIMasker",
    "ToolGuard",
    # 评估
    "BaseEvaluator",
    "EvalResult",
    "LLMJudgeEvaluator",
    "ABTestEvaluator",
]
