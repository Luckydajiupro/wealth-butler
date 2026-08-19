# Agent协作流程实现报告

## 一、实现概述

本次任务完成了智能财富管家系统中多个Agent之间的协作流程，通过EventBus实现Agent间的事件驱动通信。

### 实施时间
2026-08-16

### 涉及模块
- EventBus（事件总线）
- RiskAgent（风控监测Agent）
- CustomerServiceAgent（智能客服Agent）
- OperatorAgent（业务操作Agent）
- 定时任务调度器

---

## 二、已完成的工作

### 2.1 风控Agent定时任务调度器

**文件**: `app/Base/Service/scheduler/riskMonitorScheduler.py`

实现了两个定时任务：

1. **每日风控扫描** (`scheduled_daily_risk_scan`)
   - 调度时间：每天凌晨2点（cron: `0 2 * * *`）
   - 规则范围：DAILY_RULE_IDS（10条日批规则）
   - 客户范围：fin_customer_profile全量客户（上限1000）
   - 任务ID：`risk_daily_scan`

2. **每周风控扫描** (`scheduled_weekly_risk_scan`)
   - 调度时间：每周一凌晨3点（cron: `0 3 * * 1`）
   - 规则范围：WEEKLY_RULE_IDS（2条周批规则）
   - 客户范围：fin_customer_profile全量客户（上限1000）
   - 任务ID：`risk_weekly_scan`

**特点**：
- 复用脚手架TaskSchedulerClient和auto_register机制
- 使用装饰器自动注册，无需手动配置
- 完整的日志记录，包括处理客户数、触发告警数、创建工单数、发布事件数

---

### 2.2 客服Agent可疑意图检测与事件发布

**文件**: `app/WealthButler/Agent/customerServiceAgent.py`

新增 `_detect_suspicious_intent` 方法：

**检测规则**：
1. **洗钱相关** (`money_laundering`, 置信度0.85)
   - 关键词：现金交易、大额现金、拆分转账、代理转账、帮忙转账、账户出租等

2. **诈骗相关** (`fraud`, 置信度0.80)
   - 关键词：保证收益、稳赚不赔、内幕消息、快速致富、高额回报等

3. **钓鱼相关** (`phishing`, 置信度0.75)
   - 关键词：验证码、密码、身份证号、银行卡号、账号密码等

**事件发布**：
- Stream Key: `stream:suspicious_intent`
- Event Type: `suspicious_intent`
- Source Agent: `customer_service_agent`
- Payload: 包含customer_id、session_id、intent_type、confidence、suspicious_text、evidence等

**集成点**：
- 在 `run` 方法中的意图分类后立即执行
- 检测结果记录到metadata中
- 异常处理完善，发布失败不影响主流程

---

### 2.3 EventBus消费者增强

**文件**: `app/WealthButler/EventBus/consumer.py`

#### 2.3.1 风险预警事件处理器 (`handle_risk_alert`)

**处理流程**：
1. 校验事件格式（使用pydantic schema）
2. 更新客户画像风险标记
   - 写入 `fin_customer_profile.risk_flags`（JSON字段）
   - 更新 `risk_level` 字段（低/中/高/极高风险）
3. 写入Redis短期记忆
   - Key: `customer:risk_alert:{customer_id}`
   - TTL: 7天
   - 供投顾/客服Agent快速查询

**Severity映射**：
```python
{
    'low': '低风险',
    'medium': '中风险',
    'high': '高风险',
    'critical': '极高风险'
}
```

**容错处理**：
- 画像更新失败不影响整体处理
- Redis写入失败不影响整体处理
- 完整的日志记录

#### 2.3.2 工单事件处理器 (`handle_work_order`)

**处理流程**：
1. 校验事件格式
2. 根据工单类型决定通知对象
   - 客户转介 → advisor（理财顾问）
   - 风控预警 → risk_specialist（风控专员）
   - 投诉/咨询 → customer_service（客服主管）
   - 其他 → operator（业务操作专员）
3. 写入Redis通知队列
   - Key: `notifications:{target}`
   - 使用LPUSH + LTRIM保持队列长度（最新100条）
   - TTL: 7天
4. 如果指定了处理人，发送定向通知
   - Key: `notifications:user:{handler_id}`
   - 保留最新50条

