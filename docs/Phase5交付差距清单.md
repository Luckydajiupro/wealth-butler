# Phase 5 交付差距清单

## 1. 审计口径

- 审计日期：2026-08-17。
- 完成状态只认当前代码、可重复测试和Phase 4真实验收报告，不按旧开发计划勾选框推断。
- 正式入口固定为`app/WealthButler/main.py`；`app/Base`是复用脚手架，不是业务启动入口。
- Memory v2 side-by-side apply、独立 verify 和本机灰度切换已完成；旧集合保留。历史 DLQ 已快照和终态分类，无效 PEL 已 ACK，DLQ 未删除或重放。
- 用户批准后已用现有 `deepseek-v4-flash` 配置完成客服 SSE 外部验收。
- 当前全量自动化基线：`python -m pytest -q -p no:cacheprovider` → **193 passed**。第三方Starlette/httpx2弃用提示不影响测试结果。

## 2. 已完成并有代码/测试证据

| 能力 | 当前事实 | 主要证据 |
|---|---|---|
| 正式启动与生命周期 | WealthButler入口装配路由、5个EventBus消费者、日/周批调度器和可选真实Operator Runtime；关闭时释放资源 | `app/WealthButler/main.py`、《Phase4系统集成验收报告》 |
| 启停与 SSE 性能 | scheduler/路由并行加载差分中位改善26.3%；正式入口关闭1.39s；DeepSeek真流式热连接首帧1.85s | `tests/startup_cold_probe.py`、`scripts/verify_graceful_shutdown.py`、《Phase5性能基线报告》 |
| 风控规则 | RW-001~RW-020共20条；8条实时/准实时，10条日批、2条周批，合计12条批量 | `Rules/ruleDefinitions.py`的`REALTIME_RULE_IDS`/`DAILY_RULE_IDS`/`WEEKLY_RULE_IDS`；`riskAgent.py` |
| EventBus | 成功后才写processed并ACK；失败留PEL；processing锁防并发；DLQ有稳定脱敏错误码 | `EventBus/eventBus.py`、`tests/test_eventbus.py` |
| MySQL结构 | 13张自有业务表：初始10张，加`biz_operation_audit`、`biz_compliance_evidence`、`fin_verified_payee`三张迁移补充表；另复用Base RBAC表 | `Models/`、`scripts/migrations/operator_schema_migration.py`、`compliance_data_schema_migration.py`、《表设计文档》 |
| 数据层规模 | 180客户、30员工、55产品；客户/员工/产品/持仓跨MySQL、Milvus、Neo4j稳定关联 | 《Phase4真实种子数据导入报告》及三个seed脚本的`--verify` |
| Milvus/Neo4j | FAQ 100、产品100、政策148、客户记忆100；Neo4j 380节点/1462关系 | `scripts/seed_vector_graph_data.py --verify`、Phase 4种子报告 |
| Redis/MinIO | 隔离seed键/短TTL会话/事件信封和3个DEMO_SEED证据对象；MySQL URI/SHA严格一致 | `scripts/seed_cross_store_scenarios.py --verify` |
| 五类Agent关键旅程 | 客服RAG、投顾GraphRAG、分析NL2SQL、Operator受控写链、风控双轨具备自动化或真实只读旅程证据 | `scripts/verify_phase4_customer_journey.py`、《Phase4系统集成验收报告》 |
| API运行基线 | OpenAPI/Swagger 200；64条路径、69个操作；路由注册无method+path重复 | 《Phase4系统集成验收报告》 |
| 安全边界 | 未认证401、越权403；NL2SQL仅SELECT/白名单/LIMIT；Operator适当性、权限、证据均fail-closed | Phase 4验收报告与对应tests |

## 3. 已批准并完成的受控变更

