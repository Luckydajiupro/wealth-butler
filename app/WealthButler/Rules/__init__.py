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

15 条规则清单（需求文档§5.2）：

**反洗钱可疑交易识别规则（完整20条，RW-001~RW-020）**
来自《反洗钱可疑交易识别规则》（JR-AML-RULE-2024-001），是F4.1风控监测Agent规则引擎的直接编码依据：

实时/准实时规则（8条）：
   RW-001: 大额现金交易
   RW-003: 资金快进快出
   RW-008: 非正常时段大额交易
   RW-011: 高风险国家/地区交易
   RW-014: 非本人账户代付投资款
   RW-015: 身份变更后立即大额交易
   RW-016: 老年客户异常大额转出
   RW-017: 新开户短期大额交易

日批/周批规则（12条）：
   RW-002: 频繁小额交易（蚂蚁搬家）
   RW-004: 分散转入集中转出
   RW-005: 集中转入分散转出
   RW-006: 交易金额与客户身份不符
   RW-007: 频繁开销户
   RW-009: 整数金额规避特征
   RW-010: 关联交易异常
   RW-012: 频繁申购赎回
   RW-013: PEP关联账户异常
   RW-018: 多账户关联资金归集
   RW-019: 疑似涉赌/涉诈资金流转
   RW-020: 离岸公司异常交易

注：FM-01~FM-05熔断规则（年龄限制/无收入且低资产/风评过期/身份信息异常/可疑行为记录）不属于本层，归属Service层的客户画像服务（riskAssessService.py），在F2.1客户画像系统中实现。

典型模块：
- ruleEngine.py              规则引擎核心（评估器 + 置信度计算）
- ruleDefinitions.py         规则定义（20 条 RW 规则的 JSON Schema）
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
    # 反洗钱规则集（完整20条）
    AML_RULES = [
        RuleDefinition(
            rule_id='RW_001',
            rule_name='大额现金交易',
            category='aml',
            conditions=[
                RuleCondition(field='cash_withdraw_7d', operator='>', value=50000, weight=0.5),
                RuleCondition(field='cash_deposit_7d', operator='>', value=50000, weight=0.5)
            ],
            threshold=0.6,
            severity='medium'
        ),
        RuleDefinition(
            rule_id='RW_002',
            rule_name='频繁小额交易（蚂蚁搬家）',
            category='aml',
            conditions=[
                RuleCondition(field='tx_count_7d', operator='>=', value=20, weight=0.4),
                RuleCondition(field='tx_total_7d', operator='>=', value=100000, weight=0.3),
                RuleCondition(field='avg_tx_amount', operator='<', value=5000, weight=0.3)
            ],
            threshold=0.65,
            severity='medium_high'
        ),
        # RW_003 ~ RW_020 省略...（共20条，完整定义见 用户研判规则/反洗钱可疑交易识别规则.md）
    ]

    # 全部规则集（仅包含反洗钱20条，FM-01~05熔断规则不在此处）
    ALL_RULES = AML_RULES

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
    from app.Base.Ai.base.baseTool import BaseTool
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
