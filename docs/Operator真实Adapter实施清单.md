# Operator 真实 Adapter 实施清单

## 1. 当前状态

`OperationService` 已完成权限、适当性、业务预检、二次确认和审计编排，
`operatorAdapters.py` 已定义稳定协议；真实读、规则、写、事务、Redis 确认和
Runtime 装配 Adapter 已落地并通过离线回归。当前正式入口仍未装配真实 Runtime，
`operatorFakes.py` 和 `OperatorApiRuntimeFactory.create_fake()` 仅用于离线测试。

生产目标是通过 `OperatorApiRuntimeFactory.create_real()` 显式装配真实依赖，
并在应用启动时调用 `ensure_operator_runtime(real_runtime)`。任何依赖未完成时继续失败关闭，
不得回退到 Fake。

## 2. Adapter 与现有能力映射

| Adapter | 真实数据来源 | 当前可复用能力 | 缺口 |
|---|---|---|---|
| PermissionGateway | Base RBAC | `AuthService.has_permission` | 统一 `source_module` 口径 |
| CustomerGateway | `base_user` | `BaseUserExtModel.get_by_id` | 必须校验 `CUSTOMER`、启用状态和软删除 |
| AdvisorQualificationGateway | `base_user.employee_role` | `BaseUserExtModel` | 需要明确顾问等级到产品准入层级映射 |
| ProductGateway | `fin_product` | `ProductModel` | 补分页、组合筛选和 `admission_tier` 可信来源 |
| SuitabilityGateway | `fin_customer_profile`、`fin_risk_assessment`、规则引擎 | `RiskAssessService.check_suitability` | 需输出 FM 命中、披露要求和人工审核要求 |
| PurchaseComplianceGateway | 规则引擎 | 适当性与熔断规则 | 需要形成单一结构化校验入口 |
| HoldingGateway | `fin_holdings` | `HoldingsModel` | 需要同事务锁定持仓并计算 R3 仓位 |
| TransactionGateway | `fin_transaction`、`fin_holdings` | `MySQLTransactionGateway` | 已实现行锁、原子提交和双唯一幂等边界；待执行 Schema 迁移 |
| WorkOrderGateway | `biz_work_order` | `WorkOrderModel`、`WorkOrderService` | 需要完整状态机持久化与并发版本检查 |
| RiskAssessmentGateway | `fin_risk_assessment`、客户画像 | `RiskAssessService` | 需要问卷保存、评分、画像重算和事件发布原子边界 |
| CustomerInfoGateway | `base_user` | `BaseUserExtModel` | 仅允许手机号、邮箱白名单更新并记录审计 |
| RiskAlertGateway | `fin_risk_alert` | `RiskService.create_alert` | 增加人工上报来源、证据引用与 reporter_id |
| EventPublisher | Redis Streams | `EventBus` | 统一标准事件信封、重试和死信策略 |
| OperationRiskGateway | 规则引擎、交易数据 | 风控规则定义 | 赎回和转账前置规则尚无统一服务接口 |
| OperationAuditGateway | `biz_operation_audit` | `MySQLOperationAuditGateway` | 已实现只追加、只保存参数名；待执行 Schema 迁移 |
| ConfirmationGateway | Redis | `RedisConfirmationGateway` | 已实现 TTL、Lua CAS 和最终结果恢复 |

## 3. 必须先完成的数据约束

### 3.1 交易幂等与审计

`fin_transaction` 至少补充：

- `employee_id`：实际发起操作的员工；
- `trace_id`：贯穿 Agent、确认、交易和事件；
- `idempotency_key`：唯一索引，阻止重复成交；
- `failure_code`、`failure_reason`：失败结果审计；
- 需要时增加 `updated_at`，支持状态流转。

禁止仅依赖“先查询、再插入”实现幂等；`idempotency_key` 和非空 `trace_id` 唯一索引必须是最终防线。

落地文件：

- `scripts/migrations/operator_schema_migration.py`：默认只输出离线 dry-run 计划；`--connect-dry-run` 仅连接并对每个字段、索引和表查询 `information_schema`，不执行或提交 DDL；`--verify` 只读输出行数、目标字段、索引和重复键摘要；只有显式 `--apply --confirm APPLY_OPERATOR_SCHEMA` 时才允许迁移。
- `tests/test_operator_schema_migration.py`：纯离线验证字段集、唯一索引、独立审计表、Schema 先检查和 dry-run 不执行 DDL。

本迁移为历史数据保留兼容，`fin_transaction` 新字段先以可空方式加入；真实 Adapter 必须对新交易强制写入 `employee_id`/`trace_id`/`idempotency_key`。审计表仅设 `created_at`，不设更新时间；部署时应给 Adapter 账号仅授予 `INSERT`/`SELECT`，不授予 `UPDATE`/`DELETE`。

2026-08-17 已对当前项目业务库执行该幂等迁移：迁移前后 `fin_transaction` 均为 1282 行；6 个目标字段、`employee_id` 普通索引、`trace_id`/`idempotency_key` 唯一索引及 `biz_operation_audit` 表均已核实；两类非空幂等键重复组均为 0；审计表初始为 0 行。迁移后再次运行连接式 dry-run，所有步骤均返回 `already_satisfied`。

### 3.2 交易与持仓原子性

申购、赎回必须在同一 MySQL 事务内完成：

1. 按客户和产品锁定持仓记录；
2. 再次校验可用份额或购买条件；
3. 写入交易流水；
4. 更新持仓份额、成本和市值；
5. 提交事务后发布事件。

事件发布失败不能回滚已成交交易，应写入可靠事件表或重试队列。

### 3.3 二次确认

Redis 确认记录必须保存员工、客户、命令、trace ID、创建时间、过期时间和最终结果。
领取确认使用原子 CAS：`待确认 -> 已确认 -> 执行`。执行结果未知时禁止自动重试成交。

## 4. 推荐实施顺序

1. 实现只读 Adapter：权限、客户、顾问资质、产品、持仓。
2. 实现适当性、购买合规、赎回和转账前置风控 Adapter。
3. 增加交易幂等字段、操作审计表及迁移脚本。
4. 实现 MySQL TransactionGateway，保证交易与持仓原子提交。
5. 实现 WorkOrder、RiskAssessment、CustomerInfo、RiskAlert 写入 Adapter。
6. 实现 RedisConfirmationGateway 与确认并发测试。
7. 实现 EventPublisher 和可靠重试边界。
8. 创建正式 Runtime 工厂，在 `main.py` 生命周期中显式装配。
9. 完成申购、赎回、转账和二次确认端到端测试。

当前 1-7 的代码与离线测试已完成，正式 Runtime 工厂也已完成但未在
`main.py` 启用。剩余门禁是：DBA 审核并执行迁移、提供真实连接工厂与
合规证据读取器，然后完成 8-9 的生产装配和端到端验收。

## 5. 最低验收标准

- 客户端不能指定或冒充 `employee_id`；
- 员工只能执行其真实 RBAC 权限允许的意图；
- 申购、赎回、转账均有幂等保护；
- 同一确认令牌并发确认时最多成交一次；
- 交易和持仓不会出现单边提交；
- 每次成功、拒绝和未知结果均可通过 trace ID 审计；
- Redis、审计或事件依赖异常时按既定策略失败关闭或进入可靠重试；
- 正式启动链路中不存在 Fake Runtime 自动回退。
