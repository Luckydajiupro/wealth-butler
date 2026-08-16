"""提示词模板层

职责：
- 管理 5 个 Agent 的 System Prompt 骨架（5段式模板）
- 定义意图分类提示词模板
- 提供提示词版本管理与 A/B 测试支持
- 封装提示词变量替换与格式化逻辑

分层原则：
- 本层只存储提示词文本与模板，不包含业务逻辑
- 提示词是 AI 应用的核心资产，独立管理便于迭代优化
- 与 Agent 层解耦：Agent 负责编排逻辑，Prompts 负责提示工程
- 支持多版本共存，便于 A/B 测试与回滚

典型模块：
- customerServicePrompts.py    智能客服 Agent 提示词
  - SYSTEM_PROMPT: 5段式骨架（角色定义/能力边界/工具使用/输出格式/合规红线）
  - INTENT_CLASSIFY_PROMPT: 意图分类提示（product_consult/policy_explain/faq/chitchat/transfer）
  - FALLBACK_PROMPT: RAG 检索低于阈值时的兜底话术

- advisorPrompts.py            投顾助手 Agent 提示词
  - SYSTEM_PROMPT: 推荐理由生成骨架
  - CLARIFY_PROMPT: 客户意向模糊时的追问模板
  - EXPLAIN_PROMPT: "为什么推荐这个"的解释模板

- riskPrompts.py               风控监测 Agent 提示词
  - RULE_VIOLATION_PROMPT: 规则触发后的风险报告模板
  - CONFIDENCE_CALIBRATION_PROMPT: 置信度校准提示

- portfolioPrompts.py          资产配置 Agent 提示词（预留）
  - 本期暂不实现，预留目录结构

- dataMiningPrompts.py         数据挖掘 Agent 提示词（预留）
  - 本期暂不实现，预留目录结构

- operatorPrompts.py           业务操作 Agent 提示词
  - SYSTEM_PROMPT: NL2API 转换骨架
  - CONFIRM_PROMPT: 二次确认提示模板
  - OPERATION_RESULT_PROMPT: 操作结果反馈模板

- commonPrompts.py             通用提示词片段
  - RBAC_BOUNDARY: 越权拒绝话术
  - COMPLIANCE_REDLINE: 合规红线重申（不得承诺收益/预测涨跌）
  - SOURCE_CITATION: 引用来源格式要求

5段式 System Prompt 模板结构（Agent设计文档§1.2）：
    ①角色定义 - "你是XX系统的XX Agent，服务对象是XX"
    ②能力边界 - 能做什么 + 明确不能做什么（越权场景直接拒绝）
    ③工具使用说明 - Tool 清单 + 调用时机
    ④输出格式约束 - 是否要求引用来源、结构化字段、SSE 分段策略
    ⑤合规红线重申 - 本 Agent 的强制项

示例：
    # customerServicePrompts.py
    SYSTEM_PROMPT = '''
    ①角色定义
    你是智能财富管家系统的客服 Agent，服务对象是【普通客户】。

    ②能力边界
    你可以：回答产品咨询、解读政策文件、处理常见问题。
    你不能：执行任何写操作（购买/赎回/修改资料）、跳过适当性校验给出投资建议。

    ③工具使用说明
    - KnowledgeRetrieval: 检索产品手册/政策文档/FAQ，Score<0.7 时触发兜底
    - ProfileExtract: 对话中识别客户属性（风险偏好/投资目标）时抽取
    - work_order_tool: 无法回答或客户明确要求时转人工

    ④输出格式约束
    - 必须引用来源：metadata.source_refs 列出检索到的文档片段
    - SSE 流式：按自然段分块，每段<200字

    ⑤合规红线
    - 不得承诺收益、预测涨跌、推荐具体产品（投顾专属权限）
    - 检索不到可靠答案时，坦诚"需要人工客服协助"，不要编造
    '''

    INTENT_CLASSIFY_PROMPT = '''
    判断客户意图，返回下列标签之一及置信度：
    - product_consult: 询问具体产品（基金/理财/信托）的特性/收益/风险
    - policy_explain: 询问监管政策/合规要求/操作流程
    - faq: 通用高频问题（开户/手续费/营业时间）
    - chitchat: 寒暄/闲聊/超出业务范围
    - transfer_to_human: 明确要求人工、或以上意图置信度均<0.6

    客户输入：{user_input}
    返回格式：{{"intent": "product_consult", "confidence": 0.85}}
    '''

变量替换示例：
    from WealthButler.Prompts.customerServicePrompts import SYSTEM_PROMPT

    prompt = SYSTEM_PROMPT.format(
        customer_name="张三",
        risk_level="稳健型"
    )

版本管理（可选，本期简化）：
    # 若需要 A/B 测试，可在文件名加版本号
    # customerServicePrompts_v1.py
    # customerServicePrompts_v2.py
    # 通过配置切换版本

使用规范：
- 提示词长度控制：System Prompt <2000字，Intent Classify <500字
- 避免硬编码业务数据（如产品列表），用变量占位符 {product_list}
- 合规话术需与法务对齐，重要提示词需评审留痕
- 中英文混排时注意空格：Tool 名称用英文，业务术语用中文
"""

__all__ = [
    "ADVISOR_SYSTEM_PROMPT"
]