| 项目 | 当前状态 | 回滚/保留边界 | 证据 |
|---|---|---|---|
| 客户记忆 v2 迁移 | 目标集合100条，`VERIFY_OK`，本机已切换v2 | 移除 `.env` 切换变量即回到旧集合；旧集合不删除 | 《Phase5MemoryV2与历史DLQ处理报告》 |
| 历史 DLQ 处置 | 51条均为非正客户ID的终态schema非法消息；5条PEL已ACK，PEL归零 | DLQ 51条和完整快照保留；未调用handler重放 | 《Phase5MemoryV2与历史DLQ处理报告》 |

## 4. 待补代码/API适配

OpenAPI已有64条路径不代表需求/API设计中的每条目标路径均存在。下列是设计文档列出但当前未按原路径落地的主要接口：

- `/api/knowledge/*`知识库上传、检索、列表、下线；
- `/api/profile/*`规范画像/问卷路径（当前部分能力位于`/api/wealth/analyst/*`）；
- `/api/product/*`产品列表、详情、结构化推荐；
- `POST /api/risk/monitor`手动规则扫描；
- `/api/graph/*`统计和可视化；
- `POST /api/admin/recalculate-confidence`。

这些接口不能因Service/Tool已有类似能力而标记为REST完成。Phase 5若不补齐，应在答辩中明确“内部能力已实现、管理型REST适配延期”，并以现有可演示路径为准。

## 5. 待人工演练/量化验收

| 项目 | 自动化现状 | 人工验收要求 |
|---|---|---|
| 外部LLM完整回答质量 | 客服 DeepSeek SSE 已完成通道和耗时验收；未形成固定题集质量统计 | 使用批准的模型配置抽测客服、投顾、分析、Operator各场景，记录回答、引用、降级与耗时 |
| 性能指标 | 已形成Phase 5基线；RAG/NL2SQL达标，DeepSeek热连接达标，冷连接首帧5.87s未达标 | 扩大DeepSeek冷/热样本并固化P50/P95，不用单次样本代替统计结论 |
| 准确率指标 | 有真实旅程和单元测试，但不等于统计准确率 | 客服咨询≥80%、NL2SQL≥80%、Operator意图>80%/参数>90%，使用固定题集计算 |
| GraphRAG增益 | 图谱规模与真实查询已通过 | 用同一查询对比纯RAG与GraphRAG，记录相关性/解释性差异 |
| 前端与答辩Demo | 启动、Swagger、SSE已验收 | 按固定脚本完整演练登录→风评→咨询→推荐→受控操作→预警/工单，并准备失败降级演示 |
| 业务阈值与默认权重 | 代码有确定性默认值 | 团队确认风控/记忆/Graph排序权重是否作为最终答辩口径 |

## 6. Phase状态结论

| Phase | 当前结论 |
|---|---|
| Phase 1 | 核心代码与RAG旅程已完成；客服统计准确率和完整多轮Demo待人工量化 |
| Phase 2 | 画像、风评、NL2SQL安全链已完成；NL2SQL固定题集准确率待人工量化 |
| Phase 3 | Neo4j/GraphRAG、投顾、Operator受控链已完成；GraphRAG对照实验及意图准确率待人工量化 |
| Phase 4 | 20条双轨规则、三层记忆、EventBus、真实种子、Memory v2迁移与历史DLQ受控处置已完成 |
| Phase 5 | **进行中**：自动化集成基线通过；剩余重点为目标API取舍、性能/质量量化、完整Demo和答辩材料收口 |

## 7. 交付前最小门禁

1. `python -m pytest -q`保持全绿。
2. `python scripts/seed_wealthbutler_business_data.py --verify`、`seed_cross_store_scenarios.py --verify`、`seed_vector_graph_data.py --verify`均通过。
3. 用正式入口启动后，Swagger、登录、五类角色权限、核心旅程和SSE逐项复验。
4. 对“待批准”项目必须保留书面批准和执行前后verify证据；未批准则保持现状。
5. 答辩材料不得把“设计接口”“dry-run成功”或“内部Service存在”表述成“已上线完成”。
