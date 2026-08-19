# Phase 5 最终验收与答辩收口报告

验收日期：2026-08-17。

## 1. 当前结论

Phase 1-4 核心实现完成；Phase 5 的固定题集、目标 REST 契约、DeepSeek 多样本 SSE、
GraphRAG 对照和确定性答辩 Demo 已完成。前端代码契约已收口，但本轮浏览器人工点击
验收因本地后台启动的 Codex 安全审批通道连续返回 503，尚无浏览器证据，不能标记通过。

## 2. 验收结果

| 验收项 | 结果 | 证据 |
|---|---|---|
| Phase 5 确定性真实数据 Demo | PASS（8/8） | `scripts/run_phase5_demo.py` |
| 固定题集总门禁 | PASS | `runtime_artifacts/evaluation/accuracy-live-after-fix.json` |
| 目标 REST API | PASS | 78 paths / 83 operations；`tests/test_phase5_rest_contracts.py` |
| DeepSeek SSE 多样本 | 部分达标 | 15/15成功；P50达标，P95未达标 |
| GraphRAG行业分散对照 | PASS | 受控和2名真实客户NDCG均提升 |
| 前端主流程代码契约 | PASS | 无Mock假成功；客户选择、SSE、Operator确认/取消已接入 |
| 前端浏览器人工流程 | BLOCKED | 普通前台启动可进入 lifespan，但访问 `192.168.110.106` 的 MySQL/Redis 被沙箱以 `WinError 10013` 拒绝；提升权限启动又被审批通道503拒绝 |

全量自动化最终结果为 `223 passed, 1 Starlette/httpx2 deprecation warning`；Phase 5
确定性真实数据 Demo 为 `8/8 PASS`。登录页的6个快速账号已通过 MySQL 只读查询确认存在，
客户/员工大类与页面角色一致；本轮未执行登录，避免仅为检查账号而更新 `last_login_at`。

## 3. 固定题集

- 客服意图：18/18，100%。
- 真实RAG证据：8/9，88.89%。
- NL2SQL：8/10，80%，刚好达到下限。
- Operator意图：16/16，100%。
- Operator参数：23/23，100%；修复前为6/23。

评测只生成分类、SQL和业务参数候选；SQL不执行，Operator不进入APIExecutor，不产生
申购、赎回、转账或工单写入。

## 4. REST契约

已补齐 `/api/knowledge/*`、`/api/profile/*`、`/api/product/*`、
`POST /api/risk/monitor`、`/api/graph/*` 和
`POST /api/admin/recalculate-confidence`，共14个目标操作。知识上传真实写入未在共享数据
上执行，避免向 MySQL、MinIO、Milvus 注入验收文档；其余契约有离线测试，Neo4j子图
以 customer_id=1640 只读验证为82 nodes / 88 edges。

## 5. DeepSeek性能

5个全新正式入口进程，每进程1次cold和2次hot，共15次请求，全部HTTP 200且为真实
多帧SSE。cold首帧P50/P95为4.645s/7.591s，hot为2.735s/9.271s。因此只能宣称
P50达到5秒目标，不能宣称P95达标。

## 6. GraphRAG

修复了 Milvus 产品编码元数据映射和产品级图谱分数。固定行业分散查询中，受控样本
NDCG@3从0.9197提升至1.0000；陈秀兰真实种子NDCG@5从0.8700提升至1.0000；
王建国从0.4900提升至1.0000。增益结论只适用于行业分散意图。

## 7. 答辩演示顺序

1. 客户登录、身份隔离与风险评估。
2. 客服真实RAG和DeepSeek SSE，展示来源证据。
3. 顾问选择客户，展示适当性过滤及GraphRAG行业分散推荐。
4. Operator发起大额申购，展示确认与取消两条状态流转。
5. 风控查看预警、处理状态并追溯工单。
6. Analyst执行安全查询，并演示危险SQL拒绝。
7. 关闭外部模型或构造空流，展示明确失败提示而非Mock成功。

## 8. 剩余风险

- DeepSeek P95长尾未达标，建议cold/hot各扩至至少30次并分段观测上游排队。
- NL2SQL本轮正好80%，建议至少重复3轮并报告均值和最差轮。
- 知识上传涉及共享存储写入，最终演示前应在专用测试文档和可回收命名空间中验收一次。
- 浏览器人工流程仍待网络访问权限和审批通道恢复后补证据；当前已确认不是前端路由代码异常。
- Base导入链导致正式入口冷启动约13-18秒；继续优化需单独批准修改脚手架。
