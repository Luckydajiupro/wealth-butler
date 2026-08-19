# Phase 4 真实种子数据导入报告

## 1. 执行结论

- 执行日期：2026-08-17
- 种子命名空间：`WB-SEED-20260817`
- 数据原则：贴合《智能财富管家系统-项目需求文档》§11 的客户测试场景；使用稳定自然键关联各存储；Milvus 仅追加且不覆盖已有数据；其他存储仅更新本命名空间稳定键，不清空整库。
- 安全原则：种子账号密码由强随机值生成并保存在本地 `.env` 的 `WEALTH_BUTLER_SEED_PASSWORD`，未写入代码、日志或本文档。

## 2. MySQL 结构前置迁移

执行脚本：`scripts/migrations/phase4_seed_prerequisite_migration.py`

迁移仅为 `fin_risk_alert`、`biz_work_order`、`fin_knowledge_meta` 增加权威表设计中缺失的 15 个字段和 4 个索引。迁移前后表行数分别保持为 19、190、207，未删除或改写已有记录；重复执行验证无待执行步骤。

## 3. MySQL 业务种子

执行脚本：`scripts/seed_wealthbutler_business_data.py`

| 数据 | 新增数量 | 导入后总量 |
|---|---:|---:|
| 用户 | 210（180 客户、30 员工） | 389 |
| 用户角色关系 | 30 | 42 |
| 产品 | 55 | 81 |
| 客户画像 | 180 | 332 |
| 风险评估 | 180 | 185 |
| 交易 | 182 | 1464 |
| 持仓 | 181 | 495 |
| 风险预警 | 19 | 38 |
| 工单 | 10 | 200 |
| 会话归档 | 1 | 34 |
| 知识元数据 | 3 | 210 |
| 操作审计 | 1 | 1 |
| 合规证据 | 3 | 3 |
| 验证收款方 | 20 | 20 |

客户风险分布为 C1/C2/C3/C4/C5 = 36/42/48/36/18。员工由 12 名理财顾问、6 名客户经理、5 名风控专员、3 名业务运营、2 名合规复核和 2 名管理员组成。每名种子客户均关联有效服务员工。

核心场景保留稳定账号：`wb_seed_c1_elderly`（陈秀兰）、`wb_seed_c3_balanced`、`wb_seed_c4_professional`（王建国）、`wb_seed_c5_aggressive`，以及 `wb_seed_advisor`、`wb_seed_operator`、`wb_seed_risk`、`wb_seed_admin` 等员工账号。

独立验证通过：画像、风评、客户员工关联、员工角色、交易关联、持仓金额算术、预警、工单、合规证据、验证收款方。客户、理财顾问、Operator、风控和管理员五类代表账号的真实登录、身份边界和权限矩阵均通过。

## 4. Redis 与 MinIO

执行脚本：`scripts/seed_cross_store_scenarios.py`

- Redis：3 个核心场景键、40 个 30 分钟 TTL 会话键、1 条隔离种子事件流；不向正式业务流写测试消息。
- MinIO：3 个带 `DEMO_SEED` 标记的合规证据 JSON 对象。
- MySQL 中三条合规证据的类型、客户、产品、MinIO URI 和 SHA-256 与对象内容严格一致。
- MinIO 配置已从控制台端口修正为 S3 API 端口；默认配置执行独立 `--verify` 通过。

## 5. Milvus 与 Neo4j

执行脚本：`scripts/seed_vector_graph_data.py`

| 存储 | 最终结果 |
|---|---:|
| FAQ 向量集合 | 100（本命名空间 22） |
| 产品向量集合 | 100（本命名空间 18） |
| 政策向量集合 | 148（已有数据已达标，未覆盖、未追加） |
| 客户记忆向量集合 | 100（本命名空间 100） |
| Neo4j 节点 | 380 |
| Neo4j 关系 | 1462 |

Neo4j 已覆盖 180 名客户、30 名员工、55 个产品及 181 条持仓的跨 MySQL 映射，包含客户服务、持有、产品行业、基金经理和风险等级关系。

## 6. 可重复验证与回滚

以下命令默认不打印密码或 Token：

```powershell
python scripts/seed_wealthbutler_business_data.py --verify
python scripts/seed_cross_store_scenarios.py --verify
python scripts/seed_vector_graph_data.py --verify
```

MySQL 种子提供命名空间限定回滚，但当前未执行：

```powershell
python scripts/seed_wealthbutler_business_data.py --rollback --confirm ROLLBACK_WB_SEED_20260817
```

回滚只处理能由稳定自然键证明属于 `WB-SEED-20260817` 的记录，不处理其他业务数据。

## 7. 已知后续项

1. `fin_customer_memory_collection` 的真实Milvus schema与Model数值字段声明存在漂移。现已完成旧schema兼容读取、side-by-side v2迁移脚本和真实dry-run；v2 apply/切换仍待单独批准，本报告未执行。
2. Redis正式DLQ已只读诊断为3条流/46条历史消息；EventBus消费者语义已修复。历史消息仍未重放、删除或处置，其业务处置策略待单独批准。