**通知数据结构**：
```json
{
    "type": "work_order",
    "order_id": 123,
    "order_type": "客户转介",
    "customer_id": 456,
    "description": "...",
    "priority": "中",
    "handler_id": 789,
    "created_at": "2026-08-16 12:00:00",
    "trace_id": "uuid"
}
```

---

### 2.4 业务操作Agent事件发布（已实现）

**文件**: `app/WealthButler/Service/operationService.py`

在 `_execute_transaction` 方法中已实现大额交易事件发布：

**触发条件**：
- 申购、赎回、转账交易成功后

**事件发布**：
- Stream Key: `stream:large_transaction`
- Event Type: `large_transaction`
- Source Agent: `operator_agent`
- Payload: 包含customer_id、transaction_id、product_id、amount、transaction_type

**重试机制**：
- 事件发布失败时，调用 `event_publisher.enqueue_retry`
- 交易已成功，返回 `TRANSACTION_SUCCEEDED_EVENT_PENDING`
- 保证事件不丢失

---

## 三、端到端业务流程验证

### 3.1 完整客户旅程（从文档提取）

```
1. 客户 → 客服Agent咨询产品（RAG知识库）
   ↓
2. 客户形成购买意向 → 客服Agent检测意图 → 写biz_work_order工单（客户转介）
   ↓ （可选：检测到可疑对话）
   ├→ 发布stream:suspicious_intent事件 → 风控Agent消费评估
   ↓
3. 理财顾问领取工单 → 投顾助手Agent产品推荐（GraphRAG）
   ↓
4. 客户确认后 → 业务操作Agent执行申购（NL2API）
   ↓
5. 申购金额>阈值 → 发布stream:large_transaction事件
   ↓
6. 风控监测Agent消费事件 → 评估规则 → 写预警表和工单表
   ↓
7. 风控专员处理工单 → 标记风险客户
   ↓
8. 风控Agent发布stream:risk_alert → 投顾/客服Agent消费更新标记
```

### 3.2 EventBus事件流汇总

| Stream Key | Event Type | 生产者 | 消费者 | 触发条件 |
|-----------|-----------|-------|-------|---------|
| `stream:large_transaction` | `large_transaction` | OperatorAgent | RiskAgent | 申购/赎回/转账成功 |
| `stream:suspicious_intent` | `suspicious_intent` | CustomerServiceAgent | RiskAgent | 检测到可疑对话 |
| `stream:risk_alert` | `risk_alert` | RiskAgent | AdvisorAgent, CustomerServiceAgent | 风控规则命中 |
| `stream:work_order` | `work_order` | CustomerServiceAgent | AdvisorAgent（待实现） | 转人工意图 |
| `stream:profile_updated` | `profile_updated` | 待实现 | 待实现 | 客户画像更新 |

---

## 四、技术架构与设计决策

### 4.1 EventBus设计

**选型**：Redis Streams（而非Pub/Sub）

**优势**：
- 持久化：消息保存在Stream中，不会丢失
- 消费组：支持多消费者负载均衡（虽然当前单实例）
- Pending List：自动跟踪未ACK消息
- 幂等性：结合Redis SET NX实现trace_id去重

**配置**：
- 最大长度：10000条（近似裁剪）
- Pending List重放：启动时自动重放未ACK消息
- 死信队列：处理失败自动写入`{stream_key}:dead_letter`

### 4.2 幂等性保证

**实时轨（事件驱动）**：
- Redis Key: `risk:idem:event:{trace_id}:{event_type}:{customer_id}:{entity_id}`
- TTL: 30天
- 机制：写库成功后claim，崩溃窗口内可能重复写入（已在组F报告登记）

**批量轨（定时扫描）**：
- Redis Key: `risk:idem:scan:{run_id}:{customer_id}:{rule_id}`
- TTL: 30天
- 机制：写库成功后claim，同批重跑跳过

**EventBus消费者幂等**：
- Redis Key: `eventbus:processed:{trace_id}`
- TTL: 24小时
- 机制：消费前检查，重复消息直接ACK

### 4.3 风控监测Agent双轨触发

**实时轨（8条准实时规则）**：
- 消费 `stream:large_transaction` 和 `stream:suspicious_intent`
- 回查源表判定（事件只作触发信号）
- 不维护计数器，完全基于数据库查询

**批量轨（12条日批/周批规则）**：
- 使用APScheduler定时触发
- 与交易事件无关
- 显式上限1000客户（不做全库无上限扫描）

