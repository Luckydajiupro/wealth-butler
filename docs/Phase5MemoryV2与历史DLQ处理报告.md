# Phase 5 Memory v2 与历史 DLQ 处理报告

> 执行日期：2026-08-17  
> 原则：旧 Milvus 集合不覆盖、不删除、不重命名；DLQ 不删除、不裁剪、不盲目重放

## 1. Memory v2 迁移

- 源集合：`fin_customer_memory_collection`，100 条，全程保留。
- 目标集合：`fin_customer_memory_collection_v2`，新建并复制 100 条。
- 强类型字段：`customer_id/created_at/last_accessed_at/access_count` 为 `INT64`，`importance` 为 `FLOAT`。
- 独立 `--verify` 结果：`VERIFY_OK`，源记录覆盖 100/100，`would_copy=0`。
- 实际向量召回：TopK 返回 5 条，客户隔离通过，源记录自身可召回。
- 本机 `.env` 已设置 `WEALTH_BUTLER_MEMORY_COLLECTION=fin_customer_memory_collection_v2`。

首次 apply 后的即时校验曾报 100 条值不一致。分字段诊断确认仅为 Milvus `FLOAT` 的 float32 正常精度差，其他字段全部一致。校验器改为有限容差比较并增加回归测试，未重复插入、未覆盖目标记录。

回滚方式：从 `.env` 移除 `WEALTH_BUTLER_MEMORY_COLLECTION`并重启，即恢复读取旧集合。

## 2. 历史 DLQ 处理

- 共 3 条 DLQ Stream、51 条记录，51 个唯一原消息。
- 根因：实时风控事件 schema 原允许非正客户 ID，RiskAgent 在 handler 阶段才拒绝，导致持续重试和 DLQ 增长。
- 修复：`LargeTransactionEvent` 和 `SuspiciousIntentEvent` 统一在 schema 边界要求 `customer_id > 0`。
- 处理：51 条均重新分类为 `TERMINAL_SCHEMA_INVALID`；其中仍在 PEL 的 5 条已 ACK，最终 `pel_total=0`。
- DLQ 保留：51 条原审计记录未删除、未修改、未重放 handler。
- 修复后快照：`runtime_artifacts/dlq/historical-dlq-20260817T022043Z-a5738432.json`。
- SHA-256：`a5ba069446c762d161760fd999c7bd0931b5ffcb8c31a34d63d795c6c2d9756f`。

快照包含完整恢复数据，位于 Git 忽略的 `runtime_artifacts/` 目录；命令输出和本报告均不包含 payload。

## 3. 验收

- 全量自动化：`193 passed`。
- Memory v2：`VERIFY_OK`，活动集合确认为 `fin_customer_memory_collection_v2`。
- Redis：DLQ 51 条保留，PEL 合计 0。
- 本轮未调用外部 LLM，未执行交易或审批。

## 4. 可重复命令

```powershell
python scripts/migrate_customer_memory_schema_v2.py --verify
python scripts/manage_historical_dlq.py
python scripts/assess_pending_dlq.py
python -m pytest -q -p no:cacheprovider
```
