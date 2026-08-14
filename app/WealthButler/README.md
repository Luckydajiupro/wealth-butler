"""智能财富管家系统 - 分层架构说明

本文档定义了「智能财富管家系统」的完整分层架构与开发规范。

## 目录结构

```
app/
├── Base/                         # 脚手架层（通用基础设施，尽量不改）
│   ├── Api/                     # 基础 API（认证、通用 AI 对话）
│   ├── Service/                 # 基础服务（调度器、认证服务、记忆服务）
│   ├── Models/                  # 基础模型（用户、角色、权限、菜单）
│   ├── Client/                  # 中间件客户端（MySQL、Redis、Milvus、Neo4j、MinIO）
│   ├── Ai/                      # LLM 封装（Qwen、Deepseek、通用 Agent 框架）
│   ├── Config/                  # 配置管理（setting.py 读取 .env）
│   ├── RicUtils/                # 通用工具（HTTP、日期、加密、文件处理）
│   ├── Middleware/              # 中间件（CORS、日志、限流）
│   └── main.py                  # FastAPI 应用主体
│
├── WealthButler/                # 业务层（财富管家核心业务）
│   ├── Api/                     # 业务 API 接口层
│   │   ├── __init__.py         # 接口职责说明
│   │   ├── advisorApi.py       # 投顾服务接口
│   │   ├── productApi.py       # 理财产品接口
│   │   ├── portfolioApi.py     # 资产配置接口
│   │   ├── riskApi.py          # 风险评估接口
│   │   └── analysisApi.py      # 数据分析接口
│   │
│   ├── Service/                 # 业务服务层
│   │   ├── __init__.py         # 服务职责说明
│   │   ├── advisorService.py   # 投顾服务（匹配、排班、记录）
│   │   ├── productService.py   # 产品服务（筛选、计算、持仓）
│   │   ├── riskAssessService.py # 风险评估（问卷、评分、等级）
│   │   ├── portfolioService.py # 资产配置（MPT、再平衡）
│   │   ├── recommendService.py # 推荐引擎（协同过滤、个性化）
│   │   └── dataMiningService.py # 数据挖掘（行为分析、趋势预测）
│   │
│   ├── Models/                  # 业务模型层（ORM）
│   │   ├── __init__.py         # 模型职责说明
│   │   ├── advisorModel.py     # 投顾信息表
│   │   ├── productModel.py     # 理财产品表
│   │   ├── userProfileModel.py # 用户画像表
│   │   ├── portfolioModel.py   # 资产配置表
│   │   ├── riskAssessmentModel.py # 风险评估表
│   │   ├── consultationModel.py # 咨询记录表
│   │   └── transactionModel.py # 交易记录表
│   │
│   ├── Agent/                   # 智能 Agent 层
│   │   ├── __init__.py         # Agent 职责说明
│   │   ├── customerServiceAgent.py # 智能客服（FAQ、多轮对话）
│   │   ├── advisorAgent.py     # 投顾助手（咨询、解读、建议）
│   │   ├── riskAgent.py        # 风险研判（预警、检测、报告）
│   │   ├── portfolioAgent.py   # 资产配置（MPT、回测、优化）
│   │   └── dataMiningAgent.py  # 数据挖掘（聚类、预测、洞察）
│   │
│   ├── Tools/                   # Agent 工具层（新增）
│   │   ├── __init__.py         # 工具职责说明
│   │   ├── knowledgeRetrievalTool.py  # RAG 向量检索工具
│   │   ├── profileExtractTool.py      # 画像抽取工具
│   │   ├── suitabilityCheckTool.py    # 适当性硬匹配工具
│   │   ├── graphQueryTool.py          # Neo4j 图谱查询工具
│   │   ├── nl2sqlTool.py              # 自然语言转 SQL 工具
│   │   ├── sqlExecutorTool.py         # SQL 执行工具
│   │   ├── nl2apiTool.py              # 自然语言转 API 工具
│   │   ├── apiExecutorTool.py         # API 执行工具
│   │   ├── ruleEvaluatorTool.py       # 规则引擎评估工具
│   │   └── eventPublisherTool.py      # 事件发布工具
│   │
│   ├── Prompts/                 # 提示词模板层（新增）
│   │   ├── __init__.py         # 提示词管理说明
│   │   ├── customerServicePrompts.py  # 客服 Agent 提示词
│   │   ├── advisorPrompts.py          # 投顾 Agent 提示词
│   │   ├── riskPrompts.py             # 风控 Agent 提示词
│   │   ├── operatorPrompts.py         # 业务操作 Agent 提示词
│   │   └── commonPrompts.py           # 通用提示词片段
│   │
│   ├── Middleware/              # Agent 中间件层（新增）
│   │   ├── __init__.py         # 中间件职责说明
│   │   ├── memoryRecallMiddleware.py  # 记忆召回中间件
│   │   ├── safetyEnhancer.py          # 安全增强器（可选）
│   │   └── rbacMiddleware.py          # 权限校验中间件（可选）
│   │
│   ├── EventBus/                # 事件总线层（新增）
│   │   ├── __init__.py         # 事件总线说明
│   │   ├── eventBus.py         # 事件总线核心类
│   │   ├── schemas.py          # 事件 Schema 定义
│   │   └── consumer.py         # 消费者注册与启动
│   │
│   ├── Knowledge/               # 知识库管理层（新增）
│   │   ├── __init__.py         # 知识库管理说明
│   │   ├── ragIngestion.py     # RAG 向量入库管道
│   │   ├── graphBuilder.py     # 知识图谱构建管道
│   │   ├── chunkStrategy.py    # 切片策略实现
│   │   ├── embeddingService.py # 嵌入模型封装
│   │   └── collectionManager.py # Milvus 集合管理
│   │
│   ├── Rules/                   # 规则引擎层（新增）
│   │   ├── __init__.py         # 规则引擎说明
│   │   ├── ruleEngine.py       # 规则引擎核心
│   │   ├── ruleDefinitions.py  # 15 条规则定义
│   │   ├── ruleLoader.py       # 规则加载器
│   │   ├── confidenceCalculator.py # 置信度计算器
│   │   └── ruleAuditor.py      # 规则审计
│   │
│   ├── Utils/                   # 业务工具层
│   │   ├── __init__.py         # 工具职责说明
│   │   ├── financeCalc.py      # 金融计算（收益率、夏普比率）
│   │   ├── riskCalc.py         # 风险计算（VaR、风险等级）
│   │   ├── dataFormatter.py    # 数据格式化（金额、日期、百分比）
│   │   ├── chartHelper.py      # 图表辅助（ECharts 配置）
│   │   └── validator.py        # 业务校验（身份证、银行卡）
│   │
│   └── __init__.py              # 模块总说明
│
└── main.py                      # 项目启动入口（转发 Base.main.app）
```

## 分层职责

### 1. Api 层（接口适配层）
- **职责**：定义 RESTful API，处理 HTTP 请求与响应
- **原则**：只做接口适配，不写业务逻辑
- **调用**：Api → Service
- **示例**：
  ```python
  @router.get("/api/wealth/advisor/list")
  def get_advisor_list(page: int = 1):
      advisors = AdvisorService.list_advisors(page)
      return HttpResponse.ok(data=advisors)
  ```

### 2. Service 层（业务逻辑层）
- **职责**：封装核心业务逻辑、算法、跨表操作
- **原则**：无状态设计，可被 Api/Agent/定时任务调用
- **调用**：Service → Models / Agent / Base.Client
- **示例**：
  ```python
  class AdvisorService:
      @staticmethod
      def match_advisor(user_id: int, risk_level: str):
          # 业务逻辑：匹配算法、评分排序
          advisors = AdvisorModel.find_by_risk(risk_level)
          return sorted(advisors, key=lambda x: x.score)
  ```

### 3. Models 层（数据持久层）
- **职责**：定义数据库表结构，封装单表 CRUD
- **原则**：只做数据映射，不包含业务判断
- **调用**：Models → Base.Client.mysqlClient
- **示例**：
  ```python
  class AdvisorModel(BaseModel):
      __tablename__ = 'wealth_advisor'
      name = Column(String(50))
      rating = Column(Float)
  ```

### 4. Agent 层（智能决策层）
- **职责**：实现 AI 推理、多轮对话、工具调用
- **原则**：封装复杂决策流程，调用 LLM 与向量数据库
- **调用**：Agent → Service / Base.Ai.llms / Milvus / Neo4j
- **示例**：
  ```python
  class AdvisorAgent:
      def consult(self, question: str):
          # LangGraph 编排：意图识别 → 工具调用 → 生成回答
          tools = [产品查询, 风险评估]
          return agent_executor.invoke(question)
  ```

### 5. Tools 层（Agent 工具层）
- **职责**：实现 10 个 BaseTool 子类，封装 Agent 可调用的原子能力
- **原则**：继承 Base.Ai.base.baseTool.BaseTool，实现 Function Calling 协议
- **调用**：Tools → Service / Models / Base.Client
- **示例**：
  ```python
  class KnowledgeRetrievalTool(BaseTool):
      name = "KnowledgeRetrieval"
      query: str = Field(..., description="检索关键词")
      collection_name: str = Field(..., description="集合名称")
      
      def _run(self, query: str, collection_name: str) -> list[dict]:
          results = KnowledgeService.retrieve(query, collection_name)
          return results
  ```

### 6. Prompts 层（提示词模板层）
- **职责**：管理 5 个 Agent 的 System Prompt 骨架（5段式模板）
- **原则**：提示词与代码分离，便于迭代优化与版本管理
- **调用**：Prompts ← Agent（构造时加载）
- **示例**：
  ```python
  SYSTEM_PROMPT = '''
  ①角色定义：你是智能客服 Agent
  ②能力边界：可以查询产品/政策，不能执行购买操作
  ③工具使用：KnowledgeRetrieval、ProfileExtract、work_order_tool
  ④输出格式：必须引用来源，SSE 流式按段分块
  ⑤合规红线：不得承诺收益、预测涨跌
  '''
  ```

### 7. Middleware 层（Agent 中间件层）
- **职责**：实现中间件洋葱模型（Logging → Metrics → Safety → MemoryRecall → Eval）
- **原则**：AOP 面向切面，横切关注点统一处理
- **调用**：Middleware 包裹 Agent 执行链路
- **示例**：
  ```python
  class MemoryRecallMiddleware(BaseMiddleware):
      def before(self, context: dict) -> dict:
          # 召回短期记忆（Redis）+ 中期记忆（用户画像）
          context['short_term_memory'] = memory.get_session_history(session_id)
          context['long_term_memory'] = memory.get_customer_profile(user_id)
          return context
      
      def after(self, context: dict, result: Any) -> Any:
          # 保存本轮对话到记忆系统
          memory.append_message(session_id, role='user', content=input)
          memory.append_message(session_id, role='assistant', content=output)
          return result
  ```

### 8. EventBus 层（事件总线层）
- **职责**：封装 Redis Streams 的发布/订阅，实现 Agent 间异步通信
- **原则**：事件驱动架构，解耦 Agent 之间的消息传递
- **调用**：EventBus ← Agent（发布事件）/ Consumer（订阅事件）
- **示例**：
  ```python
  # 发布事件
  EventBus.publish(
      stream_key='stream:large_transaction',
      event_type='product_purchased',
      payload={'customer_id': 123, 'amount': 500000}
  )
  
  # 消费事件
  EventBus.consume(
      stream_key='stream:large_transaction',
      consumer_group='risk_monitor_group',
      consumer_name='worker-1',
      handler=handle_large_transaction
  )
  ```

### 9. Knowledge 层（知识库管理层）
- **职责**：实现 RAG/GraphRAG 的切片、向量化、入库流程
- **原则**：离线数据准备，与在线检索解耦
- **调用**：Knowledge → Base.Client.milvusClient / neo4jClient
- **示例**：
  ```python
  ingestion = RAGIngestion()
  ingestion.ingest_product_docs('D:\\公司业务')  # 产品手册切片入库
  ingestion.ingest_policy_docs('D:\\金融政策')   # 政策文档切片入库
  
  graph_builder = GraphBuilder()
  graph_builder.build_fund_graph(fund_data)      # 构建基金-公司-行业图谱
  ```

### 10. Rules 层（规则引擎层）
- **职责**：实现风控规则的定义、评估、触发逻辑（15 条规则）
- **原则**：声明式规则系统，配置与代码分离
- **调用**：Rules → Service（获取业务数据）
- **示例**：
  ```python
  # 定义规则
  AML_001 = RuleDefinition(
      rule_id='AML_001',
      rule_name='短期内大额现金存取',
      conditions=[
          RuleCondition(field='cash_withdraw_7d', operator='>', value=100000, weight=0.5)
      ],
      threshold=0.6
  )
  
  # 评估规则
  context = {'cash_withdraw_7d': 150000, 'tx_count_1d': 15}
  result = RuleEngine.evaluate_rule(AML_001, context)
  # result = {'triggered': True, 'confidence': 0.85, 'violated_conditions': [...]}
  ```

### 11. Utils 层（业务工具层）
- **职责**：提供纯函数式的业务工具（金融计算、格式化、校验）
- **原则**：无状态、无副作用，可被任意层调用
- **调用**：Utils ← Api / Service / Agent
- **示例**：
  ```python
  def calc_sharpe_ratio(returns: list) -> float:
      return np.mean(returns) / np.std(returns)
  ```

## 开发规范

### 复用 Base 能力
```python
# 数据库操作
from Base.Client.mysqlClient import get_mysql_client

# LLM 调用
from Base.Ai.llms.qwenLlm import QwenLlm

# 认证服务
from Base.Service.authService import AuthService

# HTTP 响应
from Base.RicUtils.httpUtils import HttpResponse
```

### 注册业务路由
在 `Base/main.py` 末尾添加：
```python
from WealthButler.Api.advisorApi import router as advisor_router
app.include_router(advisor_router)
```

### 数据库表命名
- 统一前缀 `wealth_` 避免与脚手架表冲突
- 示例：`wealth_advisor`、`wealth_product`、`wealth_user_profile`

### 配置管理
- 业务配置优先扩展 `Base/Config/setting.py`
- 或在 `WealthButler/` 下创建独立配置类

## 4 天开发计划（11 层架构版）

### Day 1：数据层 + 基础设施 + 关键路径攻坚启动

**数据层（优先级最高）：**
- MySQL 10 张业务表建表（Models 层）
- Milvus 3 个集合创建（FAQ/产品/政策）+ 索引配置
- Neo4j 图谱 schema 设计（节点/关系定义）
- Redis Key 结构设计（会话缓存/画像缓存）

**基础设施层：**
- EventBus 层：实现 Redis Streams 的 `publish()` / `consume()` 封装
- Knowledge 层：RAG 向量入库管道骨架（文档解析 → 分块 → Embedding → 写入）
- Rules 层：规则引擎骨架搭建（RuleEngine + RuleDefinition 基础结构）

**关键路径攻坚（并行开工）：**
- Tools 层：优先实现 KnowledgeRetrievalTool、GraphQueryTool（Agent 依赖）
- Service 层：实现基础 CRUD Service（advisorService、productService）

**验收标准：**
- [ ] 数据库表/集合/图谱 schema 全部就绪
- [ ] EventBus 可用 mock 事件验证发布/消费
- [ ] RAG 管道可执行文档入库（至少 1 个集合）

---

### Day 2：Agent 层 + Tools 层 + Prompts 层

**Tools 层完成（10 个工具）：**
- KnowledgeRetrievalTool（RAG 检索）
- ProfileExtractTool（画像抽取）
- SuitabilityCheckTool（适当性硬匹配）
- GraphQueryTool（Neo4j 图谱查询）
- NL2SQLTool + SQLExecutorTool（自然语言转 SQL）
- NL2APITool + APIExecutorTool（自然语言转 API）
- RuleEvaluatorTool（规则引擎评估）
- EventPublisherTool（事件发布）

**Prompts 层编写：**
- customerServicePrompts.py（客服 5段式 System Prompt）
- advisorPrompts.py（投顾 5段式 System Prompt）
- riskPrompts.py（风控 5段式 System Prompt）
- operatorPrompts.py（业务操作 5段式 System Prompt）

**Agent 层实现（核心 2 个）：**
- customerServiceAgent.py（智能客服：RAG + 短期记忆 + 意图分类）
- advisorAgent.py（投顾助手：GraphRAG + 中期记忆）

**Middleware 层：**
- memoryRecallMiddleware.py（记忆召回中间件，集成 Base 的 MemoryV1Service）

**Knowledge 层完成：**
- 3 个 Milvus 集合数据入库（FAQ/产品/政策）
- Neo4j 图谱数据导入（节点>100、关系>200）

**验收标准：**
- [ ] 客服 Agent 可完成产品咨询（准确率≥80%，5题+）
- [ ] Tools 层 10 个工具全部可单独调用测试通过

---

### Day 3：Rules 层 + 剩余 Agent + API 层

**Rules 层完成（15 条规则）：**
- ruleDefinitions.py：定义 15 条风控规则（8 条实时/准实时 + 7 条日批/周批）
- ruleEngine.py：规则评估器（多规则融合、置信度计算）
- confidenceCalculator.py：置信度体系实现

**剩余 Agent 实现：**
- riskAgent.py（风控监测：规则引擎 + EventBus 消费）
- dataMiningAgent.py（数据分析：NL2SQL）
- operatorAgent.py（业务操作：NL2API + RBAC + 二次确认状态机）

**Api 层开发：**
- advisorApi.py、productApi.py、riskApi.py、analysisApi.py
- `/api/chat` 统一入口（按 `agent_type` 分发）
- 注册所有业务路由到 `Base/main.py`

**Service 层完善：**
- riskAssessService.py（风险评估问卷 + 适当性匹配）
- portfolioService.py（资产配置 MPT 算法）
- recommendService.py（推荐引擎）

**验收标准：**
- [ ] 20 条风控规则正确匹配（10 测试交易+）
- [ ] NL2API 意图识别准确率>80%
- [ ] 所有 API 接口在 Swagger 可访问

---

### Day 4：系统集成 + 跨 Agent 协作 + 答辩准备

**跨 Agent 集成联调：**
- EventBus 事件流验证（大额交易 → 风控预警 → 投顾/客服联动）
- 中间件洋葱模型验证（Logging → Metrics → Safety → MemoryRecall → Eval）
- 多 Agent 协作编排验证（统一入口分发 + 直连路由）

**端到端业务流程测试：**
- 完整客户旅程：开户 → 风评 → 咨询 → 申购 → 持仓 → 风控触发 → 工单处理
- 边界 case 覆盖：权限拒绝、危险 SQL 拦截、适当性违规拦截

**性能与体验优化：**
- RAG<2s、NL2SQL<3s、Agent 完整回答<5s
- SSE 流式输出验证
- 降级方案测试（主模型失败切 DeepSeek）

**答辩准备：**
- 答辩 PPT 制作（15 分钟，重点展示 RAG/GraphRAG/NL2SQL/NL2API 四类场景）
- Demo 脚本演练（各 Agent 负责人自测各自部分）
- 技术文档整理归档
- Vibe Coding 经验总结（2~3 个真实案例）

**验收标准：**
- [ ] 端到端流程无阻塞
- [ ] 性能指标达标
- [ ] 答辩演示脚本准备完毕

## 技术栈依赖

已安装（来自脚手架）：
- FastAPI、Uvicorn（Web 框架）
- SQLAlchemy、PyMySQL（数据库 ORM）
- Redis、pymilvus、neo4j（中间件客户端）
- langchain、langgraph（AI Agent 框架）
- dashscope（通义千问 API）

需补充（根据业务需要）：
- pandas、numpy（数据处理）
- scikit-learn（机器学习）
- matplotlib、echarts（图表可视化）

---

**重要提示**：
1. Base/ 是通用脚手架，保持其纯净性，不要直接修改
2. WealthButler/ 是你们的业务代码，完全自主开发
3. 保持分层边界清晰，避免跨层直接调用（如 Api 直接调 Models）
4. 所有业务路由必须在 Base/main.py 中注册才能生效
"""
