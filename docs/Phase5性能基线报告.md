# Phase 5 性能基线报告

> 采样日期：2026-08-17  
> 数据命名空间：`WB-SEED-20260817`  
> 模式：主体基线为真实基础设施 + 只读查询 + 确定性 LLM 替身；另含用户批准的 DeepSeek SSE 在线验收

## 1. 结论

当前 RAG、NL2SQL 和 Agent 框架开销均达到需求指标。原始正式入口冷启动 3 次独立进程的 p50 为 13.58s，p95 为 17.64s。分段定位后，在不修改 `app/Base` 的前提下将 scheduler 客户端加载与业务路由注册并行，全新进程差分探针的中位数从 18.52s 降至 13.64s，改善 26.3%。

| 指标 | 样本 | p50 | p95 | 需求阈值 | 结果 |
|---|---:|---:|---:|---:|---|
| OpenAPI 响应 | 7 | 8.38ms | 9.65ms | - | 通过 |
| JWT 解析 + RBAC 拒绝边界 | 7 | 10.31ms | 10.63ms | - | 通过 |
| MySQL 真实只读持仓查询 | 7 | 3.73ms | 4.01ms | - | 通过 |
| NL2SQL 安全聚合查询 | 7 | 4.35ms | 4.98ms | <3s | 达标 |
| AnalystAgent 确定性框架链路 | 7 | 5.91ms | 8.08ms | <5s | 达标 |
| RAG 检索（本地 Ollama + Milvus） | 7 | 519.47ms | 526.29ms | <2s | 达标 |
| Graph 客户范围只读查询 | 7 | 5.27ms | 6.18ms | - | 通过 |
| 正式入口冷启动至 ready | 3 | 13.58s | 17.64s | - | 待优化 |
| 启动差分探针（顺序→并行） | 3×2 | 18.52s→13.64s | - | - | 改善26.3% |
| 优化后正式入口单次启动 | 1 | 17.94s | - | - | 通过 |
| 正式入口正常关闭 | 1 | 1.39s | - | <5s | 通过 |
| DeepSeek SSE 冷连接首帧 | 5 | 4.64s | 7.59s | <5s | p50达标，p95未达标 |
| DeepSeek SSE 冷连接完整回答 | 5 | 4.83s | 7.77s | <5s | p50达标，p95未达标 |
| DeepSeek SSE 热连接首帧 | 10 | 2.74s | 9.27s | <5s | p50达标，p95未达标 |
| DeepSeek SSE 热连接完整回答 | 10 | 3.00s | 9.44s | <5s | p50达标，p95未达标 |

另一次独立重复采样（5 次业务指标/2 次启动）中，RAG p95 为 1.13s，启动 p95 为 13.08s，仍与上述结论一致。RAG 延迟存在约 0.53-1.13s 的运行时波动，建议后续在固定负载和预热条件下纳入持续性能回归。

## 2. 采样口径

- 每个业务指标先预热 1 次，再记录 7 次，报告线性插值 p50/p95。
- OpenAPI 通过 FastAPI ASGI 路由真实响应 `/openapi.json`，并校验路径数不少于 60。
- JWT/RBAC 使用 seed 客户的项目 `AuthService` 真实认证链，校验客户不具有 `data:nl2sql_query`。密码仅从 `WEALTH_BUTLER_SEED_PASSWORD` 读取，不打印密码、哈希或 token。
- MySQL 仅执行 `SELECT`，读取核心客户持仓。
- RAG 调用真实 `KnowledgeService`，使用本地 Ollama embedding 和真实 Milvus 集合。
- Graph 使用固定、客户范围内的只读 Cypher 生成替身，但查询由真实 Neo4j 执行。
- NL2SQL 和 AnalystAgent 使用确定性 SQL/解读替身，SQL 仍通过真实 `Nl2sqlGuard` 并在真实 MySQL 执行。
- 启动指标每次创建全新 Python 进程，执行 `app/WealthButler/main.py` 的正式 `lifespan`，到 ready 后立即进入正常 shutdown。
- 启动差分探针以交替顺序启动全新子进程，只比较 route/scheduler 顺序与并行加载；不进入 lifespan，不启动 EventBus/scheduler，不调用外部 LLM。

## 3. 安全边界

本轮基线的外部 LLM 请求数为 **0**。脚本不实例化 DeepSeek 生成器，Graph、NL2SQL 和 Agent 均使用确定性本地替身。正式入口启动仅初始化运行时客户端，没有调用聊天/SSE 路由。基线没有执行交易、审批、事件发布或业务数据写入。

需要与本轮区分：Phase 4 早先的 SSE 权限检查曾因对风控权限矩阵误判，向已配置 DeepSeek 发出过 1 次无敏感测试文本请求。该请求未触发交易，也未写入会话归档。

