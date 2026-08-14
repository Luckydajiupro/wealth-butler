"""规则引擎层

职责：
- 实现风控规则的定义、评估、触发逻辑
- 管理 15 条规则（反洗钱 8 条 + 风险画像 7 条）的配置与版本
- 提供规则评估接口（单条规则 / 规则集批量评估）
- 支持规则置信度计算、多规则融合、阈值动态调整

分层原则：
- 本层是声明式规则系统，与 Agent 执行逻辑解耦
- 规则配置与代码分离：规则存储在 JSON/YAML，引擎只负责解释执行
- 不使用 eval()：采用安全的条件树或 DSL 解析器
- 规则变更需要版本管理与审计留痕

核心概念：
- Rule: 一条规则定义（条件表达式 + 触发动作 + 置信度权重）
- RuleSet: 规则集（一组相关规则的集合，如"反洗钱规则集"）
- Context: 规则评估上下文（业务数据字典，供规则表达式引用）
- Confidence: 置信度（规则触发的确定性评分，0-1 浮点数）
- Trigger: 触发结果（规则是否命中、置信度、违反条件列表）

15 条规则清单（需求文档§5.4 + 用户研判规则/）：

A. 反洗钱可疑交易识别规则（8 条，来自 用户研判规则/反洗钱可疑交易识别规则.md）
   1. 短期内大额现金存取
   2. 频繁小额分拆转账
   3. 资金快进快出
   4. 交易时间异常（非工作时间集中交易）
   5. 跨境资金异常流动
   6. 同一账户多人操作特征
   7. 交易金额整数倍
   8. 与高风险名单关联

B. 投资者风险画像研判规则（7 条，来自 用户研判规则/投资者风险画像研判规则.md）
   1. 风险承受能力与投资行为不匹配
   2. 高风险产品持仓过度集中
   3. 短期内频繁交易（追涨杀跌）
   4. 杠杆使用超过承受能力
   5. 投资期限与目标不匹配
   6. 风险等级跳级（保守型直接买激进产品）
   7. 年龄与风险偏好倒挂（老年人高风险）

典型模块：
- ruleEngine.py              规则引擎核心（评估器 + 置信度计算）
- ruleDefinitions.py         规则定义（15 条规则的 JSON Schema）
- ruleLoader.py              规则加载器（从配置文件/数据库加载规则）
- confidenceCalculator.py    置信度计算器（多因子融合）
- ruleAuditor.py             规则审计（触发记录 + 误报分析）

规则定义 Schema（ruleDefinitions.py）：
    from pydantic import BaseModel
    from typing import Literal

    class RuleCondition(BaseModel):
        '''规则条件（支持简单的逻辑表达式）'''
        field: str           # 上下文字段名（如 'amount', 'tx_count_7d'）
        operator: Literal['>', '<', '>=', '<=', '==', '!=', 'in', 'contains']
        value: any           # 比较值
        weight: float = 1.0  # 本条件的权重（用于置信度计算）

    class RuleDefinition(BaseModel):
        '''规则定义'''
        rule_id: str                    # 规则唯一标识（如 'AML_001'）
        rule_name: str                  # 规则名称（如 '短期内大额现金存取'）
        category: Literal['aml', 'risk_profile']  # 规则类别
        conditions: list[RuleCondition]  # 条件列表（AND 关系）
        threshold: float = 0.6           # 触发阈值（置信度>=此值才触发）
        action: str = 'alert'            # 触发动作（alert/block/review）
        severity: Literal['low', 'medium', 'high', 'critical']  # 严重程度
        enabled: bool = True             # 是否启用
        version: str = '1.0'             # 规则版本

    # 示例：AML_001 - 短期内大额现金存取
    AML_001 = RuleDefinition(
        rule_id='AML_001',
        rule_name='短期内大额现金存取',
        category='aml',
        conditions=[
            RuleCondition(field='cash_withdraw_7d', operator='>', value=100000, weight=0.4),
            RuleCondition(field='cash_deposit_7d', operator='>', value=100000, weight=0.4),
            RuleCondition(field='tx_time_night_ratio', operator='>', value=0.3, weight=0.2)
        ],
        threshold=0.6,
        action='alert',
        severity='high'
    )

规则引擎核心（ruleEngine.py）：
    from WealthButler.Rules.ruleDefinitions import RuleDefinition, RuleCondition

    class RuleEngine:
        '''规则引擎核心（条件评估 + 置信度计算）'''

        @staticmethod
        def evaluate_rule(rule: RuleDefinition, context: dict) -> dict:
            '''评估单条规则

            Args:
                rule: 规则定义
                context: 业务上下文（如 {amount: 50000, tx_count_7d: 3}）

            Returns:
                {
                    'triggered': bool,           # 是否触发
                    'confidence': float,         # 置信度（0-1）
                    'violated_conditions': list, # 违反的条件列表
                    'rule_id': str,
                    'rule_name': str
                }
            '''
            if not rule.enabled:
                return {'triggered': False, 'confidence': 0.0}

            violated = []
            total_weight = sum(c.weight for c in rule.conditions)
            matched_weight = 0.0

            # 逐条件评估
            for condition in rule.conditions:
                if RuleEngine._eval_condition(condition, context):
                    matched_weight += condition.weight
                    violated.append({
                        'field': condition.field,
                        'operator': condition.operator,
                        'expected': condition.value,
                        'actual': context.get(condition.field)
                    })

            # 置信度计算（匹配权重占比）
            confidence = matched_weight / total_weight if total_weight > 0 else 0.0

            # 判断是否触发（置信度 >= 阈值）
            triggered = confidence >= rule.threshold

            return {
                'triggered': triggered,
                'confidence': round(confidence, 3),
                'violated_conditions': violated,
                'rule_id': rule.rule_id,
                'rule_name': rule.rule_name,
                'severity': rule.severity
            }

        @staticmethod
        def _eval_condition(condition: RuleCondition, context: dict) -> bool:
            '''评估单个条件（安全实现，不使用 eval）'''
            field_value = context.get(condition.field)
            if field_value is None:
                return False

            operator = condition.operator
            expected = condition.value

            # 安全的操作符映射
            if operator == '>':
                return field_value > expected
            elif operator == '<':
                return field_value < expected
            elif operator == '>=':
                return field_value >= expected
            elif operator == '<=':
                return field_value <= expected
            elif operator == '==':
                return field_value == expected
            elif operator == '!=':
                return field_value != expected
            elif operator == 'in':
                return field_value in expected  # expected 是列表
            elif operator == 'contains':
                return expected in str(field_value)
            else:
                raise ValueError(f"Unsupported operator: {operator}")

        @staticmethod
        def evaluate_ruleset(rules: list[RuleDefinition], context: dict) -> list[dict]:
            '''批量评估规则集（返回所有触发的规则）'''
            results = []
            for rule in rules:
                result = RuleEngine.evaluate_rule(rule, context)
                if result['triggered']:
                    results.append(result)

            # 按置信度降序排序
            results.sort(key=lambda x: x['confidence'], reverse=True)
            return results

15 条规则的完整定义（ruleDefinitions.py，部分示例）：
    # 反洗钱规则集
    AML_RULES = [
        RuleDefinition(
            rule_id='AML_001',
            rule_name='短期内大额现金存取',
            category='aml',
            conditions=[
                RuleCondition(field='cash_withdraw_7d', operator='>', value=100000, weight=0.5),
                RuleCondition(field='cash_deposit_7d', operator='>', value=100000, weight=0.5)
            ],
            threshold=0.6,
            severity='high'
        ),
        RuleDefinition(
            rule_id='AML_002',
            rule_name='频繁小额分拆转账',
            category='aml',
            conditions=[
                RuleCondition(field='tx_count_1d', operator='>', value=10, weight=0.4),
                RuleCondition(field='avg_tx_amount', operator='<', value=5000, weight=0.3),
                RuleCondition(field='tx_variance', operator='<', value=1000, weight=0.3)  # 金额方差小
            ],
            threshold=0.65,
            severity='medium'
        ),
        # AML_003 ~ AML_008 省略...
    ]

    # 风险画像规则集
    RISK_PROFILE_RULES = [
        RuleDefinition(
            rule_id='RISK_001',
            rule_name='风险承受能力与投资行为不匹配',
            category='risk_profile',
            conditions=[
                RuleCondition(field='risk_tolerance', operator='==', value='保守型', weight=0.4),
                RuleCondition(field='high_risk_ratio', operator='>', value=0.3, weight=0.6)  # 高风险产品占比>30%
            ],
            threshold=0.7,
            severity='high'
        ),
        RuleDefinition(
            rule_id='RISK_002',
            rule_name='高风险产品持仓过度集中',
            category='risk_profile',
            conditions=[
                RuleCondition(field='single_product_ratio', operator='>', value=0.5, weight=0.5),
                RuleCondition(field='product_risk_level', operator='>=', value=4, weight=0.5)  # 风险等级4-5
            ],
            threshold=0.65,
            severity='medium'
        ),
        # RISK_003 ~ RISK_007 省略...
    ]

    # 全部规则集
    ALL_RULES = AML_RULES + RISK_PROFILE_RULES

上下文构造示例（在风控监测 Agent 中调用）：
    from WealthButler.Rules.ruleEngine import RuleEngine
    from WealthButler.Rules.ruleDefinitions import AML_RULES

    # 从数据库查询用户交易数据，构造规则评估上下文
    context = {
        'customer_id': 12345,
        'cash_withdraw_7d': 150000,       # 7天内现金取款总额
        'cash_deposit_7d': 120000,        # 7天内现金存款总额
        'tx_count_1d': 15,                # 1天内交易笔数
        'avg_tx_amount': 4500,            # 平均单笔金额
        'tx_variance': 800,               # 金额方差
        'tx_time_night_ratio': 0.4,       # 夜间交易占比
        'risk_tolerance': '保守型',       # 风险承受能力
        'high_risk_ratio': 0.35,          # 高风险产品占比
        # ... 更多字段
    }

    # 评估反洗钱规则集
    triggered_rules = RuleEngine.evaluate_ruleset(AML_RULES, context)

    for rule_result in triggered_rules:
        print(f"触发规则：{rule_result['rule_name']}")
        print(f"置信度：{rule_result['confidence']}")
        print(f"违反条件：{rule_result['violated_conditions']}")

        # 写入风控告警表
        # insert into biz_risk_alert (...)

与 Tools 层的集成（RuleEvaluator Tool）：
    from Base.Ai.base.baseTool import BaseTool
    from WealthButler.Rules.ruleEngine import RuleEngine
    from WealthButler.Rules.ruleDefinitions import ALL_RULES

    class RuleEvaluatorTool(BaseTool):
        name = "RuleEvaluator"
        description = "评估风控规则（反洗钱 + 风险画像）"

        rule_name: str = Field(..., description="规则名称或 'all' 表示全部规则")
        context: dict = Field(..., description="评估上下文（业务数据字典）")

        def _run(self, rule_name: str, context: dict) -> dict:
            if rule_name == 'all':
                rules = ALL_RULES
            else:
                rules = [r for r in ALL_RULES if r.rule_name == rule_name]

            results = RuleEngine.evaluate_ruleset(rules, context)

            return {
                'triggered_count': len(results),
                'triggered_rules': results
            }

与架构设计文档的对应关系：
- §8.3: 风控监测 Agent 的规则引擎评估流程
- §5.4: 用户研判规则的双轨触发机制（LLM + 规则引擎）
- 需求文档§5.4 第十五条：15 条规则清单

技术约束：
- 规则表达式禁止使用 eval()、exec()，只支持安全的操作符白名单
- 规则配置应外部化（JSON/YAML），不硬编码在代码中
- 规则变更需要版本号 + 审计日志
- 单次评估耗时应 <100ms（15 条规则串行评估）

使用规范：
- 新增规则需经风控团队审批，不能随意添加
- 规则阈值应基于历史数据校准（误报率 <5%）
- 触发记录需持久化到 biz_risk_alert 表，供人工复核
- 规则置信度计算应透明可解释（违反了哪些条件、各占多少权重）
"""

__all__ = []