**触发后的统一动作**：
1. 写入 `fin_risk_alert` 风险预警表（每规则一行）
2. 写入 `biz_work_order` 工单表（同批合并一个，就高原则）
3. 生产 `stream:risk_alert` 事件（每行预警一个）

---

## 五、代码质量与规范

### 5.1 遵循的规范

1. **复用原则**：
   - 复用Base脚手架的TaskSchedulerClient
   - 复用EventBus现有实现
   - 不重复实现Redis连接池

2. **文件落点**：
   - 定时任务放在 `Base/Service/scheduler/`（自动注册）
   - Agent修改在原文件内扩展
   - 不创建新的Service模块

3. **注释规范**：
   - 中文注释，说明WHAT和WHY
   - 模块顶部说明职责和依赖
   - 关键业务逻辑添加行内注释

4. **异常处理**：
   - 日志记录完整（logger.error with exc_info=True）
   - 非核心失败不阻断主流程（如Redis写入失败）
   - 返回明确的错误状态码

### 5.2 测试建议

**单元测试**（暂未实现）：
- RiskAgent的幂等性测试
- CustomerServiceAgent的可疑意图检测测试
- EventBus消费者的异常处理测试

**集成测试**（暂未实现）：
- 端到端事件流测试
- 定时任务触发测试
- Redis/MySQL故障降级测试

**验证步骤**（手动验证）：
1. 启动系统后检查消费者线程是否启动（日志输出）
2. 检查定时任务是否注册（访问 `/scheduler/status` 接口）
3. 模拟大额交易，观察风控Agent是否消费事件
4. 模拟可疑对话，观察客服Agent是否发布事件
5. 手动触发定时任务，观察批量扫描结果

---

## 六、未实现的功能（待后续迭代）

### 6.1 工单流转机制完善

**当前状态**：
- 工单创建已实现（客服Agent、风控Agent）
- 工单事件发布已实现
- 工单消费通知已实现

**待实现**：
- 理财顾问领取工单后的自动通知
- 工单状态变更事件发布
- 工单处理超时预警

### 6.2 画像更新事件

**当前状态**：
- `stream:profile_updated` 的Schema已定义
- 消费者handler已预留（`handle_profile_updated`）

**待实现**：
- 投顾助手Agent完成推荐后发布事件
- 风险等级变更后发布事件
- 推荐引擎消费事件重新计算

### 6.3 AdvisorAgent事件消费

**当前状态**：
- 消费者配置已添加（`advisor_group`）
- handler已预留

**待实现**：
- AdvisorAgent实际消费 `stream:risk_alert`
- 根据风险标记调整推荐策略
- 高风险客户推荐保守产品

### 6.4 监控与告警

**待实现**：
- EventBus Pending List监控（超过阈值告警）
- 定时任务执行失败告警
- 死信队列堆积告警
- Redis连接失败告警

---

## 七、部署与运维

### 7.1 启动检查清单

系统启动时会自动执行：
1. ✅ 启动EventBus消费者（5个消费者线程）
2. ✅ 注册定时任务（扫描 `Base/Service/scheduler/` 目录）
3. ✅ 创建Redis Streams消费组（幂等操作）

**日志验证**：
```
[Startup] 启动 EventBus 消费者...
[EventBus] Consumer risk-worker-1 started, group=risk_monitor_group, stream=stream:large_transaction
[EventBus] Consumer risk-worker-2 started, group=risk_monitor_group, stream=stream:suspicious_intent
[EventBus] Consumer advisor-worker-1 started, group=advisor_group, stream=stream:risk_alert
...
[Startup] 注册定时任务...
[SCAN] 开始扫描 Base/Service/scheduler 目录下的定时任务...
[OK] 扫描完成! 处理了 2 个文件，注册了 2 个任务
[Startup] 智能财富管家系统启动完成
```

### 7.2 Redis依赖

**必需的Redis配置**：
- 版本：>= 5.0（支持Streams）
- 内存：建议 >= 2GB
- 持久化：建议开启AOF（事件不丢失）

**关键Key列表**：
- `stream:large_transaction` - 大额交易事件流
- `stream:suspicious_intent` - 可疑意图事件流
- `stream:risk_alert` - 风险预警事件流
- `stream:work_order` - 工单事件流
- `eventbus:processed:{trace_id}` - 幂等记录（24h TTL）
- `risk:idem:event:*` - 风控幂等记录（30天TTL）
- `risk:idem:scan:*` - 批量扫描幂等记录（30天TTL）
- `customer:risk_alert:*` - 客户风险标记（7天TTL）
- `notifications:*` - 通知队列（7天TTL）

