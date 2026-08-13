---
name: scaffold-reuse
description: 智能财富管家系统的脚手架复用指引。AI 编码 agent 开始写任何新代码前使用，规定先查脚手架 D:\lqh\reproject\ric-train\ric-train\Base 里有什么能复用、哪些能力必须新写、复用哪些、怎么复用。
---

# 脚手架复用指引

项目最大踩坑风险是 AI 不知道脚手架里已有现成能力，照着自己的习惯重写一遍（违反 ADR-1"能复用绝不重写"）。**写任何新代码前，先读本规范和《脚手架复用能力盘点.md》，确认脚手架里有没有现成的。**

## 1. 先查脚手架：新代码找参照的对应关系

| 要写的内容 | 先去看脚手架哪里 |
|---|---|
| MySQL 业务表 Model | `Models/userModel.py`、`Repository/models/`、`Repository/base/baseDBModel.py`（自动建表/补列） |
| Milvus 向量集合 Model | `Repository/examples/exampleVDBModel.py`、`Repository/base/baseVDB.py`（配置即用，自动建集合建索引） |
| Agent 子类 | `Ai/agents/nl2cypherAgent.py`、`Ai/base/baseAgent.py`（BaseAgent + ReAct/CoT/PlanAndExecute 范式） |
| 中间件 | `Ai/middlewares/`（Logging→Metrics→Safety→Eval 洋葱模型） |
| LLM 调用 | `Ai/llms/qwenLlm.py`、`deepseekLlm.py` |
| 定时任务 | `Service/scheduler/` 装饰器模式（`scheduled(cron=...)`） |
| DB/外部系统客户端 | `Client/`（MySQL/Redis/Milvus/Neo4j/MinIO 全部已封装） |
| RBAC/认证 | `Service/authService.py`（登录/JWT/角色授予），角色用 `RoleModel.create_role` 加 |
| Function Calling 工具 | `Ai/base/baseTool.py`（`to_openai_schema()` 自动生成 schema） |

## 2. 能力清单速查

- **能直接复用 / 简单配置即用**：DB 客户端、Agent 基座+中间件、Milvus RAG（hybrid_search）、日志/指标/基础安全（含 PII 脱敏）、认证与 RBAC、Function Calling 工具框架、APScheduler。
- **必须新写（脚手架没有或不可靠）**：风控规则引擎、适当性匹配、NL2SQL 安全校验、客户画像四维评分、置信度公式体系、跨 Agent 事件总线（Streams）、8 个业务操作工具的具体业务逻辑、10 张业务表业务逻辑、二次确认状态机、多 Agent 协作编排层、trace_id 链路追踪字段。

## 3. 三个关键警告（照抄必翻车）

1. **`nl2cypherAgent.py` 不能直接改造成 GraphRAG 查询能力**——它做的是"自然语言→抽取实体关系→写入 Neo4j"（知识入库），方向相反。只复用它的 ReActAgent 双工具模式、`_run_loop` 重写技巧、`Neo4jClient.run(cypher, parameters)` 执行原语；查询方向的 Agent 要新写（约 1~1.5 人天）。
2. **`SQLBuilder` 不做表名/字段名白名单，`ToolGuard` 只是关键词黑名单**（可被注释/大小写变形绕过）——NL2SQL 安全校验必须完全新写，不能依赖脚手架这两个组件。
3. **`UserModel`（`base_user`）没有 `employee_role`/`customer_level` 字段**——直接给现有表加列（脚手架自动 `ALTER TABLE` 补列，分钟级），不要另建平行 `sys_user` 表。

## 4. 复用 vs 新写的判断原则

- 脚手架已验证可用的基础设施（连接池、认证、日志、中间件链路）一律复用，不因为"想更优雅"重写。
- 脚手架没有的，新写但**沿用脚手架同款风格**（同一套 Base 类、装饰器、连接管理、命名），保证可维护性。
- 改造脚手架已有文件时，要"标注差异"：原样是什么、改了哪里、为什么改（对应 comment-standards 的脚手架改造注释要求）。

## 5. 交付前自检

- 新写的代码是否先确认过脚手架里没有现成的？
- 复用时是否找到了正确的参照文件、没有自创一套写法？
- 改造脚手架的地方是否用注释标注了差异（WHY）？
- 是否踩了 §3 的三个警告里的任何一个？
