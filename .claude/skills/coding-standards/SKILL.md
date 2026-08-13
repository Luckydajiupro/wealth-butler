---
name: coding-standards
description: 智能财富管家系统的编码规范。AI 编码 agent 在生成或修改任何代码前必须遵守的复用原则、文件落点、命名约定与禁止事项。适用于所有编码任务（Codex 写代码、Claude Code 修改代码均适用）。
---

# 编码规范

本规范是《Vibe Coding协作规范.md》§2 与《架构设计文档.md》ADR-1 的编码级落地。生成或修改代码前，先读本条规范，再动手。

## 1. 复用优先

- 新写代码前，先确认脚手架 `D:\lqh\reproject\ric-train\ric-train\Base` 里是否已有可抄的类似模式，不要自创写法：
  - 新业务表 Model → 参照 `Models/userModel.py`
  - 新 Agent → 参照 `Ai/agents/nl2cypherAgent.py`、`Ai/base/baseAgent.py`
  - 新向量集合 Model → 参照 `Repository/examples/exampleVDBModel.py`
- 禁止引入脚手架没有的新框架 / 新 ORM / 新的第三方库（除非设计文档明确要求）。违背 ADR-1"单体不过度设计"原则。

## 2. 文件落点

新文件放哪一层、哪个目录，必须对照《架构设计文档.md》§2.1"代码目录落点"：

| 内容 | 落点 |
|---|---|
| MySQL 业务表 Model | `Repository/models/` |
| Milvus 集合 Model | `Repository/models/` |
| 业务逻辑（规则引擎/画像/操作/事件总线/置信度） | `Service/` |
| 5 个 Agent 子类 | `Ai/agents/` |
| 工具（Function Calling） | `Ai/tools/` |
| 中间件 | `Ai/middlewares/` |
| 前端 | `Frontend/streamlit_app.py` |
| 客户端封装（如 EventBus） | `Client/` |

分层依赖单向：Api 只能调 Service；Service 可以调 Ai 和 Repository；Ai 通过 Tool 调 Repository/Service，不在 Agent 里裸写 SQL/Cypher。

## 3. 命名约定

- 文件名遵循脚手架现有小驼峰风格：`riskEngineService.py`，不是 `risk_engine_service.py`。
- 生成代码后检查 AI 是否把下划线命名输出了，若输出了按小驼峰改回。
- 类名、方法名沿用脚手架既有风格，与所在文件的其他类保持一致。

## 4. 禁止事项

- 不把 API Key / 数据库密码硬编码进代码（改用环境变量或 `.env`，真实 `.env` 不入库）。
- 不把测试数据、写死的 if 分支混进正式业务逻辑。
- 不跨层调用（不在 Api 层写业务逻辑，不在 Ai 层裸写 SQL/Cypher）。

## 5. 必须人工核查的高风险代码

涉及金额、权限校验、风控规则阈值、SQL/Cypher 拼接的代码，生成后必须人工逐行确认。尤其 SQL 拼接：脚手架自带的 `SQLBuilder` 不做表名/字段名白名单，AI 极易照抄这种不安全模式，务必确认白名单校验逻辑真实存在且生效。

## 6. 交付前自检

生成代码完成后，对照本条规范逐项检查：复用与否、落点是否正确、命名是否小驼峰、有无硬编码密钥、有无跨层调用。
