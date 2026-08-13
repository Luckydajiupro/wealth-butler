---
name: prompt-engineering
description: 智能财富管家系统的提示词工程规范。AI 编码 agent 在编写或修改项目内 5 个 Agent 的提示词相关代码时使用，规范 System Prompt、意图分类、Tool schema 描述、NL2SQL/NL2Cypher 生成提示词怎么写。
---

# 提示词工程规范

本规范管的是项目内**提示词相关代码**的写法（5 个 Agent 的 System Prompt、意图分类、工具 schema 描述、NL2SQL/NL2Cypher 生成提示词、RAG query 改写提示词）。提示词是 Agent 的"灵魂"，写得好坏直接决定答辩要演示的 RAG/GraphRAG/NL2SQL/NL2API 效果。

**使用环节**：编码阶段——Codex 生成 / Claude Code 写与 review 这些提示词代码时。它不覆盖 Agent 运行时行为、不覆盖普通函数代码（那些归 coding-standards）。

## 1. System Prompt 必备要素

编写/检查任一 Agent 的 System Prompt 时，确认包含以下要素（对照《Agent设计文档.md》对应 Agent 的骨架）：

- **角色设定**：这个 Agent 是谁、服务谁（如"你是理财顾问助手，服务理财顾问员工"）
- **职责边界**：能做什么、**明确不能做什么**（如客服 Agent 不能给投资建议、风控 Agent 不走对话范式）
- **可用能力**：列出可用工具/可调用的检索能力，避免 Agent 编造能力
- **输出格式约束**：结构化输出优先（JSON schema），指明字段
- **行为准则**：二次确认（金额阈值）、来源引用（RAG 回答必须给来源）、权限意识

## 2. 意图分类提示词

- 意图清单必须与《Agent设计文档.md》§5.1 的分类清单一致（智能客服 5 类、业务操作 8 种意图），不能自创意图名。
- 每个意图给 1~2 个示例话语（few-shot），帮助 LLM 正确分类边界情况。
- 分类输出用固定枚举，便于后续路由到对应 Tool/分支。

## 3. Tool / Function Calling schema 描述

- 参数描述要**精确到枚举值、单位、校验约束**——参数提取准度直接依赖描述质量，描述含糊（如只写"金额"）会导致 LLM 提取出错误值。
- 描述中对齐《API接口设计文档.md》对应接口的契约与《Agent设计文档.md》§5.1 工具参数结构。
- 二次确认相关字段（如 `confirm_token`）要描述清楚用途，让 LLM 知道它是流程状态的一部分而非普通参数。

## 4. NL2SQL / NL2Cypher 生成提示词

- **schema-aware**：提示词必须注入表名/字段/类型（NL2SQL）或节点/关系类型（NL2Cypher），不能只让 LLM 凭常识猜表结构。
- **业务规则约束**：NL2SQL 明确"只读、仅 SELECT、禁止改写数据"，并指向白名单校验（见 §6）；NL2Cypher 指向《架构设计文档.md》§8.4 的图谱 schema。
- **输出要求**：输出带结构化字段（生成的 SQL/Cypher、意图、参数），供审计与安全校验层使用（对应《API接口设计文档.md》`metadata.generated_sql`）。
- 给 1~2 个高质量 few-shot 示例，示范"自然语言→SQL/Cypher"的标准映射。

## 5. RAG query 改写提示词

- 明确改写目标：提取检索关键词、保留关键实体、去掉口语杂质；不要求改写后的句子通顺完整，检索友好优先。
- 不改写用户的核心诉求（产品名、金额、时间等必须原样保留）。

## 6. 安全约束注入

- NL2SQL 提示词必须声明"只允许查白名单内的表和字段"（对应 coding-standards 的高风险核查项），即使有白名单校验层兜底，提示词层的约束仍要写——双层防线。
- 涉及权限/金额的生成代码（非提示词）由 coding-standards 与 code-review 把关，本 skill 只约束提示词本身。

## 7. 交付前自检

- 对照《Agent设计文档.md》System Prompt 骨架，确认本 Agent 的提示词没丢关键要素。
- 意图名与《Agent设计文档.md》§5.1 一致、工具参数与《API接口设计文档.md》一致。
- NL2SQL/NL2Cypher 提示词确认已注入 schema 与安全约束、有 few-shot。