### 7.3 MySQL依赖

**必需的表**：
- `fin_risk_alert` - 风险预警表
- `biz_work_order` - 业务工单表
- `fin_customer_profile` - 客户画像表（需有risk_flags和risk_level字段）
- `fin_transaction` - 交易流水表
- `base_apscheduler_jobs` - 定时任务持久化表

### 7.4 故障排查

**EventBus消费者未启动**：
1. 检查Redis连接是否正常（`app.Base.Client.redisClient`）
2. 检查 `start_all_consumers()` 是否被调用
3. 检查线程是否启动（`threading.enumerate()`）

**定时任务未执行**：
1. 检查MySQL连接是否正常
2. 检查 `base_apscheduler_jobs` 表是否存在
3. 访问 `/scheduler/status` 查看任务状态
4. 检查cron表达式是否正确

**事件未消费**：
1. 检查消费组是否创建（`XINFO GROUPS stream:xxx`）
2. 检查Pending List堆积（`XPENDING stream:xxx group_name`）
3. 检查handler是否抛异常（查看日志）
4. 检查幂等Key是否存在（`GET eventbus:processed:{trace_id}`）

---

## 八、总结

### 8.1 完成度评估

| 功能模块 | 完成度 | 说明 |
|---------|-------|-----|
| EventBus基础设施 | 100% | 已完善（前期已实现） |
| 风控Agent实时轨 | 100% | 消费large_transaction和suspicious_intent |
| 风控Agent批量轨 | 100% | 日批/周批定时任务 |
| 客服Agent事件生产 | 100% | 可疑意图检测与发布 |
| 业务操作Agent事件生产 | 100% | 大额交易事件发布（前期已实现） |
| 风险预警事件消费 | 100% | 更新画像+Redis通知 |
| 工单事件消费 | 100% | Redis通知队列 |
| 画像更新事件 | 30% | Schema定义，待实际生产者 |
| AdvisorAgent集成 | 30% | 消费者预留，待实际处理逻辑 |

### 8.2 核心价值

1. **Agent解耦**：通过EventBus实现松耦合，各Agent独立演进
2. **可靠性**：幂等性+Pending List+死信队列三重保障
3. **可观测性**：完整的日志+trace_id链路追踪
4. **可扩展性**：新增事件类型只需定义Schema和handler

### 8.3 后续优化方向

1. **性能优化**：批量消费（count=10）+ 并发处理
2. **监控完善**：Prometheus指标暴露+Grafana可视化
3. **测试覆盖**：单元测试+集成测试+压力测试
4. **文档完善**：EventBus使用手册+故障排查手册

---

## 附录

### A. 相关文件清单

**新增文件**：
- `app/Base/Service/scheduler/riskMonitorScheduler.py` - 风控定时任务

**修改文件**：
- `app/WealthButler/Agent/customerServiceAgent.py` - 添加可疑意图检测
- `app/WealthButler/EventBus/consumer.py` - 完善事件处理逻辑

**依赖文件（已存在）**：
- `app/WealthButler/EventBus/eventBus.py` - EventBus核心类
- `app/WealthButler/EventBus/schemas.py` - 事件Schema定义
- `app/WealthButler/Agent/riskAgent.py` - 风控Agent核心逻辑
- `app/WealthButler/Service/operationService.py` - 业务操作服务
- `app/WealthButler/main.py` - 系统启动入口

### B. 配置参数汇总

**EventBus配置**：
- `block_ms`: 5000（消费者阻塞超时）
- `count`: 10（每次拉取消息数）
- `maxlen`: 10000（Stream最大长度）

**定时任务配置**：
- 日批cron: `0 2 * * *`（每天凌晨2点）
- 周批cron: `0 3 * * 1`（每周一凌晨3点）
- 批量客户上限: 1000

**幂等性配置**：
- 事件幂等TTL: 30天
- EventBus消费幂等TTL: 24小时
- 批量扫描幂等TTL: 30天

**通知配置**：
- 风险标记TTL: 7天
- 通知队列TTL: 7天
- 通知队列长度: 100条（角色队列）/ 50条（个人队列）

---

**报告生成时间**: 2026-08-16
**报告版本**: 1.0
**作者**: Claude Code (AI Agent)
