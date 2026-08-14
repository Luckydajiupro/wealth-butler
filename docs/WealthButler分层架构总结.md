# WealthButler 完整分层架构总结

项目已完成 **11 层架构**的定义与文档编写，所有层级的 `__init__.py` 都包含了详细的职责说明、代码示例、调用关系。

## 架构分层（按调用顺序）

```
┌─────────────────────────────────────────────────────────────┐
│  Api 层              RESTful 接口适配，HTTP 请求响应         │
│  └─> Service 层      核心业务逻辑、算法、跨表操作            │
│       ├─> Agent 层   5 个智能 Agent（LLM 推理 + 工具调用）   │
│       │   ├─> Tools 层       10 个 BaseTool（原子能力）     │
│       │   ├─> Prompts 层     System Prompt 模板             │
│       │   ├─> Middleware 层  中间件洋葱（记忆/安全/评估）    │
│       │   └─> EventBus 层    Redis Streams 事件总线         │
│       ├─> Models 层  ORM 数据持久层                          │
│       ├─> Rules 层   风控规则引擎（15 条规则）                │
│       └─> Knowledge 层 RAG/GraphRAG 知识库管理               │
│
│  Utils 层            纯函数工具（金融计算/格式化/校验）       │
│                      可被任意层调用                          │
└─────────────────────────────────────────────────────────────┘
```

## 11 层详细说明

| 层级 | 目录 | 职责 | 核心模块 | 状态 |
|------|------|------|----------|------|
| 1 | **Api/** | 接口适配层 | advisorApi, productApi, riskApi | ✅ 已规划 |
| 2 | **Service/** | 业务逻辑层 | advisorService, productService, riskAssessService | ✅ 已规划 |
| 3 | **Models/** | 数据持久层 | advisorModel, productModel, userProfileModel | ✅ 已规划 |
| 4 | **Agent/** | 智能决策层 | customerServiceAgent, advisorAgent, riskAgent | ✅ 已规划 |
| 5 | **Tools/** | Agent 工具层 | KnowledgeRetrievalTool, SuitabilityCheckTool, NL2SQLTool | ✅ 已补充 |
| 6 | **Prompts/** | 提示词模板层 | customerServicePrompts, advisorPrompts, riskPrompts | ✅ 已补充 |
| 7 | **Middleware/** | Agent 中间件层 | MemoryRecallMiddleware, SafetyEnhancer, RBACMiddleware | ✅ 已补充 |
| 8 | **EventBus/** | 事件总线层 | eventBus, schemas, consumer | ✅ 已补充 |
| 9 | **Knowledge/** | 知识库管理层 | ragIngestion, graphBuilder, chunkStrategy | ✅ 已补充 |
| 10 | **Rules/** | 规则引擎层 | ruleEngine, ruleDefinitions（15 条规则） | ✅ 已补充 |
| 11 | **Utils/** | 业务工具层 | financeCalc, riskCalc, dataFormatter | ✅ 已规划 |

## 与项目文档的对应关系

- **架构设计文档 §2**: 逻辑架构图 → 对应 11 层的调用关系
- **架构设计文档 §2.3**: 中间件洋葱模型 → Middleware 层
- **架构设计文档 §2.4**: 事件总线 → EventBus 层
- **架构设计文档 §8**: 5 个 Agent 内部架构 → Agent/Tools/Prompts 层
- **Agent设计文档 §7**: 10 个 Tool Schema → Tools 层
- **Agent设计文档 §1.2**: 5段式 System Prompt → Prompts 层
- **RAG切片入库策略.md**: 三种切片策略 → Knowledge 层
- **用户研判规则/**: 15 条风控规则 → Rules 层

## 开发优先级建议（4天工期）

### Day 1: 数据层 + 基础 Service
- Models 层：7 张核心表（wealth_advisor, wealth_product, wealth_user_profile 等）
- Service 层：基础 CRUD 服务
- Knowledge 层：RAG 向量入库（产品/政策/FAQ 三个集合）

### Day 2: Agent + Tools 核心功能
- Tools 层：实现 KnowledgeRetrievalTool, SuitabilityCheckTool, GraphQueryTool
- Prompts 层：编写客服 + 投顾的 System Prompt
- Agent 层：实现客服 Agent + 投顾 Agent（其他 3 个 Agent 可简化）
- Middleware 层：实现 MemoryRecallMiddleware

### Day 3: 风控 + 事件总线
- Rules 层：实现规则引擎 + 定义 15 条规则
- EventBus 层：实现事件发布/消费
- Agent 层：实现风控监测 Agent

### Day 4: API 接口 + 联调测试
- Api 层：暴露业务接口，注册到 Base/main.py
- Service 层：完善业务逻辑（推荐引擎、风险评估）
- 前后端联调、演示准备

## 下一步建议

1. **创建第一个 Model**：从 `advisorModel.py` 或 `productModel.py` 开始
2. **配置数据库连接**：确保 .env 中的 MySQL 连接信息正确
3. **运行数据库迁移**：创建 wealth_* 表
4. **实现第一个 Service**：如 `AdvisorService.list_advisors()`
5. **创建第一个 API**：如 `GET /api/wealth/advisor/list`
6. **注册路由**：在 `Base/main.py` 中 `include_router(advisor_router)`

现在架构已经完全就绪，可以开始具体的业务开发了！
