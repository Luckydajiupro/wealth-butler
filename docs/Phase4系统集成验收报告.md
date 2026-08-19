# Phase 4 系统集成验收报告

## 1. 结论

Phase 4 的正式入口、五类 Agent 契约、真实只读客户旅程、Operator 隔离写链、跨存储种子数据和运行时资源关闭均已完成自动化验收。当前全量自动化测试为 `176 passed`；第三方Starlette/httpx2弃用提示及Windows沙箱`.pytest_cache`权限提示均不影响结果。外部LLM回答质量、性能压测、Memory v2迁移和历史DLQ处置仍属于Phase 5事项。

## 2. 正式入口与 API

- `app/WealthButler/main.py` 使用 real Operator Runtime 成功启动。
- MySQL、Redis、MinIO 和 DeepSeek 配置完成装配。
- OpenAPI/Swagger 返回 200，共 64 条路径、69 个操作。
- 路由注册幂等，method + path 无重复，核心路由完整。
- EventBus 恰好启动 5 个消费者；关闭时全部 stop/join。
- 调度器只注册 `ai_summary`、`risk_daily`、`risk_weekly` 三个唯一任务，不再重复注册。
- 服务关闭后进程退出，8010 端口无残留监听。
- 未认证访问返回 401，客户和低权限员工越权访问返回 403。
- 本地隔离 SSE 返回 `text/event-stream`，帧格式为标准 `data: ...\n\n`。

## 3. 真实只读客户旅程

执行脚本：`scripts/verify_phase4_customer_journey.py`

以 `wb_seed_c1_elderly` 为核心验收客户，真实读取 MySQL、Milvus、Neo4j 和 embedding：

| 环节 | 结果 |
|---|---|
| 登录与 JWT 回读 | 通过；客户无员工权限 |
| 风险评估 | C1，17 条答案，有效期至 2027-08-15 |
| 客服反诈 RAG | 返回 5 条命中 |
| 投顾 GraphRAG | 返回 2 行图谱结果 |
| 适当性过滤 | 76 个候选中仅放行 R1/R2，共 32 项 |
| 持仓 | 读取 1 项真实种子持仓 |
| 预警到工单 | 10 条关联，覆盖 RW-003/RW-011 |
| NL2SQL | C1-C5 聚合 5 行；强制 LIMIT；敏感列与多语句拒绝 |

## 4. 五类 Agent 与 Operator 写链

- 客服、投顾、分析、风控、Operator 五类 Agent 的隔离契约测试通过。
- Operator 申购超过 1 万元触发二次确认。
- 并发确认最多执行一次。
- 事件发布失败进入重试路径。
- 权限、适当性、合规证据缺失均 fail-closed。
- 写链使用隔离依赖验证，未产生真实资金交易。
- 外部 LLM 文案生成不作为自动化门禁；业务决策使用确定性注入，真实 RAG、Graph、数据库和工具层已验收。

## 5. Redis/EventBus 修复

只读盘点发现三个正式 DLQ 共 46 条历史消息：4 条 schema 不合法，42 条 schema 合法但旧 handler 返回失败。历史 DLQ 缺少稳定错误码，无法仅凭记录还原其业务失败原因；本次未删除、重放或篡改这些消息。

EventBus 已修复：

- handler 成功后才提交 processed 幂等标记并 ACK。
- handler 返回 False 或抛异常时保留 PEL，允许后续安全重放。
- processing 短锁防止并发重复处理。
- 新 DLQ 使用稳定且脱敏的错误码和错误类型，不持久化异常详情。

## 6. 客户记忆集合

真实 `fin_customer_memory_collection` 当前有 100 行，但除 1024 维 embedding 外的字段均为 VARCHAR，且主键 `auto_id=True`，与当前 Model 的数值字段声明存在漂移。

已完成：

- 旧 schema 兼容读取和正确的 Milvus `filter` 参数。
- Model 支持通过 `WEALTH_BUTLER_MEMORY_COLLECTION` 灰度切换集合。
- side-by-side v2 迁移脚本支持 dry-run/apply/verify，只追加、不 drop、不 rename、不覆盖。
- 真实 dry-run：source=100、target 不存在、would_copy=100、`DRY_RUN_OK`。

本阶段未执行 v2 apply，也未创建新集合；该迁移需要单独批准后再执行。

## 7. 本阶段修复

- 用户 `extra_data` JSON 反序列化，修复员工身份 403 假阳性。
- 风评 `answers` JSON 反序列化，修复投顾读取风评失败。
- 客服 Agent 在 LLM 降级时识别持仓、总资产、收益意图。
- 调度器去除重复注册。
- EventBus 生命周期 stop/join 与失败重放语义修复。
- MemoryService 兼容真实 Milvus schema。

## 8. 后续阶段入口

Phase 5 继续项：性能指标压测、外部 LLM 完整回答质量抽测、历史 DLQ 处置决策、Memory v2 灰度迁移、Demo 脚本和答辩交付物整理。
