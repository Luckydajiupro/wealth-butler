# Phase 4 Redis DLQ 与客户长期记忆 Schema 修复方案

> 状态更新（2026-08-17）：本文第 1-2 节的 46 条为当时只读诊断快照。后续总数增至 51 条，经批准后已完成快照、根因修复和 PEL 终态处理；当前结果以《Phase5MemoryV2与历史DLQ处理报告》为准。

## 1. 只读诊断结论

- Redis 正式业务 DLQ 共 3 条流、46 条历史记录：
  - `large_transaction` 2 条：均缺 `transaction_id`，且 `amount` 不是字符串；
  - `risk_alert` 1 条：缺 `rule_id`、`severity`；
  - `suspicious_intent` 43 条：1 条 `confidence` 不是字符串，42 条 schema 合法但旧处理器返回失败。
- 历史 DLQ 没有稳定 `error_code/error_type`，42 条业务失败记录无法仅凭 DLQ 继续确定根因。不得读取或打印 payload 来猜测。
- EventBus 原实现先写 `eventbus:processed:*` 再调用 handler。handler 异常时消息虽留在 PEL，重放却会因 processed 标记而直接 ACK，存在静默丢消息窗口。
- `fin_customer_memory_collection` 当前 100 行，`auto_id=true`；`embedding` 为 `FLOAT_VECTOR(1024)`，其余字段全部为 `VARCHAR`。当前 Model 将 `id/customer_id/timestamps/access_count` 声明为 `INT64`、`importance` 声明为 `FLOAT`，存在真实 schema 漂移。

## 2. EventBus 无损修复

- JSON/schema 非法是不可重试错误：写 DLQ，错误码分别为 `INVALID_JSON`、`SCHEMA_VALIDATION_FAILED`，然后 ACK。
- handler 返回失败或抛异常是可重试错误：错误码分别为 `HANDLER_REJECTED`、`HANDLER_EXCEPTION`；DLQ 只记录异常类型，不写 `str(exc)`，消息保留在 PEL。
- `processed` 标记只在 handler 成功后与 ACK 一起提交；短时 `processing` 锁避免并发重复执行。
- 同一原消息通过独立 marker 限制重复 DLQ 记录。历史 46 条不重放、不删除、不改写。

## 3. Milvus side-by-side v2 迁移

脚本：`scripts/migrate_customer_memory_schema_v2.py`

- 默认 dry-run，只验证旧数据可转换性；
- 目标集合固定为 `fin_customer_memory_collection_v2`；
- `--apply` 必须同时提供 `--confirm CREATE_MEMORY_V2_NO_DROP`；
- 只在目标不存在时新建，不 drop、不 rename、不覆盖；
- 额外保存 `source_id`，重复 apply 只追加缺失 source ID；
- `--verify` 核对目标 schema、源记录覆盖率和非向量字段值。

后续已经用户批准并执行：源 100 行全部复制到 v2，独立 verify 和客户隔离召回通过，本机已灰度切换。旧集合未删除、未重命名、未覆盖。详见《Phase5MemoryV2与历史DLQ处理报告》。

## 4. Model/Service 灰度切换与回滚

1. 经主线程单独批准后执行 v2 apply；随后独立执行 verify。
2. 先保持默认环境变量为空，生产仍读取旧集合；Service 会按实际 `customer_id` 类型生成 VARCHAR 或 INT64 过滤表达式。
3. 在验证环境设置 `WEALTH_BUTLER_MEMORY_COLLECTION=fin_customer_memory_collection_v2`，重启进程后进行按客户隔离、TopK、阈值和召回内容回归。
4. 验收通过后再在正式运行配置中切换同一环境变量。
5. 回滚只需移除环境变量并重启，恢复读取旧集合。旧集合全程保留；本方案不包含删除步骤。