用户明确批准后，2026-08-17 使用项目 `.env` 中原有 `deepseek-v4-flash` 配置完成正式 SSE 在线验收，未修改 `DEEPSEEK_DEFAULT_MODEL`。首次验收 HTTP 200，`Content-Type` 为 `text/event-stream; charset=utf-8`，仅返回 1 帧，完整耗时 16.73s，由此发现应用在 Agent 完成后才切块的伪流式问题。

修复后通过正式入口、真实 JWT 和 `/api/chat/customer` 复测两次：冷连接返回 31 帧，首帧 5.87s，完整 6.08s；随后热连接返回 28 帧，首帧 1.85s，完整 2.12s。首帧均早于完整结束，证明 DeepSeek 原生 token 流已经逐帧透传。冷连接仍超过 `<5s`，热连接达标；不能用确定性 Agent 框架的 8.08ms 指标替代该外部延迟。测试消息不含客户信息，报告和验收脚本均不输出模型正文、密码、JWT 或 API Key。

随后使用 5 个独立正式入口进程完成多样本验收，每个进程采集 1 个冷请求和 2 个热请求，共 5 cold / 10 hot。15 个请求全部为 HTTP 200、SSE content-type、至少 21 个 `data:` 帧且首帧早于完整结束，通道成功率 100%。冷请求首帧 p50/p95 为 4.64s/7.59s，完整回答为 4.83s/7.77s；热请求首帧为 2.74s/9.27s，完整回答为 3.00s/9.44s。热请求出现一次首帧 12.56s 的长尾，因此只能确认 p50 达标，不能据单次 1.85s 样本宣称 p95 达标。原始脱敏产物为 `docs/evidence/deepseek-sse-20260817-multisample.json`。

在线验收使用唯一 `deepseek-sse-*` 会话 ID，真实客服链路会按设计写入 15 条测试会话归档；固定消息不含客户信息，未触发交易、审批或可疑意图事件。产物不保存模型正文、JWT、密码、API Key 或异常正文。

## 4. 问题与优化建议

1. **P1：冷启动仍受 Base 导入链限制。** 分段探针显示 `app` 包级 Base/OpenAI/默认 DeepSeek 客户端导入约 7-11s，`authService` 依赖链约 6.06s，其中包含 MinIO、Redis、Jieba 和两个 MySQL 连接池初始化。本轮已将可安全重叠的 scheduler/路由加载并行，不跨越 `app/Base` 脚手架边界；如需继续降低冷启动，需要单独审核 Base 包级副作用和延迟客户端初始化方案。
2. **P2：RAG 波动。** 增加 Ollama embedding 预热、连接池指标与 Milvus 查询分段计时；持续回归建议至少 30 次样本。
3. **P2：Windows GBK 日志噪音。** Base Milvus logger 输出 `✅` 时会产生 `UnicodeEncodeError` 日志栈，不影响查询或进程成功退出。因本阶段禁止修改 `app/Base`，暂记录为环境问题；可在 CI/启动命令统一 UTF-8 终端编码。
4. **P3：TestClient 弃用警告。** OpenAPI 基线出现 Starlette `TestClient`/`httpx` 弃用警告，后续可迁移到 `httpx.ASGITransport`。
5. **P1：DeepSeek SSE p95 长尾未达标。** 伪流式已修复，明确寒暄也已跳过意图分类 LLM；多样本中 cold/hot 首帧 p95 分别为 7.59s/9.27s，完整回答 p95 为 7.77s/9.44s。热连接仍出现 12.56s 首帧长尾，说明连接复用不能消除上游排队或首 token 波动。建议 cold/hot 分开设 SLO，并至少扩大到各 30 次样本；可选预热会产生外部调用和费用，不应默认在每次启动时执行。

## 5. 可重复命令

```powershell
# 离线契约测试（不连真实基础设施）
python -m pytest -q tests/test_performance_baseline.py

# 标准只读基线（7 次业务采样 + 3 次独立冷启动）
python scripts/performance_baseline.py --run --iterations 7 --startup-samples 3

# 快速回归（5 次业务采样 + 2 次冷启动）
python scripts/performance_baseline.py --run --iterations 5 --startup-samples 2

# 已启动正式入口后的 DeepSeek SSE 验收（会产生一次外部调用）
python scripts/verify_deepseek_sse.py

# DeepSeek SSE 多样本验收（5 次进程冷启，5 cold + 10 hot）
python scripts/verify_deepseek_sse.py --cycles 5 --hot-per-cycle 2 --output docs/evidence/deepseek-sse-20260817-multisample.json

# 冷启动顺序/并行差分探针（不进入 lifespan）
python tests/startup_cold_probe.py --runs 3

# Windows 正式入口启停验收
python scripts/verify_graceful_shutdown.py --shutdown-timeout 5 --signal break
```

命令要求项目 `.env` 中的 MySQL、Milvus、Ollama、Neo4j、Redis 和 MinIO 可连通，且存在 `WEALTH_BUTLER_SEED_PASSWORD`。输出 JSON 只包含耗时、通过状态和非敏感命名空间。
